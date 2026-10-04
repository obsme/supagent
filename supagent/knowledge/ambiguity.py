"""Questions to ask back instead of guessing (0.9.2, rule 6 made concrete).

Two cases the agent kept answering with a guess:
  - one thing named, several match: "How did the options book do yesterday?" when five books have OPT/OPTIONS in
    their name; "the swaps book", "the pricer" (five pricers, none named). The field is the one the head noun names
    (book -> BOOK), the qualifier words are matched to the parts of its values (options -> OPTIONS, OPT); a value of
    the field named in the question or said earlier in the chat settles it, and so does a restriction ("the book that
    lost the most", "the desk with the highest VaR", "which book").
  - nothing to refer to: "Show me the late ones from yesterday.", "How many were late yesterday?" as the first message
    of a conversation: the ones of what?
The agent is told to ask one short question naming the candidates; an answer that does not ask is sent back once.
"""

from __future__ import annotations

import re
from typing import Any, Callable

MAX_CANDIDATES = 12               # more values than this: no list to ask from (a ranking question, not a name)
# "the options book", "the pricer", "this desk", "the swaps book's": an article, then up to three words
ARTICLE = re.compile(r"\b(?:the|this|that)\s+(?=[A-Za-z])", re.I)
STOP = frozenset("of on in for to the a an with that which at from by and or this these those its their is was are "
                 "were do did does has have had be".split())
RESTRICTED = re.compile(r"^\s*(?:that|which|who|whose|with|where|whom|named|called|of|on|in|for|from|at|whose)\b", re.I)
# a question about a day's data ("yesterday", "on 22 September", "this morning"): "the pricer" there is one pricer
DAY_WORDS = re.compile(r"\b(?:yesterday|today|tonight|this (?:morning|week|month)|last (?:night|week|month)|"
                       r"\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*|"
                       r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2}|\d{4}-\d{2}-\d{2}|"
                       r"hier|aujourd'hui|ce matin)\b", re.I)
NOT_QUALIFIERS = frozenset("""same other first last next previous whole total official flash main usual current new old
best worst biggest largest smallest top bottom latest earliest daily weekly monthly yearly entire overall one only
average highest lowest most least""".split())
# a message that refers to rows never named ("the late ones", "them", "how many were late") at a conversation's start
NO_ANTECEDENT = re.compile(
    r"\b(?:the|those|these)\s+(?:[a-z]+\s+)?ones?\b|^\W*(?:how many|combien)\s+(?:were|are|did|have|had|got|en)\b|"
    r"\b(?:show|list|give|count|display)\s+(?:me\s+)?(?:them|those|these|it)\b", re.I)     # ("how much was refunded": a subject)
WHICH = re.compile(r"\b(?:which|what|quel(?:le)?s?)\s+(?:[a-z]+\s+){0,2}$", re.I)


def _singular(word: str) -> str:
    w = word.lower()
    return w[:-1] if w.endswith("s") and len(w) > 3 and not w.endswith("ss") else w


def _matches(value: str, qualifiers: list[str]) -> bool:
    """A value matches when each qualifier is one of its parts, or the start of one, or a part abbreviates it
    (options: OPTIONS, OPT; swaps: SWAPS)."""
    parts = [p.lower() for p in re.split(r"[_\-\s.]+", value) if p]
    for q in qualifiers:
        if not any(p == q or p.startswith(q) or (len(p) >= 3 and q.startswith(p)) for p in parts):
            return False
    return True


def field_words(field: str) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", field.lower()) if len(w) >= 3]


