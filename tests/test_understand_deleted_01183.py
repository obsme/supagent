"""(0.11.8.3) The understanding never holds a document's units in one transaction while the whole document is
understood: what it understood is committed every UNITS_PER_COMMIT units and before each question to the LLM, so the
document's Delete (and a page's Remove) never waits for it. A document deleted while it is understood, or before its
turn, is left (nothing of it kept) and the next documents are understood; a unit removed while the LLM reads it keeps
nothing, its document goes on."""
from __future__ import annotations

import pytest

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_understand_010 import world  # noqa: F401  (two repositories and a wiki page)

README = "keeps the accounts' entries"          # the first repository's README: a unit the LLM reads


def _gone_by_another(doc_id: int | None = None, unit_id: int | None = None) -> bool:
    """A document (or one unit) deleted by another connection, as the Delete of the documents' page does; whether
    it could be (SQLite waits for a transaction that has written, then says the database is locked)."""
    from sqlalchemy import text
    from superset.extensions import db

    try:
        with db.engine.begin() as c:
            if doc_id is not None:
                c.execute(text("DELETE FROM supagent_kfact WHERE unit_id IN (SELECT id FROM supagent_kunit "
                               "WHERE doc_id = :d)"), {"d": doc_id})
                c.execute(text("DELETE FROM supagent_kunit WHERE doc_id = :d"), {"d": doc_id})
                c.execute(text("DELETE FROM supagent_doc WHERE id = :d"), {"d": doc_id})
            else:
                c.execute(text("DELETE FROM supagent_kfact WHERE unit_id = :u"), {"u": unit_id})
                c.execute(text("DELETE FROM supagent_kunit WHERE id = :u"), {"u": unit_id})
        return True
    except Exception:  # pylint: disable=broad-except
        return False


def _units(doc_id: int) -> int:
    from superset.extensions import db

    from supagent.models import KUnit

    return db.session.query(KUnit).filter(KUnit.doc_id == doc_id).count()


@pytest.fixture()
def llm_on(env):  # noqa: F811
    env["knowledge.understand_llm"] = True
    return env


def _forget(world, d) -> None:  # noqa: F811
    """The fixture's documents without the one deleted here (its teardown deletes the others)."""
    from superset.extensions import db

    world.remove(d)
    db.session.expunge(d)


def test_a_document_deleted_while_the_llm_reads_it_is_left_and_the_others_understood(world, llm_on, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U, understand_llm as L
    from supagent.models import Doc

    first, others = world[0], [d.id for d in world[1:]]
    first_id = first.id
    deleted = []

    def ask(messages):
        if README in messages[1]["content"] and not deleted:
            deleted.append(_gone_by_another(doc_id=first_id))
        return '{"links": []}'
    monkeypatch.setattr(L, "ask_llm", ask)
    out = U.run(reason="test")
    assert deleted == [True]                                  # the LLM's question held no transaction
    assert out.get("documents_deleted") == 1
    db.session.expire_all()
    assert db.session.get(Doc, first_id) is None and _units(first_id) == 0
    assert all(_units(i) > 0 for i in others)                 # the next documents understood
    _forget(world, first)


def test_a_document_deleted_before_its_turn_is_left_and_the_run_ends(world, llm_on, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.models import Doc

    last = world[-1]
    last_id = last.id
    real = U.units_of
    deleted = []

    def units_of(doc):
        got = real(doc)
        if doc.id == last_id and not deleted:                 # read, then deleted before its units are kept
            deleted.append(_gone_by_another(doc_id=last_id))
        return got
    monkeypatch.setattr(U, "units_of", units_of)
    out = U.run(reason="test")
    assert deleted == [True] and out.get("documents_deleted") == 1
    db.session.expire_all()
    assert db.session.get(Doc, last_id) is None and _units(last_id) == 0
    assert all(_units(d.id) > 0 for d in world[:-1])
    _forget(world, last)


def test_a_unit_removed_while_the_llm_reads_it_keeps_nothing_and_its_document_goes_on(world, llm_on, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U, understand_llm as L
    from supagent.models import KUnit

    first_id = world[0].id
    removed = []

    def ask(messages):
        if README in messages[1]["content"] and not removed:
            unit = db.session.query(KUnit.id).filter(KUnit.doc_id == first_id, KUnit.ukey.like("%README.md")).scalar()
            removed.append(_gone_by_another(unit_id=unit))
        return '{"links": []}'
    monkeypatch.setattr(L, "ask_llm", ask)
    out = U.run(reason="test")
    assert removed == [True] and not out.get("documents_deleted") and not out.get("documents_changed")
    db.session.expire_all()
    keys = {k for (k,) in db.session.query(KUnit.ukey).filter(KUnit.doc_id == first_id)}
    assert keys and not any(k.endswith("README.md") for k in keys)   # its other files understood


def test_units_are_committed_as_they_are_understood(world, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U

    commits = []
    real = db.session.commit
    monkeypatch.setattr(U, "UNITS_PER_COMMIT", 2)
    monkeypatch.setattr(db.session, "commit", lambda: (commits.append(1), real())[1])
    U.run(reason="test")
    units = sum(_units(d.id) for d in world)
    assert units >= 6 and len(commits) >= units // 2           # (one per document and one at the end before)


def test_a_page_removed_while_its_document_is_understood_is_left_and_the_rest_understood(world, monkeypatch):  # noqa: F811
    from sqlalchemy import text
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.models import KUnit

    first_id = world[0].id
    U.run(reason="test")                                     # its units kept once
    with db.engine.begin() as c:
        c.execute(text("UPDATE supagent_kunit SET chash = 'changed' WHERE doc_id = :d"), {"d": first_id})
    db.session.expire_all()
    monkeypatch.setattr(U, "UNITS_PER_COMMIT", 1)
    removed = []
    real = db.session.commit

    def commit():                                            # after the first unit kept: a later one's page removed
        real()
        if not removed:
            unit = db.session.query(KUnit.id).filter(KUnit.doc_id == first_id, KUnit.ukey.like("%app/db.py")).scalar()
            removed.append(_gone_by_another(unit_id=unit))
    monkeypatch.setattr(db.session, "commit", commit)
    out = U.run(reason="test")
    assert removed == [True] and out.get("removed_meanwhile") == 1 and not out.get("documents_changed")
    db.session.expire_all()
    keys = {k for (k,) in db.session.query(KUnit.ukey).filter(KUnit.doc_id == first_id)}
    assert not any(k.endswith("app/db.py") for k in keys) and any(k.endswith("docs/flows.md") for k in keys)
    assert db.session.query(KUnit).filter(KUnit.doc_id == first_id, KUnit.chash == "changed").count() == 0
