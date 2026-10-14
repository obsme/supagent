"""(0.10.10) How pages and repositories are written beyond sentences: a page's properties (Page Properties tables,
"Key: value" lines), a line that introduces a list, a caption before a table, the kinds the documents state, a
configuration repository of many services, Kubernetes' recommended labels, Ansible's lists of services and generic
roles, "runs on Sundays" (a schedule, no place)."""

from __future__ import annotations

import pytest


class _Names:
    hosts: dict = {}

    def part(self, raw):
        return None

    def service(self, raw):
        return None


def test_a_page_of_properties_is_read_as_its_part_properties():
    from supagent.knowledge.understand import _key_values, _property, _tables

    text = ("Short name | OD\nDomain | retail\nMaintained by | the harbor squad\nLifecycle | live\n")
    (t0, header, rows), = _tables(text)
    kv = _key_values(t0, header, rows)
    assert [(k, v) for _r, k, v in kv] == [("Short name", "OD"), ("Domain", "retail"),
                                          ("Maintained by", "the harbor squad"), ("Lifecycle", "live")]
    assert [_property(k) for _r, k, _v in kv] == [("alias", "part"), ("part_of", "part"), ("owned_by", "owner"), None]
    (t0, header, rows), = _tables("Attribute | Details\nDatenbank | db-a-01\nLäuft auf | pool-a, pool-b\n")
    assert [(k, v) for _r, k, v in _key_values(t0, header, rows)] == [("Datenbank", "db-a-01"),
                                                                     ("Läuft auf", "pool-a, pool-b")]
    (t0, header, rows), = _tables("Host | Role\nweb-01 | front\nweb-02 | front\n")   # no keys: no properties
    assert _key_values(t0, header, rows) is None


@pytest.mark.parametrize("text,want", [
    ("Order Desk has the following components:\n- od-web – the web front\n- od-api (REST)\n",
     "Order Desk has the following components: od-web, od-api."),
    ("Wir betreuen:\n* Order Desk\n* Stock Keeper\n", "Wir betreuen: Order Desk, Stock Keeper."),
])
def test_a_line_that_introduces_a_list(text, want):
    from supagent.knowledge.understand import _list_sentences

    assert [s for _at, s in _list_sentences(text)] == [want]


@pytest.mark.parametrize("sentence,want,kinds", [
    ("Order Desk has the following components: od-web, od-api.", [("od-web", "Order Desk"), ("od-api", "Order Desk")],
     [("od-web", "component"), ("od-api", "component")]),
    ("The components of Order Desk are od-web, od-api and od-sync.",
     [("od-web", "Order Desk"), ("od-api", "Order Desk"), ("od-sync", "Order Desk")], None),
    ("The retail domain groups the following applications: Order Desk, Stock Keeper.",
     [("Order Desk", "retail"), ("Stock Keeper", "retail")],
     [("Order Desk", "application"), ("Stock Keeper", "application"), ("retail", "domain")]),
    ("The production environment (prd) has these server pools: pool-a-prd, pool-b-prd.",
     [("pool-a-prd", "production"), ("pool-b-prd", "production")], None),
    ("od-api is the REST API of Order Desk.", [("od-api", "Order Desk")], None),
    ("od-sync is a component of Order Desk: the event listener.", [("od-sync", "Order Desk")], None),
    ("od-web ist die Komponente „web front end“ von Order Desk.", [("od-web", "Order Desk")], None),
    ("od-web est le composant « web front end » de Order Desk.", [("od-web", "Order Desk")], None),
    ("Die Domäne retail umfasst die Anwendungen Order Desk, Stock Keeper.",
     [("Order Desk", "retail"), ("Stock Keeper", "retail")], None),
    ("pool-a-prd is a server pool of the production environment.", [("pool-a-prd", "production")], None),
    ("mq-01 is the Kafka cluster of the retail applications.", [], None),   # what a cluster serves: no whole
])
def test_wholes_and_parts_as_pages_write_them(sentence, want, kinds):
    import re

    from supagent.knowledge.understand import _memberships

    found = [(m.start(), m.group(0), m.group(0)) for m in re.finditer(r"[a-z]+(?:-[a-z0-9]+)+", sentence)]
    said: list = []
    assert _memberships(sentence, found, _Names(), unit_part="", kinds=said) == want
    if kinds is not None:
        assert said == kinds


