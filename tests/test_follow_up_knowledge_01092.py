"""(0.10.9.2) A follow-up's knowledge is searched with the question it goes on from: "Which team had the most among
them?" after a question about the tickets that missed their target searches the tickets' words too, not only the
follow-up's ("most", "them"), where another subject's entries of the same word could come first."""
from __future__ import annotations

import types


def test_a_follow_ups_knowledge_search_holds_the_question_it_goes_on_from(ctx, monkeypatch):
    from supagent import settings
    from supagent.agent import Agent
    from supagent.knowledge import search as S
    from supagent.security import acting_as

    asked = []
    monkeypatch.setattr(S, "knowledge_block", lambda q, *a, **k: asked.append(q) or "")
    settings.set_value("search.enabled", True)
    a = object.__new__(Agent)
    a.username, a.rich, a.wants_saved_chart = "admin", True, False
    a.superset = types.SimpleNamespace(available=True, error=None)
    a.intent_text = "How many support tickets missed their response target last week?\nWhich team had the most among them?"
    with acting_as("admin"):
        a._question_blocks("Which team had the most among them?", set())
    assert asked and "support tickets missed their response target" in asked[0]
    a.intent_text = "Which team had the most among them?"            # a first question: its own words only
    asked.clear()
    with acting_as("admin"):
        a._question_blocks("Which team had the most among them?", set())
    assert asked and asked[0].startswith("Which team had the most among them?") and "tickets" not in asked[0]
