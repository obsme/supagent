"""(0.10.10, the team's report of 12 October: "the classifications should follow the principal categories I put in
place") A part the documents name goes to the deployment's own category for what it is: the noun next to its name
("the topic X", "the cron job X", "X squad"), what the reading knows of it (an inventory's group, a VIP), its name's
shape; the deployment's categories read from their names and categories.about. Nothing says it, or no category of
the deployment says it: where it went before. A name of several values takes the one that fits where the fact puts
it (a place parts run on, an end of a flow, an owner); a flow to what a person filed as a place, a team or a domain
is not proposed."""

from __future__ import annotations

from collections import Counter

import pytest

PFX = "zqp"
OWN = ["business line", "squad", "data store", "event bus", "queue", "object store", "third-party", "cron job",
       "ansible group", "vm", "virtual ip", "microservice"]
ABOUT = {"queue": "a topic or a queue of an event bus", "event bus": "a message broker cluster",
         "object store": "an object storage bucket", "data store": "a database holding an application's data",
         "vm": "a virtual machine by its hostname"}


@pytest.mark.parametrize("concept,cats,want", [
    ("job", ["application", "cron job", "server"], "cron job"),
    ("store", ["data store", "object store"], "data store"),
    ("object", ["data store", "object store"], "object store"),
    ("messaging", ["queue", "event bus"], "queue"),
    ("broker", ["queue", "event bus"], "event bus"),
    ("group", ["server", "ansible group"], "ansible group"),
    ("host", ["vm", "ansible group"], "vm"),
    ("vip", ["server", "virtual ip"], "virtual ip"),
    ("team", ["squad", "business line"], "squad"),
    ("domain", ["squad", "business line"], "business line"),
    ("external", ["application", "third-party"], "third-party"),
    ("job", ["application", "component", "server"], None),          # no category says it: none
])
def test_the_deployments_category_for_a_concept(concept, cats, want):
    from supagent.knowledge.placing import best_category

    assert best_category(concept, cats, ABOUT) == want


@pytest.mark.parametrize("quote,name,want", [
    ("orders-api publishes events to the topic order.created", "order.created", {"messaging": 1}),
    ("The cron job nightly-export runs on batch-01 every night.", "nightly-export", {"job": 1}),
    ("billing-api uses the database billing-pg.", "billing-pg", {"store": 1}),
    ("The VIP vip-web routes to web-api.", "vip-web", {"vip": 1}),
    ("payments squad owns the refund desk.", "payments", {"team": 1}),
    ("hosts: web", "web", {}),                                       # a key, not a noun
    ("web runs on web-01 (the Ansible group web).", "web", {}),       # twice in one sentence: which one?
    ("The payments domain consists of ledger, refunds.", "ledger", {}),   # not next to it
])
def test_the_noun_next_to_a_name(quote, name, want):
    from supagent.knowledge.placing import cues

    assert dict(cues(quote, name)) == want


def test_what_the_reading_knows_bounds_what_the_words_say():
    from supagent.knowledge.placing import choose, concept

    assert concept("group", Counter({"application": 2}), "web") == "group"      # an inventory's group stays one
    assert concept("part", Counter({"group": 2}), "web") is None                # a part that runs on places: no group
    assert concept("part", None, "billing-pg") == "store"                        # its name's shape
    assert concept("part", None, "orders.created", published=True) == "messaging"
    assert concept("part", None, "db01.prod.internal", published=True) is None   # a host's full name: no topic
    assert choose("application", "part", "web", None, OWN, ABOUT) == "application"   # nothing says it: as before
    assert choose("server", "group", "web", None, OWN, ABOUT) == "ansible group"
    assert choose("server", "group", "web", None, ["server", "component"], ABOUT) == "server"   # no group category