@pytest.mark.parametrize("sentence,title,want", [
    ("Squad Harbor is accountable for: Order Desk, Stock Keeper.", "",
     [("Order Desk", "Squad Harbor"), ("Stock Keeper", "Squad Harbor")]),
    ("Applications we maintain: Order Desk, Stock Keeper.", "Squad Harbor",
     [("Order Desk", "Squad Harbor"), ("Stock Keeper", "Squad Harbor")]),
    ("Wir betreuen: Order Desk, Stock Keeper.", "Squad Harbor",
     [("Order Desk", "Squad Harbor"), ("Stock Keeper", "Squad Harbor")]),
    ("La squad Harbor est responsable de Order Desk.", "", [("Order Desk", "squad Harbor")]),
    ("Applications we maintain: Order Desk.", "Release notes", []),        # no team's page: nobody
])
def test_who_maintains_what(sentence, title, want):
    from supagent.knowledge.understand import _ownerships

    assert _ownerships(sentence, [], "", title) == want


@pytest.mark.parametrize("sentence,want", [
    ("OD stands for Order Desk.", [("Order Desk", "OD")]),
    ("OD stands for Order Desk and is used by the shops.", [("Order Desk", "OD")]),
    ("Order Desk, also called OD, is a retail application.", [("Order Desk", "OD")]),
    ("Order Desk (a.k.a. OD) is live since 2019.", [("Order Desk", "OD")]),
    ("XY stands for Order Desk.", []),                                     # not its initials
])
def test_other_names_a_page_defines(sentence, want):
    from supagent.knowledge.understand import _abbreviations

    assert _abbreviations(sentence) == want


def test_kinds_words_and_wholes():
    from supagent.knowledge.understand import _kind_word, _whole_kind

    assert [_kind_word(w) for w in ("Komponenten", "server pools", "applications", "Domain", "Schedule")] == \
        ["component", "server pool", "application", "domain", None]
    assert _whole_kind("the retail domain") == "domain" and _whole_kind("Die Domäne retail") == "domain"


def test_a_list_of_names_in_a_cell():
    from supagent.knowledge.understand import _cell_values

    assert _cell_values("db-a-01 db-a-02") == ["db-a-01", "db-a-02"]
    assert _cell_values("pool-a / pool-b") == ["pool-a", "pool-b"]
    assert _cell_values("Order Desk") == ["Order Desk"]                   # words, not names
    assert _cell_values("od.order.created od.order.closed") == ["od.order.created", "od.order.closed"]


def test_a_tables_rows_by_its_pages_title():
    from supagent.knowledge.understand import _implied_head

    assert _implied_head("Name", "Databases") == "Databases"
    assert _implied_head("Name", "Event topics") == "topics" or _implied_head("Name", "Event topics") == "Event topics"
    assert _implied_head("Name", "Release notes") == "Name"
    assert _implied_head("Service", "Databases") == "Service"


def test_runs_on_a_day_is_a_schedule():
    from supagent.knowledge.understand import SCHEDULE_AFTER

    s = "od-export runs on Sundays at 04:15"
    assert SCHEDULE_AFTER.match(s, s.index("runs on") + len("runs on"))
    s = "od-export runs on the 1st of the month"
    assert SCHEDULE_AFTER.match(s, s.index("runs on") + len("runs on"))
    s = "od-export runs on web-01"
    assert not SCHEDULE_AFTER.match(s, s.index("runs on") + len("runs on"))


def _unit(path, text, names=()):
    return {"path": path, "text": text, "found": {"lang": "properties", "workloads": [], "names": list(names),
                                                  "tool": None, "heading": None}}


def test_a_configuration_repository_of_many_services():
    from supagent.knowledge.understand import owners, several_services

    units = [_unit("order-desk/od-api/application.properties", "spring.application.name=od-api", ["od-api"]),
             _unit("order-desk/od-web/application.properties", "spring.application.name=od-web", ["od-web"]),
             _unit("README.md", "# config", [])]
    assert several_services(units) == {"order-desk/od-api": "od-api", "order-desk/od-web": "od-web"}
    assert owners(units, "app-config", _Names()) == (None, [])        # no service of the repository's name
    one = [_unit("src/main/resources/application.properties", "spring.application.name=od-api", ["od-api"])]
    assert several_services(one) == {}


