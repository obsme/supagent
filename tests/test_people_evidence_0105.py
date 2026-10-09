"""(0.10.5, the user's request of 8 October 2026: what people add by hand changes only on evidence, with approval)
A link a person drew is proposed for removal only when the code or a configuration states the other direction, or
when a sentence naming both of its parts denies it or puts it in the past (the reader keeps such sentences as denied
facts: they never make a link); a page or a diagram stating the other direction proposes the other link only. A
"Keep" is remembered with its reason: the same reason is not proposed again, another one is."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_understand_010 import world  # noqa: F401  (two repositories and a wiki page)

HAND_PAGE = "https://wiki.example.com/display/OPS/Changes"


def _value(name):
    from superset.extensions import db

    from supagent.models import Facet

    return db.session.query(Facet).filter(Facet.value == name).first()


def _drawn(a, b, kind="calls"):
    from superset.extensions import db

    from supagent.models import Link

    a.status = b.status = "approved"                              # (drawn between two values of the map)
    x = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind=kind, status="approved", source="admin",
             note="drawn by a person")
    db.session.add(x)
    db.session.commit()
    return x.id


def _page(world, text):
    from superset.extensions import db

    from supagent.models import Doc

    body = "# Changes\n" + text + "\n"
    d = Doc(kind="url", url=HAND_PAGE, status="ok", enabled=True, content=body,
            pages=[{"url": HAND_PAGE + "/1", "id": "77", "title": "Changes", "chars": len(body), "at": 0, "links": []}])
    db.session.add(d)
    db.session.commit()
    world.append(d)
    return d


def _learn():
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose

    U.run(reason="test")
    out = propose()
    db.session.commit()
    return out


def _drop(link_id):
    from superset.extensions import db

    from supagent.models import Link

    db.session.expire_all()
    return db.session.get(Link, link_id).proposed_drop


def _clean():
    from superset.extensions import db

    from supagent.models import Facet, Link, Meta, Tag

    db.session.rollback()
    ids = [f.id for f in db.session.query(Facet).filter(Facet.source.in_(("docs", "admin")))]
    refs = [f"facet:{i}" for i in ids]
    db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
    db.session.query(Tag).filter(Tag.facet_id.in_(ids or [-1])).delete(synchronize_session=False)
    db.session.query(Facet).filter(Facet.id.in_(ids or [-1])).delete(synchronize_session=False)
    db.session.query(Meta).filter(Meta.key.in_(("kept_drops", "proposals_state"))).delete(synchronize_session=False)
    db.session.commit()


def test_a_drawn_link_the_code_contradicts_is_proposed_for_removal_a_diagram_only_proposes_the_other(world):  # noqa: F811
    try:
        _learn()
        ledger, billing, notifier = _value("ledger"), _value("billing"), _value("notifier")
        against_code = _drawn(billing, ledger)                    # the code: ledger calls billing (app/clients.py)
        against_diagram = _drawn(notifier, billing)               # only a diagram says billing --> notifier
        _learn()
        why = _drop(against_code) or ""
        assert "other way" in why and "ledger calls billing" in why and "clients.py" in why
        assert _drop(against_diagram) is None                     # a diagram or a page: the other link only
    finally:
        _clean()


def test_a_sentence_denying_a_drawn_link_proposes_its_removal_with_the_sentence(world):  # noqa: F811
    try:
        _learn()
        ledger, notifier, billing = _value("ledger"), _value("notifier"), _value("billing")
        denied = _drawn(ledger, notifier)
        other = _drawn(notifier, ledger, kind="sends_to")
        _page(world, "Since June the ledger no longer calls the notifier.\nThe billing does not send e-mails.\n"
                     "The notifier writes to the ledger every night.")
        _learn()
        why = _drop(denied) or ""
        assert "no longer calls the notifier" in why and "Changes" in why
        assert _drop(other) is None                               # stated, not denied: nothing
        from supagent.knowledge import understand as U

        g = U.export()
        assert any(d["from"] == "ledger" and d["to"] == "notifier" for d in g["denied"])
        assert not any(r["from"] == "ledger" and r["to"] == "notifier" for r in g["relations"])   # never a link
        assert _value("billing") is not None and billing.status
    finally:
        _clean()


def test_a_keep_is_remembered_for_its_reason_another_reason_is_proposed(world):  # noqa: F811
    from supagent.knowledge.sysmap import decide_removal

    try:
        _learn()
        ledger, billing = _value("ledger"), _value("billing")
        x = _drawn(billing, ledger)
        _learn()
        assert "other way" in (_drop(x) or "")
        assert decide_removal(x, remove=False, by="alice")         # Keep
        for _ in range(2):
            _learn()
            assert _drop(x) is None                                # the same reason: never again
        _page(world, "The billing no longer calls the ledger since the move.")
        _learn()
        assert "no longer calls the ledger" in (_drop(x) or "")     # another reason: proposed
    finally:
        _clean()
