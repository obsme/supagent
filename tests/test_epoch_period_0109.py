"""(0.10.9) A table whose time field holds epoch milliseconds (a number): the period check asked for a filter on it,
and the check of conditions nobody asked for refused the bounds the model then wrote (1727512800000 is no date of the
question), in turn, until the calls ran out. A bound on a table's time field is the question's period, whatever its
form; any other condition is checked as before."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)


def _spans(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.store import upsert

    upsert(world["run"], world["s_jobs"], "index", "", "spans",
           {"stats": {"docs": 100, "time_field": "startMillis", "time_range": ["2026-09-01 00:00", "2026-09-24 23:00"]}})
    upsert(world["run"], world["s_jobs"], "field", "spans", "startMillis", {"data_type": "long", "stats": {}})
    upsert(world["run"], world["s_jobs"], "field", "spans", "duration", {"data_type": "long", "stats": {}})
    db.session.commit()


def test_a_bound_in_epoch_milliseconds_on_the_time_field_is_the_period(world):  # noqa: F811
    from supagent.knowledge.conditions import build, note, refusal

    _spans(world)
    q = "Which service held the longest span on 23 September in the afternoon?"
    s = build([{"role": "user", "content": q}], [q])
    sql = ('SELECT "service", MAX("duration") FROM "spans" WHERE "startMillis" >= 1727092800000 AND '
           '"startMillis" < 1727114400000 GROUP BY 1')
    args = {"request": {"database_id": 1, "sql": sql}}
    assert refusal(s, "execute_sql", args) is None
    trace = [{"tool": "execute_sql", "status": "done", "args": args, "result": "{}"}]
    assert note(s, trace) == ""
    other = {"request": {"database_id": 1, "sql": sql.replace("GROUP BY", 'AND "duration" > 123456 GROUP BY')}}
    told = refusal(build([{"role": "user", "content": q}], [q]), "execute_sql", other)
    assert told and "duration > 123456" in told                    # another number nobody said: sent back as before
