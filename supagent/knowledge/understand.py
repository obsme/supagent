"""What the team's documents and code say about the system, read without an LLM (0.10).

Every page of a wiki or a site, every file of a repository, every uploaded document is a unit (KUnit). A unit is read
for what it states (KFact), each fact with the line that says it and where it comes from:

  code      an HTTP client calling an address (that service), a database URL and the statements run on it (reads,
            writes), a cache, a log appender or an OpenTelemetry exporter (where the logs and traces go), a metric
            registered (prometheus_client, Micrometer, Go, OpenTelemetry meters: the name the backend shows)
  config    the same in configuration (YAML, JSON, properties, ini, XML, a Kubernetes manifest's environment, a
            systemd unit), a log shipper's output (Fluent Bit, Logstash, the OpenTelemetry Collector, Jaeger,
            Alertmanager: the indices they write, read from their configuration's shape), Prometheus' scrape jobs
            (what runs where, which exporter watches it)
  diagram   the arrows of a draw.io, Gliffy, Mermaid or PlantUML diagram
  doc, wiki a sentence that names two parts and how they interact ("checkout calls payment", "runs on db-01"), where
            a part's logs are, which metric counts what

Who states it (the subject) is the part the unit belongs to: the workload a manifest declares, the tool a
configuration is the shape of, else the repository's own service (its workload, its telemetry or artifact name, its
systemd unit); a wiki page about a part (its title names it) speaks for that part. The names are resolved against what
the agent knows: the System map's parts, the data's indices, metrics and the values of their identity fields (services,
hosts, jobs), and what the documents declare; the other names of a part (an OpenTelemetry service name, an artifact's
name) are kept as its aliases. Facts are read again only from the units whose text changed (and from all of them when
the names known changed). Nothing here knows a particular system: the rules are those of common tools and conventions.
"""

from __future__ import annotations

import ast
import bisect
import datetime as dt
import hashlib
import json
import logging
import re
from collections import defaultdict
from typing import Any, Iterator

from superset import db

log = logging.getLogger(__name__)

QUOTE = 300                     # characters of the line kept with a fact
MAX_FACTS = 400                 # facts of one unit at most
LANGS = {".py": "python", ".pyi": "python", ".java": "java", ".kt": "kotlin", ".kts": "kotlin", ".scala": "scala",
         ".groovy": "groovy", ".gradle": "groovy", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
         ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".go": "go", ".rs": "rust", ".cs": "csharp",
         ".rb": "ruby", ".php": "php", ".sh": "shell", ".bash": "shell", ".ps1": "powershell", ".yaml": "yaml",
         ".yml": "yaml", ".json": "json", ".xml": "xml", ".properties": "properties", ".ini": "ini", ".cfg": "ini",
         ".conf": "conf", ".toml": "toml", ".md": "markdown", ".markdown": "markdown", ".rst": "text", ".txt": "text",
         ".sql": "sql", ".service": "systemd", ".timer": "systemd", ".tf": "terraform", ".hcl": "terraform",
         ".html": "html", ".htm": "html", ".inc": "php", ".env": "dotenv"}     # (0.10.5) x.env.j2, .env.example
NAMED_LANGS = {"dockerfile": "dockerfile", "containerfile": "dockerfile", "makefile": "make", "jenkinsfile": "groovy"}
WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "CronJob", "Job", "Rollout", "DeploymentConfig"}
# well-known tools, recognised by the shape of their configuration (not by a name)
TOOLS = [
    ("fluent-bit", re.compile(r"^\s*\[(?:INPUT|OUTPUT)\]", re.M | re.I)),
    ("logstash", re.compile(r"^\s*input\s*\{[\s\S]*^\s*output\s*\{", re.M)),
    ("otel-collector", re.compile(r"^receivers:\s*$[\s\S]*^exporters:\s*$[\s\S]*^service:\s*$", re.M)),
    ("promtail", re.compile(r"^positions:\s*$|/loki/api/v1/push", re.M)),   # (0.10.6) its scrape_configs are the
    ("prometheus", re.compile(r"^scrape_configs:\s*$", re.M)),               # logs it ships, nothing it monitors
    ("alertmanager", re.compile(r"^route:\s*$[\s\S]*^receivers:\s*$", re.M)),
    ("jaeger", re.compile(r"index-prefix:|span-storage|jaeger", re.I)),
    ("filebeat", re.compile(r"^filebeat\.inputs:", re.M)),
    ("vector", re.compile(r"^\[sinks\.|^sinks:\s*$", re.M)),
]
SHIPPERS = {"fluent-bit", "logstash", "otel-collector", "jaeger", "filebeat", "vector", "alertmanager", "promtail"}
SCRAPERS = {"prometheus", "victoriametrics", "vmagent", "zabbix", "nagios", "icinga", "telegraf"}   # (0.10.6) what an
DASHBOARDS = {"grafana", "kibana", "superset", "metabase"}                    # arrow with no word from them means
ALERT_ROUTERS = {"alertmanager"}
# the metrics a well-known exporter or a scrape job's kind gives (their prefix): what a job watches on its target
EXPORTERS = {"node": ("node_",), "node-exporter": ("node_",), "kube-state-metrics": ("kube_",),
             "cadvisor": ("container_",), "kubelet": ("container_", "kubelet_"), "postgres": ("pg_",),
             "postgresql": ("pg_",), "postgres-exporter": ("pg_",), "redis": ("redis_",), "redis-exporter": ("redis_",),
             "mysql": ("mysql_",), "mysqld": ("mysql_",), "mongodb": ("mongodb_",), "blackbox": ("probe_",),
             "snmp": ("if",), "kafka": ("kafka_",), "rabbitmq": ("rabbitmq_",), "elasticsearch": ("elasticsearch_",),
             "opensearch": ("opensearch_",), "nginx": ("nginx_",), "haproxy": ("haproxy_",)}
INFRA_PREFIXES = ("node_", "kube_", "container_", "kubelet_", "pg_", "redis_", "mysql_", "mongodb_", "probe_", "if",
                  "kafka_", "rabbitmq_", "elasticsearch_", "opensearch_", "nginx_", "haproxy_", "up")

URL = re.compile(r"\b((?:https?|grpcs?|tcp|wss?|postgres(?:ql)?|mysql|mariadb|sqlserver|oracle|mongodb(?:\+srv)?|redis|"
                 r"rediss|amqps?|kafka|nats|jdbc:[a-z0-9]+(?::[a-z]+)?)://[^\s\"'`<>)\]},;]+)", re.I)
# (0.10.5) a template as an address's password ("postgresql://app:{{ db_password }}@db-01", "${PW}", "%(pw)s"):
# masked (same length) so that the address reads whole
USERINFO_TPL = re.compile(r"(://[^\s/@:'\"]*:)(\{\{.*?\}\}|\$\{[^}\s]*\}|%\([^)\s]*\)s|<[^>@\s]*>)(?=@)")
UPSTREAM_SUFFIX = re.compile(r"(?i)[_.-](backends?|upstreams?|servers|pool|cluster|svc)$")
HOSTPORT = re.compile(r"(?<![\w./@:-])([a-zA-Z][a-zA-Z0-9-]*(?:\.[a-zA-Z0-9-]+)*):(\d{2,5})(?![\w.])")
ENDPOINT_KEY = re.compile(r"(url|uri|endpoint|host|hosts|server|servers|destination|target|targets|upstream|address|"
                          r"addr|dsn|broker|brokers|bootstrap)", re.I)
DB_SCHEMES = ("postgres", "postgresql", "mysql", "mariadb", "sqlserver", "oracle", "mongodb", "jdbc")
DB_PORTS = {5432, 3306, 1433, 1521, 27017, 5433, 26257}
CACHE_PORTS = {6379, 11211}
LOG_PORTS = {5044: "beats", 24224: "fluent", 4317: "otlp", 4318: "otlp", 514: "syslog", 12201: "gelf"}
LOG_WORDS = re.compile(r"logstash|beats|fluent|syslog|gelf|otlp|otel|collector|appender|logging", re.I)
HTTP_CALL = re.compile(r"\b(?:requests|httpx|session|client|http|aiohttp|urllib\w*|axios|fetch|restTemplate|webClient|"
                       r"HttpClient|HttpRequest|OkHttp\w*|Feign\w*)\b[\w.]*\s*\.?\s*(?:get|post|put|patch|delete|request|"
                       r"send|exchange|newBuilder|fetch|call)\b|\bfetch\s*\(|URI\.create\s*\(", re.I)
WRITES_SQL = re.compile(r"\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|MERGE\s+INTO|UPSERT)\b", re.I)
READS_SQL = re.compile(r"\bSELECT\b[\s\S]{1,200}?\bFROM\b", re.I)
GENERIC_LABELS = {"api", "www", "app", "apps", "svc", "service", "services", "web", "srv", "internal", "int", "prod",
                  "local", "localhost", "default", "cluster", "com", "net", "org", "io", "example"}
PUBLIC_SUFFIXES = {"com", "org", "net", "io", "co", "dev", "app", "ai", "cloud", "info", "biz", "eu", "us", "uk", "de",
                   "fr", "es", "it", "nl", "be", "ch", "at", "se", "no", "dk", "fi", "pl", "cz", "pt", "ie", "ru", "jp",
                   "cn", "in", "br", "ca", "au", "nz", "me", "tv", "xyz", "tech", "online", "site", "edu", "gov"}
PACKAGE_FILES = re.compile(r"(^|[/_])(composer\.(json|lock)|package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|pom\.xml|"
                           r"build\.gradle(\.kts)?|requirements[\w.-]*\.txt|Pipfile(\.lock)?|poetry\.lock|Gemfile(\.lock)?|"
                           r"go\.(mod|sum)|Cargo\.(toml|lock)|[\w.-]+\.csproj|packages\.config|setup\.(py|cfg)|"
                           r"pyproject\.toml|bower\.json|\.gitmodules)$", re.I)   # (0.10.4) where code comes from, not
#                                                                                     what it calls when it runs
NOT_ENDPOINT = re.compile(r"/licen[cs]es?\b|//(www\.)?(opensource|creativecommons|gnu|spdx|w3|schema|json-schema|"
                          r"apache)\.org\b|\.(dtd|xsd)\b|//[^/\s]+/(docs?|documentation|manual|wiki|help|blog|books|"
                          r"guides?|tutorials?|fwlink|terms|privacy|policies)\b", re.I)   # (0.10.4) a license, a schema, a
#                                                                                       page to read: no endpoint
FETCH_LINE = re.compile(r"(?i)\b(curl|wget|git\s+clone|pip3?\s+install|npm\s+(?:i|install)|go\s+(?:get|install)|"
                        r"apt(?:-get)?\s+install|apk\s+add|brew\s+install|LABEL|org\.opencontainers|ADD\s+https?:)\b")
EXTERNAL_KEY = re.compile(r"(?i)(api|endpoint|gateway|webhook|hook|server|host|broker|dsn|uri|url|upstream|backend|"
                          r"proxy_pass|target|remote_write|push)[\w.\[\]'\"-]*\s*(?:=>|[:=(,])?\s*[\"'(]?\s*$|"
                          r"\b(?:URL|Url)\s*\"?\s*$|proxy_pass\s+$")
SEE_ALSO = re.compile(r"(?i)\b(see|cf\.|documentation|details|more info|read more|reference|refer to|example|"
                      r"license|copyright|homepage|website|author)\b[^.:=]{0,30}[:\s]*$")   # "See http://...": a reference
ENV_DEFAULT = re.compile(r"(?:os\.environ\.get|os\.getenv|getenv|System\.getenv|process\.env\.?|ENV\[|env::var)\s*"
                         r"\(?\s*[\"']?([A-Z][A-Z0-9_]*?_(?:HOST|HOSTNAME|ADDR|ADDRESS|SERVICE_HOST|ENDPOINT|URL))\b")
STORE_WORDS = re.compile(r"(?i)(^|_)(DB|DATABASE|MONGO|MYSQL|POSTGRES|PG|REDIS|CACHE|SQL|MARIADB)(_|$)")
PLACEHOLDER_HOST = re.compile(r"^\$\{?([A-Za-z][A-Za-z0-9_]*?)_(?:HOST|HOSTNAME|ADDR|ADDRESS|SERVICE_HOST|ENDPOINT|URL)\}?$|"
                              r"^\{\{\s*([a-z][a-z0-9_]*?)_(?:host|hostname|addr|address|endpoint|url)\s*\}\}$", re.I)
DOC_HOSTS = re.compile(r"^(?!api\.)(?:(docs?|wiki|help|support|blog|kb|bugs|issues)\.|(.*\.)?(readthedocs\.io|github\.com|github\.io|githubusercontent\.com|"
                       r"launchpad\.net|sourceforge\.net|googlecode\.com|"
                       r"gitlab\.com|bitbucket\.org|opendev\.org|stackoverflow\.com|pypi\.org|npmjs\.(com|org)|"
                       r"docker\.(com|io)|quay\.io|apache\.org|python\.org|w3\.org|schema\.org|"
                       r"wikipedia\.org|golang\.org|go\.dev|maven\.org|spring\.io)$)")   # (an API's host is a call: api.github.com)
ACTORS = {"customers", "customer", "users", "user", "clients", "client", "browser", "browsers", "internet", "visitors",
          "people", "operators", "admins"}
GENERIC_BOXES = {"services", "service", "apps", "applications", "microservices", "backends", "backend-services",
                 "databases", "servers", "workers", "nodes", "hosts", "components", "systems", "other-services",
                 "all-services", "upstream-services", "downstream-services"}   # (0.10.5) a diagram's box for many
PLATFORMS = re.compile(r"(?i)^(kubernetes|k8s|openshift|eks|aks|gke|aws|azure|gcp|the\s+cloud|cloud|docker|containers?|"
                       r"bare[ -]metal)(\s*\(.*\))?\s*$")     # the whole value: "Kubernetes (payments)", not "vm-01"
EVERY_SERVER = re.compile(r"(?i)(all|\*|everywhere|(?:all|every|each)(?:\s+(?:the\s+)?(?:hosts?|servers?|nodes?|"
                          r"machines?|vms?))?)(\s*\(.*\))?\s*")   # (0.10.5) a group column's "all": every server, no value
COMMENT =re.compile(r"^\s*(#|//|/\*|\*|<!--|--\s|;|REM\s|%)")    # a line that is a comment (code, configuration)
DATE_PART = re.compile(r"%\{\+?[^}]*\}|%[YmdHjU]|\{\+?[yYMdH.\-]+\}|\$\{[^}]*\}|YYYY[.\-]?MM[.\-]?DD|yyyy[.\-]?MM[.\-]?dd")


def _hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8", errors="replace")).hexdigest()


def norm(name: str) -> str:
    """A name as compared: lower case, '_' and spaces as '-'."""
    return re.sub(r"[\s_]+", "-", str(name or "").strip().lower()).strip("-")


def lang_of(path: str) -> str:
    from supagent.knowledge.docs import sample_base

    name = sample_base(path).rsplit("/", 1)[-1].lower()       # (0.10.1) site.yml.sample: YAML
    for suffix in (".j2", ".jinja2", ".jinja", ".tpl", ".tmpl", ".template", ".erb"):
        if name.endswith(suffix) and "." in name[:-len(suffix)]:
            name = name[:-len(suffix)]                    # a template: the language of what it renders (x.conf.j2)
            break
    if name in NAMED_LANGS:
        return NAMED_LANGS[name]
    if "." not in name and re.search(r"(^|/)(group_vars|host_vars)/", path):
        return "yaml"                                     # (0.10.4) group_vars/all, host_vars/web1/vars: Ansible's YAML
    for ext, lang in sorted(LANGS.items(), key=lambda x: -len(x[0])):
        if name.endswith(ext):
            return lang
    if name.endswith((".j2", ".jinja2", ".jinja", ".tpl", ".tmpl", ".cfg", ".cnf", ".ini", ".conf", ".vcl", ".service")):
        return "conf"                                     # a template of a configuration: no prose
    return "text"


# --------------------------------------------------------------------------------------------------------------- #
# the names the agent knows
# --------------------------------------------------------------------------------------------------------------- #
IDENTITY = re.compile(r"(^|[._@-])(service|services|app|application|component|job|serviceName|service_name|workload|"
                      r"deployment|container|program)($|[._@-])|labels\.app$", re.I)
HOSTISH = re.compile(r"(^|[._@-])(host|hostname|node|instance|server|nodename|machine|vm)($|[._@-])", re.I)


