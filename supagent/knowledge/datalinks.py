"""Links between the parts of the system read from the data (0.9.6, the user's request).

A metric's series carries the labels of several categories at once: the server (instance, node, host) with the
component or the service that runs on it, a tenant (an application or a subject) with its servers; an index's
documents carry fields of several categories (APPLICATION with NODE). Two values seen together are linked, the kind
said by what their categories are:
  - a component, a service, a process... with a server, a host, a node, a pod: it runs on it (runs_on);
  - a disk, a volume, a filesystem... with a server: it is part of it;
  - a server with an application, a subject, a tenant: it is part of it;
  - two other categories: the narrower is part of the wider (subject, application, component, then one's own).
What a metric's labels show is a fact of the data: linked at once (categories.label_links, on), with where it was
seen; what an index's documents show waits for an admin in To review, as before. A link read from the data that the
data has not shown for categories.data_link_days days is proposed for removal (never removed alone).

A category whose values only mean something with the part they belong to (categories.qualified: {"disk": "server"},
every server has its sda1) has its values named after it ("srv-1 /dev/sda1"), made here from the pairs, part of it.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Any

from superset import db

log = logging.getLogger(__name__)

SERVERISH = re.compile(r"server|host|node|machine|instance|\bvm|pod|container", re.I)
DISKISH = re.compile(r"disk|volume|filesystem|mount|storage|partition", re.I)
RUNNING = re.compile(r"component|service|process|daemon|job|module|exporter|agent|database", re.I)
OWNING = re.compile(r"application|subject|tenant|system|platform|business|team", re.I)
PAIR_LABELS = 6          # pairs of category labels read per metric
PAIR_VALUES = 5000       # value pairs kept per pair of labels


def kind_of(cat_a: str, cat_b: str) -> tuple[str, str, str]:
    """(kind, the category the link goes from, the one it goes to) for two categories seen together."""
    from supagent.knowledge.facets import PART_OF, rank

    for x, y in ((cat_a, cat_b), (cat_b, cat_a)):
        if SERVERISH.search(y) and not SERVERISH.search(x):
            if DISKISH.search(x):
                return PART_OF, x, y                       # a disk of a server
            if OWNING.search(x):
                return PART_OF, y, x                       # a server of an application
            return "runs_on", x, y                         # a component on a server
    wide, narrow = (cat_a, cat_b) if rank(cat_a) <= rank(cat_b) else (cat_b, cat_a)
    return PART_OF, narrow, wide


def label_pairs(series: list[Any]) -> list[dict[str, Any]]:
    """The value pairs of two category labels seen in the same series ({"parent": [category, label], "child":
    [category, label], "pairs": [[value, value, series]]}, as an index's category_pairs; the wider first)."""
    from supagent.knowledge.facets import field_matches, field_rules, rank

    rules = field_rules()
    if not rules or not series:
        return []
    labels: dict[str, str] = {}
    for s in series:
        for k in (s if isinstance(s, dict) else getattr(s, "labels", {}) or {}):
            if k != "__name__" and k not in labels:
                cat = next((c for c, rx in rules if field_matches(rx, k)), None)
                if cat is not None:
                    labels[k] = cat
    names = sorted(labels)
    out: list[dict[str, Any]] = []
    for i, la in enumerate(names):
        for lb in names[i + 1:]:
            if labels[la] == labels[lb] or len(out) >= PAIR_LABELS:
                continue
            (pc, pl), (cc, cl) = sorted([(labels[la], la), (labels[lb], lb)], key=lambda x: rank(x[0]))
            counts: dict[tuple[str, str], int] = {}
            for s in series:
                lab = s if isinstance(s, dict) else getattr(s, "labels", {}) or {}
                pv, cv = lab.get(pl), lab.get(cl)
                if pv not in (None, "") and cv not in (None, ""):
                    counts[(str(pv), str(cv))] = counts.get((str(pv), str(cv)), 0) + 1
            if counts:
                rows = sorted(([p, c, n] for (p, c), n in counts.items()), key=lambda r: -r[2])[:PAIR_VALUES]
                out.append({"parent": [pc, pl], "child": [cc, cl], "pairs": rows})
    return out


def qualified() -> dict[str, str]:
    """categories.qualified: {category: the category of the part its values belong to} (known categories only)."""
    from supagent import settings
    from supagent.knowledge.facets import editable

    raw = settings.get("categories.qualified")
    cats = set(editable())
    return {str(k).strip().lower(): str(v).strip().lower() for k, v in (raw if isinstance(raw, dict) else {}).items()
            if str(k).strip().lower() in cats and str(v).strip().lower() in cats and str(k).strip().lower() != str(v).strip().lower()}


def apply(auto_metrics: bool | None = None) -> dict[str, int]:
    """The links the data shows (see the module): indices' pairs proposed, metrics' pairs linked at once (or
    proposed, categories.label_links off), seen again: their date; not seen for long: their removal proposed."""
    from supagent import settings
    from supagent.knowledge.facets import PART_OF, editable, suggest_link
    from supagent.models import Facet, KObject, Link

    least = int(settings.get("categories.relation_min_docs") or 5)
    auto = settings.get("categories.label_links") if auto_metrics is None else auto_metrics
    now = dt.datetime.utcnow()
    values: dict[tuple[str, str], Any] = {}
    for f in db.session.query(Facet).filter(Facet.status != "rejected", Facet.facet.in_(list(editable()))):
        values.setdefault((f.facet, f.value.lower()), f)
    out = {"proposed": 0, "linked": 0, "seen": 0, "stale": 0, "qualified_values": 0}
    named_after = qualified()
    from supagent.knowledge.facets import _ensure, review_all

    found = "proposed" if review_all() else "approved"
    links = {(x.a_ref, x.b_ref, x.kind): x for x in db.session.query(Link).filter(
        Link.a_ref.like("facet:%"), Link.b_ref.like("facet:%"))}
    for obj in db.session.query(KObject).filter(KObject.kind.in_(("index", "metric")), KObject.gone_at.is_(None)):
        metric = obj.kind == "metric"
        for grp in (obj.stats or {}).get("category_pairs") or []:
            (pcat, pfield), (ccat, cfield) = grp.get("parent") or ("", ""), grp.get("child") or ("", "")
            kind0, from_cat, _to_cat = kind_of(pcat, ccat)
            try:                                           # when the data was read (not when this runs)
                at = dt.datetime.fromisoformat(str(grp["at"])[:19])
            except (KeyError, ValueError, TypeError):
                at = obj.last_seen or now
            for pv, cv, n in (grp.get("pairs") or [])[:PAIR_VALUES]:
                if not metric and n < least:
                    continue
                kind_here, from_here = kind0, from_cat
                if named_after.get(ccat) == pcat or named_after.get(pcat) == ccat:   # a disk of a server: its own
                    (ocat, ov), (qcat, qv) = ((pcat, pv), (ccat, cv)) if named_after.get(ccat) == pcat else ((ccat, cv), (pcat, pv))
                    owner = values.get((ocat, str(ov).lower()))
                    if owner is None:
                        continue
                    name = f"{owner.value} {qv}"[:128]
                    q = values.get((qcat, name.lower()))
                    if q is None:
                        q = _ensure(qcat, name, found, "data", origin=f"{'label' if metric else 'field'} {cfield if qcat == ccat else pfield} "
                                                                       f"of {obj.name}, with {ov}")
                        if q is None:
                            continue
                        values[(qcat, name.lower())] = q
                        out["qualified_values"] += 1
                    parent, child = (owner, q) if ocat == pcat else (q, owner)
                    kind_here, from_here = PART_OF, qcat
                else:
                    parent, child = values.get((pcat, str(pv).lower())), values.get((ccat, str(cv).lower()))
                if parent is None or child is None or parent.id == child.id:
                    continue
                kind = kind_here
                a, b = (child, parent) if from_here == ccat else (parent, child)
                seen = (f"{obj.name}: {pfield} {pv} with {cfield} {cv} in {n} "
                        + ("series" if metric else "documents"))
                x = links.get((f"facet:{a.id}", f"facet:{b.id}", kind))
                if x is not None:
                    if x.source == "data":
                        x.seen_at = max(x.seen_at or at, at)    # shown again: not stale
                        if x.proposed_drop and x.proposed_drop.startswith("not seen in the data"):
                            x.proposed_drop, x.proposed_drop_at = None, None
                        out["seen"] += 1
                    continue
                if metric and auto:
                    x = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind=kind, status="approved",
                             source="data", confidence=1.0, evidence=seen[:2000], seen_at=at)
                    db.session.add(x)
                    links[(x.a_ref, x.b_ref, kind)] = x
                    out["linked"] += 1
                elif suggest_link(a.id, b.id, kind, "data", seen):
                    x = db.session.query(Link).filter(Link.a_ref == f"facet:{a.id}", Link.b_ref == f"facet:{b.id}",
                                                      Link.kind == kind).first()
                    if x is not None:
                        x.seen_at = at
                        links[(x.a_ref, x.b_ref, kind)] = x
                    out["proposed"] += 1
    days = max(14, int(settings.get("categories.data_link_days") or 21))
    old = now - dt.timedelta(days=days)
    for x in links.values():
        if (x.source == "data" and x.status == "approved" and x.seen_at is not None and x.seen_at < old
                and not x.proposed_drop):
            x.proposed_drop = (f"not seen in the data since {x.seen_at:%Y-%m-%d} (it was read from: "
                               f"{(x.evidence or '?')[:300]})")
            x.proposed_drop_at = now
            out["stale"] += 1
    db.session.flush()
    return out
