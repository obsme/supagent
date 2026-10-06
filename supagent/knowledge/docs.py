"""Documents and sites for the agent: uploaded text, Markdown or HTML files, and pages read again every
refresh_days days by one of the readers:

  web         a page, or a site: up to max_pages pages under the same address
  confluence  a Confluence page and the pages under it, or a whole space (Data Center or Cloud), through its
              REST API
  bitbucket   the text files of a Bitbucket repository or folder (Data Center or Cloud), through its REST API,
              the documentation first (README, docs/, Markdown); with files "code" (0.9.6.1), the source code
              too (every common language, build and deployment files), never the files that hold keys
              (.env, *.pem, *.key...) nor the vendored and built ones (node_modules, dist, *.min.js, lock files),
              the secrets written in the code (passwords, tokens, keys, a URL's password) masked

doc.reader chooses one; empty: the address says which (detect_reader).

A site may need a sign-in: doc.auth says how ({"type": "bearer" | "basic" | "header", "user": ..., "header": ...})
and doc.secret holds the token or the password (encrypted with Superset's SECRET_KEY). The sign-in goes to the
document's own site only (the scheme, host and port of its address; the API host of Bitbucket Cloud too): a
redirect to another site is followed without it, and the secret never appears in an error, a log or what the page
is sent (describe_auth).

Reading is safe by default: http(s) only, at most docs.max_kb per page or file, 20 s per request, and every
address (redirects and API calls included) must be in docs.allowed_domains; with no allowed domain, only public
addresses are read (no intranet, no localhost). Text only: PDF would need a package Superset does not have.
The sites' certificates are checked (docs.verify_tls), with docs.ca_bundle (a company's CA file) when given; a
document can have its own choice (doc.auth "verify_tls", "ca_bundle"): a site whose certificate is not trusted
says so and how to fix it (0.9.6.1).

A Bitbucket repository is read again only as far as it changed (0.9.6.1): its branch's last commit is kept with
each file; the same commit, nothing is read; another one, only the files changed between the two are read again
(the others kept as they were), and the search makes again only their pieces (a piece is named after its page).

Each page keeps where its text starts in doc.content (doc.pages: url, title, chars, at): the search makes its
pieces page by page, each with the page's address (index._doc_pieces).
"""

from __future__ import annotations

import base64
import contextvars
import datetime as dt
import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, unquote_plus, urljoin, urlparse

import requests
from superset import db

from supagent import settings
from supagent.models import Doc

log = logging.getLogger(__name__)
BLOCK_TAGS = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre",
              "table", "ul", "ol", "dd", "dt", "blockquote"}
HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
READERS = ("web", "confluence", "bitbucket")
AUTH_TYPES = ("bearer", "basic", "header")
USER_AGENT = "supagent (Superset AI agent) document reader"
TIMEOUT = 20                    # seconds per request
API_BYTES = 16 * 1024 * 1024    # an API answer (a listing, a page with its body) at most
CONFLUENCE_LIST = 25            # pages with their bodies per request (a space)
CHILDREN_LIST = 50              # children per request (a page's)
REPO_LIST = 1000                # files per request (Bitbucket Data Center)
MAX_LISTED = 5000               # files of a repository listed at most (the documentation is chosen among them)
# the API of a cloud service by the host of its pages (Bitbucket Cloud: pages on bitbucket.org, API on
# api.bitbucket.org): the sign-in goes to both
CLOUD_APIS = {"bitbucket.org": "https://api.bitbucket.org/2.0", "www.bitbucket.org": "https://api.bitbucket.org/2.0"}
TEXT_FILES = (".md", ".markdown", ".txt", ".text", ".rst", ".adoc", ".asciidoc", ".html", ".htm", ".yaml", ".yml",
              ".json", ".csv", ".ini", ".cfg", ".conf", ".properties", ".xml", ".sql")
DOC_TYPES = (".md", ".markdown", ".rst", ".adoc", ".asciidoc", ".txt", ".text", ".html", ".htm")
DOC_FOLDERS = {"doc", "docs", "documentation", "wiki", "manual", "guide", "guides", "runbook", "runbooks", "howto"}
FILES = ("docs", "code")        # what a repository gives: its documentation and text files, or all its code too
CODE_FILES = (".py", ".pyi", ".java", ".kt", ".kts", ".scala", ".groovy", ".gradle", ".js", ".jsx", ".mjs", ".cjs",
              ".ts", ".tsx", ".vue", ".svelte", ".go", ".rs", ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".hh", ".cs",
              ".fs", ".vb", ".rb", ".php", ".pl", ".pm", ".r", ".jl", ".swift", ".m", ".mm", ".lua", ".dart", ".ex",
              ".exs", ".erl", ".clj", ".hs", ".ml", ".sh", ".bash", ".zsh", ".ksh", ".ps1", ".psm1", ".bat", ".cmd",
              ".tf", ".tfvars", ".hcl", ".proto", ".graphql", ".gql", ".css", ".scss", ".less", ".toml", ".j2",
              ".jinja", ".tpl", ".tmpl", ".dockerfile", ".cfg", ".ini", ".conf", ".properties", ".xml", ".sql",
              ".yaml", ".yml", ".json")
CODE_NAMES = {"dockerfile", "containerfile", "makefile", "jenkinsfile", "vagrantfile", "procfile", "gemfile",
              "rakefile", "build", "workspace", "cmakelists.txt"}
SKIP_DIRS = {"node_modules", "vendor", "dist", "build", "target", "out", "bin", "obj", ".git", "__pycache__",
             ".venv", "venv", "site-packages", "bower_components", ".idea", ".vscode", "coverage", ".gradle", ".mvn",
             ".terraform", ".next", ".nuxt"}
SKIP_FILE = re.compile(r"(\.min\.(js|css)|\.map|\.lock|(^|/)(package-lock\.json|npm-shrinkwrap\.json|"
                       r"pnpm-lock\.yaml|go\.sum))$", re.I)
# files that hold keys or passwords by their nature: never read
KEY_FILE = re.compile(r"(^|/)(\.env(\.[\w.-]+)?|[^/]*\.(pem|key|p12|pfx|jks|keystore|crt|cer|der|kdbx|ovpn)|"
                      r"id_(rsa|dsa|ecdsa|ed25519)(\.pub)?|\.npmrc|\.pypirc|\.netrc|\.git-credentials|"
                      r"credentials(\.[\w-]+)?|secrets?\.(ya?ml|json|properties|txt))$", re.I)
