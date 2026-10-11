"""(0.10.8) "Which database user held the long transaction?" answered with the user of the lines the query kept
(message LIKE '%transaction%'): "process ... still waiting for ShareLock on transaction ... [user=X]", the victims.
The holder ran long statements then, in lines without that word. A name the answer gives for who held it, which the
results only show waiting for a lock, is sent back once."""

from __future__ import annotations

import json

WAITS = "LOG:  process {p} still waiting for ShareLock on transaction 77 after 1200.5 ms [user=app_writer]"
HOLDS = "LOG:  duration: 61000.1 ms  statement: SELECT * FROM t [user=etl_reader application_name=nightly-export]"
Q = "Which database user held the long transaction on db-x yesterday afternoon?"


def _trace(*lines):
    rows = [{"host": "db-x", "message": m} for m in lines]
    return [{"tool": "execute_sql", "status": "done", "result": json.dumps({"success": True, "rows": rows})}]


def test_a_name_the_lines_only_show_waiting():
    from supagent.agent import waiter_named

    trace = _trace(WAITS.format(p=11), WAITS.format(p=12))
    assert waiter_named(Q, "The user app_writer held it (application app_writer).", trace) == "app_writer"
    both = _trace(WAITS.format(p=11), HOLDS)
    assert waiter_named(Q, "etl_reader held it, from nightly-export; app_writer waited.", both) is None
    assert waiter_named("How many lock waits were there yesterday?", "app_writer waited 2 times.", trace) is None


def test_the_answer_is_sent_back_to_read_the_holder(ctx, monkeypatch):
    from supagent.agent import WAITER_NUDGE
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "message"}],
                       "rows": [{"message": WAITS.format(p=11)}, {"message": WAITS.format(p=12)}], "row_count": 2})
    sql = {"request": {"database_id": 1, "sql": "SELECT message FROM \"pg-logs\" WHERE message LIKE '%transaction%'"}}
    a, _ran = agent_with(monkeypatch, [call("execute_sql", sql), say("The user app_writer held the transaction."),
                                       *[say("The user etl_reader held it (nightly-export).")] * 4],
                         results=lambda n, args: rows)
    a.ask(Q)
    told = [m["content"] for seen in a.llm.seen for m in seen if m["role"] == "user"]
    assert any(WAITER_NUDGE.split("{")[0] in t for t in told)
