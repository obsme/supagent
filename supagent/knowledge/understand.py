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
import posixpath
import re
from collections import defaultdict
from typing import Any, Iterator

from superset import db

from supagent import __version__

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
ORACLE_THIN = re.compile(r"jdbc:oracle:thin:@(?://)?")    # (0.10.10) jdbc:oracle:thin:@//db-host:1521/svc: an address
DB_PORTS = {5432, 3306, 1433, 1521, 27017, 5433, 26257}
# (0.10.10) a database name inside a server that says nothing of which database it is (the same in every service's
# address): the server's own name is the database's
GENERIC_DB_NAME = re.compile(r"(?i)^(?:apps?|application|db|database|data|main|default|postgres|mysql|mongo|admin|test|"
                             r"public|prod|production|dev|local|service|svc|sys|system|master|primary|store)$")
CACHE_PORTS = {6379, 11211}
LOG_PORTS = {5044: "beats", 24224: "fluent", 4317: "otlp", 4318: "otlp", 514: "syslog", 12201: "gelf"}
LOG_WORDS = re.compile(r"logstash|beats|fluent|syslog|gelf|otlp|otel|collector|appender|logging", re.I)
HTTP_CALL = re.compile(r"\b(?:requests|httpx|session|client|http|aiohttp|urllib\w*|axios|fetch|restTemplate|webClient|"
                       r"HttpClient|HttpRequest|OkHttp\w*|Feign\w*)\b[\w.]*\s*\.?\s*(?:get|post|put|patch|delete|request|"
                       r"send|exchange|newBuilder|fetch|call)\b|\bfetch\s*\(|URI\.create\s*\(", re.I)
WRITES_SQL = re.compile(r"\b(?:INSERT\s+INTO|UPDATE\s+\w+\s+SET|DELETE\s+FROM|MERGE\s+INTO|UPSERT)\b", re.I)
READS_SQL = re.compile(r"\bSELECT\b[\s\S]{1,200}?\bFROM\b", re.I)
IN_CLUSTER = re.compile(r"(?i)\.svc(?:\.|$)")   # (0.10.9) <service>.<namespace>.svc(.cluster.local): a Kubernetes service
GENERIC_LABELS = {"api", "www", "app", "apps", "svc", "service", "services", "web", "srv", "internal", "int", "prod",
                  "local", "localhost", "default", "cluster", "com", "net", "org", "io", "example"}
# (0.10.9.3) a server's first label too common in sentences to name that server there ("the db", "a build")
GENERIC_HOSTS = {"db", "build", "mail", "proxy", "backup", "test", "dev", "staging", "stage", "files", "git", "ci", "dns",
                 "vpn", "lb", "gw", "gateway", "monitoring", "monitor", "logs", "log", "storage", "data", "admin", "ops",
                 "mgmt", "node", "host", "server", "master", "worker", "primary", "replica", "backend", "frontend"}
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
                          r"guides?|tutorials?|fwlink|terms|privacy|policies)\b|"
                          r"\.(?:txt|gz|bz2|xz|zip|tgz|7z|fa|fasta|2bit|bed|gtf|gff3?|vcf|csv|tsv|pdf|png|jpe?g|gif|svg|"
                          r"ico|iso|qcow2|rpm|deb|whl|jar)(?=$|[?#])", re.I)   # (0.10.4) a license, a schema, a page to
#                                         read; (0.10.10) a file to download (genomes.txt, an image, a package): no endpoint
# (0.10.10) an address given as a page about something (description_url=, help_url:, homepage:, logo_url): no endpoint
DOC_KEY = re.compile(r"(?i)(?<![\w-])(?:description|desc|docs?|documentation|help|info|about|homepage|home[_-]?page|website|"
                     r"citation|cite|reference|license|logo|icon|image|avatar|thumbnail|badge|favicon|readme|manual|"
                     r"terms|privacy|tutorial|guide)(?:[_-]?(?:url|uri|link|href))?\s*\"?\s*[:=]\s*[\"']?\s*$")
CATALOGUE_SITES = 8   # (0.10.10) a file naming this many sites of the internet (the data sources, sign-in providers or
#                       formats' pages one may choose): a list of the world's sites, not what the system calls
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


# (0.10.7) the names of files and folders that name no part (a stem or a folder of a repository's layout)
LAYOUT_NAMES = {"main", "app", "application", "index", "config", "configs", "configuration", "settings", "values",
                "defaults", "default", "tasks", "handlers", "vars", "templates", "files", "meta", "readme", "site",
                "hosts", "inventory", "inventories", "docker-compose", "compose", "kustomization", "chart", "charts",
                "src", "lib", "libs", "test", "tests", "docs", "doc", "scripts", "script", "jobs", "job", "bin", "cmd",
                "pkg", "internal", "java", "com", "resources", "deploy", "deployment", "deployments", "manifests",
                "base", "overlays", "prod", "production", "staging", "dev", "roles", "playbooks", "group-vars",
                "host-vars", "rules", "dashboards", "provisioning", "datasources", "services", "service", "apps",
                "clusters", "crontab", "dags", "pipeline", "pipelines", "events", "init", "setup", "utils", "common"}


def file_part(path: str, names: "Names", own: dict[str, str]) -> str | None:
    """(0.10.7) The part a repository's file is named after, else its nearest folder: a configuration of a tool that
    several parts run (prometheus/prometheus-ams1.yml), a repository of jobs (jobs/reporting_export.py) or of
    services (services/checkout/src/...) speak for the part their file or folder names, not for the tool's name
    ("prometheus": another part's other name) nor for the repository."""
    segs = [x for x in str(path or "").split("/") if x]
    if not segs:
        return None
    stem = re.sub(r"(\.[A-Za-z0-9]{1,6})+$", "", segs[-1])
    for c in [stem] + list(reversed(segs[:-1])):
        if len(c) < 3 or norm(c) in LAYOUT_NAMES or names.hosts.get(norm(c)):
            continue
        p = names.part(c) or own.get(norm(c))
        if p:
            return p
    return None


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
                    from supagent.knowledge.projects import stack_name

                    whole = stack_name(d["services"])     # (0.10.9.3) one product's containers: the product
                    out["workloads"] += [{"name": whole, "namespace": ""}] if whole else \
                        [{"name": str(k), "namespace": "", "root": _built_from_root(path, v)}
                         for k, v in d["services"].items()]
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
                      (r"^name:\s*[\"']?([\w.-]+)", r"(^|/)Chart\.ya?ml$"),          # (0.10.10) a Helm chart's
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


def service_folders(units: list[dict[str, Any]]) -> dict[str, str]:
    """(0.10.10) The folders of a repository named after the service a file in them declares ({folder: name}): a
    configuration repository of many services (billing/billing-api/application.properties with
    spring.application.name=billing-api, charts/billing-web/Chart.yaml named billing-web)."""
    out: dict[str, str] = {}
    for u in units:
        declared = u["found"]["names"]
        if len(declared) != 1:
            continue
        segs = (u["path"] or "").split("/")[:-1]
        for i in range(len(segs) - 1, -1, -1):
            if norm(segs[i]) == norm(declared[0]):
                out["/".join(segs[:i + 1])] = declared[0]
                break
    return out


def several_services(units: list[dict[str, Any]]) -> dict[str, str]:
    """(0.10.10) The service folders of a repository holding several services (none: one service or no folder)."""
    folders = service_folders(units)
    return folders if len({norm(x) for x in folders.values()}) > 1 else {}


GENERIC_WORKLOADS = {"web", "app", "api", "server", "backend", "frontend", "worker", "main", "site", "webapp",
                     "service", "application"}


def _built_from_root(path: str, service: Any) -> bool:
    """(0.10.9.3) A Compose service built from its repository's root folder (build: .., from docker/): the repository's
    own code."""
    build = service.get("build") if isinstance(service, dict) else None
    ctx = build.get("context") if isinstance(build, dict) else build
    if not isinstance(ctx, str) or not ctx.strip() or "$" in ctx or "://" in ctx:
        return False
    return posixpath.normpath(posixpath.join(posixpath.dirname(path or ""), ctx.strip())) in (".", "")


def owners(units: list[dict[str, Any]], repo: str | None, names: Names) -> tuple[str | None, list[str]]:
    """A repository's own service and its other names: its one workload (or the one named like the repository), else
    the repository's name when the map knows it; none for a repository of several workloads (each file speaks for its
    own), nor for one of several services' folders (each folder speaks for its service: their names are no other
    names of the repository)."""
    if several_services(units):
        return None, []
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
    rooted = list(dict.fromkeys(w["name"] for u in units for w in (u["found"]["workloads"] or []) if w.get("root")))
    if owner is None and repo and len(rooted) == 1 and norm(rooted[0]) in GENERIC_WORKLOADS:
        owner = repo                                      # (0.10.9.3) the one service built from the repository's
        others = others + rooted                          # root under a common word ("web"): the repository's own
    if owner is None:                                     # application, by the repository's name
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


def _site(host: str) -> str:
    """(0.10.10) The site a public host belongs to (data.example.org, www.example.org: example.org; a.b.gov.uk:
    b.gov.uk)."""
    labels = [x for x in host.lower().split(".") if x]
    n = 3 if len(labels) >= 3 and labels[-2] in ("co", "com", "org", "net", "gov", "gouv", "ac", "edu") else 2
    return ".".join(labels[-n:])


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
        if not host or "{" in host:
            return None
        return resolve(host) or (resolve(host.split(".")[0]) if "." in host else None)   # (0.10.7) "mimir.int.example"

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
                           r"node)\b|\(\s*(?:\w+\s+)?on\b|\bdeployed\s+(?:to|into)\b|\bdéployée?s?\s+sur\b|"
                           r"\bhébergée?s?\s+sur\b|\btourne(?:nt)?\s+sur\b|\bl[äa]uf(?:t|en)\s+auf\b|"
                           r"\bbereitgestellt\s+auf\b|\bbetrieben\s+auf\b|" + RUNS_ON_OTHER, re.I)),   # (0.10.10)
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
    # (0.10.10) what a component takes from a topic and puts on one, in other words ("emits X events", "listens to
    # X", "subscribes to X", "it consumes X", "reads and writes X", "Its database is X"; French, German)
    ("sends_to", re.compile(r"\b(?:emits|produces|publie|publient|émet|émettent|produit|produisent|"
                            r"veröffentlicht|veröffentlichen|publiziert|erzeugt)\b", re.I)),
    ("reads_from", re.compile(r"\b(?:listens?\s+(?:to|on)|subscribes?\s+to|consumes|reads\s+and\s+writes|"
                              r"(?:database|datastore|data\s+store|db)\s+is|s['’]abonnent?\s+à|consomment?|écoutent?|"
                              r"abonniert|abonnieren|konsumiert|konsumieren|hört\s+auf)\b", re.I)),
    ("calls", re.compile(r"\bsends?\s+requests?\s+to\b", re.I)),
    # (0.10.10) Spanish and Italian: "Se despliega en x", "Gira su x", "Publica en t", "Consuma t", "Usa la base de
    # datos d", "Usa il database d"
    ("runs_on", re.compile(r"\bse\s+despliega(?:n)?\s+en\b|\bdesplegad[oa]s?\s+en\b|\bse\s+ejecuta(?:n)?\s+en\b|"
                           r"\bgira(?:no)?\s+su\b|\b(?:viene|vengono)\s+distribuit[oi]\s+su\b|\beseguit[oi]\s+su\b",
                           re.I)),
    ("sends_to", re.compile(r"\bpublica(?:n)?\s+en\b|\bpubblica(?:no)?\s+su\b", re.I)),
    ("reads_from", re.compile(r"\bconsume(?:n)?\b|\bconsuma(?:no)?\b|\bse\s+suscribe(?:n)?\s+a\b|"
                              r"\bsi\s+iscrive(?:no)?\s+a\b|\b(?:usa|usan|utiliza|utilizan)\s+la\s+base\s+de\s+datos\b|"
                              r"\b(?:usa|usano|utilizza|utilizzano)\s+il\s+database\b", re.I)),
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
# (0.10.7) the source of a diagram written in a page or a file (Mermaid, PlantUML): the diagram reader reads its
# arrows; read as sentences too, a Mermaid source's lines ran into one another (a dot in a node's name, "orders.placed",
# ended no line) and an arrow's label ("publishes / writes") linked its part to every part of the following lines
DIAGRAM_HEAD = re.compile(r"(?:(?:graph|flowchart)\s+(?:TD|TB|BT|RL|LR)\b|sequenceDiagram\b|classDiagram\b|"
                          r"stateDiagram(?:-v2)?\b|erDiagram\b|C4(?:Context|Container|Component)\b)")
DIAGRAM_LINE = re.compile(r"-->|---|-\.->|==>|->>|-->>|-\)|[\[({]|^(?:subgraph|end|classDef|class|style|click|"
                          r"participant|actor|note|linkStyle|direction|%%)\b", re.I)


MERMAID_BOX = re.compile(r"([A-Za-z0-9_][\w.:-]*)\s*[\[({>]+\s*\"?([^\]){}\"|\n]+?)\"?\s*[\]){}]+")


def _boxes_said(line: str) -> str:
    """A Mermaid line's boxes whose label says more than their name ("db[(shopdb on dbsrv1)]"): "db (shopdb on
    dbsrv1).", each its own sentence; the arrows and their labels are the diagram reader's."""
    return " ".join(f"{i} ({lab.strip()})." for i, lab in MERMAID_BOX.findall(line)
                    if lab.strip() and norm(lab) != norm(i))


def diagram_free(text: str) -> str:
    """The text with the sources of its diagrams blanked (the same length, its lines kept): a ```mermaid or ```plantuml
    fence, an @startuml ... @enduml block, a Mermaid block that starts with its header ("graph LR", "flowchart TD",
    "sequenceDiagram"...) and goes on while its lines are diagram statements. Of a Mermaid line, only what its boxes'
    labels say of them stays, a sentence each."""
    out: list[str] = []
    mode = ""                                           # "mermaid-fence", "fence", "plant", "mermaid" or ""
    for ln in text.split("\n"):
        s = ln.strip()
        keep = None                                     # what stays of a blanked line ("": nothing)
        if mode in ("fence", "mermaid-fence"):
            keep = _boxes_said(ln) if mode == "mermaid-fence" and not s.startswith("```") else ""
            mode = "" if s.startswith("```") else mode
        elif mode == "plant":
            keep, mode = "", ("" if s.lower().startswith("@enduml") else "plant")
        elif re.match(r"```\s*mermaid\b", s, re.I):
            keep, mode = "", "mermaid-fence"
        elif re.match(r"```\s*(plantuml|puml)\b", s, re.I):
            keep, mode = "", "fence"
        elif s.lower().startswith("@startuml"):
            keep, mode = "", "plant"
        elif DIAGRAM_HEAD.match(s):
            keep, mode = "", "mermaid"
        elif mode == "mermaid" and s and DIAGRAM_LINE.search(s) and not s.startswith("#"):
            keep = _boxes_said(ln)
        else:
            mode = "" if mode == "mermaid" else mode
        if keep is None:
            out.append(ln)
        else:
            out.append(keep[:len(ln)].ljust(len(ln)) if len(keep) <= len(ln) else " " * len(ln))
    return "\n".join(out)


