"""(0.11.7) The applications, components and services the documents describe, and where a wiki documents each (the
user's wiki of 30+ spaces and ~3,000 pages, 2026-10-21: an application documented in several spaces, spaces with no
page tree, pages of other wikis among them).

For each part: what it is (the System map's kind, else what a sentence or a caption of the pages says: never a
column's head alone), what it is part of, the wiki pages about it (a page stating something of it, a page whose title
names it; not a page naming it as another part's end), its own space (the space of its own page, the one titled with
its name; else the space with the most pages about it) and the other spaces with OTHER_SPACE_PAGES pages about it or more; and the relations between parts with
the pages that state them. Without the LLM: read by the space pages, the links page, the overviews and the Part
pages."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from superset import db

KIND_SAID = 0.7            # a kind a sentence or a caption says (0.7 and more); a column's head alone (0.65): not shown
OTHER_SPACE_PAGES = 2      # pages of another space about a part for that space to document it
FLOW_VERBS = ("calls", "reads_from", "sends_to", "uses", "runs_on", "monitors", "scrapes", "collects", "routes_to")
PART_ENDS = ("part", "cluster", "database")      # an object that is a part (no host, index, metric, kind nor team)
FACT_VERBS = FLOW_VERBS + ("part_of", "is_a", "owned_by")
MIN_NAME = 3               # characters of a part's name for a page's title to name it
# (0.11.7) the pieces of a title, a name of no shape of its own ("lakeview") naming the page only as a whole piece
# ("Design: lakeview (53)", "Runbook - lakeview #77", "Minutes 04.09.2024 - lakeview", "lakeview v2.18"), never
# inside a phrase ("Lakeview reports for the board")
TITLE_PIECES = re.compile(r"\s*(?::\s|(?<![\w])[-–—](?![\w])|[()#?]|\bv\d[\d.]*\b|\b\d{4}-\d{2}-\d{2}\b|"
                          r"\b\d{1,2}\.\d{1,2}\.\d{4}\b)\s*")
CHANGE_WINDOW = 1880       # characters of a page's beginning read for a dated change (the digest's first lines)
CHANGE_CHARS = 240         # of a change's sentence
KIND_PHRASE = {"application": "an application", "component": "a component", "service": "a service",
               "database": "a database", "external": "a system outside", "job": "a job", "store": "a data store",
               "cache": "a cache", "broker": "a message broker", "module": "a module", "api": "an API"}


def norm(name: Any) -> str:
    return " ".join(str(name or "").lower().replace("_", "-").split())


def space_name(space: str, pages: list[dict[str, Any]]) -> str:
    """A wiki space's name: the title of its home (its top page holding the most pages under it); its key when no top
    page holds any (pages imported at the top of a space, no home)."""
    tops = [p for p in pages if isinstance(p.get("ancestors"), list) and not p["ancestors"] and p.get("id")]
    under = Counter(str(p["ancestors"][0]) for p in pages if isinstance(p.get("ancestors"), list) and p["ancestors"])
    best = max(tops, key=lambda p: under[str(p["id"])], default=None)
    if best is not None and under[str(best["id"])]:
        return str(best.get("title") or space)
    if len(tops) == 1 and not under:                   # (a space of one page)
        return str(tops[0].get("title") or space)
    return space


def site(doc: dict[str, Any]) -> str:
    from urllib.parse import urlparse

    return urlparse(str(doc.get("url") or "")).netloc.lower()


def space_ids(docs: list[dict[str, Any]]) -> dict[tuple[int, str], str]:
    """(doc id, space key) -> the space: its key; "KEY@host" for the other sites when documents of two sites have a
    space of that key (two wikis' "OPS" are two spaces; two links of one wiki reaching its "OPS", one), the site with
    the most pages of it keeping the bare key (a small wiki added later renames no page of the big one)."""
    pages: dict[str, Counter] = defaultdict(Counter)
    keys: dict[int, set[str]] = defaultdict(set)
    for d in docs:
        for p in d.get("pages") or []:
            if isinstance(p, dict) and p.get("space"):
                pages[str(p["space"])][site(d)] += 1
                keys[int(d["id"])].add(str(p["space"]))
    first = {k: max(c, key=lambda h: (c[h], h)) for k, c in pages.items()}
    return {(int(d["id"]), k): k if site(d) == first[k] else f"{k}@{site(d)}"
            for d in docs for k in keys.get(int(d["id"]), ())}


def _names_in_titles(names: dict[str, str]) -> Any:
    """A pattern finding the parts' names in a page's title: a name with a hyphen, a dot, an underscore, a digit or a
    capital as written (its case kept when it has a capital: "Orderly", not "orderly"), whole; None when there is no
    such name."""
    shaped = [n for n in names.values() if len(n) >= MIN_NAME and re.search(r"[-_.\dA-Z]", n)]
    if not shaped:
        return None
    alts = sorted(set(shaped), key=len, reverse=True)
    return re.compile(r"(?<![\w-])(" + "|".join(re.escape(n) for n in alts) + r")(?![\w-])")


def index(docs: list[dict[str, Any]], facets: dict[str, str] | None = None) -> dict[str, Any]:
    """docs: the documents as collect() gives them ({"id", "pages"}); facets: the System map's kind of a part's name
    (norm -> facet). {"parts": {key: {"name", "kind", "of", "home", "spaces": Counter, "pages": set}},
    "page_parts": {(doc_id, page id): [part keys, the one its title names first]}, "relations": [{"a", "verb", "b",
    "pages": [(site, page id)], "quote", "where"}], "space_names": {space: name}, "page_space": {(site, page id):
    space}}; a page two documents of one site read counts once"""
    from supagent.models import Doc, KFact, KUnit

    page_of: dict[tuple[str, str], dict[str, Any]] = {}    # (its site, its id): a page two documents read, once
    space_of: dict[tuple[str, str], str] = {}
    doc_of: dict[tuple[str, str], int] = {}
    canon: dict[tuple[int, str], tuple[str, str]] = {}    # (document, page id) -> (site, page id)
    by_space: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ids = space_ids(docs)
    for d in docs:
        for p in d.get("pages") or []:
            if isinstance(p, dict) and p.get("id") and p.get("space"):
                key = (site(d), str(p["id"]))
                canon[(int(d["id"]), str(p["id"]))] = key
                if key not in page_of:
                    page_of[key] = p
                    doc_of[key] = int(d["id"])
                    space_of[key] = ids.get((int(d["id"]), str(p["space"]))) or str(p["space"])
                    by_space[space_of[key]].append(p)
    names: dict[str, Counter] = defaultdict(Counter)
    kinds: dict[str, Counter] = defaultdict(Counter)
    wholes: dict[str, Counter] = defaultdict(Counter)
    about: dict[str, set[tuple[int, str]]] = defaultdict(set)
    rel: dict[tuple[str, str, str], dict[str, Any]] = {}
    facts_on: dict[tuple[int, str], Counter] = defaultdict(Counter)
    try:
        rows = (db.session.query(KFact.subject, KFact.verb, KFact.obj, KFact.obj_kind, KFact.confidence, KFact.quote,
                                 KUnit.doc_id, KUnit.ukey, KUnit.kind, KUnit.title)
                .join(KUnit, KUnit.id == KFact.unit_id).join(Doc, Doc.id == KUnit.doc_id)
                .filter(Doc.enabled.is_(True), KFact.verb.in_(FACT_VERBS)).all())
    except Exception:  # pylint: disable=broad-except   (no understanding yet: no parts)
        db.session.rollback()
        rows = []
    for subj, verb, obj, obj_kind, conf, quote, doc_id, ukey, ukind, title in rows:
        a = norm(subj)
        if not a or a in ("it", "this"):
            continue
        names[a][" ".join(str(subj).split())] += 1
        page = canon.get((int(doc_id), str(ukey)), (str(doc_id), str(ukey))) if ukind == "page" else None
        if page:
            about[a].add(page)
            facts_on[page][a] += 1
        if verb == "is_a":
            kinds[a][(str(obj), float(conf or 0))] += 1
            continue
        if verb == "owned_by":
            continue
        b = norm(obj)
        if not b or b == a or (obj_kind or "part") not in PART_ENDS:
            continue
        names[b][" ".join(str(obj).split())] += 1        # (a page naming it as another's end: no page about it)
        if verb == "part_of":
            wholes[a][b] += 1
            continue
        r = rel.setdefault((a, verb, b), {"a": a, "verb": verb, "b": b, "pages": set(), "quote": "", "where": "",
                                          "day": ""})
        if page:
            r["pages"].add(page)
            day = str((page_of.get(page) or {}).get("modified") or "")
            if day >= r["day"] or not r["quote"]:       # the sentence of the latest page saying it
                r["day"], r["quote"], r["where"] = day, " ".join(str(quote or "").split())[:240], str(title or "")
    shown = {k: c.most_common(1)[0][0] for k, c in names.items()}
    titles = _names_in_titles(shown)
    own_pages: dict[str, set[tuple[int, str]]] = defaultdict(set)
    title_parts: dict[tuple[int, str], list[str]] = {}
    for key, p in page_of.items():
        t = " ".join(str(p.get("title") or "").split())
        found = [norm(m) for m in titles.findall(t)] if titles else []
        if norm(t) in shown and norm(t) not in found:
            found.insert(0, norm(t))
        for piece in TITLE_PIECES.split(t):
            if len(piece) >= MIN_NAME and norm(piece) in shown and norm(piece) not in found:
                found.append(norm(piece))
        if found:
            title_parts[key] = sorted(set(found), key=lambda k: -len(k))
            for k in found:
                about[k].add(key)
            if norm(t) in shown:
                own_pages[norm(t)].add(key)
    content = {key: (d.get("content") or "") for d in docs for key in [int(d["id"])]}
    titles = {norm(p.get("title")) for p in page_of.values() if p.get("title")}
    parts: dict[str, dict[str, Any]] = {}
    for k, name in shown.items():
        pages = about.get(k) or set()
        spaces = Counter(space_of[x] for x in pages if x in space_of)
        mine = Counter(space_of[x] for x in own_pages.get(k, ()) if x in space_of)
        home = max(mine, key=lambda s: (spaces[s], s)) if mine else \
            (max(spaces, key=lambda s: (spaces[s], s)) if spaces else None)
        said = [(kind, conf) for (kind, conf), _n in kinds.get(k, Counter()).items() if conf >= KIND_SAID]
        kind = (facets or {}).get(k) or (Counter(x for x, _c in said).most_common(1)[0][0] if said else None)
        of = wholes[k].most_common(1)[0][0] if wholes.get(k) else None
        if not (facets or {}).get(k) and (kind == "module" or (kind == "service" and of)):
            kind = "component"                             # (0.11.7) "x: a module of y", "a microservice of y": a
            #                                                component of y (a service of its own has no whole)
        parts[k] = {"name": name, "kind": kind, "of": shown.get(of, of) if of else None, "home": home,
                    "spaces": spaces, "pages": pages,
                    "change": _latest_change(name, pages, page_of, space_of, content, titles, doc_of)}
    page_parts: dict[tuple[int, str], list[str]] = {}      # (document, page id): every document's copy
    for (doc_id, pid), key in canon.items():
        first = title_parts.get(key) or []
        rest = [k for k, _n in facts_on.get(key, Counter()).most_common() if k not in first]
        if first or rest:
            page_parts[(doc_id, pid)] = first + rest
    relations = [{**r, "a": shown.get(r["a"], r["a"]), "b": shown.get(r["b"], r["b"]), "a_key": r["a"],
                  "b_key": r["b"], "pages": sorted(r["pages"])} for r in rel.values()]
    relations.sort(key=lambda r: (-len(r["pages"]), r["a"].lower(), r["verb"], r["b"].lower()))
    first = {}                                         # a document's first space: its title names it when no home does
    for d in docs:                                     # (a wiki read before 0.11.4: no parents)
        p0 = next((p for p in d.get("pages") or [] if isinstance(p, dict) and p.get("space")), None)
        if p0 is not None:
            first.setdefault(ids.get((int(d["id"]), str(p0["space"]))) or str(p0["space"]), str(d.get("title") or ""))
    names = {}
    for sp, ps in by_space.items():
        key, _, host = sp.partition("@")
        name = space_name(key, ps)
        names[sp] = name if name != key else first.get(sp) or (f"{key} ({host})" if host else key)
    return {"parts": parts, "page_parts": page_parts, "relations": relations, "space_names": names,
            "page_space": space_of}


def _latest_change(name: str, pages: set[tuple[str, str]], page_of: dict[tuple[str, str], dict[str, Any]],
                   space_of: dict[tuple[str, str], str], content: dict[int, str], titles: set[str],
                   doc_of: dict[tuple[str, str], int]) -> dict[str, str] | None:
    """The newest page about a part (by the day it was last changed) whose first lines say since when something of it
    holds ("Since 12 March 2026, x runs on y", "From 20 April 2026 ...", "As of 2026-03 ..."; a page's title in a
    list of links is no sentence of it): {"day", "space",
    "sentence"}; None when no page says so. Read by every space page and the overviews, so that what a part's own
    space changed lately holds in the other spaces too (their older pages still say the old value)."""
    from supagent.knowledge.context import CHANGE_LEAD, clip

    said = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", re.I)
    dated = sorted((p for p in pages if p in page_of and page_of[p].get("modified") and
                    isinstance(page_of[p].get("at"), int) and isinstance(page_of[p].get("chars"), int)),
                   key=lambda p: str(page_of[p]["modified"]), reverse=True)
    for p in dated:
        meta = page_of[p]
        block = content.get(doc_of.get(p), "")[meta["at"]:meta["at"] + min(meta["chars"], CHANGE_WINDOW)]
        for line in block.splitlines()[1:]:
            for sentence in re.split(r"(?<=[.!?])\s+", line.strip()):
                bare = norm(re.sub(r"^\s*(?:#{1,6}\s+|[-*+>]\s+)", "", sentence).rstrip(" ."))
                if CHANGE_LEAD.search(sentence) and said.search(sentence) and bare not in titles:
                    return {"day": str(meta["modified"])[:10], "space": space_of.get(p, ""),
                            "sentence": clip(re.sub(r"^\s*(?:#{1,6}\s+|[-*+>]\s+)", "", sentence), CHANGE_CHARS)}
    return None


FORMER = re.compile(r"(?i)\b(?:before|previously|formerly|was|were|replacing|replaced|instead\s+of|until|used\s+to|"
                    r"no\s+longer)\b")


def superseded(part: dict[str, Any] | None, value: str) -> bool:
    """A value a part's latest dated change says it no longer has: named after its "before", "was", "replacing"...,
    not before it ("Since 12 March 2026, x runs on b-31; before, x runs on b-11": b-11)."""
    c = (part or {}).get("change")
    if not c or not value:
        return False
    s = c["sentence"]
    m = FORMER.search(s)
    if not m:
        return False
    v = re.compile(r"(?<![\w-])" + re.escape(str(value)) + r"(?![\w-])", re.I)
    return bool(v.search(s, m.end())) and not v.search(s[:m.start()])


def change_phrase(part: dict[str, Any], names: dict[str, str]) -> str:
    """A part's latest dated change in words, for a page's evidence: "" when none."""
    c = part.get("change")
    if not c:
        return ""
    return f"its latest dated change ({c['day']}, in {names.get(c['space'], c['space'])}): \"{c['sentence']}\""


def kind_phrase(part: dict[str, Any]) -> str:
    """What a part is, in words: "a component of Orderly", "a service", "" when the pages do not say."""
    kind = KIND_PHRASE.get(str(part.get("kind") or ""), f"a {part['kind']}" if part.get("kind") else "")
    if part.get("of"):
        return f"{kind or 'a part'} of {part['of']}"
    return kind


def others(part: dict[str, Any]) -> list[str]:
    """The other spaces whose pages are about a part (OTHER_SPACE_PAGES or more), the most first."""
    return [s for s, n in sorted(part["spaces"].items(), key=lambda x: (-x[1], x[0]))
            if s != part.get("home") and n >= OTHER_SPACE_PAGES]


def facets() -> dict[str, str]:
    """The System map's kind of each approved value (its name and its other names): norm -> facet."""
    from supagent.models import Facet

    out: dict[str, str] = {}
    try:
        for f in db.session.query(Facet).filter(Facet.status == "approved"):
            for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
                out.setdefault(norm(n), str(f.facet or ""))
    except Exception:  # pylint: disable=broad-except
        db.session.rollback()
    return {k: v for k, v in out.items() if v}
