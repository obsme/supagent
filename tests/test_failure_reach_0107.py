"""(0.10.7, obs7dev-j) "If the cache's server goes down, what is affected?": system_links said what its failure
reaches (the cache on it, the application that depends on the cache, the application that calls that one) and the
answer named the first two only, then went to the asset inventory to check them. An answer on what a failure affects
that does not name a part system_links said it reaches is sent back once, with those parts; a part that also runs
elsewhere (it may go on there) is not asked for."""
from __future__ import annotations

import json

REACH = {"zqrsrv-1": {
    "runs_on_it": ["zqrcache (cache)", "zqr-exporter (component; also runs on zqrsrv-2, zqrsrv-3)"],
    "then_through_them": ["zqrstock (application) depends on zqrcache"],
    "and_further": ["zqrshop (application) calls zqrstock", "zqrship (component) reads from zqrstock"]}}


def test_the_parts_a_failure_reaches_that_the_answer_leaves_out():
    from supagent.knowledge.leads import reach_unsaid

    q = "If zqrsrv-1 goes down, what is affected?"
    short = "The zqrcache on zqrsrv-1 goes down, and zqrstock, which depends on it, loses its cache."
    assert reach_unsaid(q, short, REACH) == ["zqrshop (application) calls zqrstock",
                                            "zqrship (component) reads from zqrstock"]
    whole = short + " zqrshop calls zqrstock and zqrship reads from it: both are affected."
    assert reach_unsaid(q, whole, REACH) == []                       # every part named (the exporter goes on)
    assert reach_unsaid("How many errors did zqrstock log yesterday?", short, REACH) == []   # no failure asked
    assert reach_unsaid(q, short, {}) == []                          # nothing said by system_links


def test_the_groups_whose_parts_may_go_on_are_not_asked_for():
    from supagent.knowledge.leads import reach_unsaid

    reach = {"zqrsrv-1": {"runs_on_its_group (may go on on the group's other servers)": {"zqrpool": ["zqrjob (job)"]},
                          "runs_on_its_servers": {"zqrsrv-1a": ["zqrdb (database)"]},
                          "goes_down_with_it (runs only on its servers)": ["zqrvm (server) on zqrsrv-1"],
                          "may_go_on (runs on other servers too)": ["zqrweb (application) on zqrsrv-1; also runs on x"]}}
    got = reach_unsaid("If zqrsrv-1 loses power, which applications go down with it?", "Nothing.", reach)
    assert got == ["zqrdb (database)", "zqrvm (server) on zqrsrv-1"]


def test_which_questions_ask_what_a_failure_reaches():
    from supagent.knowledge.leads import IMPACT_ASKED

    for q in ("If cache-a goes down, what is affected?",
              "If rack r-1 loses power, which data stores go down with it, and which applications depend on them?",
              "What would be impacted by a failure of db-2?", "Which services would break if the switch fails?",
              "Si le serveur tombe, qu'est-ce qui est touché ?"):
        assert IMPACT_ASKED.search(q), q
    for q in ("Which servers of rack r-1 had network receive errors on 27 September?",
              "Checkout was slow on 28 September in the afternoon. What was the cause?",
              "What does a request to the site go through before it reaches the gateway?",
              "How many orders failed yesterday?"):
        assert not IMPACT_ASKED.search(q), q


def test_an_answer_short_of_the_reach_is_sent_back_once(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    links = json.dumps({"if_it_fails": REACH, "parts": [{"name": "zqrcache", "category": "cache"}]})
    short = say("The zqrcache on zqrsrv-1 goes down, and zqrstock, which depends on it, loses its cache.")
    whole = say("The zqrcache on zqrsrv-1 goes down; zqrstock depends on it; zqrshop calls zqrstock and zqrship "
                "reads from it: all three are affected.")
    a, ran = agent_with(monkeypatch, [call("system_links", {"names": ["zqrsrv-1"]}), short, whole, whole],
                        results=lambda n, args: links)
    a.names.add("system_links")
    answer, trace = a.ask("If zqrsrv-1 goes down, what is affected?", [])
    assert "zqrshop" in answer and len(ran) == 1
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user"]
    assert any("zqrshop (application) calls zqrstock" in c and "zqr-exporter" not in c for c in sent)
    b, _ran = agent_with(monkeypatch, [call("system_links", {"names": ["zqrsrv-1"]}), short, short, short],
                         results=lambda n, args: links)
    b.names.add("system_links")
    again, _t = b.ask("If zqrsrv-1 goes down, what is affected?", [])
    assert again.startswith("The zqrcache")                         # once: the second answer is kept as it is
