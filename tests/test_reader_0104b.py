"""(0.10.4) The learning's second round (a held-out corpus, then development material): a subject comes before its
verb and is the part right before it when there is one, a misspelled part is still that part, a common word in
another repository's file is a word, a noun is no verb ("a POST call to", "the bootstrap checks"), alternatives are
no fact, a queue drawn as the start of an arrow is read from; public addresses, license and reference addresses,
${X_HOST} placeholders; Monit's checks, Caddy's upstreams, the Beats' targets; Compose folders mounted or shared,
an extension's file; an Ansible role's services, the databases it makes accounts in, the web site it publishes."""
from __future__ import annotations

from test_prose_010 import facts
from test_projects_010 import triples, units


def test_a_subject_comes_before_its_verb_and_is_the_part_right_before_it(ctx):
    t = facts("Our collector scrapes the node exporter every minute. Metricbeat watches Elasticsearch, Logstash and "
              "Kibana themselves, and Heartbeat pings Elasticsearch every 5 seconds. Payment puts every order on the "
              "queue and dispatch takes it off.",
              parts=("node exporter", "Metricbeat", "Elasticsearch", "Logstash", "Kibana", "Heartbeat", "Payment",
                     "queue", "dispatch"))
    assert {("Metricbeat", "monitors", "Elasticsearch"), ("Metricbeat", "monitors", "Logstash"),
            ("Metricbeat", "monitors", "Kibana"), ("Heartbeat", "monitors", "Elasticsearch"),
            ("Payment", "sends_to", "queue")} <= t
    assert not any(o in ("Heartbeat", "dispatch") or s == "node exporter" for s, _v, o in t)


def test_a_misspelled_part_is_that_part_and_a_plural_is_not(ctx):
    t = facts("Promethues scrapes cadvisor and the pushgateway. The payments go through the gateway.",
              parts=("prometheus", "cadvisor", "pushgateway", "payment", "gateway"))
    assert {("prometheus", "monitors", "cadvisor"), ("prometheus", "monitors", "pushgateway")} <= t
    assert not any(s == "payment" for s, _v, _o in t)


def test_a_noun_or_an_alternative_is_no_statement(ctx):
    t = facts("You can reload the rules by making a HTTP POST call to Prometheus. Set ERROR to 1 to have erroneous "
              "calls made to the payment service. Elasticsearch's bootstrap checks were disabled for the setup. "
              "Filebeat forwards the events either to Elasticsearch or to Logstash.",
              parts=("Prometheus", "payment service", "Elasticsearch", "setup", "Filebeat", "Logstash"))
    assert not t


def test_other_verbs_of_a_call_and_of_a_check(ctx):
    t = facts("Cart asks the catalogue for each line. Ratings checks every SKU against the catalogue. Shipping depends "
              "upon MySQL. The cart also looks up the catalogue.", parts=("Cart", "catalogue", "Ratings", "Shipping",
                                                                         "MySQL"))
    assert {("Cart", "calls", "catalogue"), ("Ratings", "calls", "catalogue"), ("Shipping", "calls", "MySQL")} <= t
    assert not any(v == "monitors" for _s, v, _o in t)


def test_a_queue_at_the_start_of_an_arrow_is_read_from(ctx):
    t = facts("- payment → rabbitmq → dispatch\nThe end of it.", parts=("payment", "rabbitmq", "dispatch"))
    assert ("payment", "calls", "rabbitmq") in t and ("dispatch", "reads_from", "rabbitmq") in t
    assert ("rabbitmq", "calls", "dispatch") not in t


def test_a_common_word_of_another_repository_is_a_word(ctx):
    from supagent.knowledge.understand import Names, _named, norm

    n = Names()
    for p in ("user", "mailserver", "payment-gateway"):
        n.add_part(p)
    n.homes = {norm("user"): {1}, norm("mailserver"): {2}, norm("payment-gateway"): {1}}
    said = "Dovecot delivers to the user mailbox; the mailserver calls payment-gateway"
    assert [w for _a, w, _p in _named(said, n, {}, home=2)] == ["mailserver", "payment-gateway"]
    assert [w for _a, w, _p in _named(said, n, {}, home=1)] == ["user", "mailserver", "payment-gateway"]
    assert len(_named(said, n, {})) == 3                       # a page of the wiki: every part


def _code(path, text, owner, parts=(), hosts=()):
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    n = Names()
    for p in parts:
        n.add_part(p)
    for h in hosts:
        n.hosts[norm(h)] = h
    u = {"ukey": path, "path": path, "kind": "file", "title": path, "text": text, "meta": {}}
    u["found"] = discover(u)
    return {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, owner, n, {})}


