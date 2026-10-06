"""The calls between services that the span indices hold (0.9.5).

A span index (Jaeger's, or OpenTelemetry's written by the collector or Data Prepper) keeps for each operation its
trace and span ids, its parent span's id, the service that ran it and how long it took. A span whose parent is a span
of another service is a call of that service to this one (frontend -> checkout); a client span that names its peer
(peer.service; Jaeger stores tags as fields as tag.peer@service) is a call to a part that writes no spans of its own
(a database, an outside provider). The learning reads them over the last day of the data and writes them on the
System map as interactions "calls" between the services' values, with how many and how long: approved when the
values read in the data are (categories.review_all off), proposed otherwise. Jaeger's default template keeps tags
nested, which SQL cannot read: there only the parent links count.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import time
from typing import Any

from superset import db

log = logging.getLogger(__name__)

SPAN_IDS = ("spanID", "spanId", "span_id", "span.id")
PARENT_IDS = ("parentSpanID", "parentSpanId", "parent_span_id", "parentId", "parent.id")
SERVICES = ("process.serviceName", "resource.service.name", "serviceName", "service.name", "service_name")
PEERS = ("tag.peer@service", "peer.service", "attributes.peer.service", "span.attributes.peer@service",
         "tag.peer.service")
DURATIONS = ("duration", "durationInNanos", "duration_ns", "durationNano", "duration_us", "duration_ms")
TIMES = ("startTimeMillis", "startTime", "@timestamp", "timestamp", "time")
LEAST = 5                  # calls a day before a pair is written


def _ms(field: str, fields: set[str]) -> float:
    """Milliseconds per unit of the duration field: Jaeger writes microseconds (its spans have startTimeMillis),
    OpenTelemetry's layouts nanoseconds (durationInNanos...)."""
    low = field.lower()
    if low.endswith(("nanos", "nano", "_ns")):
        return 1e-6
    if low.endswith("_ms"):
        return 1.0
    if low.endswith("_us") or "startTimeMillis" in fields:
        return 1e-3
    return 1e-6


def layouts() -> list[dict[str, Any]]:
    """The span tables of the dictionary: a span id, a parent id and a service field (with the peer, duration and
    time fields when they are there), with the database each is in."""
    from supagent.models import KObject, Source

    sources = {s.id: s for s in db.session.query(Source)}
    fields: dict[tuple[int, str], set[str]] = {}
    times: dict[tuple[int, str], str | None] = {}
    for o in db.session.query(KObject.source_id, KObject.kind, KObject.parent, KObject.name, KObject.stats).filter(
            KObject.kind.in_(("index", "field")), KObject.gone_at.is_(None)):
        if o.kind == "index":
            times[(o.source_id, o.name)] = (o.stats or {}).get("time_field")
        else:
            fields.setdefault((o.source_id, o.parent), set()).add(o.name)
    out = []
    for (sid, table), names in fields.items():
        pick = {k: next((n for n in cands if n in names), None)
                for k, cands in (("span", SPAN_IDS), ("parent", PARENT_IDS), ("service", SERVICES), ("peer", PEERS),
                                 ("duration", DURATIONS), ("time", TIMES))}
        src = sources.get(sid)
        if not (pick["span"] and pick["parent"] and pick["service"]) or src is None or not src.database_id:
            continue
        tf = times.get((sid, table)) or pick["time"]
        if not tf:
            continue
        out.append({"database": src.database_id, "table": table, **pick, "time": tf,
                    "ms": _ms(pick["duration"], names) if pick["duration"] else None})
    return out


TABLE = re.compile(r"^[\w.\-*?]+$")


def _table(table: str) -> str:
    """A table name as the dictionary has it (an index, or a family's pattern such as spans-*), checked."""
    t = str(table or "").strip().strip('"')
    if not TABLE.match(t):
        raise ValueError(f"not a table name: {table!r}")
    return t


