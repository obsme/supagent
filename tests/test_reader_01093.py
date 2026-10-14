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


@pytest.mark.parametrize("text,pairs", [
    ("checkout calls rates-api (api.vendor-x.example) for each parcel.", [("rates-api", "api.vendor-x.example")]),
    ("The ledger (https://ledger.int.acme.net:8443/v1) books it.", [("ledger", "ledger.int.acme.net")]),
    ("Edit the settings (config.yaml) and restart (1.2.3).", []),          # a file, a version: no address
    ("vip-db (10.0.0.12) holds the primary.", []),                         # an IP address: no host
    ("It runs on (www.example.org).", []),                                 # no name before it
])
def test_a_name_written_with_its_address(ctx, text, pairs):
    from supagent.knowledge.understand import addressed_names

    assert [(n, h) for n, h, _p in addressed_names(text)] == pairs


def test_another_companys_address_makes_an_external_service(ctx):
    from supagent.knowledge.understand import Names, _foreign, discover, facts_of, norm

    names = Names()
    names.own_sites = {"corp.example"}                   # the documents name several hosts of corp.example
    assert _foreign("api.vendor-x.example", names) and not _foreign("portal.corp.example", names)
    assert not _foreign("db.internal", names) and not _foreign("db-01", names) and not _foreign("10.0.0.1", names)
    names.add_part("rates-api")
    names.add_part("portal")
    page = {"ukey": "p", "path": "", "kind": "page", "title": "checkout", "meta": {},
            "text": "checkout calls rates-api (api.vendor-x.example) and portal (portal.corp.example)."}
    page["found"] = discover(page)
    got = {(f["subject"], f["verb"], f["obj"]) for f in facts_of(page, None, names, {})}
    assert ("rates-api", "is_a", "external") in got
    assert ("portal", "is_a", "external") not in got     # the system's own site
    names.alias[norm("api.vendor-y.example")] = "quotes-y"   # (as run() registers "quotes-y (api.vendor-y.example)")
    conf = {"ukey": "c", "path": "deploy/checkout.yaml", "kind": "file", "title": "checkout.yaml", "meta": {},
            "text": "env:\n  - name: QUOTES_API_URL\n    value: \"https://api.vendor-y.example\"\n"
                    "  - name: PORTAL_URL\n    value: \"https://portal.corp.example\"\n"}
    conf["found"] = discover(conf)
    got = {(f["subject"], f["verb"], f["obj"]) for f in facts_of(conf, "checkout", names, {"checkout": "checkout"})}
    assert ("quotes-y", "is_a", "external") in got and ("checkout", "calls", "quotes-y") in got
    assert not any(v == "is_a" and o == "external" and s != "quotes-y" for s, v, o in got)


def _code_facts(path, text, names=None):
    from supagent.knowledge.understand import Names, discover, facts_of

    unit = {"ukey": path, "path": path, "kind": "file", "title": path.rsplit("/", 1)[-1], "text": text, "meta": {}}
    unit["found"] = discover(unit)
    return {(f["subject"], f["verb"], f["obj"], f["obj_kind"]) for f in facts_of(unit, "billing", names or Names(),
                                                                                 {"billing": "billing"})}


def test_a_databases_client_in_a_script_names_the_database_it_uses(ctx):
    from supagent.knowledge.understand import Names

    got = _code_facts("jobs/nightly-ledger-export.sh",
                      "#!/bin/sh\npsql -h ledger-pg.db.internal -c '\\copy (select 1) to /tmp/x.csv'\n"
                      "redis-cli -h quotes-cache.int flushdb\n# mysql -h old-db -e 'select 1'\npsql -h localhost -l\n")
    assert ("nightly-ledger-export", "uses", "ledger-pg", "database") in got
    assert ("nightly-ledger-export", "uses", "quotes-cache", "cache") in got
    assert not any(o in ("old-db", "localhost") for _s, _v, o, _k in got)   # a comment, the local host
    names = Names()
    names.hosts["db-07"] = "db-07"
    got = _code_facts("bin/backup.sh", "pg_dump -h db-07 -d invoices > /backup/invoices.sql\n", names)
    assert ("billing", "uses", "invoices", "database") in got and ("invoices", "runs_on", "db-07", "host") in got
    assert not _code_facts(".gitlab-ci.yml", "script:\n  - psql -h ledger-pg -c 'select 1'\n")   # a pipeline's step
    assert not _code_facts("tests/test_export.py", "os.system('psql -h ledger-pg -c 1')\n")      # a test


