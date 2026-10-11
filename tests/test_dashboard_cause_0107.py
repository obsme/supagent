"""(0.10.7, the obs runs) "Redis (dashboard)" blamed with the caches for their evictions, then sent back for its
records: a dashboard shows the parts it links to, it does not make them fail. A value of a category of displays
(dashboard, panel, chart), or named as one, is no part to blame."""
from __future__ import annotations


def test_a_dashboard_is_no_part_to_blame(ctx):
    from supagent.knowledge.leads import can_fail

    values = {1: {"name": "Zq caches (dashboard)", "cat": "component", "parents": []},
              2: {"name": "zq board", "cat": "dashboard", "parents": []},
              3: {"name": "zqdcache", "cat": "component", "parents": []},
              4: {"name": "zq dashboarding api", "cat": "application", "parents": []}}
    g = {"values": values, "out": {1: [("link", 3, None)], 2: [("link", 3, None), ("reads_from", 4, None)]},
         "in": {3: [("link", 1, None), ("link", 2, None)], 4: [("reads_from", 2, None)]}, "children": {}}
    assert not can_fail(1, g) and not can_fail(2, g)          # they show the cache
    assert can_fail(3, g) and can_fail(4, g)                  # the cache; an application with "dashboard" in its name
