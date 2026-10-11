"""(0.10.8) "Orders dropped to almost nothing around 08:00: why?" answered "the data does not show a drop" from hourly
totals: the drop lasted some minutes inside its hour. An observation the question states at a time of day, denied
from queries that summed whole hours or days, is sent back once to read it by minutes around that time."""

from __future__ import annotations


def _trace(*sqls):
    return [{"tool": "execute_sql", "status": "done", "args": {"request": {"database_id": 1, "sql": q}}} for q in sqls]


HOURLY = "SELECT DATE_TRUNC('hour', ts) AS t, SUM(increase) AS n FROM \"tickets_total\" GROUP BY 1"
MINUTES = "SELECT DATE_TRUNC('minute', ts) AS t, SUM(increase) AS n FROM \"tickets_total\" GROUP BY 1"
Q = "The tickets stopped coming in around 09:15 on 4 March. Why?"
DENIED = "The data does not show a stop: 52 tickets in the 09:00 hour, as on other days."


def test_a_premise_denied_from_hourly_totals(ctx):
    from supagent.agent import premise_denied_coarse

    assert premise_denied_coarse(Q, DENIED, _trace(HOURLY)) == ("09:15", "hour")
    assert premise_denied_coarse(Q, DENIED, _trace(HOURLY, MINUTES)) is None            # read by minutes too
    assert premise_denied_coarse(Q, "They stopped at 09:14: the intake job failed.", _trace(HOURLY)) is None
    assert premise_denied_coarse("Why did the tickets stop on 4 March?", DENIED, _trace(HOURLY)) is None   # no time
