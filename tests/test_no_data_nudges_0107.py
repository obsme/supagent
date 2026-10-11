"""(0.10.7) Follow-ups answered with figures no query gave ("And its average over that day?": a table of 24 hours
written from the chat's earlier answers, cut in the middle; "how many were cancelled?": a count made up): before any
query of the answer, the messages sent after an unreadable tool call or a cut answer no longer say "write the answer
with what you have" or "from the results above"."""
from __future__ import annotations

import json

from test_agent_loop import agent_with, call, say

AVG = json.dumps({"success": True, "columns": [{"name": "avg"}], "rows": [{"avg": 2.26}], "row_count": 1})


def test_an_unreadable_call_before_any_query_asks_for_the_query(ctx, monkeypatch):
    from supagent.agent import UNREADABLE_CALL, UNREADABLE_NO_DATA
    from supagent.llm import LLMError

    bad = LLMError('LLM x/chat/completions: HTTP 500: {"error":{"message":"Failed to parse tool call arguments as '
                   'JSON"}}')
    a, ran = agent_with(monkeypatch, [bad, call("execute_sql", {"sql": "SELECT AVG(value) FROM load"}),
                                      say("The average was 2.26.")], results=lambda n, args: AVG)
    answer, _trace = a.ask("And its average over that day?")
    sent = [m["content"] for m in a.llm.seen[1] if m["role"] == "user"]
    assert sent[-1] == UNREADABLE_NO_DATA and "write the answer with what you have" not in sent[-1]
    assert answer.startswith("The average was 2.26.") and len(ran) == 1
    b, _ran = agent_with(monkeypatch, [call("execute_sql", {"sql": "SELECT 1"}), bad, say("The average was 2.26.")],
                         results=lambda n, args: AVG)
    b.ask("And its average over that day?")
    assert [m["content"] for m in b.llm.seen[-1] if m["role"] == "user"][-1] == UNREADABLE_CALL


def test_a_cut_answer_with_figures_and_no_query_asks_for_the_query(ctx, monkeypatch):
    from supagent.agent import CUT_NO_DATA

    cut = say("The average was **2.80**.\n\n| Hour | Avg |\n|---|---|\n| 00:00 | 2.80 |\n\n```sql\nSELECT DATE_TRUNC")
    a, _ran = agent_with(monkeypatch, [cut, call("execute_sql", {"sql": "SELECT AVG(value) FROM load"}),
                                       say("The average was 2.26.")], results=lambda n, args: AVG)
    a.llm.last_finish = None
    monkeypatch.setattr("supagent.agent.cut_short", lambda answer, finish=None: "SELECT DATE_TRUNC" in answer)
    answer, _trace = a.ask("And its average over that day?")
    assert CUT_NO_DATA in [m["content"] for m in a.llm.seen[1] if m["role"] == "user"]
    assert answer.startswith("The average was 2.26.")
