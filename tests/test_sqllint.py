"""Mistakes a query shows by its own text (0.9.2): one aggregate under two names, a time read from buckets."""

from __future__ import annotations

import json


def test_two_columns_with_one_aggregate_are_sent_back_before_the_query_runs():
    from supagent.knowledge.sqllint import duplicate_refusal, same_aggregates

    lost = ('SELECT SUM(increase) AS errors_500, SUM(increase) AS total_requests, ROUND(100.0 * SUM(increase) FILTER '
            '(WHERE "code" = \'500\') / SUM(increase), 2) AS share_pct FROM "requests" WHERE "app" = \'A\'')
    assert same_aggregates(lost) == [("errors_500", "total_requests", "SUM(increase)")]
    said = duplicate_refusal("execute_sql", {"request": {"database_id": 1, "sql": lost}})
    assert said.startswith("tool error (not run: two columns, one expression)") and "FILTER (WHERE" in said
    kept = 'SELECT SUM(increase) FILTER (WHERE "code" = \'500\') AS errors_500, SUM(increase) AS total FROM "requests"'
    assert same_aggregates(kept) == [] and duplicate_refusal("execute_sql", {"request": {"sql": kept}}) is None
    assert same_aggregates("SELECT COUNT(*) FROM jobs") == [] and same_aggregates("not sql at all (") == []
    assert duplicate_refusal("promql_query", {"request": {"promql": "sum(x)"}}) is None


def test_a_time_of_day_read_from_hour_buckets_is_sent_back_once(ctx, monkeypatch):
    from supagent.agent import GRAIN_NUDGE
    from supagent.knowledge.sqllint import time_from_bucket
    from test_agent_loop import agent_with, call, say

    hourly = ("SELECT DATE_TRUNC('hour', ts) AS t, MAX(value) AS top FROM \"load1\" WHERE node = 'n1' "
              "GROUP BY 1 ORDER BY 2 DESC LIMIT 1")
    assert time_from_bucket("At what time was it?", "It peaked at **04:00**.", [hourly]) == ("04:00", "hour")
    assert time_from_bucket("At what time was it?", "Between 04:00 and 05:00.", [hourly]) == ("04:00", "hour")
    raw = "SELECT ts, value FROM \"load1\" WHERE node = 'n1' ORDER BY value DESC LIMIT 5"
    assert time_from_bucket("At what time was it?", "At 04:26.", [hourly, raw]) is None     # the moment was read
    assert time_from_bucket("What was the load per hour?", "04:00: 3.4", [hourly]) is None  # no time of day asked
    rows = json.dumps({"success": True, "rows": [{"t": "2026-09-24 04:00", "top": 3.38}], "row_count": 1})
    moment = json.dumps({"success": True, "rows": [{"ts": "2026-09-24 04:26", "value": 3.38}], "row_count": 1})
    replies = [call("execute_sql", {"request": {"database_id": 2, "sql": hourly}}), say("It peaked at 04:00."),
               call("execute_sql", {"request": {"database_id": 2, "sql": raw}}), say("It peaked at 04:26.")]
    a, _ran = agent_with(monkeypatch, replies, results=lambda n, args: rows if "DATE_TRUNC" in args["request"]["sql"]
                         else moment)
    answer, _trace = a.ask("At what time was the highest load of n1 on 24 September?")
    assert answer.startswith("It peaked at 04:26.")
    assert any(m["content"] == GRAIN_NUDGE.format(time="04:00", grain="hour") for m in a.llm.seen[2] if m["role"] == "user")
