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
import time
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, unquote_plus, urljoin, urlparse, urlunparse

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
MAX_LISTED = 20000              # files of a repository listed at most (what is read is chosen among them; 0.10.12: was 5,000)
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
              ".jinja", ".jinja2", ".erb", ".epp", ".gotmpl", ".tftpl", ".tpl", ".tmpl", ".dockerfile", ".cfg", ".ini",
              ".conf", ".properties", ".xml", ".sql",
              ".yaml", ".yml", ".json", ".service", ".timer", ".socket", ".env.example",
              # (0.10.12) the scripts and configuration of operations repositories
              ".csh", ".tcsh", ".fish", ".awk", ".sed", ".tcl", ".vbs", ".psd1", ".pyw", ".pp", ".sls", ".spec",
              ".rules", ".repo", ".cnf", ".nomad", ".rego", ".bicep", ".jsonnet", ".libsonnet", ".cue", ".nix",
              ".pls", ".pks", ".pkb", ".ddl", ".hql", ".mk", ".cmake", ".bzl", ".sbt", ".cljs", ".edn", ".zig",
              ".nim", ".gemspec", ".rake", ".xsd", ".xsl", ".xslt", ".wsdl", ".ldif", ".cron", ".crontab",
              ".logrotate", ".pl.in", ".sh.in", ".py.in", ".in")
CODE_NAMES = {"dockerfile", "containerfile", "makefile", "jenkinsfile", "vagrantfile", "procfile", "gemfile",
              "rakefile", "build", "workspace", "cmakelists.txt", "caddyfile", "corefile", "monitrc", "crontab"}
# (0.10.4) the files an Ansible role copies or renders named after the path they go to (etc_monit_conf.d_postfix,
# etc_apache2_sites-available_blog): its configuration, read with the code; never one whose name speaks of a secret
ROLE_FILE = re.compile(r"(^|/)roles/[^/]+/(files|templates)/(?![^/]*(secret|passw|token|key|cert|crt|pem|vault|"
                       r"credential|id_rsa|id_ed25519|htpasswd|shadow))(etc|usr|var|opt|srv)_[^/.]*(\.[^/.]+)*$", re.I)
SKIP_DIRS = {"node_modules", "vendor", "dist", "target", "out", "obj", ".git", "__pycache__",
             ".venv", "venv", "site-packages", "bower_components", ".idea", ".vscode", "coverage", ".gradle", ".mvn",
             ".terraform", ".next", ".nuxt"}
SKIP_FILE = re.compile(r"(\.min\.(js|css)|\.map|\.lock|(^|/)(package-lock\.json|npm-shrinkwrap\.json|"
                       r"pnpm-lock\.yaml|go\.sum))$", re.I)
# (0.10.10) the folders of a repository's scripts: their files without an extension are scripts (bin/, scripts/, sbin/)
SCRIPT_DIRS = {"bin", "sbin", "scripts", "script", "tools", "cron.d", "cron"}
# (0.10.12) a build folder: its scripts are read (build/deploy.sh), what a build left in it is not
BUILD_DIRS = {"build"}
SCRIPT_FILES = (".sh", ".bash", ".zsh", ".ksh", ".csh", ".fish", ".ps1", ".psm1", ".bat", ".cmd", ".gradle", ".kts",
                ".mk", ".cmake")         # (a .py or .js there may be a copy a build made: not read)
# an Ansible role's files and templates (what it copies: ROLE_FILE says which are read) and a trust store's names
ROLE_DIR = re.compile(r"(^|/)roles/[^/]+/(files|templates)/")
TRUST_NAME = re.compile(r"(^|[_.-])(ca|cacert|ca-bundle|cabundle|truststore|keystore|chain|fullchain)$", re.I)
# files without an extension that are not scripts (a script elsewhere than bin/ or scripts/ is known by its #! line)
NOT_SCRIPT_NAME = re.compile(r"^(license|licence|copying|authors|contributors|notice|changelog|changes|history|news|"
                             r"todo|version|owners|codeowners|maintainers|patents|install|readme)", re.I)
SECRET_NAME = re.compile(r"secret|passw|token|key|cert|crt|pem|vault|credential|id_rsa|id_ed25519|htpasswd|shadow", re.I)
# (0.10) Ansible's files without an extension: the inventories (hosts, inventory, hosts.example...) and the variables
# of groups and hosts (group_vars/<group>, host_vars/<host>, or a folder of them)
ANSIBLE_FILE = re.compile(r"(^|/)((hosts|inventory)([._-][\w.-]*)?|(group|host)_vars/[^/.]+(/[^/.]+)?|"
                          r"inventor(y|ies)/([^/]+/)*[^/.]+)$", re.I)
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
    # a connection string's password (ADO.NET, Npgsql, ODBC: Password=...; Pwd=...): any character up to the next ;
    (re.compile(r"(?i)((?:^|[;\"'])\s*(?:password|pwd)=)(?!\*\*\*)([^;\"'\s]{3,})", re.M), r"\1***"),
    # a secret given as the default of an environment lookup: os.environ.get("API_TOKEN", "..."), getenv, ENV.fetch
    (re.compile(r"(?i)(\b(?:getenv|environ\.get|env\.get|ENV\.fetch|System\.getenv|process\.env\.\w+\s*\?\?)"
                r"\(?\s*[\"'][\w.-]*(?:password|passwd|pwd|secret|token|key|credential)[\w.-]*[\"']\s*,\s*)"
                r"([\"'][^\"'\n]{4,}[\"'])"), r'\1"***"'),
    (re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 ***"),
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|glpat-[A-Za-z0-9_-]{20,}|"
                r"xox[baprs]-[A-Za-z0-9-]{10,})\b"), "***"),
]
# (0.10) the names of a secret in configuration (an Ansible variable, an INI or .env key, a YAML key): any value they
# are given is masked, however short (upassword: abc, auth_pass: "1ce24b6e", ansible_ssh_pass=x, password=12345)
SECRET_WORD = re.compile(r"(?i)(password|passwd|passphrase|pwd|secret|token|credentials?|api[_-]?key|apikey|"
                         r"access[_-]?key|private[_-]?key|(?:^|[_.-])pass(?:$|[_.-]))")
# ... but not the name of a file, an address, a length or a reference that holds or describes it
NOT_SECRET_NAME = re.compile(r"(?i)(?:^|[_.-]|(?<=[a-z]))(name|names|file|files|path|dir|ref|url|uri|length|policy|"
                             r"type|mode|version|enabled|required|min|max|expiry|ttl|id|hash|algorithm|header|field|"
                             r"env|source)$")
NOT_A_VALUE = re.compile(r"(?i)^(true|false|yes|no|on|off|null|none|nil|~|str|int|bytes|string|bool|boolean|"
                         r"optional|secretstr|any|undefined|required)$")
# (0.10) a secret written in a sentence, in the languages teams write in: its label, a few words, a separator, the
# value ("Mot de passe de l'administrateur : ...", "Passwort für Grafana: ...", "the API key is ...")
PROSE_SECRET = re.compile(
    r"(?i)(?P<head>\b(?:pass(?:word|wd|phrase)|pwd|secret|token|api[ _-]?key|access[ _-]?key|private[ _-]?key|"
    r"mot de passe|mdp|passwort|kennwort|zugangsdaten|contrase[ñn]a|clave|senha|wachtwoord|parola d['’]ordine|"
    r"has[łl]o|l[öo]senord|salasana|jeton|cl[ée] (?:d['’])?api|cl[ée] secr[èe]te)\b"
    r"(?P<gap>[^\n:=.!?;|]{0,60}?)(?:\s*[:=]\s*|\s+(?:is|est|ist|es|è|é|era|was|war|vaut)\s+))"
    r"(?P<value>\"[^\"\n]{3,}\"|'[^'\n]{3,}'|`[^`\n]{3,}`|[^\s\"'`<>|]{3,})")
# the words around a secret's label that make it describe the secret, not give it (its expiry, its file...)
NOT_SECRET_GAP = re.compile(r"(?i)\b(name|names|file|files|path|dir|ref|url|uri|length|policy|type|mode|version|"
                            r"expiry|expires|ttl|id|hash|algorithm|header|field|rotation|age|lifetime|size|count|"
                            r"format|location|endpoint|nom|fichier|chemin|longueur|durée|dauer|datei|pfad|länge)\b")


def _prose_secret(m: re.Match) -> str:
    """The value of a secret written in a sentence masked when it looks like a credential: a digit or a symbol in
    it, or long and of mixed case; a plain word ("stored", "rotated"), a reference or a placeholder is kept."""
    raw = m.group("value")
    quoted = raw[:1] in "\"'`"
    v = raw.strip("\"'`")
    tail = "" if quoted else re.search(r"[.,;:!?)\]]*$", v).group(0)
    v = v[:len(v) - len(tail)] if tail else v
    if not v or v.startswith(("***", "<", "${", "{{", "$(", "%(", "/", "~", "./")) or "://" in v or \
            NOT_A_VALUE.match(v) or v.lower().startswith(("vault", "env:", "secret/")) or \
            NOT_SECRET_GAP.search(m.group("gap") or "") or re.search(r"[(\[{]", v):
        return m.group(0)                                    # (a call, an index, a structure: code, not a value)
    looks = bool(re.search(r"\d", v)) or bool(re.search(r"[^\w\s]", v)) or \
        (len(v) >= 12 and bool(re.search(r"[a-z]", v)) and bool(re.search(r"[A-Z]", v)))
    if not looks:
        return m.group(0)
    return m.group("head") + ("***" if not quoted else raw[0] + "***" + raw[0]) + tail


