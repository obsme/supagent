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
from collections import Counter, defaultdict
from typing import Any

from superset import db

from supagent import settings
from supagent.models import ContextPage, Doc, Entry, KFact, KObject, KUnit, Memory, Recipe, Relation, Run, Source

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
DOC_CHARS = 3000           # of each document in an LLM prompt (at least; a wiki of many pages: its digest, below)
DOCS_CHARS = 30000         # (0.10.12) of all the documents of a summary page: a wiki of thousands of pages gives its
DIGEST_LEAD = 160          #   central pages (the most linked to) with their first lines (0.10.12.1: ~100 of them; a
                           #   share by number of pages, not the same for every document)
DIGEST_DOCS = 6            # documents in a summary page's evidence (the ones with the most pages first)
DATED_HEAD = " and the day it was last changed"     # (0.11.5) a digest whose pages say their day (the writer's
#                                                     RECENCY rule given with it)
SPACE_MIN_PAGES = 200      # (0.11.5) a wiki space this big (read since 0.11.4: its pages say their parents) has a summary
SPACE_PAGES_MAX = 6        #   page of its own, its subjects in turns (the biggest spaces first, so many at most)
SPACE_BRIEF = ("Explain what this wiki space documents, for a newcomer (## Subjects: one table, a row per subject of "
               "the space: subject, what it is, what holds now (its owner, hosts, versions, schedules, as the most "
               "recent pages say; where a page's own text says since when something holds, what that replaced and "
               "since when, with that day); ## Where to read more: its main pages, by their titles).")
#                            (0.11.5: no dated list of changes: it gave routine page updates wrong years)
DIGEST_BRANCH = 3          # (0.11.4) pages a branch of a document's tree needs to be a subject of its digest (fewer:
#                            with its other pages)
STALE_TITLE = re.compile(r"\b(?:archived|deprecated|obsolete|outdated)\b", re.I)    # (0.11.4) a page that says (0.11.5:
#                                                                        not "legacy": a legacy system is still there)
STALE_LEAD = re.compile(r"^\W*(?:archived|deprecated|obsolete|outdated)\b|\b(?:this|the)\s+(?:page|document|article|"
                        r"content)\s+(?:is|was|has\s+been)\s+(?:now\s+)?(?:archived|deprecated|obsolete|outdated|"
                        r"superseded|no\s+longer\s+(?:maintained|valid|accurate|up\s+to\s+date))|\bsuperseded\s+by\b",
                        re.I)      # it describes the past (its title, or a banner in its first lines)
MONTHS = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|"
          r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?")                   # (a month's name, not "decision")
CHANGE_LEAD = re.compile(        # (0.11.4) first lines that say since when something holds: "since 12 March 2026",
    r"\b(?:since|as\s+of|from|starting|effective)\s+(?:(?:the\s+)?\d{1,2}(?:st|nd|rd|th)?\s+" + MONTHS + r"\s+\d{4}|"
    + MONTHS + r"\s+\d{1,2},?\s+\d{4}|" + MONTHS + r"\s+\d{4}|(?:199\d|20[0-3]\d)(?:-\d{2}){0,2})\b|"   # "as of
    r"\bfrom\s+now\s+on\b", re.I)  # 2026-03" (a year: not "from 8443 to 8080"), "from now on" (a change's verbs alone,
#                                  "no longer", "upgraded": in release notes and meeting notes as often: not said apart)
PART_RELATIONS = 80        # (0.10.12) the relations the documents and the code state (calls, uses, runs on...) given
RELATIONS_POOL = 600       #   to the summaries, the most stated first; an application's page: its own, from the pool
RELATION_VERBS = {"calls": "calls", "sends_to": "sends data to", "reads_from": "reads from", "uses": "uses",
                  "runs_on": "runs on", "depends_on": "depends on", "connects_to": "connects to",
                  "owned_by": "is owned by", "collects": "collects the logs of", "scrapes": "scrapes",
                  "monitors": "monitors", "powered_by": "is powered by", "part_of": "is part of",
                  "routes_to": "routes to", "writes": "writes", "logs_to": "logs to", "emits": "emits",
                  "watched_by": "is watched by", "in_group": "is in the server group"}
