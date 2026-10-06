"""The tool calls of one question are a hard limit (0.9.6): the setting says "Tool calls per question at most", but
the loop counted the model's turns, each of which may run up to eight calls, and an investigation, a dashboard or a
question of many parts had more turns still: an answer could run three times the calls set (51 for 16 was seen). Now
every call run counts, an investigation or a dashboard has its own explicit limit, the updates of the work plan do not
count, and when the calls are used none runs any more: the model answers with what it found."""

import json

from test_agent_loop import agent_with, last_calls, say


def many(k: int, start: int) -> dict:
    """One message of the model with k calls (different queries)."""
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"m{start + j}", "function": {"name": "execute_sql", "arguments": json.dumps(
            {"request": {"database_id": 1, "sql": f"SELECT {start + j} AS n"}})}} for j in range(k)]}


def test_eight_calls_a_turn_stop_at_the_limit(ctx, no_ledger, monkeypatch):
    a, ran = agent_with(monkeypatch, [many(8, 0), many(8, 100), say("Answered from 10 results.")])
    answer, trace = a.ask("Which applications ran the most jobs?")          # an answer: 10 calls (agent_with)
    assert len(ran) == 10                                                  # not 16
    refused = [m for m in a.llm.seen[-1] if m["role"] == "tool" and "the 10 tool calls of this question are used"
               in str(m["content"])]
    assert len(refused) == 6
    assert answer.startswith("Answered")


def test_an_investigation_has_its_own_limit(ctx, no_ledger, monkeypatch):
    a, ran = agent_with(monkeypatch, [many(8, 0), many(8, 100), say("The cause, from what was found.")])
    a.max_steps_big = 15
    answer, _ = a.ask("Why did the jobs fail yesterday?")
    assert len(ran) == 15 and answer.startswith("The cause")
    a2, ran2 = agent_with(monkeypatch, [many(8, 0), many(8, 100), many(8, 200), many(8, 300), say("The cause.")])
    a2.ask("Why did the jobs fail yesterday?")                              # unset: twice the answer's 10
    assert len(ran2) == 20


def test_the_work_plan_is_not_counted(ctx, monkeypatch):
    wp = {"role": "assistant", "content": "", "tool_calls": [
        {"id": f"w{k}", "function": {"name": "work_plan", "arguments": json.dumps(
            {"tasks": [{"title": f"Step {k}", "status": "in_progress"}]})}} for k in range(3)]}
    a, ran = agent_with(monkeypatch, [wp, many(8, 0), many(8, 100), say("Done.")])
    a.ask("Which applications ran the most jobs, which failed most, which ran longest, and which were late?")
    assert len([r for r in ran if r[0] == "execute_sql"]) == 15             # many parts: 1.5 x 10


def test_the_calls_left_are_said_as_they_are(ctx, no_ledger, monkeypatch):
    a, ran = agent_with(monkeypatch, [many(8, 0), many(1, 50), say("Answered.")])
    a.ask("Which applications ran the most jobs?")
    told = [m for m in a.llm.seen[-1] if last_calls(m)]
    assert len(told) == 1 and told[0]["content"].startswith("(2 tool calls are left") and len(ran) == 9
