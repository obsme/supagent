"""Context: what the system is, functionally and technically, written every night (context.hour,
after the day's learning run) from the knowledge the team shares: the documents and sites, the
catalog, the team memory, the data dictionary (databases, categories, relations, the values of
labels and fields such as servers, services, applications, environments) and the answers marked
Helpful. Raw chats are not read: they were answered with each user's own permissions.

Facts pages are written without the LLM: each database's data sources and inventory, the glossary,
the rules and facts. Summary pages are written by the LLM from the evidence given only (marked
AI-written, citing their sources): how the system works, the technical overview, one page per main
application. A summary page is written again only when its evidence changed (input hash), at most
context.max_llm_calls LLM calls per build: a second build with nothing new asks the LLM nothing. A
page a person edited is never written over by the agent.

A page is shown (Data dictionary -> Context, and to the agent through the knowledge search, below
the catalog and the documents) only to the users who may query every database it draws from.
The build is a run of kind "context" (the runs list, its steps, Stop); it never runs next to a
learning run. Code read through MCP servers can be added later as one more source of evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from typing import Any

from superset import db

from supagent import settings
from supagent.models import ContextPage, Doc, Entry, KObject, Memory, Recipe, Relation, Run, Source

log = logging.getLogger(__name__)
SECTIONS = ("functional", "technical")
INVENTORY = {   # what a label or field of these names holds (lower case, exact names)
    "Servers and hosts": ("node", "host", "hostname", "server", "server_name", "instance", "machine", "vm"),
    "Services and jobs": ("service", "service_name", "job", "job_name", "component", "task_name"),
    "Applications": ("application", "app", "app_name", "application_name", "system"),
    "Environments": ("env", "environment", "environment_type", "stage"),
    "Regions and sites": ("region", "datacenter", "dc", "site", "zone", "location"),
    "Clusters and pools": ("cluster", "namespace", "pool", "queue"),
    "Tenants (each usually a different application or subject)": ("__tenant_id__", "tenant_id", "tenant", "org_id",
                                                                   "x_scope_orgid"),
    "Teams": ("team", "owner", "squad"),
}
MAIN_ITEMS = 25            # the main metrics and indices of a data source on its page (a person's, used, catalog)
MAX_VALUES = 300           # values listed per inventory line
MAX_APPS = 8               # application pages at most
DOC_CHARS = 3000           # of each document in an LLM prompt
DESC_CHARS = 1200          # of a main index's or metric's description on its page (cut after a whole sentence)
FIELDS_OF = 3              # the main indices and metrics whose fields or labels a data source's page lists
FIELD_CHARS = 240          # of a field's description on that list
FORMULA_CHARS = 800        # of a formula on a data source's page
SUMMARY_TOKENS = 3000      # of an LLM summary page; cut by that limit, it is asked to go on (CONTINUATIONS times)
CONTINUATIONS = 2
REJECTED = "rejected"      # the kind of a new page a person refused: not shown nor searched; proposed again (to
#                            review) only when its evidence changes


def clip(text: str, limit: int) -> str:
    """`text` on one line, at most `limit` characters: cut after its last whole sentence that fits (else after a
    whole word), with " …" when something was left out; never in the middle of a word."""
    t = " ".join((text or "").split())
    if len(t) <= limit:
        return t
    head = t[:limit]
    ends = [m.end() for m in re.finditer(r"[.!?;](?=\s)", t[:limit + 1])]     # a sentence ending at the limit too
    if ends and ends[-1] >= limit // 2:
        return head[:ends[-1]].rstrip(";") + " …"
    return (head.rsplit(" ", 1)[0] if " " in head else head).rstrip(",;:") + " …"


PROMPT = """You write one page of the internal documentation of an information system, in Markdown, from the
evidence given as JSON (documents, catalog entries, team memory, data dictionary, questions people asked).
Rules: use only this evidence, never invent a name, a number, a link or a dependency; when the evidence does
not say, write "not known yet". Cite the evidence you use as [E1], [E2]... Use ## headings, short paragraphs
and bullet lists, no HTML, no code fences unless quoting a query. Write in the language of most of the
evidence. The page: {title}. {brief}"""


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:100] or "page"


def _hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# what is known
# --------------------------------------------------------------------------- #
def _importance() -> dict[tuple[int, str], float]:
    """(database id, metric or index name) -> how much it matters to the team: used by the answers
    (where the data was, learned answers), described by the catalog."""
    import math

    from supagent.knowledge.curated import catalog_texts
    from supagent.models import Association

    out: dict[tuple[int, str], float] = defaultdict(float)
    try:
        for dbid, name, uses in db.session.query(Association.database_id, Association.name, Association.uses):
            out[(dbid, name)] += 20 * math.log(1 + (uses or 1))
        for dbid, target in (db.session.query(Recipe.database_id, Recipe.target)
                             .filter(Recipe.status.in_(("helpful", "confirmed")))):
            if dbid and target:
                out[(dbid, target)] += 30
    except Exception:  # pylint: disable=broad-except
        db.session.rollback()
    named = {name for (kind, _parent, name) in catalog_texts() if kind in ("metric", "index")}
    return {**out, **{("*", n): 50.0 for n in named}}


def _span(stats: dict[str, Any] | None) -> dict[str, Any]:
    """An index's documents and time range, as its learning measured them."""
    st = stats or {}
    out: dict[str, Any] = {}
    if isinstance(st.get("docs"), (int, float)):
        out["docs"] = int(st["docs"])
    tr = st.get("time_range")
    if st.get("time_field") and isinstance(tr, (list, tuple)) and len(tr) == 2 and tr[0] and tr[1]:
        out["time"] = {"field": str(st["time_field"]), "from": str(tr[0])[:10], "to": str(tr[1])[:10]}
    return out


RANK = {"curated": 0, "backend": 1, "llm": 1, "inferred": 2}


