"""(0.10.9.2) What the learner made of a real infrastructure repository and its wiki: a nested role named by its piece
(roles/<software>/<piece>: "worker", "backend"), a load balancer's server labels taken for applications, the system's
own domain taken for an organisation, a table of what the team runs whose headings and names the reader did not know
("Product | Cared for by | Lives in", "Quokka"), a page titled by a name it defines ("Quokka is the update system")
not read as that part's page."""
from __future__ import annotations


def _facts(text, kind="page", title="Platform", path="", parts=(), hosts=(), groups=(), me=None):
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    n = Names()
    for p in parts:
        n.add_part(p)
    for h in hosts:
        n.hosts[norm(h)] = h
    n.inventory_groups.update(norm(g) for g in groups)
    u = {"ukey": path or "p1", "path": path, "kind": kind, "title": title, "text": text, "meta": {}}
    u["found"] = discover(u)
    return {(f["subject"], f["verb"], f["obj"], f["obj_kind"]) for f in facts_of(u, me, n, {})}


def test_a_nested_roles_generic_piece_is_named_with_its_software(ctx):
    from supagent.knowledge.projects import Role, _nested

    assert _nested("quokka/worker") == "quokka-worker"
    assert _nested("bilby2/backend") == "bilby2-backend"
    assert _nested("my_app/api") == "my_app_api"
    assert _nested("monitor/base") == "monitor" and _nested("quokka/server") == "quokka"
    assert _nested("mq/queue") == "" and _nested("vault/policy") == "" and _nested("idm/client") == ""
    assert _nested("network_plugin/calico") is None and _nested("geerlingguy.apache") is None
    assert _nested("tracker3") is None
    assert Role("quokka/worker", None).part == "quokka-worker"
    assert Role("mq/queue", None).part is None
    assert Role("network_plugin/calico", None).part == "calico"


HAPROXY = ("frontend bilby-frontend\n"
           "    bind 0.0.0.0:10020\n"
           "    default_backend bilby-backend\n"
           "\n"
           "backend bilby-backend\n"
           "    balance roundrobin\n"
           "    server  web01 web01:80 check inter 10s rise 1 fall 3\n"
           "    server  web02 web02:80 check inter 10s rise 1 fall 3\n"
           "\n"
           "listen docs\n"
           "    server  docs01 docs01.example.net:80 check\n")


def test_a_load_balancers_server_line_names_its_backend_not_an_application(ctx):
    from supagent.knowledge.understand import lb_backend

    assert lb_backend(HAPROXY, HAPROXY.index("server  web01")) == "bilby"
    assert lb_backend(HAPROXY, HAPROXY.index("server  docs01")) == "docs"
    assert lb_backend(HAPROXY, HAPROXY.index("bind 0.0.0.0")) is None
    assert lb_backend("server = db01:5432\n", 3) is None


def test_the_backend_known_is_called_and_a_server_label_is_never_a_part(ctx):
    path = "roles/haproxy/templates/haproxy.cfg"
    got = _facts(HAPROXY, kind="file", title="haproxy.cfg", path=path, parts=("haproxy", "bilby"), me="haproxy")
    objs = {o for _s, _v, o, _k in got}
    assert ("haproxy", "calls", "bilby", "part") in got
    assert not objs & {"web01", "web02", "docs01"}
    got = _facts(HAPROXY, kind="file", title="haproxy.cfg", path=path, parts=("haproxy", "bilby"), hosts=("web01",),
                 me="haproxy")
    assert ("bilby", "runs_on", "web01", "host") in got
    assert any(s == "haproxy" and o == "web01" for s, _v, o, _k in got)    # an inventory's server: sent to as well


def test_an_address_of_the_systems_own_site_naming_no_part_makes_no_organisation(ctx):
    from supagent.knowledge.understand import Names, _host_part

    n = Names()
    n.own_sites = {"example.org"}
    n.add_part("billing")
    n.inventory_groups.add("reports")
    assert _host_part("id.example.org", n) == ""
    assert _host_part("billing.example.org", n) == "billing"
    assert _host_part("reports.example.org", n) == "reports"           # the service of the inventory's group
    assert _host_part("hooks.slack.com", n) == "slack"


SERVICES = ("What the infrastructure group runs, who cares for it and where.\n"
            "Product | What it is | Cared for by | Lives in\n"
            "Ledger | the accounting system | Money crew | ledger_web, ledger_web_stg\n"
            "Quokka | the code forge | Tools crew | quokka, quokka_stg\n"
            "Monitoring | the dashboards | Ops team | grafana_hosts\n")
GROUPS = ("ledger_web", "ledger_web_stg", "quokka", "quokka_stg", "grafana_hosts")


def test_a_table_of_products_is_read_by_what_its_columns_hold(ctx):
    got = _facts(SERVICES, title="Services", groups=GROUPS, parts=("quokka",))
    assert ("Ledger", "runs_on", "ledger_web", "group") in got and ("Ledger", "runs_on", "ledger_web_stg", "group") in got
    assert ("Ledger", "owned_by", "Money crew", "owner") in got
    assert ("quokka", "owned_by", "Tools crew", "owner") in got
    assert not any(s == "Monitoring" for s, _v, _o, _k in got)       # a word no group is named after: no part


