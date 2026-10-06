"""Names of one service in two sources, told by the pods (or hosts) they run on (0.9.5).

Kubernetes calls a service by its app label (orders), OpenTelemetry by its service.name (shop-orders), Jaeger by
its process name: the same pods (orders-6c9f7b-x2kfp) carry them all. Without an inventory that lists the names of
each thing (aliases.py), the system map kept one value per name, and what was learned or filed under one name was
not found under the other. For each table whose kind gives a service field and a pod (or host) field, the services
of its last full day with their pods; two names whose pods are mostly the same in two tables (shared pods over all
their pods: at least JACCARD) are one service: made one value as an inventory's names are (aliases.apply_groups), or
suggested as the same when an admin reviews what the learning finds. A sidecar or an agent in every pod shares a
little with each service, never most: it is never merged; nor two services of one host (or one pod): only pods or
hosts a service has to itself in its table tell it. No LLM: one query per table.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from superset import db

log = logging.getLogger(__name__)

JACCARD = 0.6
SHARED = 0.2            # a service whose pods or hosts carry other services of its table (this share at least) is
#                         not told by them (several services on one host: never merged)
BROADER = 2            # a service on at least twice the pods of another (a sidecar, an agent) does not make the
#                         other's pods shared
ROWS = 5000


def tables() -> list[tuple[Any, str, str, str]]:
    """(index, its service field, its identity field, "pod" or "host") of the tables whose kind gives both."""
    from supagent.models import KObject

    out = []
    for ix in db.session.query(KObject).filter(KObject.kind == "index", KObject.gone_at.is_(None)):
        kind = (ix.stats or {}).get("kind") or {}
        role = "pod" if kind.get("pod") else "host" if kind.get("host") else None
        if kind.get("service") and role and (ix.stats or {}).get("time_field"):
            out.append((ix, kind["service"], kind[role], role))
    return out


def pods(run_sql: Any, ix: Any, svc: str, ident: str) -> dict[str, set[str]]:
    """The pods (or hosts) of each service of a table over its last full day."""
    from supagent.knowledge.logusual import _day

    span = _day(ix)
    if span is None:
        return {}
    start, end = span
    tf = ix.stats["time_field"]
    rows = run_sql(f'SELECT "{svc}", "{ident}", COUNT(*) FROM "{ix.name}" WHERE "{tf}" >= \'{start:%Y-%m-%d %H:%M:%S}\' '
                   f'AND "{tf}" < \'{end:%Y-%m-%d %H:%M:%S}\' GROUP BY 1, 2 LIMIT {ROWS}')
    out: dict[str, set[str]] = {}
    for s, p, _n in rows:
        if s not in (None, "") and p not in (None, ""):
            out.setdefault(str(s), set()).add(str(p))
    return out


def groups(maps: list[tuple[str, str, dict[str, set[str]]]]) -> list[list[str]]:
    """Names of one service: (table, role, {service: its pods}) of several tables -> groups of names (two at least),
    the name seen in the most tables first."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    seen_in: dict[str, set[str]] = {}
    for table, _role, svcs in maps:
        for s in svcs:
            seen_in.setdefault(s, set()).add(table)

    def own(svcs: dict[str, set[str]], s: str) -> bool:
        """Its pods or hosts are its own in its table: no service of about its size runs on them (two services of
        one host: not); a far broader one (a sidecar or an agent on every pod) does not count against it."""
        mine = svcs[s]
        others = [p for o, p in svcs.items() if o != s and len(p) < BROADER * len(mine)]
        return len(mine & set().union(*others)) < SHARED * len(mine) if others else True
    for i, (ta, _ra, sa) in enumerate(maps):
        for tb, _rb, sb in maps[i + 1:]:
            if ta == tb:                    # (a pod field and a host field compared too: Jaeger's hostname is the pod)
                continue
            for a, pa in sa.items():
                if not own(sa, a):
                    continue
                for b, pb in sb.items():
                    if a.lower() == b.lower() or not own(sb, b):
                        continue
                    if len(pa & pb) / len(pa | pb) >= JACCARD:
                        parent[find(a)] = find(b)
    out: dict[str, list[str]] = {}
    for name in list(parent):
        out.setdefault(find(name), []).append(name)
    return [sorted(g, key=lambda n: (-len(seen_in.get(n, ())), n)) for g in out.values()
            if len({n.lower() for n in g}) >= 2]


def run(seconds: float = 60.0) -> dict[str, Any]:
    """The services of every table that has pods (or hosts), the names that share them made one. Returns counts."""
    from superset.models.core import Database

    from supagent import tools
    from supagent.knowledge.aliases import apply_groups
    from supagent.knowledge.stopping import check
    from supagent.models import Source

    t0 = time.time()
    out: dict[str, Any] = {"tables": 0, "groups": 0, "merged": [], "suggested": []}
    maps: list[tuple[str, str, dict[str, set[str]]]] = []
    by_db: dict[int, list[tuple[Any, str, str, str]]] = {}
    for t in tables():
        src = db.session.get(Source, t[0].source_id)
        if src is not None and src.database_id:
            by_db.setdefault(src.database_id, []).append(t)
    for database_id, group in by_db.items():
        with tools._db_connection(db.session.get(Database, database_id), extract=False) as conn:
            cur = conn.cursor()

            def run_sql(sql: str) -> list:
                cur.execute(sql)
                return cur.fetchall()

            for ix, svc, ident, role in group:
                if time.time() - t0 > seconds:
                    out["left"] = True
                    break
                check()
                try:
                    found = pods(run_sql, ix, svc, ident)
                except Exception as ex:  # pylint: disable=broad-except   (one table not read: the others are)
                    log.info("supagent podnames: %s not read (%s)", ix.name, str(ex)[:200])
                    continue
                out["tables"] += 1
                if found:
                    maps.append((f"{database_id}:{ix.name}", role, found))
    rows = groups(maps)
    out["names"] = [" = ".join(g) for g in rows]
    apply_groups(rows, out)
    out["seconds"] = round(time.time() - t0, 1)
    return out
