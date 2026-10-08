"""The knowledge store in PostgreSQL (0.6): everything the agent searches, in one place, found three ways at
once and the ranks fused:

  words     BM25 (pg_textsearch: a rare word counts more than a common one), else PostgreSQL's full-text
            search, on the words of each piece (names cut at _ and at capitals, light stems, EN and FR)
  spelling  pg_trgm: a name or a value typed with a typo or in part (BILLING_APY, payrol, cpu secs), the names
            the documents and the code write too (custom_icu_anbalyzer: their config keys, settings, functions); the words
            of the pieces as written (surf_<v>, a trigram GiST index): the nearest ones to a word of a question no
            piece holds, for reading it as the knowledge spells it (spelling.py: two slips, a key far away)
  meaning   pgvector: the vectors of the embedding model (embed.model) in an HNSW index; they stay in
            PostgreSQL, not in the memory of every process, however many pieces there are

It holds the searchable pieces (supagent_chunk: dictionary, catalog, learned answers, memories, documents,
Context, charts and dashboards, MCP tools) with their vectors, the names and values of the data (near
spellings), each user's chats (found by their owner only) and the routes people confirmed (which tables
answered which question: the decider's votes for the questions like it).

It is derived from Superset's database and may be wiped at any time: `rebuild()` makes a new version beside
the one in use and then switches to it, `wipe()` drops the schema. It lives in a schema of its own
(search.store_schema), in Superset's database or another PostgreSQL (search.store_uri), reached through
connections of its own: autocommit, one statement at a time, closed after use (pg_textsearch before 0.6.1
fails a ROLLBACK after an error: see `status()`). search.store = off, an extension missing or an
error: the search of 0.5 answers instead, and nothing else depends on the store.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
import time
import unicodedata
from collections import Counter
from typing import Any, Iterable, Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine, make_url
from sqlalchemy.pool import NullPool
from superset import db

from supagent import settings

log = logging.getLogger(__name__)

CANDIDATES = 60            # pieces each way of searching gives to the fusion
BM25_POOL = 1000           # BM25's best pieces before the permission filter (a filter inside the scan of
                           # pg_textsearch 0.5 may leave fewer than asked)
RRF = 60
WAYS = {"words": 1.0, "meaning": 1.0, "spelling": 0.6}      # weight of each way in the fusion (ranks: RRF)
FUSION = "mixed"           # how the ways' lists are fused: "cc" (their scores, each list's scaled to 0..1, weighted:
                           # CC_WAYS; a piece found by one way only keeps the strength it was found with), "rrf" (ranks:
                           # a piece in two lists beats the best piece by words found by words only), "mixed": a
                           # question written as a sentence by ranks, a list of keywords or a name by scores (0.10, on
                           # 2,300 pages: cc found the right first page of keyword and name questions far more often,
                           # rrf kept natural questions better: mixed keeps both)
CC_WAYS = {"words": 1.0, "meaning": 0.3, "spelling": 0.4}     # a list of keywords, a name: the words first
CC_MEANING_SENTENCE = 0.8   # the meaning's weight for a question written as a sentence (3 words or more, one of them a
                            # function word: "how do I ...", "what is ..."), where the words alone say less (None: as
                            # CC_WAYS). Measured with a small embedding model (keywords 0.3 best of 0.3-1.0; sentences
                            # the same from 0.5 to 0.8): to measure again with the model in use
CC_PLACE = 0.015           # "cc": a place lower (search's `lower`) is this much less
SPELLING_MIN = 0.5         # pg_trgm word similarity of a word (or a name) of the question and a name or a value
                           # (BILLNG ~ BILLING: 0.57)
NAMES_PER_WORD = 8
VECTOR_FLOOR, VECTOR_MARGIN = 0.35, 0.2     # as search.py: a piece found by meaning only must be close enough
INSERT_ROWS = 200
CHAT_ANSWER_CHARS = 1200
STATE_SECONDS = 20.0
SAFE_TEXTSEARCH = (0, 6, 1)     # 0.5.0: Block-Max WAND may skip matches (fixed in 0.5.1: switched off below
                                # 0.5.1); before 0.6.1 a ROLLBACK after an error fails in a session that loaded
                                # the library (pg_textsearch #247, seen on 18.3): never a transaction from here
EXTENSIONS = ("vector", "pg_trgm", "pg_textsearch")
STOP_EXTRA = {"total", "count", "number", "value", "values", "data", "metric", "metrics", "index", "field"}
NEAR_CANDIDATES = 30       # the words of the pieces nearest to a word of a question (trigram distance), for spelling.py
IDENTS_PER_PIECE = 200     # the names a piece writes (config keys, settings, functions, metrics...) among the names of the
                           # near-spelling search, at most (0: none)
IDENT_MATCHES = 30         # the pieces writing a name typed in a question (exactly or nearly), at most
IDENT_IN_TEXT = re.compile(r"(?<![\w./:-])(?:[A-Za-z][A-Za-z0-9]*(?:[_.\-][A-Za-z0-9]+)+|[a-z]+(?:[A-Z][a-z0-9]+)+)"
                           r"(?![\w(/-])(?!:\S)")      # a key before ": value" counts, host:port or a URL does not
SURFACE_LETTERS = (4, 40)  # the words of the pieces kept as written: letters only, this many


class StoreError(Exception):
    pass


# --------------------------------------------------------------------------------------------- #
# words
# --------------------------------------------------------------------------------------------- #
def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def _split_names(s: str) -> str:
    """node_cpu_seconds_total, MemAvailable, ORDER-REPORT: node cpu seconds total, mem available, order report."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", _fold(s))
    return re.sub(r"[^A-Za-z0-9]+", " ", s).lower().strip()


def words(s: str) -> list[str]:
    """The words the store indexes and searches with: names cut, accents out, light stems, no stop words."""
    from supagent.knowledge.describe import STOP, stem

    return [stem(w) for w in _split_names(s).split() if w not in STOP and (len(w) > 1 or w.isdigit())]


def surface(s: str) -> set[str]:
    """The words of a text as written (names cut, accents out, lower case), letters only, SURFACE_LETTERS long: what
    a word of a question no piece holds is compared with (near_words)."""
    lo, hi = SURFACE_LETTERS
    return {w for w in _split_names(s).split() if lo <= len(w) <= hi and w.isalpha()}


def terms_text(title: str, body: str, extra: str = "") -> str:
    t = " ".join(words(title))
    return " ".join(x for x in (t, t, " ".join(words(extra)), " ".join(words(body))) if x)   # the title counts twice


IDENTIFIER = re.compile(r"[A-Za-z0-9]+(?:[_\-.:/][A-Za-z0-9]+)+|[a-z]+[A-Z][A-Za-z0-9]*")


def spelling_words(question: str) -> list[str]:
    """What of the question is worth a near-spelling search: its names as typed (node_cpu_secnds_total, written
    as the store writes names: node cpu secnds total) and its words of at least 5 letters, no stop words."""
    from supagent.knowledge.describe import STOP

    out = [_split_names(m.group(0)) for m in IDENTIFIER.finditer(question or "")]
    out += [w for w in _split_names(question).split() if len(w) >= 5 and not w.isdigit() and w not in STOP
            and w not in STOP_EXTRA]
    return list(dict.fromkeys(out))[:24]


# --------------------------------------------------------------------------------------------- #
# connections
# --------------------------------------------------------------------------------------------- #
_ENGINES: dict[str, Engine] = {}
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"at": 0.0, "value": None, "key": None}


def schema() -> str:
    s = (settings.get("search.store_schema") or "supagent_store").strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,40}", s):
        raise StoreError(f"search.store_schema {s!r}: lower-case letters, digits and _ only")
    return s


def _url() -> Any:
    uri = (settings.get("search.store_uri") or "").strip()
    return make_url(uri) if uri else db.engine.url


def engine() -> Engine | None:
    """The store's engine (None: no PostgreSQL to hold it)."""
    url = _url()
    if url.get_backend_name() != "postgresql":
        return None
    key = url.render_as_string(hide_password=False) + "|" + schema()
    with _LOCK:
        e = _ENGINES.get(key)
        if e is None:
            e = create_engine(url, poolclass=NullPool, isolation_level="AUTOCOMMIT")
            event.listen(e, "connect", _on_connect(schema()))
            _ENGINES[key] = e
    return e


def _on_connect(store_schema: str) -> Any:
    def setup(dbapi_con: Any, _record: Any) -> None:
        cur = dbapi_con.cursor()
        cur.execute("SELECT DISTINCT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
                    "WHERE e.extname IN %s", (EXTENSIONS,))
        path = list(dict.fromkeys([store_schema] + [r[0] for r in cur.fetchall()] + ["public"]))
        cur.execute("SET search_path TO " + ", ".join('"' + p.replace('"', '""') + '"' for p in path))
        cur.execute("SELECT extversion FROM pg_extension WHERE extname = 'pg_textsearch'")
        row = cur.fetchone()
        if row and _version(row[0]) < (0, 5, 1):
            cur.execute("SET pg_textsearch.enable_bmw = off")      # 0.5.0 could skip valid matches
        for sql in ("SET statement_timeout = '15s'", "SET hnsw.ef_search = 100",
                    "SET hnsw.iterative_scan = relaxed_order", f"SET pg_trgm.word_similarity_threshold = {SPELLING_MIN}",
                    f"SET pg_trgm.similarity_threshold = {SPELLING_MIN}"):
            cur.execute(sql)
        cur.close()
    return setup


