"""A message that continues the previous question keeps its conditions (the classic pipeline).

"when I say <APP> you should know the filter is APPLICATION=<APP> ... and show me now only <APP>", after an
answer counted with STATUS_INFO = 'KO' and POSITION_LABEL = 'D': the new queries added the application and
dropped the label ("the label rule does not apply because the request did not mention a specific label").
The previous answer's conditions on a table this answer queries again, that no query of this answer has
(nor groups by), and that the message does not change (it names their column or value) or remove ("all",
"without"...), are sent back once, then said under the answer. Time windows are not carried (a follow-up
may move them); a window written with now() is no condition here anyway (sql_conditions reads literals). A message
that goes back to an earlier question ("Back to the September returns: how many were refunded?") has that
question's scope, not the last answer's: nothing is carried.

A message that names its own subject with "that"/"this"/"the ...'s" ("how many trades of that desk were cancelled",
"that desk's official PnL", "the team's tickets"), where the noun is a field the previous queries filtered or grouped
by, is about that subject as a whole: only the conditions on that field are kept, the narrower ones of the previous
answer (booked by voice, one trader, the P1 tickets) are not (0.9.2: the check had the model add them back, and a
right count became a wrong one). "Of them", "among those" refer to the previous rows themselves: everything is kept.
"""

from __future__ import annotations

import re
from typing import Any

REFINES = re.compile(r"\b(only|just|instead|also|same|again|except|as well|"
                     r"seulement|uniquement|aussi|m[êe]me|encore|sauf|plut[ôo]t)\b", re.I)
REMOVES = re.compile(r"\b(all|any|every|without|remove|drop|ignore|regardless|whatever|no longer|not only|"
                     r"in total|overall|altogether|in all|tous|toutes|sans|enl[eè]ve|retire|ignore|quel que soit|"
                     r"au total|en tout|globalement|dans l'ensemble)\b", re.I)
DATED = re.compile(r"^\d{4}-\d{2}-\d{2}")
# "that desk", "this server", "that desk's", "the team's", "ce desk", "cette application"
SUBJECT = re.compile(r"\b(?:the|that|this)\s+([a-z][\w-]{2,})'s\b|\b(?:that|this|ce|cet|cette)\s+([a-zà-ÿ][\w-]{2,})",
                     re.I)
TIME_NOUNS = frozenset("day days week weeks month months year years date dates time times hour hours period morning "
                       "evening night moment window jour jours semaine semaines mois année heure heures période matin "
                       "soir nuit".split())
# the previous answer's rows themselves: "how many of them", "among those", "of these", "parmi eux"
OF_THEM = re.compile(r"\b(?:of|among|amongst|from)\s+(?:them|those|these)\b|\bparmi (?:eux|elles|ceux|celles)\b|"
                     r"\bd'entre (?:eux|elles)\b|\b(?:those|these) (?:ones|rows|records)\b", re.I)


def subject_fields(question: str, fields: set[str]) -> set[str]:
    """The fields (of `fields`, lower case) the message names as its own subject: "that desk" -> {"desk"} when the
    previous queries filtered or grouped by DESK. A noun of time (that day, that week) names no subject; "of them"
    is the previous rows, not a subject of its own."""
    if OF_THEM.search(question or ""):
        return set()
    nouns = {(m.group(1) or m.group(2) or "").lower() for m in SUBJECT.finditer(question or "")}
    nouns = {n[:-1] if n.endswith("s") and len(n) > 3 else n for n in nouns if n not in TIME_NOUNS}
    found = set()
    for f in fields:
        words = [w for w in re.split(r"[^a-z0-9]+", f) if len(w) >= 3]
        if any(w == n or (len(n) >= 3 and w.startswith(n)) or (len(w) >= 4 and n.startswith(w))
               for n in nouns for w in words):
            found.add(f)
    return found


WORD = re.compile(r"(?<![\w-])([A-Za-zÀ-ÿ][\w-]{2,})(?![\w-])")


