"""(0.10.7, obs7dev-l) "What does our runbook say to check when <an alert> fires?": the agent searched the knowledge
with the kind "guide" (the tool's description puts runbooks there), which found nothing: the runbook is a wiki page,
a document. Its second search, with the kind "doc", was refused as the one search of a simple question, and the
answer said the alert's own summary, not the runbook. A search of one kind that finds nothing searches every kind
(said so); a search that found nothing does not count as the question's one search."""
from __future__ import annotations

from test_judge_010 import conf, piece  # noqa: F401  (the fixture and its pieces)


def test_a_kind_that_finds_nothing_searches_every_kind(conf, monkeypatch):  # noqa: F811
    from supagent import tools
    from supagent.knowledge import search as S

    values, _unknown = conf
    values["search.rewrite"] = "off"
    seen: list = []

    def search(q, k=None, kinds=None, **kw):
        seen.append(kinds)
        return [] if kinds else [piece("doc:7")]

    monkeypatch.setattr(S, "search", search)
    monkeypatch.setattr(tools, "_as_user", lambda: __import__("contextlib").nullcontext())
    out = tools.search_knowledge("runbook zqalert what to check", kind="guide")
    assert [f["ref"] for f in out["results"]] == ["doc:7"]                  # (later: the documentation first)
    assert seen == [("guide", "doc"), ("guide", "doc", "teamnote"), None]
    assert "nothing of the kind 'guide': every kind searched" in out["note"]
    seen.clear()
    plain = tools.search_knowledge("runbook zqalert what to check")       # no kind: searched once, nothing said
    assert [f["ref"] for f in plain["results"]] == ["doc:7"] and seen == [None] and "note" not in plain


def test_a_search_that_found_nothing_is_not_the_one_search(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    from supagent import agent as agent_mod

    empty = '{"query": "zqalert runbook", "results": []}'
    a, ran = agent_with(monkeypatch, [call("search_knowledge", {"query": "zqalert runbook", "kind": "guide"}),
                                      call("search_knowledge", {"query": "zqalert runbook", "kind": "doc"}),
                                      say("The runbook says to check the recent changes first.")],
                        results=lambda n, args: empty if args.get("kind") == "guide" else
                        '{"query": "zqalert runbook", "results": [{"ref": "doc:7", "text": "check the changes"}]}')
    a.names = a.names | {"search_knowledge"}
    a.ask("What does our runbook say to check when zqalert fires?")
    assert [n for n, _args in ran] == ["search_knowledge", "search_knowledge"]   # the second one ran
    assert agent_mod.found_nothing({"result": empty}) and not agent_mod.found_nothing({"result": "{\"results\": [1]}"})
