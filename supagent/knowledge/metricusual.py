"""The usual latency and traffic of each service from its latency histograms (0.9.5).

A question of slowness ("is checkout slow today?", "was payment slower than usual this morning?") needs what is
usual. compare_to_usual measures it on demand for one expression; this keeps, for every histogram of durations
whose series name a service (service_name, service, application, app, job), the usual day of each service: its
median and 95th percentile and its requests a day, as the median of the days before the data's last day (a day of an
incident among them does not make the usual). Shown with the histogram in describe_data, labelled as a usual, never
as a figure of a day. No LLM: two range queries per histogram, one point per day.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import statistics
import time
from typing import Any

from superset import db

log = logging.getLogger(__name__)

DAYS = 7
DAY_MS = 86_400_000
SERVICE_LABELS = ("service_name", "service", "application", "app", "job")


def histograms() -> list[tuple[Any, str]]:
    """(the _bucket metric, its service label) of every histogram of durations whose series name a service."""
    from supagent.models import KObject

    out = []
    for m in db.session.query(KObject).filter(KObject.kind == "metric", KObject.gone_at.is_(None),
                                              KObject.name.like("%_bucket")):
        labels = set((m.stats or {}).get("labels") or [])
        svc = next((s for s in SERVICE_LABELS if s in labels), None)
        if "le" in labels and svc and "seconds" in m.name.lower() and (m.stats or {}).get("data_to_ms"):
            out.append((m, svc))
    return out


def _days(conn: Any, expr: str, start: int, end: int, svc: str) -> dict[str, list[float]]:
    """Per service, the value of `expr` at the end of each day (one point a day)."""
    per: dict[str, list[float]] = {}
    for s in conn.client.query_range(expr, start, end, DAY_MS):
        name = (s.labels or {}).get(svc)
        if not name:
            continue
        for _t, v in s.points:
            if v is not None and not math.isnan(v) and not math.isinf(v):
                per.setdefault(str(name), []).append(float(v))
    return per


def learn(conn: Any, m: Any, svc: str, days: int = DAYS) -> dict[str, Any] | None:
    """The usual day of each service of one histogram: the median of the full days before its last day."""
    st = m.stats or {}
    end = (int(st["data_to_ms"]) // DAY_MS) * DAY_MS              # the start of the data's last day (UTC)
    start = end - days * DAY_MS
    try:                                                          # full days only (the start is known to the day)
        first = dt.datetime.strptime(str(st.get("data_from") or "")[:16], "%Y-%m-%d %H:%M").replace(tzinfo=dt.timezone.utc)
        start = max(start, ((int(first.timestamp() * 1000) // DAY_MS) + 1) * DAY_MS)
    except ValueError:
        pass
    if end - start < DAY_MS:
        return None
    base = m.name[:-len("_bucket")]
    q = {f"p{int(100 * p)}": _days(conn, f"histogram_quantile({p}, sum by (le, {svc}) (increase({m.name}[1d])))",
                                   start + DAY_MS, end, svc) for p in (0.5, 0.95)}
    n = _days(conn, f"sum by ({svc}) (increase({base}_count[1d]))", start + DAY_MS, end, svc)
    services = {}
    for s in sorted(set(q["p50"]) | set(q["p95"])):
        med = lambda xs: round(statistics.median(xs), 4) if xs else None  # noqa: E731
        services[s] = {"p50_s": med(q["p50"].get(s, [])), "p95_s": med(q["p95"].get(s, [])),
                       "requests_day": med(n.get(s, [])), "days": len(q["p95"].get(s, []))}
    if not services:
        return None
    day = lambda ms: dt.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")  # noqa: E731
    return {"from": day(start), "to": day(end - DAY_MS), "days": (end - start) // DAY_MS, "label": svc,
            "services": services}


def run(seconds: float = 60.0) -> dict[str, Any]:
    """Every latency histogram that names its services: their usual day kept with it. Returns counts."""
    from superset.models.core import Database

    from supagent import tools
    from supagent.knowledge.stopping import check
    from supagent.models import Source

    t0 = time.time()
    out: dict[str, Any] = {"histograms": 0, "services": 0}
    conns: dict[int, Any] = {}
    try:
        for m, svc in histograms():
            if time.time() - t0 > seconds:
                out["left"] = True
                break
            check()
            src = db.session.get(Source, m.source_id)
            if src is None or not src.database_id:
                continue
            try:
                if src.database_id not in conns:
                    conns[src.database_id] = tools._promagg_connection(db.session.get(Database, src.database_id))
                usual = learn(conns[src.database_id], m, svc)
            except Exception as ex:  # pylint: disable=broad-except   (one histogram not read: the others are)
                db.session.rollback()
                log.info("supagent metricusual: %s not read (%s)", m.name, str(ex)[:200])
                continue
            st = dict(m.stats or {})
            if usual:
                st["usual"] = usual
                out["histograms"] += 1
                out["services"] += len(usual["services"])
            else:
                st.pop("usual", None)
            m.stats = st
        db.session.commit()
    finally:
        for c in conns.values():
            try:
                c.close()
            except Exception:  # pylint: disable=broad-except
                pass
    out["seconds"] = round(time.time() - t0, 1)
    return out


def _s(v: float | None) -> str:
    if v is None:
        return "?"
    return f"{v * 1000:,.0f} ms" if v < 1 else f"{v:,.2f} s"


def line(usual: dict[str, Any]) -> str:
    """The usual day of the services of a latency histogram, as the agent is told it (not a figure of a day)."""
    parts = []
    for s, u in sorted((usual.get("services") or {}).items()):
        bits = [f"p50 {_s(u.get('p50_s'))}", f"p95 {_s(u.get('p95_s'))}"]
        if u.get("requests_day") is not None:
            bits.append(f"{u['requests_day']:,.0f} requests a day")
        parts.append(f"{s}: " + ", ".join(bits))
    return (f"usual (the median of the {usual.get('days')} days from {usual.get('from')} to {usual.get('to')}, by "
            f"{usual.get('label')}; a p95 at the largest bucket means at least that; not a figure of any day asked): "
            + "; ".join(parts))
