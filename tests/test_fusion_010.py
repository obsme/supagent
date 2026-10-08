"""(0.10) The ways of the search fused by their scores (cc): each way's scores scaled to 0..1 (words: a share of the
best; meaning: from the closeness floor to the closest; near spellings as they are), weighted; a question written as a
sentence may weigh the meaning more than a list of keywords or a name."""

from __future__ import annotations


def test_each_way_scaled(ctx):
    from supagent.knowledge.pgstore import VECTOR_FLOOR, _scaled

    assert _scaled("words", [(1, 12.0), (2, 6.0), (3, 0.0)]) == {1: 1.0, 2: 0.5, 3: 0.0}
    got = _scaled("meaning", [(1, 0.85), (2, VECTOR_FLOOR), (3, 0.2)])
    assert got[1] == 1.0 and got[2] == 0.0 and got[3] == 0.0                  # under the floor: nothing
    assert _scaled("spelling", [(1, 0.7)]) == {1: 0.7} and _scaled("words", []) == {}


def test_a_sentence_is_not_a_list_of_keywords(ctx):
    from supagent.knowledge.pgstore import _sentence

    assert _sentence("how do I restore a snapshot?") and _sentence("what is the refresh interval")
    assert not _sentence("snapshot restore timeout")                        # keywords
    assert not _sentence("refresh_interval of the index")                   # a name typed: words first
    assert not _sentence("is it")                                           # too short


def test_mixed_fuses_a_sentence_by_ranks(ctx):
    from supagent.knowledge import pgstore

    assert pgstore.FUSION == "mixed"                                       # the default
    assert pgstore._sentence("how do I restore a snapshot?") and not pgstore._sentence("snapshot restore")