INFRA_VERBS = {"runs_on", "connects_to", "powered_by", "part_of", "routes_to", "in_group", "depends_on"}   # (0.11.0)
DESC_CHARS = 1200          # of a main index's or metric's description on its page (cut after a whole sentence)
FIELDS_OF = 3              # the main indices and metrics whose fields or labels a data source's page lists
FIELD_CHARS = 240          # of a field's description on that list
FORMULA_CHARS = 800        # of a formula on a data source's page
SUMMARY_TOKENS = 3000      # of an LLM summary page; cut by that limit, it is asked to go on (CONTINUATIONS times)
CONTINUATIONS = 2
LLM_CONTEXT_SLUGS = ("llm-context", "llm-context-light")   # (0.10.9.1) the LLM context's two versions
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
evidence given as JSON (documents, catalog entries, team memory, data dictionary, questions people asked, the
relations the documents state). Write for a new member of the team who must understand the system quickly.
Rules: use only this evidence, never invent a name, a number, a link or a dependency; when the evidence does
not say, write "not known yet". Start with a short paragraph "In short" (two or three sentences: what it is and
why it matters), then the sections asked, each opening with its main point. Explain how things work and why,
in sentences; group what belongs together; define a term the first time it is used and keep one name for one
thing. Say the chains between parts in words (A sends to B, which stores in C): the relations diagram is added
to the page by the system, so draw none yourself. Leave out what does not help understanding: counts of
objects, documents or pages, sizes, identifiers, long lists of names (metrics, fields, indices, servers, values:
name the few that matter and say where the others are, the Data dictionary or the Inventory pages), and
repetitions: say a thing once, where it belongs.
Name each part as the evidence names it, the same way every time. Cite the evidence you use as [E1], [E2]...
(only the ids given) once per paragraph and after each table, not after every sentence. Use ## headings, short
paragraphs, bullet lists, and a Markdown table where several things are compared on the same points (one row
each) instead of a list repeated per group; no HTML, no code fences unless quoting a query. Write in the language
of most of the evidence. The page: {title}. {brief}"""
# (0.11.5) given only to a page whose evidence says the day its pages were last changed (the prompt is part of a page's
# hash: a page without such evidence is not written again for it)
RECENCY = """Where two sources disagree (an owner, a host, a version, a port, a schedule...) and the evidence gives the
day each was last changed, follow the most recent one, say what it replaced and since when, and never give the older
statement as the current one; a page that says it is archived or superseded describes the past. Never guess from
what is usual or likely: where the most recent page does not settle it, say that the pages disagree and give each
statement with its day; and do not write these rules on the page. """
#                     (0.11.5: "never guess": a page reasoned "given typical feature store patterns, we assume ...")
DIAGRAM_EDGES = 30         # (0.11.0) relations drawn on a summary page's diagram at most (the most stated first)
DIAGRAM_HEAD = "diagram: relations"     # the first line of the block the pages draw (dictionary.js: S.diagrams)


QUALIFIED = re.compile(r"\s*\([^()]*\)$")     # a name's qualifier in parentheses ("payment_vms (infra prod)")
DIAGRAM_NODES = 24         # (0.11.1) parts drawn on a diagram at most (the page drops the edges beyond 40 unsaid)


def part_key(name: str) -> str:
    """(0.11.1) One part however it is written: "Checkout API", "checkout_api", "checkout-api (prod)" are one."""
    return " ".join(re.sub(r"[_\-\s]+", " ", QUALIFIED.sub("", str(name or "")).lower()).split())


def diagram_block(rels: list[dict[str, Any]], limit: int = DIAGRAM_EDGES) -> str:
    """(0.11.0) The relations the documents and the code state, as a block the Context page draws as a diagram (and
    any other reader reads as lines: "A -> B : calls"), the most stated first; "" when there are fewer than two.
    (0.11.1) One box per part: its spellings (case, "_" or "-", a qualifier) are one name, the plain one the documents
    use most; what a part does to another is one line ("A -> B : calls, reads from"); a part is never drawn as using
    itself; DIAGRAM_NODES parts at most (the most stated relations first)."""
    names: dict[str, str] = {}
    pairs: dict[tuple[str, str], list[str]] = {}
    clean = [(" ".join(str(r["a"]).split())[:60], " ".join(str(r["b"]).split())[:60], r["verb"]) for r in rels]
    clean = [(a, b, v) for a, b, v in clean if a and b and "->" not in a and "->" not in b]
    for a, b, _v in clean:                            # the plain spelling first seen (the most stated): its name
        for x in (a, b):
            k = part_key(x)
            if k and (k not in names or (QUALIFIED.search(names[k]) and not QUALIFIED.search(x))):
                names[k] = x
    for a, b, verb in clean:
        ka, kb = part_key(a), part_key(b)
        if not ka or not kb or ka == kb:
            continue
        if (ka, kb) not in pairs:
            drawn = {k for pair in pairs for k in pair}
            if len(pairs) >= limit or len(drawn | {ka, kb}) > DIAGRAM_NODES:
                continue
            pairs[(ka, kb)] = []
        said = RELATION_VERBS.get(verb, verb)
        if said not in pairs[(ka, kb)]:
            pairs[(ka, kb)].append(said)
    if len(pairs) < 2:
        return ""
    lines = [f"{names[ka]} -> {names[kb]} : {', '.join(verbs)}" for (ka, kb), verbs in pairs.items()]
    return "```text\n" + DIAGRAM_HEAD + "\n" + "\n".join(lines) + "\n```"


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
    from supagent.knowledge.values import learned_whole

    for kind, name in items:
        rows = (db.session.query(KObject).filter(KObject.source_id == source_id, KObject.parent == name,
                                                 KObject.kind == ("label" if kind == "metric" else "field"),
                                                 KObject.gone_at.is_(None)).all())
        if not rows:
            continue
        sampled = False                    # (0.10.9) an index learned on a sample: its fields' values are a sample
        if kind != "metric":
            ix = db.session.query(KObject).filter(KObject.source_id == source_id, KObject.kind == "index",
                                                  KObject.name == name, KObject.gone_at.is_(None)).first()
            sampled = not learned_whole((ix.stats or {}) if ix is not None else {})

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
                          "values": [str(v) for v in vals[:12]] if few else [],
                          "sampled": sampled or bool(st.get("partial"))})
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
                            "content": d.content or "",
                            "pages": [p for p in (d.pages or []) if isinstance(p, dict)]})   # (0.10.12) its digest
    out["part_relations"] = _part_relations()
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
                             + (f"{' ' if x['about'] else ': '}"
                                + ("Values seen in a sample (others may exist): " if x.get("sampled") else "Values: ")
                                + f"{', '.join(x['values'])}." if x["values"] else ""))
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
def _part_relations(limit: int = RELATIONS_POOL) -> list[dict[str, Any]]:
    """(0.10.12) What the documents and the code state about the parts (the understanding's facts: A calls B, runs on
    C...), the most stated first: [{"a", "verb", "b", "pages"}], the pages being the units (wiki pages, files) that
    state it. A summary was written from the documents' first lines and never saw them."""
    from sqlalchemy import func

    try:
        n = func.count(func.distinct(KFact.unit_id))
        rows = (db.session.query(KFact.subject, KFact.verb, KFact.obj, n)
                .join(KUnit, KUnit.id == KFact.unit_id).join(Doc, Doc.id == KUnit.doc_id)
                .filter(Doc.enabled.is_(True), KFact.verb.in_(list(RELATION_VERBS)))
                .group_by(KFact.subject, KFact.verb, KFact.obj).order_by(n.desc()).limit(limit * 3).all())
    except Exception:  # pylint: disable=broad-except   (no understanding yet: the summaries as before)
        db.session.rollback()
        log.warning("supagent context: the relations stated in the documents", exc_info=True)
        return []
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for a, verb, b, count in rows:
        a, b = " ".join(str(a or "").split()), " ".join(str(b or "").split())
        if not a or not b or a.lower() == b.lower():
            continue
        key = (a.lower(), verb, b.lower())
        r = merged.setdefault(key, {"a": a, "verb": verb, "b": b, "pages": 0})
        r["pages"] += int(count or 0)
    return sorted(merged.values(), key=lambda r: (-r["pages"], r["a"].lower(), r["b"].lower()))[:limit]


def _relation_lines(rels: list[dict[str, Any]]) -> list[str]:
    """The relations as sentences, the most stated first; (0.11.1) without how many pages state each (a count the
    pages repeated: "stated by 9 pages")."""
    return [f"{r['a']} {RELATION_VERBS.get(r['verb'], r['verb'])} {r['b']}" for r in rels]


