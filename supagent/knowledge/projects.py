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

CONFIDENCE = 0.85
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
CONFIG_SUFFIX = re.compile(r"[_-](users|user|databases|database|dbs|schemas|privs|privileges|extensions|config|"
                           r"configure|configuration|settings|tuning|maintenance|index[_-]maintenance|setup|install|"
                           r"vars|defaults|common|repo|repository)$", re.I)
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


MASKED = re.compile(r"(?m)(:[ \t]+|^[ \t]*-[ \t]+|[\[,][ \t]*)\*\*\*(?=[ \t]*(?:#.*)?$|[ \t]*[,}\]])")


def yaml_text(text: str) -> str:
    """A text whose masked secrets (password: ***) stay a value for YAML (*** is an alias there)."""
    return MASKED.sub(r'\1"***"', text or "")


def _yaml(text: str) -> Any:
    text = yaml_text(text)
    try:
        import yaml

        class Loader(yaml.SafeLoader):                    # Ansible's !vault and !unsafe values: kept as text
            pass

        Loader.add_constructor(None, lambda loader, node: getattr(node, "value", None))
        return yaml.load(text, Loader=Loader)             # noqa: S506 (a SafeLoader)
    except Exception:  # pylint: disable=broad-except   (a template, or not YAML)
        return None


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


def inventories(units: list[dict[str, Any]]) -> dict[str, Inventory]:
    out = {}
    for u in units:
        path = u["path"] or ""
        low = path.lower()
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
        m = re.search(r"(?:^|/)(group|host)_vars/([^/]+?)(?:\.ya?ml)?(?:/[^/]+?)?$", path)
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

    @property
    def part(self) -> str | None:
        """The part this role is, or None (it configures the system or installs a language)."""
        short = _short(self.name)
        n = _norm(short)
        if self.root is not None and self.tasks:           # its tasks tell
            own = [s for s in self.services if not SYSTEM_SERVICES.match(s)]
            return short if (own or self.deploys) and not n.startswith(("base-", "common")) else None
        if n in BASE_ROLES or n.startswith("base-") or CONFIG_SUFFIX.search(n) or \
                any(n.startswith(lang + "-") for lang in LANGUAGES):
            return None
        return short


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
        if rest.startswith(("defaults/", "vars/")) and rest.endswith((".yml", ".yaml")):
            data = _yaml(by_path[path]["text"] or "")
            if isinstance(data, dict):
                r.vars.update(data)
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
        roles = []
        for r in p.get("roles") or []:
            name = r if not isinstance(r, dict) else (r.get("role") or r.get("name"))
            if name:
                roles.append(str(name))
        tasks = []
        for key in ("pre_tasks", "tasks", "post_tasks", "handlers"):
            tasks += list(_tasks(p.get(key)))
        for t in tasks:
            mod, val = _module(t)
            if mod.endswith(("include_role", "import_role")) and isinstance(val, dict) and val.get("name"):
                roles.append(str(val["name"]))
        out.append({"file": u["path"], "pos": pos, "pattern": pattern, "roles": list(dict.fromkeys(roles)),
                    "tasks": tasks, "vars": p.get("vars") if isinstance(p.get("vars"), dict) else {},
                    "vars_files": [str(x) for x in (p.get("vars_files") or []) if isinstance(x, str)]})
    return out


def _places(pattern: str, inv: Inventory | None) -> list[tuple[str, str]]:
    """Where a play's pattern points: [("group", name) | ("host", name)]; all the hosts for "all"."""
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
        elif not inv or not inv.groups:
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