CONFIG_LINE = re.compile(r"(?m)^(?P<head>[ \t]*#?[ \t]*(?:-[ \t]+)?[\"']?(?P<key>[A-Za-z_][\w.-]*)[\"']?[ \t]*"
                         r"(?:=>|:=|[:=])[ \t]*)(?P<value>\"[^\"\n]*\"|'[^'\n]*'|[^\s#\"'][^\s#]*)(?=[ \t]*(?:#.*)?$)")
INLINE_PAIR = re.compile(r"(?<![\w.$-])(?P<head>(?P<key>[A-Za-z_][\w.-]*)=)(?P<value>\"[^\"\n]*\"|'[^'\n]*'|"
                         r"[^\s\"',;&)]+)")


def _literal(value: str, inline: bool) -> bool:
    """A secret's value written as it is (not a reference to it, not a type, not an expression)."""
    v = value.strip().strip("\"'")
    if not v or v.startswith(("***", "{{", "${", "$(", "%(", "<", "!", "lookup(", "vault")) or NOT_A_VALUE.match(v):
        return False
    if re.search(r"[(\[{]", v):
        return False                                   # a call, an index, a structure: code
    if inline and re.fullmatch(r"[A-Z][A-Z0-9_]+", v):
        return False                                   # an environment variable's name (password=PGPASSWORD)
    return True


def _secret_value(m: re.Match, inline: bool = False) -> str:
    key = m.group("key")
    if not SECRET_WORD.search(key) or NOT_SECRET_NAME.search(key) or not _literal(m.group("value"), inline):
        return m.group(0)
    return m.group("head") + "***"


def _secret_maps(text: str) -> tuple[str, int]:
    """The values under a key that names secrets and holds a map (app_secrets:\\n  prod: 9bf8...): masked."""
    out, depth, n = [], None, 0
    for line in text.split("\n"):
        ind = len(line.expandtabs()) - len(line.expandtabs().lstrip(" "))
        if depth is not None:
            if line.strip() and ind <= depth:
                depth = None
            else:
                m = re.match(r"^([ \t]*(?:-[ \t]+)?[\"']?[\w.-]+[\"']?[ \t]*:[ \t]*)(\S.*)$", line)   # (0.11.1) no
                if m and not m.group(2).startswith(("{{", "***", "#", "|", ">", "&", "*")) and \
                        _literal(m.group(2).rstrip(" \t"), False):          # backtracking on a run of spaces
                    line, n = m.group(1) + "***", n + 1
        if depth is None:
            m = re.match(r"^([ \t]*)(?:-[ \t]+)?[\"']?([A-Za-z_][\w.-]*)[\"']?[ \t]*:[ \t]*(?:#.*)?$", line)
            if m and SECRET_WORD.search(m.group(2)) and not NOT_SECRET_NAME.search(m.group(2)):
                depth = len(m.group(1).expandtabs())
        out.append(line)
    return "\n".join(out), n
MAX_CHANGES = 3000              # files changed between two reads of a repository at most (more: read in full)
_VERIFY: contextvars.ContextVar[Any] = contextvars.ContextVar("supagent_doc_verify", default=True)
# (0.10.7) what a reading left out, for the list of a document's pages: each page not read and why, and how many
# pages its links led to that the document's limit (max_pages) left unread
_READ_LOG: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar("supagent_doc_read", default=None)
NOT_READ_KEPT = 1000            # pages not read, said one by one at most
READ_LOG_KEY = "docread:{}"     # supagent_meta: the last reading of a document (pages not read, limit reached)
# (0.11.4) the date the page being fetched says it was last changed (fetch writes it, _read_web keeps it in the page)
_PAGE_DAY: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("supagent_page_day", default=None)
ANCESTORS = 12                  # (0.11.4) a Confluence page's parents kept (the top ones: its place in the tree)


def _not_read(where: str, title: str, why: str) -> None:
    got = _READ_LOG.get()
    if got is not None:
        got["not_read"] += 1
        if len(got["skipped"]) < NOT_READ_KEPT:
            got["skipped"].append({"url": str(where or "")[:500], "title": str(title or "")[:200], "why": why[:200]})


def _left_unread(n: int) -> None:
    got = _READ_LOG.get()
    if got is not None:
        got["left"] = max(0, int(n))


def day_of(value: Any) -> str | None:
    """(0.11.4) The day a source says a page was last changed, as YYYY-MM-DD: an ISO date or time (Confluence's
    version.when, a page's dated meta) or an HTTP date (Last-Modified). None when it is not a date, or not a plausible
    one (before 1990, after tomorrow): a page's date is what its source says, never guessed."""
    s = str(value or "").strip()
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?![\d])", s)
    try:
        if m:
            day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        elif re.search(r"[A-Za-z]{3}", s) and re.search(r"\b\d{4}\b", s):
            from email.utils import parsedate_to_datetime

            day = parsedate_to_datetime(s).date()
        else:
            return None
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    return day.isoformat() if dt.date(1990, 1, 1) <= day <= dt.date.today() + dt.timedelta(days=1) else None


def _header_day(headers: Any) -> str | None:
    """(0.11.4) A web page's Last-Modified header as its date, only when it is a day older than the answer (its Date
    header, else now): a page made for each request says when it was made, not when its text changed."""
    from email.utils import parsedate_to_datetime

    said = (headers or {}).get("Last-Modified")
    if not said or day_of(said) is None:
        return None
    try:
        changed = parsedate_to_datetime(said)
        sent = parsedate_to_datetime(headers["Date"]) if headers.get("Date") else dt.datetime.now(dt.timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    changed, sent = (x if x.tzinfo else x.replace(tzinfo=dt.timezone.utc) for x in (changed, sent))
    return day_of(said) if sent - changed >= dt.timedelta(days=1) else None


def read_log(doc_id: int) -> dict[str, Any]:
    """(0.10.7) The last reading of a document: {"at", "reader", "read", "max_pages", "limit_reached", "left",
    "not_read", "skipped": [{"url", "title", "why"}]}; {} before its first reading with 0.10.7."""
    from supagent.models import Meta

    try:
        row = db.session.get(Meta, READ_LOG_KEY.format(doc_id))
        return json.loads(row.value) if row is not None and row.value else {}
    except Exception:  # pylint: disable=broad-except   (an older or broken row: none)
        db.session.rollback()
        return {}
HEADER_NAME = re.compile(r"^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$")
# where a site sends a reader that is not signed in (a redirect there: "the site asked to sign in")
LOGIN = re.compile(r"(^|/)(login|log-in|logon|signin|sign-in|sso|saml2?|oauth2?|openid-connect|cas|adfs|idp)"
                   r"(/|\.|$)|j_security_check|dologin", re.I)


class DocError(Exception):
    pass


class _OutOfCalls(Exception):
    """A reader made as many API requests as it may: it keeps what it read."""


class _DocGone(Exception):
    """(0.11.8.2) The document was deleted while it was read: the reading stops there."""


WATCH_SECONDS = 10      # (0.11.8.2) how often a reading looks whether its document is still there


class _Watch:
    """(0.11.8.2) A reading's look at its document every WATCH_SECONDS: deleted while it is read (Documents and
    sites, Delete), the reading stops instead of reading every page for nothing and failing at the end."""

    def __init__(self, doc: Doc) -> None:
        self.doc_id, self.at = doc.id, time.monotonic()

    def check(self) -> None:
        if self.doc_id is None or time.monotonic() - self.at < WATCH_SECONDS:
            return
        self.at = time.monotonic()
        if _gone(self.doc_id):
            raise _DocGone()


def _gone(doc_id: int) -> bool:
    """(0.11.8.2) Whether a document's row is no more: a query of its id (the session's object never says it)."""
    try:
        return db.session.query(Doc.id).filter(Doc.id == doc_id).scalar() is None
    except Exception:  # pylint: disable=broad-except   (the database cannot say: read on)
        db.session.rollback()
        return False


REMOVED_WHY = "removed by a person from the document's pages (Read again in its list brings it back)"


# --------------------------------------------------------------------------------------------- #
# text of a page
# --------------------------------------------------------------------------------------------- #
LINK_SAID_CHARS = 300   # (0.10.7) the address of a link kept in the text when it is this long at most


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.links: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False
        self._anchor: tuple[str, int] | None = None      # (0.10.7) the full address of the link being read
        self._rows = 0                                  # (0.10.9) inside a table's row: the row stays one line
        self._cell_at: int | None = None                # where the cell being read starts (its text so far)
        self.metas: dict[str, str] = {}                 # (0.11.4) <meta> name (or property, itemprop) -> content

    def _in_cell_text(self) -> bool:
        return self._cell_at is not None and bool("".join(self.parts[self._cell_at:]).strip(" |"))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta":
            a = {k: v or "" for k, v in attrs}
            name = (a.get("property") or a.get("name") or a.get("itemprop") or a.get("http-equiv") or "").lower()
            if name and a.get("content"):
                self.metas.setdefault(name, a["content"])
        if tag in ("script", "style", "noscript", "svg", "nav", "footer"):
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
                if href.startswith(("http://", "https://")) and len(href) <= LINK_SAID_CHARS and not self._skip:
                    self._anchor = (href, len(self.parts))
        if tag == "tr":
            self._rows += 1
            self.parts.append("\n")
        elif self._rows and tag in BLOCK_TAGS and tag != "table":
            # (0.10.9) a cell's paragraphs, line breaks and list items (Confluence wraps a cell's text in <p>): its
            # values on the row's line, a new one after a comma (the cells' readers split values at commas)
            if tag in ("li", "br", "p", "div") and self._in_cell_text():
                self.parts.append(", ")
            else:
                self.parts.append(" ")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")
            if tag in HEADINGS and not self._skip:    # a heading stays one (0.9.6): the pieces are cut at sections
                self.parts.append("#" * int(tag[1]) + " ")
            elif tag == "li" and not self._skip:      # (0.10.4) an item of a list stays one: no sentence runs on
                self.parts.append("- ")               # from one item into the next
        if tag in ("td", "th"):
            self.parts.append(" | ")                  # the cells of a row stay apart
            self._cell_at = len(self.parts)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "svg", "nav", "footer") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "a" and self._anchor is not None:  # (0.10.7) a link's full address said after its text ("the
            href, at = self._anchor                    # dashboard (https://...)"): what the page points to stays
            self._anchor = None                        # in what is searched and read
            if href not in "".join(self.parts[at:]):
                self.parts.append(f" ({href})")
        if tag in ("td", "th"):
            self._cell_at = None
        if tag == "tr":
            self._rows = max(0, self._rows - 1)
            self.parts.append("\n")
        elif self._rows and tag in BLOCK_TAGS and tag != "table":
            self.parts.append(" ")
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip:
            if self._rows and ("\n" in data or "\r" in data):
                data = " ".join(data.split()) if data.strip() else " "   # (0.10.9) a row's source on several lines
            self.parts.append(data)


