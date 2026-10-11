"""(0.10.8, the main suite) "Which book lost the most money on 22 September, in official PnL?" was answered from the
single row with the lowest PnL (one trader's -130,365), where the book's rows summed give -248,707.32: a query of
single rows, for a question of which part has the most or the least, whose rows name one part several times, says so
with its result (nothing is refused: a table of one row per part is not concerned)."""
from __future__ import annotations

import json

ROWS = """SELECT "BOOK", "TRADER", "PNL_TOTAL" FROM "zq-pnl" WHERE "COB_DATE" = '2026-09-22' ORDER BY "PNL_TOTAL" ASC"""


def _q(sql):
    return {"request": {"database_id": 1, "sql": sql}}


def _res(rows):
    return json.dumps({"success": True, "columns": [{"name": k} for k in rows[0]], "rows": rows, "row_count": len(rows)})


def test_a_part_repeated_in_single_rows_is_said(app):
    from supagent.knowledge.sqllint import per_part_note

    repeated = _res([{"BOOK": "EQ", "TRADER": "T1", "PNL_TOTAL": -130}, {"BOOK": "FX", "TRADER": "T2", "PNL_TOTAL": -90},
                     {"BOOK": "EQ", "TRADER": "T3", "PNL_TOTAL": -80}])
    said = per_part_note("Which book lost the most money on 22 September?", _q(ROWS), repeated)
    assert said and "EQ 2 times" in said and 'GROUP BY "BOOK"' in said
    once = _res([{"BOOK": "EQ", "TRADER": "T1", "PNL_TOTAL": -130}, {"BOOK": "FX", "TRADER": "T2", "PNL_TOTAL": -90}])
    assert per_part_note("Which book lost the most money on 22 September?", _q(ROWS), once) is None   # one row each
    grouped = """SELECT "BOOK", SUM("PNL_TOTAL") AS pnl FROM "zq-pnl" GROUP BY "BOOK" ORDER BY pnl"""
    assert per_part_note("Which book lost the most money?", _q(grouped), repeated) is None           # aggregated
    assert per_part_note("How much did the EQ book lose?", _q(ROWS), repeated) is None               # no which-most


def test_the_note_goes_with_the_result_to_the_model(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    rows = _res([{"BOOK": "EQ", "PNL_TOTAL": -130}, {"BOOK": "EQ", "PNL_TOTAL": -80}, {"BOOK": "FX", "PNL_TOTAL": -90}])
    a, ran = agent_with(monkeypatch, [call("execute_sql", _q('SELECT "BOOK", "PNL_TOTAL" FROM "zq-pnl" ORDER BY '
                                                             '"PNL_TOTAL"')), say("EQ lost the most."),
                                      say("EQ lost the most."), say("EQ lost the most.")],
                        results=lambda n, args: rows)
    a.ask("Which book lost the most money?", [])
    sent = a.llm.seen[-1]
    assert any(m["role"] == "tool" and '"BOOK" repeats in these rows (EQ 2 times)' in m["content"] for m in sent)