class Names:
    """What a name in a text can be: a part (of the System map, a service or a host the data holds, one the documents
    declare), an index (a name or a pattern of the data), a metric (a name or a family of the data)."""

    def __init__(self) -> None:
        self.parts: dict[str, str] = {}             # norm(name) -> the part's name as shown
        self.alias: dict[str, str] = {}             # norm(other name) -> the part's name
        self.hosts: dict[str, str] = {}
        self.indices: dict[str, str] = {}           # norm(name or pattern) -> name
        self.metrics: dict[str, str] = {}           # name -> name (a family by its base too)
        self.homes: dict[str, set] = {}             # (0.10.4) norm(part) -> the documents that declare it

    def add_part(self, name: str, *others: str) -> None:
        n = norm(name)
        if not n or len(n) < 2:
            return
        shown = self.parts.get(n) or self.alias.get(n) or name
        self.parts.setdefault(norm(shown), shown)
        for o in others:
            if norm(o) and norm(o) != norm(shown):
                self.alias.setdefault(norm(o), shown)

    def part(self, raw: str) -> str | None:
        n = norm(raw)
        return self.parts.get(n) or self.alias.get(n) or self.hosts.get(n)

    def service(self, raw: str) -> str | None:
        """(0.10.5) A part, never a server nor a group of servers: what a page or a table's row is about."""
        n = norm(raw)
        return self.parts.get(n) or self.alias.get(n)

    def misspelled(self, raw: str, extra: dict[str, str] | None = None) -> str | None:
        """(0.10.4) The one part a word of 6 letters or more is a misspelling of: two letters swapped, one missing or
        one too many ("Promethues", "catalouge", "Elasticsearh"); never another letter instead (shipping is not
        shopping), never a plural ("payments" are not the payment service)."""
        w = norm(raw)
        if len(w) < 6 or not w.isascii():
            return None
        index = getattr(self, "_fuzzy", None)
        if index is None or getattr(self, "_fuzzy_size", 0) != len(self.parts) + len(self.alias) + len(extra or {}):
            index = {}
            names = {**{k: v for k, v in self.parts.items()}, **self.alias, **(extra or {})}
            for n, shown in names.items():
                if len(n) < 6:
                    continue
                for i in range(len(n)):                     # one letter missing in the word
                    index.setdefault(n[:i] + n[i + 1:], set()).add(shown)
                for i in range(len(n) - 1):                 # two letters swapped
                    if n[i] != n[i + 1]:
                        index.setdefault(n[:i] + n[i + 1] + n[i] + n[i + 2:], set()).add(shown)
            self._fuzzy, self._fuzzy_size = index, len(self.parts) + len(self.alias) + len(extra or {})
        found = set(index.get(w, set()))
        for i in range(len(w)):                             # one letter too many in the word
            if w[:i] + w[i + 1:] in self.parts:
                found.add(self.parts[w[:i] + w[i + 1:]])
        found = {f for f in found if norm(f) + "s" != w and norm(f) + "es" != w and not self.hosts.get(norm(f))}
        return next(iter(found)) if len(found) == 1 else None

    def index(self, raw: str) -> str | None:
        """An index name or pattern as the data names it ("logstash-%{+YYYY.MM.dd}" is "logstash-*")."""
        s = DATE_PART.sub("*", str(raw or "")).strip().strip("\"'")
        s = re.sub(r"\*+", "*", s)
        for cand in (s, s.rstrip("-.*") + "-*", s.rstrip("-.*") + "*"):
            if norm(cand) in self.indices:
                return self.indices[norm(cand)]
        for n, name in self.indices.items():         # a concrete daily index of a known pattern
            if "*" in n and re.fullmatch(re.escape(n).replace(r"\*", ".*"), norm(s)):
                return name
        return None

    def metric(self, raw: str) -> str | None:
        return self.metrics.get(str(raw or "").strip())


def known_names() -> Names:
    """The System map's parts, the data's indices and metrics and the values of their identity fields."""
    from supagent.models import Facet, KObject

    from supagent.knowledge.datalinks import SERVERISH

    from supagent.knowledge.interactions import TOPICS

    n = Names()
    try:
        for f in db.session.query(Facet).filter(Facet.status == "approved"):
            if f.facet in TOPICS:                        # (0.10.6) a subject is a topic, no part a text names ("every
                continue                                 # other service reads..." is no link of the subject Other)
            if SERVERISH.search(f.facet or ""):          # (0.10.5) a server, a group of servers, a VIP: a place, as
                for x in [f.value, *[str(y) for y in (f.synonyms or [])]]:   # the inventories read them (as a part,
                    n.hosts.setdefault(norm(x), f.value)  # the next reading renamed the groups "lb (group)")
                continue
            n.add_part(f.value, *[str(x) for x in (f.synonyms or [])])
    except Exception:  # pylint: disable=broad-except   (an older map: the names of the data only)
        db.session.rollback()
    for o in db.session.query(KObject).filter(KObject.gone_at.is_(None)):
        if o.kind == "index":
            n.indices[norm(o.name)] = o.name
        elif o.kind in ("metric", "family"):
            n.metrics[o.name] = o.name
        elif o.kind in ("field", "label"):
            vals = [str(v) for v in ((o.stats or {}).get("values") or [])][:500]
            if HOSTISH.search(o.name):
                for v in vals:
                    h = v.split(":", 1)[0]
                    if h and not re.fullmatch(r"[\d.]+", h):
                        n.hosts.setdefault(norm(h), h)
            elif IDENTITY.search(o.name):
                for v in vals:                       # (an exporter's job, "node" or "redis", is a tool, not a part)
                    if 2 <= len(v) <= 80 and norm(v) not in EXPORTERS and norm(v) not in ("kube-state-metrics",):
                        n.add_part(v)
    return n


# --------------------------------------------------------------------------------------------------------------- #
# units
# --------------------------------------------------------------------------------------------------------------- #
def units_of(doc: Any) -> list[dict[str, Any]]:
    """The units of a document: its pages (a wiki's, a site's) or its files (a repository's), or itself (an upload)."""
    from supagent.knowledge.index import _doc_pages

    meta = {str(p.get("url") or ""): p for p in (doc.pages or []) if isinstance(p, dict)}
    pages = _doc_pages(doc)
    out = []
    if pages is None:
        out.append({"ukey": f"doc:{doc.id}", "kind": "document", "title": doc.title or doc.url or "", "url": doc.url,
                    "path": "", "text": doc.content or "", "meta": {}})
        return out
    for url, title, block in pages:
        m = meta.get(url) or {}
        head = f"# {title}\n" if title else ""
        text = block[len(head):] if block.startswith(head) else block
        path = str(m.get("path") or "")
        out.append({"ukey": path or str(m.get("id") or url), "kind": "file" if path else "page", "title": title,
                    "url": url, "path": path, "text": text, "meta": m})
    return out


# --------------------------------------------------------------------------------------------------------------- #
# reading one unit
# --------------------------------------------------------------------------------------------------------------- #
def _line_of(text: str, pos: int) -> tuple[int, str]:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text.count("\n", 0, pos) + 1, text[start:end if end >= 0 else len(text)].strip()[:QUOTE]


def _yaml_docs(text: str) -> list[Any]:
    try:
        import yaml

        from supagent.knowledge.projects import yaml_text

        return [d for d in yaml.safe_load_all(yaml_text(text)) if d is not None]
    except Exception:  # pylint: disable=broad-except   (not YAML, or a template)
        return []


def _walk(obj: Any, path: tuple = ()) -> Iterator[tuple[tuple, Any]]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, path + (str(k),))
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v, path)
    else:
        yield path, obj


def discover(unit: dict[str, Any]) -> dict[str, Any]:
    """What a unit declares about who it is: the workloads it defines (Kubernetes, compose, systemd), the tool its
    configuration is the shape of, the names of the service it is (telemetry, artifact, package, application), its
    first heading."""
    text, path, lang = unit["text"] or "", unit["path"] or "", lang_of(unit["path"] or unit["title"] or "")
    out: dict[str, Any] = {"lang": lang, "workloads": [], "names": [], "tool": None, "heading": None}
    if lang == "yaml":
        from supagent.knowledge.projects import untemplated

        for d in _yaml_docs(untemplated(text) if "{{" in text or "{%" in text else text):   # (0.10.4) a template too
            if isinstance(d, dict) and d.get("kind") in WORKLOADS and isinstance(d.get("metadata"), dict):
                out["workloads"].append({"name": str(d["metadata"].get("name") or ""),
                                         "namespace": str(d["metadata"].get("namespace") or "")})
            if isinstance(d, dict) and isinstance(d.get("services"), dict) and ("version" in d or "services" in d):
                if any(isinstance(v, dict) and ("image" in v or "build" in v) for v in d["services"].values()):
                    out["workloads"] += [{"name": str(k), "namespace": ""} for k in d["services"]]
    if lang == "systemd" or path.endswith(".service"):
        out["workloads"].append({"name": path.rsplit("/", 1)[-1].rsplit(".", 1)[0], "namespace": ""})
    compose = bool(re.search(r"(^|/)[\w.-]*(compose|docker-stack)[\w.-]*\.ya?ml$", path, re.I))
    for tool, rx in TOOLS:
        if lang in ("markdown", "text", "html") or compose:
            break                                         # (0.10.4) a README's example of a configuration is not it;
            #                                               (0.10.5) a Compose file is no one tool's configuration
        if rx.search(text) and (tool != "jaeger" or lang in ("yaml", "json", "properties", "conf")):
            out["tool"] = tool
            break
    for rx, where in ((r"OTEL_SERVICE_NAME[\"']?\s*[:=,]\s*(?:value:\s*)?[\"']?([\w.-]+)", None),
                      (r"[\"']service\.name[\"']\s*[:=]\s*[\"']([\w.-]+)", None),
                      (r"service_name:\s*[\"']?([\w.-]+)", None),
                      (r"spring\.application\.name\s*[:=]\s*([\w.-]+)", None),
                      # (0.10.4) a package's own name, in its own file only (a dashboard's "name": "Prometheus" is
                      # no name of the service the folder is built into)
                      (r"<artifactId>([\w.-]+)</artifactId>", r"(^|/)pom\.xml$"),
                      (r"^name\s*=\s*[\"']([\w.-]+)[\"']", r"(^|/)(pyproject\.toml|Cargo\.toml|setup\.cfg)$"),
                      (r"^\s{0,2}\"name\":\s*\"([\w@/.-]+)\"", r"(^|/)(package|composer|bower)\.json$")):
        if where and not re.search(where, path):
            continue
        for m in re.finditer(rx, text, re.M):
            out["names"].append(m.group(1).rsplit("/", 1)[-1])
    if lang == "markdown":
        h = re.search(r"^#\s+(.+?)\s*$", text, re.M)
        out["heading"] = h.group(1).strip("` ") if h else None
    if path.endswith("pom.xml"):          # the project's artifact, not its dependencies' (0.10.4: nor its parent's)
        bare = re.sub(r"<(parent|dependencies|dependencyManagement|build|plugins|profiles)\b[\s\S]*?</\1>", "", text)
        m = re.search(r"<project[^>]*>[\s\S]*?<artifactId>([\w.-]+)</artifactId>", bare)
        out["names"] = [x for x in out["names"] if not m or x == m.group(1)] or out["names"][:1]
    out["names"] = list(dict.fromkeys(out["names"]))[:10]
    if compose or (len({norm(x) for x in out["names"]}) > 1 and not PACKAGE_FILES.search(path)):
        out["names"] = []                                 # (0.10.5) a file naming several services (a Compose file's
    return out                                            # OTEL_SERVICE_NAME of each): no one's other names


def owners(units: list[dict[str, Any]], repo: str | None, names: Names) -> tuple[str | None, list[str]]:
    """A repository's own service and its other names: its one workload (or the one named like the repository), else
    the repository's name when the map knows it; none for a repository of several workloads (each file speaks for its
    own)."""
    workloads = list(dict.fromkeys(w["name"] for u in units for w in (u["found"]["workloads"] or []) if w["name"]))
    others = list(dict.fromkeys([x for u in units for x in u["found"]["names"]] +
                                [u["found"]["heading"] for u in units if u["found"].get("heading") and
                                 re.fullmatch(r"[\w.-]+", u["found"]["heading"] or "") and
                                 u["path"].lower().split("/")[-1].startswith("readme") and "/" not in u["path"]]))
    rn = norm(repo or "")
    owner = None
    if len(workloads) == 1:
        owner = workloads[0]
    elif workloads:
        owner = next((w for w in workloads if norm(w) == rn or rn.endswith(norm(w)) or norm(w) in rn.split("-")), None)
    if owner is None and repo and names.part(repo) and len(workloads) <= 1:
        owner = names.part(repo)
    if owner is None and not workloads and others:
        owner = repo
    if owner is None:
        return None, []
    aliases = [x for x in others + ([repo] if repo else []) if x and norm(x) != norm(owner)]
    return owner, list(dict.fromkeys(aliases))


def _host_part(host: str, names: Names) -> str:
    """The part an address's host is: the map's or the data's name for it, else the host's own first meaningful label
    (payment.shop.svc -> payment, api.vendor.example -> vendor, db-01 -> db-01)."""
    if host.startswith("[") and ":" not in host:
        return ""                                         # (0.10.4) "http://[a-z0-9]+" in a check: no address
    h = host.split("@")[-1].split(":")[0].strip("[]").lower()
    if not h or re.fullmatch(r"[\d.]+", h) or not re.fullmatch(r"[a-z0-9_.-]+", h):
        return ""                                         # (0.10.4) "[a-z0-9]+" in a check is no host
    found = names.part(h)
    if found:
        return found
    if "." in h and names.hosts.get(norm(h.split(".")[0])):
        return names.hosts[norm(h.split(".")[0])]       # (0.10.5) db-01.example.net: the inventory's db-01
    stem = UPSTREAM_SUFFIX.sub("", h)
    if stem != h and names.part(stem):
        return names.part(stem) or stem                   # (0.10.5) an upstream "orders_backend": orders
    labels = [x for x in h.split(".") if x]
    for lab in labels:
        if names.part(lab):
            return names.part(lab) or lab
    if len(labels) >= 2 and labels[-1] in PUBLIC_SUFFIXES:   # (0.10.4) a public name: its organisation
        org = labels[-3] if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "net", "ac", "gov") else labels[-2]
        return "" if org in ("example", "invalid", "test", "localhost") else org   # (hooks.slack.com: slack)
    meaningful = [x for x in labels if x not in GENERIC_LABELS]
    return meaningful[0] if meaningful else labels[0]



VIP_WORD = re.compile(r"(?i)(?:^|[.\-_])vips?(?:[.\-_]|$)")   # (0.10.4) orders-vip.example.com, vip-orders, x.vip.y
VIP_KEY = re.compile(r"(?i)(?:^|_)(?:vips?|virtual_ip(?:address)?(?:es)?|vip_(?:address|addr|ip|fqdn|host|url)s?)$")
VIP_TEXT = re.compile(r"(?i)\bVIPs?\b|\bvirtual IPs?\b")
HOLDER_TEXT = re.compile(r"(?i)\bkeepalived\b|\bheld\s+(?:by|on)\b|\bholders?\b|\bvrrp\b|\bfloats?\s+(?:on|between)\b")
ADDRESS_NAME = re.compile(r"(?:[a-z0-9-]+\.){2,}[a-z]{2,}")   # (0.10.6) a fully qualified name: www.example.com
DIAGRAM_SYNTAX = re.compile(r"-->|->|<-|@startuml|@enduml|\bcomponent\s+[\"\[]|\bnote\s+(?:right|left|top|bottom)\s+of\b|"
                            r"\bgraph\s+(?:LR|RL|TD|TB|BT)\b|\bsequenceDiagram\b")   # (0.10.6) a diagram's source
VIP_CUE = re.compile(r"(?i)\b(points?|fronts?|forwards?|routes?|balances?|load[- ]balances?|in front of|goes|go|resolves?|"
                     r"sends?|serves?|for)\b")
IP_ADDR = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def _vip_name(text: str) -> str | None:
    """(0.10.4) A VIP's own name in an address or a value: its host ("https://orders-vip.example.com:443/x" ->
    orders-vip.example.com), an IP address as written."""
    t = re.sub(r"^\w+://", "", str(text or "").strip().strip("\"'")).split("/")[0].split("@")[-1]
    t = re.sub(r":\d+$", "", t)
    return t if re.fullmatch(r"[A-Za-z0-9][\w.-]*", t) and "{" not in t else None


def _vip_service(host: str, names: "Names", own: dict[str, str]) -> str | None:
    """(0.10.4) The service a VIP's name says it fronts: orders-vip.example.com, vip-orders, orders.vip.example.com:
    orders, when a part has that name."""
    first = re.split(r"\.", host.lower())[0]
    stem = re.sub(r"(?:^|[-_])vips?(?=[-_]|$)", "", first).strip("-_")
    for cand in [stem] + [x for x in re.split(r"[.\-_]", host.lower()) if x not in ("vip", "vips")]:
        if not cand or cand in GENERIC_LABELS or cand in PUBLIC_SUFFIXES:
            continue
        p = names.part(cand) or own.get(norm(cand))
        if p and not names.hosts.get(norm(cand)):
            return p
    return None


def _is_public(host: str) -> bool:
    """(0.10.4) A host on the public internet's names (hooks.slack.com), not one of the system's own (catalogue,
    db.internal, payment.shop.svc)."""
    labels = [x for x in host.lower().split(".") if x]
    return len(labels) >= 2 and labels[-1] in PUBLIC_SUFFIXES and not re.fullmatch(r"[\d.]+", host)


def _url_parts(url: str) -> tuple[str, str, int | None, str]:
    """(scheme, host, port, first path segment) of an address."""
    m = re.match(r"^(?P<scheme>[a-z0-9:+]+)://(?:[^@/\s]*@)?(?P<host>\[[^\]]+\]|[^:/\s?#]+)(?::(?P<port>\d+))?"
                 r"(?:/(?P<path>[^/?#\s]*))?", url, re.I)
    if not m:
        return "", "", None, ""
    return m.group("scheme").lower(), m.group("host"), int(m.group("port")) if m.group("port") else None, \
        (m.group("path") or "")