class _Storage(_Text):
    """Confluence's storage format: XHTML with its macros (ac:, ri:). A code macro's text (CDATA) is kept, the
    macros' parameters (language, colour, ...) are not. What the page refers to is kept too (0.10): the pages it links
    to (by title and space, `pages`), its images (`images`: their alternative text, title and file) and the diagrams
    its macros draw (`diagrams`: draw.io and Gliffy by their attachment's name, Mermaid and PlantUML by their source);
    a link with no text of its own reads as the page it names, an image as its alternative text."""

    BLOCKS = {"ac:structured-macro", "ac:plain-text-body", "ac:rich-text-body", "ac:task", "ac:layout-section",
              "ac:layout-cell"}
    DIAGRAMS = {"drawio": "draw.io", "drawio-sketch": "draw.io", "inc-drawio": "draw.io", "gliffy": "Gliffy",
                "plantuml": "PlantUML", "plantumlrender": "PlantUML", "mermaid": "Mermaid", "mermaid-macro": "Mermaid",
                "mermaid-cloud": "Mermaid"}

    def __init__(self) -> None:
        super().__init__()
        self.pages: list[tuple[str, str | None]] = []
        self.ids: list[str] = []                         # (0.10.7) pages linked by their id (ri:content-entity)
        self.images: list[dict[str, str]] = []
        self.diagrams: list[dict[str, str]] = []
        self._link: dict[str, Any] | None = None
        self._image: dict[str, str] | None = None
        self._macros: list[dict[str, Any]] = []
        self._param: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        if tag == "ac:structured-macro":
            self._macros.append({"name": a.get("ac:name", "").lower(), "params": {}, "body": []})
        if tag == "ac:parameter":
            self._param = a.get("ac:name", "")
            self._skip += 1
            return
        if tag == "ac:link":
            self._link = {"page": None, "text": False}
        elif tag == "ri:page" and self._link is not None and a.get("ri:content-title"):
            self._link["page"] = (a["ri:content-title"], a.get("ri:space-key") or None)
        elif tag in ("ac:plain-text-link-body", "ac:link-body") and self._link is not None:
            self._link["text"] = True
        elif tag == "ri:url" and self._link is not None and self._image is None and a.get("ri:value"):
            self._link["url"] = a["ri:value"]            # (0.10.7) a link by its full address
            self.links.append(a["ri:value"])
        elif tag == "ri:content-entity" and self._link is not None and str(a.get("ri:content-id") or "").isdigit():
            self._link["id"] = a["ri:content-id"]        # (0.10.7) a link by the page's id
        elif tag == "ac:image":
            self._image = {"alt": a.get("ac:alt", ""), "title": a.get("ac:title", ""), "file": ""}
        elif tag in ("ri:attachment", "ri:url") and self._image is not None:
            self._image["file"] = a.get("ri:filename") or a.get("ri:value") or ""
        if tag in self.BLOCKS:
            self.parts.append("\n")
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "ac:parameter":
            self._param = None
            self._skip = max(0, self._skip - 1)
            return
        if tag == "ac:link" and self._link is not None:
            if self._link["page"]:
                self.pages.append(self._link["page"])
                if not self._link["text"]:
                    self.parts.append(self._link["page"][0])     # the page's title is the link's text
            if self._link.get("id"):
                self.ids.append(self._link["id"])
            if self._link.get("url") and not self._skip:
                self.parts.append(f" ({self._link['url']})" if self._link["text"] else self._link["url"])
            self._link = None
        elif tag == "ac:image" and self._image is not None:
            img, self._image = self._image, None
            self.images.append(img)
            said = img["alt"] or img["title"]
            self.parts.append(f" [image {img['file']}: {said}] " if said else f" [image {img['file']}] ")
        elif tag == "ac:structured-macro" and self._macros:
            m = self._macros.pop()
            kind = self.DIAGRAMS.get(m["name"])
            if m["name"] == "code" and str(m["params"].get("language", "")).lower() in ("mermaid", "plantuml"):
                kind = "Mermaid" if m["params"]["language"].lower() == "mermaid" else "PlantUML"
            if kind:
                name = m["params"].get("diagramName") or m["params"].get("name") or m["params"].get("title") or ""
                self.diagrams.append({"kind": kind, "name": str(name), "source": "".join(m["body"])})
        if tag in self.BLOCKS:
            self.parts.append("\n")
        super().handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self._param is not None and self._macros:
            self._macros[-1]["params"][self._param] = self._macros[-1]["params"].get(self._param, "") + data
        super().handle_data(data)

    def _cdata(self, text: str) -> None:
        if self._macros and self._macros[-1]["name"] in ("code", "plantuml", "plantumlrender", "mermaid",
                                                         "mermaid-macro", "mermaid-cloud"):
            self._macros[-1]["body"].append(text)
        if not self._skip:
            self.parts.append(text)

    def unknown_decl(self, data: str) -> None:
        if data[:6].upper() == "CDATA[":
            self._cdata(data[6:])

    def handle_comment(self, data: str) -> None:      # a Python that reads CDATA as a comment outside SVG
        if data[:7].upper() == "[CDATA[":
            self._cdata(data[7:].rstrip("]"))


def _lines(parts: list[str]) -> str:
    lines = [" ".join(line.split()).replace(" , ", ", ") for line in "".join(parts).split("\n")]
    lines = [line[2:] if line.startswith("| ") else line for line in lines]
    return "\n".join(line for line in lines if line and line != "|")


def html_to_text(html: str) -> tuple[str, str, list[str]]:
    """(title, text, links) of an HTML page."""
    return _html_read(html)[:3]


# (0.11.4) the metas that say when a page was changed, the surest first; then the ones that say when it was written
DATED_METAS = ("article:modified_time", "og:updated_time", "datemodified", "dcterms.modified", "dc.date.modified",
               "last-modified", "modified", "article:published_time", "datepublished", "dcterms.created",
               "dc.date.created", "dc.date", "date")
