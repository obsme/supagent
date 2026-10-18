"""(0.11.1.1) A learning stayed for hours at its step "search index and embeddings": its reading embedded a whole wiki
again on CPUs, its lease ran out after 30 minutes, the hourly tick and the documents read started readings of their own
at the same time, and each reading asked meanwhile made it read once more. A reading is now bounded in time, keeps its
lease while it runs, shows what it does, and leaves a worker's time limit to the worker."""

from __future__ import annotations

import time

import numpy as np
import pytest


@pytest.fixture()
def reading(ctx):
    from superset import db

    from supagent.knowledge import index as I
    from supagent.models import Meta

    I._again(False)
    yield I
    db.session.rollback()
    row = db.session.get(Meta, I.INDEX_LEASE)
    if row is not None:
        row.value = ""
    db.session.commit()
    I._again(False)


def _lease_value() -> str:
    from sqlalchemy import text
    from superset import db

    with db.engine.connect() as con:                  # what the other processes read (not this session's cache)
        return con.execute(text("SELECT value FROM supagent_meta WHERE key = 'index:lease'")).scalar() or ""


def test_a_reading_ends_at_its_time_while_readings_keep_being_asked(reading, monkeypatch):
    I = reading
    passes = []

    def once(deadline, progress):
        passes.append(1)
        I._again(True)                                # another process asks for a reading during every pass
        time.sleep(0.05)
        return {"embed": {"embedded": 16, "left": 99}}

    monkeypatch.setattr(I, "_index_once", once)
    t0 = time.time()
    out = I.index_knowledge(seconds=0.4)
    assert time.time() - t0 < 3                       # before 0.11.1.1: 5 passes, then once more, for ever
    assert len(passes) >= 2 and out["passes"] == len(passes)
    assert out["embed"]["embedded"] == 16 * len(passes)            # every pass's embeddings, not the last one's
    assert "next one" in out["again"] and I._again()               # the reading asked is kept for the next one


def test_a_reading_asked_meanwhile_is_done_at_once_while_time_is_left(reading, monkeypatch):
    I = reading
    passes = []

    def once(deadline, progress):
        passes.append(1)
        if len(passes) == 1:
            I._again(True)
        return {"read": len(passes)}

    monkeypatch.setattr(I, "_index_once", once)
    out = I.index_knowledge(seconds=60)
    assert out == {"read": 2, "passes": 2} and not I._again()


def test_the_lease_is_renewed_while_the_reading_runs(reading, monkeypatch):
    I = reading
    monkeypatch.setattr(I, "RENEW_S", 0.05)
    monkeypatch.setattr(I, "LEASE_S", 2)
    seen = {}

    def once(deadline, progress):
        first = float(_lease_value().rpartition("|")[2])
        time.sleep(1.2)                               # longer than the lease left when it was taken (rounded)
        seen["renewed"] = float(_lease_value().rpartition("|")[2]) > first
        monkeypatch.setattr(I, "_me", lambda: "another-host:1")
        seen["other"] = I._lease(True)                # another process asks for the lease meanwhile
        monkeypatch.undo()
        return {}

    monkeypatch.setattr(I, "_index_once", once)
    I.index_knowledge(seconds=30)
    assert seen == {"renewed": True, "other": False}
    assert _lease_value() == ""                       # given back at the end


def test_renewing_never_takes_another_process_lease(reading):
    from superset import db

    from supagent.models import Meta

    I = reading
    I._lease(True)
    row = db.session.get(Meta, I.INDEX_LEASE)
    row.value = f"another-host:1|{time.time() + 60:.0f}"
    db.session.commit()
    assert I._renew(I._me()) is False
    assert _lease_value().startswith("another-host:1|")


def _pieces(n: int) -> None:
    from superset import db

    from supagent.models import Chunk

    db.session.query(Chunk).filter(Chunk.ref.like("test-bounded:%")).delete(synchronize_session=False)
    for i in range(n):
        db.session.add(Chunk(ref=f"test-bounded:{i}", kind="doc", title=f"piece {i}", text="some words", scope="team",
                             content_hash=str(i)))
    db.session.commit()


@pytest.fixture()
def embedder(ctx, monkeypatch):
    from superset import db

    from supagent import settings
    from supagent.knowledge import embeddings as E
    from supagent.models import Chunk

    calls = []

    def fake_embed(texts):
        calls.append(len(texts))
        time.sleep(0.05)
        return [np.ones(4, dtype=np.float32) / 2.0 for _ in texts]

    real_get = settings.get
    monkeypatch.setattr(E, "embed", fake_embed)
    monkeypatch.setattr(settings, "get", lambda k: {"embed.model": "fake-model", "embed.batch": 4}.get(k, real_get(k)))
    kept = db.session.query(Chunk.id, Chunk.vector, Chunk.embed_model).all()    # the other tests' pieces: as they were
    db.session.query(Chunk).update({"vector": b"\x00\x3c" * 4, "embed_model": "fake-model"}, synchronize_session=False)
    db.session.commit()
    _pieces(40)
    yield calls
    db.session.query(Chunk).filter(Chunk.ref.like("test-bounded:%")).delete(synchronize_session=False)
    for cid, vector, model in kept:
        db.session.query(Chunk).filter(Chunk.id == cid).update({"vector": vector, "embed_model": model},
                                                               synchronize_session=False)
    db.session.commit()