FLOW_SOURCE = re.compile(r"(^|-)(rabbitmq|rabbit|kafka|nats|activemq|artemis|pulsar|sqs|kinesis|queue|broker|mq|redis|"
                         r"mysql|mariadb|postgres|postgresql|pgsql|mongo|mongodb|cassandra|db|database|elasticsearch|"
                         r"opensearch|s3|minio|bucket|storage)(-|$)", re.I)   # (0.10.4) what is read, never calls
ARROW = re.compile(r"\s*(→|⟶|->|-->|←|⟵|<-|<--)\s*")
FLOW_LABEL = re.compile(r"\b(alerts?|notifications?|events?|logs?|metrics?|messages?|spans?|traces?|records?)\b", re.I)
SOURCE_LABEL = re.compile(r"\bdata\s*-?\s*sources?\b|\bdatasources?\b|\bsource\s+of\s+data\b", re.I)
PARTS_COLUMN = re.compile(r"\b(services?|applications?|apps?|components?|containers?|software|processes|daemons?|"
                          r"workloads?|runs|parts?|roles?)\b", re.I)
# (0.10.9) what a column of a table of hosts says of its host besides what runs there: its power, its network ports, its
# owner ("Server | Uplinks | Power feed | Maintainer"): (the link, its target's kind for the category it goes in)
# (0.10.9) what a cell writes for nothing: no value of the map ("Calls: None", "Owner: TBD", "-")
PLACEHOLDER = re.compile(r"(?i)(?:none|n/?a|tb[ad]|todo|null|nil|unknown|not applicable|nothing|empty|n\.a\.|no|yes|"
                         r"aucune?|néant|keine?|ninguno|nessuno|[-—–?/.*]+)")


ID_TOKEN = re.compile(r"[A-Za-z0-9][\w-]*(?:[._-][\w-]+)+")   # (0.10.10) a name with a separator: pr.record.done


def _cell_values(cell: str) -> list[str]:
    """(0.10.9) The values a table's cell names, apart (commas, semicolons, "and"), a placeholder for nothing left out;
    (0.10.10) names with separators listed with spaces or slashes ("pg-a-01 pg-a-02", "pool-a / pool-b") apart too."""
    out = []
    for v in (x.strip() for x in re.split(r",|;|\band\b", cell)):
        if not v or PLACEHOLDER.fullmatch(v):
            continue
        toks = [t for t in re.split(r"\s*/\s+|\s+/\s*|\s+", v) if t]
        out += toks if len(toks) > 1 and all(ID_TOKEN.fullmatch(t) for t in toks) else [v]
    return out


HOST_HEAD = re.compile(r"(?i)host\s*names?|fqdns?|servidor(?:es)?|serveurs?|h[ôo]tes?|rechner|nom\s+d[eu]\s+serveur|"
                       r"nombre\s+del?\s+servidor")    # (0.10.9) a table of hosts by its host column ("Hostname")
INFRA_INDEX = r"(?:\s*[-_#]?\s*(?:\d{1,2}|[a-dA-D]))?"   # one column per supply or link: PSU1, PSU_A, Uplink 2
INFRA_COLUMNS = [
    ("powered_by", re.compile(r"\b(pdus?|power(?:\s+(?:feeds?|supply|supplies|sources?|strips?))?|psus?|ups|"
                              r"alimentaci[oó]n|alim|alimentations?|fuentes?|netzteile?|stromversorgung)" +
                              INFRA_INDEX + r"\b", re.I), "power"),
    ("connects_to", re.compile(r"\b(switch(?:es)?(?:\s+ports?)?|(?:network\s+|uplink\s+)?ports?|uplinks?|tor|puertos?|"
                               r"commutateurs?|"
                               r"top[\s-]of[\s-]rack|connected\s+to|cabling)" + INFRA_INDEX + r"\b", re.I), "port"),
    ("owned_by", re.compile(r"\b(owners?|owned\s+by|team|squad|responsible|maintainers?|responsables?|propietarios?|"
                            r"[ée]quipes?|equipos?|verantwortlich|eigent[üu]mer)\b", re.I), "team"),
]
# (0.10.9) a host's network card or interface ("NIC 1", "Interface 2"): a port only when the cell names a switch and
# its port ("sw-1 / Ethernet1/10"), never a lone word (a card's model, X710)
NIC_COLUMN = re.compile(r"\b(nics?|network\s+(?:cards?|interfaces?|adapters?)|interfaces?)" + INFRA_INDEX + r"\b", re.I)
# a column saying something else of them: "PSU status", "Uplink speed", "Power usage (W)", "Switch model", "Port VLAN"
INFRA_NOT = re.compile(r"\b(status|state|health|speed|bandwidth|count|number|usage|load|watts?|kw|amps?|volts?|voltage|"
                       r"mode|type|model|capacity|consumption|redundan\w*|vlans?|mac|ip|address(?:es)?)\b", re.I)
DEVICE = r"[A-Za-z][\w.-]*?[-_.\d][\w.-]*?"      # (0.10.9) a device's name: a letter first, a digit or a separator in it
IFACE = (r"(?:(?:ethernet|eth|et|e|gigabitethernet|gige|gig|gi|g|tengigabitethernet|tengige|ten|te|twentyfivegige|twe|"
         r"fortygigabitethernet|fortygige|fo|hundredgige|hu|fastethernet|fa|xe|ge|swp|port|p)-?\d+(?:/\d+)*|"
         r"\d+(?:/\d+)+|\d{1,3})")     # an interface: Ethernet1/10, Eth1/10, E1/10, ge-0/0/10, xe-1/0/3, 1/0/5, 24
# (0.10.9) a cell naming a power supply with its outlet ("pdu-b07-l / 1", "pdu-b07-l:1", "pdu-b07-l/1", "pdu-b07-l #1",
# "pdu-b07-l outlet 3") or a switch with its port ("sw-1 / Ethernet1/10", "sw-1:Eth1/10", "sw-1/E1/10", "sw-1 ge-0/0/10",
# "Gi1/0/5 on sw-1"): the device, and for a port the device and its interface
POWER_CELL = re.compile(r"(?P<dev>" + DEVICE + r")(?:\s*(?:/|:|#)\s*\d+|\s+(?:outlet|socket|port|o)\s*#?\s*\d+)?")
PORT_CELL = re.compile(r"(?P<dev>" + DEVICE + r")\s*(?:/|:|\s)\s*(?:port\s+)?(?P<iface>" + IFACE + r")|"
                       r"(?P<iface2>" + IFACE + r")\s+on\s+(?P<dev2>" + DEVICE + r")", re.I)


# (0.10.9) an interface's usual abbreviations, one name each: Eth1/10, Et1/10, E1/10 -> Ethernet1/10; Gi1/0/5, Gig1/0/5 ->
# GigabitEthernet1/0/5 (Juniper's ge-0/0/1, xe-, et- are names already)
IFACE_NAMES = [(re.compile(r"(?i)^(?:ethernet|eth|et|e)(?=\d)"), "Ethernet"),
               (re.compile(r"(?i)^(?:gigabitethernet|gige|gig|gi|g)(?=\d)"), "GigabitEthernet"),
               (re.compile(r"(?i)^(?:tengigabitethernet|tengige|ten|te)(?=\d)"), "TenGigabitEthernet"),
               (re.compile(r"(?i)^(?:twentyfivegige|twe)(?=\d)"), "TwentyFiveGigE"),
               (re.compile(r"(?i)^(?:fortygigabitethernet|fortygige|fo)(?=\d)"), "FortyGigabitEthernet"),
               (re.compile(r"(?i)^(?:hundredgige|hu)(?=\d)"), "HundredGigE"),
               (re.compile(r"(?i)^(?:fastethernet|fa)(?=\d)"), "FastEthernet")]


def _iface(name: str) -> str:
    """(0.10.9) An interface's one name whatever the abbreviation written ("Eth1/10" and "Ethernet1/10": one port)."""
    for rx, full in IFACE_NAMES:
        if rx.match(name):
            return rx.sub(full, name, count=1)
    return name


HOST_NIC = re.compile(r"(?i)(?:eth|eno|ens|enp|em|bond|nic|vmnic|lan|wan|mgmt|ilo|idrac|bmc)\d")   # the host's own


POWER_NAME = r"(?:[A-Za-z][\w.-]*?)?(?:pdu|ups|psu|rpp|ats|feed|panel)[\w.-]*"   # a power device's name by its words
_PW = r"(?<![\w.-])(" + POWER_NAME + r")(?![\w-])"
POWER_FEEDS = re.compile(_PW + r"\s+(?:feeds|supplies|powers)\s+((?:" + POWER_NAME + r")(?:\s*(?:,|and|&)\s*(?:"
                         + POWER_NAME + r"))*)", re.I)
POWER_FED = re.compile(r"(?<![\w.-])((?:" + POWER_NAME + r")(?:\s*(?:,|and|&)\s*(?:" + POWER_NAME + r"))*)\s*(?:\(\s*)?"
                       r"(?:(?:is|are)\s+)?(?:fed|powered|supplied)\s+(?:by|from)\s+" + _PW, re.I)


def _power_sentence(sentence: str) -> list[tuple[str, str]]:
    """(0.10.9) What a sentence says powers what, both ends power devices by their names (a PDU, a UPS, a feed, a
    panel: "UPS-A feeds pdu-1 and pdu-2", "pdu-1 and pdu-2 are fed by UPS-A", "pdu-1 (fed from UPS-A)"):
    [(device, its supply)]. A device's name has a digit or a separator (no "the UPS")."""
    out: list[tuple[str, str]] = []
    named = lambda x: bool(re.search(r"[-_.\d]", x))                    # noqa: E731

    def clean(x: str) -> str:
        return x.strip().rstrip(".")                      # a sentence's full stop is no part of the name

    def each(listed: str) -> list[str]:
        return [clean(x) for x in re.split(r",|\band\b|&", listed) if clean(x)]

    for m in POWER_FEEDS.finditer(sentence):
        out += [(d, clean(m.group(1))) for d in each(m.group(2)) if named(d) and named(m.group(1))]
    for m in POWER_FED.finditer(sentence):
        out += [(d, clean(m.group(2))) for d in each(m.group(1)) if named(d) and named(m.group(2))]
    return [(d, sup) for d, sup in dict.fromkeys(out) if norm(d) != norm(sup)]


def _infra_values(verb: str, value: str, ports_only: bool = False) -> list[str]:
    """(0.10.9) The link targets a cell of a table of hosts names: one (_infra_value), or the devices a slash keeps
    apart in one cell ("pdu-a / pdu-b", "PSU1 / PSU2" written as their PDUs)."""
    one = _infra_value(verb, value, ports_only)
    if one:
        return [one]
    if "/" in value and verb in ("powered_by", "connects_to"):
        parts = [x.strip() for x in value.split("/")]
        got = [_infra_value(verb, x, ports_only) for x in parts if x]
        if len(parts) >= 2 and all(got) and all(re.search(r"[A-Za-z]", x) for x in parts):
            return [g for g in got if g]
    return []


def _infra_value(verb: str, value: str, ports_only: bool = False) -> str | None:
    """(0.10.9) The link's target a cell of a table of hosts names, in one spelling ("<switch> <interface>" for a
    port), else None (a status, a number, a person, a word); `ports_only`: a switch's port, never a lone name."""
    if verb == "powered_by":
        m = POWER_CELL.fullmatch(value)
        return m.group("dev") if m else None
    if verb == "connects_to":
        m = PORT_CELL.fullmatch(value)
        if m and re.fullmatch(IFACE, m.group("dev") or m.group("dev2"), re.I):
            return None                                   # (0.10.9) "GigabitEthernet1/0/11": a port alone, its switch
        if m and not HOST_NIC.match(m.group("dev") or m.group("dev2")):   # in the header: no device named here
            return f"{m.group('dev') or m.group('dev2')} {_iface(m.group('iface') or m.group('iface2'))}"
        return value if not m and not ports_only and re.fullmatch(DEVICE, value) and re.search(r"\d", value) and \
            not HOST_NIC.match(value) and not re.fullmatch(IFACE, value, re.I) else None   # a switch, no port; never
        #                                                   the host's own eth0, bond0; never a port alone (Eth1/2)
    return value if INFRA_VALUE[verb].search(value) else None


INFRA_VALUE = {   # (0.10.9) what such a cell must look like to be a link (or name a part already known): a device's
    #               name (pdu-a-left, ups2: a digit or a separator in it; not "OK", "yes"), a device and its interface
    #               (sw-1 ge-0/0/10), a team (not a person, not a port number)
    "powered_by": re.compile(r"^[A-Za-z][A-Za-z]*[-_.\d][\w.-]*$"),
    "connects_to": re.compile(r"^[A-Za-z][\w.-]*\d[\w.-]*\s+[A-Za-z]*-?\d+(?:/\d+)*$|^[A-Za-z][\w.-]*\d[\w.-]*$"),
    "owned_by": re.compile(r"\b(team|squad|tribe|crew|group|ops|devops|sre|platform|guild|[ée]quipe|equipo|grupo|"
                           r"groupe|plateforme)\b", re.I),
}
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


# (0.10.9.3) a column naming the area or the domain a row's part belongs to ("Area", "Service area", "Domain")
AREA_COL = re.compile(r"(?i)^\s*(?:(?:service|business|functional|platform)\s+)?(?:areas?|domains?|domaines?|"
                      r"dominios?|bereiche?|domänen?)\s*$")
PART_OF_HEAD = re.compile(r"^\s*(?:apps?|applications?|services?|platform\s+services?|systems?|products?|parent|"
                          r"part\s+of|belongs\s+to)\s*$", re.I)   # (0.10.10) a module's whole, in a table of modules