def test_ansible_lists_and_generic_roles():
    from supagent.knowledge.projects import _app_of, _listed_services, _plays

    assert _listed_services({"services": [{"name": "od-api", "port": 8080}, {"name": "od-web"}],
                             "deployed_modules": ["od-sync"], "heap": "1g"}) == ["od-api", "od-web", "od-sync"]
    assert [_app_of(x) for x in ("ansible-infra", "infra-ansible", "orders-ansible")] == ["", "", "orders"]
    play = _plays({"path": "playbooks/deploy.yml", "text": (
        "- hosts: pool-a\n  tasks:\n    - name: od-api\n      ansible.builtin.include_role:\n"
        "        name: java_service\n      vars:\n        service_name: od-api\n")})
    assert play[0]["roles"] == ["@service:od-api"]


def test_kubernetes_namespace_part_of_label_and_jobs(ctx):
    from supagent.knowledge.projects import kubernetes

    text = ("apiVersion: batch/v1\nkind: CronJob\nmetadata:\n  name: od-purge\n  namespace: batch\n  labels:\n"
            "    app.kubernetes.io/part-of: order-desk\nspec:\n  schedule: \"0 2 * * *\"\n  jobTemplate:\n"
            "    spec:\n      template:\n        spec:\n          containers:\n            - name: od-purge\n"
            "              image: tools:1\n")
    facts, workloads, _r = kubernetes([{"path": "cronjobs/od-purge.yaml", "text": text}])
    got = {(f["subject"], f["verb"], f["obj"]) for fs in facts.values() for f in fs}
    assert {("od-purge", "runs_on", "batch"), ("od-purge", "part_of", "order-desk"), ("od-purge", "is_a", "job")} <= got
    assert workloads == ["od-purge"]


def test_key_value_lines_are_sentences_of_their_own():
    from supagent.knowledge.understand import _sentences

    text = ("Part of: retail business area\nProduct team: Team Quokka\nTier: tier 2\n"
            "Built from: a-b, c-d and e-f.\nThe service keeps the orders of the shops and\nsends them to the stock.\n")
    assert [x for _at, x in _sentences(text)] == [
        "Part of: retail business area", "Product team: Team Quokka", "Tier: tier 2",
        "Built from: a-b, c-d and e-f.", "The service keeps the orders of the shops and sends them to the stock."]


@pytest.mark.parametrize("sentence,want", [
    ("Built from: od-web, od-api and od-sync.", [("od-web", "Order Desk"), ("od-api", "Order Desk"),
                                                 ("od-sync", "Order Desk")]),
    ("Composé de : od-web, od-api.", [("od-web", "Order Desk"), ("od-api", "Order Desk")]),
    ("Built from: Java 17 and Spring Boot.", []),                          # a build's stack: no part
    ("od-sync — the batch runner of Order Desk.", [("od-sync", "Order Desk")]),
    ("od-web - the web user interface of Order Desk.", [("od-web", "Order Desk")]),
])
def test_parts_after_a_label_and_a_dash(sentence, want):
    import re

    from supagent.knowledge.understand import _memberships

    found = [(m.start(), m.group(0), m.group(0)) for m in re.finditer(r"[a-z]+(?:-[a-z0-9]+)+", sentence)]
    assert _memberships(sentence, found, _Names(), unit_part="Order Desk") == want


def test_property_keys_people_write():
    from supagent.knowledge.understand import _property

    assert _property("Product team") == ("owned_by", "owner")
    assert _property("Contract owner") == ("owned_by", "owner")
    assert _property("Runs in") == ("runs_on", "host")
    assert _property("Store") == ("uses", "database")
    assert _property("Tier") is None


