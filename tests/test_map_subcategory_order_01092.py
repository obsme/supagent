"""(0.10.9.2) A subcategory's box takes a place among its column's values like a value does: the order a person gives
a column keeps "sub:<category>" entries next to the value ids (a new subcategory is no longer held at the bottom of
its column); anything else in the list is still dropped."""
from __future__ import annotations


def test_a_subcategory_box_keeps_its_place_in_its_columns_order(ctx):
    from supagent.knowledge import sysmap

    given = ["sub:db server", 3, "1", "sub:db server", " sub:web ", "sub:", "sub:" + "k" * 90, "x", {"sub": 1},
             "sub:a\nb", 2]
    out = sysmap.save_layout({"order": {"server": given, "in:12": [5, "sub:web"]}}, "admin")
    assert out["order"]["server"] == ["sub:db server", 3, 1, "sub:web", 2]   # once each, in the order given
    assert out["order"]["in:12"] == [5, "sub:web"]
    assert sysmap.layout()["order"] == out["order"]
    assert sysmap.save_layout({"order": {"server": ["sub:", "x"]}}, "admin")["order"] == {}
    sysmap.save_layout({}, "admin")