JSON_LD = re.compile(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", re.S | re.I)


def _html_read(html: str) -> tuple[str, str, list[str], str | None]:
    """(title, text, links, the day it says it was changed or written) of an HTML page: (0.11.4) its dated meta, else
    the dateModified (or datePublished) of its structured data (JSON-LD); None when it says none."""
    p = _Text()
    p.feed(html or "")
    day = next((d for k in DATED_METAS if (d := day_of(p.metas.get(k)))), None)
    if day is None:
        for key in ("dateModified", "datePublished"):
            m = next((m for block in JSON_LD.findall(html or "")
                      if (m := re.search(r'"' + key + r'"\s*:\s*"([^"]{8,40})"', block))), None)
            if m and (day := day_of(m.group(1))):
                break
    return p.title.strip(), _lines(p.parts), p.links, day


def storage_to_text(xhtml: str) -> str:
    """The text of a Confluence page's body in the storage format (code macros and table cells kept)."""
    return read_storage(xhtml)["text"]


def read_storage(xhtml: str) -> dict[str, Any]:
    """A Confluence page's body in the storage format: its text, and what it refers to: the pages it links to
    ((title, space or None)), the addresses of its plain links, its images and its diagrams."""
    p = _Storage()
    p.feed(xhtml or "")
    p.close()
    return {"text": _lines(p.parts), "pages": list(dict.fromkeys(p.pages)), "links": list(dict.fromkeys(p.links)),
            "ids": list(dict.fromkeys(p.ids)), "images": p.images, "diagrams": p.diagrams}


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


def _same_site(a: str, b: str) -> bool:
    """(0.10.7) Two addresses of one site: the same host and port, the default ports of http and https taken as one (a
    link "http://wiki.example.com/..." written before the site moved to https, "https://wiki.example.com:443/...")."""
    oa, ob = origin(a), origin(b)
    if oa is None or ob is None or oa[1] != ob[1]:
        return False
    return oa[2] == ob[2] or (oa[2] in (80, 443) and ob[2] in (80, 443))


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


OPTIONS = ("verify_tls", "ca_bundle", "files", "excluded")   # kept in doc.auth with the sign-in (no secret among them)
EXCLUDED_KEPT = 20000          # (0.10.9.1) pages removed from a document by a person, kept at most (0.10.12: was 5,000)


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
    """What a repository gives: "docs" (its documentation and text files) or "code" (all its code too: the default
    since 0.10.12, a repository of scripts and libraries being read for what it does)."""
    f = str(_auth(doc).get("files") or "").strip().lower()
    return f if f in FILES else "code"


def page_key(p: dict[str, Any]) -> str:
    """(0.10.9.1) What names a page of a document for good: its wiki id, its path in a repository, else its address."""
    if p.get("id"):
        return f"id:{p['id']}"
    if p.get("path"):
        return f"path:{p['path']}"
    return f"url:{p.get('url') or ''}"


def excluded_pages(doc: Doc) -> list[dict[str, Any]]:
    """(0.10.9.1) The pages a person removed from the document: [{"key", "url", "title", "by", "at"}]."""
    return [e for e in _auth(doc).get("excluded") or [] if isinstance(e, dict) and e.get("key")]


def _excluded_elsewhere(doc: Doc) -> set[str]:
    """The addresses of the pages removed from the other documents: a page removed from the one that read it is not
    read by another one either (the pages a wiki's spaces share go to the document with the lowest id)."""
    out: set[str] = set()
    for other in db.session.query(Doc).filter(Doc.kind == "url"):
        if other.id != doc.id:
            out.update(str(e.get("url")) for e in excluded_pages(other) if e.get("url"))
    return out


def _without_excluded(doc: Doc, found: list) -> tuple[list, int]:
    """(0.10.9.1) The pages read, without the ones a person removed (this document's: by id, path or address; the
    other documents': by address); each said in the reading's log. Their links were followed: only the page goes.
    (0.11.8.2) A wiki page removed and read (removed before 0.11.8.2) keeps the pages it links to and its space in
    its removal: the next readings follow them without fetching it again (_read_confluence)."""
    entries = excluded_pages(doc)
    mine = {e["key"] for e in entries} | {f"url:{e['url']}" for e in entries if e.get("url")}
    elsewhere = _excluded_elsewhere(doc) if doc.kind == "url" else set()
    if not mine and not elsewhere:
        return found, 0
    by_key = {e["key"]: e for e in entries}
    kept, gone, noted = [], 0, {}
    for f in found:
        url, title, meta = f[0], f[1], (f[3] if len(f) > 3 and isinstance(f[3], dict) else {})
        keys = {page_key({**meta, "url": url}), f"url:{url}"}
        if keys & mine or (url and url in elsewhere):
            gone += 1
            _not_read(url, title, REMOVED_WHY)
            key = page_key({**meta, "url": url})
            if key in by_key and meta.get("id") and "links" not in by_key[key]:
                noted[key] = _removed_links(meta)
            continue
        kept.append(f)
    if noted:                                         # (new entries: the saved ones are never changed in place)
        doc.auth = {**_auth(doc), "excluded": [{**e, **noted[e["key"]]} if e["key"] in noted else e
                                               for e in entries]}
    return kept, gone


def _removed_links(page: dict[str, Any]) -> dict[str, Any]:
    """(0.11.8.2) What a removed wiki page leads to, kept with its removal: the pages it links to (ids, or
    "SPACE:Title") and its space (the pages under it are listed in it)."""
    return {"links": [str(x) for x in page.get("links") or []][:LINKS_KEPT],
            **({"space": str(page["space"])} if page.get("space") else {})}


LINKS_KEPT = 200        # (0.11.8.2) the links of a removed wiki page kept with its removal (as a page's own meta)


def exclude_page(doc: Doc, by: str, url: str = "", page_id: str = "", path: str = "") -> dict[str, Any]:
    """(0.10.9.1) A page removed from a document by a person: never read again (excluded_pages), its text taken out of
    the document's text now (the search's pieces follow), and what the understanding read from it deleted (its unit
    and its facts). What the map was proposed from it is withdrawn by the next learning, and a link approved from it
    only proposed for removal (never removed without a person)."""
    out = exclude_pages(doc, by, [{"url": url, "page_id": page_id, "path": path}])
    if not out["removed"]:
        raise ValueError("no such page in this document")
    first = out["removed"][0]
    return {"removed": first["key"], "title": first["title"], "pages": out["pages"], "units": out["units"],
            "facts": out["facts"]}


def exclude_pages(doc: Doc, by: str, refs: list[dict[str, Any]]) -> dict[str, Any]:
    """(0.10.11.1) Several pages removed at once ({"page_id"} or {"path"} or {"url"} each), as exclude_page removes
    one: the document's text rebuilt once, their units and facts deleted in one go. Pages not found are said."""
    from supagent.models import KFact, KUnit

    pages = [p for p in doc.pages or [] if isinstance(p, dict)]
    by_id = {str(p.get("id")): p for p in pages if p.get("id")}
    by_path = {p.get("path"): p for p in pages if p.get("path")}
    by_url = {p.get("url"): p for p in pages if p.get("url")}
    hits: list[dict[str, Any]] = []
    missing = []
    for r in refs:
        page_id, path, url = str(r.get("page_id") or ""), str(r.get("path") or ""), str(r.get("url") or "")
        hit = (by_id.get(page_id) if page_id else None) or (by_path.get(path) if path else None) or \
            (by_url.get(url) if url and not page_id and not path else None)
        if hit is None:
            missing.append(page_id or path or url)
        elif not any(h is hit for h in hits):
            hits.append(hit)
    if not hits:
        return {"removed": [], "missing": missing, "pages": len(pages), "units": 0, "facts": 0}
    now = dt.datetime.utcnow().isoformat(timespec="seconds")
    keys = [page_key(h) for h in hits]
    kept_ex = [e for e in excluded_pages(doc) if e["key"] not in set(keys)]
    kept_ex += [{"key": k, "url": str(h.get("url") or "")[:2000], "title": str(h.get("title") or "")[:300], "by": by,
                 "at": now, **(_removed_links(h) if h.get("id") else {})} for k, h in zip(keys, hits)]
    doc.auth = {**_auth(doc), "excluded": kept_ex[-EXCLUDED_KEPT:]}
    gone = {id(h) for h in hits}
    rest = [p for p in pages if id(p) not in gone]
    content = doc.content or ""
    if all(isinstance(p.get("at"), int) and isinstance(p.get("chars"), int) for p in pages):
        texts, placed, at = [], [], 0
        for p in rest:                                 # the document's text without them, each page's place again
            block = content[p["at"]:p["at"] + p["chars"]]
            if placed:
                at += 2
            placed.append({**p, "at": at})
            texts.append(block)
            at += len(block)
        doc.content, doc.pages = "\n\n".join(texts), placed
    else:                                              # (a reading before 0.10.7 said no place: its text goes at the next)
        doc.pages = rest
    doc.content_hash = hashlib.sha256((doc.content or "").encode()).hexdigest()[:40]
    ukeys = {str(h.get("path") or h.get("id") or h.get("url") or "")[:512] for h in hits} - {""}
    units = [i for (i,) in db.session.query(KUnit.id).filter(KUnit.doc_id == doc.id, KUnit.ukey.in_(ukeys or {"-"}))]
    facts = db.session.query(KFact).filter(KFact.unit_id.in_(units or [-1])).delete(synchronize_session=False)
    db.session.query(KUnit).filter(KUnit.id.in_(units or [-1])).delete(synchronize_session=False)
    return {"removed": [{"key": k, "title": h.get("title") or "", "url": h.get("url") or ""} for k, h in zip(keys, hits)],
            "missing": missing, "pages": len(doc.pages or []), "units": len(units), "facts": facts}


def include_page(doc: Doc, key: str) -> bool:
    """(0.10.9.1) A removed page given back: read again at the document's next reading."""
    before = excluded_pages(doc)
    after = [e for e in before if e["key"] != key]
    if len(after) == len(before):
        return False
    doc.auth = {**_auth(doc), "excluded": after}
    return True


def mask_secrets(text: str) -> tuple[str, int]:
    """A file's text with the secrets written in it masked (passwords, tokens, keys, a URL's password), and how many."""
    n = 0
    for rx, by in SECRETS:
        text, k = rx.subn(by, text)
        n += k
    changed = [0]

    def line_value(m: re.Match, inline: bool = False) -> str:
        out = _secret_value(m, inline)
        changed[0] += out != m.group(0)
        return out

    text = CONFIG_LINE.sub(line_value, text)                 # a secret's name given a value, however short
    text = INLINE_PAIR.sub(lambda m: line_value(m, True), text)
    text, k = _secret_maps(text)

    def prose(m: re.Match) -> str:
        out = _prose_secret(m)
        changed[0] += out != m.group(0)
        return out

    text = PROSE_SECRET.sub(prose, text)                     # (0.10) one written in a sentence, in any language
    return text, n + changed[0] + k


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


def _skip_title() -> Any:
    """(0.10.6.1) The titles of the pages not read (docs.skip_titles: "deprecated"), compiled; None: every page."""
    rx = str(settings.get("docs.skip_titles") or "").strip()
    if not rx:
        return None
    try:
        return re.compile(rx, re.I)
    except re.error:
        log.warning("supagent: docs.skip_titles is not a regular expression: every page is read")
        return None


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
    modified: str | None = None       # (0.11.4) its Last-Modified day, when older than the answer (_header_day)

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
            return _Answer(url, r.headers.get("Content-Type", ""), body, _header_day(r.headers))
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
    """(title, text, links) of one page, following redirects only to allowed addresses. (0.11.4) The day it says it
    was changed (a dated meta, else its Last-Modified header when older than the answer) given to the reading that
    asks for it (_PAGE_DAY)."""
    got = _get(url, sign, _limit())
    text = got.text()
    day = got.modified
    if "html" in got.ctype or text.lstrip()[:15].lower().startswith(("<!doctype html", "<html")):
        title, content, links, said = _html_read(text)
        out: tuple[str, str, list[str]] = (title, content, [urljoin(got.url, link) for link in links])
        day = said or day
    elif got.ctype and not got.ctype.startswith(("text/", "application/json", "application/xml")):
        raise DocError(f"{_where(got.url)}: {got.ctype} is not text (text, Markdown and HTML only)")
    else:
        out = ("", text, [])
    holder = _PAGE_DAY.get()
    if holder is not None and day:
        holder["modified"] = day
    return out


# --------------------------------------------------------------------------------------------- #
# the readers: each gives [(page address, page title, text)], the document's title if it has none, the pages
# skipped (too large, unreadable)
# --------------------------------------------------------------------------------------------- #
Pages = list[tuple[str, str, str]]


def _on_site(link: str, start: str) -> str:
    """(0.10.7) A link of the site written with the start's scheme and host (an "http://" link of an https site, its
    host in capitals, its default port): the sign-in goes with it, and one page is read once."""
    s, u = urlparse(start), urlparse(link)
    return urlunparse((s.scheme, s.netloc, u.path or "/", u.params, u.query, ""))


def _read_web(doc: Doc, sign: SignIn | None) -> tuple[Pages, str, int]:
    """A page, then the pages under the same address it links to, up to max_pages. (0.10.7) "Under the same address":
    the same site (http or https, its default port or none) and a path under the start's folder."""
    start = doc.url or ""
    folder = urlparse(start).path.rsplit("/", 1)[0] + "/"
    todo, seen, pages = [start], set(), []
    skipped, skip = 0, _skip_title()
    watch = _Watch(doc)                                 # (0.11.8.2) deleted while it is read: stopped
    while todo and len(pages) < _max_pages(doc):
        watch.check()
        url = todo.pop(0).split("#")[0]
        if url in seen:
            continue
        seen.add(url)
        dated: dict[str, str] = {}
        day_token = _PAGE_DAY.set(dated)               # (0.11.4) the day the page says it was changed
        try:
            title, text, links = fetch(url, sign) if sign is not None else fetch(url)
        except (DocError, requests.exceptions.RequestException) as ex:
            if len(seen) == 1:                         # the address itself: the document's error
                raise
            skipped += 1                               # (0.10.6.1) a page it links to that cannot be read (404,
            log.info("supagent: document %s: a page not read (%s): %s", doc.id, _where(url), str(ex)[:200])
            _not_read(_where(url), "", f"not read: {str(ex)[:150]}")
            continue                                   # 403, not text, too large): skipped, the others read
        finally:
            _PAGE_DAY.reset(day_token)
        if len(seen) > 1 and skip is not None and skip.search(title or ""):
            skipped += 1                               # (0.10.6.1) "deprecated" in its title: not read, nor what it
            _not_read(_where(url), title, "its title matches the setting docs.skip_titles")
            continue                                   # leads to (the first page always is)
        if (text or "").strip():
            pages.append((url, title, text, {"modified": dated["modified"]}) if dated.get("modified") else
                         (url, title, text))
        else:
            skipped += 1                               # (0.10.6.1) no text: not kept, its links followed
            _not_read(_where(url), title, "no text (its links followed)")
        todo += [_on_site(link, start) for link in links
                 if _same_site(link, start) and urlparse(link).path.startswith(folder)
                 and _on_site(link, start) not in seen]
    _left_unread(len({u.split("#")[0] for u in todo} - seen))
    return pages, (pages[0][1] if pages else "") or start, skipped


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


CONFLUENCE_HREF = [   # a link to a page of the same Confluence: (kind, pattern on the address's path)
    ("id", re.compile(r"/pages/viewpage\.action/?$")),
    ("id", re.compile(r"/spaces/[^/]+/pages/(?P<id>\d+)(?:/|$)")),
    ("title", re.compile(r"/display/(?P<space>[^/]+)/(?P<title>[^/?#]+)/?$")),
]
TINY_LINK = re.compile(r"^/x/(?P<code>[A-Za-z0-9_-]{1,11})/?$")    # (0.10.7) a short link, under the context path
DIAGRAM_ATTACHMENT = {"draw.io": (".drawio", ".xml", ""), "Gliffy": (".gliffy", ".json", "")}


def tiny_page_id(code: str) -> str | None:
    """(0.10.7) The page id a Confluence short link (…/x/AbCd) names: the id's 8 bytes, little-endian, in base64 with
    '/' and '+' written '-' and '_', its trailing zeros ("A") and padding left out. None: not such a code."""
    try:
        raw = code.replace("-", "/").replace("_", "+")
        n = int.from_bytes(base64.b64decode(raw + "A" * (11 - len(raw)) + "="), "little")
    except ValueError:                                # binascii.Error is a ValueError
        return None
    return str(n) if 0 < n < 2 ** 63 else None


def _href_target(href: str, page_url: str, web: str, bases: tuple[str, ...] = ()) -> tuple[str, ...] | None:
    """A plain link of a page that names another page of the same Confluence: ("id", id) or ("title", title, space).
    (0.10.7) The same Confluence also at the addresses its API gives as its base (`bases`: the site's own URL, when
    it is read through another name or address), over http or https, by a short link (…/x/AbCd) or by its title in
    viewpage.action?spaceKey=…&title=…"""
    url = urljoin(page_url, href or "")
    u = urlparse(url)
    ctx = next((urlparse(site).path.rstrip("/") for site in (web, *bases)
                if site and _same_site(url, site) and u.path.startswith(urlparse(site).path.rstrip("/"))), None)
    if ctx is None:
        return None
    m = TINY_LINK.match(u.path[len(ctx):])
    if m:
        pid = tiny_page_id(m.group("code"))
        return ("id", pid) if pid else None
    for kind, rx in CONFLUENCE_HREF:
        m = rx.search(u.path)
        if not m:
            continue
        if kind == "id":
            query = parse_qs(u.query)
            pid = m.groupdict().get("id") or (query.get("pageId") or [""])[0]
            if pid.isdigit():
                return ("id", pid)
            title, space = (query.get("title") or [""])[0], (query.get("spaceKey") or [""])[0]
            return ("title", title, space) if title and space else None
        return ("title", unquote_plus(m.group("title")), unquote(m.group("space")))
    return None


def _read_confluence(doc: Doc, sign: SignIn | None) -> tuple[Pages, str, int]:
    """A page and every page it leads to, or a space's pages and every page they lead to (0.10), through the REST API,
    breadth first, up to max_pages: the pages under a page and the pages its links name (by title, in its space or
    another one, and by their address on the same Confluence), down to the last one. Each page keeps the pages it links
    to, its images (their alternative text) and the diagrams it draws (draw.io and Gliffy read from their attachments,
    Mermaid and PlantUML from their source), their text added to the page's."""
    from supagent.knowledge import diagrams as G

    t = confluence_target(doc.url or "")
    if t is None:
        raise DocError(f"{_where(doc.url or '')}: not the address of a Confluence page or space (…/display/SPACE/Page, "
                       "…/spaces/SPACE/pages/ID/…, …/pages/viewpage.action?pageId=ID, …/display/SPACE)")
    want, limit = _max_pages(doc), _limit()
    calls = _Calls(want * 4 + 40)
    pages: list[tuple[str, str, str, dict[str, Any]]] = []
    skipped = 0
    q = lambda s: quote(str(s), safe="")  # noqa: E731
    expand = "expand=body.storage,version,space,ancestors"     # (0.11.4) its parents: its place in the tree

    def get(path: str) -> dict[str, Any]:
        calls.spend()
        return _json(t["api"] + path, sign, "Confluence")

    by_title: dict[tuple[str, str], str] = {}        # (space, title) -> id, of the pages met
    items: dict[str, tuple[dict[str, Any], str | None]] = {}
    # (0.11.8.2) the pages a person removed (by their id): never fetched again, the pages under them still listed and
    # read; a reading of a document deleted meanwhile stops (watch)
    removed = {str(e["key"])[3:]: e for e in excluded_pages(doc) if str(e["key"]).startswith("id:")}
    watch = _Watch(doc)

    def met(item: dict[str, Any], space: str = "") -> None:
        """(0.11.8.2) A page met (fetched, listed): its title in its space names it, so that a link by that title
        costs no request."""
        sp = str((item.get("space") or {}).get("key") or space or "")
        if sp and item.get("title") and item.get("id"):
            by_title.setdefault((sp, str(item["title"])), str(item["id"]))

    def fetch(key: tuple[str, ...]) -> str | None:
        """A page by its id or by its title and space: its id (its body kept in items), None when there is none."""
        if key[0] == "id":
            if key[1] not in items:
                item = get(f"/content/{q(key[1])}?{expand}")
                items[key[1]] = (item, (item.get("_links") or {}).get("base"))
                met(item)
            return key[1]
        title, space = key[1], key[2]
        if (space, title) in by_title:
            return fetch(("id", by_title[(space, title)]))   # (0.11.8.2) met by its id or listed: fetched by it
        data = get(f"/content?spaceKey={q(space)}&title={q(title)}&{expand}")
        results = [r for r in data.get("results") or [] if isinstance(r, dict) and r.get("id")]
        if not results:
            return None
        item = results[0]
        items[str(item["id"])] = (item, (data.get("_links") or {}).get("base"))
        by_title[(space, title)] = str(item["id"])
        return str(item["id"])

    def diagram_text(page_id: str, found: list[dict[str, str]]) -> tuple[str, list[list[str]]]:
        """The diagrams of a page as text and arrows (draw.io and Gliffy from the page's attachments)."""
        texts, edges = [], []
        files = None
        for d in found[:10]:
            got = None
            try:
                if d["kind"] in ("Mermaid", "PlantUML") and d.get("source"):
                    got = G.mermaid(d["source"], d["name"]) if d["kind"] == "Mermaid" else G.plantuml(d["source"], d["name"])
                elif d["kind"] in DIAGRAM_ATTACHMENT and d.get("name"):
                    if files is None:
                        listed = get(f"/content/{q(page_id)}/child/attachment?limit=100")
                        files = {str(r.get("title") or ""): r for r in listed.get("results") or [] if isinstance(r, dict)}
                    att = next((files[d["name"] + ext] for ext in DIAGRAM_ATTACHMENT[d["kind"]]
                                if d["name"] + ext in files), None)
                    href = str(((att or {}).get("_links") or {}).get("download") or "")
                    if href:
                        calls.spend()
                        raw = _get(urljoin(t["web"] + "/", href.lstrip("/")), sign, limit).text()
                        got = G.drawio(raw, d["name"]) if d["kind"] == "draw.io" else G.gliffy(raw, d["name"])
            except (ValueError, DocError, requests.exceptions.RequestException) as ex:
                log.info("supagent: document %s: the diagram %s of page %s not read: %s", doc.id, d.get("name"),
                         page_id, str(ex)[:200])      # (0.10.6.1) an attachment the sign-in may not see: the page kept
            if got and got["text"]:
                texts.append(got["text"])
                edges += got["edges"]
        return "\n".join(texts), edges

    queue: deque[tuple[str, ...]] = deque()
    seen: set[str] = set()
    bases: set[str] = set()                          # (0.10.7) the site's own URL as its API says it (_links.base)
    title = ""
    skip = _skip_title()
    listing = {"start": 0, "more": t["kind"] == "space", "listed": 0}
    own: deque[tuple[str, ...]] = deque()             # (0.11.0) the space's own pages, read before what they link to

    def list_more() -> None:
        """(0.11.0) The space's next batch of pages listed (with their text) once the last one is read: a space of
        50,000 pages is read batch by batch, never held whole (each page's text dropped once read)."""
        while listing["more"] and not own and listing["listed"] < want:
            data = get(f"/content?spaceKey={q(t['space'])}&type=page&{expand}&limit={CONFLUENCE_LIST}"
                       f"&start={listing['start']}")
            results = [r for r in data.get("results") or [] if isinstance(r, dict) and r.get("id")]
            base = (data.get("_links") or {}).get("base")
            for item in results:
                items[str(item["id"])] = (item, base)
                met(item, t["space"])
                own.append(("id", str(item["id"])))
            listing["listed"] += len(results)
            if len(results) < CONFLUENCE_LIST or not (data.get("_links") or {}).get("next"):
                listing["more"] = False
            listing["start"] += len(results)

    def list_children(pid: str, space: str) -> None:
        """The pages under a page (a space's are all listed), each named by its title in the page's space."""
        start = 0
        while t["kind"] != "space" and len(pages) + len(queue) < want:
            try:
                data = get(f"/content/{q(pid)}/child/page?limit={CHILDREN_LIST}&start={start}")
            except DocError as ex:                   # (0.10.6.1) its children not listed: the page and the rest kept
                log.info("supagent: document %s: the pages under Confluence page %s not listed: %s", doc.id, pid,
                         str(ex)[:200])
                break
            results = [r for r in data.get("results") or [] if isinstance(r, dict)]
            for r in results:
                met(r, space)                        # (0.11.8.2) a page under it is in its space
            queue.extend(("id", str(r["id"])) for r in results if r.get("id") and str(r["id"]) not in seen)
            if len(results) < CHILDREN_LIST or not (data.get("_links") or {}).get("next"):
                break
            start += len(results)

    try:
        if t["kind"] == "space":
            title = f"Confluence space {t['space']}"
            list_more()
        elif t["kind"] == "title":
            if fetch(("title", t["title"], t["space"])) is None:
                raise DocError(f"no page titled {t['title']!r} in the Confluence space {t['space']}")
            queue.append(("title", t["title"], t["space"]))
        else:
            queue.append(("id", str(t["id"])))
        while (own or queue or listing["more"]) and len(pages) < want:
            watch.check()
            if not own:
                list_more()
            if not own and not queue:
                break
            key = own.popleft() if own else queue.popleft()
            if key[0] == "title" and (key[2], key[1]) in by_title:
                key = ("id", by_title[(key[2], key[1])])     # (0.11.8.2) a page met: by its id, no request
            if key[0] == "id" and key[1] in removed and "links" in removed[key[1]]:   # (0.11.8.2) removed by a
                if key[1] not in seen:                 # person, its links kept with its removal: not fetched again;
                    seen.add(key[1])                   # the pages under it and the pages it links to still read
                    skipped += 1
                    gone = removed[key[1]]
                    _not_read(gone.get("url") or f"page {key[1]}", gone.get("title") or "", REMOVED_WHY)
                    list_children(key[1], str(gone.get("space") or ""))
                    queue.extend(k for k in (("id", x) if x.isdigit() else ("title", *reversed(x.split(":", 1)))
                                             for x in gone.get("links") or [] if x and (x.isdigit() or ":" in x))
                                 if not (k[0] == "id" and k[1] in seen))
                continue
            try:
                pid = fetch(key)
            except DocError as ex:                   # (0.10.6.1) a page under it or linked from it that this
                if not seen:                         # document's sign-in may not see (404, 403, a login page):
                    raise                            # skipped, the others read; the first page itself: the error
                skipped += 1
                log.info("supagent: document %s: a Confluence page not read (%s): %s", doc.id, key[1], str(ex)[:200])
                _not_read(f"page {key[1]}" if key[0] == "id" else f"{key[2]}: {key[1]}", "",
                          f"not read: {str(ex)[:150]}")
                continue
            if pid is None or pid in seen:
                continue
            seen.add(pid)
            item, base = items[pid]
            if base:
                bases.add(str(base))
            first = (t["kind"] == "page" and pid == str(t.get("id"))) or \
                (t["kind"] == "title" and pid == by_title.get((t["space"], t["title"])))
            if not first and skip is not None and skip.search(str(item.get("title") or "")):
                skipped += 1                           # (0.10.6.1) "deprecated" in its title: not read, nor the
                log.info("supagent: document %s: Confluence page %s not read (its title: %s)", doc.id, pid,
                         str(item.get("title") or "")[:120])
                _not_read(_confluence_url(item, base, t), str(item.get("title") or ""),
                          "its title matches the setting docs.skip_titles (nor the pages under it read)")
                continue                               # pages under it and its links
            space = str((item.get("space") or {}).get("key") or (key[2] if key[0] == "title" else t.get("space") or ""))
            url = _confluence_url(item, base, t)
            read = read_storage(((item.get("body") or {}).get("storage") or {}).get("value") or "")
            dtext, dedges = diagram_text(pid, read["diagrams"]) if read["diagrams"] else ("", [])
            text = read["text"] + (f"\n\n{dtext}" if dtext else "")
            linked: list[tuple[str, ...]] = [("title", ti, sp or space) for ti, sp in read["pages"]]
            linked += [("id", i) for i in read.get("ids") or []]
            linked += [x for x in (_href_target(h, url, t["web"], tuple(bases)) for h in read["links"]) if x]
            parents = [str(a["id"]) for a in item.get("ancestors") or [] if isinstance(a, dict) and a.get("id")]
            changed = day_of((item.get("version") or {}).get("when"))
            meta = {"id": pid, "space": space, "version": (item.get("version") or {}).get("number"),
                    "links": [x[1] if x[0] == "id" else f"{x[2]}:{x[1]}" for x in linked][:200],
                    # (0.11.4) when it was last changed (version.when), and its parents, the top first: the Context
                    # compares the pages' dates and gives every branch of the tree its room
                    **({"modified": changed} if changed else {}), "ancestors": parents[:ANCESTORS],
                    **({"diagram_edges": dedges[:200]} if dedges else {}),
                    **({"images": [{k: v for k, v in i.items() if v} for i in read["images"]][:50]} if read["images"]
                       else {})}
            items[pid] = ({k: item.get(k) for k in ("id", "title", "space", "version", "_links")}, base)   # (0.11.0)
            #                                            its text no longer held (the page's id kept: not fetched again)
            if len(text.encode()) > limit or not text.strip():
                skipped += 1                           # too large, or no text (0.10.6.1: its pages and links followed)
                _not_read(url, str(item.get("title") or ""), "no text (the pages under it and its links followed)"
                          if not text.strip() else f"larger than docs.max_kb ({limit // 1024} KB)")
            else:
                pages.append((url, str(item.get("title") or f"page {pid}"), text, meta))
            title = title or str(item.get("title") or "")
            list_children(pid, space)                  # the pages under it, then its links
            queue.extend(x for x in linked if not (x[0] == "id" and x[1] in seen))
    except _OutOfCalls:
        log.info("supagent: document %s: Confluence requests used up, %d page(s) read", doc.id, len(pages))
        _not_read("", "", "the reading's requests were used up: the pages left in its queue were not read")
    _left_unread(len({k for k in queue if not (k[0] == "id" and k[1] in seen)}))
    for i, (url, ti, text, meta) in enumerate(pages):      # the links by title as the ids they turned out to be
        meta["links"] = list(dict.fromkeys(by_title.get(tuple(x.split(":", 1)), x) if ":" in x and not x.isdigit()
                                           else x for x in meta["links"]))
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


SAMPLE_SUFFIX = re.compile(r"\.(sample|example|dist|default)$", re.I)


def sample_base(path: str) -> str:
    """(0.10.1) A file given as a sample to copy (site.yml.sample, all.yml.example, hosts.dist): the path it stands
    for."""
    base = SAMPLE_SUFFIX.sub("", path or "")
    return base if "." in base.rsplit("/", 1)[-1] else path


def is_text_file(path: str) -> bool:
    name = sample_base(path).rsplit("/", 1)[-1].lower()
    return name.endswith(TEXT_FILES) or (name.startswith("readme") and "." not in name) or bool(ANSIBLE_FILE.search(path))


def wanted_file(path: str, files: str = "docs") -> bool:
    """A repository's file to read: a text file (and with files "code", a source or build file, or a file without an
    extension that may be a script: maybe_script), never a file that holds keys, nor one under node_modules, vendor,
    dist... (a build folder: its scripts only), nor a minified or lock file."""
    low = path.lower()
    parts = low.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]) or KEY_FILE.search(low) or SKIP_FILE.search(low):
        return False
    name = sample_base(parts[-1])
    if any(p in BUILD_DIRS for p in parts[:-1]):        # (0.10.12) build/deploy.sh: read; what a build left: not
        return files == "code" and name.endswith(SCRIPT_FILES)
    if is_text_file(path):
        return True
    script = "." not in name and len(parts) >= 2 and parts[-2] in SCRIPT_DIRS and not name.startswith(("license",
                                                                                                    "copying")) and \
        not SECRET_NAME.search(name)
    return files == "code" and (name.endswith(CODE_FILES) or name in CODE_NAMES or bool(ROLE_FILE.search(path)) or
                                script or maybe_script(path))   # (0.10.10) bin/backup, scripts/rotate


