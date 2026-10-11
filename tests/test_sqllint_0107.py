"""(0.10.7) "Over the whole of September, which books breached their VaR limit most often?" ran GROUP BY "BOOK" with
"BOOK" = 'ALL' kept from the question before (about desks): one row, 'ALL', answered as the one book that breached."""
from __future__ import annotations

from supagent.knowledge.sqllint import grouped_fixed, grouped_fixed_refusal

SQL = ('SELECT "BOOK", COUNT(*) AS n FROM "risk" WHERE "COB_DATE" >= \'2026-09-01\' AND "BOOK" = \'ALL\' AND '
       '"BREACH" = true GROUP BY "BOOK" ORDER BY n DESC')


def test_a_column_grouped_and_kept_at_one_value():
    assert grouped_fixed(SQL) == [("BOOK", "ALL")]
    assert grouped_fixed(SQL.replace('GROUP BY "BOOK"', "GROUP BY 1")) == [("BOOK", "ALL")]
    assert grouped_fixed('SELECT "BOOK", COUNT(*) FROM "risk" WHERE "BOOK" <> \'ALL\' GROUP BY "BOOK"') == []
    assert grouped_fixed('SELECT "DESK", COUNT(*) FROM "risk" WHERE "BOOK" = \'ALL\' GROUP BY "DESK"') == []


def test_sent_back_when_the_question_asks_about_that_column():
    args = {"request": {"database_id": 1, "sql": SQL}}
    q = "Over the whole of September, which books breached their VaR limit most often?"
    said = grouped_fixed_refusal(q, "execute_sql", args)
    assert said and "(not run: grouped and kept at one value)" in said and "\"BOOK\" = 'ALL'" in said
    assert grouped_fixed_refusal("How many breaches were there in September?", "execute_sql", args) is None
    assert grouped_fixed_refusal(q, "describe_data", args) is None
