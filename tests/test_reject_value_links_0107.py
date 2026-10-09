"""(0.10.7, the user's report of 9 October) A value rejected in To review left the links proposed with it (and the
items given to it) waiting in To review. A value set aside (rejected, retired, removed) takes with it the links drawn
with it, proposed or approved, the items given to it and the other values' "same as" naming it; what a person refused
stays (it keeps the same proposal from coming back)."""
from __future__ import annotations

from test_dictionary_080 import _client
from test_knowledge import world  # noqa: F401  (the fixture)


def test_a_rejected_value_takes_its_proposals_with_it(world, app):
    from superset.extensions import db

    from supagent.models import Facet, Link, Tag

    with app.app_context():
        gone = Facet(facet="component", value="zz-old-cache", status="proposed", source="llm")
        kept = Facet(facet="component", value="zz-api", status="approved", source="admin")
        twin = Facet(facet="component", value="zz-old-cache-2", status="proposed", source="llm")
        db.session.add_all([gone, kept, twin])
        db.session.flush()
        twin.suggested = {"same_as": gone.id}
        a, b = f"facet:{gone.id}", f"facet:{kept.id}"
        db.session.add_all([Link(a_ref=b, b_ref=a, kind="calls", status="proposed", source="llm"),
                            Link(a_ref=a, b_ref=b, kind="part_of", status="proposed", source="llm"),
                            Link(a_ref=b, b_ref=a, kind="reads", status="approved", source="llm"),
                            Link(a_ref=a, b_ref=b, kind="writes", status="rejected", source="llm"),
                            Tag(ref="object:1", facet_id=gone.id, status="proposed"),
                            Tag(ref="object:2", facet_id=gone.id, status="rejected")])
        db.session.commit()
        gid, kid, tid = gone.id, kept.id, twin.id
    try:
        with _client(app, "admin") as c:
            r = c.post(f"/supagent/admin/api/facets/{gid}", json={"status": "rejected"})
            assert r.status_code == 200, r.get_json()
        with app.app_context():
            ref = f"facet:{gid}"
            left = db.session.query(Link).filter((Link.a_ref == ref) | (Link.b_ref == ref)).all()
            assert [(x.kind, x.status) for x in left] == [("writes", "rejected")]     # only what a person refused
            assert [(t.ref, t.status) for t in db.session.query(Tag).filter(Tag.facet_id == gid)] == [("object:2", "rejected")]
            assert not (db.session.get(Facet, tid).suggested or {}).get("same_as")
            assert db.session.get(Facet, gid).status == "rejected" and db.session.get(Facet, kid).status == "approved"
    finally:
        with app.app_context():
            for fid in (gid, kid, tid):
                ref = f"facet:{fid}"
                db.session.query(Link).filter((Link.a_ref == ref) | (Link.b_ref == ref)).delete(synchronize_session=False)
                db.session.query(Tag).filter(Tag.facet_id == fid).delete(synchronize_session=False)
                db.session.query(Facet).filter(Facet.id == fid).delete(synchronize_session=False)
            db.session.commit()
