"""(0.11.0) A proposed link a person corrected in To review (turned round, another kind) is theirs: the next
learning never withdraws it as no longer stated."""
from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_proposals_010 import _link, _value
from test_understand_010 import world  # noqa: F401  (two repositories and a wiki page)


def test_a_corrected_proposal_is_kept_by_the_next_learning(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet, Link, Tag

    try:
        U.run(reason="test")
        propose()
        ledger, billing = _value("ledger"), _value("billing")
        x = _link(ledger, billing, "calls")
        assert x is not None and x.status == "proposed"
        from conftest import login
        from flask import current_app

        c = current_app.test_client()
        login(c, "admin")
        r = c.post(f"/supagent/admin/api/links/{x.id}", json={"reverse": True})   # To review: turned round, saved
        assert r.status_code == 200, r.get_data(as_text=True)[:200]
        db.session.expire_all()
        turned = _link(billing, ledger, "calls")
        assert turned is not None and turned.explained_by == "admin"
        U.run(reason="test")
        propose()                                                       # read again: the documents say ledger -> billing
        db.session.expire_all()
        assert _link(billing, ledger, "calls") is not None              # the person's correction kept
    finally:
        db.session.rollback()
        ids = [f.id for f in db.session.query(Facet).filter(Facet.source == "docs")]
        refs = [f"facet:{i}" for i in ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Tag).filter(Tag.facet_id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.commit()