def maybe_script(path: str) -> bool:
    """(0.10.12) A file without an extension outside bin/ and scripts/ (ops/backup, deploy/run): read, and kept only
    when its first line is #! (shebang_kept)."""
    low = path.lower()
    parts = low.split("/")
    name = parts[-1]
    return ("." not in name and not (len(parts) >= 2 and parts[-2] in SCRIPT_DIRS) and name not in CODE_NAMES
            and not NOT_SCRIPT_NAME.match(name) and not SECRET_NAME.search(name) and not ANSIBLE_FILE.search(path)
            and not ROLE_DIR.search(low) and not TRUST_NAME.search(name) and not is_text_file(path))


def shebang_kept(path: str, text: str) -> bool:
    """A file read as maybe a script: kept when it is one (#! on its first line)."""
    return not maybe_script(path) or text.lstrip("\ufeff").startswith("#!")


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
FRONT_KEY = re.compile(r"^(title|description|summary)[ \t]*:[ \t]*(.+)$", re.M | re.I)   # (its value stripped after)
FIRST_HEADING = re.compile(r"^#[ \t]+(.+)$", re.M)    # (its closing #s taken off after: no backtracking)


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
        title = meta.get("title") or (h.group(1).rstrip(" \t").rstrip("#").strip() if h else "")
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
    one = bool(t["path"] and wanted_file(t["path"], "code") and not maybe_script(t["path"]) and   # (a folder's
               (t["cloud"] is False or t["ref"]))                                              # name: no file)
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
    watch = _Watch(doc)                                 # (0.11.8.2) deleted while it is read: stopped
    if touched is not None:                             # only the files that changed are read again
        prefix = t["path"] + "/" if t["path"] else ""
        keep = {p: v for p, v in before.items() if p not in touched}
        todo = sorted((p for p in touched if p.startswith(prefix) and wanted_file(p, files)), key=doc_rank)
        pages = [(u, ti, tx, meta(p)) for p, (u, ti, tx, _m) in keep.items()]
        for path in todo:
            watch.check()
            if len(pages) >= want:
                break
            f = _file_at(t, path, head)
            try:
                text, n = _read_file(f, sign, limit, calls)
            except _OutOfCalls:
                return _with_rest(pages, before, touched, meta), title, skipped   # the rest kept as it was
            except (DocError, requests.exceptions.RequestException) as ex:
                if isinstance(ex, DocError) and "asked to sign in" in str(ex):
                    raise
                if isinstance(ex, DocError) and "HTTP 404" in str(ex):   # 404: deleted (or moved away) at that commit
                    continue
                skipped, last = skipped + 1, (str(ex) if isinstance(ex, DocError) else f"{path}: {type(ex).__name__}")
                if _transient(ex) and path in before:   # (0.11.0) refused for now (429, 5xx, a timeout): the version
                    pages.append(before[path])          # read before, with its own commit: read again next time
                continue
            if not shebang_kept(path, text):           # (0.10.12) a file without an extension that is no script
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
    if not chosen and files == "docs":               # (0.10.12) a repository of scripts and libraries, no documentation:
        chosen = sorted((f for f in found if wanted_file(f["path"], "code")), key=lambda f: doc_rank(f["path"]))
        if chosen:                                   # its code read (it was "no text file", the repository unread)
            files = "code"
            scope = f"{t['path']}|{t.get('ref') or t.get('at') or ''}|{files}|{want}"
            log.info("supagent: document %s: %s has no documentation file: its code read", doc.id, t["name"])
    if not chosen:
        kinds = "text or code" if files == "code" else "text (Markdown, text, HTML, YAML, JSON, CSV, SQL...)"
        raise DocError(f"{t['name']}: no {kinds} file{where}")
    pages, partial = [], False
    for f in chosen:
        watch.check()
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
        except (DocError, requests.exceptions.RequestException) as ex:
            if isinstance(ex, DocError) and "asked to sign in" in str(ex):
                raise
            skipped, last = skipped + 1, (str(ex) if isinstance(ex, DocError) else f"{f['path']}: {type(ex).__name__}")
            if _transient(ex):                        # (0.11.0) refused for now: no commit kept (read in full next
                partial = True                        # time), the version read before kept meanwhile
                if f["path"] in before:
                    pages.append(before[f["path"]])
            continue
        if not shebang_kept(f["path"], text):         # (0.10.12) a file without an extension that is no script
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