def _shares(chosen: list[dict[str, Any]]) -> dict[int, int]:
    """(0.10.12.1) Each document's room in a summary page: a small one its text (DOC_CHARS at most), the ones of many
    pages the rest in proportion to their pages (DOC_CHARS at least): a wiki of 5,000 pages had the room of a page of
    three, about nine of its pages."""
    def small(d: dict[str, Any]) -> bool:
        return len(d.get("pages") or []) < 3 or len(d.get("content") or "") <= DOC_CHARS

    big = [d for d in chosen if not small(d)]
    if not big:
        return {d["id"]: max(DOC_CHARS, DOCS_CHARS // max(1, len(chosen))) for d in chosen}
    out = {d["id"]: min(len(d.get("content") or ""), DOC_CHARS) for d in chosen if small(d)}
    left = max(DOCS_CHARS - sum(out.values()), DOC_CHARS * len(big))
    pages = sum(len(d["pages"]) for d in big)
    out.update({d["id"]: max(DOC_CHARS, int(left * len(d["pages"]) / pages)) for d in big})
    return out


def _place(p: dict[str, Any]) -> tuple[str, ...] | None:
    """(0.11.4) A page's place in its document's tree, from the top: a wiki page its parents and itself (Confluence's
    ancestors, kept since 0.11.4: a wiki read before has none until its next reading), a repository's file its folders
    and itself, a site's page the folders of its address and itself; None: not known."""
    if p.get("id"):
        parents = p.get("ancestors")
        return tuple(str(x) for x in parents) + (str(p["id"]),) if isinstance(parents, list) else None
    if p.get("path"):
        return tuple(x for x in str(p["path"]).split("/") if x) or None
    from urllib.parse import urlparse

    return tuple(x for x in urlparse(str(p.get("url") or "")).path.split("/") if x) or None


def _top_first(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """(0.11.5) A wiki page's parents from the top, whatever the order its source gives them: the parents that are
    pages of the document say their depth (how many parents they have); a list that goes from the page up is turned
    round (a copy: the document's pages are not changed)."""
    depth = {str(p["id"]): len(p["ancestors"]) for p in pages if p.get("id") and isinstance(p.get("ancestors"), list)}
    out = []
    for p in pages:
        parents = p.get("ancestors")
        if isinstance(parents, list) and len(parents) > 1:
            known = [depth[str(x)] for x in parents if str(x) in depth]
            if len(known) > 1 and known[0] > known[-1]:
                p = {**p, "ancestors": list(reversed(parents))}
        out.append(p)
    return out


def _branches(pages: list[dict[str, Any]]) -> list[tuple[tuple[str, ...] | None, list[dict[str, Any]]]]:
    """(0.11.4) A document's pages as its subjects: in each space, the branches where its tree first splits into
    several of DIGEST_BRANCH pages or more (a wiki's page trees under its space's home, a repository's or a site's
    folders), the biggest first (of one size: in the reading's order). The pages at the top of the tree that are no
    subject's (a space's home, a repository's README next to its folders): first (key ()); the pages of a smaller
    branch below them, and the ones whose place is not known: last (key None). [(the branch's place, its pages)]."""
    spaces: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in pages:
        spaces[str(p.get("space") or "")].append(p)
    found: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    top: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    for space, mine in spaces.items():
        placed = [(p, _place(p)) for p in mine]
        level = 0
        while True:                                   # down while one node alone holds pages below it (a space's home,
            below = Counter(x[level] for _p, x in placed if x and len(x) > level + 1)      # a repository's src/)
            if sum(1 for c in below.values() if c >= DIGEST_BRANCH) != 1:
                break
            level += 1
        for p, x in placed:
            if x and len(x) > level:
                found.setdefault((space,) + x[:level + 1], []).append(p)
            else:
                (top if x else rest).append(p)
    out: list[tuple[tuple[str, ...] | None, list[dict[str, Any]]]] = []
    for key, mine in sorted(found.items(), key=lambda kv: -len(kv[1])):     # (of one size: in the reading's order)
        if len(mine) >= DIGEST_BRANCH:
            out.append((key, mine))
        else:                                         # a small branch: its own page at the top, the others last
            for p in mine:
                (top if len(_place(p) or ()) == len(key) - 1 else rest).append(p)
    return ([((), top)] if top else []) + out + ([(None, rest)] if rest else [])


def _digest(d: dict[str, Any], chars: int, by_branch: bool = False) -> str:
    """(0.10.12) What a summary page reads of a document: a small one, its beginning; one of many pages (a wiki, a
    repository), each with its first lines, up to `chars`: what thousands of pages are about, not their first page.
    (0.11.4) Each of its subjects (_branches: the branches of its tree, a wiki's page trees, a repository's folders)
    has its room, in turns, not only the few most linked to (a wiki of many subjects was summarized by the few its
    other pages link to most): its own page first, then its most linked and its latest pages in turn (the latest that
    say since when something holds first), a page that says it is archived or superseded last; the pages at the top
    that are no subject's first (a space's home, a repository's README); each page with the day its source says it
    was last changed, so that the summary follows the latest where pages disagree. A wiki read before 0.11.4 (no
    parents yet), a site of one folder: its central pages first (the ones its other pages link to most), as before,
    dated when known.
    (0.11.5) By subject (by_branch) only for a wiki space's own summary page (_space_specs); the overviews read every
    document as up to 0.11.4 (_flat)."""
    content = d.get("content") or ""
    pages = _top_first([p for p in d.get("pages") or []
                        if isinstance(p.get("at"), int) and isinstance(p.get("chars"), int)])
    if len(content) <= chars or len(pages) < 3:
        return content[:chars]
    key = lambda p: str(p.get("id") or p.get("path") or p.get("title") or p.get("url") or "")  # noqa: E731
    ids = {str(p.get("id")): key(p) for p in pages if p.get("id")}
    titles = {str(p.get("title") or "").lower(): key(p) for p in pages if p.get("title")}
    inbound: Counter = Counter()
    for p in pages:
        for x in p.get("links") or []:
            x = str(x)
            target = ids.get(x) or titles.get(x.split(":", 1)[-1].lower())     # a page's id, or "SPACE:Title"
            if target and target != key(p):
                inbound[target] += 1

    made: dict[int, tuple[str, bool, str, bool]] = {}

    def line(p: dict[str, Any]) -> tuple[str, bool, str, bool]:
        """The page's line (title, its day when known, its first lines), whether it says it describes the past, its
        title, whether its first lines say what changed (each page's once: a wiki of 50,000 pages)."""
        if id(p) not in made:
            block = content[p["at"]:p["at"] + min(p["chars"], 600 + 8 * DIGEST_LEAD)]     # its first lines only
            first, _, body = block.partition("\n")
            title = str(p.get("title") or first.lstrip("# ").strip())
            lead = " ".join((body if first.startswith("# ") else block).split())[:DIGEST_LEAD]
            day = p.get("modified")
            made[id(p)] = (f"- {title}{f' [last changed {day}]' if day else ''}: {lead}\n",   # (0.11.5: said: a
            #                                    title of a day of its own, "2025-06-18 weekly sync", was mixed with it)
                           bool(STALE_TITLE.search(title) or STALE_LEAD.search(lead)), title,
                           bool(CHANGE_LEAD.search(lead)))
        return made[id(p)]

    central = lambda p: (-inbound[key(p)], str(p.get("path") or "").count("/"),  # noqa: E731
                         len(str(p.get("title") or "")))
    read_since = any(p.get("modified") or isinstance(p.get("ancestors"), list) for p in pages)
    if not by_branch:                                 # (0.11.5) the overviews: as up to 0.11.4, to the byte
        return _flat(content, pages, chars, central)
    # (0.11.5) by subject only a wiki whose pages say their parents (read since 0.11.4): a repository or a site keeps
    # its central pages first, as before
    branches = _branches(pages) if any(isinstance(p.get("ancestors"), list) for p in pages) else [(None, pages)]
    subjects = any(place for place, _mine in branches)
    if not subjects:                                  # no subject (a wiki read before 0.11.4, a flat site): one list
        branches = [(None, pages)]
    groups: list[tuple[str, list[str]]] = []          # (its name, its lines in the order they are given room)
    for place, mine in branches:
        own = [p for p in mine if place and _place(p) == place[1:]]
        lines = [line(p) for p in own]
        rest = sorted((p for p in mine if not any(p is o for o in own)), key=central)
        latest = sorted((p for p in rest if p.get("modified")),       # the latest: the ones that say since when
                        key=lambda p: (line(p)[3], str(p["modified"])), reverse=True)    # something holds first (a
        #                                      dated change: "since 12 March 2026"), then the newest first
        taken: set[int] = set()
        ordered = []
        for i in range(max(len(rest), len(latest))):  # the latest and the most linked in turn (0.11.5: the latest
            #                                           first: in a small room, a subject's last change before the rest)
            for p in (latest[i] if i < len(latest) else None, rest[i] if i < len(rest) else None):
                if p is not None and id(p) not in taken:
                    taken.add(id(p))
                    ordered.append(p)
        if read_since:                                # what says it describes the past: last (0.11.5: a document
            lines += [line(p) for p in ordered if not line(p)[1]] + [line(p) for p in ordered if line(p)[1]]
        else:                                         # read before 0.11.4, no day nor parent: its pages as before)
            lines += [line(p) for p in ordered]
        name = lines[0][2] if own else ("/".join(place[1:]) if place and not mine[0].get("id") else
                                        lines[0][2] if place else "Top pages" if place == () else "Other pages")
        groups.append((name, [x[0] for x in lines]))
    spaces = sorted({str(p["space"]) for p in pages if p.get("space")})
    dated = DATED_HEAD if any(p.get("modified") for p in pages) else ""
    # (0.11.1) no count of its pages, nor of the pages linking to each (the summaries said "the wiki has 5,000 pages")
    head = (f"Spaces: {', '.join(spaces[:10])}. " if spaces else "") + (
        f"Its subjects (the branches of its tree), each with its own page first, then its most linked and its latest "
        f"pages, each page with its first lines{dated}:\n" if subjects else
        f"Its central pages first (the ones its other pages link to most), each with its first lines{dated}:\n")
    used, taken_lines = len(head), [0] * len(groups)
    open_ = list(range(len(groups)))
    while open_:                                      # in turns: a line of each subject, as long as there is room
        for g in list(open_):
            name, lines = groups[g]
            if taken_lines[g] >= len(lines):
                open_.remove(g)
                continue
            cost = len(lines[taken_lines[g]]) + (len(name) + 2 if subjects and not taken_lines[g] else 0)
            if used + cost > chars:
                open_.remove(g)
                continue
            used += cost
            taken_lines[g] += 1
    out = [head]
    for (name, lines), n in zip(groups, taken_lines):
        if n:
            out += ([f"{name}:\n"] if subjects else []) + lines[:n]
    return "".join(out)


def _flat(content: str, pages: list[dict[str, Any]], chars: int, central: Any) -> str:
    """(0.11.5) A document as the overviews read it, exactly as up to 0.11.4 (its central pages first, the ones its
    other pages link to most, each with its first lines): every change of it made a big wiki's subjects or its changes
    take the overview, the other documents left out (measured, 0.11.5). A big wiki's subjects and what changed are on
    its spaces' own pages (_space_specs)."""
    spaces = sorted({str(p["space"]) for p in pages if p.get("space")})
    # (0.11.1) no count of its pages, nor of the pages linking to each (the summaries said "the wiki has 5,000 pages")
    head = ((f"Spaces: {', '.join(spaces[:10])}. " if spaces else "") +
            "Its central pages first (the ones its other pages link to most), each with its first lines:\n")
    out, used = [head], len(head)
    for p in sorted(pages, key=central):
        block = content[p["at"]:p["at"] + p["chars"]]
        first, _, body = block.partition("\n")
        title = str(p.get("title") or first.lstrip("# ").strip())
        lead = " ".join((body if first.startswith("# ") else block).split())[:DIGEST_LEAD]
        line = f"- {title}: {lead}\n"
        if used + len(line) > chars:
            break
        out.append(line)
        used += len(line)
    return "".join(out)


SPACE_SUBJECTS = 40         # (0.11.5) the subjects of a space named to its page at most (the biggest branches first)


def _subject_names(pages: list[dict[str, Any]]) -> list[str]:
    """(0.11.5) The subjects of a wiki space as its tree says them: the title of each branch's own page (_branches),
    the biggest branches first."""
    out: list[str] = []
    for place, mine in _branches(_top_first(pages)):
        if not place:
            continue
        own = next((p for p in mine if _place(p) == place[1:]), None)
        title = " ".join(str((own or {}).get("title") or "").split())
        if title and title not in out:
            out.append(title)
    return out


def _space_specs(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """(0.11.5) A summary page for each big space of a wiki read since 0.11.4 (its pages say their parents;
    SPACE_MIN_PAGES pages or more; the biggest first, SPACE_PAGES_MAX at most): its subjects in turns, each page
    dated, its latest changes first (_digest by branch): what the overviews no longer hold of such a wiki."""
    found = []
    for d in ev["docs"]:
        mine: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for p in d.get("pages") or []:
            if p.get("space") and isinstance(p.get("ancestors"), list):
                mine[str(p["space"])].append(p)
        found += [(len(v), str(k), d, v) for k, v in mine.items() if len(v) >= SPACE_MIN_PAGES]
    specs = []
    for _n, space, d, pages in sorted(found, key=lambda x: (-x[0], x[1]))[:SPACE_PAGES_MAX]:
        home = next((p for p in pages if not p.get("ancestors")), None)      # the space's home: no parent
        name = str(home.get("title") or space) if home else space
        subjects = _subject_names(pages)[:SPACE_SUBJECTS]
        specs.append({"section": "functional", "slug": f"space-{slugify(space)}", "title": f"Wiki space {name}",
                      "database_ids": [], "diagram": [], "guard": {"subjects": subjects},
                      "brief": SPACE_BRIEF + (f" Its subjects (a row each): {', '.join(subjects)}." if subjects else ""),
                      "evidence": [{"ref": f"doc:{d['id']}", "title": f"{d['title']}: space {space}",
                                    "text": _digest({"content": d.get("content") or "", "pages": pages}, DOCS_CHARS,
                                                    by_branch=True)}]})
    return specs


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
    # (0.10.12) every page of every document counts (was: each document's first 20,000 characters); (0.11.0) counted
    # text by text, only the names looked for (the words of every page were held at once: GBs for a dozen wikis)
    texts = [d["content"] for d in ev["docs"]] + [a["question"] or "" for a in ev["answers"]] + \
        [e["content"] for e in ev["entries"]]
    single = {a.lower(): a for a in found if re.fullmatch(r"[\w][\w.-]*", a)}
    several = [a for a in found if a.lower() not in single]
    counts: Counter = Counter()
    for text in texts:
        for m in re.finditer(r"[\w][\w.-]*", text or ""):
            w = m.group(0).lower()
            if w in single:
                counts[single[w]] += 1
        for a in several:
            counts[a] += len(re.findall(r"(?<![\w-])" + re.escape(a) + r"(?![\w-])", text or "", re.I))
    ranked = sorted(found, key=lambda a: (-counts[a], a))
    return [a for a in ranked if counts[a]][:MAX_APPS]


def _excerpts(text: str, name: str, limit: int = 20) -> list[str]:
    lines = [ln.strip() for ln in (text or "").splitlines() if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])",
                                                                        ln, re.I)]
    return [ln[:300] for ln in lines[:limit]]


def summary_specs(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """The summary pages to write, each with its evidence (the hash of which decides whether to write it)."""
    all_dbs = sorted(ev["databases"])
    databases = [{"ref": f"database:{i}", "name": d["name"], "engine": d["backend"],      # (0.11.0) no counts of
                  "domains": list(d["categories"])[:12]} for i, d in ev["databases"].items()]   # objects: noise
    inventory = [{"ref": f"inventory:{dim}", "title": dim, "what": dim,
                  "examples": sorted({v for slot in per_db.values() for v in slot["values"]})[:25]}
                 for dim, per_db in ev["inventory"].items()]
    chosen = sorted(ev["docs"], key=lambda d: (-len(d.get("pages") or []), d["id"]))[:DIGEST_DOCS]
    shares = _shares(chosen)
    docs = [{"ref": f"doc:{d['id']}", "title": d["title"], "text": _digest(d, shares[d["id"]])} for d in chosen]
    pool = ev.get("part_relations") or []
    stated = [{"ref": "facts", "title": "what the documents and the code state about the parts (the most stated first)",
               "relations": _relation_lines(pool[:PART_RELATIONS])}] if pool else []
    entries = [{"ref": f"entry:{e['id']}", "title": e["title"], "classification": e["classification"],
                "text": e["content"][:600]} for e in ev["entries"] if e["classification"] != "formula"][:40]
    questions = [{"ref": f"recipe:{a['id']}", "title": (a["question"] or "")[:80], "question": a["question"]}
                 for a in ev["answers"]][:40]
    relations = [{"ref": "relations", "title": "relations between the data sources",
                  "links": [f"{r['a']} = {r['b']}" for r in ev["relations"][:40]]}] if ev["relations"] else []
    specs = [
        {"section": "functional", "slug": "overview", "title": "How the system works", "database_ids": all_dbs,
         "brief": "Explain what the system does for its users, its applications and their roles, the main processes "
                  "and chains between applications (who calls, uses, depends on and runs on what: the relations the "
                  "documents state, the most stated first), and where the data of each one is (## What it "
                  "does; ## Applications: one table, a row per application (application, what it does, its data), "
                  "never a list per domain; ## Processes and chains; ## Where the data is: the data sources and what "
                  "each holds, without repeating the table).",
         "evidence": docs + stated + entries + questions + databases + inventory, "diagram": pool},
        {"section": "technical", "slug": "architecture", "title": "Technical overview", "database_ids": all_dbs,
         "brief": "Describe the data sources, the infrastructure (servers, services, clusters, environments, regions), "
                  "how the data sources and the parts relate (the relations the documents state: what calls, runs on, "
                  "connects to what) and what is not known (## Data sources: one table, a row per data source "
                  "(data source, engine, what it holds); ## Infrastructure; ## Links; ## Not known yet: at most five "
                  "points, the gaps a newcomer would hit first).",
         "evidence": databases + inventory + relations + stated + docs,
         "diagram": [r for r in pool if r["verb"] in INFRA_VERBS]},
    ]
    specs += _space_specs(ev)                         # (0.11.5) a big wiki's spaces, after the overviews
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
        key = part_key(app)                         # (0.11.1) "Billing_Service (prod)" is billing-service too
        mine = [r for r in pool if key in (part_key(r["a"]), part_key(r["b"]))][:40]
        if mine:                                    # (0.10.12) its chain as the documents and the code state it
            ev_app.append({"ref": "facts", "title": f"what the documents state about {app}",
                           "relations": _relation_lines(mine)})
        holders = [{"ref": f"database:{i}", "title": ev["databases"][i]["name"], "holders": slot["holders"][:10]}
                   for i, slot in (ev["inventory"].get("Applications") or {}).items() if app in slot["values"]]
        specs.append({"section": "functional", "slug": f"application-{slugify(app)}", "title": f"Application {app}",
                      "database_ids": sorted({int(h["ref"].split(":")[1]) for h in holders}),
                      "brief": f"Explain what the application {app} is and does, what it depends on and what depends "
                               "on it (the chain), where its data is, and what people ask about it (## What it is, "
                               "## Chain, ## Its data, ## Questions people ask).",
                      "evidence": ev_app[:30] + holders, "diagram": mine})
    return specs


CONTINUE = ("Your page stopped before its end (the length limit of one answer). Go on exactly where it stopped, "
            "with the same rules: no repetition, no preamble.")
CUT_NOTE = ("*(The page stops here: the LLM's answer reached its length limit three times. The next build writes it "
            "again.)*")


def _page_text(msg: dict[str, Any]) -> str:
    """An answer's text without its reasoning, a reasoning cut before its end (no closing tag) included."""
    text = re.sub(r"<think>.*?</think>", "", (msg or {}).get("content") or "", flags=re.S)
    return re.sub(r"<think>.*\Z", "", text, flags=re.S)


# (0.11.1) what the page's checks look for in the LLM's answer, before it is saved
CITATION = re.compile(r"[ \t]?\[\s*(E\d+(?:\s*[,;]\s*E?\d+)*)\s*\]")
COUNT_NOUNS = (r"(?:servers?|hosts?|machines?|vms?|instances?|metrics?|indices|indexes|fields?|labels?|documents?|docs|"
               r"pages?|files?|objects?|entries|series|values?|dashboards?|panels?|tables?|columns?|datasets?|charts?|"
               r"repositories|repos?|wikis?|wiki spaces?|applications?|apps?|services?|components?|categories|"
               r"domains?|relations?|items?|terms?|data sources?|databases?)")
COUNT = re.compile(r"(?<![\w.:/#-])(?:(?:about|around|some|over|nearly|roughly|approximately|almost|more than|"
                   r"fewer than|less than|up to|at least)\s+)?(?:\d{1,3}(?:,\d{3})+|\d+)\s+(?:(?:distinct|different|"
                   r"unique|known|active|learned|main|other|more|separate)\s+)?(" + COUNT_NOUNS +
                   r")\b(?!\s+(?:per|each|every)\b)", re.I)
COUNT_VERB = re.compile(r"(?:\bthere\s+(?:are|is|were|was)|\b(?:has|have|had|holds?|contains?|counts?|lists?|includes?|"
                        r"totals?|numbers?|comprises?|spans?|consists\s+of|gathers?|groups?|keeps?|stores?|tracks?|"
                        r"describes?|covers?|knows?|learned|reads?))\s*$", re.I)
COUNT_PASSIVE = re.compile(r"\s+(?:are|were|is|was|have\s+been|has\s+been)\s+(?:learned|known|listed|indexed|described|"
                           r"documented|read|collected|found|defined|available|stored|tracked|monitored|referenced)\b",
                           re.I)
IN_SHORT = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*|__)?in\s+short\b", re.I)
NOT_KNOWN = re.compile(r"^#{2,6}\s*(?:what is\s+)?not\s+known\s+yet\b", re.I)
NOT_KNOWN_POINTS = 5       # the points of a page's "Not known yet" (the ones a newcomer needs first)
DRAWN_LANGS = {"mermaid", "plantuml", "puml", "dot", "graphviz"}     # a diagram drawn in the page by the LLM
DRAWN = re.compile(r"^\s*(?:graph\s+(?:TD|TB|BT|RL|LR)\b|flowchart\b|sequenceDiagram\b|classDiagram\b|erDiagram\b|"
                   r"stateDiagram|@startuml\b|digraph\b|diagram: relations\s*$)", re.I)
DRAWN_HEADING = re.compile(r"\bdiagram\b", re.I)
LIST_ITEM = re.compile(r"^\s*(?:[-*+>]\s+|\d+[.)]\s+)")      # a list's line (a paragraph may start with **bold**)
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\[*_`(\"'])")


def _without_counts(line: str) -> tuple[str, list[str]]:
    """A line of a page without its counts of objects, documents or pages: a count in parentheses left out ("the wiki
    (5,000 pages) says" -> "the wiki says"); a sentence that is a count ("There are 42 servers.", "The wiki holds 5,000
    pages [E3].") left out; a count before the names it introduces left out of the sentence ("There are 3 services:
    a, b and c." -> "The services: a, b and c."). Other figures (02:00, 30 days, port 8080) stay."""
    removed: list[str] = []

    def paren(m: re.Match) -> str:
        inner = m.group(1)
        if not COUNT.search(inner):
            return m.group(0)
        rest = re.sub(r"\b(?:about|some|over|stated|by|in|across|state|states|it|them|mentioned|and|of|the|total|all|"
                      r"read|learned|described|linked|link|to|from)\b|[,;~]", " ", COUNT.sub(" ", inner), flags=re.I)
        if rest.strip():
            return m.group(0)
        removed.append(m.group(0).strip())
        return ""

    line = re.sub(r"\s*\(([^()]{1,120})\)", paren, line)
    lead_m = re.match(r"^(\s*(?:[-*+>]\s+|\d+[.)]\s+)?)", line)
    lead = lead_m.group(1) if lead_m else ""
    kept: list[str] = []
    carried: list[str] = []                    # the sources of a sentence left out: cited by the one next to it

    def keep(sentence: str) -> None:
        kept.append(_cite_into(sentence, carried) if carried else sentence)
        carried.clear()

    for sentence in SENTENCE_END.split(line[len(lead):]):
        m = COUNT.search(sentence)
        bare = re.sub(r"^(?:\*\*|__)", "", sentence)
        if m is None or not (COUNT_VERB.search(sentence[:m.start()]) or
                             (bare.find(m.group(0)) == 0 and COUNT_PASSIVE.match(sentence[m.end():]))):
            keep(sentence)
            continue
        tail = CITATION.sub("", sentence[m.end():])
        noun = m.group(1)
        if re.match(r"\s*(?::|\(|,?\s*(?:such as|including|namely|like)\b)", tail):    # the names follow: kept
            head = sentence[:m.start()]
            there = re.match(r"^(\s*)there\s+(?:are|is|were|was)\s*$", head, re.I)
            new = (there.group(1) + "The " + noun) if there else head + noun
            keep(new + sentence[m.end():])
            removed.append(m.group(0))
            continue
        if len(re.findall(r"[^\W\d_][\w'-]*", tail)) <= 8 and not re.match(r"\s*[;,]", tail) and \
                not IN_SHORT.match(bare):                    # a count and little else: the sentence goes
            removed.append(sentence.strip())
            ids = [x.strip() for c in CITATION.finditer(sentence) for x in re.split(r"[,;]", c.group(1))]
            if kept:
                kept[-1] = _cite_into(kept[-1], ids)
            else:
                carried.extend(ids)
            continue
        keep(sentence[:m.start()] + noun + sentence[m.end():])
        removed.append(m.group(0))
    text = " ".join(s.strip() for s in kept if s.strip())
    return (lead + text if text else ""), removed


def _cite_into(sentence: str, ids: list[str]) -> str:
    """(0.11.1) `sentence` citing `ids` too, at its end (in the citation it ends with, if any)."""
    ids = [x for x in dict.fromkeys(ids) if x]
    if not ids:
        return sentence
    end = re.search(r"\s*[.!?:;]*\s*$", sentence)
    body, tail = sentence[:end.start()], sentence[end.start():]
    last = None
    for last in CITATION.finditer(body):
        pass
    if last is not None and last.end() == len(body):
        have = [x.strip() for x in re.split(r"[,;]", last.group(1))]
        space = last.group(0)[:1] if last.group(0)[:1] in " \t" else ""
        return body[:last.start()] + space + "[" + ", ".join(have + [x for x in ids if x not in have]) + "]" + tail
    return body + " [" + ", ".join(ids) + "]" + tail


def _cited_once(line: str) -> tuple[str, int]:
    """(0.11.1) A paragraph's citations, each source once: where it is cited last (the end of what it supports);
    "A [E1]. B [E1]. C [E1, E2]." -> "A. B. C [E1, E2].". How many were left out."""
    found = list(CITATION.finditer(line))
    ids = [[x.strip() for x in re.split(r"[,;]", m.group(1))] for m in found]
    last = {x: i for i, group in enumerate(ids) for x in group}
    if len(last) == sum(len(g) for g in ids):
        return line, 0
    out, at = [], 0
    for i, m in enumerate(found):
        keep = [x for x in ids[i] if last[x] == i]
        out.append(line[at:m.start()] + (m.group(0)[:1] if m.group(0)[:1] in " \t" else "") +
                   ("[" + ", ".join(keep) + "]" if keep else "") if keep else line[at:m.start()])
        at = m.end()
    out.append(line[at:])
    return "".join(out), sum(len(g) for g in ids) - len(last)


def check_page(text: str, evidence: list[dict[str, Any]], spec: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    """(0.11.1) The LLM's page checked before it is saved, as a new member of the team reads it: a citation [E#] to no
    evidence given is left out (the page's sources are E1...En); a count of objects, documents or pages left out
    (_without_counts); "In short" first (written elsewhere, or as a heading, it is moved to the top; a title repeated
    as a "# " heading is left out: the page shows its title); "Not known yet" kept to NOT_KNOWN_POINTS points. What is
    said but not changed: no "In short" at all, a `name` the evidence never gives (an invented part, maybe). Returns
    (the page, what was changed or found, for the build's steps); tables and code are left as they are."""
    notes: list[str] = []
    n = len(evidence)
    wrong: list[str] = []

    def cite(m: re.Match) -> str:
        ids = [x.strip().upper() for x in re.split(r"[,;]", m.group(1))]
        ids = [x if x.startswith("E") else "E" + x for x in ids]
        good = [x for x in ids if 1 <= int(x[1:]) <= n]
        wrong.extend(x for x in ids if x not in good)
        lead = m.group(0)[:1] if m.group(0)[:1] in " \t" else ""
        return lead + "[" + ", ".join(good) + "]" if good else ""

    counts: list[str] = []
    out: list[str] = []
    fence: list[str] | None = None
    drawn = again = 0
    for line in (text or "").splitlines():
        if fence is not None:                             # a code block: kept as written, unless it draws a diagram
            fence.append(line)
            if line.lstrip().startswith("```"):
                body = [x for x in fence[1:-1] if x.strip()]
                if fence[0].strip()[3:].strip().lower() in DRAWN_LANGS or (body and DRAWN.match(body[0])):
                    drawn += 1                            # (the page draws its own, from what the documents state)
                else:
                    out += fence
                fence = None
            continue
        if line.lstrip().startswith("```"):
            fence = [line]
            continue
        line = CITATION.sub(cite, line)
        if line.lstrip().startswith(("|", "#")) or not line.strip():
            out.append(line)
            continue
        new, removed = _without_counts(line)
        counts += removed
        line = new if removed else line
        if line and not LIST_ITEM.match(line):
            line, n_again = _cited_once(line)             # a paragraph: each source cited once, at its end
            again += n_again
        if line:
            out.append(line)
    out += fence or []                                    # a code block never closed: as written
    if wrong:
        notes.append("citations to no evidence left out: " + ", ".join(sorted(set(wrong), key=lambda x: int(x[1:]))))
    if counts:
        notes.append("counts left out: " + "; ".join(clip(c, 80) for c in counts[:5]))
    if again:
        notes.append(f"citations said again in a paragraph left out: {again}")
    blocks = re.split(r"\n\s*\n", "\n".join(out).strip())
    if blocks and re.match(r"^#\s", blocks[0]) and "\n" not in blocks[0].strip():
        blocks = blocks[1:]                                   # the page's title again: the page shows it
    if drawn:                                             # its heading, when the diagram was all its section held
        notes.append("a diagram the LLM drew left out (the page draws the relations itself)")
        level = [len(m.group(1)) if (m := re.match(r"^(#{1,6})\s", b)) and "\n" not in b.strip() else 0
                 for b in blocks]
        blocks = [b for i, b in enumerate(blocks) if not level[i] or not DRAWN_HEADING.search(b) or
                  (i + 1 < len(blocks) and (not level[i + 1] or level[i + 1] > level[i]))]
    first = next((i for i, b in enumerate(blocks) if b.strip()), None)
    if first is not None and not IN_SHORT.match(blocks[first]):
        at = next((i for i, b in enumerate(blocks) if IN_SHORT.match(b)), None)
        if at is None:
            notes.append('no "In short" paragraph')
        else:
            heading = re.compile(r"^\s*#{1,6}\s")
            moved = [blocks[at]]
            if heading.match(blocks[at]) and "\n" not in blocks[at].strip():   # a heading "In short": its paragraphs
                end = next((j for j in range(at + 1, len(blocks)) if heading.match(blocks[j])), len(blocks))
                moved = blocks[at + 1:end]
                blocks = blocks[:at] + blocks[end:]
                if moved:
                    moved[0] = "In short: " + moved[0].lstrip()
            else:
                blocks = blocks[:at] + blocks[at + 1:]
            if at and heading.match(blocks[at - 1]) and (at == len(blocks) or heading.match(blocks[at])):
                blocks = blocks[:at - 1] + blocks[at:]       # its section held only "In short": no empty heading left
            blocks = moved + blocks
            notes.append('"In short" moved first' if moved else 'no "In short" paragraph')
    page = "\n\n".join(blocks)
    lines, inside, points, dropped = page.splitlines(), False, 0, 0
    kept: list[str] = []
    for line in lines:
        if line.startswith("#"):
            inside, points = bool(NOT_KNOWN.match(line)), 0
        elif inside and re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            points += 1
            if points > NOT_KNOWN_POINTS:
                dropped += 1
                continue
        elif inside and dropped and line.startswith((" ", "\t")) and line.strip():
            continue                                          # the rest of a point left out
        kept.append(line)
    if dropped:
        notes.append(f"not known yet: {dropped} points left out")
        page = "\n".join(kept)
    unknown = unknown_names(page, evidence, spec)
    if unknown:
        notes.append("names not in the evidence: " + ", ".join(f"`{x}`" for x in unknown[:10]))
    spelled: dict[str, dict[str, str]] = defaultdict(dict)          # one part, one name (case aside)
    for found in re.findall(r"`([^`\n]{2,60})`|\*\*([^*\n]{2,60})\*\*|(?<![\w-])([^\W\d_]\w*(?:[-_]\w+)+)(?![\w-])",
                            re.sub(r"```.*?```", "", page, flags=re.S)):
        name = next(x for x in found if x).strip()
        if name and not re.fullmatch(r"E\d+", name):
            spelled[part_key(name)].setdefault(name.lower(), name)
    twice = [" / ".join(sorted(v.values())) for k, v in spelled.items() if k and len(v) > 1]
    if twice:
        notes.append("one part, several names: " + "; ".join(twice[:5]))
    if n and not re.search(r"\[E\d+", page):                 # (a reader cannot check what the page says)
        notes.append("no citation")
    return re.sub(r"\n{3,}", "\n\n", page).strip(), notes


def _prompt(spec: dict[str, Any]) -> str:
    """(0.11.5) The writer's prompt for a page: with RECENCY when its evidence gives its pages' days (DATED_HEAD)."""
    if not any(DATED_HEAD in str(item.get("text") or "") for item in spec.get("evidence") or []
               if isinstance(item, dict)):
        return PROMPT
    k = PROMPT.rindex("The page: {title}.")
    return PROMPT[:k] + RECENCY + PROMPT[k:]


HOST_LIKE = re.compile(r"(?<![\w.-])[a-z][a-z0-9]*(?:-[a-z0-9]+)*-\d+[a-z]?(?![\w-])")   # (0.11.5) srv-web-01
GUARD_ASK = ("Your page {what}. Write the whole page again with the same rules: a row for each subject of the space, "
             "and none of those names (write \"not known yet\" where the evidence does not say).")


def unknown_names(page: str, evidence: Any, spec: dict[str, Any] | None = None, hosts: bool = False) -> list[str]:
    """The names a page writes in backticks (and, with `hosts`, the host-like names it writes bare: srv-web-01) that
    its evidence never gives (its title and its brief count as evidence)."""
    said = json.dumps(evidence, ensure_ascii=False, default=str).lower() + " " + \
        " ".join(str((spec or {}).get(k) or "") for k in ("title", "brief")).lower()
    folded = re.sub(r"[_\-\s]+", " ", said)
    unknown: list[str] = []
    found = re.findall(r"`([^`\s]{3,60})`", page) + (HOST_LIKE.findall(re.sub(r"`[^`]*`", " ", page)) if hosts else [])
    for name in found:
        if name.lower() not in said and part_key(name) not in folded and name not in unknown:
            unknown.append(name)
    return unknown


GUESS = re.compile(r"\b(?:assum(?:e|ed|es|ing|ption)|presumabl[ey]|probabl[ey]|typical(?:ly)?|usually|likely|"
                   r"implie[sd]|suggest(?:s|ed)?|seems?|appears? to|guess(?:ed|es)?|inferr?(?:ed|s)?)\b", re.I)
#                    (0.11.5) a page that reasons from what is usual where its pages do not say (the words its
#                    evidence never uses: "given typical feature store patterns, we assume ...")


def guesses(page: str, evidence: Any, spec: dict[str, Any] | None = None) -> list[str]:
    """(0.11.5) The words of a page that guess from what is usual or likely (GUESS) where its evidence never uses them
    (its title and its brief count as evidence), lower case, once each; code left out."""
    said = json.dumps(evidence, ensure_ascii=False, default=str).lower() + " " + \
        " ".join(str((spec or {}).get(k) or "") for k in ("title", "brief")).lower()
    out: list[str] = []
    for m in GUESS.finditer(re.sub(r"`[^`]*`", " ", page)):
        word = m.group(0).lower()
        if word not in out and not re.search(r"\b" + re.escape(word) + r"\b", said):
            out.append(word)
    return out


def _faults(text: str, prompt_items: Any, spec: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    """(0.11.5) What a wiki space's page must be written again for: (the subjects of the space it leaves out, the
    names its evidence never gives, bare host names too, the words it guesses with where its pages do not say)."""
    missing = [n for n in (spec.get("guard") or {}).get("subjects") or []
               if not re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", text, re.I)]
    return missing, unknown_names(text, prompt_items, spec, hosts=True), guesses(text, prompt_items, spec)


def _guard(text: str, prompt_items: Any, spec: dict[str, Any]) -> str:
    """(0.11.5) _faults said to the LLM; "" when nothing."""
    missing, unknown, guessed = _faults(text, prompt_items, spec)
    what = ([f"leaves out these subjects of the space: {', '.join(missing[:20])}"] if missing else []) + \
        ([f"names these that the evidence never gives: {', '.join(unknown[:20])}"] if unknown else []) + \
        ([f"guesses from what is usual where the pages do not say ({', '.join(guessed[:10])}): write what the pages "
          f"say, or that they disagree, each statement with its day"] if guessed else [])
    return "; and ".join(what)


def _without_names(page: str, names: list[str]) -> tuple[str, list[str]]:
    """(0.11.5) A page without the sentences that say a name its evidence never gives (what a page still names after
    it was asked again: an invented host; a word it guesses with): in a paragraph or a list item, the sentence; in a
    table, the sentence of its cell (its parts apart: "<br>"; "not known yet" when the cell held nothing else);
    headings and code as written. (the page, the sentences left out)"""
    if not names:
        return page, []
    said = re.compile(r"(?<![\w.-])(?:" + "|".join(re.escape(n) for n in names) + r")(?![\w-])", re.I)
    removed: list[str] = []

    def without(text: str) -> str:
        parts = []
        for part in re.split(r"\s*<br\s*/?>\s*", text):
            kept = []
            for sentence in SENTENCE_END.split(part):
                (removed if said.search(sentence) else kept).append(sentence.strip())
            if any(kept):
                parts.append(" ".join(s for s in kept if s))
        return "<br>".join(parts)

    out: list[str] = []
    fence = False
    for line in page.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
            out.append(line)
        elif fence or line.lstrip().startswith("#") or not said.search(line):
            out.append(line)
        elif line.lstrip().startswith("|"):
            out.append("|".join(" " + (without(c.strip()) or "not known yet") + " " if said.search(c) else c
                                for c in line.split("|")))
        else:
            lead = re.match(r"^(\s*(?:[-*+>]\s+|\d+[.)]\s+)?)", line).group(1)
            text = without(line[len(lead):])
            if text:
                out.append(lead + text)
    return "\n".join(out), removed


def write_summary(spec: dict[str, Any], llm: Any) -> dict[str, Any]:
    """One summary page. An answer cut by the length limit (finish_reason "length") is asked to go on, at most
    CONTINUATIONS times (one cut while reasoning, with nothing written yet, is asked again with twice the room);
    still cut, the page keeps its whole lines and says that it stops there ("cut": the next build writes it
    again)."""
    prompt_items, sources = _numbered(spec["evidence"])
    messages = [{"role": "system", "content": _prompt(spec).format(title=spec["title"], brief=spec["brief"])},
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
        text = text.rsplit("\n", 1)[0].rstrip() if "\n" in text else text
    calls, corrected, left_out = 1, "", []            # (a page's calls as before; the corrective turn counted)
    if spec.get("guard") and text and not cut:        # (0.11.5) asked once again, what to correct said
        corrected = _guard(text, prompt_items, spec)
        if corrected:
            msg = llm.chat(messages[:2] + [{"role": "assistant", "content": text},
                                           {"role": "user", "content": GUARD_ASK.format(what=corrected)}],
                           max_tokens=room)
            usage = getattr(llm, "last_usage", None) or {}
            tokens += int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
            calls += 1
            again = _page_text(msg).strip()
            if again and getattr(llm, "last_finish", None) != "length" and \
                    sum(map(len, _faults(again, prompt_items, spec))) <= \
                    sum(map(len, _faults(text, prompt_items, spec))):
                text = again                          # what comes back, unless it is worse (no second turn)
            text, left_out = _without_names(text, sum(_faults(text, prompt_items, spec)[1:], []))   # still invented
    #                                                   (a host completed from another: atl-sso-11) is left out
    checks: list[str] = []
    try:                                          # (0.11.1) checked before it is saved; a check that fails never
        text, checks = check_page(text, prompt_items, spec) if text else (text, [])     # costs the page
    except Exception as ex:  # pylint: disable=broad-except
        log.warning("supagent context: the checks of the page %s: %s", spec.get("title"), ex)
        checks = [f"checks not done: {type(ex).__name__}"]
    if cut and text:
        text += "\n\n" + CUT_NOTE
    block = diagram_block(spec.get("diagram") or [])
    if text and block:                            # (0.11.0) the relations the documents state, drawn by the page
        text += ("\n\n## Relations diagram\n\nWhat the documents and the code state about the parts (the most stated "
                 "first; read each line as the part on the left, what it does, the part on the right).\n\n" + block)
    if corrected:
        checks = [f"written again once: it {corrected}"[:500]] + \
            ([f"still there after that, left out: {'; '.join(clip(s, 80) for s in left_out[:5])}"[:500]]
             if left_out else []) + checks
    return {"content": text, "sources": sources, "tokens": tokens, "cut": cut, "checks": checks, "calls": calls}


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
    if p is not None and p.content and (settings.get("context.review") or p.kind == REJECTED) and \
            page["slug"] not in LLM_CONTEXT_SLUGS:       # (0.10.9.1) the LLM context follows the learning at once
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
    from supagent import dashlist

    unread = dashlist.unread_slugs()                    # (0.10.10) a dashboard not read (Documents and sites)
    for p in db.session.query(ContextPage).filter(ContextPage.author == "agent"):
        if (p.section, p.slug) not in keep:
            if p.kind == REJECTED or p.slug in unread:  # refused and hidden already: nothing to review; a dashboard
                db.session.delete(p)                    # not read: deleted, never proposed
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
    grafana_ok = _grafana_readable()
    osd_ok = _osd_readable()
    for p in db.session.query(ContextPage).order_by(ContextPage.section, ContextPage.title):
        refused = p.kind == REJECTED
        if p.slug in LLM_CONTEXT_SLUGS:                  # (0.10.9.1) written from the rest at every learning: its
            continue                                     # page shows it, a person may edit it, nothing to validate
        if not grafana_ok and (p.slug or "").startswith("grafana-"):
            continue                                     # (0.10.10) not for this user's roles (grafana.roles)
        if not osd_ok and (p.slug or "").startswith("osd-"):
            continue                                     # (0.10.10) nor osd.roles
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
            grafana: list[dict[str, Any]] = []
            grafana_keep: set[tuple[str, str]] = set()
            from supagent.knowledge import grafana_pages as GP

            if GP.enabled():                             # (0.10.10) the team's Grafana: its dashboards, its alert rules
                steps.begin("Grafana: dashboards and alert rules" + ("" if llm else " (no LLM)"))
                try:
                    explainer = None
                    if llm:
                        from supagent.llm import LLM

                        explainer = LLM()
                    grafana, grafana_keep, done_g = GP.pages(explainer=explainer,
                                                             budget=int(settings.get("grafana.max_llm_calls") or 0))
                    steps.end(**done_g)
                except LearningStopped:
                    raise
                except Exception as ex:  # pylint: disable=broad-except   (its pages are kept as they are)
                    db.session.rollback()
                    grafana = []
                    grafana_keep = {(p.section, p.slug) for p in db.session.query(ContextPage).filter(
                        ContextPage.slug.like(GP.PREFIX + "%"))}
                    steps.end(error=f"{type(ex).__name__}: {str(ex)[:300]}")
            osd_pages_: list[dict[str, Any]] = []
            from supagent.knowledge import osd_pages as OP

            if OP.enabled():                             # (0.10.10) the team's OpenSearch Dashboards: its dashboards
                steps.begin("OpenSearch Dashboards: dashboards and visualizations" + ("" if llm else " (no LLM)"))
                try:
                    explainer = None
                    if llm:
                        from supagent.llm import LLM

                        explainer = LLM()
                    osd_pages_, osd_keep, done_o = OP.pages(explainer=explainer,
                                                            budget=int(settings.get("osd.max_llm_calls") or 0))
                    grafana_keep |= osd_keep
                    steps.end(**{k: v for k, v in done_o.items() if not isinstance(v, dict)})
                except LearningStopped:
                    raise
                except Exception as ex:  # pylint: disable=broad-except   (its pages are kept as they are)
                    db.session.rollback()
                    osd_pages_ = []
                    grafana_keep |= {(p.section, p.slug) for p in db.session.query(ContextPage).filter(
                        ContextPage.slug.like(OP.PREFIX + "%"))}
                    steps.end(error=f"{type(ex).__name__}: {str(ex)[:300]}")
            grafana = grafana + osd_pages_
            keep: set[tuple[str, str]] = set(grafana_keep)
            steps.begin("facts pages (no LLM)")
            done: dict[str, int] = defaultdict(int)
            understood: list[dict[str, Any]] = []
            if settings.get("knowledge.understand"):     # (0.10) the parts, repositories and wiki spaces the documents
                try:                                     # and the code describe
                    from supagent.knowledge.context_docs import pages as understood_pages

                    understood = understood_pages()
                except Exception:  # pylint: disable=broad-except   (the other pages are written)
                    db.session.rollback()
                    log.warning("supagent context: the pages of the documents' facts", exc_info=True)
            systems: list[dict[str, Any]] = []
            if settings.get("context.system_pages"):     # (0.10.10) the communities of the map: a page each
                try:
                    from supagent.knowledge.communities import pages as system_pages

                    systems = system_pages()
                except Exception:  # pylint: disable=broad-except   (the other pages are written)
                    db.session.rollback()
                    log.warning("supagent context: the systems' pages", exc_info=True)
            from supagent.knowledge.llm_context import pages as llm_pages   # (0.10.9.1) the LLM context, its
            #                                                                 full and its light version
            for page in fact_pages(ev) + boards + grafana + understood + systems + llm_pages(ev):
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
                checked: list[str] = []
                client = None
                for spec in specs:
                    check()
                    h = _hash([_prompt(spec), spec["title"], spec["brief"], spec["evidence"]])
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
                    res["llm_calls"] += out.get("calls", 1)      # (0.11.5: a space's page asked again: 2)
                    res["tokens"] += out["tokens"]
                    if not out["content"]:
                        res["empty"] += 1
                        continue
                    if out.get("cut"):
                        res["cut"] += 1                       # saved as it is, written again at the next build
                    if out.get("checks"):                     # (0.11.1) what the checks changed or found on the page
                        res["checked"] += 1
                        checked.append(f"{spec['title']}: {'; '.join(out['checks'])}"[:600])
                    res[save_page({**spec, "content": out["content"], "sources": out["sources"]}, "summary",
                                  _hash([h, "cut"]) if out.get("cut") else h, 1, out["tokens"])] += 1
                    steps.update(**res)
                steps.end(**res, **({"failed_pages": failed[:12]} if failed else {}),
                          **({"checked_pages": checked[:12]} if checked else {}))
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
    """The pages the current user may read: every database of a page must be one they may query; (0.10.10) a page of
    the team's Grafana, a user grafana.roles allows; of its OpenSearch Dashboards, a user osd.roles allows."""
    from supagent.security import visible_databases

    dbs = visible_databases()
    grafana = _grafana_readable()
    osd = _osd_readable()
    return [p for p in db.session.query(ContextPage).order_by(ContextPage.section, ContextPage.title)
            if set(p.database_ids or []) <= dbs and p.kind != REJECTED
            and (grafana or not (p.slug or "").startswith("grafana-"))
            and (osd or not (p.slug or "").startswith("osd-"))]


def _grafana_readable() -> bool:
    from flask import g

    from supagent import grafana as G

    try:
        return G.allowed(getattr(g, "user", None))
    except Exception:  # pylint: disable=broad-except
        return False


def _osd_readable() -> bool:
    from flask import g

    from supagent import osd

    try:
        return osd.allowed(getattr(g, "user", None))
    except Exception:  # pylint: disable=broad-except
        return False


def hidden_from_user(page: Any) -> bool:
    """(0.10.10) A page of the team's Grafana for a user grafana.roles does not allow, of its OpenSearch Dashboards
    for a user osd.roles does not allow (every path that shows a page's content: the Context, To review, the diff,
    the map's hints)."""
    slug = getattr(page, "slug", "") or ""
    return (slug.startswith("grafana-") and not _grafana_readable()) or (slug.startswith("osd-") and
                                                                         not _osd_readable())


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
    ("technical", "Grafana", ("grafana-",)),
    ("technical", "OpenSearch Dashboards", ("osd-",)),
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