def _fields_of(source_id: int, items: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """The fields (of an index) or labels (of a metric) of a data source's first main items, for its page: the
    described ones first, then the most filled; at most context.fields_shown of each (the Data dictionary has
    them all)."""
    try:
        limit = max(0, int(settings.get("context.fields_shown")))
    except Exception:  # pylint: disable=broad-except   (an older settings table)
        limit = 30
    out: list[dict[str, Any]] = []
    if not limit:
        return out
    for kind, name in items:
        rows = (db.session.query(KObject).filter(KObject.source_id == source_id, KObject.parent == name,
                                                 KObject.kind == ("label" if kind == "metric" else "field"),
                                                 KObject.gone_at.is_(None)).all())
        if not rows:
            continue

        def rank(o: KObject) -> tuple:
            st = o.stats or {}
            filled = st.get("filled_pct")
            return (0 if o.verified else RANK.get(o.description_source or "", 3) if o.description else 4,
                    -(filled if isinstance(filled, (int, float)) else 0), o.name.lower())

        shown = []
        for o in sorted(rows, key=rank)[:limit]:
            st = o.stats or {}
            vals = st.get("values") if isinstance(st.get("values"), list) else []
            card = st.get("cardinality")
            few = vals and len(vals) <= 12 and (not isinstance(card, (int, float)) or card <= 12)
            shown.append({"name": o.name, "type": o.data_type or o.metric_type or "",
                          "about": clip(o.description or o.backend_help or "", FIELD_CHARS),
                          "values": [str(v) for v in vals[:12]] if few else []})
        out.append({"kind": kind, "name": name, "child": "label" if kind == "metric" else "field",
                    "total": len(rows), "shown": shown})
    return out


def collect() -> dict[str, Any]:
    """The shared knowledge, bounded: databases, inventories, relations, catalog, documents, team
    memory, Helpful answers."""
    from superset.models.core import Database

    from supagent.knowledge.catalog import AGENT
    from supagent.tools import agent_databases

    dbs = {d.id: d for d in agent_databases(list(db.session.query(Database).order_by(Database.id)))}
    sources = {s.id: s for s in db.session.query(Source).filter(Source.database_id.in_(list(dbs) or [-1]))}
    weight = _importance()
    out: dict[str, Any] = {"databases": {}, "inventory": defaultdict(dict), "relations": [], "entries": [],
                           "docs": [], "memory": [], "answers": []}
    for sid, s in sources.items():
        objs = db.session.query(KObject).filter(KObject.source_id == sid, KObject.gone_at.is_(None))
        counts: dict[str, int] = defaultdict(int)
        categories: dict[str, int] = defaultdict(int)
        main = []
        for o in objs:
            counts[o.kind] += 1
            if o.kind in ("metric", "index") and o.category:
                categories[o.category] += 1
            if o.kind in ("metric", "index", "family"):                # what matters first (not all of 10,000)
                score = weight.get((s.database_id, o.name), 0) + weight.get(("*", o.name), 0) \
                    + (100 if o.description_source == "curated" else 0) \
                    + (5 if o.description else 0) + (10 if o.kind in ("index", "family") else 0)
                main.append((-score, o.kind, o.name, (o.description or "").strip()[:4000],
                             o.stats if o.kind == "index" else None))
            names = [dim for dim, keys in INVENTORY.items() if o.kind in ("label", "field") and o.name.lower() in keys]
            if names:
                st = o.stats or {}
                vals = st.get("values") or st.get("sample") or []
                slot = out["inventory"][names[0]].setdefault(s.database_id, {"holders": [], "values": set(),
                                                                            "partial": False})
                slot["holders"].append(f"{o.kind} {o.name} of {o.parent}")
                slot["values"].update(map(str, vals))
                slot["partial"] = slot["partial"] or bool(st.get("partial") or st.get("sample"))
        if not counts:                                   # nothing learned there (yet): no page
            continue
        main.sort(key=lambda x: x[:3])
        d = dbs.get(s.database_id)
        out["databases"][s.database_id] = {
            "name": s.database_name or (d.database_name if d else str(s.database_id)), "backend": s.backend,
            "counts": dict(counts), "categories": dict(sorted(categories.items(), key=lambda x: -x[1])[:20]),
            "main": [{"kind": k, "name": n, "about": t, **_span(st)} for _s, k, n, t, st in main[:MAIN_ITEMS]],
            "others": max(0, len(main) - MAIN_ITEMS),
            "fields": _fields_of(sid, [(k, n) for _s, k, n, _t, _st in main[:MAIN_ITEMS]
                                       if k in ("index", "family", "metric")][:FIELDS_OF])}
    for dim, per_db in out["inventory"].items():
        for slot in per_db.values():
            slot["values"] = sorted(slot["values"])
    by_obj = {o.id: o for o in db.session.query(KObject).filter(
        KObject.id.in_(db.session.query(Relation.a_id).filter(Relation.rejected_at.is_(None))) |
        KObject.id.in_(db.session.query(Relation.b_id).filter(Relation.rejected_at.is_(None))))}
    for r in db.session.query(Relation).filter(Relation.rejected_at.is_(None)).limit(400):
        a, b = by_obj.get(r.a_id), by_obj.get(r.b_id)
        if a is None or b is None or a.source_id == b.source_id or a.source_id not in sources \
                or b.source_id not in sources:
            continue
        out["relations"].append({"a": f"{a.parent + '.' if a.parent else ''}{a.name}",
                                 "a_db": sources[a.source_id].database_id,
                                 "b": f"{b.parent + '.' if b.parent else ''}{b.name}",
                                 "b_db": sources[b.source_id].database_id, "origin": r.origin})
    for e in db.session.query(Entry).filter(Entry.deleted_at.is_(None), Entry.enabled.is_(True)).order_by(Entry.id):
        database_id = (e.evidence or {}).get("database_id")
        out["entries"].append({"id": e.id, "title": e.title, "classification": e.classification,
                               "category": e.category, "content": (e.content or "")[:1500],
                               "agent": e.updated_by == AGENT, "database_id": database_id})
    for d in db.session.query(Doc).filter(Doc.enabled.is_(True), Doc.status == "ok").order_by(Doc.id):
        out["docs"].append({"id": d.id, "title": d.title or d.url or f"document {d.id}", "url": d.url,
                            "content": d.content or ""})
    for m in db.session.query(Memory).filter(Memory.scope == "team", Memory.status == "active").order_by(Memory.id):
        out["memory"].append({"id": m.id, "kind": m.kind, "text": m.text})
    for r in (db.session.query(Recipe).filter(Recipe.status.in_(("helpful", "confirmed")))
              .order_by(Recipe.id.desc()).limit(200)):
        out["answers"].append({"id": r.id, "question": r.question, "tool": r.tool, "database_id": r.database_id})
    db.session.commit()
    out["inventory"] = dict(out["inventory"])
    return out


# --------------------------------------------------------------------------- #
# facts pages (no LLM)
# --------------------------------------------------------------------------- #
PLURALS = {"index": "indices", "family": "families"}


def _plural(kind: str, n: int) -> str:
    return kind if n == 1 else PLURALS.get(kind, kind + "s")


def _sentence(text: str) -> str:
    """A text that ends as a sentence (a full stop added when it ends without one)."""
    t = (text or "").rstrip()
    return t if not t or t[-1] in ".!?…:" else t + "."


def _main_line(m: dict[str, Any]) -> str:
    """One main index or metric: its description (whole sentences), its documents and time range."""
    line = f"- {m['kind']} `{m['name']}`" + (f": {clip(m['about'], DESC_CHARS)}" if m.get("about") else "")
    facts = []
    if m.get("docs") is not None:
        facts.append(f"{m['docs']:,} documents")
    if m.get("time"):
        facts.append(f"from {m['time']['from']} to {m['time']['to']}, time field `{m['time']['field']}`")
    return line + (f" ({'; '.join(facts)})" if facts else "")


def fact_pages(ev: dict[str, Any]) -> list[dict[str, Any]]:
    pages = []
    names = {i: d["name"] for i, d in ev["databases"].items()}
    for dbid, d in ev["databases"].items():
        lines = [f"# {d['name']}", "", f"Engine: {d['backend']}. Learned objects: " +
                 ", ".join(f"{n:,} {_plural(k, n)}" for k, n in sorted(d["counts"].items())) + "."]
        if d["categories"]:
            lines += ["", "## Domains", ""] + [f"- {c}: {n}" for c, n in d["categories"].items()]
        if d["main"]:
            lines += ["", "## Main data", "", "What the team described or uses most (the Data dictionary has every "
                      "object)."] + [_main_line(m) for m in d["main"]]
            if d.get("others"):
                lines.append(f"- ... and {d['others']:,} more, in the domains above")
        for f in d.get("fields") or []:
            lines += ["", f"## The {f['child']}s of {f['kind']} `{f['name']}`", "",
                      f"{f['total']:,} {f['child']}{'s' if f['total'] > 1 else ''}"
                      + (f"; the {len(f['shown'])} described or filled most:" if len(f["shown"]) < f["total"] else ":")]
            for x in f["shown"]:
                lines.append(f"- `{x['name']}`" + (f" ({x['type']})" if x["type"] else "")
                             + (f": {_sentence(x['about'])}" if x["about"] else "")
                             + (f"{' ' if x['about'] else ': '}Values: {', '.join(x['values'])}." if x["values"] else ""))
            if len(f["shown"]) < f["total"]:
                lines.append(f"- ... and {f['total'] - len(f['shown']):,} more in the Data dictionary")
        formulas = [e for e in ev["entries"] if e["database_id"] == dbid and e["classification"] == "formula"]
        if formulas:
            lines += ["", "## Formulas", ""] + [f"- {e['title']}: {clip(e['content'], FORMULA_CHARS)}" for e in formulas]
        pages.append({"section": "technical", "slug": f"data-sources-{slugify(d['name'])}",
                      "title": f"Data source: {d['name']}", "content": "\n".join(lines), "database_ids": [dbid],
                      "sources": [{"ref": f"database:{dbid}", "title": d["name"]}]})
        inv = [(dim, per_db[dbid]) for dim, per_db in ev["inventory"].items() if dbid in per_db]
        if inv:
            lines = [f"# Inventory from {d['name']}", "",
                     "The values of the labels and fields that name servers, services, applications, environments, "
                     "regions, clusters and teams (learned from the data; a list may be a sample)."]
            for dim, slot in sorted(inv):
                vals = slot["values"]
                lines += ["", f"## {dim}", "", "Found in: " + "; ".join(sorted(set(slot["holders"]))[:12]) + ".", ""]
                shown = ", ".join(vals[:MAX_VALUES]) if vals else "(no values learned yet)"
                more = f" ... ({len(vals)} values)" if len(vals) > MAX_VALUES else f" ({len(vals)} values)"
                lines.append(shown + (more if vals else "") + (" - a sample of the values" if slot["partial"] else ""))
            pages.append({"section": "technical", "slug": f"inventory-{slugify(d['name'])}",
                          "title": f"Inventory: {d['name']}", "content": "\n".join(lines), "database_ids": [dbid],
                          "sources": [{"ref": f"database:{dbid}", "title": d["name"]}]})
    pairs: dict[tuple[int, int], list[dict]] = {}          # the links of two sources: a page of both (seen only
    for r in ev["relations"]:                                # by the users who may query both databases)
        if r["a_db"] != r["b_db"] and r["a_db"] in names and r["b_db"] in names:
            pairs.setdefault(tuple(sorted((r["a_db"], r["b_db"]))), []).append(r)
    for (a, b), links in pairs.items():
        lines = [f"# Links between {names[a]} and {names[b]}", "",
                 "Fields and labels that hold the same values in the two data sources (measured, or from the catalog)."]
        for r in links[:60]:
            lines.append(f"- `{r['a']}` ({names.get(r['a_db'], r['a_db'])}) holds the same values as `{r['b']}` "
                         f"({names.get(r['b_db'], r['b_db'])}){' (catalog)' if r['origin'] == 'curated' else ''}")
        pages.append({"section": "technical", "slug": f"links-{slugify(names[a])}-{slugify(names[b])}",
                      "title": f"Links: {names[a]} and {names[b]}", "content": "\n".join(lines),
                      "database_ids": [a, b], "sources": [{"ref": f"database:{a}", "title": names[a]},
                                                          {"ref": f"database:{b}", "title": names[b]}]})
    glossary = [e for e in ev["entries"] if e["classification"] == "glossary"]
    if glossary:
        lines = ["# Glossary", "", "Terms defined in the catalog (by the team, or quoted word for word from the documents "
                 "by the agent)."]
        for e in sorted(glossary, key=lambda x: x["title"].lower()):
            lines += ["", f"## {e['title']}", "", e["content"]]
        pages.append({"section": "functional", "slug": "glossary", "title": "Glossary", "content": "\n".join(lines),
                      "database_ids": [], "sources": [{"ref": f"entry:{e['id']}", "title": e["title"]} for e in glossary]})
    rules = [e for e in ev["entries"] if e["classification"] in ("rule", "guide")]
    if rules or ev["memory"]:
        lines = ["# Rules and facts of the team", ""]
        for e in rules:
            lines += [f"## {e['title']}", "", e["content"], ""]
        if ev["memory"]:
            lines += ["## Team memory", ""] + [f"- ({m['kind']}) {m['text']}" for m in ev["memory"]]
        pages.append({"section": "functional", "slug": "rules-and-facts", "title": "Rules and facts",
                      "content": "\n".join(lines).strip(), "database_ids": [],
                      "sources": [{"ref": f"entry:{e['id']}", "title": e["title"]} for e in rules] +
                                 [{"ref": f"memory:{m['id']}", "title": m["text"][:60]} for m in ev["memory"]]})
    return pages


# --------------------------------------------------------------------------- #
# summary pages (LLM, only when their evidence changed)
# --------------------------------------------------------------------------- #
def _numbered(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Evidence items as E1, E2...: (for the prompt, the page's sources)."""
    prompt, sources = [], []
    for i, it in enumerate(items, 1):
        prompt.append({"id": f"E{i}", **{k: v for k, v in it.items() if k != "ref"}})
        sources.append({"ref": it["ref"], "title": it.get("title") or it.get("name") or it["ref"]})
    return prompt, sources


def _apps(ev: dict[str, Any]) -> list[str]:
    """The main applications: the values of the application labels and fields, most mentioned first."""
    found: set[str] = set()
    for slot in (ev["inventory"].get("Applications") or {}).values():
        found.update(v for v in slot["values"] if v and 2 <= len(v) <= 60 and not v.isdigit())   # not "A", not "7"
    text = " ".join([d["content"][:20000] for d in ev["docs"]] + [a["question"] or "" for a in ev["answers"]] +
                    [e["content"] for e in ev["entries"]])

    def mentions(app: str) -> int:
        return len(re.findall(r"(?<![\w-])" + re.escape(app) + r"(?![\w-])", text, re.I))

    ranked = sorted(found, key=lambda a: (-mentions(a), a))
    return [a for a in ranked if mentions(a)][:MAX_APPS]


def _excerpts(text: str, name: str, limit: int = 20) -> list[str]:
    lines = [ln.strip() for ln in (text or "").splitlines() if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])",
                                                                        ln, re.I)]
    return [ln[:300] for ln in lines[:limit]]


