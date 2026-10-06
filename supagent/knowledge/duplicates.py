"""The same events in two log tables (0.9.5): an application's lines shipped twice, by two shippers.

A platform's logs often reach OpenSearch twice: the application writes them through the OpenTelemetry SDK (the
Collector's table) and to its container's stdout (Fluent Bit's table), or a file read by Filebeat/Logstash. Counted
in both and added, every error is counted twice; compared across the two, one table's "new" pattern is the other's
usual one. This finds them from the data: for each log table, a few lines of each of its busiest services on its
last full day, each looked for in every other log table (the same pod or host when both tables have one, within two
seconds, the line's text inside the other's line); most of them found there: the same events, said with both
tables (how many of how many lines were found, by what). No LLM.
"""

from __future__ import annotations

import datetime as dt
import logging
import time
from typing import Any

from superset import db

log = logging.getLogger(__name__)

SERVICES = 3            # services sampled per table (the most lines first)
LINES = 8               # lines looked for per service
FOUND = 0.8             # the share found that makes them the same events
SECONDS = 2             # how far apart in time the same event may be in the two tables
MIN_TEXT = 12           # a line shorter than this says too little to be looked for


def _tables() -> list[Any]:
    from supagent.models import KObject

    return [ix for ix in db.session.query(KObject).filter(KObject.kind == "index", KObject.gone_at.is_(None))
            if ((ix.stats or {}).get("kind") or {}).get("kind") == "logs"
            and ((ix.stats or {}).get("kind") or {}).get("message") and (ix.stats or {}).get("time_field")]


def _identity(a: dict[str, Any], b: dict[str, Any]) -> tuple[str, str] | None:
    """The fields that name the same pod (else the same host) in two log tables, when both have one."""
    for role in ("pod", "host"):
        if a.get(role) and b.get(role):
            return a[role], b[role]
    return None


def _identity_values(ix: Any) -> tuple[str | None, set[str]]:
    """("pod" or "host", the values the dictionary knows of that field) of a log table, to leave out the pairs of
    tables of one role that share none: no query for them (many log tables: most pairs are other applications)."""
    from supagent.models import KObject

    kind = (ix.stats or {}).get("kind") or {}
    role = "pod" if kind.get("pod") else "host" if kind.get("host") else None
    if not role:
        return None, set()
    f = db.session.query(KObject).filter(KObject.kind == "field", KObject.parent == ix.name, KObject.name == kind[role],
                                         KObject.source_id == ix.source_id).first()
    return role, {str(v).lower() for v in (((f.stats or {}).get("values") or []) if f is not None else [])}


def _piece(text: str) -> str | None:
    """The longest part of a line without LIKE's wildcards or a quote, when long enough to be looked for."""
    import re

    parts = [p.strip() for p in re.split(r"[%_'\\\n]", str(text or ""))]
    best = max(parts, key=len, default="")
    return best[:200] if len(best) >= MIN_TEXT else None


def _day(ix: Any) -> tuple[dt.datetime, dt.datetime] | None:
    from supagent.knowledge.logusual import _day as last_full_day

    return last_full_day(ix)


def _services(ix: Any, field: str | None) -> list[str | None]:
    if not field:
        return [None]
    from supagent.knowledge.logusual import _services as top

    return top(ix, field)[:SERVICES] or [None]


