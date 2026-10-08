"""A term the team defined, computed another way (0.9.2, agent.definition_check, a test: off)."""

from __future__ import annotations

import json


def test_a_defined_term_computed_another_way_is_sent_back_once(ctx, monkeypatch):
    from supagent import settings
    from supagent.agent import DEFINITION_NUDGE
    from supagent.knowledge import definitions, glossary
    from test_agent_loop import agent_with, call, say

    term = {"term": "net revenue", "definition": "The AMOUNT_EUR of the orders sold (STATUS PAID or DELIVERED), minus "
            "the REFUND_EUR of the returns with STATUS REFUNDED of those orders."}
    monkeypatch.setattr(glossary, "found", lambda q: [term] if "net revenue" in q.lower() else [])
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: True if key == "agent.definition_check" else real(key))
    week = {"request": {"database_id": 1, "sql": "SELECT SUM(\"REFUND_EUR\") FROM \"returns\" WHERE \"RETURN_DATE\" >= "
                                                 "'2026-09-14' AND \"RETURN_DATE\" < '2026-09-21'"}}
    rows = json.dumps({"success": True, "rows": [{"n": 1}], "row_count": 1})
    judged = {"role": "assistant", "content": "DIFFERS: the refunds of those orders, not the refunds dated in the week."}
    replies = [call("execute_sql", week), say("The net revenue of the week was 1 EUR."), judged,
               call("execute_sql", week), say("The net revenue of the week was 1 EUR, the refunds of its orders deducted.")]
    a, _ran = agent_with(monkeypatch, replies, results=lambda n, args: rows)
    answer, _trace = a.ask("What was the net revenue of the week of 14 to 20 September?")
    nudge = DEFINITION_NUDGE.format(term="net revenue", definition=term["definition"][:700],
                                    why="the refunds of those orders, not the refunds dated in the week.")
    assert any(m["content"] == nudge for m in a.llm.seen[-1] if m["role"] == "user")
    assert answer.startswith("The net revenue of the week was 1 EUR, the refunds of its orders deducted.")
    # the judge says OK: nothing more; a question with no defined term: no call
    ok = {"role": "assistant", "content": "OK"}
    b, _ran = agent_with(monkeypatch, [call("execute_sql", week), say("It was 1 EUR."), ok], results=lambda n, args: rows)
    b.ask("What was the net revenue of the week?")
    assert not b.usage.get("nudges") and len(b.llm.seen) == 3
    c, _ran = agent_with(monkeypatch, [call("execute_sql", week), say("1 order.")], results=lambda n, args: rows)
    c.ask("How many orders were placed that week?")
    assert len(c.llm.seen) == 2
    assert definitions.COMPUTABLE.search(term["definition"]) and not definitions.COMPUTABLE.search("a portfolio of trades")


def test_the_check_is_off_by_default(ctx, monkeypatch):
    from supagent.knowledge import glossary
    from test_agent_loop import agent_with, call, say

    monkeypatch.setattr(glossary, "found", lambda q: [{"term": "net revenue", "definition": "AMOUNT_EUR minus REFUND_EUR"}])
    a, _ran = agent_with(monkeypatch, [call("execute_sql", {"request": {"database_id": 1, "sql": "SELECT 1"}}),
                                       say("It was 1 EUR.")])
    a.ask("What was the net revenue of the week?")
    assert len(a.llm.seen) == 2


