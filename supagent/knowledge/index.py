"""The searchable pieces of knowledge (supagent_chunk), kept in step with what they come from:

  metric / index   one piece per metric or index (its labels or fields summarised in it; one
                   piece per field would cost hundreds of thousands of embeddings on OTel data)
  rule / note / glossary / formula   the catalog's text entries (notes cut into parts)
  recipe           the learned answers (marked Helpful or confirmed by an admin)
  memory           the preferences, rules and facts of a user or of the team (active ones)
  doc              the parts of the documents and sites (page by page, each with its address)

`sync()` writes the pieces whose text changed (and removes the ones whose origin is gone):
cheap, done after a learning run, a catalog change, an answer. `embed_pending()` gives the new
or changed pieces their vector (the embedding model), a batch at a time.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import re
from typing import Any, Iterator

from superset import db

from supagent import settings
from supagent.models import Chunk, Doc, Entry, KObject, Memory, Recipe

log = logging.getLogger(__name__)
PART_CHARS = 1500
OVERLAP = 200


def _hash(*parts: Any) -> str:
    return hashlib.sha256("\x1f".join(str(p or "") for p in parts).encode()).hexdigest()[:40]


def split_text(text: str, size: int = PART_CHARS, overlap: int = OVERLAP) -> list[str]:
    """Parts of about `size` characters, cut at paragraph or sentence ends, overlapping a little (from a word's
    start)."""
    text = (text or "").strip()
    if len(text) <= size:
        return [text] if text else []
    parts, start = [], 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = max(text.rfind("\n\n", start, end), text.rfind(". ", start, end))
            if cut > start + size // 2:
                end = cut + 1
        parts.append(text[start:end].strip())
        if end >= len(text):
            break
        nxt = max(end - overlap, start + 1)
        space = text.find(" ", nxt, end)
        start = space + 1 if space >= 0 else nxt
    return [p for p in parts if p]


HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
HEADING_ATTRS = re.compile(r"\s*\{[:#][^}]*\}\s*$")     # {: .label} {#an-id} after a heading (kramdown, Pandoc)
FENCE = re.compile(r"^[ \t]*(```|~~~)")
SHORT_SECTION = 300      # a section shorter than this (a heading and a line) goes with the next one
PACK_SIBLINGS = True     # the sections that follow (siblings too) go together while they fit
SECTION_CHARS = 2000     # a section and the ones after it together, up to this (2,000 rather than 1,500: 26%
#                          fewer pieces, words scattered over a section found better, topics the same)


def sections(text: str) -> list[tuple[list[str], str]]:
    """The sections of a Markdown text, in order: (the headings above it, the outermost first, its own last; its text
    from its heading line). A text with no heading is one section under none. A heading inside a code block is not
    one."""
    out: list[tuple[list[str], str]] = []
    path: list[tuple[int, str]] = []
    here: list[str] = []
    lines: list[str] = []
    fence = None
    for line in (text or "").split("\n"):
        m = None
        f = FENCE.match(line)
        if f:
            fence = None if fence == f.group(1) else (fence or f.group(1))
        elif fence is None:
            m = HEADING.match(line)
        if m:
            if "".join(lines).strip():
                out.append((here, "\n".join(lines).strip()))
            level, title = len(m.group(1)), HEADING_ATTRS.sub("", m.group(2)).strip()
            path = [(lv, t) for lv, t in path if lv < level] + [(level, title)]
            here, lines = [t for _lv, t in path], []
        lines.append(line)
    if "".join(lines).strip():
        out.append((here, "\n".join(lines).strip()))
    return out


def split_sections(text: str, size: int | None = None, overlap: int = OVERLAP) -> list[tuple[str, str]]:
    """Parts of a text cut at its sections (Markdown headings) first: (the headings of the part, "A \u203a B", ""
    for none; its text). A section and the sections under it go together while they fit in `size`; a section too long
    is cut as split_text cuts, each part under its headings; a short section (a heading and a line) goes with the
    next one. A text with no heading: split_text's parts."""
    size = size or SECTION_CHARS
    secs = sections(text)
    if len(secs) <= 1 and not (secs and secs[0][0]):
        return [("", p) for p in split_text(text, size, overlap)]
    out: list[tuple[str, str]] = []
    cur: list[tuple[list[str], str]] = []

    def flush() -> None:
        if not cur:
            return
        head = cur[0][0]
        others = [p[-1] for p, _t in cur[1:] if p and p[:len(head)] != head]     # a sibling taken along
        label = " \u203a ".join(head) + ("".join(f" \u00b7 {t}" for t in others[:3]) if others else "")
        out.append((label, "\n\n".join(t for _p, t in cur)))
        cur.clear()

    for path, body in secs:
        if len(body) > size:
            flush()
            for part in split_text(body, size, overlap):
                out.append((" \u203a ".join(path), part))
            continue
        if cur:
            length = sum(len(t) + 2 for _p, t in cur)
            head = cur[0][0]
            under = len(path) > len(head) and path[:len(head)] == head
            if length + len(body) > size or not (under or length < SHORT_SECTION or PACK_SIBLINGS):
                flush()
        cur.append((path, body))
    flush()
    return out


