"""(0.10.5) An address naming a server or a VIP is the service there whose technology its line says: an env file
(read as configuration, a template's too) with "redis://:{{ pw }}@cache-1", "amqp://app:{{ pw }}@mq-1",
"PAYMENT_ADAPTER_URL=http://app-1:8080", a scrape target "cache-1:9121", a VIP's own service; a templated password
keeps the address whole; a fully qualified name is the inventory's host; an upstream "orders_backend" is orders; what
holds a VIP is never behind it; "query X via Y" is a step, "X collects the logs via Y" is Y sending to X."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_prose_010 import facts

REPO = {
    "inventory/hosts": "[cache]\ncache-1 ansible_host=10.1.0.5\n\n[brokers]\nmq-1 ansible_host=10.1.0.6\n\n"
                       "[app]\napp-1 ansible_host=10.1.0.7\n\n[mon]\nmon-1 ansible_host=10.1.0.8\n\n"
                       "[prod:children]\ncache\nbrokers\napp\nmon\n",
    "site.yml": "- hosts: cache\n  roles: [redis]\n\n- hosts: brokers\n  roles: [rabbitmq]\n\n- hosts: app\n"
                "  roles: [orders, payment_adapter]\n\n- hosts: mon\n  roles: [prometheus]\n\n- hosts: all\n"
                "  roles: [node_exporter]\n",
    "roles/orders/templates/orders.env.j2": "# orders service\nREDIS_URL=redis://:{{ redis_password }}@cache-1.corp.example:6379/0\n"
                                            "AMQP_URL=amqp://orders:{{ mq_password }}@mq-1.corp.example:5672/orders\n"
                                            "PAYMENT_ADAPTER_URL=http://app-1.corp.example:8080\n",
    "roles/prometheus/templates/prometheus.yml.j2": "scrape_configs:\n  - job_name: redis\n    static_configs:\n"
                                                    "      - targets: ['cache-1.corp.example:9121']\n",
}


def _repo(files):
    from superset.extensions import db

    from supagent.models import Doc

    content, pages, at = [], [], 0
    for path, text in files.items():
        block = f"# {path}\n{text}"
        if content:
            at += 2
        pages.append({"url": f"https://git.example.com/projects/P/repos/ops/browse/{path}", "title": path,
                      "chars": len(block), "at": at, "path": path, "commit": "c1"})
        content.append(block)
        at += len(block)
    d = Doc(kind="url", url="https://git.example.com/projects/P/repos/ops/browse", status="ok", enabled=True,
            content="\n\n".join(content), pages=pages)
    db.session.add(d)
    db.session.commit()
    return d


def test_an_address_naming_a_server_is_the_service_there_its_line_says(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.models import Doc, KFact, KUnit

    d = _repo(REPO)
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert any(a == "orders" and b == "redis" for a, _k, b in rels)                 # redis://...@cache-1
        assert any(a == "orders" and b == "rabbitmq" for a, _k, b in rels)              # amqp://orders:{{ pw }}@mq-1
        assert ("orders", "calls", "payment_adapter") in rels                           # the key names it
        assert ("prometheus", "monitors", "redis") in rels                              # cache-1:9121
        assert not any(b in ("orders", "{{") for a, _k, b in rels if a == "orders")     # the user is no host
        assert not any(b == "node_exporter" for a, k, b in rels if a == "orders")      # what runs everywhere: never
    finally:
        db.session.query(KFact).filter(KFact.unit_id.in_(
            db.session.query(KUnit.id).filter(KUnit.doc_id == d.id))).delete(synchronize_session=False)
        db.session.query(KUnit).filter(KUnit.doc_id == d.id).delete(synchronize_session=False)
        db.session.query(Doc).filter(Doc.id == d.id).delete(synchronize_session=False)
        db.session.commit()


def test_holders_upstreams_steps_and_receivers(ctx):
    from supagent.knowledge.understand import USERINFO_TPL, lang_of

    assert lang_of("roles/app/templates/app.env.j2") == "dotenv" and lang_of(".env.example") == "dotenv"
    masked = USERINFO_TPL.sub(lambda t: t.group(1) + "x" * len(t.group(2)), "postgresql://app:{{ db_pw }}@db-1:5432/x")
    assert masked.startswith("postgresql://app:") and masked.endswith("@db-1:5432/x") and "{" not in masked
    t = facts("Query Loki on the monitoring server via Grafana. Loki collects the logs of every node via promtail. "
              "The orders VIP is managed by keepalived.", parts=("Loki", "Grafana", "promtail", "keepalived"))
    assert ("Loki", "sends_to", "Grafana") not in t and ("Loki", "calls", "Grafana") not in t
    assert ("promtail", "sends_to", "Loki") in t and ("Loki", "sends_to", "promtail") not in t
    assert not any(v == "routes_to" and o == "keepalived" for _s, v, o in t)
