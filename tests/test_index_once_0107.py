"""(0.10.7) One reading of the documents at a time: two documents fetched together read the same units at the same
time and proposed the same values, links and search pieces twice (the database refused one of them: "duplicate key
value violates unique constraint uq_supagent_facet / uq_supagent_link / supagent_chunk_ref_key" on the test world's
eleven documents). A reading asked while one runs is done by the running one, once more when it ends."""

from __future__ import annotations

import time


def test_a_reading_asked_meanwhile_is_done_by_the_running_one(ctx, monkeypatch):
    from supagent.knowledge import index as I

    calls = []

    def once(*_a):
        calls.append(1)
        if len(calls) == 1:                         # a document fetched during the first reading
            assert I.index_knowledge().get("queued")
        return {"n": len(calls)}

    monkeypatch.setattr(I, "_index_once", once)
    I._again(False)
    out = I.index_knowledge()
    assert len(calls) == 2 and out == {"n": 2, "passes": 2}       # read once more, not at the same time
    assert not I._again()


def test_a_lease_held_by_another_process_is_respected(ctx, monkeypatch):
    from superset import db

    from supagent.knowledge import index as I
    from supagent.models import Meta

    monkeypatch.setattr(I, "_index_once", lambda *_a: {"read": True})
    I._lease(True)
    row = db.session.get(Meta, I.INDEX_LEASE)
    row.value = f"another-host:1|{time.time() + 60:.0f}"
    db.session.commit()
    try:
        assert I.index_knowledge().get("queued") and I._again()
        row = db.session.get(Meta, I.INDEX_LEASE)
        row.value = f"another-host:1|{time.time() - 1:.0f}"     # its process died: the lease has run out
        db.session.commit()
        assert I.index_knowledge() == {"read": True} and not I._again()
        assert db.session.get(Meta, I.INDEX_LEASE).value == ""
    finally:
        db.session.get(Meta, I.INDEX_LEASE).value = ""
        db.session.commit()
        I._again(False)
