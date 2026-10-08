"""(0.10) The search judged: weak when a word of the question no piece holds was read as nothing, or when the reranker
(the judge) scores the best piece under rerank.judge_floor; weak and search.rewrite = weak: the LLM writes the question
again once and both searches are fused; a question the search found well never waits for the LLM. The agent is told
which words no piece holds."""

from __future__ import annotations

import pytest


@pytest.fixture()
def conf(ctx, monkeypatch):
    from supagent import settings
    from supagent.knowledge import judge, spelling

    values = {"search.rewrite": "weak", "rerank.judge_floor": "", "search.rewrite_seconds": 4.0}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: values[k] if k in values else real(k))
    unknown: dict[str, list] = {}
    monkeypatch.setattr(spelling, "correct", lambda q: {"query": q, "changes": [], "unknown": unknown.get(q, [])})
    judge._CACHE.clear()
    return values, unknown


def piece(ref, rerank=None):
    return {"ref": ref, "kind": "doc", "title": ref, "text": ref, **({"rerank": rerank} if rerank is not None else {})}


def test_the_verdict_needs_no_llm(conf):
    from supagent.knowledge.judge import verdict

    values, unknown = conf
    assert verdict("payment timeout", [piece("doc:1")])["weak"] is False
    unknown["paymnet tmieout zz"] = ["tmieout"]
    v = verdict("paymnet tmieout zz", [piece("doc:1")])
    assert v["weak"] and v["unknown"] == ["tmieout"] and "no piece holds 'tmieout'" in v["why"][0]
    values["rerank.judge_floor"] = "0.2"                       # the reranker judges
    assert verdict("payment timeout", [piece("doc:1", 0.05), piece("doc:2", 0.12)])["weak"] is True
    assert verdict("payment timeout", [piece("doc:1", 0.6), piece("doc:2", 0.12)])["weak"] is False
    values["rerank.judge_floor"] = ""
    assert verdict("payment timeout", [piece("doc:1", 0.05)])["weak"] is False      # no floor: no judging
    assert verdict("payment timeout", [])["weak"] is True


def test_weak_written_again_once_and_fused(conf):
    from supagent.knowledge.judge import judged

    values, unknown = conf
    unknown["the paymnet gatwey tmieout"] = ["gatwey"]
    asked, ran = [], []

    def run(q):
        ran.append(q)
        return [piece("doc:1"), piece("doc:2")] if q.startswith("the") else [piece("doc:3"), piece("doc:1")]

    def ask(messages):
        asked.append(messages)
        return "<think>fix it</think>\nQuery: payment gateway timeout"

    found, v = judged("the paymnet gatwey tmieout", run, 3, ask)
    assert ran == ["the paymnet gatwey tmieout", "payment gateway timeout"] and len(asked) == 1
    assert "gatwey" in asked[0][1]["content"] and v["searched_also"] == "payment gateway timeout"
    assert [f["ref"] for f in found] == ["doc:1", "doc:3", "doc:2"]          # in both lists: first
    ran.clear()
    found, v = judged("payment timeout", run, 3, ask)                        # found well: no LLM
    assert len(asked) == 1 and ran == ["payment timeout"] and "searched_also" not in v
    values["search.rewrite"] = "off"
    found, v = judged("the paymnet gatwey tmieout", run, 3, ask)
    assert v["weak"] and "searched_also" not in v and len(asked) == 1         # off: never


def test_a_rewrite_that_fails_or_repeats_leaves_the_first_search(conf):
    from supagent.knowledge.judge import judged, rewrite

    _values, unknown = conf
    unknown["shard alocation"] = ["alocation"]

    def boom(_m):
        raise RuntimeError("LLM down")
    assert rewrite("shard alocation", ["alocation"], boom) is None
    assert rewrite("shard alocation", ["alocation"], lambda _m: "Shard alocation") is None   # the same query
    found, v = judged("shard alocation", lambda q: [piece("doc:9")], 5, boom)
    assert [f["ref"] for f in found] == ["doc:9"] and v["weak"] and "searched_also" not in v


def test_the_tool_tells_the_agent_which_words_no_piece_holds(conf, monkeypatch):
    from supagent import tools
    from supagent.knowledge import search as S

    values, unknown = conf
    values["search.rewrite"] = "off"
    unknown["xqzzv tuning"] = ["xqzzv"]
    monkeypatch.setattr(S, "search", lambda q, k=None, kinds=None, **kw: [piece("doc:4")])
    monkeypatch.setattr(tools, "_as_user", lambda: __import__("contextlib").nullcontext())
    out = tools.search_knowledge("xqzzv tuning")
    assert out["no_piece_holds"] == ["xqzzv"] and "if misspelled, search again" in out["note"]


def test_without_a_reranker_the_closeness_by_meaning_judges(conf):
    from supagent.knowledge.judge import verdict

    values, _unknown = conf
    far = [dict(piece("doc:1"), cos=0.31), dict(piece("doc:2"), cos=0.28)]
    q = "why does the payment time out at night?"
    assert verdict(q, far)["weak"] is False                                # no floor set: not judged
    values["search.judge_meaning_floor"] = "0.45"
    v = verdict(q, far)
    assert v["weak"] and "by meaning is 0.310" in v["why"][0]
    assert verdict(q, [dict(piece("doc:1"), cos=0.62)])["weak"] is False
    assert verdict("payment timeout", far)["weak"] is False                # keywords: not judged by meaning