# --------------------------------------------------------------------------- #
# the pieces
# --------------------------------------------------------------------------- #
def _object_pieces(only: set[int] | None = None) -> Iterator[dict[str, Any]]:
    """One piece per metric and index (`only`: of these ids)."""
    from supagent.knowledge.experience import COUNTER_SUFFIXES, counter_formulas

    tops = db.session.query(KObject).filter(KObject.kind.in_(("metric", "index")), KObject.gone_at.is_(None))
    if only is not None:
        tops = tops.filter(KObject.id.in_(list(only) or [-1]))
    tops = tops.all()
    kids_q = db.session.query(KObject).filter(KObject.kind.in_(("label", "field")), KObject.gone_at.is_(None))
    if only is not None:                                   # the children of these only
        kids_q = kids_q.filter(KObject.source_id.in_({o.source_id for o in tops} or {-1}),
                               KObject.parent.in_({o.name for o in tops} or {""}))
    children: dict[tuple[int, str], list[KObject]] = {}
    for o in kids_q:
        children.setdefault((o.source_id, o.parent), []).append(o)
    for o in tops:
        st = o.stats or {}
        kids = children.get((o.source_id, o.name), [])
        lines = [f"{o.kind} {o.name}" + (f" ({o.metric_type}{', ' + o.unit if o.unit else ''})" if o.metric_type
                                           else ""),
                 (o.description or "").strip()]
        if o.synonyms:
            lines.append("also called: " + ", ".join(map(str, o.synonyms)))
        if o.category:
            lines.append(f"category: {o.category}")
        # no counts here (series, documents: they change every run, and a changed text is embedded
        # again): the text changes when the meaning does
        if st.get("time_field"):
            lines.append(f"time field {st['time_field']}")
        if st.get("kind"):                   # logs and their shipper, spans... (0.9.5: found by what they are)
            from supagent.knowledge.indexkinds import line as kind_line

            lines.append(kind_line(st["kind"]))
        if st.get("data_stream"):
            lines.append("a data stream (rolled over into hidden backing indices)")
        others = [n["name"] for n in st.get("names") or []] + [p["name"] for p in st.get("parts") or []]
        if others:                           # its other names and the aliases on a part of it (0.9.5)
            lines.append("also reached as: " + ", ".join(others))
        same = sorted({m.group(1) for s in st.get("same_events") or [] for m in [re.search(r'also in "([^"]+)"', s)] if m})
        if same:
            lines.append("the same events as: " + ", ".join(same))
        said = st.get("data_says") or {}
        if said.get("increases_only"):
            lines.append("its values only increase: it counts (its increase over a period, never its value)")
        if said.get("goes_down"):
            lines.append("a level, not a count (its values go up and down)")
        kid_word = "labels" if o.kind == "metric" else "fields"
        described = []
        for k in sorted(kids, key=lambda x: x.name)[:120]:
            item = k.name
            if k.description:
                item += f" ({k.description[:120]})"
            elif (k.stats or {}).get("computed"):
                item += f" ({k.stats['computed']})"
            kst = k.stats or {}
            vals = kst.get("values") or []
            if vals and len(vals) <= 20 and not kst.get("partial"):     # every value, not a sample
                item += ": " + ", ".join(sorted(map(str, vals))[:8])
            described.append(item)
        if described:
            lines.append(f"{kid_word}: " + "; ".join(described))
        if o.kind == "metric":
            if o.metric_type in ("counter", "histogram", "summary") or o.name.endswith(COUNTER_SUFFIXES):
                lines.append("SQL: a counter: use the column rate (per second) or increase (per time bucket); "
                             "value is cumulative, never SUM or AVG it")
            formulas = counter_formulas(o.name)
            if formulas:
                lines.append("formulas (catalog): " + " | ".join(formulas)[:900])
        yield {"ref": f"object:{o.id}", "kind": o.kind, "source_id": o.source_id, "title": f"{o.kind} {o.name}",
               "text": "\n".join(x for x in lines if x)[:4000]}


