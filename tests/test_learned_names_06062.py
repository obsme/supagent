"""(0.10.6.2, the team's reports of 9 October) What the learning proposes is a name, filed where it belongs, and the
subjects are linked: a value is no phrase and no name over 30 characters (a server's or a group's name excepted, a
host's full name shortened to its first label); a monitoring tool, an infrastructure service or a database server is
no application, a library no value; what waits from an older reading is put right; a part and a subject that two
texts or more are about together are proposed linked, never followed by the agent's paths; an Ansible repository that
keeps its inventories per environment (inventory/PRD/hosts, inventory/STG/hosts) gives each environment its groups
and its servers."""

from __future__ import annotations

import pytest

from test_docs_readers import env  # noqa: F401  (the fixture)

PFX = "zq62"


def _clean(db, names_like: str = PFX + "%") -> None:
    from supagent.models import Classified, Facet, Link, Tag

    db.session.rollback()
    ids = [f.id for f in db.session.query(Facet).filter(Facet.value.ilike(names_like))]
    refs = [f"facet:{i}" for i in ids]
    if ids:
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Tag).filter(Tag.facet_id.in_(ids)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
    db.session.query(Classified).filter(Classified.ref.like("doc:9062%")).delete(synchronize_session=False)
    db.session.query(Tag).filter(Tag.ref.like("doc:9062%")).delete(synchronize_session=False)
    db.session.commit()


@pytest.mark.parametrize("name,want", [
    ("orders-api", "orders-api"), ("Payments", "Payments"), ("data storage", "data storage"),
    ("Formulas learned from answers", None),            # four words: a phrase (29 characters)
    ("Monitoring of the payment flow", None), ("The payment platform", None), ("Payments, refunds", None),
    ("payment service is down", None), ("billing (legacy)", None), ("Order intake.", None),
    ("customer-notification-dispatcher", None),         # one word of 32 characters: over the limit
    ("checkout.shop.svc.cluster.local", "checkout"),    # a host's full name: its first label
])
def test_a_learned_value_is_a_name(ctx, name, want):
    from supagent.knowledge.naming import checked

    got, others, why = checked("application", name)
    assert got == want, (name, why)
    if want == "checkout":
        assert others == ["checkout.shop.svc.cluster.local"]
    if want is None:
        assert why


def test_servers_groups_and_aspects_take_any_name(ctx):
    from supagent.knowledge.naming import checked

    from supagent import settings

    before = settings.get("categories.custom")
    settings.set_value("categories.custom", ["server"])
    try:
        long_group = "k8s_ams1_prod_pool_general_ams1 (group)"
        assert checked("server", long_group)[0] == long_group
        assert checked("server", "db-pg-01.par1.prod.example.internal")[0] == "db-pg-01.par1.prod.example.internal"
        assert checked("aspect", "functional")[0] == "functional"
    finally:
        settings.set_value("categories.custom", before)


@pytest.mark.parametrize("name,description,kind", [
    ("log4j", None, "library"), ("jackson-databind", None, "library"), ("spring-boot-starter-web", None, "library"),
    ("orders-common", None, "library"), ("lodash", None, "library"), ("jsonkit", "Java library for JSON", "library"),
    ("Grafana", None, "monitoring"), ("node-exporter", None, "monitoring"), ("zabbix", None, "monitoring"),
    ("prometheus", None, "monitoring"), ("orders-db", None, "database"), ("postgresql", None, "database"),
    ("keycloak", None, "infrastructure"), ("rabbitmq", None, "infrastructure"), ("haproxy", None, "infrastructure"),
    ("orders-api", None, None), ("billing", None, None), ("jsonkit", "service exposing the orders API", None),
    ("risk-models", None, None), ("trade-driver", None, None), ("quartz", None, None),
    ("postgresql-jdbc", None, "library"),
    ("metricsbox", "Prometheus instance for the team's metrics", "monitoring"),
    ("orders-api", "exposes its metrics to Prometheus", None),
])
def test_what_a_part_is_by_its_name(ctx, name, description, kind):
    from supagent.knowledge.naming import kind_of

    assert kind_of(name, description) == kind


def test_where_the_learning_files_a_part(ctx):
    from supagent.knowledge.naming import filed

    base = ["subject", "application", "component"]
    assert filed("application", "grafana", None, base) == ("component", "monitoring")
    assert filed("application", "grafana", None, base + ["monitoring"]) == ("monitoring", "monitoring")
    assert filed("component", "grafana", None, base + ["observability tools"]) == ("observability tools", "monitoring")
    assert filed("application", "log4j", None, base) == (None, "library")
    assert filed("application", "log4j", None, base + ["libraries"]) == ("libraries", "library")
    assert filed("application", "orders-api", None, base) == ("application", None)
    assert filed("subject", "grafana", None, base) == ("subject", None)            # a topic keeps its category
    assert filed("application", "rabbitmq", None, base + ["middleware"]) == ("middleware", "infrastructure")


def test_the_classification_proposes_names_where_they_belong(ctx):
    from superset.extensions import db

    from supagent.knowledge.facets import apply
    from supagent.models import Facet

    _clean(db)
    batch = [{"ref": "doc:906201", "hash": "h1", "text": "zq62"}, {"ref": "doc:906202", "hash": "h2", "text": "zq62"}]
    args = {"items": [
        {"ref": "doc:906201", "aspect": "technical", "confidence": "high",
         "applications": [f"{PFX}-orders-api", f"{PFX}-common", f"Order intake and validation of {PFX} payments"],
         "components": [f"{PFX}-grafana"], "subjects": [f"{PFX} payments monitoring for the checkout team",
                                                        f"{PFX}payments"]}],
        "new_values": [{"facet": "application", "value": f"{PFX}-prometheus", "description": "the metrics server"},
                       {"facet": "application", "value": f"{PFX}-jdbc", "description": "a driver"},
                       {"facet": "subject", "value": f"{PFX} everything about how the payments are monitored"}]}
    try:
        n = apply(args, batch, {})
        made = {(f.facet, f.value) for f in db.session.query(Facet).filter(Facet.value.ilike(PFX + "%"))}
        assert made == {("application", f"{PFX}-orders-api"), ("component", f"{PFX}-grafana"),
                        ("subject", f"{PFX}payments"), ("component", f"{PFX}-prometheus")}, made
        assert n.get("not proposed", 0) >= 4
    finally:
        _clean(db)


def test_what_waits_from_an_older_reading_is_put_right(ctx):
    from superset.extensions import db

    from supagent.knowledge.naming import tidy
    from supagent.models import Facet, Link, Tag

    _clean(db)
    rows = {
        "tool": Facet(facet="application", value=f"{PFX}-grafana", status="proposed", source="llm"),
        "lib": Facet(facet="application", value=f"{PFX}-starter", status="proposed", source="docs"),
        "phrase": Facet(facet="subject", value=f"{PFX} how the payments are watched", status="proposed", source="llm"),
        "host": Facet(facet="component", value=f"{PFX}pay.payments.svc.cluster.local", status="proposed",
                      source="docs"),
        "person": Facet(facet="application", value=f"{PFX}-zabbix", status="approved", source="admin"),
        "edited": Facet(facet="application", value=f"{PFX}-nagios", status="proposed", source="llm",
                        reviewed_by="admin"),
        "app": Facet(facet="application", value=f"{PFX}-billing", status="approved", source="admin"),
    }
    db.session.add_all(rows.values())
    db.session.flush()
    db.session.add_all([Link(a_ref=f"facet:{rows['app'].id}", b_ref=f"facet:{rows['lib'].id}", kind="depends_on",
                             status="proposed", source="docs"),
                        Tag(ref="doc:906203", facet_id=rows["phrase"].id, status="proposed", source="llm")])
    db.session.commit()
    ids = {k: f.id for k, f in rows.items()}
    try:
        out = tidy()
        db.session.commit()
        assert out == {"withdrawn_names": 1, "withdrawn_libraries": 1, "moved_tools": 1}, out
        get = lambda k: db.session.get(Facet, ids[k])                                    # noqa: E731
        assert get("tool").facet == "component" and get("lib") is None and get("phrase") is None
        assert get("host").value == f"{PFX}pay" and f"{PFX}pay.payments.svc.cluster.local" in get("host").synonyms
        assert get("person").facet == "application" and get("edited").facet == "application"
        assert not db.session.query(Link).filter(Link.b_ref == f"facet:{ids['lib']}").count()
        assert not db.session.query(Tag).filter(Tag.ref == "doc:906203").count()
    finally:
        _clean(db)


def test_document_proposals_name_and_file_their_parts(ctx, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import STATE_KEY, propose
    from supagent.models import Facet, Meta

    _clean(db)
    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
    db.session.commit()
    rels = [{"from": f"{PFX}-orders", "kind": "uses", "to": f"{PFX}-common", "obj_kind": "part"},
            {"from": f"{PFX}-orders", "kind": "calls", "to": f"{PFX}-zabbix", "obj_kind": "part"},
            {"from": f"{PFX}-orders", "kind": "calls", "to": f"the {PFX} internal payment processing",
             "obj_kind": "part"},
            {"from": f"{PFX}-orders", "kind": "calls", "to": f"{PFX}pay.payments.svc.cluster.local", "obj_kind": "part"}]
    graph = {"relations": [{"sources": ["doc"], "quote": "q", "where": "Page", **r} for r in rels], "aliases": [],
             "data_links": [], "denied": []}
    monkeypatch.setattr(U, "export", lambda *a, **k: graph)
    try:
        out = propose()
        made = {(f.facet, f.value): f for f in db.session.query(Facet).filter(Facet.value.ilike(PFX + "%"))}
        assert set(made) == {("application", f"{PFX}-orders"), ("component", f"{PFX}-zabbix"),
                             ("application", f"{PFX}pay")}, set(made)
        assert made[("application", f"{PFX}pay")].synonyms == [f"{PFX}pay.payments.svc.cluster.local"]
        assert out.get("a library: no part") == 1 and out.get("no name: not proposed") == 1
    finally:
        _clean(db)
        db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
        db.session.commit()


def test_subjects_linked_to_the_parts_their_texts_are_about(ctx):
    from superset.extensions import db

    from supagent.knowledge import brief
    from supagent.knowledge.naming import SUBJECT_LINKS, subject_links
    from supagent.models import Facet, Link, Tag

    _clean(db)
    s = Facet(facet="subject", value=f"{PFX}payments", status="approved", source="seed")
    a = Facet(facet="application", value=f"{PFX}-pay-api", status="approved", source="admin")
    c = Facet(facet="component", value=f"{PFX}-ledger", status="approved", source="admin")
    b = Facet(facet="application", value=f"{PFX}-shop", status="approved", source="admin")
    db.session.add_all([s, a, c, b])
    db.session.flush()
    tags = [("doc:906211", s), ("doc:906211", a), ("doc:906212", s), ("doc:906212", a), ("doc:906216", s),
            ("doc:906216", a), ("doc:906213", s), ("doc:906213", c), ("doc:906217", s), ("doc:906217", c),
            ("doc:906214", b), ("doc:906215", b)]
    db.session.add_all([Tag(ref=r, facet_id=f.id, status="approved", source="llm") for r, f in tags])
    db.session.commit()
    sid, aid, cid, bid = s.id, a.id, c.id, b.id
    try:
        assert subject_links(dry_run=True)["proposed"] == 1
        out = subject_links()
        assert out["proposed"] == 1 and out["largest"] == 1
        x = db.session.query(Link).filter(Link.source == SUBJECT_LINKS, Link.b_ref == f"facet:{sid}").one()
        assert (x.a_ref, x.kind, x.status) == (f"facet:{aid}", "about", "proposed")
        assert "3 texts are about both" in x.evidence and x.note and x.detail
        assert subject_links()["proposed"] == 0                         # once
        x.status = "approved"                                          # approved: shown, never a path
        db.session.add(Link(a_ref=f"facet:{aid}", b_ref=f"facet:{bid}", kind="calls", status="approved",
                            source="admin"))
        db.session.commit()
        brief._CACHE.update(stamp=None, graph=None)
        g = brief._graph()
        assert not any(b_ == sid for _k, b_, _n in g["out"].get(aid, []))
        assert g["subjects"].get(aid) == [sid] and g["subjects"].get(sid) == [aid]
        from supagent.knowledge.leads import reachable

        assert bid in reachable([aid], g) and sid not in reachable([aid], g)
        got = brief.links_of([f"{PFX}-pay-api"])["parts"][0]
        assert got["subjects"] == [f"{PFX}payments (subject)"]
        x.status = "rejected"                                          # refused: not proposed again
        db.session.commit()
        assert subject_links()["proposed"] == 0
        db.session.delete(x)                                           # a proposal no text supports: withdrawn
        db.session.query(Tag).filter(Tag.ref == "doc:906212").delete(synchronize_session=False)
        db.session.commit()
        db.session.add(Link(a_ref=f"facet:{cid}", b_ref=f"facet:{sid}", kind="about", status="proposed",
                            source=SUBJECT_LINKS))
        db.session.commit()
        assert subject_links()["withdrawn"] == 1
    finally:
        brief._CACHE.update(stamp=None, graph=None)
        _clean(db)


def _units(files: dict[str, str]) -> list[dict]:
    return [{"ukey": p, "path": p, "kind": "file", "title": p, "text": t, "meta": {}} for p, t in files.items()]


def test_inventories_kept_per_environment(ctx):
    from supagent.knowledge.projects import facts, inventory_place, test_file

    files = {
        "inventory/PRD/hosts": "[web]\nprd-web-01\nprd-web-02\n\n[db]\nprd-db-01\n\n[back:children]\ndb\n",
        "inventory/STG/hosts": "[web]\nstg-web-01\n\n[db]\nstg-db-01\n\nstg-lone-01\n",
        "inventory/PRD/group_vars/all.yml": "ntp: 10.0.0.1\n",
        "site.yml": "- hosts: web\n  roles: [storefront]\n",
        "roles/storefront/tasks/main.yml": "- service: name=storefront state=started\n",
    }
    found, names = facts(_units(files), label="zq62shop-ansible")
    t = {(f["subject"], f["verb"], f["obj"]) for fs in found.values() for f in fs}
    assert {("prd-web-01", "in_group", "web (zq62shop PRD)"), ("prd-db-01", "in_group", "db (zq62shop PRD)"),
            ("db (zq62shop PRD)", "in_group", "back (zq62shop PRD)"), ("web (zq62shop PRD)", "in_group", "zq62shop PRD"),
            ("back (zq62shop PRD)", "in_group", "zq62shop PRD"), ("stg-web-01", "in_group", "web (zq62shop STG)"),
            ("web (zq62shop STG)", "in_group", "zq62shop STG")} <= t, t
    assert not any(o in ("web", "db") for _s, v, o in t if v == "in_group")       # no group mixing the environments
    assert not any(s == "db (zq62shop PRD)" and o == "zq62shop PRD" for s, _v, o in t)   # inside its parent group
    assert {("storefront", "runs_on", "web (zq62shop PRD)"), ("storefront", "runs_on", "web (zq62shop STG)")} <= t
    assert {"prd-web-01", "stg-web-01"} <= set(names["hosts"])
    assert inventory_place("apps/orders/inventory/prd/hosts") == ("prd", "orders")
    assert inventory_place("inventories/orders/uat/hosts.ini") == ("uat", "orders")
    assert inventory_place("inventory/prod.ini") == ("prod", None)
    assert inventory_place("inventory/hosts") == (None, None) and inventory_place("hosts") == (None, None)
    assert not test_file("inventory/test/hosts") and test_file("tests/inventory/test/hosts")


def test_one_inventory_keeps_its_names(ctx):
    from supagent.knowledge.projects import facts

    files = {"inventory/hosts": "[web]\nweb-01\n", "site.yml": "- hosts: web\n  roles: [storefront]\n",
             "roles/storefront/tasks/main.yml": "- service: name=storefront state=started\n"}
    found, _names = facts(_units(files), label="zq62shop")
    t = {(f["subject"], f["verb"], f["obj"]) for fs in found.values() for f in fs}
    assert ("web-01", "in_group", "web") in t and ("storefront", "runs_on", "web") in t


def test_a_group_named_like_its_environment_is_the_environment(ctx):
    from supagent.knowledge.projects import _app_of, facts

    files = {"inventory/prod/hosts": "[web]\nw1\n\n[db]\nd1\n\n[prod:children]\nweb\ndb\n",
             "inventory/stg/hosts": "[web]\nsw1\n\n[zq62pay:children]\nweb\n"}
    found, _names = facts(_units(files), label="zq62pay-ansible")
    t = {(f["subject"], f["verb"], f["obj"]) for fs in found.values() for f in fs}
    assert {("w1", "in_group", "web (zq62pay prod)"), ("web (zq62pay prod)", "in_group", "zq62pay prod"),
            ("sw1", "in_group", "web (zq62pay stg)"), ("web (zq62pay stg)", "in_group", "zq62pay stg")} <= t, t
    assert not any("prod (zq62pay prod)" in (s, o) or "zq62pay (zq62pay stg)" in (s, o) for s, _v, o in t)
    assert not any(s == o for s, _v, o in t)
    assert [_app_of(x) for x in ("orders-ansible", "ansible-orders", "parcel-ops", "infra-ansible", "kolla-ansible")] \
        == ["orders", "orders", "parcel", "infra", "kolla"]


ENVREPO = {
    "inventory/PRD/hosts": "[web]\nzqe-prd-web-1\nzqe-prd-web-2\n\n[db]\nzqe-prd-db-1\n",
    "inventory/STG/hosts": "[web]\nzqe-stg-web-1\n\n[db]\nzqe-stg-db-1\n",
    "site.yml": "- hosts: web\n  roles: [zqeshop]\n",
    "roles/zqeshop/tasks/main.yml": "- service: name=zqeshop state=started\n",
    "README.md": "# Deployment\n\n| Role | Target Group | Notes |\n|---|---|---|\n| zqeshop | web | the shop |\n",
}


def test_inventories_per_environment_end_to_end(env):  # noqa: F811
    """The reading, the export and the proposals of a repository with two environments: each environment a value of
    the servers' category holding its groups, holding their servers; a group the README names bare is each
    environment's; the application named like the repository untouched."""
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import STATE_KEY, propose
    from supagent.models import Facet, Link, Meta
    from test_second_pass_0105 import _clean as clean_repo, _repo, _state

    env["categories.custom"] = ["server"]
    before = _state()
    app = Facet(facet="application", value="zqe", status="approved", source="admin")
    db.session.add(app)
    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
    db.session.commit()
    app_id = app.id
    d = _repo(ENVREPO, name="zqe-ansible")
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert {("zqeshop", "runs_on", "web (zqe PRD)"), ("zqeshop", "runs_on", "web (zqe STG)")} <= rels, rels
        assert not any(b == "web" for _a, _k, b in rels)                    # the README's bare group: each one's
        propose()
        V = {(f.facet, f.value): f for f in db.session.query(Facet)}
        for name in ("zqe PRD", "zqe STG", "web (zqe PRD)", "web (zqe STG)", "db (zqe PRD)", "zqe-prd-web-1"):
            assert ("server", name) in V, (name, sorted(k for k in V if "zq" in k[1]))
        assert not any(v == "web" for _c, v in V)

        def linked(a: str, kind: str, b: str) -> bool:                    # two values of the servers' category
            return db.session.query(Link).filter(Link.a_ref == f"facet:{V[('server', a)].id}", Link.kind == kind,
                                                 Link.b_ref == f"facet:{V[('server', b)].id}").count() > 0

        assert linked("zqe-prd-web-1", "part_of", "web (zqe PRD)") and linked("zqe-stg-web-1", "part_of", "web (zqe STG)")
        assert linked("web (zqe PRD)", "part_of", "zqe PRD") and linked("db (zqe STG)", "part_of", "zqe STG")
        assert not linked("zqe-prd-web-1", "part_of", "web (zqe STG)")
        part = next(f for (c, v), f in V.items() if v == "zqeshop")
        on = {x.b_ref for x in db.session.query(Link).filter(Link.a_ref == f"facet:{part.id}", Link.kind == "runs_on")}
        assert {f"facet:{V[('server', 'web (zqe PRD)')].id}", f"facet:{V[('server', 'web (zqe STG)')].id}"} <= on
        ref = f"facet:{app_id}"
        assert not db.session.query(Link).filter((Link.a_ref == ref) | (Link.b_ref == ref)).count()   # untouched
    finally:
        clean_repo(before, [d])
        db.session.query(Facet).filter(Facet.id == app_id).delete(synchronize_session=False)
        db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
        db.session.commit()
        settings.get("categories.custom")
