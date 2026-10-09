"""What a repository states across its files (0.10, the user's message of 7 October 2026: "most of repo is ansible
repo where inventory is there and configurations, and playbooks for deployments... everything can be connected"):
the facts no single file states alone, kept with the file and the line that state them.

Ansible (a repository with an inventory, playbooks or roles):
  - an inventory (INI or YAML): every host in its groups, a group's children's hosts too         host in_group group
  - a play: the roles it applies to the hosts of its pattern. A role that runs a service or deploys an application is
    a part, named by the role (its namespace removed: geerlingguy.apache is apache); a role that configures the system
    (common, firewall, ntp, users...) or installs a language is not. A role of the repository is judged by its tasks
    (a service started, an application copied), another by its name                          part runs_on group | host
  - an application a play's tasks deploy (git: repo=<url>): named by its repository                  app runs_on ...
  - a script's ad-hoc commands (ansible <pattern> -m service -a "name=X state=started")          X runs_on pattern
  - a part's templates, tasks and variables naming another group (groups['dbservers'], groups.webservers,
    hostvars[groups['x'][0]]): the part reaches the part that runs on that group (chosen by the port or the
    variable's name when several do); how, by the lines: an upstream, a backend, a proxy calls; a database, a cache,
    a coordination store is used; a monitoring object monitors. A firewall's rule, a known_hosts or an /etc/hosts
    line, a loop of an operation (delegate_to) are no link
  - an address in a part's variables (haproxy_backend_servers: 192.168.56.3:80, filebeat_output_logstash_hosts:
    logs.test:5044) that is a host of the inventory: the part reaches what runs there
Kubernetes (manifests): a workload's environment (env, envFrom a ConfigMap of the repository) giving another
  workload's address (X_ADDR: productcatalogservice:3550, a database's URI): the workload calls it, or uses it (a
  database, a cache). A ConfigMap several workloads take: only the variables a workload's own code reads.
Docker Compose: a service's depends_on and links (a database, a cache, a broker: used; another service: called) and
  the addresses of other services in its environment (DB_HOST=db, MONGO_URL=mongodb://mongo:27017).
"""

from __future__ import annotations

import fnmatch
import posixpath
import re
from collections import Counter, defaultdict
from typing import Any, Iterator


def sample_base(path: str) -> str:
    """(0.10.1) A sample file to copy (site.yml.sample, hosts.example): the path it stands for."""
    from supagent.knowledge.docs import sample_base as base

    return base(path)

CONFIDENCE = 0.85
# (0.10.6) a repository's tests, fixtures and examples: their inventories, plays and services describe a test or an
# example, not the deployment (tests/functional/all_daemons/hosts gave "mon0 part of ceph-monitoring"); read for the
# search, never for the System map
TEST_DIR = re.compile(r"(^|/)(tests?|testing|testdata|__tests__|fixtures?|molecule|examples?|e2e|spec)/", re.I)
INVENTORY_NAME = re.compile(r"(^|/)(hosts|inventory)([._-][\w.-]*)?$", re.I)
INVENTORY_DIR = re.compile(r"(^|/)inventor(y|ies)/", re.I)
HOST_TOKEN = re.compile(r"^[A-Za-z0-9_.-]*(?:\[[0-9a-zA-Z]+:[0-9a-zA-Z]+\])?[A-Za-z0-9_.-]*$")
# roles that configure the system or install a language, by their name (a role of another repository: its tasks are
# not there to tell)
BASE_ROLES = {
    "common", "base", "baseline", "bootstrap", "init", "prepare", "preflight", "prechecks", "pre-checks", "checks",
    "validate", "facts", "setup", "users", "user", "groups", "sudo", "sudoers", "ssh", "sshd", "ssh-keys",
    "authorized-keys", "hostname", "hosts", "etc-hosts", "resolv-conf", "resolvconf", "dns-client", "ntp", "chrony",
    "timezone", "time", "locale", "locales", "motd", "firewall", "iptables", "firewalld", "ufw", "selinux",
    "apparmor", "security", "hardening", "sysctl", "kernel", "limits", "swap", "mount", "mounts", "disks", "lvm",
    "filesystem", "packages", "package", "repo", "repos", "repository", "repositories", "epel", "repo-epel", "yum",
    "apt", "updates", "update", "upgrade", "reboot", "cron", "logrotate", "certificates", "certs", "ca", "tls",
    "vault", "copy", "files", "templates", "finish", "cleanup", "network", "networking", "interfaces", "environment",
    "java", "openjdk", "jdk", "jre", "python", "python3", "pip", "git", "nodejs", "node", "npm", "ruby", "rbenv",
    "rvm", "php", "golang", "go", "dotnet", "docker", "containerd", "podman",
    # an operation on the hosts, not a service: what a play does once
    "download", "downloads", "reset", "remove", "uninstall", "install", "preinstall", "postinstall", "configure",
    "deploy-finish", "post-deploy", "pre-deploy", "migrate", "migration", "backup-config", "gather-facts"}
LANGUAGES = ("java", "python", "pip", "nodejs", "node", "ruby", "php", "golang", "dotnet")
SERVICE_REST = re.compile(r"(?:prometheus-)?exporter|server|agent|daemon|proxy|gateway|red|api|worker")   # (0.10.4)
#                                     after a language's name, a service of its own: node-exporter, node-red
CONFIG_SUFFIX = re.compile(r"[_-](users|user|databases|database|dbs|schemas|privs|privileges|extensions|config|"
                           r"configure|configuration|settings|tuning|maintenance|index[_-]maintenance|setup|install|"
                           r"vars|defaults|common|repo|repository|manifests?|deploy|deployments?|provision|"
                           r"provisioning|apply)$", re.I)   # (0.10.4) k8s_manifests: what applies others, no part
# the services of the system itself: a role starting only these configures the system
SYSTEM_SERVICES = re.compile(r"^(ntpd?|chronyd?|firewalld|iptables|ip6tables|ufw|sshd?|rsyslog|syslog-ng|crond?|"
                             r"auditd|systemd-[\w-]+|tuned|irqbalance|network|networking|NetworkManager|docker|"
                             r"containerd|snapd|fail2ban|postfix|sendmail|atd|acpid|kdump|rpcbind|nscd|sssd|"
                             r"getty@?[\w-]*|udev)$", re.I)
SERVICE_MODULES = ("service", "systemd", "sysvinit", "ansible.builtin.service", "ansible.builtin.systemd",
                   "ansible.builtin.systemd_service", "ansible.builtin.sysvinit", "community.general.supervisorctl",
                   "supervisorctl")
DEPLOY_MODULES = ("git", "ansible.builtin.git", "unarchive", "ansible.builtin.unarchive", "docker_container",
                  "community.docker.docker_container", "podman_container", "containers.podman.podman_container",
                  "helm", "kubernetes.core.helm")
NO_LINK = re.compile(r"iptables|firewall|-A INPUT|--dport|allow from|\bhba\b|pg_hba|known_hosts|/etc/hosts|etc_hosts|"
                     r"with_items|with_\w+:|\bloop:|\bpriv\s*:|\bgrants?\b|_users\s*:|\busers\s*:|"
                     r"\bufw\b|security_group|delegate_to|authorized|ssh_known|ansible_host\b|hostname\b|"
                     r"difference\(|length\s*[><=]|\|\s*length", re.I)
MONITORS = re.compile(r"nagios|icinga|zabbix|check_\w+|hostgroup|define (host|service)|monitor|scrape|"
                      r"blackbox|probe|^prometheus$|^victoriametrics$|^telegraf$", re.I)
USES = re.compile(r"mysql|mariadb|postgres|pgsql|psql|jdbc|mongo|redis|valkey|keydb|memcache|cache|etcd|consul|zookeeper|"
                  r"configdb|\bdcs\b|database|(?<![a-z])db(?![a-z])|dbname|\bsql|ldap|session", re.I)
CALLS = re.compile(r"upstream|backend|server\s|proxy_pass|balance|\.host\s*=|add_backend|director|endpoint|url|"
                   r"https?:|listen|nodes", re.I)
BALANCES = re.compile(r"\bbackend\b|\bupstream\b|proxy_pass|\bbalance\b|^\s*server\s|add_backend|\bdirector",
                      re.I | re.M)
SHIPPER = re.compile(r"filebeat|fluent-?bit|fluentd|logstash-forwarder|promtail|vector|otel|collector|beat", re.I)
PORTS = {5432: ("postgres", "postgresql", "patroni"), 6432: ("pgbouncer",), 3306: ("mysql", "mariadb", "db"),
         27017: ("mongod", "mongo", "mongodb", "mongos"), 6379: ("redis",), 11211: ("memcached",), 2379: ("etcd",),
         8500: ("consul",), 9200: ("elasticsearch", "opensearch"), 5044: ("logstash",), 5601: ("kibana",),
         9092: ("kafka",), 2181: ("zookeeper",), 5672: ("rabbitmq",), 8080: ("tomcat", "jboss", "app")}
GROUP_REF = re.compile(r"groups\s*(?:\[\s*['\"](?P<q>[\w.-]+)['\"]\s*\]|\.(?P<a>[A-Za-z_]\w*)(?!\s*\()|"
                       r"\.get\(\s*['\"](?P<g>[\w.-]+)['\"]|\[\s*(?P<v>[A-Za-z_]\w*)\s*\])")
ADDRESS = re.compile(r"(?<![\w.:/@-])(?P<host>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)*)"
                     r"(?::(?P<port>\d{2,5}))?(?![\w.-])")
LOCAL = re.compile(r"\b(localhost|127\.0\.0\.1)\b")
STORE_NAME = re.compile(r"mysql|mariadb|postgres|pgsql|mongo|redis|memcache|cassandra|\bdb\b|database|oracle|mssql|"
                        r"sqlserver|elasticsearch|opensearch", re.I)
ADHOC = re.compile(r"(?m)^\s*ansible\s+(?P<pattern>[^\s-][^\s]*)\s+(?P<args>.*?-m\s+(?P<module>[\w.]+).*)$")


def _norm(x: str) -> str:
    return " ".join(str(x or "").strip().lower().replace("_", "-").split())


def _short(role: str) -> str:
    """A role's name without its namespace (geerlingguy.apache, vitabaks.autobase.patroni: apache, patroni)."""
    return str(role or "").strip().split("/")[-1].split(".")[-1]