def _entry_pieces() -> Iterator[dict[str, Any]]:
    from supagent.knowledge.glossary import entry_terms

    for e in db.session.query(Entry).filter(Entry.deleted_at.is_(None), Entry.enabled.is_(True),
                                            Entry.classification.in_(("rule", "guide", "glossary", "formula"))):
        # a formula the agent learned on a database: found only by the users who may query it
        database_id = (e.evidence or {}).get("database_id") if e.origin and e.classification == "formula" else None
        terms = entry_terms(e) if e.classification == "glossary" else []
        for ref, term, definition in terms:            # a term, its own piece: found for its own words
            yield {"ref": ref, "kind": "glossary", "database_id": None,
                   "title": f"{term} ({e.category or 'glossary'})", "text": f"{term}: {definition}"}
        if terms:
            continue
        for i, (where, part) in enumerate(split_sections(e.content or "")):
            yield {"ref": f"entry:{e.id}#{i}", "kind": e.classification, "database_id": database_id,
                   "title": _titled(e.title, where, f" ({e.category})" if e.category else ""), "text": part}


def _recipe_pieces() -> Iterator[dict[str, Any]]:
    from supagent.knowledge.experience import USED

    for r in db.session.query(Recipe).filter(Recipe.status.in_(USED)):
        yield {"ref": f"recipe:{r.id}", "kind": "recipe", "database_id": r.database_id or 0,   # unknown: nobody
               "title": f"answered before ({r.status}): {(r.question or '')[:200]}",
               "text": f"{r.question}\n{r.tool}: {(r.query or '')[:2500]}"}


def _memory_pieces() -> Iterator[dict[str, Any]]:
    for m in db.session.query(Memory).filter(Memory.status == "active"):
        yield {"ref": f"memory:{m.id}", "kind": "memory", "scope": m.scope,
               "user_id": m.user_id if m.scope == "user" else None,
               "title": f"{m.kind} ({'team' if m.scope == 'team' else 'personal'})"
               + (f", {m.category}" if m.category else ""), "text": m.text}


def _doc_pages(d: Doc) -> list[tuple[str, str, str]] | None:
    """(address, title, text) of each page of a document read page by page (doc.pages with where each page's
    text starts in its content); None for an upload or a document read by an older version (one text)."""
    content, pages = d.content or "", d.pages or []
    if not pages or not all(isinstance(p, dict) and isinstance(p.get("at"), int) and isinstance(p.get("chars"), int)
                            for p in pages):
        return None
    out = []
    for p in pages:
        if p["at"] < 0 or p["at"] + p["chars"] > len(content):
            return None                               # the text changed without its pages: one text
        out.append((str(p.get("url") or ""), str(p.get("title") or ""), content[p["at"]:p["at"] + p["chars"]]))
    return out


