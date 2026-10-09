"""(0.10.4) A question names a part of the System map written with other separators or with a one-letter slip:
the system picture the agent gets starts from it all the same; an ordinary word is no part, a plural no slip."""
from __future__ import annotations


def _g(*names):
    from supagent.knowledge.brief import loose_index

    values = {i + 1: {"id": i + 1, "name": n, "about": "", "parents": []} for i, n in enumerate(names)}
    idx = {n.lower(): [i] for i, n in ((v["id"], v["name"]) for v in values.values())}
    loose, slips = loose_index(idx)
    return {"values": values, "names": idx, "children": {}, "out": {}, "in": {}, "rank": [], "long": {},
            "loose": loose, "slips": slips}


def test_other_separators_and_slips_name_the_part_in_a_question(ctx):
    from supagent.knowledge.brief import named

    g = _g("node-exporter", "payment_gateway", "prometheus", "catalogue", "gateway")
    assert named("is node exporter down?", g, loose=True) == [1]
    assert named("errors of the payment gateway", g, loose=True) == [2]
    assert named("why is Promethues slow", g, loose=True) == [3] and named("why is Promethues slow", g) == []
    assert named("the catalouge returns 502", g, loose=True) == [4]
    assert named("the gateways are fine", g, loose=True) == []          # a plural is no slip
    assert named("the catalxgue returns 502", g, loose=True) == []      # another letter: no
    assert named("how many orders were cancelled yesterday", g, loose=True) == []


def test_a_short_name_gets_no_slip(ctx):
    from supagent.knowledge.brief import named

    g = _g("cache", "backup", "tix-indexer")
    assert named("how much is cached", g, loose=True) == []            # 5 letters: "cached" is a word, no slip
    assert named("is the cache full", g, loose=True) == [1]
    assert named("did the backkup run", g, loose=True) == [2]          # 6 letters: a letter too many is a slip
    assert named("the tix-indexr is stuck", g, loose=True) == [3]
