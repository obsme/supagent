"""Searching the knowledge for a question: words (PostgreSQL full-text search, built in) and
meaning (vectors of the embedding model, when one is set), ranks fused; with the knowledge store
(pgstore, 0.6) BM25, near spellings and pgvector in PostgreSQL instead. Only what the user may
see is searched: pieces about databases the user may query, the team's pieces and the user's
own (personal memories); the filter is applied before ranking."""

from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import and_, func, or_
from superset import db

from supagent import settings
from supagent.models import Chunk

log = logging.getLogger(__name__)
RRF = 60
VECTOR_FLOOR = 0.35     # a piece found by meaning only must be at least this close (cosine)...
VECTOR_MARGIN = 0.2     # ... and not far behind the closest one: a weak neighbour is noise, not knowledge


CONTEXT_PLACES = 5      # a Context page (partly AI-written) counts as found 5 places lower: on equal
                        # relevance, the catalog and the documents come first


def _allowed_query(kinds: tuple[str, ...] | None = None) -> Any:
    from flask import g

    from supagent.knowledge.context import visible_pages
    from supagent.knowledge.curated import sources_of_user
    from supagent.security import group_scopes, visible_databases

    user_id = getattr(getattr(g, "user", None), "id", None)
    sources = [s.id for s in sources_of_user()] or [-1]
    dbs = list(visible_databases()) or [-1]
    q = (db.session.query(Chunk)
         .filter(or_(Chunk.source_id.is_(None), Chunk.source_id.in_(sources)))
         .filter(or_(Chunk.database_id.is_(None), Chunk.database_id.in_(dbs)))
         .filter(or_(Chunk.scope == "team", and_(Chunk.scope == "user", Chunk.user_id == user_id),
                     Chunk.scope.in_(group_scopes() or ["-"]))))     # a group's notes: its members'
    pages = [p.id for p in visible_pages()]                # a Context page: every database of it readable
    q = q.filter(or_(Chunk.kind != "context", *[Chunk.ref.like(f"context:{i}#%") for i in pages]))
    if kinds:
        q = q.filter(Chunk.kind.in_(kinds))
    return q


def _superset_allowed(c: Chunk) -> bool:
    """A chart or dashboard piece only for a user Superset lets open it (and, for a dashboard, every chart
    it lists): its database alone is not enough (dashboard roles, dataset access)."""
    if c.kind not in ("chart", "dashboard"):
        return True
    try:
        from superset.extensions import security_manager
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice

        parts = c.ref.split(":")
        if parts[1] == "chart":
            chart = db.session.get(Slice, int(parts[2]))
            return chart is not None and bool(security_manager.can_access_chart(chart))
        board = db.session.get(Dashboard, int(parts[2]))
        return board is not None and bool(security_manager.can_access_dashboard(board)) and all(
            security_manager.can_access_chart(sl) for sl in board.slices or [])
    except Exception:  # pylint: disable=broad-except
        db.session.rollback()
        return False


def _terms(query: str) -> list[str]:
    from supagent.knowledge.describe import STOP, stem

    words = [stem(w) for w in re.findall(r"[a-z0-9_]+", (query or "").lower())]
    return [w for w in dict.fromkeys(words) if w not in STOP and len(w) > 1][:24]


def _lexical(q: Any, terms: list[str], limit: int = 50) -> list[int]:
    if not terms:
        return []
    if db.engine.dialect.name == "postgresql":
        doc = func.to_tsvector("simple", func.coalesce(Chunk.title, "") + " " + func.coalesce(Chunk.text, ""))
        tsq = func.to_tsquery("simple", " | ".join(f"{re.sub(r'[^a-z0-9_]', '', t)}:*" for t in terms))
        rows = (q.filter(doc.op("@@")(tsq)).with_entities(Chunk.id, func.ts_rank_cd(doc, tsq).label("r"))
                .order_by(func.ts_rank_cd(doc, tsq).desc()).limit(limit).all())
        return [r[0] for r in rows]
    scored = []                                   # other databases: words counted here
    for c in q.limit(20000):
        text = f"{c.title} {c.text}".lower()
        hits = sum(1 for t in terms if t in text)
        if hits:
            scored.append((hits, c.id))
    return [cid for _h, cid in sorted(scored, key=lambda x: -x[0])[:limit]]


