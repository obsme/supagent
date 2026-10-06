"""0.9.6: what some rows have in common that the other rows of the window do not (the failing calls, the slow
requests), field by field, then below them: the nodes their pods run on, the inventory's rack and switch port."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

import pytest
from test_groups import _Conn
from test_knowledge import world  # noqa: F401  (the fixture)


def test_the_values_far_more_frequent_among_the_rows_of_interest(world, monkeypatch):  # noqa: F811
    duckdb = pytest.importorskip("duckdb")
    from superset.extensions import db, security_manager

    from supagent import tools as T
    from supagent.agent import intents
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    con = duckdb.connect(":memory:")
    con.execute('CREATE TABLE "spans" ("ts" TIMESTAMP, "svc" VARCHAR, "pod" VARCHAR, "err" VARCHAR)')
    t = dt.datetime(2026, 9, 27, 6, 0)
    rows = []
    for i in range(300):
        pod = ("a-1", "b-1", "b-2")[i % 3]
        err = "true" if pod.startswith("b") and i % 2 == 0 else "false"          # the failing ones: on b-* only
        rows.append((t + dt.timedelta(seconds=i), ("inventory", "frontend")[i % 2], pod, err))
    con.executemany('INSERT INTO "spans" VALUES (?, ?, ?, ?)', rows)
    con.execute('CREATE TABLE "podlogs" ("pod" VARCHAR, "node" VARCHAR)')
    con.executemany('INSERT INTO "podlogs" VALUES (?, ?)', [("a-1", "node-1"), ("b-1", "node-2"), ("b-2", "node-3")])
    conn = _Conn(con, dt.datetime(2026, 9, 27, 11, 0))

    @contextmanager
    def fake(database, extract, max_rows=0):
        yield conn

    run, src = db.session.query(Run).first(), world["s_jobs"]
    upsert(run, src, "index", "", "spans", {"stats": {"time_field": "ts", "kind": {"kind": "spans", "host": "pod"}}})
    for f, vals in (("svc", ["frontend", "inventory"]), ("pod", ["a-1", "b-1", "b-2"]), ("err", ["false", "true"])):
        upsert(run, src, "field", "spans", f, {"data_type": "keyword", "stats": {"cardinality": len(vals), "values": vals}})
    upsert(run, src, "index", "", "podlogs", {"stats": {"time_field": "ts", "kind": {"kind": "logs", "pod": "pod",
                                                                                  "node": "node"}}})
    db.session.commit()
    monkeypatch.setattr(T, "_db_connection", fake)
    monkeypatch.setattr(T, "_table_database", lambda table, ref: world["jobs"])
    monkeypatch.setattr(T, "_row_time_field", lambda table, tf: ("ts", False))
    monkeypatch.setattr(security_manager, "raise_for_access", lambda **kw: None)
    from supagent.knowledge import inventory

    monkeypatch.setattr(inventory, "load", lambda: inventory.build([
        {"name": "node-1", "table": "cmdb", "aliases": [], "raw": {"rack": "A"}},
        {"name": "node-2", "table": "cmdb", "aliases": [], "raw": {"rack": "B"}},
        {"name": "node-3", "table": "cmdb", "aliases": [], "raw": {"rack": "B"}}]))
    monkeypatch.setattr(inventory, "walk", lambda names, depth=2: None)
    from supagent.security import acting_as

    with acting_as("admin"):
        r = T.what_they_share("spans", "2026-09-27 06:00", "2026-09-27 07:00", "\"err\" = 'true'", fields=["svc", "pod"])
    assert r["rows"] == 300 and r["of_interest"] == 100
    by = {x["field"]: x for x in r["what_they_share"]}
    pods = [v["value"] for v in by["pod"]["values"]]
    assert set(pods) == {"b-1", "b-2"} and "a-1" not in pods
    assert by["rack (inventory)"]["all_of_them"] == "B"                         # every failing call: rack B
    assert {v["value"] for v in by["node (where their pods run)"]["values"]} == {"node-2", "node-3"}
    assert by["svc"]["all_of_them"] == "inventory"                              # (every failing call is inventory's)
    assert "common" in intents("What do the failing calls have in common?")