def compare(run_sql: Any, a: Any, b: Any) -> list[dict[str, Any]]:
    """Which services' lines of table a are found in table b: [{"service", "found", "lines", "by"}]."""
    ka, kb = a.stats["kind"], b.stats["kind"]
    ta, tb = a.stats["time_field"], b.stats["time_field"]
    ident = _identity(ka, kb)
    span = _day(a)
    if span is None:
        return []
    start, end = span
    out = []
    for service in _services(a, ka.get("service")):
        scope = f' AND "{ka["service"]}" = \'' + str(service).replace("'", "''") + "'" if service is not None else ""
        cols = f'"{ta}", "{ka["message"]}"' + (f', "{ident[0]}"' if ident else "")
        rows = run_sql(f'SELECT {cols} FROM "{a.name}" WHERE "{ta}" >= \'{start:%Y-%m-%d %H:%M:%S}\' AND "{ta}" < '
                       f'\'{end:%Y-%m-%d %H:%M:%S}\'{scope} ORDER BY "{ta}" LIMIT {LINES * 25}')
        picked = [r for r in rows[::max(1, len(rows) // LINES)] if isinstance(r[0], dt.datetime) and _piece(r[1])][:LINES]
        if len(picked) < LINES // 2:
            continue
        found, there = 0, None
        for r in picked:
            t0, t1 = r[0] - dt.timedelta(seconds=SECONDS), r[0] + dt.timedelta(seconds=SECONDS)
            same = (f' AND "{ident[1]}" = \'' + str(r[2]).replace("'", "''") + "'") if ident and r[2] is not None else ""
            where = (f'"{tb}" >= \'{t0:%Y-%m-%d %H:%M:%S}\' AND "{tb}" <= \'{t1:%Y-%m-%d %H:%M:%S}\'{same} AND '
                     f'"{kb["message"]}" LIKE \'%{_piece(r[1])}%\'')
            got = run_sql(f'SELECT COUNT(*) FROM "{b.name}" WHERE {where}')
            if got and got[0][0]:
                found += 1
                if there is None and kb.get("service"):        # the service's name in the other table
                    named = run_sql(f'SELECT "{kb["service"]}" FROM "{b.name}" WHERE {where} LIMIT 1')
                    there = str(named[0][0]) if named and named[0][0] is not None else ""
        out.append({"service": service, "found": found, "lines": len(picked), "there": there or None,
                    "by": f"the same {'pod' if ident and ident == (ka.get('pod'), kb.get('pod')) else 'host'}, "
                          if ident else ""})
    return out


def run(seconds: float = 120.0) -> dict[str, Any]:
    """Every pair of log tables of one database looked at both ways; what is found kept with both tables
    (stats["same_events"]). Returns counts."""
    from superset.models.core import Database

    from supagent import tools
    from supagent.knowledge.stopping import check

    t0 = time.time()
    tables = _tables()
    said: dict[int, list[str]] = {ix.id: [] for ix in tables}
    out: dict[str, Any] = {"tables": len(tables), "pairs": 0, "same": 0}
    by_db: dict[int, list[Any]] = {}
    from supagent.models import Source

    for ix in tables:
        src = db.session.get(Source, ix.source_id)
        if src is not None and src.database_id:
            by_db.setdefault(src.database_id, []).append(ix)
    for database_id, group in by_db.items():
        database = db.session.get(Database, database_id)
        with tools._db_connection(database, extract=False) as conn:
            cur = conn.cursor()

            def run_sql(sql: str) -> list:
                cur.execute(sql)
                return cur.fetchall()

            idents = {ix.id: _identity_values(ix) for ix in group}
            for a in group:
                for b in group:
                    if a.id == b.id:
                        continue
                    (ra, ia), (rb, ib) = idents[a.id], idents[b.id]
                    if ra and ra == rb and ia and ib and not ia & ib:
                        continue                   # their pods (hosts) never meet: not the same events (no query)
                    if time.time() - t0 > seconds:
                        out["left"] = True
                        break
                    check()
                    out["pairs"] += 1
                    try:
                        found = compare(run_sql, a, b)
                    except Exception as ex:  # pylint: disable=broad-except   (one pair not read: the others are)
                        log.info("supagent duplicates: %s in %s: %s", a.name, b.name, str(ex)[:200])
                        continue
                    for f in found:
                        if f["lines"] and f["found"] >= FOUND * f["lines"]:
                            ka, kb = a.stats["kind"], b.stats["kind"]
                            mine = f" of \"{ka['service']}\" = {f['service']}" if f["service"] is not None else ""
                            theirs = f" (\"{kb['service']}\" = {f['there']} there)" if f.get("there") else ""
                            said[a.id].append(f"its lines{mine} are also in \"{b.name}\"{theirs}: {f['found']} of "
                                              f"{f['lines']} found there ({f['by']}within {SECONDS} s, the same text)")
                            back = f" of \"{kb['service']}\" = {f['there']}" if f.get("there") else ""
                            said[b.id].append(f"its lines{back} are also in \"{a.name}\""
                                              + (f" (\"{ka['service']}\" = {f['service']} there)" if f["service"] is not None
                                                 else ""))
                            out["same"] += 1
    for ix in tables:
        st = dict(ix.stats or {})
        if said.get(ix.id):
            st["same_events"] = sorted(set(said[ix.id]))
        else:
            st.pop("same_events", None)
        ix.stats = st
    db.session.commit()
    out["seconds"] = round(time.time() - t0, 1)
    return out


def line(same: list[str]) -> str:
    """What the agent is told: the same events shipped twice, never to be added."""
    return ("the same events shipped twice: " + "; ".join(same) + ": count, search and compare them in one table "
            "only, never add the two (a rule of the team may say which)")
