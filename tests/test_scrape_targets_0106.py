"""(0.10.6) A Prometheus job's targets are the names in its targets' list (a flow list or a block list, quoted or
not), never a label's value nor a template's expression ("instance: {{ hostvars[host]['ansible_facts'] }}" names no
server); a job named after a part runs on the hosts it scrapes, never on another part (a Compose service as a
target, "otel:9464")."""

from __future__ import annotations


def _facts(text):
    from supagent.knowledge.understand import Names, discover, facts_of

    u = {"ukey": "f1", "path": "prometheus/prometheus.yml", "kind": "file", "title": "prometheus.yml", "text": text,
         "meta": {}}
    u["found"] = discover(u)
    return {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, None, Names(), {})}


def test_the_targets_list_only(ctx):
    t = _facts("scrape_configs:\n  - job_name: node\n    static_configs:\n      - targets: ['app-1:9100', 'db-1:9100']\n"
               "        labels:\n          env: 'prod'\n          instance: \"{{ hostvars[host]['ansible_facts']['nodename'] }}\"\n"
               "  - job_name: 'postgres'\n    static_configs:\n      - targets:\n          - 'db-01.example.net:9187'\n"
               "          - db-02.example.net:9187\n")
    assert {("node", "scrapes", "app-1"), ("node", "scrapes", "db-1"), ("postgres", "scrapes", "db-01.example.net"),
            ("postgres", "scrapes", "db-02.example.net")} <= t
    assert not any(o in ("prod", "ansible_facts", "nodename", "hostvars") for _s, _v, o in t)


def test_a_part_scraped_is_no_host_of_the_job(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.models import Doc, KFact, KUnit

    compose = ("services:\n  collector:\n    image: otel/opentelemetry-collector\n    command: [\"--config=/etc/c.yaml\"]\n"
               "  shop:\n    image: shop:1\n    environment:\n      OTEL_EXPORTER_OTLP_ENDPOINT: http://collector:4317\n"
               "  prometheus:\n    image: prom/prometheus\n")
    prom = ("scrape_configs:\n  - job_name: 'prometheus'\n    static_configs:\n"
            "      - targets: [\"shop:8080\", \"collector:9464\"]\n")
    content = f"# docker-compose.yml\n{compose}\n\n# prometheus/prometheus.yml\n{prom}"
    pages = [{"url": "https://git.example.com/projects/P/repos/zqshop/browse/docker-compose.yml", "title": "docker-compose.yml",
              "chars": len(f"# docker-compose.yml\n{compose}"), "at": 0, "path": "docker-compose.yml", "commit": "c1"},
             {"url": "https://git.example.com/projects/P/repos/zqshop/browse/prometheus/prometheus.yml",
              "title": "prometheus/prometheus.yml", "chars": len(f"# prometheus/prometheus.yml\n{prom}"),
              "at": len(f"# docker-compose.yml\n{compose}") + 2, "path": "prometheus/prometheus.yml", "commit": "c1"}]
    d = Doc(kind="url", url="https://git.example.com/projects/P/repos/zqshop/browse", status="ok", enabled=True,
            content=content, pages=pages)
    db.session.add(d)
    db.session.commit()
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert not any(a == "prometheus" and k == "runs_on" and b in ("collector", "shop") for a, k, b in rels)
    finally:
        db.session.query(KFact).filter(KFact.unit_id.in_(
            db.session.query(KUnit.id).filter(KUnit.doc_id == d.id))).delete(synchronize_session=False)
        db.session.query(KUnit).filter(KUnit.doc_id == d.id).delete(synchronize_session=False)
        db.session.query(Doc).filter(Doc.id == d.id).delete(synchronize_session=False)
        db.session.commit()


from test_docs_readers import env  # noqa: E402,F401  (the fixture)
