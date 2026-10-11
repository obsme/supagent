"""(0.10.7) "(day 1) OR (day 2) AND <filters>": every alternative in parentheses, the filters of all of them joined
with AND after the last one. AND binds first, so the first day went unfiltered; refused once, the same call sent
again ran, and the answer took that total over the right one. Its meaning is plain: refused every time, with the
WHERE to write."""

from __future__ import annotations

import json

Q = ("SELECT SUM(\"AMT\") FROM \"sales\" WHERE (\"T_AT\" >= '2031-03-03 00:00' AND \"T_AT\" < '2031-03-04 00:00') OR "
     "(\"T_AT\" >= '2031-02-24 00:00' AND \"T_AT\" < '2031-02-25 00:00') AND \"STATE\" IN ('OK', 'DONE') AND "
     "\"KIND\" <> 'TEST'")


def test_the_where_meant_is_written():
    from supagent.knowledge.sqllint import grouped_alternatives, or_and_refusal

    meant = grouped_alternatives(Q)
    assert meant.startswith("((\"T_AT\" >= '2031-03-03 00:00'") and meant.endswith("AND \"KIND\" <> 'TEST'")
    assert grouped_alternatives("SELECT 1 FROM s WHERE \"KIND\" <> 'TEST' AND (t = 1) OR (t = 2)") == \
        "\"KIND\" <> 'TEST' AND ((t = 1) OR (t = 2))"
    assert grouped_alternatives("SELECT 1 FROM s WHERE a = 1 OR b = 2 AND c = 3") is None      # not this shape
    assert grouped_alternatives("SELECT 1 FROM s WHERE ((t = 1) OR (t = 2)) AND c = 3") is None
    assert grouped_alternatives("SELECT 1 FROM s WHERE (t = 1) OR (t = 2)") is None
    said = or_and_refusal("execute_sql", {"request": {"database_id": 1, "sql": Q}})
    assert "(not run: AND before OR, the alternatives in parentheses)" in said and meant in said
    assert "send this same call again unchanged" not in said
    plain = or_and_refusal("execute_sql", {"request": {"sql": "SELECT 1 FROM s WHERE a = 1 OR b = 2 AND c = 3"}})
    assert "send this same call again unchanged" in plain                    # the other shapes: as before


def test_sent_again_unchanged_it_is_still_refused(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    sql = {"request": {"database_id": 1, "sql": Q}}
    rows = json.dumps({"success": True, "rows": [{"amt": 10}], "row_count": 1})
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), call("execute_sql", sql), say("No figure.")],
                        results=lambda n, args: rows)
    a.ask("How do the sales of 3 March compare with the Monday before?")
    assert ran == []                                                           # never run as written
