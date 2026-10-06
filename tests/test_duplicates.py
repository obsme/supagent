"""0.9.5: the same events in two log tables (an application's lines shipped by the OpenTelemetry SDK and by Fluent Bit
from its stdout) are found in the data and said with both tables, so that they are never added."""

from __future__ import annotations

import datetime as dt

from test_knowledge import world  # noqa: F401  (the fixture)

OTEL = {"kind": "logs", "layout": "OpenTelemetry Collector", "message": "body", "level": "severity.text",
        "service": "resource.service.name", "pod": "resource.k8s.pod.name"}
FLUENT = {"kind": "logs", "layout": "Fluent Bit (Kubernetes filter)", "message": "log", "service": "kubernetes.labels.app",
          "pod": "kubernetes.pod_name"}


def test_the_same_events_are_found_and_said_with_both_tables(world, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import duplicates as D
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    run, src = db.session.query(Run).first(), world["s_jobs"]
    rng = ["2026-09-23 22:00", "2026-09-27 08:59"]
    a = upsert(run, src, "index", "", "otel-logs", {"stats": {"kind": OTEL, "time_field": "@timestamp", "time_range": rng}})
    b = upsert(run, src, "index", "", "fluentbit-*", {"stats": {"kind": FLUENT, "time_field": "@timestamp", "time_range": rng}})
    db.session.commit()
    monkeypatch.setattr("supagent.agent.now", lambda: dt.datetime(2026, 9, 27, 11, 0))
    monkeypatch.setattr(D, "_services", lambda ix, field: ["shop-checkout"] if ix.name == "otel-logs" else ["checkout"])
    t = dt.datetime(2026, 9, 26, 10, 0, 14)
    lines = [(t + dt.timedelta(minutes=7 * i), f"order {93180 + i} placed in {383 + i} ms", f"checkout-{i % 2}")
             for i in range(16)]
    shipped = {text for _t, text, _p in lines[:15]}          # one line of sixteen not shipped by Fluent Bit
    asked = []

    def run_sql(sql):
        asked.append(sql)
        if sql.startswith('SELECT "@timestamp", "body"'):
            assert "\"resource.service.name\" = 'shop-checkout'" in sql and "'2026-09-26 00:00:00'" in sql
            return lines
        if sql.startswith('SELECT "@timestamp", "log"'):
            return []                                        # Fluent Bit's own lines: not looked at here
        if sql.startswith("SELECT COUNT(*)"):
            assert '"kubernetes.pod_name" = ' in sql and '"log" LIKE' in sql
            return [(int(any(f"%{x}%" in sql for x in shipped)),)]
        if sql.startswith('SELECT "kubernetes.labels.app"'):
            return [("checkout",)]
        raise AssertionError(sql)

    found = D.compare(run_sql, a, b)
    assert found == [{"service": "shop-checkout", "found": 8, "lines": 8, "there": "checkout", "by": "the same pod, "}]
    assert D._piece("x%y") is None and D._piece("order 93180 placed in 383 ms") == "order 93180 placed in 383 ms"
    assert D._identity(OTEL, FLUENT) == ("resource.k8s.pod.name", "kubernetes.pod_name")
    assert D._identity(OTEL, {"host": "host.name"}) is None
    text = D.line(['its lines of "resource.service.name" = shop-checkout are also in "fluentbit-*"'])
    assert text.startswith("the same events shipped twice: its lines of") and "never add the two" in text


def test_the_search_text_of_a_table_says_what_it_is(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.index import _object_pieces
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    run, src = db.session.query(Run).first(), world["s_jobs"]
    o = upsert(run, src, "index", "", "otel-logs", {"stats": {"kind": OTEL, "time_field": "@timestamp", "data_stream": {
        "backing": 3}, "names": [{"name": "otel-logs-all", "kind": "alias"}], "same_events": [
        'its lines of "resource.service.name" = shop-checkout are also in "fluentbit-*" ("kubernetes.labels.app" = '
        'checkout there): 8 of 8 found there (the same pod, within 2 s, the same text)']}})
    db.session.commit()
    text = next(p for p in _object_pieces({o.id}))["text"]
    assert "kind: logs (OpenTelemetry Collector)" in text and "a data stream" in text
    assert "also reached as: otel-logs-all" in text and "the same events as: fluentbit-*" in text
    assert "8 of 8" not in text                                   # (no counts: the text changes with the meaning only)


def test_two_log_tables_whose_pods_never_meet_are_not_compared(world, monkeypatch):  # noqa: F811
    from contextlib import contextmanager

    from superset.extensions import db

    from supagent import tools
    from supagent.knowledge import duplicates as D
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    run, src = db.session.query(Run).first(), world["s_jobs"]
    rng = ["2026-09-23 22:00", "2026-09-27 08:59"]
    for name, pods in (("app-a-logs", ["a-1", "a-2"]), ("app-b-logs", ["b-1"]), ("app-a-stdout", ["a-2", "a-3"])):
        upsert(run, src, "index", "", name, {"stats": {"kind": FLUENT, "time_field": "@timestamp", "time_range": rng}})
        upsert(run, src, "field", name, "kubernetes.pod_name", {"data_type": "keyword", "stats": {"values": pods}})
    db.session.commit()

    class Conn:
        def cursor(self):
            return None

    @contextmanager
    def fake(database, extract, max_rows=0):
        yield Conn()

    asked = []
    monkeypatch.setattr(tools, "_db_connection", fake)
    monkeypatch.setattr(D, "compare", lambda run_sql, a, b: asked.append((a.name, b.name)) or [])
    D.run()
    assert sorted(asked) == [("app-a-logs", "app-a-stdout"), ("app-a-stdout", "app-a-logs")]   # b never compared
