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
    assert read("paymentGatewy", WORDS)["changes"] == []                  # camelCase: one word, nothing one slip away
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


def near_look(words: dict[str, int], near: dict[str, list]):
    """The knowledge with its words as written too: the nearest ones to each word asked (as the store's trigram index
    gives them, nearest first)."""
    from supagent.knowledge.spelling import Lookup

    return Lookup(lambda stems: {s for s in stems if s in words},
                  lambda stems: {s: words[s] for s in stems if s in words},
                  lambda pairs: set(), lambda ws: {w: near[w] for w in ws if w in near})


def test_two_slips_read_as_the_nearest_written_word(ctx):
    """(0.10) A word no single slip reads: the word of the pieces as written near it (pg_trgm), two slips at most for a
    word of 7 letters or more, one for a shorter one (a key far away), the same first letter, held by a piece the user
    may see; the fewest slips first, then the one most pieces hold."""
    from supagent.knowledge.spelling import read as r, slips

    assert slips("aggrergatioon", "aggregation") == 2 and slips("ttansefrred", "transferred") == 2
    assert slips("aggrrergatioonn", "aggregation") is None and slips("form", "from") == 1
    words = {"aggreg": 30, "transferr": 4, "deploy": 20, "aggregate": 9, "tradeoff": 2}
    near = {"aggrergatioon": [("aggregate", "aggregate", 9, 0.41), ("aggregation", "aggreg", 30, 0.53)],
            "ttansefrred": [("tradeoffs", "tradeoff", 2, 0.21), ("transferred", "transferr", 4, 0.26)],
            "deplxy": [("deploy", "deploy", 20, 0.4)], "dwplxy": [("deploy", "deploy", 20, 0.2)],
            "aggrrergatioonn": [("aggregation", "aggreg", 30, 0.5)],
            "gransferred": [("transferred", "transferr", 4, 0.8)],
            "hiddenword": [("hiddenwork", "hiddenwork", 3, 0.7)]}
    look = near_look(words, near)
    got = r("aggrergatioon errors", look)
    assert got["query"] == "aggregation errors" and got["changes"] == [{"typed": "aggrergatioon", "read": "aggregation"}]
    assert r("files ttansefrred twice", look)["query"] == "files transferred twice"
    assert r("deplxy failed", look)["query"] == "deploy failed"              # one slip, a key far away: read
    assert r("dwplxy failed", look)["changes"] == []                         # two slips in 6 letters: as typed
    assert r("aggrrergatioonn", look)["changes"] == []                       # three slips: as typed
    assert r("gransferred", look)["changes"] == []                           # another first letter: never
    assert r("hiddenword", look)["changes"] == []                            # no piece the user may see holds it
    assert r("aggrergatioon", near_look(words, {}))["changes"] == []         # nothing near: as typed


def test_without_the_written_words_one_slip_only(ctx):
    from supagent.knowledge.spelling import read as r

    assert r("ttansefrred files", look({"transferr": 4}))["changes"] == []  # no store: the slips one away only


def test_maybe_misspelled_only_when_near_a_written_word(ctx):
    """(0.10) "unknown": a word no piece holds that is near a word of the pieces (two slips at most) but not read as
    it; a real word the pieces never use, near nothing, is nothing to correct."""
    from supagent.knowledge.spelling import read as r

    near = {"according": [], "dwplxy": [("deploy", "deploy", 20, 0.2)],
            "ttansefrred": [("transferred", "transferr", 4, 0.26)]}
    look = near_look({"deploy": 20, "transferr": 4}, near)
    got = r("According to dwplxy logs", look)
    assert got["changes"] == [] and got["unknown"] == ["dwplxy"]          # 6 letters, two slips: maybe misspelled
    assert r("ttansefrred files", look)["unknown"] == []                  # read: not unknown


def test_two_typing_slips_only(ctx, monkeypatch):
    """(0.10) NEAR_TYPING (on): a word read two slips away only through two typing slips (as edits1 reads one: a key next to
    the right one, a letter typed twice, one missing, two swapped), not any two changes: a real word the pieces never
    use (communist) is not read as a word of theirs (community)."""
    from supagent.knowledge import spelling
    from supagent.knowledge.spelling import read as r

    near = {"communist": [("community", "community", 40, 0.5)],
            "ttansefrred": [("transferred", "transferr", 4, 0.26)]}
    look = near_look({"community": 40, "transferr": 4}, near)
    monkeypatch.setattr(spelling, "NEAR_TYPING", False)
    assert r("communist party", look)["changes"][0]["read"] == "community"       # any two changes
    monkeypatch.setattr(spelling, "NEAR_TYPING", True)                          # (the default)
    got = r("communist party", look)
    assert got["changes"] == [] and got["unknown"] == ["communist"]
    assert r("ttansefrred files", look)["query"] == "transferred files"         # two typing slips: read


def test_the_words_inside_a_typed_name(ctx, monkeypatch):
    """(0.10) READ_NAMES (on): a word inside a name typed with a slip is read as the others (the name itself is still
    searched as typed by the near spelling of the names); off: names are left as typed."""
    from supagent.knowledge import spelling

    words = {"second": 30, "node": 40, "cpu": 50, "total": 60}
    got = read("node_cpu_secnds_total", words)
    assert got["query"] == "node_cpu_seconds_total" and got["changes"] == [{"typed": "secnds", "read": "seconds"}]
    monkeypatch.setattr(spelling, "READ_NAMES", False)
    assert read("node_cpu_secnds_total", words)["changes"] == []
