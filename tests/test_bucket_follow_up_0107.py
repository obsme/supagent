"""(0.10.7) "At what time was it?" after "What was the highest 1-minute load of the server on the 24th?" (its query by
hour): answered "04:00" from the answer before's hourly rows, with no query (the peak: 04:26). A follow-up answered
with no query of its own is checked against the queries of the answer before."""
from __future__ import annotations

from supagent.agent import Agent

HOURLY = ("SELECT DATE_TRUNC('hour', ts) AS t, MAX(value) AS max_load FROM \"node_load1\" WHERE ts >= TIMESTAMP "
          "'2026-09-24 00:00' AND ts < TIMESTAMP '2026-09-25 00:00' AND node = 'srv-1' GROUP BY 1 ORDER BY 1")


def _agent(raw: str, follow: bool) -> Agent:
    a = object.__new__(Agent)
    a.raw_question = raw
    a.intent_text = ("What was the highest 1-minute load of srv-1 on the 24th?\n" + raw) if follow else raw
    a.prev_queries = [HOURLY]
    return a


def test_a_time_read_from_the_hours_of_the_answer_before(ctx):
    q = "At what time was it?"
    assert _agent(q, True)._time_from_bucket(q, "The peak of 3.38 was at **04:00**.", []) == ("04:00", "hour")
    assert _agent(q, False)._time_from_bucket(q, "The peak of 3.38 was at **04:00**.", []) is None   # not a follow-up
    minutes = [{"tool": "execute_sql", "status": "done", "args": {"request": {"database_id": 3, "sql": (
        "SELECT ts, value FROM \"node_load1\" WHERE node = 'srv-1' AND ts >= TIMESTAMP '2026-09-24 04:00' AND ts < "
        "TIMESTAMP '2026-09-24 05:00' ORDER BY value DESC LIMIT 1")}}}]
    assert _agent(q, True)._time_from_bucket(q, "It peaked at 04:26.", minutes) is None   # read from the samples
