"""(0.10) What the documents and the code state, proposed for the categories and the System map, compared with what
exists: parts as values in the category their kind says, links with where they were read, a part's data as its
items; stated again: confirmed; a learned link the other way round: its removal proposed; no longer stated: the
proposal withdrawn; what a person refused or made: never proposed again, never changed."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_understand_010 import world  # noqa: F401  (two repositories and a wiki page)


def _value(name):
    from superset.extensions import db

    from supagent.models import Facet

    return db.session.query(Facet).filter(Facet.value == name).first()


def _link(a, b, kind):
    from superset.extensions import db

    from supagent.models import Link

    return db.session.query(Link).filter(Link.a_ref == f"facet:{a.id}", Link.b_ref == f"facet:{b.id}",
                                         Link.kind == kind).first()


def test_what_the_documents_state_waits_in_to_review(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet, KObject, Link, Tag

    try:
        U.run(reason="test")
        out = propose()
        assert out["values"] >= 4 and out["links"] >= 2 and out["items"] >= 1
        ledger, billing = _value("ledger"), _value("billing")
        assert (ledger.facet, ledger.status, ledger.source) == ("application", "proposed", "docs")
        assert "ledger-api" in (ledger.synonyms or [])                      # its other names
        assert _value("journal").facet == "component"                      # a database: a component
        calls = _link(ledger, billing, "calls")
        assert calls.status == "proposed" and "billing" in calls.evidence and "code" in calls.evidence
        metric = db.session.query(KObject).filter(KObject.name == "ledger_entries_total").one()
        tag = db.session.query(Tag).filter(Tag.ref == f"object:{metric.id}", Tag.facet_id == ledger.id).one()
        assert (tag.status, tag.source) == ("proposed", "docs")
        # stated again: confirmed, nothing more
        calls.status = "approved"
        db.session.commit()
        again = propose()
        assert again["links"] == 0 and again["values"] == 0 and again["confirmed"] >= 2
        # a value a person refused: never proposed again, nor its links
        notifier = _value("notifier")
        notifier.status = "rejected"
        db.session.commit()
        assert propose()["values"] == 0 and _value("notifier").status == "rejected"
        # a learned link the other way round: its removal proposed; a person's: left as it is
        back = Link(a_ref=f"facet:{billing.id}", b_ref=f"facet:{ledger.id}", kind="calls", status="approved", source="llm")
        mine = Link(a_ref=f"facet:{_value('journal').id}", b_ref=f"facet:{ledger.id}", kind="sends_to", status="approved",
                    source="admin", note="the journal's exports")
        db.session.delete(calls)
        db.session.add_all([back, mine])
        db.session.commit()
        out = propose()
        assert out["removals"] >= 1 and "other way" in (db.session.get(Link, back.id).proposed_drop or "")
        # (0.10.5) a person's: only on the code's or a configuration's word, quoting it, and it waits for approval
        why = db.session.get(Link, mine.id).proposed_drop or ""
        assert "other way" in why and "(" in why and db.session.get(Link, mine.id).status == "approved"
    finally:
        db.session.rollback()
        ids = [f.id for f in db.session.query(Facet).filter(Facet.source.in_(("docs",)))]
        refs = [f"facet:{i}" for i in ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Tag).filter(Tag.facet_id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.commit()


def test_a_proposal_no_longer_stated_is_withdrawn(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet, Link, Tag

    try:
        U.run(reason="test")
        propose()
        ledger, billing = _value("ledger"), _value("billing")
        assert _link(ledger, billing, "calls") is not None
        d = world[0]                                                  # the code calls invoicing now, not billing
        d.content = d.content.replace("billing.apps.svc", "invoicing.apps.svc")
        d.pages = [dict(p, chars=p["chars"] + (len("invoicing") - len("billing")) if p["path"] == "app/clients.py" else
                        p["chars"], at=p["at"] + (len("invoicing") - len("billing")) if p["at"] > d.pages[1]["at"] else p["at"])
                   for p in d.pages]
        docs = [x for x in world if "wiki" in x.url]                  # and no page says it either
        for w in docs:
            w.content = w.content.replace("ledger calls billing and writes", "ledger writes")
            w.pages = [dict(p, chars=len(w.content)) for p in w.pages]
        mermaid = world[0]
        mermaid.content = mermaid.content.replace("  ledger --> billing\n", "  ledger --> invoicing\n")
        db.session.commit()
        U.run(reason="test")
        out = propose()
        assert out["withdrawn"] >= 1 and _link(ledger, billing, "calls") is None
        assert _link(ledger, _value("invoicing"), "calls") is not None
    finally:
        db.session.rollback()
        ids = [f.id for f in db.session.query(Facet).filter(Facet.source == "docs")]
        refs = [f"facet:{i}" for i in ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Tag).filter(Tag.facet_id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.commit()


def test_nothing_is_withdrawn_when_the_facts_read_shrink_at_once(world, monkeypatch):  # noqa: F811
    """A document not fetched a moment: what it stated is not withdrawn (the facts read fell under half)."""
    from superset.extensions import db

    from supagent.knowledge import proposals as P
    from supagent.knowledge import understand as U
    from supagent.models import Facet, Link, Meta, Tag

    try:
        U.run(reason="test")
        P.propose()
        db.session.get(Meta, P.STATE_KEY).value = '{"facts": 40}'          # as if 40 had been read before
        db.session.commit()
        ledger, billing = _value("ledger"), _value("billing")
        real = U.export
        monkeypatch.setattr(U, "export", lambda: {**real(), "relations": [], "data_links": []})
        out = P.propose()
        assert out["withdrawn"] == 0 and "kept: fewer facts read than before" in out
        assert _link(ledger, billing, "calls") is not None
    finally:
        db.session.rollback()
        ids = [f.id for f in db.session.query(Facet).filter(Facet.source == "docs")]
        refs = [f"facet:{i}" for i in ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Tag).filter(Tag.facet_id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.query(Meta).filter(Meta.key == P.STATE_KEY).delete(synchronize_session=False)
        db.session.commit()
