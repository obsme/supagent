"""(0.10.6) What a page's words propose, once a team has approved a map: no link the other way round of an approved one
(pages write "talks to" both ways), no call from what holds data or messages to its clients ("ridesdb / Talks to:
orders"), no link to a VIP (the service behind it gets it), no flow from a server or a group; the code and the
configurations still propose what they state."""

from __future__ import annotations

NAMES = ("zqorders", "zqbilling", "zqordersdb", "zqvip.example.com", "zqapps")


def _graph(rels):
    return {"relations": [{"sources": ["wiki"], "quote": "q", "where": "Page", **r} for r in rels], "aliases": [],
            "data_links": [], "denied": []}


def test_page_words_after_approval(ctx, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import STATE_KEY, propose
    from supagent import settings
    from supagent.models import Facet, Link, Meta

    before = settings.get("categories.custom")
    settings.set_value("categories.custom", ["server"])                    # (the servers' category, as a team has)
    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
    vals = {"zqorders": Facet(facet="application", value="zqorders", status="approved", source="docs"),
            "zqbilling": Facet(facet="application", value="zqbilling", status="approved", source="docs"),
            "zqordersdb": Facet(facet="component", value="zqordersdb", status="approved", source="docs"),
            "zqvip.example.com": Facet(facet="server", value="zqvip.example.com", status="approved", source="docs"),
            "zqapps": Facet(facet="server", value="zqapps", status="approved", source="docs")}
    db.session.add_all(vals.values())
    db.session.flush()
    ref = lambda n: f"facet:{vals[n].id}"                                   # noqa: E731
    db.session.add(Link(a_ref=ref("zqorders"), b_ref=ref("zqbilling"), kind="calls", status="approved", source="docs"))
    db.session.commit()
    rels = [{"from": "zqbilling", "kind": "calls", "to": "zqorders", "obj_kind": "part"},          # the other way
            {"from": "zqordersdb", "kind": "calls", "to": "zqorders", "obj_kind": "part"},         # a store calls
            {"from": "zqorders", "kind": "calls", "to": "zqvip.example.com", "obj_kind": "part"},  # to a VIP
            {"from": "zqvip.example.com", "kind": "routes_to", "to": "zqorders", "obj_kind": "part"},
            {"from": "zqapps", "kind": "sends_to", "to": "zqbilling", "obj_kind": "part"},          # a group's flow
            {"from": "zqorders", "kind": "uses", "to": "zqordersdb", "obj_kind": "part"}]           # a right one
    monkeypatch.setattr(U, "export", lambda *a, **k: _graph(rels))
    try:
        out = propose()
        made = {(x.a_ref, x.kind, x.b_ref) for x in db.session.query(Link).filter(Link.status == "proposed")}
        assert (ref("zqbilling"), "calls", ref("zqorders")) not in made and out["the other way approved"] == 1
        assert (ref("zqordersdb"), "calls", ref("zqorders")) not in made and out["a store calls no one"] == 1
        assert not any(b == ref("zqvip.example.com") for _a, _k, b in made) and out["to a VIP: its service"] == 1
        assert not any(a == ref("zqapps") for a, _k, _b in made) and out["a server is no flow's subject"] == 1
        assert (ref("zqvip.example.com"), "calls", ref("zqorders")) in made or db.session.query(Link).filter(
            Link.a_ref == ref("zqvip.example.com"), Link.b_ref == ref("zqorders")).count()   # its routing stays
        assert any(a == ref("zqorders") and b == ref("zqordersdb") for a, _k, b in made)
        rels[0]["sources"] = ["config"]                                     # the configuration states it: proposed
        propose()
        assert db.session.query(Link).filter(Link.a_ref == ref("zqbilling"), Link.b_ref == ref("zqorders")).count()
    finally:
        db.session.rollback()
        ids = [v.id for v in db.session.query(Facet).filter(Facet.value.in_(NAMES))]
        refs = [f"facet:{i}" for i in ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.commit()
        settings.set_value("categories.custom", before)


def test_a_role_deploying_a_compose_stack_is_no_part(ctx):
    from supagent.knowledge.projects import Role

    r = Role("monitoring_stack", "roles/monitoring_stack")
    r.tasks, r.services = True, ["docker"]
    r.deploys = [("community.docker.docker_compose_v2", {"project_src": "/opt/stack"})]
    assert r.part == "monitoring-stack" or r.part                          # a role that deploys: a part ...
    r.stack = True
    assert r.part is None                                                   # ... unless its Compose file holds several
