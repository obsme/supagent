"""What kind of table each index of the data is (0.9.5), read from its fields alone: logs and the shipper that wrote
them, spans, Kubernetes events, alerts, changes, incidents, an inventory; and, for logs and spans, which field holds
what (the line, its level, the service, the pod, the node, the parent span, the duration and its unit).

A platform's logs come from several shippers, each with its own layout: Fluent Bit's Kubernetes filter (the raw
line in "log", "stream" stdout or stderr, kubernetes.labels.app...), Logstash and the Elastic Common Schema
("message", "log.level", "service.name", "host.name"), the OpenTelemetry Collector ("body", "severity.text",
"resource.service.name"...); its traces are spans (Jaeger: durations in microseconds, the start in microseconds since
the epoch). The agent reads a table through its fields: told what kind of table it is and where each thing is, it
counts errors where they are, reads durations in their unit and finds a service under its name in that table. Each
kind is told only from its whole signature; a table that has none (the business data) gets nothing. Kept in the
index's statistics ("kind") and shown with the index; units are written on the fields that have none.
"""

from __future__ import annotations

import logging
from typing import Any

from superset import db

log = logging.getLogger(__name__)


def _pick(names: set[str], *cands: str) -> str | None:
    low = {n.lower(): n for n in names}
    return next((low[c.lower()] for c in cands if c.lower() in low), None)


def _prefixed(names: set[str], prefix: str) -> bool:
    return any(n.startswith(prefix) for n in names)