def _endpoint_verb(scheme: str, port: int | None, line: str, text: str) -> tuple[str, str]:
    """How a unit uses an address: (verb, what the address is: service | database | cache | logs)."""
    s = scheme.split(":")[-1] if scheme.startswith("jdbc") else scheme
    if scheme.startswith("jdbc") or s.startswith(DB_SCHEMES) or port in DB_PORTS or \
            re.search(r"\b(?:db|database|datasource|dsn|jdbc)\b|_DB_", line, re.I):
        w, r = bool(WRITES_SQL.search(text)), bool(READS_SQL.search(text))
        return ("sends_to" if w and not r else "reads_from" if r and not w else "uses"), "database"
    if s.startswith("redis") or port in CACHE_PORTS or re.search(r"\bredis|memcache|cache\b", line, re.I):
        return "uses", "cache"
    if port in LOG_PORTS or LOG_WORDS.search(line):
        return "sends_to", "logs"
    # (0.10.5) what the line says of the address: a mail relay is sent to; a broker is sent to, unless the unit consumes
    # from it; an object store is written to; a search cluster is written by an indexer, read otherwise
    if s.startswith("smtp") or port in (25, 465, 587) or re.search(r"smtp|smarthost|relayhost|mail_?relay", line, re.I):
        return "sends_to", "service"
    if port in (4317, 4318) or re.search(r"OTEL_EXPORTER|OTLP|otlp", line):   # telemetry exported: sent to
        return "sends_to", "service"
    if s.startswith(("amqp", "kafka", "nats")) or port in (5671, 5672, 9092) or \
            re.search(r"amqp|rabbit|kafka|broker", line, re.I):
        consumes = re.search(r"consum|subscrib|listen|_QUEUE\b|queue_name|\bpoll", text, re.I)
        return ("reads_from" if consumes else "sends_to"), "service"
    if port == 9000 or re.search(r"\bs3\b|s3[_-]|bucket|minio|object.?stor", line, re.I):
        return "sends_to", "service"
    if port in (9200, 9300) or re.search(r"opensearch|elastic", line, re.I):
        writes = re.search(r"\b(?:index(?:ing|er|es)?|bulk|ingest|push(?:es)?|writes?)\b", text, re.I)
        return ("sends_to" if writes else "reads_from"), "service"
    return "calls", "service"


MON_KEY = re.compile(r"^(?:(?P<who>[a-z][a-z0-9-]*?)_)?(?P<what>scrape_configs|targets|alertmanager_config|alertmanagers|"
                     r"datasources)$", re.I)


def _monitoring(text: str, names: "Names", own: dict[str, str], me: str | None) -> list[tuple[str, str, str, int]]:
    """(0.10.4) What a monitoring configuration says, in its own files (prometheus.yml, a Grafana provisioning file) or
    in a deployment's variables (prometheus_scrape_configs, prometheus_targets, prometheus_alertmanager_config,
    grafana_datasources): the parts a scrape job reads (monitors: a job named after a part, "node" for node-exporter,
    or targets on a part's address), where the alerts go (sends_to: the alertmanagers) and what a dashboard tool reads
    (reads_from: a data source's address, else its type when a part has that name). The variables' owner is the part
    their prefix names; a configuration file's is its own part. [(subject, verb, object, position)]"""
    out: list[tuple[str, str, str, int]] = []

    def resolve(x: Any) -> str | None:
        x = str(x or "").strip()
        p = names.part(x) or own.get(norm(x)) if x and "{" not in x else None
        return p if p and not names.hosts.get(norm(x)) else None

    def at_host(t: Any) -> str | None:                    # "http://grafana:3000", "alertmanager:9093"
        host = re.sub(r"^\w+://", "", str(t or "")).split("/")[0].split("@")[-1].rsplit(":", 1)[0]
        return resolve(host) if host and "{" not in host else None

    def pick(cands: list[str], who: str | None) -> str | None:
        """The one part meant: the only one, else the only one declared where the subject is (the storage
        Prometheus beside the storage Grafana)."""
        cands = list(dict.fromkeys(c for c in cands if c))
        if len(cands) <= 1:
            return cands[0] if cands else None
        mine = names.homes.get(norm(who or "")) or set()
        near = [c for c in cands if mine & (names.homes.get(norm(c)) or set())]
        return near[0] if len(near) == 1 else None

    def named_like(word: Any, who: str | None) -> str | None:
        """A part by a job's or a type's word: "node" is node-exporter, "prometheus" one of the Prometheus parts."""
        j = norm(str(word or "").strip())
        if not j or "{" in j or (who and (j in norm(who).split("-") or norm(who) == j)):
            return None                                   # (the tool's own job: "prometheus" in prometheus-server's)
        cands = [p for k, p in {**names.parts, **names.alias}.items() if k in (j, j + "-exporter") or
                 k.startswith(j + "-") or k.endswith("-" + j) or (j.endswith("-exporter") and k == j[:-9])]
        cands += [v for k, v in own.items() if k in (j, j + "-exporter")]
        cands = list(dict.fromkeys(c for c in cands if not names.hosts.get(norm(c)) and norm(c) != norm(who or "")))
        mine = names.homes.get(norm(who or "")) or set()
        near = [c for c in cands if mine & (names.homes.get(norm(c)) or set())]
        if len(near) == 1:
            return near[0]                                # the one declared where the subject is
        exact = [c for c in cands if norm(c) in (j, j + "-exporter")]
        return exact[0] if len(exact) == 1 else pick(cands, who)

    def targets(obj: Any) -> list[Any]:
        found: list[Any] = []
        for path, v in _walk(obj):
            if path and path[-1] in ("targets", "url", "urls", "address", "host", "hosts"):
                found.append(v)
        return found

    def where(x: Any) -> int:
        i = text.find(str(x)) if x is not None else -1
        return max(0, i)

    def visit(obj: Any) -> None:
        if isinstance(obj, list):
            for v in obj:
                visit(v)
            return
        if not isinstance(obj, dict):
            return
        for k, v in obj.items():
            if str(k) in ("metricbeat.modules", "heartbeat.monitors") and isinstance(v, list) and resolve(me):
                for item in v:                            # (0.10.4) what a Beat watches: its modules' and monitors'
                    for tgt in dict.fromkeys(p for p in map(at_host, targets(item)) if p):   # hosts
                        if norm(tgt) != norm(resolve(me) or ""):
                            out.append((resolve(me), "monitors", tgt, where(tgt)))
                continue
            m = MON_KEY.match(str(k))
            if m:
                who = resolve(m.group("who")) if m.group("who") else (resolve(me) if me else None)
                what = m.group("what").lower()
                if who and what == "scrape_configs" and isinstance(v, list):
                    for job in v:
                        if not isinstance(job, dict):
                            continue
                        name = job.get("job_name")
                        tgt = named_like(name, who) or next((p for p in map(at_host, targets(job)) if p), None)
                        if tgt and norm(tgt) != norm(who):
                            out.append((who, "monitors", tgt, where(name)))
                elif who and what == "targets" and m.group("who") and isinstance(v, dict):
                    for job, val in v.items():                # prometheus_targets: {node: [...], grafana: [...]}
                        tgt = named_like(job, who) or next((p for p in map(at_host, targets(val)) if p), None)
                        if tgt and norm(tgt) != norm(who):
                            out.append((who, "monitors", tgt, where(job)))
                elif who and what in ("alertmanager_config", "alertmanagers"):
                    tgt = next((p for p in map(at_host, targets(v)) if p), None) or named_like("alertmanager", who)
                    if tgt and norm(tgt) != norm(who):
                        out.append((who, "sends_to", tgt, where(k)))
                elif who and what == "datasources" and isinstance(v, list):
                    for ds in v:
                        if not isinstance(ds, dict):
                            continue
                        tgt = at_host(ds.get("url")) or named_like(ds.get("type"), who)
                        if tgt and norm(tgt) != norm(who):
                            out.append((who, "reads_from", tgt, where(ds.get("name") or ds.get("url") or k)))
            visit(v)

    for data in _yaml_docs(text):
        visit(data)
    return out


def _metric_names(text: str, lang: str) -> list[tuple[int, str, str]]:
    """The metrics a unit registers: (position, the name the backend shows, its kind)."""
    out = []
    for m in re.finditer(r"\b(Counter|Gauge|Histogram|Summary|Info|Enum)\s*\(\s*[\"']([a-zA-Z_:][\w:]*)[\"']", text):
        kind, name = m.group(1).lower(), m.group(2)
        out.append((m.start(), name + ("_total" if kind == "counter" and not name.endswith("_total") else ""), kind))
    for m in re.finditer(r"\b(Counter|Timer|Gauge|DistributionSummary|LongTaskTimer)\s*\.\s*builder\s*\(\s*\"([\w.]+)\"",
                         text):
        kind, base = m.group(1).lower(), m.group(2).replace(".", "_").replace("-", "_")
        name = base + {"counter": "_total", "timer": "_seconds", "distributionsummary": "", "longtasktimer": "_seconds",
                       "gauge": ""}[kind]
        out.append((m.start(), name, kind))
    for m in re.finditer(r"\b(?:registry|meterRegistry|Metrics)\s*\.\s*(counter|timer|gauge)\s*\(\s*\"([\w.]+)\"", text):
        base = m.group(2).replace(".", "_")
        out.append((m.start(), base + {"counter": "_total", "timer": "_seconds", "gauge": ""}[m.group(1)], m.group(1)))
    for m in re.finditer(r"\b(Counter|Gauge|Histogram|Summary)(?:Vec)?Opts\s*\{[^}]*?Name:\s*\"([\w:]+)\"", text, re.S):
        out.append((m.start(), m.group(2), m.group(1).lower()))
    for m in re.finditer(r"\bnew\s+(?:client|promClient|prom)\.(Counter|Gauge|Histogram|Summary)\s*\(\s*\{[^}]*?"
                         r"name:\s*[\"'](\w+)[\"']", text, re.S):
        out.append((m.start(), m.group(2), m.group(1).lower()))
    for m in re.finditer(r"\bcreate_(counter|up_down_counter|histogram|gauge)\s*\(\s*[\"']([\w.]+)[\"']", text):
        base = m.group(2).replace(".", "_")
        out.append((m.start(), base + ("_total" if m.group(1) == "counter" else ""), m.group(1)))
    return out


def _metric_in_data(name: str, kind: str, names: Names) -> str | None:
    """The data's name for a registered metric (a histogram by its family or its _bucket / _count series)."""
    for cand in (name, name + "_total", name.removesuffix("_total"), name + "_bucket", name + "_count"):
        if names.metric(cand):
            found = names.metric(cand) or cand
            if kind in ("histogram", "timer", "summary") and found.endswith(("_bucket", "_count", "_sum")):
                fam = re.sub(r"_(bucket|count|sum)$", "", found)
                return names.metric(fam) or fam
            return found
    return None


def _outline(text: str, lang: str) -> list[dict[str, Any]]:
    """A unit's symbols: functions, classes and routes (Python by its syntax tree, others by their declarations), or
    a document's headings."""
    out: list[dict[str, Any]] = []
    if lang == "python":
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    item = {"kind": "class" if isinstance(node, ast.ClassDef) else "function", "name": node.name,
                            "line": node.lineno, "end": getattr(node, "end_lineno", node.lineno)}
                    doc = ast.get_docstring(node)
                    if doc:
                        item["doc"] = doc.strip().split("\n")[0][:200]
                    for d in getattr(node, "decorator_list", []):
                        if isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ("get", "post", "put", "patch",
                                                                                       "delete", "route") and d.args \
                                and isinstance(d.args[0], ast.Constant) and isinstance(d.args[0].value, str):
                            item["route"] = f"{d.func.attr.upper()} {d.args[0].value}"
                    out.append(item)
            return sorted(out, key=lambda x: x["line"])
    if lang in ("java", "kotlin", "scala", "groovy", "csharp", "typescript", "javascript", "go", "rust", "php", "ruby"):
        decl = re.compile(r"^\s*(?:(?:public|private|protected|internal|static|final|abstract|override|suspend|async|"
                          r"export|default|open|data|sealed|pub|func|fn|def|function|class|interface|object|enum|struct|"
                          r"record|trait|impl|module)\s+)+(?:[\w<>\[\],?\s]+?\s+)?([A-Za-z_]\w*)\s*(?:\(|\{|<|:|=|$)",
                          re.M)
        route = re.compile(r"@(Get|Post|Put|Delete|Patch|Request)Mapping\s*\(\s*(?:value\s*=\s*)?\"([^\"]+)\"|"
                           r"\b(?:app|router)\.(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]")
        for m in decl.finditer(text):
            name = m.group(1)
            if name in ("if", "for", "while", "switch", "return", "new", "else", "catch", "try"):
                continue
            kind = "class" if re.search(r"\b(class|interface|object|enum|struct|record|trait)\s+" + name,
                                        m.group(0)) else "function"
            out.append({"kind": kind, "name": name, "line": text.count("\n", 0, m.start()) + 1})
        for m in route.finditer(text):
            verb = (m.group(1) or m.group(3) or "").upper()
            out.append({"kind": "route", "name": f"{verb} {m.group(2) or m.group(4)}",
                        "line": text.count("\n", 0, m.start()) + 1})
        return sorted(out, key=lambda x: x["line"])[:300]
    for m in re.finditer(r"^(#{1,4})\s+(.+?)\s*$", text, re.M):
        out.append({"kind": "heading", "name": m.group(2)[:200], "level": len(m.group(1)),
                    "line": text.count("\n", 0, m.start()) + 1})
    return out[:300]


# the sentences of a document that state an interaction: a cue between two parts
RUNS_ON_OTHER = (r"\bse\s+ejecuta\s+en\b|\bcorre\s+en\b|\bfunciona\s+en\b|\best[aá]n?\s+(?:instalad|desplegad|alojad)[oa]s?\s+en"
                 r"\b|\bs['’]ex[ée]cute\s+sur\b|\btourne\s+sur\b|\bfonctionne\s+sur\b|\best\s+(?:install|d[ée]ploy|h[ée]berg)"
                 r"[ée]e?s?\s+sur\b|\bl[äa]uft\s+auf\b|\blaufen\s+auf\b|\broda\s+em\b|\bexecuta\s+em\b|\best[aá]\s+"
                 r"(?:instalad|implantad|hospedad)[oa]\s+em\b|\bgira\s+su\b|\b[èe]\s+in\s+esecuzione\s+su\b|\b[èe]\s+"
                 r"(?:installat|ospitat)[oa]\s+su\b")   # (0.10.4) where a part runs, in a team's other languages
HOST_SHAPE = re.compile(r"(?<![\w.-])(?P<h>[a-z][a-z0-9]*(?:[-.][a-z0-9]+)*?[-.]?\d+[a-z]?)(?![\w-]|\.\w)", re.I)
NOT_HOST = re.compile(r"(?i)^(python|java|jdk|jre|node|nodejs|ruby|php|go|golang|perl|dotnet|net|centos|ubuntu|debian|rhel|"
                      r"rocky|alma|fedora|alpine|windows|win|macos|k8s|k3s|eks|aks|gke|ec2|s3|x86|arm|amd|ipv|http|tls|"
                      r"ssl|tcp|udp|v|version|port|step|phase|stage|day|week|month|year|q|h|top|tier|level|gen|log4j|"
                      r"utf|iso|rfc|cve|pep|jsr|es|ecma|html|css|sha|md|base|mp|h26|p)[-.]?\d")


def _host_tokens(text: str) -> list[str]:
    """(0.10.4) The host names a clause gives ("on meet-01", "on web1 and web2"), known to an inventory or not: a
    name of letters then digits, not a language, a system, a protocol, a version or a port."""
    return [m.group("h") for m in HOST_SHAPE.finditer(text) if not NOT_HOST.match(m.group("h"))]


CUES = [
    ("runs_on", re.compile(r"\b(?:runs?|running|installed|deployed|hosted|lives?)\s+on\b|\bon\s+the\s+(?:VM|host|server|"
                           r"node)\b|\(\s*(?:\w+\s+)?on\b|" + RUNS_ON_OTHER, re.I)),
    ("calls", re.compile(r"\b(?:calls?|calling|invokes?|requests?|queries|forwards?\b[^.]{0,40}?\bto|reserves?\b[^.]{0,40}?"
                         r"\bin|authori[sz]es?\b[^.]{0,40}?\bwith|depends?\s+(?:up)?on|talks?\s+to|connects?\s+to)\b", re.I)),
    ("sends_to", re.compile(r"\b(?:writes?|publishes|pushes|sends?|stores?|puts?|ships?|keeps|saves|persists)\b(?:[^.]{0,40}?"
                            r"\b(?:in|into|to)\b)?|\b(?:writing|publishing|pushing|sending|shipping)\s+(?:[^.]{0,30}?\s)?"
                            r"(?:to|into)\b", re.I)),   # (0.10.6) "... and pushing to tix-search"
    ("reads_from", re.compile(r"\b(?:reads?|loads?|fetches|consumes?|pulls?)\b[^.]{0,40}?\b(?:from|in)\b|\bcaches?\b[^.]"
                              r"{0,30}?\bin\b|\buses\b|\b(?:reading|loading|fetching|consuming|pulling)\s+"
                              r"(?:[^.]{0,30}?\s)?from\b", re.I)),   # (0.10.6) "responsible for reading from the DB"
    ("monitors", re.compile(r"\b(?:monitors|watches|checks(?!\b[^.]{0,40}?\bagainst\b)|probes|scrapes|pings|polls)\b", re.I)),
    ("calls", re.compile(r"\b(?:asks?|looks\s+up|checks\b[^.]{0,40}?\bagainst|routes?\b[^.]{0,30}?\bto|"
                         r"dispatches\b[^.]{0,30}?\bto|proxies\b[^.]{0,30}?\bto)\b", re.I)),   # (0.10.4)
    ("calls", re.compile(r"\b(?:ruft|rufen|llama\s+a|llaman\s+a|appelle|appellent|chama|chamam|chiama|chiamano)\b", re.I)),
    ("sends_to", re.compile(r"\b(?:(?:is|are)\s+(?:stored|kept|saved|persisted|written)\s+(?:in|into|to)|schreibt\b[^.]{0,40}?"
                            r"\b(?:in|nach)|speichert\b[^.]{0,40}?\bin|escribe\b[^.]{0,40}?\ben|guarda\b[^.]{0,40}?\ben|"
                            r"écrit\b[^.]{0,40}?\bdans|envoie\b[^.]{0,40}?\b(?:vers|à|dans)|envía\b[^.]{0,40}?\b(?:a|hacia)|"
                            r"grava\b[^.]{0,40}?\bem|scrive\b[^.]{0,40}?\bin)\b", re.I)),
    ("reads_from", re.compile(r"\b(?:liest\b[^.]{0,40}?\b(?:aus|von)|lee\b[^.]{0,40}?\bde|lit\b[^.]{0,40}?\b(?:dans|depuis)|"
                              r"lê\b[^.]{0,40}?\bde|legge\b[^.]{0,40}?\bda)\b", re.I)),
]
OBJECT_OF = re.compile(r"(?i)\b(runs|running|hosts|hosting|has|have|installs|installing|contains|includes|serves|"
                       r"exposes|deploys|deploying|starts)\s+(?:an?|the|its|their|our)?\s*$")