def _version(v: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def _q(name: str) -> str:
    """A table or index of the store, schema-qualified (names are ours: lower case, no quoting needed)."""
    return f"{schema()}.{name}"


def capabilities(con: Connection) -> dict[str, Any]:
    exts = dict(con.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname IN "
                                 "('vector', 'pg_trgm', 'pg_textsearch')")).all())
    server = int(con.execute(text("SHOW server_version_num")).scalar() or 0)
    # shared_preload_libraries is shown to superusers and pg_read_all_settings only: SHOW fails for the others
    # (Superset's database user, as a rule), pg_settings leaves it out. None: not known.
    row = con.execute(text("SELECT setting FROM pg_settings WHERE name = 'shared_preload_libraries'")).first()
    ts = exts.get("pg_textsearch")
    return {"server": server, "vector": exts.get("vector"), "pg_trgm": exts.get("pg_trgm"), "pg_textsearch": ts,
            "pg_textsearch_preloaded": None if row is None else "pg_textsearch" in str(row[0] or ""),
            "pg_textsearch_safe": bool(ts) and _version(ts) >= SAFE_TEXTSEARCH}


def _bm25_wanted(caps: dict[str, Any]) -> bool:
    how = settings.get("search.bm25") or "auto"
    return bool(caps.get("pg_textsearch")) and how != "builtin"


# --------------------------------------------------------------------------------------------- #
# state
# --------------------------------------------------------------------------------------------- #
def _read_state(con: Connection) -> dict[str, Any] | None:
    exists = con.execute(text("SELECT to_regclass(:t)"), {"t": _q("state")}).scalar()
    if not exists:
        return None
    row = con.execute(text(f"SELECT version, dims, model, bm25, built_at, synced_at, info FROM {_q('state')} "
                           "WHERE id = 1")).mappings().first()
    return dict(row) if row else None


def state(fresh: bool = False) -> dict[str, Any] | None:
    """The version in use (cached STATE_SECONDS per process); None: no store."""
    e = engine()
    if e is None:
        return None
    key = str(e.url) + schema()
    now = time.time()
    if not fresh and _STATE["key"] == key and now - _STATE["at"] < STATE_SECONDS:
        return _STATE["value"]
    try:
        with e.connect() as con:
            value = _read_state(con)
    except Exception as ex:  # pylint: disable=broad-except
        log.warning("supagent store: %s", str(ex)[:300])
        value = None
    _STATE.update(at=now, value=value, key=key)
    return value


def forget_state() -> None:
    _STATE.update(at=0.0, value=None, key=None)


_SAID: dict[str, float] = {}


def active() -> bool:
    """Search through the store (search.store: auto = when it was built; on = the same, and an error in the logs,
    every 10 minutes, while it cannot be used)."""
    how = settings.get("search.store") or "auto"
    if how == "off":
        return False
    st = state()
    ok = bool(st and st.get("version"))
    if not ok and how == "on" and time.time() - _SAID.get("on", 0.0) > 600:
        _SAID["on"] = time.time()
        log.error("supagent store: search.store is on but the store cannot be used (superset supagent store status); "
                  "the search of 0.5 answers meanwhile")
    return ok


# --------------------------------------------------------------------------------------------- #
# the rows
# --------------------------------------------------------------------------------------------- #
def _vec_text(v: Any) -> str | None:
    if v is None:
        return None
    return "[" + ",".join(f"{float(x):.5g}" for x in v) + "]"


def _chunk_rows(model: str | None) -> Iterator[dict[str, Any]]:
    """The searchable pieces (supagent_chunk) with their vectors when they are of the model in use."""
    from supagent.knowledge.embeddings import from_bytes
    from supagent.models import Chunk

    try:
        from supagent.knowledge.facets import facets_of

        refs = [r for (r,) in db.session.query(Chunk.ref)]
        cats = facets_of(refs)
    except Exception:  # pylint: disable=broad-except   (not classified yet: the pieces alone)
        db.session.rollback()
        cats = {}
    for c in db.session.query(Chunk).yield_per(500):
        vec = from_bytes(c.vector) if (model and c.vector is not None and c.embed_model == model) else None
        mine = cats.get(c.ref) or []
        extra = " ".join(x.split(": ", 1)[1] for x in mine)
        yield {"ref": c.ref, "kind": c.kind or "", "source_id": c.source_id, "database_id": c.database_id,
               "scope": c.scope or "team", "user_id": c.user_id, "title": c.title or "", "body": c.text or "",
               "terms": terms_text(c.title or "", c.text or "", extra), "meta": {"facets": mine} if mine else None,
               "hash": (c.content_hash or "") + (_digest(mine)[:8] if mine else ""),
               "embedding": vec, "embed_model": model if vec is not None else None}


def _tables_of_steps(steps: Any) -> list[str]:
    """data:<database>:<table> the queries of an answer read (its steps)."""
    from supagent.knowledge.experience import promql_pattern, sql_pattern

    out = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        args = s.get("arguments") or s.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        dbid = args.get("database_id") if isinstance(args, dict) else None
        query = (args.get("sql") or args.get("query") or "") if isinstance(args, dict) else ""
        if not dbid or not query:
            continue
        try:
            names = promql_pattern(query)[1] if s.get("tool") == "promql_query" else sql_pattern(query)[1]
        except Exception:  # pylint: disable=broad-except
            names = []
        out += [f"data:{int(dbid)}:{n}" for n in names]
    return list(dict.fromkeys(out))


def _chat_window() -> dt.datetime:
    return dt.datetime.utcnow() - dt.timedelta(days=max(1, int(settings.get("search.chat_days") or 365)))


def _chat_ids() -> dict[int, dt.datetime]:
    """The answers the store keeps (done, of the last search.chat_days days): {message id: its last change}."""
    from sqlalchemy import func

    from supagent.models import Message

    if not settings.get("search.chats"):
        return {}
    return {i: u for i, u in db.session.query(Message.id, func.coalesce(Message.updated_at, Message.created_at))
            .filter(Message.role == "assistant", Message.status == "done", Message.created_at >= _chat_window())}


def _chat_rows(only: set[int] | None = None) -> Iterator[dict[str, Any]]:
    """Each answer (`only`: of these ids) with its question: found by its owner only."""
    from supagent.models import Conversation, Message, Route

    if not settings.get("search.chats") or (only is not None and not only):
        return
    since = _chat_window()
    convs: set[int] | None = None
    if only is not None:
        ids = sorted(only)
        convs = set()
        for i in range(0, len(ids), 1000):
            convs |= {c for (c,) in db.session.query(Message.conversation_id).filter(Message.id.in_(ids[i:i + 1000]))}
    owners = dict(db.session.query(Conversation.id, Conversation.user_id))
    routes = {r.message_id: r for r in db.session.query(Route).filter(Route.message_id.isnot(None),
                                                                      Route.created_at >= since)}
    question: dict[int, str] = {}
    rows = db.session.query(Message).filter(Message.created_at >= since)
    batches = [sorted(convs)[i:i + 500] for i in range(0, len(convs), 500)] if convs is not None else [None]
    for batch in batches:
        q = rows if batch is None else rows.filter(Message.conversation_id.in_(batch))
        for m in q.order_by(Message.conversation_id, Message.id).yield_per(500):
            if m.role == "user":
                question[m.conversation_id] = m.content or ""
                continue
            asked = question.get(m.conversation_id)
            if (m.role != "assistant" or m.status != "done" or not asked or not (m.content or "").strip()
                    or (only is not None and m.id not in only)):
                continue
            r = routes.get(m.id)
            tables = list((r.used or r.chosen or []) if r is not None else []) or _tables_of_steps(m.steps)
            answer = (m.content or "")[:CHAT_ANSWER_CHARS]
            meta = {"conversation_id": m.conversation_id, "message_id": m.id,
                    "at": (m.created_at or dt.datetime.utcnow()).isoformat(timespec="minutes"),
                    "feedback": m.feedback, "tables": [t for t in tables if str(t).startswith("data:")]}
            body = f"Q: {asked}\nA: {answer}"
            yield {"ref": f"chat:{m.id}", "kind": "chat", "source_id": None, "database_id": None, "scope": "user",
                   "user_id": owners.get(m.conversation_id), "title": asked[:300], "body": body,
                   "terms": terms_text(asked, answer), "hash": _digest(meta, body, owners.get(m.conversation_id)),
                   "meta": meta, "embedding": None, "embed_model": None}


def _route_rows() -> Iterator[dict[str, Any]]:
    """The routes people confirmed (Helpful, an admin's confirmation, the reply to a question back): which
    tables answered which question, for every user (the decider's votes; the text is never shown)."""
    from supagent.governed.gate import CONFIRMED
    from supagent.models import Route

    for r in db.session.query(Route).filter(Route.signal.in_(CONFIRMED)).order_by(Route.id.desc()).limit(20000):
        subjects = [s for s in (r.used or r.chosen or []) if str(s).startswith("data:")]
        moa = r.moa if (r.moa and r.moa_followed) else None           # a route the execution kept to
        if not (subjects or moa) or not (r.question or "").strip():
            continue
        meta = {"tables": subjects, "signal": r.signal, "moa": moa, "moa_admin": bool(moa and r.moa_by == "admin"),
                "at": (r.signal_at or r.created_at or dt.datetime.utcnow()).isoformat(timespec="minutes")}
        yield {"ref": f"route:{r.id}", "kind": "route", "source_id": None, "database_id": None, "scope": "team",
               "user_id": r.user_id, "title": (r.question or "")[:300], "body": r.question or "",
               "terms": terms_text(r.question or "", ""), "hash": _digest(meta, r.question or "", r.user_id),
               "meta": meta, "embedding": None, "embed_model": None}


