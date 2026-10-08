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
         ".html": "html", ".htm": "html"}
NAMED_LANGS = {"dockerfile": "dockerfile", "containerfile": "dockerfile", "makefile": "make", "jenkinsfile": "groovy"}
WORKLOADS = {"Deployment", "StatefulSet", "DaemonSet", "CronJob", "Job", "Rollout", "DeploymentConfig"}
# well-known tools, recognised by the shape of their configuration (not by a name)
TOOLS = [
    ("fluent-bit", re.compile(r"^\s*\[(?:INPUT|OUTPUT)\]", re.M | re.I)),
    ("logstash", re.compile(r"^\s*input\s*\{[\s\S]*^\s*output\s*\{", re.M)),
    ("otel-collector", re.compile(r"^receivers:\s*$[\s\S]*^exporters:\s*$[\s\S]*^service:\s*$", re.M)),
    ("prometheus", re.compile(r"^scrape_configs:\s*$", re.M)),
    ("alertmanager", re.compile(r"^route:\s*$[\s\S]*^receivers:\s*$", re.M)),
    ("jaeger", re.compile(r"index-prefix:|span-storage|jaeger", re.I)),
    ("filebeat", re.compile(r"^filebeat\.inputs:", re.M)),
    ("vector", re.compile(r"^\[sinks\.|^sinks:\s*$", re.M)),
]
SHIPPERS = {"fluent-bit", "logstash", "otel-collector", "jaeger", "filebeat", "vector", "alertmanager"}
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
DOC_HOSTS = re.compile(r"^(?!api\.)(?:(docs?|wiki|help|support|blog|kb|bugs|issues)\.|(.*\.)?(readthedocs\.io|github\.com|github\.io|githubusercontent\.com|"
                       r"launchpad\.net|sourceforge\.net|googlecode\.com|"
                       r"gitlab\.com|bitbucket\.org|opendev\.org|stackoverflow\.com|pypi\.org|npmjs\.(com|org)|"
                       r"docker\.(com|io)|quay\.io|apache\.org|python\.org|w3\.org|schema\.org|"
                       r"wikipedia\.org|golang\.org|go\.dev|maven\.org|spring\.io)$)")   # (an API's host is a call: api.github.com)
ACTORS = {"customers", "customer", "users", "user", "clients", "client", "browser", "browsers", "internet", "visitors",
          "people", "operators", "admins"}
PLATFORMS = re.compile(r"(?i)^(kubernetes|k8s|openshift|eks|aks|gke|aws|azure|gcp|the\s+cloud|cloud|docker|containers?|"
                       r"bare[ -]metal)(\s*\(.*\))?\s*$")     # the whole value: "Kubernetes (payments)", not "vm-01"
COMMENT = re.compile(r"^\s*(#|//|/\*|\*|<!--|--\s|;|REM\s|%)")    # a line that is a comment (code, configuration)
DATE_PART = re.compile(r"%\{\+?[^}]*\}|%[YmdHjU]|\{\+?[yYMdH.\-]+\}|\$\{[^}]*\}|YYYY[.\-]?MM[.\-]?DD|yyyy[.\-]?MM[.\-]?dd")


def _hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8", errors="replace")).hexdigest()


def norm(name: str) -> str:
    """A name as compared: lower case, '_' and spaces as '-'."""
    return re.sub(r"[\s_]+", "-", str(name or "").strip().lower()).strip("-")


