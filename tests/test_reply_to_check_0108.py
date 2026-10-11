"""(0.10.8) A right list sent back by a check (a field the question names, never read) came back as a reply to the
check: "The question asks which ... I answered with ... So I used the field X, which directly answers the question",
the list itself never written again. A reply that argues, with none of the results, keeps the answer it replaces."""

from __future__ import annotations

import json

ROWS = json.dumps({"success": True, "columns": [{"name": "TOOL"}, {"name": "n"}],
                   "rows": [{"TOOL": "tool-a1", "n": 12}, {"TOOL": "tool-b2", "n": 7}], "row_count": 2})
SQL = {"request": {"database_id": 1, "sql": "SELECT TOOL, COUNT(*) AS n FROM builds GROUP BY TOOL"}}
DRAFT = "The teams use two build tools: tool-a1 (12 builds) and tool-b2 (7 builds)."
ARGUES = ("The question asks which build tools are used. The field TEAM exists, but the question did not ask for a "
          "breakdown by team, so I used the TOOL field, which directly answers the question.")


def _agent(monkeypatch, reply):
    from test_agent_loop import agent_with, call, say

    a, _ran = agent_with(monkeypatch, [call("execute_sql", SQL), say(DRAFT), say(reply)],
                         results=lambda n, args: ROWS)
    told = []
    a._fields_named = lambda q, trace: [] if told else told.append(1) or ["TEAM"]   # the check fires once
    return a


def test_a_reply_that_argues_keeps_the_answer_it_replaces(ctx, monkeypatch):
    a = _agent(monkeypatch, ARGUES)
    answer, _trace = a.ask("Which build tools do the teams use?")
    assert answer.startswith(DRAFT)


def test_a_reply_with_results_is_the_answer(ctx, monkeypatch):
    again = "The teams use tool-a1 (12 builds) and tool-b2 (7 builds); the TOOL field holds the tool of each build."
    a = _agent(monkeypatch, again)
    answer, _trace = a.ask("Which build tools do the teams use?")
    assert answer.startswith(again)


def test_what_tells_a_reply_that_argues():
    from supagent.agent import REPLY_TALK, argues_back, sent_back_draft

    assert REPLY_TALK.search(ARGUES) and REPLY_TALK.search("I answered with the list above.")
    assert not REPLY_TALK.search("The teams use two tools.")
    tool = {"role": "tool", "content": ROWS}
    msgs = [{"role": "user", "content": "q"}, tool, {"role": "assistant", "content": DRAFT},
            {"role": "user", "content": "(Check before answering: ...)"}, {"role": "assistant", "content": ARGUES}]
    assert sent_back_draft(msgs) == DRAFT and argues_back(ARGUES, DRAFT, msgs)
    made_up = "The teams use tool-z9 (40 builds)."                   # figures no tool gave: never brought back
    assert not argues_back(ARGUES, made_up, msgs[:2] + [{"role": "assistant", "content": made_up}] + msgs[3:])


def test_a_reply_that_only_repeats_one_of_its_figures_keeps_the_answer(ctx, monkeypatch):
    stands = "Good: the 12 builds of tool-a1 are confirmed. The answer stands."
    a = _agent(monkeypatch, stands)
    answer, _trace = a.ask("Which build tools do the teams use?")
    assert answer.startswith(DRAFT)