def detect(names: set[str]) -> dict[str, Any] | None:
    """The kind of a table from its field names, or None (no whole signature: a table of data)."""
    n = names
    # spans: Jaeger's template, OpenTelemetry's (Data Prepper's otel-v1-apm-span, the collector's)
    if {"traceID", "spanID", "operationName", "duration"} <= n and ("startTimeMillis" in n or "startTime" in n) and \
            _pick(n, "process.serviceName"):
        tags = _prefixed(n, "tag.")
        return {"kind": "spans", "layout": "Jaeger", "service": "process.serviceName", "operation": "operationName",
                "span": "spanID", "parent": _pick(n, "parentSpanID"), "trace": "traceID", "duration": "duration",
                "duration_unit": "microseconds", "start": _pick(n, "startTime"), "time": _pick(n, "startTimeMillis"),
                "peer": _pick(n, "tag.peer@service"), "error": _pick(n, "tag.error"),
                "host": _pick(n, "process.tag.hostname", "process.tag.host@name"),
                "status": _pick(n, "tag.http@status_code", "tag.http@response@status_code"), "tags_as_fields": tags}
    span, parent = _pick(n, "spanId", "span_id"), _pick(n, "parentSpanId", "parent_span_id")
    trace = _pick(n, "traceId", "trace_id")
    dur = _pick(n, "durationInNanos", "duration_nanos", "durationNano")
    service = _pick(n, "serviceName", "resource.service.name", "resource.attributes.service@name",
                    "resource.attributes.service.name", "service.name")
    if span and parent and trace and service and (dur or _pick(n, "endTime")):
        return {"kind": "spans", "layout": "OpenTelemetry", "service": service, "operation": _pick(n, "name"),
                "span": span, "parent": parent, "trace": trace, "duration": dur,
                "duration_unit": "nanoseconds" if dur else None, "time": _pick(n, "startTime", "@timestamp"),
                "status": _pick(n, "status.code", "span.attributes.http@status_code"),
                "peer": _pick(n, "span.attributes.peer@service", "attributes.peer.service")}
    # logs, by the shipper's layout
    if _pick(n, "body", "Body") and _pick(n, "severity.text", "severityText", "SeverityText", "severity.number",
                                           "severityNumber", "SeverityNumber") and \
            (_prefixed(n, "resource.") or _prefixed(n, "Resource.")):
        return {"kind": "logs", "layout": "OpenTelemetry Collector", "message": _pick(n, "body", "Body"),
                "level": _pick(n, "severity.text", "severityText", "SeverityText"),
                "level_number": _pick(n, "severity.number", "severityNumber", "SeverityNumber"),
                "service": _pick(n, "resource.service.name", "Resource.service.name", "resource.attributes.service@name"),
                "pod": _pick(n, "resource.k8s.pod.name", "Resource.k8s.pod.name"),
                "node": _pick(n, "resource.k8s.node.name", "Resource.k8s.node.name", "resource.host.name"),
                "namespace": _pick(n, "resource.k8s.namespace.name"), "trace": _pick(n, "traceId", "TraceId", "trace_id")}
    if _pick(n, "kubernetes.pod_name") and _pick(n, "log", "message") and _prefixed(n, "kubernetes."):
        app = _pick(n, "kubernetes.labels.app_kubernetes_io/name", "kubernetes.labels.app.kubernetes.io/name",
                    "kubernetes.labels.app_kubernetes_io_name", "kubernetes.labels.app", "kubernetes.labels.k8s-app",
                    "kubernetes.container_name")
        return {"kind": "logs", "layout": "Fluent Bit (Kubernetes filter)", "message": _pick(n, "log", "message"),
                "level": _pick(n, "level", "log.level", "severity"), "stream": _pick(n, "stream"), "service": app,
                "pod": "kubernetes.pod_name", "node": _pick(n, "kubernetes.host"),
                "namespace": _pick(n, "kubernetes.namespace_name"), "container": _pick(n, "kubernetes.container_name")}
    if _pick(n, "message") and (_pick(n, "log.level") or _pick(n, "ecs.version") or
                                ("@version" in n and _prefixed(n, "host."))):
        return {"kind": "logs", "layout": "Logstash / Elastic Common Schema", "message": _pick(n, "message"),
                "level": _pick(n, "log.level", "level"), "service": _pick(n, "service.name"),
                "host": _pick(n, "host.name", "host.hostname"), "file": _pick(n, "log.file.path")}
    # metrics stored as documents: OpenTelemetry's (Data Prepper's ss4o_metrics), Metricbeat's / Elastic Agent's
    if _pick(n, "name") and _pick(n, "kind") and (_pick(n, "value", "bucketCounts", "sum", "quantileValues")) and \
            (_pick(n, "time", "@timestamp", "startTime")) and (_pick(n, "serviceName") or _prefixed(n, "resource.")
                                                                or _prefixed(n, "attributes.")):
        return {"kind": "metrics", "layout": "OpenTelemetry", "name": _pick(n, "name"), "value": _pick(n, "value"),
                "type": _pick(n, "kind"), "unit": _pick(n, "unit"), "buckets": _pick(n, "bucketCounts"),
                "bounds": _pick(n, "explicitBounds"), "temporality": _pick(n, "aggregationTemporality"),
                "service": _pick(n, "serviceName", "resource.attributes.service@name", "resource.service.name"),
                "time": _pick(n, "time", "@timestamp")}
    if _pick(n, "metricset.name") and _pick(n, "event.module"):
        return {"kind": "metrics", "layout": "Metricbeat / Elastic Agent", "name": _pick(n, "metricset.name"),
                "module": _pick(n, "event.module"), "host": _pick(n, "host.name", "host.hostname"),
                "service": _pick(n, "service.type", "service.name")}
    # Kubernetes events, alerts
    if _pick(n, "involvedObject.kind") and _pick(n, "reason"):
        return {"kind": "events", "layout": "Kubernetes events", "object": _pick(n, "involvedObject.name"),
                "reason": "reason", "type": _pick(n, "type"), "message": _pick(n, "message", "note"),
                "node": _pick(n, "source.host")}
    if _pick(n, "alertname", "labels.alertname") and _pick(n, "startsAt", "status", "starts_at"):
        return {"kind": "alerts", "layout": "Alertmanager", "name": _pick(n, "alertname", "labels.alertname"),
                "status": _pick(n, "status"), "start": _pick(n, "startsAt", "starts_at"), "end": _pick(n, "endsAt", "ends_at"),
                "severity": _pick(n, "severity", "labels.severity")}
    from supagent.knowledge.aliases import ALIAS_FIELDS, NAME_FIELDS

    if _pick(n, *NAME_FIELDS) and _pick(n, *ALIAS_FIELDS):
        return {"kind": "inventory", "layout": "", "name": _pick(n, *NAME_FIELDS), "aliases": _pick(n, *ALIAS_FIELDS)}
    # logs of no known shipper: a field of the line and a field of its level, by their names
    msg, lvl = _pick(n, "message", "msg", "log_message", "log"), _pick(n, "level", "log_level", "loglevel", "severity")
    if msg and lvl:
        return {"kind": "logs", "layout": "", "message": msg, "level": lvl,
                "service": _pick(n, "application", "app", "service", "service_name"), "host": _pick(n, "host", "hostname", "node")}
    return None


TITLES = {"spans": "spans of traces", "logs": "logs", "events": "events", "alerts": "alerts", "inventory":
          "an inventory of the platform's parts", "metrics": "metrics stored as documents"}


