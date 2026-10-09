"""(0.10.4) What a team writes, read better: a denied or past statement is no link, a clause after a colon or a
"which" has its own subject, arrows between parts, a table of hosts, a route ("through the proxy to the app server"),
where a part runs in another language; a monitoring configuration (scrape jobs, alertmanagers, data sources) in its
own files or in a deployment's variables; a Compose service's build folder speaks for it; a list's item stays one."""
from __future__ import annotations

from test_prose_010 import facts
from test_projects_010 import triples, units


def test_a_denied_or_past_statement_is_no_link(ctx):
    t = facts("The frontend never calls the payment service directly: only the checkout does. The old job used to "
              "read from the orders database. The cart does not write to the ledger.",
              parts=("frontend", "payment service", "checkout", "job", "orders database", "cart", "ledger"))
    assert not {x for x in t if not x[1].startswith("not_")}           # no link
    # (0.10.5) kept as denied facts: they propose removing such a link, never make one
    assert {("frontend", "not_calls", "payment service"), ("job", "not_reads_from", "orders database"),
            ("cart", "not_sends_to", "ledger")} <= t


def test_a_clause_after_a_colon_or_a_which_has_its_own_subject(ctx):
    t = facts("When the checkout fails, look at the payment service first: the checkout service calls the payment "
              "service for every order, then the email service. The frontend calls the cart, which calls the stock.",
              parts=("checkout service", "payment service", "email service", "frontend", "cart", "stock"))
    assert {("checkout service", "calls", "payment service"), ("checkout service", "calls", "email service"),
            ("frontend", "calls", "cart"), ("cart", "calls", "stock")} <= t
    assert not any(s == "payment service" for s, _v, _o in t) and ("frontend", "calls", "stock") not in t


def test_arrows_between_parts(ctx):
    text = ("- shopper → frontend → checkout → payment\n- Prometheus → Alertmanager (the alerts)\n"
            "- Grafana ← Prometheus (its data source)\n- jibri on rec-01 -> object store; genai -> object store\n"
            "The end.")
    t = facts(text, parts=("frontend", "checkout", "payment", "Prometheus", "Alertmanager", "Grafana", "jibri", "genai"))
    assert {("frontend", "calls", "checkout"), ("checkout", "calls", "payment"),
            ("Prometheus", "sends_to", "Alertmanager"), ("Grafana", "reads_from", "Prometheus")} <= t
    assert ("jibri", "calls", "genai") not in t and ("frontend", "calls", "payment") not in t


def test_a_table_of_hosts_says_where_its_parts_run(ctx):
    text = "Host | Role | Services\nshop-vm-01 | shop front | reverse_proxy, appserver\nshop-vm-02 | shop back | db\n"
    t = facts(text, parts=("reverse_proxy", "appserver", "db"))
    assert t == {("reverse_proxy", "runs_on", "shop-vm-01"), ("appserver", "runs_on", "shop-vm-01"),
                 ("db", "runs_on", "shop-vm-02")}


def test_a_route_through_a_part(ctx):
    t = facts("Requests go through the reverse proxy (nginx) to the app server; the app server keeps the orders in the "
              "shop database and charges the cards through the payment gateway.",
              parts=("reverse proxy", "app server", "shop database", "payment gateway"))
    assert {("reverse proxy", "calls", "app server"), ("app server", "sends_to", "shop database"),
            ("app server", "calls", "payment gateway")} <= t
    assert ("app server", "sends_to", "payment gateway") not in t


def test_where_a_part_runs_in_another_language(ctx):
    t = facts("La pasarela de pago (gateway) de la tienda se ejecuta en shop-vm-02. Le collecteur tourne sur obs-01.",
              parts=("gateway", "collecteur"))
    assert {("gateway", "runs_on", "shop-vm-02"), ("collecteur", "runs_on", "obs-01")} <= t


def test_a_list_item_does_not_run_into_the_next_paragraph(ctx):
    from supagent.knowledge.understand import _sentences

    text = "Intro of it\n- A → B (the alerts)\nThe blackbox probes the proxy.\n- an item\n  wrapped on two lines"
    got = [(at, s) for at, s in _sentences(text)]
    assert [s for _a, s in got] == ["Intro of it", "- A → B (the alerts)", "The blackbox probes the proxy.",
                                   "- an item wrapped on two lines"]
    assert all(text[at:at + 6] == s[:6] for at, s in got)          # positions as in the text


def _monitoring(text, parts, homes=None, me=None):
    from supagent.knowledge.understand import Names, _monitoring, norm

    n = Names()
    for p in parts:
        n.add_part(p)
    n.homes = {norm(k): v for k, v in (homes or {}).items()}
    return {(s, v, o) for s, v, o, _at in _monitoring(text, n, {}, me)}


