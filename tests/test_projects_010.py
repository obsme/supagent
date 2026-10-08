"""(0.10) What a repository states across its files: an Ansible project's inventory (hosts in groups), its plays
(what runs where, only the roles that run a service or deploy an application), its templates and variables naming
another group (who reaches whom, and how), an application its tasks deploy, a script's ad-hoc commands; a
Kubernetes workload's environment (an address of another workload, a database's URI, a ConfigMap several workloads
take: only what each one's code reads). The servers and their groups go to the map's server category, a group named
like a part apart from it, the same host in two repositories one server."""

from __future__ import annotations

import pytest

from test_docs_readers import env  # noqa: F401  (the fixture)


def units(files: dict[str, str]) -> list[dict]:
    return [{"ukey": p, "path": p, "kind": "file", "title": p, "text": t, "meta": {}} for p, t in files.items()]


def triples(found: dict) -> set[tuple[str, str, str]]:
    return {(f["subject"], f["verb"], f["obj"]) for fs in found.values() for f in fs}


SHOP = {
    "inventory/hosts": "[edge]\nlb-1\n\n[shop]\napp-[1:2]\n\n[stock]\ndb-1 stock_port=5433\n\n[prod:children]\nedge\nshop\n"
                       "stock\n\n[prod:vars]\nntp_server=10.0.0.1\n",
    "ansible.cfg": "[defaults]\ninventory = inventory/hosts\nhost_key_checking = False\n",
    "site.yml": "- hosts: all\n  roles: [common, acme.firewall]\n\n- hosts: stock\n  roles:\n    - role: stockdb\n\n"
                "- hosts: shop\n  roles: [shopfront]\n\n- hosts: edge\n  roles:\n    - acme.haproxy\n  vars:\n"
                "    haproxy_backends:\n      - address: app-1:8080\n\n- hosts: monitoring\n  roles: [watch]\n",
    "roles/common/tasks/main.yml": "- name: time\n  service: name=chronyd state=started\n- name: motd\n  copy: "
                                   "src=motd dest=/etc/motd\n",
    "roles/stockdb/tasks/main.yml": "- service:\n    name: postgresql\n    state: started\n",
    "roles/shopfront/tasks/main.yml": "- git: repo=https://git.example.com/shop/storefront.git dest=/srv/shop\n"
                                      "- template: src=app.conf.j2 dest=/etc/shop.conf\n",
    "roles/shopfront/templates/app.conf.j2": "# the stock database\n{% for h in groups['stock'] %}\ndb.url = "
                                             "postgresql://{{ h }}:{{ stock_port }}/stock\n{% endfor %}\n",
    "roles/shopfront/templates/iptables.j2": "{% for h in groups['edge'] %}\n-A INPUT -s {{ h }} --dport 8080 -j "
                                             "ACCEPT\n{% endfor %}\n",
    "roles/watch/tasks/main.yml": "- service: name=nagios state=started\n",
}


def test_an_ansible_project_read_across_its_files(ctx):
    from supagent.knowledge.projects import facts

    found, names = facts(units(SHOP))
    t = triples(found)
    # the inventory: every host in its groups, a child group's hosts in its parent's; a settings file is no inventory
    assert {("app-1", "in_group", "shop"), ("app-2", "in_group", "shop"), ("db-1", "in_group", "prod"),
            ("shop", "in_group", "prod")} <= t
    assert not any(s == "inventory" or o == "defaults" for s, _v, o in t)
    # the plays: the roles that run a service or deploy an application, where they run (a namespace dropped)
    assert {("stockdb", "runs_on", "stock"), ("shopfront", "runs_on", "shop"), ("haproxy", "runs_on", "edge")} <= t
    assert not any(s in ("common", "firewall", "acme.firewall") for s, v, _o in t if v == "runs_on")
    # the application its tasks deploy is the role's (named by the role)
    # a template naming another group: a database is used; a firewall's rule is no link
    assert ("shopfront", "uses", "stockdb") in t
    assert not any(s == "shopfront" and o == "haproxy" for s, _v, o in t)
    # an address in a part's own variables, a host of the inventory: the part runs there
    assert ("haproxy", "calls", "shopfront") in t
    assert {"stockdb", "shopfront", "haproxy"} <= set(names["parts"]) and "app-2" in names["hosts"]
    # each fact with its file and line
    f = next(f for fs in found.values() for f in fs if f["verb"] == "uses")
    assert "groups['stock']" in f["quote"] and f["line"] == 2


