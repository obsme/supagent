"""(0.11.8.3) The owner's wiki of 8,390 pages (56 MB) read at 19:27 was still "not yet" in the search at 23:00, its
learning's step "search index and embeddings" running for hours with nothing shown: the reading's pass understood every
page first (all of them again whenever the names known changed: a learning adds metrics), and only then wrote the search's
pieces; its embeddings took 2,000 pieces a pass (hourly). Now the pieces of a document read are written first (found by
their words at once), the understanding has its share of the pass's time and goes on where it stopped at the next pass,
saying how far it is, and the embeddings go round after round until the pass's time is up."""
from __future__ import annotations

import time

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_index_bounded_01111 import embedder, reading  # noqa: F401  (the fixtures)
from test_understand_010 import world  # noqa: F401  (two repositories and a wiki page)


def _doc_pieces(doc_id: int) -> int:
    from superset.extensions import db

    from supagent.models import Chunk

    return db.session.query(Chunk).filter(Chunk.ref.like(f"doc:{doc_id}#%")).count()


def test_a_document_read_is_in_the_search_before_it_is_understood(world, reading, env, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand
    from supagent.models import Chunk, Doc

    I = reading
    env.update({"knowledge.understand": True, "knowledge.propose": False, "embed.model": ""})
    at_understanding = {}

    def run(**_k):
        at_understanding.update({d.id: _doc_pieces(d.id) for d in world})
        return {}
    monkeypatch.setattr(understand, "run", run)
    try:
        I._index_once(time.time() + 60, None)
        assert at_understanding and all(n > 0 for n in at_understanding.values())   # found by their words already
        assert not I._docs_read_since()
        d = db.session.get(Doc, world[2].id)
        d.content, d.content_hash = d.content + "\nA line added.", "another"
        db.session.commit()
        assert I._docs_read_since() == [d.id]                                       # read again: first next time
    finally:
        for d in world:
            db.session.query(Chunk).filter(Chunk.ref.like(f"doc:{d.id}#%")).delete(synchronize_session=False)
        db.session.commit()


def test_the_understanding_stops_at_its_time_and_the_next_run_goes_on_where_it_stopped(world, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.store import source_for
    from supagent.models import KObject, KUnit, Meta
    from superset.models.core import Database

    U.run(reason="test")                                          # every unit read once
    units = db.session.query(KUnit).filter(KUnit.doc_id.in_([d.id for d in world])).count()
    before = db.session.get(Meta, "understand_names").value
    src = source_for(db.session.query(Database).filter(Database.database_name == "logs and metrics").one())
    new = KObject(source_id=src.id, kind="metric", parent="", name="ledger_payments_total")   # a learning added a
    db.session.add(new)                                                                       # metric: the names
    db.session.commit()                                                                       # changed
    try:
        clock = {"t": 0}

        class Clock:
            @staticmethod
            def time():
                clock["t"] += 1
                return clock["t"]
        monkeypatch.setattr(U, "time", Clock)
        beats = []
        out = U.run(reason="test", until=8, beat=lambda **k: beats.append(k))   # a few units, then the time is up
        done = out.get("analysed", 0) + out.get("unchanged", 0)
        assert 1 <= done < units and out["left_for_next_run"] == units - done
        assert any(str(b.get("detail")).startswith("reading document 1 of ") for b in beats)
        db.session.expire_all()
        assert db.session.get(Meta, "understand_names").value == before          # not every unit read: not said
        monkeypatch.undo()
        again = U.run(reason="test")
        assert again.get("unchanged", 0) == done and again.get("analysed", 0) == units - done   # where it stopped
        assert "left_for_next_run" not in again
        db.session.expire_all()
        assert db.session.get(Meta, "understand_names").value != before
    finally:
        db.session.delete(db.session.get(KObject, new.id))
        db.session.commit()


def test_embeddings_go_round_after_round_until_the_reading_s_time_is_up(embedder, monkeypatch):  # noqa: F811
    from supagent import settings
    from supagent.knowledge.index import embed_pending

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: 8 if k == "embed.per_run" else real(k))
    assert embed_pending(limit=8, deadline=time.time() + 60)["embedded"] == 8        # a round asked: one round
    out = embed_pending(deadline=time.time() + 60)                                   # a reading: every round
    assert out == {"embedded": 32, "left": 0}


def test_a_slow_llm_leaves_the_rules_time_to_read_every_unit(world, env, monkeypatch):  # noqa: F811
    from supagent.knowledge import understand as U, understand_llm as L

    env["knowledge.understand_llm"] = True
    calls = []

    def ask(messages):
        calls.append(1)
        time.sleep(1.2)                                     # an LLM slower than the pass's share allows
        return '{"links": []}'
    monkeypatch.setattr(L, "ask_llm", ask)
    out = U.run(reason="test", until=time.time() + 2.0)
    assert "left_for_next_run" not in out                  # every unit read by the rules
    assert len(calls) == 1 and out.get("llm_left_for_next_run", 0) >= 1      # the others at the next run
