"""The words of a search read as the knowledge spells them (0.9.6).

A word typed with a letter missing, one too many, two letters swapped or a wrong key, a space inside a word or two
words run together: the search looked for the word as typed, matched nothing by it, and the pieces that hold the word
were found only by the question's other words, or not at all (with one word misspelled, the right page among the ten
first fell from 81 to 39-47 out of 100 on a corpus of 2,300 documentation pages). Before a search, each word of it
that no piece the user may see holds (5 letters at least, letters only: a name, an identifier, a number keeps the
near-spelling search of the names) is read as:
  - two words run together (wo rking) or a word cut by a space (paymentrefund): the known word or the two known words
    they make;
  - else the known word one edit away (a letter missing, one too many, two swapped, one replaced), the one most pieces
    hold.
A word some piece holds as typed is never changed; a word with no known word one edit away is searched as typed. Known
means held by a piece the user may see (the store's words, checked in its live index: a word written a minute ago
counts); the candidates come from the store's list of words (or, without the store, the words of the pieces the user
may see). The search says what it read otherwise ("refunnd" read as "refund"): the agent and the user see it.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

MIN_LETTERS = 5          # shorter words have too many neighbours one edit away to be read otherwise safely
MIN_PIECES = 1           # a word offered instead is held by at least this many pieces
LETTERS = "abcdefghijklmnopqrstuvwxyz"
VOWELS = set("aeiouy")
TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
CACHE_SECONDS = 60.0
CACHE_SIZE = 256
FALLBACK_SECONDS = 600.0
BIG = 10 ** 9
_CACHE: dict[tuple, tuple[float, dict[str, Any]]] = {}
_LOCK = threading.Lock()
_FALLBACK: dict[Any, tuple[float, dict[str, int]]] = {}
# the keys next to each key, on a QWERTY and on an AZERTY keyboard (a key on the row above or below counts when it
# touches it)
LAYOUTS = ((("qwertyuiop", 0.0), ("asdfghjkl", 0.25), ("zxcvbnm", 0.75)),
           (("azertyuiop", 0.0), ("qsdfghjklm", 0.25), ("wxcvbn", 0.75)))


def _neighbours() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {c: set() for c in LETTERS}
    for rows in LAYOUTS:
        at = {ch: (x + off, y) for y, (row, off) in enumerate(rows) for x, ch in enumerate(row)}
        for a, (xa, ya) in at.items():
            for b, (xb, yb) in at.items():
                if a != b and ((xa - xb) ** 2 + (ya - yb) ** 2) ** 0.5 <= 1.3:
                    out[a].add(b)
    return out


NEAR = _neighbours()


def edits1(word: str) -> list[str]:
    """The words one typing slip from `word`, the first letter kept (it is rarely the one mistyped): a letter it
    lacks (any), a letter too many (typed twice, or a key next to its neighbour), two letters swapped, a letter
    replaced by a key next to it or a vowel by another; in that order, each once."""
    n = len(word)
    out = [word[:i] + c + word[i:] for i in range(1, n + 1) for c in LETTERS]          # it lacks a letter
    for i in range(1, n):                                                               # a letter too many
        c, around = word[i], {word[i - 1]} | ({word[i + 1]} if i + 1 < n else set())
        if c in around or any(c in NEAR.get(x, ()) for x in around):
            out.append(word[:i] + word[i + 1:])
    out += [word[:i] + word[i + 1] + word[i] + word[i + 2:] for i in range(1, n - 1)]  # two swapped
    for i in range(1, n):                                                               # a key next to it
        c = word[i]
        for x in sorted(NEAR.get(c, set()) | (VOWELS - {c} if c in VOWELS else set())):
            out.append(word[:i] + x + word[i + 1:])
    return list(dict.fromkeys(w for w in out if w != word))


def _norm(word: str) -> str:
    from supagent.knowledge.pgstore import _fold

    return _fold(word).lower()


def _stem(word: str) -> str:
    from supagent.knowledge.describe import stem

    return stem(word)


def _stop() -> set[str]:
    from supagent.knowledge.describe import STOP

    return STOP


def tokens(query: str) -> list[dict[str, Any]]:
    """The words of the query with where they are ({"at", "end", "raw", "word"}), the ones inside a name (an
    identifier: node_cpu_seconds, payment-gateway, camelCase) marked: names are never read otherwise."""
    from supagent.knowledge.pgstore import IDENTIFIER

    names = [(m.start(), m.end()) for m in IDENTIFIER.finditer(query or "")]
    out = []
    for m in TOKEN.finditer(query or ""):
        word = _norm(m.group(0))
        if not re.fullmatch(r"[a-z]+", word):
            continue
        out.append({"at": m.start(), "end": m.end(), "raw": m.group(0), "word": word,
                    "name": any(a <= m.start() and m.end() <= b for a, b in names)})
    return out


class Lookup:
    """What the knowledge holds: `known(stems)` the stems some piece the user may see holds now; `counts(stems)` how
    many pieces hold each stem, by the list of words (the candidates); `side_by_side(pairs)` the pairs of stems some
    piece the user may see holds next to each other."""

    def __init__(self, known: Callable[[list[str]], set[str]], counts: Callable[[list[str]], dict[str, int]],
                 side_by_side: Callable[[list[tuple[str, str]]], set[tuple[str, str]]]) -> None:
        self.known, self.counts, self.side_by_side = known, counts, side_by_side


def read(query: str, look: Lookup) -> dict[str, Any]:
    """{"query": the query as read, "changes": [{"typed", "read"}]}: the words of the query no piece holds, read as
    the knowledge spells them (see the module's text)."""
    toks = tokens(query)
    stop = _stop()
    plain = [t for t in toks if not t["name"] and t["word"] not in stop]
    if not plain:
        return {"query": query, "changes": []}
    held_typed = look.known(sorted({_stem(t["word"]) for t in plain}))

    def as_typed(t: dict[str, Any]) -> bool:
        return t["word"] in stop or _stem(t["word"]) in held_typed

    def fragment(t: dict[str, Any]) -> bool:
        return len(t["word"]) <= 3 and t["word"] not in stop

    fixable = [t for t in plain if not as_typed(t) and len(t["word"]) >= MIN_LETTERS]
    pairs = [(i, a, b) for i, (a, b) in enumerate(zip(toks, toks[1:]))
             if not a["name"] and not b["name"] and query[a["end"]:b["at"]].strip() == ""
             and len(a["word"] + b["word"]) >= MIN_LETTERS
             and (not as_typed(a) or not as_typed(b) or fragment(a) or fragment(b))]
    if not fixable and not pairs:
        return {"query": query, "changes": []}
    # the candidates: every word one slip away, the halves of a word cut in two, two words run together
    # a slip in the word's stem first (Restire: restore; paymnets: payments), then in the word as typed (filteriong:
    # filtering): a word one slip away whose stem collapses to a shorter known word (resture: rest) is not offered
    # when the stem itself has a known neighbour
    by_stem: dict[int, list[tuple[str, str]]] = {}
    edits: dict[int, list[tuple[str, str]]] = {}
    for t in fixable:
        w = t["word"]
        ts = _stem(w)
        tail = w[len(ts):] if w.startswith(ts) else ""
        keep = tail if tail in ("s", "es") else ""      # payments; deducing, sentenced: deduce, sentence
        by_stem[t["at"]] = [(c + keep, c) for c in edits1(ts)] if len(ts) >= MIN_LETTERS - 1 else []
        edits[t["at"]] = [(c, _stem(c)) for c in edits1(w)]
    asked = {s for got in list(edits.values()) + list(by_stem.values()) for _w, s in got}
    for t in fixable:
        w = t["word"]
        asked |= {_stem(h) for k in range(1, len(w)) for h in (w[:k], w[k:]) if h not in stop}
    asked |= {_stem(a["word"] + b["word"]) for _i, a, b in pairs}
    counts = {s: c for s, c in look.counts(sorted(x for x in asked if x)).items() if c >= MIN_PIECES}
    held = look.known(sorted(counts)) if counts else set()
    known = {s: counts[s] for s in held}

    def is_known(word: str) -> bool:
        return word in stop or _stem(word) in known or _stem(word) in held_typed

    # what each word may be read as: two words typed apart that are one known word; a word one slip from a known
    # word (the one most pieces hold); a word that is two known words run together (two words of 3 letters at least
    # that some piece has next to each other, or a word and a function word of 3 letters at least: workingwith)
    joins, splits, ask = [], {}, []
    for i, a, b in pairs:
        if _stem(a["word"] + b["word"]) not in known:
            continue
        if as_typed(a) and as_typed(b):                 # both words of their own, one short ("set up", "ML models"):
            if a["word"] in stop or b["word"] in stop:  # joined only when the knowledge never has them side by side
                continue
            ask.append((_stem(a["word"]), _stem(b["word"])))
        joins.append((i, a, b))
    best: dict[int, str] = {}
    for t in fixable:
        top = None
        for got in (by_stem[t["at"]], edits[t["at"]]):
            for w, st in got:
                if st in known and (top is None or known[st] > top[1]):
                    top = (w, known[st])
            if top:
                break
        if top:
            best[t["at"]] = top[0]
            continue
        w, cands = t["word"], []
        for k in range(1, len(w)):
            x, y = w[:k], w[k:]
            sx, sy = x in stop, y in stop
            if sx and sy:
                continue
            if sx or sy:                                 # a function word and a word: with, from, the...
                word, func = (y, x) if sx else (x, y)
                if len(func) >= 3 and len(word) >= 4 and is_known(word):
                    cands.append((known.get(_stem(word), BIG), x, y, None))
            elif len(x) >= 3 and len(y) >= 3 and is_known(x) and is_known(y):
                pair = (_stem(x), _stem(y))
                cands.append((min(known.get(pair[0], BIG), known.get(pair[1], BIG)), x, y, pair))
                ask.append(pair)
        splits[t["at"]] = cands
    together = look.side_by_side(ask) if ask else set()
    changes: list[dict[str, Any]] = []
    spans: list[tuple[int, int, str]] = []
    used: set[int] = set()
    for i, a, b in joins:
        if i in used or i + 1 in used:
            continue
        if as_typed(a) and as_typed(b) and (_stem(a["word"]), _stem(b["word"])) in together:
            continue
        joined = a["word"] + b["word"]
        spans.append((a["at"], b["end"], joined))
        changes.append({"typed": query[a["at"]:b["end"]], "read": joined})
        used |= {i, i + 1}
    for t in fixable:
        idx = toks.index(t)
        if idx in used:
            continue
        read_as = best.get(t["at"])
        if read_as is None:
            ok = [c for c in splits.get(t["at"], []) if c[3] is None or c[3] in together]
            if ok:
                _n, x, y, _p = max(ok)
                read_as = f"{x} {y}"
        if read_as:
            spans.append((t["at"], t["end"], read_as))
            changes.append({"typed": t["raw"], "read": read_as})
            used.add(idx)
    if not spans:
        return {"query": query, "changes": []}
    out, at = [], 0
    for a, b, w in sorted(spans):
        out.append(query[at:a] + w)
        at = b
    out.append(query[at:])
    return {"query": "".join(out), "changes": changes}


def _store_lookup() -> Lookup | None:
    from supagent.knowledge import pgstore

    if not pgstore.active():
        return None
    return Lookup(pgstore.holding, pgstore.word_counts, pgstore.side_by_side)


def _fallback_lookup() -> Lookup:
    """Without the store: the words of the pieces the user may see (made again every 10 minutes)."""
    from flask import g

    key = getattr(getattr(g, "user", None), "id", None)
    hit = _FALLBACK.get(key)
    if hit is None or time.time() - hit[0] > FALLBACK_SECONDS:
        from supagent.knowledge.pgstore import words
        from supagent.knowledge.search import _allowed_query

        counts: dict[str, int] = {}
        for title, text in _allowed_query().with_entities(_title_col(), _text_col()).limit(50000):
            for w in set(words(f"{title or ''} {text or ''}")):
                if w.isalpha():
                    counts[w] = counts.get(w, 0) + 1
        if len(_FALLBACK) > 32:
            _FALLBACK.clear()
        hit = _FALLBACK[key] = (time.time(), counts)
    vocab = hit[1]
    return Lookup(lambda stems: {s for s in stems if s in vocab}, lambda stems: {s: vocab[s] for s in stems if s in vocab},
                  lambda pairs: set(pairs))          # without the store, two known words are never joined


def _title_col() -> Any:
    from supagent.models import Chunk

    return Chunk.title


def _text_col() -> Any:
    from supagent.models import Chunk

    return Chunk.text


def correct(query: str) -> dict[str, Any]:
    """The query as the search reads it, and what it read otherwise; the query unchanged when nothing needs it or the
    words cannot be looked up (cached a minute per user and query: the search and the tool's answer ask twice)."""
    from flask import g

    from supagent import settings

    if not str(query or "").strip() or not settings.get("search.spelling"):
        return {"query": query, "changes": []}
    try:
        from supagent.knowledge import pgstore

        st = pgstore.state() if pgstore.active() else None
        key = (query, getattr(getattr(g, "user", None), "id", None), (st or {}).get("version"))
    except Exception:  # pylint: disable=broad-except
        key = (query, None, None)
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_SECONDS:
            return hit[1]
    try:
        look = _store_lookup() or _fallback_lookup()
        out = read(query, look)
    except Exception as ex:  # pylint: disable=broad-except   (the search goes on with the words as typed)
        log.warning("supagent spelling: %s", str(ex)[:300])
        try:
            from superset import db

            db.session.rollback()
        except Exception:  # pylint: disable=broad-except
            pass
        out = {"query": query, "changes": []}
    with _LOCK:
        if len(_CACHE) > CACHE_SIZE:
            _CACHE.clear()
        _CACHE[key] = (now, out)
    return out


def said(changes: list[dict[str, Any]]) -> str:
    """The words read otherwise, for the agent and the page: 'refunnd' read as 'refund'."""
    return "; ".join(f"'{c['typed']}' read as '{c['read']}'" for c in changes or [])
