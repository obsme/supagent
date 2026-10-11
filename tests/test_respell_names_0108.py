"""(0.10.8, the team's request of 11 October) "When a server or component name is given, the search should manage
capital and lower cases and special characters": a query comparing a field (or a metric's label) with a name
written another way than the data writes it ('HOST-A-07', 'host_a_7' for host-a-07) found nothing. Such a
value is rewritten as the data writes it before the query runs (only when one value is written so), and said."""

from __future__ import annotations

import json

from test_knowledge import world  # noqa: F401  (the fixture)


def _fields(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.store import upsert

    upsert(world["run"], world["s_jobs"], "field", "jobs", "HOST",
           {"data_type": "keyword", "stats": {"cardinality": 3, "values": ["host-a-07", "host-b-10", "Web-01"]}})
    upsert(world["run"], world["s_prom"], "label", "node_load1", "node",
           {"stats": {"cardinality": 2, "values": ["host-a-07", "host-b-10"]}})
    db.session.commit()


def test_a_name_written_another_way_is_written_as_the_data_writes_it(world):  # noqa: F811
    from supagent.knowledge.values import loose, respell_promql, respell_sql

    _fields(world)
    sql, changes = respell_sql('SELECT COUNT(*) FROM "jobs" WHERE "HOST" = \'HOST-A-07\'')
    assert "'host-a-07'" in sql and changes == [("HOST-A-07", "host-a-07")]
    sql, changes = respell_sql('SELECT COUNT(*) FROM "jobs" WHERE "HOST" IN (\'host_a_7\', \'web 01\')')
    assert "'host-a-07'" in sql and "'Web-01'" in sql and len(changes) == 2
    same = 'SELECT COUNT(*) FROM "jobs" WHERE "HOST" = \'host-b-10\''
    assert respell_sql(same) == (same, [])                                       # as written: untouched
    other = 'SELECT COUNT(*) FROM "jobs" WHERE "HOST" = \'host-c-01\''
    assert respell_sql(other) == (other, [])                                     # no value written so
    expr, changes = respell_promql('max_over_time(node_load1{node="HOST-A-07"}[1h])')
    assert 'node="host-a-07"' in expr and changes
    assert loose("HOST_A_07") == loose("host-a-7") == loose("Host A 007")


def test_two_values_written_so_leave_it_as_written(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.store import upsert
    from supagent.knowledge.values import respell_sql

    upsert(world["run"], world["s_jobs"], "field", "jobs", "APP",
           {"data_type": "keyword", "stats": {"cardinality": 2, "values": ["Pay-Gw", "pay_gw"]}})
    db.session.commit()
    sql = 'SELECT COUNT(*) FROM "jobs" WHERE "APP" = \'PAY GW\''
    assert respell_sql(sql) == (sql, [])                                         # which one: not guessed


def test_the_query_runs_with_it_and_its_result_says_so(world, monkeypatch):  # noqa: F811
    from test_agent_loop import agent_with, call, say

    _fields(world)
    rows = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 7}], "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": 'SELECT COUNT(*) AS n FROM "jobs" WHERE "HOST" = \'HOST-A-07\''}}
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), say("7 jobs ran on host-a-07.")] * 2,
                        results=lambda n, args: rows)
    a.ask("How many jobs ran on HOST-A-07?")
    assert "'host-a-07'" in ran[0][1]["request"]["sql"]
    told = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"]
    assert any("'HOST-A-07' is written 'host-a-07' in the data" in t for t in told)


def test_the_result_stays_whole_for_the_page(world, monkeypatch):  # noqa: F811
    """The note goes after the result with the system's notes: the query's own result (its rows, for the table and
    the chart under the answer) stays JSON, and a long result never cuts the note."""
    from supagent.runner import _results_of
    from test_agent_loop import agent_with, call, say

    _fields(world)
    rows = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 7}], "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": 'SELECT COUNT(*) AS n FROM "jobs" WHERE "HOST" = \'HOST-A-07\''}}
    a, _ran = agent_with(monkeypatch, [call("execute_sql", sql), say("7 jobs ran on host-a-07.")] * 2,
                         results=lambda n, args: rows)
    _answer, trace = a.ask("How many jobs ran on HOST-A-07?")
    step = next(t for t in trace if t.get("tool") == "execute_sql")
    assert json.loads(step["full"])["rows"] == [{"n": 7}]
    assert "is written 'host-a-07' in the data" in step["result"]
    assert [r["rows"] for r in _results_of(trace)] == [[[7]]]


def test_the_map_finds_a_name_written_any_way():
    from supagent.knowledge.brief import loose_index, named

    names = {"host-a-07": [1], "payment service": [2]}
    loose, slips = loose_index(names)
    g = {"names": names, "values": {1: {"name": "host-a-07"}, 2: {"name": "payment service"}},
         "loose": loose, "slips": slips}
    assert named("errors on HOST-A-07 today", g, loose=True) == [1]
    assert named("errors on host_a_07 today", g, loose=True) == [1]
    assert named("is Payment-Service slow?", g, loose=True) == [2]
