"""What the documents and the code state, proposed for the categories and the System map (0.10, the user's request
of 6 October 2026: the wiki, the repositories' code and files, the catalog understood, their parts, links and
categories proposed, compared with what exists, each with approval).

From the understanding (knowledge.understand: who calls whom, what reads or writes what, what runs where, which
indices and metrics are whose):
  values  the parts they name that are no value yet, in the category their kind says: a service an application; a
          database, a cache or a tool a component; a host the deployment's server category (none: not proposed);
          their other names (a repository's, a telemetry name) as synonyms
  links   between values: calls, sends data to, reads from, depends on, runs on, monitors; a server part of its
          group (an inventory's host in its group: the servers grouped as the inventory groups them)
  items   a part's indices and metrics (what it logs to, emits, writes, is watched by) given to it
Each waits in To review with where it was read (the line of a file, the sentence of a page, the arrow of a
diagram). Compared with what exists:
  - stated again: confirmed (where it was read is kept with it), nothing proposed
  - a learned link the other way round (the code says a calls b, a link says b calls a): its removal proposed
  - what the documents proposed before and no longer state: a proposal withdrawn; an approved link, its removal
    proposed (never removed alone)
A value, a link or an item a person refused is never proposed again; nothing a person made is changed.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from superset import db

log = logging.getLogger(__name__)

SOURCE = "docs"
STATE_KEY = "proposals_state"   # how many facts the last reading gave (supagent_meta)
SHRUNK = 0.5                    # fewer than half of them now (a document not fetched a moment): nothing withdrawn
LINK_OF = {"calls": "calls", "sends_to": "sends_to", "reads_from": "reads_from", "uses": "depends_on",
           "runs_on": "runs_on", "monitors": "monitors", "in_group": "part_of"}
FLOWS = ("calls", "sends_to", "reads_from", "depends_on")
CONFIDENCE = {"code": 0.95, "config": 0.9, "inferred": 0.8, "diagram": 0.8, "doc": 0.7, "wiki": 0.7, "llm": 0.6}
# a part that is a store or a tool of the platform, by its name: a component rather than an application
TECHNICAL = re.compile(r"(^|[\W_])(db|database|postgres(ql)?|pg|mysql|mariadb|oracle|mongo(db)?|redis|memcached|cache|"
                       r"kafka|rabbit(mq)?|queue|topic|broker|zookeeper|etcd|s3|bucket|minio|elastic(search)?|"
                       r"opensearch|loki|prometheus|mimir|grafana|alertmanager|fluent-?bit|fluentd|logstash|filebeat|"
                       r"vector|otel|collector|jaeger|tempo|nginx|haproxy|envoy|ingress|exporter)($|[\W_])", re.I)


def _norm(name: str) -> str:
    return " ".join(str(name or "").lower().replace("_", "-").split())


def _category(kind: str, name: str) -> str | None:
    """The category a new part is proposed in (see the module); None: not proposed."""
    from supagent.knowledge.datalinks import SERVERISH
    from supagent.knowledge.facets import editable

    cats = list(editable())
    if kind == "host":
        return next((c for c in cats if SERVERISH.search(c)), None)
    if kind in ("database", "cache") or TECHNICAL.search(name):
        return "component" if "component" in cats else None
    return "application" if "application" in cats else None


def _evidence(r: dict[str, Any]) -> str:
    where = r.get("where") or ""
    return (f'{r.get("quote") or ""} ({where}{"; " if where else ""}{", ".join(r.get("sources") or [])})')[:2000]


def _confidence(r: dict[str, Any]) -> float:
    return max([CONFIDENCE.get(s, 0.6) for s in r.get("sources") or []] or [0.6])


def propose(dry_run: bool = False) -> dict[str, Any]:
    """The proposals made again from what the documents and the code state now (see the module). Counts."""
    from supagent.knowledge.facets import editable, suggest_link
    from supagent.knowledge.understand import export
    from supagent.models import Facet, KObject, Link, Tag

    g = export()
    out = {"values": 0, "links": 0, "confirmed": 0, "removals": 0, "withdrawn": 0, "items": 0, "not placed": 0}
    import json as _json

    from supagent.models import Meta

    now = len(g.get("relations") or []) + len(g.get("data_links") or [])
    row = db.session.get(Meta, STATE_KEY)
    try:
        before = int((_json.loads(row.value) if row is not None and row.value else {}).get("facts") or 0)
    except (ValueError, TypeError, AttributeError):
        before = 0
    shrunk = before >= 10 and now < before * SHRUNK      # what the documents state did not vanish at once: wait
    if shrunk:
        out["kept: fewer facts read than before"] = f"{now} of {before}"
    cats = set(editable())
    values: dict[str, Facet] = {}
    for f in db.session.query(Facet).filter(Facet.facet.in_(list(cats))):
        for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
            key = _norm(n)
            if key and (key not in values or values[key].status == "rejected"):
                values[key] = f
    aliases: dict[str, set[str]] = {}
    for a in g.get("aliases") or []:
        aliases.setdefault(_norm(a["part"]), set()).add(a["name"])
    # an inventory's group named like a part (a group "web" and an application "web"): two values, the group's
    # "web (group)"
    rels = g.get("relations") or []
    groups = {_norm(r["to"]) for r in rels if r["kind"] == "in_group" or
              (r["kind"] == "runs_on" and r.get("obj_kind") == "group")}
    partish = {_norm(r["from"]) for r in rels if r["kind"] not in ("in_group", "alias")} | \
        {_norm(r["to"]) for r in rels if r["kind"] in LINK_OF and r["kind"] not in ("in_group", "runs_on")}
    clash = groups & partish

    def as_group(name: str) -> str:
        return f"{name} (group)" if _norm(name) in clash else name

    def ends(r: dict[str, Any]) -> tuple[str, str]:
        if r["kind"] == "in_group":
            return (as_group(r["from"]) if _norm(r["from"]) in groups else r["from"]), as_group(r["to"])
        if r["kind"] == "runs_on" and r.get("obj_kind") == "group":
            return r["from"], as_group(r["to"])
        return r["from"], r["to"]

    kind_of: dict[str, str] = {}                          # what each part is, as the facts name it
    for r in rels:
        a, b = ends(r)
        if r["kind"] == "in_group":                       # an inventory's host in its group: both servers
            kind_of[_norm(a)] = kind_of[_norm(b)] = "host"
            continue
        kind_of.setdefault(_norm(a), "part")
        if r["kind"] in LINK_OF:
            k = "host" if r["kind"] == "runs_on" or r.get("obj_kind") == "group" else str(r.get("obj_kind") or "part")
            kind_of[_norm(b)] = k if kind_of.get(_norm(b)) in (None, "part") else kind_of[_norm(b)]
    for d in g.get("data_links") or []:
        kind_of.setdefault(_norm(d["part"]), "part")

    def value_of(name: str) -> Facet | None:
        key = _norm(name)
        f = values.get(key)
        if f is not None:
            return None if f.status == "rejected" else f
        cat = _category(kind_of.get(key, "part"), name)
        if cat is None:
            out["not placed"] += 1
            return None
        f = Facet(facet=cat, value=" ".join(str(name).split())[:128], status="proposed", source=SOURCE,
                  synonyms=sorted(a for a in aliases.get(key, ()) if _norm(a) != key) or None,
                  origins=["read in the documents and the code"])
        if not dry_run:
            db.session.add(f)
            db.session.flush()
        values[key] = f
        out["values"] += 1
        return f

    stated: set[tuple[int, int, str]] = set()
    for r in rels:
        kind = LINK_OF.get(r["kind"])
        if kind is None:
            continue
        a, b = (value_of(x) for x in ends(r))
        if a is None or b is None or a.id == b.id or dry_run:
            continue
        stated.add((a.id, b.id, kind))
        same = (db.session.query(Link).filter(Link.a_ref == f"facet:{a.id}", Link.b_ref == f"facet:{b.id}",
                                              Link.kind == kind).first())
        if same is not None:
            if same.status != "rejected":
                out["confirmed"] += 1
                if not same.evidence:
                    same.evidence = _evidence(r)
            continue
        if kind in FLOWS:                                  # a learned link the other way round: its removal proposed
            back = (db.session.query(Link).filter(Link.a_ref == f"facet:{b.id}", Link.b_ref == f"facet:{a.id}",
                                                  Link.kind == kind, Link.status == "approved").first())
            if back is not None and back.source in ("llm", "data", SOURCE) and not back.both_ways \
                    and not back.proposed_drop and not (back.explained_by and back.explained_by not in ("llm", "data")):
                back.proposed_drop = f"the documents and the code state the other way: {r['from']} {kind} {r['to']}"
                out["removals"] += 1
        if suggest_link(a.id, b.id, kind, SOURCE, _evidence(r), _confidence(r)):
            out["links"] += 1
    if not dry_run and not shrunk:                       # what the documents proposed before and no longer state
        for x in db.session.query(Link).filter(Link.source == SOURCE, Link.a_ref.like("facet:%"),
                                               Link.b_ref.like("facet:%")):
            try:
                key = (int(x.a_ref.split(":", 1)[1]), int(x.b_ref.split(":", 1)[1]), x.kind)
            except ValueError:
                continue
            if key in stated:
                continue
            if x.status == "proposed":
                db.session.delete(x)
                out["withdrawn"] += 1
            elif x.status == "approved" and not x.proposed_drop:
                x.proposed_drop = "no document nor code states it any more"
                out["removals"] += 1
    objects: dict[tuple[str, str], int] = {}
    for oid, kind, name in db.session.query(KObject.id, KObject.kind, KObject.name).filter(
            KObject.kind.in_(("index", "metric", "family")), KObject.gone_at.is_(None)):
        objects.setdefault((kind, name), oid)
    given: set[tuple[str, int]] = set()
    for d in g.get("data_links") or []:
        okind = d.get("object_kind")
        oid = objects.get((okind, d["object"])) or objects.get(("family", d["object"]))
        if oid is None:
            continue
        f = value_of(d["part"])
        if f is None or dry_run:
            continue
        ref = f"object:{oid}"
        given.add((ref, f.id))
        have = db.session.query(Tag).filter(Tag.ref == ref, Tag.facet_id == f.id).first()
        if have is not None:
            if have.status != "rejected":
                out["confirmed"] += 1
            continue
        db.session.add(Tag(ref=ref, facet_id=f.id, source=SOURCE, status="proposed", confidence=_confidence(d)))
        out["items"] += 1
    if not dry_run:
        if not shrunk:
            for t in db.session.query(Tag).filter(Tag.source == SOURCE, Tag.status == "proposed"):
                if (t.ref, t.facet_id) not in given:
                    db.session.delete(t)
                    out["withdrawn"] += 1
        state = _json.dumps({"facts": max(now, before) if shrunk else now})
        if row is None:
            db.session.add(Meta(key=STATE_KEY, value=state))
        else:
            row.value = state
        db.session.commit()
    else:
        db.session.rollback()
    return out
