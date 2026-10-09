"""(0.10.6) What the reader proposes for the System map, from the lab's demonstration map of 8 October: a subject is
a topic, never a link's end ("ceph-mon (subject) runs on stor-mon-01", "Other (subject) reads from config-server");
a subject the AI proposed with the name of a part the code names is that part; an inventory's group named like a
subject is the group "monitoring (group)"; a repository's tests, fixtures and examples are no fact of the map
("mon0 part of ceph-monitoring" from tests/functional/all_daemons/hosts); a scrape job's target that a file of the
repository defines as a service is no host ("prometheus runs on otel" from targets: ["otel:9464"])."""

from __future__ import annotations

import pytest
from test_docs_readers import env  # noqa: F401  (the fixture)
from test_projects_010 import triples, units


def test_the_tests_fixtures_and_examples_of_a_repository_are_no_fact(ctx):
    from supagent.knowledge.projects import facts, test_file

    files = {"inventory/hosts": "[web]\nweb-1\n",
             "site.yml": "- hosts: web\n  roles: [zq-shop]\n- hosts: mons\n  roles: [zq-mon]\n",
             "roles/zq-shop/tasks/main.yml": "- service: name=zq-shop state=started\n",
             "roles/zq-mon/tasks/main.yml": "- service: name=zq-mon state=started\n",
             "tests/functional/all/hosts": "[web]\nmon0\n\n[mons]\nmon0\n",
             "tests/functional/all/site.yml": "- hosts: mons\n  roles: [zq-shop]\n",
             "molecule/default/converge.yml": "- hosts: all\n  roles: [zq-shop]\n",
             "examples/compose/docker-compose.yml": "services:\n  zq-demo:\n    image: nginx\n    depends_on: [zq-api]\n"
                                                    "  zq-api:\n    image: zq/api\n"}
    found, names = facts(units(files))
    t = triples(found)
    assert ("web-1", "in_group", "web") in t and ("zq-shop", "runs_on", "web") in t
    assert not any("mon0" in (s, o) for s, _v, o in t)
    # a play's group the inventory has not, named by the tests' inventories: the group, none of their hosts
    assert ("zq-mon", "runs_on", "mons") in t and ("zq-shop", "runs_on", "mons") not in t
    assert "zq-demo" not in names["parts"] and "mon0" not in names["hosts"]
    assert test_file("tests/functional/all/hosts") and test_file("a/molecule/default/converge.yml")
    assert not test_file("latest/hosts") and not test_file("roles/contest/tasks/main.yml") and not test_file("hosts")


def _repo(name: str, files: dict[str, str]):
    from supagent.models import Doc

    content, pages, at = [], [], 0
    for path, text in files.items():
        block = f"# {path}\n{text}"
        if content:
            at += 2
        pages.append({"url": f"https://git.example.com/projects/P/repos/{name}/browse/{path}", "title": path,
                      "chars": len(block), "at": at, "path": path, "commit": "c1"})
        content.append(block)
        at += len(block)
    return Doc(kind="url", url=f"https://git.example.com/projects/P/repos/{name}/browse", status="ok", enabled=True,
               content="\n\n".join(content), pages=pages)


@pytest.fixture()
def topics(env):  # noqa: F811
    """A repository of Ansible whose names are subjects too: one the AI proposed ("zq-mon", with an item), one a
    person approved ("zq-topic"), a group named like the AI's subject "monitoring"."""
    from superset.extensions import db

    from supagent.models import Facet, KFact, KUnit, Link, Tag

    env["categories.custom"] = ["server"]
    doc = _repo("zq-deploy", {
        "hosts": "[mons]\nmon-1\n\n[monitoring]\nmgmt-1\n",
        "site.yml": "- hosts: mons\n  roles: [zq-mon, zq-topic]\n- hosts: monitoring\n  roles: [zq-dash]\n",
        "roles/zq-mon/tasks/main.yml": "- service: name=zq-mon state=started\n",
        "roles/zq-topic/tasks/main.yml": "- service: name=zq-topic state=started\n",
        "roles/zq-dash/tasks/main.yml": "- service: name=zq-dash state=started\n"})
    ai = Facet(facet="subject", value="zq-mon", status="proposed", source="llm")
    watch = Facet(facet="subject", value="monitoring", status="proposed", source="llm")
    mine = Facet(facet="subject", value="zq-topic", status="approved", source="admin")
    db.session.add_all([doc, ai, watch, mine])
    db.session.commit()
    db.session.add(Tag(ref="entry:987654", facet_id=ai.id, source="llm", status="proposed", confidence=0.9))
    db.session.commit()
    made = [ai.id, watch.id, mine.id]
    yield {"ai": ai.id, "watch": watch.id, "mine": mine.id}
    db.session.rollback()
    ids = made + [f.id for f in db.session.query(Facet).filter(Facet.source == "docs")]
    refs = [f"facet:{i}" for i in ids]
    db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
    db.session.query(Tag).filter(Tag.facet_id.in_(ids)).delete(synchronize_session=False)
    db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
    unit_ids = [u.id for u in db.session.query(KUnit.id).filter(KUnit.doc_id == doc.id)]
    db.session.query(KFact).filter(KFact.unit_id.in_(unit_ids or [-1])).delete(synchronize_session=False)
    db.session.query(KUnit).filter(KUnit.doc_id == doc.id).delete(synchronize_session=False)
    db.session.commit()


