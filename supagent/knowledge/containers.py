"""One table for each set of documents (0.9.5).

An OpenSearch database names the same documents in several ways: a family of indices (fluentbit-2026.09.24...,
jaeger-span-000001...: learned as its pattern), an alias on all of them (jaeger-span-read), an alias on one index
(customers on customers_v3), a data stream over its hidden backing indices (ss4o_logs-default-namespace, rolled over
into .ds-ss4o_logs-default-namespace-000002, -000003...), an alias on the newest index only (jaeger-span-write: the
documents since the last rollover). Learned as so many tables, the agent was told the same spans twice (two tables
to add up) and a write alias as if it held the spans of the platform (the last rollover's share of them).

Each name is the set of indices it reads. Names that read the same indices, with as many documents (an alias with a
filter has fewer: it stays a table of its own), are one table: learned once, under the name a Superset dataset uses,
else the name already learned, else the data stream's, the alias's, the pattern's, the index's; the others are kept
with it as its other names. An alias that reads only some indices of a family (the newest: a write alias; the last
weeks: a read alias with a look-back) is not a table of its own either: it is kept with the table of the whole
family as a part (its indices, its documents, since when), so that a count of the history is never made on it. A
data stream is said to be one: its backing indices, the first and the latest, and whether the first generations are
gone (deleted by retention: no data before its first document).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from supagent.knowledge.throttle import SourceStopped

log = logging.getLogger(__name__)

GENERATION = re.compile(r"-(\d{6})$")
PREFER = {"data_stream": 0, "alias": 1, "pattern": 2, "index": 3}


def container_kinds(conn: Any) -> dict[str, str]:
    """{name: index | alias | data_stream} as the connector lists them; {} when it does not say (another transport)."""
    try:
        from osagg.metadata import CACHE

        return {n: k for n, k in CACHE.list_tables(conn.cache_key, conn.transport, getattr(conn, "extra_tables", None)
                                                   or None)}
    except SourceStopped:
        raise
    except Exception as ex:  # pylint: disable=broad-except   (the names alone, as before)
        log.info("supagent learn: the kinds of the tables are not listed (%s)", str(ex)[:200])
        return {}


def _indices_read(conn: Any, name: str, kind: str, families: dict[str, list[str]]) -> frozenset[str] | None:
    if name in families:
        return frozenset(families[name])
    if kind not in ("alias", "data_stream"):
        return frozenset([name])
    try:
        meta = conn.table_meta(name)
    except SourceStopped:
        raise
    except Exception as ex:  # pylint: disable=broad-except   (not known: the name stays a table)
        log.info("supagent learn: the indices of %s: %s", name, str(ex)[:200])
        return None
    return frozenset(meta.indices) if meta is not None and getattr(meta, "indices", None) else None


def one_table_each(conn: Any, objects: dict[str, str], families: dict[str, list[str]], known: set[str],
                   datasets: set[str]) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """(the objects to learn, {table: what it is said to be}): names of the same documents made one table, the
    aliases on a part of a family kept with the family's table, the data streams said. `objects`: name -> the index
    read to learn its fields (group_indices)."""
    from supagent.knowledge.learn_indices import family_of

    listed = container_kinds(conn)
    kind = {o: ("pattern" if o in families else listed.get(o, "index")) for o in objects}
    if not any(k in ("alias", "data_stream") for k in kind.values()):
        return objects, {}
    sets = {o: s for o in objects if (s := _indices_read(conn, o, kind[o], families))}
    said: dict[str, dict[str, Any]] = {}
    counts: dict[str, int | None] = {}

    def docs(name: str) -> int | None:
        if name not in counts:
            try:
                counts[name] = int(conn.transport.count(name, None))
            except SourceStopped:
                raise
            except Exception:  # pylint: disable=broad-except
                counts[name] = None
        return counts[name]

    for o, s in sets.items():
        if kind[o] == "data_stream":
            backing = sorted(s)
            gens = [int(m.group(1)) for m in map(GENERATION.search, backing) if m]
            said.setdefault(o, {})["data_stream"] = {"backing": len(backing), "first": backing[0], "latest": backing[-1],
                                                     **({"gone_before": min(gens)} if gens and min(gens) > 1 else {})}
        elif kind[o] == "alias":
            said.setdefault(o, {})["alias"] = {"indices": len(s), "first": min(s), "latest": max(s)}
    rank = lambda o: (o not in datasets, o not in known, PREFER.get(kind[o], 4), o)  # noqa: E731
    by_set: dict[frozenset[str], list[str]] = {}
    for o, s in sets.items():
        by_set.setdefault(s, []).append(o)
    dropped: set[str] = set()
    for names in by_set.values():
        if len(names) < 2:
            continue
        names.sort(key=rank)
        keep = names[0]
        for other in names[1:]:
            if docs(other) is not None and docs(other) == docs(keep):
                dropped.add(other)
                said.setdefault(keep, {}).setdefault("names", []).append({"name": other, "kind": kind[other]})
    # an alias on some indices of one family: a part of the table that reads the whole family
    whole: dict[frozenset[str], str] = {}
    for s, names in by_set.items():
        for o in sorted(names, key=rank):
            if o not in dropped:
                whole.setdefault(s, o)
    for o in sorted(sets):
        if kind[o] != "alias" or o in dropped:
            continue
        fams = {family_of(i) for i in sets[o]}
        fam = next(iter(fams)) if len(fams) == 1 else None
        if fam not in families:
            continue
        table = whole.get(frozenset(families[fam]))
        if table is None or table == o or not sets[o] < sets[table]:
            continue
        n, total = docs(o), docs(table)
        if n is None or total is None or n >= total:
            continue
        dropped.add(o)
        part = sorted(sets[o])
        newest = part[-1] == max(sets[table])
        said.setdefault(table, {}).setdefault("parts", []).append(
            {"name": o, "indices": part, "of": len(sets[table]), "docs": n, "newest": newest})
    for o in dropped:
        said.pop(o, None)
    return {o: i for o, i in objects.items() if o not in dropped}, said


def lines(st: dict[str, Any], name: str) -> list[str]:
    """What the agent is told of the container of a table: a data stream, an alias on several indices, its other
    names, the aliases on a part of it."""
    q = lambda n: f'"{n}"'  # noqa: E731
    out = []
    ds = st.get("data_stream")
    if ds:
        gone = (f"; its generations before {ds['gone_before']:06d} were deleted (retention): no data before its first "
                f"document") if ds.get("gone_before") else ""
        out.append(f"a data stream: its documents are in {ds['backing']} hidden backing indices, rolled over "
                   f"({ds['first']} .. {ds['latest']}){gone}; query {q(name)}, it reads them all (never a backing index)")
    al = st.get("alias")
    if al and al.get("indices", 0) > 1:
        out.append(f"an alias on {al['indices']} indices ({al['first']} .. {al['latest']}): {q(name)} reads them all")
    names = [n["name"] for n in st.get("names") or []]
    if names:
        out.append(f"the same documents as {', '.join(q(n) for n in names)} (other names of this table: count once, "
                   f"never add them)")
    for p in st.get("parts") or []:
        since = f" from {p['from']}" if p.get("from") else ""
        which = "the newest" if p.get("newest") else "some"
        out.append(f"{q(p['name'])} is an alias on only {len(p['indices'])} of its {p['of']} indices ({which}: "
                   f"{', '.join(p['indices'][-2:])}): {p['docs']:,} documents{since}, not the history: count and "
                   f"compare on {q(name)}")
    return out


def other_names(st: dict[str, Any]) -> set[str]:
    """The names a table is also reached by (its other names, the aliases on a part of it)."""
    return {n["name"] for n in st.get("names") or []} | {p["name"] for p in st.get("parts") or []}