def _doc_pieces() -> Iterator[dict[str, Any]]:
    """The parts of the documents: page by page (a part never mixes two pages), each named after its document
    and its page and starting with the page's address, for the agent to say where it read it."""
    for d in db.session.query(Doc).filter(Doc.enabled.is_(True), Doc.content.isnot(None)):
        name = d.title or d.url or f"document {d.id}"
        category = f" ({d.category})" if d.category else ""
        pages = _doc_pages(d)
        if pages is None:
            for i, (where, part) in enumerate(split_sections(d.content or "")):
                yield {"ref": f"doc:{d.id}#{i}", "kind": "doc", "title": _titled(name, where, category), "text": part}
            continue
        for url, title, text in pages:
            named = f"{name} \u203a {title}" if title and title != name else name
            key = hashlib.sha1((url or title).encode("utf-8")).hexdigest()[:10]
            for j, (where, part) in enumerate(split_sections(text)):   # named after its page (0.9.6.1): a page
                yield {"ref": f"doc:{d.id}#{key}-{j}", "kind": "doc",      # changed makes again its pieces only
                       "title": _titled(named, where, category), "text": f"Source: {url}\n{part}" if url else part}


def _titled(name: str, where: str, category: str = "") -> str:
    """A piece's title: its document (and page), the headings of its section, its category; the piece's title
    column holds 512 characters (the section's headings cut first)."""
    if where and where.split(" \u203a ")[0].strip().lower() == name.rsplit(" \u203a ", 1)[-1].strip().lower():
        where = " \u203a ".join(where.split(" \u203a ")[1:])      # the page's own title as its first heading
    full = f"{name} \u203a {where}" if where else name
    return full[:480 - len(category)] + category


CATALOG_COPIES = ("glossary", "rules-and-facts")       # Context pages that gather catalog entries and memories


def _context_pieces() -> Iterator[dict[str, Any]]:
    """The Context pages (search filters them by the databases each one draws from)."""
    from supagent.models import ContextPage

    for p in db.session.query(ContextPage):
        if p.kind == "facts" and p.slug in CATALOG_COPIES:
            continue                                    # the catalog's own pieces are searched
        if p.kind == "rejected":
            continue                                    # a new page a person refused: not searched
        ai = p.kind == "summary" and (p.author or "agent") == "agent"
        label = "Context (AI-written overview)" if ai else "Context"
        for i, (where, part) in enumerate(split_sections(p.content or "")):
            yield {"ref": f"context:{p.id}#{i}", "kind": "context", "title": _titled(f"{label}: {p.title}", where),
                   "text": part}


def _filters_text(params: dict) -> str:
    out = []
    for f in params.get("adhoc_filters") or []:
        if isinstance(f, dict) and f.get("expressionType") == "SIMPLE":
            out.append(f"{f.get('subject')} {f.get('operator')} {f.get('comparator')}")
        elif isinstance(f, dict) and f.get("sqlExpression"):
            out.append(str(f["sqlExpression"])[:120])
    return "; ".join(out)


def _metric_names(params: dict) -> list[str]:
    out = []
    for m in (params.get("metrics") or []) + ([params["metric"]] if params.get("metric") else []):
        if isinstance(m, str):
            out.append(m)
        elif isinstance(m, dict):
            out.append(str(m.get("label") or m.get("sqlExpression") or
                           f"{m.get('aggregate')}({(m.get('column') or {}).get('column_name')})"))
    return out