# secrets written in a file: the value masked, the rest of the line kept
SECRETS = [
    (re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.S),
     "[a private key, masked]"),
    (re.compile(r"(?i)(\b[\w.-]*(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|"
                r"private[_-]?key|client[_-]?secret|credentials?)[\w.-]*[\"']?\s*(?:=>|:=|[:=])\s*)"
                r"(\"[^\"\n$]{4,}\"|'[^'\n$]{4,}'|[A-Za-z0-9+/=_\-]{8,}(?![\w(.\[]))"), r"\1***"),
    (re.compile(r"\b([a-z][a-z0-9+.-]*://[^\s:/@]+):([^\s@/]+)@"), r"\1:***@"),
    # a DSN without a scheme (Go's MySQL driver, ODBC): user:password@tcp(host:port)/db, user:password@host:port/db
    (re.compile(r"(?<![\w/:.-])([A-Za-z_][\w.-]{0,63}):([^\s@/:\"'`(){}]{3,})@(?=tcp\(|unix\(|\(|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*"
                r"(?::\d+)?[/?])"), r"\1:***@"),
    # a key held by a name that says so (RATES_KEY, apiKey, signingKey...) and given a literal value
    (re.compile(r"(?i)(\b[\w.-]*(?:_key|key)\b[\"']?\s*(?:=>|:=|[:=])\s*)(\"[^\"\n$]{8,}\"|'[^'\n$]{8,}'|"
                r"`[^`\n$]{8,}`)"), r"\1***"),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 ***"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}|"
                r"xox[baprs]-[A-Za-z0-9-]{10,})\b"), "***"),
]
MAX_CHANGES = 3000              # files changed between two reads of a repository at most (more: read in full)
_VERIFY: contextvars.ContextVar[Any] = contextvars.ContextVar("supagent_doc_verify", default=True)
HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
# where a site sends a reader that is not signed in (a redirect there: "the site asked to sign in")
LOGIN = re.compile(r"(^|/)(login|log-in|logon|signin|sign-in|sso|saml2?|oauth2?|openid-connect|cas|adfs|idp)"
                   r"(/|\.|$)|j_security_check|dologin", re.I)


class DocError(Exception):
    pass


class _OutOfCalls(Exception):
    """A reader made as many API requests as it may: it keeps what it read."""


# --------------------------------------------------------------------------------------------- #
# text of a page
# --------------------------------------------------------------------------------------------- #
class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "svg", "nav", "footer"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in BLOCK_TAGS:
            self.parts.append("\n")
            if tag in HEADINGS and not self._skip:    # a heading stays one (0.9.6): the pieces are cut at sections
                self.parts.append("#" * int(tag[1]) + " ")
        elif tag in ("td", "th"):
            self.parts.append(" | ")                  # the cells of a row stay apart

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg", "nav", "footer") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        if tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


class _Storage(_Text):
    """Confluence's storage format: XHTML with its macros (ac:, ri:). A code macro's text (CDATA) is kept, the
    macros' parameters (language, colour, ...) are not."""

    BLOCKS = {"ac:structured-macro", "ac:plain-text-body", "ac:rich-text-body", "ac:task", "ac:layout-section",
              "ac:layout-cell"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "ac:parameter":
            self._skip += 1
            return
        if tag in self.BLOCKS:
            self.parts.append("\n")
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "ac:parameter":
            self._skip = max(0, self._skip - 1)
            return
        if tag in self.BLOCKS:
            self.parts.append("\n")
        super().handle_endtag(tag)

    def unknown_decl(self, data: str) -> None:
        if data[:6].upper() == "CDATA[" and not self._skip:
            self.parts.append(data[6:])

    def handle_comment(self, data: str) -> None:      # a Python that reads CDATA as a comment outside SVG
        if data[:7].upper() == "[CDATA[" and not self._skip:
            self.parts.append(data[7:].rstrip("]"))


def _lines(parts: list[str]) -> str:
    lines = [" ".join(line.split()) for line in "".join(parts).split("\n")]
    lines = [line[2:] if line.startswith("| ") else line for line in lines]
    return "\n".join(line for line in lines if line and line != "|")


def html_to_text(html: str) -> tuple[str, str, list[str]]:
    """(title, text, links) of an HTML page."""
    p = _Text()
    p.feed(html or "")
    return p.title.strip(), _lines(p.parts), p.links


def storage_to_text(xhtml: str) -> str:
    """The text of a Confluence page's body in the storage format (code macros and table cells kept)."""
    p = _Storage()
    p.feed(xhtml or "")
    p.close()
    return _lines(p.parts)


def _decode(body: bytes, ctype: str) -> str:
    m = re.search(r"charset=[\"']?([\w.:-]+)", ctype or "", re.I)
    if m:
        try:
            return body.decode(m.group(1), errors="replace")
        except LookupError:
            pass
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return body.decode("cp1252", errors="replace")


# --------------------------------------------------------------------------------------------- #
# where a document may be read from
# --------------------------------------------------------------------------------------------- #
def check_url(url: str) -> None:
    """http(s), and an allowed domain (or, with no allowed domain, a public address)."""
    u = urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise DocError(f"{url}: only http and https addresses")
    allowed = [d.strip().lower() for d in settings.get("docs.allowed_domains") or [] if d.strip()]
    host = u.hostname.lower()
    if allowed:
        if not any(host == d or host.endswith("." + d) for d in allowed):
            raise DocError(f"{host} is not in docs.allowed_domains: only the domains of that setting are read "
                           "(an admin adds the domain in Settings, Knowledge search and memory)")
        return
    try:
        infos = socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80))
    except socket.gaierror as ex:
        raise DocError(f"{host}: unknown host") from ex
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise DocError(f"{host} is a private (intranet) address: it is read only once its domain is in the "
                           "setting docs.allowed_domains (an admin adds it in Settings, Knowledge search and memory)")


