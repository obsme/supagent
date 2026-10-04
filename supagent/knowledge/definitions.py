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
    for q, ts in per:
        if len(ts) >= 2 and re.search(r"\bJOIN\b|\bIN\s*\(\s*SELECT\b|\bEXISTS\s*\(", q, re.I):
            return None                                  # linked in a query
    term = terms[0]
    phrase = RELATED_ROWS.search(term["definition"]).group(0)
    return term, (f"your queries read {' and '.join(sorted(tables))} apart, each with its own conditions, while the "
                  f"definition relates them: \"{phrase}\" are the rows of the first part, linked by their key "
                  "(the period goes on the first part only)")


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
            return None                                  # the part read within the whole's rows
    return (f"the question asks for a share of a set of rows, and your queries read {' and '.join(sorted(tables))} "
            "apart, each with its own conditions: the part must be counted within the same rows (linked to them by "
            "their key), not over its own period")