COLUMNS = [   # what a table's column says of its row's part (its header)
    ("runs_on", re.compile(r"\b(runs?\s+on|hosts?|servers?|nodes?|machines?|vms?|platform|cluster|located|hosting|"
                           r"hosted\s+on|deployed\s+(?:to|on))\b|"
                           r"\b(?:target|host|inventory|ansible|server|deployment)\s+groups?\b|^\s*groups?\s*$", re.I)),
    #                         (0.10.5) "Target Group", "Inventory group": where a role runs, not what it monitors
    ("monitors", re.compile(r"\b(scrapes?|scraped\s+targets?|monitors|watches|probes|targets?)\b", re.I)),   # (0.10.4)
    ("owned_by", re.compile(r"\b(owners?|owned\s+by|team|squad|responsible|maintainers?|maintained\s+by|accountable|"
                            r"contacts?|(?:run|operated|managed|supported)\s+by)\b", re.I)),   # (0.10.9.3) "Run by"
    ("alias", re.compile(r"^\s*(?:short\s+names?|abbreviations?|acronyms?|aliases|aka|nom\s+court|kurzname)\s*$", re.I)),
    ("reads_from", re.compile(r"^\s*(?:reads?|reads?\s+from|consumes?|subscribes?(?:\s+to)?|inputs?|in)\s*$", re.I)),
    ("sends_to", re.compile(r"^\s*(?:writes?|writes?\s+(?:to|into)|publishes|publishes\s+to|produces?|outputs?|"
                            r"out)\s*$", re.I)),     # (0.10.10) a table of jobs or modules: what each reads, writes
    ("uses", re.compile(r"\b(depends?\s+on|dependencies|dependency|requires)\b|^\s*(?:dbs?|databases?|datastores?|"
                        r"data\s+stores?)\s*$", re.I)),   # (0.10.9) what it needs:
    #                         a dependency, written from the dependent's side, not a call ("Depends on: prometheus")
    ("calls", re.compile(r"\b(calls|upstreams?|uses|clients?\s+of)\b", re.I)),
    ("logs_to", re.compile(r"\b(logs?|log\s+index|indices|indexes)\b", re.I)),
    ("watched_by", re.compile(r"\b(metrics?|dashboards?|monitoring|alerts?)\b", re.I)),
    ("code_in", re.compile(r"\b(repo|repository|repositories|code|source)\b", re.I)),
]


# (0.10.10) a table of jobs: what each takes from (its source) and puts into (its target); a column naming a row's
# whole whatever the table ("Owning application"); who writes or reads a row (a table of topics: "Producer",
# "Consumers"); who uses it ("Used by"); a table of places listing what runs in each ("Namespace | Workloads")
JOB_HEAD = re.compile(r"(?i)^\s*(?:(?:cron|batch|scheduled|etl)?\s*jobs?|cronjobs?|tasks?|scheduled\s+tasks?|pipelines?|"
                      r"etls?|batch(?:es)?)\s*$")
SOURCE_COL = re.compile(r"(?i)^\s*(?:sources?|inputs?|from|reads?(?:\s+from)?|origin)\s*$")
TARGET_COL = re.compile(r"(?i)^\s*(?:targets?|destinations?|outputs?|to|sinks?|writes?(?:\s+(?:to|into))?)\s*$")
OWNING_HEAD = re.compile(r"(?i)^\s*(?:owning\s+(?:application|app|system|service)|owner\s+(?:application|app|system)|"
                         r"belongs\s+to|part\s+of|parent\s+(?:application|system)|application\s+owner)\s*$")
PRODUCER_COL = re.compile(r"(?i)^\s*(?:producers?|publishers?|writers?|written\s+by|published\s+by|produced\s+by)\s*$")
CONSUMER_COL = re.compile(r"(?i)^\s*(?:consumers?|subscribers?|readers?|listeners?|read\s+by|consumed\s+by)\s*$")
CALLER_COL = re.compile(r"(?i)^\s*(?:used\s+by|callers?|called\s+by)\s*$")
BUS_COL = re.compile(r"(?i)^\s*(?:(?:event\s+|message\s+)?bus|brokers?|(?:kafka\s+)?clusters?)\s*$")
EXTERNAL_HEAD = re.compile(r"(?i)^\s*(?:external\s+(?:systems?|services?|apis?|parties|partners?)|partners?|"
                           r"third[\s-]+part(?:y|ies)|vendors?|suppliers?|partner\s+apis?)\s*$")
TOPIC_HEAD = re.compile(r"(?i)^\s*(?:topics?|queues?|streams?|event\s+topics?|channels?)(?:\s+names?)?\s*$")
PLACE_HEAD = re.compile(r"(?i)^\s*(?:namespaces?|(?:server\s+|node\s+)?pools?|host\s+groups?|server\s+groups?|"
                        r"clusters?)\s*$")


# (0.10.10) a page's properties (Confluence's Page Properties, a "Property | Value" table, "Key: value" lines):
# what its row says of the part the page is about, by the property's name (English, French, German)
KV_HEAD = re.compile(r"(?i)^\s*(?:propert(?:y|ies)|keys?|attributes?|fields?|items?|parameters?|settings?|"
                     r"propriétés?|clés?|attributs?|champs?|eigenschaften?|schlüssel|merkmale?|felder?)\s*$")
KV_VALUE = re.compile(r"(?i)^\s*(?:values?|details?|descriptions?|infos?|information|valeurs?|détails?|werte?|"
                      r"angaben?)\s*$")
PROPERTIES = [
    ("part_of", "part", re.compile(r"(?i)^(?:domain|domaine|domäne|application|app|anwendung|system|système|área|area|"
                                   r"ámbito|dominio|sistema|"
                                   r"product(?:\s+line)?|produit|platform|plateforme|belongs\s+to|part\s+of|parent|"
                                   r"appartient\s+à|gehört\s+zu|teil\s+von)$")),
    ("owned_by", "owner", re.compile(r"(?i)^(?:(?:[\w-]+\s+)?owners?|owned\s+by|(?:[\w-]+\s+)?(?:team|squad|tribe)|"
                                     r"(?:team|equipo|squadra)(?:\s+[\w-]+)?|propietario|proprietario|"
                                     r"maintained\s+by|maintainers?|"
                                     r"accountable(?:\s+(?:team|squad|tribe))?|responsible(?:\s+(?:team|squad))?|"
                                     r"(?:support|owning)\s+team|équipe(?:\s+responsable)?|responsable|"
                                     r"verantwortlich(?:es\s+team)?|zuständig(?:es\s+team)?|eigentümer)$")),
    ("alias", "part", re.compile(r"(?i)^(?:short\s+name|abbreviation|acronym|aliases|alias|also\s+known\s+as|"
                                 r"a\.?k\.?a\.?|other\s+names?|nom\s+court|abréviation|sigle|acronyme|kurzname|"
                                 r"abkürzung|kürzel)$")),
    ("uses", "database", re.compile(r"(?i)^(?:databases?|datastores?|data\s+stores?|stores?|dbs?|base(?:s)?\s+de\s+données|"
                                    r"datenbank(?:en)?)$")),
    ("sends_to", "part", re.compile(r"(?i)^(?:emits|publishes(?:\s+to)?|produces|writes(?:\s+to)?|outputs?|"
                                    r"events?\s+out|topics?\s+out|publie|écrit|produit|veröffentlicht|schreibt|"
                                    r"sendet)$")),
    ("reads_from", "part", re.compile(r"(?i)^(?:listens\s+to|subscribes(?:\s+to)?|consumes|reads(?:\s+from)?|inputs?|"
                                      r"events?\s+in|topics?\s+in|s['’]abonne\s+à|consomme|écoute|abonniert|"
                                      r"konsumiert|liest)$")),
    ("calls", "part", re.compile(r"(?i)^(?:talks\s+to|calls|upstreams?|clients?\s+of|appelle|ruft(?:\s+auf)?)$")),
    ("runs_on", "host", re.compile(r"(?i)^(?:deployed\s+(?:to|on|in)|runs?\s+(?:on|in)|running\s+(?:on|in)|"
                                   r"hosted\s+(?:on|in)|hosting|servers?|hosts?|"
                                   r"déployée?\s+sur|hébergée?\s+sur|läuft\s+auf|bereitgestellt\s+auf|"
                                   r"betrieben\s+auf)$")),
]


def _property(key: str) -> tuple[str, str] | None:
    """(0.10.10) The link a page's property says by its name ("Maintained by": owned_by), else none."""
    k = " ".join(re.sub(r"[*`:]+", " ", key or "").split())
    return next(((verb, kind) for verb, kind, rx in PROPERTIES if rx.fullmatch(k)), None)


def _key_values(t0: int, header: list[str], rows: list[tuple[int, list[str]]]) -> list[tuple[int, str, str]] | None:
    """(0.10.10) A table of a page's properties as (position, key, value): two columns, "Property | Value" on top or
    keys the reader knows down its first column (its first row is one of them: no header)."""
    every = [(t0, header)] + rows
    if any(len(c) != 2 for _r, c in every):
        return None
    if KV_HEAD.match(header[0]) and KV_VALUE.match(header[1]):
        return [(r, c[0], c[1]) for r, c in rows]
    known = sum(1 for _r, c in every if _property(c[0]))
    return [(r, c[0], c[1]) for r, c in every] if known >= 2 and 2 * known >= len(every) else None


PARTS_HEAD = re.compile(r"(?i)^\s*(?:modules?|components?|micro-?services?|sub-?systems?|composants?|komponenten?)\s*$")
DEPLOYABLE_HEAD = re.compile(r"(?i)^\s*(?:modules?|components?|micro-?services?|services?|svcs?|apps?|applications?|"
                             r"workers?|jobs?|workloads?|apis?)\s*$")


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


# (0.10.10) what a part is made of, and what it is part of, as pages write it ("X is a module of the Y service", "Y is
# made of A, B and C", "X fait partie de Y", "Modules: A, B"): a system and its parts, the communities of the map
MEMBER_KIND = (r"(?:parts?|modules?|components?|micro-?services?|services?|applications?|apps?|sub-?systems?|pieces?|"
               r"members?|elements?|workers?|apis?|jobs?|consumers?|platform\s+services?)")
MEMBER_KIND_FR = r"(?:modules?|composants?|services?|micro-?services?|applications?|parties?|éléments?|briques?)"
# (0.10.10) German, the roles a component plays ("the event listener of X", "the backend for the front end of X"),
# what places are made of ("the production environment has these server pools: ...")
MEMBER_KIND_DE = r"(?:komponenten|komponente|module?|dienste?|services?|anwendungen|anwendung|teile?|bestandteile?|systeme?)"
ROLE_KIND = (r"(?:front[\s-]?ends?|back[\s-]?ends?(?:\s+for\s+the\s+front[\s-]?end)?|bffs?|listeners?|importers?|"
             r"exporters?|senders?|notifiers?|processors?|schedulers?|gateways?|adapters?|connectors?|daemons?|uis?|"
             r"endpoints?|producers?|publishers?|runners?|(?:user\s+)?interfaces?)")
PLACE_KIND = (r"(?:(?:server\s+|node\s+|host\s+)?pools?|host\s+groups?|server\s+groups?|namespaces?|clusters?|"
              r"environments?)")
PLACE_KIND_FR = r"(?:pools?|groupes?\s+de\s+serveurs|namespaces?|clusters?|environnements?)"
PLACE_KIND_DE = r"(?:pools?|servergruppen|namespaces?|cluster|umgebungen?)"
MEMBER_OF = re.compile(r"^\W*(?:the\s+)?(?P<a>.+?)\s+(?:(?:is|are)\s+|[—–]\s*|-{1,2}\s+)(?:(?:a|an|one|the)\s+)?"
                       r"(?:[\w-]+\s+){0,2}?(?P<kind>"
                       + MEMBER_KIND + "|" + ROLE_KIND + r")\s+of\s+(?:the\s+|a\s+|an\s+)?"
                       r"(?P<b>[^:;]+?)(?:\s*[:;]\s.*)?\s*[.;]?\s*$", re.I)   # (0.10.10) "...: the event listener"
PLACE_OF = re.compile(r"^\W*(?:the\s+)?(?P<a>.+?)\s+(?:is|are)\s+(?:(?:a|an|one|the)\s+)?(?:[\w-]+\s+)?(?P<kind>"
                      + PLACE_KIND + r")\s+of\s+(?:the\s+)?(?P<b>[^:;]+?\s(?:environment|landscape|cluster|datacenter|"
                      r"data\s+center|site|region|zone))\s*[.;]?\s*$", re.I)   # (0.10.10) "a pool of the prod environment"
BELONGS = re.compile(r"^\W*(?:the\s+)?(?P<a>.+?)\s+belongs?\s+to\s+(?:the\s+)?(?P<b>.+?)\s*[.;]?\s*$", re.I)
MADE_OF = re.compile(r"^\W*(?:the\s+)?(?P<b>.+?)\s+(?:(?:is|are)\s+(?:made\s+(?:up\s+)?of|composed\s+of|built\s+(?:from|of))|"
                     r"consists?\s+of|comprises?)\s+(?:the\s+)?(?:(?:[\w-]+\s+)?" + MEMBER_KIND +
                     r"\s+)?(?P<list>.+?)\s*[.;]?\s*$", re.I)
MEMBER_OF_FR = re.compile(r"^\W*(?:l[ea]\s+|les\s+|l['’])?(?P<a>.+?)\s+(?:est|sont)\s+(?:(?:un|une|le|la|les)\s+|l['’])?"
                          r"(?P<kind>" + MEMBER_KIND_FR + r")(?:\s*[«“\"„][^»”\"“]{0,40}[»”\"“])?\s+(?:de|du|des|d['’])"
                          r"\s*(?:la\s+|le\s+|l['’])?(?P<b>.+?)\s*[.;]?\s*$", re.I)   # (0.10.10) « its role » between
MEMBER_OF_DE = re.compile(r"^\W*(?P<a>.+?)\s+(?:ist|sind)\s+(?:die|der|das|eine?|ein)\s+(?P<kind>" + MEMBER_KIND_DE +
                          r")(?:\s*[„“\"«][^“”\"»]{0,40}[“”\"»])?\s+(?:von|der|des)\s+(?P<b>.+?)\s*[.;]?\s*$", re.I)
MEMBER_KIND_ES = r"(?:microservicios?|componentes?|módulos?|servicios?|aplicaci(?:ón|ones))"
MEMBER_KIND_IT = r"(?:microservizi[oi]?|component[ei]|modul[oi]|serviz[io]|applicazion[ei])"
MEMBER_OF_ES = re.compile(r"^\W*(?:el\s+|la\s+)?(?P<a>.+?)\s+(?:es|son)\s+(?:el|la|los|las|un|una|uno)\s+(?P<kind>" +
                          MEMBER_KIND_ES + r")(?:\s*[«“\"][^»”\"“]{0,40}[»”\"“])?\s+(?:del|de\s+la|de\s+los|de)\s+"
                          r"(?:sistema\s+|aplicaci[oó]n\s+|plataforma\s+)?(?P<b>.+?)\s*[.;]?\s*$", re.I)
MEMBER_OF_IT = re.compile(r"^\W*(?:il\s+|lo\s+|la\s+)?(?P<a>.+?)\s+(?:è|sono)\s+(?:il|lo|la|l['’]|un|uno|una|i|gli|le)\s*"
                          r"(?P<kind>" + MEMBER_KIND_IT + r")(?:\s*[«“\"][^»”\"“]{0,40}[»”\"“])?\s+(?:del|della|dello|"
                          r"dei|degli|di)\s+(?:sistema\s+|applicazione\s+|piattaforma\s+)?(?P<b>.+?)\s*[.;]?\s*$", re.I)