def _calls(t: dict[str, Any], hours: int) -> dict[tuple[str, str], dict[str, Any]]:
    """(caller, callee) -> {"n", "ms", "how"} over the last `hours` of the data (the clock's, else the table's own
    last day)."""
    from superset.models.core import Database

    from supagent import tools
    from supagent.knowledge import groups as G

    database = db.session.get(Database, t["database"])
    if database is None:
        return {}
    table, svc, tf = G.table(t["table"]), G.name(t["service"]), G.name(t["time"])
    span, parent = G.name(t["span"]), G.name(t["parent"])
    dur = G.name(t["duration"]) if t.get("duration") else None
    out: dict[tuple[str, str], dict[str, Any]] = {}
    with tools._db_connection(database, extract=False) as conn:
        cur = conn.cursor()
        end = tools._local_now(conn)
        start = end - dt.timedelta(hours=hours)
        cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{tf}" >= {G.lit(start)} AND "{tf}" < {G.lit(end)}')
        if not (cur.fetchall() or [[0]])[0][0]:
            cur.execute(f'SELECT MAX("{tf}") FROM "{table}"')       # the table's own last day (older data)
            last = (cur.fetchall() or [[None]])[0][0]
            if last is None:
                return {}
            end = last if isinstance(last, dt.datetime) else end
            start = end - dt.timedelta(hours=hours)
        window = f'"{tf}" >= {G.lit(start)} AND "{tf}" <= {G.lit(end)}'
        child = f'c."{tf}" >= {G.lit(start)} AND c."{tf}" <= {G.lit(end)}'
        early = f'p."{tf}" >= {G.lit(start - dt.timedelta(hours=1))} AND p."{tf}" <= {G.lit(end)}'   # (a parent starts first)
        avg = f', AVG(c."{dur}")' if dur else ""
        cur.execute(f'SELECT p."{svc}", c."{svc}", COUNT(*){avg} FROM "{table}" c JOIN "{table}" p '
                    f'ON c."{parent}" = p."{span}" WHERE {child} AND {early} GROUP BY 1, 2')
        for row in cur.fetchall():
            a, b, n = row[0], row[1], int(row[2] or 0)
            if a and b and a != b and n:
                out[(str(a), str(b))] = {"n": n, "ms": float(row[3]) * t["ms"] if dur and row[3] is not None and t["ms"] else None,
                                         "how": "parent"}
        if t.get("peer"):
            peer = G.name(t["peer"])
            avg = f', AVG("{dur}")' if dur else ""
            cur.execute(f'SELECT "{svc}", "{peer}", COUNT(*){avg} FROM "{table}" WHERE {window} AND "{peer}" IS NOT NULL '
                        f'GROUP BY 1, 2')
            for row in cur.fetchall():
                a, b, n = row[0], row[1], int(row[2] or 0)
                if a and b and a != b and n and (str(a), str(b)) not in out:
                    out[(str(a), str(b))] = {"n": n, "ms": float(row[3]) * t["ms"] if dur and row[3] is not None and t["ms"] else None,
                                             "how": "peer"}
    for v in out.values():
        v.update(start=start, end=end)
    return out


def run(seconds: float = 120.0, hours: int = 24) -> dict[str, Any]:
    """The span tables read, their calls written on the System map between the services' values. Returns counts."""
    from supagent.knowledge.brief import _graph
    from supagent.knowledge.facets import review_all
    from supagent.knowledge.linkfinder import resolve
    from supagent.knowledge.stopping import check
    from supagent.models import Link

    t0 = time.time()
    out: dict[str, Any] = {"tables": 0, "calls": 0, "written": 0, "unmapped": []}
    g = _graph()
    names: dict[str, list[int]] = g.get("names") or {}      # the values' names and their synonyms
    if len(g["values"]) < 2:
        return out
    status = "proposed" if review_all() else "approved"
    for t in layouts():
        if time.time() - t0 > seconds:
            out["left"] = True
            break
        check()
        try:
            calls = _calls(t, hours)
        except Exception as ex:  # pylint: disable=broad-except   (one table not read: the others are)
            db.session.rollback()
            log.info("supagent spans: %s not read (%s)", t["table"], str(ex)[:200])
            out.setdefault("not_read", []).append(t["table"])
            continue
        out["tables"] += 1
        for (a, b), f in sorted(calls.items(), key=lambda kv: -kv[1]["n"]):
            out["calls"] += 1
            ia, ib = resolve(a, names), resolve(b, names)
            if ia is None or ib is None or ia == ib:
                out["unmapped"].append(f"{a} -> {b}")
                continue
            if f["n"] < LEAST:
                continue
            a_ref, b_ref = f"facet:{ia}", f"facet:{ib}"
            how = (f"child spans of {b} under spans of {a}" if f["how"] == "parent" else
                   f"client spans of {a} naming {b} as their peer")
            each = f", about {f['ms']:.0f} ms each" if f.get("ms") is not None else ""
            note = f"{a} calls {b} ({f['n']} calls in a day{each})"
            evidence = (f"{f['n']} {how} in {t['table']} from {f['start']:%Y-%m-%d %H:%M} to {f['end']:%Y-%m-%d %H:%M}"
                        f"{each}")
            x = db.session.query(Link).filter(Link.a_ref == a_ref, Link.b_ref == b_ref, Link.kind == "calls").first()
            if x is None:
                db.session.add(Link(a_ref=a_ref, b_ref=b_ref, kind="calls", confidence=0.95, source="spans", status=status,
                                    note=note[:500], evidence=evidence[:2000]))
                out["written"] += 1
            elif x.source == "spans":                 # (a link of the admin, the documents or the logs is theirs)
                x.evidence = evidence[:2000]
                if not x.explained_by:
                    x.note = note[:500]
        db.session.commit()
    out["unmapped"] = out["unmapped"][:10]
    out["seconds"] = round(time.time() - t0, 1)
    return out
