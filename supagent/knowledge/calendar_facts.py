"""The calendar facts of the days an investigation looks at, when the team's own knowledge speaks of them (candidate
C of 0.9.3).

"The night batch is late, the jobs are longer than usual: why?" on the Monday after the third Friday of the month:
the business day before was the third Friday (a monthly expiry, a month-end close, a payroll day...), and the team
wrote that such a day holds more of the work. Nothing in the data says it; the team's documents and notes do. The
facts of a day (the n-th weekday of its month, the last weekday of its month, the last or first business day of the
month, of the quarter, of the year) are written the way a team writes them, the knowledge is searched with them,
and a piece of knowledge that literally says one of those phrases is given with the question, with the day. The
model decides what it explains: a day the team documented, with the effect it documented, is the explanation.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Callable

ORDINALS = {1: ("first", "1st"), 2: ("second", "2nd"), 3: ("third", "3rd"), 4: ("fourth", "4th"), 5: ("fifth", "5th")}
MONTH_END = ("month end", "month-end", "end of month", "end of the month", "last business day of the month",
             "fin de mois")
QUARTER_END = ("quarter end", "quarter-end", "end of quarter", "end of the quarter", "fin de trimestre")
YEAR_END = ("year end", "year-end", "end of year", "end of the year", "fin d'ann")
MONTH_START = ("first business day", "start of the month", "start of month", "month start", "début de mois")
MAX_DAYS = 3
MAX_LINES = 3


def _business(day: dt.date, step: int) -> dt.date:
    """The business day (Monday to Friday) after (step 1) or before (step -1) a day."""
    d = day + dt.timedelta(days=step)
    while d.weekday() >= 5:
        d += dt.timedelta(days=step)
    return d


def facts(day: dt.date) -> list[tuple[str, tuple[str, ...]]]:
    """(what the day is, the phrases a team writes it with), lower case."""
    weekday = day.strftime("%A").lower()
    n = (day.day - 1) // 7 + 1
    word, short = ORDINALS[n]
    out: list[tuple[str, tuple[str, ...]]] = [
        (f"the {word} {weekday.capitalize()} of {day:%B}", (f"{word} {weekday}", f"{short} {weekday}"))]
    if (day + dt.timedelta(days=7)).month != day.month:
        out.append((f"the last {weekday.capitalize()} of {day:%B}", (f"last {weekday}",)))
    if day.weekday() < 5 and _business(day, 1).month != day.month:
        out.append(("the last business day of the month", MONTH_END))
        if day.month in (3, 6, 9, 12):
            out.append(("the last business day of the quarter", QUARTER_END))
        if day.month == 12:
            out.append(("the last business day of the year", YEAR_END))
    if day.weekday() < 5 and _business(day, -1).month != day.month:
        out.append(("the first business day of the month", MONTH_START))
    return out


def days_of(question: str, today: dt.date) -> list[dt.date]:
    """The days the question is about (named, else today), each with the business day before it (what a night
    batch computes: the position date of D-1)."""
    from supagent.knowledge.period import days_named

    named = list(days_named(question or "", today)) or [today]
    out: list[dt.date] = []
    for d in named[:2]:
        for x in (d, _business(d, -1)):
            if x not in out:
                out.append(x)
    return out[:MAX_DAYS]


def documented(question: str, today: dt.date, search: Callable[[str], list[dict[str, Any]]] | None = None) -> list[str]:
    """Lines: a day of the question, its calendar fact, and the knowledge that literally says that fact."""
    if search is None:
        from supagent.knowledge.search import search as found

        def search(q: str) -> list[dict[str, Any]]:
            return found(q, k=6, rerank=False)

    lines: list[str] = []
    for day in days_of(question, today):
        for fact, phrases in facts(day):
            try:
                hits = search(" ".join(phrases[:2]))
            except Exception:  # pylint: disable=broad-except   (no knowledge store: nothing to say)
                return lines
            said = []
            for h in hits or []:
                text = " ".join(str(h.get(k) or "") for k in ("title", "text")).lower()
                m = next((p for p in phrases if re.search(rf"(?<![a-z]){re.escape(p)}(?![a-z])", text)), None)
                if m:
                    at = text.find(m)
                    said.append(f"{str(h.get('title') or h.get('kind') or 'knowledge')[:80]}: "
                                f"\"...{text[max(0, at - 120):at + 160].strip()}...\"")
            if said:
                lines.append(f"{day:%A %d %B %Y} is {fact}; the team's knowledge speaks of such a day: "
                             + " | ".join(said[:2]))
            if len(lines) >= MAX_LINES:
                return lines
    return lines


def note(lines: list[str]) -> str:
    return ("(The calendar of the days looked at, as the team wrote it: " + " ".join(f"{x}." for x in lines)
            + " A day the team documented, with the effect it documented, is the explanation: check that the "
            "effect is the one documented.)")