def test_a_group_read_by_its_port_an_app_deployed_by_a_play_and_a_script(ctx):
    from supagent.knowledge.projects import facts

    files = {
        "hosts": "[pg]\npg-1\n\n[lb]\nlb-1\n\n[api]\napi-1\napi-2\n",
        "lb.yml": "- hosts: lb\n  roles: [acme.haproxy]\n",
        "pg.yml": "- hosts: pg\n  roles: [acme.postgresql, acme.pgbouncer, acme.node_exporter]\n",
        "api.yml": "- hosts: api\n  vars:\n    repo: https://git.example.com/team/orders-api.git\n  tasks:\n"
                   "    - git:\n        repo: '{{ repo }}'\n        dest: /opt/api\n",
        "roles/haproxy/templates/haproxy.cfg.j2": "backend db\n{% for h in groups['pg'] %}\n  server {{ h }} "
                                                  "{{ h }}:{{ pgbouncer_port }} check\n{% endfor %}\n",
        "ops/restart.sh": "#!/bin/sh\nansible api -i hosts -b -m service -a \"name=orders-worker state=restarted\"\n",
    }
    found, _names = facts(units(files))
    t = triples(found)
    assert ("haproxy", "calls", "pgbouncer") in t and ("haproxy", "calls", "postgresql") not in t
    assert ("orders-api", "runs_on", "api") in t                       # named by its repository
    assert ("orders-worker", "runs_on", "api") in t                    # a script's command
    assert not any(s == "node_exporter" for s, _v, _o in t) or ("node_exporter", "runs_on", "pg") in t


def test_a_monitoring_part_and_an_operation_loop(ctx):
    from supagent.knowledge.projects import facts

    files = {
        "hosts": "[web]\nw1\n\n[mon]\nm1\n",
        "site.yml": "- hosts: web\n  roles: [web]\n- hosts: mon\n  roles: [checks]\n",
        "roles/web/tasks/main.yml": "- service: name=httpd state=started\n- name: out of the pool\n  command: drain\n"
                                    "  delegate_to: '{{ item }}'\n  with_items: \"{{ groups['mon'] }}\"\n",
        "roles/checks/tasks/main.yml": "- service: name=icinga2 state=started\n",
        "roles/checks/templates/hosts.conf.j2": "{% for h in groups['web'] %}\nobject Host \"{{ h }}\" { check_command "
                                                "= \"http\" }\n{% endfor %}\n",
    }
    t = triples(facts(units(files))[0])
    assert ("checks", "monitors", "web") in t
    assert not any(s == "web" and o == "checks" for s, _v, o in t)    # a task's loop: an operation, no link


def test_a_database_on_the_same_host_and_a_shipper(ctx):
    from supagent.knowledge.projects import facts

    files = {
        "hosts": "[blog]\nb1\n",
        "logs/hosts": "[logs]\nl1\n",
        "site.yml": "- hosts: all\n  roles: [mysql, blog]\n",
        "logs/site.yml": "- hosts: logs\n  roles: [acme.logstash, acme.opensearch]\n",
        "ship.yml": "- hosts: blog\n  roles: [acme.filebeat]\n  vars:\n    filebeat_output_hosts: ['l1:5044']\n",
        "roles/mysql/tasks/main.yml": "- service: name=mysqld state=started\n",
        "roles/blog/tasks/main.yml": "- unarchive: src=https://example.com/blog.tar.gz dest=/srv\n",
        "roles/blog/templates/config.php": "define('DB_HOST', 'localhost');\ndefine('DB_NAME', 'blog');\n",
    }
    t = triples(facts(units(files))[0])
    assert ("blog", "uses", "mysql") in t                              # localhost: the database beside it
    assert ("filebeat", "sends_to", "logstash") in t                   # the beats port of a host of the other inventory
    assert ("mysql", "runs_on", "b1") in t                             # "all": the inventory's hosts


