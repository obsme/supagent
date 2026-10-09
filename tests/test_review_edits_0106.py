"""(0.10.6) To review corrects before approving (the user's request with two screenshots): a proposed link gets its kind
from the list and its direction turned round; a warning acts in one click: a loop keeps one direction (the other
rejected), a proposal named as an approved value is rejected, a document holding only pages read before is disabled."""

from __future__ import annotations

from test_dictionary_080 import _client


def test_a_proposed_link_is_corrected_then_approved(app):
    from superset.extensions import db

    from supagent.models import Facet, Link

    with app.app_context():
        made = [Facet(facet="component", value="zqsearch-engine", status="approved", source="admin"),
                Facet(facet="server", value="zqsearch-01", status="approved", source="data")]
        db.session.add_all(made)
        db.session.flush()
        ids = [f.id for f in made]
        e, s = (f"facet:{i}" for i in ids)
        x = Link(a_ref=s, b_ref=e, kind="part_of", status="proposed", source="llm")
        db.session.add(x)
        db.session.commit()
        try:
            with _client(app, "admin") as c:
                r = c.post(f"/supagent/admin/api/links/{x.id}", json={"kind": "runs_on", "reverse": True,
                                                                       "status": "approved"}).get_json()
                assert (r["kind"], r["a"], r["b"], r["status"]) == ("runs_on", e, s, "approved")
                bad = c.post(f"/supagent/admin/api/links/{x.id}", json={"kind": "owns"})
                assert bad.status_code == 400
                twin = Link(a_ref=s, b_ref=e, kind="runs_on", status="proposed", source="llm")
                db.session.add(twin)
                db.session.commit()
                clash = c.post(f"/supagent/admin/api/links/{twin.id}", json={"reverse": True})
                assert clash.status_code == 409                              # on the map already
        finally:
            db.session.rollback()
            db.session.query(Link).filter(Link.a_ref.in_([f"facet:{i}" for i in ids])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()


def test_the_warnings_act_in_one_click(app):
    from superset.extensions import db

    from supagent.knowledge import lint as L
    from supagent.models import Doc, Facet, Link

    with app.app_context():
        made = [Facet(facet="server", value="zqdb-01", status="approved", source="data"),
                Facet(facet="component", value="zqpg", status="approved", source="admin"),
                Facet(facet="application", value="zqmds", status="approved", source="admin"),
                Facet(facet="subject", value="zqmds", status="proposed", source="llm")]
        db.session.add_all(made)
        db.session.flush()
        srv, pg = f"facet:{made[0].id}", f"facet:{made[1].id}"
        right = Link(a_ref=pg, b_ref=srv, kind="runs_on", status="approved", source="docs")
        wrong = Link(a_ref=srv, b_ref=pg, kind="runs_on", status="proposed", source="llm")
        pages = [{"url": f"https://wiki.example/zq/{i}", "title": f"Page {i}"} for i in range(4)]
        docs = [Doc(kind="url", url="https://wiki.example/zqa", title="ZQ space A", pages=pages, enabled=True),
                Doc(kind="url", url="https://wiki.example/zqb", title="ZQ space B", pages=pages[1:], enabled=True)]
        db.session.add_all([right, wrong] + docs)
        db.session.commit()
        try:
            ws = L.warnings()
            loop = next(w for w in ws if w["kind"] == "loop" and "zqdb-01" in w["subject"])
            keep = {k["label"]: k["reject"] for k in loop["keep"]}
            assert keep["Keep “zqpg runs on zqdb-01”"] == wrong.id and keep["Keep “zqdb-01 runs on zqpg”"] == right.id
            same = next(w for w in ws if w["kind"] == "same_name" and w["subject"].lower() == "zqmds")
            assert same["reject"] == [{"facet": made[3].id, "label": "Reject the subject “zqmds”"}]
            shared = next(w for w in ws if w["kind"] == "shared_pages" and "ZQ space B" in w["subject"])
            assert shared["disable"] == [{"doc": docs[1].id, "label": "Disable “ZQ space B”"}]
        finally:
            db.session.query(Link).filter(Link.id.in_([right.id, wrong.id])).delete(synchronize_session=False)
            db.session.query(Doc).filter(Doc.id.in_([d.id for d in docs])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_([f.id for f in made])).delete(synchronize_session=False)
            db.session.commit()
