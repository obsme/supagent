"""(0.10.9.3) The parts an Ansible repository states, read the way its authors wrote it: a role installed from Ansible
Galaxy into roles/ by its full name (namespace.name), a role applied as another part's user (its content), the
systemd units, modules and jobs of other software, the helper units a play starts, the system's own daemons; a Compose
file that runs one product's containers (each named after the product) is that product."""

from __future__ import annotations

import pytest


def _units(files):
    return [{"ukey": p, "path": p, "kind": "file", "title": p, "text": t, "meta": {}} for p, t in files.items()]


def _parts(found):
    return {f["subject"] for fs in found.values() for f in fs if f["verb"] == "runs_on"}


def test_a_role_installed_from_galaxy_is_read_from_its_own_folder(ctx):
    from supagent.knowledge.projects import facts

    files = {"hosts": "[app]\napp-1\n",
             "site.yml": "- hosts: app\n  roles: [acme.shop-procstat, acme.deploy-key, shopfront]\n",
             "roles/acme.shop-procstat/tasks/main.yml": "- template: src=procstat.conf.j2 "
                                                        "dest=/etc/telegraf/telegraf.d/procstat.conf\n",
             "roles/acme.deploy-key/tasks/main.yml": "- copy: src=id_ed25519 dest=/root/.ssh/id_ed25519\n",
             "roles/shopfront/tasks/main.yml": "- service: name=shopfront state=started\n"}
    assert _parts(facts(_units(files))[0]) == {"shopfront"}


def test_roles_applied_as_another_parts_user_and_its_units_modules_and_jobs_are_no_parts(ctx):
    from supagent.knowledge.projects import facts

    files = {"hosts": "[app]\napp-1\n",
             "site.yml": "- hosts: app\n  roles:\n    - vendor.shopfront\n"
                         "    - role: acme.shop-tours\n      become: true\n      become_user: shopfront\n"
                         "    - acme.shopfront_systemd\n    - acme.ansible_nginx_upload_module\n"
                         "    - acme.catalog-importer\n    - acme.price_auto_lint\n    - acme.ledger\n"}
    assert _parts(facts(_units(files))[0]) == {"shopfront", "ledger"}
    files["site.yml"] += "    - role: shop-worker\n      become: true\n      become_user: shopfront\n"
    files["roles/shop-worker/tasks/main.yml"] = "- service: name=shop-worker state=started\n"
    assert _parts(facts(_units(files))[0]) == {"shopfront", "ledger", "shop-worker"}   # a worker it starts: a part


def test_the_systems_own_daemons_and_a_plays_helper_units_are_no_parts(ctx):
    from supagent.knowledge.projects import facts

    files = {"hosts": "[app]\napp-1\n",
             "site.yml": "- hosts: app\n  tasks:\n"
                         "    - systemd: name=require-autofs.service state=started\n"
                         "    - systemd: name=pricing-svc.service state=started\n"
                         "  roles: [automount, perfstat]\n",
             "roles/automount/tasks/main.yml": "- service: name=autofs state=started\n",
             "roles/perfstat/tasks/main.yml": "- service: name=atop state=started\n"}
    assert _parts(facts(_units(files))[0]) == {"pricing-svc"}


@pytest.mark.parametrize("services,whole", [
    (["tick-web", "tick-worker", "tick-postgresql", "tick-nginx"], "tick"),
    (["shop-console-api", "shop-console-ui", "shop-console-db"], "shop-console"),
    (["web_1", "web_2", "web_3"], "web"),
    (["fare-calc", "fare-rules-loader", "ticket-checkout"], None),    # services of several products
    (["api", "worker", "db"], None),
    (["tick-web", "tick-worker"], None),                              # two: not enough to tell
    (["acme-orders", "acme-payments", "acme-shipping"], None),         # a company's several products
    (["acme-orders-api", "acme-orders-db", "acme-payments-api", "acme-payments-db"], None),
    (["app-web", "app-web-2", "app-worker"], "app"),
])
def test_a_compose_file_of_one_products_containers(services, whole):
    from supagent.knowledge.projects import stack_name

    assert stack_name(services) == whole