def test_embeddings_stop_at_the_deadline_and_say_the_pieces_left(embedder):
    from supagent.knowledge.index import embed_pending

    beats = []
    out = embed_pending(deadline=time.time() + 0.12, beat=lambda **k: beats.append(k))
    assert 0 < out["embedded"] < 40 and out["left"] == 40 - out["embedded"]
    assert "time is up" in out["note"]
    assert beats and beats[-1] == {"detail": f"{out['embedded']} of 40"}


def test_embeddings_yield_to_a_reading_asked_meanwhile(embedder, monkeypatch):
    from supagent.knowledge import index as I
    from supagent.knowledge.index import embed_pending

    monkeypatch.setattr(I, "YIELD_AFTER_S", 10)
    assert embed_pending(limit=8, yield_to=lambda: True)["embedded"] == 8      # not in its first seconds
    monkeypatch.setattr(I, "YIELD_AFTER_S", 0)
    out = embed_pending(yield_to=lambda: True)
    assert out["embedded"] == 4 and out["left"] == 28 and "done first" in out["note"]
    out = embed_pending()                             # no deadline, nothing asked: all of them, as before
    assert out == {"embedded": 28, "left": 0}


class SoftTimeLimitExceeded(Exception):              # Celery's (billiard's) is an Exception too
    pass


@pytest.mark.parametrize("where", ["understand", "embed"])
def test_a_worker_time_limit_is_not_taken_for_the_error_of_one_part(reading, monkeypatch, where):
    from supagent import settings
    from supagent.knowledge import understand

    I = reading

    def boom(*_a, **_k):
        raise SoftTimeLimitExceeded()

    real_get = settings.get
    flags = {"knowledge.understand": where == "understand", "knowledge.propose": False}
    monkeypatch.setattr(settings, "get", lambda k: flags[k] if k in flags else real_get(k))
    monkeypatch.setattr(I, "sync", lambda **_k: {})
    monkeypatch.setattr(understand, "run", boom)
    monkeypatch.setattr(I, "embed_pending", boom if where == "embed" else lambda **_k: {})
    with pytest.raises(SoftTimeLimitExceeded):
        I._index_once(time.time() + 60, None)


def test_a_reading_tells_its_progress_and_sees_a_stop(reading, monkeypatch):
    from supagent.knowledge import stopping

    I = reading
    said = []
    checks = []
    monkeypatch.setattr(stopping, "check", lambda force=False: checks.append(1))
    beat = I._beat(said.append)
    beat("embeddings")
    beat(detail="16 of 32")
    beat("the search's pieces", detail="2,000 read")
    assert said == ["embeddings", "embeddings: 16 of 32", "the search's pieces: 2,000 read"] and len(checks) == 3


def test_the_learning_step_shows_the_reading_and_beats_apart_from_its_session(ctx, monkeypatch):
    from sqlalchemy import text
    from superset import db

    from supagent.knowledge import learner as L
    from supagent.models import Meta, Run

    run = Run(kind="learn", reason="test", status="running", stats={})
    db.session.add(run)
    db.session.commit()
    rid = run.id
    try:
        steps = L.Steps(rid, {})
        steps.begin("search index and embeddings")
        db.session.add(Meta(key="test:not-committed", value="x"))      # the step's work in progress
        steps.published = 0.0
        steps.progress("embeddings: 400 of 2,000")
        db.session.rollback()                         # the work given up: the progress saved apart is kept
        assert db.session.get(Meta, "test:not-committed") is None
        with db.engine.connect() as con:
            stats = con.execute(text("SELECT stats FROM supagent_run WHERE id = :i"), {"i": rid}).scalar()
        stats = stats if isinstance(stats, dict) else __import__("json").loads(stats)
        assert stats["steps"][-1]["phase"] == "embeddings: 400 of 2,000" and stats["beat"]
        steps.end(embedded=400)
        assert "phase" not in steps.items[-1]
    finally:
        db.session.query(Run).filter(Run.id == rid).delete()
        db.session.commit()


def test_the_learning_gives_its_index_step_a_bounded_time(ctx, monkeypatch):
    from supagent import settings
    from supagent.knowledge import learner as L

    real_get = settings.get
    monkeypatch.setattr(settings, "get", lambda k: 45 if k == "embed.max_minutes" else real_get(k))
    assert L.index_seconds(time.time() - 3600) == L.INDEX_MIN_S          # the run's time is up: ten minutes still
    assert L.index_seconds(time.time() + 6 * 3600) == 45 * 60          # hours left: embed.max_minutes at most
    assert 1190 < L.index_seconds(time.time() + 1200) <= 1200          # else what is left of the run's


def test_the_index_command_reads_again_until_the_vectors_are_done(ctx, monkeypatch):
    from supagent.cli import supagent
    from supagent.knowledge import index as I

    left = [40]
    calls = []

    def reading(seconds=None, progress=None):
        calls.append(seconds)
        progress("embeddings: 16 of 16")
        done = min(16, left[0])
        left[0] -= done
        return {"embed": {"embedded": done, "left": left[0]}}

    monkeypatch.setattr(I, "index_knowledge", reading)
    r = ctx.test_cli_runner().invoke(supagent, ["index", "--minutes", "5"])
    assert r.exit_code == 0, r.output
    assert len(calls) == 3 and left[0] == 0 and 0 < calls[0] <= 300      # 16 + 16 + 8: until none is left
    left[0], calls[:] = 40, []
    r = ctx.test_cli_runner().invoke(supagent, ["index"])
    assert r.exit_code == 0 and calls == [None]                          # no --minutes: one reading, as before