ROLE_AFFIX = re.compile(r"^(?:ansible[-_]role[-_]|ansible[-_])|(?:[-_]ansible(?:[-_]role)?|[-_]role)$", re.I)


def _part_name(short: str) -> str:
    """(0.10.4) The part a role installs, without the words of Ansible's naming (ansible-role-nginx, proxy_ansible:
    nginx, proxy)."""
    bare = ROLE_AFFIX.sub("", short)
    return bare if len(bare) >= 2 else short


DB_FAMILY = {"postgresql": r"^(postgres|postgresql|pgsql|pg)(-|$)", "mysql": r"^(mysql|mariadb)(-|$)",
             "mongodb": r"^mongo(db)?(-|$)", "rabbitmq": r"^rabbit(mq)?(-|$)"}
DB_SERVER = {"postgresql": r"^(postgres|pg)", "mysql": r"^(mysql|mariadb)", "mongodb": r"^mongo",
             "rabbitmq": r"^rabbit"}
DB_MODULES = (("postgresql", re.compile(r"^postgresql_(db|user|privs|schema|ext|owner)$")),
              ("mysql", re.compile(r"^mysql_(db|user|query)$")), ("mongodb", re.compile(r"^mongodb_(user|shell)$")),
              ("rabbitmq", re.compile(r"^rabbitmq_(user|vhost|queue|exchange)$")))   # (0.10.4)
MASKED = re.compile(r"(?m)(:[ \t]+|^[ \t]*-[ \t]+|[\[,][ \t]*)\*\*\*(?=[ \t]*(?:#.*)?$|[ \t]*[,}\]])")
MASKED_KEY = re.compile(r"(?m)^([ \t]*(?:-[ \t]+)?)\*\*\*(?=[ \t]*:(?:[ \t]|$))")


def yaml_text(text: str) -> str:
    """A text whose masked secrets (password: ***) stay a value for YAML (*** is an alias there); (0.10.4) a masked
    key too (a Compose file's secrets: "***:", the name of a secret masked), else the whole file was no YAML."""
    return MASKED_KEY.sub(r'\1"***"', MASKED.sub(r'\1"***"', text or ""))


def _yaml(text: str) -> Any:
    text = yaml_text(text)
    try:
        import yaml

        class Loader(yaml.SafeLoader):                    # Ansible's !vault and !unsafe values: kept as text
            pass

        Loader.add_constructor(None, lambda loader, node: getattr(node, "value", None))
        docs = [d for d in yaml.load_all(text, Loader=Loader) if d is not None]   # noqa: S506 (a SafeLoader)
    except Exception:  # pylint: disable=broad-except   (a template, or not YAML)
        return None
    if len(docs) > 1 and all(isinstance(d, list) for d in docs):
        return [x for d in docs for x in d]               # (0.10.5) "---", comments, "---" again: one stream of
    return docs[0] if docs else None                      # documents (was: no YAML, the playbook unread)


def _line(text: str, pos: int) -> tuple[int, str]:
    start = text.rfind("\n", 0, pos) + 1
    end = text.find("\n", pos)
    return text.count("\n", 0, pos) + 1, text[start:end if end >= 0 else len(text)].strip()[:300]


def _expand(host: str) -> list[str]:
    """An inventory's host range (web[01:03], db-[a:c]) as its hosts."""
    m = re.search(r"\[([0-9a-zA-Z]+):([0-9a-zA-Z]+)\]", host)
    if not m:
        return [host]
    a, b = m.group(1), m.group(2)
    if a.isdigit() and b.isdigit():
        width = len(a) if a.startswith("0") else 0
        items = [str(i).zfill(width) for i in range(int(a), int(b) + 1)][:256]
    elif len(a) == 1 and len(b) == 1:
        items = [chr(c) for c in range(ord(a), ord(b) + 1)]
    else:
        return [host]
    return [host[:m.start()] + x + host[m.end():] for x in items]


# --------------------------------------------------------------------------------------------------------------- #
# inventories
# --------------------------------------------------------------------------------------------------------------- #
class Inventory:
    def __init__(self, path: str) -> None:
        self.path = path
        self.groups: dict[str, dict[str, Any]] = {}       # name -> {hosts: {host: line}, children: [..], vars, line}
        self.hostvars: dict[str, dict[str, Any]] = defaultdict(dict)

    def group(self, name: str, line: int) -> dict[str, Any]:
        return self.groups.setdefault(name, {"hosts": {}, "children": [], "vars": {}, "line": line})

    def hosts_of(self, group: str, seen: set[str] | None = None) -> dict[str, int]:
        """A group's hosts, its children's too: {host: the line naming it}."""
        seen = seen if seen is not None else set()
        if group in seen or group not in self.groups:
            return {}
        seen.add(group)
        out = dict(self.groups[group]["hosts"])
        for c in self.groups[group]["children"]:
            for h, ln in self.hosts_of(c, seen).items():
                out.setdefault(h, ln)
        return out

    def all_hosts(self) -> list[str]:
        return sorted({h for g in self.groups.values() for h in g["hosts"]})

    def parents(self, group: str) -> list[str]:
        return [g for g, v in self.groups.items() if group in v["children"]]


def _ini_inventory(path: str, text: str) -> Inventory | None:
    inv = Inventory(path)
    current, kind = "ungrouped", "hosts"
    hosts = 0
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        m = re.match(r"^\[([^\]:\s]+)(?::(hosts|children|vars))?\]\s*(?:[#;].*)?$", line)
        if m:
            current, kind = m.group(1), m.group(2) or "hosts"
            inv.group(current, i)
            continue
        if re.match(r"^\[", line):
            return None                                   # another kind of INI file
        if kind == "vars":
            k, _, v = line.partition("=")
            if k.strip():
                inv.group(current, i)["vars"][k.strip()] = v.strip().strip("\"'")
            continue
        token = line.split()[0]
        if kind == "children":
            inv.group(current, i)["children"].append(token)
            continue
        rest = line[len(token):].split()
        if "=" in token or (rest and rest[0] in ("=", ":")) or not HOST_TOKEN.match(token):
            return None                                   # key = value lines: settings, not an inventory
        for h in _expand(token):
            inv.group(current, i)["hosts"].setdefault(h, i)
            hosts += 1
            for kv in rest:
                k, eq, v = kv.partition("=")
                if eq:
                    inv.hostvars[h][k] = v.strip("\"'")
    named = [g for g in inv.groups if g not in ("ungrouped", "all")]
    return inv if named else None                          # (an /etc/hosts-like file: no group, no inventory)


def _yaml_inventory(path: str, text: str) -> Inventory | None:
    data = _yaml(text)
    if not isinstance(data, dict):
        return None
    top = data.get("all") if isinstance(data.get("all"), dict) else data
    if not isinstance(top, dict) or not any(isinstance(v, dict) and ("hosts" in v or "children" in v)
                                            for v in ([top] if "all" in data else list(top.values()))):
        return None
    inv = Inventory(path)

    def line_of(name: str) -> int:
        m = re.search(r"(?m)^\s*" + re.escape(name) + r"\s*:", text)
        return text.count("\n", 0, m.start()) + 1 if m else 1

    def walk(name: str, node: Any) -> None:
        g = inv.group(name, line_of(name))
        if not isinstance(node, dict):
            return
        for h, hv in (node.get("hosts") or {}).items() if isinstance(node.get("hosts"), dict) else []:
            for x in _expand(str(h)):
                g["hosts"].setdefault(x, line_of(str(h)))
                if isinstance(hv, dict):
                    inv.hostvars[x].update(hv)
        if isinstance(node.get("vars"), dict):
            g["vars"].update(node["vars"])
        for c, cv in (node.get("children") or {}).items() if isinstance(node.get("children"), dict) else []:
            g["children"].append(str(c))
            walk(str(c), cv)

    if "all" in data:
        walk("all", top)
    else:
        for name, node in top.items():
            walk(str(name), node)
    return inv if inv.all_hosts() or len(inv.groups) > 1 else None


# (0.10.6.2, the team's report of 9 October: "we have inventory per application in the repo, like inventory/PRD/hosts
# or inventory/STG/hosts") an inventory kept per environment: its groups are that environment's, its servers too
ENV_WORDS = re.compile(r"^(prd|prod|production|live|stg|stage|staging|uat|qa|qua|qualif|qualification|test|tst|dev|"
                       r"develop|development|int|integration|sit|preprod|pre-prod|preproduction|ppd|pprod|pp|rec|"
                       r"recette|hom|homol|homologation|sandbox|sbx|dr|drp|perf|performance|demo|lab|nonprod|non-prod|"
                       r"(?:prd|prod|stg|uat|dev|test|qa|int)[-_]?\d{1,2})$", re.I)
NOT_ENV = {"main", "all", "default", "site", "static", "local", "example", "sample", "hosts", "inventory", "group_vars",
           "host_vars", "files", "templates"}
ANSIBLE_WORDS = ("ansible|deploy|deployments?|infra|infrastructure|playbooks?|inventor(?:y|ies)|config|configuration|"
                 "ops|automation|provisioning|platform")
REPO_SUFFIX = re.compile(rf"[-_](?:{ANSIBLE_WORDS})$", re.I)
REPO_PREFIX = re.compile(rf"^(?:{ANSIBLE_WORDS})[-_]", re.I)
GENERIC_FOLDER = re.compile(rf"^(?:{ANSIBLE_WORDS}|src|repo|repository|files|etc)$", re.I)


def _app_of(label: str | None) -> str:
    """A repository's name without its Ansible words (orders-ansible, ansible-orders, parcel-ops: orders, parcel;
    infra-ansible: infra)."""
    x = str(label or "").strip()
    for rx in (REPO_SUFFIX, REPO_PREFIX):
        y = rx.sub("", x, count=1)
        if y:
            x = y
    return x