def _superset_pieces() -> Iterator[dict[str, Any]]:
    """Superset's charts and dashboards: what each shows (its dataset, metrics, dimensions, filters, time
    range, the dashboards it is on), found for a question about a subject ("what is happening now with
    the gateway"). Each piece is about one database: seen only by the users who may query it."""
    import json

    try:
        from superset.connectors.sqla.models import SqlaTable
        from superset.models.dashboard import Dashboard
        from superset.models.slice import Slice
    except Exception:  # pylint: disable=broad-except
        return
    from superset.models.core import Database

    tables = {t.id: t for t in db.session.query(SqlaTable)}
    db_names = {i: n for i, n in db.session.query(Database.id, Database.database_name)}
    try:                                     # what the nightly look found and wrote (0.7): no figure here
        from supagent.knowledge.charts import summary_line
        from supagent.models import ChartScan

        scans = {r.chart_id: r for r in db.session.query(ChartScan)}
    except Exception:  # pylint: disable=broad-except   (the table comes with superset supagent init)
        db.session.rollback()
        scans, summary_line = {}, None
    boards: dict[int, list[Any]] = {}
    for d in db.session.query(Dashboard):
        for sl in d.slices or []:
            boards.setdefault(sl.id, []).append(d)
    per_board: dict[tuple[int, int], list[str]] = {}
    for sl in db.session.query(Slice):
        t = tables.get(sl.datasource_id) if sl.datasource_type == "table" else None
        if t is None:
            continue
        try:
            params = json.loads(sl.params or "{}")
        except ValueError:
            params = {}
        dims = [str(x if isinstance(x, str) else (x or {}).get("label") or "") for x in
                (params.get("groupby") or []) + ([params["x_axis"]] if params.get("x_axis") else [])]
        where = " (a query: " + " ".join((t.sql or "").split())[:300] + ")" if t.sql else ""
        lines = [f"chart {sl.slice_name} ({sl.viz_type}) on the dataset {t.table_name} (id {t.id}) of database "
                 f'{t.database_id} "{db_names.get(t.database_id, "")}"{where}',
                 "metrics: " + ", ".join(_metric_names(params)[:8]) if _metric_names(params) else "",
                 "by: " + ", ".join(d for d in dims if d)[:300] if any(dims) else "",
                 "filters: " + _filters_text(params) if _filters_text(params) else "",
                 f"time range: {params.get('time_range')}" if params.get("time_range") else "",
                 "on the dashboards: " + ", ".join(sorted({b.dashboard_title for b in boards.get(sl.id, [])}))
                 if boards.get(sl.id) else "",
                 f"chart id {sl.id}"]
        scan = scans.get(sl.id)
        if scan is not None and scan.understanding:
            lines.append("what it shows (AI-written): " + " ".join(scan.understanding.split())[:600])
        if scan is not None and summary_line is not None and summary_line(scan):
            lines.append(summary_line(scan))
        yield {"ref": f"superset:chart:{sl.id}", "kind": "chart", "database_id": t.database_id,
               "title": f"chart {sl.slice_name}", "text": "\n".join(x for x in lines if x)}
        for b in boards.get(sl.id, []):
            per_board.setdefault((b.id, t.database_id), []).append(f"{sl.slice_name} ({sl.viz_type}, "
                                                                    f"{', '.join(_metric_names(params)[:3])})")
    titles = {d.id: d for d in db.session.query(Dashboard)}
    for (board_id, database_id), charts in per_board.items():
        d = titles.get(board_id)
        if d is None:
            continue
        yield {"ref": f"superset:dashboard:{board_id}:{database_id}", "kind": "dashboard", "database_id": database_id,
               "title": f"dashboard {d.dashboard_title}",
               "text": f"dashboard {d.dashboard_title} (dashboard id {board_id}), its charts on database {database_id} "
                       f'"{db_names.get(database_id, "")}": ' + "; ".join(charts[:40])}


def _note_pieces() -> Iterator[dict[str, Any]]:
    """The notes users write (0.7): the team's for everyone, a personal one for its author only."""
    from supagent.knowledge.notes import pieces as note_pieces

    yield from note_pieces()


def _mcp_pieces() -> Iterator[dict[str, Any]]:
    """The tools of the other MCP servers (mcp.servers): the decider routes questions to them."""
    try:
        from supagent import mcp_sources

        if mcp_sources.servers():
            yield from mcp_sources.pieces()
    except Exception:  # pylint: disable=broad-except   (a server down: its pieces stay as they were)
        log.warning("supagent index: MCP tools not read", exc_info=True)