def test_a_relation_between_rows_computed_apart_is_sent_back_once(ctx, monkeypatch):
    """"The refunds of those orders": the refunds were read with their own dates, apart from the week's orders (0.9.1
    and 0.9.2 candidate A, every run). By code: the definition relates rows, the queries never read the two tables
    together (JOIN, key IN (SELECT ...)): sent back once to link them on their key."""
    from supagent.agent import DEFINITION_NUDGE
    from supagent.knowledge import definitions, glossary
    from test_agent_loop import agent_with, call, say

    term = {"term": "net revenue", "definition": "The AMOUNT_EUR of the orders sold (STATUS PAID or DELIVERED), minus "
            "the REFUND_EUR of the returns with STATUS REFUNDED of those orders."}
    monkeypatch.setattr(glossary, "found", lambda q: [term] if "net revenue" in q.lower() else [])
    orders = ("SELECT SUM(\"AMOUNT_EUR\") FROM \"orders\" WHERE \"ORDER_TIME\" >= '2026-09-14' AND \"ORDER_TIME\" < "
              "'2026-09-21'")
    refunds = ("SELECT SUM(\"REFUND_EUR\") FROM \"returns\" WHERE \"RETURN_DATE\" >= '2026-09-14' AND \"RETURN_DATE\" < "
               "'2026-09-21'")
    linked = ("SELECT SUM(r.\"REFUND_EUR\") FROM \"returns\" r JOIN \"orders\" o ON r.\"ORDER_ID\" = o.\"ORDER_ID\" WHERE "
              "o.\"ORDER_TIME\" >= '2026-09-14' AND o.\"ORDER_TIME\" < '2026-09-21'")
    keyed = ("SELECT SUM(\"REFUND_EUR\") FROM \"returns\" WHERE \"ORDER_ID\" IN (SELECT \"ORDER_ID\" FROM \"orders\" "
             "WHERE \"ORDER_TIME\" >= '2026-09-14' AND \"ORDER_TIME\" < '2026-09-21')")
    q = "What was the net revenue of the week of 14 to 20 September?"
    found = definitions.unlinked(q, [orders, refunds])
    assert found and found[0] is term and '"of those orders"' in found[1]
    assert definitions.unlinked(q, [orders, refunds, linked]) is None                  # linked in one query
    assert definitions.unlinked(q, [orders, keyed]) is None
    assert definitions.unlinked(q, [orders]) is None                                   # one table
    assert definitions.unlinked("How many orders were sold that week?", [orders, refunds]) is None   # no such term
    monkeypatch.setattr(glossary, "found", lambda q: [term])                           # found by a shared word only
    assert definitions.unlinked("And the gross revenue?", [orders, refunds]) is None   # not the term itself
    monkeypatch.setattr(glossary, "found", lambda q: [term] if "net revenue" in q.lower() else [])
    aligned = {"term": "return rate", "definition": "The returns of a period divided by the orders delivered in it, "
               "for the same product category."}
    monkeypatch.setattr(glossary, "found", lambda q: [aligned])
    assert definitions.unlinked("What was the return rate of the week?", [orders, refunds]) is None  # no row relation
    monkeypatch.setattr(glossary, "found", lambda q: [term] if "net revenue" in q.lower() else [])
    rows = json.dumps({"success": True, "rows": [{"n": 1}], "row_count": 1})
    sql = lambda s: {"request": {"database_id": 1, "sql": s}}  # noqa: E731
    replies = [call("execute_sql", sql(orders)), call("execute_sql", sql(refunds)), say("The net revenue was 2 EUR."),
               call("execute_sql", sql(linked)), say("The net revenue was 3 EUR, the refunds of its orders deducted.")]
    a, _ran = agent_with(monkeypatch, replies, results=lambda n, args: rows)
    answer, _trace = a.ask(q)
    assert answer.startswith("The net revenue was 3 EUR") and a.usage.get("nudges") == 1
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith("(Check")]
    assert sent and sent[0].startswith(DEFINITION_NUDGE.split("{term}")[0]) and "of those orders" in sent[0]