def ansible(units: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    """The facts of an Ansible repository ({path: [fact]}) and the names it declares ({"parts", "hosts", "groups"})."""
    by_path = {u["path"]: u for u in units if u.get("path")}
    invs = inventories(units)
    roles = _roles(units, by_path)
    plays = [p for u in units if (u["path"] or "").endswith((".yml", ".yaml")) and "roles/" not in (u["path"] or "")
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
    # the inventories: every host in its groups (a child group's hosts in its parents' too)
    for path, inv in invs.items():
        for g in inv.groups:
            if g in ("all", "ungrouped"):
                continue
            names["groups"].append(g)
            for h, ln in inv.hosts_of(g).items():
                F.add(path, h, "in_group", g, "group", line=ln, conf=0.95)
                names["hosts"].append(h)
            for p in inv.parents(g):
                if p not in ("all", "ungrouped") and inv.hosts_of(g):
                    F.add(path, g, "in_group", p, "group", line=inv.groups[g]["line"], conf=0.95)
        names["hosts"] += inv.all_hosts()
    # the plays: what runs where
    on: dict[tuple[str | None, str], set[str]] = defaultdict(set)      # (inventory, group or host) -> parts
    part_scopes: dict[str, list[dict[str, Any]]] = defaultdict(list)    # part -> its variables' scopes
    play_parts: list[tuple[dict[str, Any], list[str], Inventory | None, list[tuple[str, str]]]] = []
    for p in plays:
        inv = _inventory_for(p["file"], invs, p["pattern"])
        places = _places(p["pattern"], inv)
        if not places:
            continue
        here = posixpath.dirname(p["file"])
        play_vars = dict(p["vars"])
        for vf in p["vars_files"]:
            data = _yaml((by_path.get(posixpath.normpath(posixpath.join(here, vf))) or {}).get("text") or "")
            if isinstance(data, dict):
                play_vars.update(data)
        groups_vars = [vfiles.get(f"group:{g}", {}) for kind, g in places if kind == "group"] + [vfiles.get("group:all", {})]
        parts = []
        for name in p["roles"]:
            role = _find_role(name, p["file"], roles)
            part = role.part
            if part:
                parts.append(part)
                part_scopes[part] += [play_vars, role.vars, *groups_vars]
        scopes = [play_vars, *groups_vars]
        for mod, a in _deploys(p["tasks"]):                 # an application the play's own tasks deploy
            src = _resolve(a.get("repo") or a.get("image") or a.get("src") or "", scopes)
            app = re.sub(r"(\.git)?/*$", "", str(src)).rsplit("/", 1)[-1].split(":")[0]
            app = re.sub(r"\.(war|ear|jar|tar\.gz|tgz|zip)$", "", app)
            if app and "{{" not in app and re.fullmatch(r"[A-Za-z][\w.-]{1,80}", app):
                parts.append(app)
                part_scopes[app] += scopes
        for part in dict.fromkeys(parts):
            names["parts"].append(part)
            for kind, place in places:
                on[(inv.path if inv else None, place)].add(part)
                F.add(p["file"], part, "runs_on", place, "group" if kind == "group" else "host", pos=p["pos"],
                      conf=0.9)
        play_parts.append((p, list(dict.fromkeys(parts)), inv, places))
    # a script's ad-hoc commands: a service started on a pattern's hosts
    for u, m in adhoc:
        inv = _inventory_for(u["path"], invs, m.group("pattern"))
        a = _args(m.group("args").split("-a", 1)[-1].strip().strip("\"'") if "-a" in m.group("args") else "")
        if m.group("module").split(".")[-1] in ("service", "systemd") and a.get("name") and \
                not SYSTEM_SERVICES.match(str(a["name"])) and str(a.get("state", "")).lower() in ("started", "restarted"):
            for kind, place in _places(m.group("pattern"), inv):
                on[(inv.path if inv else None, place)].add(str(a["name"]))
                F.add(u["path"], str(a["name"]), "runs_on", place, kind, pos=m.start(), conf=0.85)
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
    names = {k: (list(dict.fromkeys(v)) if isinstance(v, list) else v) for k, v in names.items()}
    speaks: dict[str, str] = {}                            # a file's own part: its role's (none for a base role)
    for path in by_path:
        root = next((k for k in sorted(roles, key=len, reverse=True) if not k.startswith("@") and
                     path.startswith(k + "/")), None)
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


def _docs_with_lines(text: str) -> Iterator[tuple[int, Any]]:
    """The YAML documents of a manifest with the line each starts at."""
    offset = 0
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


def kubernetes(units: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """The links a repository's manifests state through the workloads' environment ({path: [fact]}, the workloads)."""
    by_path = {u["path"]: u for u in units if u.get("path")}
    workloads: list[dict[str, Any]] = []
    configmaps: dict[str, dict[str, Any]] = {}
    for u in units:
        path = u["path"] or ""
        if not path.endswith((".yml", ".yaml")) or "{{" in (u["text"] or "")[:2000]:
            continue
        text = u["text"] or ""
        for start, d in _docs_with_lines(text):
            if not isinstance(d, dict) or not isinstance(d.get("metadata"), dict):
                continue
            kind, name = d.get("kind"), str(d["metadata"].get("name") or "")
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
        return {}, []
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
    return dict(F.out), sorted({w["name"] for w in workloads})


# --------------------------------------------------------------------------------------------------------------- #
# Docker Compose
# --------------------------------------------------------------------------------------------------------------- #
COMPOSE_NAME = re.compile(r"(^|/)(docker-)?compose([._-][\w.-]*)?\.ya?ml$", re.I)
STORE_IMAGE = re.compile(r"(^|/)(mysql|mariadb|postgres|postgis|timescale\w*|mongo|redis|valkey|memcached|cassandra|"
                         r"elasticsearch|opensearch|kafka|rabbitmq|nats|zookeeper|etcd|consul|minio|influxdb|"
                         r"clickhouse|mssql|oracle|couchdb|neo4j)([:@/-]|$)", re.I)


def compose(units: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """The links a Compose file states between its services: what a service depends on (depends_on, links: a
    database, a cache or a broker is used, another service called) and the addresses of other services in its
    environment ({path: [fact]}, the services)."""
    by_path = {u["path"]: u for u in units if u.get("path")}
    F = Facts(by_path)
    names: list[str] = []
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
                if host and host in services and host != n and (ADDRESS_VAR.search(key) or got):
                    F.add(path, n, "uses" if host in store or (got and DB_SCHEME.match(got[2] or "")) else "calls",
                          host, "part", line=line_of(n, key), conf=0.8)
    return dict(F.out), list(dict.fromkeys(names))


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


def facts(units: list[dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """The facts a repository states across its files ({path: [fact]}), the names it declares and, in an Ansible
    repository, who speaks in its files ({"owners": {path: a role's part, or "" for nobody}})."""
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    a, names = ansible(units)
    k, workloads = kubernetes(units)
    c, services = compose(units)
    for src in (a, k, c):
        for path, fs in src.items():
            out[path] += fs
    names = dict(names)
    names["parts"] = list(dict.fromkeys(list(names.get("parts", [])) + workloads + services))
    names.setdefault("owners", {})
    names["kinds"] = kinds(units, names, workloads, services)
    return dict(out), names