def test_kubernetes_workloads_and_their_shared_configmap(ctx):
    from supagent.knowledge.projects import facts

    files = {
        "k8s/config.yaml": "apiVersion: v1\nkind: ConfigMap\nmetadata: {name: apis}\ndata:\n  PRICES_ADDR: prices:8080\n"
                           "  STOCK_ADDR: stock:8080\n---\napiVersion: v1\nkind: ConfigMap\nmetadata: {name: db}\ndata:\n"
                           "  DB_URI: postgresql://shop:***@orders-db:5432/orders\n  POSTGRES_PASSWORD: ***\n",
        "k8s/web.yaml": "# Licensed under the Apache License: http://www.apache.org/licenses/LICENSE-2.0\napiVersion: apps/v1\n"
                        "kind: Deployment\nmetadata: {name: web}\nspec:\n  template:\n    spec:\n      containers:\n"
                        "        - name: web\n          envFrom: [{configMapRef: {name: apis}}]\n          env:\n"
                        "            - name: CART_SERVICE_ADDR\n              value: \"cart:7070\"\n"
                        "            - name: PUBLIC_HOST\n              value: SHOP_PUBLIC_HOSTNAME:443\n",
        "k8s/checkout.yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: checkout}\nspec:\n  template:\n"
                             "    spec:\n      containers:\n        - name: c\n          envFrom:\n"
                             "            - configMapRef: {name: apis}\n            - configMapRef: {name: db}\n",
        "k8s/orders-db.yaml": "apiVersion: apps/v1\nkind: StatefulSet\nmetadata: {name: orders-db}\n",
        "k8s/cart.yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: cart}\n---\napiVersion: apps/v1\n"
                         "kind: Deployment\nmetadata: {name: prices}\n---\napiVersion: apps/v1\nkind: Deployment\n"
                         "metadata: {name: stock}\n---\napiVersion: v1\nkind: ConfigMap\nmetadata: {name: ext}\n"
                         "data:\n  RATES_ADDR: rates.example.com:443\n",
        "src/web/main.py": "import os\nPRICES = os.environ['PRICES_ADDR']\nSTOCK = os.environ['STOCK_ADDR']\n",
        "src/checkout/main.go": "var prices = os.Getenv(\"PRICES_ADDR\")\nvar dsn = os.Getenv(\"DB_URI\")\n",
    }
    t = triples(facts(units(files))[0])
    assert {("web", "calls", "cart"), ("web", "calls", "prices"), ("web", "calls", "stock"),
            ("checkout", "calls", "prices"), ("checkout", "uses", "orders-db")} <= t
    assert ("checkout", "calls", "stock") not in t                    # shared, and its code does not read it
    assert not any(o.startswith("rates") for _s, _v, o in t)          # no workload of the repository: not read here
    assert not any("shop-public" in o or "apache" in o for _s, _v, o in t)   # a placeholder, a license


def test_masked_secrets_stay_yaml(ctx):
    from supagent.knowledge.projects import _yaml

    assert _yaml("a:\n  password: ***\n  l: [x, ***]\n  m: {p: ***}\n") == {
        "a": {"password": "***", "l": ["x", "***"], "m": {"p": "***"}}}


def test_ansible_files_without_an_extension_are_read(ctx):
    from supagent.knowledge.docs import wanted_file

    for path in ("hosts", "inventory", "inventories/prod/hosts", "hosts.example", "inventory-staging",
                 "group_vars/all", "group_vars/webservers", "host_vars/db-1", "group_vars/all/vault"):
        assert wanted_file(path, "docs"), path
    for path in ("roles/x/files/secret", "bin/run", ".env"):
        assert not wanted_file(path, "code"), path


def test_the_secrets_of_configuration_are_masked_however_short(ctx):
    from supagent.knowledge.docs import mask_secrets

    for text, masked in [("upassword: abc", "upassword: ***"), ('auth_pass: "1ce24b6e"', "auth_pass: ***"),
                         ("mongo_admin_pass: 123456", "mongo_admin_pass: ***"),
                         ("#ansible_ssh_pass='pw-of-mine'  # a comment", "#ansible_ssh_pass=***  # a comment"),
                         ('-a "name=app host=% password=12345 priv=*.*:ALL"', '-a "name=app host=% password=*** '
                                                                              'priv=*.*:ALL"'),
                         ("app_secrets:\n  dev: 0f1e2d3c4b5a\n  prod: 9a8b7c6d5e4f\nother: 1",
                          "app_secrets:\n  dev: ***\n  prod: ***\nother: 1")]:
        assert mask_secrets(text)[0] == masked, text
    for kept in ("passenger_app_root: /opt/app", "ssl_key_file: site.p8", "password: str", "token = get_token()",
                 'db_password: ""', "bypass_cache: true", "secretName: tls", "password_min_length: 12",
                 "db = connect(host=h, password=PGPW)"):
        assert mask_secrets(kept)[0] == kept, kept


