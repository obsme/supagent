"""(0.10.4, the user's request of 8 October 2026: many categories and links are added by hand where the knowledge
says nothing of them; they must not be deleted when nothing is found about them, only what is found may propose a
change, with approval.) What a person made, through the whole learning: the documents' proposals read twice (and a
document that stops stating something), the interactions' check, the classification's settling, the reset of what
the learning made. Nothing a person made is deleted nor marked for removal; the learned values a person's work rests
on stay with it (a link drawn to one, a part_of under one, an item a person gave one); a text saying a value put by
hand was decommissioned proposes its retirement, with the sentence, and nothing else."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_retire_090 import _state
from test_understand_010 import world  # noqa: F401  (two repositories and a wiki page)

HAND = ("zz-hand-portal", "zz-hand-queue")
LEARNED = ("zz-learned-suite", "zz-learned-lone")


def _value(name):
    from superset.extensions import db

    from supagent.models import Facet

    return db.session.query(Facet).filter(Facet.value == name).first()


def _people(world):
    """The documents read and proposed, two of their values approved; then what a person made on top of them."""
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet, Link, Tag

    U.run(reason="test")
    propose()
    ledger, journal, billing = _value("ledger"), _value("journal"), _value("billing")
    ledger.status = journal.status = "approved"                     # approved by a person, learned all the same
    portal = Facet(facet="application", value=HAND[0], status="approved", source="admin", description="By a person")
    queue = Facet(facet="component", value=HAND[1], status="approved", source="admin")
    suite = Facet(facet="application", value=LEARNED[0], status="approved", source="llm")
    lone = Facet(facet="application", value=LEARNED[1], status="approved", source="llm")
    db.session.add_all([portal, queue, suite, lone])
    db.session.flush()
    f = lambda v: f"facet:{v.id}"                                    # noqa: E731
    links = {
        "drawn": Link(a_ref=f(portal), b_ref=f(queue), kind="calls", status="approved", source="admin"),
        "to a learned value": Link(a_ref=f(portal), b_ref=f(journal), kind="depends_on", status="approved",
                                   source="admin", note="reads the journal"),
        "under a learned parent": Link(a_ref=f(portal), b_ref=f(suite), kind="part_of", status="approved",
                                       source="admin"),
        "to a proposed value": Link(a_ref=f(portal), b_ref=f(billing), kind="calls", status="approved", source="admin"),
        "described by a person": Link(a_ref=f(ledger), b_ref=f(queue), kind="sends_to", status="approved", source="llm",
                                      note="its exports", explained_by="alice"),
        # (the controls: learned, nothing of a person's on them)
        "learned, its text gone": Link(a_ref=f(lone), b_ref=f(queue), kind="calls", status="approved", source="llm",
                                       evidence='"zz-learned-lone calls zz-hand-queue" (A page gone)'),
    }
    tags = {"given by a person": Tag(ref="doc:9903#0", facet_id=journal.id, source="admin", status="approved"),
            "the LLM's": Tag(ref="doc:9903#1", facet_id=journal.id, source="llm", status="approved")}
    db.session.add_all([*links.values(), *tags.values()])
    db.session.commit()
    return {"values": {v.value: v.id for v in (portal, queue, suite, lone, ledger, journal, billing)},
            "links": {k: x.id for k, x in links.items()}, "tags": {k: t.id for k, t in tags.items()}}


def _mine(ids):
    """What a person made, as it is now: {name: (status, proposed_drop or retire proposal)} / None when gone."""
    from superset.extensions import db

    from supagent.models import Facet, Link, Tag

    out = {}
    for v in HAND:
        x = db.session.get(Facet, ids["values"][v])
        out[v] = None if x is None else (x.status, (x.suggested or {}).get("retire"))
    for k in ("drawn", "to a learned value", "under a learned parent", "to a proposed value", "described by a person"):
        x = db.session.get(Link, ids["links"][k])
        out[k] = None if x is None else (x.status, x.proposed_drop)
    x = db.session.get(Tag, ids["tags"]["given by a person"])
    out["item given by a person"] = None if x is None else (x.status, None)
    return out


def _clean():
    from superset.extensions import db

    from supagent.models import Facet, Link, Tag

    db.session.rollback()
    ids = [f.id for f in db.session.query(Facet).filter((Facet.source == "docs") | (Facet.value.in_(HAND + LEARNED)))]
    refs = [f"facet:{i}" for i in ids]
    db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
    db.session.query(Tag).filter(Tag.facet_id.in_(ids or [-1]) | Tag.ref.like("doc:9903#%")).delete(
        synchronize_session=False)
    db.session.query(Facet).filter(Facet.id.in_(ids or [-1])).delete(synchronize_session=False)
    db.session.commit()


UNTOUCHED = {HAND[0]: ("approved", None), HAND[1]: ("approved", None), "drawn": ("approved", None),
             "to a learned value": ("approved", None), "under a learned parent": ("approved", None),
             "to a proposed value": ("approved", None), "described by a person": ("approved", None),
             "item given by a person": ("approved", None)}


def test_the_learning_never_removes_nor_proposes_removing_what_a_person_made(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import interactions
    from supagent.knowledge import understand as U
    from supagent.knowledge.facets import settle
    from supagent.knowledge.proposals import propose
    from supagent.models import Link

    try:
        ids = _people(world)
        for _ in range(2):                                           # the learning, twice, the documents silent on it
            U.run(reason="test")
            propose()
            interactions.stale()
            settle()
            db.session.commit()
            assert _mine(ids) == UNTOUCHED
        assert db.session.get(Link, ids["links"]["learned, its text gone"]).proposed_drop   # (the check does work)
        for w in [x for x in world if "wiki" in x.url]:              # a document stops stating billing
            w.content = w.content.replace("ledger calls billing and writes", "ledger writes")
            w.pages = [dict(p, chars=len(w.content)) for p in w.pages]
        d = world[0]
        d.content = d.content.replace("billing.apps.svc", "invoicing.apps.svc").replace("  ledger --> billing\n",
                                                                                        "  ledger --> invoicing\n")
        db.session.commit()
        U.run(reason="test")
        propose()
        db.session.commit()
        assert _mine(ids) == UNTOUCHED and _value("billing") is not None
    finally:
        _clean()


def test_a_reset_keeps_what_a_person_made_and_the_learned_values_it_rests_on(world, tmp_path):  # noqa: F811
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import reset as R
    from supagent.models import Facet, Link, Run, Tag

    settings.set_value("backup.dir", str(tmp_path))
    db.session.query(Run).filter(Run.status == "running").update({"status": "done"})
    db.session.commit()
    try:
        ids = _people(world)
        plan = R.plan(context=False, categories=True, links=True)
        assert plan["kept"]["learned values a person's work rests on"] >= 4   # journal, suite, billing, ledger
        out = R.run(context=False, categories=True, links=True, by="test")
        assert out["backup"]
        assert _mine(ids) == UNTOUCHED
        for v in ("journal", LEARNED[0], "billing", "ledger"):       # what a person's work rests on: kept
            assert db.session.get(Facet, ids["values"][v]) is not None, v
        assert db.session.get(Facet, ids["values"][LEARNED[1]]) is None            # nothing of a person's on it: gone
        assert db.session.get(Link, ids["links"]["learned, its text gone"]) is None
        assert db.session.get(Tag, ids["tags"]["the LLM's"]) is None                # a kept value's learned item: gone
        learned_of_kept = db.session.query(Link).filter(
            Link.a_ref == f"facet:{ids['values']['ledger']}", Link.source == "docs").count()
        assert learned_of_kept == 0                                  # a kept value's learned links: gone
    finally:
        settings.set_value("backup.dir", None)
        _clean()


def test_only_a_text_saying_so_proposes_retiring_a_value_put_by_hand(world, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import retire
    from supagent.knowledge.freshness import touch
    from supagent.models import Doc

    try:
        ids = _people(world)
        touch()
        db.session.commit()
        _state(monkeypatch, retire, 1)
        assert retire.check()["proposed"] == 0 and _mine(ids) == UNTOUCHED          # nothing found: nothing proposed
        db.session.add(Doc(kind="upload", title="Ops notes", enabled=True, status="ok",
                           content="Changes.\n\nzz-hand-portal was decommissioned last month; its users moved."))
        db.session.commit()
        out = retire.check()
        assert out["said"] == 1
        now = _mine(ids)
        status, proposal = now[HAND[0]]
        assert status == "approved" and proposal["kind"] == "said" and "decommissioned last month" in proposal["evidence"]
        assert {k: v for k, v in now.items() if k != HAND[0]} == {k: v for k, v in UNTOUCHED.items() if k != HAND[0]}
    finally:
        db.session.query(Doc).filter(Doc.title == "Ops notes").delete(synchronize_session=False)
        db.session.commit()
        _clean()
