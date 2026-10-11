"""(0.10.7) "And how many trades of that desk were cancelled that day?" was answered with a query written out (the
right one) and a count no query gave (12; the data: 4), the check's "run it" and its compulsory call ignored: 176 s,
no call, marked. The query the answer wrote is then run once, and the answer is written from its rows."""
from __future__ import annotations

import json

from test_agent_loop import agent_with, say

WRITTEN = ("Of the trades the D1 desk did that day, **12** were cancelled.\n\n```sql\nSELECT COUNT(*) AS cancelled\n"
           "FROM \"trades\"\nWHERE \"DESK\" = 'D1'\n  AND \"TRADE_DATE\" = '2026-09-23'\n  AND \"STATUS\" = 'CANCELLED'\n"
           "```\n\n| cancelled |\n|---|\n| 12 |")
HISTORY = [{"role": "user", "content": "How many trades did the D1 desk do on 23 September?"},
           {"role": "assistant", "content": "The D1 desk did 93 trades on 23 September.",
            "queries": [{"tool": "execute_sql", "database_id": 7,
                         "query": "SELECT COUNT(*) FROM \"trades\" WHERE \"DESK\" = 'D1' AND \"TRADE_DATE\" = '2026-09-23'"}]}]


def test_the_query_written_with_a_made_up_result_is_run(ctx, monkeypatch):
    rows = json.dumps({"success": True, "columns": [{"name": "cancelled"}], "rows": [{"cancelled": 4}], "row_count": 1})
    a, ran = agent_with(monkeypatch, [say(WRITTEN), say(WRITTEN), say("Of the trades of the D1 desk that day, **4** "
                                                                      "were cancelled.")],
                        results=lambda n, args: rows)
    answer, trace = a.ask("And how many trades of that desk were cancelled that day?", HISTORY)
    assert ran and ran[0][0] == "execute_sql" and ran[0][1]["request"]["database_id"] == 7
    assert "'CANCELLED'" in ran[0][1]["request"]["sql"] and answer.startswith("Of the trades of the D1 desk that day, **4**")
    assert [t["tool"] for t in trace] == ["execute_sql"]


def test_a_query_asked_for_is_not_run(ctx, monkeypatch):
    """The user asks for the query itself: writing it is the answer, nothing runs."""
    text = "Here is the query:\n\n```sql\nSELECT COUNT(*) FROM \"trades\" WHERE \"STATUS\" = 'CANCELLED'\n```"
    a, ran = agent_with(monkeypatch, [say(text), say(text)])
    answer, _trace = a.ask("Write me the SQL query that counts the cancelled trades.", HISTORY)
    assert not ran and "SELECT COUNT(*)" in answer
