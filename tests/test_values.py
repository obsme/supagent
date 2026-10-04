"""A query that compares a field with a value the field does not have is sent back once before it runs (knowledge.
values): CHANNEL = 'EXPRESS' (EXPRESS is a field of its own) gave 0 % express orders, STATUS = 'CLOSED' (OPEN,
RESOLVED) gave 0 tickets. Only on an index learned whole; case does not matter; a join's field of the same name
that holds the value lets it pass."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)


def _learned_whole(db, KObject):
    idx = db.session.query(KObject).filter_by(kind="index", name="jobs").one()
    old = dict(idx.stats or {})
    idx.stats = {**old, "sampled_docs": old.get("docs")}
    db.session.commit()
    return idx, old


def test_a_value_the_field_does_not_have_is_sent_back(world):
    from superset.extensions import db

    from supagent.knowledge.values import refusal, unknown
    from supagent.models import KObject

    idx, old = _learned_whole(db, KObject)
    retried = KObject(source_id=idx.source_id, kind="field", parent="jobs", name="RETRIED", data_type="boolean",
                      stats={"values": ["false", "true"]})
    db.session.add(retried)
    db.session.commit()
    try:
        u = unknown('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'CLOSED\'')
        assert [(x["field"], x["value"], x["op"]) for x in u] == [("STATUS", "CLOSED", "=")]
        assert unknown('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'FAILED\'') == []
        assert unknown('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'failed\'') == []          # case: another hint
        assert unknown('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" IN (\'FAILED\', \'SUCCESS\')') == []
        assert unknown("SELECT COUNT(*) FILTER (WHERE \"STATUS\" = 'CLOSED') FROM \"jobs\"")      # in a FILTER too
        back = refusal("execute_sql", {"request": {"database_id": 1, "sql": 'SELECT COUNT(*) FROM "jobs" WHERE '
                                                                            '"STATUS" = \'RETRIED\''}})
        assert back.startswith("tool error (not run: value)") and "its values: FAILED, SUCCESS" in back
        assert "counts nothing" in back and "a field of jobs of its own (\"RETRIED\")" in back
        back = refusal("execute_sql", {"request": {"database_id": 1, "sql": 'SELECT COUNT(*) FROM "jobs" WHERE '
                                                                            '"STATUS" <> \'CLOSED\''}})
        assert "leaves out nothing" in back
        assert refusal("describe_data", {"index": "jobs"}) is None
        idx.stats = {**old, "sampled_docs": 10}                                                 # learned on a sample
        db.session.commit()
        assert unknown('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'CLOSED\'') == []
    finally:
        idx.stats = old
        db.session.delete(retried)
        db.session.commit()


def test_the_value_check_sends_the_call_back_once(world, monkeypatch):
    from superset.extensions import db
    from test_agent_loop import agent_with, call, say

    from supagent.models import KObject

    idx, old = _learned_whole(db, KObject)
    try:
        wrong = {"request": {"database_id": 1, "sql": 'SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'CLOSED\''}}
        right = {"request": {"database_id": 1, "sql": 'SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'SUCCESS\''}}
        a, ran = agent_with(monkeypatch, [call("execute_sql", wrong), call("execute_sql", right), say("40 jobs.")])
        answer, trace = a.ask("How many jobs were closed with success?")
        assert [r[1] for r in ran] == [right] and answer == "40 jobs."
        assert trace[0]["status"] == "error" and "not run: value" in str(trace[0].get("result"))
    finally:
        idx.stats = old
        db.session.commit()


def test_hosts_ids_and_targets_are_not_checked(world):
    """In investigations the agent looks hosts up in the change records (TARGET = a new host: the incident's own,
    which the dictionary learned before it existed): a field with more than 25 values is no fixed vocabulary."""
    from superset.extensions import db

    from supagent.knowledge.values import unknown
    from supagent.models import KObject

    idx, old = _learned_whole(db, KObject)
    many = KObject(source_id=idx.source_id, kind="field", parent="jobs", name="TARGET", data_type="keyword",
                   stats={"values": [f"host{i:03d}" for i in range(30)]})
    db.session.add(many)
    db.session.commit()
    try:
        assert unknown('SELECT COUNT(*) FROM "jobs" WHERE "TARGET" = \'host999\'') == []
        assert unknown('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'CLOSED\'')               # a vocabulary still
    finally:
        idx.stats = old
        db.session.delete(many)
        db.session.commit()


def test_a_question_back_about_sources_when_the_value_is_in_one_of_them_is_needless(world):
    """"For the <app> jobs of 23 September: how many ran, failed...?" answered with "which of these sources: the
    jobs, the batch runs, the reports?", when the value named is a value of only one of the offered sources: needless
    (sent back with a compulsory query). A question back that offers no source, or a value in two offered sources,
    is left alone."""
    from superset.extensions import db

    from supagent.knowledge.resolve import needless_ask
    from supagent.models import KObject
    from supagent.security import acting_as

    idx = db.session.query(KObject).filter_by(kind="index", name="jobs").one()
    batch = KObject(source_id=idx.source_id, kind="index", name="batch", stats={"docs": 10})
    db.session.add(batch)
    db.session.commit()
    try:
        with acting_as("admin"):
            ask = ("Which of these sources should I use?\n1. jobs (index `jobs`)\n2. batch runs (index `batch`)")
            assert needless_ask("How many jobs ran on srv-1 on 23 September?", ask) == ("srv-1", "NODE", "jobs")
            assert needless_ask("How many jobs ran on srv-1 on 23 September?",
                                "Do you mean the jobs that started or the ones that ended that day?") is None
            assert needless_ask("How many jobs ran yesterday?", ask) is None                     # no value named
    finally:
        db.session.delete(batch)
        db.session.commit()