def lang_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1].lower()
    for suffix in (".j2", ".jinja2", ".jinja", ".tpl", ".tmpl", ".template", ".erb"):
        if name.endswith(suffix) and "." in name[:-len(suffix)]:
            name = name[:-len(suffix)]                    # a template: the language of what it renders (x.conf.j2)
            break
    if name in NAMED_LANGS:
        return NAMED_LANGS[name]
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

    n = Names()
    try:
        for f in db.session.query(Facet).filter(Facet.status == "approved"):
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
        for d in _yaml_docs(text):
            if isinstance(d, dict) and d.get("kind") in WORKLOADS and isinstance(d.get("metadata"), dict):
                out["workloads"].append({"name": str(d["metadata"].get("name") or ""),
                                         "namespace": str(d["metadata"].get("namespace") or "")})
            if isinstance(d, dict) and isinstance(d.get("services"), dict) and ("version" in d or "services" in d):
                if any(isinstance(v, dict) and ("image" in v or "build" in v) for v in d["services"].values()):
                    out["workloads"] += [{"name": str(k), "namespace": ""} for k in d["services"]]
    if lang == "systemd" or path.endswith(".service"):
        out["workloads"].append({"name": path.rsplit("/", 1)[-1].rsplit(".", 1)[0], "namespace": ""})
    for tool, rx in TOOLS:
        if rx.search(text) and (tool != "jaeger" or lang in ("yaml", "json", "properties", "conf")):
            out["tool"] = tool
            break
    for rx in (r"OTEL_SERVICE_NAME[\"']?\s*[:=,]\s*(?:value:\s*)?[\"']?([\w.-]+)",
               r"[\"']service\.name[\"']\s*[:=]\s*[\"']([\w.-]+)", r"service_name:\s*[\"']?([\w.-]+)",
               r"spring\.application\.name\s*[:=]\s*([\w.-]+)", r"<artifactId>([\w.-]+)</artifactId>",
               r"^name\s*=\s*[\"']([\w.-]+)[\"']", r"^\s*\"name\":\s*\"([\w@/.-]+)\""):
        for m in re.finditer(rx, text, re.M):
            out["names"].append(m.group(1).rsplit("/", 1)[-1])
    if lang == "markdown":
        h = re.search(r"^#\s+(.+?)\s*$", text, re.M)
        out["heading"] = h.group(1).strip("` ") if h else None
    if path.endswith("pom.xml"):          # the project's artifact, not its dependencies'
        m = re.search(r"<project[^>]*>[\s\S]*?<artifactId>([\w.-]+)</artifactId>", text)
        out["names"] = [x for x in out["names"] if not m or x == m.group(1)] or out["names"][:1]
    out["names"] = list(dict.fromkeys(out["names"]))[:10]
    return out


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
    h = host.split("@")[-1].split(":")[0].strip("[]").lower()
    if not h or re.fullmatch(r"[\d.]+", h):
        return ""
    found = names.part(h)
    if found:
        return found
    labels = [x for x in h.split(".") if x]
    for lab in labels:
        if names.part(lab):
            return names.part(lab) or lab
    meaningful = [x for x in labels if x not in GENERIC_LABELS]
    return meaningful[0] if meaningful else labels[0]


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
    return "calls", "service"


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
CUES = [
    ("runs_on", re.compile(r"\b(?:runs?|running|installed|deployed|hosted|lives?)\s+on\b|\bon\s+the\s+(?:VM|host|server|"
                           r"node)\b|\(\s*(?:\w+\s+)?on\b", re.I)),
    ("calls", re.compile(r"\b(?:calls?|calling|invokes?|requests?|queries|forwards?\b[^.]{0,40}?\bto|reserves?\b[^.]{0,40}?"
                         r"\bin|authori[sz]es?\b[^.]{0,40}?\bwith|depends?\s+on|talks?\s+to|connects?\s+to)\b", re.I)),
    ("sends_to", re.compile(r"\b(?:writes?|publishes|pushes|sends?|stores?|puts?|ships?)\b(?:[^.]{0,40}?\b(?:in|into|to)\b)?",
                            re.I)),
    ("reads_from", re.compile(r"\b(?:reads?|loads?|fetches|consumes?|pulls?)\b[^.]{0,40}?\b(?:from|in)\b|\bcaches?\b[^.]"
                              r"{0,30}?\bin\b|\buses\b", re.I)),
    ("monitors", re.compile(r"\b(?:monitors|watches|checks|probes|scrapes)\b", re.I)),
]
OBJECT_OF = re.compile(r"(?i)\b(runs|running|hosts|hosting|has|have|installs|installing|contains|includes|serves|"
                       r"exposes|deploys|deploying|starts)\s+(?:an?|the|its|their|our)?\s*$")
