"""One figure of a period answered from per-hour rows only (0.9.6): the database computes it over the period."""

import json

from supagent.agent import by_buckets, figure_from_buckets

Q = "What was the success rate of the login health probe on 15 January?"
HOURLY = ("SELECT DATE_TRUNC('hour', ts) AS t, AVG(value) AS avg_value FROM \"probe_success\" WHERE ts >= TIMESTAMP "
          "'2030-01-15 00:00' AND ts < TIMESTAMP '2030-01-16 00:00' GROUP BY 1 ORDER BY 1")
WHOLE = ("SELECT AVG(value) AS success FROM \"probe_success\" WHERE ts >= TIMESTAMP '2030-01-15 00:00' AND ts < "
         "TIMESTAMP '2030-01-16 00:00'")


def sql(q, rows=None, status="done"):
    out = {"tool": "execute_sql", "status": status, "args": {"request": {"sql": q}}}
    if rows is not None:
        out["result"] = json.dumps({"row_count": rows, "rows": []})
    return out


def test_hours_only_sent_back(ctx):
    assert figure_from_buckets(Q, [sql(HOURLY, 24)])
    assert figure_from_buckets(Q, [sql(HOURLY)])                       # no result kept: by the query
    five = HOURLY.replace("DATE_TRUNC('hour', ts)", "TIME_BUCKET(INTERVAL '5 minutes', ts)")
    assert figure_from_buckets(Q, [sql(five, 288)])


def test_the_period_queried_not_sent_back(ctx):
    assert not figure_from_buckets(Q, [sql(HOURLY, 24), sql(WHOLE, 1)])
    assert not figure_from_buckets(Q, [sql(WHOLE, 1)])
    # the hours of a subquery summed by the outer query: one figure of the period
    nested = f"SELECT SUM(n) AS total, AVG(a) AS mean FROM ({HOURLY.replace(' ORDER BY 1', '')}) AS h"
    assert not by_buckets(nested)
    assert not figure_from_buckets(Q, [sql(nested, 1)])


def test_one_bucket_or_one_row_is_the_period(ctx):
    hour = HOURLY.replace("2030-01-15 00:00", "2030-01-14 09:00").replace("2030-01-16 00:00", "2030-01-14 10:00")
    assert not by_buckets(hour)                                         # a one-hour range by the hour
    assert not by_buckets(HOURLY, json.dumps({"row_count": 1}))
    assert by_buckets(HOURLY, json.dumps({"row_count": 24}))


def test_questions_of_the_hours_or_of_days_left_alone(ctx):
    assert not figure_from_buckets("What was the success rate of the probe per hour on 15 January?", [sql(HOURLY, 24)])
    assert not figure_from_buckets("When was the success rate of the probe lowest on 15 January?", [sql(HOURLY, 24)])
    assert not figure_from_buckets("How many probes ran on 15 January?", [sql(HOURLY, 24)])     # not a rate
    assert not figure_from_buckets("What is the success rate of the probe?", [sql(HOURLY, 24)])   # no period
    days = HOURLY.replace("'hour'", "'day'").replace("2030-01-16", "2030-01-17")
    assert not figure_from_buckets("By how many points did the success rate change between 15 and 16 January?",
                                   [sql(days, 2)])                      # the days compared are the rows
    assert not figure_from_buckets(Q, [sql(HOURLY, 24, status="error")])
    assert not figure_from_buckets(Q, [])


def test_sent_back_once_then_the_period_query_answers(ctx, no_ledger, monkeypatch):
    """In the loop: the answer read from the hours is sent back once; the model runs the period's figure; that
    answer stands (the check is not repeated)."""
    from test_agent_loop import agent_with, call, say

    from supagent.agent import BUCKETS_NUDGE

    def results(name, args):
        sql_text = args["request"]["sql"]
        if "DATE_TRUNC" in sql_text:
            rows = [{"t": f"2030-01-15 {h:02d}:00", "avg_value": 1.0 if h != 9 else 0.75} for h in range(24)]
        else:
            rows = [{"success": 0.9896}]
        return json.dumps({"success": True, "columns": [{"name": k} for k in rows[0]], "rows": rows,
                           "row_count": len(rows)})

    a, ran = agent_with(monkeypatch, [
        call("execute_sql", {"request": {"database_id": 1, "sql": HOURLY}}),
        say("The probe was up all day: 1.0 in 23 of the 24 hours, 0.75 at 09:00."),
        call("execute_sql", {"request": {"database_id": 1, "sql": WHOLE}}),
        say("The probe's success rate on 15 January was 0.9896 (98.96 %)."),
    ], results=results)
    answer = a.ask(Q)
    text = answer if isinstance(answer, str) else getattr(answer, "answer", None) or str(answer)
    assert "0.9896" in text
    nudges = [m for m in a.llm.seen[-1] if m["role"] == "user" and m["content"] == BUCKETS_NUDGE]
    assert len(nudges) == 1
    assert [r[1]["request"]["sql"] for r in ran] == [HOURLY, WHOLE]


def test_another_tool_giving_figures_is_not_sent_back(ctx):
    health = {"tool": "check_health", "status": "done", "args": {"entities": ["login"]}}
    assert not figure_from_buckets(Q, [health, sql(HOURLY, 24)])
    assert not figure_from_buckets("What do the failing calls share on 15 January?", [sql(HOURLY, 24)])
    assert figure_from_buckets("What was the share of failed calls on 15 January?", [sql(HOURLY, 24)])