def _clean(db):
    from supagent.models import Facet, Link, Tag

    db.session.rollback()
    ids = [i for (i,) in db.session.query(Facet.id).filter(Facet.value.ilike(PFX + "%"))]
    refs = [f"facet:{i}" for i in ids]
    if ids:
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Tag).filter(Tag.facet_id.in_(ids)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()


def _graph(rels):
    return {"relations": [{"sources": ["doc"], "where": "Page", "unit_ids": [1, 2], **r} for r in rels],
            "aliases": [], "data_links": [], "denied": []}


def test_the_documents_parts_go_to_the_deployments_categories(ctx, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import STATE_KEY, propose
    from supagent.models import Facet, Meta

    conf = {"categories.custom": OWN, "categories.about": ABOUT}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    _clean(db)
    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
    db.session.commit()
    rels = [
        {"from": f"{PFX}-orders-api", "kind": "sends_to", "to": f"{PFX}.order.created", "obj_kind": "part",
         "quote": f"{PFX}-orders-api publishes events to the topic {PFX}.order.created."},
        {"from": f"{PFX}-nightly-export", "kind": "runs_on", "to": f"{PFX}-batch-01", "obj_kind": "host",
         "quote": f"The cron job {PFX}-nightly-export runs on {PFX}-batch-01 every night."},
        {"from": f"{PFX}-orders-api", "kind": "uses", "to": f"{PFX}-orders-pg", "obj_kind": "part",
         "quote": f"{PFX}-orders-api uses the database {PFX}-orders-pg."},
        {"from": f"{PFX}-web-01", "kind": "in_group", "to": f"{PFX}_web", "obj_kind": "group",
         "quote": f"[{PFX}_web]"},
        {"from": f"{PFX}-vip-web", "kind": "routes_to", "to": f"{PFX}-orders-api", "obj_kind": "part",
         "quote": f"The VIP {PFX}-vip-web routes to {PFX}-orders-api."},
        {"from": f"{PFX}-orders-api", "kind": "calls", "to": f"{PFX}-ledger", "obj_kind": "part",
         "quote": f"{PFX}-orders-api calls {PFX}-ledger."}]
    monkeypatch.setattr(U, "export", lambda *a, **k: _graph(rels))
    try:
        propose()
        made = {f.value: f.facet for f in db.session.query(Facet).filter(Facet.value.ilike(PFX + "%"))}
        assert made[f"{PFX}.order.created"] == "queue"
        assert made[f"{PFX}-nightly-export"] == "cron job"
        assert made[f"{PFX}-orders-pg"] == "data store"
        assert made[f"{PFX}_web"] == "ansible group" and made[f"{PFX}-web-01"] == "vm"
        assert made[f"{PFX}-vip-web"] == "virtual ip"
        assert made[f"{PFX}-ledger"] == "application" and made[f"{PFX}-orders-api"] == "application"   # as before
    finally:
        _clean(db)
        db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
        db.session.commit()


def test_a_name_of_several_values_takes_the_one_that_fits(ctx, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import STATE_KEY, propose
    from supagent.models import Facet, Link, Meta

    conf = {"categories.custom": OWN, "categories.about": ABOUT}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    _clean(db)
    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
    group = Facet(facet="ansible group", value=f"{PFX}-pay", status="approved", source="admin")
    line = Facet(facet="business line", value=f"{PFX}-pay", status="approved", source="admin")
    app = Facet(facet="application", value=f"{PFX}-settle", status="approved", source="admin")
    db.session.add_all([group, line, app])
    db.session.commit()
    rels = [{"from": f"{PFX}-settle", "kind": "runs_on", "to": f"{PFX}-pay", "obj_kind": "group",
             "quote": f"{PFX}-settle runs on the hosts of {PFX}-pay."},
            {"from": f"{PFX}-refunds", "kind": "calls", "to": f"{PFX}-pay", "obj_kind": "part",
             "quote": f"{PFX}-refunds calls {PFX}-pay."},
            {"from": f"{PFX}-vip-pay", "kind": "routes_to", "to": f"{PFX}-pay", "obj_kind": "group",
             "quote": f"The VIP {PFX}-vip-pay routes to the hosts of {PFX}-pay."}]
    monkeypatch.setattr(U, "export", lambda *a, **k: _graph(rels))
    try:
        out = propose()
        runs = db.session.query(Link).filter(Link.a_ref == f"facet:{app.id}", Link.kind == "runs_on").all()
        assert [x.b_ref for x in runs] == [f"facet:{group.id}"]                    # the group, not the business line
        refunds = db.session.query(Facet).filter(Facet.value == f"{PFX}-refunds").first()
        assert refunds is None or not db.session.query(Link).filter(
            Link.a_ref == f"facet:{refunds.id}", Link.kind == "calls").count()     # "calls" a group, a domain: no
        assert out.get("not a flow's end (what a person filed it as)") == 1
        vip = db.session.query(Facet).filter(Facet.value == f"{PFX}-vip-pay").one()        # a VIP's pool: kept
        assert db.session.query(Link).filter(Link.a_ref == f"facet:{vip.id}", Link.b_ref == f"facet:{group.id}").count() == 1
    finally:
        _clean(db)
        db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
        db.session.commit()


def test_one_environments_group_is_the_persons_group_of_that_name(ctx, monkeypatch):
    """(0.10.10) The inventory's group of one environment ("x (repo prod)") is the group x a person has; a name with
    groups of two environments keeps them apart."""
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import STATE_KEY, propose
    from supagent.models import Facet, Link, Meta

    conf = {"categories.custom": OWN, "categories.about": ABOUT}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    _clean(db)
    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
    web = Facet(facet="ansible group", value=f"{PFX}_web", status="approved", source="admin")
    api = Facet(facet="ansible group", value=f"{PFX}_api", status="approved", source="admin")
    db.session.add_all([web, api])
    db.session.commit()
    rels = [{"from": f"{PFX}-shop", "kind": "runs_on", "to": f"{PFX}_web (ops prod)", "obj_kind": "group",
             "quote": f"hosts: {PFX}_web"},
            {"from": f"{PFX}-cart", "kind": "runs_on", "to": f"{PFX}_api (ops prod)", "obj_kind": "group",
             "quote": f"hosts: {PFX}_api"},
            {"from": f"{PFX}-cart", "kind": "runs_on", "to": f"{PFX}_api (ops uat)", "obj_kind": "group",
             "quote": f"hosts: {PFX}_api"}]
    monkeypatch.setattr(U, "export", lambda *a, **k: _graph(rels))
    try:
        propose()
        shop = db.session.query(Facet).filter(Facet.value == f"{PFX}-shop").one()
        assert [x.b_ref for x in db.session.query(Link).filter(Link.a_ref == f"facet:{shop.id}")] == [f"facet:{web.id}"]
        cart = db.session.query(Facet).filter(Facet.value == f"{PFX}-cart").one()
        ends = {x.b_ref for x in db.session.query(Link).filter(Link.a_ref == f"facet:{cart.id}")}
        assert f"facet:{api.id}" not in ends and len(ends) == 2                  # two environments: apart
    finally:
        _clean(db)
        db.session.query(Facet).filter(Facet.value.ilike(f"{PFX}_api (%")).delete(synchronize_session=False)
        db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
        db.session.commit()
