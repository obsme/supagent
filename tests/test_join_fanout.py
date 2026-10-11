"""A SUM over a join that repeats rows (candidate C): orders JOIN returns sums an order once per return."""

from __future__ import annotations

import sqlite3

import pytest

FANOUT = ('SELECT SUM(o."AMOUNT_EUR") - SUM(r."REFUND_EUR") FROM "orders" o LEFT JOIN "returns" r '
          'ON o."ORDER_ID" = r."ORDER_ID" WHERE o."ORDER_TIME" >= \'2026-09-14\'')


def test_the_joins_whose_rows_repeat():
    from supagent.knowledge.sqllint import fanout_joins, fanout_refusal

    assert fanout_joins(FANOUT) == [("orders", "returns", "ORDER_ID", "SUM"), ("returns", "orders", "ORDER_ID", "SUM")]
    assert fanout_joins('SELECT COUNT(*) FROM "shipments" s JOIN "orders" o ON s."ORDER_ID" = o."ORDER_ID"') == \
        [("shipments", "orders", "ORDER_ID", "COUNT")]
    assert fanout_joins('SELECT COUNT(DISTINCT o."ORDER_ID") FROM "orders" o JOIN "returns" r '
                        'ON o."ORDER_ID" = r."ORDER_ID"') == []                       # distinct: no repeat
    assert fanout_joins('SELECT SUM("AMOUNT_EUR") FROM "orders" WHERE "ORDER_ID" IN (SELECT "ORDER_ID" FROM "returns")') == []
    said = fanout_refusal(FANOUT, lambda table, key: 2 if table == "returns" else 0)
    assert said.startswith("tool error (not run: the join repeats rows): returns has several rows for some ORDER_ID")
    assert fanout_refusal(FANOUT, lambda table, key: 0) is None                        # unique keys: as it is
    assert fanout_refusal(FANOUT, lambda table, key: None) is None                     # not known: as it is


@pytest.fixture()
def shop(app, tmp_path, monkeypatch):
    from superset.extensions import db, security_manager
    from superset.models.core import Database

    path = tmp_path / "shop.db"
    con = sqlite3.connect(path)
    con.execute('CREATE TABLE orders ("ORDER_ID" TEXT, "AMOUNT_EUR" REAL)')
    con.execute('CREATE TABLE returns ("ORDER_ID" TEXT, "REFUND_EUR" REAL)')
    con.executemany("INSERT INTO orders VALUES (?, ?)", [("A", 100.0), ("B", 50.0)])
    con.executemany("INSERT INTO returns VALUES (?, ?)", [("A", 10.0), ("A", 5.0)])      # A returned twice
    con.commit()
    con.close()
    monkeypatch.setattr(security_manager, "raise_for_access", lambda **kw: None)
    with app.app_context():
        d = Database(database_name="shop-fanout", sqlalchemy_uri=f"sqlite:///{path}")
        db.session.add(d)
        db.session.commit()
        yield d
        db.session.delete(d)
        db.session.commit()


def test_the_probe_reads_whether_a_key_repeats(shop, app):
    from supagent import tools as T

    T._REPEATS.clear()
    with app.app_context():
        assert T.repeated_keys(shop, "returns", "ORDER_ID") == 1      # A has two returns
        assert T.repeated_keys(shop, "orders", "ORDER_ID") == 0       # one row per order


def test_a_with_name_is_no_table():
    from supagent.knowledge.sqllint import fanout_joins

    sql = ('WITH official AS (SELECT "BOOK", SUM("PNL") AS p FROM "pnl" GROUP BY "BOOK"), restated AS (SELECT "BOOK", '
           'SUM("PNL") AS p FROM "pnl" GROUP BY "BOOK") SELECT SUM(o.p) FROM official o JOIN restated r ON o."BOOK" = '
           'r."BOOK"')
    assert fanout_joins(sql) == []


def test_a_left_join_condition_that_keeps_empty_rows_gets_the_inner_join_hint():
    """osagg refuses `OR r.STATUS IS NULL` on a LEFT JOIN's right index; the old hint (list the keys, then IN) led to
    a hand-made list of the first rows and a wrong total: the hint for that refusal says how to write the join."""
    from supagent.tools_superset import LEFT_WHERE, LEFT_WHERE_HINT, STEPS_HINT

    said = ("JoinRefused: This JOIN cannot run in OpenSearch: WHERE condition r.\"STATUS\" = 'REFUNDED' OR r.\"STATUS\" "
            "IS NULL on the right index of a LEFT JOIN. osagg joins indices on equal fields in aggregating queries")
    assert LEFT_WHERE.search(said) and "inner JOIN" in LEFT_WHERE_HINT and "IS NULL" in LEFT_WHERE_HINT
    assert "a list that misses keys gives a wrong total" in STEPS_HINT


def test_a_refused_join_of_a_raw_index_gets_the_join_that_runs():
    """(0.10.7, main suite M2-0107n) "the sales minus the refunds of those orders" written WITH a CTE joined to the
    returns was refused ("JOIN on an OpenSearch table is not supported"), and with the rules' "one index per query"
    the answer never tried the join that runs. That refusal now says the join that does run, and the rules too."""
    from supagent.tools_superset import JOIN_HINT, JOIN_REFUSED, SQL_RULES

    said = ("PushdownError: JOIN on an OpenSearch table is not supported: aggregate or filter each side in a subquery "
            "first, e.g. SELECT ... FROM (SELECT k, COUNT(*) c FROM idx GROUP BY k) a JOIN (...) b ON ...")
    assert JOIN_REFUSED.search(said) and JOIN_REFUSED.search("JOIN with a raw OpenSearch table is not supported")
    assert "JOIN \"idx_b\" b ON a.\"KEY\" = b.\"KEY\"" in JOIN_HINT and "not WITH" in JOIN_HINT
    assert "two joined on equal fields in an aggregating query" in SQL_RULES["osagg"]
