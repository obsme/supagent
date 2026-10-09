"""(0.10.6) The reading of layouts found on a development corpus: a PlantUML box's name is its label's first line and a
box holding other boxes stands for the one it holds (else for no one); an arrow with no word from a scraper monitors,
from a dashboard reads, from a log shipper sends; a VIP table is found by its holder's column ("Keepalived on") when
no header says VIP; a play deploying with its own tasks places the services it starts; a verb inside a part's name
("photo-store") is no verb; the word VIP inside a name (db-vip.example.com) makes no sentence about a VIP, and neither
does a diagram's source."""

from __future__ import annotations

from test_prose_010 import facts

UML = """@startuml
component "Edge\\n(lb-1, lb-2)" as edge {
  component "HAProxy" as haproxy
  component "Keepalived" as keepalived
}
component "Front\\n(web-1)" as front {
  component "shop-web\\n(Node.js :3000)" as shop_web
}
component "orders-api\\n(Java :8080)" as orders_api
component "Prometheus" as prometheus
component "Grafana" as grafana
component "Fluent Bit" as fluent_bit
component "Loki" as loki
component "Alertmanager" as alertmanager
edge --> shop_web : HTTPS
front --> orders_api
prometheus --> orders_api
prometheus --> alertmanager
grafana --> prometheus
fluent_bit --> loki
@enduml
"""


def test_plantuml_names_containers_and_arrow_kinds(ctx):
    from supagent.knowledge import diagrams as G

    edges = [tuple(e[:2]) for d in G.in_text(UML) for e in d["edges"]]
    assert ("shop-web", "orders-api") in edges                     # the box holding one box: that box
    assert not any(a in ("Edge", "edge") for a, _b in edges)       # holding two: no one
    t = facts(UML, parts=("shop-web", "orders-api", "prometheus", "grafana", "fluent-bit", "loki", "alertmanager"))
    assert ("prometheus", "monitors", "orders-api") in t and ("prometheus", "sends_to", "alertmanager") in t
    assert ("grafana", "reads_from", "prometheus") in t and ("fluent-bit", "sends_to", "loki") in t
    assert not any("\\n" in a or "\\n" in b for a, _v, b in t)


def test_a_vip_table_by_its_holder_and_vip_words_in_names(ctx):
    page = ("Name | IP | Target service | Keepalived on\n"
            "www.shop.example.com | 10.1.9.10 | shop-web | lb-1, lb-2\n"
            "db-vip.shop.example.com | 10.1.9.20 | ordersdb | db-1, db-2\n")
    t = facts(page, hosts=("lb-1", "lb-2", "db-1", "db-2"), parts=("shop-web", "ordersdb"))
    assert ("www.shop.example.com", "routes_to", "shop-web") in t and ("lb-1", "in_group", "www.shop.example.com") in t
    assert ("db-vip.shop.example.com", "routes_to", "ordersdb") in t
    assert not any(b == "db-vip.shop.example.com" for a, v, b in t if v == "in_group" and a.startswith("lb-"))


def test_a_verb_inside_a_name_is_no_verb(ctx):
    t = facts("The photo-store keeps the scanned tickets; the orders service calls the billing service.",
              parts=("photo-store", "orders", "billing"))
    assert ("orders", "calls", "billing") in t and not any(a == "photo-store" for a, _v, _b in t)
    t = facts("The orders service stores its receipts in the photo-store.", parts=("photo-store", "orders"))
    assert ("orders", "sends_to", "photo-store") in t


def test_a_play_deploying_with_tasks_places_the_services_it_starts(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.models import Doc, KFact, KUnit

    files = {"inventory/hosts.yml": "all:\n  children:\n    zqapps:\n      hosts:\n        zqapp-1:\n          ansible_host: 10.9.1.5\n",
             "playbooks/apps.yml": "- name: Deploy zqquote and zqledger\n  hosts: zqapps\n  tasks:\n"
                                   "    - name: Deploy zqquote\n      ansible.builtin.copy:\n        src: files/zqquote\n"
                                   "        dest: /opt/zqquote\n    - name: Start zqquote\n      ansible.builtin.systemd:\n"
                                   "        name: zqquote\n        state: started\n    - name: Start zqledger\n"
                                   "      ansible.builtin.systemd:\n        name: zqledger\n        state: started\n"
                                   "    - name: Start chrony\n      ansible.builtin.systemd:\n        name: chronyd\n"
                                   "        state: started\n",
             "site.yml": "---\n# all of it\n---\n- import_playbook: playbooks/apps.yml\n"}
    content, pages, at = [], [], 0
    for path, text in files.items():
        block = f"# {path}\n{text}"
        if content:
            at += 2
        pages.append({"url": f"https://git.example.com/projects/P/repos/zqops/browse/{path}", "title": path,
                      "chars": len(block), "at": at, "path": path, "commit": "c1"})
        content.append(block)
        at += len(block)
    d = Doc(kind="url", url="https://git.example.com/projects/P/repos/zqops/browse", status="ok", enabled=True,
            content="\n\n".join(content), pages=pages)
    db.session.add(d)
    db.session.commit()
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert ("zqquote", "runs_on", "zqapps") in rels and ("zqledger", "runs_on", "zqapps") in rels
        assert not any(a == "chronyd" for a, _k, _b in rels)              # the system's own service: no part
    finally:
        db.session.query(KFact).filter(KFact.unit_id.in_(
            db.session.query(KUnit.id).filter(KUnit.doc_id == d.id))).delete(synchronize_session=False)
        db.session.query(KUnit).filter(KUnit.doc_id == d.id).delete(synchronize_session=False)
        db.session.query(Doc).filter(Doc.id == d.id).delete(synchronize_session=False)
        db.session.commit()


from test_docs_readers import env  # noqa: E402,F401  (the fixture)
