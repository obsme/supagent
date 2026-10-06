"""0.9.5: list_alerts also reads the alerts recorded in the data (an Alertmanager archive indexed with the logs):
"Which alerts are still firing?" was answered "none" from an empty ruler while the archive had four."""

from __future__ import annotations

import datetime as dt
from contextlib import contextmanager

import pytest
from test_groups import _Conn
from test_knowledge import world  # noqa: F401  (the fixture)


def test_the_alerts_still_firing_in_the_data(world, monkeypatch):  # noqa: F811
    duckdb = pytest.importorskip("duckdb")
    from superset.extensions import db, security_manager

    from supagent import settings
    from supagent import tools as T
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    con = duckdb.connect(":memory:")
    con.execute('CREATE TABLE "alerts" ("alertname" VARCHAR, "status" VARCHAR, "startsAt" TIMESTAMP, '
                '"endsAt" TIMESTAMP, "summary" VARCHAR, "_id" VARCHAR)')
    con.executemany('INSERT INTO "alerts" VALUES (?, ?, ?, ?, ?, ?)', [
        ("SwitchPortErrors", "firing", dt.datetime(2026, 9, 27, 6, 50), None, "input errors on xe-0/0/2", "a"),
        ("CheckoutErrorRateHigh", "resolved", dt.datetime(2026, 9, 27, 6, 49), dt.datetime(2026, 9, 27, 7, 38),
         "checkout error rate above 5 %", "b"),
        ("Future", "firing", dt.datetime(2026, 9, 28, 1, 0), None, "not yet", "c")])
    conn = _Conn(con, dt.datetime(2026, 9, 27, 11, 0))

    @contextmanager
    def fake(database, extract, max_rows=0):
        yield conn

    run, src = db.session.query(Run).first(), world["s_jobs"]
    upsert(run, src, "index", "", "alerts", {"stats": {"kind": {
        "kind": "alerts", "layout": "Alertmanager", "name": "alertname", "status": "status", "start": "startsAt",
        "end": "endsAt"}}})
    db.session.commit()
    monkeypatch.setattr(T, "_db_connection", fake)
    monkeypatch.setattr(T, "_table_database", lambda table, ref: world["jobs"])
    monkeypatch.setattr(security_manager, "raise_for_access", lambda **kw: None)
    monkeypatch.setattr(T, "_metrics_database", lambda ref: (_ for _ in ()).throw(T.ToolError("no metrics database")))
    settings.set_value("agent.now", "2026-09-27 11:00")
    try:
        from supagent.security import acting_as

        with acting_as("admin"):
            out = T.list_alerts()
    finally:
        settings.set_value("agent.now", None)
    rec = out["in_the_data"][0]
    assert rec["table"] == "alerts" and rec["firing"] == 1
    assert rec["alerts"][0]["alertname"] == "SwitchPortErrors" and "_id" not in rec["alerts"][0]
    assert "error" not in out                              # no metrics backend: the data's alerts still told
