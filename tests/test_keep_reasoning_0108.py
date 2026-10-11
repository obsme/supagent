"""(0.10.8, to measure) gpt-oss keeps its plan between its tool calls when its reasoning is sent back with them (as
OpenAI advises; vLLM and llama.cpp read it from the assistant message): with llm.keep_reasoning on, the assistant
message of a tool call keeps the reasoning the server gave, in the field it gave it; off (the default), as before."""
from __future__ import annotations

import json


def _run(monkeypatch, on: bool):
    from test_agent_loop import agent_with, say

    from supagent import settings

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: on if k == "llm.keep_reasoning" else real(k))
    rows = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 3}], "row_count": 1})
    step = {"role": "assistant", "content": "", "reasoning_content": "Count the zq rows first.",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "execute_sql", "arguments": json.dumps(
                {"request": {"database_id": 1, "sql": "SELECT COUNT(*) AS n FROM zq"}})}}]}
    a, _ran = agent_with(monkeypatch, [step, say("There are 3 zq rows.")], results=lambda n, args: rows)
    a.ask("How many zq rows are there?", [])
    sent = a.llm.seen[-1]
    return next(m for m in sent if m["role"] == "assistant" and m.get("tool_calls"))


def test_the_reasoning_of_a_tool_call_is_sent_back_when_asked(ctx, monkeypatch):
    assert _run(monkeypatch, True).get("reasoning_content") == "Count the zq rows first."
    assert "reasoning_content" not in _run(monkeypatch, False)          # the default: as before
