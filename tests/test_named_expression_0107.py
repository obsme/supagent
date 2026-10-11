"""(0.10.7) A count of a metric written SUM(CAST(x AS BIGINT)), which the metrics source cannot compute: the same
call sent three times (the repeats refused, not run) counted as three failures of the source, and the query that
fixed it (SUM(x)) was refused too; a simple question went over its budget. Repeats not run are not failures, and a
call without the expression the error names runs."""

from __future__ import annotations

import json

ERR = json.dumps({"success": False, "error": "PushdownError: SUM(CAST(n AS BIGINT)): cannot be computed inside the "
                  "metrics source. What this database can run: one metric table per query"})


def test_a_call_without_the_named_expression_runs(ctx):
    from supagent.agent import fixes_named

    err = json.loads(ERR)["error"]
    assert fixes_named(err, {"request": {"sql": 'SELECT SUM(n) FROM "m"'}})
    assert not fixes_named(err, {"request": {"sql": 'SELECT SUM(CAST(n AS BIGINT)) FROM "m" WHERE a = 1'}})
    assert not fixes_named("Column x does not exist", {"request": {"sql": "SELECT 1"}})


def test_repeats_not_run_are_no_failures_of_the_source(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    bad = {"request": {"database_id": 1, "sql": 'SELECT SUM(CAST(n AS BIGINT)) AS c FROM "m"'}}
    good = {"request": {"database_id": 1, "sql": 'SELECT SUM(n) AS c FROM "m"'}}
    ok = json.dumps({"success": True, "columns": [{"name": "c"}], "rows": [{"c": 42}], "row_count": 1})
    results = lambda n, args: ERR if "CAST" in json.dumps(args) else ok  # noqa: E731
    a, ran = agent_with(monkeypatch, [call("execute_sql", bad), call("execute_sql", bad), call("execute_sql", bad),
                                      call("execute_sql", good), say("42 in all.")], results=results)
    answer, _trace = a.ask("How many requests were there in all?")
    assert [json.dumps(r[1]) for r in ran].count(json.dumps(good)) == 1 and answer.startswith("42 in all")
