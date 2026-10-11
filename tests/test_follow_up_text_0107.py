"""(0.10.7, obs7dev-u) "How many times were the checkout pods killed for memory that morning?" after the root cause
was found: the check "where the rows ran, never read" took the follow-up for the investigation (it read the chat's
first question with it) and sent the count back for the pods' hosts: the model wrote the whole report again, the
count lost. The checks and limits made for an investigation read the question itself: a follow-up that asks a figure
or a summary is no investigation, nor an open question."""
from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)

WHY = "Why did the zq jobs fail this morning? Find the root cause."
COUNT = "How many times did they fail that morning?"
TRACE = [{"tool": "execute_sql", "called": "execute_sql", "status": "done",
          "args": {"request": {"sql": "SELECT COUNT(*) FROM \"jobs\" WHERE \"STATUS\" = 'FAILED'"}}, "result": "{}"}]


def test_a_follow_up_count_is_not_asked_where_the_rows_ran(world, monkeypatch):  # noqa: F811
    from test_agent_loop import agent_with, say

    from supagent.agent import Agent

    monkeypatch.setattr(Agent, "_route_intents", lambda self: set())
    a, _ran = agent_with(monkeypatch, [say("x")])
    a.intent_text = WHY
    assert a._where_unread(WHY, "The jobs failed because the disk was full.", TRACE) is not None   # the investigation
    a.intent_text, a.raw_question = f"{WHY}\n{COUNT}", COUNT
    assert a._where_unread(COUNT, "They failed 4 times.", TRACE) is None                         # its follow-up count


def test_a_follow_up_count_is_no_open_question_for_the_send_backs(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    from supagent.agent import Agent

    monkeypatch.setattr(Agent, "_route_intents", lambda self: set())
    a, _ran = agent_with(monkeypatch, [say("x")])
    a.open_question, a.intent_text = True, f"{WHY}\n{COUNT}"
    assert a._asks_open(COUNT) is False                                 # a count of the investigation
    a.intent_text = f"{WHY}\nAnd why was the disk full?"
    assert a._asks_open("And why was the disk full?") is True           # a follow-up that asks why: still open
    a.intent_text = WHY
    assert a._asks_open(WHY) is True