def singular_choice(question: str, history_text: str, values_of: Callable[[str], dict[str, list[str]]]
                    ) -> tuple[str, str, list[str]] | None:
    """(the words of the question, the field, the candidates) when the question names one thing of a field that
    several values match, None otherwise. values_of(head noun) -> {field: [its values]}. With qualifier words
    ("the options book") the values they match; with none ("the pricer") every value, and only for a day's data."""
    q = question or ""
    low_history = (history_text or "").lower()
    for m in ARTICLE.finditer(q):
        if WHICH.search(q[:m.start()]):
            continue                                   # "which book ...": asking for it, not naming it
        words, spans, rest, last = [], [], q[m.end():], 0
        for w in re.finditer(r"[A-Za-z][\w-]*(?:'s)?", rest):
            if len(words) == 3 or w.group(0).lower() in STOP or rest[last:w.start()].strip(" "):
                break                                  # up to three words in a row, no "of", "the", punctuation
            words.append(w.group(0))
            spans.append(m.end() + w.end())
            last = w.end()
        for k, raw in enumerate(words):
            after = q[spans[k]:]
            if raw.endswith("'s"):
                raw = raw[:-2]
            elif RESTRICTED.match(after):
                continue                               # "the book that lost the most", "the desk with ..."
            head = _singular(raw)
            if len(head) < 3 or head in NOT_QUALIFIERS or head != raw.lower():
                continue                               # "the options books": all of them, nothing to choose
            if raw.isupper():
                continue                               # "the ACME jobs": a name (a value), not the thing named
            quals = [_singular(w) for w in words[:k] if w.lower() not in NOT_QUALIFIERS]
            if not quals and not _day_after(q, spans[k]):
                continue                               # "what is the timeout of the pricer?": no one pricer meant;
                #                                        "note for the team: the meeting of 30 September": no day of it
            if not quals and not all(DAY_WORDS.fullmatch(w) for w in words[k + 1:]):
                continue                               # "the most job failures": job says which failures
            fields = {f: [str(v) for v in vs if v not in (None, "")] for f, vs in (values_of(head) or {}).items()}
            text = q.lower() + "\n" + low_history
            if any(re.search(rf"(?<![\w-]){re.escape(v.lower())}(?![\w-])", text)
                   for vs in fields.values() if len(vs) <= 200 for v in vs):
                continue                               # a value of it named here or earlier ("the LOANS business
                #                                        line": LOANS of the business lines): settled
            every = [_singular(w) for w in words[:k]]
            for field, values in fields.items():
                if not values or len(values) > 200:
                    continue
                if every != quals and len([v for v in values if _matches(v, every)]) == 1:
                    continue                           # "the official PnL report": its words name one of them
                found = [v for v in values if _matches(v, quals)] if quals else values
                if 2 <= len(found) <= MAX_CANDIDATES:
                    return " ".join(words[:k + 1]).strip(), field, sorted(found)
    return None


def _day_after(q: str, end: int) -> bool:
    """A day said right after the noun (at most four words later, no punctuation between): "the pricer yesterday",
    "the job on 22 September"."""
    m = DAY_WORDS.search(q, end)
    if m is None:
        return False
    between = q[end:m.start()]
    return not re.search(r"[:;,.!?()]", between) and len(between.split()) <= 4


def no_antecedent(question: str, history: list[dict] | None) -> str | None:
    """The words that refer to rows never named, when the message starts the conversation."""
    if any(h.get("content") for h in history or []):
        return None
    m = NO_ANTECEDENT.search(question or "")
    return m.group(0).strip() if m else None


def db_values_of(head: str) -> dict[str, list[str]]:
    """The keyword fields whose name is the head noun (book -> BOOK, pricer -> PRICER), with the values the
    dictionary learned for them (one list per field name, the fields of every table merged)."""
    from superset import db

    from supagent.models import KObject

    out: dict[str, list[str]] = {}
    rows = (db.session.query(KObject.name, KObject.stats).filter(KObject.kind == "field", KObject.gone_at.is_(None))
            .filter(KObject.name.ilike(f"%{head}%")).limit(400).all())
    for name, stats in rows:
        words = field_words(name)
        if not words or not (head in words or (words[-1].startswith(head) and len(head) >= 4)):
            continue
        values = (stats or {}).get("values") if isinstance(stats, dict) else None
        if isinstance(values, list) and values:
            merged = out.setdefault(name.upper(), [])
            merged.extend(str(v) for v in values if str(v) not in merged)
    return out


def ask_first(question: str, history: list[dict] | None,
              values_of: Callable[[str], dict[str, list[str]]] | None = None) -> dict[str, Any] | None:
    """What makes the question one to ask back first: {"kind": "choice", "said", "field", "candidates"} or
    {"kind": "unclear", "said"}; None when it can be answered."""
    words = no_antecedent(question, history)
    if words:
        return {"kind": "unclear", "said": words}
    text = "\n".join(str(h.get("content") or "") for h in history or [])
    found = singular_choice(question, text, values_of or db_values_of)
    if found:
        return {"kind": "choice", "said": found[0], "field": found[1], "candidates": found[2]}
    return None


def note(found: dict[str, Any]) -> str:
    """The instruction given with the question."""
    if found["kind"] == "choice":
        names = ", ".join(found["candidates"])
        return (f"(Ask back first: the question says \"{found['said']}\" and several {found['field']} values match: "
                f"{names}. Answer only with one short question asking which one is meant (name them); run no query.)")
    return (f"(Ask back first: this message starts the conversation and says \"{found['said']}\" without saying of "
            "what. Answer only with one short question asking what it means (name the two or three kinds of data it "
            "could be, from the knowledge above); run no query.)")