NEXT_VERB = re.compile(r"\s+(?:(?:also|then|only|now|still|never|always)\s+)?(?:takes|consumes|reads|writes|sends|pings|"
                       r"polls|calls|uses|stores|keeps|gets|pulls|pushes|publishes|forwards|serves|runs|receives|queries|"
                       r"fetches|handles|processes|checks|watches|scrapes|monitors|collects|ships|exposes|proxies|talks|"
                       r"connects|depends|asks|looks|needs|listens|accepts|returns|updates|deletes|creates|notifies|"
                       r"posts|emits|exports|loads|caches|saves|persists|probes|routes|balances)\b", re.I)
VERB_OBJECT = re.compile(r"\s+[a-z]{3,}s\s+(?:the|a|an|it|its|them|their|everything|all|every|each|up|out|off)\b")
# (0.10.6) where a part runs ends where the sentence says something else of it: "the job running on the app group is
# responsible for reading from the DB" runs on the app group, not on the DB's
RUNS_ON_END = re.compile(r"\b(?:is|are|was|were|has|have|does|do|did|will|would|can|could|must|should|may|might)\b|"
                         r"\b[a-z]{3,}ing\s+(?:from|to|into|with|the|a|an|its|their)\b", re.I)
CLAUSE_END = re.compile(r",?\s+and\s+(?:is|are|was|were|has|have|it|its|they|their)\b|;|\bwhich\b|"
                        r",?\s+and\s+[a-z]+s\s+(?:the|a|an|its|their|all|every|each)\b", re.I)   # (0.10.4) "... and
#                                                         charges the cards through ...": a second predicate
# (0.10.4) a statement denied or in the past is no fact: "the frontend never calls the payment service", "the job used
# to read the database", "X does not run on Y any more"
DENIABLE = ("calls", "sends_to", "reads_from", "uses", "runs_on", "monitors")   # (0.10.5) kept as "not_<verb>"
NEGATED = re.compile(r"\b(?:never|not|no\s+longer|no\s+more|cannot|neither|nor|used\s+to|formerly|previously|"
                     r"nunca|jam[aá]s|ya\s+no|ne\s+\w+\s+(?:pas|plus|jamais)|n['’]\w+\s+(?:pas|plus|jamais)|nie|"
                     r"nicht|kein\w*|n[aã]o)\b|\bnon(?=\s)|n['’]t\b", re.I)
# (0.10.5) a sentence opening on a verb is a step ("Query Loki via Grafana", "check X through Y"); a part that
# collects or receives through another gets from it ("Loki collects the logs from every node via promtail")
IMPERATIVE = re.compile(r"(?i)\W*(?:\*\*[^*]+\*\*:?\s*)?(?:query|check|look|see|use|open|search|run|find|inspect|grep|browse|"
                        r"view|read|go|try|ask|call|verify|ensure|make|restart|connect)\b")
RECEIVES = re.compile(r"(?i)\b(?:collect(?:s|ing|ed)?|receiv(?:es|ing|ed)|gets?|gather(?:s|ing)?|pulls?|ingest(?:s|ing)?|"
                      r"fetch(?:es|ing)?|is fed|are fed|consum(?:es|ing))\b")
# (0.10.4) "requests go through the proxy to the app server": the proxy calls the app server
ROUTE = re.compile(r"\b(?:through|via|por\s+medio\s+de|a\s+trav[eé]s\s+de|über|attraverso)\s+", re.I)
ROUTE_TO = re.compile(r"\b(?:to|into|on\s+to|towards|onto|hacia|vers|zum|zur|verso)\s+(?:the\s+|el\s+|la\s+|le\s+|l['’]\s*|"
                      r"den\s+|dem\s+|der\s+|il\s+|lo\s+)?$", re.I)
FLOW_SOURCE = re.compile(r"(^|-)(rabbitmq|rabbit|kafka|nats|activemq|artemis|pulsar|sqs|kinesis|queue|broker|mq|redis|"
                         r"mysql|mariadb|postgres|postgresql|pgsql|mongo|mongodb|cassandra|db|database|elasticsearch|"
                         r"opensearch|s3|minio|bucket|storage)(-|$)", re.I)   # (0.10.4) what is read, never calls
ARROW = re.compile(r"\s*(→|⟶|->|-->|←|⟵|<-|<--)\s*")
FLOW_LABEL = re.compile(r"\b(alerts?|notifications?|events?|logs?|metrics?|messages?|spans?|traces?|records?)\b", re.I)
SOURCE_LABEL = re.compile(r"\bdata\s*-?\s*sources?\b|\bdatasources?\b|\bsource\s+of\s+data\b", re.I)
PARTS_COLUMN = re.compile(r"\b(services?|applications?|apps?|components?|containers?|software|processes|daemons?|"
                          r"workloads?|runs|parts?|roles?)\b", re.I)
ON_HOSTS = re.compile(r"(?:\s+(?:routers?|servers?|nodes?|instances?|processes|daemons?|agents?))?\s+(?:runs?\s+)?on\s+"
                      r"(?P<hosts>(?:the\s+)?[A-Za-z0-9][\w.-]*(?:\s+(?:host|server|machine|node))?(?:\s*,\s*"
                      r"[A-Za-z0-9][\w.-]*|\s+and\s+[A-Za-z0-9][\w.-]*)*)")
PASSIVE = re.compile(r"\b(?:is|are|was|were|be|been|being|gets?|got)\s+(?:\w+ly\s+)?(?P<verb>read|written|sent|published|"
                     r"pushed|stored|consumed|fetched|loaded|pulled|called|used|queried|requested|invoked|served|"
                     r"proxied|exposed|fronted|watched|monitored|checked|scraped)\b(?:\s+\w+){0,4}?\s+by\s+", re.I)
PASSIVE_VERBS = {"read": "reads_from", "consumed": "reads_from", "fetched": "reads_from", "loaded": "reads_from",
                 "pulled": "reads_from", "written": "sends_to", "sent": "sends_to", "published": "sends_to",
                 "pushed": "sends_to", "stored": "sends_to", "called": "calls", "queried": "calls",
                 "requested": "calls", "invoked": "calls", "used": "uses", "served": "calls", "proxied": "calls",
                 "exposed": "calls", "fronted": "calls", "watched": "monitors", "monitored": "monitors",
                 "checked": "monitors", "scraped": "monitors"}
LOGS_CUE = re.compile(r"\blogs?\b", re.I)
METRIC_CUE = re.compile(r"\b(metrics?|counts?|counters?|histograms?|gauges?|exporters?|exports?|exposes?|emits?)\b",
                        re.I)
QUERY_LIKE = re.compile(r"\b(?:rate|irate|increase|sum|avg|max|min|histogram_quantile)\s*\(|\[\d+[smhd]\]")


COLUMNS = [   # what a table's column says of its row's part (its header)
    ("runs_on", re.compile(r"\b(runs?\s+on|hosts?|servers?|nodes?|machines?|vms?|platform|cluster|located)\b|"
                           r"\b(?:target|host|inventory|ansible|server|deployment)\s+groups?\b|^\s*groups?\s*$", re.I)),
    #                         (0.10.5) "Target Group", "Inventory group": where a role runs, not what it monitors
    ("monitors", re.compile(r"\b(scrapes?|scraped\s+targets?|monitors|watches|probes|targets?)\b", re.I)),   # (0.10.4)
    ("owned_by", re.compile(r"\b(owners?|team|squad|responsible|maintainers?|contacts?)\b", re.I)),
    ("calls", re.compile(r"\b(depends?\s+on|dependencies|calls|upstreams?|uses|clients?\s+of)\b", re.I)),
    ("logs_to", re.compile(r"\b(logs?|log\s+index|indices|indexes)\b", re.I)),
    ("watched_by", re.compile(r"\b(metrics?|dashboards?|monitoring|alerts?)\b", re.I)),
    ("code_in", re.compile(r"\b(repo|repository|repositories|code|source)\b", re.I)),
]


def _tables(text: str) -> list[tuple[int, list[str], list[tuple[int, list[str]]]]]:
    """The tables of a text (rows of cells joined by " | "): (position, header, [(position, cells)])."""
    out, lines, pos = [], text.split("\n"), 0
    block: list[tuple[int, list[str]]] = []
    for line in lines + [""]:
        cells = [c.strip(" `*") for c in re.split(r"\s*\|\s*", line.strip().strip("|"))] if " | " in line else []
        if len(cells) >= 2 and not set(line.strip()) <= set("|-: "):
            block.append((pos, cells))
        elif not (set(line.strip()) <= set("|-: ") and line.strip()):
            if len(block) >= 2:
                out.append((block[0][0], block[0][1], block[1:]))
            block = []
        pos += len(line) + 1
    return out


def _sentences(text: str) -> Iterator[tuple[int, str]]:
    """A text's sentences, a line wrapped in the middle of one going on (a bullet, a heading, a blank line, a table's
    row start a new one); positions as in the text (0.10.4: the wrapped lines joined, where the sentence starts in
    the text, so that its quote is its own line)."""
    pieces, flat_at, text_at, last, size = [], [], [], 0, 0
    for m in re.finditer(r"\n(?![ \t]*(?:[-*+#|>]|\d+[.)]\s|\n))[ \t]*", text):
        item = re.match(r"[ \t]*(?:[-*+]|\d+[.)])\s", text[text.rfind("\n", 0, m.start()) + 1:m.start()])
        if item and m.end() - m.start() == 1:
            continue                                      # (0.10.4) a line after a list's item, not indented: no
        flat_at.append(size)                              # continuation of the item ("- A → B" then a paragraph)
        text_at.append(last)
        pieces.append(text[last:m.start()] + " ")
        size += m.start() - last + 1
        last = m.end()
    flat_at.append(size)
    text_at.append(last)
    pieces.append(text[last:])
    flat = "".join(pieces)

    def at(i: int) -> int:                                # a position of the joined text in the text
        k = bisect.bisect_right(flat_at, i) - 1
        return text_at[k] + (i - flat_at[k])

    for m in re.finditer(r"(?:[^\n.!?;]|[.!?;](?![\s)\]]|$))+(?:[.!?;](?=[\s)\]]|$)|\n|$)", flat):   # (a dot inside
        #                                                            a name, logs.test, db-01.example.net, keeps going)
        s = m.group(0).strip()
        if len(s) >= 8:
            yield at(m.start() + len(m.group(0)) - len(m.group(0).lstrip())), s


def _depths(sentence: str) -> list[int]:
    depth, out = 0, []
    for ch in sentence:
        depth += 1 if ch == "(" else 0
        out.append(depth)
        depth -= 1 if ch == ")" and depth else 0
    return out


COMMON_WORDS = {"user", "users", "web", "load", "news", "mail", "git", "blog", "data", "files", "setup", "test",
                "tests", "demo", "docs", "home", "info", "search", "help", "admin", "chat", "store", "shop", "app",
                "api", "core", "main", "base", "common", "config", "server", "client", "service", "system", "network",
                "cloud", "storage", "backup", "monitoring", "logs", "metrics", "alerts", "cache", "queue", "worker",
                "jobs", "tasks", "events", "auth", "login", "account", "accounts", "profile", "report", "reports",
                "front", "back", "public", "private", "static", "media", "assets", "images", "content", "page",
                "pages", "site", "portal", "proxy", "gateway", "router", "db", "database", "vpn", "files", "status",
                "health", "notify", "notifications", "email", "sms", "queue", "jobs", "batch", "cron", "tools", "util",
                "utils", "lib", "libs", "sdk", "cli", "ui", "www", "dashboard", "dashboards"}


def _named(sentence: str, names: Names, own: dict[str, str], home: Any = None) -> list[tuple[int, str, str]]:
    """The parts and hosts a sentence names: (position, name as written, the part). (0.10.4) In a repository's file
    (`home`: its document), a common word is a part only when that repository declares it: "user", "web" or "load"
    in another project's text are words, not that project's services."""
    out = _named_all(sentence, names, own)
    if home is None:
        return out
    return [x for x in out if norm(x[2]) not in COMMON_WORDS or home in (names.homes.get(norm(x[2])) or {home})]


def _named_all(sentence: str, names: Names, own: dict[str, str]) -> list[tuple[int, str, str]]:
    out = []
    for m in re.finditer(r"[A-Za-z][\w.-]*[\w]|[A-Za-z]", sentence):
        w = m.group(0).strip(".-")
        p = names.part(w) or own.get(norm(w)) or names.misspelled(w, own)    # (0.10.4) "Promethues scrapes ..."
        if p:
            out.append((m.start(), w, p))
    # names of two words ("orders database"), or one name written in two ("ledger writer": ledgerwriter)
    for m in re.finditer(r"\b(?=(([A-Za-z][\w-]*)\s+([A-Za-z][\w-]*))\b)", sentence):   # (overlapping pairs)
        two, at = m.group(1), m.start()
        joined = m.group(2) + m.group(3)
        p = names.part(two) or own.get(norm(two)) or names.part(joined) or own.get(norm(joined)) \
            or own.get(norm(m.group(2) + "-" + m.group(3)))
        if p and not any(a <= at < a + len(w) for a, w, _p in out):
            out.append((at, two, p))
        elif p and any(a == at and norm(_p) != norm(p) for a, w, _p in out):
            out = [x for x in out if not (x[0] == at or at < x[0] < at + len(two))]
            out.append((at, two, p))                       # the two words name another part than the first alone
    return sorted(out)


