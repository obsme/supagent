"""(0.10.7) A level asked at a time of day answered with the average of the hour that starts then: a level that
moves within the hour is not its average over the hour. Sent back once to read the samples at the moment itself."""

from __future__ import annotations

import json

HOURLY = ("SELECT DATE_TRUNC('hour', ts) AS t, AVG(value) AS v FROM \"m\" WHERE ts >= TIMESTAMP '2031-03-03 08:00' "
          "AND ts < TIMESTAMP '2031-03-03 10:00' GROUP BY 1 ORDER BY 1")
RAW = "SELECT ts, value FROM \"m\" WHERE ts >= TIMESTAMP '2031-03-03 09:30' AND ts < TIMESTAMP '2031-03-03 09:31'"


def test_a_value_at_a_moment_is_not_its_hours_average():
    from supagent.knowledge.sqllint import value_at_moment

    assert value_at_moment("What was the memory use of the cache at 09:30 on 3 March?", [HOURLY]) == ("09:30", "hour")
    assert value_at_moment("What was the memory use of the cache at 9h30 on 3 March?", [HOURLY]) == ("09:30", "hour")
    assert value_at_moment("What was the memory use of the cache at 09:30 on 3 March?", [HOURLY, RAW]) is None   # the samples read
    assert value_at_moment("What was the memory use of the cache around 09:30 on 3 March?", [HOURLY]) is None
    assert value_at_moment("At what time was the cache's memory highest?", [HOURLY]) is None       # a time asked: the other check
    summed = HOURLY.replace("AVG(value)", "SUM(value)")
    assert value_at_moment("How many errors at 09:30 on 3 March?", [summed]) is None   # a count: that hour


def test_the_answer_is_sent_back_once(ctx, monkeypatch):
    from supagent.agent import MOMENT_NUDGE
    from test_agent_loop import agent_with, call, say

    rows = lambda n, args: json.dumps({"success": True, "row_count": 1, "rows": [  # noqa: E731
        {"v": 0.64} if "09:31" in args["request"]["sql"] else {"t": "2031-03-03 09:30", "v": 0.71}]})
    sql = lambda q: {"request": {"database_id": 1, "sql": q}}  # noqa: E731
    a, _ran = agent_with(monkeypatch, [call("execute_sql", sql(HOURLY)), say("It was 0.71."),
                                       call("execute_sql", sql(RAW)), say("It was 0.64.")], results=rows)
    answer, _trace = a.ask("What was the memory use of the cache at 09:30 on 3 March 2031?")
    assert answer.startswith("It was 0.64")
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith("(Check")]
    assert sent and sent[0] == MOMENT_NUDGE.format(time="09:30", grain="hour")
