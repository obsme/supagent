"""(0.10.9.2) A save in the Data dictionary or in a document's pages answers at once: deactivating a field or a metric
writes the LLM context again in the background (it reads the whole dictionary), and removing a page of a document
writes again that document's search pieces only, never every document's."""
from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)
from test_search import clean_knowledge  # noqa: F401  (the fixture)


def _paged_doc(n: int, label: str):
    from supagent.models import Doc

    texts, pages, at = [], [], 0
    for j in range(3):
        t = f"# {label} page {j}\nThe service {label}-{j} runs on host h{j}. " + "Words. " * 20
        if texts:
            at += 2
        pages.append({"id": f"{label}-{j}", "url": f"https://wiki.example.org/{label}/{j}", "title": f"{label} page {j}",
                      "at": at, "chars": len(t)})
        texts.append(t)
        at += len(t)
    return Doc(kind="url", url=f"https://wiki.example.org/{label}", title=label, content="\n\n".join(texts), pages=pages,
               enabled=True, reader="confluence")


def test_one_documents_pieces_are_written_again_alone(clean_knowledge):
    from superset.extensions import db

    from supagent.knowledge import index
    from supagent.models import Chunk

    a, b = _paged_doc(3, "alpha"), _paged_doc(3, "beta")
    db.session.add_all([a, b])
    db.session.commit()
    index.sync(("doc:",))
    db.session.commit()
    before_b = {c.ref: c.id for c in db.session.query(Chunk).filter(Chunk.ref.like(f"doc:{b.id}#%"))}
    assert before_b and db.session.query(Chunk).filter(Chunk.ref.like(f"doc:{a.id}#%")).count()
    a.content, a.pages = a.content.replace("alpha page 1", "alpha page one"), a.pages
    b.enabled = False                                   # (b's pieces would go if every document were synced)
    db.session.commit()
    index.sync((f"doc:{a.id}#",))
    db.session.commit()
    assert {c.ref: c.id for c in db.session.query(Chunk).filter(Chunk.ref.like(f"doc:{b.id}#%"))} == before_b
    assert any("alpha page one" in (c.text or "") for c in db.session.query(Chunk).filter(Chunk.ref.like(f"doc:{a.id}#%")))
    index.sync((f"doc:{b.id}#",))                       # its own sync: a document turned off has no pieces
    db.session.commit()
    assert db.session.query(Chunk).filter(Chunk.ref.like(f"doc:{b.id}#%")).count() == 0


def test_a_prefix_with_like_signs_is_taken_literally(clean_knowledge):
    from superset.extensions import db

    from supagent.knowledge import index
    from supagent.models import Chunk

    db.session.add(Chunk(ref="memory:1", kind="memory", title="t", text="x"))
    db.session.commit()
    assert index.sync(("mem_ry:",), dry_run=True) is not None   # "_" is no wildcard: memory:1 is not that prefix
    assert db.session.query(Chunk).filter(Chunk.ref == "memory:1").count() == 1


def test_the_llm_context_follows_a_deactivation_through_the_applier(clean_knowledge, app, monkeypatch):
    from superset.extensions import db

    from conftest import login
    from supagent.knowledge import apply, llm_context
    from supagent.models import KObject

    built = []
    monkeypatch.setattr(llm_context, "build", lambda: built.append(1) or 0)
    m = db.session.query(KObject).filter_by(kind="metric").first()
    with app.app_context(), app.test_client() as c:
        login(c, "admin")
        r = c.post(f"/supagent/dictionary/api/objects/{m.id}", json={"active": False})
        body = r.get_json()
        assert r.status_code == 200 and body["deactivated"] is True and m.id in body["changed"]
    assert built == [1]                                 # (the tests apply at once: the background in production)
    assert apply.run({"llm_context": True}) == {} and built == [1, 1]
    with app.app_context(), app.test_client() as c:
        login(c, "admin")
        c.post(f"/supagent/dictionary/api/objects/{m.id}", json={"active": True})