def field_values(tables: set[str]) -> dict[str, str]:
    """{a value, lower case: its field} of the keyword fields of these tables, as the dictionary learned them."""
    from superset import db

    from supagent.models import KObject

    out: dict[str, str] = {}
    for name, stats in (db.session.query(KObject.name, KObject.stats)
                        .filter(KObject.kind == "field", KObject.parent.in_(sorted(tables) or ["-"]),
                                KObject.gone_at.is_(None)).limit(2000)):
        values = (stats or {}).get("values") if isinstance(stats, dict) else None
        for v in values if isinstance(values, list) else []:
            text = str(v).strip()
            if len(text) >= 3 and not text[0].isdigit():
                out.setdefault(text.lower(), name)
    return out


def new_values(question: str, seen: list[str], queries: list[str],
               values_of: Any = None) -> list[str]:
    """The words of a follow-up that are values of a field of the tables the previous answer read, which neither
    that answer, its queries nor the earlier question used ("And the flash PnL?" after the official PnL: FLASH, a
    value of PNL_STATUS): it asks for another figure, which the chat does not hold: its own query."""
    from supagent.knowledge.rulecheck import _tables

    tables: set[str] = set()
    for q in queries:
        tables |= _tables(q or "")
    words = {m.group(1).lower(): m.group(1) for m in WORD.finditer(question or "")}
    if not tables or not words:
        return []
    values = (values_of or field_values)(tables)
    text = " ".join(list(seen) + list(queries)).lower()
    out = []
    for low, word in words.items():
        field = values.get(low)
        if field and not re.search(rf"(?<![\w-]){re.escape(low)}(?![\w-])", text):
            out.append(f"{word} ({field})")
    return out


def continues(question: str, follow: bool) -> bool:
    """The message goes on from the previous question (it refers to it, completes it, or refines it)."""
    return follow or bool(REFINES.search(question or ""))


def dropped(question: str, previous: list[str], current: list[str]) -> list[Any]:
    """The previous answer's conditions this answer's queries lost (see the module)."""
    from supagent.knowledge.conditions import sql_conditions
    from supagent.knowledge.rulecheck import _tables, grouped_by

    from supagent.knowledge.topics import BACK_TO

    if not previous or not current or REMOVES.search(question or "") or BACK_TO.search(question or ""):
        return []                                      # "Back to the failed jobs: ...": that question's scope
    tables = set().union(*(_tables(q) for q in current))
    used = {c.column.lower() for q in current for c in sql_conditions(q)}
    used |= {g.lower() for q in current for g in grouped_by(q)}
    asked = (question or "").lower()
    before = [q for q in previous if _tables(q) & tables]          # another table: another question
    named = {c.column.lower() for q in before for c in sql_conditions(q)} | \
        {g.lower() for q in before for g in grouped_by(q)}
    # "that desk's PnL": the desk as a whole; the desk a field the previous queries filtered or grouped by, or the
    # one this answer filters (after "which desk does the first one work on?": SELECT DISTINCT DESK, no filter on it)
    subject = subject_fields(question, named | used)
    out: dict[str, Any] = {}
    for q in before:
        for c in sql_conditions(q):
            col = c.column.lower()
            if col in used or col in out or "(" in col:
                continue                               # kept, or an aggregate's (HAVING)
            if subject and col not in subject:
                continue                               # narrower than the subject the message names
            if any(isinstance(v, str) and DATED.match(v) for v in c.values):
                continue                               # a time window: a follow-up may move it
            words = [w for w in re.split(r"[^a-z0-9]+", col) if len(w) >= 4]
            if col not in subject and (any(re.search(rf"\b{re.escape(w)}", asked) for w in words) or
                                       any(str(v).lower() in asked for v in c.values if len(str(v)) >= 2)):
                continue                               # the message names it: it changes it ("that desk": the same)
            out[col] = c
    return list(out.values())