def _transient(ex: Exception) -> bool:
    """(0.11.0) A file the server refused for now (too many requests, its own error, a timeout or a cut connection):
    read again next time, not taken for gone."""
    if isinstance(ex, requests.exceptions.RequestException):
        return True
    return bool(re.search(r"HTTP (429|5\d\d)\b", str(ex)))


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
        title = (title or "").replace("\x00", "")        # (0.11.0) a NUL (a UTF-16 or binary file): PostgreSQL
        block = (f"# {title}\n" if title else "") + (text or "").replace("\x00", "")   # refuses it in a text
        if texts:
            at += 2                                     # the blank line between two pages
        pages.append({"url": url, "title": title, "chars": len(block), "at": at,
                      **{k: v for k, v in (more[0] if more and isinstance(more[0], dict) else {}).items()
                         if k in ("path", "commit", "scope", "id", "space", "version", "links", "diagram_edges",
                                  "images", "modified", "ancestors")}})       # (0.11.4) its date, its parents
        texts.append(block)
        at += len(block)
    return "\n\n".join(texts), pages


def _read_by_another(doc: Doc, reader: str, found: list) -> tuple[list, int]:
    """(0.10.1) The pages of a wiki or a site that another document already reads are left to it: a wiki read to the
    last page its links lead to, given as several documents (one per space) whose pages link to each other, had every
    page read, cut, embedded and understood once per document. A page is the document's with the lowest id that
    reaches it (each refresh, so that a document removed or disabled gives its pages to the next one); a document all
    of whose pages another reads keeps its own address. A repository's files are never shared."""
    if reader not in ("confluence", "web") or doc.id is None:
        return found, 0
    held: set[str] = set()
    for other in db.session.query(Doc).filter(Doc.enabled.is_(True), Doc.kind == "url", Doc.id < doc.id):
        if reader_of(other) not in ("confluence", "web"):
            continue
        held.update(str(p["url"]) for p in other.pages or [] if isinstance(p, dict) and p.get("url"))
    kept = [f for f in found if not (f[0] and f[0] in held)]
    if found and not kept:
        kept = found[:1]
    for f in found:
        if f not in kept:
            _not_read(f[0], f[1], "read by another document of the same site (the first one added)")
    return kept, len(found) - len(kept)