CLAUSE_END = re.compile(r",?\s+and\s+(?:is|are|was|were|has|have|it|its|they|their)\b|;|\bwhich\b", re.I)
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
    ("runs_on", re.compile(r"\b(runs?\s+on|hosts?|servers?|nodes?|machines?|vms?|platform|cluster|located)\b", re.I)),
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
    row start a new one); positions as in the text."""
    flat = re.sub(r"\n(?![ \t]*(?:[-*+#|>]|\d+[.)]\s|\n))[ \t]*", " ", text)
    for m in re.finditer(r"(?:[^\n.!?;]|[.!?;](?![\s)\]]|$))+(?:[.!?;](?=[\s)\]]|$)|\n|$)", flat):   # (a dot inside
        #                                                            a name, logs.test, db-01.example.net, keeps going)
        s = m.group(0).strip()
        if len(s) >= 8:
            yield m.start(), s


def _depths(sentence: str) -> list[int]:
    depth, out = 0, []
    for ch in sentence:
        depth += 1 if ch == "(" else 0
        out.append(depth)
        depth -= 1 if ch == ")" and depth else 0
    return out


def _named(sentence: str, names: Names, own: dict[str, str]) -> list[tuple[int, str, str]]:
    """The parts and hosts a sentence names: (position, name as written, the part)."""
    out = []
    for m in re.finditer(r"[A-Za-z][\w.-]*[\w]|[A-Za-z]", sentence):
        w = m.group(0).strip(".-")
        p = names.part(w) or own.get(norm(w))
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
    if source in ("code", "config") and tool != "prometheus" and not operation:
        for m in URL.finditer(text):
            scheme, host, port, first = _url_parts(m.group(1))
            line = _line_of(text, m.start())[1]
            if COMMENT.match(line) or host.isupper() or re.search(r"[{}%$<>]", host) or DOC_HOSTS.search(host.lower()):
                continue                                # a comment (a license's address), a placeholder (HOST_IP), a
                #                                         template ({{ host }}), documentation or code (docs., github)
            if not host or host.lower() in ("localhost", "127.0.0.1", "0.0.0.0") or me == "" or \
                    re.search(r"xmlns|schemaLocation|\$schema|DOCTYPE|xsi:", text[max(0, m.start() - 40):m.start()]):
                continue
            verb, what = _endpoint_verb(scheme, port, line, text)
            if tool in SHIPPERS and verb == "calls":
                verb = "sends_to"                       # a shipper's outputs: where it sends what it collects
            part = _host_part(host, names)
            served = names.parts.get(norm(part)) or names.alias.get(norm(part)) or own.get(norm(part)) \
                if not names.hosts.get(norm(part)) else None   # the host is a part (a workload, a service), no server
            if what == "database" and served:
                fact(me, verb, served, "database", m.start())     # (the path names a database inside it)
            elif what == "database" and first and re.fullmatch(r"[A-Za-z_][\w-]{1,62}", first):
                db_part = names.part(first) or first
                fact(me, verb, db_part, "database", m.start())
                fact(db_part, "runs_on", names.hosts.get(norm(host)) or host, "host", m.start(), conf=0.7)
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
                         names.hosts.get(norm(m.group(3))) or m.group(3), "host", m.start(), conf=0.7)
                else:
                    fact(me, "uses", _host_part(m.group(3), names), "database", m.start(), conf=0.7)
            if me and m.group(2) == "NAME" and re.search(r"DB|DATABASE", m.group(0)):
                fact(me, "uses", names.part(m.group(3)) or m.group(3), "database", m.start(), conf=0.7)
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
        for job in re.finditer(r"(?m)^\s*-\s*job_name:\s*[\"']?([\w.-]+)[\"']?([\s\S]*?)(?=^\s*-\s*job_name:|\Z)", text):
            for t in re.finditer(r"[\"']([A-Za-z][\w.-]*)(?::(\d+))?[\"']", job.group(2)):
                if t.group(1) in ("http_2xx",) or "/" in t.group(1):
                    continue
                fact(job.group(1), "scrapes", t.group(1), "host", job.start() + t.start(2 if t.group(2) else 1), conf=0.85)
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
        verb = "uses" if re.search(r"\b(sql|jdbc|db|database|query)\b", label or "", re.I) else \
            "sends_to" if re.search(r"\blogs?\b|\bpublish|\bwrite", label or "", re.I) else "calls"
        pos = max(0, text.find(a))
        fact(pa, verb, pb, "part", pos, src="diagram", conf=0.85)
    # sentences of a document or a page: two parts and how they interact, a part's logs, its metrics
    if source in ("doc", "wiki"):
        unit_part = me or ""
        tools = {norm(t) for t, _rx in TOOLS}
        prose = text
        for t0, header, rows in _tables(text):
            roles = [next((v for v, rx in COLUMNS if rx.search(h)), None) for h in header]
            for r0, cells in rows:
                first = cells[0] if cells else ""
                part = names.part(first) or own.get(norm(first)) or _page_owner(first, names, own)
                if not part:
                    continue
                for role, cell in zip(roles[1:], cells[1:]):
                    for value in [v.strip() for v in re.split(r",|;|\band\b", cell) if v.strip()][:6]:
                        if not role or not re.search(r"\w", value):
                            continue
                        if role == "runs_on":
                            if PLATFORMS.match(value):
                                continue                          # Kubernetes, a cloud: where, but no host
                            fact(part, "runs_on", names.hosts.get(norm(value)) or re.sub(r"\s*\(.*\)", "", value),
                                 "host", r0, conf=0.75)
                        elif role in ("logs_to", "watched_by"):
                            obj = names.index(value) if role == "logs_to" else names.metric(value)
                            if obj:
                                fact(part, role, obj, "index" if role == "logs_to" else "metric", r0, conf=0.75)
                        elif role == "calls":
                            fact(part, "calls", names.part(value) or own.get(norm(value)) or value, "part", r0, conf=0.7)
                        else:
                            fact(part, role, value, "attribute", r0, conf=0.75)
            for r0, cells in [(t0, header)] + rows:   # a table's rows are not sentences
                line_end = prose.find("\n", r0)
                prose = prose[:r0] + " " * ((line_end if line_end >= 0 else len(prose)) - r0) + prose[line_end:] \
                    if line_end >= 0 else prose[:r0]
        for start, s in _sentences(prose):
            found = _named(s, names, own)
            found = [x for x in found if not any(y is not x and abs(y[0] - x[0]) <= len(x[1]) + 16 and
                                                 norm(x[2]) != norm(y[2]) and norm(x[2]) in norm(y[2]) for y in found)]
            depth = _depths(s)
            outside = [(at, w, p) for at, w, p in found if depth[at] == 0]
            # the sentence's subject: its first part outside brackets near its start, else the unit's own part
            # (a README speaks of its repository's service, a page of the part its title names)
            heads = [x for x in outside if x[0] < 40 and not OBJECT_OF.search(s[max(0, x[0] - 24):x[0]])]
            lead = heads[0] if heads and heads[0] is outside[0] and not re.match(r"(?i)\s*(it|its|they|their)\b", s) \
                else None                                 # ("the server runs an Nginx webserver": no Nginx's sentence)
            subject = lead[2] if lead else unit_part
            cues = sorted([(c.start(), c.end(), verb) for verb, rx in CUES for c in rx.finditer(s)])
            for k, (c0, c1, verb) in enumerate(cues):
                stop = cues[k + 1][0] if k + 1 < len(cues) else len(s)
                bound = CLAUSE_END.search(s, c1)                  # "... and is published by ...": another clause
                stop = min(stop, bound.start()) if bound else stop
                inner = depth[c0] > 0
                before = [x for x in (found if inner else outside) if x[0] < c0 and (depth[x[0]] < depth[c0] or not inner)]
                # inside brackets ("(which calls X)") the clause speaks of the part just before them
                subj = before[-1][2] if inner and before else subject
                if verb == "runs_on":
                    hosts = [w for at, w, p in found if c0 < at < stop and names.hosts.get(norm(w))] or \
                        [w for at, w, p in found if c0 < at < stop and re.search(r"\d", w)][:1]
                    if s[c0:c1].lstrip().startswith("("):        # "X (... on host)": X is the name just before
                        who = next((p for at, w, p in found if at + len(w) >= c0 - 2 and at < c0), None)
                    else:
                        who = next((p for at, w, p in reversed(outside) if at < c0), None) or subj
                    for host in hosts[:12]:                       # "runs on web1, web2 and web3": each of them
                        if who:
                            fact(who, "runs_on", names.hosts.get(norm(host)) or host, "host", start + c0, conf=0.7)
                    continue
                if verb == "monitors" and not lead:
                    continue                                      # "Check the ...": a step of a runbook, no subject
                objs = [p for at, w, p in found if c1 <= at < stop and (depth[at] == depth[c0])
                        and norm(p) != norm(subj or "") and not names.hosts.get(norm(w))]
                for o in objs[:4]:
                    at_o = next((at for at, w, p in found if p == o and c1 <= at < stop), None)
                    if verb == "sends_to" and re.match(r"(?i)(stores?|keeps?|holds?)\b(?!.*\b(in|into|to)\b)",
                                                       s[c0:c1]) and at_o is not None and re.search(r"\bof\b",
                                                                                                    s[c1:at_o]):
                        fact(o, "uses", subj, "part", start + c0, conf=0.6)   # "a cache stores the sessions of X"
                    else:
                        fact(subj, verb, o, "part", start + c0, conf=0.6)
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


def _page_owner(title: str, names: Names, own: dict[str, str]) -> str | None:
    """The part a page is about: its title names it ("Billing service" -> billing)."""
    t = re.sub(r"\b(service|services|application|app|database|db|server|system|component|page|overview)\b", " ",
               title or "", flags=re.I)
    for cand in [title or ""] + [w for w in re.split(r"[\s/|:,()-]+", t) if w]:
        p = names.part(cand) or own.get(norm(cand))
        if p:
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
    doc_owner: dict[int, str | None] = {}
    stored = {(r.doc_id, r.ukey): (r.chash, (r.outline or {}).get("found"))
              for r in db.session.query(KUnit.doc_id, KUnit.ukey, KUnit.chash, KUnit.outline)}
    for d in docs:
        us = _catalog_units() if isinstance(d, _Catalog) else units_of(d)
        for u in us:                                 # a unit unchanged: what it declares, as read last time
            u["chash"] = _hash(u["text"])
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
            for u in us:
                u["across"] = across.get(u["path"] or "", []) if u["path"] else []
                if u["path"] and u["path"] in speaks:
                    u["speaks"] = speaks[u["path"]]       # an Ansible file: its role's part, or nobody
            for name in declared.get("parts", []):
                own.setdefault(norm(name), names.part(name) or name)
            for h in declared.get("hosts", []):
                names.hosts.setdefault(norm(h), h)
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
    for n, shown in own.items():
        if not names.part(n):
            names.add_part(shown)
    names_hash = _hash(json.dumps([sorted(names.parts), sorted(names.alias), sorted(names.hosts), sorted(names.indices),
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
        if not use_llm or not L.eligible(u["kind"], u["found"]["lang"]):
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
            across_hash = _hash(json.dumps([u.get("across") or [], u.get("speaks")], sort_keys=True))
            if row is not None and row.chash == ch and not everything and \
                    (row.outline or {}).get("across") == across_hash:
                stats["unchanged"] += 1
                if use_llm and ((row.outline or {}).get("llm") or {}).get("hash") != ch:
                    llm_facts(row, u, None)               # read by the LLM for the first time
                continue
            before = ((row.outline or {}).get("llm") if row is not None else None)
            owner = (u["found"]["workloads"][0]["name"] if len(u["found"]["workloads"]) == 1 else None) or \
                u["found"]["tool"] or doc_owner.get(d.id)
            if "speaks" in u:                              # (not the repository: a role's part, or nobody)
                owner = u["speaks"] or None
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
        db.session.commit()
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
PART_VERBS = ("calls", "reads_from", "sends_to", "uses", "runs_on", "alias", "collects", "scrapes", "owned_by",
              "code_in", "in_group", "monitors")
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

    rel: dict[tuple, dict[str, Any]] = {}
    for f, u in rows:
        s = canon(f.subject)
        o = canon(f.obj) if f.obj_kind in ("part", "host", "group") else f.obj
        key = (s, f.verb, o)
        r = rel.setdefault(key, {"from": s, "kind": f.verb, "to": o, "obj_kind": f.obj_kind, "sources": set(),
                                 "units": set(), "quote": f.quote, "where": u.title or u.ukey})
        r["sources"].add(f.source)
        r["units"].add(u.id)
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
    for u in db.session.query(KUnit):                # every unit's workloads (a manifest with no fact of its own too)
        for w in ((u.outline or {}).get("found") or {}).get("workloads") or []:
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
        elif names.part(job) or job in {canon(x) for x in alias.values()}:
            implied.append({"from": canon(job), "kind": "runs_on", "to": names.hosts.get(norm(host)) or host,
                            "obj_kind": "host", "sources": {"config"}, "units": set(r["units"]),
                            "quote": f"the scrape job {job} reads {host}", "where": r["where"]})
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
    return {"relations": relations, "data_links": data_links, "aliases": [{"name": k, "part": v} for k, v in alias.items()],
            "wiki_edges": sorted(map(list, {tuple(e) for e in wiki_edges})), "diagram_edges": diagram_edges}