MADE_OF_ES_IT = re.compile(r"^\W*(?:el\s+|la\s+|il\s+|lo\s+)?(?:sistema\s+|aplicaci[oó]n\s+|applicazione\s+|"
                           r"plataforma\s+|piattaforma\s+)?(?P<b>.+?)\s+(?:se\s+compone\s+de|está\s+compuest[oa]\s+"
                           r"(?:por|de)|consta\s+de|está\s+formad[oa]\s+por|si\s+compone\s+di|è\s+compost[oa]\s+da|"
                           r"è\s+costituit[oa]\s+da)\s+(?P<list>.+?)\s*[.;]?\s*$", re.I)
PART_DE = re.compile(r"^\W*(?:die\s+|der\s+|das\s+)?(?P<a>.+?)\s+gehör(?:t|en)\s+zu(?:r|m)?\s+(?P<b>.+?)\s*[.;]?\s*$", re.I)
PART_FR = re.compile(r"^\W*(?:l[ea]\s+|les\s+|l['’])?(?P<a>.+?)\s+fai(?:t|s|sons|tes|ont)\s+partie\s+(?:de|du|des|d['’])"
                     r"\s*(?:la\s+|le\s+|l['’])?(?P<b>.+?)\s*[.;]?\s*$", re.I)
MADE_OF_FR = re.compile(r"^\W*(?:l[ea]\s+|les\s+|l['’])?(?P<b>.+?)\s+(?:(?:est|sont)\s+(?:composée?s?|constituée?s?|formée?s?)"
                        r"\s+(?:de|d['’])|se\s+compose\s+(?:de|d['’])|comprend)\s+(?:(?:les\s+|des\s+)?" + MEMBER_KIND_FR +
                        r"\s+)?(?P<list>.+?)\s*[.;]?\s*$", re.I)
# (0.10.10) a whole's own page listing what it is made of after a label ("Built from: a, b and c", "Composé de : a, b",
# "Besteht aus: a, b", "Compuesto por: a, b", "Composto da: a, b")
MADE_OF_LABEL = re.compile(r"^\W*(?:(?:it\s+is\s+)?(?:built\s+(?:from|of|with)|made\s+(?:up\s+)?of|composed\s+of)|"
                           r"consists?\s+of|comprises?|composée?s?\s+(?:de|d['’])|constituée?s?\s+(?:de|d['’])|"
                           r"besteht\s+aus|bestehend\s+aus|compuest[oa]s?\s+(?:por|de)|formad[oa]s?\s+por|"
                           r"compost[oaie]\s+da|costituit[oaie]\s+da)\s*:\s*(?P<list>.+?)\s*[.;]?\s*$", re.I)
LABEL_LIST = re.compile(r"^\W*(?P<label>" + MEMBER_KIND + r"|" + MEMBER_KIND_FR + r"|" + MEMBER_KIND_DE +
                        r")(?:\s+(?:of|de|du|des|von|der)\s+(?:the\s+|la\s+|le\s+)?(?P<b>[^:]+?))?\s*:\s*(?P<list>.+?)\s*[.;]?\s*$",
                        re.I)
# (0.10.10) a whole and the list of its parts after a colon ("X has the following components: a, b", "the clinical
# domain groups the following applications: ...", "the components of X are a, b and c", French, German)
HAS_LIST = re.compile(r"^\W*(?:the\s+)?(?P<b>.+?)\s+(?:has|have|groups|group|includes?|contains?|covers?|gathers?|"
                      r"brings\s+together)\s+(?:(?:the\s+)?following|these|those|its|the|\d+|two|three|four|five|six)?"
                      r"\s*(?:[\w-]+\s+){0,2}?(?P<kind>" + MEMBER_KIND + "|" + PLACE_KIND + r")\s*(?:\([^)]*\))?\s*:\s*"
                      r"(?P<list>.+?)\s*[.;]?\s*$", re.I)
KIND_OF_ARE = re.compile(r"^\W*(?:the\s+)?(?P<kind>" + MEMBER_KIND + "|" + PLACE_KIND + r")\s+of\s+(?:the\s+)?(?P<b>.+?)"
                         r"\s+(?:are|include)\s*:?\s+(?P<list>.+?)\s*[.;]?\s*$", re.I)
HAS_LIST_FR = re.compile(r"^\W*(?:l[ea]\s+|les\s+|l['’])?(?P<b>.+?)\s+(?:regroupe|regroupent|comprend|comprennent|"
                         r"contient|contiennent|inclut|incluent|rassemble|rassemblent|a|possède)\s+(?:les|des|ses|ces)?\s*"
                         r"(?P<kind>" + MEMBER_KIND_FR + "|" + PLACE_KIND_FR + r")(?:\s+suivante?s)?\s*:\s*(?P<list>.+?)"
                         r"\s*[.;]?\s*$", re.I)
HAS_LIST_DE = re.compile(r"^\W*(?:die\s+|der\s+|das\s+)?(?P<b>.+?)\s+(?:umfasst|umfassen|enthält|enthalten|"
                         r"besteht\s+aus|bestehen\s+aus|beinhaltet|gruppiert)\s+(?:die|den|folgende|diese|der)?\s*"
                         r"(?P<kind>" + MEMBER_KIND_DE + "|" + PLACE_KIND_DE + r")\s*:?\s+(?P<list>.+?)\s*[.;]?\s*$", re.I)
CONTAINER_NOUN = re.compile(r"(?i)\s+(?:application|app|platform\s+service|service|system|domain|product\s+line|"
                            r"business\s+line|line|platform|suite|stack|solution|product|subsystem|environment|"
                            r"landscape|(?:business\s+|functional\s+)?area)s?\s*$")
NOT_A_WHOLE = re.compile(r"(?i)(?:^|\s)(?:team|squad|tribe|crew|problem|issue|plan|process|project|effort|work|"
                         r"migration|roadmap|release|incident|meeting)s?\s*$")
PRONOUN = re.compile(r"(?i)^\W*(?:it|this|that|they|these|those|il|elle|ils|elles|ce|cela|ceci|celui-ci|celle-ci)\W*$")
NAME_SPAN = re.compile(r"^[A-Za-zÀ-ÿ0-9][\w.À-ÿ-]*(?:\s+[\w.À-ÿ-]+){0,3}$")
CONTAINER_KIND = re.compile(r"(?i)^(?:applications?|apps?|services?|platform\s+services?|sub-?systems?|systems?)$")
# (0.10.10) what a word says a thing is, as the map's categories would name it ("composants": component)
KIND_WORDS = {
    "application": ("application", "applications", "app", "apps", "anwendung", "anwendungen"),
    "component": ("component", "components", "composant", "composants", "komponente", "komponenten", "componente",
                  "componentes", "componenti"),
    "module": ("module", "modules", "modul"),
    "service": ("service", "services", "microservice", "microservices", "micro-service", "micro-services", "dienst",
                "dienste", "microservicio", "microservicios", "microservizio", "microservizi", "servicio", "servicios",
                "servizio", "servizi"),
    "domain": ("domain", "domains", "domaine", "domaines", "domäne", "domänen", "area", "areas", "business area",
               "business areas"),
    "environment": ("environment", "environments", "environnement", "environnements", "umgebung", "umgebungen",
                    "landscape", "landscapes"),
    "server pool": ("server pool", "server pools", "pool", "pools", "node pool", "node pools", "host pool",
                    "host pools"),
    "host group": ("host group", "host groups", "server group", "server groups", "servergruppe", "servergruppen"),
    "namespace": ("namespace", "namespaces"),
    "cluster": ("cluster", "clusters"),
    "product line": ("product line", "product lines"),
    "platform": ("platform", "platforms", "plateforme", "plateformes", "plattform", "plattformen"),
}
_KIND_OF_WORD = {w: k for k, ws in KIND_WORDS.items() for w in ws}


def _kind_word(word: str) -> str | None:
    """(0.10.10) The kind a noun says ("Komponenten": component; "server pools": server pool), else none."""
    w = " ".join(re.sub(r"[^\wÀ-ÿ\s-]", " ", str(word or "").lower()).split())
    return _KIND_OF_WORD.get(w) or _KIND_OF_WORD.get(w.split()[-1] if w else "")


WHOLE_NOUN = re.compile(r"(?i)\s(?P<n>domain|environment|landscape|application|app|platform|product\s+line|"
                        r"(?:business\s+)?area)s?\s*(?:\([^)]*\))?\s*$|"
                        r"^\W*(?:the\s+|l[ea]\s+|die\s+|der\s+|das\s+)?(?P<p>domaine|domäne|environnement|umgebung|"
                        r"anwendung|plateforme|plattform)\s")


def _whole_kind(span: str) -> str | None:
    """(0.10.10) The kind the words around a whole's name say ("the clinical domain", "Die Domäne X")."""
    m = WHOLE_NOUN.search(span or "")
    return _kind_word(m.group("n") or m.group("p")) if m else None


# (0.10.10) the line before a table naming what its rows are part of ("Applications of the clinical domain.")
CAPTION = re.compile(r"(?i)^\W*(?P<kind>" + MEMBER_KIND + r"|systems?|" + MEMBER_KIND_FR + r"|" + MEMBER_KIND_DE +
                     r")\s+(?:of|in|de|du|des|dans|"
                     r"von|der)\s+(?:the\s+|la\s+|le\s+|l['’])?(?P<b>[^:.]+?)\s*[.:]?\s*$")


def _span_name(span: str, at: int, found: list[tuple[int, str, str]], kind_said: bool) -> str | None:
    """The part a span of a sentence names: a name known in it (the closest to its end), else the span itself when
    it reads as a name (a known shape, Title Case, or a kind the sentence says: "an application of")."""
    inside = [x for x in found if at <= x[0] < at + len(span)]
    if inside:
        return inside[-1][2]
    text = re.sub(r"\s*\([^)]*\)", "", span).strip(" *`'\"")
    text = re.sub(r"(?i)^(?:the|a|an|our|their|its|le|la|les|l['’]|un|une)\s+", "", text).strip()
    text = re.sub(r"(?i)^(?:service|application|système|domaine|ligne|plateforme|environnement|domäne|anwendung|"
                  r"dienst|plattform|umgebung|bereich)\s+(?:de\s+|d['’])?", "", text).strip()
    text = CONTAINER_NOUN.sub("", text).strip()   # (the French noun comes first: "du service Paiement")
    if not text or not NAME_SPAN.match(text) or NOT_A_WHOLE.search(text):
        return None
    from supagent.knowledge.naming import DETERMINERS, VERBS

    words = text.lower().split()
    if any(w in VERBS for w in words) or words[0] in DETERMINERS:
        return None
    shaped = bool(re.search(r"[-_\d]", text)) or text[:1].isupper() and all(w[:1].isupper() or not w[:1].isalpha()
                                                                             for w in text.split())
    return text if shaped or kind_said else None