def test_a_subject_is_no_end_of_a_link_and_the_ais_subject_is_the_part(topics):
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet, Link, Tag

    U.run(reason="test")
    out = propose()
    vals = {(f.facet, f.value): f for f in db.session.query(Facet).filter(Facet.value.like("%")) if
            f.value.startswith(("zq-", "mon", "mgmt"))}
    # the AI's subject "zq-mon": the part the code names, with its item
    assert db.session.get(Facet, topics["ai"]) is None and out.get("subjects the AI proposed: the part") == 1
    part = vals[("application", "zq-mon")]
    assert db.session.query(Tag).filter(Tag.ref == "entry:987654", Tag.facet_id == part.id).count() == 1
    group = vals[("server", "mons")]
    assert db.session.query(Link).filter(Link.a_ref == f"facet:{part.id}", Link.b_ref == f"facet:{group.id}",
                                         Link.kind == "runs_on").count() == 1
    # a person's subject stays a subject: no part, no link of it
    assert ("application", "zq-topic") not in vals and db.session.get(Facet, topics["mine"]).facet == "subject"
    assert out.get("a subject's name: no part", 0) >= 1
    refs = {f"facet:{topics['mine']}", f"facet:{topics['watch']}"}
    assert db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).count() == 0
    # the group named like a subject: "monitoring (group)", the subject left as it is
    assert ("server", "monitoring (group)") in vals and db.session.get(Facet, topics["watch"]).facet == "subject"
    mgmt = vals[("server", "mgmt-1")]
    assert db.session.query(Link).filter(Link.a_ref == f"facet:{mgmt.id}", Link.kind == "part_of",
                                         Link.b_ref == f"facet:{vals[('server', 'monitoring (group)')].id}").count() == 1


def test_a_part_and_a_subject_of_one_name_the_link_is_the_parts(topics, env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet, Link

    env["categories.custom"] = ["server", "zpart"]       # a category read after "subject" (the order rows come in)
    app = Facet(facet="zpart", value="zq-topic", status="approved", source="admin")
    db.session.add(app)
    db.session.commit()
    try:
        U.run(reason="test")
        propose()
        group = db.session.query(Facet).filter(Facet.value == "mons", Facet.facet == "server").one()
        assert db.session.query(Link).filter(Link.a_ref == f"facet:{app.id}", Link.b_ref == f"facet:{group.id}",
                                             Link.kind == "runs_on").count() == 1
        assert db.session.get(Facet, topics["mine"]).facet == "subject"          # a person's subject: kept
    finally:
        db.session.rollback()
        db.session.query(Link).filter(Link.a_ref == f"facet:{app.id}").delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id == app.id).delete(synchronize_session=False)
        db.session.commit()


def test_a_subject_is_no_part_a_text_names(ctx):
    from superset.extensions import db

    from supagent.knowledge.understand import known_names
    from supagent.models import Facet

    rows = [Facet(facet="subject", value="zqother", status="approved", source="seed"),
            Facet(facet="application", value="zqconfig", status="approved", source="admin")]
    db.session.add_all(rows)
    db.session.commit()
    try:
        n = known_names()
        assert n.part("zqconfig") == "zqconfig" and n.part("zqother") is None
    finally:
        for f in rows:
            db.session.delete(f)
        db.session.commit()


