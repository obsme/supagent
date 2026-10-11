"""(0.10.7) An investigation that named the failing part and its error spent its calls on queries that failed and
never looked up what changed on that part (a deployment): with the plan's step "Deeper" open and no records_about
run, the notice of the last calls comes one call earlier and asks for that lookup first."""

from __future__ import annotations

import json


def test_the_last_calls_go_to_what_changed_first(ctx, monkeypatch):
    from supagent.agent import DEEPER_LAST
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "c"}], "rows": [{"c": 3}], "row_count": 1})
    calls = [call("execute_sql", {"request": {"database_id": 1, "sql": f"SELECT COUNT(*) AS c{k} FROM jobs"}})
             for k in range(22)]
    a, _ran = agent_with(monkeypatch, calls + [say("The jobs were late: their feed was late.")] * 6,
                         results=lambda n, args: rows)
    a.ask("Why are the jobs late this morning?")
    told = [m["content"] for seen in a.llm.seen for m in seen if m["role"] == "user"
            and "left for this answer" in str(m["content"])]
    assert told and DEEPER_LAST.strip()[:40] in told[0]


def test_no_such_notice_once_the_records_were_read(ctx, monkeypatch):
    from supagent.agent import DEEPER_LAST
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "c"}], "rows": [{"c": 3}], "row_count": 1})
    calls = [call("records_about", {"names": ["feed"], "start": "2031-03-03 06:00"})] + [
        call("execute_sql", {"request": {"database_id": 1, "sql": f"SELECT COUNT(*) AS c{k} FROM jobs"}})
        for k in range(22)]
    a, _ran = agent_with(monkeypatch, calls + [say("The jobs were late: their feed was late.")] * 6,
                         results=lambda n, args: rows)
    a.names = a.names | {"records_about"}
    a.ask("Why are the jobs late this morning?")
    told = [m["content"] for seen in a.llm.seen for m in seen if m["role"] == "user"
            and "left for this answer" in str(m["content"])]
    assert told and DEEPER_LAST.strip()[:40] not in told[0]
