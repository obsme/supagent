"""(0.10.7) "Inventory warns about its cache miss ratio every night. Was that related to the problem of 29 September in
the morning?" was answered yes: the nightly warning taken for the morning's cause, its other nights never looked at."""
from __future__ import annotations

from supagent.agent import CAUSE_ASKED, RECURRING_ASKED


def test_a_recurring_thing_asked_as_a_cause():
    q = "Inventory warns about its cache miss ratio every night. Was that related to the problem of 29 September?"
    assert RECURRING_ASKED.search(q) and CAUSE_ASKED.search(q)
    assert RECURRING_ASKED.search("Is the weekly report job behind the slowdown of Tuesday?")
    assert RECURRING_ASKED.search("Les sauvegardes tournent chaque nuit : sont-elles liées au problème ?")
    assert not RECURRING_ASKED.search("Why did checkout fail on 2 October around 09:00?")
    assert not RECURRING_ASKED.search("How many orders were placed on 30 September?")


def test_a_figure_asked_after_an_investigation_is_not_one():
    """(0.10.7) "How many times were the pods killed for memory that morning?" after "Find the root cause.": the
    whole investigation again (and a count of every event mentioning the kill: twice the kills)."""
    from supagent.agent import Agent

    a = object.__new__(Agent)
    a._route_intents = lambda: set()
    q = "How many times were the pods killed for memory that morning?"
    a.intent_text = "The shop returned errors this morning. Find the root cause.\n" + q
    assert not a._investigating(q)
    q2 = "Why did the pods restart that morning?"
    a.intent_text = "The shop returned errors this morning. Find the root cause.\n" + q2
    assert a._investigating(q2)                         # a cause asked: still one
    a.intent_text = q
    assert not a._investigating(q)