def search_all(query: str, kinds: tuple[str, ...] | None = None, cap: int = 500) -> list[dict[str, Any]]:
    """Every piece the search finds for a query (at most `cap`), best first: the first ones as search() orders
    them for the agent (reranked when a reranker is set), then the others as the ways of searching rank them.
    For the Data dictionary's search, which lists them all, page by page."""
    from supagent.knowledge import rerank as R

    found = _search(query, cap, kinds, None, (), n=cap)
    if not found or not R.enabled():
        return found
    return R.rerank(query, found)                 # the first rerank.depth reordered, the others after them


ITEM_REF = re.compile(r"(object|entry|memory|doc|note|context|recipe):\d+")


def link_of(ref: str) -> dict[str, str] | None:
    """Where a piece is read or edited: a chart or a dashboard in Superset, else its place in the Data dictionary
    (#open/<ref>, which the page opens: an index or a metric, a catalog entry, a note, a document...)."""
    from urllib.parse import quote

    kind, _, rest = (ref or "").partition(":")
    if kind == "superset":
        parts = rest.split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            if parts[0] == "chart":
                return {"href": f"/explore/?slice_id={parts[1]}", "where": "superset"}
            if parts[0] == "dashboard":
                return {"href": f"/superset/dashboard/{parts[1]}/", "where": "superset"}
        return None
    base = rest.split("#", 1)[0]
    if kind in ("object", "entry", "memory", "doc", "note", "context", "recipe") and base.split(":")[0].isdigit():
        return {"href": "#open/" + quote(f"{kind}:{base.split(':')[0]}", safe=""), "where": "dictionary"}
    return None


def _piece_order(c: Any) -> tuple:
    """A piece's place in its item: doc:4#7 (its number), doc:4#<page>-7 (its page, then its number in it)."""
    tail = c.ref.rsplit("#", 1)[-1] if "#" in c.ref else ""
    if tail.isdigit():
        return ("", int(tail))
    page, _, n = tail.rpartition("-")
    return (page, int(n) if n.isdigit() else 0)


def item(ref: str) -> dict[str, Any] | None:
    """One piece of the knowledge as the search sees it (its parts joined), for a user who may search it."""
    ref = (ref or "").strip()
    if not ITEM_REF.fullmatch(ref):
        return None
    q = _allowed_query().filter(or_(Chunk.ref == ref, Chunk.ref.like(f"{ref}#%")))
    rows = sorted(q.limit(200).all(), key=lambda c: (len(c.ref), c.ref))
    rows = [c for c in rows if _superset_allowed(c)]
    if not rows:
        return None
    first = rows[0]
    parts = sorted(rows, key=_piece_order)
    return {"ref": ref, "kind": first.kind, "title": first.title, "text": "\n\n".join(c.text or "" for c in parts),
            "link": link_of(ref)}


PER_PAGE = 2            # pieces of one page among a search's results at most: the room goes to other pages (on 2,300
                        # documentation pages, the right page among the ten first: 87 out of 100 instead of 86)
SOURCE_LINE = re.compile(r"^Source: (\S+)")
EXCERPT_CHARS = 1200    # of a piece given to the agent: the part of it the query's words are in


def page_of(ref: str, text: str | None) -> str:
    """The page a piece is part of: a document's page (its address, the first line of each of its pieces), else the
    item (an entry, a Context page, a metric...)."""
    base = (ref or "").split("#", 1)[0]
    m = SOURCE_LINE.match(text or "") if base.startswith("doc:") else None
    return f"{base} {m.group(1)}" if m else base


UNCAPPED = {"glossary", "rule", "formula", "definition"}   # each section a term or a rule of its own: never capped


def _terms_uncapped() -> bool:
    try:
        from supagent import settings

        return bool(settings.get("search.terms_uncapped"))
    except Exception:  # pylint: disable=broad-except   (no app: as the default)
        return True


