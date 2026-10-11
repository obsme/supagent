"""Does the query that computed a term the team defined follow its definition? (0.9.2, agent.definition_check, off
until measured.)

"What was the net revenue of the week?" with the glossary's "net revenue: the amounts of the orders sold minus the
refunds of those orders" was computed three runs out of three with the refunds dated in the week, not the refunds of
the week's orders. Rules by code cannot read such a definition; one short LLM call can compare it with the query: the
term, its definition, the question and the queries of the answer, and one line back, OK or what differs. A
difference sends the answer back once, with that line.
"""

from __future__ import annotations

import re
from typing import Any

# a definition that says how to compute (a field, a value, arithmetic, a relation), not only what a word means
COMPUTABLE = re.compile(r"\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\b[A-Z]{3,}\b|%|(?i:\bminus\b|\bdivided by\b|\bper\b|"
                        r"\bratio\b|\bshare\b|\bof (?:those|these|the same|that|its|their)\b|\bonly\b|\bexcept\b|"
                        r"\bwhose\b)")      # (field and value names in capitals: case-sensitive)
MAX_TERMS = 2
# a definition relating rows of two sets: "the refunds of those orders" (not "for the same category": an alignment)
RELATED_ROWS = re.compile(r"\bof (?:those|these|the same|the said) ([a-z][a-z_]+)", re.I)
JUDGE = (
    "You check one thing: whether SQL queries compute a business term exactly as the team's glossary defines it. "
    "Compare every part of the definition with the query that computes the term: each condition (a status, a "
    "channel, a value) and each relation it states (\"of those orders\" = the same orders as the rest of the "
    "definition, linked by their key; \"divided by\" = the ratio). Rounding, column names, extra columns, the order "
    "of the rows and the team's usual filters do not matter. Answer with ONE line: OK when the query follows the "
    "definition, or DIFFERS: <the part of the definition the query does not follow, and what it does instead>.")


def computed_terms(question: str) -> list[dict[str, Any]]:
    """The glossary terms of the question whose definition says how to compute them (at most MAX_TERMS)."""
    from supagent.knowledge.glossary import found

    return [t for t in found(question) if COMPUTABLE.search(t.get("definition") or "")][:MAX_TERMS]


def judge(llm: Any, term: dict[str, Any], question: str, queries: list[str]) -> str | None:
    """The line that says what differs, or None (OK, or no clear answer)."""
    shown = "\n\n".join(q.strip()[:1500] for q in queries[-4:])
    messages = [{"role": "system", "content": JUDGE},
                {"role": "user", "content": f"Term: {term['term']}\nDefinition: {term['definition'][:900]}\n\n"
                                            f"Question: {question[:400]}\n\nQueries run:\n{shown}"}]
    msg = llm.chat(messages, tools=None, max_tokens=160)
    text = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
    m = re.search(r"\bDIFFERS?\s*:\s*(.+)", text, re.I | re.S)
    if not m or re.match(r"^\W*OK\b", text, re.I):
        return None
    return " ".join(m.group(1).split())[:400]


def unlinked(question: str, queries: list[str]) -> tuple[dict[str, Any], str] | None:
    """(the term, what differs) when a term of the question is defined with a relation between rows ("the refunds of
    those orders") and the answer's queries read the tables only apart: no query reads two of them with a JOIN or a
    key IN (SELECT ...), so the second part has rows of its own (the refunds dated that week), not those of the
    first. By code, no LLM call (agent.definition_links)."""
    from supagent.knowledge.glossary import found
    from supagent.knowledge.rulecheck import _tables

    low = (question or "").lower()
    terms = [t for t in found(question) if RELATED_ROWS.search(t.get("definition") or "")
             and any(re.search(rf"(?<![a-z0-9_]){re.escape(n.strip().lower())}(?![a-z0-9_])", low)
                     for n in str(t.get("term") or "").split("/") if len(n.strip()) >= 2)]
    #                                                   (the term itself said: "the gross revenue" is not it)
    per = [(q, _tables(q)) for q in queries or [] if q and re.search(r"\bSELECT\b", q, re.I)]
    tables: set[str] = set().union(*(ts for _q, ts in per)) if per else set()
    if not terms or len(tables) < 2:
        return None
    restricted = None
    for q, ts in per:
        if len(ts) >= 2 and re.search(r"\bJOIN\b|\bIN\s*\(\s*SELECT\b|\bEXISTS\s*\(", q, re.I):
            cut = restricted_total(q) if _share_join_on() else None
            if cut:                                      # (0.10.7) linked, but the total kept only its rows with a
                restricted = restricted or cut           # part ("the sales minus the refunds of those orders" as one
                continue                                 # INNER JOIN: 0 when every refund is its order's amount)
            return None                                  # linked in a query
    term = terms[0]
    phrase = RELATED_ROWS.search(term["definition"]).group(0)
    if restricted:
        return term, (f"your query subtracts {restricted[1]} from {restricted[0]} through an INNER JOIN: the total is "
                      f"then only the {restricted[0]} rows that have a {restricted[1]} row. Compute the total over all "
                      f"its rows (a query of its own, or FROM {restricted[0]} LEFT JOIN {restricted[1]}), the part of "
                      "those rows through the join with the total's conditions, then subtract")
    return term, (f"your queries read {' and '.join(sorted(tables))} apart, each with its own conditions, while the "
                  f"definition relates them: \"{phrase}\" are the rows of the first part, linked by their key "
                  "(the period goes on the first part only); a total minus such a part is the total over all its rows "
                  "(a query of its own) minus the part read through the JOIN on the key with the total's conditions: "
                  "one INNER JOIN for both keeps only the rows that have a part")


