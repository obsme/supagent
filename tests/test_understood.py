"""How a question is understood before the work (0.9.6): a call made at the same time as the router's (its own
instruction and tool, read_question) writes the question again as one precise request in the team's names (used to
find the knowledge and the earlier answers, shown to the user) and says whether it is a general question (a script, a
technology in general), answered without the platform's data. A reading that brings a name or a value of its own is
not used."""

import json
import types

from test_agent_loop import agent_with, call, say

from supagent.agent import GENERAL_NOTE, UNDERSTOOD_NOTE, Agent, knowledge_found, restated_ok
from supagent.router import Decision, extras


def routed(restated="", general=False, given=""):
    msg = {"role": "assistant", "content": "", "tool_calls": [{"id": "r", "function": {"name": "route_question",
           "arguments": json.dumps({"scores": {"functional": 80}, "route": "functional", "restated": restated,
                                    "general": general})}}]}
    return msg


def test_the_router_call_gives_the_reading_and_general():
    assert extras(routed("How many failed jobs on 26 September per application", False)) == \
        ("How many failed jobs on 26 September per application", False)
    assert extras(routed("", True)) == ("", True)
    assert extras({"content": '{"route": "other", "general": "true", "restated": "x  y"}'}) == ("x y", True)
    assert extras({"content": "nothing"}) == ("", False)


def test_a_reading_with_a_name_of_its_own_is_not_used():
    given = "Parts named: payment-legacy (application)\nQuestion: how many erors of paymnt yesterday"
    q = "how many erors of paymnt yesterday"
    assert restated_ok("How many errors did payment-legacy log yesterday", q, given)
    assert not restated_ok("How many errors did payment-gw log yesterday", q, given)          # a name not given
    assert not restated_ok("How many errors did payment-legacy log on 2026-09-26", q, given)  # a date of its own
    assert not restated_ok("How many erors of paymnt yesterday?", q, given)                   # nothing more
    assert not restated_ok("", q, given)


def decision(restated="", general=False, given=""):
    return Decision(route="other", restated=restated, general=general, given=given)


def test_the_reading_goes_with_the_question(ctx, no_ledger, monkeypatch):
    q = "how many failed jbos yesterday"
    monkeypatch.setattr(Agent, "route", lambda self, question, previous="": decision(
        "How many failed jobs yesterday", given=f"Question: {q}"))
    a, ran = agent_with(monkeypatch, [say("No figure here.")] * 3)
    a.ask(q)
    first_user = next(m for m in a.llm.seen[0] if m["role"] == "user")
    assert "Understood as: How many failed jobs yesterday" in first_user["content"]
    assert a.understood["as"] == "How many failed jobs yesterday" and not a.understood["general"]
    monkeypatch.setattr(Agent, "route", lambda self, question, previous="": decision(
        "How many failed jobs of PRICER-FX yesterday", given=f"Question: {q}"))
    b, _ = agent_with(monkeypatch, [say("No figure here.")] * 3)
    b.ask(q)
    assert "Understood as" not in next(m for m in b.llm.seen[0] if m["role"] == "user")["content"]
    assert UNDERSTOOD_NOTE.startswith("(Understood as: {restated}")


def test_a_general_question_is_answered_without_the_platform(ctx, monkeypatch):
    monkeypatch.setattr(Agent, "route", lambda self, question, previous="": decision(general=True))
    a, ran = agent_with(monkeypatch, [say("Use reversed(xs) or xs[::-1].")])
    answer, trace = a.ask("How do I reverse a list in Python?")
    assert answer == "Use reversed(xs) or xs[::-1]." + GENERAL_NOTE and trace == [] and not ran
    sent = a.llm.seen[0]
    assert sent[0]["role"] == "system" and "general question" in sent[0]["content"] and len(sent) == 2
    assert a.understood["general"] is True


def test_a_general_question_that_needs_the_platform_goes_the_normal_way(ctx, no_ledger, monkeypatch):
    monkeypatch.setattr(Agent, "route", lambda self, question, previous="": decision(general=True))
    a, ran = agent_with(monkeypatch, [say("NEEDS_DATA"), call("execute_sql", {"request": {"database_id": 1,
                                       "sql": "SELECT 1 AS n"}}), say("A: 3, B: 2.")])
    answer, trace = a.ask("Which script failed most this week?")
    assert answer.startswith("A: 3") and len(ran) == 1 and not a.understood["general"]
    assert any(m["role"] == "system" and "general question" not in m["content"] for m in a.llm.seen[-1])


def test_what_a_search_found_is_kept_readable():
    found = knowledge_found(json.dumps({"query": "x", "results": [
        {"kind": "doc", "title": "Runbook of the payment service", "ref": "doc:12", "text": "..."},
        {"kind": "metric", "title": "probe_success"}]}))
    assert found == [{"kind": "doc", "title": "Runbook of the payment service", "ref": "doc:12"},
                     {"kind": "metric", "title": "probe_success"}]
    assert knowledge_found("not json") == []


def test_the_reading_is_the_first_step_on_the_page():
    from supagent.runner import _steps_for_page

    agent = types.SimpleNamespace(understood={"as": "How many failed jobs yesterday", "general": False,
                                              "similar": [{"question": "failed jobs yesterday", "status": "helpful",
                                                           "uses": 3}]})
    steps = _steps_for_page([{"tool": "search_knowledge", "status": "done", "args": {"query": "jobs"},
                              "result": "{}", "found": [{"kind": "doc", "title": "Jobs"}]}], agent)
    assert steps[0]["tool"] == "understood" and steps[0]["args"]["as"].startswith("How many")
    assert steps[1]["found"] == [{"kind": "doc", "title": "Jobs"}]
    assert _steps_for_page([], types.SimpleNamespace(understood={"as": "", "general": False, "similar": []})) == []


def test_the_reading_is_no_tool_call_for_the_learned_answers():
    from supagent.knowledge.experience import trace_of

    m = types.SimpleNamespace(results=[], steps=[{"tool": "understood", "status": "done", "args": {"as": "x"}},
                                                 {"tool": "execute_sql", "status": "done", "args": {"sql": "SELECT 1"}}])
    assert [t["tool"] for t in trace_of(m)] == ["execute_sql"]