def summary_specs(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """The summary pages to write, each with its evidence (the hash of which decides whether to write it)."""
    all_dbs = sorted(ev["databases"])
    databases = [{"ref": f"database:{i}", "name": d["name"], "engine": d["backend"], "objects": d["counts"],
                  "domains": list(d["categories"])[:12]} for i, d in ev["databases"].items()]
    inventory = [{"ref": f"inventory:{dim}", "title": dim, "what": dim,
                  "examples": sorted({v for slot in per_db.values() for v in slot["values"]})[:25],
                  "count": len({v for slot in per_db.values() for v in slot["values"]})}
                 for dim, per_db in ev["inventory"].items()]
    docs = [{"ref": f"doc:{d['id']}", "title": d["title"], "text": d["content"][:DOC_CHARS]} for d in ev["docs"][:6]]
    entries = [{"ref": f"entry:{e['id']}", "title": e["title"], "classification": e["classification"],
                "text": e["content"][:600]} for e in ev["entries"] if e["classification"] != "formula"][:40]
    questions = [{"ref": f"recipe:{a['id']}", "title": (a["question"] or "")[:80], "question": a["question"]}
                 for a in ev["answers"]][:40]
    relations = [{"ref": "relations", "title": "relations between the data sources",
                  "links": [f"{r['a']} = {r['b']}" for r in ev["relations"][:40]]}] if ev["relations"] else []
    specs = [
        {"section": "functional", "slug": "overview", "title": "How the system works", "database_ids": all_dbs,
         "brief": "Explain what the system does for its users, its applications and their roles, the main processes "
                  "and chains between applications, and where the data of each one is (## What it does, ## Applications, "
                  "## Processes and chains, ## Where the data is).",
         "evidence": docs + entries + questions + databases + inventory},
        {"section": "technical", "slug": "architecture", "title": "Technical overview", "database_ids": all_dbs,
         "brief": "Describe the data sources, the infrastructure (servers, services, clusters, environments, regions), "
                  "how the data sources relate and what is not known (## Data sources, ## Infrastructure, ## Links, "
                  "## Not known yet).",
         "evidence": databases + inventory + relations + docs},
    ]
    for app in _apps(ev):
        ev_app = []
        for d in ev["docs"]:
            ex = _excerpts(d["content"], app)
            if ex:
                ev_app.append({"ref": f"doc:{d['id']}", "title": d["title"], "lines": ex})
        for e in ev["entries"]:
            if re.search(r"(?<![\w-])" + re.escape(app) + r"(?![\w-])", e["title"] + " " + e["content"], re.I):
                ev_app.append({"ref": f"entry:{e['id']}", "title": e["title"], "text": e["content"][:600]})
        for a in ev["answers"]:
            if re.search(r"(?<![\w-])" + re.escape(app) + r"(?![\w-])", a["question"] or "", re.I):
                ev_app.append({"ref": f"recipe:{a['id']}", "title": (a["question"] or "")[:80],
                               "question": a["question"]})
        holders = [{"ref": f"database:{i}", "title": ev["databases"][i]["name"], "holders": slot["holders"][:10]}
                   for i, slot in (ev["inventory"].get("Applications") or {}).items() if app in slot["values"]]
        specs.append({"section": "functional", "slug": f"application-{slugify(app)}", "title": f"Application {app}",
                      "database_ids": sorted({int(h["ref"].split(":")[1]) for h in holders}),
                      "brief": f"Explain what the application {app} is and does, what it depends on and what depends "
                               "on it (the chain), where its data is, and what people ask about it (## What it is, "
                               "## Chain, ## Its data, ## Questions people ask).",
                      "evidence": ev_app[:30] + holders})
    return specs


CONTINUE = ("Your page stopped before its end (the length limit of one answer). Go on exactly where it stopped, "
            "with the same rules: no repetition, no preamble.")
CUT_NOTE = ("*(The page stops here: the LLM's answer reached its length limit three times. The next build writes it "
            "again.)*")


def _page_text(msg: dict[str, Any]) -> str:
    """An answer's text without its reasoning, a reasoning cut before its end (no closing tag) included."""
    text = re.sub(r"<think>.*?</think>", "", (msg or {}).get("content") or "", flags=re.S)
    return re.sub(r"<think>.*\Z", "", text, flags=re.S)


def write_summary(spec: dict[str, Any], llm: Any) -> dict[str, Any]:
    """One summary page. An answer cut by the length limit (finish_reason "length") is asked to go on, at most
    CONTINUATIONS times (one cut while reasoning, with nothing written yet, is asked again with twice the room);
    still cut, the page keeps its whole lines and says that it stops there ("cut": the next build writes it
    again)."""
    prompt_items, sources = _numbered(spec["evidence"])
    messages = [{"role": "system", "content": PROMPT.format(title=spec["title"], brief=spec["brief"])},
                {"role": "user", "content": json.dumps(prompt_items, ensure_ascii=False, default=str)}]
    text, tokens, cut, room = "", 0, False, SUMMARY_TOKENS
    for _turn in range(CONTINUATIONS + 1):
        msg = llm.chat(messages, max_tokens=room)
        usage = getattr(llm, "last_usage", None) or {}
        tokens += int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        part = _page_text(msg)
        cut = getattr(llm, "last_finish", None) == "length"
        if cut and not part.strip() and not text:
            room *= 2                                 # the room went to the reasoning: again, with more
            continue
        text += part
        if not cut:
            break
        messages = messages + [{"role": "assistant", "content": part}, {"role": "user", "content": CONTINUE}]
    text = text.strip()
    if cut and text:
        whole = text.rsplit("\n", 1)[0].rstrip() if "\n" in text else text
        text = whole + "\n\n" + CUT_NOTE
    return {"content": text, "sources": sources, "tokens": tokens, "cut": cut}


# --------------------------------------------------------------------------- #
# saving
# --------------------------------------------------------------------------- #
SAME_STATEMENT = 0.85      # two statements this close (difflib ratio, normalized) are the same one


def statements(markdown: str) -> list[str]:
    """The statements of a page: its lines and sentences, without Markdown marks, citations or headings' hashes,
    normalized (lower case, single spaces); headings and empty lines left out."""
    out: list[str] = []
    for line in (markdown or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or set(line) <= set("-|: "):
            continue
        line = re.sub(r"\[E\d+\]|\*\*|__|`|^[-*+>]\s+|^\d+[.)]\s+", "", line)
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", line):
            norm = " ".join(part.lower().split()).strip(" .;:")
            if len(norm) >= 12:
                out.append(norm)
    return out


def compare(old: str, new: str) -> dict[str, list[str]]:
    """What `new` adds to `old` and what it leaves out of it, statement by statement (no LLM)."""
    import difflib

    a, b = statements(old), statements(new)

    def has(x: str, pool: list[str]) -> bool:
        return any(x == y or difflib.SequenceMatcher(None, x, y).ratio() >= SAME_STATEMENT for y in pool)

    return {"added": [x for x in b if not has(x, a)][:40], "dropped": [x for x in a if not has(x, b)][:40]}


def _words(a: str, b: str) -> tuple[list[list[str]], list[list[str]]]:
    """Two versions of a line, word by word: [["eq"|"del", text], ...] for the old one, [["eq"|"ins", text], ...]
    for the new one (the words that changed, to show in red and green)."""
    import difflib

    ta, tb = re.findall(r"\s+|[^\s]+", a or ""), re.findall(r"\s+|[^\s]+", b or "")
    old_parts: list[list[str]] = []
    new_parts: list[list[str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ta, tb, autojunk=False).get_opcodes():
        if op == "equal":
            old_parts.append(["eq", "".join(ta[i1:i2])])
            new_parts.append(["eq", "".join(tb[j1:j2])])
            continue
        if i2 > i1:
            old_parts.append(["del", "".join(ta[i1:i2])])
        if j2 > j1:
            new_parts.append(["ins", "".join(tb[j1:j2])])

    def merged(parts: list[list[str]], changed: str) -> list[list[str]]:
        """A space between two changed words is part of the change: one highlight, not several."""
        out: list[list[str]] = []
        for k, (op, text) in enumerate(parts):
            if op == "eq" and not text.strip() and out and out[-1][0] == changed and k + 1 < len(parts) and \
                    parts[k + 1][0] == changed:
                op = changed
            if out and out[-1][0] == op:
                out[-1][1] += text
            else:
                out.append([op, text])
        return out

    return merged(old_parts, "del"), merged(new_parts, "ins")


REWRITTEN = 0.5            # a changed line this unlike its old one is shown as removed and added, not word by word


def diff_rows(old: str, new: str) -> list[dict[str, Any]]:
    """The old and the new version of a page line by line, for a side-by-side view: {"op": same | del | add | mod,
    "o": line number in the old (or None), "n": in the new, "old": text, "new": text}, a changed line ("mod") with its
    words ("old_parts", "new_parts"). A changed block pairs its lines in order; what is left over is removed or added."""
    import difflib

    a, b = (old or "").splitlines(), (new or "").splitlines()
    rows: list[dict[str, Any]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            rows += [{"op": "same", "o": i1 + k + 1, "n": j1 + k + 1, "old": a[i1 + k], "new": b[j1 + k]}
                     for k in range(i2 - i1)]
            continue
        pairs = min(i2 - i1, j2 - j1) if op == "replace" else 0
        for k in range(pairs):
            o, n = a[i1 + k], b[j1 + k]
            if difflib.SequenceMatcher(None, o, n, autojunk=False).ratio() < REWRITTEN:
                rows.append({"op": "del", "o": i1 + k + 1, "n": None, "old": o, "new": None})
                rows.append({"op": "add", "o": None, "n": j1 + k + 1, "old": None, "new": n})
                continue
            op_parts = _words(o, n)
            rows.append({"op": "mod", "o": i1 + k + 1, "n": j1 + k + 1, "old": o, "new": n,
                         "old_parts": op_parts[0], "new_parts": op_parts[1]})
        rows += [{"op": "del", "o": i + 1, "n": None, "old": a[i], "new": None} for i in range(i1 + pairs, i2)]
        rows += [{"op": "add", "o": None, "n": j + 1, "old": None, "new": b[j]} for j in range(j1 + pairs, j2)]
    return rows


def _refused(p: ContextPage) -> dict[str, Any] | None:
    """What a page keeps of its review when its proposal is cleared: the version a person refused, if any."""
    h = (p.compared or {}).get("rejected_hash")
    return {"rejected_hash": h} if h else None


def _propose(p: ContextPage, page: dict[str, Any], kind: str, input_hash: str) -> str:
    """The agent's new version of a page that exists: a proposal a person validates (the page shown stays as it
    is). A proposal not validated yet is replaced by this one, and what it said that this one does not is kept
    with it ("left out"), as is what the page shown says that this one no longer does ("obsolete")."""
    if p.proposed_hash == input_hash and p.proposed_content:
        return "unchanged"
    now_vs = compare(p.content or "", page["content"])
    earlier = compare(p.proposed_content or "", page["content"]) if p.proposed_content else {"dropped": []}
    done = dict(p.compared or {})
    p.compared = {"added": now_vs["added"], "obsolete": now_vs["dropped"], "left_out": earlier["dropped"],
                  "replaced": int(done.get("replaced") or 0) + (1 if p.proposed_content else 0),
                  "replaced_at": dt.datetime.utcnow().isoformat(timespec="seconds") if p.proposed_content else None,
                  **({"rejected_hash": done["rejected_hash"]} if done.get("rejected_hash") else {})}
    p.proposed_content, p.proposed_sources, p.proposed_kind = page["content"], page.get("sources") or [], kind
    p.proposed_hash, p.proposed_at, p.proposed_drop = input_hash, dt.datetime.utcnow(), False
    db.session.commit()
    return "proposed"


def save_page(page: dict[str, Any], kind: str, input_hash: str, llm_calls: int = 0, tokens: int = 0) -> str:
    """written | proposed (a change waiting for a person's validation, context.review) | unchanged | kept (a
    person's edit)."""
    p = (db.session.query(ContextPage).filter(ContextPage.section == page["section"], ContextPage.slug == page["slug"])
         .one_or_none())
    if p is not None and (p.author or "agent") != "agent":
        return "kept"
    if p is not None and p.input_hash == input_hash and p.content:
        if p.proposed_content or p.proposed_drop:          # the evidence came back to what the page says
            p.proposed_content = p.proposed_sources = p.proposed_kind = p.proposed_hash = None
            p.compared = _refused(p)
            p.proposed_at, p.proposed_drop = None, False
            db.session.commit()
        return "unchanged" if p.kind != REJECTED else "rejected"
    if p is not None and input_hash and input_hash == (p.compared or {}).get("rejected_hash"):
        return "rejected"                                  # a person refused this very version
    if p is not None and p.content and (settings.get("context.review") or p.kind == REJECTED):
        return _propose(p, page, kind, input_hash)
    if p is None:
        p = ContextPage(section=page["section"], slug=page["slug"], version=0)
        db.session.add(p)
    p.title, p.kind, p.content = page["title"][:255], kind, page["content"]
    p.sources, p.database_ids = page.get("sources") or [], sorted(page.get("database_ids") or [])
    p.input_hash, p.author, p.version = input_hash, "agent", (p.version or 0) + 1
    p.llm_calls, p.tokens, p.updated_at = llm_calls, tokens, dt.datetime.utcnow()
    db.session.commit()
    return "written"


def drop_pages(keep: set[tuple[str, str]]) -> int:
    """Pages of the agent whose subject is gone (a database or an application no longer found): deleted, or with
    context.review proposed for removal (a person validates it)."""
    n = 0
    review = settings.get("context.review")
    for p in db.session.query(ContextPage).filter(ContextPage.author == "agent"):
        if (p.section, p.slug) not in keep:
            if p.kind == REJECTED:                      # refused and hidden already: nothing to review
                db.session.delete(p)
                n += 1
            elif review:
                if not p.proposed_drop:
                    p.proposed_drop, p.proposed_at = True, dt.datetime.utcnow()
                    n += 1
            else:
                db.session.delete(p)
                n += 1
    db.session.commit()
    return n


def review(page_id: int, action: str, by: str, content: str | None = None) -> dict[str, Any]:
    """A person's answer to the agent's proposal for a page: approve (the proposed content is shown, or the page
    removed) or reject (the page stays as it is; a removal refused keeps the page as theirs, never proposed again).
    `content`: the proposal (or a new page) as the person edited it before approving: that text is shown; the agent
    proposes again only when its evidence changes, compared with this text (what of it a proposal drops is listed)."""
    p = db.session.get(ContextPage, page_id)
    if p is None:
        raise ValueError("no such page")
    if action not in ("approve", "reject"):
        raise ValueError("approve or reject")
    if not (p.proposed_content or p.proposed_drop or not p.reviewed_by):
        raise ValueError("nothing to review on this page")
    now = dt.datetime.utcnow()
    if action == "approve" and p.proposed_drop:
        db.session.delete(p)
        db.session.commit()
        return {"removed": page_id}
    edited = (content or "").strip() or None
    if edited is not None and len(edited) > 200_000:
        raise ValueError("the page is too long (200,000 characters at most)")
    if action == "approve" and p.proposed_content:
        p.content, p.sources, p.kind = edited or p.proposed_content, p.proposed_sources or [], p.proposed_kind or p.kind
        p.input_hash, p.version, p.updated_at = p.proposed_hash, (p.version or 0) + 1, now
        p.edited_by = by if edited is not None and edited != p.proposed_content.strip() else None
    elif action == "approve" and edited is not None and edited != (p.content or "").strip():
        p.content, p.version, p.updated_at, p.edited_by = edited, (p.version or 0) + 1, now, by   # a new page edited
    elif action == "reject" and p.proposed_drop:
        p.author = by                                   # kept by a person: the agent leaves it alone
    refused = p.proposed_hash if action == "reject" and p.proposed_content else (p.compared or {}).get("rejected_hash")
    if action == "reject" and not p.proposed_content and not p.proposed_drop:
        p.kind = REJECTED                               # a new page refused: neither shown nor searched; the agent
        refused = p.input_hash                          # proposes it again (to review) when its evidence changes
    p.proposed_content = p.proposed_sources = p.proposed_kind = p.proposed_hash = None
    p.compared = {"rejected_hash": refused} if refused else None
    p.proposed_at, p.proposed_drop = None, False
    p.reviewed_by, p.reviewed_at = by, now
    db.session.commit()
    return {"page": p.id, "version": p.version, "reviewed_by": by, "edited": p.edited_by == by}


def proposals() -> list[dict[str, Any]]:
    """The pages with a change or a removal waiting, and the new pages nobody reviewed yet (for To review)."""
    out = []
    for p in db.session.query(ContextPage).order_by(ContextPage.section, ContextPage.title):
        refused = p.kind == REJECTED
        if p.proposed_content or p.proposed_drop or (not refused and not p.reviewed_by and
                                                     (p.author or "agent") == "agent"):
            c = p.compared or {}
            what = "remove" if p.proposed_drop else "new" if refused or not p.proposed_content else "change"
            text = (p.proposed_content if refused else p.content) or ""
            out.append({"id": p.id, "section": p.section, "title": p.title, "slug": p.slug, "what": what,
                        "diff": diff_rows(p.content or "", "" if what == "remove" else p.proposed_content or "")
                        if what != "new" else diff_rows("", text), "rejected_before": refused,
                        "content": text, "proposed": p.proposed_content or "",
                        "added": c.get("added") or [], "obsolete": c.get("obsolete") or [],
                        "left_out": c.get("left_out") or [], "replaced": c.get("replaced") or 0,
                        "proposed_at": p.proposed_at, "version": p.version})
    return out


# --------------------------------------------------------------------------- #
# the build
# --------------------------------------------------------------------------- #
def build_context(reason: str = "manual", llm: bool = True, force: bool = False) -> dict[str, Any]:
    """One Context build (a run of kind "context"); returns its summary."""
    from supagent.knowledge.learner import Steps, _start_run, running_run
    from supagent.knowledge.stopping import LearningStopped, check, watching
    from supagent.llm import background, llm_task

    busy = running_run()
    run_id = _start_run(reason, kind="context") if busy is None else None
    if run_id is None:
        busy = busy or running_run()
        return {"run": busy.id if busy else None, "status": "skipped",
                "reason": f"run {busy.id} is still {busy.status}" if busy else "another run started at the same time"}
    stats: dict[str, Any] = {}
    steps = Steps(run_id, stats)
    status, error = "done", None
    t0 = time.time()
    try:
        with background(), watching(run_id), llm_task("context", run_id=run_id):
            steps.begin("collect what the team shares")
            ev = collect()
            steps.end(databases=len(ev["databases"]), documents=len(ev["docs"]), catalog_entries=len(ev["entries"]),
                      team_memory=len(ev["memory"]), helpful_answers=len(ev["answers"]),
                      inventory=len(ev["inventory"]), relations=len(ev["relations"]))
            boards: list[dict[str, Any]] = []
            if settings.get("charts.scan"):              # the team's charts (0.7): their data, what they show
                from supagent.knowledge import charts as K

                steps.begin("charts: their last day against the weeks before (no LLM)")
                try:
                    steps.end(**K.scan_isolated(run_id))
                except LearningStopped:
                    raise
                except Exception as ex:  # pylint: disable=broad-except   (the rest of the build goes on)
                    db.session.rollback()
                    steps.end(error=f"{type(ex).__name__}: {str(ex)[:300]}")
                if llm:
                    steps.begin("charts: what they show (LLM)")
                    try:
                        from supagent.llm import LLM

                        steps.end(**K.understand(LLM()))
                    except LearningStopped:
                        raise
                    except Exception as ex:  # pylint: disable=broad-except
                        db.session.rollback()
                        steps.end(error=f"{type(ex).__name__}: {str(ex)[:300]}")
                try:
                    boards = K.dashboard_pages()
                except Exception:  # pylint: disable=broad-except
                    db.session.rollback()
                    log.warning("supagent context: dashboard pages", exc_info=True)
            keep: set[tuple[str, str]] = set()
            steps.begin("facts pages (no LLM)")
            done: dict[str, int] = defaultdict(int)
            for page in fact_pages(ev) + boards:
                check()
                keep.add((page["section"], page["slug"]))
                done[save_page(page, "facts", _hash([page["title"], page["content"], page["database_ids"]]))] += 1
            steps.end(**done)
            specs = summary_specs(ev)
            keep |= {(s["section"], s["slug"]) for s in specs}
            if llm:
                budget = int(settings.get("context.max_llm_calls"))
                steps.begin("summary pages (LLM)")
                res: dict[str, int] = defaultdict(int)
                failed: list[str] = []
                client = None
                for spec in specs:
                    check()
                    h = _hash([PROMPT, spec["title"], spec["brief"], spec["evidence"]])
                    p = (db.session.query(ContextPage).filter(ContextPage.section == spec["section"],
                                                              ContextPage.slug == spec["slug"]).one_or_none())
                    if p is not None and (p.author or "agent") != "agent":
                        res["kept"] += 1
                        continue
                    if p is not None and p.input_hash == h and p.content and not force:
                        res["unchanged"] += 1
                        continue
                    if p is not None and p.proposed_hash == h and p.proposed_content and not force:
                        res["waiting"] += 1                   # its proposal waits for a person: no LLM call again
                        continue
                    if p is not None and (p.compared or {}).get("rejected_hash") == h and not force:
                        res["rejected"] += 1                  # a person refused this version: no LLM call again
                        continue
                    if not spec["evidence"]:
                        continue
                    if res["llm_calls"] >= budget:
                        res["left"] += 1
                        continue
                    if client is None:
                        from supagent.llm import LLM

                        client = LLM()
                    db.session.commit()                       # no connection held during the LLM call
                    try:
                        out = write_summary(spec, client)
                    except LearningStopped:
                        raise
                    except Exception as ex:  # pylint: disable=broad-except   (the other pages are written)
                        db.session.rollback()
                        res["llm_calls"] += 1
                        res["failed"] += 1
                        failed.append(f"{spec['title']}: {type(ex).__name__}: {str(ex)[:200]}")
                        log.warning("supagent context: the page %s was not written: %s", spec["title"], ex)
                        steps.update(**res)
                        continue
                    res["llm_calls"] += 1
                    res["tokens"] += out["tokens"]
                    if not out["content"]:
                        res["empty"] += 1
                        continue
                    if out.get("cut"):
                        res["cut"] += 1                       # saved as it is, written again at the next build
                    res[save_page({**spec, "content": out["content"], "sources": out["sources"]}, "summary",
                                  _hash([h, "cut"]) if out.get("cut") else h, 1, out["tokens"])] += 1
                    steps.update(**res)
                steps.end(**res, **({"failed_pages": failed[:12]} if failed else {}))
                if res.get("left") or failed:
                    status = "partial"
                if failed:
                    error = "pages not written (the next build tries again): " + "; ".join(failed)[:1400]
            steps.begin("pages of subjects gone")
            steps.end(dropped=drop_pages(keep))
            from supagent.knowledge.index import embed_pending, sync

            steps.begin("search index")
            written = sync(("context:",))
            if written["added"] + written["changed"]:
                try:                                  # found by meaning from the next question on
                    written["embedded"] = embed_pending().get("embedded", 0)
                except Exception as ex:  # pylint: disable=broad-except   (words meanwhile; hourly)
                    db.session.rollback()
                    log.warning("supagent context: vectors: %s", ex)
            steps.end(**written)
    except LearningStopped:
        db.session.rollback()
        status, error = "stopped", "stopped by an admin"
        steps.interrupted("stopped by an admin")
    except Exception as ex:  # pylint: disable=broad-except
        db.session.rollback()
        log.exception("supagent context: build %s failed", run_id)
        status, error = "error", f"{type(ex).__name__}: {str(ex)[:1500]}"
        steps.interrupted(error)
    stats["seconds"] = round(time.time() - t0, 1)
    run = db.session.get(Run, run_id)
    run.status, run.error, run.stats, run.finished_at = status, error, stats, dt.datetime.utcnow()
    db.session.commit()
    return {"run": run_id, "status": status, "error": error, **stats}


def build_then_classify(reason: str = "manual", llm: bool = True, force: bool = False) -> dict[str, Any]:
    """A Context build, then the classification on what it wrote (context.classify_after): the categories of the
    items, the part-of of the values and the interactions are read from the Context pages, the documents, the
    metrics and the data of that night. The build's own summary, with the classification's under
    "classification"."""
    out = build_context(reason=reason, llm=llm, force=force)
    if llm and settings.get("context.classify_after") and out.get("status") != "skipped":
        from supagent.knowledge.learner import run_classification

        try:
            out["classification"] = run_classification(reason="after the Context")
        except Exception as ex:  # pylint: disable=broad-except   (the build is done: kept)
            db.session.rollback()
            log.exception("supagent: the classification after the Context")
            out["classification"] = {"status": "error", "error": str(ex)[:300]}
    return out


def classify_follows() -> bool:
    """The categories wait for tonight's Context: it is built every night, the classification follows it, and
    no build is done yet today (the nightly learning then leaves the categories to it)."""
    if not (settings.get("context.enabled") and settings.get("context.classify_after")):
        return False
    now = dt.datetime.now()
    start_of_day_utc = dt.datetime.utcnow() - (now - now.replace(hour=0, minute=0, second=0, microsecond=0))
    done = (db.session.query(Run.id).filter(Run.kind == "context", Run.started_at >= start_of_day_utc,
                                            Run.status.in_(("done", "partial"))).first())
    return done is None


def context_due(now: dt.datetime | None = None) -> bool:
    """The nightly build is due: enabled, its hour has come, none done today, none running."""
    from supagent.knowledge.learner import running_run

    if not settings.get("context.enabled"):
        return False
    now = now or dt.datetime.now()
    if now.hour < int(settings.get("context.hour")):
        return False
    if running_run() is not None:
        return False
    start_of_day_utc = dt.datetime.utcnow() - (now - now.replace(hour=0, minute=0, second=0, microsecond=0))
    today = db.session.query(Run).filter(Run.kind == "context", Run.started_at >= start_of_day_utc).all()
    return not any(r.status in ("done", "partial") for r in today) and len(today) < 3


# --------------------------------------------------------------------------- #
# who sees what
# --------------------------------------------------------------------------- #
def visible_pages() -> list[ContextPage]:
    """The pages the current user may read: every database of a page must be one they may query."""
    from supagent.security import visible_databases

    dbs = visible_databases()
    return [p for p in db.session.query(ContextPage).order_by(ContextPage.section, ContextPage.title)
            if set(p.database_ids or []) <= dbs and p.kind != REJECTED]


# --------------------------------------------------------------------------- #
# the Context as a book (0.9.6): parts, chapters, numbers, a summary, related pages
# --------------------------------------------------------------------------- #
CHAPTERS = (   # (part, chapter title, the slugs it takes: exact, or a prefix ending with "-")
    ("functional", "Overview", ("overview",)),
    ("functional", "Applications", ("application-",)),
    ("functional", "Glossary, rules and facts", ("glossary", "rules-and-facts")),
    ("technical", "Architecture", ("architecture",)),
    ("technical", "Data sources", ("data-sources-",)),
    ("technical", "Inventories", ("inventory-",)),
    ("technical", "Links between data sources", ("links-",)),
    ("technical", "Dashboards", ("dashboard-", "dashboards")),
)
PARTS = (("functional", "Functional"), ("technical", "Technical"))
RELATED = 5               # related pages listed per page at most


def _chapter_of(p: ContextPage) -> int:
    slug = p.slug or ""
    for i, (part, _title, slugs) in enumerate(CHAPTERS):
        if part == p.section and any(slug == s or (s.endswith("-") and slug.startswith(s)) for s in slugs):
            return i
    return len(CHAPTERS) + (0 if p.section == "functional" else 1)      # "Other pages" of its part


def subject(p: ContextPage) -> str:
    """What a page is about, as a name other pages would write: an application's, a data source's ("Application
    BILLING" -> "BILLING", "Data source: Lab (osagg)" -> "Lab (osagg)")."""
    title = p.title or ""
    m = re.match(r"^(?:application|data source|inventory|dashboard)\s*:?\s*(.+)$", title, re.I)
    return (m.group(1) if m else "").strip()


def lead(markdown: str, chars: int = 220) -> str:
    """The first sentence of a page's first paragraph (headings, lists' marks and citations left out)."""
    for block in re.split(r"\n\s*\n", markdown or ""):
        lines = [ln for ln in block.strip().splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "|"))]
        if not lines:
            continue
        text = " ".join(re.sub(r"\[E\d+\]|\*\*|__|`|^[-*+>]\s+|^\d+[.)]\s+", "", ln.strip()) for ln in lines)
        text = " ".join(text.split())
        m = re.match(r"(.{8,}?[.!?])(\s|$)", text)
        out = m.group(1) if m else text
        return out[:chars].rstrip() + ("..." if len(out) > chars else "")
    return ""


def related_pages(pages: list[ContextPage]) -> dict[int, list[int]]:
    """For each page, the pages most related to it: the same sources (documents, catalog entries), the same databases,
    a page naming the other's subject (an application, a data source); the strongest first, RELATED at most."""
    score: dict[int, dict[int, float]] = {p.id: {} for p in pages}
    refs = {p.id: {str(s.get("ref")) for s in (p.sources or []) if isinstance(s, dict) and s.get("ref")} for p in pages}
    dbs = {p.id: set(p.database_ids or []) for p in pages}
    names = {p.id: subject(p).lower() for p in pages}
    texts = {p.id: (p.content or "").lower() for p in pages}
    for a in pages:
        for b in pages:
            if a.id == b.id:
                continue
            s = 0.0
            shared = refs[a.id] & refs[b.id]
            if shared:
                s += min(3.0, 0.5 * len(shared))
            if dbs[a.id] and dbs[a.id] == dbs[b.id]:
                s += 1.5
            elif dbs[a.id] & dbs[b.id]:
                s += 0.75
            if names[b.id] and len(names[b.id]) >= 3 and names[b.id] in texts[a.id]:
                s += 2.0                                  # a names b's subject
            if names[a.id] and len(names[a.id]) >= 3 and names[a.id] in texts[b.id]:
                s += 1.0
            if s:
                score[a.id][b.id] = s
    return {pid: [b for b, _s in sorted(sc.items(), key=lambda kv: (-kv[1], kv[0]))[:RELATED]]
            for pid, sc in score.items()}


def book(pages: list[ContextPage]) -> dict[str, Any]:
    """The pages as a book: {"parts": [{"title", "chapters": [{"number", "title", "pages": [{"number", "page"}]}]}],
    "numbers": {page id: "2.3"}, "related": {page id: [ids]}, "summary": Markdown}. Chapters in the order of
    CHAPTERS (pages of no chapter last, as "Other pages"), numbered across the book."""
    by_chapter: dict[int, list[ContextPage]] = {}
    for p in pages:
        by_chapter.setdefault(_chapter_of(p), []).append(p)
    parts, numbers, n = [], {}, 0
    for key, part_title in PARTS:
        chapters = []
        keys = [i for i, c in enumerate(CHAPTERS) if c[0] == key] + [len(CHAPTERS) + (0 if key == "functional" else 1)]
        for i in keys:
            mine = sorted(by_chapter.get(i) or [], key=lambda p: (p.title or "").lower())
            if not mine:
                continue
            n += 1
            title = CHAPTERS[i][1] if i < len(CHAPTERS) else "Other pages"
            entries = []
            for k, p in enumerate(mine, start=1):
                numbers[p.id] = f"{n}.{k}"
                entries.append({"number": f"{n}.{k}", "page": p})
            chapters.append({"number": str(n), "title": title, "pages": entries})
        if chapters:
            parts.append({"title": part_title, "chapters": chapters})
    lines = [f"This book holds {len(pages)} page{'s' if len(pages) != 1 else ''} of the system's Context in "
             f"{n} chapter{'s' if n != 1 else ''}: what the system is functionally (its applications, the team's words, "
             "rules and facts) and technically (its architecture, data sources, inventories and the links between them), "
             "written from the team's knowledge (documents, catalog, team memory, data dictionary). Pages marked "
             "AI-written were written by the agent from that knowledge: check them before relying on them.", ""]
    for part in parts:
        lines.append(f"## {part['title']}")
        lines.append("")
        for ch in part["chapters"]:
            lines.append(f"**{ch['number']} {ch['title']}**")         # a chapter, then its pages, each in a line
            lines.append("")
            for e in ch["pages"]:
                gist = lead(e["page"].content or "")
                lines.append(f"- {e['number']} {e['page'].title}" + (f": {gist}" if gist else ""))
            lines.append("")
    return {"parts": parts, "numbers": numbers, "related": related_pages(pages), "summary": "\n".join(lines).strip()}
