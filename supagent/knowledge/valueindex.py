"""(0.10.2) Where a value of the data is: the labels of the metrics and the fields of the indices that hold it, and the
category values that name it, so that a search for "app-host-07" or "checkout" finds the metrics and the indices that
carry it, with how (the user's request of 7 October 2026: the metrics' and the fields' values linked to the
categories, for the search). A metric's piece lists a label's values only when it has a few (a server among
hundreds was never found by its name).

The values are the ones the learning kept (up to 1,000 per label or field). A label is kept once per metric (thousands
of metrics have the label "instance"): the index holds each value once per label name and source, and the metrics or
indices of each label or field apart, so that its size is the number of distinct (name, value) pairs, not metrics x
values. A word of a question is a value when it is written as one, whatever the case (app-host-07, eu-west-1,
CHECKOUT), or with other separators ("web shop", "web_shop" for the data's "web-shop"): 3 characters at least, not a
number alone, not a word half the data holds (true, error, info: a value of more than COMMON label or field names says
nothing). A question naming a value of the categories (or one of its other names) gets where that value is in the
data, written as the data writes it. Only the databases the user may query; read again when the dictionary changes
(its freshness stamp) or the categories do (the map's stamp).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from superset import db

MIN_CHARS = 3
COMMON = 40             # a value held by more label or field names than this says nothing of where it is
SHOWN = 6               # label or field names said per value
PARENTS = 3             # metrics or indices named per label or field
PIECES = 3              # pieces at most for a question
GRAM = 5                # words of a question read together as one value at most ("pnl eod flash commodities")
WORD = re.compile(r"[A-Za-z0-9](?:[\w.:/@-]*[A-Za-z0-9])?")
_CACHE: dict[str, Any] = {"stamp": None, "values": None, "parents": None, "compact": None}
_NAMES: dict[str, Any] = {"stamp": None, "names": None}

Key = tuple[str, str, int]          # (label | field, its name, source)


def compact(text: str) -> str:
    """Letters and digits only, in lower case: "Web Shop", "web_shop", "web-shop" are one."""
    return re.sub(r"[\W_]+", "", str(text or "").lower())


def _value_like(text: str) -> bool:
    k = compact(text)
    return len(k) >= MIN_CHARS and not k.isdigit()


def _index() -> tuple[dict[str, dict[Key, str]], dict[Key, list[str]]]:
    """(value in lower case -> {(label | field, name, source): the value as the data writes it}, (label | field, name,
    source) -> its metrics or indices); _CACHE["compact"]: compact form -> the lower-case values written so."""
    from supagent.knowledge.freshness import stamp
    from supagent.models import KObject

    now = stamp()
    if _CACHE["values"] is not None and _CACHE["stamp"] == now:
        return _CACHE["values"], _CACHE["parents"]
    import json

    import sqlalchemy as sa

    values: dict[str, dict[Key, str]] = defaultdict(dict)
    parents: dict[Key, list[str]] = defaultdict(list)
    squeezed: dict[str, set[str]] = defaultdict(set)
    read: dict[Key, set[int]] = defaultdict(set)     # the stats a label or field name was read from (their hash)
    rows = db.session.query(KObject.kind, KObject.name, KObject.parent, KObject.source_id,
                            sa.cast(KObject.stats, sa.Text))
    for kind, name, parent, sid, raw in rows.filter(KObject.kind.in_(("label", "field")),
                                                   KObject.gone_at.is_(None)).yield_per(500):
        key = (kind, name, sid)
        parents[key].append(parent)
        mark = hash(raw)
        if not raw or mark in read[key]:             # a label kept once per metric: its values read once
            continue
        read[key].add(mark)
        try:
            stats = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            continue
        for v in (stats or {}).get("values") or [] if isinstance(stats, dict) else []:
            s = str(v).strip()
            if _value_like(s):
                low = s.lower()
                values[low].setdefault(key, s)
                c = compact(s)
                if c != low:
                    squeezed[c].add(low)
    _CACHE.update(stamp=now, values=values, parents=parents, compact=squeezed)
    return values, parents


def _names() -> dict[str, set[int]]:
    """A name of an approved category value (its value, its other names), in lower case and compact -> the values."""
    from sqlalchemy import func

    from supagent.knowledge.index import _map_stamp
    from supagent.models import Facet

    approved = db.session.query(Facet).filter(Facet.status == "approved")
    now = (_map_stamp(), *approved.with_entities(func.count(Facet.id), func.max(Facet.id)).one())
    if _NAMES["names"] is not None and _NAMES["stamp"] == now:
        return _NAMES["names"]
    names: dict[str, set[int]] = defaultdict(set)
    for f in approved:
        for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
            if _value_like(n):
                names[" ".join(n.lower().split())].add(f.id)
                names[compact(n)].add(f.id)
    _NAMES.update(stamp=now, names=names)
    return names


def _held(text: str, values: dict[str, dict[Key, str]]) -> dict[Key, str]:
    """Where a value is held, written as the question writes it or with other separators."""
    out: dict[Key, str] = {}
    for low in [text.lower()] + sorted(_CACHE["compact"].get(compact(text)) or ()):
        for key, written in (values.get(low) or {}).items():
            out.setdefault(key, written)
    return out


def _lines(held: dict[Key, str], parents: dict[Key, list[str]], names: dict[int, str], said: str) -> list[str]:
    lines = []
    for (kind, name, sid), written in sorted(held.items(), key=lambda h: (h[0][0] != "label", h[0][1]))[:SHOWN]:
        of = sorted(set(parents.get((kind, name, sid)) or []))
        what = "metric" if kind == "label" else "index"
        shown = ", ".join(of[:PARENTS]) + (f" and {len(of) - PARENTS} more" if len(of) > PARENTS else "")
        lines.append(f"{'label' if kind == 'label' else 'field'} {name} of {what}{'s' if len(of) > 1 else ''} "
                     f"{shown} ({names.get(sid, sid)})" + (f" written “{written}”" if written != said else ""))
    return lines


def where(query: str, limit: int = PIECES) -> list[dict[str, Any]]:
    """Pieces saying where the values a question names are: a value of the data (the labels and fields that hold it,
    the category values named so), a value of the categories (where it is in the data); the most specific first."""
    from supagent.knowledge.curated import sources_of_user
    from supagent.models import Facet, Source

    words = WORD.findall(query or "")
    if not words:
        return []
    values, parents = _index()
    allowed = {s.id for s in sources_of_user()}
    sources = {s.id: s.database_name or f"database {s.database_id}" for s in db.session.query(Source)}
    # the longest match first: a word inside a value the question names ("amer" in "srv amer 000") is not one alone
    grams = [(i, n, " ".join(words[i:i + n])) for n in range(min(GRAM, len(words)), 0, -1)
             for i in range(len(words) - n + 1)]
    found: list[tuple[int, str, str, dict[Key, str], list[Any]]] = []      # (specific, ref, said, held, categories)
    seen: set[str] = set()
    covered: set[int] = set()
    for i, n, w in grams:
        span = set(range(i, i + n))
        if not _value_like(w) or span & covered or compact(w) in seen:
            continue
        held = _held(w, values)
        mine = {k: v for k, v in held.items() if k[2] in allowed}
        if mine and len({k for k in held}) <= COMMON:
            seen.add(compact(w))
            covered |= span
            found.append((len(mine), f"value:{w.lower()}", w, mine, []))
    by_name = _names()
    named: dict[int, str] = {}
    for i, n, w in grams:
        ids = by_name.get(" ".join(w.lower().split())) or by_name.get(compact(w)) or set()
        if not ids or (set(range(i, i + n)) & covered and compact(w) not in seen):
            continue                     # inside a value of the data the question names: that one is said
        covered |= set(range(i, i + n))
        for fid in sorted(ids):
            named.setdefault(fid, w)
    if named:
        facets = {f.id: f for f in db.session.query(Facet).filter(Facet.id.in_(list(named)))}
        for fid, w in named.items():
            f = facets.get(fid)
            if f is None:
                continue
            same = next((x for x in found if compact(x[2]) in {compact(n) for n in [f.value] + list(f.synonyms or [])}),
                        None)
            if same is not None:                    # the question's word is the data's value: one piece, both said
                same[4].append(f)
                continue
            held: dict[Key, str] = {}
            for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
                if _value_like(n):
                    for k, v in _held(n, values).items():
                        held.setdefault(k, v)
            mine = {k: v for k, v in held.items() if k[2] in allowed}
            if mine and len(held) <= COMMON and compact(f.value) not in seen:
                seen.add(compact(f.value))
                found.append((len(mine), f"facet-data:{f.id}", w, mine, [f]))
    out = []
    for _n, ref, said, held, cats in sorted(found, key=lambda x: x[0])[:limit]:   # the rarest first: the most telling
        lines = _lines(held, parents, sources, said if ref.startswith("value:") else "")
        more = len(held) - SHOWN
        listed = "; ".join(lines) + (f"; and {more} more" if more > 0 else "")
        if ref.startswith("facet-data:"):
            f = cats[0]
            text = (f"Where {f.value} ({f.facet}) is in the data: " + listed + ". Filter on it with that label or field,"
                    " written as there.")
            title = f"Where {f.value} ({f.facet}) is in the data"
        else:
            in_cats = cats + [c for c in db.session.query(Facet).filter(
                Facet.status == "approved", Facet.value.ilike(said)).limit(5) if c not in cats]
            text = (f"{said} is a value of: " + listed + "."
                    + (f" In the categories: {', '.join(f'{c.facet} {c.value}' for c in in_cats)}." if in_cats else "")
                    + " Filter on it with that label or field (its case as written there).")
            title = f"Where the value {said} is"
        out.append({"ref": ref, "kind": "value", "title": title, "text": text, "score": 1.0,
                    "via": "a value of the data"})
    return out


def places(names: list[str]) -> list[dict[str, Any]]:
    """Where any of these names (a category value and its other names) is in the data the user may query: per label
    or field, its metrics or indices and the value as written there (the Categories page, the agent)."""
    from supagent.knowledge.curated import sources_of_user
    from supagent.models import Source

    values, parents = _index()
    allowed = {s.id for s in sources_of_user()}
    sources = {s.id: s.database_name or f"database {s.database_id}" for s in db.session.query(Source)}
    held: dict[Key, str] = {}
    for n in names:
        if _value_like(n):
            for k, v in _held(str(n), values).items():
                held.setdefault(k, v)
    out = []
    for (kind, name, sid), written in sorted(held.items(), key=lambda h: (h[0][0] != "label", h[0][1], h[0][2])):
        if sid not in allowed:
            continue
        of = sorted(set(parents.get((kind, name, sid)) or []))
        out.append({"kind": kind, "name": name, "database": sources.get(sid, sid), "written": written,
                    "of": of[:PARENTS * 4], "count": len(of)})
    return out