KINDS = (("object:", _object_pieces), ("entry:", _entry_pieces), ("recipe:", _recipe_pieces),
         ("memory:", _memory_pieces), ("doc:", _doc_pieces), ("context:", _context_pieces),
         ("superset:", _superset_pieces), ("mcp:", _mcp_pieces), ("note:", _note_pieces))


def pieces(prefixes: tuple[str, ...] | None = None) -> Iterator[dict[str, Any]]:
    """Every piece (`prefixes`: only the kinds of these refs: a memory saved does not read the
    whole dictionary again)."""
    for prefix, make in KINDS:
        if prefixes is None or any(p.startswith(prefix) or prefix.startswith(p) for p in prefixes):
            yield from make()


# --------------------------------------------------------------------------- #
# keeping the chunks in step
# --------------------------------------------------------------------------- #
def sync(prefixes: tuple[str, ...] | None = None, dry_run: bool = False) -> dict[str, Any]:
    """Write the pieces that changed, remove the ones whose origin is gone. `prefixes` limits
    the work to some kinds of refs (e.g. ("recipe:",) after an answer); `dry_run`: only count
    (and name a few of) what would be written (the knowledge check)."""
    existing = {c.ref: c for c in db.session.query(Chunk)
                if prefixes is None or c.ref.startswith(prefixes)}
    wanted = (p for p in pieces(prefixes) if prefixes is None or p["ref"].startswith(prefixes))
    return _write(existing, wanted, dry_run)


def sync_objects(ids: list[int] | set[int]) -> dict[str, int]:
    """The pieces of these metrics and indices, or of the metric or index of these labels and
    fields, at once (after a person's edit: not the whole dictionary)."""
    tops: set[int] = set()
    for o in db.session.query(KObject).filter(KObject.id.in_(list(ids) or [-1])):
        if o.kind in ("metric", "index"):
            tops.add(o.id)
            continue
        parent = (db.session.query(KObject.id).filter(KObject.source_id == o.source_id, KObject.name == o.parent,
                                                       KObject.kind == ("metric" if o.kind == "label" else "index"))
                  .first())
        if parent is not None:
            tops.add(parent[0])
    refs = [f"object:{i}" for i in tops]
    existing = {c.ref: c for c in db.session.query(Chunk).filter(Chunk.ref.in_(refs or ["-"]))}
    return _write(existing, _object_pieces(only=tops))


def _write(existing: dict[str, Chunk], wanted: Iterator[dict[str, Any]], dry_run: bool = False) -> dict[str, Any]:
    """The chunks of `existing` made like the pieces `wanted` (new, changed, removed)."""
    from supagent.knowledge.embeddings import qdrant_delete

    seen: set[str] = set()
    out: dict[str, Any] = {"added": 0, "changed": 0, "removed": 0, "unchanged": 0}
    touched = False                                  # the dictionary or the catalog changed
    for p in wanted:
        seen.add(p["ref"])
        h = _hash(p.get("title"), p.get("text"), p.get("source_id"), p.get("database_id"), p.get("scope"),
                  p.get("user_id"))
        c = existing.get(p["ref"])
        if c is not None and c.content_hash == h:
            out["unchanged"] += 1
            continue
        if dry_run:
            out["added" if c is None else "changed"] += 1
            out.setdefault("examples", []).append(p.get("title") or p["ref"])
            continue
        if c is None:
            c = Chunk(ref=p["ref"])
            db.session.add(c)
            out["added"] += 1
        else:
            out["changed"] += 1
        touched = touched or p["ref"].startswith(("object:", "entry:"))
        c.kind, c.title, c.text = p["kind"], (p.get("title") or "")[:512], p.get("text") or ""
        c.source_id, c.database_id = p.get("source_id"), p.get("database_id")
        c.scope, c.user_id = p.get("scope") or "team", p.get("user_id")
        c.content_hash, c.vector, c.embed_model = h, None, None     # a new text needs a new vector
        c.updated_at = dt.datetime.utcnow()
    gone = [c for ref, c in existing.items() if ref not in seen]
    if dry_run:
        out["removed"] = len(gone)
        out["examples"] = (out.get("examples") or [])[:8] + [f"(gone) {c.title}" for c in gone[:4]]
        db.session.rollback()
        return out
    for c in gone:
        db.session.delete(c)
    out["removed"] = len(gone)
    if touched or any(c.ref.startswith(("object:", "entry:")) for c in gone):
        from supagent.knowledge.freshness import touch

        touch()                                      # every process: its caches made again
    db.session.commit()
    if gone:
        try:
            qdrant_delete([c.id for c in gone])
        except Exception as ex:  # pylint: disable=broad-except
            log.warning("supagent: qdrant delete: %s", ex)
    if out["added"] or out["changed"] or out["removed"]:
        _store_sync(tuple(sorted({ref.split(":")[0] + ":" for ref in seen} | {c.ref.split(":")[0] + ":"
                                                                               for c in gone})))
    return out