def facts_of(unit: dict[str, Any], owner: str | None, names: Names, own: dict[str, str]) -> list[dict[str, Any]]:
    """The facts a unit states (without an LLM)."""
    from supagent.knowledge import diagrams as G
    from supagent.knowledge.docs import mask_secrets

    text, path = unit["text"] or "", unit["path"] or ""
    lang = unit["found"]["lang"]
    home = unit.get("doc_id") if unit.get("kind") == "file" else None   # (0.10.4) a repository's file: its repository
    source = "code" if lang in ("python", "java", "kotlin", "scala", "groovy", "javascript", "typescript", "go", "rust",
                                "csharp", "ruby", "php", "shell", "powershell") else \
        "doc" if lang in ("markdown", "text", "html") else "wiki" if unit["kind"] == "page" else "config"
    if unit["kind"] == "page":
        source = "wiki"
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    me = owner or ""

    def fact(subject: str, verb: str, obj: str, obj_kind: str, pos: int, src: str = source, conf: float = 0.9) -> None:
        if not subject or not obj or norm(subject) == norm(obj) or len(out) >= MAX_FACTS:
            return
        if verb == "routes_to" and any(h in norm(obj) for h in HOLDERS):
            return                                        # (0.10.5) what holds a VIP is never behind it
        key = (norm(subject), verb, norm(obj))
        if key in seen:
            return
        seen.add(key)
        line, quote = _line_of(text, pos)
        out.append({"subject": subject, "verb": verb, "obj": obj, "obj_kind": obj_kind, "line": line,
                    "quote": mask_secrets(quote)[0], "source": src, "confidence": conf})

    # aliases a unit declares for its owner (an OpenTelemetry service name, an artifact, a package)
    for other in unit["found"]["names"]:
        if me and norm(other) != norm(me):
            fact(me, "alias", other, "part", max(0, text.find(other)), conf=0.8)
    # addresses: who is called, which database, cache, where the logs go
    tool = unit["found"]["tool"]
    operation = "speaks" in unit and bool(re.search(r"(^|/)(tasks|handlers|meta|molecule|tests?)/", path)) and \
        lang == "yaml"                                    # an Ansible task's get_url, git, yum: a download, no link
    if source in ("code", "config") and tool != "prometheus" and not operation and not PACKAGE_FILES.search(path):
        scan = USERINFO_TPL.sub(lambda t: t.group(1) + "x" * len(t.group(2)), text)   # (0.10.5) "amqp://app:{{ pw
        for m in URL.finditer(scan):                                                   # }}@mq-01": mq-01
            scheme, host, port, first = _url_parts(m.group(1))
            line = _line_of(scan, m.start())[1]           # (the line as scanned: the address is found in it)
            ph = PLACEHOLDER_HOST.match(host)
            if ph and (names.part(ph.group(1) or ph.group(2)) or own.get(norm(ph.group(1) or ph.group(2)))):
                host = (ph.group(1) or ph.group(2)).lower()   # (0.10.4) http://${CATALOGUE_HOST}:8080: the catalogue
            if COMMENT.match(line) or host.isupper() or re.search(r"[{}%$<>]", host) or DOC_HOSTS.search(host.lower()) \
                    or NOT_ENDPOINT.search(m.group(1)) or SEE_ALSO.search(line[:max(0, line.find(m.group(1)))]) or \
                    FETCH_LINE.search(line) or (_is_public(host) and not EXTERNAL_KEY.search(
                        line[:max(0, line.find(m.group(1)))]) and not any(names.part(x) for x in host.lower().split("."))):
                continue                                # (0.10.4) a download, an image's label, a public site named
                #                                         under no endpoint's key (a privacy link, a terms page)
                continue                                # a comment (a license's address), a placeholder (HOST_IP), a
                #                                         template ({{ host }}), documentation or code (docs., github)
            if not host or host.lower() in ("localhost", "127.0.0.1", "0.0.0.0") or me == "" or \
                    re.search(r"xmlns|schemaLocation|\$schema|DOCTYPE|xsi:", text[max(0, m.start() - 40):m.start()]):
                continue
            verb, what = _endpoint_verb(scheme, port, line, text)
            if tool in SHIPPERS and verb == "calls":
                verb = "sends_to"                       # a shipper's outputs: where it sends what it collects
            if VIP_WORD.search(host) and not re.search(r"[{}%$<>]", host):
                svc = _vip_service(host, names, own)    # (0.10.4) a VIP in front of a service: the VIP routes to it,
                if svc:                                 # the caller calls the service; a VIP of no known service: the
                    fact(host.lower(), "routes_to", svc, "part", m.start(), conf=0.8)   # caller calls the VIP
                    if norm(svc) != norm(me):
                        fact(me, verb, svc, "part", m.start())
                else:
                    fact(me, verb, host.lower(), "vip", m.start())
                continue
            part = _host_part(host, names)
            served = names.parts.get(norm(part)) or names.alias.get(norm(part)) or own.get(norm(part)) \
                if not names.hosts.get(norm(part)) else None   # the host is a part (a workload, a service), no server
            if what == "database" and served:
                fact(me, verb, served, "database", m.start())     # (the path names a database inside it)
            elif what == "database" and first and re.fullmatch(r"[A-Za-z_][\w-]{1,62}", first):
                db_part = names.part(first) or first
                fact(me, verb, db_part, "database", m.start())
                fact(db_part, "runs_on", names.hosts.get(norm(host)) or names.hosts.get(norm(host.split(".")[0])) or
                     host, "host", m.start(), conf=0.7)
            else:
                fact(me, verb, part, what if what in ("database", "cache") else "part", m.start())
        for m in HOSTPORT.finditer(text):
            line = _line_of(text, m.start())[1]
            if URL.search(line) or me == "" or not (ENDPOINT_KEY.search(line) or LOG_WORDS.search(line)) or \
                    COMMENT.match(line) or m.group(1).isupper():
                continue
            host, port = m.group(1), int(m.group(2))
            if host.lower() in ("localhost", "0.0.0.0"):
                continue
            verb, what = _endpoint_verb("", port, line, text)
            fact(me, verb, _host_part(host, names), "part", m.start())
        for m in re.finditer(r"\b(?:Redis|StrictRedis|RedisCluster|Jedis\w*|createClient|from_url|Memcache\w*)\s*\("
                             r"[^)]*?(?:host\s*=\s*)?(?:os\.environ\.get\(\s*[\"']\w+[\"']\s*,\s*)?[\"']"
                             r"(?:redis://)?([A-Za-z][\w.-]+)", text):
            if me:
                verb = "reads_from" if re.search(r"\.(?:get|mget|hget|hgetall|exists)\(", text) and not \
                    re.search(r"\.(?:set|setex|hset|mset|lpush|rpush)\(", text) else \
                    "sends_to" if re.search(r"\.(?:set|setex|hset|mset)\(", text) else "uses"
                fact(me, verb, _host_part(m.group(1), names), "part", m.start(), conf=0.85)
        for m in re.finditer(r"\b([A-Z][A-Z0-9_]*?)_(?:DB_)?(HOST|NAME)\b[\"']?\s*[,:=]\s*(?:value:\s*)?[\"']?"
                             r"([A-Za-z][\w.-]+)", text):
            db_name = re.search(r"\b" + re.escape(m.group(1)) + r"_(?:DB_)?NAME\b[\"']?\s*[,:=]\s*(?:value:\s*)?[\"']?"
                                r"([A-Za-z][\w.-]+)", text) if m.group(2) == "HOST" else None
            if m.group(3).lower() in ("localhost", "127.0.0.1", "0.0.0.0"):
                continue                                  # the database beside it: no host's name
            if me and m.group(2) == "HOST" and re.search(r"DB|DATABASE|SQL", m.group(1) + m.group(0)):
                if db_name:                               # the database, on that host
                    fact(names.part(db_name.group(1)) or db_name.group(1), "runs_on",
                         names.hosts.get(norm(m.group(3))) or names.hosts.get(norm(m.group(3).split(".")[0])) or
                         m.group(3), "host", m.start(), conf=0.7)       # (0.10.5) db-01.example.net: db-01
                else:
                    fact(me, "uses", _host_part(m.group(3), names), "database", m.start(), conf=0.7)
            if me and m.group(2) == "NAME" and re.search(r"DB|DATABASE", m.group(0)):
                fact(me, "uses", names.part(m.group(3)) or m.group(3), "database", m.start(), conf=0.7)
    # (0.10.4) an address variable's default in code ("details" if os.environ.get("DETAILS_HOSTNAME") is None ...,
    # process.env.CATALOGUE_HOST || 'catalogue', System.getenv("RATINGS_HOSTNAME") == null ? "ratings" : ...)
    if source == "code" and me:
        for m in ENV_DEFAULT.finditer(text):
            line = _line_of(text, m.start())[1]
            for lit in re.findall(r"[\"']([A-Za-z][\w.-]*)[\"']", line):
                target = names.part(lit) or own.get(norm(lit))
                if target and norm(target) != norm(me) and not names.hosts.get(norm(lit)) and \
                        norm(lit) in norm(m.group(1)).replace("_", "-"):
                    verb = "uses" if STORE_WORDS.search(m.group(1)) else "calls"
                    fact(me, verb, target, "part", m.start(), conf=0.75)
    # metrics registered in code
    for pos, name, kind in _metric_names(text, lang):
        if me:
            fact(me, "emits", _metric_in_data(name, kind, names) or name, "metric", pos, conf=0.95)
    # a shipper's configuration: the indices it writes
    if tool in SHIPPERS:
        for m in re.finditer(r"(?im)(?<![\w.])(?:service\.name|\[service\]\[name\]|service_name|app)[\"']?\s*(?:=>|[:=])\s*"
                             r"[\"']([A-Za-z][\w.-]+)[\"']", text):
            fact(names.part(m.group(1)) or m.group(1), "sends_to", tool, "part", m.start(), conf=0.8)
        for m in re.finditer(r"(?im)^\s*(?:Logstash_Prefix|Index|logs_index|traces_index|index)(?![\w-])\s*(?:=>|[:=]|\s)"
                             r"\s*[\"']?([A-Za-z0-9_.%{}+*$-]+)[\"']?", text):
            raw = m.group(1)
            if re.search(r"(?im)^\s*Logstash_Format\s+On", text) and re.match(r"(?i)\s*Logstash_Prefix", m.group(0)):
                raw = raw + "-*"
            fact(tool, "writes", names.index(raw) or DATE_PART.sub("*", raw), "index", m.start())
        for m in re.finditer(r"(?im)^\s*index-prefix\s*:\s*([\w.-]+)", text):   # Jaeger: <prefix>-span-<date>
            fact(tool, "writes", names.index(m.group(1) + "-span-*") or m.group(1) + "-span-*", "index", m.start(), conf=0.7)
        for m in re.finditer(r"[?&](?:target|index)=([\w.*-]+)", text):
            fact(tool, "writes", names.index(m.group(1)) or m.group(1), "index", m.start(), conf=0.8)
        for m in re.finditer(r"(?im)^\s*Path\s+\S*?_(\w[\w-]*)_\*\.log", text):   # Kubernetes' container logs of a namespace
            fact(tool, "collects", f"namespace:{m.group(1)}", "namespace", m.start(), conf=0.8)
    # Prometheus' scrape jobs: what runs where, which exporter watches what
    if tool == "prometheus":
        live = re.sub(r"(?m)^[ \t]*#.*$", lambda c: " " * len(c.group(0)), text)   # (0.10.5) a target commented
        live = re.sub(r"\{\{.*?\}\}|\{%.*?%\}", lambda c: " " * len(c.group(0)), live)   # out is scraped by no one;
        for job in re.finditer(r"(?m)^\s*-\s*job_name:\s*[\"']?([\w.-]+)[\"']?([\s\S]*?)(?=^\s*-\s*job_name:|\Z)", live):
            body, base = job.group(2), job.start(2)        # (0.10.6) a template's expression and a label's value
            items = [(base + m.start(1) + x.start(1), x.group(1)) for m in re.finditer(r"targets:\s*\[([^\]]*)\]", body)
                     for x in re.finditer(r"([^,\s][^,]*?)\s*(?:,|$)", m.group(1))]   # ("instance: ...") are no
            items += [(base + m.start(1) + x.start(1), x.group(1)) for m in   # target: the targets' list only
                      re.finditer(r"(?m)targets:[ \t]*\n((?:[ \t]*-[^\n]*(?:\n|$))+)", body)
                      for x in re.finditer(r"(?m)^[ \t]*-[ \t]*(\S[^\n]*?)[ \t]*$", m.group(1))]
            for at, item in items:
                t = re.fullmatch(r"[\"']?([A-Za-z][\w.-]*)(?::(\d+))?[\"']?", item.strip())
                if not t or t.group(1) in ("http_2xx",) or t.group(1).lower() == "localhost":
                    continue
                fact(job.group(1), "scrapes", t.group(1), "host", at, conf=0.85)   # (0.10.5) on its own line
    # (0.10.4) a monitoring configuration: what is scraped, where the alerts go, what a dashboard tool reads; (0.10.6)
    # not Promtail's: its "scrape_configs" jobs, named after the services whose logs it reads, monitor nothing
    if lang == "yaml" and tool != "promtail" and re.search(r"scrape_configs|alertmanager|datasources|_targets\s*:|"
                                                           r"metricbeat\.modules|heartbeat\.monitors", text):
        for subj, verb, obj, pos in _monitoring(text, names, own, me or tool):
            fact(subj, verb, obj, "part", pos, conf=0.8)
    # (0.10.4) a VIP a configuration gives (orders_vip: 10.0.0.10, keepalived's virtual_ipaddress, vip_fqdn: ...):
    # the VIP routes to the part the variables are of (the key's prefix, else the file's part)
    if lang == "yaml" and re.search(r"(?i)vip|virtual_ip", text):
        for data in _yaml_docs(text):
            for kpath, leaf in _walk(data):
                if not kpath or not VIP_KEY.search(str(kpath[-1])) or not isinstance(leaf, (str, int)):
                    continue
                vip = _vip_name(str(leaf))
                head = re.sub(r"(?i)_?(?:vips?|virtual_ip\w*|vip_\w+)$", "", str(kpath[-1]))
                grouped = bool(head) and bool(names.hosts.get(norm(head))) and not names.service(head)
                svc = (names.service(head) or own.get(norm(head)) if head else None) or \
                    (None if grouped else (me or None))   # (0.10.5) "db_vip_address": a group's VIP, no service
                if vip and svc and norm(vip) != norm(svc):
                    fact(vip.lower(), "routes_to", svc, "part", max(0, text.find(str(leaf))), conf=0.8)
    for m in re.finditer(r"(?s)virtual_ipaddress\s*\{([^}]*)\}", text):
        for ip in IP_ADDR.findall(m.group(1)):
            if me:
                fact(ip, "routes_to", me, "part", m.start(), conf=0.8)
    # (0.10.4) a supervisor's checks (Monit: "check process postfix with pidfile ..."): what it watches
    for m in re.finditer(r"(?im)^\s*check\s+(?:process|program|host)\s+([A-Za-z][\w.-]*)", text):
        target = names.part(m.group(1)) or own.get(norm(m.group(1)))
        if me and target and norm(target) != norm(me) and not names.hosts.get(norm(m.group(1))):
            fact(me, "monitors", target, "part", m.start(), conf=0.8)
    # (0.10.4) a web server's upstreams in its own syntax (Caddy: "reverse_proxy grafana:3000", "proxy / app:8080")
    for m in re.finditer(r"(?im)^\s*(?:reverse_proxy(?:\s+/\S*)?|proxy\s+/\S*)\s+((?:[a-z0-9_.-]+:\d+[ \t]*)+)$", text):
        for hp in m.group(1).split():
            if me and hp.split(":")[0].lower() not in ("localhost", "127.0.0.1", "0.0.0.0"):
                fact(me, "calls", _host_part(hp, names), "part", m.start(), conf=0.8)
    # diagrams: drawn on a page (kept with it) or written in a text (Mermaid, PlantUML)
    edges = list((unit["meta"] or {}).get("diagram_edges") or [])
    for d in G.in_text(text):
        edges += d["edges"]
    def boxed(x: str) -> str:
        bare = re.sub(r"\s*\([^)]*\)\s*", " ", x).strip()
        known = names.part(x) or own.get(norm(x)) or names.part(bare) or own.get(norm(bare))
        if known:
            return known
        inside = [p for _a, w, p in _named(bare, names, own) if not names.hosts.get(norm(w))]
        if inside:                                        # a part named in the box, with its host or its role
            return inside[0]
        head = re.split(r"\s+on\s+|:\s|,\s", bare)[0].strip()
        return head or bare or x

    for a, b, label in edges:
        pa, pb = boxed(a), boxed(b)
        if norm(pa) in ACTORS or norm(pb) in ACTORS:
            continue                                      # the customers, the users: who uses the system, no part
        if norm(pa) in GENERIC_BOXES or norm(pb) in GENERIC_BOXES:
            continue                                      # (0.10.5) "Services --> OTel Collector": every service, no part
        verb = "uses" if re.search(r"\b(sql|jdbc|db|database|query)\b", label or "", re.I) else \
            "sends_to" if re.search(r"\blogs?\b|\bpublish|\bwrite", label or "", re.I) else "calls"
        if not (label or "").strip():                     # (0.10.6) an arrow with no word: what its tool does
            if norm(pa) in SCRAPERS:
                verb = "sends_to" if norm(pb) in ALERT_ROUTERS else "monitors"
            elif norm(pa) in DASHBOARDS:
                verb = "reads_from"
            elif norm(pa) in SHIPPERS | {"promtail", "fluentd"}:
                verb = "sends_to"
        pos = max(0, text.find(a))
        if verb == "calls" and FLOW_SOURCE.search(norm(pa)) and not FLOW_SOURCE.search(norm(pb)):
            fact(pb, "reads_from", pa, "part", pos, src="diagram", conf=0.85)   # (0.10.4) "queue --> worker": the
            continue                                      # worker takes from the queue; a store or a broker calls no one
        fact(pa, verb, pb, "part", pos, src="diagram", conf=0.85)
    # sentences of a document or a page: two parts and how they interact, a part's logs, its metrics
    if source in ("doc", "wiki"):
        unit_part = me or ""
        tools = {norm(t) for t, _rx in TOOLS}
        prose = text
        for t0, header, rows in _tables(text):
            roles = [next((v for v, rx in COLUMNS if rx.search(h)), None) for h in header]
            vcol = next((i for i, h in enumerate(header) if VIP_TEXT.search(h)), None)
            if vcol is None and any(HOLDER_TEXT.search(h) for h in header):   # (0.10.6) "Name | IP | Target service |
                vcol = next((i for i, h in enumerate(header) if not HOLDER_TEXT.search(h) and 2 * sum(   # Keepalived
                    1 for _r, c in rows if i < len(c) and (ADDRESS_NAME.fullmatch(c[i].strip(" `*").lower()) or   # on":
                                                           IP_ADDR.fullmatch(c[i].strip(" `*")))) >= len(rows)), None)
            if vcol is not None:                          # (0.10.4) "VIP | Service | Servers": what each VIP fronts
                for r0, cells in rows:
                    vip = _vip_name(cells[vcol]) if vcol < len(cells) else None
                    if not vip:
                        continue
                    for i, cell in enumerate(cells):
                        if i == vcol:
                            continue
                        for value in [v.strip() for v in re.split(r",|;|\band\b", cell) if v.strip()][:12]:
                            value = re.sub(r"\s*\(.*?\)", "", value).strip()
                            if names.hosts.get(norm(value)) or (HOST_SHAPE.fullmatch(value) and not
                                                                 (names.part(value) or own.get(norm(value)))):
                                fact(names.hosts.get(norm(value)) or value, "in_group", vip.lower(), "vip", r0, conf=0.75)
                            elif names.part(value) or own.get(norm(value)):
                                fact(vip.lower(), "routes_to", names.part(value) or own.get(norm(value)), "part", r0,
                                     conf=0.75)
                continue
            for r0, cells in rows:
                first = cells[0] if cells else ""
                if roles and roles[0] == "runs_on" and not (names.part(first) and not names.hosts.get(norm(first))) \
                        and not own.get(norm(first)) and re.fullmatch(r"[A-Za-z0-9][\w.-]*", first or "") and \
                        not PLATFORMS.match(first) and not EVERY_SERVER.fullmatch(first):
                    # (0.10.4) a table of hosts ("Host | Role | Services"): what its parts' column names runs there
                    host = names.hosts.get(norm(first)) or first
                    for h, cell in zip(header[1:], cells[1:]):
                        if not PARTS_COLUMN.search(h) or COLUMNS[0][1].search(h):
                            continue
                        for value in [v.strip() for v in re.split(r",|;|\band\b", cell) if v.strip()][:12]:
                            value = re.sub(r"\s*\(.*?\)", "", value).strip()
                            p = names.part(value) or own.get(norm(value))
                            if p and not names.hosts.get(norm(value)):
                                fact(p, "runs_on", host, "host", r0, conf=0.75)
                    continue
                part = names.service(first) or own.get(norm(first)) or _page_owner(first, names, own)
                if not part:
                    continue
                if not (names.service(first) or own.get(norm(first))):   # (0.10.4) a qualified name: which one
                    others = [names.part(re.sub(r"\s*\(.*?\)", "", v).strip()) for c in cells[1:]
                              for v in re.split(r",|;|\band\b", c)]
                    part = _qualified(first, part, names, [o for o in others if o])
                for role, cell in zip(roles[1:], cells[1:]):
                    for value in [v.strip() for v in re.split(r",|;|\band\b", cell) if v.strip()][:6]:
                        if not role or not re.search(r"\w", value):
                            continue
                        if role == "runs_on":
                            if PLATFORMS.match(value) or EVERY_SERVER.fullmatch(value):
                                continue                          # Kubernetes, a cloud, "all": where, but no host
                            fact(part, "runs_on", names.hosts.get(norm(value)) or re.sub(r"\s*\(.*\)", "", value),
                                 "host", r0, conf=0.75)
                        elif role in ("logs_to", "watched_by"):
                            obj = names.index(value) if role == "logs_to" else names.metric(value)
                            if obj:
                                fact(part, role, obj, "index" if role == "logs_to" else "metric", r0, conf=0.75)
                        elif role == "calls":
                            fact(part, "calls", names.part(value) or own.get(norm(value)) or value, "part", r0, conf=0.7)
                        elif role == "monitors":                  # (0.10.4) "Scrapes: ceph-mgr (port 9283)": a known part
                            target = names.part(re.sub(r"\s*\(.*?\)", "", value).strip()) or \
                                own.get(norm(re.sub(r"\s*\(.*?\)", "", value)))
                            if target and norm(target) != norm(part):
                                fact(part, "monitors", target, "part", r0, conf=0.7)
                        else:
                            fact(part, role, value, "attribute", r0, conf=0.75)
            for r0, cells in [(t0, header)] + rows:   # a table's rows are not sentences
                line_end = prose.find("\n", r0)
                prose = prose[:r0] + " " * ((line_end if line_end >= 0 else len(prose)) - r0) + prose[line_end:] \
                    if line_end >= 0 else prose[:r0]
        # (0.10.4) arrows between parts ("frontend → checkout → payment", "Grafana ← Prometheus (its data source)")
        for lm in re.finditer(r"[^\n;]+", prose):           # (a list of edges "A -> B; C -> D": each its own)
            line = lm.group(0)
            if not ARROW.search(line):
                continue
            segs = ARROW.split(line)
            label = (re.search(r"\(([^)]*)\)[\s.;]*$", line) or [None, ""])[1] or ""
            named = [[p for _a, w, p in _named(re.sub(r"\([^)]*\)", lambda x: " " * len(x.group(0)), seg), names, own,
                                               home)
                      if not names.hosts.get(norm(w))] for seg in segs[0::2]]
            for k in range(len(named) - 1):
                a, b = (named[k][-1] if named[k] else None), (named[k + 1][0] if named[k + 1] else None)
                if not a or not b or norm(a) == norm(b) or NEGATED.search(segs[2 * k] + " " + segs[2 * k + 2]):
                    continue
                if segs[2 * k + 1] in ("←", "⟵", "<-", "<--"):
                    a, b = b, a                               # written backwards: b's flow goes to a
                if SOURCE_LABEL.search(label) and k == len(named) - 2:
                    src = named[k + 1][0]                     # "X ← Y (its data source)": X reads from Y
                    fact(a if src == b else b, "reads_from", src, "part", lm.start(), conf=0.65)
                elif FLOW_SOURCE.search(norm(a)) and not FLOW_SOURCE.search(norm(b)) and not FLOW_LABEL.search(label):
                    fact(b, "reads_from", a, "part", lm.start(), conf=0.65)   # "queue → worker"
                else:
                    fact(a, "sends_to" if FLOW_LABEL.search(label) else "calls", b, "part", lm.start(), conf=0.65)
        for start, s in _sentences(prose):
            found = _named(s, names, own, home)
            found = [x for x in found if not any(y is not x and abs(y[0] - x[0]) <= len(x[1]) + 16 and
                                                 norm(x[2]) != norm(y[2]) and norm(x[2]) in norm(y[2]) and
                                                 not (names.hosts.get(norm(y[1])) and not names.service(y[1]))
                                                 for y in found)]   # (0.10.5) a server named after its service
            #                                     ("the media relays (sfu) run on sfu-node-01") hides no part's name
            depth = _depths(s)
            outside = [(at, w, p) for at, w, p in found if depth[at] == 0]
            # the sentence's subject: its first part outside brackets near its start, else the unit's own part
            # (a README speaks of its repository's service, a page of the part its title names)
            heads = [x for x in outside if x[0] < 40 and not OBJECT_OF.search(s[max(0, x[0] - 24):x[0]])]
            lead = heads[0] if heads and heads[0] is outside[0] and not re.match(r"(?i)\s*(it|its|they|their)\b", s) \
                else None                                 # ("the server runs an Nginx webserver": no Nginx's sentence)
            subject = lead[2] if lead else unit_part
            cues = sorted([(c.start(), c.end(), verb) for verb, rx in CUES for c in rx.finditer(s)])
            spans = [(at, at + len(w)) for at, w, _p in found]   # (0.10.6) "photo-store": a name, not "stores"
            cues = [c for c in cues if not any(a <= c[0] < b for a, b in spans)]
            for k, (c0, c1, verb) in enumerate(cues):
                stop = next((c[0] for c in cues[k + 1:] if c[0] >= c1), len(s))   # (0.10.4) not a cue inside this one
                bound = CLAUSE_END.search(s, c1)                  # "... and is published by ...": another clause
                stop = min(stop, bound.start()) if bound else stop
                for x in outside:                                 # (0.10.4) "... on the queue and dispatch takes it
                    if c1 <= x[0] < stop and re.search(r"(?:,\s*|\s)and\s+(?:the\s+)?$", s[:x[0]]) and \
                            (NEXT_VERB.match(s, x[0] + len(x[1])) or VERB_OBJECT.match(s, x[0] + len(x[1]))):
                        stop = re.search(r"(?:,\s*|\s)and\s+(?:the\s+)?$", s[:x[0]]).start()
                        break
                if verb == "calls" and re.match(r"(?i)(calls?|requests?|quer(y|ies))\b", s[c0:c1]) and (
                        re.match(r"\s+(?:to|made|from|are|were|is|per|for|of)\b", s[c1:]) or
                        re.search(r"(?i)\b(a|an|the|each|every|this|that|any|one|per|its|their|our|your|incoming|"
                                  r"outgoing|first|next|last|single|http|https|rest|grpc|post|get|put)\s+$", s[:c0])):
                    continue                                      # (0.10.4) a call as a thing: "a POST call to X",
                    #                                               "reloaded on each request"
                if re.match(r"(?i)checks\b", s[c0:c1]) and not (
                        re.search(r"\b(?:it|which|that|also|then|and|regularly|periodically)\s+$", s[:c0], re.I) or
                        any(x[0] + len(x[1]) >= c0 - 2 for x in outside if x[0] < c0)):
                    continue                                      # (0.10.4) "the bootstrap checks", "health checks"
                if re.search(r"\beither\b", s[c0:stop], re.I):
                    continue                                      # (0.10.4) "forwards them either to A or to B"
                inner = depth[c0] > 0
                before = [x for x in (found if inner else outside) if x[0] < c0 and (depth[x[0]] < depth[c0] or not inner)]
                # inside brackets ("(which calls X)") the clause speaks of the part just before them
                subj = before[-1][2] if inner and before else subject
                if not inner and lead and lead[0] > c0:           # (0.10.4) a sentence's subject comes before its
                    opens = re.fullmatch(r"[\s*\-•>]*(?:(?:it|also|then|and)\s+)?", s[:c0], re.I)   # verb: an
                    subj = unit_part if opens and re.match(r"\w+s\b", s[c0:c1]) else None   # unknown one is no one;
                    #   "Reads the orders from Kafka" (a README's own service) yes, "Put it back in X" (a step) no
                said = None                                   # (0.10.4) where the subject is named in the sentence
                if not inner:
                    colon = s.rfind(": ", 0, c0)              # "look at X first: the checkout calls the payment ..."
                    head = re.match(r"\s*(?:(?:the|a|an|its|our|their|this|that|our|each|every)\s+)?", s[colon + 2:]) \
                        if colon >= 0 else None
                    clause = [x for x in outside if head and x[0] == colon + 2 + head.end() and x[0] < c0 and
                              not names.hosts.get(norm(x[1]))]  # (the part that opens the clause: "...: it takes the
                    #                                             basket from the frontend" has none)
                    which = [m for m in re.finditer(r"\bwhich\b", s[:c0]) if depth[m.start()] == 0]
                    adjacent = [x for x in outside if x[0] < c0 and c0 - (x[0] + len(x[1])) <= 2 and
                                not s[x[0] + len(x[1]):c0].strip() and not names.hosts.get(norm(x[1]))]   # (0.10.4)
                    #   "..., and Heartbeat pings X": Heartbeat; "takes it from the frontend, reserves ...": not it
                    if adjacent and not OBJECT_OF.search(s[max(0, adjacent[-1][0] - 24):adjacent[-1][0]]):
                        said = adjacent[-1]
                    elif clause:
                        said = clause[0]
                    elif which:                               # "A calls B, which calls C": B calls C
                        prev = [x for x in outside if x[0] < which[-1].start() and not names.hosts.get(norm(x[1])) and
                                re.fullmatch(r"[\s,]*", s[x[0] + len(x[1]):which[-1].start()])]
                        said = prev[-1] if prev else None
                    if said:                                  # (0.10.4) "the storage Prometheus scrapes them with
                        subj = _qualified(s[max(0, said[0] - 24):said[0]] + " " + said[1], said[2], names,   # the
                                          [p for at, w, p in found if at >= c1]) or said[2]   # node exporter": which one
                    else:
                        said = next((x for x in outside if x[2] == subj and x[0] < c0), None)
                scope = said[0] if said else max(0, s.rfind(": ", 0, c0) + 1)
                scope = max(scope, s.rfind(": ", scope, c0) + 1, s.rfind("; ", scope, c0) + 1)   # (0.10.5) "X never
                if NEGATED.search(s[scope:c1]):          # talks to a database: they ask Y": the "never" is not Y's
                    if subj and verb in DENIABLE:             # (0.10.4) "X never calls Y", "X used to read Y": no
                        end = min([i for i in (s.find(":", c1), s.find(";", c1)) if i >= 0] + [stop])   # (0.10.5) in
                        #   its clause: "never talk to a database directly: they ask quotes" denies no quotes
                        obj = next((x for x in outside if c1 <= x[0] < end and norm(x[2]) != norm(subj) and   # link;
                                    (verb == "runs_on") == bool(names.hosts.get(norm(x[1])))), None)   # (0.10.5) a
                        if obj:                                   # denied fact: it proposes removing such a link
                            fact(subj, "not_" + verb, obj[2], "host" if verb == "runs_on" else "part", start + c0,
                                 conf=0.6)
                    continue
                if verb == "runs_on":
                    if s[c0:c1].lstrip().startswith("(") and s.find(")", c1) >= 0:   # (0.10.5) "X (... on host)":
                        stop = min(stop, s.find(")", c1))         # the hosts in its brackets ("db[(shopdb on dbsrv1)]")
                    end = RUNS_ON_END.search(s, c1, stop)         # (0.10.6) "... is responsible for reading from
                    stop = end.start() if end else stop           # the DB": not where it runs
                    hosts = [w for at, w, p in found if c0 < at < stop and names.hosts.get(norm(w))] or \
                        [w for at, w, p in found if c0 < at < stop and re.search(r"\d", w)][:1]
                    if not hosts and not s[c0:c1].lstrip().startswith("("):   # (0.10.4) hosts no inventory names
                        hosts = _host_tokens(s[c1:stop])
                    whos = []
                    if s[c0:c1].lstrip().startswith("("):        # "X (... on host)": X is the name just before
                        who = next((p for at, w, p in found if at + len(w) >= c0 - 2 and at < c0), None)
                    else:
                        near = [x for x in found if x[0] < c0]
                        last = near[-1] if near else None        # (0.10.4) "the recorder (rec) runs on": rec
                        if last and depth[last[0]] > 0 and re.fullmatch(r"\)\s*", s[last[0] + len(last[1]):c0]) and \
                                s.rfind("(", 0, last[0]) >= 0 and not s[s.rfind("(", 0, last[0]) + 1:last[0]].strip():
                            who = last[2]                         # (only a name in the brackets: "(its old name in
                            #                                       the log tool)" is no other name of the part)
                        else:                                    # (0.10.4) else a name in brackets, the only one
                            who = next((p for at, w, p in reversed(outside) if at < c0), None) or \
                                next((p for at, w, p in found if at < c0 and depth[at] > 0 and not names.hosts.get(norm(w))
                                      and re.fullmatch(r"\(\s*" + re.escape(w) + r"\s*\)",
                                                       s[s.rfind("(", 0, at):s.find(")", at) + 1])), None) or subj
                        # (0.10.4) "the web, chat and focus containers run on ...": each subject joined to it
                        chain = [x for x in outside if x[0] < c0]
                        k = max((i for i, x in enumerate(chain) if x[2] == who), default=None)
                        while k is not None and k >= 1:
                            prev = chain[k - 1]
                            gap = s[prev[0] + len(prev[1]):chain[k][0]]
                            if not re.fullmatch(r"\s*(?:,|,?\s+and|,?\s+&)\s+(?:the\s+)?", gap, re.I):
                                break
                            whos.append(prev[2])
                            k -= 1
                    if hosts and names.homes:                     # (0.10.4) "the shop Grafana ... on shop-obs-01"
                        ctx = [names.hosts.get(norm(h)) or h for h in hosts] + [p for at, w, p in found if at >= c1]
                        mention = {p: w for at, w, p in found if at < c0}
                        fix = lambda q: _qualified(s[max(0, s.find(mention.get(q, q)) - 24):s.find(mention.get(q, q))]
                                                   + " " + mention.get(q, q), q, names, ctx) if q else q
                        who, whos = fix(who), [fix(x) for x in whos]
                    for host in hosts[:12]:                       # "runs on web1, web2 and web3": each of them
                        for w0 in ([who] if who else []) + whos:
                            fact(w0, "runs_on", names.hosts.get(norm(host)) or host, "host", start + c0, conf=0.7)
                    continue
                if subj and names.hosts.get(norm(subj)) and not names.service(subj) and not own.get(norm(subj)):
                    continue                                      # (0.10.5) a server, a group: where parts run, no
                    #                                               flow's subject ("Backup store is MinIO")
                if verb == "monitors" and not (lead and lead[0] < c0) and not said:
                    continue                                      # "Check the ...": a step of a runbook, no subject
                objs = [p for at, w, p in found if c1 <= at < stop and (depth[at] == depth[c0])
                        and norm(p) != norm(subj or "") and not names.hosts.get(norm(w))]
                for o in list(dict.fromkeys(objs))[:8]:           # (0.10.4) six services in a list: each of them
                    at_o = next((at for at, w, p in found if p == o and c1 <= at < stop), None)
                    if verb == "sends_to" and re.match(r"(?i)(stores?|keeps?|holds?)\b(?!.*\b(in|into|to)\b)",
                                                       s[c0:c1]) and at_o is not None and re.search(r"\bof\b",
                                                                                                    s[c1:at_o]):
                        fact(o, "uses", subj, "part", start + c0, conf=0.6)   # "a cache stores the sessions of X"
                    else:
                        fact(subj, verb, o, "part", start + c0, conf=0.6)
            # (0.10.4) a VIP in a sentence: "the VIP orders-vip.example.com (10.0.0.10) points to the orders service on
            # app-01 and app-02": it routes to the parts named, the hosts named are behind it
            if VIP_TEXT.search(s) and VIP_CUE.search(s) and not NEGATED.search(s) and len(s) <= 300 and \
                    not DIAGRAM_SYNTAX.search(s) and " | " not in s:   # (0.10.6) a sentence: not a diagram's
                #                                             source, a table's row nor a whole page
                bare = re.sub(r"(?i)(?<![\w.-])(?:VIPs?|virtual IPs?)(?![\w.-])", " ", s)   # the word alone out
                vtok = re.search(r"(?i)(?<![\w.-])[\w.-]*vip[\w.-]*[\w]", bare) or IP_ADDR.search(s)
                vip = _vip_name(vtok.group(0)) if vtok else None
                if vip:
                    for at, w, p in outside:
                        if norm(w) == norm(vip) or norm(p) == norm(vip):
                            continue
                        if names.hosts.get(norm(w)):
                            fact(names.hosts[norm(w)], "in_group", vip.lower(), "vip", start + at, conf=0.65)
                        else:
                            fact(vip.lower(), "routes_to", p, "part", start + at, conf=0.65)
                    for h in _host_tokens(s):
                        if not names.part(h) and norm(h) != norm(vip) and not VIP_WORD.search(h):
                            fact(h, "in_group", vip.lower(), "vip", start + s.find(h), conf=0.65)
            # (0.10.4) a route: "requests go through the proxy to the app server" (the proxy calls the app server),
            # "the app server charges the cards through the payment gateway" (it calls the gateway)
            for rm in ROUTE.finditer(s):
                if depth[rm.start()] > 0:
                    continue
                via = next((x for x in outside if rm.end() <= x[0] <= rm.end() + 30 and not names.hosts.get(norm(x[1]))),
                           None)
                if not via:
                    continue
                bound = CLAUSE_END.search(s, via[0] + len(via[1]))
                end = bound.start() if bound else len(s)
                to = next((x for x in outside if via[0] < x[0] < end and not names.hosts.get(norm(x[1])) and
                           ROUTE_TO.search(s[via[0] + len(via[1]):x[0]][-40:])), None)
                kind = "sends_to" if FLOW_LABEL.search(s) else "calls"
                head = lead if lead and lead[0] < rm.start() else None
                if NEGATED.search(s[head[0] if head else 0:rm.start()]):
                    continue
                if to and norm(to[2]) != norm(via[2]):
                    fact(via[2], kind, to[2], "part", start + rm.start(), conf=0.6)
                elif not to and head and norm(head[2]) != norm(via[2]):
                    if IMPERATIVE.match(s):                   # (0.10.5) "Query Loki via Grafana": a step, Loki the
                        continue                              # object (no flow from it)
                    if RECEIVES.search(s[head[0] + len(head[1]):rm.start()]):   # (0.10.5) "Loki collects the logs
                        fact(via[2], "sends_to", head[2], "part", start + rm.start(), conf=0.6)   # via promtail"
                    else:
                        fact(head[2], kind, via[2], "part", start + rm.start(), conf=0.6)
            # "HAProxy on lb1", "the mongos routers on mongo1 and mongo2": where a part runs
            for at, w, p in outside:
                if names.hosts.get(norm(w)):
                    continue
                m = ON_HOSTS.match(s, at + len(w))
                if not m:
                    continue
                for h in re.split(r"\s*,\s*|\s+and\s+", m.group("hosts")):
                    h = re.sub(r"(?i)^the\s+|\s+(host|server|machine|node)$", "", h.strip().rstrip(".,;:"))
                    if names.hosts.get(norm(h)):
                        fact(p, "runs_on", names.hosts[norm(h)], "host", start + at, conf=0.65)
            # the passive voice: "the orders are published by the ledger writer to the archive", "X is read by Y"
            for m in PASSIVE.finditer(s):
                after = [(a, w, p) for a, w, p in found if a >= m.end() - 1]
                if not after:
                    continue
                agent = after[0]
                rest = s[agent[0] + len(agent[1]):]
                target = next((p for a, w, p in after[1:] if re.search(r"\b(to|into|in|from|through|on)\b",
                                                                       s[agent[0] + len(agent[1]):a])), None)
                lead_p = next((p for a, w, p in found if a < m.start()), None)
                kind = PASSIVE_VERBS.get(m.group("verb").lower(), "calls")
                if kind == "sends_to" and not target:
                    kind, target = "calls", lead_p                # "Kibana is published by nginx"
                obj = target or lead_p
                if obj and norm(obj) != norm(agent[2]) and not names.hosts.get(norm(obj)):
                    fact(agent[2], kind, obj, "part", start + m.start(), conf=0.6)
                del rest
            # the indices a part's logs are in (a tool writes them, it does not log there)
            if LOGS_CUE.search(s) and subject and norm(subject) not in tools:
                for m in re.finditer(r"[`'\"]?([a-z0-9][\w.-]*[\w*](?:-\*)?)[`'\"]?", s):
                    idx = names.index(m.group(1))
                    if idx:
                        fact(subject, "logs_to", idx, "index", start + m.start(), conf=0.7)
            # the metrics a part emits, or that watch it (a sentence about metrics, not a query)
            if METRIC_CUE.search(s) and not QUERY_LIKE.search(s):
                for m in re.finditer(r"\b([a-zA-Z_][a-zA-Z0-9_]*_[a-zA-Z0-9_]+|[a-z]+[A-Z][A-Za-z0-9]+|up)\b", s):
                    met = names.metric(m.group(1))
                    who = subject
                    if depth[m.start()] > 0:                 # "(its counters: x)": the name before the bracket
                        before = [p for at, w, p in found if at < m.start() and depth[at] < depth[m.start()]]
                        who = before[-1] if before else subject
                    if met and who and norm(who) not in tools:
                        verb = "watched_by" if met.startswith(INFRA_PREFIXES) or not (lead or unit_part) else "emits"
                        fact(who, verb, met, "metric", start + m.start(), conf=0.7)
    return out