def test_addresses_public_placeholders_licenses_and_references(ctx):
    conf = ("receivers:\n  - api_url: 'https://hooks.slack.com/services/x'\n"
            "upstream: http://${CATALOGUE_HOST}:8080/\nother: http://${UNKNOWN_HOST}:80/\n"
            "check: egrep '^http://[a-z0-9]+'\n# License: http://www.opensource.org/licenses/mit-license.php\n"
            "docs: See http://project.example-search.org/algorithms.html for the details\n")
    t = _code("conf/app.yml", conf, "web", parts=("web", "catalogue"))
    assert ("web", "calls", "slack") in t and ("web", "calls", "catalogue") in t
    assert not any(o in ("hooks", "a-z0-9", "opensource", "example-search", "unknown") for _s, _v, o in t)
    assert not _code("var_www_app_composer.json", '{"url": "https://git.vendor.org/lib.git"}', "web", parts=("git",))


def test_monit_checks_caddy_upstreams_and_beats_targets(ctx):
    assert _code("roles/monitoring/files/etc_monit_conf.d_postfix",
                 "check process postfix with pidfile /run/postfix.pid\n  group mail\n", "monitoring",
                 parts=("monitoring", "postfix")) == {("monitoring", "monitors", "postfix")}
    assert _code("caddy/Caddyfile", ":3000 {\n    reverse_proxy grafana:3000\n}\n:9090 {\n    reverse_proxy prometheus:9090"
                 "\n}\n", "caddy", parts=("caddy", "grafana", "prometheus")) == \
        {("caddy", "calls", "grafana"), ("caddy", "calls", "prometheus")}
    beats = ("metricbeat.modules:\n- module: logstash\n  hosts: [ http://logstash:9600 ]\n"
             "heartbeat.monitors:\n- type: icmp\n  hosts:\n    - elasticsearch\n")
    t = _code("metricbeat/config/metricbeat.yml", beats, "metricbeat", parts=("metricbeat", "logstash", "elasticsearch"))
    assert {("metricbeat", "monitors", "logstash"), ("metricbeat", "monitors", "elasticsearch")} <= t


def test_a_readme_with_an_example_configuration_is_no_tool(ctx):
    from supagent.knowledge.understand import discover

    md = "# Stack\n```\nroute:\n  receiver: x\nreceivers:\n  - name: x\n```\n"
    assert discover({"path": "README.md", "title": "", "text": md})["tool"] is None
    assert discover({"path": "alertmanager/config.yml", "title": "", "text": md[11:-4]})["tool"] == "alertmanager"


def test_compose_folders_mounted_shared_or_from_an_extension(ctx):
    from supagent.knowledge import projects as P

    files = {"docker-compose.yml": "services:\n  kibana-keys:\n    build:\n      context: kibana/\n  kibana:\n    build:\n"
                                   "      context: kibana/\n  prom:\n    image: prom\n    volumes:\n"
                                   "      - ./prometheus:/etc/prometheus\n      - data:/prometheus\n",
             "kibana/config/kibana.yml": "x: 1", "prometheus/prometheus.yml": "x: 1",
             "extensions/beat/beat-compose.yml": "services:\n  beat:\n    build:\n      context: extensions/beat/\n",
             "extensions/beat/config/beat.yml": "x: 1"}
    _f, names = P.facts(units(files))
    assert names["built"] == {"kibana/config/kibana.yml": "kibana", "prometheus/prometheus.yml": "prom",
                              "extensions/beat/config/beat.yml": "beat"}


ROLES = {
    "site.yml": "- hosts: all\n  roles: [common, mailserver, news, blog, db]\n",
    "hosts": "[box]\nhost-1\n",
    "roles/common/tasks/main.yml": "- apt: name=postgresql\n- service: name=postgresql state=started\n",
    "roles/mailserver/tasks/main.yml": "- postgresql_user: name=mail\n- service: name=postfix state=started\n"
                                       "- service: name=dovecot state=started\n",
    "roles/news/tasks/main.yml": "- postgresql_db: name=news\n- git: repo=https://example.org/selfoss.git dest=/var/www\n",
    "roles/blog/tasks/main.yml": "- copy: src=index.html dest=/var/www/blog\n",
    "roles/blog/templates/etc_apache2_sites-available_blog.j2": "<VirtualHost *:80></VirtualHost>",
    "roles/db/tasks/main.yml": "- mysql_db: name=app\n- service: name=mysql state=started\n",
}


def test_an_ansible_roles_services_databases_and_web_site(ctx):
    from supagent.knowledge import projects as P

    found, names = P.facts(units(ROLES))
    t = triples(found)
    assert {("mailserver", "uses", "postgresql"), ("news", "uses", "postgresql"), ("blog", "runs_on", "host-1")} <= t
    assert not any(s == "db" and v == "uses" for s, v, _o in t)       # the database's own role: no client of itself
    assert names["aliases"] == {"postfix": "mailserver", "dovecot": "mailserver", "mysql": "db"}


def test_a_roles_files_and_a_caddyfile_are_read(ctx):
    from supagent.knowledge.docs import wanted_file

    assert wanted_file("roles/monitoring/files/etc_monit_conf.d_postfix", "code")
    assert not wanted_file("roles/x/files/etc_ssl_private_server_key", "code") and not wanted_file("roles/x/files/secret", "code")
    assert wanted_file("caddy/Caddyfile", "code")
    assert not wanted_file("roles/monitoring/files/etc_monit_conf.d_postfix", "docs")
