"""What each service's logs say every day (0.9.5): the patterns of its lines that come as often every day, learned
from the log tables, so that a warning written every night is known as usual before an investigation blames it.

For each log table whose kind says where the service is (indexkinds: the service field of Fluent Bit, Logstash/ECS,
the OpenTelemetry Collector or a log table of no known shipper), the services with the most lines are each read over
the data's last full day against the days before (compare_logs: its patterns judged "as usual"); their few patterns
of every day (there on each earlier day) are kept with the table (their level, how many lines a day: the median of
the earlier days, their hours) and
describe_data shows them, labelled as what the logs say every day (not what they said on the day asked).
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

from superset import db

log = logging.getLogger(__name__)

SERVICES = 6               # services read per table (the most lines first)
KEPT = 3                   # patterns of every day kept per service


def _tables() -> list[Any]:
    from supagent.models import KObject

    return [ix for ix in db.session.query(KObject).filter(KObject.kind == "index", KObject.gone_at.is_(None))
            if ((ix.stats or {}).get("kind") or {}).get("kind") == "logs" and ((ix.stats or {}).get("kind") or {}).get("service")
            and (ix.stats or {}).get("time_field")]


def _services(ix: Any, field: str) -> list[str]:
    from supagent.models import KObject

    f = db.session.query(KObject).filter(KObject.kind == "field", KObject.parent == ix.name, KObject.name == field,
                                         KObject.source_id == ix.source_id).first()
    st = (f.stats or {}) if f is not None else {}
    top = [str(v[0]) for v in (st.get("top") or []) if isinstance(v, (list, tuple)) and v]
    return (top or [str(v) for v in (st.get("values") or [])])[:SERVICES]


def _day(ix: Any) -> tuple[dt.datetime, dt.datetime] | None:
    """The data's last full day (by the table's learned time range and the clock)."""
    from supagent.agent import now

    rng = (ix.stats or {}).get("time_range") or []
    try:
        last = dt.datetime.strptime(str(rng[1])[:16], "%Y-%m-%d %H:%M") if len(rng) > 1 and rng[1] else None
    except ValueError:
        last = None
    clock = now().replace(tzinfo=None)
    end = min(last, clock) if last else clock
    end = end.replace(hour=0, minute=0, second=0, microsecond=0)
    return end - dt.timedelta(days=1), end


def run(seconds: float = 180.0) -> dict[str, Any]:
    """The usual patterns of the services of every log table, kept with the table. Returns counts."""
    from supagent import tools
    from supagent.knowledge.stopping import check

    t0 = time.time()
    out: dict[str, Any] = {"tables": 0, "services": 0, "patterns": 0}
    for ix in _tables():
        kind = ix.stats["kind"]
        span = _day(ix)
        if span is None:
            continue
        start, end = span
        usual: dict[str, list[dict[str, Any]]] = {}
        for value in _services(ix, kind["service"]):
            if time.time() - t0 > seconds:
                out["left"] = True
                break
            check()
            where = f'"{kind["service"]}" = \'' + value.replace("'", "''") + "'"
            try:
                res = tools.compare_logs(ix.name, f"{start:%Y-%m-%d %H:%M}", f"{end:%Y-%m-%d %H:%M}", where=where, days=7)
            except Exception as ex:  # pylint: disable=broad-except   (one service not read: the others are)
                db.session.rollback()
                log.info("supagent logusual: %s %s not read (%s)", ix.name, value, str(ex)[:200])
                continue
            keep, pats = [], (res or {}).get("patterns") or []
            # of every day: as usual, and there on each earlier day that has lines (the most days any pattern has)
            full = max([int(p.get("earlier_days_with_it") or 0) for p in pats] or [0])
            for p in pats:
                if p.get("verdict") != "as usual" or full < 2 or int(p.get("earlier_days_with_it") or 0) < full \
                        or not p.get("usual"):
                    continue
                keep.append({"pattern": str(p.get("pattern") or "")[:160], "level": p.get("level"),
                             "lines": p.get("usual"), "days": full,
                             "from": str(p.get("from") or "")[11:16], "to": str(p.get("to") or "")[11:16]})
            if keep:
                usual[value] = keep[:KEPT]
                out["services"] += 1
                out["patterns"] += len(keep[:KEPT])
        st = dict(ix.stats or {})
        if usual:
            st["usual_logs"] = {"day": f"{start:%Y-%m-%d}", "services": usual}
        else:
            st.pop("usual_logs", None)
        ix.stats = st
        db.session.commit()
        out["tables"] += 1
    out["seconds"] = round(time.time() - t0, 1)
    return out


def line(usual: dict[str, Any]) -> str:
    """The services' patterns of every day, as the agent is told them (labelled: not what the day asked said)."""
    parts = []
    for s, pats in sorted((usual.get("services") or {}).items()):
        said = []
        for p in pats:
            when = f", {p['from']}-{p['to']}" if p.get("from") and p.get("to") else ""
            lvl = f"{p['level']}, " if p.get("level") else ""
            said.append(f"\"{p['pattern']}\" ({lvl}about {p.get('lines'):,.0f} lines a day{when})")
        parts.append(f"{s}: " + "; ".join(said))
    return (f"what the logs say every day (patterns there on every day before {usual.get('day')}, lines a day: their "
            f"median; usual, not what a day asked said): " + " | ".join(parts))
