"""(0.10.7) "Which carrier had the most late ones?" after "How many parcels of the orders placed from 14 to 20
September were delivered late?" (293): the follow-up's query also kept the orders of one channel out, a team rule the
first count had not applied, and answered 270 of 290 without a word on it."""
from __future__ import annotations

from supagent.knowledge.conditions import rows_changed

SHIP = '"shop-shipments"'
BEFORE = [f'SELECT COUNT(*) FROM {SHIP} WHERE "ORDER_DATE" >= \'2026-09-14\' AND "ORDER_DATE" <= \'2026-09-20\' '
          'AND "LATE" = true']
CHAT = ("How many parcels of the orders placed from 14 to 20 September were delivered late?\n"
        "There were **293** parcels from orders placed between September 14 and 20 that were delivered late.")


def _call(sql: str) -> dict:
    return {"request": {"database_id": 1, "sql": sql}}


def test_a_follow_up_on_other_rows_is_sent_back(ctx):
    sql = (f'SELECT "CARRIER", COUNT(*) AS n FROM {SHIP} WHERE "LATE" = true AND "ORDER_ID" IN (SELECT "ORDER_ID" '
           'FROM "shop-orders" WHERE "ORDER_DATE" >= \'2026-09-14\' AND "ORDER_DATE" <= \'2026-09-20\' AND '
           '"CHANNEL" <> \'TEST\') GROUP BY "CARRIER" ORDER BY n DESC')
    why = rows_changed("Which carrier had the most late ones?", CHAT, BEFORE, "execute_sql", _call(sql))
    assert why and "CHANNEL <> 'TEST'" in why and "send this same call again" in why


def test_what_the_follow_up_or_the_chat_says_is_kept(ctx):
    same = (f'SELECT "CARRIER", COUNT(*) AS n FROM {SHIP} WHERE "ORDER_DATE" >= \'2026-09-14\' AND "ORDER_DATE" <= '
            '\'2026-09-20\' AND "LATE" = true GROUP BY "CARRIER"')
    assert rows_changed("Which carrier had the most late ones?", CHAT, BEFORE, "execute_sql", _call(same)) is None
    chat = CHAT + "\nWhich carrier had the most late ones?\n**QUICKSHIP** had the most late parcels (272)."
    one = (f'SELECT AVG("DELIVERY_DAYS") FROM {SHIP} WHERE "ORDER_DATE" >= \'2026-09-14\' AND "ORDER_DATE" <= '
           '\'2026-09-20\' AND "LATE" = true AND "CARRIER" = \'QUICKSHIP\'')
    assert rows_changed("What was that carrier's average delivery time, in days?", chat, BEFORE, "execute_sql",
                        _call(one)) is None                       # the carrier the answer before named
    express = (f'SELECT COUNT(*) FROM {SHIP} WHERE "ORDER_DATE" >= \'2026-09-14\' AND "ORDER_DATE" <= \'2026-09-20\' '
               'AND "LATE" = true AND "EXPRESS" = true')
    assert rows_changed("And the express ones only?", CHAT, BEFORE, "execute_sql", _call(express)) is None
    week = f'SELECT COUNT(*) FROM {SHIP} WHERE "ORDER_DATE" >= \'2026-09-07\' AND "ORDER_DATE" <= \'2026-09-13\' AND "LATE" = true'
    assert rows_changed("And the week before?", CHAT, BEFORE, "execute_sql", _call(week)) is None
    other = 'SELECT COUNT(*) FROM "shop-orders" WHERE "CHANNEL" <> \'TEST\''
    assert rows_changed("How many orders were there?", CHAT, BEFORE, "execute_sql", _call(other)) is None
    assert rows_changed("Which carrier?", CHAT, [], "execute_sql", _call(same)) is None


def test_a_share_counts_every_row(ctx):
    """"What was its failure rate?": the failures counted in a FILTER over every row are no other rows."""
    before = ['SELECT COUNT(*) FROM "jobs" WHERE "APPLICATION" = \'BILLING\'']
    rate = ('SELECT 100.0 * COUNT(*) FILTER (WHERE "STATUS" IN (\'ERROR\', \'TIMEOUT\')) / COUNT(*) FROM "jobs" '
            'WHERE "APPLICATION" = \'BILLING\'')
    assert rows_changed("What was its failure rate?", "How many BILLING jobs ran?\n120 jobs.", before, "execute_sql",
                        _call(rate)) is None
    only = 'SELECT COUNT(*) FROM "jobs" WHERE "APPLICATION" = \'BILLING\' AND "ENV" = \'PROD\''
    assert rows_changed("And how long did they take?", "How many BILLING jobs ran?\n120 jobs.", before,
                        "execute_sql", _call(only))