def origin(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) of an address: the sign-in of a document goes to its own origin only."""
    try:
        u = urlparse(url or "")
        if u.scheme not in ("http", "https") or not u.hostname:
            return None
        return u.scheme, u.hostname.lower(), u.port or (443 if u.scheme == "https" else 80)
    except ValueError:                                # a port that is not a number
        return None


def _where(url: str) -> str:
    """An address as said in an error: without its query (nothing a server put there is repeated)."""
    u = urlparse(url or "")
    return f"{u.scheme}://{u.netloc}{u.path}" if u.scheme else str(url or "")[:200]


# --------------------------------------------------------------------------------------------- #
# the sign-in
# --------------------------------------------------------------------------------------------- #
@dataclass
class SignIn:
    """The sign-in headers of a document and the origins they may be sent to."""

    headers: dict[str, str]
    origins: frozenset

    def for_url(self, url: str) -> dict[str, str]:
        return dict(self.headers) if origin(url) in self.origins else {}


def _auth(doc: Doc) -> dict[str, Any]:
    return doc.auth if isinstance(doc.auth, dict) else {}


OPTIONS = ("verify_tls", "ca_bundle", "files")   # kept in doc.auth with the sign-in (no secret among them)


def tls_of(doc: Doc) -> Any:
    """How a document's site is checked: True (its certificate, with the system's CAs), a CA file (the document's,
    else docs.ca_bundle), or False (not checked: the document's choice, or docs.verify_tls off)."""
    own = _auth(doc).get("verify_tls")
    check = settings.get("docs.verify_tls") if own is None else bool(own)
    if not check:
        return False
    ca = str(_auth(doc).get("ca_bundle") or settings.get("docs.ca_bundle") or "").strip()
    if ca and not os.path.exists(ca):
        raise DocError(f"the CA file {ca} is not on this server: give the path of a PEM file present on every "
                       "Superset host (or the system's CAs: leave it empty)")
    return ca or True


def files_of(doc: Doc) -> str:
    """What a repository gives: "docs" (its documentation and text files) or "code" (all its code too)."""
    f = str(_auth(doc).get("files") or "").strip().lower()
    return f if f in FILES else "docs"


def mask_secrets(text: str) -> tuple[str, int]:
    """A file's text with the secrets written in it masked (passwords, tokens, keys, a URL's password), and how many."""
    n = 0
    for rx, by in SECRETS:
        text, k = rx.subn(by, text)
        n += k
    return text, n


def _hidden(doc: Doc) -> list[str]:
    """The secret of a document as it could appear in a text: itself, URL-quoted, and the base64 forms."""
    secret = doc.secret or ""
    if not secret:
        return []
    user = str(_auth(doc).get("user") or "")
    forms = {secret, quote(secret, safe=""), base64.b64encode(secret.encode()).decode(),
             base64.b64encode(f"{user}:{secret}".encode()).decode()}
    return sorted((f for f in forms if f), key=len, reverse=True)


def scrub(text: Any, doc: Doc) -> str:
    """A text with the document's secret (in any of its forms) replaced by ***."""
    out = str(text or "")
    for form in _hidden(doc):
        out = out.replace(form, "***")
    return out


def _api_bases(doc: Doc) -> list[str]:
    """The other origins a reader of this document calls (the API host of Bitbucket Cloud)."""
    if reader_of(doc) != "bitbucket":
        return []
    api = CLOUD_APIS.get((urlparse(doc.url or "").netloc or "").lower())
    return [api] if api else []


def sign_in(doc: Doc) -> SignIn | None:
    """The sign-in of a document (None: it has none)."""
    auth = _auth(doc)
    kind = str(auth.get("type") or "").strip().lower()
    if kind in ("", "none"):
        return None
    if kind not in AUTH_TYPES:
        raise DocError(f"unknown sign-in type {kind!r}: bearer, basic or header")
    secret = doc.secret or ""
    if not secret:
        raise DocError("the sign-in has no token or password saved: write it again")
    if kind == "bearer":
        headers = {"Authorization": f"Bearer {secret}"}
    elif kind == "basic":
        pair = f"{auth.get('user') or ''}:{secret}".encode()
        headers = {"Authorization": "Basic " + base64.b64encode(pair).decode()}
    else:
        name = str(auth.get("header") or "").strip()
        if not HEADER_NAME.match(name):
            raise DocError("the sign-in's header name is not valid (e.g. X-Api-Key)")
        headers = {name: secret}
    origins = {o for o in [origin(doc.url or "")] + [origin(x) for x in _api_bases(doc)] if o}
    origins |= {("https", host, 443) for scheme, host, port in list(origins) if scheme == "http" and port == 80}
    return SignIn(headers, frozenset(origins))          # (an http site moving to https: the same site, safer)


def describe_auth(doc: Doc) -> dict[str, Any]:
    """The sign-in of a document as the page shows it: never the secret, only whether one is saved."""
    auth = _auth(doc)
    kind = str(auth.get("type") or "").strip().lower() or None
    if kind == "none":
        kind = None
    return {"type": kind, "user": (auth.get("user") or None) if kind == "basic" else None,
            "header": (auth.get("header") or None) if kind == "header" else None, "secret_set": bool(doc.secret),
            "verify_tls": auth.get("verify_tls") if isinstance(auth.get("verify_tls"), bool) else None,
            "ca_bundle": auth.get("ca_bundle") or "", "files": files_of(doc)}


def configure(doc: Doc, body: dict[str, Any], previous_url: str | None = None) -> None:
    """The reader and the sign-in of a document from what the page sent: {"reader": "" | web | confluence |
    bitbucket, "auth": {"type": "" | none | bearer | basic | header, "user", "header"}, "secret": "..."}. An empty
    secret keeps the one saved; a sign-in of type none (or empty) removes it with its secret. A secret is never sent
    to another site: when the address moves to another origin (`previous_url`), the token must be written again."""
    reader = str(body.get("reader") or "").strip().lower()
    if reader and reader not in READERS:
        raise DocError("reader: web, confluence or bitbucket (empty: from the address)")
    if "reader" in body:
        doc.reader = reader or None
    opts = {k: v for k, v in _auth(doc).items() if k in OPTIONS}      # kept unless the page sends them
    signin: dict[str, Any] | None = {k: v for k, v in _auth(doc).items() if k not in OPTIONS} or None
    if "verify_tls" in body:                         # true, false, or null: as docs.verify_tls says
        v = body.get("verify_tls")
        if v is None or v == "":
            opts.pop("verify_tls", None)
        else:
            opts["verify_tls"] = v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true", "yes", "on")
    if "ca_bundle" in body:
        ca = str(body.get("ca_bundle") or "").strip()
        if ca and not os.path.exists(ca):
            raise DocError(f"the CA file {ca} is not on this server (the path of a PEM file on the Superset hosts)")
        if ca:
            opts["ca_bundle"] = ca[:500]
        else:
            opts.pop("ca_bundle", None)
    if "files" in body:
        f = str(body.get("files") or "").strip().lower()
        if f and f not in FILES:
            raise DocError("files: docs (the documentation and text files) or code (all the code too)")
        if f == "code":
            opts["files"] = f
        else:
            opts.pop("files", None)
    new_secret = str(body.get("secret") or "").strip()
    auth_in = body.get("auth")
    if isinstance(auth_in, dict):
        kind = str(auth_in.get("type") or "").strip().lower()
        if kind in ("", "none"):
            signin, doc.secret = None, None
            new_secret = ""
        elif kind not in AUTH_TYPES:
            raise DocError("sign-in: none, bearer (a token), basic (a user and a password or token) or header "
                           "(a header's name and its value)")
        else:
            auth: dict[str, Any] = {"type": kind}
            if kind == "basic":
                user = " ".join(str(auth_in.get("user") or "").split())[:255]
                if not user:
                    raise DocError("basic sign-in: write the user (for a cloud service, often the e-mail address)")
                auth["user"] = user
            if kind == "header":
                header = str(auth_in.get("header") or "").strip()
                if not HEADER_NAME.match(header):
                    raise DocError("header sign-in: write the header's name (e.g. X-Api-Key)")
                auth["header"] = header
            signin = auth
    elif auth_in is not None:
        raise DocError("auth: an object {type, user, header}")
    doc.auth = {**(signin or {}), **opts} or None
    moved = previous_url is not None and origin(previous_url) != origin(doc.url or "")
    if new_secret:
        doc.secret = new_secret
    elif moved and doc.secret:
        doc.secret = None                             # a secret saved for one site never goes to another
        if signin:
            raise DocError("the address is on another site now: write the token (or password) of its sign-in again")
    if signin and not doc.secret:
        raise DocError("write the token (or password) of the sign-in")
    if doc.secret and not signin:
        raise DocError("choose how the token is sent: bearer, basic (with a user) or header (with its name)")


def reader_of(doc: Doc) -> str:
    chosen = str(doc.reader or "").strip().lower()
    return chosen if chosen in READERS else detect_reader(doc.url or "")


def detect_reader(url: str) -> str:
    """The reader an address needs: confluence, bitbucket, or web."""
    if confluence_target(url) is not None:
        return "confluence"
    if bitbucket_target(url) is not None:
        return "bitbucket"
    return "web"


# --------------------------------------------------------------------------------------------- #
# requests
# --------------------------------------------------------------------------------------------- #
def _limit() -> int:
    return int(settings.get("docs.max_kb")) * 1024


def _max_pages(doc: Doc) -> int:
    return max(1, int(doc.max_pages or 1))


def _asked_to_sign_in(url: str, sign: SignIn | None, how: str) -> str:
    where = _where(url)
    if sign is not None and sign.for_url(url):
        return f"{where}: {how}: the site asked to sign in: check the token / user of this document's sign-in"
    if sign is not None:
        return (f"{where}: {how}: the site asked to sign in (another site than the document's: its sign-in is only "
                "sent to the document's own site; if the site moved, give the document its new address)")
    return f"{where}: {how}: the site asked to sign in: give this document a sign-in (a token or a user and password)"


@dataclass
class _Answer:
    url: str
    ctype: str
    body: bytes

    def text(self) -> str:
        return _decode(self.body, self.ctype)


def _get(url: str, sign: SignIn | None, limit: int, accept: str | None = None) -> _Answer:
    """One address, following redirects by hand: each one is checked (check_url) and gets the sign-in only if it is
    on the document's own site; a redirect to a login page, 401 or 403: "the site asked to sign in"."""
    for _hop in range(6):
        check_url(url)
        headers = {"User-Agent": USER_AGENT}
        if accept:
            headers["Accept"] = accept
        if sign is not None:
            headers.update(sign.for_url(url))
        verify = _VERIFY.get()                        # (False: urllib3 warns once per process, as Python does)
        try:
            r = requests.get(url, timeout=TIMEOUT, allow_redirects=False, stream=True, headers=headers, verify=verify)
        except requests.exceptions.SSLError as ex:
            raise DocError(_not_trusted(url, ex, verify)) from ex
        with r:
            if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("Location"):
                nxt = urljoin(url, r.headers["Location"])
                if LOGIN.search(urlparse(nxt).path or ""):
                    raise DocError(_asked_to_sign_in(url, sign, f"HTTP {r.status_code} to a login page"))
                url = nxt
                continue
            if r.status_code in (401, 403):
                raise DocError(_asked_to_sign_in(url, sign, f"HTTP {r.status_code}"))
            if r.status_code == 404:
                who = ("this document's sign-in" if sign is not None and sign.for_url(url)
                       else "a reader without sign-in")
                raise DocError(f"{_where(url)}: HTTP 404: not found, or not visible to {who}")
            if r.status_code >= 400:
                raise DocError(f"{_where(url)}: HTTP {r.status_code}")
            body = b""
            for chunk in r.iter_content(65536):
                body += chunk
                if len(body) > limit:
                    raise DocError(f"{_where(url)}: larger than {limit // 1024} KB")
            return _Answer(url, r.headers.get("Content-Type", ""), body)
    raise DocError(f"{_where(url)}: too many redirects")


def _not_trusted(url: str, ex: Exception, verify: Any) -> str:
    """A site whose certificate this server does not trust: why, and the two ways to read it."""
    said = str(ex)
    why = re.search(r"certificate verify failed: ([^(\]'\"]+)", said) or re.search(r"(hostname [^(\]'\"]+)", said)
    reason = (why.group(1).strip().rstrip(" .,") if why else type(ex).__name__)[:160]
    ca = f" (checked with the CA file {verify})" if isinstance(verify, str) else ""
    return (f"{urlparse(url).hostname}: the site's certificate is not trusted by this server{ca}: {reason}. For a site "
            "of the company: give its CA file (this document's CA file, or docs.ca_bundle for every document), or "
            "switch off the certificate check of this document (Edit: certificate not checked)")


def _json(url: str, sign: SignIn | None, what: str) -> dict[str, Any]:
    got = _get(url, sign, max(_limit(), API_BYTES), accept="application/json")
    try:
        data = json.loads(got.body.decode("utf-8", errors="replace"))
    except ValueError as ex:
        raise DocError(f"{_where(got.url)}: not an answer of the {what} API (JSON expected): is the address "
                       "right?") from ex
    if not isinstance(data, dict):
        raise DocError(f"{_where(got.url)}: not an answer of the {what} API")
    return data


class _Calls:
    """The API requests a reader may still make (a server whose paging never ends does not hold it)."""

    def __init__(self, n: int) -> None:
        self.left = n

    def spend(self) -> None:
        if self.left <= 0:
            raise _OutOfCalls()
        self.left -= 1


def fetch(url: str, sign: SignIn | None = None) -> tuple[str, str, list[str]]:
    """(title, text, links) of one page, following redirects only to allowed addresses."""
    got = _get(url, sign, _limit())
    text = got.text()
    if "html" in got.ctype or text.lstrip()[:15].lower().startswith(("<!doctype html", "<html")):
        title, content, links = html_to_text(text)
        return title, content, [urljoin(got.url, link) for link in links]
    if got.ctype and not got.ctype.startswith(("text/", "application/json", "application/xml")):
        raise DocError(f"{_where(got.url)}: {got.ctype} is not text (text, Markdown and HTML only)")
    return "", text, []


# --------------------------------------------------------------------------------------------- #
# the readers: each gives [(page address, page title, text)], the document's title if it has none, the pages
# skipped (too large, unreadable)
# --------------------------------------------------------------------------------------------- #
Pages = list[tuple[str, str, str]]


def _read_web(doc: Doc, sign: SignIn | None) -> tuple[Pages, str, int]:
    """A page, then the pages under the same address it links to, up to max_pages."""
    start = doc.url or ""
    base = start.rsplit("/", 1)[0] + "/"
    todo, seen, pages = [start], set(), []
    while todo and len(pages) < _max_pages(doc):
        url = todo.pop(0).split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        title, text, links = fetch(url, sign) if sign is not None else fetch(url)
        pages.append((url, title, text))
        todo += [link for link in links if link.startswith(base) and link.split("#")[0] not in seen]
    return pages, (pages[0][1] if pages else "") or start, 0


CONFLUENCE = [
    ("page", re.compile(r"^(?P<ctx>.*?)/spaces/(?P<space>[^/]+)/pages/(?P<id>\d+)(?:/.*)?$")),
    ("page", re.compile(r"^(?P<ctx>.*?)/pages/viewpage\.action/?$")),
    ("title", re.compile(r"^(?P<ctx>.*?)/display/(?P<space>[^/]+)/(?P<title>[^/]+)/?$")),
    ("space", re.compile(r"^(?P<ctx>.*?)/display/(?P<space>[^/]+)/?$")),
    ("space", re.compile(r"^(?P<ctx>.*?)/spaces/(?P<space>[^/]+)(?:/overview)?/?$")),
]


def confluence_target(url: str) -> dict[str, Any] | None:
    """What a Confluence address names: a page (by id or by title) or a space, and its API (Data Center: under the
    site's context path; Cloud: under /wiki); None: not a Confluence address."""
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    for kind, rx in CONFLUENCE:
        m = rx.match(u.path or "")
        if m is None:
            continue
        found = m.groupdict()
        page_id = found.get("id") or ""
        if "viewpage" in rx.pattern:
            page_id = (parse_qs(u.query).get("pageId") or [""])[0]
            if not page_id.isdigit():
                continue
        web = f"{u.scheme}://{u.netloc}{found['ctx'].rstrip('/')}"
        out: dict[str, Any] = {"kind": kind, "api": f"{web}/rest/api", "web": web,
                               "space": unquote(found.get("space") or "") or None}
        if kind == "page":
            out["id"] = page_id
        if kind == "title":
            out["title"] = unquote_plus(found["title"])
        return out
    return None


def _confluence_url(item: dict[str, Any], base: str | None, t: dict[str, Any]) -> str:
    webui = str((item.get("_links") or {}).get("webui") or "")
    if webui.startswith(("http://", "https://")):
        return webui
    if webui:
        return (base or t["web"]).rstrip("/") + webui
    return f"{t['web']}/pages/viewpage.action?pageId={item.get('id')}"


def _read_confluence(doc: Doc, sign: SignIn | None) -> tuple[Pages, str, int]:
    """A page and the pages under it (breadth first), or a space's pages, through the REST API, up to max_pages."""
    t = confluence_target(doc.url or "")
    if t is None:
        raise DocError(f"{_where(doc.url or '')}: not the address of a Confluence page or space (…/display/SPACE/Page, "
                       "…/spaces/SPACE/pages/ID/…, …/pages/viewpage.action?pageId=ID, …/display/SPACE)")
    want, limit = _max_pages(doc), _limit()
    calls = _Calls(want * 3 + 40)
    pages: Pages = []
    skipped = 0

    def get(path: str) -> dict[str, Any]:
        calls.spend()
        return _json(t["api"] + path, sign, "Confluence")

    def add(item: dict[str, Any], base: str | None) -> None:
        nonlocal skipped
        storage = ((item.get("body") or {}).get("storage") or {}).get("value")
        text = storage_to_text(storage or "")
        if len(text.encode()) > limit:
            skipped += 1
            return
        pages.append((_confluence_url(item, base, t), str(item.get("title") or f"page {item.get('id')}"), text))

    q = lambda s: quote(str(s), safe="")  # noqa: E731
    title = ""
    try:
        if t["kind"] == "space":
            title, start = f"Confluence space {t['space']}", 0
            while len(pages) < want:
                data = get(f"/content?spaceKey={q(t['space'])}&type=page&expand=body.storage,version"
                           f"&limit={CONFLUENCE_LIST}&start={start}")
                results = [r for r in data.get("results") or [] if isinstance(r, dict)]
                base = (data.get("_links") or {}).get("base")
                for item in results:
                    if len(pages) < want:
                        add(item, base)
                if len(results) < CONFLUENCE_LIST or not (data.get("_links") or {}).get("next"):
                    break
                start += len(results)
            return pages, title, skipped
        first, first_base = None, None
        if t["kind"] == "title":
            data = get(f"/content?spaceKey={q(t['space'])}&title={q(t['title'])}&expand=body.storage,version,space")
            results = [r for r in data.get("results") or [] if isinstance(r, dict)]
            if not results:
                raise DocError(f"no page titled {t['title']!r} in the Confluence space {t['space']}")
            first, first_base = results[0], (data.get("_links") or {}).get("base")
            root = str(first.get("id") or "")
        else:
            root = str(t["id"])
        queue, seen = deque([root]), set()
        while queue and len(pages) < want:
            pid = queue.popleft()
            if pid in seen:
                continue
            seen.add(pid)
            if first is not None and str(first.get("id")) == pid:
                item, base = first, first_base
            else:
                item = get(f"/content/{q(pid)}?expand=body.storage,version,space")
                base = (item.get("_links") or {}).get("base")
            add(item, base)
            title = title or str(item.get("title") or "")
            start = 0
            while len(pages) + len(queue) < want:          # the pages under it, until enough wait to be read
                data = get(f"/content/{q(pid)}/child/page?limit={CHILDREN_LIST}&start={start}")
                results = [r for r in data.get("results") or [] if isinstance(r, dict)]
                queue.extend(str(r["id"]) for r in results if r.get("id") and str(r["id"]) not in seen)
                if len(results) < CHILDREN_LIST or not (data.get("_links") or {}).get("next"):
                    break
                start += len(results)
    except _OutOfCalls:
        log.info("supagent: document %s: Confluence requests used up, %d page(s) read", doc.id, len(pages))
    return pages, title or (f"Confluence space {t['space']}" if t.get("space") else "Confluence"), skipped


BITBUCKET_DC = re.compile(r"^(?P<ctx>.*?)/(?:projects/(?P<project>[^/]+)|users/(?P<user>[^/]+))/repos/(?P<repo>[^/]+)"
                          r"(?:/(?:browse|raw)(?:/(?P<path>.*?))?)?/?$")
BITBUCKET_CLOUD = re.compile(r"^/(?P<ws>[^/]+)/(?P<repo>[^/]+)(?:/src(?:/(?P<ref>[^/]+)(?:/(?P<path>.*?))?)?)?/?$")
# a repository's clone address (Data Center: https://host[/context]/scm/KEY/repo.git, ~user for a personal one)
BITBUCKET_SCM = re.compile(r"^(?P<ctx>.*?)/scm/(?P<key>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


def bitbucket_target(url: str) -> dict[str, Any] | None:
    """What a Bitbucket address names: a repository and a folder in it (with its branch or commit), and its API;
    None: not a Bitbucket repository address."""
    u = urlparse(url or "")
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    netloc = u.netloc.rsplit("@", 1)[-1].lower()      # (a clone address may carry a user: user@host)
    q = lambda s: quote(str(s), safe="")  # noqa: E731
    if netloc in CLOUD_APIS:
        m = BITBUCKET_CLOUD.match(u.path or "")
        if m is None:
            return None
        ws, repo = unquote(m.group("ws")), unquote(m.group("repo"))
        if repo.endswith(".git") and not m.group("ref"):
            repo = repo[:-len(".git")]                  # its clone address: the repository
        return {"cloud": True, "api": f"{CLOUD_APIS[netloc]}/repositories/{q(ws)}/{q(repo)}/src",
                "ref": unquote(m.group("ref") or ""), "path": unquote((m.group("path") or "").strip("/")),
                "web": f"{u.scheme}://{netloc}/{q(ws)}/{q(repo)}", "name": f"{ws}/{repo}"}
    m = BITBUCKET_DC.match(u.path or "")
    if m is None:
        s = BITBUCKET_SCM.match(u.path or "")         # its clone address: the repository, its default branch
        if s is None:
            return None
        key, repo = unquote(s.group("key")), unquote(s.group("repo"))
        base = f"{u.scheme}://{netloc}{s.group('ctx').rstrip('/')}"
        owner = f"users/{q(key[1:])}" if key.startswith("~") else f"projects/{q(key)}"
        return {"cloud": False, "api": f"{base}/rest/api/1.0/projects/{q(key)}/repos/{q(repo)}", "at": "",
                "path": "", "web": f"{base}/{owner}/repos/{q(repo)}", "name": f"{key}/{repo}"}
    user = unquote(m.group("user") or "")
    project = unquote(m.group("project") or "") or f"~{user}"
    repo = unquote(m.group("repo"))
    base = f"{u.scheme}://{netloc}{m.group('ctx').rstrip('/')}"
    owner = f"projects/{q(project)}" if m.group("project") else f"users/{q(user)}"
    return {"cloud": False, "api": f"{base}/rest/api/1.0/projects/{q(project)}/repos/{q(repo)}",
            "at": (parse_qs(u.query).get("at") or [""])[0], "path": unquote((m.group("path") or "").strip("/")),
            "web": f"{base}/{owner}/repos/{q(repo)}", "name": f"{project}/{repo}"}


def is_text_file(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name.endswith(TEXT_FILES) or (name.startswith("readme") and "." not in name)


def wanted_file(path: str, files: str = "docs") -> bool:
    """A repository's file to read: a text file (and with files "code", a source or build file), never a file that
    holds keys, nor one under node_modules, vendor, dist, build... nor a minified or lock file."""
    low = path.lower()
    parts = low.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]) or KEY_FILE.search(low) or SKIP_FILE.search(low):
        return False
    if is_text_file(path):
        return True
    return files == "code" and (parts[-1].endswith(CODE_FILES) or parts[-1] in CODE_NAMES)


def doc_rank(path: str) -> tuple[int, int, str]:
    """The documentation first: READMEs, the documentation folders' texts, the other texts (Markdown, text...),
    the documentation folders' other files, then the rest (configuration, SQL...); the shallow ones first."""
    low = path.lower()
    name = low.rsplit("/", 1)[-1]
    in_docs = any(part in DOC_FOLDERS for part in low.split("/")[:-1])
    texts = name.endswith(DOC_TYPES)
    if name.startswith("readme"):
        group = 0
    else:
        group = (1 if texts else 3) if in_docs else (2 if texts else 4)
    return group, low.count("/"), low


def _repo_api(t: dict[str, Any]) -> str:
    """The API of the repository itself (Cloud: its address without /src)."""
    return t["api"][:-len("/src")] if t["cloud"] and t["api"].endswith("/src") else t["api"]


def _head(t: dict[str, Any], sign: SignIn | None, calls: _Calls) -> str | None:
    """The last commit of the branch (or commit) the document reads; None when the server does not say (the
    repository is then read in full)."""
    try:
        if t["cloud"]:
            ref = t["ref"]
            if not ref:
                calls.spend()
                ref = str(((_json(_repo_api(t), sign, "Bitbucket").get("mainbranch") or {}).get("name")) or "")
                if not ref:
                    return None
            calls.spend()
            values = _json(f"{_repo_api(t)}/commits/{quote(ref, safe='')}?pagelen=1", sign, "Bitbucket").get("values")
            key = "hash"
        else:
            calls.spend()
            until = f"&until={quote(t['at'], safe='')}" if t["at"] else ""
            values = _json(f"{t['api']}/commits?limit=1{until}", sign, "Bitbucket").get("values")
            key = "id"
        first = values[0] if isinstance(values, list) and values and isinstance(values[0], dict) else {}
        return str(first.get(key) or "") or None
    except (DocError, _OutOfCalls, requests.exceptions.RequestException) as ex:
        if "asked to sign in" in str(ex):
            raise
        log.info("supagent: the last commit of %s not known (%s): read in full", t["name"], str(ex)[:200])
        return None


def _changed(t: dict[str, Any], sign: SignIn | None, old: str, new: str, calls: _Calls) -> set[str] | None:
    """The paths a change between two commits touched (added, changed, deleted, the old and new path of a move);
    None when the server does not say or too many changed (the repository is then read in full)."""
    out: set[str] = set()
    try:
        if t["cloud"]:
            url: str | None = f"{_repo_api(t)}/diffstat/{quote(new, safe='')}..{quote(old, safe='')}?pagelen=500"
            while url and len(out) < MAX_CHANGES:
                calls.spend()
                data = _json(url, sign, "Bitbucket")
                for v in data.get("values") or []:
                    for side in ("old", "new"):
                        path = ((v or {}).get(side) or {}).get("path") if isinstance(v, dict) else None
                        if path:
                            out.add(str(path))
                url = data.get("next")
        else:
            start = 0
            while len(out) < MAX_CHANGES:
                calls.spend()
                data = _json(f"{t['api']}/changes?since={quote(old, safe='')}&until={quote(new, safe='')}"
                             f"&limit=500&start={start}", sign, "Bitbucket")
                values = [v for v in data.get("values") or [] if isinstance(v, dict)]
                for v in values:
                    for side in ("path", "srcPath"):
                        path = (v.get(side) or {}).get("toString") if isinstance(v.get(side), dict) else None
                        if path:
                            out.add(str(path))
                if data.get("isLastPage", True) or not values:
                    break
                nxt = data.get("nextPageStart")
                start = int(nxt) if isinstance(nxt, int) else start + len(values)
    except (DocError, _OutOfCalls, requests.exceptions.RequestException) as ex:
        if "asked to sign in" in str(ex):
            raise
        log.info("supagent: the changes of %s not known (%s): read in full", t["name"], str(ex)[:200])
        return None
    return out if len(out) < MAX_CHANGES else None


def _file_at(t: dict[str, Any], path: str, commit: str | None) -> dict[str, Any]:
    """A file's addresses: raw at the commit read (or the document's branch), and its page, the document's branch
    (not the commit: the page's address names its pieces in the search, the same from one read to the next)."""
    q = quote(path)
    if t["cloud"]:
        at = commit or t["ref"]
        raw = f"{t['api']}/{quote(at, safe='')}/{q}" if at else f"{t['api']}/HEAD/{q}"
        return {"path": path, "raw": raw, "web": f"{t['web']}/src/{quote(t['ref'] or 'HEAD', safe='')}/{q}"}
    at = commit or t["at"]
    suffix = f"?at={quote(t['at'], safe='')}" if t["at"] else ""
    return {"path": path, "raw": f"{t['api']}/raw/{q}" + (f"?at={quote(at, safe='')}" if at else ""),
            "web": f"{t['web']}/browse/{q}{suffix}"}


def _bitbucket_dc_files(t: dict[str, Any], sign: SignIn | None, calls: _Calls) -> list[dict[str, Any]]:
    """The files under the folder (Bitbucket Data Center lists them recursively), page by page."""
    at = f"at={quote(t['at'], safe='')}" if t["at"] else ""
    folder = "/" + quote(t["path"]) if t["path"] else ""
    paths: list[str] = []
    start = 0
    try:
        while len(paths) < MAX_LISTED:
            calls.spend()
            data = _json(f"{t['api']}/files{folder}?limit={REPO_LIST}&start={start}" + (f"&{at}" if at else ""),
                         sign, "Bitbucket")
            values = [str(v) for v in data.get("values") or []]
            paths += [f"{t['path']}/{v}" if t["path"] else v for v in values]
            if data.get("isLastPage", True) or not values:
                break
            nxt = data.get("nextPageStart")
            start = int(nxt) if isinstance(nxt, int) else start + len(values)
    except _OutOfCalls:                                 # what was listed is read
        log.info("supagent: Bitbucket listing of %s cut at %d files", t["name"], len(paths))
    suffix = f"?{at}" if at else ""
    return [{"path": p, "raw": f"{t['api']}/raw/{quote(p)}{suffix}", "web": f"{t['web']}/browse/{quote(p)}{suffix}"}
            for p in paths[:MAX_LISTED]]


def _bitbucket_cloud_files(t: dict[str, Any], sign: SignIn | None, calls: _Calls) -> list[dict[str, Any]]:
    """The files under the folder (Bitbucket Cloud lists one folder at a time: the folders under it after it)."""
    ref = quote(t["ref"], safe="")
    first = f"{t['api']}/{ref}/{quote(t['path']) + '/' if t['path'] else ''}" if t["ref"] else t["api"]
    queue: deque[str] = deque([first])
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    try:
        while queue and len(out) < MAX_LISTED:
            url: str | None = queue.popleft()
            while url and len(out) < MAX_LISTED and url not in seen:
                seen.add(url)
                calls.spend()
                data = _json(url if "pagelen=" in url else url + ("&" if "?" in url else "?") + "pagelen=100", sign,
                             "Bitbucket")
                for v in data.get("values") or []:
                    if not isinstance(v, dict):
                        continue
                    path = str(v.get("path") or "")
                    href = ((v.get("links") or {}).get("self") or {}).get("href")
                    at = t["ref"] or str((v.get("commit") or {}).get("hash") or "")
                    if v.get("type") == "commit_directory":
                        folder = href or f"{t['api']}/{quote(at, safe='')}/{quote(path)}/"
                        if path.rsplit("/", 1)[-1].lower() in DOC_FOLDERS:
                            queue.appendleft(folder)            # the documentation's folders first
                        else:
                            queue.append(folder)
                    elif v.get("type") == "commit_file":
                        out.append({"path": path, "size": v.get("size"),
                                    "raw": href or f"{t['api']}/{quote(at, safe='')}/{quote(path)}",
                                    "web": f"{t['web']}/src/{quote(t['ref'] or 'HEAD', safe='')}/{quote(path)}"})
                url = data.get("next")
    except _OutOfCalls:                                 # what was listed is read
        log.info("supagent: Bitbucket listing of %s cut at %d files", t["name"], len(out))
    return out


def _one_file(t: dict[str, Any]) -> dict[str, Any]:
    path = quote(t["path"])
    if t["cloud"]:
        ref = quote(t["ref"], safe="")
        return {"path": t["path"], "raw": f"{t['api']}/{ref}/{path}", "web": f"{t['web']}/src/{ref}/{path}"}
    at = f"?at={quote(t['at'], safe='')}" if t["at"] else ""
    return {"path": t["path"], "raw": f"{t['api']}/raw/{path}{at}", "web": f"{t['web']}/browse/{path}{at}"}


FRONT_MATTER = re.compile(r"\A---[ \t]*\n(.*?)\n(?:---|\.\.\.)[ \t]*(?:\n|\Z)", re.S)
FRONT_KEY = re.compile(r"^(title|description|summary)[ \t]*:[ \t]*(.+?)[ \t]*$", re.M | re.I)
FIRST_HEADING = re.compile(r"^#[ \t]+(.+?)[ \t]*#*[ \t]*$", re.M)


def repo_page(url: str, path: str, text: str) -> tuple[str, str, str]:
    """A text file of a repository as a page (its address, its title, its text): a Markdown file's front matter (the
    YAML block of Jekyll, Hugo, MkDocs... at its top) is not its text, its title (or its first heading) names the page
    with the file's path, its description starts the text."""
    title, body = "", text or ""
    if path.lower().endswith((".md", ".markdown")):
        m = FRONT_MATTER.match(body)
        meta: dict[str, str] = {}
        if m:
            for k, v in FRONT_KEY.findall(m.group(1)):
                meta.setdefault(k.lower(), v.strip().strip("'\""))
            body = body[m.end():]
            if meta.get("description") or meta.get("summary"):
                body = (meta.get("description") or meta.get("summary") or "") + "\n\n" + body.lstrip("\n")
        h = FIRST_HEADING.search(body)
        title = meta.get("title") or (h.group(1).strip() if h else "")
    return url, (f"{title} ({path})" if title and title != path else path), body


def _stored(doc: Doc) -> dict[str, tuple[str, str, str, dict[str, Any]]]:
    """The files a repository document read last time, by path, with their text and what they were read at (only the
    pages a version that keeps them wrote: else {}, and the repository is read in full)."""
    content, out = doc.content or "", {}
    for p in doc.pages or []:
        if not (isinstance(p, dict) and p.get("path") and isinstance(p.get("at"), int)
                and isinstance(p.get("chars"), int)):
            return {}
        block = content[p["at"]:p["at"] + p["chars"]]
        head = f"# {p['title']}\n" if p.get("title") else ""
        if not block.startswith(head):
            return {}
        out[str(p["path"])] = (str(p.get("url") or ""), str(p.get("title") or ""), block[len(head):],
                               {k: p.get(k) for k in ("path", "commit", "scope")})
    return out


def _read_file(f: dict[str, Any], sign: SignIn | None, limit: int, calls: _Calls) -> tuple[str, int]:
    """A repository file's text (HTML as text), its secrets masked; (text, secrets masked)."""
    calls.spend()
    text = _get(f["raw"], sign, limit).text()
    if f["path"].lower().endswith((".html", ".htm")):
        text = html_to_text(text)[1]
    return mask_secrets(text)


def _read_bitbucket(doc: Doc, sign: SignIn | None) -> tuple[Pages, str, int]:
    """The files of a repository folder through the REST API, the documentation first, up to max_pages: its text files
    (files "docs"), or all its code too (files "code"), the secrets in them masked. Read again, only what changed since
    the commit read last time (the same commit: nothing; a change too big to list: in full)."""
    t = bitbucket_target(doc.url or "")
    if t is None:
        raise DocError(f"{_where(doc.url or '')}: not the address of a Bitbucket repository (…/projects/KEY/repos/"
                       "REPO/browse/folder, …/scm/KEY/REPO.git, or bitbucket.org/WORKSPACE/REPO/src/BRANCH/folder)")
    want, limit, files = _max_pages(doc), _limit(), files_of(doc)
    where = f" in {t['path']}" if t["path"] else ""
    title = f"{t['name']}{(' ' + t['path']) if t['path'] else ''}"
    one = bool(t["path"] and wanted_file(t["path"], "code") and (t["cloud"] is False or t["ref"]))
    calls = _Calls(want * 2 + 40)
    head = None if one else _head(t, sign, calls)
    scope = f"{t['path']}|{t.get('ref') or t.get('at') or ''}|{files}|{want}"
    before = _stored(doc)
    same = bool(before) and all(m.get("scope") == scope for *_x, m in before.values())
    meta = lambda path: {"path": path, "commit": head or "", "scope": scope}  # noqa: E731
    if head and same and all(m.get("commit") == head for *_x, m in before.values()):
        log.info("supagent: document %s: %s at the same commit %s: nothing to read", doc.id, t["name"], head[:12])
        return [(u, ti, tx, meta(p)) for p, (u, ti, tx, _m) in before.items()], title, 0
    stale = {m.get("commit") for *_x, m in before.values()} if same else set()
    touched = _changed(t, sign, stale.pop(), head, calls) if (head and len(stale) == 1 and None not in stale
                                                              and "" not in stale) else None
    pages: list[tuple[str, str, str, dict[str, Any]]] = []
    skipped, last, masked = 0, "", 0
    if touched is not None:                             # only the files that changed are read again
        prefix = t["path"] + "/" if t["path"] else ""
        keep = {p: v for p, v in before.items() if p not in touched}
        todo = sorted((p for p in touched if p.startswith(prefix) and wanted_file(p, files)), key=doc_rank)
        pages = [(u, ti, tx, meta(p)) for p, (u, ti, tx, _m) in keep.items()]
        for path in todo:
            if len(pages) >= want:
                break
            f = _file_at(t, path, head)
            try:
                text, n = _read_file(f, sign, limit, calls)
            except _OutOfCalls:
                return _with_rest(pages, before, touched, meta), title, skipped   # the rest kept as it was
            except DocError as ex:
                if "asked to sign in" in str(ex):
                    raise
                if "HTTP 404" not in str(ex):          # 404: deleted (or moved away) at that commit
                    skipped, last = skipped + 1, str(ex)
                continue
            except requests.exceptions.RequestException as ex:
                skipped, last = skipped + 1, f"{path}: {type(ex).__name__}"
                continue
            masked += n
            pages.append((*repo_page(f["web"], path, text), meta(path)))
        log.info("supagent: document %s: %s read again from %s: %d file(s) changed, %d kept, %d secret(s) masked",
                 doc.id, t["name"], (head or "")[:12], len(todo), len(keep), masked)
        pages.sort(key=lambda x: doc_rank(x[3]["path"]))
        if pages:
            return pages, title, skipped
    if one:
        found = [_one_file(t)]                          # the address of one file: that file
    else:
        lister: Callable[..., list[dict[str, Any]]] = _bitbucket_cloud_files if t["cloud"] else _bitbucket_dc_files
        found = lister(t, sign, _Calls(80 + want))      # listing and reading: each its own number of requests
    chosen = sorted((f for f in found if wanted_file(f["path"], files) or one), key=lambda f: doc_rank(f["path"]))
    if not chosen:
        kinds = "text or code" if files == "code" else "text (Markdown, text, HTML, YAML, JSON, CSV, SQL...)"
        raise DocError(f"{t['name']}: no {kinds} file{where}")
    pages, partial = [], False
    for f in chosen:
        if len(pages) >= want:
            break
        if isinstance(f.get("size"), int) and f["size"] > limit:
            skipped += 1
            last = f"{f['path']}: larger than {limit // 1024} KB"
            continue
        g = _file_at(t, f["path"], head) if head else f
        try:
            text, n = _read_file({**f, "raw": g["raw"]}, sign, limit, calls)
        except _OutOfCalls:
            partial = True                            # not all read: no commit kept, read in full next time
            break
        except DocError as ex:
            if "asked to sign in" in str(ex):
                raise
            skipped, last = skipped + 1, str(ex)
            continue
        except requests.exceptions.RequestException as ex:
            skipped, last = skipped + 1, f"{f['path']}: {type(ex).__name__}"
            continue
        masked += n
        pages.append((*repo_page(f["web"], f["path"], text), meta(f["path"])))
    if not pages:
        raise DocError(f"{t['name']}: none of its files{where} could be read ({last})")
    if partial:
        pages = [(u, ti, tx, {**m, "commit": ""}) for u, ti, tx, m in pages]
    log.info("supagent: document %s: %s read in full at %s: %d file(s), %d secret(s) masked", doc.id, t["name"],
             (head or "the branch")[:12], len(pages), masked)
    return pages, title, skipped


def _with_rest(pages: list, before: dict, touched: set[str], meta: Callable[[str], dict]) -> list:
    """The files read again so far, and the others as they were (the requests ran out: the next read goes on).
    A file kept as it was keeps the commit it was read at, so that it is read again next time."""
    have = {x[3]["path"] for x in pages}
    rest = [(u, ti, tx, m) for p, (u, ti, tx, m) in before.items() if p in touched and p not in have]
    return sorted(pages + rest, key=lambda x: doc_rank(x[3]["path"]))


def _join(found: list) -> tuple[str, list[dict[str, Any]]]:
    """The document's text (its pages joined) and its pages, each with where its text starts (at) and its length,
    and for a repository's file its path and the commit it was read at."""
    texts: list[str] = []
    pages: list[dict[str, Any]] = []
    at = 0
    for url, title, text, *more in found:
        block = (f"# {title}\n" if title else "") + (text or "")
        if texts:
            at += 2                                     # the blank line between two pages
        pages.append({"url": url, "title": title, "chars": len(block), "at": at,
                      **{k: v for k, v in (more[0] if more and isinstance(more[0], dict) else {}).items()
                         if k in ("path", "commit", "scope")}})
        texts.append(block)
        at += len(block)
    return "\n\n".join(texts), pages


def refresh(doc: Doc) -> dict[str, Any]:
    """Read a document's address again with its reader (and its sign-in, if it has one)."""
    reader = reader_of(doc)
    skipped, changed = 0, False
    token = None
    try:
        sign = sign_in(doc)
        token = _VERIFY.set(tls_of(doc))            # the site's certificate: checked, with a CA file, or not
        read = {"web": _read_web, "confluence": _read_confluence, "bitbucket": _read_bitbucket}[reader]
        found, title, skipped = read(doc, sign)
        content, pages = _join(found)
        h = hashlib.sha256(content.encode()).hexdigest()[:40]
        changed = h != doc.content_hash
        doc.content, doc.pages, doc.content_hash = content, pages, h
        doc.title = doc.title or title or doc.url
        doc.status, doc.error = "ok", None
    except Exception as ex:  # pylint: disable=broad-except   (any failure is the document's error, said safely)
        said = str(ex) if isinstance(ex, DocError) else f"{type(ex).__name__}: {ex}"
        doc.status, doc.error = "error", scrub(said, doc)[:500]
        log.info("supagent: document %s (%s) not read: %s", doc.id, reader, doc.error)
    finally:
        if token is not None:
            _VERIFY.reset(token)
    doc.fetched_at = dt.datetime.utcnow()
    db.session.commit()
    return {"id": doc.id, "status": doc.status, "reader": reader, "pages": len(doc.pages or []), "skipped": skipped,
            "changed": changed, "error": doc.error}


def due_docs() -> list[Doc]:
    now = dt.datetime.utcnow()
    return [d for d in db.session.query(Doc).filter(Doc.kind == "url", Doc.enabled.is_(True))
            if d.fetched_at is None or now - d.fetched_at > dt.timedelta(days=max(1, d.refresh_days or 7))]


def refresh_due() -> list[dict[str, Any]]:
    return [refresh(d) for d in due_docs()]