VARS = """
prometheus_alertmanager_config:
  - static_configs:
      - targets: ["{{ ansible_host }}:9093"]
prometheus_targets:
  node:
    - targets: ["{{ ansible_host }}:9100"]
  grafana:
    - targets: ["{{ ansible_host }}:3000"]
prometheus_scrape_configs:
  - job_name: prometheus
    static_configs: [{targets: ["{{ ansible_host }}:9090"]}]
  - job_name: blackbox
    metrics_path: /probe
  - job_name: other-site
    static_configs: [{targets: ["status.example.org"]}]
grafana_datasources:
  - name: Prometheus
    type: prometheus
    url: "http://{{ ansible_host }}:9090"
"""


def test_a_deployments_monitoring_variables(ctx):
    t = _monitoring(VARS, ("prometheus", "alertmanager", "grafana", "node-exporter", "blackbox-exporter"))
    assert t == {("prometheus", "sends_to", "alertmanager"), ("prometheus", "monitors", "node-exporter"),
                 ("prometheus", "monitors", "grafana"), ("prometheus", "monitors", "blackbox-exporter"),
                 ("grafana", "reads_from", "prometheus")}


def test_a_monitoring_file_of_its_own_and_the_part_beside_it(ctx):
    prom = "scrape_configs:\n  - job_name: prometheus\n  - job_name: api\n    static_configs: [{targets: ['api-gw:8080']}]\n"
    assert _monitoring(prom, ("prometheus-server", "prometheus", "api-gw"), me="prometheus-server") == \
        {("prometheus-server", "monitors", "api-gw")}             # its own job is no other Prometheus
    ds = "datasources:\n  - name: x\n    type: prometheus\n    url: '{{ url }}'\n"
    homes = {"store-grafana": {1}, "store-prometheus": {1}, "prometheus": {2}, "prometheus-server": {3}}
    assert _monitoring(ds, ("store-grafana", "store-prometheus", "prometheus", "prometheus-server"), homes,
                       me="store-grafana") == {("store-grafana", "reads_from", "store-prometheus")}


def test_yaml_with_a_masked_secret_name_is_still_yaml(ctx):
    from supagent.knowledge.projects import _yaml

    data = _yaml("services:\n  db:\n    image: postgres\nsecrets:\n  ***:\n    file: ***\n")
    assert data["services"]["db"]["image"] == "postgres" and data["secrets"]["***"]["file"] == "***"


def test_a_compose_services_build_folder_speaks_for_it(ctx):
    from supagent.knowledge import projects as P

    files = {"docker-compose.yml": "services:\n  proxy:\n    build: ./proxy\n  app:\n    build:\n      context: app\n"
                                   "  db:\n    image: postgres\n  web:\n    build: .\n",
             "proxy/nginx.conf": "proxy_pass http://app:8080;", "app/src/application.yml": "x: 1",
             "README.md": "# shop", "docker-stack.yml": "services:\n  viz:\n    image: viz\n"}
    _facts, names = P.facts(units(files))
    assert names["built"] == {"proxy/nginx.conf": "proxy", "app/src/application.yml": "app"}
    assert "viz" in names["parts"]                                  # a Swarm stack file is read as Compose


def test_a_roles_part_without_ansibles_words_and_an_exporter_is_no_language(ctx):
    from supagent.knowledge import projects as P

    assert P.Role("caddy_ansible.caddy_ansible", None).part == "caddy"
    assert P.Role("ansible-role-nginx", None).part == "nginx"
    assert P.Role("cloudalchemy.node-exporter", None).part == "node-exporter"
    assert P.Role("python-pip", None).part is None and P.Role("nodejs-16", None).part is None
    assert P.Role("geerlingguy.php-mysql", None).part is None and P.Role("node-red", None).part == "node-red"


def test_a_play_on_all_hosts_puts_its_part_on_each(ctx):
    from supagent.knowledge import projects as P

    files = {"site.yml": "- hosts: all\n  roles: [vendor.node-exporter]\n- hosts: mon\n  roles: [vendor.prometheus]\n",
             "hosts": "demo\n[mon]\ndemo\n"}
    t = triples(P.facts(units(files))[0])
    assert ("node-exporter", "runs_on", "demo") in t and ("prometheus", "runs_on", "mon") in t


def test_a_files_own_name_comes_from_its_package_file_only(ctx):
    from supagent.knowledge.understand import discover

    dash = discover({"path": "grafana/dashboards/app.json", "title": "", "text": '{\n  "panels": [\n    {"name": "x"}],'
                     '\n  "name": "Prometheus"\n}'})
    pkg = discover({"path": "web/package.json", "title": "", "text": '{\n  "name": "shopping-cart",\n  "deps": {"name": "y"}\n}'})
    pom = discover({"path": "pom.xml", "title": "", "text": "<project><parent><artifactId>spring-parent</artifactId>"
                    "</parent><artifactId>atsea</artifactId></project>"})
    assert dash["names"] == [] and pkg["names"] == ["shopping-cart"] and pom["names"] == ["atsea"]


def test_a_pages_list_items_are_kept_apart(ctx):
    from supagent.knowledge.docs import html_to_text

    _title, text, _links = html_to_text("<ul><li>A → B</li><li>B → C</li></ul><p>The end.</p>")
    assert text.splitlines() == ["- A → B", "- B → C", "The end."]