def inventory_place(path: str) -> tuple[str | None, str | None]:
    """(0.10.6.2) What where an inventory is kept says it is for: (its environment, the application or site above it)
    from inventory/<env>/hosts, <app>/inventory/<env>/hosts, inventories/<app>/<env>/hosts.yml, inventory/<env>.ini,
    inventory/hosts-<env>, <env>/hosts; (None, None) when the place says nothing (inventory/hosts, hosts)."""
    segs = [x for x in sample_base(path or "").split("/") if x]
    if not segs:
        return None, None
    dirs, stem = segs[:-1], re.sub(r"\.(ya?ml|ini|cfg|txt|toml)$", "", segs[-1], flags=re.I)
    rest = re.sub(r"^(?:hosts|inventory)[._-]?|[._-]?(?:hosts|inventory)$", "", stem, flags=re.I)
    at = next((i for i in range(len(dirs) - 1, -1, -1) if re.fullmatch(r"inventor(?:y|ies)", dirs[i], re.I)), None)
    if at is not None:
        above = dirs[at - 1] if at >= 1 else None
        below = [x for x in dirs[at + 1:] if x.lower() not in NOT_ENV]
        if not below:                                     # inventory/prod.ini, inventory/hosts-stg
            env = rest if rest and rest.lower() not in NOT_ENV else None
            return (env, above) if env else (None, None)
        envs = [x for x in below if ENV_WORDS.match(x)]
        env = envs[-1] if envs else below[-1]
        others = [x for x in below if x != env]
        return env, (others[-1] if others else above)
    if rest and ENV_WORDS.match(rest):                    # hosts-prd, prod-inventory.yml
        return rest, (dirs[-1] if dirs else None)
    if dirs and ENV_WORDS.match(dirs[-1]) and re.fullmatch(r"hosts|inventory", stem, re.I):   # prd/hosts
        up = dirs[-2] if len(dirs) >= 2 and not re.fullmatch(r"env(?:ironment)?s?", dirs[-2], re.I) else None
        return dirs[-1], up
    return None, None


def levels(invs: dict[str, "Inventory"], label: str | None = None) -> dict[str, str]:
    """(0.10.6.2) {inventory path: its environment's name} for a repository that keeps its inventories per
    environment (two environments or more, or one its folder names as such: PRD, staging, uat...): the application
    (the folder above the inventory, else the repository's name without its Ansible words) and the environment as
    the folders write them, "orders PRD"."""
    places = {p: inventory_place(p) for p in invs}
    places = {p: (env, above) for p, (env, above) in places.items() if env}
    if not places:
        return {}
    if len({(env.lower(), (above or "").lower()) for env, above in places.values()}) < 2 and \
            not any(ENV_WORDS.match(env) for env, _above in places.values()):
        return {}
    repo = _app_of(label)
    out = {}
    for p, (env, above) in places.items():
        app = above if above and above.lower() not in NOT_ENV and not GENERIC_FOLDER.match(above) else repo
        out[p] = f"{app} {env}" if app else env
    return out


def inventories(units: list[dict[str, Any]]) -> dict[str, Inventory]:
    out = {}
    for u in units:
        path = u["path"] or ""
        low = sample_base(path).lower()                     # (0.10.1) hosts.example, inventory.ini.sample
        if not (INVENTORY_NAME.search(low) or INVENTORY_DIR.search(low)) or \
                low.endswith((".py", ".php", ".sh", ".cfg", ".j2", ".md", ".json", ".rb", ".js")) or \
                "/group_vars/" in "/" + low or "/host_vars/" in "/" + low:
            continue
        text = u["text"] or ""
        inv = _yaml_inventory(path, text) if low.endswith((".yml", ".yaml")) else _ini_inventory(path, text)
        if inv is not None and "plugin" not in (_yaml(text) or {} if low.endswith((".yml", ".yaml")) else {}):
            out[path] = inv
    return out


