"""The usual behaviour of each service, learned from the span tables (0.9.5): how many of its spans a day, how long
they take (average and 95th percentile) and how many end in an error, as the median of the days before, with its
busiest hours.

To tell a slowness or a burst of errors from what a service always does, an answer compares a figure with its usual;
the comparisons (compare_groups, compare_logs) do it on demand for one window. This keeps, for every service of the
span tables, its usual day: the median of each day's figures over the days before the data's last day (a day of an
incident among them does not make the usual), the service's own work only (its server spans when the spans say
their kind), with the busiest hours. Spans are the traces kept, not every request: the counts say how many spans,
not how many requests. Shown with the span table in describe_data, labelled as a usual, never as a figure of a day.
"""

from __future__ import annotations

import datetime as dt
import logging
import statistics
import time
from typing import Any

from superset import db

log = logging.getLogger(__name__)

DAYS = 7
KIND_FIELDS = ("tag.span@kind", "span.kind", "kind")


def _rows(t: dict[str, Any], days: int) -> tuple[list[tuple], list[tuple], dt.datetime, dt.datetime, bool]:
    """(daily rows, hourly rows, start, end, server spans only) of a span table over the `days` days before its last
    day: (day or hour, service, spans, avg, p95, errors)."""
    from superset.models.core import Database

    from supagent import tools
    from supagent.knowledge import groups as G
    from supagent.models import KObject

    database = db.session.get(Database, t["database"])
    table, svc, tf, dur = G.table(t["table"]), G.name(t["service"]), G.name(t["time"]), G.name(t["duration"])
    names = {n for (n,) in db.session.query(KObject.name).filter(KObject.kind == "field", KObject.parent == t["table"],
                                                                 KObject.gone_at.is_(None))}
    kind = next((k for k in KIND_FIELDS if k in names), None)
    err = t.get("error") or ("tag.error" if "tag.error" in names else None)
    with tools._db_connection(database, extract=False) as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT MAX("{tf}") FROM "{table}"')
        last = (cur.fetchall() or [[None]])[0][0]
        if not isinstance(last, dt.datetime):
            return [], [], None, None, False
        end = min(last, tools._local_now(conn)).replace(hour=0, minute=0, second=0, microsecond=0)
        start = end - dt.timedelta(days=days)
        where = f'"{tf}" >= {G.lit(start)} AND "{tf}" < {G.lit(end)}' + (f" AND \"{G.name(kind)}\" = 'server'" if kind else "")
        errors = f", SUM(CASE WHEN \"{G.name(err)}\" = 'true' THEN 1 ELSE 0 END)" if err else ", 0"
        out = []
        for grain in ("day", "hour"):
            sql = (f"SELECT DATE_TRUNC('{grain}', \"{tf}\"), \"{svc}\", COUNT(*), AVG(\"{dur}\"), "
                   f"APPROX_QUANTILE(\"{dur}\", 0.95){errors} FROM \"{table}\" WHERE {where} GROUP BY 1, 2")
            try:
                cur.execute(sql)
            except Exception:  # pylint: disable=broad-except   (an engine without the quantile: no p95)
                cur.execute(sql.replace(f'APPROX_QUANTILE("{dur}", 0.95)', "NULL"))
            out.append(cur.fetchall())
    return out[0], out[1], start, end, bool(kind)


def learn(t: dict[str, Any], days: int = DAYS) -> dict[str, Any] | None:
    """The usual day of each service of one span table."""
    daily, hourly, start, end, server = _rows(t, days)
    if not daily:
        return None
    ms = t.get("ms") or 1.0
    per: dict[str, dict[str, list[float]]] = {}
    days_seen = sorted({d.date() for d, *_x in daily if isinstance(d, dt.datetime)})
    for _day, s, n, avg, p95, errs in daily:
        if not s or not n:
            continue
        d = per.setdefault(str(s), {"n": [], "avg": [], "p95": [], "err": []})
        d["n"].append(float(n))
        if avg is not None:
            d["avg"].append(float(avg) * ms)
        if p95 is not None:
            d["p95"].append(float(p95) * ms)
        d["err"].append(100.0 * float(errs or 0) / float(n))
    hours: dict[str, dict[int, list[float]]] = {}
    for hour, s, n, *_rest in hourly:
        if s and n and isinstance(hour, dt.datetime):
            hours.setdefault(str(s), {}).setdefault(hour.hour, []).append(float(n))
    med = lambda xs: round(statistics.median(xs), 1) if xs else None  # noqa: E731
    services = {}
    for s, d in per.items():
        by_hour = {h: statistics.median(v) for h, v in (hours.get(s) or {}).items()}
        busiest = sorted(by_hour, key=lambda h: -by_hour[h])[:3]
        services[s] = {"spans_day": med(d["n"]), "avg_ms": med(d["avg"]), "p95_ms": med(d["p95"]),
                       "error_pct": med(d["err"]), "days": len(d["n"]), "busiest_hours": sorted(busiest)}
    if not days_seen:
        return None
    return {"from": f"{days_seen[0]:%Y-%m-%d}", "to": f"{days_seen[-1]:%Y-%m-%d}", "days": len(days_seen),
            "server_spans": server, "services": services}


def run(seconds: float = 120.0) -> dict[str, Any]:
    """Every span table's services: their usual day kept with the table. Returns counts."""
    from supagent.knowledge.spans import layouts
    from supagent.knowledge.stopping import check
    from supagent.models import KObject

    t0 = time.time()
    out: dict[str, Any] = {"tables": 0, "services": 0}
    for t in layouts():
        if time.time() - t0 > seconds:
            out["left"] = True
            break
        if not t.get("duration"):
            continue
        check()
        try:
            usual = learn(t)
        except Exception as ex:  # pylint: disable=broad-except   (one table not read: the others are)
            db.session.rollback()
            log.info("supagent behaviour: %s not read (%s)", t["table"], str(ex)[:200])
            out.setdefault("not_read", []).append(t["table"])
            continue
        ix = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == t["table"],
                                              KObject.gone_at.is_(None)).first()
        if ix is None or usual is None:
            continue
        st = dict(ix.stats or {})
        st["usual"] = usual
        ix.stats = st
        out["tables"] += 1
        out["services"] += len(usual["services"])
    db.session.commit()
    out["seconds"] = round(time.time() - t0, 1)
    return out


def line(usual: dict[str, Any]) -> str:
    """The usual day of the services of a span table, as the agent is told it (labelled: not a figure of a day)."""
    head = (f"usual (the median of the {usual.get('days')} days from {usual['from']} to {usual.get('to') or usual.get('until')}; "
            f"{'server spans, ' if usual.get('server_spans') else ''}the traces kept, not every request; not a figure "
            f"of any day asked):")
    parts = []
    for s, u in sorted((usual.get("services") or {}).items()):
        bits = [f"{u['spans_day']:,.0f} spans a day" if u.get("spans_day") is not None else ""]
        if u.get("avg_ms") is not None:
            bits.append(f"avg {u['avg_ms']:,.0f} ms")
        if u.get("p95_ms") is not None:
            bits.append(f"p95 {u['p95_ms']:,.0f} ms")
        if u.get("error_pct") is not None:
            bits.append(f"errors {u['error_pct']:.1f} %")
        if u.get("busiest_hours"):
            bits.append("busiest hours " + ", ".join(f"{h:02d}h" for h in u["busiest_hours"]))
        parts.append(f"{s}: " + ", ".join(b for b in bits if b))
    return head + " " + "; ".join(parts)