def test_a_place_and_the_servers_it_holds():
    from supagent.knowledge.understand import GROUP_LIST

    m = GROUP_LIST.match("Machine group grp-q7 (production): q7-vm01, q7-vm02.")
    assert m and m.group("b") == "grp-q7" and m.group("list") == "q7-vm01, q7-vm02"
    assert GROUP_LIST.match("Server pool pool-a: web-01, web-02").group("b") == "pool-a"
    assert GROUP_LIST.match("The team: a, b") is None


def test_a_category_by_what_its_description_defines():
    from supagent.knowledge.placing import defining

    assert set(defining("a tenant project (a namespace) of a cluster")) == {"namespace"}
    assert set(defining("a pool of worker hosts of a cluster")) == {"group"}   # a pool, no worker
    assert set(defining("a scheduled task: its calendar, what it reads and writes")) == {"job"}


def test_one_name_in_another_word_order_and_a_whole_beside_its_parts():
    from types import SimpleNamespace

    from supagent.knowledge.consolidate import _extends, _stems, same

    assert same("Quokka team", "Team Quokka", "product team") == "strong"
    assert same("the quokka team", "Team Quokka", "product team") == "strong"
    assert same("web-prod", "prod-web", "server") == ""                # a host's name as written
    values = [SimpleNamespace(value=v, synonyms=None) for v in
              ("Order Desk", "order-desk-adapter", "order-desk-ui", "order-desk-api", "Billing",
               "billing-api")]
    stems = _stems(values)
    assert "order desk" in stems and "billing" not in stems
    assert _extends(values[0], values[1], stems) and _extends(values[3], values[0], stems)
    assert not _extends(values[4], values[5], stems)                  # one name only extends billing: maybe one


def test_identifiers_in_another_order_stay_two():
    from supagent.knowledge.consolidate import same

    assert same("ups-x1-a-b", "ups-x1-b-a", "power") != "strong"   # (a doubt at most, as before)
    assert same("orders-db", "db-orders", "data store") != "strong"


@pytest.mark.parametrize("sentence,want", [
    ("od-sync es el microservicio «background worker» del sistema Order Desk.", [("od-sync", "Order Desk")]),
    ("od-sync è il microservizio «scheduler» del sistema Order Desk.", [("od-sync", "Order Desk")]),
    ("El sistema Order Desk se compone de od-web, od-api y od-sync.",
     [("od-web", "Order Desk"), ("od-api", "Order Desk"), ("od-sync", "Order Desk")]),
    ("Il sistema Order Desk è composto da od-web e od-api.", [("od-web", "Order Desk"), ("od-api", "Order Desk")]),
])
def test_parts_in_spanish_and_italian(sentence, want):
    import re

    from supagent.knowledge.understand import _memberships

    found = [(m.start(), m.group(0), m.group(0)) for m in re.finditer(r"[a-z]+(?:-[a-z0-9]+)+", sentence)]
    assert _memberships(sentence, found, _Names(), unit_part="") == want


def test_spanish_and_italian_keys_and_verbs():
    from supagent.knowledge.understand import CUES, _property

    assert _property("Área") == ("part_of", "part") and _property("Equipo") == ("owned_by", "owner")
    assert _property("Team responsabile") == ("owned_by", "owner")
    said = {verb for verb, rx in CUES for s in ("Gira su mg-a-01.", "Se despliega en mg-a-01.") if rx.search(s)}
    assert said == {"runs_on"}
    assert {verb for verb, rx in CUES if rx.search("Usa il database orders_pg.")} == {"reads_from"}


def test_a_topics_dotted_name_is_never_cut_to_its_first_word(ctx):
    from supagent.knowledge.naming import checked

    assert checked("queue", "com.acme-billing.invoice.published.v1")[0] == "com.acme-billing.invoice.published.v1"
    assert checked("queue", "ops.orders.created.v2")[0] == "ops.orders.created.v2"


def test_a_jobs_table_names_what_its_jobs_read_and_write():
    from supagent.knowledge.understand import JOB_HEAD, SOURCE_COL, STORE_HEAD, TARGET_COL

    assert JOB_HEAD.match("Task") and SOURCE_COL.match("Input") and TARGET_COL.match("Output")
    assert STORE_HEAD.fullmatch("Channel") and STORE_HEAD.fullmatch("Channels")


