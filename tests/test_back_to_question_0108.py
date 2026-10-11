"""(0.10.8) "Back to <an earlier question>: ...?" after two follow-ups that narrowed the subject (one carrier, then
its deliveries): the answer counted the last question's scope. The question it goes back to is the one its words
name, said with it: its scope, not the later questions'."""

from __future__ import annotations

from test_subjects import chat, msg

RETURNS = {"tool": "execute_sql", "sql": "SELECT COUNT(*) FROM \"parcels\" WHERE STATE = 'RETURNED'",
           "database": "OpenSearch", "database_id": 1, "columns": ["n"], "rows": [[31]], "row_count": 1}
Q1 = "How many parcels were returned on 4 March?"
Q2 = "Which carrier had the most returns that day?"
Q3 = "How many parcels did that carrier deliver that week?"


def _assign(question):
    from supagent.knowledge import topics

    earlier = chat((Q1, "31 parcels were returned.", 1, [RETURNS]), (Q2, "CARRIER-B with 12 returns.", 1, [RETURNS]),
                   (Q3, "CARRIER-B delivered 940 parcels.", 1, [RETURNS]))
    q, a = msg(7, "user", question), msg(8, "assistant", "")
    d, _hist = topics.assign(earlier, q, a)
    return d


def test_the_earlier_question_named_is_said_with_the_later_ones(ctx):
    d = _assign("Back to the returns of the 4th: how many were there on the 3rd?")
    assert d.topic == 1 and d.returns_to == Q1 and d.after == [Q2, Q3]


def test_nothing_said_when_the_words_name_no_one_question_or_the_last(ctx):
    assert _assign("Back to that carrier: how many parcels did it deliver the week before?").returns_to is None
    assert _assign("And how many were returned on the 3rd?").returns_to is None      # no "back to"


def test_the_note_goes_with_the_question(ctx, monkeypatch):
    from supagent.agent import BACK_TO_NOTE
    from test_agent_loop import agent_with, say

    d = _assign("Back to the returns of the 4th: how many were there on the 3rd?")
    a, _ran = agent_with(monkeypatch, [say("No figure.")] * 6)
    a.subject = d
    a.ask("Back to the returns of the 4th: how many were there on the 3rd?")
    first = next(m["content"] for m in a.llm.seen[0] if m["role"] == "user")
    assert BACK_TO_NOTE.split("{")[0].strip() in first and f"«{Q1}»" in first and f"«{Q3}»" in first


def test_the_note_speaks_of_conditions_not_of_what_is_asked():
    from supagent.agent import BACK_TO_NOTE

    assert "conditions" in BACK_TO_NOTE and "What it counts" not in BACK_TO_NOTE
    assert "what it asks, and in which unit, is its own" in BACK_TO_NOTE
