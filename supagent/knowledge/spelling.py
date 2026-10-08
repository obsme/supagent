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
    hold;
  - else (0.10, with the knowledge store and pg_trgm) a word of the pieces as written that is near it by its trigrams
    and at most two slips away (two slips for words of NEAR_LETTERS letters at least, one for shorter ones: a key far
    from the right one), the same first letter: the fewest slips, then the one most pieces hold.
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
NEAR_LETTERS = 7         # a word read two slips away has this many letters at least (fewer: too many neighbours)
NEAR_SLIPS = 2
NEAR_PIECES = 1          # a word read two slips away is held by this many pieces at least
NEAR_MARGIN = 1.0        # ... and the next candidate as many slips away is held by fewer than 1/this of its pieces
                         # (1.0: no margin asked)
READ_NAMES = True        # the words inside a name typed (custom_icu_anbalyzer) read as the others (the name itself is
                         # still searched as typed by the near spelling of the names): on 2,300 pages, a name typed
                         # with a slip found among the first ten 72% -> 80% of the time, a name typed exactly 94% -> 93%
NEAR_SINGLE = True       # the words as written may read a word one slip away that edits1 does not (a key far away,
                         # any letter): off, they only read words two typing slips away
NEAR_TYPING = True       # two slips: each one a typing slip as edits1 reads one (a key next to the right one or a vowel
                         # for a vowel, a letter typed twice or a key next to its neighbour, a letter missing, two
                         # swapped), not any two changes (communist is not a slip of community): on 2,300 pages, the
                         # correct words the pages never use read otherwise fell from 45 to 29 of 148, the queries
                         # with two words two slips away kept their right page among the first ten (72%)
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


def slips(a: str, b: str, most: int = NEAR_SLIPS) -> int | None:
    """The typing slips between two words (a letter missing, one too many, one replaced, two neighbours swapped: the
    optimal string alignment distance); None when more than `most`."""
    if abs(len(a) - len(b)) > most:
        return None
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > most:
            return None
        prev2, prev = prev, cur
    return prev[-1] if prev[-1] <= most else None


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
    identifier: node_cpu_seconds, payment-gateway, camelCase) marked: never joined with a neighbour; read otherwise
    only with READ_NAMES."""
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
    piece the user may see holds next to each other; `near(words)` (optional) the words of the pieces as written that
    are nearest to each word, {word: [(word as written, its stem, pieces holding it, similarity)]}."""

    def __init__(self, known: Callable[[list[str]], set[str]], counts: Callable[[list[str]], dict[str, int]],
                 side_by_side: Callable[[list[tuple[str, str]]], set[tuple[str, str]]],
                 near: Callable[[list[str]], dict[str, list[tuple[str, str, int, float]]]] | None = None) -> None:
        self.known, self.counts, self.side_by_side, self.near = known, counts, side_by_side, near


def read(query: str, look: Lookup) -> dict[str, Any]:
    """{"query": the query as read, "changes": [{"typed", "read"}], "unknown": [the words no piece holds that are
    near a word of the pieces (two slips at most) and were not read as it (not sure enough): maybe misspelled, as
    typed]}: the words of the query no piece holds, read as the knowledge spells them (see the module's text). A word
    near nothing the pieces write (a real word they do not use, a new name) is not "unknown": nothing to correct."""
    toks = tokens(query)
    stop = _stop()
    plain = [t for t in toks if (READ_NAMES or not t["name"]) and t["word"] not in stop]
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
    doubt: set[int] = set()
    nearest = _nearest([t for t in fixable if t["at"] not in best], look, known, doubt)
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
        if read_as is None:
            read_as = nearest.get(t["at"])
        if read_as:
            spans.append((t["at"], t["end"], read_as))
            changes.append({"typed": t["raw"], "read": read_as})
            used.add(idx)
    unknown = [t["raw"] for t in fixable if toks.index(t) not in used and t["at"] in doubt]
    if not spans:
        return {"query": query, "changes": [], "unknown": unknown}
    out, at = [], 0
    for a, b, w in sorted(spans):
        out.append(query[at:a] + w)
        at = b
    out.append(query[at:])
    return {"query": "".join(out), "changes": changes, "unknown": unknown}


def _nearest(todo: list[dict[str, Any]], look: Lookup, known: dict[str, int],
             doubt: set[int] | None = None) -> dict[int, str]:
    """The words no slip one away reads: the word of the pieces as written they are (see the module), by the place of
    each in the query; `doubt` gets the places of the words near one (two slips at most) not read as it."""
    todo = [t for t in todo if len(t["word"]) >= MIN_LETTERS]
    if not todo or look.near is None:
        return {}
    got = look.near([t["word"] for t in todo])
    stems = {st for cands in got.values() for _w, st, n, _s in cands if n >= MIN_PIECES}
    held = set(known) | (look.known(sorted(stems - set(known))) if stems - set(known) else set())
    out: dict[int, str] = {}
    for t in todo:
        w = t["word"]
        most = NEAR_SLIPS if len(w) >= NEAR_LETTERS else 1
        if not NEAR_SINGLE and most < 2:                   # short: no reading by the words as written
            continue
        typing: set[str] | None = None
        options = []
        for word, st, n, sim in got.get(w, []):
            if word == w or word[:1] != w[:1] or n < MIN_PIECES or st not in held:
                continue
            d = slips(w, word, most)
            if d is not None and (NEAR_SINGLE or d >= 2):
                options.append((d, -n, -sim, word))
            elif doubt is not None and slips(w, word, NEAR_SLIPS) is not None:
                doubt.add(t["at"])                       # near one, too short to be read two slips away
        if not options:
            continue
        options.sort()
        d, n, _s, word = options[0]
        if d >= 2 and NEAR_TYPING:                        # two slips: two typing slips, the best of them
            if typing is None:
                one = edits1(w)
                typing = set(one) | {x for e in one for x in edits1(e)}
            options = [o for o in options if o[0] < 2 or o[3] in typing]
            if not options:
                if doubt is not None:
                    doubt.add(t["at"])
                continue
            d, n, _s, word = options[0]
        if d >= 2:                                        # two slips: a word held enough, clearly ahead of the next
            rival = next((o for o in options[1:] if o[0] == d), None)
            if -n < NEAR_PIECES or (rival is not None and -rival[1] * NEAR_MARGIN > -n):
                if doubt is not None:
                    doubt.add(t["at"])
                continue
        out[t["at"]] = word
    return out


def _store_lookup() -> Lookup | None:
    from supagent.knowledge import pgstore

    if not pgstore.active():
        return None
    return Lookup(pgstore.holding, pgstore.word_counts, pgstore.side_by_side, pgstore.near_words)


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
