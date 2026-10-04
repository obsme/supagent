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


def test_or_then_and_without_parentheses_is_sent_back_before_the_query_runs():
    """"How does the 23rd's total compare with the same weekday one week earlier?" written WHERE (day 23) OR (day 16)
    AND STATUS IN ('PAID', 'DELIVERED') AND CHANNEL <> 'TEST': AND binds first, the 23rd counted every order (three
    versions, three wrong answers). Parentheses around the alternatives pass; an OR alone passes."""
    from supagent.knowledge.sqllint import or_and_refusal, or_then_and

    day23 = "(\"ORDER_TIME\" >= '2030-01-23' AND \"ORDER_TIME\" < '2030-01-24')"
    day16 = "(\"ORDER_TIME\" >= '2030-01-16' AND \"ORDER_TIME\" < '2030-01-17')"
    rules = "\"STATUS\" IN ('PAID', 'DELIVERED') AND \"CHANNEL\" <> 'TEST'"
    bad = f'SELECT SUM("AMOUNT_EUR") FROM "orders" WHERE {day23} OR {day16} AND {rules}'
    assert "STATUS" in (or_then_and(bad) or "") and "2030-01-16" in or_then_and(bad)
    back = or_and_refusal("execute_sql", {"request": {"database_id": 1, "sql": bad}})
    assert back.startswith("tool error (not run: AND before OR)") and "WHERE (a OR b) AND c" in back
    good = f'SELECT SUM("AMOUNT_EUR") FROM "orders" WHERE ({day23} OR {day16}) AND {rules}'
    assert or_then_and(good) is None and or_and_refusal("execute_sql", {"request": {"sql": good}}) is None
    assert or_then_and('SELECT 1 FROM "t" WHERE "A" = 1 OR "B" = 2') is None                          # OR alone
    assert or_then_and(f'SELECT 1 FROM "t" WHERE {day23} OR {day16}') is None                          # in parentheses
    assert or_and_refusal("describe_data", {"index": "orders"}) is None


def test_an_average_per_day_computed_over_the_records_is_sent_back():
    """"FX_SPOT desk, September: average unexplained PnL per day?" as AVG over the records: 448.64 for 2,691.84
    (the daily totals averaged over the 19 days). A per-day step (GROUP BY the day, COUNT(DISTINCT day)) passes;
    another question passes."""
    from supagent.knowledge.sqllint import per_day_refusal

    q = "FX_SPOT desk, September: average unexplained PnL per day (official figures)?"
    rows = {"request": {"sql": 'SELECT AVG("PNL_UNEXPLAINED") FROM "pnl" WHERE "DESK" = \'FX_SPOT\''}}
    back = per_day_refusal(q, "execute_sql", rows)
    assert back.startswith("tool error (not run: average per day)") and "COUNT(DISTINCT the day)" in back
    per_day = {"request": {"sql": 'SELECT AVG(t) FROM (SELECT "COB_DATE", SUM("PNL_UNEXPLAINED") AS t FROM "pnl" '
                                  'GROUP BY "COB_DATE") d'}}
    assert per_day_refusal(q, "execute_sql", per_day) is None
    ratio = {"request": {"sql": 'SELECT SUM("PNL_UNEXPLAINED") / COUNT(DISTINCT "COB_DATE") FROM "pnl"'}}
    assert per_day_refusal(q, "execute_sql", ratio) is None
    assert per_day_refusal("What was the average unexplained PnL of a record?", "execute_sql", rows) is None
    assert per_day_refusal("Quelle est la moyenne par jour du PnL inexpliqué ?", "execute_sql", rows)


def test_a_column_named_for_one_extreme_computed_with_the_other_is_sent_back():
    """"What was its lowest available memory that day, in GiB?" computed MAX(value) / 2^30 AS min_mem_gib: 95.95 GiB
    (the highest) for 2.56. Only the alias's first word: max_duration_min (minutes) and ts_at_max pass."""
    from supagent.knowledge.sqllint import extreme_mismatch, extreme_refusal

    bad = 'SELECT MAX(value) / 1024.0 / 1024.0 / 1024.0 AS min_mem_gib FROM "node_memory" WHERE node = \'srv-a\''
    assert extreme_mismatch(bad) == "MAX(...) AS min_mem_gib"
    back = extreme_refusal("execute_sql", {"request": {"sql": bad}})
    assert back.startswith("tool error (not run: the other extreme)")
    assert extreme_mismatch('SELECT MIN(latency) AS highest_latency FROM "t"') == "MIN(...) AS highest_latency"
    assert extreme_mismatch('SELECT MAX("DURATION_S") / 60 AS max_duration_min FROM "jobs"') is None
    assert extreme_mismatch('SELECT MIN(ts) AS ts_at_max FROM "t" WHERE value = 3') is None
    assert extreme_mismatch('SELECT MIN(value) AS min_value, MAX(value) AS max_value FROM "t"') is None