def _memberships(s: str, found: list[tuple[int, str, str]], names: Any, unit_part: str = "",
                 kinds: list[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
    """(0.10.10) (part, whole) pairs a sentence states (see MEMBER_OF...). "It", "this", "il"...: the part the page is
    about (its title names it), else nothing ("It consists of the rooms a, b" on a datacenter's page)."""
    if NEGATED.search(s) or len(s) > 400:
        return []
    out: list[tuple[str, str]] = []

    def whole_of(span: str, at: int, said: bool) -> str | None:
        if PRONOUN.match(span):
            return unit_part or None
        w = _span_name(span, at, found, said or bool(CONTAINER_NOUN.search(span)))
        if w is None or names.hosts.get(norm(w)) or NOT_A_WHOLE.search(w) or NOT_A_WHOLE.search(span):
            return None                                   # (a team is an owner, a group a place: no whole)
        return w

    for rx in (MEMBER_OF, PLACE_OF, MEMBER_OF_FR, MEMBER_OF_DE, MEMBER_OF_ES, MEMBER_OF_IT, BELONGS, PART_FR, PART_DE):
        m = rx.match(s)
        if not m:
            continue
        said = bool(re.fullmatch(MEMBER_KIND + "|" + MEMBER_KIND_FR + "|" + MEMBER_KIND_DE + "|" + MEMBER_KIND_ES + "|" +
                                 MEMBER_KIND_IT + "|" + ROLE_KIND + "|" + PLACE_KIND,
                                 (m.groupdict().get("kind") or "").strip(), re.I))
        a = (unit_part or None) if PRONOUN.match(m.group("a")) else _span_name(m.group("a"), m.start("a"), found, said)
        #   (0.10.10) "x is a module of y": the sentence says x is a part, a name even written in words
        b = whole_of(m.group("b"), m.start("b"), True)
        if a and b and norm(a) != norm(b):
            out.append((a, b))
            if kinds is not None:                         # (0.10.10) what the sentence says they are
                kinds += [(a, k) for k in [_kind_word(m.groupdict().get("kind") or "")] if k]
                kinds += [(b, k) for k in [_whole_kind(m.group("b"))] if k]
        return out
    for rx in (MADE_OF_LABEL, MADE_OF, MADE_OF_FR, MADE_OF_ES_IT, LABEL_LIST, HAS_LIST, KIND_OF_ARE, HAS_LIST_FR,
               HAS_LIST_DE):
        m = rx.match(s)
        if not m:
            continue
        b = whole_of(m.group("b"), m.start("b"), True) if m.groupdict().get("b") else unit_part or None
        if not b:
            return out
        listed = rx in (LABEL_LIST, HAS_LIST, KIND_OF_ARE, HAS_LIST_FR, HAS_LIST_DE) or bool(re.match(
            r"(?i)\s*(?:the\s+|les\s+|des\s+)?(?:[\w-]+\s+)?" + MEMBER_KIND + r"\b", m.group("list")))   # the
        #                                                                         list says what its items are
        at = m.start("list")
        items = re.split(r",\s*|\s+(?:and|et|und|y|e)\s+|;\s*", m.group("list"))
        if items:                                         # "made of the microservices A, B": the kind before the first
            items[0] = re.sub(r"(?i)^(?:the\s+|les\s+|des\s+)?(?:[\w-]+\s+)?" + MEMBER_KIND + r"\s+", "", items[0])
        said_kind = _kind_word(m.groupdict().get("kind") or m.groupdict().get("label") or "")
        for item in items:
            pos = s.find(item, at)
            if rx is MADE_OF_LABEL and not re.search(r"[\w][-_][\w]", item) and not any(
                    (pos if pos >= 0 else at) <= x[0] < (pos if pos >= 0 else at) + len(item) for x in found):
                continue                                  # (a name a part goes by: "Built from: Java 17" no part)
            a = _span_name(item, pos if pos >= 0 else at, found, listed)
            if a and norm(a) != norm(b):
                out.append((a, b))
                if kinds is not None and said_kind:      # (0.10.10) "the following components: a, b": components
                    kinds.append((a, said_kind))
            at = pos + len(item) if pos >= 0 else at
        if out and kinds is not None and m.groupdict().get("b"):
            kinds += [(b, k) for k in [_whole_kind(m.group("b"))] if k]
        return out
    return out


# (0.10.10) who owns a part, as a sentence says it: "x is owned by the y team", "the y squad owns x and z", "x est géré
# par l'équipe y", "x appartient à l'équipe y"; the owner is a team (its words say so), never a person
TEAM_WORD = re.compile(r"(?i)\b(?:teams?|squads?|tribes?|crews?|guilds?|chapters?|[ée]quipes?|equipos?)\b")
OWNED_BY = re.compile(r"(?i)^\W*(?:the\s+)?(?P<a>.+?)\s+(?:is|are)\s+(?:owned|maintained|run|operated|managed)\s+by\s+"
                      r"(?:the\s+)?(?P<b>[^,;:()]+?)\s*(?:[.;,(]|$)")
OWNS = re.compile(r"(?i)^\W*(?:the\s+|l[ea]\s+|l['’]|die\s+|der\s+|das\s+)?(?P<b>[^,;:()]+?)\s+(?:owns|maintains|operates|"
                  r"is\s+responsible\s+for|"
                  r"(?:is|are)\s+accountable\s+for|(?:is|are)\s+in\s+charge\s+of|looks\s+after|takes\s+care\s+of|"
                  r"(?:est|sont)\s+responsables?\s+(?:de|du|des|d['’])|betreut|betreuen|verantwortet|verantworten|pflegt|"
                  r"pflegen)\s*:?\s+(?:the\s+|l['’]|la\s+|le\s+|les\s+|die\s+|den\s+|das\s+)?(?P<list>.+?)\s*[.;]?$")
# (0.10.10) a team's own page speaking of itself: "We maintain: a, b", "Applications we maintain: a, b", "Nous sommes
# responsables de : a, b", "Wir betreuen: a, b"
WE_OWN = re.compile(r"(?i)^\W*(?:(?:we|nous|wir)\s+(?:own|maintain|run|operate|are\s+(?:responsible|accountable)\s+for|"
                    r"sommes\s+responsables\s+(?:de|du|des|d['’])|gérons|maintenons|betreuen|verantworten|pflegen)|"
                    r"(?:applications?|services?|systems?|components?)\s+we\s+(?:own|maintain|run|operate))\s*:?\s+"
                    r"(?:the\s+|les\s+|die\s+)?(?P<list>.+?)\s*[.;]?$")
OWNED_FR = re.compile(r"(?i)^\W*(?:l[ea]\s+|les\s+|l['’])?(?P<a>.+?)\s+(?:(?:est|sont)\s+(?:gérée?s?|maintenue?s?|"
                      r"opérée?s?|possédée?s?)\s+par|appartien(?:t|nent)\s+à)\s+(?:l['’]|la\s+|le\s+)?"
                      r"(?P<b>[^,;:()]+?)\s*(?:[.;,(]|$)")


INTRODUCED = re.compile(r"(?i)\b(?:the|a|an|la|le|du|de\s+la|l['’])\s*(?P<noun>datastores?|data\s+stores?|databases?|db|"
                        r"base(?:\s+de\s+données)?|caches?|buckets?|blob\s+containers?|file\s+shares?|topics?|"
                        r"queues?|streams?)\s+"
                        r"(?P<name>[A-Za-z0-9][\w.]*[-_\d][\w.-]*[A-Za-z0-9])")


DEFINED = re.compile(r"(?:^|(?<=[.\n]))\s*(?P<name>[A-Za-z0-9][\w-]*(?: [A-Za-z0-9][\w-]*){0,3})\s*:\s*(?:an?|the)\s+"
                     r"(?P<what>[^.\n:]{3,80})")
DEFINED_KINDS = {"store", "cache", "messaging", "broker", "object", "external", "job"}


TITLE_DATE = re.compile(r"\b\d{4}[-/.]\d{1,2}|\b\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}\b|#\d")


def titled_name(title: str, text: str) -> str | None:
    """(0.10.10) The part a page is about when its title is its name: a page of its properties (a table of keys the
    reader knows, with one saying what it is part of, uses or where it runs), or a page whose first sentence opens on
    its title written as a name ("billing-api is the REST API of ...", "billing-api est le composant ..."); never a
    title with a date or a number of notes, nor a phrase."""
    from supagent.knowledge.naming import DETERMINERS, VERBS

    t = " ".join((title or "").split())
    if not t or len(t) > 60 or not NAME_SPAN.match(t) or TITLE_DATE.search(t):
        return None
    words = t.lower().split()
    if any(w in VERBS for w in words) or words[0] in DETERMINERS:
        return None
    structural = ("part_of", "uses", "runs_on", "sends_to", "reads_from", "alias")
    for t0, header, rows in _tables(text or ""):
        kv = _key_values(t0, header, rows)
        if kv and any((_property(k) or ("", ""))[0] in structural for _r, k, _v in kv):
            return t
    top = re.split(r"(?m)^[ \t]*#{1,6}[ \t]", diagram_free(text or ""), maxsplit=1)[0]   # (before any section)
    said = [(_property(km.group("key")) or ("", ""))[0] for _at, x in list(_sentences(top))[:12]
            for km in [KEY_LINE.match(x)] if km]       # (0.10.10) or its "Key: value" lines at its top ("Part of: x",
    if sum(1 for v in said if v) >= 2 and any(v in structural for v in said):   # "Product team: y"), two the reader
        return t                                                                  # knows, one of them structural
    if ID_TOKEN.fullmatch(t):
        first = next((x for _at, x in _sentences(diagram_free(text or "")) if " | " not in x), "")
        if norm(first[:len(t) + 2]).startswith(norm(t)):
            return t
    return None


def introduced_names(text: str) -> list[str]:
    """(0.10.10) The names a page introduces by what they are: "the datastore x", "the blob container y" (a name of
    its own shape), "x: an API of a partner company", "y: a cron job exporting..." (a definition saying a kind of
    part)."""
    from supagent.knowledge.placing import PHRASE_OF, phrases

    out = [m.group("name") for m in INTRODUCED.finditer(text)]
    for m in DEFINED.finditer(text):
        name = m.group("name").strip()
        if name.lower() in TINY_WORDS or not re.search(r"[a-z]", name) or len(name) < 3:
            continue
        if set(phrases(m.group("what"))) & DEFINED_KINDS and not PHRASE_OF.get(name.lower()):
            out.append(name)                              # (a heading word alone, "Database:", is no name)
    return list(dict.fromkeys(out))


STORAGE_CMD = re.compile(r"\baz\s+storage\s+(?:blob|file|fs)\s+(?P<az>upload(?:-batch)?|download(?:-batch)?|copy\s+start|sync)"
                         r"\b(?P<azargs>[^\n]*)|\b(?:aws\s+s3|gsutil(?:\s+-m)?|mc)\s+(?:cp|sync|mv|rsync)\s+"
                         r"(?:--?[\w-]+(?:\s+[^\s-]\S*)?\s+)*(?P<src>\S+)\s+(?P<dst>\S+)")
STORAGE_URL = re.compile(r"^(?:s3|gs|az|abfss?|wasbs?)://(?P<b>[\w.-]+)|^(?P<alias>[\w-]+)/(?P<mb>[\w.-]+)")


def _storage_ends(m: Any) -> list[tuple[str, str]]:
    """(0.10.10) (verb, bucket or container) a storage command writes to or reads from."""
    if m.group("az"):
        c = re.search(r"(?:--container-name|--container|-c|--destination|-d|--share-name|-s)\s+([\w.-]+)",
                      m.group("azargs") or "")
        return [("reads_from" if m.group("az").startswith("download") else "sends_to", c.group(1))] if c else []
    out = []
    for verb, url in (("reads_from", m.group("src")), ("sends_to", m.group("dst"))):
        u = STORAGE_URL.match(url or "")
        if u and (u.group("b") or (u.group("mb") and not url.startswith(("/", ".")))):
            out.append((verb, u.group("b") or u.group("mb")))
    return out


JOB_FILE = re.compile(r"(?i)(?:^|/)(?:tasks?|jobs?|cron(?:jobs?)?|batch(?:es)?)/(?P<stem>[\w.-]+?)\.(?:sh|bash|py|ps1)$")


TABLE_KIND = {"task": "job", "scheduled task": "job", "batch task": "job", "job": "job", "cron job": "job",
              "cronjob": "job", "event topic": "topic", "batch": "job", "external system": "external", "partner": "external",
              "third party": "external", "vendor": "external", "supplier": "external", "external api": "external",
              "batch job": "job", "datastore": "database", "data store": "database", "database": "database",
              "db": "database", "cache": "cache", "topic": "topic", "queue": "queue", "stream": "stream",
              "bucket": "object", "blob container": "object"}


def _ownerships(s: str, found: list[tuple[int, str, str]], unit_part: str = "", title: str = ""
                ) -> list[tuple[str, str]]:
    """(0.10.10) (part, team) pairs a sentence states: the team as written ("field tribe"), the part a name of the
    sentence (or the page's own part for "it"); "It owns a, b" on a team's own page (its title says a team)."""
    if NEGATED.search(s) or len(s) > 300:
        return []
    for rx in (OWNED_BY, OWNED_FR):
        m = rx.match(s)
        if m and TEAM_WORD.search(m.group("b")) and len(m.group("b").split()) <= 5:
            team = " ".join(m.group("b").split()).strip(" .")
            first = [x for x in found if m.start("a") <= x[0] < m.end("a")]   # ("a is part of d and is owned by t":
            a = (unit_part or None) if PRONOUN.match(m.group("a")) else first[0][2] if first else \
                _span_name(m.group("a"), m.start("a"), found, False)       # a, the sentence's subject, not d)
            return [(a, team)] if a and norm(a) != norm(team) else []
    m = OWNS.match(s)
    page_team = next((x for x in (title, unit_part) if x and TEAM_WORD.search(x) and len(x.split()) <= 5), "")
    if not m and page_team:
        m = WE_OWN.match(s)
        if m:
            team = " ".join(page_team.split()).strip(" .")
    if m and m.re is WE_OWN:
        pass
    elif m and (PRONOUN.match(m.group("b")) or re.fullmatch(r"(?i)\W*(?:we|nous|wir|on)\W*", m.group("b"))) and page_team:
        team = " ".join(page_team.split()).strip(" .")
    elif m and TEAM_WORD.search(m.group("b")) and len(m.group("b").split()) <= 5:
        team = " ".join(m.group("b").split()).strip(" .")
    else:
        m = None
    if m:
        out, at = [], m.start("list")
        for item in re.split(r",\s*|\s+(?:and|et|und)\s+|;\s*", m.group("list")):
            pos = s.find(item, at)
            a = _span_name(item, pos if pos >= 0 else at, found, True)   # (what a team owns: parts)
            if a and norm(a) != norm(team):
                out.append((a, team))
            at = pos + len(item) if pos >= 0 else at
        return out
    return []


ABBR_AFTER = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:[ -][A-Za-z][A-Za-z0-9]*){1,5})\s*\(([A-Z][A-Z0-9]{1,5})\)")
ABBR_BEFORE = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\s*\(([A-Z][A-Za-z0-9]*(?:[ -][A-Za-z][A-Za-z0-9]*){1,5})\)")


STANDS_FOR = re.compile(r"\b([A-Z][A-Z0-9]{1,5})\s+(?:stands\s+for|is\s+short\s+for|means|steht\s+für|signifie|"
                        r"veut\s+dire)\s+(?:the\s+)?([A-Z][A-Za-z0-9]*(?:[ -][A-Za-z][A-Za-z0-9]*){1,5})")
ALSO_CALLED = re.compile(r"\b([A-Z][A-Za-z0-9]*(?:[ -][A-Za-z][A-Za-z0-9]*){1,5}),?\s+(?:\(\s*)?(?:also\s+(?:called|known\s+as)|"
                         r"a\.k\.a\.?|aka|alias|auch|appelée?\s+aussi|dit[e]?|genannt)\s+([A-Z][A-Z0-9]{1,5})\b")


def _abbreviations(s: str) -> list[tuple[str, str]]:
    """(0.10.10) (name, its initials) a sentence defines: "Identity Hub (IH)", "IH (Identity Hub)"; the initials
    must be the name's words' first letters (a version or a code in brackets is no other name)."""
    out = []
    for rx, long_first in ((ABBR_AFTER, True), (ABBR_BEFORE, False), (ALSO_CALLED, True), (STANDS_FOR, False)):
        for m in rx.finditer(s):
            long, short = (m.group(1), m.group(2)) if long_first else (m.group(2), m.group(1))
            words = [w for w in re.split(r"[ -]+", long) if w]
            spans = [words[i:] for i in range(len(words) - 1)] if rx is not STANDS_FOR else \
                [words[:j] for j in range(len(words), 1, -1)]   # (0.10.10) "PR stands for Patient Record and is":
            for ws in spans:                            # the name's words start after "for"
                if "".join(w[0] for w in ws).lower() == short.lower():   # "The Access Ordering (AO)": the words
                    out.append((" ".join(ws), short))                   # the letters are of
                    break
    return list(dict.fromkeys(out))


SCHEDULE_AFTER = re.compile(r"(?i)\s+(?:the\s+|every\s+|each\s+)?(?:\d{1,2}(?:st|nd|rd|th)?\b|first|second|last|"
                            r"mondays?|tuesdays?|wednesdays?|thursdays?|fridays?|saturdays?|sundays?|weekends?|"
                            r"weekdays?|nights?|mornings?|evenings?|days?|daily|weekly|monthly|hourly|schedule|demand|"
                            r"request|lundis?|dimanches?|montags?|sonntags?)\b")
# (0.10.10) a line of a page's properties ("Database: pg-01", "Base de données : pg-01"), a line listing what runs on
# the place the page is about ("Services on this pool: a, b", "Services hébergés : a, b", "Dienste auf diesem Pool:")
KEY_LINE = re.compile(r"^\W*(?P<key>[A-Za-zÀ-ÿ][\w À-ÿ'’.-]{1,38}?)\s*:\s+(?P<value>[^:]{1,200}?)\s*[.;]?\s*$")
HOSTED_LINE = re.compile(r"(?i)^\W*(?:(?:services?|applications?|apps?|components?|workloads?)\s+(?:on|in|running\s+on)\s+"
                         r"this\s+[\w-]+|services?\s+hébergés|applications?\s+hébergées|dienste\s+auf\s+diesem\s+[\w-]+|"
                         r"anwendungen\s+auf\s+diesem\s+[\w-]+)\s*:\s*(?P<list>.+?)\s*[.;]?\s*$")
INTRO_LIST = re.compile(r"(?m)^[ \t]*(?P<intro>[^\n|]{3,200}?:)[ \t]*\n(?P<items>(?:[ \t]*[-*+•][ \t]+[^\n]*(?:\n|$))+)")