def test_a_share_of_rows_that_something_happened_to_is_counted_within_them():
    """"Back to that week's sales: what share of the revenue was refunded?": the refunds dated in the week over the
    week's sales (every run). A share of rows that something happened to is counted within those rows; "what share
    of all the orders is that?" compares two counts and is left alone."""
    from supagent.knowledge.definitions import unlinked_share

    orders = ("SELECT SUM(\"AMOUNT_EUR\") FROM \"orders\" WHERE \"ORDER_TIME\" >= '2026-09-14' AND \"ORDER_TIME\" < "
              "'2026-09-21'")
    refunds = ("SELECT SUM(\"REFUND_EUR\") FROM \"returns\" WHERE \"RETURN_DATE\" >= '2026-09-14' AND \"RETURN_DATE\" < "
               "'2026-09-21'")
    keyed = ("SELECT SUM(\"REFUND_EUR\") FROM \"returns\" WHERE \"ORDER_ID\" IN (SELECT \"ORDER_ID\" FROM \"orders\" "
             "WHERE \"ORDER_TIME\" >= '2026-09-14' AND \"ORDER_TIME\" < '2026-09-21')")
    q = "Back to that week's sales: what share of the revenue was refunded?"
    assert unlinked_share(q, [orders, refunds]) and "within the same rows" in unlinked_share(q, [orders, refunds])
    assert unlinked_share(q, [orders, keyed]) is None                                  # counted within them
    assert unlinked_share(q, [orders]) is None
    assert unlinked_share("What share of all the orders of that day is that?", [orders, refunds]) is None
    assert unlinked_share("Quelle part du chiffre d'affaires a été remboursée ?", [orders, refunds])


def test_a_share_over_an_inner_join_keeps_only_the_rows_with_a_part():
    """(0.9.7) The part and the whole joined, but by an INNER join: the whole is then only the rows that have a
    part (the cancellations over the subscriptions that were cancelled: 100 %). Sent back once; a LEFT join from
    the whole, an unqualified column, or a question that is not a share: nothing said."""
    from supagent.knowledge.definitions import restricted_whole, unlinked_share

    q = "What share of last month's subscriptions were cancelled?"
    inner = ('SELECT ROUND(100.0 * SUM(c."FEE") / SUM(s."PRICE"), 2) AS pct FROM "cancellations" c JOIN '
             '"subscriptions" s ON c."SUB_ID" = s."SUB_ID" WHERE s."START" >= \'2030-01-01\'')
    left = ('SELECT 100.0 * SUM(CASE WHEN c."SUB_ID" IS NOT NULL THEN c."FEE" ELSE 0 END) / SUM(s."PRICE") FROM '
            '"subscriptions" s LEFT JOIN "cancellations" c ON c."SUB_ID" = s."SUB_ID"')
    loose = 'SELECT SUM("FEE") / SUM("PRICE") FROM "cancellations" JOIN "subscriptions" USING ("SUB_ID")'
    assert restricted_whole(inner) == ("subscriptions", "cancellations")
    said = unlinked_share(q, [inner])
    assert said and "only the subscriptions rows that have a cancellations row" in said and "LEFT JOIN" in said
    assert restricted_whole(left) is None and unlinked_share(q, [left]) is None
    assert restricted_whole(loose) is None                              # which table each sum reads: not known
    assert unlinked_share("How many subscriptions started last month?", [inner]) is None
    both = 'SELECT SUM(o."QTY" * o."PRICE") / SUM(o."QTY") FROM "lines" o JOIN "items" i ON o."ITEM" = i."ITEM"'
    assert restricted_whole(both) is None                               # one table on both sides: no part/whole


def test_the_share_join_check_has_its_setting(app, monkeypatch):
    from supagent import settings
    from supagent.knowledge.definitions import unlinked_share

    inner = ('SELECT ROUND(100.0 * SUM(c."FEE") / SUM(s."PRICE"), 2) AS pct FROM "cancellations" c JOIN '
             '"subscriptions" s ON c."SUB_ID" = s."SUB_ID"')
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: False if k == "agent.share_join_check" else real(k))
    with app.app_context():
        assert unlinked_share("What share of last month's subscriptions were cancelled?", [inner]) is None