def _units(files):
    return [{"ukey": p, "path": p, "kind": "file", "title": p, "text": t, "meta": {}} for p, t in files.items()]


def _triples(found):
    return {(f["subject"], f["verb"], f["obj"]) for fs in found.values() for f in fs}


@pytest.mark.parametrize("inventory", [
    ("hosts", "[web]\nweb-1\nweb-2\n\n[db]\ndb-1\n\n[app:children]\nweb\ndb\n\n[prod:children]\napp\n"),
    ("inventory/hosts.yml", "all:\n  children:\n    prod:\n      children:\n        app:\n          children:\n"
                            "            web:\n              hosts:\n                web-1:\n                web-2:\n"
                            "            db:\n              hosts:\n                db-1:\n"),
])
def test_groups_of_groups_in_ini_and_yaml_inventories(ctx, inventory):
    from supagent.knowledge.projects import facts

    path, text = inventory
    got = _triples(facts(_units({path: text, "site.yml": "- hosts: web\n  roles: [shopfront]\n",
                                 "roles/shopfront/tasks/main.yml": "- service: name=shopfront state=started\n"}))[0])
    for h in ("web-1", "web-2"):
        assert (h, "in_group", "web") in got and (h, "in_group", "app") in got and (h, "in_group", "prod") in got
    assert ("db-1", "in_group", "db") in got and ("db-1", "in_group", "prod") in got
    assert ("shopfront", "runs_on", "web") in got


def test_roles_that_set_the_hosts_up_are_no_services(ctx):
    from supagent.knowledge.projects import facts

    files = {"hosts": "[app]\napp-1\n",
             "site.yml": "- hosts: app\n  roles: [acme.os_setup, acme.ssh_hardening, admin-tools, fix-stuck-jobs, "
                         "monitor-queue, shopfront, acme.dynmotd, acme.yum_cron]\n",
             "roles/admin-tools/tasks/main.yml": "- package: name=htop\n",
             "roles/fix-stuck-jobs/tasks/main.yml": "- cron: name=fix job=/usr/local/bin/fix\n",
             "roles/monitor-queue/tasks/main.yml": "- copy: src=check dest=/etc/telegraf/telegraf.d/q.conf\n  "
                                                   "notify: restart telegraf\n",
             "roles/monitor-queue/handlers/main.yml": "- name: restart telegraf\n  service: name=telegraf "
                                                     "state=restarted\n",
             "roles/shopfront/tasks/main.yml": "- service: name=shopfront state=started\n"}
    parts = {s for s, v, o in _triples(facts(_units(files))[0]) if v == "runs_on"}
    assert parts == {"shopfront"}


def test_a_host_agent_on_most_groups_is_still_a_part(ctx):
    from supagent.knowledge.projects import facts

    groups = ["web", "db", "cache", "queue", "batch"]
    files = {"hosts": "".join(f"[{g}]\n{g}-1\n" for g in groups),
             "site.yml": "".join(f"- hosts: {g}\n  roles: [acme.telegraf, {g}app]\n" for g in groups[:4]) +
                         "- hosts: batch\n  roles: [batchapp]\n"}
    for g in groups:
        files[f"roles/{g}app/tasks/main.yml"] = f"- service: name={g}app state=started\n"
    on = {(s, o) for s, v, o in _triples(facts(_units(files))[0]) if v == "runs_on"}
    assert {o for s, o in on if s == "telegraf"} >= {"web", "db", "cache", "queue"}


def test_firewall_lists_and_a_collections_steps_are_no_parts(ctx):
    from supagent.knowledge.projects import facts

    files = {"hosts": "[app]\napp-1\n[db]\ndb-1\n",
             "group_vars/app.yml": "firewall_public_services:\n  - http\n  - https\n  - shopfront\n"
                                   "services:\n  - shopfront\n  - ssh\n",
             "site.yml": "- hosts: db\n  roles: [acme.mongodb.mongodb_install, acme.mongodb.mongodb_auth, "
                         "acme.mongodb.mongodb_mongod, acme.wireguard.machine]\n"}
    on = {(s, o) for s, v, o in _triples(facts(_units(files))[0]) if v == "runs_on"}
    assert {s for s, o in on} == {"shopfront", "mongodb"}, on