# --------------------------------------------------------------------------------------------------------------- #
# variables
# --------------------------------------------------------------------------------------------------------------- #
def _vars_files(units: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """group_vars and host_vars: {"group:<name>" | "host:<name>": variables}, per folder of the repository."""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    for u in units:
        path = u["path"] or ""
        m = re.search(r"(?:^|/)(group|host)_vars/([^/]+?)(?:\.ya?ml)?(?:/[^/]+?)?$", sample_base(path))
        if not m:
            continue
        data = _yaml(u["text"] or "")
        if isinstance(data, dict):
            out[f"{m.group(1)}:{m.group(2)}"].update(data)
    return out


def _resolve(value: Any, scopes: list[dict[str, Any]], depth: int = 0) -> Any:
    """A value with its {{ variable }} references replaced from the scopes given (two levels), else kept."""
    if isinstance(value, str) and "{{" in value and depth < 3:
        def one(m: re.Match) -> str:
            name = m.group(1)
            for s in scopes:
                if name in s and not isinstance(s[name], (dict, list)):
                    return str(_resolve(s[name], scopes, depth + 1))
            return m.group(0)
        whole = re.fullmatch(r"\{\{\s*([A-Za-z_]\w*)\s*\}\}", value.strip())
        if whole:
            for s in scopes:
                if whole.group(1) in s:
                    return _resolve(s[whole.group(1)], scopes, depth + 1)
        return re.sub(r"\{\{\s*([A-Za-z_]\w*)\s*(?:\|[^}]*)?\}\}", one, value)
    return value


# --------------------------------------------------------------------------------------------------------------- #
# plays and roles
# --------------------------------------------------------------------------------------------------------------- #
def _tasks(items: Any) -> Iterator[dict[str, Any]]:
    for t in items or []:
        if not isinstance(t, dict):
            continue
        yield t
        for key in ("block", "rescue", "always"):
            yield from _tasks(t.get(key))


def _module(task: dict[str, Any]) -> tuple[str, Any]:
    skip = {"name", "when", "tags", "become", "become_user", "notify", "register", "with_items", "loop", "vars",
            "args", "delegate_to", "run_once", "ignore_errors", "changed_when", "failed_when", "until", "retries",
            "delay", "environment", "no_log", "block", "rescue", "always", "listen", "loop_control", "check_mode",
            "become_method", "async", "poll", "throttle", "any_errors_fatal", "with_dict", "with_fileglob"}
    for k, v in task.items():
        if k not in skip and not k.startswith("with_"):
            return k, v
    return "", None


def _args(value: Any) -> dict[str, Any]:
    """A task's arguments: a mapping, or "key=value key=value" written in one line."""
    if isinstance(value, dict):
        return value
    out = {}
    for m in re.finditer(r"(\w+)=(\"[^\"]*\"|'[^']*'|\S+)", str(value or "")):
        out[m.group(1)] = m.group(2).strip("\"'")
    return out


def _starts_service(tasks: list[dict[str, Any]]) -> list[str]:
    """The services the tasks (or handlers) start, restart, reload or enable."""
    out = []
    for t in tasks:
        mod, val = _module(t)
        a = _args(val)
        if mod in SERVICE_MODULES and a.get("name") and (str(a.get("state", "")).lower() in
                                                         ("started", "restarted", "reloaded") or
                                                         str(a.get("enabled", "")).lower() in ("yes", "true")):
            out.append(str(a["name"]))
        if mod in ("command", "shell", "ansible.builtin.command", "ansible.builtin.shell"):
            name = r"((?:[\w@.-]|\{\{[^}]*\}\})+)"
            for m in re.finditer(r"systemctl\s+(?:start|restart|enable(?:\s+--now)?)\s+" + name + r"|/etc/init\.d/" +
                                 name + r"\s+(?:start|restart)|\bservice\s+" + name + r"\s+(?:start|restart)",
                                 str(a.get("cmd") or val or "")):
                out.append(next(x for x in m.groups() if x))
    return out


def _deploys(tasks: list[dict[str, Any]]) -> list[tuple[str, Any]]:
    """What the tasks put in place as an application: (module, arguments)."""
    out = []
    for t in tasks:
        mod, val = _module(t)
        a = _args(val)
        if mod in DEPLOY_MODULES and (a.get("repo") or a.get("src") or a.get("image") or a.get("chart_ref")):
            out.append((mod, a))
        elif isinstance(val, dict) and val.get("image") and (val.get("name") or val.get("action")):
            out.append((mod, a))                              # a container (a module of the project's own: an image)
        if mod in ("copy", "ansible.builtin.copy") and re.search(r"\.(war|ear|jar)$", str(a.get("src") or "")):
            out.append((mod, a))
    return out


class Role:
    def __init__(self, name: str, root: str | None) -> None:
        self.name = name
        self.root = root                                   # its folder in the repository, when there
        self.services: list[str] = []
        self.deploys: list[tuple[str, Any]] = []
        self.vars: dict[str, Any] = {}
        self.tasks = False                                 # its tasks are in the repository
        self.stores: list[tuple[str, str, int]] = []       # (0.10.4) (family, file, line): the databases its tasks
        #                                                    make an account or a database in (postgresql_db ...)
        self.site = False                                  # (0.10.4) it publishes a web site (a virtual host)
        self.stack = False                                 # (0.10.6) it carries a Compose file of several services

    @property
    def part(self) -> str | None:
        """The part this role is, or None (it configures the system or installs a language; (0.10.6) it deploys a
        Compose stack: its services are the parts, not the role)."""
        if self.stack:
            return None
        short = _short(self.name)
        n = _norm(short)
        if self.root is not None and self.tasks:           # its tasks tell
            own = [s for s in self.services if not SYSTEM_SERVICES.match(s)]
            return _part_name(short) if (own or self.deploys or self.site) and \
                not n.startswith(("base-", "common")) else None   # (0.10.4) a web site it publishes: an application
        if n in BASE_ROLES or n.startswith("base-") or CONFIG_SUFFIX.search(n) or \
                any(n.startswith(lang + "-") and not SERVICE_REST.fullmatch(n[len(lang) + 1:]) for lang in LANGUAGES):
            return None                                    # (0.10.4) php-mysql, nodejs-16: the language's; node-exporter
        return _part_name(short)                           # is a service of its own


EVERYWHERE_SHARE = 0.6         # (0.10.4) a role applied to this share of a project's groups at least (and to 3)...
EVERYWHERE_MIN = 3


def _service_bases(name: str) -> set[str]:
    """(0.10.4) The names a service is known by, without its instance and unit suffix: "ceph-mds@{{ host }}" ->
    ceph-mds, "node_exporter" -> node-exporter, "{{ 'x-crash@' + h if c else 'x-crash.service' }}" -> x-crash; a name
    only a variable gives ("{{ service_name }}") has none."""
    text = str(name or "")
    exprs = [re.sub(r"\[[^\]]*\]", "", e) for e in re.findall(r"\{\{(.*?)\}\}", text)]   # not a subscript's key
    parts = re.findall(r"'([^']+)'|\"([^\"]+)\"", " ".join(exprs))
    words = [a or b for a, b in parts] + [re.sub(r"\{\{.*?\}\}", "", text)]
    out = set()
    for w in words:
        base = re.split(r"[@\s]", w.strip(), maxsplit=1)[0]
        base = re.sub(r"\.(service|target|socket|timer)$", "", base)
        base = _norm(base)
        if base and re.search(r"[a-z]", base):
            out.add(base)
    return out


def _role_prefix(roles: dict[str, "Role"]) -> str:
    """(0.10.4) The prefix every role of a project shares ("ceph-" for ceph-mon, ceph-osd...), or ""."""
    names = sorted({_norm(_short(r.name)) for r in roles.values()})
    if len(names) < 3:
        return ""
    pre = posixpath.commonprefix(names)
    return pre[: max(pre.rfind("-"), pre.rfind(" ")) + 1] if pre else ""


def _own_service(role: "Role", prefix: str) -> bool:
    """(0.10.4) The role starts a service named after itself (ceph-mds starts ceph-mds@...; node-exporter starts
    node_exporter), not only the system's, another role's or a variable's."""
    short = _norm(_short(role.name))
    core = short[len(prefix):] if prefix and short.startswith(prefix) else short
    for svc in role.services:
        for base in _service_bases(svc):
            if SYSTEM_SERVICES.match(base):
                continue
            b = base[len(prefix):] if prefix and base.startswith(prefix) else base
            if b and (b == core or (len(core) >= 3 and core in b) or (len(b) >= 4 and b in core)):
                return True
    return False


def _roles(units: list[dict[str, Any]], by_path: dict[str, dict[str, Any]]) -> dict[str, Role]:
    """The roles of the repository: {"<folder>/roles/<name>" or "<name>": Role}."""
    out: dict[str, Role] = {}
    for path in by_path:                                    # (a role may be nested: roles/kubernetes/node)
        m = re.match(r"^(?P<root>(?:.*/)?roles/(?P<name>(?:[^/]+/)*?[^/]+))/(?P<rest>(?:tasks|handlers|defaults|vars|"
                     r"templates|files|meta|library)/.+)$", path)
        if not m:
            continue
        r = out.setdefault(m.group("root"), Role(m.group("name"), m.group("root")))
        rest = m.group("rest")
        if rest.startswith(("tasks/", "handlers/")) and rest.endswith((".yml", ".yaml")):
            data = _yaml(by_path[path]["text"] or "")
            r.tasks = r.tasks or rest.startswith("tasks/")
            if isinstance(data, list):
                ts = list(_tasks(data))
                r.services += _starts_service(ts)
                r.deploys += _deploys(ts)
                text = by_path[path]["text"] or ""
                for t in ts:                               # (0.10.4) postgresql_db, mysql_user ...: a database it uses
                    mod = _module(t)[0].split(".")[-1]
                    fam = next((f for f, rx in DB_MODULES if rx.match(mod)), None)
                    if fam:
                        at = text.find(mod)
                        r.stores.append((fam, path, text.count("\n", 0, max(at, 0)) + 1))
        if re.search(r"(^|/)[^/]*(sites-(available|enabled)|vhost|virtualhost|conf\.d_[^/]*\.conf)[^/]*$", rest, re.I) \
                and rest.startswith(("templates/", "files/")):
            r.site = True                                  # (0.10.4) an Apache or nginx site of its own
        if rest.startswith(("defaults/", "vars/")) and rest.endswith((".yml", ".yaml")):
            data = _yaml(by_path[path]["text"] or "")
            if isinstance(data, dict):
                r.vars.update(data)
        if re.search(r"(^|/)(docker-)?compose(\.[\w-]+)?\.ya?ml(\.j2)?$", rest):   # (0.10.6) a stack of services
            data = _yaml(by_path[path]["text"] or "")
            if isinstance(data, dict) and isinstance(data.get("services"), dict) and len(data["services"]) >= 2:
                r.stack = True
    return out


def _find_role(name: str, playbook: str, roles: dict[str, Role]) -> Role:
    """The role a play names: the repository's own (a roles/ folder at or above the playbook), else one from elsewhere
    (a collection, Ansible Galaxy)."""
    short = _short(name)
    rel = str(name).strip().strip("/") if "/" in str(name) and "." not in str(name).split("/")[0] else short
    d = posixpath.dirname(playbook)
    while True:
        for cand in dict.fromkeys((rel, short)):           # a nested role by its path (kubernetes/node), else its name
            key = posixpath.join(d, "roles", cand) if d else f"roles/{cand}"
            if key in roles:
                return roles[key]
        if not d:
            break
        d = posixpath.dirname(d)
    matches = [r for k, r in roles.items() if k.endswith("/roles/" + rel) or k == "roles/" + rel] or \
        [r for k, r in roles.items() if k.endswith("/roles/" + short) or k == "roles/" + short]
    return matches[0] if len(matches) == 1 else roles.setdefault(f"@{name}", Role(name, None))


def _plays(u: dict[str, Any]) -> list[dict[str, Any]]:
    data = _yaml(u["text"] or "")
    if not isinstance(data, list) or not any(isinstance(p, dict) and "hosts" in p for p in data):
        return []
    text = u["text"] or ""
    starts = [m.start() for m in re.finditer(r"(?m)^\s*-?\s*hosts\s*:", text)]
    out, k = [], 0
    for p in data:
        if not isinstance(p, dict) or "hosts" not in p:
            continue
        pos = starts[k] if k < len(starts) else 0
        k += 1
        pattern = p["hosts"]
        pattern = ":".join(map(str, pattern)) if isinstance(pattern, list) else str(pattern)
        roles, where = [], {}
        for r in p.get("roles") or []:
            name = r if not isinstance(r, dict) else (r.get("role") or r.get("name"))
            if name:
                roles.append(str(name))
                g = _when_group(r.get("when")) if isinstance(r, dict) else None
                if g:
                    where[str(name)] = g
        tasks = []
        for key in ("pre_tasks", "tasks", "post_tasks", "handlers"):
            tasks += list(_tasks(p.get(key)))
        for t in tasks:
            mod, val = _module(t)
            if mod.endswith(("include_role", "import_role")) and isinstance(val, dict) and val.get("name"):
                roles.append(str(val["name"]))
                g = _when_group(t.get("when"))
                if g:
                    where[str(val["name"])] = g
        out.append({"file": u["path"], "pos": pos, "pattern": pattern, "roles": list(dict.fromkeys(roles)),
                    "where": where, "tasks": tasks, "vars": p.get("vars") if isinstance(p.get("vars"), dict) else {},
                    "vars_files": [str(x) for x in (p.get("vars_files") or []) if isinstance(x, str)]})
    return out


WHEN_GROUP = re.compile(r"inventory_hostname\s+in\s+groups\s*(?:\.get\(\s*(?P<get>.+?)\s*(?:,|\)\s*$|\)\s)|"
                        r"\[\s*(?P<idx>.+?)\s*\])|['\"](?P<lit>[\w.-]+)['\"]\s+in\s+group_names")


def _when_group(cond: Any) -> str | None:
    """(0.10.1) The group a role's condition keeps it to ("inventory_hostname in groups[mon_group_name]", "'web' in
    group_names"): "{{ expression }}" for a variable's (with its default), the name itself for a literal; None
    without one, or with several groups."""
    text = " ".join(map(str, cond)) if isinstance(cond, list) else str(cond or "")
    if " or " in text:
        return None                                       # (several groups: the play's places stay)
    m = WHEN_GROUP.search(text)
    if not m:
        return None
    if m.group("lit"):
        return m.group("lit")
    expr = (m.group("get") or m.group("idx") or "").strip()
    lit = re.fullmatch(r"['\"]([\w.-]+)['\"]", expr)
    return lit.group(1) if lit else "{{ " + expr + " }}"


def hosts_pattern(pattern: str, scopes: list[dict[str, Any]], defaults: dict[str, Any] | None = None) -> str:
    """(0.10.1) A play's hosts written with Jinja, resolved: a variable (the play's, the inventory's for all), else the
    value of its default('x') filter, else the one of a role's defaults; groups['x'] or groups.x (with a default(...)
    after it); what stays unresolved keeps its braces (no place)."""
    def one(m: re.Match) -> str:
        expr = m.group(1).strip()
        g = re.match(r"groups\s*(?:\[\s*['\"]([\w.-]+)['\"]\s*\]|\.([A-Za-z_]\w*))", expr)
        if g:
            return g.group(1) or g.group(2)
        v = re.match(r"([A-Za-z_]\w*)\s*(?:\|\s*(?:default|d)\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*\w+\s*)?\))?\s*$", expr)
        if not v:
            return m.group(0)
        for sc in scopes:
            val = sc.get(v.group(1)) if isinstance(sc, dict) else None
            if isinstance(val, (str, int)) and "{{" not in str(val):
                return str(val)
        if v.group(2):
            return v.group(2)
        val = (defaults or {}).get(v.group(1))
        return str(val) if isinstance(val, (str, int)) and "{{" not in str(val) else m.group(0)
    return re.sub(r"\{\{(.*?)\}\}", one, pattern or "")


def _places(pattern: str, inv: Inventory | None, named: frozenset[str] | set[str] = frozenset()) -> list[tuple[str, str]]:
    """Where a play's pattern points: [("group", name) | ("host", name)]; all the hosts for "all". (0.10.6) A group
    the inventory has not but the repository's tests name (`named`: ceph's mdss, nfss): the group, without hosts."""
    out: list[tuple[str, str]] = []
    if "{{" in pattern:
        return out
    items = [re.sub(r"\[[\d:\-]*\]$", "", x.strip()) for x in re.split(r"[:,]", pattern) if x.strip()]
    for x in items:                                       # (group[0], group[1:3]: the group's hosts, the group)
        if x.startswith(("!", "&", "_")) or x in ("localhost", "127.0.0.1"):
            continue                                       # (an exclusion, an intersection, a group made at run time)
        if x in ("all", "*"):
            out += [("host", h) for h in (inv.all_hosts() if inv else [])]
        elif inv and x in inv.groups:
            out.append(("group", x))
        elif inv and x in inv.all_hosts():
            out.append(("host", x))
        elif inv and any(ch in x for ch in "*?["):
            out += [("group", g) for g in inv.groups if fnmatch.fnmatch(g, x) and g not in ("all", "ungrouped")]
        elif not inv or not inv.groups or x in named:
            out.append(("group", x))                       # no inventory in the repository: the group as named
    return list(dict.fromkeys(out))


def _inventory_for(path: str, invs: dict[str, Inventory], pattern: str = "") -> Inventory | None:
    """The inventory a playbook (or a script) runs with: the one of its folder or the nearest above it, else the only
    one, else the one holding the groups of its pattern (one with hosts first)."""
    d = posixpath.dirname(path)
    while True:
        here = sorted(i for i in invs if posixpath.dirname(i) == d or (posixpath.dirname(posixpath.dirname(i)) == d
                                                                         and INVENTORY_DIR.search(i + "/")))
        if len(here) == 1 or (here and not pattern):
            return invs[here[0]]
        if here:
            invs = {i: invs[i] for i in here}
            break
        if not d:
            break
        d = posixpath.dirname(d)
    if len(invs) == 1:
        return next(iter(invs.values()))
    wanted = [x for x in re.split(r"[:,&!]", pattern) if x.strip() and x.strip() not in ("all", "*", "localhost")]
    fit = sorted((i for i in invs if all(w.strip() in invs[i].groups for w in wanted)),
                 key=lambda i: (not invs[i].all_hosts(), i))
    return invs[fit[0]] if fit and wanted else None


# --------------------------------------------------------------------------------------------------------------- #
# the facts
# --------------------------------------------------------------------------------------------------------------- #
class Facts:
    def __init__(self, by_path: dict[str, dict[str, Any]]) -> None:
        self.by_path = by_path
        self.out: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self.seen: set[tuple] = set()

    def add(self, path: str, subject: str, verb: str, obj: str, obj_kind: str, pos: int | None = None,
            line: int | None = None, conf: float = CONFIDENCE, source: str = "config") -> None:
        if not subject or not obj or (_norm(subject) == _norm(obj) and obj_kind != "group"):
            return                                         # (a role "web" on the group "web": kept)
        key = (path, _norm(subject), verb, _norm(obj))
        if key in self.seen:
            return
        self.seen.add(key)
        text = (self.by_path.get(path) or {}).get("text") or ""
        if line is not None:
            lines = text.splitlines()
            quote = lines[line - 1].strip()[:300] if 0 < line <= len(lines) else ""
        else:
            line, quote = _line(text, pos or 0)
        from supagent.knowledge.docs import mask_secrets

        self.out[path].append({"subject": subject, "verb": verb, "obj": obj, "obj_kind": obj_kind, "line": line,
                               "quote": mask_secrets(quote)[0], "source": source, "confidence": conf})


def _target(group_parts: set[str], window: str, scopes: list[dict[str, Any]], me: str) -> str | None:
    """Which of the parts on a group a line reaches: the only one, else the one its port or its variable names."""
    cands = sorted(p for p in group_parts if _norm(p) != _norm(me))
    if len(cands) <= 1:
        return cands[0] if cands else None
    names = re.findall(r"\{\{\s*([A-Za-z_]\w*)", window) + re.findall(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", window)
    for v in names:                                       # pgbouncer_listen_port, postgresql_port: by its name
        for p in cands:
            if _norm(v).startswith(_norm(p) + "-"):
                return p
    ports = [int(x) for x in re.findall(r":(\d{2,5})\b", window)]
    for v in names:
        val = _resolve("{{ %s }}" % v, scopes)
        if isinstance(val, (int, str)) and str(val).isdigit():
            ports.append(int(val))
    for port in ports:
        for p in cands:
            if any(_norm(p).startswith(x) or x.startswith(_norm(p)) for x in PORTS.get(port, ())):
                return p
    return None


def _verb(window: str, me: str) -> str | None:
    if NO_LINK.search(window):
        return None
    if MONITORS.search(window) or MONITORS.search(me):
        return "monitors"
    if SHIPPER.search(me):
        return "sends_to"
    if BALANCES.search(window):
        return "calls"                                     # a proxy's backends (a database's too: it forwards to it)
    if USES.search(window):
        return "uses"
    return "calls"


def ansible(units: list[dict[str, Any]], named: frozenset[str] | set[str] = frozenset(), label: str | None = None
            ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    """The facts of an Ansible repository ({path: [fact]}) and the names it declares ({"parts", "hosts", "groups"}).
    `named`: (0.10.6) the groups its tests' inventories name (no host of theirs). `label`: (0.10.6.2) the
    repository's name, for its environments' (levels())."""
    by_path = {u["path"]: u for u in units if u.get("path")}
    invs = inventories(units)
    staged = levels(invs, label)                       # (0.10.6.2) {inventory: "orders PRD"}

    def gname(path: str | None, group: str) -> str:
        """A group of an inventory kept per environment: "web (orders PRD)" (each environment's web its own); a group
        named like its environment or its application (production, orders, orders_prd: every server of it) is the
        environment itself."""
        if path not in staged:
            return group
        level = staged[path]
        words = [_norm(w) for w in level.split()]
        if _norm(group) in {_norm(level), *words, "-".join(words), "-".join(reversed(words))}:
            return level
        return f"{group} ({level})"

    def placed(inv: "Inventory | None", kind: str, place: str) -> list[str]:
        """Where a play's group is: in each environment of the application that has it (a play runs with any of
        them), else the group itself."""
        if kind != "group" or inv is None or inv.path not in staged:
            return [place]
        app = staged[inv.path].rsplit(" ", 1)[0] if " " in staged[inv.path] else None
        out = [gname(inv.path, place)]
        for other, oi in sorted(invs.items()):
            if other != inv.path and other in staged and place in oi.groups and \
                    (staged[other].rsplit(" ", 1)[0] if " " in staged[other] else None) == app:
                out.append(gname(other, place))
        return list(dict.fromkeys(out))
    roles = _roles(units, by_path)
    plays = [p for u in units if sample_base(u["path"] or "").endswith((".yml", ".yaml")) and   # (site.yml.sample too)
             "roles/" not in (u["path"] or "")
             for p in _plays(u)]
    adhoc = [(u, m) for u in units if (u["path"] or "").endswith((".sh", ".bash")) for m in ADHOC.finditer(u["text"] or "")]
    names: dict[str, list[str]] = {"parts": [], "hosts": [], "groups": []}
    role_tasks = any(re.search(r"(^|/)roles/[^/]+/tasks/[^/]+\.ya?ml$", p) for p in by_path)
    tooling = any(re.search(r"(^|/)(ansible\.cfg|galaxy\.yml|requirements\.ya?ml|site\.ya?ml)$", p) for p in by_path)
    if not (plays or adhoc or invs or (role_tasks and tooling)):
        return {}, names                                   # no play, no inventory, no role with tasks: not Ansible
    names["ansible"] = {"inventories": len(invs), "hosts": len({h for i in invs.values() for h in i.all_hosts()}),
                        "groups": len({g for i in invs.values() for g in i.groups if g not in ("all", "ungrouped")}),
                        "playbooks": len({p["file"] for p in plays}),
                        "roles": len({k for k in roles if not k.startswith("@")} |
                                     {r for p in plays for r in p["roles"]})}
    F = Facts(by_path)
    vfiles = _vars_files(units)
    # the inventories: every host in its groups (a child group's hosts in its parents' too); (0.10.6.2) an
    # inventory kept per environment: its groups in the environment ("web (orders PRD)" in "orders PRD"), the hosts of
    # no group of its own in the environment itself
    for path, inv in invs.items():
        env = staged.get(path)
        for g in inv.groups:
            if g in ("all", "ungrouped"):
                if env:                                    # a host of no group of its own: in the environment
                    for h, ln in inv.groups[g]["hosts"].items():
                        F.add(path, h, "in_group", env, "group", line=ln, conf=0.95)
                continue
            me = gname(path, g)
            names["groups"].append(me)
            for h, ln in inv.hosts_of(g).items():
                F.add(path, h, "in_group", me, "group", line=ln, conf=0.95)
                names["hosts"].append(h)
            ups = [p for p in inv.parents(g) if p not in ("all", "ungrouped")]
            for p in ups:
                if inv.hosts_of(g) and gname(path, p) != me:
                    F.add(path, me, "in_group", gname(path, p), "group", line=inv.groups[g]["line"], conf=0.95)
            if env and me != env and inv.hosts_of(g) and not any(gname(path, p) != me for p in ups):
                F.add(path, me, "in_group", env, "group", line=inv.groups[g]["line"], conf=0.95)
        names["hosts"] += inv.all_hosts()
    # the plays: what runs where
    on: dict[tuple[str | None, str], set[str]] = defaultdict(set)      # (inventory, group or host) -> parts
    part_scopes: dict[str, list[dict[str, Any]]] = defaultdict(list)    # part -> its variables' scopes
    play_parts: list[tuple[dict[str, Any], list[str], Inventory | None, list[tuple[str, str]]]] = []
    defaults: dict[str, Any] = {}                       # (0.10.1) the roles' defaults: a play's templated hosts
    for r in roles.values():
        for k, v in r.vars.items():
            defaults.setdefault(k, v)
    runtime: set[str] = set()                           # (0.10.4) groups a play makes as it runs (add_host, group_by)
    for p in plays:
        for t in p["tasks"]:
            mod, val = _module(t)
            a = _args(val)
            short_mod = mod.split(".")[-1]
            names_made = a.get("groups") or a.get("group") or a.get("groupname") if short_mod == "add_host" else \
                a.get("key") if short_mod == "group_by" else None
            for g in (names_made if isinstance(names_made, list) else str(names_made or "").split(",")):
                if str(g).strip() and "{{" not in str(g):
                    runtime.add(str(g).strip())
    plays_seen: list[tuple[dict[str, Any], Inventory | None, list[tuple[str, str]], list[str], dict[str, Any]]] = []
    for p in plays:
        here = posixpath.dirname(p["file"])
        play_vars = dict(p["vars"])
        for vf in p["vars_files"]:
            data = _yaml((by_path.get(posixpath.normpath(posixpath.join(here, vf))) or {}).get("text") or "")
            if isinstance(data, dict):
                play_vars.update(data)
        pattern = hosts_pattern(p["pattern"], [play_vars, vfiles.get("group:all", {})], defaults)
        inv = _inventory_for(p["file"], invs, pattern)
        places = [x for x in _places(pattern, inv, named) if not (x[0] == "group" and x[1] in runtime)]
        if not places:
            continue
        groups_vars = [vfiles.get(f"group:{g}", {}) for kind, g in places if kind == "group"] + [vfiles.get("group:all", {})]
        parts, kept = [], {}
        for name in p["roles"]:
            role = _find_role(name, p["file"], roles)
            part = role.part
            if part:
                parts.append(part)
                part_scopes[part] += [play_vars, role.vars, *groups_vars]
                if name in p.get("where", {}):               # (0.10.1) a role kept to one group by its condition
                    g = hosts_pattern(p["where"][name], [play_vars, vfiles.get("group:all", {})], defaults)
                    if "{{" not in g:
                        kept[part] = [("group", g)]
        scopes = [play_vars, *groups_vars]
        for mod, a in _deploys(p["tasks"]):                 # an application the play's own tasks deploy
            src = _resolve(a.get("repo") or a.get("image") or a.get("src") or "", scopes)
            app = re.sub(r"(\.git)?/*$", "", str(src)).rsplit("/", 1)[-1].split(":")[0]
            app = re.sub(r"\.(war|ear|jar|tar\.gz|tgz|zip)$", "", app)
            if app and "{{" not in app and re.fullmatch(r"[A-Za-z][\w.-]{1,80}", app):
                parts.append(app)
                part_scopes[app] += scopes
        for svc in _starts_service(p["tasks"]):            # (0.10.6) a service the play's own tasks start (no
            svc = _resolve(svc, scopes)                     # role: "systemd: name: pricing-svc, state: started"):
            if isinstance(svc, str) and "{{" not in svc and not SYSTEM_SERVICES.match(svc) and \
                    re.fullmatch(r"[A-Za-z][\w.-]{1,80}", svc) and svc not in parts:   # a part on the play's hosts
                parts.append(svc)
                part_scopes[svc] += scopes
        plays_seen.append((p, inv, places, parts, kept))
    # (0.10.4) a role the plays apply to most of the project's groups, starting no service of its own (the container
    # engine, the common settings, the handlers of the other roles' daemons): configuration, not a part of the system
    prefix = _role_prefix(roles)
    groups_of: dict[str, set[str]] = defaultdict(set)
    role_of: dict[str, Role] = {}
    for p, _inv, places, parts, kept in plays_seen:
        for name in p["roles"]:
            role = _find_role(name, p["file"], roles)
            if role.part:
                role_of.setdefault(role.part, role)
        for part in parts:
            groups_of[part] |= {place for kind, place in kept.get(part, places) if kind == "group"}
    every_group = set().union(*groups_of.values()) if groups_of else set()
    everywhere = {part for part, gs in groups_of.items() if part in role_of and len(every_group) >= 4 and
                  len(gs) >= max(EVERYWHERE_MIN, EVERYWHERE_SHARE * len(every_group)) and
                  not role_of[part].deploys and not _own_service(role_of[part], prefix)}
    for part in everywhere:
        part_scopes.pop(part, None)
    for p, inv, places, parts, kept in plays_seen:
        parts = [x for x in parts if x not in everywhere]
        for part in dict.fromkeys(parts):
            names["parts"].append(part)
            for kind, place in kept.get(part, places):
                on[(inv.path if inv else None, place)].add(part)
                for where in placed(inv, kind, place):   # (0.10.6.2) each environment's group
                    F.add(p["file"], part, "runs_on", where, "group" if kind == "group" else "host", pos=p["pos"],
                          conf=0.9)
        play_parts.append((p, list(dict.fromkeys(parts)), inv, places))
    # a script's ad-hoc commands: a service started on a pattern's hosts
    for u, m in adhoc:
        inv = _inventory_for(u["path"], invs, m.group("pattern"))
        a = _args(m.group("args").split("-a", 1)[-1].strip().strip("\"'") if "-a" in m.group("args") else "")
        if m.group("module").split(".")[-1] in ("service", "systemd") and a.get("name") and \
                not SYSTEM_SERVICES.match(str(a["name"])) and str(a.get("state", "")).lower() in ("started", "restarted"):
            for kind, place in _places(m.group("pattern"), inv, named):
                on[(inv.path if inv else None, place)].add(str(a["name"]))
                for where in placed(inv, kind, place):
                    F.add(u["path"], str(a["name"]), "runs_on", where, kind, pos=m.start(), conf=0.85)
                names["parts"].append(str(a["name"]))

    def parts_on(inv: Inventory | None, group: str) -> set[str]:
        return set(on.get((inv.path if inv else None, group), set()))

    def part_files(part: str, variables: bool = False) -> list[tuple[str, Inventory | None]]:
        """The files that speak for a part: its role's, and the files of the plays it is the only part of (templates,
        variables files); with `variables`, the variables files of every play it is in (a variable named after it)."""
        out = []
        for p, parts, inv, _pl in play_parts:
            if part not in parts:
                continue
            here = posixpath.dirname(p["file"])
            for name in p["roles"]:
                role = _find_role(name, p["file"], roles)
                if role.part == part and role.root:
                    out += [(path, inv) for path in by_path if path.startswith(role.root + "/")]
            if variables:
                out += [(posixpath.normpath(posixpath.join(here, vf)), inv) for vf in p["vars_files"]
                        if posixpath.normpath(posixpath.join(here, vf)) in by_path] + [(p["file"], inv)]
            mine = [x for x in parts]
            if len(mine) == 1:                              # the play's own templates and variables files
                for t in p["tasks"]:
                    mod, val = _module(t)
                    a = _args(val)
                    if mod.split(".")[-1] == "template" and a.get("src"):
                        for cand in (posixpath.join(here, str(a["src"])), posixpath.join(here, "templates", str(a["src"]))):
                            if posixpath.normpath(cand) in by_path:
                                out.append((posixpath.normpath(cand), inv))
                out += [(posixpath.normpath(posixpath.join(here, vf)), inv) for vf in p["vars_files"]
                        if posixpath.normpath(posixpath.join(here, vf)) in by_path]
                out.append((p["file"], inv))
        return list(dict.fromkeys(out))

    every_part = sorted({x for _p, parts, _i, _pl in play_parts for x in parts})
    for part in every_part:
        scopes = part_scopes.get(part, [])
        for path, inv in part_files(part):
            text = (by_path.get(path) or {}).get("text") or ""
            lines = text.splitlines()
            if re.search(r"(^|/)(tasks|handlers|meta|molecule|tests?)/", path) and not path.endswith((".j2", ".jinja2")):
                continue                                     # what a task does with a group is an operation
            for m in GROUP_REF.finditer(text):              # another group named: the part reaches what runs there
                g = m.group("q") or m.group("a") or m.group("g")
                if m.group("v"):
                    val = _resolve("{{ %s }}" % m.group("v"), scopes)
                    g = val if isinstance(val, str) and "{{" not in val else None
                if not g or g in ("all", "ungrouped") or (inv and g not in inv.groups and not parts_on(inv, g)):
                    continue
                ln = text.count("\n", 0, m.start()) + 1
                window = "\n".join(lines[max(0, ln - 2):ln + 3])
                if NO_LINK.search("\n".join(lines[max(0, ln - 3):ln - 1])) and (path.endswith((".yml", ".yaml"))):
                    continue                                 # a task's loop (delegate_to, with_items): an operation
                verb = _verb(window, part)
                target = _target(parts_on(inv, g), window, scopes, part)
                if verb and target and target != part:
                    F.add(path, part, verb, target, "part", line=ln)
        # an address in the part's own variables: a host of the inventory
        for scope in scopes:
            for key, value in scope.items() if isinstance(scope, dict) else []:
                if not _norm(key).startswith(_norm(part) + "-"):
                    continue
                for path, _inv in part_files(part, variables=True):
                    text = (by_path.get(path) or {}).get("text") or ""
                    if key not in text:
                        continue
                    flat = str(_resolve(value, scopes))
                    for am in ADDRESS.finditer(flat):
                        host = am.group("host")
                        there: set[str] = set()
                        for inv in invs.values():                # any inventory of the repository names it
                            if host in inv.all_hosts():
                                groups = [g for g in inv.groups if host in inv.hosts_of(g)]
                                there |= set().union(*[parts_on(inv, g) for g in groups] + [parts_on(inv, host)])
                        if not there:
                            continue
                        target = _target(there, key + " " + flat, scopes, part)
                        verb = _verb(key, part) or "calls"
                        if target:
                            pos = text.find(am.group(0), text.find(key))
                            F.add(path, part, verb if verb != "monitors" else "calls", target, "part",
                                  pos=pos if pos >= 0 else text.find(key))
        # a database or a cache on the part's own hosts (DB_HOST localhost): the one of them running there
        places = {(i, pl) for (i, pl), ps in on.items() if part in ps}
        beside = set().union(*[on[k] for k in places]) - {part} if places else set()
        stores = sorted(x for x in beside if STORE_NAME.search(x))
        for path, _inv in part_files(part):
            text = (by_path.get(path) or {}).get("text") or ""
            for m in LOCAL.finditer(text):
                ln = text.count("\n", 0, m.start()) + 1
                line = text.splitlines()[ln - 1] if text else ""
                if not USES.search(line) or NO_LINK.search(line):
                    continue
                target = _target(set(stores), line, scopes, part) or (stores[0] if len(stores) == 1 else None)
                if target:
                    F.add(path, part, "uses", target, "part", line=ln)
    # (0.10.4) the databases a role's tasks make an account or a database in: the role's part uses them (the
    # project's own part of that family, else the family's name: postgresql_db -> postgresql)
    applied = set(names["parts"])
    for role in roles.values():
        if not (role.root and role.part in applied and role.stores):
            continue
        for fam, path, line in role.stores:
            if re.search(DB_SERVER[fam], _norm(role.part)) or _norm(role.part) in ("db", "database") or \
                    any(re.search(DB_SERVER[fam], b) for svc in role.services for b in _service_bases(svc)):
                continue                                   # the database's own role: no client of itself
            same = [x for x in applied if re.search(DB_FAMILY[fam], _norm(x)) and x != role.part]
            F.add(path, role.part, "uses", same[0] if len(same) == 1 else fam, "part", line=line, conf=0.8)
    # (0.10.4) the services a role starts are other names of its part (monit's "check process postfix" is the
    # mail server), when no other role starts one of that name
    starters: dict[str, set[str]] = defaultdict(set)
    for role in roles.values():
        if role.root and role.part in applied:
            for svc in role.services:
                for base in _service_bases(svc):              # (a mail server's postfix is its own, though
                    if base and (not SYSTEM_SERVICES.match(base) or base in ("postfix", "sendmail")) and \
                            base != _norm(role.part):              # a system's mail relay too)
                        starters[base].add(role.part)
    names["aliases"] = {b: next(iter(ps)) for b, ps in starters.items() if len(ps) == 1}
    names = {k: (list(dict.fromkeys(v)) if isinstance(v, list) else v) for k, v in names.items()}
    speaks: dict[str, str] = {}                            # a file's own part: its role's (none for a base role)
    for path in by_path:
        root = next((k for k in sorted(roles, key=len, reverse=True) if not k.startswith("@") and
                     path.startswith(k + "/")), None)
        if root and roles[root].stack:
            continue                                      # (0.10.6) a stack's files: their own tool's (prometheus.yml)
        if root:
            speaks[path] = roles[root].part or ""
        elif path in invs or re.search(r"(^|/)(group|host)_vars/", path) or \
                any(p["file"] == path for p in plays):
            speaks[path] = ""
    names["owners"] = speaks                              # (type: dict, read by understand.run)
    return dict(F.out), names


# --------------------------------------------------------------------------------------------------------------- #
# Kubernetes
# --------------------------------------------------------------------------------------------------------------- #
WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "CronJob", "Job", "Rollout", "DeploymentConfig"}
ADDRESS_VAR = re.compile(r"(ADDR|ADDRESS|HOST|HOSTS|URL|URI|ENDPOINT|ENDPOINTS|SERVER|SERVERS|DSN|BROKERS?|"
                         r"BOOTSTRAP|SERVICE)(_|$)", re.I)
DB_SCHEME = re.compile(r"^(jdbc:)?(postgres(ql)?|mysql|mariadb|sqlserver|oracle|mongodb(\+srv)?|redis|rediss|"
                       r"memcached|cassandra|amqp|amqps|kafka|nats)\b", re.I)


def untemplated(text: str) -> str:
    """(0.10.4) A Jinja-templated YAML file readable as YAML: its control lines out, each expression a word
    (namespace: {{ ns }} -> namespace: tpl), the literal values kept."""
    text = re.sub(r"(?m)^[ \t]*\{%.*?%\}[ \t]*$\n?", "", text or "")
    return re.sub(r"\{\{.*?\}\}", "tpl", text)


def _docs_with_lines(text: str) -> Iterator[tuple[int, Any]]:
    """The YAML documents of a manifest with the line each starts at."""
    offset = 0
    text = untemplated(text) if "{{" in text or "{%" in text else text
    for chunk in re.split(r"(?m)^---\s*$", text):
        data = _yaml(chunk)
        if data is not None:
            yield offset, data
        offset += chunk.count("\n") + 1


def _env_line(text: str, start: int, name: str) -> int:
    lines = text.splitlines()
    for i in range(max(0, start), len(lines)):
        if re.search(r"\b" + re.escape(name) + r"\b", lines[i]):
            for j in range(i, min(i + 3, len(lines))):     # the value's line (name: and value: on two lines)
                if re.search(r"value\s*:|:\s*\S", lines[j]) and j != i or re.search(re.escape(name) + r"\s*[:=]\s*\S",
                                                                                   lines[j]):
                    return j + 1
            return i + 1
    return start + 1


def _host_of(value: str) -> tuple[str, int | None, str] | None:
    """(host, port, scheme) of an address given as a value; None for a value that is no address of another part."""
    v = str(value or "").strip().strip("\"'")
    if not v or re.search(r"[\[\]{}<>$]|\s", v):
        return None                                        # a placeholder, a template, several words
    scheme = ""
    m = re.match(r"^((?:jdbc:)?[a-z][a-z0-9+.-]*)://(?:[^@/\s]*@)?([^:/?#\s]+)(?::(\d+))?", v, re.I)
    if m:
        scheme, host, port = m.group(1).lower(), m.group(2), m.group(3)
    else:
        m = re.match(r"^([A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)*):(\d{2,5})$", v)
        if not m:
            return None
        host, port = m.group(1), m.group(2)
    if host.isupper() or "_" in host:
        return None                                        # a placeholder (FRONTEND_IP_ADDRESS), no host's name
    host = host.lower()
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or re.fullmatch(r"[\d.]+", host):
        return None
    return host.split(".")[0], int(port) if port else None, scheme


def kubernetes(units: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], list[str], dict[str, str]]:
    """The links a repository's manifests state through the workloads' environment ({path: [fact]}, the workloads)."""
    by_path = {u["path"]: u for u in units if u.get("path")}
    workloads: list[dict[str, Any]] = []
    configmaps: dict[str, dict[str, Any]] = {}
    renamed: dict[str, str] = {}                           # (0.10.4) {a workload's name: its application's}
    for u in units:
        path = u["path"] or ""
        if not path.endswith((".yml", ".yaml", ".yml.j2", ".yaml.j2")):
            continue
        text = u["text"] or ""
        for start, d in _docs_with_lines(text):
            if not isinstance(d, dict) or not isinstance(d.get("metadata"), dict):
                continue
            kind, name = d.get("kind"), str(d["metadata"].get("name") or "")
            if name == "tpl":
                continue                                   # (a name only a variable gives)
            labels = {**((d["metadata"].get("labels") or {}) if isinstance(d["metadata"].get("labels"), dict) else {}),
                      **(((((d.get("spec") or {}).get("template") or {}).get("metadata") or {}).get("labels") or {})
                         if isinstance(d.get("spec"), dict) else {})}
            app = str(labels.get("app") or labels.get("app.kubernetes.io/name") or "") if isinstance(labels, dict) else ""
            if kind in WORKLOAD_KINDS and app and app != name and app != "tpl" and \
                    re.fullmatch(re.escape(app) + r"[-_]v?\d+(\.\d+)*|" + re.escape(app) + r"[-_]\w+", name):
                renamed[name] = app                        # (0.10.4) details-v1 of app details: the part details
                name = app
            if kind == "ConfigMap" and isinstance(d.get("data"), dict):
                configmaps.setdefault(name, {"path": path, "start": start, "data": d["data"], "users": set()})
            elif kind in WORKLOAD_KINDS and name:
                spec = d.get("spec") or {}
                tpl = (spec.get("jobTemplate") or {}).get("spec", spec) if kind == "CronJob" else spec
                pod = ((tpl.get("template") or {}).get("spec") or {}) if isinstance(tpl, dict) else {}
                env, env_from = [], []
                for c in (pod.get("containers") or []) + (pod.get("initContainers") or []):
                    if not isinstance(c, dict):
                        continue
                    for e in c.get("env") or []:
                        if isinstance(e, dict) and e.get("name"):
                            ref = ((e.get("valueFrom") or {}).get("configMapKeyRef") or {}) if isinstance(
                                e.get("valueFrom"), dict) else {}
                            env.append((str(e["name"]), e.get("value"), ref.get("name"), ref.get("key")))
                    for ef in c.get("envFrom") or []:
                        if isinstance(ef, dict) and isinstance(ef.get("configMapRef"), dict):
                            env_from.append(str(ef["configMapRef"].get("name") or ""))
                workloads.append({"name": name, "path": path, "start": start, "env": env, "from": env_from})
    if not workloads:
        return {}, [], renamed
    known = {w["name"].lower() for w in workloads}
    for w in workloads:
        for cm in w["from"]:
            if cm in configmaps:
                configmaps[cm]["users"].add(w["name"])
    code = [u for u in units if (u["path"] or "").endswith((".py", ".go", ".js", ".ts", ".java", ".cs", ".rb", ".kt",
                                                             ".properties")) or
            (u["path"] or "").endswith(("application.yml", "application.yaml"))]

    def reads(workload: str, var: str) -> bool | None:
        """Does the workload's own code read the variable? None: no code of it in the repository."""
        mine = [u for u in code if re.search(r"(^|/)" + re.escape(workload.lower()) + r"(/|$)",
                                             (u["path"] or "").lower().replace("-", ""))
                or re.search(r"(^|/)" + re.escape(workload.lower()) + r"(/|$)", (u["path"] or "").lower())]
        if not mine:
            return None
        return any(var in (u["text"] or "") for u in mine)

    F = Facts(by_path)
    for w in workloads:
        items = [(name, value, w["path"], _env_line(by_path[w["path"]]["text"] or "", w["start"], name))
                 for name, value, _cm, _k in w["env"] if value is not None]
        for name, _v, cm, key in w["env"]:
            if cm in configmaps and key in configmaps[cm]["data"]:
                c = configmaps[cm]
                items.append((name, c["data"][key], c["path"], _env_line(by_path[c["path"]]["text"] or "",
                                                                        c["start"], key)))
        for cm in w["from"]:
            c = configmaps.get(cm)
            if not c:
                continue
            for key, value in c["data"].items():
                if len(c["users"]) > 1 and reads(w["name"], key) is False:
                    continue                                # a shared ConfigMap: what this workload's code reads only
                items.append((key, value, c["path"], _env_line(by_path[c["path"]]["text"] or "", c["start"], key)))
        for name, value, path, ln in items:
            got = _host_of(str(value))
            if not got:
                continue
            host, port, scheme = got
            if not (ADDRESS_VAR.search(name) or scheme) or host == w["name"].lower() or host not in known:
                continue                                    # another workload of the repository only (a server's
                #                                             address, a database's URI: the file's own reading)
            store = bool(DB_SCHEME.match(scheme)) or port in (5432, 3306, 27017, 6379, 11211, 1433, 1521, 9042) or \
                re.search(r"(^|_)(DB|DATABASE|REDIS|CACHE|MONGO|SQL)(_|$)", name, re.I)
            F.add(path, w["name"], "uses" if store else "calls", host, "part", line=ln, conf=0.85)
    return dict(F.out), sorted({w["name"] for w in workloads}), renamed


# --------------------------------------------------------------------------------------------------------------- #
# Docker Compose
# --------------------------------------------------------------------------------------------------------------- #
SENDS_KEY = re.compile(r"OTEL_EXPORTER|OTLP|SMTP|MAIL_?RELAY|SMARTHOST", re.I)   # (0.10.5) what is sent to: telemetry,
#                                                                                     mail
COMPOSE_NAME = re.compile(r"(^|/)[\w.-]*(compose|docker-stack)[\w.-]*\.ya?ml$", re.I)   # (0.10.4) a Swarm stack,
#                                                                    an extension's x-compose.yml: the same format
STORE_IMAGE = re.compile(r"(^|/)(mysql|mariadb|postgres|postgis|timescale\w*|mongo|redis|valkey|memcached|cassandra|"
                         r"elasticsearch|opensearch|kafka|rabbitmq|nats|zookeeper|etcd|consul|minio|influxdb|"
                         r"clickhouse|mssql|oracle|couchdb|neo4j)([:@/-]|$)", re.I)


def compose(units: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], list[str], dict[str, str]]:
    """The links a Compose file states between its services: what a service depends on (depends_on, links: a
    database, a cache or a broker is used, another service called) and the addresses of other services in its
    environment ({path: [fact]}, the services, and (0.10.4) the files a service is built from: {path: service}, the
    files of a build context in a folder of its own, whose configuration and code speak for the service)."""
    by_path = {u["path"]: u for u in units if u.get("path")}
    F = Facts(by_path)
    names: list[str] = []
    contexts: dict[str, set[str]] = {}
    aliases: dict[str, str] = {}
    for u in units:
        path = u["path"] or ""
        if not COMPOSE_NAME.search(path):
            continue
        data = _yaml(u["text"] or "")
        services = data.get("services") if isinstance(data, dict) else None
        if not isinstance(services, dict):
            continue
        text = u["text"] or ""
        store = {n for n, v in services.items() if isinstance(v, dict) and
                 (STORE_IMAGE.search(str(v.get("image") or "")) or STORE_NAME.search(str(n)))}

        def line_of(service: str, word: str) -> int:
            m = re.search(r"(?m)^(\s*)" + re.escape(service) + r"\s*:", text)
            if not m:
                return 1
            at = text.find(word, m.end()) if word else -1
            return text.count("\n", 0, at if at >= 0 else m.start()) + 1

        for n, v in services.items():
            if not isinstance(v, dict):
                continue
            n = str(n)
            names.append(n)
            build = v.get("build")
            ctx = build.get("context") if isinstance(build, dict) else build
            mounts = [str(x).split(":", 1)[0] for x in (v.get("volumes") or []) if isinstance(x, str) and ":" in str(x)]
            mounts += [str(x.get("source")) for x in (v.get("volumes") or []) if isinstance(x, dict) and
                       x.get("type") == "bind" and x.get("source")]
            for src in ([ctx] if isinstance(ctx, str) else []) + [m for m in mounts if m.startswith(".")]:
                if not src.strip() or "://" in src or "$" in src:
                    continue
                folder = posixpath.normpath(posixpath.join(posixpath.dirname(path), src.strip()))
                if not any(f == folder or f.startswith(folder + "/") for f in by_path):
                    folder = posixpath.normpath(src.strip())   # (0.10.4) an extension's file, merged with the main
                    #                                            one: its folders are the project's (-f a -f b)
                if folder != "." and not folder.startswith(".."):   # (the repository's root: everybody's)
                    contexts.setdefault(folder, set()).add(n)   # (0.10.4) its build folder, the files it mounts
            nets = v.get("networks")                       # (0.10.4) a network alias is another name of it
            for net in (nets.values() if isinstance(nets, dict) else []):
                for al in ((net or {}).get("aliases") or []) if isinstance(net, dict) else []:
                    al = re.sub(r"\$\{[A-Z0-9_]+:-([^}]+)\}", r"\1", str(al))
                    if al and "$" not in al and al != n:
                        aliases[al] = n
                        aliases.setdefault(al.split(".")[0], n)
            deps = v.get("depends_on") or []
            deps = list(deps) if isinstance(deps, (list, dict)) else []
            links = [str(x).split(":")[0] for x in (v.get("links") or []) if isinstance(x, str)]
            for t in dict.fromkeys([str(x) for x in deps] + links):
                if t in services and t != n:
                    F.add(path, n, "uses" if t in store else "calls", t, "part", line=line_of(n, t), conf=0.8)
            env = v.get("environment") or {}
            pairs = [str(x).split("=", 1) for x in env] if isinstance(env, list) else \
                [[str(k), str(val)] for k, val in env.items()] if isinstance(env, dict) else []
            for kv in pairs:
                if len(kv) != 2:
                    continue
                key, val = kv
                got = _host_of(val.strip())
                host = got[0] if got else (val.strip().lower() if val.strip() in services else None)
                if host is None:                          # (0.10.5) "http://${OTEL_COLLECTOR_HOST}:...": the service
                    ph = re.search(r"\$\{([A-Za-z][A-Za-z0-9_]*?)_(?:HOST|HOSTNAME|ADDR|ADDRESS)\b", val)   # named so
                    named = ph and next((x for x in services if _norm(x) == _norm(ph.group(1).replace("_", "-"))),
                                        None)
                    host = named or None
                if host and host in services and host != n and (ADDRESS_VAR.search(key) or got):
                    F.add(path, n, "uses" if host in store or (got and DB_SCHEME.match(got[2] or "")) else
                          "sends_to" if SENDS_KEY.search(key) else "calls", host, "part", line=line_of(n, key), conf=0.8)
    built: dict[str, str] = {}
    for path in by_path:
        folder = next((k for k in sorted(contexts, key=len, reverse=True) if path == k or path.startswith(k + "/")),
                      None)
        if not folder or COMPOSE_NAME.search(path):
            continue
        who = sorted(contexts[folder])
        named = [x for x in who if _norm(x) == _norm(posixpath.basename(folder))]
        if len(who) == 1 or len(named) == 1:            # (0.10.4) a folder two services use: the one named after it
            built[path] = who[0] if len(who) == 1 else named[0]   # (kibana/ for kibana, not kibana-genkeys)
    built["@aliases"] = aliases                           # (read by facts(): {another name: the service})
    return dict(F.out), list(dict.fromkeys(names)), built