def test_a_license_address_in_a_comment_is_no_call(env):  # noqa: F811
    from supagent.knowledge.understand import Names, discover, facts_of

    text = ("# Licensed under the Apache License, Version 2.0: http://www.apache.org/licenses/LICENSE-2.0\n"
            "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\n")
    u = {"ukey": "k8s/web.yaml", "path": "k8s/web.yaml", "kind": "file", "title": "", "text": text, "meta": {}}
    u["found"] = discover(u)
    assert not [f for f in facts_of(u, "web", Names(), {}) if f["verb"] == "calls"]


@pytest.fixture()
def two_inventories(env):  # noqa: F811
    """Two repositories of Ansible: the same database host in both, a group named like a part."""
    from superset.extensions import db

    from supagent.models import Doc

    env["categories.custom"] = ["server"]
    repos = {
        "shop-deploy": {"hosts": "[web]\nweb-1\n\n[db]\ndb-01.example.net\n",
                        "site.yml": "- hosts: web\n  roles: [web]\n- hosts: db\n  roles: [acme.postgresql]\n",
                        "roles/web/tasks/main.yml": "- service: name=nginx state=started\n"},
        "billing-deploy": {"inventory": "[billing]\nbill-1\n\n[databases]\ndb-01.example.net\n",
                           "site.yml": "- hosts: billing\n  roles: [acme.billing]\n"},
    }
    docs = []
    for repo, files in repos.items():
        content, pages, at = [], [], 0
        for path, text in files.items():
            block = f"# {path}\n{text}"
            if content:
                at += 2
            pages.append({"url": f"https://git.example.com/projects/P/repos/{repo}/browse/{path}", "title": path,
                          "chars": len(block), "at": at, "path": path, "commit": "c1"})
            content.append(block)
            at += len(block)
        docs.append(Doc(kind="url", url=f"https://git.example.com/projects/P/repos/{repo}/browse", status="ok",
                        enabled=True, content="\n\n".join(content), pages=pages))
    db.session.add_all(docs)
    db.session.commit()
    yield docs


def test_servers_grouped_in_the_map_and_one_host_in_two_repositories(two_inventories):
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet, Link

    U.run(reason="test")
    propose()
    vals = {f.value: f for f in db.session.query(Facet).filter(Facet.source == "docs")}
    assert vals["web-1"].facet == "server" and vals["db-01.example.net"].facet == "server"
    assert vals["web"].facet == "application" and vals["web (group)"].facet == "server"   # two values
    host = vals["db-01.example.net"]
    parents = {x.b_ref for x in db.session.query(Link).filter(Link.a_ref == f"facet:{host.id}",
                                                              Link.kind == "part_of")}
    assert parents == {f"facet:{vals['db'].id}", f"facet:{vals['databases'].id}"}           # one server, two groups
    runs = {(x.a_ref, x.b_ref) for x in db.session.query(Link).filter(Link.kind == "runs_on")}
    assert (f"facet:{vals['web'].id}", f"facet:{vals['web (group)'].id}") in runs


def test_a_template_reads_as_what_it_renders_and_operations_are_no_link(ctx):
    from supagent.knowledge.docs import wanted_file
    from supagent.knowledge.projects import facts
    from supagent.knowledge.understand import lang_of

    assert (lang_of("roles/x/templates/app.yaml.j2"), lang_of("roles/x/templates/app.conf.j2"),
            lang_of("roles/x/templates/settings.py.j2")) == ("yaml", "conf", "python")
    assert wanted_file("ansible/inventory/multinode", "docs") and wanted_file("inventories/prod/web", "docs")
    files = {
        "inventory/multinode": "[cache]\nc1\n\n[api]\na1\n\n[monitor]\nm1\n",
        "site.yml": "- hosts: cache\n  roles: [cache]\n- hosts: api\n  roles: [api]\n- hosts: monitor\n"
                    "  roles: [prometheus]\n",
        "roles/cache/handlers/main.yml": "- name: start\n  acme_container:\n    action: start\n    name: cache\n"
                                         "    image: registry.example.net/cache:1\n",
        "roles/api/tasks/main.yml": "- name: start\n  acme_container:\n    name: api\n    image: registry.example.net/api:2\n"
                                    "- name: warm the caches\n  command: warm {{ item }}\n"
                                    "  with_items: \"{{ groups['cache'] }}\"\n",
        "roles/api/templates/api.conf.j2": "cache_servers = {% for h in groups['cache'] %}{{ h }}:11211{% endfor %}\n",
        "roles/prometheus/tasks/main.yml": "- service: name=prometheus state=started\n",
        "roles/prometheus/templates/prometheus.yml.j2": "{% for h in groups['api'] %}\n  - {{ h }}:9100\n{% endfor %}\n",
    }
    found, names = facts(units(files))
    t = triples(found)
    assert {("cache", "runs_on", "cache"), ("api", "uses", "cache"), ("prometheus", "monitors", "api"),
            ("c1", "in_group", "cache")} <= t                     # containers are parts; a cache is used
    assert sum(1 for s, v, o in t if (s, o) == ("api", "cache")) == 1   # the task's loop added nothing
    assert names["owners"]["roles/api/templates/api.conf.j2"] == "api" and names["owners"]["site.yml"] == ""