def capped(found: list[dict[str, Any]], k: int, per: int = PER_PAGE) -> list[dict[str, Any]]:
    """The first k pieces, at most `per` of one page; the terms of a glossary and the rules of an entry are each a
    piece of their own (0.9.8: the cap of a page let two terms of a team's glossary through, the definition that
    said which orders are sold among those left out)."""
    out: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    copies: set[tuple[str, str]] = set()
    for f in found:
        ref = f.get("ref") or ""
        key = page_of(ref, f.get("text"))
        m = SOURCE_LINE.match(f.get("text") or "") if ref.startswith("doc:") and "#" in ref else None
        if m:                         # (0.10.0) a page several documents read (a wiki's spaces linking to each other):
            same = (m.group(1), ref.split("#", 1)[1].rsplit("-", 1)[-1])     # its section once, its page capped once
            if same in copies:
                continue
            copies.add(same)
            key = f"page {m.group(1)}"
        if seen.get(key, 0) >= per and not (str(f.get("kind") or "") in UNCAPPED and _terms_uncapped()):
            continue
        seen[key] = seen.get(key, 0) + 1
        out.append(f)
        if len(out) >= k:
            break
    return out


def excerpt(text: str, query: str, size: int = EXCERPT_CHARS) -> str:
    """The part of a piece (`size` characters) that holds the most of the query's words, from a line or a sentence
    start; the piece's address (its "Source:" line) kept in front; "…" where it is cut."""
    from supagent.knowledge.pgstore import words

    text = text or ""
    if len(text) <= size:
        return text
    head = ""
    m = SOURCE_LINE.match(text)
    if m:
        head, text = text[:m.end()] + "\n", text[m.end():].lstrip("\n")
        size = max(200, size - len(head))
        if len(text) <= size:
            return head + text
    wanted = set(words(query))
    starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n" or (ch == " " and i and text[i - 1] in ".:;")]
    found = [(mm.start(), w) for mm in re.finditer(r"[A-Za-z0-9_]+", text) for w in words(mm.group(0)) if w in wanted]
    best, best_at = -1, 0
    for at in starts:
        if at > len(text) - size // 2 and best >= 0:
            break
        got = len({w for pos, w in found if at <= pos < at + size})
        if got > best or (got == best and got > 0):    # the same words from a later start: they open the part
            best, best_at = got, at
    part = text[best_at:best_at + size]
    if best_at + size < len(text):
        cut = max(part.rfind("\n"), part.rfind(". "))
        part = part[:cut + 1] if cut > size // 2 else part
    return head + ("\u2026" if best_at else "") + part.strip() + ("\u2026" if best_at + len(part) < len(text) else "")


# (0.10.6) A question about how the system is built (its parts, what depends on what, a chain, what a failure
# reaches) and not about figures: the System map, the documents and the Context first; the data's objects lower, and
# no "where the value is" first ("How does a user request reach the database?" got "Where the value user is", request
# metrics and charts, and none of the pages that answer it)
STRUCTURE_Q = re.compile(r"\b(?:chain|path|depends?|dependen(?:cy|cies|t)|upstream|downstream|architecture|"
                         r"make\s+up|made\s+of|consists?\s+of|involved|runs?\s+on|running\s+on|behind|"
                         r"reach(?:es|ed)?|goes\s+down|go\s+down|is\s+down|are\s+down|talks?\s+to|connects?\s+to|"
                         r"impact(?:s|ed)?|affected|in\s+order)\b", re.I)
DATA_Q = re.compile(r"\b(?:metrics?|fields?|labels?|index|indexes|indices|columns?|tables?|measures?|counts?|rates?|"
                    r"how\s+many|how\s+much|total|sum|average|mean|median|percent(?:age)?|p\d\d|figures?|values?|"
                    r"yesterday|today|last\s+(?:hour|day|week|month)|between|least|most|highest|lowest|max(?:imum)?|"
                    r"min(?:imum)?|peak|top|busiest|slowest|fastest|january|february|march|april|may|june|july|"
                    r"august|september|october|november|december|sept?|oct|nov|dec|jan|feb|mar|apr|jun|jul|aug)\b",
                    re.I)
DATA_KINDS = ("metric", "family", "index", "chart", "dashboard", "value")   # the data's objects (a question about the
#                                                                           build gets them after the other pieces)


