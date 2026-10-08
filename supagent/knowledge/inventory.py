"""What an inventory says the parts stand on (0.9.5): a walk down a CMDB's relations, read when asked.

An inventory of the platform (a CMDB, an asset or service catalog indexed with the data: a name field and a field of
other names, aliases.tables) also says what each thing runs on and depends on: a service runs_on its nodes, a node
sits in a rack and is connected_to a switch port ("switch-1:ge-1/0/7"), a service depends_on its database. The
agent, asked what failing calls have in common or why two services fail together, stayed at the services the spans
name: the rack, the switch port and the change on the switch (the cause) were three joins away in a table it had no
reason to read. This reads the inventories (a few thousand rows at most, cached for a minute) and, for the names
given, says each one's row (its type and facts: rack, team, tier...), what its relation fields name, down to two
steps (with the port of a host:port value), what names it (runs on it, depends on it), and what the names have in
common below them (the node, the rack, the switch port two failing services share). A field is a relation when most
of its values are names of the inventory's rows. No LLM, no learning: the inventory as it is now.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from superset import db

log = logging.getLogger(__name__)

ROWS = 5000
FIELDS = 40              # fields of an inventory read at most
DEPTH = 2
TTL = 60.0
RUNS = re.compile(r"run|host|node|server|vm\b|deploy|instance|machine", re.I)
CONNECT = re.compile(r"connect|uplink|link|switch|port|network|attach", re.I)
DEPENDS = re.compile(r"depend|use|require|need|upstream|backend|call|consume|read", re.I)
SKIP = re.compile(r"^(@?timestamp|updated|created|modified|_id|id|asset_id|ci_id)$", re.I)
_CACHE: dict[str, tuple[float, Any]] = {}


def _values(value: Any) -> list[str]:
    from supagent.knowledge.aliases import _names

    return [v for v in _names(value) if v]


def _target(value: str, index: dict[str, dict[str, Any]]) -> tuple[str, str] | None:
    """A value naming a row: the row's own name, and the rest of a host:port value (the port)."""
    v = value.strip()
    row = index.get(v.lower())
    if row is not None:
        return row["name"], ""
    if ":" in v:
        head, rest = v.split(":", 1)
        row = index.get(head.strip().lower())
        if row is not None:
            return row["name"], rest.strip()
    return None


def load() -> dict[str, Any]:
    """{"rows": {name: row}, "index": {name or alias (lower): row}, "relations": {field: kind}} of every inventory,
    each row {"name", "table", "facts": {field: value}, "rel": [(kind, field, target, detail)]}."""
    hit = _CACHE.get("inv")
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    from superset.models.core import Database

    from supagent import tools
    from supagent.knowledge import groups as G
    from supagent.knowledge.aliases import tables
    from supagent.models import KObject, Source

    rows: list[dict[str, Any]] = []
    for t in tables():
        src = db.session.query(Source).filter_by(database_id=t["database"]).first()
        names = [f for (f,) in db.session.query(KObject.name).filter(
            KObject.kind == "field", KObject.parent == t["table"], KObject.gone_at.is_(None),
            KObject.source_id == (src.id if src else -1))]
        fields = [t["name"], t["aliases"]] + sorted(f for f in names if f not in (t["name"], t["aliases"])
                                                    and not SKIP.match(f) and G.FIELD.match(f))[:FIELDS]
        database = db.session.get(Database, t["database"])
        if database is None:
            continue
        try:
            with tools._db_connection(database, extract=False) as conn:
                cur = conn.cursor()
                cur.execute(f'SELECT {", ".join(chr(34) + G.name(f) + chr(34) for f in fields)} FROM '
                            f'"{G.table(t["table"])}" LIMIT {ROWS}')
                got = cur.fetchall()
        except Exception as ex:  # pylint: disable=broad-except   (an inventory this user may not read: left out)
            db.session.rollback()
            log.info("supagent inventory: %s not read (%s)", t["table"], str(ex)[:200])
            continue
        for r in got:
            name = str(r[0] or "").strip()
            if name:
                rows.append({"name": name, "table": t["table"], "aliases": _values(r[1]),
                             "raw": dict(zip(fields[2:], r[2:]))})
    out = build(rows)
    _CACHE["inv"] = (time.time(), out)
    return out


