"""(0.10.8) An answer's table gave "(value from earlier result)" in two cells: a result pointed at, its value never
written. Sent back once to write the values or leave the rows out."""

from __future__ import annotations

import json

ROWS = json.dumps({"success": True, "columns": [{"name": "h"}, {"name": "n"}],
                   "rows": [{"h": "10:00", "n": 12}, {"h": "11:00", "n": 9}], "row_count": 2})
SQL = {"request": {"database_id": 1, "sql": "SELECT h, COUNT(*) AS n FROM jobs GROUP BY h"}}


def test_a_placeholder_is_found():
    from supagent.agent import PLACEHOLDER

    assert PLACEHOLDER.search("| 11:00 | (value from earlier result) |")
    assert PLACEHOLDER.search("the rest (see the results above)") and PLACEHOLDER.search("| [value] |")
    assert not PLACEHOLDER.search("| 11:00 | 9 | (from the jobs table) |")


def test_the_answer_is_sent_back_once(ctx, monkeypatch):
    from supagent.agent import PLACEHOLDER_NUDGE
    from test_agent_loop import agent_with, call, say

    a, _ran = agent_with(monkeypatch, [call("execute_sql", SQL), say("| h | n |\n|---|---|\n| 10:00 | 12 |\n| 11:00 | "
                                                                      "(value from earlier result) |"),
                                       *[say("| h | n |\n|---|---|\n| 10:00 | 12 |\n| 11:00 | 9 |")] * 4],
                         results=lambda n, args: ROWS)
    answer, _trace = a.ask("How many jobs ran per hour this morning?")
    told = [m["content"] for seen in a.llm.seen for m in seen if m["role"] == "user"]
    assert any(PLACEHOLDER_NUDGE.split("(")[1][:30] in t for t in told) and "| 11:00 | 9 |" in answer