def _digest(*parts: Any) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()[:40]


def _name_rows() -> Iterator[dict[str, Any]]:
    """The names of the data for near spellings: metrics, indices, their labels and fields, the values seen,
    synonyms, glossary terms, charts and dashboards, databases."""
    from superset.models.core import Database

    from supagent.models import Entry, KObject, Source

    src_db = dict(db.session.query(Source.id, Source.database_id))
    tops = {(o.source_id, o.name, o.kind): o.id for o in db.session.query(KObject).filter(
        KObject.kind.in_(("metric", "index")), KObject.gone_at.is_(None))}
    for o in db.session.query(KObject).filter(KObject.gone_at.is_(None)).yield_per(2000):
        dbid = src_db.get(o.source_id)
        if o.kind in ("metric", "index"):
            ref = f"object:{o.id}"
            yield _name(o.name, "object", ref, o.source_id, dbid, o.name, None)
            for syn in o.synonyms or []:
                yield _name(str(syn), "synonym", ref, o.source_id, dbid, o.name, None)
            continue
        parent_id = tops.get((o.source_id, o.parent, "metric" if o.kind == "label" else "index"))
        if parent_id is None:
            continue
        ref = f"object:{parent_id}"
        yield _name(o.name, o.kind, ref, o.source_id, dbid, o.parent, o.name)
        for v in ((o.stats or {}).get("values") or [])[:200]:
            if isinstance(v, (str, int)) and len(str(v)) >= 3:
                yield _name(str(v), "value", ref, o.source_id, dbid, o.parent, o.name)
    try:
        from supagent.knowledge.glossary import entry_terms

        for e in db.session.query(Entry).filter(Entry.deleted_at.is_(None), Entry.enabled.is_(True),
                                                Entry.classification == "glossary"):
            for ref, term, _definition in entry_terms(e):
                yield _name(term, "term", ref, None, None, None, None)
    except Exception:  # pylint: disable=broad-except
        db.session.rollback()
        log.warning("supagent store: glossary names", exc_info=True)
    for dbid, name in db.session.query(Database.id, Database.database_name):
        yield _name(name, "database", None, None, dbid, None, None)


def _name(name: str, what: str, ref: str | None, source_id: int | None, database_id: int | None,
          parent: str | None, field: str | None) -> dict[str, Any]:
    return {"name": name[:300], "norm": _split_names(name)[:300], "what": what, "doc_ref": ref,
            "source_id": source_id, "database_id": database_id, "parent": parent, "field": field}


# --------------------------------------------------------------------------------------------- #
# building
# --------------------------------------------------------------------------------------------- #
DOC_COLUMNS = ("ref", "kind", "source_id", "database_id", "scope", "user_id", "title", "body", "terms", "meta",
               "hash", "embedding", "embed_model")
NAME_COLUMNS = ("name", "norm", "what", "doc_ref", "source_id", "database_id", "parent", "field")


def _create_tables(con: Connection, v: int, dims: int | None) -> None:
    emb = f"halfvec({dims})" if dims else "text"                 # no vector extension or model: a placeholder
    con.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema()}"))
    con.execute(text(f"CREATE TABLE IF NOT EXISTS {_q('state')} (id int PRIMARY KEY, version int NOT NULL, "
                     "dims int, model text, bm25 text, built_at timestamptz, synced_at timestamptz, info jsonb)"))
    con.execute(text(f"DROP TABLE IF EXISTS {_q(f'doc_{v}')}, {_q(f'name_{v}')}, {_q(f'word_{v}')}, "
                     f"{_q(f'surf_{v}')}"))
    con.execute(text(f"CREATE TABLE {_q(f'doc_{v}')} (id bigserial PRIMARY KEY, ref text NOT NULL UNIQUE, "
                     "kind text NOT NULL, source_id int, database_id int, scope text NOT NULL DEFAULT 'team', "
                     "user_id int, title text NOT NULL DEFAULT '', body text NOT NULL DEFAULT '', "
                     "terms text NOT NULL DEFAULT '', meta jsonb, hash text, "
                     f"embedding {emb}, embed_model text, updated_at timestamptz NOT NULL DEFAULT now())"))
    con.execute(text(f"CREATE TABLE {_q(f'name_{v}')} (id bigserial PRIMARY KEY, name text NOT NULL, "
                     "norm text NOT NULL, what text NOT NULL, doc_ref text, source_id int, database_id int, "
                     "parent text, field text)"))
    con.execute(text(f"CREATE TABLE {_q(f'word_{v}')} (word text PRIMARY KEY, ndoc int NOT NULL)"))
    con.execute(text(SURF_TABLE.format(t=_q(f"surf_{v}"))))


SURF_TABLE = "CREATE TABLE {t} (word text PRIMARY KEY, stem text NOT NULL, ndoc int NOT NULL)"


def _fill_surface(con: Connection, v: int, counts: Counter, add: bool = False) -> int:
    """The words of the pieces as written, with their stems and how many pieces hold each (`add`: added to the counts,
    a sync: they only grow until the next build, as the store's list of words)."""
    from supagent.knowledge.describe import stem

    t = _q(f"surf_{v}")
    rows = [{"word": w, "stem": stem(w), "ndoc": n} for w, n in counts.items()]
    for i in range(0, len(rows), 1000):
        part = rows[i:i + 1000]
        con.execute(text(f"INSERT INTO {t} (word, stem, ndoc) SELECT * FROM unnest(CAST(:w AS text[]), "
                         "CAST(:s AS text[]), CAST(:n AS int[])) ON CONFLICT (word) DO UPDATE SET ndoc = "
                         + (f"{t}.ndoc + EXCLUDED.ndoc" if add else "EXCLUDED.ndoc")),
                    {"w": [r["word"] for r in part], "s": [r["stem"] for r in part], "n": [r["ndoc"] for r in part]})
    return len(rows)


def idents(text_: str) -> list[str]:
    """The names a text writes (snake_case, kebab-case, dotted.keys, camelCase): two parts at least, one of them a word
    of three letters or more, 6 to 120 characters; IDENTS_PER_PIECE at most."""
    out = []
    for m in IDENT_IN_TEXT.finditer(text_ or ""):
        name = m.group(0).strip("._-")
        parts = [x for x in re.split(r"[_.\-]|(?<=[a-z0-9])(?=[A-Z])", name) if x]
        if 6 <= len(name) <= 120 and len(parts) >= 2 and any(len(x) >= 3 and x.isalpha() for x in parts):
            out.append(name)
    return list(dict.fromkeys(out))[:IDENTS_PER_PIECE]


def _ident_rows(r: dict[str, Any]) -> list[dict[str, Any]]:
    if not IDENTS_PER_PIECE or r.get("kind") in ("chat", "route"):
        return []
    return [_name(x, "ident", r["ref"], r.get("source_id"), r.get("database_id"), None, None)
            for x in idents(f"{r.get('title') or ''}\n{r.get('body') or ''}")]


def _surface_of(rows: Iterable[dict[str, Any]], counts: Counter, con: Connection | None = None,
                names: str | None = None) -> Iterator[dict[str, Any]]:
    """The rows as they go by: the words of each piece (not the chats, not the routes) counted once per piece; with
    `con` and the table of `names`, the names each piece writes added to it (in batches, between the pieces')."""
    batch: list[dict[str, Any]] = []
    for r in rows:
        if r.get("kind") not in ("chat", "route"):
            counts.update(surface(f"{r.get('title') or ''} {r.get('body') or ''}"))
            if con is not None and names:
                batch += _ident_rows(r)
                if len(batch) >= 2000:
                    _insert(con, names, NAME_COLUMNS, batch)
                    batch = []
        yield r
    if batch and con is not None and names:
        _insert(con, names, NAME_COLUMNS, batch)


def _insert(con: Connection, table: str, columns: tuple[str, ...], rows: Iterable[dict[str, Any]],
            vector_cast: str | None = None) -> int:
    """Rows in batches of INSERT_ROWS (one statement each: autocommit)."""
    n, batch = 0, []

    def flush() -> None:
        if not batch:
            return
        values, params = [], {}
        for i, r in enumerate(batch):
            cells = []
            for c in columns:
                key = f"{c}_{i}"
                v = r.get(c)
                if c == "embedding":
                    params[key] = _vec_text(v)
                    cells.append(f"CAST(:{key} AS {vector_cast})" if vector_cast else f":{key}")
                elif c == "meta":
                    params[key] = json.dumps(v) if v is not None else None
                    cells.append(f"CAST(:{key} AS jsonb)")
                else:
                    params[key] = v
                    cells.append(f":{key}")
            values.append("(" + ", ".join(cells) + ")")
        con.execute(text(f"INSERT INTO {table} ({', '.join(columns)}) VALUES " + ", ".join(values)), params)
        batch.clear()

    for r in rows:
        batch.append(r)
        n += 1
        if len(batch) >= INSERT_ROWS:
            flush()
    flush()
    return n


WORDS_OF = ("SELECT w, count(*) FROM (SELECT unnest(tsvector_to_array(to_tsvector('simple', terms))) AS w FROM {doc} "
            "WHERE kind NOT IN ('chat', 'route'){more}) x WHERE w ~ '^[a-z]{{2,40}}$' GROUP BY w")


