"""Names that are one thing (0.9.5): an inventory of the platform (a CMDB, an asset or service catalog indexed with
the data) that lists each thing with its other names.

The sources of a platform name one service several ways: "orders" for Kubernetes, "shop-orders" for
OpenTelemetry and its traces, "billing-legacy" for the Logstash pipeline of a service called "billing". The
categories read each of them as a value of their own, so the system map, the calls the spans show and the team's
knowledge end up split between them. A table of the dictionary with a name field and a field of other names (aliases,
alias, aka, other_names...) says which names are one thing: the values found among one row's names become one value
(the row's own name when it is a value), its other names its synonyms, with what was filed under them and the
interactions drawn from or to them. When an admin reviews what the learning finds (categories.review_all), the merge
waits in To review as a suggestion ("same as"), one click away; otherwise it is done at once.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from superset import db

log = logging.getLogger(__name__)

NAME_FIELDS = ("name", "asset_name", "ci_name", "service_name", "display_name", "hostname")
ALIAS_FIELDS = ("aliases", "alias", "aka", "also_known_as", "other_names", "synonyms")
ROWS = 5000                     # rows of an inventory read at most
TABLE = re.compile(r"^[\w.\-*?]+$")


def tables() -> list[dict[str, Any]]:
    """The inventories of the dictionary: a table with a name field and a field of other names."""
    from supagent.models import KObject, Source

    sources = {s.id: s for s in db.session.query(Source)}
    fields: dict[tuple[int, str], set[str]] = {}
    for sid, parent, name in db.session.query(KObject.source_id, KObject.parent, KObject.name).filter(
            KObject.kind == "field", KObject.gone_at.is_(None)):
        fields.setdefault((sid, parent), set()).add(name)
    out = []
    for (sid, table), names in fields.items():
        low = {n.lower(): n for n in names}
        name = next((low[n] for n in NAME_FIELDS if n in low), None)
        alias = next((low[n] for n in ALIAS_FIELDS if n in low), None)
        src = sources.get(sid)
        if name and alias and src is not None and src.database_id and TABLE.match(table):
            out.append({"database": src.database_id, "table": table, "name": name, "aliases": alias})
    return out


def _names(value: Any) -> list[str]:
    """A field of other names as the database returns it: a list, a JSON list in a string, or one name."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v not in (None, "")]
    s = str(value).strip()
    if s.startswith("["):
        try:
            return [str(v) for v in json.loads(s) if v not in (None, "")]
        except ValueError:
            pass
    return [s] if s else []


def groups(t: dict[str, Any]) -> list[list[str]]:
    """Each row's names, its own first."""
    from superset.models.core import Database

    from supagent import tools
    from supagent.knowledge import groups as G

    database = db.session.get(Database, t["database"])
    if database is None:
        return []
    out = []
    with tools._db_connection(database, extract=False) as conn:
        cur = conn.cursor()
        cur.execute(f'SELECT "{G.name(t["name"])}", "{G.name(t["aliases"])}" FROM "{t["table"]}" '
                    f'WHERE "{G.name(t["aliases"])}" IS NOT NULL LIMIT {ROWS}')
        for name, aliases in cur.fetchall():
            names = [n for n in dict.fromkeys([str(name or "").strip()] + _names(aliases)) if n]
            if len(names) >= 2:
                out.append(names)
    return out


def _move_links(old: int, new: int) -> int:
    """The interactions drawn from or to value `old` drawn from or to `new` (once each)."""
    from supagent.models import Link

    moved = 0
    for x in db.session.query(Link).filter((Link.a_ref == f"facet:{old}") | (Link.b_ref == f"facet:{old}")):
        a = f"facet:{new}" if x.a_ref == f"facet:{old}" else x.a_ref
        b = f"facet:{new}" if x.b_ref == f"facet:{old}" else x.b_ref
        if a == b or db.session.query(Link.id).filter(Link.a_ref == a, Link.b_ref == b, Link.kind == x.kind).first():
            db.session.delete(x)                      # (the same interaction already drawn on `new`)
            continue
        x.a_ref, x.b_ref = a, b
        moved += 1
    return moved


def run(seconds: float = 60.0) -> dict[str, Any]:
    """The inventories read, the values that name one thing merged (or suggested). Returns counts."""
    from supagent.knowledge.facets import editable
    from supagent.knowledge.stopping import check

    t0 = time.time()
    out: dict[str, Any] = {"tables": 0, "groups": 0, "merged": [], "suggested": []}
    cats = list(editable())
    for t in tables():
        if time.time() - t0 > seconds:
            out["left"] = True
            break
        check()
        try:
            rows = groups(t)
        except Exception as ex:  # pylint: disable=broad-except   (one table not read: the others are)
            db.session.rollback()
            log.info("supagent aliases: %s not read (%s)", t["table"], str(ex)[:200])
            out.setdefault("not_read", []).append(t["table"])
            continue
        out["tables"] += 1
        apply_groups(rows, out, cats)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def apply_groups(rows: list[list[str]], out: dict[str, Any], cats: list[str] | None = None) -> None:
    """Each group of names that are one thing: the approved values of one category found among them made one (the
    group's first name kept when it is a value), or suggested as the same when an admin reviews what the learning
    finds. Counts in out ("groups", "merged", "suggested")."""
    from supagent.knowledge.facets import editable, merge_value, review_all
    from supagent.models import Facet

    cats = list(editable()) if cats is None else cats
    for k in ("groups",):
        out.setdefault(k, 0)
    for k in ("merged", "suggested"):
        out.setdefault(k, [])

    def by_names() -> dict[str, list[Any]]:
        found: dict[str, list[Any]] = {}
        for f in db.session.query(Facet).filter(Facet.status == "approved", Facet.facet.in_(cats)):
            for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
                found.setdefault(" ".join(n.lower().split()), []).append(f)
        return found

    by_name = by_names()
    for names in rows:
        found = []
        for n in names:
            for f in by_name.get(" ".join(n.lower().split()), []):
                if f not in found:
                    found.append(f)
        if len(found) < 2:
            continue
        out["groups"] += 1
        own = " ".join(names[0].lower().split())
        keep = next((f for f in found if f.value.lower() == own), None) or found[0]
        for f in found:
            if f is keep or f.facet != keep.facet:
                continue                          # (a name in two categories is two things: left to an admin)
            if review_all():
                if (f.suggested or {}).get("same_as") != keep.id:
                    f.suggested = {**(f.suggested or {}), "same_as": keep.id}     # one click: merge
                    out["suggested"].append(f"{f.value} = {keep.value}")
                continue
            _move_links(f.id, keep.id)
            merge_value(f, keep)
            out["merged"].append(f"{f.value} -> {keep.value}")
        db.session.commit()
        by_name = by_names()