def test_a_column_of_groups_mixed_with_words_is_not_where_its_rows_run(ctx):
    text = ("Product | Lives in\n"
            "Ledger | ledger_web, the old farm\n"
            "Quokka | quokka\n")
    got = _facts(text, title="Services", groups=GROUPS)
    assert not any(v == "runs_on" for _s, v, _o, _k in got)


def test_a_one_word_title_defined_as_a_system_is_its_pages_part(ctx):
    from supagent.knowledge.understand import titled_name

    assert titled_name("Quokka", "Quokka is the update system (quokka.example.org). It stores updates in PostgreSQL.") \
        == "Quokka"
    assert titled_name("bilbyQA", "bilbyQA is the automated test system of the project.") == "bilbyQA"
    assert titled_name("Ledger", "Ledger est le système comptable de la banque.") == "Ledger"
    assert titled_name("Operations", "Operations is where we keep the runbooks of the group.") is None
    assert titled_name("Journal", "Journal is the record of our weekly meetings.") is None
    assert titled_name("Quokka", "Updates go through Quokka, the update system.") is None


def test_the_teams_words_for_a_part_defined_in_a_sentence_are_its_other_name(ctx):
    got = _facts("The event bus is a Kafka cluster of three nodes. It carries the orders.", parts=("Kafka",))
    assert ("Kafka", "alias", "event bus", "part") in got
    got = _facts("Le bus de messages est un cluster Kafka de trois noeuds.", parts=("Kafka",))
    assert ("Kafka", "alias", "bus de messages", "part") in got
    got = _facts("The database servers are the machines the db playbook configures.", parts=("db",))
    assert not any(v == "alias" for _s, v, _o, _k in got)              # the part named too far: no other name
    got = _facts("The service is a Kafka consumer.", parts=("Kafka",))
    assert not any(v == "alias" for _s, v, _o, _k in got)              # a generic word: no other name


def test_applications_go_to_the_persons_category_for_what_users_use(ctx):
    from supagent import settings
    from supagent.knowledge.proposals import _category

    settings.set_value("categories.custom", ["crew", "product", "backend service", "database", "outside provider",
                                             "host collection", "machine"])
    settings.set_value("categories.about", {"product": "what the community uses: a web application, the build system",
                                            "backend service": "an internal service the products rely on"})
    assert _category("part", "quokka") == "product"                 # two service categories: the one for users
    settings.set_value("categories.custom", ["team", "site", "shared service", "vendor service", "host"])
    settings.set_value("categories.about", {"site": "a website or public API the program runs for the public"})
    assert _category("part", "quokka") == "site"
    settings.set_value("categories.custom", ["team", "site", "room", "rack", "server"])
    settings.set_value("categories.about", {"site": "a datacenter of the company", "room": "a room of a datacenter"})
    assert _category("part", "quokka") != "site"                    # a place's "site": no application there


def test_a_team_page_saying_what_the_team_runs_in_french_or_english(ctx):
    got = _facts("L'équipe Socle s'occupe des files de messages Kafka et des serveurs PostgreSQL. "
                 "L'équipe Socle gère aussi Quokka et Bilby.", parts=("Kafka", "PostgreSQL", "Quokka", "Bilby"))
    owned = {(s, o) for s, v, o, _k in got if v == "owned_by"}
    assert {("Kafka", "équipe Socle"), ("PostgreSQL", "équipe Socle"), ("Quokka", "équipe Socle"),
            ("Bilby", "équipe Socle")} <= owned
    got = _facts("The delivery crew runs Quokka and Bilby. The ops team manages the Kafka cluster.",
                 parts=("Kafka", "Quokka", "Bilby"))
    owned = {(s, o) for s, v, o, _k in got if v == "owned_by"}
    assert {("Quokka", "delivery crew"), ("Bilby", "delivery crew"), ("Kafka", "ops team")} <= owned
    got = _facts("The nightly job runs on the app servers.", parts=("app",))
    assert not any(v == "owned_by" for _s, v, _o, _k in got)              # no team: no owner


def test_a_name_holding_a_teams_word_is_no_team(ctx):
    got = _facts("The teams-chat-notifier runs every hour and posts to the release channel.", parts=("teams-chat-notifier",))
    assert not any(v == "owned_by" for _s, v, _o, _k in got)


def test_a_system_named_in_prose_by_its_own_shape_is_a_part_when_a_known_part_relates_to_it(ctx):
    got = _facts("Before a release goes out, Quokka reads its test results from BilbyDB.", parts=("Quokka",))
    assert any(s == "Quokka" and o == "BilbyDB" for s, _v, o, _k in got)
    got = _facts("The team writes JavaScript and follows DevOps practices.", parts=("Quokka",))
    assert not any(o in ("JavaScript", "DevOps") for _s, _v, o, _k in got)
    got = _facts("We met at the BilbyHub conference last week.", parts=("Quokka",))
    assert not any(o == "BilbyHub" for _s, _v, o, _k in got)              # no known part relating to it


def test_an_organisations_deployment_role_is_named_after_its_software(ctx):
    from supagent.knowledge.projects import Role

    assert Role("acme.acme-deploy-redis", None).part == "redis"
    assert Role("acme_role_solr", None).part == "solr"
    assert Role("deploy-tools", None).part != "tools"                      # no organisation before it
    assert Role("php-fixes", None).part is None and Role("core_dependencies", None).part is None