def test_the_products_containers_are_the_product(ctx):
    from supagent.knowledge.projects import compose

    text = ("services:\n  tick-web:\n    image: x/tick:6\n    depends_on: [tick-postgresql, tick-redis]\n"
            "  tick-worker:\n    image: x/tick:6\n    depends_on: [tick-postgresql]\n"
            "  tick-postgresql:\n    image: postgres:16\n  tick-redis:\n    image: redis:7\n")
    found, names, built = compose(_units({"stack/docker-compose.yml": text}))
    assert names == ["tick"]
    assert not [f for fs in found.values() for f in fs]                # no links between its own containers
    assert built["@aliases"]["tick-postgresql"] == "tick"


def test_a_table_of_services_says_their_area_and_who_runs_them(ctx):
    from test_prose_010 import facts

    text = ("Service | Area | Run by | Inventory group\n"
            "shopfront | sales | the web team | web\n"
            "ledger | finance | Team Ledger | db\n")
    t = facts(text, parts=("shopfront", "ledger"))
    assert {("shopfront", "part_of", "sales"), ("ledger", "part_of", "finance")} <= t
    assert {("shopfront", "owned_by", "web team"), ("ledger", "owned_by", "Team Ledger")} <= t
    assert {("sales", "is_a", "domain"), ("finance", "is_a", "domain")} <= t


@pytest.mark.parametrize("category,name,ok", [
    ("application", "config-server", True), ("application", "customers-service", True),   # identifiers: names
    ("application", "Config Server", False), ("application", "application", False),
    ("team", "Platform team", True), ("team", "Team Data", True), ("team", "team", False),
    ("service area", "data", True), ("platform service", "data", False), ("platform service", "platform team", False),
])
def test_a_team_or_an_area_named_with_common_words(ctx, category, name, ok):
    from supagent.knowledge.naming import no_name

    assert (no_name(category, name) == "") == ok


def test_the_one_service_built_from_the_repositorys_root_is_the_repository(ctx):
    from supagent.knowledge.understand import Names, discover, owners

    text = ("services:\n  db:\n    image: postgres:16\n  web:\n    build:\n      context: ..\n"
            "      dockerfile: docker/Dockerfile\n    depends_on: [db]\n")
    unit = {"ukey": "c", "path": "docker/docker-compose.yml", "kind": "file", "title": "docker-compose.yml",
            "text": text, "meta": {}}
    unit["found"] = discover(unit)
    owner, aliases = owners([unit], "pingwatch", Names())
    assert owner == "pingwatch" and "web" in aliases
    many = text.replace("  db:\n    image: postgres:16\n", "  api:\n    build: ..\n")   # two from the root: no owner
    unit2 = dict(unit, text=many)
    unit2["found"] = discover(unit2)
    assert owners([unit2], "pingwatch", Names()) == (None, [])


def test_a_database_name_the_code_computes_is_no_name(ctx):
    from supagent.knowledge.understand import Names, discover, facts_of

    text = ('DATABASES = {"default": {"NAME": os.getenv("DB_NAME", BASE_DIR / "app.sqlite")}}\n'
            'if os.getenv("DB") == "postgres":\n    DATABASES = {"default": {"NAME": os.getenv("DB_NAME", "pingdb")}}\n')
    unit = {"ukey": "s", "path": "app/settings.py", "kind": "file", "title": "settings.py", "text": text, "meta": {}}
    unit["found"] = discover(unit)
    got = {(f["subject"], f["verb"], f["obj"]) for f in facts_of(unit, "pingwatch", Names(), {"pingwatch": "pingwatch"})}
    assert ("pingwatch", "uses", "pingdb") in got
    assert not any(o == "BASE_DIR" for _s, _v, o in got)