def _store_sync(prefixes: tuple[str, ...] | None) -> None:
    """The knowledge store (pgstore) in step with the pieces just written (their kinds only)."""
    try:
        from supagent.knowledge import pgstore

        if pgstore.active():
            pgstore.sync(prefixes=prefixes, chats=False)
    except Exception as ex:  # pylint: disable=broad-except   (the hourly sync catches up)
        log.warning("supagent: the knowledge store was not updated: %s", str(ex)[:300])


def embed_few(out: dict[str, int]) -> None:
    """After a change of a few pieces (`out` of sync): their vectors at once, so that the search
    finds them by meaning too (more pieces: at the next indexing, hourly)."""
    if 0 < out.get("added", 0) + out.get("changed", 0) <= 64:
        try:
            embed_pending(limit=64)
        except Exception as ex:  # pylint: disable=broad-except   (found by words meanwhile)
            db.session.rollback()
            log.warning("supagent: vectors of the new pieces: %s", ex)


def embed_pending(limit: int | None = None) -> dict[str, Any]:
    """Vectors for the pieces that have none (or another model's), the newest first."""
    from supagent.knowledge import embeddings as E

    if not E.enabled():
        return {"embedded": 0, "note": "no embedding model (embed.model): search by words only"}
    model = E.model()
    limit = int(limit or settings.get("embed.per_run"))
    todo = (db.session.query(Chunk).filter((Chunk.vector.is_(None)) | (Chunk.embed_model != model))
            .order_by(Chunk.updated_at.desc(), Chunk.id).limit(limit).all())
    done, batch = 0, max(1, int(settings.get("embed.batch")))
    qdrant = settings.get("search.vector_store") == "qdrant"
    from supagent.knowledge.stopping import check

    for i in range(0, len(todo), batch):
        check()                                    # an admin stopped the learning run
        part = todo[i:i + batch]
        vectors = E.embed([f"{c.title}\n{c.text}" for c in part])
        for c, v in zip(part, vectors):
            c.vector = E.to_bytes(v)
            c.embed_model = model
        if qdrant:
            E.qdrant_upsert([(c.id, v) for c, v in zip(part, vectors)])
        db.session.commit()
        done += len(part)
    left = db.session.query(Chunk).filter((Chunk.vector.is_(None)) | (Chunk.embed_model != model)).count()
    if done:
        _store_sync(None)                          # the new vectors into the store
    return {"embedded": done, "left": left}


def index_knowledge() -> dict[str, Any]:
    out: dict[str, Any] = {"sync": sync()}
    try:
        out["embed"] = embed_pending()
    except Exception as ex:  # pylint: disable=broad-except
        db.session.rollback()
        out["embed"] = {"error": str(ex)[:300]}
    return out
