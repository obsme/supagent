"""The search judged (0.10, the user's requests of 6 October 2026: "a judge to judge the result with the search query
if it is not taking so long"; "the help of the agent if typo or misspelled ... only if the search does not reach
100%").

  1. the search as always: words (BM25), meaning (vectors), near spellings (pg_trgm), the reranker when one is set
  2. the verdict, without the LLM (it costs nothing):
       weak  a word of the question no piece holds, near a word of the pieces but not read as it (maybe
             misspelled), or the reranker scored the best piece under rerank.judge_floor (the reranker is the judge: it
             reads each piece whole with the question), or, without a reranker, the closest of the first pieces by
             meaning is under search.judge_meaning_floor (cosine of the embedding model: its own scale)
  3. weak and search.rewrite = weak (the default): the LLM writes the question again once (spelling fixed, names kept, a few other
     words for the same things; search.rewrite_seconds at most), the search runs with it and both lists are fused
     (ranks); a question the search found well never waits for the LLM
The verdict goes with the results (the words no piece holds, what was searched): the agent sees them and may search
again itself.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from supagent import settings

log = logging.getLogger(__name__)

RRF = 60
CACHE_S = 300.0
CACHE_N = 256
_CACHE: OrderedDict[str, tuple[float, str]] = OrderedDict()
_LOCK = threading.Lock()
PROMPT = ("You correct search queries for a search of documentation, code and data descriptions. Write the query "
          "again: fix the misspelled words, keep names, identifiers and numbers as written unless clearly misspelled, "
          "and add at most three other words for the same things. Answer with the query only, on one line.")


def verdict(query: str, found: list[dict[str, Any]]) -> dict[str, Any]:
    """{"weak": bool, "why": [...], "unknown": [words no piece holds, nothing near], "best": the reranker's best
    score or None} (no LLM)."""
    from supagent.knowledge.spelling import correct

    why: list[str] = []
    try:
        unknown = list(correct(query).get("unknown") or [])
    except Exception:  # pylint: disable=broad-except
        unknown = []
    if unknown:
        why.append("no piece holds " + ", ".join(f"'{w}'" for w in unknown[:5]))
    best = max((float(f["rerank"]) for f in found if f.get("rerank") is not None), default=None)
    floor = str(settings.get("rerank.judge_floor") or "").strip()
    if best is not None and floor:
        try:
            if best < float(floor):
                why.append(f"the judge (reranker) scored the best piece {best:.3f}, under {floor}")
        except ValueError:
            pass
    close = max((float(f["cos"]) for f in found[:5] if f.get("cos") is not None), default=None)
    cos_floor = str(settings.get("search.judge_meaning_floor") or "").strip()
    from supagent.knowledge.pgstore import _sentence

    if close is not None and cos_floor and _sentence(query):   # a question in words (a list of keywords or a name:
        #                                                         their closeness by meaning says little)
        try:
            if close < float(cos_floor):
                why.append(f"the closest piece by meaning is {close:.3f} from the question, under {cos_floor}")
        except ValueError:
            pass
    if not found:
        why.append("nothing found")
    return {"weak": bool(why), "why": why, "unknown": unknown, "best": best}


def rewrite(query: str, unknown: list[str], ask: Callable[[list[dict]], str] | None = None) -> str | None:
    """The question written again by the LLM (one line), None when it cannot (no LLM, too slow, the same query).
    `ask`: the LLM's call (tests)."""
    key = f"{query}\x00{','.join(unknown)}"
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and now - hit[0] < CACHE_S:
            return hit[1] or None
    messages = [{"role": "system", "content": PROMPT},
                {"role": "user", "content": f"Query: {query}" + (f"\nWords no document holds: {', '.join(unknown)}"
                                                                 if unknown else "")}]
    try:
        if ask is None:
            from supagent.llm import LLM, bounded

            llm = LLM()
            with bounded(llm, float(settings.get("search.rewrite_seconds") or 4.0)):
                text = str((llm.chat(messages, max_tokens=80) or {}).get("content") or "")
        else:
            text = ask(messages)
    except Exception as ex:  # pylint: disable=broad-except   (the first search answers alone)
        log.info("supagent judge: no rewrite: %s", str(ex)[:200])
        return None
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.S).strip()
    line = next((ln.strip().strip('"').strip() for ln in text.splitlines() if ln.strip()), "")
    line = re.sub(r"^(query|rewritten( query)?)\s*:\s*", "", line, flags=re.I)[:300]
    out = line if line and line.lower() != query.strip().lower() else ""
    with _LOCK:
        _CACHE[key] = (now, out)
        while len(_CACHE) > CACHE_N:
            _CACHE.popitem(last=False)
    return out or None


def fused(first: list[dict[str, Any]], second: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """Both lists by their ranks (a piece in both counts twice), at most k."""
    score: dict[str, float] = {}
    piece: dict[str, dict[str, Any]] = {}
    for got in (first, second):
        for rank, f in enumerate(got):
            ref = f.get("ref") or ""
            score[ref] = score.get(ref, 0.0) + 1.0 / (RRF + rank)
            piece.setdefault(ref, f)
    return [piece[r] for r, _s in sorted(score.items(), key=lambda x: -x[1])][:k]


def judged(query: str, run: Callable[[str], list[dict[str, Any]]], k: int,
           ask: Callable[[list[dict]], str] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The search `run` judged, written again by the LLM when weak (search.rewrite): (pieces, {"weak", "why",
    "unknown", "best", "searched_also"?, "seconds"?})."""
    found = run(query)
    v = verdict(query, found)
    if not v["weak"] or (settings.get("search.rewrite") or "off") != "weak":
        return found, v
    t0 = time.time()
    again = rewrite(query, v["unknown"], ask)
    if not again:
        return found, v
    second = run(again)
    v["searched_also"] = again
    v["seconds"] = round(time.time() - t0, 2)
    return fused(found, second, k), v