def test_a_configurations_host_and_port_still_read_after_the_scripts(ctx):
    got = _code_facts("config/app.yaml", "database:\n  host: ledger-pg:5432\n")
    assert any(o == "ledger-pg" for _s, _v, o, _k in got)


def test_a_datastores_column_and_a_table_of_stores(ctx):
    from test_prose_010 import facts

    text = ("Module | Datastores\nledger-worker | ledger-cass, quotes-ch\n\n"
            "Datastore | Engine | Node\nledger-cass | Cassandra 4 | db-01\n\n"
            "Job | Prometheus | Scrapes\nledger-worker | prom-1 | db-01\n")
    t = facts(text, parts=("ledger-worker", "ledger-cass", "quotes-ch"))
    assert {("ledger-worker", "uses", "ledger-cass"), ("ledger-worker", "uses", "quotes-ch")} <= t
    assert ("ledger-cass", "is_a", "database") in t            # a known datastore in a table of datastores
    assert ("ledger-worker", "is_a", "job") not in t           # a scrape job named after what it scrapes


def test_the_systems_own_services_never_go_to_a_category_of_partners(ctx):
    from supagent.knowledge.placing import best_category

    cats = ["partner api", "platform service", "datastore"]
    assert best_category("service", cats) != "partner api"
    assert best_category("external", cats) == "partner api"


def test_a_vip_in_front_of_an_inventory_group_sends_to_the_group(ctx):
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    names = Names()
    names.hosts[norm("prod_web")] = "prod_web (prod)"  # (as run() maps the one environment's group of that name)
    names.groups.add(norm("prod_web"))
    names.hosts[norm("web-07")] = "web-07"
    names.add_part("accounts-api")
    page = {"ukey": "v", "path": "", "kind": "page", "title": "VIPs", "meta": {},
            "text": "VIP | Service | Servers\nvip-accounts-prod | accounts-api | prod_web, web-07\n"}
    page["found"] = discover(page)
    got = {(f["subject"], f["verb"], f["obj"], f["obj_kind"]) for f in facts_of(page, None, names, {})}
    assert ("vip-accounts-prod", "routes_to", "prod_web (prod)", "group") in got
    assert not any(s == "prod_web (prod)" and v == "in_group" for s, v, _o, _k in got)
    assert ("web-07", "in_group", "vip-accounts-prod", "vip") in got     # a server: held by the VIP, as before


def test_an_address_in_a_docstring_is_an_example(ctx):
    got = _code_facts("hc/front/forms.py",
                      'class URLField:\n    """Unlike the default field it accepts "http://home_server"."""\n\n'
                      '    def check(self):\n        return requests.get("http://ledger-api:8080/health")\n')
    assert any(o == "ledger-api" for _s, _v, o, _k in got)
    assert not any(o == "home_server" for _s, _v, o, _k in got)


def test_an_applications_database_named_after_it_does_not_make_it_a_database(ctx):
    from supagent.knowledge.placing import cues

    assert "store" not in cues("Connect to the Galaxy database", "Galaxy")          # Galaxy's database
    assert cues("It reads from the database ledger-pg", "ledger-pg").get("store") == 1   # the database ledger-pg


def test_a_sentence_saying_what_a_name_is_names_its_category(ctx):
    from supagent.knowledge.placing import named_categories

    cats = ["platform service", "module", "datastore"]
    assert named_categories("ContractDesk is a platform service of the enterprise line", "ContractDesk", cats) == \
        {"platform service": 1}
    assert named_categories("bill-viewer est un module de Billing", "bill-viewer", cats) == {"module": 1}
    assert not named_categories("ContractDesk is owned by the pro tribe", "ContractDesk", cats)


def test_a_list_item_after_a_french_possessive_is_the_name(ctx):
    from supagent.knowledge.understand import _ownerships, _span_name

    assert _span_name("de son RabbitMQ", 0, [], True) == "RabbitMQ"
    assert _span_name("d'Inventaire", 0, [], True) == "Inventaire"
    assert _span_name("Delta Gateway", 0, [], True) == "Delta Gateway"
    got = _ownerships("L'équipe Plateforme est responsable de Portail et de son RabbitMQ.", [])
    assert ("Portail", "équipe Plateforme") in got and ("RabbitMQ", "équipe Plateforme") in got


