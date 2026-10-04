"""Questions to ask back instead of guessing (0.9.2): one thing named that several values match, or a conversation
that starts with something never said."""

from __future__ import annotations

import pytest

BOOKS = ["BK_VANILLA_A", "FX_OPT_EM", "FX_OPT_EXOTICS", "FX_OPT_G10", "IR_EUR_OPTIONS", "IR_USD_OPTIONS",
         "IR_EUR_SWAPS", "IR_USD_SWAPS", "FX_SPOT_G10"]
SERVICES = ["svc-ir", "svc-fx", "svc-eq"]


def values_of(head: str) -> dict[str, list[str]]:
    return {"book": {"BOOK": BOOKS}, "pricer": {"PRICER": SERVICES}, "desk": {"DESK": ["D_ONE", "D_TWO"]},
            "acme": {"ACME_RUN_MODE": ["HYBRID", "FULL", "NA", "NONE"]},
            "job": {"JOB_EXEC_TYPE": ["BATCH", "INTRADAY", "ONDEMAND", "RERUN"]},
            "report": {"REPORT": ["DAILY_PNL_FLASH", "DAILY_PNL_OFFICIAL", "TRADER_PNL"]}}.get(head, {})


@pytest.mark.parametrize("question, history, expected", [
    ("How did the options book do yesterday?", [], ["FX_OPT_EM", "FX_OPT_EXOTICS", "FX_OPT_G10", "IR_EUR_OPTIONS",
                                                   "IR_USD_OPTIONS"]),
    ("What was the PnL of the swaps book yesterday?", [], ["IR_EUR_SWAPS", "IR_USD_SWAPS"]),
    ("What was the PnL of the FX options book yesterday?", [], ["FX_OPT_EM", "FX_OPT_EXOTICS", "FX_OPT_G10"]),
    ("Show me the failures of the pricer yesterday.", [], ["svc-eq", "svc-fx", "svc-ir"]),
    ("How did the options books do yesterday?", [], None),                  # all of them: nothing to choose
    ("Which book lost the most money on 22 September?", [], None),          # asks for it
    ("What was the VaR of the desk with the highest PnL?", [], None),       # restricted
    ("What was the PnL of the book that lost the most yesterday?", [], None),
    ("How did the FX_OPT_EM book do yesterday?", [], None),                 # named
    ("What is the timeout of the pricer?", [], None),                       # no day: no one pricer meant
    ("How much was refunded for SHOES in September?", [], None),
    ("And the desk's flash PnL that day?", [{"role": "assistant", "content": "D_ONE made 3."}], None),   # said before
    # 0.9.2 candidate A asked back on these two (a name before the noun, a noun before the noun):
    ("What was the average duration of the ACME jobs on 22 September, in minutes?", [], None),
    ("Which error category caused the most job failures in PROD on 23 September?", [], None),
    ("How long did the job take yesterday?", [], None),       # a word after the noun: a verb or a noun, not told
    ("How long was the job yesterday?", [], ["BATCH", "INTRADAY", "ONDEMAND", "RERUN"]),   # apart: not asked
    ("Note for the desk: the meeting of 30 September moved.", [], None),                   # no day of the desk
    ("I need the failed jobs of today with their duration and the desk.", [], None),       # the day is before it
    ("How many trades for the D_ONE desk yesterday?", [], None),                           # a value of it named
    ("Was the official PnL report late yesterday?", [], None),                             # its words name one
    ("Was the PnL report late yesterday?", [], ["DAILY_PNL_FLASH", "DAILY_PNL_OFFICIAL", "TRADER_PNL"]),
])
def test_one_thing_named_that_several_values_match(question, history, expected):
    from supagent.knowledge.ambiguity import ask_first

    found = ask_first(question, history, values_of)
    assert (found or {}).get("candidates") == expected


def test_a_conversation_that_starts_with_something_never_said():
    from supagent.knowledge.ambiguity import ask_first, note

    for q in ("Show me the late ones from yesterday.", "How many were late yesterday?", "List them for yesterday."):
        found = ask_first(q, [], values_of)
        assert found and found["kind"] == "unclear", q
        assert "starts the conversation" in note(found)
    said = [{"role": "user", "content": "Which parcels were delivered late?"}, {"role": "assistant", "content": "12."}]
    assert ask_first("Show me the late ones from yesterday.", said, values_of) is None     # they were named
    choice = ask_first("How did the options book do yesterday?", [], values_of)
    assert "FX_OPT_EM, FX_OPT_EXOTICS" in note(choice) and "run no query" in note(choice)


def test_the_agent_is_told_to_ask_and_an_answer_that_guesses_is_sent_back_once(ctx, monkeypatch):
    from supagent import settings
    from supagent.agent import ASK_FIRST_NUDGE
    from supagent.knowledge import ambiguity
    from test_agent_loop import agent_with, call, say

    monkeypatch.setattr(ambiguity, "db_values_of", values_of)
    guess = say("The FX_OPT_EM book made 186,235 EUR yesterday.")
    asked = say("Which options book do you mean: FX_OPT_EM, FX_OPT_EXOTICS, FX_OPT_G10, IR_EUR_OPTIONS or IR_USD_OPTIONS?")
    a, ran = agent_with(monkeypatch, [guess, asked])
    answer, trace = a.ask("How did the options book do yesterday?")
    assert "Ask back first" in a.llm.seen[0][-1]["content"] and "IR_USD_OPTIONS" in a.llm.seen[0][-1]["content"]
    assert a.llm.seen[1][-1]["content"] == ASK_FIRST_NUDGE and answer == asked["content"] and ran == []
    b, _ran = agent_with(monkeypatch, [asked])
    b.ask("How did the options book do yesterday?")
    assert not b.usage.get("nudges")                                     # asked at once: nothing more
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: False if key == "agent.ask_unclear" else real(key))
    c, _ran = agent_with(monkeypatch, [call("execute_sql", {"request": {"database_id": 1, "sql": "SELECT 1"}}),
                                       say("A: 3, B: 2.")])
    c.ask("How did the options book do yesterday?")
    assert "Ask back first" not in c.llm.seen[0][-1]["content"]
