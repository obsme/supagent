"""(0.10.12) Rows linked to a period's rows taken by their own date: "the net revenue of the week" (the week's sold
orders minus the refunds of those orders) answered with the refunds of the week by their return date. Fires only on
the queries that give the answer's figures: a query tried along the way and dropped is not the answer's reading."""
from __future__ import annotations

import json

from supagent.knowledge.owndate import date_conditions, join_keys, reading, ties


def step(sql: str, rows: list[dict]) -> dict:
    return {"tool": "execute_sql", "status": "done", "args": {"request": {"database_id": 1, "sql": sql}},
            "result": json.dumps({"success": True, "rows": rows, "row_count": len(rows)})}


SALES = step('SELECT SUM("AMOUNT") AS revenue FROM "sales" WHERE "SALE_TIME" >= \'2026-03-02 00:00\' '
             'AND "SALE_TIME" < \'2026-03-09 00:00\'', [{"revenue": 81250.4}])
REFUNDS_OWN_DATE = step('SELECT SUM(r."REFUND") AS refunds FROM "refunds" r JOIN "sales" s ON r."SALE_ID" = s."SALE_ID" '
                        'WHERE r."REFUND_DATE" >= \'2026-03-02 00:00\' AND r."REFUND_DATE" < \'2026-03-09 00:00\'',
                        [{"refunds": 4310.75}])
ONE_QUERY = step('SELECT SUM(s."AMOUNT") AS revenue, COALESCE(SUM(r."REFUND"), 0) AS refunds FROM "sales" s '
                 'LEFT JOIN "refunds" r ON s."SALE_ID" = r."SALE_ID" AND r."REFUND_DATE" >= \'2026-03-02\' '
                 'AND r."REFUND_DATE" < \'2026-03-09\' WHERE s."SALE_TIME" >= \'2026-03-02\' AND s."SALE_TIME" < '
                 '\'2026-03-09\'', [{"revenue": 81250.4, "refunds": 612.3}])
BY_KEY = step('SELECT SUM(s."AMOUNT") AS revenue, COALESCE(SUM(r."REFUND"), 0) AS refunds FROM "sales" s '
              'LEFT JOIN "refunds" r ON s."SALE_ID" = r."SALE_ID" WHERE s."SALE_TIME" >= \'2026-03-02\' '
              'AND s."SALE_TIME" < \'2026-03-09\'', [{"revenue": 81250.4, "refunds": 2875.1}])


def test_parsing():
    conds = date_conditions(ONE_QUERY["args"]["request"]["sql"])
    assert conds[("refunds", "REFUND_DATE")] == {"2026-03-02", "2026-03-09"}
    assert conds[("sales", "SALE_TIME")] == {"2026-03-02", "2026-03-09"}
    assert ("refunds", "sales", "SALE_ID") in join_keys(ONE_QUERY["args"]["request"]["sql"])


def test_two_queries_both_giving_the_figures():
    answer = "Net revenue: 81,250.40 - 4,310.75 = 76,939.65 EUR."
    assert reading([SALES, REFUNDS_OWN_DATE], answer, "What was the net revenue of that week?") == \
        ("refunds", "REFUND_DATE", "SALE_ID", "sales", "SALE_TIME")


def test_one_query_with_the_linked_date_in_the_join():
    answer = "Refunded share: 612.30 of 81,250.40, 0.75 %."
    assert reading([ONE_QUERY], answer, "What share of the revenue was refunded?") == \
        ("refunds", "REFUND_DATE", "SALE_ID", "sales", "SALE_TIME")


def test_a_query_tried_and_dropped_is_not_the_answer():
    answer = "Net revenue: 81,250.40 - 2,875.10 = 78,375.30 EUR."
    assert reading([REFUNDS_OWN_DATE, SALES, BY_KEY], answer, "What was the net revenue of that week?") is None


def test_only_combined_measures():
    assert reading([SALES, REFUNDS_OWN_DATE], "4,310.75 EUR", "How much was refunded that week?") is None


def test_ties():
    assert ties(["Net revenue is the value of the orders sold minus the refunds issued for those orders."])
    assert not ties(["Net revenue is the revenue minus the refunds."])


def test_the_answer_is_sent_back_once_with_the_tie(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    by_key = json.dumps({"success": True, "rows": [{"revenue": 81250.4, "refunds": 2875.1, "net": 78375.3}],
                         "row_count": 1})

    def results(name, args):
        sql = json.dumps(args)
        return REFUNDS_OWN_DATE["result"] if "REFUND_DATE" in sql else by_key if "LEFT JOIN" in sql else SALES["result"]

    a, _ran = agent_with(monkeypatch, [
        call("execute_sql", {"sql": SALES["args"]["request"]["sql"]}),
        call("execute_sql", {"sql": REFUNDS_OWN_DATE["args"]["request"]["sql"]}),
        say("Net revenue of that week: 81,250.40 - 4,310.75 = 76,939.65 EUR."),
        call("execute_sql", {"sql": BY_KEY["args"]["request"]["sql"].replace(
            'AS refunds FROM', 'AS refunds, SUM(s."AMOUNT") - COALESCE(SUM(r."REFUND"), 0) AS net FROM')}),
        say("Net revenue of that week: 81,250.40 - 2,875.10 = 78,375.30 EUR (the refunds of those sales)."),
    ], results=results)
    history = [{"role": "user", "content": "What does net revenue mean here?"},
               {"role": "assistant", "content": "The sales of a period minus the refunds issued for those sales."}]
    answer, _trace = a.ask("Then what was the net revenue of that week?", history)
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and "two different sets" in str(m["content"])]
    assert len(sent) == 1 and "by SALE_ID" in sent[0]
    assert "78,375.30" in answer