# --------------------------------------------------------------------------------------------------------------- #
# the run: units read again when their text (or the names known) changed
# --------------------------------------------------------------------------------------------------------------- #
def _repo_name(doc: Any) -> str | None:
    from supagent.knowledge.docs import bitbucket_target

    t = bitbucket_target(doc.url or "") if doc.kind == "url" else None
    return t["name"].rsplit("/", 1)[-1] if t else None


def _qualified(raw: str, part: str | None, names: Names, context: list[str]) -> str | None:
    """(0.10.4) "the storage Prometheus", "the clinic Prometheus": a name several parts end with or begin with
    (ceph-prometheus, prometheus-server, prometheus) is the one declared in the same repository as the other parts
    the row or the sentence names (what it scrapes, what it calls), else the one whose name holds the qualifier;
    otherwise the name as it was resolved."""
    if not part or not names.homes:
        return part
    head = norm(part)
    cands = sorted({p for p in names.parts.values() if norm(p) == head or norm(p).startswith(head + "-") or
                    norm(p).endswith("-" + head) or ("-" + head + "-") in norm(p)}, key=str.lower)
    if len(cands) < 2:
        return part
    docs = set()
    for c in context:
        docs |= names.homes.get(norm(c), set())
    if docs:
        same = [c for c in cands if names.homes.get(norm(c), set()) & docs]
        if len(same) == 1:
            return same[0]
    words = set(re.findall(r"[a-z]{3,}", norm(raw))) - {head, "the", "its", "our", "their"}
    if words:
        named = [c for c in cands if words & set(re.findall(r"[a-z]{3,}", norm(c)))]
        if len(named) == 1:
            return named[0]
    return part


