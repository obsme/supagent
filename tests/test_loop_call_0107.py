"""(0.10.7, M3-0107n C15.5) "Back to <a server>: what was its lowest available memory that day, in GiB?" was answered
with no query (a figure made up), sent back with a tool compulsory; the model wrote 15,806 characters going round in
circles instead of the call, was told to "write the final answer from the results above" (there were none) and wrote
the made-up figure again. A step that had to call a tool and went round in circles is asked for the call again."""
from __future__ import annotations

import json

CIRCLES = ("I will now check the lowest available memory of zq-node-17 for that day in GiB.\n"
           "To do so I need the zq_mem_available_bytes series of zq-node-17 over the whole day.\n"
           "Then I will take its minimum and convert it from bytes to GiB by dividing by 1073741824.\n") * 4


def test_circles_where_a_call_was_due_ask_for_the_call(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    from supagent.agent import LOOP_CALL_NUDGE, LOOP_NUDGE, Agent

    rows = json.dumps({"success": True, "columns": [{"name": "low_gib"}], "rows": [{"low_gib": 2.56}], "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": "SELECT MIN(value) / 1073741824 AS low_gib FROM "
                                                 "zq_mem_available_bytes WHERE instance = 'zq-node-17'"}}
    made_up = say("The lowest available memory of zq-node-17 that day was 1.37 GiB.")
    a, ran = agent_with(monkeypatch, [made_up, say(CIRCLES), call("execute_sql", sql),
                                      say("The lowest available memory of zq-node-17 that day was 2.56 GiB.")],
                        results=lambda n, args: rows)
    prompt = Agent.prompt

    def asks_new(self, question, history=None):              # a follow-up asking for another measure: the step
        out = prompt(self, question, history)                 # after the no-query send-back must call a tool
        self.asks_new = True
        return out

    monkeypatch.setattr(Agent, "prompt", asks_new)
    answer, _trace = a.ask("Back to zq-node-17: what was its lowest available memory that day, in GiB?")
    assert answer.startswith("The lowest available memory of zq-node-17 that day was 2.56 GiB.") and len(ran) == 1
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user"]
    assert LOOP_CALL_NUDGE in sent and LOOP_NUDGE not in sent
    assert a.llm.choices[:3] == [None, "required", "required"]           # the call compulsory again


def test_circles_after_results_ask_for_the_answer(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    from supagent.agent import LOOP_CALL_NUDGE, LOOP_NUDGE

    rows = json.dumps({"success": True, "columns": [{"name": "OWNER"}], "rows": [{"OWNER": "T37"}], "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": "SELECT \"OWNER\" FROM \"assets\" WHERE \"NAME\" = 'zq-gw'"}}
    a, _ran = agent_with(monkeypatch, [call("execute_sql", sql), say(CIRCLES), say("T37 runs zq-gw.")],
                         results=lambda n, args: rows)
    answer, _trace = a.ask("Who runs zq-gw?")
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user"]
    assert answer.startswith("T37 runs zq-gw.") and LOOP_NUDGE in sent and LOOP_CALL_NUDGE not in sent