READING = "reading"          # (0.11.0) a document's status while one process reads it (the others leave it)
READING_HOURS = 6           # a "reading" older than this: its process died; read again


def refresh(doc: Doc) -> dict[str, Any]:
    """Read a document's address again with its reader (and its sign-in, if it has one). (0.11.0) Claimed first
    (status "reading", committed): the hourly tick and a person's Read again never read it twice at once."""
    reader = reader_of(doc)
    skipped, changed, shared = 0, False, 0
    token = None
    got: dict[str, Any] = {"skipped": [], "not_read": 0, "left": 0}
    doc_id = doc.id
    if doc.id is not None and doc in db.session:       # (a document of this session: claimed, saved now)
        doc.status, doc.fetched_at = READING, dt.datetime.utcnow()
        db.session.commit()
    log_token = _READ_LOG.set(got)                   # (0.10.7) what the reading leaves out, said on the page
    found: list = []
    try:
        sign = sign_in(doc)
        token = _VERIFY.set(tls_of(doc))            # the site's certificate: checked, with a CA file, or not
        read = {"web": _read_web, "confluence": _read_confluence, "bitbucket": _read_bitbucket}[reader]
        found, title, skipped = read(doc, sign)
        got["read"] = len(found)
        if doc.id is not None and doc in db.session:   # (0.11.0) the pages a person removed while it was read
            db.session.expire(doc, ["auth"])
        found, removed = _without_excluded(doc, found)   # (0.10.9.1) the pages a person removed: not kept
        skipped += removed
        found = [(u, ti, mask_secrets(tx)[0], *more) for u, ti, tx, *more in found]   # every page's secrets (0.10)
        found, shared = _read_by_another(doc, reader, found)
        content, pages = _join(found)
        h = hashlib.sha256(content.encode()).hexdigest()[:40]
        changed = h != doc.content_hash
        doc.content, doc.pages, doc.content_hash = content, pages, h
        doc.title = doc.title or title or doc.url
        doc.status, doc.error = "ok", None
    except Exception as ex:  # pylint: disable=broad-except   (any failure is the document's error, said safely)
        if type(ex).__name__ in ("SoftTimeLimitExceeded", "TimeLimitExceeded"):   # (0.11.0) the worker's time ran
            db.session.rollback()                      # out: not the document's fault; read again at the next tick
            _unclaim(doc)
            raise
        if isinstance(ex, _DocGone) or type(ex).__name__ in ("ObjectDeletedError", "StaleDataError"):
            db.session.rollback()                      # (0.11.8.2) deleted while it was read: nothing to save
            if doc_id is not None and _gone(doc_id):
                log.info("supagent: document %s deleted while it was read: its reading stopped", doc_id)
                return _deleted(doc_id, reader, skipped)
        said = str(ex) if isinstance(ex, DocError) else f"{type(ex).__name__}: {ex}"
        doc.status, doc.error = "error", scrub(said, doc)[:500]
        log.info("supagent: document %s (%s) not read: %s", doc.id, reader, doc.error)
    finally:
        if token is not None:
            _VERIFY.reset(token)
        _READ_LOG.reset(log_token)
    try:
        doc.fetched_at = dt.datetime.utcnow()
        _keep_read_log(doc, reader, got)
        db.session.commit()
    except Exception as ex:  # pylint: disable=broad-except   (0.11.0) what was read cannot be saved: said, not retried
        db.session.rollback()                          # every hour (the tick goes on with the other documents)
        if doc_id is not None and _gone(doc_id):       # (0.11.8.2) deleted at the end of its reading: nothing to save
            log.info("supagent: document %s deleted while it was read: what was read is not kept", doc_id)
            return _deleted(doc_id, reader, skipped)
        log.warning("supagent: document %s read but not saved: %s", doc_id, ex)
        d = db.session.get(Doc, doc_id) if doc_id is not None else None
        if d is not None:
            d.status, d.error, d.fetched_at = "error", f"read but not saved: {type(ex).__name__}: {str(ex)[:300]}", \
                dt.datetime.utcnow()
            db.session.commit()
            doc = d
    return {"id": doc.id, "status": doc.status, "reader": reader, "pages": len(doc.pages or []), "skipped": skipped,
            "changed": changed, "error": doc.error, **({"read_by_another": shared} if shared else {})}


