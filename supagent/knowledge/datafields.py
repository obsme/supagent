"""(0.10.2) Where a category is in the data, proposed from the values (the user's request of 7 October 2026: every
metric and field linked to the categories they hold). A category is read from the fields and labels that
categories.fields names (application: application, app, service...); a deployment whose services are in a label
"svc", "job" or "k8s_app" had its applications known by name only, the metrics and indices holding them unknown to
the agent, the services nobody wrote about never proposed. Here a label or a field holding several values of a
category (MIN_VALUES, and SHARE of the category's values), a good part of its own values being the category's
(OWN_SHARE, or TEN of them), not read for it yet, is proposed in To review: "label svc holds 14 of the 20
applications and 36 other values: read the applications from it?". Approved, categories.fields reads it (the agent
then knows where the category is in the data, and the next learning proposes its other values as values of the
category, to approve as any other); set aside, it is not proposed again.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from typing import Any

from superset import db

MIN_VALUES = 3          # values of the category a label or field holds, at least
SHARE = 0.2             # ... and this share of the category's values
OWN_SHARE = 0.1         # its own values that are the category's: this share at least, or TEN of them
TEN = 10
SAMPLE = 6              # values said in a proposal
DISMISSED = "fields_dismissed"      # supagent_meta: the proposals set aside ("category:name")


def dismissed() -> set[str]:
    from supagent.models import Meta

    row = db.session.get(Meta, DISMISSED)
    try:
        return set(json.loads(row.value)) if row is not None and row.value else set()
    except ValueError:
        return set()


def _names(f: Any) -> list[str]:
    return [f.value] + [str(x) for x in (f.synonyms or [])]


def proposals() -> list[dict[str, Any]]:
    """The labels and fields to read a category from, with what they hold (the user's databases only)."""
    from supagent.knowledge.curated import sources_of_user
    from supagent.knowledge.facets import MAX_DATA_VALUES, field_matches, field_rules
    from supagent.knowledge.valueindex import _held, _index, _value_like, compact
    from supagent.models import Facet, KObject, Source

    values, parents = _index()
    allowed = {s.id for s in sources_of_user()}
    sources = {s.id: s.database_name or f"database {s.database_id}" for s in db.session.query(Source)}
    rules = field_rules()
    gone = dismissed()
    by_cat: dict[str, list[Any]] = defaultdict(list)
    for f in db.session.query(Facet).filter(Facet.status == "approved"):
        by_cat[f.facet].append(f)
    out = []
    for cat, fs in sorted(by_cat.items()):
        if len(fs) < MIN_VALUES:
            continue
        need = max(MIN_VALUES, math.ceil(SHARE * len(fs)))
        # a label or field name, whatever its case (the patterns of categories.fields ignore it) -> the values it holds
        hits: dict[str, set[int]] = defaultdict(set)
        where: dict[str, set[tuple[str, int, str]]] = defaultdict(set)
        for f in fs:
            for n in _names(f):
                if _value_like(n):
                    for kind, name, sid in _held(n, values):
                        if sid in allowed:
                            hits[name.lower()].add(f.id)
                            where[name.lower()].add((kind, sid, name))
        known = {compact(n) for f in fs for n in _names(f)}
        for low, ids in sorted(hits.items()):
            name = sorted(x[2] for x in where[low])[0]
            if len(ids) < need or f"{cat}:{low}" in gone:
                continue
            if any(c == cat and field_matches(rx, x[2]) for c, rx in rules for x in where[low]):
                continue                                          # read for it already
            own: set[str] = set()
            for kind, sid, exact in where[low]:
                for (stats,) in db.session.query(KObject.stats).filter(
                        KObject.kind == kind, KObject.name == exact, KObject.source_id == sid,
                        KObject.gone_at.is_(None)).limit(200):
                    own.update(str(v).strip() for v in (stats or {}).get("values") or [] if str(v).strip())
            if cat == "application" and len(own) > MAX_DATA_VALUES:
                continue                                          # (the learning reads no such field for it)
            held = len(ids)
            if own and held < TEN and held < OWN_SHARE * len(own):
                continue                                          # a few of its many values: not the category's
            others = sorted(v for v in own if compact(v) not in known)
            places = []
            for kind, sid, exact in sorted(where[low]):
                of = sorted(set(parents.get((kind, exact, sid)) or []))
                places.append(f"{'label' if kind == 'label' else 'field'} {exact} of {len(of)} "
                              f"{('metric' if kind == 'label' else 'index') if len(of) == 1 else ('metrics' if kind == 'label' else 'indices')}"
                              f" such as {', '.join(of[:3])} ({sources.get(sid, sid)})")
            said = sorted(f.value for f in fs if f.id in ids)
            out.append({"category": cat, "name": name, "held": held, "of": len(fs), "others": len(others),
                        "where": places, "values": said[:SAMPLE], "other_values": others[:SAMPLE],
                        "subject": f"{cat} ← {name}",
                        "why": f"{'; '.join(places)} hold{'s' if len(places) == 1 else ''} {held} of the {len(fs)} "
                               f"values of {cat} ({', '.join(said[:SAMPLE])}{', …' if held > SAMPLE else ''})"
                               + (f" and {len(others)} other value{'s' if len(others) > 1 else ''} "
                                  f"({', '.join(others[:SAMPLE])}{', …' if len(others) > SAMPLE else ''})"
                                  if others else ""),
                        "fix": f"Read {cat} from {name}: the agent then knows where {cat} is in the data"
                               + (f", and the next learning proposes its {len(others)} other value"
                                  f"{'s' if len(others) > 1 else ''} as values of {cat}, to approve here" if others else "")})
    return sorted(out, key=lambda p: (-p["held"], p["category"], p["name"]))


def decide(category: str, name: str, read: bool, by: str) -> dict[str, Any]:
    """Read the category from that label or field (categories.fields), or set the proposal aside."""
    from supagent import settings
    from supagent.models import Meta

    category, name = " ".join(str(category).lower().split()), str(name).strip()
    if not category or not name:
        raise ValueError("category and name")
    if read:
        fields = settings.get("categories.fields")
        fields = dict(fields) if isinstance(fields, dict) else {}
        add = f"^{re.escape(name)}$"
        old = str(fields.get(category) or "").strip()
        fields[category] = f"(?:{old})|{add}" if old else add
        re.compile(fields[category])
        settings.set_value("categories.fields", fields, by=by)
        return {"category": category, "name": name, "read": True, "pattern": fields[category]}
    keys = sorted(dismissed() | {f"{category}:{name.lower()}"})[-5000:]
    row = db.session.get(Meta, DISMISSED)
    if row is None:
        db.session.add(Meta(key=DISMISSED, value=json.dumps(keys)))
    else:
        row.value = json.dumps(keys)
    db.session.commit()
    return {"category": category, "name": name, "read": False}