def _fill_words(con: Connection, v: int, refs: list[str] | None = None) -> int:
    """The store's words (its pieces' words, as indexed: stems) and how many pieces hold each, for reading a search's
    words as the knowledge spells them (spelling.py); `refs`: the words of these pieces added to the counts (a sync:
    the counts only grow until the next build, and a word no piece holds any more is never offered: the live index
    is asked)."""
    words_t, doc = _q(f"word_{v}"), _q(f"doc_{v}")
    if refs is None:
        con.execute(text(f"TRUNCATE {words_t}"))
        return con.execute(text(f"INSERT INTO {words_t} (word, ndoc) " + WORDS_OF.format(doc=doc, more=""))).rowcount
    n = 0
    for i in range(0, len(refs), 1000):
        n += con.execute(text(f"INSERT INTO {words_t} (word, ndoc) " + WORDS_OF.format(doc=doc, more=" AND ref = ANY(:refs)")
                              + f" ON CONFLICT (word) DO UPDATE SET ndoc = {words_t}.ndoc + EXCLUDED.ndoc"),
                         {"refs": refs[i:i + 1000]}).rowcount
    return n


def _create_indexes(con: Connection, v: int, caps: dict[str, Any], dims: int | None) -> str:
    doc, name = _q(f"doc_{v}"), _q(f"name_{v}")
    for sql in (f"CREATE INDEX doc_{v}_kind ON {doc} (kind)", f"CREATE INDEX doc_{v}_db ON {doc} (database_id)",
                f"CREATE INDEX doc_{v}_user ON {doc} (user_id)",
                f"CREATE INDEX doc_{v}_fts ON {doc} USING gin (to_tsvector('simple', terms))",
                f"CREATE INDEX name_{v}_ref ON {name} (doc_ref)"):
        con.execute(text(sql))
    if caps.get("pg_trgm"):
        con.execute(text(f"CREATE INDEX name_{v}_trgm ON {name} USING gin (norm gin_trgm_ops)"))
        con.execute(text(f"CREATE INDEX surf_{v}_trgm ON {_q(f'surf_{v}')} USING gist (word gist_trgm_ops)"))
    if caps.get("vector") and dims:
        con.execute(text(f"CREATE INDEX doc_{v}_hnsw ON {doc} USING hnsw (embedding halfvec_cosine_ops)"))
    bm25 = "builtin"
    if _bm25_wanted(caps):
        try:
            con.execute(text(f"CREATE INDEX doc_{v}_bm25 ON {doc} USING bm25 (terms) WITH (text_config = 'simple')"))
            bm25 = "pg_textsearch " + str(caps["pg_textsearch"])
        except Exception as ex:  # pylint: disable=broad-except   (the built-in full-text search stays)
            log.warning("supagent store: no BM25 index: %s", str(ex)[:300])
    con.execute(text(f"ANALYZE {doc}"))
    con.execute(text(f"ANALYZE {name}"))
    con.execute(text(f"ANALYZE {_q(f'surf_{v}')}"))
    return bm25


def _dims(model: str | None) -> int | None:
    """The dimension of the model's vectors: from a stored vector, else one asked of the model."""
    from supagent.models import Chunk

    if not model:
        return None
    row = db.session.query(Chunk.vector).filter(Chunk.embed_model == model, Chunk.vector.isnot(None)).first()
    if row is not None and row[0]:
        return len(row[0]) // 2                             # float16
    from supagent.knowledge import embeddings as E

    try:
        return int(E.embed(["dimension"])[0].shape[0])
    except Exception as ex:  # pylint: disable=broad-except
        log.warning("supagent store: no vectors (%s)", str(ex)[:200])
        return None


def rebuild(embed: bool = True) -> dict[str, Any]:
    """A new version of the store from Superset's database, then used; the older ones dropped."""
    from supagent.knowledge import embeddings as E

    e = engine()
    if e is None:
        raise StoreError("the store needs PostgreSQL: Superset's database is not, and search.store_uri is empty")
    t0 = time.time()
    model = E.model() or None
    from supagent.knowledge.freshness import stamp

    names_stamp = stamp()
    with e.connect() as con:
        if not _lock(con):
            return {"skipped": "another process is writing the store"}
        con.execute(text("SET statement_timeout = 0"))
        caps = capabilities(con)
        dims = _dims(model) if caps.get("vector") else None
        if dims and dims > 4000:
            log.warning("supagent store: vectors of %s dimensions: over halfvec's 4000, no meaning search", dims)
            dims = None
        st = _read_state(con) if con.execute(text("SELECT to_regnamespace(:s)"), {"s": schema()}).scalar() else None
        v = int((st or {}).get("version") or 0) + 1
        _create_tables(con, v, dims)
        cast = f"halfvec({dims})" if dims else None
        seen: Counter = Counter()
        docs = _insert(con, _q(f"doc_{v}"), DOC_COLUMNS, _surface_of(
            (r for rows in (_chunk_rows(model if dims else None), _chat_rows(), _route_rows()) for r in rows), seen,
            con, _q(f"name_{v}")), cast)
        n_idents = con.execute(text(f"SELECT count(*) FROM {_q(f'name_{v}')}")).scalar()
        names = _insert(con, _q(f"name_{v}"), NAME_COLUMNS, _name_rows()) + int(n_idents or 0)
        n_words = _fill_words(con, v)
        n_surface = _fill_surface(con, v, seen)
        bm25 = _create_indexes(con, v, caps, dims)
        info = {"docs": docs, "names": names, "words": n_words, "surface": n_surface,
                "seconds": round(time.time() - t0, 1), "caps": caps, "names_stamp": names_stamp}
        con.execute(text(f"INSERT INTO {_q('state')} (id, version, dims, model, bm25, built_at, synced_at, info) "
                         "VALUES (1, :v, :d, :m, :b, now(), now(), CAST(:i AS jsonb)) ON CONFLICT (id) DO UPDATE SET "
                         "version = :v, dims = :d, model = :m, bm25 = :b, built_at = now(), synced_at = now(), "
                         "info = CAST(:i AS jsonb)"),
                    {"v": v, "d": dims, "m": model if dims else None, "b": bm25, "i": json.dumps(info, default=str)})
        _drop_old(con, keep=v)
    forget_state()
    out = {"version": v, **{k: x for k, x in info.items() if k != "names_stamp"}, "bm25": bm25, "dims": dims}
    if embed and dims:
        out["embedded"] = embed_pending()
    return out


def _drop_old(con: Connection, keep: int) -> None:
    """The versions not in use (a search still reading one: dropped at the next sync)."""
    rows = con.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = :s AND tablename ~ '^(doc|name|word|surf)_[0-9]+$'"),
                       {"s": schema()}).scalars().all()
    for t in rows:
        if int(t.split("_")[1]) == keep:
            continue
        try:
            con.execute(text("SET lock_timeout = '2s'"))
            con.execute(text(f"DROP TABLE IF EXISTS {_q(t)}"))
        except Exception as ex:  # pylint: disable=broad-except
            log.info("supagent store: %s kept for now: %s", t, str(ex)[:120])
        finally:
            con.execute(text("SET lock_timeout = 0"))


def wipe() -> bool:
    """The store dropped (the search of 0.5 answers until the next rebuild)."""
    e = engine()
    if e is None:
        return False
    with e.connect() as con:
        con.execute(text(f"DROP SCHEMA IF EXISTS {schema()} CASCADE"))
    forget_state()
    return True


# --------------------------------------------------------------------------------------------- #
# keeping it in step
# --------------------------------------------------------------------------------------------- #
def _lock(con: Connection) -> bool:
    """One process at a time writes the store (released when the connection closes)."""
    key = int.from_bytes(__import__("hashlib").sha256(f"supagent store {schema()}".encode()).digest()[:8], "big",
                         signed=True)
    return bool(con.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key}).scalar())


