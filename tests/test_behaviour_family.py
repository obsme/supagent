"""0.9.5: the usual day of each service from the span tables (behaviour), and a family of daily indices told as the
whole family (its documents and time range), not as its latest day."""

from __future__ import annotations

import datetime as dt

from test_knowledge import world  # noqa: F401  (the fixture)


def test_the_usual_day_of_each_service_is_the_median_of_the_days_before(monkeypatch):
    """Three days of server spans of two services, one of them a day of incident (errors, slowness): the usual is
    the median of each day (the incident does not make it), the busiest hours by their median, durations in ms by
    the table's unit; the line says it is a usual, of which days, server spans, traces kept, not a figure of a day."""
    from supagent.knowledge import behaviour

    d = lambda day, h=0: dt.datetime(2026, 9, day, h)  # noqa: E731
    daily = [(d(24), "checkout", 1000, 380_000, 590_000, 0), (d(25), "checkout", 980, 390_000, 600_000, 2),
             (d(26), "checkout", 900, 2_400_000, 30_000_000, 77),                   # the day of an incident
             (d(24), "inventory", 1000, 22_000, 42_000, 0), (d(25), "inventory", 1010, 23_000, 41_000, 0),
             (d(26), "inventory", 990, 24_000, 43_000, 0)]
    hourly = [(d(24, h), "checkout", n, 0, 0, 0) for h, n in ((9, 40), (13, 90), (14, 95), (19, 88), (3, 5))] + \
             [(d(25, h), "checkout", n, 0, 0, 0) for h, n in ((9, 42), (13, 92), (14, 97), (19, 85), (3, 4))]
    monkeypatch.setattr(behaviour, "_rows", lambda t, days: (daily, hourly, d(20), d(27), True))
    u = behaviour.learn({"table": "spans-*", "ms": 1e-3})
    co = u["services"]["checkout"]
    assert (co["spans_day"], co["avg_ms"], co["p95_ms"]) == (980.0, 390.0, 600.0)
    assert co["error_pct"] == 0.2 and co["busiest_hours"] == [13, 14, 19] and co["days"] == 3
    assert (u["from"], u["to"], u["days"]) == ("2026-09-24", "2026-09-26", 3)
    line = behaviour.line(u)
    assert line.startswith("usual (the median of the 3 days from 2026-09-24 to 2026-09-26; server spans, the traces kept, "
                           "not every request; not a figure of any day asked):")
    assert "checkout: 980 spans a day, avg 390 ms, p95 600 ms, errors 0.2 %, busiest hours 13h, 14h, 19h" in line
    monkeypatch.setattr(behaviour, "_rows", lambda t, days: ([], [], None, None, False))
    assert behaviour.learn({"table": "spans-*"}) is None


def test_a_family_of_daily_indices_is_told_as_the_whole_family(world):  # noqa: F811
    """fluentbit-*: its fields come from its latest index, but its documents and its time range are the pattern's
    own (the agent was told the latest day's 1,338 documents from 02:00, as if the logs began that morning)."""
    from superset.extensions import db

    from supagent.knowledge.describe import describe
    from supagent.knowledge.learn_indices import family_span
    from supagent.knowledge.store import upsert
    from supagent.models import Run, Source

    class Meta:
        fields = {"@timestamp": type("F", (), {"agg_field": "@timestamp"})()}

    seen = {}

    class Conn:
        tz = None

        class transport:  # noqa: N801
            @staticmethod
            def search(index, body):
                seen.update(index=index, body=body)
                return {"hits": {"total": {"value": 22493}},
                        "aggregations": {"lo": {"value": 1790287200000.0}, "hi": {"value": 1790585940000.0}}}

    span = family_span(Conn(), "logs-*", "@timestamp", Meta())
    assert seen["index"] == "logs-*" and seen["body"]["aggs"]["lo"] == {"min": {"field": "@timestamp"}}
    assert span == {"docs": 22493, "time_range": ["2026-09-24 22:00 UTC", "2026-09-28 08:59 UTC"]}
    run, src = db.session.query(Run).first(), db.session.query(Source).first()
    upsert(run, src, "index", "", "logs-*", {"stats": {"docs": 22493, "time_field": "@timestamp", "family": True,
                                                       "members": 5, "first": "logs-2026.09.23", "latest": "logs-2026.09.27",
                                                       "time_range": span["time_range"], "latest_docs": 1338}})
    upsert(run, src, "field", "logs-*", "@timestamp", {"data_type": "date", "stats": {}})
    db.session.commit()
    from supagent.security import acting_as

    with acting_as("admin"):
        text = describe(name="logs-*") or ""
    assert ("22,493 documents in 5 indices (logs-2026.09.23 .. logs-2026.09.27: query the pattern, not one of them; an "
            "index's day may be the UTC day)") in text
    assert "1,338" not in text