def structural(query: str) -> bool:
    """(0.10.6) A question about how the system is built, not about its data (STRUCTURE_Q and no DATA_Q word)."""
    return bool(STRUCTURE_Q.search(query or "")) and not DATA_Q.search(query or "")


def search(query: str, k: int | None = None, kinds: tuple[str, ...] | None = None,
           lower: dict[str, int] | None = None, skip: tuple[str, ...] = (), rerank: bool = True) -> list[dict[str, Any]]:
    """The pieces for a query, best first, at most PER_PAGE of one page. `lower`: kinds counted as found that many
    places lower (default: the Context, CONTEXT_PLACES); `skip`: kinds left out; `rerank`: the reranker orders the
    first ones again (rerank.url; the router, which must be quick, does without)."""
    from supagent.knowledge import rerank as R
    from supagent.knowledge.index import refresh_map

    refresh_map()                                       # (0.10) the System map's pieces in step with its last change

    k = int(k or settings.get("search.top_k"))
    build = structural(query)             # (0.10.6) how the system is built: no "where the value is" first
    vals = [] if build else _values(query, kinds, skip)   # (0.10.2) where the values the question names are: first
    if not (rerank and R.enabled()):
        found = _search(query, k * 3, kinds, lower, skip)
    else:
        depth = max(k * 3, int(settings.get("rerank.depth") or 40))
        found = R.rerank(query, _search(query, depth, kinds, lower, skip), depth)
    if build:                             # (0.10.6) the map's, the documents' and the Context's pieces first: the
        found = [f for f in found if f["kind"] not in DATA_KINDS] + \
            [f for f in found if f["kind"] in DATA_KINDS]   # data's objects (found by their names' words) after them
    return vals + capped(found, k)


def _values(query: str, kinds: tuple[str, ...] | None, skip: tuple[str, ...]) -> list[dict[str, Any]]:
    """(0.10.2) The pieces saying which metrics' labels and indices' fields hold a value the question names (a
    server, a service, a status...), with the category values named so; none when search.values is off or the
    kinds asked for leave values out."""
    if not settings.get("search.values") or (kinds and "value" not in kinds) or "value" in (skip or ()):
        return []
    try:
        from supagent.knowledge.valueindex import where

        return where(query)
    except Exception as ex:  # pylint: disable=broad-except   (the search goes on without them)
        db.session.rollback()
        log.warning("supagent search: the values' index: %s", str(ex)[:300])
        return []


def _search(query: str, k: int, kinds: tuple[str, ...] | None, lower: dict[str, int] | None,
            skip: tuple[str, ...], n: int | None = None) -> list[dict[str, Any]]:
    from supagent.knowledge import embeddings as E, pgstore

    lower = {"context": CONTEXT_PLACES} if lower is None else lower
    from supagent.knowledge.spelling import correct

    words_query = correct(query)["query"]          # a misspelled word read as the knowledge spells it (0.9.6)
    if pgstore.active():                          # the knowledge store (0.6): BM25, near spellings, pgvector
        try:
            return pgstore.search(query, k, kinds=kinds, lower=lower, skip=skip, n=n, words_query=words_query)
        except Exception as ex:  # pylint: disable=broad-except   (the search of 0.5 answers)
            log.warning("supagent search: the store failed, searched without it: %s", str(ex)[:300])
    q = _allowed_query(kinds)
    if skip:
        q = q.filter(Chunk.kind.notin_(list(skip)))
    found: list[tuple[int, int, str]] = []                # (chunk, rank, list)
    by_words = _lexical(q, _terms(words_query), max(50, int(n or 50)))
    found += [(cid, rank, "words") for rank, cid in enumerate(by_words)]
    by_meaning: set[int] = set()
    if E.enabled():
        try:
            allowed = {cid for (cid,) in q.with_entities(Chunk.id)}
            qv = E.embed([query])[0]
            hits = E.nearest(qv, allowed, max(50, int(n or 50)))
            floor = max(VECTOR_FLOOR, (hits[0][1] - VECTOR_MARGIN) if hits else 0.0)
            words = set(by_words)
            for rank, (cid, score) in enumerate(hits):
                if score < floor and cid not in words:       # a weak neighbour found by meaning only
                    continue
                by_meaning.add(cid)
                found.append((cid, rank, "meaning"))
        except Exception as ex:  # pylint: disable=broad-except   (words still work)
            log.warning("supagent search: vectors not used: %s", ex)
    ranks: dict[int, float] = {}
    if found:
        kinds_of = dict(db.session.query(Chunk.id, Chunk.kind).filter(Chunk.id.in_({cid for cid, _r, _l in found})))
        for cid, rank, _list in found:
            ranks[cid] = ranks.get(cid, 0.0) + 1.0 / (RRF + rank + lower.get(kinds_of.get(cid) or "", 0))
    best = sorted(ranks.items(), key=lambda x: -x[1])[:k + 10]
    if not best:
        return []
    rows = {c.id: c for c in db.session.query(Chunk).filter(Chunk.id.in_([cid for cid, _s in best]))}
    best = [(cid, sc) for cid, sc in best if cid in rows and _superset_allowed(rows[cid])][:k]
    words_found = set(by_words)
    out = []
    for cid, score in best:
        c = rows.get(cid)
        if c is not None:
            via = "words and meaning" if cid in words_found and cid in by_meaning else \
                ("words" if cid in words_found else "meaning")
            out.append({"ref": c.ref, "kind": c.kind, "title": c.title, "text": c.text, "score": round(score, 4),
                        "via": via})
    return out