# (0.10.7) a condition taking several values of one field: F IN ('A', 'B') (not NOT IN), F = 'A' OR F = 'B'
IN_LIST = re.compile(r"(?<![\w\"`])[\"`]?([A-Za-z_][A-Za-z0-9_]*)[\"`]?\s+(NOT\s+)?IN\s*\(\s*('[^'\n]*'(?:\s*,\s*'[^'\n]*')*)"
                     r"\s*\)", re.I)
OR_CHAIN = re.compile(r"(?<![\w\"`])([\"`]?)([A-Za-z_][A-Za-z0-9_]*)\1\s*=\s*'[^'\n]*'(?:\s+OR\s+(?:[A-Za-z_]\w*\.)?\1\2\1"
                      r"\s*=\s*'[^'\n]*')+", re.I)
ONE_VALUE = re.compile(r"(?<![\w\"`])[\"`]?([A-Za-z_][A-Za-z0-9_]*)[\"`]?\s*=\s*'([^'\n]*)'", re.I)


def _said_in(value: str, definition: str) -> bool:
    """Does the definition name this value? As a word, its case aside ("shipments dispatched" names 'DISPATCHED',
    CLOSED_WON is "closed won"); a value under 4 letters only as written ("the EU requests", not "us")."""
    norm = " ".join(re.sub(r"[_\-]+", " ", value).split())
    if not norm:
        return False
    if len(re.sub(r"[^A-Za-z]", "", norm)) < 4:
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(norm)}(?![A-Za-z0-9])", definition.replace("_", " ")) is not None
    text = re.sub(r"[_\-]+", " ", definition.lower())
    return re.search(rf"(?<![a-z0-9]){re.escape(norm.lower())}(?![a-z0-9])", text) is not None


def _conditions(sql: str) -> list[tuple[str, list[str]]]:
    """The values each condition of a query takes: [(field, [values])], NOT IN left out."""
    out = []
    spans = []
    for m in IN_LIST.finditer(sql):
        spans.append(m.span())
        if not m.group(2):
            out.append((m.group(1), re.findall(r"'([^'\n]*)'", m.group(3))))
    for m in OR_CHAIN.finditer(sql):
        spans.append(m.span())
        out.append((m.group(2), re.findall(r"=\s*'([^'\n]*)'", m.group(0))))
    for m in ONE_VALUE.finditer(sql):
        if not any(a <= m.start() < b for a, b in spans):
            out.append((m.group(1), [m.group(2)]))
    return out


def _terms_said(text: str) -> list[dict[str, Any]]:
    from supagent.knowledge.glossary import found

    low = (text or "").lower()
    return [t for t in found(text) if any(re.search(rf"(?<![a-z0-9_]){re.escape(n.strip().lower())}(?![a-z0-9_])", low)
                                          for n in str(t.get("term") or "").split("/") if len(n.strip()) >= 2)]


def widened(question: str, queries: list[str], intent: str | None = None) -> tuple[dict[str, Any], str] | None:
    """(the term, what differs) when a term of the question is defined with some values of a field ("the shipments
    dispatched") and the answer's last query that conditions on them takes other values of that field too
    (STAGE IN ('DISPATCHED', 'PACKED'): a wider rule of the team, "shipments count when DISPATCHED or PACKED", put
    in place of the definition). The terms the message itself says, else those of the question as understood ("And
    in week 6?"). By code, no LLM call (agent.definition_links)."""
    terms = _terms_said(question) or (_terms_said(intent) if intent and intent != question else [])
    selects = [q for q in queries or [] if q and re.search(r"\bSELECT\b", q, re.I)]
    # a value another term of the question or the question itself names is asked ("the VaR and the stressed VaR")
    asked = "\n".join([question or "", intent or ""] + [t.get("definition") or "" for t in terms])
    for term in terms:
        definition = term.get("definition") or ""
        if not COMPUTABLE.search(definition):          # says what a word means, not which rows it counts
            continue
        for q in reversed(selects):                    # the last query on the defined values decides (a query run
            said = [(f, vs) for f, vs in _conditions(q)   # again with the definition makes up for the first one)
                    if any(_said_in(v, definition) for v in vs)]
            if not said:
                continue
            for f, vs in said:
                extra = [v for v in vs if not _said_in(v, asked)]
                if extra:
                    named = [v for v in vs if _said_in(v, definition)]
                    return term, (f"your condition on {f} takes {', '.join(repr(v) for v in vs)}: the definition names "
                                  f"{', '.join(repr(v) for v in named)}, not {', '.join(repr(v) for v in extra)} (a "
                                  "wider rule of the team does not change what this term counts); keep only the "
                                  "values the definition names")
            break
    return None


