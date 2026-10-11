"""(0.10.7) A follow-up counted every day; sent back for the chat's period, the model ran no query and wrote that its
figures were "for the orders placed between 14 and 20 September". Such an answer is sent back once with a query
made compulsory."""

from __future__ import annotations

import json


def test_the_period_said_without_a_query_is_sent_back(ctx, monkeypatch):
    from supagent.agent import Agent, PERIOD_CLAIMED_NUDGE
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 7}], "row_count": 1})
    every = {"request": {"database_id": 1, "sql": 'SELECT COUNT(*) AS n FROM "parcels" WHERE "LATE" = true'}}
    within = {"request": {"database_id": 1, "sql": 'SELECT COUNT(*) AS n FROM "parcels" WHERE "LATE" = true AND '
                          "\"ORDERED\" >= '2031-03-14' AND \"ORDERED\" < '2031-03-21'"}}
    replies = [call("execute_sql", every), say("7 late parcels."),
               say("For the orders placed between 14 and 20 March 2031, 7 parcels were late."),
               call("execute_sql", within), say("7 late parcels in that week.")]
    a, ran = agent_with(monkeypatch, replies, results=lambda n, args: rows)
    lost = iter([["parcels"]])
    monkeypatch.setattr(Agent, "_period_lost", lambda self, trace: next(lost, None))
    chat = [{"role": "user", "content": "How many parcels of the orders placed from 14 to 20 March 2031 were late?"},
            {"role": "assistant", "content": "5 parcels."}]
    answer, _trace = a.ask("Which of them were late?", chat)
    assert answer.startswith("7 late parcels in that week") and len(ran) == 2
    told = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith("(Check")]
    assert PERIOD_CLAIMED_NUDGE in told