CODE_EXT = {".py": "Python", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".js": "JavaScript", ".ts": "TypeScript",
            ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".rs": "Rust", ".scala": "Scala", ".sh": "shell", ".ps1": "PowerShell",
            ".pl": "Perl", ".tf": "Terraform", ".sql": "SQL"}


def kinds(units: list[dict[str, Any]], declared: dict[str, Any], workloads: list[str], services: list[str]) -> dict:
    """What a repository is, in words (several at once): an Ansible project (its inventories, hosts, groups, playbooks,
    roles), Kubernetes manifests, a Helm chart, a Compose file, Terraform, code by language, scripts."""
    paths = [u["path"] or "" for u in units if u.get("path")]
    langs: Counter = Counter()
    scripts = 0
    for p in paths:
        low = p.lower()
        if re.search(r"(^|/)(roles|group_vars|host_vars|inventor(y|ies)|library|filter_plugins|module_utils|"
                     r"action_plugins|molecule|tests?)/", low) and declared.get("ansible"):
            continue                                       # an Ansible project's own modules and plugins
        ext = "." + low.rsplit(".", 1)[-1] if "." in low.rsplit("/", 1)[-1] else ""
        if ext in CODE_EXT:
            langs[CODE_EXT[ext]] += 1
            scripts += ext in (".sh", ".py", ".ps1", ".pl") and bool(re.search(r"(^|/)(scripts?|bin|tools|cron)/", low))
    out: dict[str, Any] = {"labels": [], "sentences": []}
    a = declared.get("ansible")
    if a:
        out["labels"].append("ansible")
        out["sentences"].append(f"An Ansible project: {a['inventories']} inventor{'y' if a['inventories'] == 1 else 'ies'}"
                                f" ({a['hosts']} hosts in {a['groups']} groups), {a['playbooks']} playbook"
                                f"{'' if a['playbooks'] == 1 else 's'}, {a['roles']} roles"
                                + (f"; what it deploys: {', '.join(declared.get('parts', [])[:12])}"
                                   if declared.get("parts") else "") + ".")
    if workloads:
        out["labels"].append("kubernetes")
        out["sentences"].append(f"Kubernetes manifests: {len(workloads)} workloads ({', '.join(workloads[:12])}).")
    if any(re.search(r"(^|/)Chart\.ya?ml$", p) for p in paths):
        out["labels"].append("helm")
        out["sentences"].append("A Helm chart.")
    if services:
        out["labels"].append("compose")
        out["sentences"].append(f"A Docker Compose file: {len(services)} services ({', '.join(services[:12])}).")
    if langs.get("Terraform"):
        out["labels"].append("terraform")
        out["sentences"].append(f"Terraform: {langs['Terraform']} files.")
    code = [(k, v) for k, v in langs.most_common() if k not in ("Terraform", "SQL")]
    if code:
        out["labels"] += [k.lower() for k, _v in code[:3]]
        out["sentences"].append("Code: " + ", ".join(f"{k} {v} file{'s' if v > 1 else ''}" for k, v in code[:6]) + ".")
    if scripts:
        out["labels"].append("scripts")
        out["sentences"].append(f"Scripts: {scripts} (scripts, bin or tools folders).")
    return out


