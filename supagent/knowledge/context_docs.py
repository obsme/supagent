"""Context pages from what the documents and the code state (0.10, the user's request of 6 October 2026: the wiki,
the repositories' code and files understood, a better Context from them, well placed in the search).

  a part       an application, a component, a tool the documents and the code describe (two facts at least): its
               other names, its code (the repositories and files that are its code), what it calls, reads, writes,
               depends on and runs on, what uses it, its data (the indices it logs to, the metrics it emits, what
               watches it), the pages about it; each statement with where it was read (a file's line, a page, a
               diagram) and how (code, configuration, page, diagram)
  a repository its files by language, its folders, the services it is the code of, what its files state
  a wiki space its pages, the pages they link to, the parts they describe, their diagrams

Facts pages, written without the LLM, again only when what they say changes; they are searched like every Context
page. A page that names the data of a database is shown to who may query that database (as every Context page).
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any

from superset import db

log = logging.getLogger(__name__)

MAX_PART_PAGES = 120       # pages of parts at most (the most described first)
MIN_FACTS = 2              # a part named once only gets no page of its own
MAX_LINES = 40             # statements of one kind on a page
VERBS_OUT = {"calls": "calls", "sends_to": "sends data to", "reads_from": "reads from", "uses": "uses",
             "runs_on": "runs on", "owned_by": "is owned by", "collects": "collects the logs of", "scrapes": "scrapes",
             "monitors": "monitors", "in_group": "is in the server group"}
VERBS_IN = {"calls": "calls it", "sends_to": "sends it data", "reads_from": "reads from it", "uses": "uses it",
            "runs_on": "runs on it", "owned_by": "owns it", "collects": "collects its logs", "scrapes": "scrapes it",
            "monitors": "monitors it", "in_group": "is one of its servers"}
GROUP = "group:"           # an inventory's group of servers: a page of its own, never a part's of the same name
DATA_VERBS = {"logs_to": "logs to", "emits": "emits", "writes": "writes", "watched_by": "is watched by"}
HOW = {"code": "code", "config": "configuration", "inferred": "inferred", "diagram": "diagram", "doc": "document",
       "wiki": "page", "llm": "LLM"}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:100] or "x"


def _norm(name: str) -> str:
    return " ".join(str(name or "").lower().replace("_", "-").split())


def _how(r: dict[str, Any]) -> str:
    how = ", ".join(HOW.get(s, s) for s in r.get("sources") or [])
    where = r.get("where") or ""
    return f" ({how}{': ' + where if where else ''})" if how or where else ""


def pages() -> list[dict[str, Any]]:
    """The pages (see the module): {"section", "slug", "title", "content", "database_ids", "sources"}."""
    from supagent.knowledge.understand import _repo_name, export
    from supagent.models import Doc, Facet, KObject, KUnit, Source

    g = export()
    docs = {d.id: d for d in db.session.query(Doc).filter(Doc.enabled.is_(True))}
    units = [u for u in db.session.query(KUnit) if u.doc_id in docs]
    values = {}
    for f in db.session.query(Facet).filter(Facet.status == "approved"):
        for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
            values.setdefault(_norm(n), f)
    db_of: dict[str, int] = {}                           # a data object's database (who may read its page)
    for name, sid in db.session.query(KObject.name, KObject.source_id).filter(KObject.kind.in_(("index", "metric",
                                                                                                   "family"))):
        db_of.setdefault(name, sid)
    source_db = dict(db.session.query(Source.id, Source.database_id))
    aliases: dict[str, set[str]] = defaultdict(set)
    for a in g.get("aliases") or []:
        aliases[_norm(a["part"])].add(a["name"])
    out_rel: dict[str, list[dict]] = defaultdict(list)
    in_rel: dict[str, list[dict]] = defaultdict(list)
    data: dict[str, list[dict]] = defaultdict(list)
    shown: dict[str, str] = {}
    rels = g.get("relations") or []
    groups = {_norm(r["to"]) for r in rels if r["kind"] == "in_group" or
              (r["kind"] == "runs_on" and r.get("obj_kind") == "group")}
    for r in rels:
        group_to = r["kind"] == "in_group" or (r["kind"] == "runs_on" and r.get("obj_kind") == "group")
        a = (GROUP if r["kind"] == "in_group" and _norm(r["from"]) in groups else "") + _norm(r["from"])
        b = (GROUP if group_to else "") + _norm(r["to"])
        out_rel[a].append(r)
        in_rel[b].append(r)
        shown.setdefault(a, r["from"])
        shown.setdefault(b, r["to"])
    for d in g.get("data_links") or []:
        data[_norm(d["part"])].append(d)
        shown.setdefault(_norm(d["part"]), d["part"])
    code_of: dict[str, list[Any]] = defaultdict(list)    # the files that are a part's code
    pages_about: dict[str, set[int]] = defaultdict(set)  # the pages that state something of a part
    unit_of = {u.id: u for u in units}
    for u in units:
        if u.owner and u.kind == "file":
            code_of[_norm(u.owner)].append(u)
    from supagent.models import KFact

    homes: dict[str, Counter] = defaultdict(Counter)    # the repositories a part's or a group's facts come from
    for unit_id, subject, verb, obj, obj_kind in db.session.query(KFact.unit_id, KFact.subject, KFact.verb, KFact.obj,
                                                                  KFact.obj_kind):
        u = unit_of.get(unit_id)
        if u is not None and u.kind == "page":
            pages_about[_norm(subject)].add(u.id)
            pages_about[_norm(obj)].add(u.id)
        if u is not None and u.kind == "file":
            to_group = verb == "in_group" or (verb == "runs_on" and obj_kind == "group")
            homes[(GROUP if verb == "in_group" and _norm(subject) in groups else "") + _norm(subject)][u.doc_id] += 1
            homes[(GROUP if to_group else "") + _norm(obj)][u.doc_id] += 1
    out: list[dict[str, Any]] = []
    weight = Counter({k: len(out_rel[k]) + len(in_rel[k]) + len(data[k]) for k in shown})
    for key, n in weight.most_common():
        if n < MIN_FACTS or len(out) >= MAX_PART_PAGES:
            break
        name = shown[key]
        if key.startswith("namespace:"):
            continue
        group = key.startswith(GROUP)
        f = None if group else values.get(key)
        lines = [f"# {name}" + (" (a group of servers)" if group else ""), ""]
        kind = f"{'An application' if f.facet == 'application' else 'A ' + f.facet} of the categories" if f else \
            "A group of servers of an inventory: its servers and what runs on them" if group else \
            "A part the documents and the code describe"
        lines.append(kind + ".")
        if f is not None and f.description:
            lines += ["", f.description]
        other = sorted(a for a in aliases.get(key, ()) if _norm(a) != key)
        if other:
            lines += ["", "Also named: " + ", ".join(other) + "."]
        mine = code_of.get(key) or []
        refs: set[int] = set()
        if mine:
            by_doc: dict[int, list[Any]] = defaultdict(list)
            for u in mine:
                by_doc[u.doc_id].append(u)
            lines += ["", "## Its code", ""]
            for doc_id, us in by_doc.items():
                langs = Counter(u.lang or "other" for u in us)
                refs.add(doc_id)
                lines.append(f"- {docs[doc_id].title or docs[doc_id].url}: {len(us)} file{'s' if len(us) > 1 else ''} ("
                             + ", ".join(f"{k} {v}" for k, v in langs.most_common(5)) + ")")
        if out_rel.get(key):
            lines += ["", "## What it uses", ""]
            for r in sorted(out_rel[key], key=lambda x: (x["kind"], x["to"]))[:MAX_LINES]:
                lines.append(f"- {VERBS_OUT.get(r['kind'], r['kind'])} **{r['to']}**{_how(r)}")
        if in_rel.get(key):
            lines += ["", "## What uses it", ""]
            for r in sorted(in_rel[key], key=lambda x: (x["kind"], x["from"]))[:MAX_LINES]:
                lines.append(f"- **{r['from']}** {VERBS_IN.get(r['kind'], r['kind'])}{_how(r)}")
        dbids: set[int] = set()
        if data.get(key):
            lines += ["", "## Its data", ""]
            for d in sorted(data[key], key=lambda x: (x["kind"], x["object"]))[:MAX_LINES]:
                lines.append(f"- {DATA_VERBS.get(d['kind'], d['kind'])} {d.get('object_kind') or 'object'} "
                             f"`{d['object']}`{_how(d)}")
                sid = db_of.get(d["object"])
                if sid is not None and source_db.get(sid) is not None:
                    dbids.add(source_db[sid])
        about = sorted({unit_of[i].title or unit_of[i].ukey for i in pages_about.get(key, ()) if i in unit_of})
        if about:
            lines += ["", "## Pages about it", ""] + [f"- {t}" for t in about[:MAX_LINES]]
            refs |= {unit_of[i].doc_id for i in pages_about.get(key, ()) if i in unit_of}
        repos = [_repo_name(docs[i]) or docs[i].title or docs[i].url
                 for i, _n in homes.get(key, Counter()).most_common(3) if i in docs]
        bare = key[len(GROUP):] if group else key
        twin = (bare in shown) if group else (GROUP + key in shown)
        where = f" ({', '.join(repos)})" if repos and twin else ""     # (a name a part and a group both have)
        if repos:                                        # (two projects' "web" are two things: said on the page)
            lines.insert(2, f"Read in: {', '.join(repos)}.")
        out.append({"section": "technical", "slug": f"{'servers' if group else 'parts'}-{_slug(name)}",
                    "title": f"{'Server group' if group else 'Part'}: {name}{where}",
                    "content": "\n".join(lines), "database_ids": sorted(dbids),
                    "sources": [{"ref": f"doc:{i}", "title": docs[i].title or docs[i].url} for i in sorted(refs) if i in docs]})
    for doc_id, d in docs.items():                     # a repository, a wiki space: a page each
        us = [u for u in units if u.doc_id == doc_id]
        if not us:
            continue
        files = [u for u in us if u.kind == "file"]
        wiki = [u for u in us if u.kind == "page"]
        title = d.title or d.url
        if files:
            langs = Counter(u.lang or "other" for u in files)
            folders = Counter((u.ukey.split("/", 1)[0] if "/" in u.ukey else "(top)") for u in files)
            owners = Counter(u.owner for u in files if u.owner)
            lines = [f"# {title}", "", f"A repository: {len(files)} file{'s' if len(files) > 1 else ''} read ("
                     + ", ".join(f"{k} {v}" for k, v in langs.most_common(8)) + ")."]
            from supagent.models import Meta

            row = db.session.get(Meta, f"repo_kinds:{doc_id}")
            try:
                kinds = json.loads(row.value) if row is not None and row.value else {}
            except ValueError:
                kinds = {}
            if kinds.get("sentences"):                     # what it is: an Ansible project, manifests, code...
                lines += ["", "## What it is", ""] + [f"- {x}" for x in kinds["sentences"]]
                if "ansible" not in kinds.get("labels", []):
                    lines.append("- Not an Ansible project (no play, no inventory, no role with tasks).")
            lines += ["", "## Folders", ""]
            lines += [f"- {k}: {v} file{'s' if v > 1 else ''}" for k, v in folders.most_common(20)]
            if owners:
                lines += ["", "## The services it is the code of", ""] + [f"- {k} ({v} file{'s' if v > 1 else ''})"
                                                                         for k, v in owners.most_common(20)]
            out.append({"section": "technical", "slug": f"repositories-{_slug(title)}", "title": f"Repository: {title}",
                        "content": "\n".join(lines), "database_ids": [],
                        "sources": [{"ref": f"doc:{doc_id}", "title": title}]})
        if wiki and any(isinstance(p, dict) and p.get("space") for p in d.pages or []):
            continue                                       # (0.10.1) a wiki's pages: a page per space, below
        if wiki:
            ids = {str((p or {}).get("id")): (p or {}).get("title") for p in (d.pages or []) if isinstance(p, dict)}
            lines = [f"# {title}", "", f"A wiki space: {len(wiki)} page{'s' if len(wiki) > 1 else ''} read.", "", "## Pages", ""]
            for p in (d.pages or [])[:200]:
                if not isinstance(p, dict) or not p.get("title"):
                    continue
                to = [ids.get(str(x)) for x in p.get("links") or [] if ids.get(str(x))]
                lines.append(f"- {p['title']}" + (f" (links to: {', '.join(to[:8])})" if to else "")
                             + (f" ({len(p.get('diagram_edges') or [])} arrows in its diagrams)" if p.get("diagram_edges")
                                else ""))
            named = sorted({shown[k] for k, ids_ in pages_about.items() if k in shown
                            and ids_ & {u.id for u in wiki}})
            if named:
                lines += ["", "## The parts its pages describe", "", ", ".join(named[:80])]
            out.append({"section": "functional", "slug": f"wiki-{_slug(title)}", "title": f"Wiki: {title}",
                        "content": "\n".join(lines), "database_ids": [],
                        "sources": [{"ref": f"doc:{doc_id}", "title": title}]})
    out.extend(_space_pages(docs, units, pages_about, shown))
    return out


def _space_pages(docs: dict[int, Any], units: list[Any], pages_about: dict[str, set[int]],
                 shown: dict[str, str]) -> list[dict[str, Any]]:
    """(0.10.1) A page per wiki space, whatever document read its pages (a wiki given as one document per space reads
    each page once, by the first document that reaches it: the other spaces' pages are in that document): its pages,
    the pages they link to, their diagrams, the parts they describe. Titled after the document that starts in it."""
    has_pages = {u.doc_id for u in units if u.kind == "page"}
    unit_ids: dict[tuple[int, str], int] = {(u.doc_id, u.ukey): u.id for u in units if u.kind == "page"}
    items: dict[str, list[tuple[Any, dict[str, Any]]]] = defaultdict(list)
    named_by: dict[str, str] = {}
    seen: set[tuple[str, str]] = set()
    holders: dict[str, dict[int, Any]] = defaultdict(dict)
    for doc_id, d in sorted(docs.items()):
        if doc_id not in has_pages:
            continue
        for i, p in enumerate(d.pages or []):
            if isinstance(p, dict) and p.get("space") and p.get("title"):
                holders[str(p["space"])][doc_id] = d
                if i == 0:
                    named_by.setdefault(str(p["space"]), d.title or d.url)
                key = (str(p["space"]), str(p.get("id") or p.get("url") or p["title"]))
                if key not in seen:                        # (a document's own address another one reads too)
                    seen.add(key)
                    items[str(p["space"])].append((d, p))
    out: list[dict[str, Any]] = []
    for space, these in sorted(items.items()):
        title = named_by.get(space) or space
        ids = {str(p.get("id")): p.get("title") for _d, p in these}
        lines = [f"# {title}", "", f"A wiki space ({space}): {len(these)} page{'s' if len(these) > 1 else ''} read.", "",
                 "## Pages", ""]
        for _d, p in these[:200]:
            to = [ids.get(str(x)) for x in p.get("links") or [] if ids.get(str(x))]
            lines.append(f"- {p['title']}" + (f" (links to: {', '.join(to[:8])})" if to else "")
                         + (f" ({len(p.get('diagram_edges') or [])} arrows in its diagrams)" if p.get("diagram_edges")
                            else ""))
        mine = {unit_ids.get((d.id, str(p.get(k)))) for d, p in these for k in ("id", "url")} - {None}
        named = sorted({shown[k] for k, ids_ in pages_about.items() if k in shown and ids_ & mine})
        if named:
            lines += ["", "## The parts its pages describe", "", ", ".join(named[:80])]
        out.append({"section": "functional", "slug": f"wiki-{_slug(title)}", "title": f"Wiki: {title}",
                    "content": "\n".join(lines), "database_ids": [],
                    "sources": [{"ref": f"doc:{i}", "title": d.title or d.url} for i, d in sorted(holders[space].items())]})
    return out
