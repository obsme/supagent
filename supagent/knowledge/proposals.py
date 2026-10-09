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
           "runs_on": "runs_on", "monitors": "monitors", "in_group": "part_of", "routes_to": "calls"}
FLOWS = ("calls", "sends_to", "reads_from", "depends_on")
STORE_NAME = re.compile(r"(?:^|[-_])(?:db|database|cache|queue|bus|broker|store|storage|sessions)$|db$")   # (0.10.6)
#   what holds data or messages, by its name (ordersdb, event-bus, photo-store): read and written, it calls no one
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
    if kind in ("host", "vip"):                            # (0.10.4) a VIP: an address, with the servers
        return next((c for c in cats if SERVERISH.search(c)), None)
    if kind in ("database", "cache") or TECHNICAL.search(name):
        return "component" if "component" in cats else None
    return "application" if "application" in cats else None


def _rank(f: Any) -> tuple:
    """(0.10.6) Which of the values of one name a fact is about: not refused, approved, then the oldest."""
    return (f.status == "rejected", f.status != "approved", f.id or 0)


def _llm_proposal(f: Any) -> bool:
    """(0.10.6) A value the AI proposed and nobody approved, edited nor refused yet."""
    return f.status == "proposed" and f.source == "llm"


def _evidence(r: dict[str, Any]) -> str:
    where = r.get("where") or ""
    return (f'{r.get("quote") or ""} ({where}{"; " if where else ""}{", ".join(r.get("sources") or [])})')[:2000]


def _confidence(r: dict[str, Any]) -> float:
    return max([CONFIDENCE.get(s, 0.6) for s in r.get("sources") or []] or [0.6])


def _quote_of(evidence: str | None) -> str:
    """A link's evidence without its "(where; sources)" tail: the words a document said."""
    e = (evidence or "").strip()
    if e.endswith(")"):
        depth = 0
        for i in range(len(e) - 1, -1, -1):
            depth += {")": 1, "(": -1}.get(e[i], 0)
            if depth == 0:
                return e[:i].rstrip()
    return e


def still_written(evidence: str | None) -> bool:
    """(0.10.5) Whether the words a learned link was read from are still in an enabled document (its first and last
    ten words, whatever the line breaks between them): then the reading changed (a name approved since, read in the
    same sentence), not what the documents say, and its removal is not proposed: only a document updated or removed
    proposes one (the user's rule of 8 October)."""
    from supagent.models import Doc

    words = _quote_of(evidence).split()
    if len(words) < 3:
        return False

    def pattern(ws: list[str]) -> str:
        return "%" + "%".join(w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for w in ws) + "%"

    q = db.session.query(Doc.id).filter(Doc.enabled.is_(True))
    for ws in ([words[:10], words[-10:]] if len(words) > 10 else [words]):
        q = q.filter(Doc.content.like(pattern(ws), escape="\\"))
    try:
        return q.first() is not None
    except Exception:  # pylint: disable=broad-except   (a database that cannot match the pattern: as before)
        db.session.rollback()
        return False


