"""(0.10.9.1) A page removed from a document by an admin (its list of pages): never read again, by this document nor
by another one reaching it; its text taken out of the document now (the other pages keep their places), its search
pieces gone with it, and what the understanding read from it deleted (its unit and its facts). Given back, it is
read at the document's next reading. A sign-in changed later keeps the removed pages."""

from __future__ import annotations

PAGES = {"https://wiki.example.com/ops/a": ("Alpha", "Alpha page. It links to the others.",
                                            ["https://wiki.example.com/ops/b", "https://wiki.example.com/ops/c"]),
         "https://wiki.example.com/ops/b": ("Bravo", "Bravo page about the QZX_RELAY bridge.",
                                            ["https://wiki.example.com/ops/d"]),
         "https://wiki.example.com/ops/c": ("Charlie", "Charlie page.", []),
         "https://wiki.example.com/ops/d": ("Delta", "Delta page, linked from Bravo only.", [])}


def _site(monkeypatch):
    from supagent.knowledge import docs as D

    monkeypatch.setattr(D, "fetch", lambda url: PAGES[url])


def _blocks(doc):
    return [doc.content[p["at"]:p["at"] + p["chars"]] for p in doc.pages]


def test_a_removed_page_goes_now_and_is_not_read_again(ctx, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import docs as D
    from supagent.models import Doc, KFact, KUnit

    _site(monkeypatch)
    doc = Doc(kind="url", url="https://wiki.example.com/ops/a", max_pages=10)
    db.session.add(doc)
    db.session.commit()
    try:
        assert D.refresh(doc)["pages"] == 4 and "QZX_RELAY" in doc.content
        units = {}
        for p in doc.pages:
            u = KUnit(doc_id=doc.id, ukey=p["url"], kind="page", title=p["title"], url=p["url"])
            db.session.add(u)
            db.session.flush()
            db.session.add(KFact(unit_id=u.id, subject=p["title"], verb="mentions", obj="x", source="rules"))
            units[p["title"]] = u.id
        db.session.commit()
        out = D.exclude_page(doc, "admin", url="https://wiki.example.com/ops/b")
        db.session.commit()
        assert out["removed"] == "url:https://wiki.example.com/ops/b" and out["units"] == 1 and out["facts"] == 1
        assert [p["title"] for p in doc.pages] == ["Alpha", "Charlie", "Delta"] and "QZX_RELAY" not in doc.content
        assert [b.split("\n")[0] for b in _blocks(doc)] == ["# Alpha", "# Charlie", "# Delta"]    # places moved
        assert db.session.get(KUnit, units["Bravo"]) is None
        assert db.session.query(KFact).filter(KFact.unit_id == units["Bravo"]).count() == 0
        assert db.session.query(KFact).filter(KFact.unit_id == units["Alpha"]).count() == 1          # the others kept
        r = D.refresh(doc)                                         # read again: not kept, its links still followed
        assert r["pages"] == 3 and "QZX_RELAY" not in doc.content and "Delta page" in doc.content
        why = [k["why"] for k in D.read_log(doc.id)["skipped"] if k["url"].endswith("/ops/b")]
        assert why and why[0].startswith("removed by a person")
        D.configure(doc, {"auth": {"type": "bearer"}, "secret": "tok-123"})      # a sign-in set: the removal kept
        D.configure(doc, {"auth": {"type": "none"}})                               # and taken off: kept too
        assert [e["key"] for e in D.excluded_pages(doc)] == ["url:https://wiki.example.com/ops/b"]
        assert D.include_page(doc, "url:https://wiki.example.com/ops/b")
        db.session.commit()
        assert D.refresh(doc)["pages"] == 4 and "QZX_RELAY" in doc.content         # given back: read again
    finally:
        db.session.query(KUnit).filter(KUnit.doc_id == doc.id).delete(synchronize_session=False)
        db.session.delete(doc)
        db.session.commit()


def test_a_page_removed_from_one_document_is_not_read_by_another(ctx, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import docs as D
    from supagent.models import Doc

    _site(monkeypatch)
    first = Doc(kind="url", url="https://wiki.example.com/ops/a", max_pages=10)
    second = Doc(kind="url", url="https://wiki.example.com/ops/c", max_pages=10)   # its own start, B in reach
    db.session.add_all([first, second])
    db.session.commit()
    try:
        D.refresh(first)
        D.exclude_page(first, "admin", url="https://wiki.example.com/ops/b")
        db.session.commit()
        PAGES["https://wiki.example.com/ops/c"] = ("Charlie", "Charlie page.", ["https://wiki.example.com/ops/b"])
        D.refresh(second)
        assert all(p["url"] != "https://wiki.example.com/ops/b" for p in second.pages or [])
    finally:
        PAGES["https://wiki.example.com/ops/c"] = ("Charlie", "Charlie page.", [])
        db.session.delete(first)
        db.session.delete(second)
        db.session.commit()


def test_the_pages_list_removes_and_gives_back_admins_only(app, monkeypatch):
    from superset.extensions import db

    from conftest import login
    from supagent.knowledge import docs as D
    from supagent.models import Chunk, Doc

    _site(monkeypatch)
    with app.app_context():
        doc = Doc(kind="url", url="https://wiki.example.com/ops/a", max_pages=10)
        db.session.add(doc)
        db.session.commit()
        D.refresh(doc)
        doc_id = doc.id
        db.session.remove()
    try:                                     # (no context held: each request has its own user)
        c = app.test_client()
        login(c, "admin")
        d = c.get(f"/supagent/admin/api/docs/{doc_id}/pages").get_json()
        assert d["can_remove"] and d["excluded"] == [] and len(d["pages"]) == 4
        r = c.post(f"/supagent/admin/api/docs/{doc_id}/pages/remove", json={"url": "https://wiki.example.com/ops/b"})
        assert r.status_code == 200 and r.get_json()["pages"] == 3, r.get_data(as_text=True)
        d = c.get(f"/supagent/admin/api/docs/{doc_id}/pages").get_json()
        assert len(d["pages"]) == 3 and [e["title"] for e in d["excluded"]] == ["Bravo"]
        assert d["excluded"][0]["by"] == "admin"
        with app.app_context():
            texts = " ".join(t for (t,) in db.session.query(Chunk.text).filter(Chunk.ref.like(f"doc:{doc_id}%")))
            db.session.remove()
        assert "QZX_RELAY" not in texts and "Delta page" in texts                 # its search pieces gone, not theirs
        assert c.post(f"/supagent/admin/api/docs/{doc_id}/pages/remove",
                      json={"url": "https://wiki.example.com/ops/zz"}).status_code == 400
        r = c.post(f"/supagent/admin/api/docs/{doc_id}/pages/restore", json={"key": d["excluded"][0]["key"]})
        assert r.status_code == 200
        assert c.get(f"/supagent/admin/api/docs/{doc_id}/pages").get_json()["excluded"] == []
        c2 = app.test_client()
        login(c2, "alice")
        assert c2.post(f"/supagent/admin/api/docs/{doc_id}/pages/remove",
                       json={"url": "https://wiki.example.com/ops/c"}).status_code in (401, 403)
    finally:
        with app.app_context():
            db.session.delete(db.session.get(Doc, doc_id))
            db.session.commit()
            db.session.remove()