# "what share of that week's sales was refunded?": a part of those rows that something happened to, counted within
# them ("what share of all the orders is that?" compares two counts: not this)
SHARE_OF = re.compile(r"\b(?:what|which)\s+(?:share|part|percentage|proportion|fraction|portion)\s+of\b[^?]{0,80}?"
                      r"\b(?:was|were|got|had been|have been|has been)\s+\w+(?:ed|en)\b|"
                      r"\bquel(?:le)?\s+(?:part|pourcentage|proportion)\b[^?]{0,80}?\b(?:a|ont|a été|ont été)\s+"
                      r"\w+(?:é|ée|és|ées)\b", re.I)


def unlinked_share(question: str, queries: list[str]) -> str | None:
    """What differs, when the question asks for a share of a set of rows and the queries read the part and the
    whole from different tables apart (the refunds dated that week over the sales of that week): the part must be
    counted within the same rows (its key in them)."""
    from supagent.knowledge.rulecheck import _tables

    if not SHARE_OF.search(question or ""):
        return None
    per = [(q, _tables(q)) for q in queries or [] if q and re.search(r"\bSELECT\b", q, re.I)]
    tables: set[str] = set().union(*(ts for _q, ts in per)) if per else set()
    if len(tables) < 2:
        return None
    for q, ts in per:
        if len(ts) >= 2 and re.search(r"\bJOIN\b|\bIN\s*\(\s*SELECT\b|\bEXISTS\s*\(", q, re.I):
            whole = restricted_whole(q) if _share_join_on() else None
            if whole:                                    # joined, but the whole kept only the rows with a part
                return (f"your query divides by the rows of {whole[0]} through an INNER JOIN with {whole[1]}: the whole "
                        f"is then only the {whole[0]} rows that have a {whole[1]} row (a share near 100 % is the sign). "
                        f"Count the whole over all its rows (FROM {whole[0]} LEFT JOIN {whole[1]}, the part counted "
                        "from the joined rows, or the whole in a query of its own), then the share")
            return None                                  # the part read within the whole's rows
    return (f"the question asks for a share of a set of rows, and your queries read {' and '.join(sorted(tables))} "
            "apart, each with its own conditions: the part must be counted within the same rows (linked to them by "
            "their key), not over its own period")


def _share_join_on() -> bool:
    """agent.share_join_check (0.9.7): a share over an inner join of the part and the whole is sent back."""
    try:
        from supagent import settings

        return bool(settings.get("agent.share_join_check"))
    except Exception:  # pylint: disable=broad-except   (no app: as the default)
        return True


def restricted_whole(sql: str) -> tuple[str, str] | None:
    """(the whole's table, the part's table) when a share is computed as an aggregate of one table over an aggregate
    of another joined to it by INNER joins only: the whole keeps only its rows that have a part (the refunds of a
    week over the sales of the refunded orders: 100 %). Columns without their table: not judged."""
    pair = _inner_pair(sql, "Div")                       # (the part's, the whole's)
    return (pair[1], pair[0]) if pair else None


def restricted_total(sql: str) -> tuple[str, str] | None:
    """(0.10.7) (the total's table, the part's table) when a total minus a part of it is computed as an aggregate of
    one table minus an aggregate of another joined to it by INNER joins only ("the sales minus the refunds of those
    orders" as SUM(o.amount) - SUM(r.refund) FROM orders JOIN returns): the total keeps only its rows that have a part
    (0 when every refund is its order's whole amount)."""
    return _inner_pair(sql, "Sub")


def _inner_pair(sql: str, op: str) -> tuple[str, str] | None:
    """(the tables of the left operand, of the right one) of a division or subtraction (`op`) between aggregates of
    different tables in a SELECT whose joins are all INNER; None otherwise (columns without their table: not
    judged)."""
    import sqlglot
    from sqlglot import exp

    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:  # pylint: disable=broad-except
        return None
    for sel in tree.find_all(exp.Select):
        joins = sel.args.get("joins") or []
        if not joins or any((j.side or "").upper() in ("LEFT", "RIGHT", "FULL") for j in joins):
            continue
        names = {(t.alias or t.name): t.name for t in sel.find_all(exp.Table)}

        def tables_of(node: Any) -> set[str] | None:
            if next(node.find_all(exp.AggFunc), None) is None:
                return None
            ts = {c.table for c in node.find_all(exp.Column)}
            return None if not ts or "" in ts else {names.get(t, t) for t in ts}

        for node in sel.find_all(getattr(exp, op)):
            left, right = tables_of(node.this), tables_of(node.expression)
            if left and right and not left & right:
                return ", ".join(sorted(left)), ", ".join(sorted(right))
    return None