def _list_sentences(text: str) -> list[tuple[int, str]]:
    """(0.10.10) A line ending with a colon and the list after it, as one sentence ("X has the following
    components:" then "- a – the web front", "- b"): "X has the following components: a, b." (each item's name only)."""
    out = []
    for m in INTRO_LIST.finditer(text or ""):
        items, names_only = [], True
        for line in m.group("items").splitlines():
            it = re.sub(r"^[ \t]*[-*+•][ \t]+", "", line).strip()
            it = re.split(r"\s+[–—-]\s+|\s*:\s+|\s*\(", it, maxsplit=1)[0].strip(" .;*`")
            if it:
                items.append(it)
                names_only = names_only and len(it.split()) <= 4 and bool(NAME_SPAN.match(it)) and \
                    not re.search(r"[,;]", it)            # (a list of sentences is no list of names: each item
        if items and names_only:                          # stays its own sentence)
            out.append((m.start("intro"), m.group("intro") + " " + ", ".join(items) + "."))
    return out


# (0.10.10) a place and the servers it holds, as an inventory page lists them: "Machine group grp-q7 (production):
# q7-vm01, q7-vm02", "Server pool pool-a: web-01, web-02", "Cluster pg-main (Paris): pg-1, pg-2"
GROUP_LIST = re.compile(r"^\W*(?P<kind>(?:[A-Za-zÀ-ÿ-]+\s+){0,2}?(?:groups?|pools?|clusters?|farms?|racks?|groupes?|"
                        r"gruppen?|gruppe))\s+(?P<b>[A-Za-z0-9][\w.-]*[-_\d][\w.-]*)\s*(?:\([^)]{1,40}\))?\s*:\s*"
                        r"(?P<list>[^:]+?)\s*[.;]?\s*$", re.I)
KEYISH = re.compile(r"[ \t]*[A-ZÀ-Ý][\wÀ-ÿ'’.-]*(?:[ \t]+[\wÀ-ÿ'’.-]+){0,3}[ \t]*:[ \t]+\S")


def _sentences(text: str) -> Iterator[tuple[int, str]]:
    """A text's sentences, a line wrapped in the middle of one going on (a bullet, a heading, a blank line, a table's
    row start a new one); positions as in the text (0.10.4: the wrapped lines joined, where the sentence starts in
    the text, so that its quote is its own line)."""
    pieces, flat_at, text_at, last, size = [], [], [], 0, 0
    for m in re.finditer(r"\n(?![ \t]*(?:[-*+#|>]|\d+[.)]\s|\n))[ \t]*", text):
        line = text[text.rfind("\n", 0, m.start()) + 1:m.start()]
        if KEYISH.match(line) or KEYISH.match(text, m.end()):
            continue                                      # (0.10.10) a page's "Key: value" lines, each its own
            #                                               paragraph ("Part of: x", "Product team: y"): no wrap
        item = re.match(r"[ \t]*(?:[-*+]|\d+[.)])\s", line)
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


TINY_WORDS = {"on", "in", "at", "to", "it", "is", "as", "or", "an", "of", "by", "be", "we", "us", "no", "so", "up", "do",
              "if", "me", "my", "go", "he", "am", "and", "the", "for", "are", "was", "not", "but", "all", "can", "one",
              "sa", "se", "si", "ce", "ma", "la", "le", "un", "et", "ou", "où", "du", "de", "en", "il", "ne", "sur", "par",
              "les", "des", "une", "est", "son", "ses", "aux", "pas", "qui", "que"}


def _named_all(sentence: str, names: Names, own: dict[str, str]) -> list[tuple[int, str, str]]:
    out = []
    for m in re.finditer(r"[A-Za-z][\w.-]*[\w]|[A-Za-z]", sentence):
        w = m.group(0).strip(".-")
        if w.lower() in TINY_WORDS and not w.isupper():
            continue                                      # (0.10.10) "on", "it", "sa": words, even when a part's
            #                                               initials are ON, IT or SA (those name it written so)
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
    for size in (4, 3):                                   # (0.10.10) a name of three or four words ("national
        rx = r"\b(?=(" + r"\s+".join([r"[A-Za-z][\w-]*"] * size) + r"))\b"   # porting registry", "usage meter store
        for m in re.finditer(rx, sentence):               # writer" for usage-meter-store-writer)
            words_, at = m.group(1), m.start()
            p = names.part(words_) or own.get(norm(words_)) or names.part("-".join(words_.split())) or \
                own.get(norm("-".join(words_.split())))
            if p and not any(a <= at < a + len(w) and len(w) > len(words_) for a, w, _p in out):
                out = [x for x in out if not (at <= x[0] < at + len(words_))]
                out.append((at, words_, p))
    return sorted(out)