ENV_TEST = re.compile(r"(^|/)(inventor(?:y|ies))/(?:tests?|testing)(?=/)", re.I)


def test_file(path: str) -> bool:
    """(0.10.6) A file of a repository's tests, fixtures or examples (TEST_DIR): no fact of the System map. (0.10.6.2)
    An inventory's environment named test (inventory/test/hosts) is one of the deployment's environments."""
    return bool(TEST_DIR.search(ENV_TEST.sub(r"\1\2/env", path or "")))


def facts(units: list[dict[str, Any]], label: str | None = None
          ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """The facts a repository states across its files ({path: [fact]}), the names it declares and, in an Ansible
    repository, who speaks in its files ({"owners": {path: a role's part, or "" for nobody}}). (0.10.6) Its tests,
    fixtures and examples left out (test_file)."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    tests = inventories([u for u in units if test_file(u.get("path") or "")])
    named = {g for i in tests.values() for g in i.groups if g not in ("all", "ungrouped")}   # their groups' names
    units = [u for u in units if not test_file(u.get("path") or "")]
    a, names = ansible(units, named, label)
    k, workloads, renamed = kubernetes(units)
    c, services, built = compose(units)
    for src in (a, k, c):
        for path, fs in src.items():
            out[path] += fs
    names = dict(names)
    names["parts"] = list(dict.fromkeys(list(names.get("parts", [])) + workloads + services))
    names.setdefault("aliases", {})                       # (0.10.4) {another name: the part}
    for other, app in renamed.items():                    # (0.10.4) a workload's versioned name: its application
        names["aliases"].setdefault(other, app)
    names.setdefault("owners", {})
    for other, svc in (built.pop("@aliases", None) or {}).items():   # (0.10.4) xmpp.meet.jitsi is prosody
        if other not in names["parts"]:
            names["aliases"].setdefault(other, svc)
    names["built"] = built                                # (0.10.4) {path: the Compose service built from it}
    names["kinds"] = kinds(units, names, workloads, services)
    return dict(out), names
