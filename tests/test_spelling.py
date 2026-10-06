"""A search's words read as the knowledge spells them (0.9.6, spelling.py): a word no piece holds is read as the known
word one typing slip away (the one most pieces hold), two words typed apart as the known word they make, a word that
is two known words run together as those two; a word known as typed, a short word, a name, a first letter are never
changed; two known words typed apart stay apart when the knowledge has them side by side."""

from __future__ import annotations

import pytest


def look(words: dict[str, int], side: tuple = ()):
    """The knowledge as a lookup: its words (stems, as the store indexes them) with the pieces that hold each, and the
    pairs of words some piece has side by side."""
    from supagent.knowledge.spelling import Lookup

    side = set(side)
    return Lookup(lambda stems: {s for s in stems if s in words},
                  lambda stems: {s: words[s] for s in stems if s in words},
                  lambda pairs: {p for p in pairs if p in side})


def read(query, words, side=()):
    from supagent.knowledge.spelling import read as r

    return r(query, look(words, side))


WORDS = {"refund": 40, "payment": 120, "gateway": 60, "restore": 30, "snapshot": 25, "work": 80, "filter": 50,
         "data": 300, "seconds": 5, "ticket": 9, "rest": 70, "ore": 2, "setup": 12, "set": 90, "up": 50, "mart": 1,
         "lambda": 3}


@pytest.mark.parametrize("typed,expected", [
    ("refnd policy", "refund policy"),            # a letter missing
    ("refunnd policy", "refund policy"),          # a letter twice
    ("paymnet errors", "payment errors"),         # two letters swapped
    ("gatewat timeouts", "gateway timeouts"),     # a key next to it
    ("Restire the snapshot", "restore the snapshot"),
])
def test_one_slip_is_read_as_the_known_word(ctx, typed, expected):
    got = read(typed, WORDS)
    assert got["query"].lower() == expected.lower() and len(got["changes"]) == 1
    assert got["changes"][0]["typed"].lower() == typed.split()[0].lower()


def test_known_short_names_and_first_letters_stay(ctx):
    assert read("refund payment gateway", WORDS)["changes"] == []        # known as typed
    assert read("rfnd tkt", WORDS)["changes"] == []                       # under 5 letters: too many neighbours
    assert read("node_cpu_secnds_total", WORDS)["changes"] == []          # a name: its own near-spelling search
    assert read("paymentGatewy", WORDS)["changes"] == []                  # camelCase: a name
    assert read("rickets", WORDS)["changes"] == []                        # the first letter is never the slip
    assert read("zzzzzzzz", WORDS)["changes"] == []                       # nothing near: searched as typed


def test_the_word_most_pieces_hold_wins(ctx):
    got = read("snapshat", {"snapshot": 25, "snapshut": 300})
    assert got["changes"] == [{"typed": "snapshat", "read": "snapshut"}]  # 300 pieces against 25
    got = read("snapshat", {"snapshot": 25, "snapshut": 3})
    assert got["changes"] == [{"typed": "snapshat", "read": "snapshot"}]


def test_a_floor_of_pieces_for_what_is_offered(ctx, monkeypatch):
    from supagent.knowledge import spelling

    monkeypatch.setattr(spelling, "MIN_PIECES", 2)
    assert read("lambdq functions", {"lambda": 1})["changes"] == []      # held by one piece: not offered
    monkeypatch.setattr(spelling, "MIN_PIECES", 1)
    assert read("lambdq functions", {"lambda": 1})["changes"][0]["read"] == "lambda"


def test_two_words_typed_apart(ctx):
    assert read("wo rking hours", WORDS)["query"] == "working hours"     # a piece of a word: joined
    got = read("Rest ore the snapshot", WORDS)                           # both known, never side by side: joined
    assert got["query"].startswith("restore") and got["changes"][0] == {"typed": "Rest ore", "read": "restore"}
    kept = read("Rest ore the snapshot", WORDS, side=(("rest", "ore"),))
    assert kept["changes"] == []                                          # side by side somewhere: two words
    assert read("set up the gateway", WORDS, side=(("set", "up"),))["changes"] == []
    assert read("payment gateway", {**WORDS, "paymentgateway": 2})["changes"] == []   # two long known words


