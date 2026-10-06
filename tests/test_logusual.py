"""0.9.5: what each service's logs say every day (logusual), kept with the log table and told as usual; and a
family of daily indices (fluentbit-*) accepted as a table by the comparisons."""

from __future__ import annotations

import pytest

from test_knowledge import world  # noqa: F401  (the fixture)


def test_a_pattern_is_a_table_name_and_nothing_else_is():
    from supagent.knowledge import groups as G

    for ok in ("fluentbit-*", "logs-2026.09.*", "ss4o_logs-default-namespace", "jaeger-span-read", "ORDERS"):
        assert G.table(ok) == ok
    assert G.table('"fluentbit-*"') == "fluentbit-*"
    for bad in ('a"b', "a;b", "x' OR '1'='1", "", "logs-*)"):
        with pytest.raises(G.GroupsError):
            G.table(bad)
    with pytest.raises(G.GroupsError):
        G.name("fluentbit-*")                       # a field is still a field


def test_the_patterns_of_every_day_are_kept_with_the_table(world, monkeypatch):  # noqa: F811
    """A log table of a known kind: the services with the most lines are read (compare_logs, the last full day
    against the days before); only the patterns there on every earlier day are kept, with their usual (the median
    a day, not the count of the day read); the line says they are usual, not what a day asked said."""
    from superset.extensions import db

    from supagent import tools
    from supagent.knowledge import logusual
    from supagent.knowledge.store import upsert
    from supagent.models import KObject, Run, Source

    run, src = db.session.query(Run).first(), db.session.query(Source).first()
    kind = {"kind": "logs", "layout": "Logstash / Elastic Common Schema", "message": "message", "level": "log.level",
            "service": "service.name"}
    upsert(run, src, "index", "", "logstash-*", {"stats": {"docs": 9000, "time_field": "@timestamp", "kind": kind,
                                                          "time_range": ["2026-09-23 22:00", "2026-09-27 08:59"]}})
    upsert(run, src, "field", "logstash-*", "service.name", {"data_type": "keyword",
                                                             "stats": {"top": [["payment-gateway", 4000], ["shop-db", 900]]}})
    db.session.commit()
    monkeypatch.setattr("supagent.agent.now", lambda: __import__("datetime").datetime(2026, 9, 27, 11, 0))
    seen = []

    def compare_logs(table, start, end, where="", days=8, **_kw):
        seen.append((table, start, end, where))
        if "shop-db" in where:
            return {"patterns": [{"pattern": "checkpoint took # s", "level": "WARN", "verdict": "as usual", "now": 1,
                                  "usual": 1.0, "earlier_days_with_it": 1}]}           # there on one day of three
        return {"patterns": [
            {"pattern": "retry # of # to acquirer", "level": "WARN", "verdict": "as usual", "now": 410, "usual": 395.0,
             "earlier_days_with_it": 3, "from": "2026-09-26 00:01", "to": "2026-09-26 23:58"},
            {"pattern": "acquirer timeout after # ms", "level": "ERROR", "verdict": "new", "now": 77, "usual": 0.0,
             "earlier_days_with_it": 0}]}

    monkeypatch.setattr(tools, "compare_logs", compare_logs)
    out = logusual.run()
    assert out["tables"] == 1 and out["services"] == 1 and out["patterns"] == 1
    assert seen[0] == ("logstash-*", "2026-09-26 00:00", "2026-09-27 00:00", "\"service.name\" = 'payment-gateway'")
    ix = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == "logstash-*").one()
    kept = ix.stats["usual_logs"]
    assert kept["day"] == "2026-09-26" and list(kept["services"]) == ["payment-gateway"]
    assert kept["services"]["payment-gateway"][0]["lines"] == 395.0             # the usual, not the 410 of the day
    line = logusual.line(kept)
    assert line.startswith("what the logs say every day (patterns there on every day before 2026-09-26, lines a day: "
                           "their median; usual, not what a day asked said):")
    assert "payment-gateway: \"retry # of # to acquirer\" (WARN, about 395 lines a day, 00:01-23:58)" in line
    assert "timeout" not in line and "410" not in line
