"""A value the question names that the answer's queries never use (the classic pipeline; the governed plan has
its own check). "How many web orders did we sell on 23 September?" counted over every channel (384 instead of
223, the retail lab): the question names WEB, a value of CHANNEL in the orders it read, and no query had a
condition with it nor grouped by CHANNEL. Named = written as the data writes it, a code-like value (digits, _ or -)
in any case, or a value in any case just before the table's subject or its field's name ("web orders", "web
channel" in an orders index); "per
channel" asks for every value, "UAT included" for it with the others. A value the question leaves out ("cancelled
trades left out", "excluding UAT", "hors UAT") is met by any condition on its field (<> 'CANCELLED', or IN of the
values kept): the check once sent a right answer back asking for = 'CANCELLED', and the model then answered about
the cancelled trades."""

from __future__ import annotations

import re

from superset import db

PER = re.compile(r"\b(?:per|by|for each|each|every|which|par|pour chaque|chaque)\s+((?:[a-zA-Z][\w-]*\s+){0,2}"
                 r"[a-zA-Z][\w-]*)", re.I)
INCLUDED_AFTER = re.compile(r"^\W*(?:\w+\s+){0,2}?(?:included|including|inclus\w*|too|as well|also)\b", re.I)
INCLUDED_BEFORE = re.compile(r"\b(?:including|incl\.?|y compris)\s+(?:\w+\s+)?$", re.I)   # not "with": a filter
EXCLUDED_AFTER = re.compile(r"^\W*(?:[\w-]+\s+){0,2}?(?:left\s+out|excluded|set\s+aside|put\s+aside|aside|not\s+counted|"
                            r"exclu\w*|mis\w*\s+de\s+c[oô]t[ée]|mis\w*\s+[àa]\s+part|[ée]cart[ée]\w*)\b", re.I)
EXCLUDED_BEFORE = re.compile(r"\b(?:excluding|exclude|except|without|other\s+than|apart\s+from|leaving\s+out|leave\s+out|"
                             r"minus|ignoring|ignore|not|non|no|hors|sans|sauf|except[ée]s?|autres?\s+que|pas)\s+"
                             r"(?:the\s+|any\s+|les?\s+|la\s+|des\s+|d'|l')?(?:[\w-]+\s+)?$", re.I)


def before_noun(question: str, value: str, nouns: set[str]) -> re.Match | None:
    """The value in any case just before one of these nouns (the table's subject, the value's own field): "test
    orders", "web channel"."""
    from supagent.knowledge.rulecheck import _stem

    for m in re.finditer(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])(?=\s+([a-z]+))", question, re.I):
        if _stem(m.group(1).lower()) in nouns:
            return m
    return None


def nouns_of(table: str, field: str) -> set[str]:
    """The words a value may be said before: its table's subject (orders) and its field's name (channel)."""
    from supagent.knowledge.rulecheck import _stem

    return {_stem(w) for w in re.split(r"[^a-z0-9]+", f"{table} {field}".lower()) if len(w) >= 3}


def included(question: str, m: re.Match) -> bool:
    """"UAT included", "including UAT": the value is counted with the others, not alone."""
    return bool(INCLUDED_AFTER.match(question[m.end():]) or INCLUDED_BEFORE.search(question[:m.start()]))


def excluded(question: str, m: re.Match) -> bool:
    """"cancelled trades left out", "excluding UAT", "hors UAT": the question wants the value left out."""
    return bool(EXCLUDED_AFTER.match(question[m.end():]) or EXCLUDED_BEFORE.search(question[:m.start()]))


def left_out(question: str, value: str) -> bool:
    """Whether the question names this value to leave it out (the check's advice is then <>, not =)."""
    for m in re.finditer(r"(?<![\w-])" + re.escape(value) + r"(?![\w-])", question or "", re.I):
        if excluded(question, m):
            return True
    return False


def conditioned(field: str, sqls: list[str]) -> bool:
    """A query of the answer has a condition on this field (=, <>, IN, NOT IN, LIKE, IS)."""
    pat = re.compile(r"(?<![\w@])\"?" + re.escape(field) + r"\"?\s*(?:=|<>|!=|\bNOT\s+IN\b|\bIN\b|\bNOT\s+LIKE\b|"
                     r"\bLIKE\b|\bIS\b)", re.I)
    return any(pat.search(q or "") for q in sqls)


def unused(question: str, sqls: list[str]) -> list[tuple[str, str, str]]:
    """[(the value, its field, its table)] the question names in the tables the queries read, that no query
    writes (as a quoted literal) nor groups by its field."""
    from supagent.knowledge.rulecheck import _tables, grouped_by
    from supagent.models import KObject

    sqls = [q for q in sqls if q]
    if not sqls or not question:
        return []
    tables = set().union(*(_tables(q) for q in sqls))
    if not tables:
        return []
    said = " ".join(sqls).lower()
    grouped = set().union(*(grouped_by(q) for q in sqls))
    per = [m.span() for m in PER.finditer(question)]
    out: list[tuple[str, str, str]] = []
    rows = db.session.query(KObject).filter(KObject.kind.in_(("field", "label")), KObject.parent.in_(list(tables)),
                                            KObject.gone_at.is_(None)).all()
    names = {o.name.lower() for o in rows}
    for o in rows:
        words = names | {w for w in re.split(r"[^a-z0-9]+", o.parent.lower()) if w}
        if o.name in grouped or o.name.lower() in {g.lower() for g in grouped}:
            continue                                     # per that field: every value
        for v in ((o.stats or {}).get("values") or [])[:300]:
            v = str(v)
            if len(v) < 2 or re.fullmatch(r"[\d.:+-]+", v) or v.lower() in words:
                continue
            code_like = bool(re.search(r"[\d_-]", v))
            m = re.search(r"(?<![\w-])" + re.escape(v) + r"(?![\w-])", question, re.I if code_like else 0)
            if m is None and not code_like:              # "web orders", "web channel": before the subject or field
                m = before_noun(question, v, nouns_of(o.parent, o.name))
            if m is None or any(a <= m.start() < b for a, b in per) or included(question, m):
                continue
            low = v.lower()
            if f"'{low}'" in said or f'"{low}"' in said:
                continue
            if excluded(question, m) and conditioned(o.name, sqls):
                continue                                 # left out: any condition on its field keeps it out
            out.append((v, o.name, o.parent))
    return list(dict.fromkeys(out))