def test_a_scrape_target_a_file_defines_as_a_service_is_no_host(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.models import Facet, KFact, KUnit

    doc = _repo("zq-meet", {
        "docker-compose.yml": "services:\n  zq-prom:\n    image: prom/prometheus\n    volumes:\n"
                              "      - ./prometheus:/etc/prometheus\n  zq-bridge:\n    image: zq/bridge\n",
        "log-analyser.yml": "services:\n  zq-otel:\n    image: otel/opentelemetry-collector-contrib\n",
        "prometheus/prometheus.yml": "scrape_configs:\n  - job_name: \"zq-prom\"\n    static_configs:\n"
                                     "      - targets: [\"zq-bridge:8080\", \"zq-otel:9464\"]\n"})
    prom = Facet(facet="component", value="zq-prom", status="approved", source="admin")
    db.session.add_all([doc, prom])
    db.session.commit()
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert not any(k == "runs_on" and a == "zq-prom" for a, k, _b in rels)
    finally:
        db.session.rollback()
        unit_ids = [u.id for u in db.session.query(KUnit.id).filter(KUnit.doc_id == doc.id)]
        db.session.query(KFact).filter(KFact.unit_id.in_(unit_ids or [-1])).delete(synchronize_session=False)
        db.session.query(KUnit).filter(KUnit.doc_id == doc.id).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id == prom.id).delete(synchronize_session=False)
        db.session.commit()


def test_where_a_part_runs_ends_where_the_sentence_says_something_else(ctx):
    """"The indexer running on the app group is responsible for reading from the DB and pushing to the search": it
    runs on the app group, reads from the database, pushes to the search; the DB is no place it runs on (a demo map
    proposed "indexer runs on db")."""
    from test_prose_010 import facts

    t = facts("The zq-indexer running on the zqapp group is responsible for reading from the zqdb and pushing to "
              "zq-search. If this is stuck, no new data gets indexed.", hosts=("zqapp", "zqdb"),
              parts=("zq-indexer", "zq-search"))
    assert ("zq-indexer", "runs_on", "zqapp") in t and ("zq-indexer", "runs_on", "zqdb") not in t
    assert ("zq-indexer", "sends_to", "zq-search") in t


def test_promtail_ships_logs_and_monitors_nothing(env):  # noqa: F811
    """(0.10.6) Promtail's configuration has scrape_configs too: its jobs, named after the services whose logs it
    reads, are no monitoring ("promtail monitors zq-api" was proposed); a Prometheus configuration still is."""
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.models import Facet, KFact, KUnit

    doc = _repo("zq-logs", {
        "roles/zq-promtail/templates/promtail.yml.j2":
            "server:\n  http_listen_port: 9080\npositions:\n  filename: /tmp/positions.yaml\nclients:\n"
            "  - url: http://zq-loki:3100/loki/api/v1/push\nscrape_configs:\n  - job_name: zq-api\n"
            "    static_configs:\n      - targets: [localhost]\n        labels:\n          __path__: /var/log/zq-api/*.log\n",
        "roles/zq-prom/templates/prometheus.yml.j2":
            "scrape_configs:\n  - job_name: zq-api\n    static_configs:\n      - targets: ['zq-api:8080']\n"})
    made = [Facet(facet="component", value=v, status="approved", source="admin") for v in ("zq-promtail", "zq-prom",
                                                                                            "zq-api", "zq-loki")]
    db.session.add_all([doc, *made])
    db.session.commit()
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert not any(a == "zq-promtail" and k == "monitors" for a, k, _b in rels), rels
        tools = {u.ukey.rsplit("/", 1)[-1]: ((u.outline or {}).get("found") or {}).get("tool")
                 for u in db.session.query(KUnit).filter(KUnit.doc_id == doc.id)}
        assert tools.get("promtail.yml.j2") == "promtail" and tools.get("prometheus.yml.j2") == "prometheus", tools
    finally:
        db.session.rollback()
        unit_ids = [u.id for u in db.session.query(KUnit.id).filter(KUnit.doc_id == doc.id)]
        db.session.query(KFact).filter(KFact.unit_id.in_(unit_ids or [-1])).delete(synchronize_session=False)
        db.session.query(KUnit).filter(KUnit.doc_id == doc.id).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_([f.id for f in made])).delete(synchronize_session=False)
        db.session.commit()