def test_two_words_run_together(ctx):
    got = read("workingwith snapshots", WORDS)
    assert got["query"] == "working with snapshots"                       # a word and a function word
    assert read("paymentrefund", WORDS)["changes"] == []                  # never side by side: not cut
    got = read("paymentrefund", WORDS, side=(("payment", "refund"),))
    assert got["query"] == "payment refund"
    assert read("lambdamart", {"lambda": 3, "mart": 1}, side=(("lambda", "mart"),))["query"] == "lambda mart"


def test_the_rest_of_the_query_is_kept_as_typed(ctx):
    got = read("Why did the paymnet (EU) fail at 10:00?", WORDS)
    assert got["query"] == "Why did the payment (EU) fail at 10:00?"


def test_correct_asks_the_store_and_says_it(ctx, monkeypatch):
    from supagent import settings
    from supagent.knowledge import pgstore, spelling

    spelling._CACHE.clear()
    monkeypatch.setattr(pgstore, "active", lambda: True)
    monkeypatch.setattr(pgstore, "state", lambda fresh=False: {"version": 7})
    monkeypatch.setattr(pgstore, "holding", lambda stems: {s for s in stems if s in WORDS})
    monkeypatch.setattr(pgstore, "word_counts", lambda stems: {s: WORDS[s] for s in stems if s in WORDS})
    monkeypatch.setattr(pgstore, "side_by_side", lambda pairs: set())
    got = spelling.correct("refunnd policy")
    assert got["query"] == "refund policy" and spelling.said(got["changes"]) == "'refunnd' read as 'refund'"
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: False if k == "search.spelling" else real(k))
    spelling._CACHE.clear()
    assert spelling.correct("refunnd policy")["changes"] == []           # switched off: as typed


def test_a_failing_lookup_leaves_the_query_as_typed(ctx, monkeypatch):
    from supagent.knowledge import pgstore, spelling

    spelling._CACHE.clear()
    monkeypatch.setattr(pgstore, "active", lambda: True)
    monkeypatch.setattr(pgstore, "state", lambda fresh=False: {"version": 8})

    def boom(stems):
        raise RuntimeError("store down")
    monkeypatch.setattr(pgstore, "holding", boom)
    assert spelling.correct("refunnd policy") == {"query": "refunnd policy", "changes": []}


def test_the_search_uses_the_read_words_and_the_tool_says_so(ctx, monkeypatch):
    from supagent import tools
    from supagent.knowledge import pgstore, search, spelling

    spelling._CACHE.clear()
    monkeypatch.setattr(spelling, "correct", lambda q: {"query": q.replace("refunnd", "refund"),
                                                        "changes": [{"typed": "refunnd", "read": "refund"}]}
                        if "refunnd" in q else {"query": q, "changes": []})
    seen = {}
    monkeypatch.setattr(pgstore, "active", lambda: True)

    def fake(query, k, kinds=None, lower=None, skip=(), n=None, words_query=None):
        seen.update(query=query, words_query=words_query)
        return [{"ref": "doc:1#0", "kind": "doc", "title": "Refunds", "text": "how a refund is made", "score": 1}]
    monkeypatch.setattr(pgstore, "search", fake)
    monkeypatch.setattr(tools, "_as_user", lambda: __import__("contextlib").nullcontext())
    out = tools.search_knowledge("refunnd policy")
    assert seen == {"query": "refunnd policy", "words_query": "refund policy"}   # meaning: as typed; words: as read
    assert out["searched_for"] == "refund policy" and out["spelling"] == [{"typed": "refunnd", "read": "refund"}]
    assert "'refunnd' read as 'refund'" in out["note"]


def test_the_step_on_the_page_keeps_what_was_read(ctx):
    import json

    from supagent.agent import knowledge_read

    content = json.dumps({"query": "refunnd", "results": [], "spelling": [{"typed": "refunnd", "read": "refund"}]})
    assert knowledge_read(content) == [{"typed": "refunnd", "read": "refund"}]
    assert knowledge_read(content[:40] + "\n...[truncated]") == []
    assert knowledge_read(json.dumps({"results": []})) == []


def test_a_slip_in_the_stem_is_read_in_the_stem(ctx):
    got = read("Restire the snapshot", {"restore": 30, "rest": 70})
    assert got["changes"] == [{"typed": "Restire", "read": "restore"}]        # not resture (whose stem is rest)
    got = read("paymnets", {"payment": 120})
    assert got["changes"] == [{"typed": "paymnets", "read": "payments"}]
    got = read("deducing", {"deduce": 4})                                     # the stemmer's deduc: deduce
    assert got["changes"] == [{"typed": "deducing", "read": "deduce"}]