OBJECT_KINDS = ("metric", "index")
USAGE_LINE = re.compile(r"^(SQL|formulas \(catalog\)):")
LABEL_ABOUT = re.compile(r"(\b[\w.\-]+) \([^()]{15,}\)(?=: )")   # a label's description, before its values
USAGE_CHARS = 320       # a metric's usage lines kept whole in its line of the prompt, at most
OBJECT_PLACES = 3       # in the knowledge found with a question: "Where the data is" gives the data first
CONTEXT_LINES = 2       # at most, the pages about a subject of the question (an application...) first
PAGE_WORDS = ("context ai written overview application data source inventory how the system works architecture "
              "glossary rules and facts")


SUPERSET_KINDS = ("chart", "dashboard")



def usage_apart(text: str) -> tuple[str, str]:
    """(0.10.6) A metric's piece without its usage lines ("SQL: a counter: use the column rate or increase...",
    "formulas (catalog): ...") and those lines, whole ones, USAGE_CHARS at most; the piece unchanged and no usage
    when it fits in its line of the prompt (450 characters) or has no such line."""
    lines = (text or "").splitlines()
    usage = [ln.strip() for ln in lines if USAGE_LINE.match(ln.strip())]
    if not usage or len(" ".join((text or "").split())) <= 450:
        return text, ""
    taken: list[str] = []
    for ln in usage:
        if sum(len(x) + 1 for x in taken) + len(ln) > USAGE_CHARS:
            break
        taken.append(ln)
    if not taken:
        return text, ""
    return "\n".join(ln for ln in lines if ln.strip() not in taken), " ".join(taken)