def propose(dry_run: bool = False) -> dict[str, Any]:
    """The proposals made again from what the documents and the code state now (see the module). Counts."""
    from supagent.knowledge.facets import editable, merge_value, suggest_link
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
    from supagent.knowledge.interactions import TOPICS

    cats = set(editable())
    values: dict[str, Facet] = {}
    topics: dict[str, list[Facet]] = {}                   # (0.10.6) the subjects: topics, never a link's end
    for f in db.session.query(Facet).filter(Facet.facet.in_(list(cats))).order_by(Facet.id):
        for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
            key = _norm(n)
            if not key:
                continue
            if f.facet in TOPICS:
                if f.status != "rejected" and f not in topics.get(key, []):
                    topics.setdefault(key, []).append(f)
                continue
            if key not in values or _rank(f) < _rank(values[key]):   # (0.10.6) a part a person approved before a
                values[key] = f                                      # proposed one of the same name, then the oldest
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
    from supagent.knowledge.datalinks import SERVERISH

    servers = {_norm(f.value) for f in values.values() if f.status == "approved" and SERVERISH.search(f.facet or "")}
    vips = {_norm(r["from"]) for r in rels if r["kind"] == "routes_to"}
    kept_topics = {k for k, fs in topics.items() if not all(_llm_proposal(f) for f in fs)}
    clash = (groups & (partish | set(topics))) - servers - vips   # (0.10.5) a group already on the map as a server
    #                                                       stays itself; a VIP is an address with its servers, not a
    #                                                       group to rename; (0.10.6) a group named like a subject
    #                                                       ("monitoring", a topic): "monitoring (group)"

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
            kind_of[_norm(a)] = kind_of[_norm(b)] = "host"   # (a VIP's servers grouped under it: a VIP is an address)
            continue
        if r["kind"] == "routes_to":                      # (0.10.4) a VIP: an address, with the servers
            kind_of[_norm(a)] = "host"
        kind_of.setdefault(_norm(a), "part")
        if r["kind"] in LINK_OF:
            k = "host" if r["kind"] == "runs_on" or r.get("obj_kind") == "group" else str(r.get("obj_kind") or "part")
            kind_of[_norm(b)] = k if kind_of.get(_norm(b)) in (None, "part") else kind_of[_norm(b)]
    for d in g.get("data_links") or []:
        kind_of.setdefault(_norm(d["part"]), "part")

    merged: set[int] = set()

    def ai_subjects_into(key: str, part: Facet) -> None:
        """(0.10.6) The subjects the AI proposed with the name of a part the code, a configuration or a page names
        (it read the name before they did): that part, with what they were given; a person's subject stays, and a
        server is no topic's twin."""
        if dry_run or key in kept_topics or SERVERISH.search(part.facet or ""):
            return
        for t in topics.pop(key, []):
            if t.id in merged:                            # (one of its other names merged it already)
                continue
            merged.add(t.id)
            merge_value(t, part)
            out["subjects the AI proposed: the part"] = out.get("subjects the AI proposed: the part", 0) + 1

    def value_of(name: str) -> Facet | None:
        key = _norm(name)
        f = values.get(key)
        if f is not None:
            if f.status == "rejected":
                return None
            ai_subjects_into(key, f)
            return f
        if key in kept_topics:                            # (0.10.6) a subject a person approved or made: the name of
            out["a subject's name: no part"] = out.get("a subject's name: no part", 0) + 1   # a topic, no part (a
            return None                                   # person decides; To review is no place for a twin)
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
            ai_subjects_into(key, f)
        values[key] = f
        out["values"] += 1
        return f

    from supagent.knowledge.sysmap import kept_reasons, propose_drop

    kept = kept_reasons()                                 # (0.10.5) the reasons a person answered Keep to
    stated: set[tuple[int, int, str]] = set()
    said = {(_norm(x), _norm(y), LINK_OF.get(r["kind"])) for r in rels for x, y in [ends(r)]}   # (0.10.5) both
    for r in rels:                                        # ways stated: neither is the other one reversed
        kind = LINK_OF.get(r["kind"])
        if kind is None:
            continue
        a, b = (value_of(x) for x in ends(r))
        if a is None or b is None or a.id == b.id or dry_run:
            continue
        stated.add((a.id, b.id, kind))
        if kind in FLOWS:                                  # a learned link the other way round: its removal proposed;
            back = (db.session.query(Link).filter(Link.a_ref == f"facet:{b.id}", Link.b_ref == f"facet:{a.id}",
                                                  Link.kind == kind, Link.status == "approved").first())
            person = back is not None and (back.source == "admin" or
                                           bool(back.explained_by and back.explained_by not in ("llm", "data")))
            strong = bool(set(r.get("sources") or []) & {"code", "config"})    # (0.10.5) a person's: only when the
            if back is not None and not back.both_ways and not back.proposed_drop and \
                    (_norm(ends(r)[1]), _norm(ends(r)[0]), kind) not in said and (   # code or a configuration
                    (person and strong) or (not person and back.source in ("llm", "data", SOURCE))):   # says so
                where = f" ({r.get('where')})" if r.get("where") else ""
                if propose_drop(back, f"the documents and the code state the other way: {r['from']} {kind} {r['to']}"
                                + where, kept):
                    out["removals"] += 1
        same = (db.session.query(Link).filter(Link.a_ref == f"facet:{a.id}", Link.b_ref == f"facet:{b.id}",
                                              Link.kind == kind).first())
        if same is not None:
            if same.status != "rejected":
                out["confirmed"] += 1
                if not same.evidence:
                    same.evidence = _evidence(r)
            continue
        if kind in FLOWS and not set(r.get("sources") or []) & {"code", "config"}:
            if db.session.query(Link.id).filter(Link.a_ref == f"facet:{b.id}", Link.b_ref == f"facet:{a.id}",
                                                Link.kind.in_(list(FLOWS)), Link.status == "approved").first():
                out["the other way approved"] = out.get("the other way approved", 0) + 1   # (0.10.6) pages write
                continue                                   # "talks to" both ways: no reversed link from their words
            if kind == "calls" and STORE_NAME.search(_norm(a.value)) and not STORE_NAME.search(_norm(b.value)):
                out["a store calls no one"] = out.get("a store calls no one", 0) + 1   # (0.10.6) "ridesdb / Talks
                continue                                   # to: rental-api": its clients use it, it calls none
        if (r["kind"] in ("calls", "sends_to", "reads_from", "uses", "runs_on")) and _norm(b.value) in vips:
            out["to a VIP: its service"] = out.get("to a VIP: its service", 0) + 1   # (0.10.6) a VIP is an address:
            continue                                       # the service behind it gets the link (the reading adds it)
        if r["kind"] in ("calls", "sends_to", "reads_from", "uses") and SERVERISH.search(a.facet or "") and \
                a.status == "approved":                    # (a VIP's routes_to is no flow: it stays)
            out["a server is no flow's subject"] = out.get("a server is no flow's subject", 0) + 1
            continue                                       # (0.10.6) a server or a group: where parts run
        if suggest_link(a.id, b.id, kind, SOURCE, _evidence(r), _confidence(r)):
            out["links"] += 1
    if not dry_run and not shrunk:                       # what the documents proposed before and no longer state
        import datetime as _dt

        from supagent.knowledge.understand import TEXTS_KEY

        stamp = _dt.datetime.utcnow()
        texts = db.session.get(Meta, TEXTS_KEY)
        try:
            texts_at = _dt.datetime.fromisoformat(texts.value) if texts is not None and texts.value else None
        except ValueError:
            texts_at = None
        for x in db.session.query(Link).filter(Link.source == SOURCE, Link.a_ref.like("facet:%"),
                                               Link.b_ref.like("facet:%")):
            try:
                key = (int(x.a_ref.split(":", 1)[1]), int(x.b_ref.split(":", 1)[1]), x.kind)
            except ValueError:
                continue
            if key in stated:
                x.seen_at = stamp                          # (0.10.5) when the documents stated it last
                continue
            if x.status == "proposed":
                db.session.delete(x)
                out["withdrawn"] += 1
            elif x.status == "approved" and not x.proposed_drop:
                if (x.seen_at is not None and texts_at is not None and texts_at <= x.seen_at) or \
                        still_written(x.evidence):         # (0.10.5) no text changed since it was stated, or its
                    out["still written"] = out.get("still written", 0) + 1   # words are still in a document: the
                    continue                               # reading moved (a name approved since), not the documents
                if propose_drop(x, "no document nor code states it any more", kept):
                    out["removals"] += 1
    if not dry_run:                                      # (0.10.5) a sentence denying a link or putting it in the
        strong = {(_norm(r["from"]), _norm(r["to"])) for r in rels   # past: its removal proposed with the sentence,
                  if set(r.get("sources") or []) & {"code", "config"}}   # unless the code or a configuration states it
        for d in g.get("denied") or []:
            kind = LINK_OF.get(d["kind"])
            a, b = values.get(_norm(d["from"])), values.get(_norm(d["to"]))
            if kind is None or a is None or b is None or "rejected" in (a.status, b.status) or \
                    (_norm(d["from"]), _norm(d["to"])) in strong:
                continue
            family = FLOWS if kind in FLOWS else (kind,)
            for x in db.session.query(Link).filter(Link.a_ref == f"facet:{a.id}", Link.b_ref == f"facet:{b.id}",
                                                   Link.kind.in_(family), Link.status == "approved",
                                                   Link.proposed_drop.is_(None)):
                if propose_drop(x, f'a document says it does not hold any more: "{d["quote"]}" ({d["where"]})', kept):
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