def line(kind: dict[str, Any]) -> str:
    """The kind of a table as the agent is told it (one line)."""
    k = kind.get("kind")
    q = lambda f: f'"{f}"'  # noqa: E731
    head = f"kind: {TITLES.get(k, k)}" + (f" ({kind['layout']})" if kind.get("layout") else "")
    parts: list[str] = []
    if k == "spans":
        if kind.get("duration"):
            unit = kind.get("duration_unit")
            div = {"microseconds": " (/1000 for ms)", "nanoseconds": " (/1000000 for ms)"}.get(unit or "", "")
            parts.append(f"{q(kind['duration'])} in {unit}{div}" if unit else f"duration {q(kind['duration'])}")
        if kind.get("start") and kind.get("layout") == "Jaeger":
            parts.append(f"{q(kind['start'])} in microseconds since the epoch"
                         + (f" (bound the time on {q(kind['time'])}, a date)" if kind.get("time") else ""))
        for role, said in (("service", "service"), ("operation", "operation"), ("parent", "parent span"),
                           ("peer", "the service a client span calls"), ("error", "errors"), ("status", "status")):
            if kind.get(role):
                parts.append(f"{said} {q(kind[role])}" + (" = 'true'" if role == "error" else ""))
        if kind.get("layout") == "Jaeger" and not kind.get("tags_as_fields"):
            parts.append("its tags are nested: SQL cannot filter on them (no status, error or peer here)")
        parts.append("a span whose parent is a span of another service is a call between them")
        if kind.get("trace"):                # (0.9.5: "how many traces had an error" was answered with the spans)
            parts.append(f"each row is a span: a trace is the spans sharing {q(kind['trace'])}, counted with "
                         f"COUNT(DISTINCT {q(kind['trace'])})")
    elif k == "logs":
        if kind.get("message"):
            parts.append(f"the line is {q(kind['message'])}")
        if kind.get("level"):
            parts.append(f"its level {q(kind['level'])}")
        elif kind.get("layout", "").startswith("Fluent Bit"):
            parts.append("no level field: a level, when the application writes one, is in the line's text")
        if kind.get("level_number"):
            parts.append(f"{q(kind['level_number'])} 17-20 is ERROR, 13-16 WARN, 9-12 INFO")
        if kind.get("stream"):
            parts.append(f"{q(kind['stream'])} is stdout or stderr")
        for role, said in (("service", "service"), ("pod", "pod"), ("node", "node"), ("host", "host"),
                           ("namespace", "namespace"), ("trace", "trace id (the spans of the request)")):
            if kind.get(role):
                parts.append(f"{said} {q(kind[role])}")
    elif k == "events":
        parts += [f"object {q(kind['object'])}" if kind.get("object") else "", f"reason {q(kind['reason'])}",
                  f"Normal or Warning in {q(kind['type'])}" if kind.get("type") else ""]
    elif k == "alerts":
        parts += [f"alert {q(kind['name'])}", f"firing or resolved in {q(kind['status'])}" if kind.get("status") else "",
                  f"from {q(kind['start'])} to {q(kind['end'])}" if kind.get("start") and kind.get("end") else ""]
    elif k == "inventory":
        parts.append(f"each {q(kind['name'])} with its other names in {q(kind['aliases'])}")
    elif k == "metrics" and kind.get("layout") == "OpenTelemetry":
        parts.append(f"one document per data point: the metric's name in {q(kind['name'])} (filter on it first)")
        if kind.get("value"):
            parts.append(f"its value in {q(kind['value'])}")
        parts.append(f"GAUGE, SUM or HISTOGRAM in {q(kind['type'])}" + (
            f" (a SUM may be cumulative: {q(kind['temporality'])} says; its increase is the last value minus the first, "
            f"per series)" if kind.get("temporality") else ""))
        if kind.get("buckets"):
            parts.append(f"histograms in {q(kind['buckets'])}" + (f" and {q(kind['bounds'])}" if kind.get("bounds") else ""))
        for role, said in (("service", "service"), ("unit", "unit")):
            if kind.get(role):
                parts.append(f"{said} {q(kind[role])}")
    elif k == "metrics":
        parts.append(f"one document per metricset and period: {q(kind['name'])} says which (cpu, memory, network...), "
                     f"the values in their own fields")
        for role, said in (("module", "module"), ("host", "host"), ("service", "service")):
            if kind.get(role):
                parts.append(f"{said} {q(kind[role])}")
    parts = [p for p in parts if p]
    return head + (": " + "; ".join(parts) if parts else "")


UNITS = {"microseconds": ("duration", "start"), "nanoseconds": ("duration",)}


def run(seconds: float = 60.0) -> dict[str, Any]:
    """Every index of the dictionary looked at: its kind kept (or dropped when it has none any more), the units of
    its spans' fields written where none is. Returns the kinds found."""
    from supagent.models import KObject

    fields: dict[tuple[int, str], set[str]] = {}
    for sid, parent, name in db.session.query(KObject.source_id, KObject.parent, KObject.name).filter(
            KObject.kind == "field", KObject.gone_at.is_(None)):
        fields.setdefault((sid, parent), set()).add(name)
    out: dict[str, Any] = {"indices": 0, "kinds": {}}
    for ix in db.session.query(KObject).filter(KObject.kind == "index", KObject.gone_at.is_(None)):
        out["indices"] += 1
        kind = detect(fields.get((ix.source_id, ix.name), set()))
        st = dict(ix.stats or {})
        if kind is None:
            if "kind" in st:
                st.pop("kind")
                ix.stats = st
            continue
        if st.get("kind") != kind:
            st["kind"] = kind
            ix.stats = st
        out["kinds"][ix.name] = f"{kind['kind']} ({kind.get('layout') or '-'})"
        unit = kind.get("duration_unit")
        for role in UNITS.get(unit or "", ()):
            name = kind.get(role)
            if not name:
                continue
            f = db.session.query(KObject).filter(KObject.source_id == ix.source_id, KObject.kind == "field",
                                                 KObject.parent == ix.name, KObject.name == name).first()
            said = unit if role == "duration" else f"{unit} since the epoch"
            if f is not None and not f.unit:
                f.unit = said
    db.session.commit()
    return out
