"""0.9.5: the kind of each index from its fields alone (logs and their shipper, spans and their units, events, alerts,
an inventory), shown with the index; a table of data gets nothing."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)

JAEGER = {"traceID", "spanID", "parentSpanID", "operationName", "startTime", "startTimeMillis", "duration", "flags",
          "process.serviceName", "process.tag.hostname"}
FLUENT = {"@timestamp", "log", "stream", "time", "kubernetes.pod_name", "kubernetes.namespace_name", "kubernetes.host",
          "kubernetes.container_name", "kubernetes.labels.app", "kubernetes.labels.pod-template-hash"}
OTEL_LOGS = {"@timestamp", "body", "severity.text", "severity.number", "traceId", "spanId", "resource.service.name",
             "resource.k8s.pod.name", "resource.k8s.node.name", "attributes.http.route"}
ECS = {"@timestamp", "@version", "message", "log.level", "host.name", "service.name", "event.dataset", "agent.type"}


def test_each_layout_is_told_from_its_whole_signature():
    from supagent.knowledge.indexkinds import detect

    j = detect(JAEGER | {"tag.peer@service", "tag.error", "tag.http@status_code"})
    assert (j["kind"], j["layout"], j["duration_unit"], j["service"], j["peer"], j["error"]) == \
        ("spans", "Jaeger", "microseconds", "process.serviceName", "tag.peer@service", "tag.error")
    assert detect(JAEGER)["tags_as_fields"] is False                     # Jaeger's default: nested tags
    o = detect({"traceId", "spanId", "parentSpanId", "name", "serviceName", "durationInNanos", "startTime", "endTime"})
    assert (o["kind"], o["layout"], o["duration_unit"], o["service"]) == ("spans", "OpenTelemetry", "nanoseconds", "serviceName")
    f = detect(FLUENT)
    assert (f["kind"], f["layout"], f["message"], f["level"], f["stream"], f["service"], f["pod"], f["node"]) == \
        ("logs", "Fluent Bit (Kubernetes filter)", "log", None, "stream", "kubernetes.labels.app", "kubernetes.pod_name",
         "kubernetes.host")
    assert detect(FLUENT | {"kubernetes.labels.app_kubernetes_io/name"})["service"] == "kubernetes.labels.app_kubernetes_io/name"
    t = detect(OTEL_LOGS)
    assert (t["kind"], t["layout"], t["message"], t["level"], t["service"], t["trace"]) == \
        ("logs", "OpenTelemetry Collector", "body", "severity.text", "resource.service.name", "traceId")
    e = detect(ECS)
    assert (e["kind"], e["layout"], e["level"], e["service"], e["host"]) == \
        ("logs", "Logstash / Elastic Common Schema", "log.level", "service.name", "host.name")
    assert detect({"firstTimestamp", "type", "reason", "message", "involvedObject.kind", "involvedObject.name"})["kind"] == "events"
    assert detect({"alertname", "severity", "status", "startsAt", "endsAt", "labels.instance"})["kind"] == "alerts"
    assert detect({"name", "aliases", "owner", "team"})["kind"] == "inventory"
    g = detect({"@timestamp", "MESSAGE", "LEVEL", "APPLICATION", "HOST"})
    assert (g["kind"], g["layout"], g["message"], g["level"], g["service"]) == ("logs", "", "MESSAGE", "LEVEL", "APPLICATION")
    # tables of data: nothing (business tables with a duration, a message field alone, a trace id alone)
    for fields in ({"ORDER_ID", "ORDER_DATE", "STATUS", "AMOUNT_EUR", "COUNTRY"},
                   {"JOB_NAME", "STATUS", "duration", "START_TIME", "END_TIME", "NODE"},
                   {"TICKET_ID", "message", "PRIORITY", "OPENED_TIME"}, {"traceId", "ORDER_ID", "AMOUNT"},
                   {"name", "owner", "team"}):
        assert detect(fields) is None, fields


def test_the_line_the_agent_is_told():
    from supagent.knowledge.indexkinds import detect, line

    j = line(detect(JAEGER | {"tag.peer@service", "tag.error"}))
    assert j.startswith("kind: spans of traces (Jaeger): \"duration\" in microseconds (/1000 for ms); \"startTime\" in "
                        "microseconds since the epoch (bound the time on \"startTimeMillis\", a date)")
    assert "the service a client span calls \"tag.peer@service\"" in j and "errors \"tag.error\" = 'true'" in j
    assert "nested" not in j
    assert "its tags are nested: SQL cannot filter on them" in line(detect(JAEGER))
    f = line(detect(FLUENT))
    assert "\"stream\" is stdout or stderr" in f and "error" not in f.lower()         # stderr is not said to be errors
    assert "no level field: a level, when the application writes one, is in the line's text" in f
    t = line(detect(OTEL_LOGS))
    assert "\"severity.number\" 17-20 is ERROR, 13-16 WARN, 9-12 INFO" in t and "service \"resource.service.name\"" in t


def test_the_kinds_are_kept_with_the_indices_and_the_units_written_where_none_is(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import indexkinds
    from supagent.knowledge.store import upsert
    from supagent.models import KObject, Run, Source

    run, src = db.session.query(Run).first(), db.session.query(Source).first()
    upsert(run, src, "index", "", "spans-*", {"stats": {"docs": 10, "time_field": "startTimeMillis"}})
    for n in JAEGER:
        upsert(run, src, "field", "spans-*", n, {"data_type": "long" if n in ("duration", "startTime") else "keyword",
                                                 "unit": "us" if n == "startTime" else None})
    db.session.commit()
    out = indexkinds.run()
    assert out["kinds"]["spans-*"] == "spans (Jaeger)" and "jobs" not in out["kinds"]
    ix = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == "spans-*").one()
    assert ix.stats["kind"]["layout"] == "Jaeger" and ix.stats["docs"] == 10
    units = {f.name: f.unit for f in db.session.query(KObject).filter(KObject.parent == "spans-*", KObject.kind == "field")}
    assert units["duration"] == "microseconds" and units["startTime"] == "us"           # a unit already there is kept
    jobs = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == "jobs").one()
    assert "kind" not in (jobs.stats or {})
    db.session.query(KObject).filter(KObject.parent == "spans-*", KObject.name == "spanID").delete()
    db.session.commit()
    indexkinds.run()                                                                     # no longer spans: said no more
    assert "kind" not in db.session.get(KObject, ix.id).stats


def test_metrics_stored_as_documents_are_told_apart():
    from supagent.knowledge.indexkinds import detect, line

    otel = {"name", "kind", "value", "unit", "time", "startTime", "serviceName", "aggregationTemporality",
            "bucketCounts", "explicitBounds", "attributes.http.route", "resource.attributes.host@name"}
    o = detect(otel)
    assert (o["kind"], o["layout"], o["name"], o["value"], o["type"], o["service"]) == \
        ("metrics", "OpenTelemetry", "name", "value", "kind", "serviceName")
    text = line(o)
    assert text.startswith("kind: metrics stored as documents (OpenTelemetry): one document per data point: the metric's "
                           "name in \"name\" (filter on it first)")
    assert "\"aggregationTemporality\" says" in text and "histograms in \"bucketCounts\" and \"explicitBounds\"" in text
    mb = detect({"@timestamp", "metricset.name", "event.module", "host.name", "system.cpu.total.pct", "service.type"})
    assert (mb["kind"], mb["layout"], mb["name"], mb["host"]) == ("metrics", "Metricbeat / Elastic Agent", "metricset.name",
                                                               "host.name")
    assert detect({"name", "kind", "owner"}) is None                         # a table of data with a name and a kind


def test_a_trace_is_counted_by_its_id():
    from supagent.knowledge.indexkinds import detect, line

    j = line(detect(JAEGER | {"tag.error"}))
    assert 'each row is a span: a trace is the spans sharing "traceID", counted with COUNT(DISTINCT "traceID")' in j
    o = line(detect({"traceId", "spanId", "parentSpanId", "name", "serviceName", "durationInNanos", "startTime"}))
    assert 'COUNT(DISTINCT "traceId")' in o
