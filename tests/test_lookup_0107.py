"""(0.10.7) "Which database user and which application held the long transaction on orders-db on 28 September in the
afternoon?" was read as an incident by the router: the investigation's steps (the facts against usual, where, why, the
check) took all 33 calls, the answer found at the 24th. Facts asked by their name are a lookup. "How many errors did
X log on 30 September?" was answered "0 errors" with "no logs of X exist in any of the indices" in the same answer."""
from __future__ import annotations

from supagent.agent import Agent, absent_zero, lookup_asked
from supagent.router import Decision


def _agent(raw: str, intent_text: str | None = None, route: str = "incident") -> Agent:
    a = object.__new__(Agent)
    a.moa = Decision(route=route)
    a.raw_question, a.intent_text = raw, intent_text or raw
    return a


def test_facts_asked_by_their_name_are_a_lookup():
    for q in ("Which database user and which application held the long transaction on the orders database on 28 "
              "September in the afternoon?", "When did the export job start on the 28th, and when did it end?",
              "On which servers does the orders database run?", "How many orders were placed on 29 September?",
              "Combien de commandes ont échoué hier ?"):
        assert lookup_asked(q), q
    for q in ("Which change caused the checkout errors on 2 October?", "Which servers were slow on the 27th?",
              "Was the database overloaded during the network incident?", "What was the root cause of the failures?",
              "Which application is responsible for the lock?", "Checkout failed at 09:00. Which change was it?",
              "Which deploy broke checkout?", "Which change triggered the cache evictions?"):
        assert not lookup_asked(q), q


def test_an_incident_route_of_a_lookup_is_no_investigation():
    q = "Which database user and which application held the long transaction on the orders database on the 28th?"
    a = _agent(q)
    assert "investigation" not in a._route_intents() and a._route_intents()     # the route's other tools stay
    assert not a._investigating(q)
    q = "Which change caused the checkout errors on 2 October?"
    assert _agent(q)._investigating(q)
    q = "Which metrics show it on the database side?"                 # a follow-up of an investigation: still one
    assert _agent(q, "Checkout was slow on 28 September. What was the cause?\n" + q)._investigating(q)
    q = "Which database user held the long transaction?"
    assert not _agent(q, route="infrastructure")._investigating(q)
    assert _agent(q)._incident_lookup() and not _agent(q, route="infrastructure")._incident_lookup()
    q = "Which change caused the checkout errors on 2 October?"
    assert not _agent(q)._incident_lookup()


def test_an_incident_lookup_keeps_the_route_but_not_the_steps():
    """The route's tools and the parts' whole picture stay (where their servers' logs are); the note is the lookup's,
    not the investigation's steps."""
    from supagent import agent as A
    from supagent.router import ROUTE_INTENTS

    q = "Which database user held the long transaction on the orders database on the 28th?"
    a = _agent(q)
    assert a._incident_lookup()
    assert a._route_intents() == (ROUTE_INTENTS["incident"] - {"investigation"}) | {"system"}   # records_about
    assert "not for a cause" in A.LOOKUP_NOTE and "investigation" not in A.LOOKUP_NOTE
    assert "own log lines" in A.LOOKUP_NOTE and "author" in A.LOOKUP_NOTE     # (who ran it: the part's logs)


def test_a_zero_for_what_the_data_holds_nothing_of():
    assert absent_zero("There are **0 errors** logged by `jobs-runner` on September 30.\n\nThis is because **no "
                       "application logs for `jobs-runner` exist in any of the available log indices**.")
    assert absent_zero("No failures were recorded: the service's logs are not collected.")
    assert not absent_zero("There were 0 failed checkout orders on 25 September (the orders counter, status failed).")
    assert not absent_zero("No logs of jobs-runner are collected: none of the log indices holds it, so its errors "
                           "cannot be counted.")
    assert not absent_zero("Payment logged 10 errors; the logs of the legacy service are not collected by this "
                           "shipper.")
