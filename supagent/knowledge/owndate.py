"""(0.10.12) The rows linked to a period's rows, taken by their own date. "What was the net revenue of the week?",
defined in the chat as the week's sold orders minus the refunds of those orders: the answer took the refunds by their
own return date in the week, and the orders by their order date: two different sets of orders (refunds of other weeks'
orders counted, later refunds of this week's orders left out). Found only on the query whose results give the answer's
figures (a query tried along the way and dropped is not a reading of the answer): a table B read with a period on
its own date column, while a table A that B links to by a shared key is read, in that query or another of the answer,
with the same period on A's date column."""
from __future__ import annotations

import json
import re
from typing import Any, Callable

ID_LIKE = re.compile(r"(?:^|_)(?:id|key|ref|uuid|no|num|number)$|id$", re.I)
DATE_LIT = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")
NUMBER = re.compile(r"(?<![\w.])-?\d{1,3}(?:[,  ]\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.,])-?\d+(?:\.\d+)?(?![\w])")
COMBINED = re.compile(r"\b(?:net|share|ratio|rates?|percent\w*|proportion|minus|after|less|of (?:those|these|them)|"
                      r"their|per|refunded|returned)\b|%|\bnets?\b|\bpart\b|\bpourcentage\b|\bpart des?\b", re.I)
TIES = re.compile(r"\b(?:of|for|from|on)\s+(?:those|these|the same|them)\b|\btheir\s+(?:own\s+)?\w+s\b|"
                  r"\b(?:de|des|sur)\s+ces\b", re.I)


def _parse(sql: str):
    try:
        import sqlglot

        return sqlglot.parse_one(sql, read="duckdb")
    except Exception:  # pylint: disable=broad-except   (a query it cannot read: no finding)
        return None


def _aliases(tree) -> dict[str, str]:
    from sqlglot import exp

    out: dict[str, str] = {}
    for t in tree.find_all(exp.Table):
        if t.name:
            out[(t.alias_or_name or t.name).lower()] = t.name
            out[t.name.lower()] = t.name
    return out


def _table_of(col, aliases: dict[str, str], tables: list[str]) -> str | None:
    q = (col.table or "").lower()
    if q:
        return aliases.get(q)
    return tables[0] if len(tables) == 1 else None


def date_conditions(sql: str) -> dict[tuple[str, str], set[str]]:
    """{(table, date column): the dates its conditions compare it with} in one query (WHERE and JOIN ... ON)."""
    from sqlglot import exp

    tree = _parse(sql)
    if tree is None:
        return {}
    aliases = _aliases(tree)
    tables = sorted({t.name for t in tree.find_all(exp.Table) if t.name})
    out: dict[tuple[str, str], set[str]] = {}

    def note(col, lit) -> None:
        m = DATE_LIT.match(str(lit.this)) if isinstance(lit, exp.Literal) and lit.is_string else None
        table = _table_of(col, aliases, tables) if isinstance(col, exp.Column) else None
        if m and table:
            out.setdefault((table, col.name), set()).add(m.group(1))

    for node in tree.find_all(exp.GT, exp.GTE, exp.LT, exp.LTE, exp.EQ):
        a, b = node.left, node.right
        if isinstance(a, exp.Column):
            note(a, b)
        else:
            note(b, a)
    for node in tree.find_all(exp.Between):
        for lit in (node.args.get("low"), node.args.get("high")):
            note(node.this, lit)
    return out


def join_keys(sql: str) -> set[tuple[str, str, str]]:
    """{(table, other table, column)}: a condition table.col = other.col with the same column name."""
    from sqlglot import exp

    tree = _parse(sql)
    if tree is None:
        return set()
    aliases = _aliases(tree)
    tables = sorted({t.name for t in tree.find_all(exp.Table) if t.name})
    out = set()
    for node in tree.find_all(exp.EQ):
        a, b = node.left, node.right
        if isinstance(a, exp.Column) and isinstance(b, exp.Column) and a.name.lower() == b.name.lower():
            ta, tb = _table_of(a, aliases, tables), _table_of(b, aliases, tables)
            if ta and tb and ta != tb:
                out.add((ta, tb, a.name))
                out.add((tb, ta, a.name))
    return out


def _numbers(text: str) -> set[float]:
    out = set()
    for x in NUMBER.findall(text or ""):
        try:
            v = float(re.sub(r"[,  ]", "", x))
        except ValueError:
            continue
        if abs(v) >= 100:
            out.add(round(v, 2))
    return out


def _gives(result: Any, answer_numbers: set[float]) -> bool:
    """The query's results hold a figure of the answer (100 or more, to the cent or rounded to the unit)."""
    text = result if isinstance(result, str) else json.dumps(result, default=str)
    for v in _numbers(text):
        for w in answer_numbers:
            if abs(v - w) <= max(0.01, abs(v) * 0.0005) or round(v) == w:
                return True
    return False


def _owner(key: str, a: str, b: str) -> tuple[str, str]:
    """(the table the key names, the other): ORDER_ID belongs to the orders, not to their returns."""
    stem = re.sub(r"(?:^|_)(?:id|key|ref|uuid|no|num|number)$|id$", "", key, flags=re.I).strip("_").lower()
    if stem and stem in b.lower() and stem not in a.lower():
        return b, a
    return a, b


def reading(trace: list[dict], answer: str, question: str,
            fields_of: Callable[[str], set[str]] | None = None) -> tuple[str, str, str, str, str] | None:
    """(B, B's date column, the key, A, A's date column) when the answer's figures come from reading B by its own
    date over the period that they read A by A's date (in one query, or in two that both give its figures), B
    linking to A by the key; else None. A query tried along the way whose results the answer does not give is not
    a reading of the answer."""
    if not COMBINED.search(question or ""):
        return None
    queries: list[tuple[str, Any]] = []
    for t in trace or []:
        if t.get("status") != "done" or (t.get("called") or t.get("tool")) not in ("execute_sql",):
            continue
        args = t.get("args") or {}
        req = args.get("request") if isinstance(args.get("request"), dict) else args
        sql = (req or {}).get("sql") if isinstance(req, dict) else None
        if sql:
            queries.append((sql, t.get("result")))
    wanted = _numbers(answer)
    if not queries or not wanted:
        return None
    giving = [i for i, (_sql, result) in enumerate(queries) if _gives(result, wanted)]
    conds = {i: date_conditions(queries[i][0]) for i in giving}
    keys = set().union(*(join_keys(sql) for sql, _r in queries))
    for i in giving:
        for j in giving:
            for (x, dx), x_dates in conds[i].items():
                for (y, dy), y_dates in conds[j].items():
                    if x == y or dx.lower() == dy.lower() or min(x_dates) != min(y_dates):
                        continue
                    key = next((k for (p, q, k) in keys if p == x and q == y), None)
                    if key is None and fields_of is not None:
                        shared = {f for f in fields_of(x) & fields_of(y) if ID_LIKE.search(f)}
                        key = sorted(shared)[0] if shared else None
                    if key:
                        a, b = _owner(key, x, y)
                        da, db = (dx, dy) if a == x else (dy, dx)
                        return b, db, key, a, da
    return None


def ties(texts: list[str]) -> bool:
    """A definition in the chat takes the linked rows of the period's rows ("the refunds of those orders")."""
    return any(TIES.search(t or "") for t in texts)