def _page_owner(title: str, names: Names, own: dict[str, str]) -> str | None:
    """The part a page is about: its title names it ("Billing service" -> billing)."""
    t = re.sub(r"\b(service|services|application|app|database|db|server|system|component|page|overview)\b", " ",
               title or "", flags=re.I)
    for cand in [title or ""] + [w for w in re.split(r"[\s/|:,()-]+", t) if w]:
        p = names.service(cand) or own.get(norm(cand))     # (0.10.5) "storage Prometheus": the storage group is
        if p:                                              # where it runs; once approved, it is no page's subject
            return p
    return None


class _Catalog:
    """The catalog's guides, notes, rules, definitions and glossaries, read as one more document (0.10: the user named
    the catalog with the wiki and the code): each entry a unit (entry:<id>)."""

    id = None
    kind = "catalog"
    url = ""
    title = "Catalog"
    content = ""
    pages = None
    enabled = True


CATALOG_KINDS = ("guide", "note", "rule", "definition", "glossary")


def _catalog_units() -> list[dict[str, Any]]:
    from supagent.knowledge.docs import mask_secrets
    from supagent.models import Entry

    out = []
    for e in db.session.query(Entry).filter(Entry.deleted_at.is_(None), Entry.enabled.is_(True),
                                            Entry.classification.in_(CATALOG_KINDS)):
        text = mask_secrets(e.content or "")[0]
        if text.strip():
            out.append({"ukey": f"entry:{e.id}", "kind": "document", "title": e.title or "", "url": "",
                        "path": f"catalog/{e.id}.md", "text": text, "meta": {}})
    return out


def run(reason: str = "manual", llm: bool = False) -> dict[str, Any]:
    """Read the units of every document whose text changed (all of them when the names known changed) and keep their
    facts; the units of a document gone are removed with it. With the LLM (`llm`, or knowledge.understand_llm): the
    pages and prose documents read by it too (understand_llm.py), knowledge.llm_units of them per run at most."""
    from supagent import settings
    from supagent.knowledge import understand_llm as L
    from supagent.models import Doc, KFact, KUnit, Meta

    use_llm = llm or L.enabled()
    budget = [int(settings.get("knowledge.llm_units") or 0) if use_llm else 0]

    names = known_names()
    docs: list[Any] = list(db.session.query(Doc).filter(Doc.enabled.is_(True), Doc.content.isnot(None)))
    if settings.get("knowledge.understand_catalog"):
        docs.append(_Catalog())                       # the catalog's entries (doc_id NULL, ukey entry:<id>)
    per_doc: dict[int, list[dict[str, Any]]] = {}
    kinds_of: dict[int, dict[str, Any]] = {}
    own: dict[str, str] = {}                        # the documents' own parts (owners, workloads, tools, aliases)
    late_aliases: list[tuple[str, str]] = []
    doc_owner: dict[int, str | None] = {}
    stored = {(r.doc_id, r.ukey): (r.chash, (r.outline or {}).get("found"))
              for r in db.session.query(KUnit.doc_id, KUnit.ukey, KUnit.chash, KUnit.outline)}
    for d in docs:
        us = _catalog_units() if isinstance(d, _Catalog) else units_of(d)
        for u in us:                                 # a unit unchanged: what it declares, as read last time
            u["chash"] = _hash(u["text"])
            u["doc_id"] = d.id if not isinstance(d, _Catalog) else None
            was = stored.get((d.id, u["ukey"][:512]))
            u["found"] = was[1] if was and was[0] == u["chash"] and was[1] else discover(u)
        per_doc[d.id] = us
        if not isinstance(d, _Catalog):               # what the repository states across its files (Ansible, manifests)
            from supagent.knowledge import projects as PJ

            try:
                across, declared = PJ.facts(us)
            except Exception as ex:  # pylint: disable=broad-except   (the files' own facts stay)
                log.warning("supagent understand: reading %s across its files: %s", d.id, str(ex)[:300])
                across, declared = {}, {}
            if declared.get("kinds"):                     # what the repository is: its Context page says it
                kinds_of[d.id] = declared["kinds"]
            speaks = declared.get("owners") or {}
            built = declared.get("built") or {}
            for u in us:
                u["across"] = across.get(u["path"] or "", []) if u["path"] else []
                if u["path"] and u["path"] in speaks:
                    u["speaks"] = speaks[u["path"]]       # an Ansible file: its role's part, or nobody
                elif u["path"] and u["path"] in built:
                    u["built"] = built[u["path"]]         # (0.10.4) a file a Compose service is built from
            for name in declared.get("parts", []):
                own.setdefault(norm(name), names.part(name) or name)
                names.homes.setdefault(norm(names.part(name) or name), set()).add(d.id)
            for other, name in (declared.get("aliases") or {}).items():   # (0.10.4) a role's services: its names,
                late_aliases.append((other, name))           # once every repository's parts are known
            for h in declared.get("hosts", []):
                names.hosts.setdefault(norm(h), h)
                names.homes.setdefault(norm(h), set()).add(d.id)        # (0.10.4) a host's repository too
        repo = _repo_name(d)
        owner, aliases = owners(us, repo, names) if repo else (None, [])
        if any("speaks" in u for u in us):
            owner, aliases = None, []                     # an Ansible repository: its roles are its parts
        doc_owner[d.id] = owner
        for name in [owner] + [w["name"] for u in us for w in u["found"]["workloads"]] + \
                [u["found"]["tool"] for u in us if u["found"]["tool"]]:
            if name:
                own.setdefault(norm(name), names.part(name) or name)
        if owner:
            for a in aliases:
                own.setdefault(norm(a), names.part(owner) or owner)
    for other, name in late_aliases:                     # (0.10.4) never over a name a repository declares as a part
        if norm(other) not in own and not names.part(other):
            own[norm(other)] = names.part(name) or own.get(norm(name)) or name
            names.alias.setdefault(norm(other), own[norm(other)])   # (an address's host by it too)
    for n, shown in own.items():
        if not names.part(n):
            names.add_part(shown)
    names_hash = _hash(json.dumps([READER, sorted(names.parts), sorted(names.alias), sorted(names.hosts),
                                   sorted(names.indices),
                                   sorted(names.metrics), sorted(own.items())]))
    meta = db.session.get(Meta, "understand_names")
    everything = meta is None or meta.value != names_hash
    stats: dict[str, Any] = defaultdict(int)
    known = sorted({*names.parts.values(), *own.values()}, key=str.lower)
    data_names = sorted({*names.indices.values(), *names.metrics.values()}, key=str.lower)

    def data_object(raw: str, kind: str) -> str | None:
        return names.index(raw) if kind == "index" else (names.metric(raw) or names.metric(raw.strip().split("{")[0]))

    def resolve(raw: str) -> str | None:
        return names.part(raw) or own.get(norm(raw))

    def llm_facts(row: Any, u: dict[str, Any], before: dict[str, Any] | None) -> None:
        """The links the LLM reads in the unit (read again only when its text changed), checked, kept as facts."""
        from supagent.knowledge.projects import test_file

        if not use_llm or not L.eligible(u["kind"], u["found"]["lang"]) or \
                (u["kind"] == "file" and test_file(u["path"] or "")):   # (0.10.6) no fact of a test: no call
            return
        was = before if isinstance(before, dict) and before.get("hash") == u["chash"] else None
        if was is None:
            if budget[0] <= 0:
                stats["llm_left_for_next_run"] += 1
                return
            budget[0] -= 1
            try:
                links = L.read_links(u["text"] or "", known, data_names=data_names)
            except Exception:  # pylint: disable=broad-except   (read again at the next run)
                stats["llm_errors"] += 1
                return
            was = {"hash": u["chash"], "links": links}
            stats["llm_read"] += 1
        row.outline = {**(row.outline or {}), "llm": was}
        have = {(f.subject.lower(), f.verb, f.obj.lower()) for f in db.session.query(KFact).filter(
            KFact.unit_id == row.id, KFact.source != "llm")}
        db.session.query(KFact).filter(KFact.unit_id == row.id, KFact.source == "llm").delete(synchronize_session=False)
        for f in L.checked(was["links"], u["text"] or "", resolve,
                           lambda raw: bool(names.index(raw) or names.metric(raw))) + \
                L.data_checked(was["links"], u["text"] or "", resolve, data_object):
            if (f["subject"].lower(), f["verb"], f["obj"].lower()) in have:
                continue                                 # the rules read it already
            line, _q = _line_of(u["text"] or "", f["pos"])
            from supagent.knowledge.docs import mask_secrets

            db.session.add(KFact(unit_id=row.id, subject=f["subject"][:255], verb=f["verb"], obj=f["obj"][:512],
                                 obj_kind=f["obj_kind"], line=line, quote=mask_secrets(f["quote"])[0][:400],
                                 source="llm", confidence=L.CONFIDENCE))
            stats["llm_facts"] += 1
    for d in docs:
        have = {u.ukey: u for u in db.session.query(KUnit).filter(KUnit.doc_id == d.id)}
        keep = set()
        for u in per_doc[d.id]:
            keep.add(u["ukey"][:512])
            ch = u["chash"]
            row = have.get(u["ukey"][:512])
            across_hash = _hash(json.dumps([u.get("across") or [], u.get("speaks")] + ([u["built"]] if u.get("built")
                                                                                     else []), sort_keys=True))
            if row is not None and row.chash == ch and not everything and \
                    (row.outline or {}).get("across") == across_hash:
                stats["unchanged"] += 1
                if use_llm and ((row.outline or {}).get("llm") or {}).get("hash") != ch:
                    llm_facts(row, u, None)               # read by the LLM for the first time
                continue
            before = ((row.outline or {}).get("llm") if row is not None else None)
            if row is None or row.chash != ch:
                stats["texts_changed"] += 1               # (0.10.5) not a reading again for names: a text changed
            owner = (u["found"]["workloads"][0]["name"] if len(u["found"]["workloads"]) == 1 else None) or \
                u["found"]["tool"] or doc_owner.get(d.id)
            if "speaks" in u:                              # (not the repository: a role's part, or nobody)
                owner = u["speaks"] or None
            elif u.get("built"):                           # (0.10.4) the service built from its folder (nginx.conf's
                owner = u["built"]                         # proxy_pass is the reverse proxy's, not nginx's)
            if u["kind"] == "page":
                owner = _page_owner(u["title"], names, own) or owner
            owner = (names.part(owner) or own.get(norm(owner)) or owner) if owner else None
            if row is None:
                row = KUnit(doc_id=d.id, ukey=u["ukey"][:512])
                db.session.add(row)
                db.session.flush()
            row.kind, row.title, row.url = u["kind"], (u["title"] or "")[:512], (u["url"] or "")[:2000]
            row.lang, row.owner, row.chash = u["found"]["lang"], (owner or "")[:255] or None, ch
            row.outline = {"symbols": _outline(u["text"], u["found"]["lang"]), "found": u["found"],
                           "links": (u["meta"] or {}).get("links") or [], "page_id": (u["meta"] or {}).get("id"),
                           "space": (u["meta"] or {}).get("space"), "across": across_hash}
            row.analysed_at = dt.datetime.utcnow()
            db.session.query(KFact).filter(KFact.unit_id == row.id).delete(synchronize_session=False)
            mine = facts_of(u, owner, names, own)
            said = {(norm(f["subject"]), f["verb"], norm(f["obj"])) for f in mine}
            for f in mine + [f for f in u.get("across") or [] if (norm(f["subject"]), f["verb"], norm(f["obj"]))
                             not in said]:
                db.session.add(KFact(unit_id=row.id, subject=f["subject"][:255], verb=f["verb"], obj=f["obj"][:512],
                                     obj_kind=f["obj_kind"], line=f["line"], quote=f["quote"][:400],
                                     source=f["source"], confidence=f["confidence"]))
                stats["facts"] += 1
            db.session.flush()
            llm_facts(row, u, before)                     # (what the LLM read last time, placed again)
            stats["analysed"] += 1
        for key, row in have.items():
            if key not in keep:
                db.session.delete(row)
                stats["removed"] += 1
                stats["texts_changed"] += 1
        db.session.commit()
    ids = [d.id for d in docs if not isinstance(d, _Catalog)]
    if stats["texts_changed"] or db.session.query(KUnit.id).filter(KUnit.doc_id.isnot(None),
                                                                     KUnit.doc_id.notin_(ids or [-1])).first():
        row = db.session.get(Meta, TEXTS_KEY)            # (0.10.5) when a document's text last changed: a learned
        now = dt.datetime.utcnow().isoformat()            # link is proposed for removal only after such a change
        if row is None:
            db.session.add(Meta(key=TEXTS_KEY, value=now))
        else:
            row.value = now
    for doc_id, k in kinds_of.items():                  # what each repository is (its Context page)
        row = db.session.get(Meta, f"repo_kinds:{doc_id}")
        value = json.dumps(k, sort_keys=True)
        if row is None:
            db.session.add(Meta(key=f"repo_kinds:{doc_id}", value=value))
        elif row.value != value:
            row.value = value
    if meta is None:
        db.session.add(Meta(key="understand_names", value=names_hash))
    else:
        meta.value = names_hash
    db.session.commit()
    return dict(stats)