def knowledge_block(question: str, shown: set[str] | None = None, with_charts: bool = False,
                    prefer: dict[str, int] | None = None) -> str:
    """The knowledge relevant to a question, for the agent's prompt (short). `shown`: what the
    other blocks give already (refs, titles of the metrics and indices): not given twice, nor a
    metric or an index of the same name in another database, so that the room goes to the
    catalog, the documents and the Context. Superset's charts and dashboards only `with_charts` (a
    question about them, or about what is happening now)."""
    shown = set() if shown is None else shown        # the caller's set: it learns what was given (ranking)
    top_k = int(settings.get("search.top_k"))
    try:
        lower = {"context": CONTEXT_PLACES, **{kind: OBJECT_PLACES for kind in OBJECT_KINDS + SUPERSET_KINDS}}
        for kind, places in (prefer or {}).items():         # the router's kind of question: its knowledge first
            lower[kind] = lower.get(kind, 0) + places
        from supagent.knowledge.judge import judged

        found, verdict = judged(question, lambda q: search(  # weak (a word no piece holds, the judge's low score):
            q, k=top_k + len(shown),                          # written again once by the LLM (search.rewrite)
            lower=lower,                                      # data objects, charts: "Where the data is" and the
            skip=() if with_charts else SUPERSET_KINDS),      # tools give them; the room is for the team's words
            top_k + len(shown))                               # (charts: for questions about them)
    except Exception as ex:  # pylint: disable=broad-except
        log.warning("supagent search: %s", ex)
        db.session.rollback()
        return ""
    if not found:
        return ""
    from supagent.knowledge.resolve import gone_names, mentions_gone

    gone = gone_names()
    found = [f for f in found if f["kind"] not in ("recipe", "memory") or not mentions_gone(f["text"], gone)]
    given, kept = set(shown), []
    for f in found:          # one line per metric or index name, glossary term, entry, page of a document
        key = f["title"] if f["kind"] in OBJECT_KINDS else (f["ref"] if f["kind"] == "glossary"
                                                            else page_of(f["ref"], f.get("text")))
        if key in given:
            continue
        given.add(key)
        kept.append(f)
    from supagent.knowledge.experience import words

    asked, generic = words(question), words(PAGE_WORDS)

    def about_it(f: dict[str, Any]) -> bool:          # a Context page named after a subject of the question
        subject = words(f["title"]) - generic
        return bool(subject) and subject <= asked

    pages = [f for f in kept if f["kind"] == "context"]
    pages = ([f for f in pages if about_it(f)] + [f for f in pages if not about_it(f)])[:CONTEXT_LINES]
    found = [f for f in kept if f["kind"] != "context" or f in pages][:top_k]
    found.sort(key=lambda f: f["kind"] == "context" and not about_it(f))   # the others' order kept
    try:                                 # their categories (the application, the subject): which rule is whose
        from supagent.knowledge.facets import facets_of

        cats = facets_of([f["ref"] for f in found])
    except Exception:  # pylint: disable=broad-except
        db.session.rollback()
        cats = {}
    budget = int(settings.get("search.prompt_chars"))
    lines = ["\n\nBackground that looks relevant to this question (from the data dictionary, the catalog, the "
             "team's learned answers and memory, the documents). It is a summary, not an answer: call "
             "describe_data for the fields and their meaning, and run the query for any number; search_knowledge "
             "gives more:"]
    from supagent.knowledge.spelling import correct, said

    read = correct(question)["changes"]          # (cached: the search above read them)
    if read:
        lines[0] += (f"\n(Words of the question no piece of the knowledge holds were searched as the knowledge spells "
                     f"them: {said(read)}.)")
    # (the words no piece holds are said by the search tool, not here: this block's room is for the pieces, and what it
    # says counts as said by the knowledge when a query's conditions are checked)
    if verdict.get("searched_also"):
        lines[0] += "\n(The question was also searched as the AI wrote it again: a word of it matched nothing.)"
    for f in found:
        body, usage = f["text"] or "", ""
        if f["kind"] in OBJECT_KINDS:                 # (0.10.6) how to compute it, kept whole: a window around
            body, usage = usage_apart(body)           # the question's words cut "SQL: a counter: use rate or
            if usage and all(" ".join(u.split()) in " ".join(excerpt(f["text"] or "", question, 450).split())
                             for u in usage.split(" formulas (catalog): ")[:1]):   # increase, never SUM" when the
                body, usage = f["text"] or "", ""     # labels' descriptions were long (a count summed from the
            elif usage:                               # per-second rate): the room taken from those descriptions,
                body = LABEL_ABOUT.sub(r"\1", body)    # the labels and their values kept
        size = max(180, 450 - len(usage))
        text = " ".join(excerpt(body, question, size).split())
        about = [t.split(": ", 1)[1] for t in cats.get(f["ref"], []) if not t.startswith("aspect")][:3]
        line = (f"- [{f['kind']}] {f['title']}" + (f" ({', '.join(about)})" if about else "") + f": {text[:size]}"
                + (f" {usage}" if usage else ""))
        if sum(len(x) for x in lines) + len(line) > budget:
            break
        lines.append(line)
        shown.add(f["ref"])
    return "\n".join(lines) if len(lines) > 1 else ""