def sync(prefixes: tuple[str, ...] | None = None, chats: bool = True, names: bool = False) -> dict[str, Any]:
    """The pieces (`prefixes`: of these kinds of refs only), chats and routes (`chats`) that changed since the
    store was written (their text, their vector), the ones gone removed; `names`: the names and values of the
    data made again when the dictionary changed. Another embedding model, an extension added, removed or of
    another version (pg_textsearch 0.5 -> 1.x): the store is built again."""
    from supagent.knowledge import embeddings as E
    from supagent.knowledge.freshness import stamp

    st = state(fresh=True)
    e = engine()
    if not st or e is None:
        return {"skipped": "no store"}
    model = E.model() or None
    if st.get("dims") and model != (st.get("model") or None):
        return {"rebuilt": rebuild()}                     # another embedding model: every vector again
    info = st.get("info") if isinstance(st.get("info"), dict) else json.loads(st.get("info") or "{}")
    with e.connect() as con:
        caps = capabilities(con)
    built = info.get("caps") or {}
    if any((caps.get(x) or None) != (built.get(x) or None) for x in EXTENSIONS):
        return {"rebuilt": rebuild()}                     # an extension added, removed or upgraded (index formats)
    v, dims = int(st["version"]), st.get("dims")
    cast = f"halfvec({dims})" if dims else None
    doc = _q(f"doc_{v}")
    out = {"added": 0, "changed": 0, "removed": 0}

    def in_scope(ref: str) -> bool:
        if ref.startswith(("chat:", "route:")):
            return chats
        return prefixes is None or ref.startswith(prefixes)

    with e.connect() as con:
        if not _lock(con):
            return {"skipped": "another process is writing the store"}
        con.execute(text("SET statement_timeout = 0"))
        have = {r.ref: r for r in con.execute(text(f"SELECT ref, hash, (embedding IS NOT NULL) AS has_v FROM {doc}"))
                .all() if in_scope(r.ref)}
        todo: list[dict[str, Any]] = []
        keep: set[str] = set()

        def compare(r: dict[str, Any], with_vector: bool) -> None:
            keep.add(r["ref"])
            old = have.get(r["ref"])
            same = old is not None and old.hash == r["hash"] and (
                not with_vector or bool(old.has_v) == (r["embedding"] is not None))
            if not same:
                todo.append(r)
                out["changed" if old is not None else "added"] += 1

        for r in _chunk_rows(model if dims else None):
            if prefixes is None or r["ref"].startswith(prefixes):
                compare(r, True)
        if chats:
            for r in _route_rows():                      # their vector comes later (embed_pending)
                compare(r, False)
            ids = _chat_ids()
            last = st.get("synced_at")
            since = (last.astimezone(dt.timezone.utc).replace(tzinfo=None) - dt.timedelta(minutes=10)
                     if isinstance(last, dt.datetime) else None)
            keep |= {f"chat:{i}" for i in ids}
            changed = {i for i, at in ids.items() if f"chat:{i}" not in have or since is None or (at and at >= since)}
            for r in _chat_rows(only=changed):
                compare(r, False)
        gone = [ref for ref in have if ref not in keep]
        name_t = _q(f"name_{v}")
        for i in range(0, len(gone), 500):
            con.execute(text(f"DELETE FROM {doc} WHERE ref = ANY(:refs)"), {"refs": gone[i:i + 500]})
            con.execute(text(f"DELETE FROM {name_t} WHERE what = 'ident' AND doc_ref = ANY(:refs)"),
                        {"refs": gone[i:i + 500]})
        out["removed"] = len(gone)
        for i in range(0, len(todo), INSERT_ROWS):
            part = todo[i:i + INSERT_ROWS]
            con.execute(text(f"DELETE FROM {doc} WHERE ref = ANY(:refs)"), {"refs": [r["ref"] for r in part]})
            _insert(con, doc, DOC_COLUMNS, part, cast)
            con.execute(text(f"DELETE FROM {name_t} WHERE what = 'ident' AND doc_ref = ANY(:refs)"),
                        {"refs": [r["ref"] for r in part]})
            _insert(con, name_t, NAME_COLUMNS, [x for r in part for x in _ident_rows(r)])
        if not con.execute(text("SELECT to_regclass(:t)"), {"t": f"{schema()}.word_{v}"}).scalar():
            con.execute(text(f"CREATE TABLE {_q(f'word_{v}')} (word text PRIMARY KEY, ndoc int NOT NULL)"))
            out["words"] = _fill_words(con, v)          # a store built before 0.9.6: its words now
        elif todo:
            _fill_words(con, v, [r["ref"] for r in todo if r["kind"] not in ("chat", "route")])
        if not con.execute(text("SELECT to_regclass(:t)"), {"t": f"{schema()}.surf_{v}"}).scalar():
            out["surface"] = _surface_now(con, v, built)  # a store built before 0.10: its words as written now
        elif todo:
            got: Counter = Counter()
            for _r in _surface_of(todo, got):
                pass
            _fill_surface(con, v, got, add=True)
        now_stamp = stamp()
        if names and info.get("names_stamp") != now_stamp:
            name = _q(f"name_{v}")
            con.execute(text(f"DELETE FROM {name} WHERE what <> 'ident'"))
            out["names"] = _insert(con, name, NAME_COLUMNS, _name_rows())
            con.execute(text(f"UPDATE {_q('state')} SET info = jsonb_set(coalesce(info, '{{}}'::jsonb), "
                             "'{names_stamp}', to_jsonb(CAST(:s AS text))) WHERE id = 1"), {"s": now_stamp})
        con.execute(text(f"UPDATE {_q('state')} SET synced_at = now() WHERE id = 1"))
    if dims and chats:
        out["embedded"] = embed_pending()
    forget_state()
    return out


def _surface_now(con: Connection, v: int, caps: dict[str, Any]) -> int:
    """The table of the words as written for a store built before it existed, from the pieces it holds."""
    con.execute(text(SURF_TABLE.format(t=_q(f"surf_{v}"))))
    got: Counter = Counter()
    last = 0
    while True:                                    # by pages of pieces (autocommit: no cursor kept open)
        rows = con.execute(text(f"SELECT id, title, body FROM {_q(f'doc_{v}')} WHERE kind NOT IN ('chat', 'route') "
                                "AND id > :last ORDER BY id LIMIT 500"), {"last": last}).all()
        if not rows:
            break
        for row in rows:
            got.update(surface(f"{row.title or ''} {row.body or ''}"))
        last = rows[-1].id
    n = _fill_surface(con, v, got)
    if caps.get("pg_trgm"):
        con.execute(text(f"CREATE INDEX surf_{v}_trgm ON {_q(f'surf_{v}')} USING gist (word gist_trgm_ops)"))
    con.execute(text(f"ANALYZE {_q(f'surf_{v}')}"))
    return n


def near_words(typed: list[str], n: int = NEAR_CANDIDATES) -> dict[str, list[tuple[str, str, int, float]]]:
    """For each word (lower case, letters only), the words of the pieces nearest to it by their trigrams (pg_trgm's
    distance, through the GiST index), with the same first letter and a length within two: {typed: [(word, stem,
    pieces holding it, similarity)]}; {} without the store, its table of words or pg_trgm. Which of them a word is
    read as (two slips at most, held by a piece the user may see) is spelling.py's choice."""
    st = state()
    e = engine()
    lo, hi = SURFACE_LETTERS
    typed = [w for w in dict.fromkeys(typed) if isinstance(w, str) and w.isalpha() and lo <= len(w) <= hi]
    if not st or e is None or not typed:
        return {}
    info = st.get("info") if isinstance(st.get("info"), dict) else json.loads(st.get("info") or "{}")
    if not (info.get("caps") or {}).get("pg_trgm"):
        return {}
    v = int(st["version"])
    with e.connect() as con:
        if not con.execute(text("SELECT to_regclass(:t)"), {"t": f"{schema()}.surf_{v}"}).scalar():
            return {}
        rows = con.execute(text(
            f"SELECT t.w, s.word, s.stem, s.ndoc, similarity(s.word, t.w) AS sim FROM unnest(CAST(:ws AS text[])) "
            f"AS t(w) CROSS JOIN LATERAL (SELECT x.word, x.stem, x.ndoc FROM {_q(f'surf_{v}')} x "
            f"WHERE left(x.word, 1) = left(t.w, 1) AND length(x.word) BETWEEN length(t.w) - 2 AND length(t.w) + 2 "
            f"ORDER BY x.word <-> t.w LIMIT :n) s"), {"ws": typed, "n": int(n)}).all()
    out: dict[str, list[tuple[str, str, int, float]]] = {}
    for r in rows:
        out.setdefault(r.w, []).append((r.word, r.stem, int(r.ndoc), float(r.sim)))
    return out


def rename_kind(old: str, new: str, ref_prefix: str) -> int:
    """The pieces of a kind renamed by an upgrade (0.8: the catalog's notes are guides): their kind in the store
    (sync compares contents, not kinds). 0 without a store."""
    st = state(fresh=True)
    e = engine()
    if not st or e is None:
        return 0
    doc = _q(f"doc_{int(st['version'])}")
    with e.connect() as con:
        n = con.execute(text(f"UPDATE {doc} SET kind = :new WHERE kind = :old AND ref LIKE :prefix"),
                        {"new": new, "old": old, "prefix": ref_prefix.replace("%", "") + "%"}).rowcount
    forget_state()
    return int(n or 0)