# --------------------------------------------------------------------------------------------------------------- #
# the graph: the facts of all units, merged
# --------------------------------------------------------------------------------------------------------------- #
TEXTS_KEY = "understand_texts_at"   # (0.10.5) supagent_meta: when a document's text last changed
READER = "0.10.6"     # (0.10.4) the reading's rules: when they change, the next run reads every unit again once
#                     (0.10.5: the denied sentences kept as denied facts; 0.10.6: tests, fixtures and examples no
#                     fact, a subject no part's name, where a part runs ends at its sentence's next predicate)
# (0.10.5) what an address is for, read in its line: its scheme, its port, the name of the key it is the value of
TECH = {"postgres": ("postgres", "postgresql", "pgsql", "psql"), "mysql": ("mysql", "mariadb", "percona"),
        "redis": ("redis", "valkey", "keydb"), "rabbitmq": ("rabbitmq", "rabbit", "amqp"), "mongo": ("mongo", "mongodb"),
        "kafka": ("kafka",), "search": ("opensearch", "elasticsearch", "elastic", "solr"), "memcached": ("memcached",),
        "mail": ("postfix", "exim", "sendmail", "smtp", "mailrelay", "relay"), "s3": ("minio", "s3", "seaweedfs"),
        "loki": ("loki",), "prometheus": ("prometheus",), "alertmanager": ("alertmanager",), "grafana": ("grafana",),
        "nginx": ("nginx",), "haproxy": ("haproxy",), "node": ("node_exporter", "node-exporter", "nodeexporter")}
SCHEME_TECH = {"postgres": "postgres", "postgresql": "postgres", "mysql": "mysql", "mariadb": "mysql", "redis": "redis",
               "rediss": "redis", "amqp": "rabbitmq", "amqps": "rabbitmq", "mongodb": "mongo", "mongodb+srv": "mongo",
               "kafka": "kafka", "smtp": "mail", "smtps": "mail", "s3": "s3"}
PORT_TECH = {5432: "postgres", 6432: "postgres", 3306: "mysql", 6379: "redis", 5672: "rabbitmq", 5671: "rabbitmq",
             15672: "rabbitmq", 27017: "mongo", 9092: "kafka", 9200: "search", 9300: "search", 11211: "memcached",
             25: "mail", 465: "mail", 587: "mail", 3100: "loki", 9090: "prometheus", 9093: "alertmanager",
             3000: "grafana", 9187: "postgres", 9121: "redis", 15692: "rabbitmq", 9104: "mysql", 9216: "mongo",
             9308: "kafka", 9114: "search", 9113: "nginx", 8405: "haproxy", 9101: "haproxy", 9100: "node"}
KEY_TECH = [(re.compile(r"redis|cache", re.I), "redis"), (re.compile(r"amqp|rabbit|broker|queue|_mq|mq_", re.I), "rabbitmq"),
            (re.compile(r"postgres|\bpg|_pg|psql", re.I), "postgres"), (re.compile(r"mysql|maria", re.I), "mysql"),
            (re.compile(r"mongo", re.I), "mongo"), (re.compile(r"kafka", re.I), "kafka"),
            (re.compile(r"opensearch|elastic|search", re.I), "search"), (re.compile(r"smtp|mail", re.I), "mail"),
            (re.compile(r"\bs3|minio|bucket|_repo", re.I), "s3")]
ADDRESS = re.compile(r"(?:(?P<scheme>[a-z][a-z0-9+.-]*)://)?(?:[^@\s/'\"]*@)?(?P<host>[A-Za-z0-9][\w.-]*)(?::(?P<port>\d{2,5}))?")
HOLDERS = ("keepalived", "vrrp", "pacemaker", "corosync", "ucarp")   # what holds a VIP is never behind it


def _tech(line: str, host: str) -> tuple[set[str], str]:
    """(0.10.5) What an address in a line is for: the technologies its scheme, its port and its key say, and the key's
    stem ("PAYMENT_ADAPTER_URL=http://app-01:8080": payment_adapter)."""
    out: set[str] = set()
    for m in ADDRESS.finditer(line or ""):
        if norm(m.group("host").split(".")[0]) != norm(host.split(".")[0]):
            continue
        if m.group("scheme") and m.group("scheme").lower() in SCHEME_TECH:
            out.add(SCHEME_TECH[m.group("scheme").lower()])
        if m.group("port") and int(m.group("port")) in PORT_TECH:
            out.add(PORT_TECH[int(m.group("port"))])
    key = re.match(r"\s*(?:export\s+|-\s*)?['\"]?([A-Za-z_][\w.-]*)['\"]?\s*[:=]", line or "")
    stem = ""
    if key:
        stem = re.sub(r"(?i)[_.-]?(url|uri|host|hosts|hostname|addr|address|endpoint|dsn|server|servers|smarthost|"
                      r"port|base|api)$", "", key.group(1)).strip("_.-")
        stem = re.sub(r"(?i)[_.-]?(url|uri|host|hosts|endpoint|api)$", "", stem).strip("_.-")
        for rx, t in KEY_TECH:
            if rx.search(key.group(1)) and not out:
                out.add(t)
    return out, stem


def _behind_addresses(rel: dict[tuple, dict[str, Any]], canon: Any) -> list[dict[str, Any]]:
    """(0.10.5) An address naming a server or a VIP (a connection string, a scrape target) is the service there whose
    technology its line says (redis://...@cache-01: the redis on the cache group's servers; db-01:9187: the postgres
    exporter's database; a VIP's own service), when one part only matches; the part the line's key is named after
    first (PAYMENT_ADAPTER_URL=http://app-01: the payment adapter). The parts running on every server are left out
    unless the line says them."""
    groups_of: dict[str, set[str]] = defaultdict(set)
    placed: dict[str, set[str]] = defaultdict(set)
    vips: dict[str, set[str]] = defaultdict(set)
    hosts: set[str] = set()
    for r in rel.values():
        if r["kind"] == "in_group" and r.get("obj_kind") == "group":
            groups_of[norm(r["from"])].add(norm(r["to"]))
            hosts.add(norm(r["from"]))
        elif r["kind"] == "runs_on":
            placed[norm(r["to"])].add(r["from"])
            if r.get("obj_kind") == "host":
                hosts.add(norm(str(r["to"]).split(".")[0]))
    for r in rel.values():                            # a VIP: what it routes to (a part, not a server, not its holder)
        if r["kind"] == "in_group" and r.get("obj_kind") == "vip":
            vips[norm(r["to"])]
        elif r["kind"] == "routes_to" and norm(str(r["from"]).split(".")[0]) not in hosts and \
                norm(str(r["to"]).split(".")[0]) not in hosts and not any(h in norm(r["to"]) for h in HOLDERS):
            vips[norm(r["from"])].add(r["to"])
    everywhere = placed.get("all", set())

    def on(host: str) -> set[str]:
        h = norm(host.split(".")[0])
        out = set(placed.get(h, ())) | set(placed.get(norm(host), ()))
        for g in groups_of.get(h, ()):
            out |= placed.get(g, set())
        return out

    def matches(part: str, tech: set[str], stem: str) -> bool:
        words = set(re.split(r"[\s_.-]+", str(part).lower())) | {norm(part)}
        return any(w in words or any(w in x for x in words) for t in tech for w in TECH.get(t, ()))

    out: list[dict[str, Any]] = []
    for r in list(rel.values()):
        if r["kind"] not in FLOWS + ("scrapes",):
            continue
        to = str(r["to"])
        vip = norm(to) in vips or r.get("obj_kind") == "vip"
        if not vip and norm(to.split(".")[0]) not in hosts:
            continue
        tech, stem = _tech(r.get("quote") or "", to)
        cands = set(vips.get(norm(to), ())) if vip else on(to) - (everywhere if "node" not in tech else set())
        if vip and not cands:                         # a VIP named after a group of servers ("db-vip": the db group's)
            group = re.sub(r"(?:^|[-_])vips?(?=[-_]|$)", "", norm(to.split(".")[0])).strip("-_")
            if group and group in placed:
                cands = set(placed[group]) - everywhere
        named = [p for p in cands if stem and norm(p) == norm(stem)]
        pick = named or [p for p in cands if matches(p, tech, stem)] or (list(cands) if vip and len(cands) == 1 else [])
        if len(pick) != 1:
            continue
        svc = canon(pick[0])
        quote = r.get("quote") or ""
        if r["kind"] == "scrapes":
            for owner in sorted(r.get("owners") or ()):
                if norm(owner) != norm(svc):
                    out.append({"from": canon(owner), "kind": "monitors", "to": svc, "obj_kind": "part",
                                "sources": {"inferred"}, "units": set(r["units"]), "quote": quote, "where": r["where"]})
        elif norm(r["from"]) != norm(svc):
            out.append({"from": r["from"], "kind": r["kind"], "to": svc, "obj_kind": "part", "sources": {"inferred"},
                        "units": set(r["units"]), "quote": quote, "where": r["where"]})
        if vip and norm(to) != norm(svc):             # the VIP routes to the service found behind it
            out.append({"from": to, "kind": "routes_to", "to": svc, "obj_kind": "part", "sources": {"inferred"},
                        "units": set(r["units"]), "quote": quote, "where": r["where"]})
    return out


PART_VERBS = ("calls", "reads_from", "sends_to", "uses", "runs_on", "alias", "collects", "scrapes", "owned_by",
              "code_in", "in_group", "monitors", "routes_to")
FLOWS = ("calls", "reads_from", "sends_to", "uses")
SOURCE_RANK = {"code": 0, "config": 1, "inferred": 2, "diagram": 3, "doc": 4, "wiki": 4, "llm": 5}
DATA_VERBS = ("emits", "writes", "logs_to", "watched_by")


def export() -> dict[str, Any]:
    """What the documents state, merged: the relations between parts and the links of parts to the data (with their
    sources, how many units say them, a line that does), what the facts imply together (a service's logs are in the
    indices of the shipper it sends them to; what a scrape job watches on the part its target runs), the wiki's page
    links and the diagrams' arrows."""
    from supagent.models import Doc, KFact, KUnit

    names = known_names()
    alias: dict[str, str] = {}
    rows = list(db.session.query(KFact, KUnit).join(KUnit, KFact.unit_id == KUnit.id))
    for f, _u in rows:
        if f.verb == "alias":
            alias[norm(f.obj)] = f.subject

    def canon(x: str) -> str:
        return alias.get(norm(x)) or names.part(x) or x

    from supagent.knowledge.projects import test_file

    rel: dict[tuple, dict[str, Any]] = {}
    for f, u in rows:
        if u.kind == "file" and test_file(u.ukey):    # (0.10.6) a repository's tests, fixtures, examples (read
            continue                                 # before 0.10.6 too): no fact of the System map
        s = canon(f.subject)
        o = canon(f.obj) if f.obj_kind in ("part", "host", "group") else f.obj
        key = (s, f.verb, o)
        r = rel.setdefault(key, {"from": s, "kind": f.verb, "to": o, "obj_kind": f.obj_kind, "sources": set(),
                                 "units": set(), "quote": f.quote, "where": u.title or u.ukey})
        r["sources"].add(f.source)
        r["units"].add(u.id)
        if u.owner:
            r.setdefault("owners", set()).add(u.owner)
    # implied: a part's logs go where the shipper it sends them to writes; a namespace's workloads to its collector
    runs_on = {(r["from"]): r["to"] for r in rel.values() if r["kind"] == "runs_on"}
    host_of = defaultdict(set)
    for r in rel.values():
        if r["kind"] == "runs_on":
            host_of[norm(r["to"])].add(r["from"])
    writes = defaultdict(set)
    for r in rel.values():
        if r["kind"] == "writes":
            writes[norm(r["from"])].add(r["to"])
    implied: list[dict[str, Any]] = []
    for r in list(rel.values()):
        if r["kind"] == "sends_to" and norm(r["to"]) in writes:
            for idx in writes[norm(r["to"])]:
                implied.append({"from": r["from"], "kind": "logs_to", "to": idx, "obj_kind": "index",
                                "sources": {"inferred"}, "units": set(r["units"]),
                                "quote": f'{r["from"]} sends to {r["to"]}, which writes {idx}', "where": r["where"]})
    workloads_ns = defaultdict(set)
    declared: set[str] = set()                       # (0.10.6) every workload a unit defines (a Compose service...)
    for u in db.session.query(KUnit):                # every unit's workloads (a manifest with no fact of its own too)
        for w in ((u.outline or {}).get("found") or {}).get("workloads") or []:
            declared.add(norm(w.get("name") or ""))
            if w.get("namespace"):
                workloads_ns[w["namespace"]].add(canon(w["name"]))
    for r in list(rel.values()):
        if r["kind"] == "collects" and str(r["to"]).startswith("namespace:"):
            for w in workloads_ns.get(r["to"].split(":", 1)[1], ()):
                implied.append({"from": w, "kind": "sends_to", "to": r["from"], "obj_kind": "part", "sources": {"inferred"},
                                "units": set(r["units"]), "quote": f'{r["from"]} collects the logs of its namespace',
                                "where": r["where"]})
                for idx in writes.get(norm(r["from"]), ()):
                    implied.append({"from": w, "kind": "logs_to", "to": idx, "obj_kind": "index",
                                    "sources": {"inferred"}, "units": set(r["units"]),
                                    "quote": f'{r["from"]} collects its logs and writes {idx}', "where": r["where"]})
    acting = {norm(r["from"]) for r in rel.values() if r["kind"] in FLOWS}   # (0.10.6) the parts that act: no host
    for r in list(rel.values()):                    # a scrape job: what runs on its target, what its exporter watches
        if r["kind"] != "scrapes":
            continue
        job, host = r["from"], r["to"]
        on_host = host_of.get(norm(host)) or {names.part(host) or host}    # what runs there, else the host itself
        prefixes = EXPORTERS.get(norm(job))
        if prefixes:                                 # the exporter's own "up" (or "success") series stands for it
            ups = sorted(m for m in names.metrics if m in {p + "up" for p in prefixes} | {p + "success" for p in prefixes})
            for part in on_host:
                for m in ups:
                    implied.append({"from": part, "kind": "watched_by", "to": m, "obj_kind": "metric",
                                    "sources": {"inferred"}, "units": set(r["units"]),
                                    "quote": f"{job} scrapes {host}", "where": r["where"]})
        # (0.10.6) a target that is a part itself (a Compose service, "otel:9464", one of another file of the
        # repository too) is no host the job's part runs on
        elif (names.part(job) or job in {canon(x) for x in alias.values()}) and not names.service(host) and \
                norm(canon(host)) not in acting and norm(host) not in declared and norm(canon(host)) not in declared:
            implied.append({"from": canon(job), "kind": "runs_on", "to": names.hosts.get(norm(host)) or host,
                            "obj_kind": "host", "sources": {"config"}, "units": set(r["units"]),
                            "quote": f"the scrape job {job} reads {host}", "where": r["where"]})
    implied += _behind_addresses(rel, canon)
    for r in implied:
        key = (r["from"], r["kind"], r["to"])
        if key in rel:
            rel[key]["sources"] |= r["sources"]
            rel[key]["units"] |= r["units"]
        else:
            rel[key] = r
    del runs_on
    # one pair, one way: the verb of its strongest source (code, then configuration, then what follows from them, then a
    # diagram, then a sentence), the sources of every way it is stated kept with it
    by_pair: dict[tuple[str, str], list[tuple]] = defaultdict(list)
    for key, r in rel.items():
        if r["kind"] in FLOWS:
            by_pair[(norm(r["from"]), norm(r["to"]))].append(key)
    for keys in by_pair.values():
        if len(keys) < 2:
            continue
        rank = {k: min(SOURCE_RANK.get(x, 9) for x in rel[k]["sources"]) for k in keys}
        best = min(rank.values())
        keep = [k for k in keys if rank[k] == best]
        directed = [k for k in keep if rel[k]["kind"] in ("reads_from", "sends_to")]
        keep = directed or [k for k in keep if rel[k]["kind"] == "uses"] or keep
        sources = set().union(*(rel[k]["sources"] for k in keys))
        units = set().union(*(rel[k]["units"] for k in keys))
        for k in keys:
            if k in keep:
                rel[k]["sources"], rel[k]["units"] = set(sources), set(units)
            else:
                del rel[k]
    relations, data_links = [], []
    denied = [{"from": r["from"], "kind": r["kind"][4:], "to": r["to"], "quote": r["quote"], "where": r["where"],
               "sources": sorted(r["sources"])} for r in rel.values() if r["kind"].startswith("not_")]
    for r in rel.values():
        item = {"from": r["from"], "kind": r["kind"], "to": r["to"], "obj_kind": r.get("obj_kind"),
                "sources": sorted(r["sources"]), "units": len(r["units"]), "quote": r["quote"], "where": r["where"]}
        if r["kind"] in DATA_VERBS:
            data_links.append({"part": r["from"], "kind": r["kind"], "object_kind": r["obj_kind"], "object": r["to"],
                               "sources": item["sources"], "units": item["units"], "quote": r["quote"]})
        elif r["kind"] in PART_VERBS:
            relations.append(item)
    wiki_edges, diagram_edges = [], []
    for d in db.session.query(Doc).filter(Doc.enabled.is_(True)):
        for p in d.pages or []:
            if isinstance(p, dict) and p.get("id"):
                for to in p.get("links") or []:
                    if str(to).isdigit():
                        wiki_edges.append([int(p["id"]), int(to)])
                for e in p.get("diagram_edges") or []:
                    diagram_edges.append(list(e))
    return {"relations": relations, "data_links": data_links, "denied": denied,
            "aliases": [{"name": k, "part": v} for k, v in alias.items()],
            "wiki_edges": sorted(map(list, {tuple(e) for e in wiki_edges})), "diagram_edges": diagram_edges}