def test_a_server_group_and_a_part_of_the_same_name_have_their_own_pages(two_inventories):
    from supagent.knowledge import understand as U
    from supagent.knowledge.context_docs import pages

    U.run(reason="test")
    by_title = {p["title"]: p["content"] for p in pages()}
    group = by_title.get("Server group: web (shop-deploy)", "")
    assert "web-1" in group and "Read in: shop-deploy" in group      # the repository, a name used twice
    part = by_title.get("Part: web (shop-deploy)", "")
    assert "is one of its servers" not in part                       # the group's servers stay on the group's page


def test_a_compose_files_services_and_their_links(ctx):
    from supagent.knowledge.projects import facts

    files = {"compose.yaml": "services:\n  db:\n    image: postgres:16\n  cache:\n    image: valkey/valkey:8\n"
                             "  api:\n    build: api\n    depends_on:\n      db:\n        condition: service_healthy\n"
                             "    environment:\n      - CACHE_URL=redis://cache:6379/0\n      - PUBLIC_URL=https://shop.example\n"
                             "  web:\n    image: nginx\n    depends_on: [api]\n  worker:\n    build: worker\n"
                             "    environment:\n      QUEUE_HOST: cache\n"}
    found, names = facts(units(files))
    t = triples(found)
    assert {("api", "uses", "db"), ("api", "uses", "cache"), ("web", "calls", "api"), ("worker", "uses", "cache")} <= t
    assert not any(o.startswith("shop") for _s, _v, o in t)          # an address outside the file: not a service
    assert {"db", "api", "web", "worker"} <= set(names["parts"])


def test_what_a_repository_is(ctx):
    from supagent.knowledge.projects import facts

    _f, ansible = facts(units(SHOP))
    k = ansible["kinds"]
    assert "ansible" in k["labels"] and k["sentences"][0].startswith("An Ansible project: 1 inventory (4 hosts in 4 groups)")
    # not Ansible: a Kubernetes repository with RBAC roles, a system's hosts file, a Python package named inventory
    other = {"deploy/roles/reader.yaml": "apiVersion: rbac.authorization.k8s.io/v1\nkind: Role\nmetadata: {name: r}\n",
             "deploy/app.yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: shop}\n",
             "docker/hosts": "127.0.0.1 localhost\n10.0.0.5 db.internal db\n",
             "inventory/__init__.py": "from .stock import Stock\n", "inventory/stock.py": "class Stock: pass\n",
             "scripts/backup.sh": "#!/bin/sh\npg_dump shop > /tmp/x\n"}
    found, names = facts(units(other))
    k = names["kinds"]
    assert "ansible" not in k["labels"] and not names["owners"] and not any(
        f["verb"] == "in_group" for fs in found.values() for f in fs)
    assert {"kubernetes", "python", "scripts"} <= set(k["labels"])


def test_a_nested_role_is_judged_by_its_tasks(ctx):
    from supagent.knowledge.projects import facts

    files = {"inventory/hosts.ini": "[cp]\nc1\n\n[nodes]\nn1\n",
             "cluster.yml": "- hosts: cp\n  roles:\n    - { role: platform/control-plane }\n    - { role: platform/labels }\n"
                            "- hosts: nodes\n  roles: [platform/agent]\n",
             "roles/platform/control-plane/tasks/main.yml": "- service: name=apiserver state=started\n",
             "roles/platform/labels/tasks/main.yml": "- command: label-nodes\n",
             "roles/platform/agent/tasks/main.yml": "- service: name=agent state=started\n",
             "roles/platform/agent/templates/lb.conf.j2": "upstream api {\n{% for h in groups['cp'] %}\n  server {{ h }}:6443;"
                                                          "\n{% endfor %}\n}\n"}
    t = triples(facts(units(files))[0])
    assert {("control-plane", "runs_on", "cp"), ("agent", "runs_on", "nodes"), ("agent", "calls", "control-plane")} <= t
    assert not any(s == "labels" for s, _v, _o in t)                 # a role without a service: no part