HELM_VALUES = re.compile(r"(?i)(?:^|/)values(?:[-_.][\w-]+)?\.ya?ml$")


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
    jm = JOB_FILE.search(path)                            # (0.10.10) a job's own script (tasks/nightly-export.sh):
    job_script = bool(jm and re.search(r"[-_]", jm.group("stem")))   # the job is what it does, not its repository
    if job_script:
        me = jm.group("stem")

    reading = {"src": source}                            # (0.10.9.2) a table's rows: "table" (a column says what it is)

    def fact(subject: str, verb: str, obj: str, obj_kind: str, pos: int, src: str | None = None,
             conf: float = 0.9) -> None:
        src = src or reading["src"]
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
    # (0.10.10) a Helm chart's values: the namespace it is installed in (a top-level "namespace:")
    if me and HELM_VALUES.search(path):
        hm = re.search(r"(?m)^namespace:[ \t]*[\"']?([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)[\"']?[ \t]*(?:#.*)?$", text)
        if hm and hm.group(1) not in ("default", "tpl"):
            fact(me, "runs_on", hm.group(1), "namespace", hm.start(1), conf=0.8)
    # addresses: who is called, which database, cache, where the logs go
    tool = unit["found"]["tool"]
    operation = "speaks" in unit and bool(re.search(r"(^|/)(tasks|handlers|meta|molecule|tests?)/", path)) and \
        lang == "yaml"                                    # an Ansible task's get_url, git, yum: a download, no link
    if source in ("code", "config") and tool != "prometheus" and not operation and not PACKAGE_FILES.search(path):
        scan = USERINFO_TPL.sub(lambda t: t.group(1) + "x" * len(t.group(2)), text)   # (0.10.5) "amqp://app:{{ pw
        scan = ORACLE_THIN.sub(lambda t: " " * (len(t.group(0)) - 14) + "jdbc:oracle://", scan)   # (0.10.10) same
        #                                                  length: the positions of what follows are kept
        sites: dict[str, int] = defaultdict(int)          # (0.10.10) the sites of the internet the file names
        for u in URL.finditer(scan):
            h = _url_parts(u.group(1))[1].lower()
            if _is_public(h):
                sites[_site(h)] += 1
        catalogue = len(sites) >= CATALOGUE_SITES
        for m in URL.finditer(scan):                                                   # }}@mq-01": mq-01
            scheme, host, port, first = _url_parts(m.group(1))
            line = _line_of(scan, m.start())[1]           # (the line as scanned: the address is found in it)
            ph = PLACEHOLDER_HOST.match(host)
            if ph and (names.part(ph.group(1) or ph.group(2)) or own.get(norm(ph.group(1) or ph.group(2)))):
                host = (ph.group(1) or ph.group(2)).lower()   # (0.10.4) http://${CATALOGUE_HOST}:8080: the catalogue
            if COMMENT.match(line) or host.isupper() or re.search(r"[{}%$<>]", host) or DOC_HOSTS.search(host.lower()) \
                    or NOT_ENDPOINT.search(m.group(1)) or SEE_ALSO.search(line[:max(0, line.find(m.group(1)))]) or \
                    FETCH_LINE.search(line) or DOC_KEY.search(line[:max(0, line.find(m.group(1)))]) or \
                    (_is_public(host) and (not EXTERNAL_KEY.search(line[:max(0, line.find(m.group(1)))]) or
                                           (catalogue and sites[_site(host)] == 1)) and
                     not any(names.part(x) for x in host.lower().split("."))):
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
            elif what == "database" and first and re.fullmatch(r"[A-Za-z_][\w-]{1,62}", first) and \
                    not GENERIC_DB_NAME.match(first) and norm(first) not in norm(host.split(".")[0]) and \
                    not (names.service(first) or own.get(norm(first))):   # (0.10.10) jdbc:...//pg-ah-01/appointment_hub
                #                                             of the application Appointment Hub: its database is pg-ah-01
                #                                             (0.10.10) mongodb://orders-mongo:27017/app ("app" names no
                #                                             database) or postgres://orders-pg/orders (a server named
                #                                             after its database): the server's name is the database's
                db_part = names.part(first) or first
                fact(me, verb, db_part, "database", m.start())
                fact(db_part, "runs_on", names.hosts.get(norm(host)) or names.hosts.get(norm(host.split(".")[0])) or
                     host, "host", m.start(), conf=0.7)
            else:
                fact(me, verb, part, what if what in ("database", "cache") else "part", m.start())
        if job_script and (STORAGE_CMD.search(text) or URL.search(text)):
            fact(me, "is_a", "job", "kind", 0, conf=0.8)  # (0.10.10) a job's script that touches something: a job
        for m in STORAGE_CMD.finditer(text):              # (0.10.10) "az storage blob upload -c x", "aws s3 cp f
            if COMMENT.match(_line_of(text, m.start())[1]) or not me:   # s3://x/...": what a job writes or reads
                continue
            for verb, target in _storage_ends(m):
                if target and not re.search(r"[{}$<>%]", target):
                    fact(me, verb, names.part(target) or own.get(norm(target)) or target, "object", m.start(),
                         conf=0.8)
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
            if text[m.start(3) - 1] not in "\"'" and re.search(r",\s*$", text[m.start():m.start(3)]):
                continue                                  # (0.10.9.3) getenv("DB_NAME", BASE_DIR / "x.db"): a default
                #                                           the code computes, no name
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
            "sends_to" if re.search(r"\blogs?\b|\bpublish|\bwrite|\bemit|\bproduce", label or "", re.I) else "calls"
        if re.search(r"(?i)\b(?:consumed|read|subscribed|listened)(?:\s+(?:by|to))?\b|\bconsumers?\b", label or "") and \
                not re.search(r"(?i)\b(?:consumes|reads|subscribes|listens)\b", label or ""):
            fact(pb, "reads_from", pa, "part", max(0, text.find(a)), src="diagram", conf=0.85)   # (0.10.10) "topic
            continue                                      # ..> [svc] : consumed": the service reads the topic
        if re.search(r"(?i)\b(?:consumes|reads|subscribes(?:\s+to)?|listens(?:\s+to)?)\b", label or ""):
            fact(pa, "reads_from", pb, "part", max(0, text.find(a)), src="diagram", conf=0.85)
            continue
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
        prose = diagram_free(text)                    # (0.10.7) a diagram's arrows: its reader's

        def property_facts(part: str, key: str, value: str, pos: int) -> bool:
            """(0.10.10) What a page's property says of the part the page is about ("Maintained by: the x squad",
            "Database: pg-01", "Deployed to: pool-a, pool-b"); False when the key names no property."""
            prop = _property(key)
            if not prop or not part:
                return False
            verb, kind = prop
            value = value.strip(" .;*`")
            if not value or PLACEHOLDER.fullmatch(value) or len(value) > 200:
                return True
            if verb == "owned_by":
                team = " ".join(re.sub(r"(?i)^(?:the|l['’]|la|le|die|der)\s+", "", value).split())
                if INFRA_VALUE["owned_by"].search(team) and len(team) <= 60:
                    fact(part, "owned_by", team, "owner", pos, conf=0.8)
                return True
            for v in _cell_values(value)[:12]:
                v = re.sub(r"\s*\(.*?\)", "", v).strip(" .")
                if not v or not re.search(r"\w", v) or norm(v) == norm(part):
                    continue
                known = names.part(v) or own.get(norm(v))
                if verb == "alias":
                    if len(v) <= 40 and re.fullmatch(r"[A-Za-z0-9][\w.-]*", v):
                        fact(part, "alias", v, "part", pos, conf=0.8)
                elif verb == "part_of":
                    if len(v) <= 60 and NAME_SPAN.match(v) and not names.hosts.get(norm(v)):
                        bare = re.sub(r"(?i)^(?:the|le|la|l['’]|die|der|das)\s+", "", v)
                        whole = known or (CONTAINER_NOUN.sub("", bare).strip() if _whole_kind(" " + v) else v) or v
                        fact(part, "part_of", whole, "part", pos, conf=0.8)
                        k = _kind_word(key) or _whole_kind(" " + v)
                        if k:                             # (0.10.10) "Domain: clinical": clinical is a domain
                            fact(whole, "is_a", k, "kind", pos, conf=0.7)
                elif verb == "runs_on":
                    if PLATFORMS.match(v) or EVERY_SERVER.fullmatch(v) or (re.search(r"\s", v) and
                                                                         not names.hosts.get(norm(v))):
                        continue
                    fact(part, "runs_on", names.hosts.get(norm(v)) or v, "host", pos, conf=0.75)
                elif known or ID_TOKEN.fullmatch(v):
                    fact(part, verb, known or v, kind if verb == "uses" else "part", pos, conf=0.75)
            return True
        for t0, header, rows in _tables(text):
            reading["src"] = "table"
            kv = _key_values(t0, header, rows) if unit_part else None
            if kv is not None:                            # (0.10.10) the page's properties: what they say of its part
                for r0, key, value in kv:
                    property_facts(unit_part, key, value, r0)
                for r0, cells in [(t0, header)] + rows:   # (no sentence of its rows)
                    line_end = prose.find("\n", r0)
                    prose = prose[:r0] + " " * ((line_end if line_end >= 0 else len(prose)) - r0) + prose[line_end:] \
                        if line_end >= 0 else prose[:r0]
                reading["src"] = source
                continue
            header = [_implied_head(header[0], unit.get("title") or "")] + header[1:] if header else header
            first_head = header[0].strip(" *`") if header else ""
            roles = [next((v for v, rx in COLUMNS if rx.search(h)), None) for h in header]
            if header and DEPLOYABLE_HEAD.match(header[0].strip(" *`")):   # (0.10.10) a table of modules: the
                roles = [("part_of" if i and PART_OF_HEAD.match(h.strip(" *`")) else r)   # column of their whole
                         for i, (h, r) in enumerate(zip(header, roles))]
            # (0.10.10) a table of jobs: their sources and targets; a column of the row's whole in any table; a
            # table of topics: their bus; who writes, reads, uses a row: the row is what they write, read, use
            roles = [r if not i else "reads_from" if JOB_HEAD.match(first_head) and SOURCE_COL.match(h) else
                     "sends_to" if JOB_HEAD.match(first_head) and TARGET_COL.match(h) else
                     "in_area" if AREA_COL.match(h.strip(" *`")) else
                     "part_of" if OWNING_HEAD.match(h.strip(" *`")) or (TOPIC_HEAD.match(first_head) and
                                                                        BUS_COL.match(h.strip(" *`"))) else
                     "alias" if STORE_HEAD.fullmatch(first_head) and re.fullmatch(
                         r"(?i)\s*(?:schemas?|database\s+names?|db\s+names?)\s*", h) else r
                     for i, (h, r) in enumerate(zip(header, roles))]
            reverse = {i: ("sends_to" if PRODUCER_COL.match(h) else "reads_from" if CONSUMER_COL.match(h) else
                           "calls" if CALLER_COL.match(h) and not STORE_HEAD.fullmatch(first_head) else None)
                       for i, h in enumerate(header) if i}
            reverse = {i: v for i, v in reverse.items() if v}
            roles = [None if i in reverse else r for i, r in enumerate(roles)]
            if PLACE_HEAD.match(first_head) and any(PARTS_COLUMN.search(h) for h in header[1:]):
                kind = "namespace" if re.search(r"(?i)namespace", first_head) else "group"   # (0.10.10) a table of
                for r0, cells in rows:                    # places listing what runs in each: "Namespace | Workloads"
                    place = re.sub(r"\s*\(.*?\)", "", cells[0] if cells else "").strip(" `*")
                    if not re.fullmatch(r"[A-Za-z0-9][\w.-]{1,62}", place):
                        continue
                    for i, h in enumerate(header[1:], 1):
                        if i >= len(cells) or not PARTS_COLUMN.search(h):
                            continue
                        for v in _cell_values(cells[i])[:20]:
                            v = re.sub(r"\s*\(.*?\)", "", v).strip()
                            known = names.part(v) or own.get(norm(v))
                            if (known or ID_TOKEN.fullmatch(v)) and not names.hosts.get(norm(v)):
                                fact(known or v, "runs_on", place, kind, r0, conf=0.75)
                for r0, cells in [(t0, header)] + rows:
                    line_end = prose.find("\n", r0)
                    prose = prose[:r0] + " " * ((line_end if line_end >= 0 else len(prose)) - r0) + prose[line_end:] \
                        if line_end >= 0 else prose[:r0]
                reading["src"] = source
                continue
            before = text[:t0].rstrip().rsplit("\n", 1)[-1].strip()   # (0.10.10) "Applications of the clinical
            cm = CAPTION.match(before) if before and " | " not in before else None   # domain." then a table of them
            caption = None
            caption_kind = None
            if not cm and unit_part and PARTS_HEAD.match(first_head) and "part_of" not in roles[1:] and \
                    not NOT_A_WHOLE.search(unit_part) and not names.hosts.get(norm(unit_part)):
                caption = unit_part                       # (0.10.10) a table of components on an application's own
            elif cm and (SERVICE_HEAD.fullmatch(first_head) or DEPLOYABLE_HEAD.match(first_head)):   # page: its parts
                caption = _span_name(cm.group("b"), 0, [], True)
                caption = names.part(caption) or own.get(norm(caption)) or caption if caption else None
                caption_kind = _kind_word(cm.group("kind"))
                if caption and _whole_kind(" " + cm.group("b")):
                    fact(caption, "is_a", _whole_kind(" " + cm.group("b")), "kind", t0, conf=0.7)
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
                        for value in _cell_values(cell)[:12]:
                            value = re.sub(r"\s*\(.*?\)", "", value).strip()
                            if names.hosts.get(norm(value)) or (HOST_SHAPE.fullmatch(value) and not
                                                                 (names.part(value) or own.get(norm(value)))):
                                fact(names.hosts.get(norm(value)) or value, "in_group", vip.lower(), "vip", r0, conf=0.75)
                            elif names.part(value) or own.get(norm(value)):
                                fact(vip.lower(), "routes_to", names.part(value) or own.get(norm(value)), "part", r0,
                                     conf=0.75)
                continue
            hcol = 0 if roles and (roles[0] == "runs_on" or HOST_HEAD.fullmatch(header[0].strip(" *`"))) else next(
                (i for i, h in enumerate(header) if i and HOST_HEAD.fullmatch(h.strip(" *`"))), None)
            for r0, cells in rows:
                first = cells[0] if cells else ""
                hcell = cells[hcol] if hcol is not None and hcol < len(cells) else ""
                hcell = re.sub(r"\s*\([^()]*\)$", "", hcell).strip()   # (0.10.9) "web-01 (B07/U30)"
                if hcol is not None and (hcol == 0 or not (names.service(first) or own.get(norm(first)))) and \
                        not (names.part(hcell) and not names.hosts.get(norm(hcell))) \
                        and not own.get(norm(hcell)) and re.fullmatch(r"[A-Za-z0-9][\w.-]*", hcell or "") and \
                        not PLATFORMS.match(hcell) and not EVERY_SERVER.fullmatch(hcell):
                    # (0.10.4) a table of hosts ("Host | Role | Services"): what its parts' column names runs there;
                    # (0.10.9) its host's column may come after an asset tag ("Asset tag | Hostname | PDUs")
                    host = names.hosts.get(norm(hcell)) or hcell
                    for h, cell in [(h, c) for i, (h, c) in enumerate(zip(header, cells)) if i != hcol]:
                        infra = next(((verb, kind) for verb, rx, kind in INFRA_COLUMNS
                                      if rx.search(h) and not PARTS_COLUMN.search(h) and not INFRA_NOT.search(h)), None)
                        nic = not infra and bool(NIC_COLUMN.search(h)) and not INFRA_NOT.search(h)
                        infra = infra or (("connects_to", "port") if nic else None)
                        if infra:                     # (0.10.9) its power, its switch ports, its owner
                            for value in _cell_values(cell)[:6]:
                                value = re.sub(r"\s*\(.*?\)", "", value).strip()
                                known = names.part(value) or own.get(norm(value))
                                for target in ([known] if known else _infra_values(infra[0], value, ports_only=nic)
                                               if len(value) <= 60 else []):
                                    fact(host, infra[0], target, infra[1], r0, conf=0.7)
                            continue
                        if not PARTS_COLUMN.search(h) or COLUMNS[0][1].search(h):
                            continue
                        for value in _cell_values(cell)[:12]:
                            value = re.sub(r"\s*\(.*?\)", "", value).strip()
                            p = names.part(value) or own.get(norm(value))
                            if p and not names.hosts.get(norm(value)):
                                fact(p, "runs_on", host, "host", r0, conf=0.75)
                    continue
                part = names.service(first) or own.get(norm(first)) or _page_owner(first, names, own)
                new_part = False
                if not part and _service_row(header, roles, first, cells, names):
                    part, new_part = first, True          # (0.10.9) a table of services names its services
                if not part and EXTERNAL_HEAD.match(first_head) and NAME_SPAN.match(first.strip(" `*")) and \
                        not PLACEHOLDER.fullmatch(first.strip()) and not names.hosts.get(norm(first)):
                    part, new_part = first.strip(" `*"), True   # (0.10.10) a table of external systems lists them
                if not part:
                    continue
                if caption and norm(caption) != norm(part):   # (0.10.10) the whole its caption names
                    fact(part, "part_of", caption, "part", r0, conf=0.7)
                head_kind = caption_kind or _kind_word(first_head)
                if head_kind and not new_part:            # (0.10.10) a table of applications, of components: what
                    fact(part, "is_a", head_kind, "kind", r0, conf=0.65)   # its rows are
                if not new_part and not (names.service(first) or own.get(norm(first))):   # (0.10.4) a qualified name
                    others = [names.part(re.sub(r"\s*\(.*?\)", "", v).strip()) for c in cells[1:]
                              for v in re.split(r",|;|\band\b", c)]
                    part = _qualified(first, part, names, [o for o in others if o])
                store_table = bool(header) and bool(STORE_HEAD.fullmatch(header[0].strip(" *`")))
                row_kind = TABLE_KIND.get(re.sub(r"(?i)\s+names?$", "", header[0].strip(" *`").lower()).rstrip("s")) \
                    if header else None
                if row_kind and new_part:                 # (0.10.10) "Task | When | ...", "Datastore | Engine": what
                    fact(part, "is_a", row_kind, "kind", r0, conf=0.75)   # its new rows are
                for h, cell in zip(header[1:], cells[1:]) if store_table else []:
                    if USED_BY_HEAD.match(h.strip(" *`")):        # (0.10.10) "Datastore | Engine | Host | Service":
                        for value in _cell_values(cell)[:6]:   # the service uses its store
                            value = re.sub(r"\s*\(.*?\)", "", value).strip()
                            user = names.part(value) or own.get(norm(value)) if value else None
                            if user and not names.hosts.get(norm(value)):   # (a service known: nothing invented)
                                fact(user, "uses", part, "database", r0, conf=0.75)
                for i, verb in reverse.items():           # (0.10.10) "Producer", "Consumers", "Used by" of the row
                    for value in _cell_values(cells[i])[:12] if i < len(cells) else []:
                        value = re.sub(r"\s*\(.*?\)", "", value).strip()
                        known = names.part(value) or own.get(norm(value))
                        if (known or ID_TOKEN.fullmatch(value)) and not names.hosts.get(norm(value)) and \
                                norm(known or value) != norm(part):
                            fact(known or value, verb, part, "part", r0, conf=0.7)
                for role, cell in zip(roles[1:], cells[1:]):
                    for value in _cell_values(cell)[:6]:
                        if not role or not re.search(r"\w", value):
                            continue
                        if role == "alias":               # (0.10.10) a store's name inside it (its schema), never
                            if re.fullmatch(r"[A-Za-z][\w.-]{1,40}", value) and norm(value) != norm(part) and \
                                    not (names.service(value) or own.get(norm(value))):   # the application's name
                                fact(part, "alias", value, "part", r0, conf=0.7)
                            continue
                        if role == "runs_on":
                            value = re.sub(r"(?i)^(?:on|in|at)\s+(?:the\s+)?(?=\S)", "", value)   # (0.10.7) "on db-01"
                            if PLATFORMS.match(value) or EVERY_SERVER.fullmatch(value):
                                continue                          # Kubernetes, a cloud, "all": where, but no host
                            inside = names.service(value) or own.get(norm(value))
                            if inside and not names.hosts.get(norm(value)) and norm(inside) != norm(part):
                                continue      # (0.10.9) "Group: on pg-shared-1": a part known as no server nor group of
                                #               servers (a database inside its cluster): no host made of it
                            if re.search(r"\s", value.strip()) and not names.hosts.get(norm(value)):
                                continue      # (0.10.10) "Sim Lifecycle" in a host's cell: words, no host's name
                            fact(part, "runs_on", names.hosts.get(norm(value)) or re.sub(r"\s*\(.*\)", "", value),
                                 "host", r0, conf=0.75)
                        elif role in ("logs_to", "watched_by"):
                            obj = names.index(value) if role == "logs_to" else names.metric(value)
                            if obj:
                                fact(part, role, obj, "index" if role == "logs_to" else "metric", r0, conf=0.75)
                        elif role in ("calls", "uses", "reads_from", "sends_to"):
                            if new_part and not (names.part(value) or own.get(norm(value))) and not (
                                    JOB_HEAD.match(first_head) and role in ("reads_from", "sends_to") and
                                    re.fullmatch(r"[A-Za-z0-9][\w.-]*[-_.\d][\w.-]*", value) and
                                    not names.hosts.get(norm(value))):
                                continue                  # (0.10.9) a new part's calls: to parts known, nothing invented;
                                #   (0.10.10) a job's input and output named as names: what it reads and writes
                            fact(part, role, names.part(value) or own.get(norm(value)) or value, "part", r0, conf=0.7)
                        elif role == "monitors":                  # (0.10.4) "Scrapes: ceph-mgr (port 9283)": a known part
                            target = names.part(re.sub(r"\s*\(.*?\)", "", value).strip()) or \
                                own.get(norm(re.sub(r"\s*\(.*?\)", "", value)))
                            if target and norm(target) != norm(part):
                                fact(part, "monitors", target, "part", r0, conf=0.7)
                        elif role == "part_of":           # (0.10.10) only in a table of deployables (Module, Component),
                            #                                     or a column naming the row's whole whatever the table
                            if (DEPLOYABLE_HEAD.match(header[0].strip(" *`")) or STORE_HEAD.fullmatch(first_head) or
                                TOPIC_HEAD.match(first_head) or JOB_HEAD.match(first_head)) and len(value) <= 60 and \
                                    norm(value) != norm(part) and not PLACEHOLDER.fullmatch(value):
                                fact(part, "part_of", names.part(value) or own.get(norm(value)) or value, "part", r0,
                                     conf=0.75)
                        elif role == "in_area":           # (0.10.9.3) the area or the domain the row's part is in
                            if len(value) <= 60 and norm(value) != norm(part) and not PLACEHOLDER.fullmatch(value) \
                                    and not names.hosts.get(norm(value)):
                                fact(part, "part_of", names.part(value) or own.get(norm(value)) or value, "part", r0,
                                     conf=0.75)
                                if not (names.part(value) or own.get(norm(value))):   # what the column says it is
                                    fact(value, "is_a", "domain", "kind", r0, conf=0.7)
                        elif role == "owned_by" and INFRA_VALUE["owned_by"].search(value) and len(value) <= 60:
                            value = re.sub(r"(?i)^(?:the|l['’]|la|le|die|der)\s+", "", value)   # (0.10.10) "the x squad"
                            fact(part, role, value, "owner", r0, conf=0.75)   # (0.10.9) a team: its owner on the map
                        else:
                            fact(part, role, value, "attribute", r0, conf=0.75)
            reading["src"] = source
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
        hosted_here = unit_part and re.search(r"(?i)\b(?:pools?|groups?|namespaces?|clusters?|servers?|hosts?|nodes?)\b",
                                              unit.get("title") or "")
        sections = []                                     # (0.10.10) a catalogue page: each heading names a part,
        for hm in re.finditer(r"(?m)^[ \t]*#{1,6}[ \t]+(.+?)[ \t]*$", prose):   # its "Key: value" lines that part's
            h = re.sub(r"\s*\([^)]*\)\s*$", "", hm.group(1)).strip(" `*")   # ("### Quote API (app-1, app-2)")
            said = [x for x in _named(h, names, own, home) if x[0] == 0 and len(h[len(x[1]):].split()) <= 2]
            #   ("### Quote Exporter": quote; "### Quote API": quote-api)
            sections.append((hm.start(), said[0][2] if said else names.part(h) or own.get(norm(h)) or (
                h if ID_TOKEN.fullmatch(h) and not names.hosts.get(norm(h)) else None)))

        def section_part(at: int) -> str | None:
            last = [p for h0, p in sections if h0 < at]
            return last[-1] if last else None

        for start, s in list(_sentences(prose)) + _list_sentences(prose):
            gm = GROUP_LIST.match(s)
            if gm and not names.part(gm.group("b")):      # (0.10.10) "Machine group x (production): a, b"
                held = [v for v in _cell_values(gm.group("list"))[:60] if names.hosts.get(norm(v)) or
                        (HOST_SHAPE.fullmatch(v) and not NOT_HOST.match(v) and not names.part(v))]
                if len(held) >= 2 and len(held) * 2 >= len(_cell_values(gm.group("list"))[:60]):
                    for h in held:
                        fact(names.hosts.get(norm(h)) or h, "in_group", gm.group("b"), "group", start, conf=0.75)
                    continue
            km = KEY_LINE.match(s)
            if km and property_facts(section_part(start) or unit_part, km.group("key"), km.group("value"), start):
                continue                                  # (0.10.10) "Database: pg-01", "Datenbank: pg-01"
            hm = HOSTED_LINE.match(s) if hosted_here else None
            if hm:                                        # (0.10.10) "Services on this pool: a, b, c" on a place's
                for v in _cell_values(hm.group("list"))[:40]:   # own page: each runs there
                    v = re.sub(r"\s*\(.*?\)", "", v).strip(" .")
                    known = names.part(v) or own.get(norm(v))
                    if (known or ID_TOKEN.fullmatch(v)) and not names.hosts.get(norm(v)):
                        fact(known or v, "runs_on", unit_part, "host", start, conf=0.7)
                continue
            for dev, supply in _power_sentence(s):        # (0.10.9) "UPS-A feeds pdu-1 and pdu-2", "pdu-1 (fed by
                fact(dev, "powered_by", supply, "power", start, conf=0.7)   # UPS-A)": a power device's supply
            found = _named(s, names, own, home)
            found = [x for x in found if not any(y is not x and abs(y[0] - x[0]) <= len(x[1]) + 16 and
                                                 norm(x[2]) != norm(y[2]) and norm(x[2]) in norm(y[2]) and
                                                 not (names.hosts.get(norm(y[1])) and not names.service(y[1]))
                                                 for y in found)]   # (0.10.5) a server named after its service
            #                                     ("the media relays (sfu) run on sfu-node-01") hides no part's name
            for m in INTRODUCED.finditer(s):              # (0.10.10) "uses the datastore orders-pg": a name its
                at = m.start("name")                      # noun says what it is, known or not
                if not any(a <= at < a + len(w) for a, w, _p in found) and not names.hosts.get(norm(m.group("name"))):
                    found.append((at, m.group("name"), names.part(m.group("name")) or m.group("name")))
            found.sort(key=lambda x: x[0])
            said_kinds: list[tuple[str, str]] = []
            members = _memberships(s, found, names, unit_part, said_kinds)
            for part, whole in members:                   # (0.10.10) a system and its parts
                fact(part, "part_of", whole, "part", start, conf=0.75)
            for x, k in said_kinds:                       # (0.10.10) and what the sentence says they are
                fact(x, "is_a", k, "kind", start, conf=0.7)
            for part, team in _ownerships(s, found, unit_part, unit.get("title") or ""):   # (0.10.10) "x is owned
                fact(part, "owned_by", team, "owner", start, conf=0.75)                      # by the y team"
            for long, short in _abbreviations(s):         # (0.10.10) "Identity Hub (IH)": IH is Identity Hub
                fact(long, "alias", short, "part", start, conf=0.8)
            if members or any(rx.match(s) for rx in (MADE_OF_LABEL, MADE_OF, MADE_OF_FR, MADE_OF_ES_IT, MEMBER_OF_ES,
                                                      MEMBER_OF_IT, LABEL_LIST, MEMBER_OF, MEMBER_OF_FR,
                                                      MEMBER_OF_DE, PLACE_OF, HAS_LIST, KIND_OF_ARE, HAS_LIST_FR,
                                                      HAS_LIST_DE)):
                continue                                  # (0.10.10) what a part is part of, a whole's parts: no
                #                                           flow ("x store writer is a module of y": no "stores")
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
                    if SCHEDULE_AFTER.match(s, c1):           # (0.10.10) "runs on Sundays at 04:15", "runs on the
                        continue                              # 1st of the month": when, not where
                    colon = s.find(": ", c1 + (1 if s[c1:c1 + 1] == ":" else 0))   # (0.10.10) "...: it exports pg-01
                    stop = min(stop, colon) if colon >= 0 else stop   # to s3-x": the place, if any, is before the colon
                    #                                                  (not "Runs on: web-01", the colon its value's)
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