def maintain() -> dict[str, Any]:
    """Hourly: everything in step (pieces, chats, routes, names), the vectors of the new chats; built again
    when a third of it changed (pg_textsearch before 0.6.1 keeps the words of deleted rows until then)."""
    if (settings.get("search.store") or "auto") == "off" or not state(fresh=True):
        return {"skipped": "no store"}
    out = sync(names=True)
    st = state(fresh=True) or {}
    info = st.get("info") if isinstance(st.get("info"), dict) else json.loads(st.get("info") or "{}")
    churn = int(info.get("churn") or 0) + out.get("added", 0) + out.get("changed", 0) + out.get("removed", 0)
    if churn > max(500, int(info.get("docs") or 0) // 3):
        return {"sync": out, "rebuilt": rebuild()}
    e = engine()
    if e is not None and st:
        with e.connect() as con:
            con.execute(text(f"UPDATE {_q('state')} SET info = jsonb_set(coalesce(info, '{{}}'::jsonb), '{{churn}}', "
                             "to_jsonb(CAST(:c AS int))) WHERE id = 1"), {"c": churn})
    return {"sync": out}


def embed_pending(limit: int = 2000) -> dict[str, Any]:
    """Vectors for the chats and routes (their question) that have none: the pieces' vectors come from
    supagent_chunk (index.embed_pending), never twice."""
    from supagent.knowledge import embeddings as E

    st = state(fresh=True)
    e = engine()
    if not st or e is None or not st.get("dims") or not E.enabled():
        return {"embedded": 0}
    v, dims = int(st["version"]), int(st["dims"])
    doc = _q(f"doc_{v}")
    done = 0
    with e.connect() as con:
        rows = con.execute(text(f"SELECT id, kind, title, body FROM {doc} WHERE embedding IS NULL AND kind IN "
                                f"('chat', 'route') ORDER BY id DESC LIMIT :n"), {"n": limit}).all()
        batch = max(1, int(settings.get("embed.batch") or 16))
        for i in range(0, len(rows), batch):
            part = rows[i:i + batch]
            vectors = E.embed([r.title for r in part])
            for r, vec in zip(part, vectors):
                if vec.shape[0] != dims:
                    raise StoreError(f"the model gives {vec.shape[0]} dimensions, the store holds {dims}: rebuild it")
                con.execute(text(f"UPDATE {doc} SET embedding = CAST(:e AS halfvec({dims})), embed_model = :m "
                                 "WHERE id = :id"), {"e": _vec_text(vec), "m": E.model(), "id": r.id})
            done += len(part)
    return {"embedded": done}


# --------------------------------------------------------------------------------------------- #
# searching
# --------------------------------------------------------------------------------------------- #
def _who() -> dict[str, Any]:
    """What the current user may see: the learned sources, the databases, their own pieces, the Context pages."""
    from flask import g

    from supagent.knowledge.context import visible_pages
    from supagent.knowledge.curated import sources_of_user
    from supagent.security import group_scopes, visible_databases

    return {"uid": getattr(getattr(g, "user", None), "id", None) or -1, "groups": group_scopes() or ["-"],
            "sources": [s.id for s in sources_of_user()] or [-1], "dbs": sorted(visible_databases()) or [-1],
            "pages": [f"context:{p.id}#%" for p in visible_pages()] or ["-"]}


PERMITTED = ("(d.source_id IS NULL OR d.source_id = ANY(:sources)) "
             "AND (d.database_id IS NULL OR d.database_id = ANY(:dbs)) "
             "AND (d.scope = 'team' OR d.user_id = :uid OR d.scope = ANY(:groups)) "
             "AND (d.kind <> 'context' OR d.ref LIKE ANY(:pages))")


def word_counts(stems: list[str]) -> dict[str, int]:
    """How many pieces hold each of these words (stems) by the store's list of words ({}: none of them, or a store
    without its list)."""
    st = state()
    e = engine()
    if not st or e is None or not stems:
        return {}
    v = int(st["version"])
    with e.connect() as con:
        if not con.execute(text("SELECT to_regclass(:t)"), {"t": f"{schema()}.word_{v}"}).scalar():
            return {}
        rows = con.execute(text(f"SELECT word, ndoc FROM {_q(f'word_{v}')} WHERE word = ANY(:w)"),
                           {"w": list(stems)}).all()
    return {r.word: int(r.ndoc) for r in rows}


def holding(stems: list[str]) -> set[str]:
    """The words (stems) some piece the current user may see holds now (the live index: a piece written a minute
    ago counts; the chats and routes do not)."""
    st = state()
    e = engine()
    stems = [w for w in dict.fromkeys(stems) if re.fullmatch(r"[a-z0-9]{1,60}", w or "")]
    if not st or e is None or not stems:
        return set()
    doc = _q(f"doc_{int(st['version'])}")
    with e.connect() as con:
        rows = con.execute(text(
            f"SELECT t.w FROM unnest(CAST(:ws AS text[])) AS t(w) WHERE EXISTS (SELECT 1 FROM {doc} d "
            f"WHERE to_tsvector('simple', d.terms) @@ to_tsquery('simple', t.w) AND d.kind NOT IN ('chat', 'route') "
            f"AND {PERMITTED})"), {**_who(), "ws": stems}).all()
    return {r.w for r in rows}


def side_by_side(pairs: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """The pairs of words (stems) some piece the current user may see holds next to each other."""
    st = state()
    e = engine()
    ok = re.compile(r"[a-z0-9]{1,60}")
    pairs = [(a, b) for a, b in dict.fromkeys(pairs) if ok.fullmatch(a or "") and ok.fullmatch(b or "")]
    if not st or e is None or not pairs:
        return set()
    doc = _q(f"doc_{int(st['version'])}")
    with e.connect() as con:
        rows = con.execute(text(
            f"SELECT t.a, t.b FROM unnest(CAST(:a AS text[]), CAST(:b AS text[])) AS t(a, b) WHERE EXISTS (SELECT 1 "
            f"FROM {doc} d WHERE to_tsvector('simple', d.terms) @@ (to_tsquery('simple', t.a) <-> "
            f"to_tsquery('simple', t.b)) AND d.kind NOT IN ('chat', 'route') AND {PERMITTED})"),
            {**_who(), "a": [a for a, _b in pairs], "b": [b for _a, b in pairs]}).all()
    return {(r.a, r.b) for r in rows}


def _kinds_sql(kinds: tuple[str, ...] | None, skip: tuple[str, ...]) -> tuple[str, dict[str, Any]]:
    sql, params = "", {}
    if kinds:
        sql += " AND d.kind = ANY(:kinds)"
        params["kinds"] = list(kinds)
    if skip:
        sql += " AND NOT (d.kind = ANY(:skip))"
        params["skip"] = list(skip)
    return sql, params


def _by_words(con: Connection, v: int, st: dict[str, Any], query: str, where: str,
              params: dict[str, Any], builtin: bool = False, n: int = CANDIDATES) -> list[tuple[int, float]]:
    """Pieces by their words, best first: BM25 over the whole store, then the user's filter (pg_textsearch 0.5 may
    fill a filtered scan short); when the filter leaves few of the BM25_POOL best, PostgreSQL's full-text search
    (filtered first) adds the others. `builtin`: that one only (the chats of one user)."""
    q = " ".join(dict.fromkeys(words(query)))
    if not q:
        return []
    doc = _q(f"doc_{v}")
    out: list[tuple[int, float]] = []
    if not builtin and str(st.get("bm25") or "").startswith("pg_textsearch"):
        idx = _q(f"doc_{v}_bm25")
        rows = con.execute(text(
            f"WITH top AS (SELECT id, terms <@> to_bm25query(:q, :idx) AS s FROM {doc} "
            f"ORDER BY terms <@> to_bm25query(:q, :idx) LIMIT :pool) "
            f"SELECT d.id, -top.s AS s FROM top JOIN {doc} d ON d.id = top.id WHERE {where} AND top.s < 0 "
            f"ORDER BY top.s LIMIT :n"), {**params, "q": q, "idx": idx, "pool": max(BM25_POOL, n), "n": n}).all()
        out = list(dict.fromkeys((r.id, float(r.s)) for r in rows))       # 0.5.x may give a row twice
        if len(out) >= n // 2:
            return out
    tsq = " | ".join(re.sub(r"[^a-z0-9]", "", w) for w in q.split() if re.sub(r"[^a-z0-9]", "", w))
    if not tsq:
        return out
    rows = con.execute(text(
        f"SELECT d.id, ts_rank_cd(to_tsvector('simple', d.terms), q, 1) AS s FROM {doc} d, "
        f"to_tsquery('simple', :tsq) q WHERE to_tsvector('simple', d.terms) @@ q AND {where} "
        f"ORDER BY s DESC LIMIT :n"), {**params, "tsq": tsq, "n": n}).all()
    seen = {i for i, _s in out}
    return out + [(r.id, float(r.s)) for r in rows if r.id not in seen][:n - len(out)]


def _by_meaning(con: Connection, v: int, st: dict[str, Any], query: str, where: str,
                params: dict[str, Any], n: int = CANDIDATES) -> list[tuple[int, float]]:
    from supagent.knowledge import embeddings as E

    if not st.get("dims") or not E.enabled():
        return []
    qv = query_vector(query)
    if qv.shape[0] != int(st["dims"]):
        log.warning("supagent store: the model gives %s dimensions, the store %s: rebuild it", qv.shape[0], st["dims"])
        return []
    rows = con.execute(text(
        f"SELECT d.id, d.embedding <=> CAST(:qv AS halfvec({int(st['dims'])})) AS dist FROM {_q(f'doc_{v}')} d "
        f"WHERE d.embedding IS NOT NULL AND d.kind NOT IN ('chat', 'route') AND {where} "
        f"ORDER BY dist LIMIT :n"), {**params, "qv": _vec_text(qv), "n": n}).all()
    return sorted(((r.id, 1.0 - float(r.dist)) for r in rows), key=lambda x: -x[1])   # relaxed order: sorted here


def query_text(query: str) -> str:
    """The text embedded for a question (embed.query_instruction before it: Qwen3-Embedding, E5...)."""
    inst = (settings.get("embed.query_instruction") or "").strip()
    return f"{inst}\n{query}" if inst else query


_QVEC: dict[tuple[str, str], Any] = {}


def query_vector(query: str) -> Any:
    """The question's vector, once per question (the search and the neighbours ask for it)."""
    from supagent.knowledge import embeddings as E

    key = (E.model(), query_text(query))
    v = _QVEC.get(key)
    if v is None:
        v = E.embed([key[1]])[0]
        if len(_QVEC) > 64:
            _QVEC.clear()
        _QVEC[key] = v
    return v


def _by_spelling(con: Connection, v: int, query: str, params: dict[str, Any]) -> tuple[list[tuple[int, float]],
                                                                                      dict[int, list[dict]]]:
    """Pieces whose names or values are spelled almost like a word or a name of the question (a typo, a
    variant: a name spelled exactly is found by words): (doc id, word similarity), and what matched."""
    toks = spelling_words(query)
    if not toks:
        return [], {}
    doc, name = _q(f"doc_{v}"), _q(f"name_{v}")
    # the names the documents write are for a name typed (custom_icu_anbalyzer), near the whole name (not a part of
    # it: /api/checkout is not checkout_orders_total); not for the words of a question (aggregation would find each
    # name holding aggregations; a misspelled word is read by spelling.py and found by words)
    # (a name typed exactly as a document writes it counts too: refreshInterval is two common words for BM25, one
    # name of a few pages)
    itoks = [t for t in toks if " " in t]
    perm = ("AND (x.source_id IS NULL OR x.source_id = ANY(:sources)) "
            "AND (x.database_id IS NULL OR x.database_id = ANY(:dbs)) ")
    rows = con.execute(text(
        f"SELECT n.tok, n.name, n.what, n.field, n.s, d.id FROM unnest(CAST(:toks AS text[])) AS t(tok) "
        f"CROSS JOIN LATERAL (SELECT t.tok, x.name, x.what, x.field, x.doc_ref, word_similarity(t.tok, x.norm) AS s "
        f"  FROM {name} x WHERE t.tok <% x.norm AND x.doc_ref IS NOT NULL AND x.what <> 'ident' "
        f"  AND position(' ' || t.tok || ' ' IN ' ' || x.norm || ' ') = 0 {perm}"
        f"  ORDER BY word_similarity(t.tok, x.norm) DESC LIMIT :per) n "
        f"JOIN {doc} d ON d.ref = n.doc_ref "
        f"UNION ALL "
        f"SELECT n.tok, n.name, n.what, n.field, n.s, d.id FROM unnest(CAST(:itoks AS text[])) AS t(tok) "
        f"CROSS JOIN LATERAL (SELECT t.tok, x.name, x.what, x.field, x.doc_ref, similarity(t.tok, x.norm) AS s "
        f"  FROM {name} x WHERE x.norm % t.tok AND x.what = 'ident' AND x.doc_ref IS NOT NULL {perm}"
        f"  ORDER BY similarity(t.tok, x.norm) DESC LIMIT :per_ident) n "
        f"JOIN {doc} d ON d.ref = n.doc_ref"), {**params, "toks": toks, "itoks": itoks, "per": NAMES_PER_WORD,
                                                "per_ident": IDENT_MATCHES}).all()
    best: dict[int, float] = {}
    matched: dict[int, list[dict]] = {}
    for r in rows:
        s = float(r.s)
        if s < SPELLING_MIN:
            continue
        if s > best.get(r.id, 0.0):
            best[r.id] = s
        matched.setdefault(r.id, []).append({"word": r.tok, "name": r.name, "what": r.what, "field": r.field,
                                             "similarity": round(s, 3)})
    return sorted(best.items(), key=lambda x: -x[1])[:CANDIDATES], matched


MEANING_READ = True        # the meaning of the query as read (its misspelled words read otherwise), not as typed:
#                            measured +2 to +4 points on misspelled queries, the same on the others


def search(query: str, k: int, kinds: tuple[str, ...] | None = None, lower: dict[str, int] | None = None,
           skip: tuple[str, ...] = (), n: int | None = None, words_query: str | None = None) -> list[dict[str, Any]]:
    """As search.search: the pieces for a query, best first, each with how it was found ("via": words,
    meaning, spelling) and its rank in each way ("ranks"). `n`: the pieces each way gives (CANDIDATES; more
    to list every piece found, the Data dictionary's search). `words_query`: the query as its words are read
    (spelling.py: a misspelled word read as the knowledge spells it), for the search by words and by meaning; the
    near spellings of names take the query as typed."""
    from supagent.knowledge.search import _superset_allowed

    st = state()
    e = engine()
    if not st or e is None:
        raise StoreError("no store")
    v = int(st["version"])
    lower = lower or {}
    who = _who()
    kind_sql, kind_params = _kinds_sql(kinds, tuple(skip) + ("chat", "route"))
    where = PERMITTED + kind_sql
    params = {**who, **kind_params}
    found: dict[str, list[tuple[int, float]]] = {}
    matched: dict[int, list[dict]] = {}
    info = st.get("info") if isinstance(st.get("info"), dict) else json.loads(st.get("info") or "{}")
    built = info.get("caps") or {}
    n = max(int(n or CANDIDATES), CANDIDATES)
    ways = [("words", lambda: _by_words(con, v, st, words_query or query, where, params, n=n)),
            ("meaning", lambda: _by_meaning(con, v, st, words_query if MEANING_READ and words_query else query, where,
                                            params, n=n))]
    if built.get("pg_trgm") or "caps" not in info:   # near spellings need pg_trgm (built without it: none)
        ways.append(("spelling", lambda: _by_spelling(con, v, query, params)))
    with e.connect() as con:
        for way, run in ways:
            try:
                got = run()
            except Exception as ex:  # pylint: disable=broad-except   (the other ways still count)
                log.warning("supagent store: %s: %s", way, str(ex)[:300])
                continue
            if way == "spelling":
                got, matched = got
            found[way] = got
        meaning = found.get("meaning") or []
        if meaning:                                       # a weak neighbour found by meaning only is noise
            floor = max(VECTOR_FLOOR, meaning[0][1] - VECTOR_MARGIN)
            others = {i for way, got in found.items() if way != "meaning" for i, _s in got}
            found["meaning"] = [(i, s) for i, s in meaning if s >= floor or i in others]
        ids = list(dict.fromkeys(i for got in found.values() for i, _s in got))
        if not ids:
            return []
        rows = {r.id: r for r in con.execute(text(
            f"SELECT d.id, d.ref, d.kind, d.title, d.body FROM {_q(f'doc_{v}')} d WHERE d.id = ANY(:ids) AND {where}"),
            {**params, "ids": ids}).all()}
    scores: dict[int, float] = {}
    ranks: dict[int, dict[str, int]] = {}
    weights = dict(CC_WAYS)
    fusion = FUSION
    if FUSION == "mixed":                                 # a sentence by ranks, keywords and names by scores
        fusion = "rrf" if _sentence(query) else "cc"
    elif FUSION == "cc" and CC_MEANING_SENTENCE is not None and _sentence(query):
        weights["meaning"] = float(CC_MEANING_SENTENCE)
    for way, got in found.items():
        scaled = _scaled(way, got) if fusion == "cc" else {}
        for rank, (i, _s) in enumerate(got):
            r = rows.get(i)
            if r is None:
                continue
            if fusion == "cc":
                scores[i] = scores.get(i, 0.0) + weights.get(way, 0.0) * scaled.get(i, 0.0)
            else:
                scores[i] = scores.get(i, 0.0) + WAYS[way] / (RRF + rank + lower.get(r.kind or "", 0))
            ranks.setdefault(i, {})[way] = rank
    if fusion == "cc":                                    # a kind counted as found places lower
        for i in scores:
            places = lower.get(rows[i].kind or "", 0) if i in rows else 0
            scores[i] -= CC_PLACE * places
    cos = dict(found.get("meaning") or [])
    out = []
    for i, score in sorted(scores.items(), key=lambda x: -x[1]):
        r = rows[i]
        if r.kind in ("chart", "dashboard"):
            from supagent.models import Chunk

            if not _superset_allowed(Chunk(ref=r.ref, kind=r.kind)):
                continue
        via = [w for w in ("words", "meaning", "spelling") if w in ranks[i]]
        out.append({"ref": r.ref, "kind": r.kind, "title": r.title, "text": r.body, "score": round(score, 4),
                    "via": " and ".join(via), "ranks": ranks[i], "cos": round(cos[i], 4) if i in cos else None,
                    "spelled": matched.get(i) or []})
        if len(out) >= k:
            break
    return out


def _sentence(query: str) -> bool:
    """A question written as a sentence (not a list of keywords, not a name): 3 words or more, one a function word."""
    from supagent.knowledge.describe import STOP

    ws = re.findall(r"[^\W\d_]+", (query or "").lower())
    return len(ws) >= 3 and any(w in STOP for w in ws) and not IDENTIFIER.search(query or "")


def _scaled(way: str, got: list[tuple[int, float]]) -> dict[int, float]:
    """A way's scores scaled to 0..1 for the "cc" fusion: by words, as a share of the best one (BM25 has no upper
    bound; 0 is no match); by meaning, from the floor of the closeness (VECTOR_FLOOR: 0) to the closest (1); the near
    spellings' similarity as it is (0..1)."""
    if not got:
        return {}
    if way == "words":
        top = max(s for _i, s in got) or 1.0
        return {i: max(0.0, s) / top for i, s in got}
    if way == "meaning":
        top = max(s for _i, s in got)
        span = max(top - VECTOR_FLOOR, 1e-6)
        return {i: min(1.0, max(0.0, (s - VECTOR_FLOOR) / span)) for i, s in got}
    return {i: min(1.0, max(0.0, s)) for i, s in got}


def neighbors(question: str, user_id: int | None, k: int = 20) -> dict[str, float]:
    """The tables of the confirmed routes of questions like this one (everyone's) and of the user's own
    earlier answers (not the ones marked Not helpful): {data:<database>:<table>: vote in 0..1}, each
    question counting as close as it is (meaning, else words)."""
    st = state()
    e = engine()
    if not st or e is None or not settings.get("search.chats"):
        return {}
    v = int(st["version"])
    doc = _q(f"doc_{v}")
    uid = user_id or -1
    mine = "(d.kind = 'route' OR (d.kind = 'chat' AND d.user_id = :uid AND coalesce((d.meta->>'feedback')::int, 0) >= 0))"
    close: dict[int, float] = {}
    meta: dict[int, Any] = {}
    with e.connect() as con:
        try:
            from supagent.knowledge import embeddings as E

            if st.get("dims") and E.enabled():
                qv = query_vector(question)
                for r in con.execute(text(
                        f"SELECT d.id, d.kind, d.meta, 1 - (d.embedding <=> CAST(:qv AS halfvec({int(st['dims'])}))) AS s "
                        f"FROM {doc} d WHERE d.embedding IS NOT NULL AND {mine} "
                        f"ORDER BY d.embedding <=> CAST(:qv AS halfvec({int(st['dims'])})) LIMIT :n"),
                        {"qv": _vec_text(qv), "uid": uid, "n": k}).all():
                    close[r.id] = float(r.s)
                    meta[r.id] = (r.kind, r.meta)
        except Exception as ex:  # pylint: disable=broad-except
            log.warning("supagent store: neighbours by meaning: %s", str(ex)[:300])
        if not close:
            q = " | ".join(re.sub(r"[^a-z0-9]", "", w) for w in dict.fromkeys(words(question)) if w)
            if q:
                for r in con.execute(text(
                        f"SELECT d.id, d.kind, d.meta, ts_rank_cd(to_tsvector('simple', d.terms), q, 1) AS s "
                        f"FROM {doc} d, to_tsquery('simple', :q) q WHERE to_tsvector('simple', d.terms) @@ q "
                        f"AND {mine} ORDER BY s DESC LIMIT :n"), {"q": q, "uid": uid, "n": k}).all():
                    close[r.id] = min(1.0, float(r.s))
                    meta[r.id] = (r.kind, r.meta)
    votes: dict[str, float] = {}
    for i, s in close.items():
        if s < NEIGHBOR_MIN:
            continue
        kind, m = meta[i]
        m = m if isinstance(m, dict) else json.loads(m or "{}")
        weight = s * (1.0 if kind == "route" else OWN_CHAT)
        for t in m.get("tables") or []:
            votes[t] = votes.get(t, 0.0) + weight
    top = max(votes.values(), default=0.0)
    return {t: round(w / top, 4) for t, w in votes.items()} if top else {}


def route_examples(question: str, k: int = 6) -> list[dict[str, Any]]:
    """The router's examples: the routes people confirmed (and the execution kept to) of the questions most like
    this one, closest first: [{question, route, similarity, admin}], by meaning ([] without vectors: the router
    compares the words itself)."""
    st = state()
    e = engine()
    if not st or e is None or not settings.get("search.chats"):
        return []
    doc = _q(f"doc_{int(st['version'])}")
    where = "d.kind = 'route' AND (d.meta->>'moa') IS NOT NULL"
    out: list[dict[str, Any]] = []
    with e.connect() as con:
        try:
            from supagent.knowledge import embeddings as E

            if st.get("dims") and E.enabled():
                qv = query_vector(question)
                rows = con.execute(text(
                    f"SELECT d.title, d.meta, 1 - (d.embedding <=> CAST(:qv AS halfvec({int(st['dims'])}))) AS s "
                    f"FROM {doc} d WHERE d.embedding IS NOT NULL AND {where} "
                    f"ORDER BY d.embedding <=> CAST(:qv AS halfvec({int(st['dims'])})) LIMIT :n"),
                    {"qv": _vec_text(qv), "n": k}).all()
                out = [{"question": r.title, "similarity": round(float(r.s), 3), **_route_meta(r.meta)} for r in rows]
        except Exception as ex:  # pylint: disable=broad-except   (the router's words instead)
            log.warning("supagent store: route examples by meaning: %s", str(ex)[:300])
    return [x for x in out if x.get("route")]


def _route_meta(meta: Any) -> dict[str, Any]:
    m = meta if isinstance(meta, dict) else json.loads(meta or "{}")
    return {"route": m.get("moa"), "admin": bool(m.get("moa_admin"))}     # an admin set this route (not the answer)


NEIGHBOR_MIN = 0.72         # a question at least this close (cosine) votes for the tables it was answered from
OWN_CHAT = 0.5              # the user's own earlier answer (not confirmed) counts half a confirmed route


def chats(query: str, user_id: int, k: int = 8, days: int | None = None,
          min_cos: float | None = None) -> list[dict[str, Any]]:
    """The user's own earlier questions and answers like this query (theirs only), newest first among the
    closest: date, question, the answer's beginning, the tables it read. min_cos (a search box): a chat with
    every word of the query, or found by meaning at least this close; never the nearest of anything."""
    st = state()
    e = engine()
    if not st or e is None or not user_id:
        return []
    v = int(st["version"])
    doc = _q(f"doc_{v}")
    where = "d.kind = 'chat' AND d.user_id = :uid"
    params: dict[str, Any] = {"uid": user_id}
    if days:
        where += " AND (d.meta->>'at') >= :since"
        params["since"] = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat(timespec="minutes")
    found: dict[int, float] = {}
    close: set[int] = set()                       # found by meaning at least min_cos close
    with e.connect() as con:
        for rank, (i, _s) in enumerate(_by_words(con, v, st, query, where, params, builtin=True)):
            found[i] = found.get(i, 0.0) + 1.0 / (RRF + rank)
        try:
            from supagent.knowledge import embeddings as E

            if st.get("dims") and E.enabled():
                qv = query_vector(query)
                rows = con.execute(text(
                    f"SELECT d.id, d.embedding <=> CAST(:qv AS halfvec({int(st['dims'])})) AS dist FROM {doc} d "
                    f"WHERE d.embedding IS NOT NULL AND {where} "
                    f"ORDER BY d.embedding <=> CAST(:qv AS halfvec({int(st['dims'])})) LIMIT :n"),
                    {**params, "qv": _vec_text(qv), "n": CANDIDATES}).all()
                for rank, r in enumerate(rows):
                    if min_cos is not None and 1.0 - float(r.dist) < min_cos:
                        break
                    found[r.id] = found.get(r.id, 0.0) + 1.0 / (RRF + rank)
                    close.add(r.id)
        except Exception as ex:  # pylint: disable=broad-except
            log.warning("supagent store: chats by meaning: %s", str(ex)[:300])
        if min_cos is not None and found:         # a search box: every word typed, or close in meaning
            asked = set(words(query))
            have = dict(con.execute(text(f"SELECT d.id, d.terms FROM {doc} d WHERE d.id = ANY(:ids)"),
                                    {"ids": list(found)}).all())
            found = {i: sc for i, sc in found.items() if i in close or asked <= set((have.get(i) or "").split())}
        ids = [i for i, _s in sorted(found.items(), key=lambda x: -x[1])[:k]]
        rows = con.execute(text(f"SELECT d.id, d.title, d.body, d.meta FROM {doc} d WHERE d.id = ANY(:ids)"),
                           {"ids": ids or [-1]}).all()
    by_id = {r.id: r for r in rows}
    out = []
    for i in ids:
        r = by_id.get(i)
        if r is None:
            continue
        m = r.meta if isinstance(r.meta, dict) else json.loads(r.meta or "{}")
        answer = (r.body or "").split("\nA: ", 1)[-1]
        out.append({"at": m.get("at"), "question": r.title, "answer": answer[:600], "tables": m.get("tables") or [],
                    "conversation_id": m.get("conversation_id"), "message_id": m.get("message_id"),
                    "feedback": m.get("feedback")})
    return out


def status() -> dict[str, Any]:
    """What the store is: where, which extensions and versions, the version in use, its size, and the
    warnings an admin must read (pg_textsearch before 0.6.1 loaded for every session)."""
    e = engine()
    if e is None:
        return {"store": "unavailable", "why": "Superset's database is not PostgreSQL and search.store_uri is empty"}
    out: dict[str, Any] = {"setting": settings.get("search.store"), "schema": schema(),
                           "database": _url().render_as_string(hide_password=True)}
    try:
        with e.connect() as con:
            caps = capabilities(con)
            out["extensions"] = caps
            st = _read_state(con) if con.execute(text("SELECT to_regnamespace(:s)"), {"s": schema()}).scalar() else None
            out["state"] = {k: (str(v) if isinstance(v, dt.datetime) else v) for k, v in (st or {}).items()}
            if st:
                v = int(st["version"])
                out["rows"] = dict(con.execute(text(f"SELECT kind, count(*) FROM {_q(f'doc_{v}')} GROUP BY kind "
                                                    "ORDER BY kind")).all())
                out["names"] = con.execute(text(f"SELECT count(*) FROM {_q(f'name_{v}')}")).scalar()
                if st.get("dims"):
                    out["without_vector"] = con.execute(text(f"SELECT count(*) FROM {_q(f'doc_{v}')} WHERE "
                                                             "embedding IS NULL")).scalar()
    except Exception as ex:  # pylint: disable=broad-except
        out["error"] = str(ex)[:500]
        return out
    warnings = []
    if caps.get("pg_textsearch") and not caps.get("pg_textsearch_safe"):
        warnings.append(f"pg_textsearch {caps['pg_textsearch']} is a pre-release: before 0.6.1 a ROLLBACK after an "
                        "error can fail (ResourceOwnerEnlarge called after release started) and leave the session "
                        "stuck in any session that loaded it"
                        + (" (it is in shared_preload_libraries: every session, Superset's too)"
                           if caps.get("pg_textsearch_preloaded")
                           else " (whether it is in shared_preload_libraries is not shown to this database user: "
                                "check it as a superuser, SHOW shared_preload_libraries; there, every session, "
                                "Superset's too)" if caps.get("pg_textsearch_preloaded") is None else "")
                        + "; upgrade it (1.x). The store's own connections never run a transaction.")
    if not caps.get("vector"):
        warnings.append("no pgvector: no search by meaning in the store")
    if not caps.get("pg_trgm"):
        warnings.append("no pg_trgm: no search by near spellings")
    if not caps.get("pg_textsearch"):
        warnings.append("no pg_textsearch: words ranked by PostgreSQL's full-text search (no BM25)")
    out["warnings"] = warnings
    return out