def test_the_dns_servers_a_program_asks_are_no_service_it_calls(ctx):
    got = _code_facts("conf/http/portal.conf",
                      "upstream portal {\n    server portal-1.corp.example:8080;\n}\n"
                      "resolver ns-a.corp.example:8600 ns-b.corp.example:8600 valid=5s;\n")
    assert not any("ns-a" in o or "ns-b" in o for _s, _v, o, _k in got)


def test_a_repository_to_clone_is_no_endpoint(ctx):
    from supagent.knowledge.understand import NOT_ENDPOINT

    assert NOT_ENDPOINT.search("https://git.vendor-x.example/team/billing.git")
    assert not NOT_ENDPOINT.search("https://rates.vendor-x.example/v2")
    got = _code_facts("conf/billing.yml", "billing_repo_url: 'https://git.vendor-x.example/team/billing.git'\n")
    assert not any(o == "vendor-x" for _s, _v, o, _k in got)


def test_an_upstream_of_inventory_hosts_is_the_application_deployed_on_their_group(ctx):
    from supagent.knowledge.understand import Names, norm, upstream_part, upstreams

    conf = ("upstream shop-prod {\n    server service.consul service=wall resolve;\n"
            "    server shop1.corp.example resolve backup;\n    server shop2.corp.example:8080 resolve;\n}\n"
            "upstream search-prod {\n\tserver idx1.corp.example:8983;\n}\n")
    ups = upstreams(conf)
    assert ups == {"shop-prod": ["shop1.corp.example", "shop2.corp.example"], "search-prod": ["idx1.corp.example"]}
    names = Names()
    for h in ("shop1.corp.example", "shop2.corp.example", "idx1.corp.example"):
        names.hosts[norm(h)] = h
    names.placement = {"groups_of": {norm("shop1.corp.example"): {"shop_production", "shop_production_web"},
                                     norm("shop2.corp.example"): {"shop_production", "shop_production_web"},
                                     norm("idx1.corp.example"): {"search_production"}},
                       "runs_on": {"storefront": {"shop_production"}, "storefront-workers": {"shop_production"},
                                   "passenger": {"shop_production"}, "solr9cloud": {"search_production"}}}
    assert upstream_part("shop-prod", ups["shop-prod"], names) == "storefront"       # its workers and software: no
    assert upstream_part("search-prod", ups["search-prod"], names) == "solr9cloud"   # a store when no application
    assert upstream_part("x", ["unknown.corp.example"], names) is None               # a server of no inventory


def test_an_applications_own_processes_listed_in_its_group_are_its_names(ctx):
    from supagent.knowledge.projects import facts

    files = {"hosts": "[storefront]\nweb-1\n",
             "site.yml": "- hosts: storefront\n  roles: [storefront]\n",
             "roles/storefront/tasks/main.yml": "- service: name=storefront state=started\n",
             "group_vars/storefront/common.yml": "app_site_services:\n  - storefront-workers\n"
                                                 "  - storefront-realtime-workers\n  - storefront-sneakers\n"
                                                 "  - ledger-api\n"}
    found, declared = facts(_units(files))
    assert {"storefront-workers", "storefront-realtime-workers", "storefront-sneakers"}.isdisjoint(_parts(found))
    assert "ledger-api" in _parts(found)                   # another application listed there stays one
    assert declared["aliases"].get("storefront-workers") == "storefront"


def test_a_worker_role_named_after_the_plays_application_is_its_name(ctx):
    from supagent.knowledge.projects import facts

    files = {"hosts": "[catalog]\ncat-1\n",
             "site.yml": "- hosts: catalog\n  roles: [catalog, catalog_sqs_poller, catalog_indexer_api]\n",
             "roles/catalog/tasks/main.yml": "- service: name=catalog state=started\n",
             "roles/catalog_sqs_poller/tasks/main.yml": "- service: name=catalog-sqs-poller state=started\n",
             "roles/catalog_indexer_api/tasks/main.yml": "- service: name=catalog-indexer-api state=started\n"}
    found, declared = facts(_units(files))
    assert "catalog_sqs_poller" not in _parts(found) and declared["aliases"].get("catalog_sqs_poller") == "catalog"
    assert "catalog_indexer_api" in _parts(found)          # no process word: a part of its own