SERVICE_HEAD = re.compile(r"(?i)(?:services?|applications?|apps?|components?|microservices?|workloads?|systems?|"
                          r"(?:scheduled\s+|batch\s+|cron\s*)?(?:tasks?|jobs?))(?:\s+names?)?")
STORE_HEAD = re.compile(r"(?i)(?:data\s*stores?|databases?|dbs?|caches?|buckets?|topics?|queues?|streams?|channels?)"
                        r"(?:\s+names?)?")
USED_BY_HEAD = re.compile(r"(?i)^\s*(?:(?:platform\s+)?services?|applications?|apps?|used\s+by|clients?|owners?\s+services?|"
                          r"systems?)\s*$")


def _implied_head(head: str, title: str) -> str:
    """(0.10.10) What a table's rows are when its first column is only "Name": what its page's title says ("Databases",
    "Event topics", "Batch jobs", "Component overview")."""
    if not re.fullmatch(r"(?i)\s*(?:names?|ids?|identifiers?|noms?|namen?)\s*", head or ""):
        return head
    for w in re.findall(r"[A-Za-zÀ-ÿ][\w-]*(?:\s+[A-Za-zÀ-ÿ][\w-]*)?", title or ""):
        for cand in (w, w.split()[-1]):
            if STORE_HEAD.fullmatch(cand) or SERVICE_HEAD.fullmatch(cand) or JOB_HEAD.match(cand) or \
                    TOPIC_HEAD.match(cand):
                return cand
    return head


def _service_row(header: list[str], roles: list[str | None], first: str, cells: list[str], names: Names) -> bool:
    """(0.10.9) A row of a table of services ("Application | Purpose | Owner | Servers") naming a service nothing else
    declares: its first column is headed as services, its name is a name (lowercase, or with a separator or a digit:
    no "Monitoring", no phrase), and its row says the server it runs on (a server known, or a host's name)."""
    if header and (STORE_HEAD.fullmatch(header[0].strip(" *`")) or JOB_HEAD.match(header[0].strip(" *`"))) and \
            not PLACEHOLDER.fullmatch(first or "") and not names.hosts.get(norm(first)) and \
            re.fullmatch(r"[A-Za-z0-9][\w]*[-_.\d][\w.-]*", first or ""):
        return True                                       # (0.10.10) a table of datastores, topics, jobs lists them
    if not header or not SERVICE_HEAD.fullmatch(header[0].strip(" *`")) or PLACEHOLDER.fullmatch(first or "") or \
            PLATFORMS.match(first or "") or names.hosts.get(norm(first)) or not (
                re.fullmatch(r"[a-z0-9][a-z0-9_.-]{1,40}", first or "") or
                (re.fullmatch(r"[A-Za-z0-9][\w.-]{1,40}", first or "") and re.search(r"[-_.\d]", first))):
        return False
    for role, cell in zip(roles[1:], cells[1:]):
        if role != "runs_on":
            continue
        for v in _cell_values(cell):
            v = re.sub(r"\s*\(.*?\)", "", re.sub(r"(?i)^(?:on|in|at)\s+(?:the\s+)?(?=\S)", "", v)).strip()
            if names.hosts.get(norm(v)) or (HOST_SHAPE.fullmatch(v) and not NOT_HOST.match(v)):
                return True
    return False


def _page_owner(title: str, names: Names, own: dict[str, str]) -> str | None:
    """The part a page is about: its title names it ("Billing service" -> billing)."""
    t = re.sub(r"\b(service|services|application|app|database|db|server|system|component|page|overview)\b", " ",
               title or "", flags=re.I)
    for cand in [title or ""] + [w for w in re.split(r"[\s/|:,()]+", t) if len(w) >= 3]:   # (0.10.10) never a
        #                                                   fragment of a name: "maria-bb-01" is not BB's
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
                across, declared = PJ.facts(us, label=_repo_name(d) or   # (0.10.6.2) its environments' name
                                            (str(d.title or "").rstrip("/").rsplit("/", 1)[-1] or None))
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
        for u in us:                                      # (0.10.10) the names a page introduces by what they are
            if u.get("kind") == "page":                   # ("the blob container x", "x: an API of a partner")
                for nm in introduced_names(u["text"] or ""):
                    if not names.hosts.get(norm(nm)):
                        own.setdefault(norm(nm), names.part(nm) or nm)
                nm = titled_name(u.get("title") or "", u["text"] or "")   # (0.10.10) the part a page is about,
                if nm and not names.hosts.get(norm(nm)):                     # by its title
                    own.setdefault(norm(nm), names.part(nm) or nm)
        repo = _repo_name(d)
        owner, aliases = owners(us, repo, names) if repo else (None, [])
        if any("speaks" in u for u in us):
            owner, aliases = None, []                     # an Ansible repository: its roles are its parts
        doc_owner[d.id] = owner
        for name in several_services(us).values():         # (0.10.10) each service folder's service: a part, the
            own.setdefault(norm(name), names.part(name) or name)   # files of its folder speak for it
        named_as = {norm(a) for a in aliases} if owner else set()   # (0.10.9.3) a workload that is the owner's
        for name in [owner] + [w["name"] for u in us for w in u["found"]["workloads"]                # other name:
                               if norm(w["name"]) not in named_as] + \
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
    shorts: dict[str, set[str]] = defaultdict(set)       # (0.10.9.3) a server known by its full name (mt.example.net)
    for h in list(names.hosts.values()):                 # is its first label in the pages ("the mt host", a diagram's
        if "." in h and not re.fullmatch(r"[\d.]+", h):  # node "mt"): that server, when no other server has that label
            shorts[norm(h.split(".")[0])].add(h)         # and no part is named so
    for s, full in shorts.items():
        if len(full) == 1 and len(s) >= 3 and s not in names.hosts and s not in own and not names.part(s) and \
                s not in GENERIC_LABELS and s not in GENERIC_HOSTS:
            names.hosts[s] = next(iter(full))
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
            elif "speaks" not in u and not u.get("built") and len(u["found"]["workloads"]) != 1 and \
                    (not owner or owner in (u["found"]["tool"], doc_owner.get(d.id))):
                owner = file_part(u.get("path") or "", names, own) or owner   # (0.10.7) the part its name says
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
READER = __version__  # (0.10.4) the reading's rules: when they change, the next run reads every unit again once.
#                     (0.10.9) the version: the rules change in a release without anyone thinking of it (0.10.7's and
#                     0.10.8's did, under "0.10.6": a deployment upgraded read nothing again until its names changed);
#                     an upgrade reads every unit again once (the LLM's reading of a unit is kept while its text is)
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
              "code_in", "in_group", "monitors", "routes_to", "powered_by", "connects_to", "part_of", "is_a")
FLOWS = ("calls", "reads_from", "sends_to", "uses")
SOURCE_RANK = {"code": 0, "config": 1, "inferred": 2, "diagram": 3, "table": 3, "doc": 4, "wiki": 4, "llm": 5}
DATA_VERBS = ("emits", "writes", "logs_to", "watched_by")


ENV_GROUP = re.compile(r"^(.+) \(([^()]+)\)$")   # (0.10.6.2) "web (orders PRD)": the group web of orders PRD


def export() -> dict[str, Any]:
    """What the documents state, merged: the relations between parts and the links of parts to the data (with their
    sources, how many units say them, a line that does), what the facts imply together (a service's logs are in the
    indices of the shipper it sends them to; what a scrape job watches on the part its target runs), the wiki's page
    links and the diagrams' arrows."""
    from supagent.models import Doc, KFact, KUnit

    names = known_names()
    alias: dict[str, str] = {}
    rows = list(db.session.query(KFact, KUnit).join(KUnit, KFact.unit_id == KUnit.id))
    given: dict[str, set[str]] = defaultdict(set)
    for f, _u in rows:
        if f.verb == "alias":
            given[norm(f.obj)].add(f.subject)
    for other, parts in given.items():               # (0.10.10) initials two names share ("PC": plan catalog and
        if len({norm(p) for p in parts}) == 1:        # perf collector): nobody's other name
            alias[other] = sorted(parts)[0]

    def canon(x: str) -> str:
        return alias.get(norm(x)) or names.part(x) or x

    from supagent.knowledge.projects import test_file

    # (0.10.6.2) a repository whose inventories are kept per environment names its groups "web (orders PRD)", in
    # its environment "orders PRD": a group its other files name bare (a README's "Target Group", a sentence) is that
    # group in each environment, never a group of its own mixing them
    levels: dict[Any, set[str]] = defaultdict(set)
    for f, u in rows:
        if f.verb == "in_group" and f.obj_kind == "group":
            levels[u.doc_id].add(f.obj)
    per_env: dict[Any, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for f, u in rows:
        if f.verb == "in_group":
            for name in (f.subject, f.obj):
                m = ENV_GROUP.match(name or "")
                if m and m.group(2) in levels[u.doc_id] and name not in per_env[u.doc_id][norm(m.group(1))]:
                    per_env[u.doc_id][norm(m.group(1))].append(name)
    rel: dict[tuple, dict[str, Any]] = {}
    for f, u in rows:
        if u.kind == "file" and test_file(u.ukey):    # (0.10.6) a repository's tests, fixtures, examples (read
            continue                                 # before 0.10.6 too): no fact of the System map
        s = canon(f.subject)
        objs = [f.obj]
        if f.obj_kind in ("group", "host") and f.verb != "in_group" and per_env.get(u.doc_id):
            objs = per_env[u.doc_id].get(norm(f.obj)) or objs
        for obj in objs:
            o = canon(obj) if f.obj_kind in ("part", "host", "group") else obj
            key = (s, f.verb, o)
            r = rel.setdefault(key, {"from": s, "kind": f.verb, "to": o, "obj_kind": f.obj_kind, "sources": set(),
                                     "units": set(), "quote": f.quote, "where": u.title or u.ukey})
            if (r["obj_kind"] in (None, "part", "attribute") and f.obj_kind not in (None, "part", "attribute")) or \
                    (r["obj_kind"] == "host" and f.obj_kind in ("namespace", "cluster", "vip")):
                r["obj_kind"] = f.obj_kind                # (0.10.10) the most telling kind of its end: a script's
            r["sources"].add(f.source)                    # "bucket" over a table's plain part
            r["units"].add(u.id)
            r.setdefault("said", set()).add(f"{u.id}|{' '.join(str(f.quote or '').split())[:120]}")   # (0.10.9.3)
            #                                               each statement saying it: a sentence, a row
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
                norm(canon(host)) not in acting and norm(host) not in declared and norm(canon(host)) not in declared \
                and not IN_CLUSTER.search(host):          # (0.10.9) a Kubernetes service's name: the service, no host
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
                "sources": sorted(r["sources"]), "units": len(r["units"]), "quote": r["quote"], "where": r["where"],
                "unit_ids": sorted(r["units"], key=str), "said": sorted(r.get("said") or ())}
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