def _deleted(doc_id: int, reader: str, skipped: int) -> dict[str, Any]:
    """(0.11.8.2) What a reading says of a document deleted while it was read."""
    return {"id": doc_id, "status": "deleted", "reader": reader, "pages": 0, "skipped": skipped, "changed": False,
            "error": None}


def _unclaim(doc: Doc) -> None:
    """(0.11.0) A read stopped by its worker's time: the document due again (its claim taken back)."""
    try:
        d = db.session.get(Doc, doc.id) if doc.id is not None else None
        if d is not None and d.status == READING:
            d.status, d.fetched_at = "error", None
            d.error = "the reading took longer than the worker allows: read again at the next hourly tick"
            db.session.commit()
    except Exception:  # pylint: disable=broad-except
        db.session.rollback()


def _keep_read_log(doc: Doc, reader: str, got: dict[str, Any]) -> None:
    """(0.10.7) The reading's log kept for the list of the document's pages (supagent_meta, one row per document)."""
    from supagent.models import Meta

    if doc.id is None:
        return
    want = _max_pages(doc)
    value = json.dumps({"at": doc.fetched_at.isoformat() if doc.fetched_at else None, "reader": reader,
                        "status": doc.status, "read": int(got.get("read") or 0), "max_pages": want,
                        "limit_reached": int(got.get("read") or 0) >= want and reader != "bitbucket",
                        "left": int(got.get("left") or 0), "not_read": int(got.get("not_read") or 0),
                        "skipped": got.get("skipped") or []})
    key = READ_LOG_KEY.format(doc.id)
    row = db.session.get(Meta, key)
    if row is None:
        db.session.add(Meta(key=key, value=value))
    else:
        row.value = value


def due_docs() -> list[Doc]:
    now = dt.datetime.utcnow()
    out = []
    for d in db.session.query(Doc).filter(Doc.kind == "url", Doc.enabled.is_(True)):
        if d.status == READING and d.fetched_at is not None and now - d.fetched_at < dt.timedelta(hours=READING_HOURS):
            continue                                    # (0.11.0) another process reads it now
        if d.fetched_at is None or d.status == READING or \
                now - d.fetched_at > dt.timedelta(days=max(1, d.refresh_days or 7)):
            out.append(d)
    return out


def refresh_due() -> list[dict[str, Any]]:
    """The documents due, each read on its own: (0.11.0) one that fails never stops the others nor the tick."""
    out = []
    for d in due_docs():
        try:
            out.append(refresh(d))
        except Exception as ex:  # pylint: disable=broad-except
            if type(ex).__name__ in ("SoftTimeLimitExceeded", "TimeLimitExceeded"):
                raise
            db.session.rollback()
            log.warning("supagent: document %s: its reading failed: %s", getattr(d, "id", "?"), ex)
    return out