def build(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The inventory from its rows ({"name", "table", "aliases", "raw": {field: value}}): the index of names and
    aliases, the relation fields and their kinds, each row's facts and relations."""
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        for n in [row["name"]] + row["aliases"]:
            index.setdefault(n.lower(), row)
    # a relation field: most of its values name a row (host:port values by their host)
    counts: dict[str, list[int]] = {}
    for row in rows:
        for f, v in row["raw"].items():
            vals = _values(v) if not isinstance(v, (int, float)) else []
            if vals:
                c = counts.setdefault(f, [0, 0])
                c[0] += sum(1 for x in vals if _target(x, index))
                c[1] += len(vals)
    relations = {}
    for f, (named, total) in counts.items():
        if total and named >= 0.5 * total:
            relations[f] = ("connected_to" if CONNECT.search(f) else "runs_on" if RUNS.search(f) else
                            "depends_on" if DEPENDS.search(f) else "relates_to")
    for row in rows:
        row["facts"], row["rel"] = {}, []
        for f, v in row["raw"].items():
            if f in relations:
                for x in _values(v):
                    tgt = _target(x, index)
                    if tgt and tgt[0] != row["name"]:
                        row["rel"].append((relations[f], f, tgt[0], tgt[1]))
            elif v not in (None, "", "[]", "{}") and not isinstance(v, (dict, list)) and len(str(v)) <= 60:
                row["facts"][f] = str(v)
    return {"rows": {r["name"]: r for r in rows}, "index": index, "relations": relations}


PLACE = re.compile(r"type|kind|class|rack|zone|site|region|dc|datacenter|location|room|engine|version|os", re.I)


def _said(row: dict[str, Any]) -> str:
    """A row with its few telling facts: its type and where it is first (rack, zone, site...), then the others."""
    facts = sorted(row["facts"].items(), key=lambda kv: (not PLACE.search(kv[0]), kv[0]))[:4]
    said = ", ".join(f"{k} {v}" for k, v in facts)
    return f"{row['name']}" + (f" ({said})" if said else "")


def walk(names: list[str], depth: int = DEPTH) -> dict[str, Any] | None:
    """What the inventories say of these names and of what they stand on (None: no inventory, or none of them in
    it): per name, its row, what its relations name down to `depth` steps, what names it; then what they share."""
    inv = load()
    if not inv["rows"]:
        return None
    index, rows = inv["index"], inv["rows"]
    out: dict[str, Any] = {"parts": {}, "not_in_the_inventory": []}
    below: dict[str, set[str]] = {}
    for n in names:
        row = index.get(str(n).strip().lower())
        if row is None:
            out["not_in_the_inventory"].append(n)
            continue
        lines, seen = [], {row["name"]}
        reach: set[str] = set()
        frontier = [(row, 0)]
        while frontier:
            cur, d = frontier.pop(0)
            for kind, field, tgt, detail in cur["rel"]:
                t = rows.get(tgt)
                if t is None:
                    continue
                port = f" port {detail}" if detail else ""
                lines.append(f"{cur['name']} {kind.replace('_', ' ')} {_said(t)}{port} ({field})")
                reach.add(t["name"] + (f" port {detail}" if detail else ""))
                reach.add(t["name"])
                if t["name"] not in seen and d + 1 < depth:
                    seen.add(t["name"])
                    frontier.append((t, d + 1))
        named_by = [f"{r['name']} {k.replace('_', ' ')} it ({f})" for r in rows.values() for k, f, tgt, _d in r["rel"]
                    if tgt == row["name"]]
        out["parts"][row["name"]] = {"is": _said(row), "stands_on": lines[:20], "named_by": named_by[:20],
                                     "from": row["table"]}
        below[row["name"]] = reach
    if len(below) >= 2:
        common = set.intersection(*below.values())
        if common:
            out["in_common_below"] = sorted(common)
    if not out["parts"]:
        return None
    if not out["not_in_the_inventory"]:
        out.pop("not_in_the_inventory")
    out["note"] = ("from the inventory as it is now (what each part runs on, is connected to, depends on, down to "
                   f"{depth} steps): a cause below the services (a node, a rack, a switch port) shows here; check its "
                   "records (records_about) and its own data")
    return out


def below(names: list[str], depth: int = DEPTH) -> list[str]:
    """The inventory's parts these names stand on (their nodes, the devices those connect to), for records_about."""
    w = walk(names, depth) or {}
    out: list[str] = []
    for p in (w.get("parts") or {}).values():
        for line in p.get("stands_on") or []:
            m = re.search(r" (?:runs on|connected to|depends on|relates to) (\S+)", line)
            if m and m.group(1) not in out and m.group(1) not in names:
                out.append(m.group(1))
    return out
