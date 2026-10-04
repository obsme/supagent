"""Mistakes a query shows by its own text (0.9.2), checked by code:

  - two result columns computed by the same aggregate under different names ("SUM(increase) AS errors_500,
    SUM(increase) AS total_requests"): one of them lost its own condition, and the answer then reads the total as the
    errors (the share next to it was right). Sent back before the query runs.
  - a time of day read from a time bucket: "At what time was it?" answered "04:00" from a query that grouped the
    samples by hour (the peak was at 04:26): the bucket's start is no moment. Sent back once after the answer.
  - a OR b AND c in a WHERE (0.9.4): AND binds first, c applies to b only; the other branch is counted without the
    team's conditions (stored queries: 3 such, all three answers wrong). Sent back before the query runs.
  - an average per day asked, AVG over the records computed (0.9.4): the daily totals averaged is meant. Sent back
    once before the query runs, both readings said.
"""

from __future__ import annotations

import re
from typing import Any, Callable

TIME_ASKED = re.compile(r"\b(?:at what time|what time|which time|when (?:was|did|exactly)|at which (?:hour|minute)|"
                        r"what hour|[àa] quelle heure|quand (?:[ée]tait|a)|what moment)\b", re.I)
TRUNC = re.compile(r"\b(?:DATE_TRUNC|date_trunc)\s*\(\s*'(hour|day|minute|week|month)'|"
                   r"\btime_bucket\s*\(\s*INTERVAL\s*'1\s*(hour|day)'|\b(?:toStartOf(Hour|Day))\b", re.I)
CLOCK = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])")


def _parse(sql: str) -> Any:
    import sqlglot

    for dialect in ("duckdb", None):
        try:
            return sqlglot.parse_one(sql, read=dialect) if dialect else sqlglot.parse_one(sql)
        except Exception:  # pylint: disable=broad-except   (a query sqlglot cannot read: no finding)
            continue
    return None


def same_aggregates(sql: str) -> list[tuple[str, str, str]]:
    """(alias, other alias, expression) for the columns of the outer SELECT that compute the same aggregate."""
    from sqlglot import exp

    tree = _parse(sql or "")
    if tree is None:
        return []
    select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
    if select is None:
        return []
    seen: dict[str, str] = {}
    out = []
    for col in select.expressions:
        alias = col.alias_or_name
        body = col.this if isinstance(col, exp.Alias) else col
        if not body.find(exp.AggFunc) or isinstance(body, exp.Star):
            continue
        key = body.sql(dialect="duckdb").lower().replace(" ", "")
        if key in seen and seen[key] != alias:
            out.append((seen[key], alias, body.sql(dialect="duckdb")))
        else:
            seen.setdefault(key, alias)
    return out


def duplicate_refusal(name: str, args: dict) -> str | None:
    if name != "execute_sql":
        return None
    req = args.get("request") if isinstance(args.get("request"), dict) else args
    found = same_aggregates(str((req or {}).get("sql") or ""))
    if not found:
        return None
    a, b, expr = found[0]
    return (f"tool error (not run: two columns, one expression): the columns {a} and {b} are both {expr}: they "
            f"give the same figure, so one of them lacks its own condition (a FILTER (WHERE ...) or a CASE WHEN ... "
            "THEN ... END inside the aggregate). Write each column with its own condition, or keep one column.")


def or_then_and(sql: str) -> str | None:
    """The conditions an OR without parentheses leaves to one of its branches: in WHERE a OR b AND c, AND binds
    first, so c applies to b only ("(one day) OR (the same weekday a week before) AND <the team's conditions>": the
    first day counted every row, the ones the team's rules leave out too). The text of that branch, or None."""
    from sqlglot import exp

    tree = _parse(sql)
    if tree is None:
        return None
    for clause in tree.find_all(exp.Where, exp.Having):
        if not isinstance(clause.this, exp.Or):
            continue
        branches, todo = [], [clause.this]
        while todo:
            node = todo.pop()
            if isinstance(node, exp.Or):
                todo += [node.this, node.expression]
            else:
                branches.append(node)
        for b in branches:
            if isinstance(b, exp.And):
                return b.sql(dialect="duckdb")
    return None


def or_and_refusal(name: str, args: dict) -> str | None:
    if name not in ("execute_sql", "export_excel", "chart_from_sql", "create_virtual_dataset", "save_sql_query"):
        return None
    req = args.get("request") if isinstance(args.get("request"), dict) else args
    branch = or_then_and(str((req or {}).get("sql") or ""))
    if not branch:
        return None
    return ("tool error (not run: AND before OR): in this WHERE, AND binds before OR, so the conditions joined with "
            f"AND after the last OR apply to that branch only ({branch[:200]}): the other branches are counted "
            "without them. Put the alternatives in parentheses: WHERE (a OR b) AND c. If one branch alone is meant, "
            "send this same call again unchanged.")


PER_DAY = re.compile(r"\b(?:average|mean|avg)\b[^?.]{0,60}\bper (?:day|business day|cob|working day)\b|"
                     r"\bdaily average\b|\baverage (?:daily|per day)\b|\bper day\b[^?.]{0,40}\bon average\b|"
                     r"\bon average\b[^?.]{0,60}\bper day\b|\bmoyenne\b[^?.]{0,40}\bpar jour\b|\bmoyenne journali", re.I)
DAY_STEP = re.compile(r"\bGROUP\s+BY\b[^;]*?(?:DATE|COB|DAY|_date|\bts\b|TRUNC|POSITION)|COUNT\s*\(\s*DISTINCT\b", re.I)


def per_day_refusal(question: str, name: str, args: dict) -> str | None:
    """"Average unexplained PnL per day" computed as AVG over the records (books, traders: several a day): 448.64
    for 2,691.84, though the answer counted the 19 days (stored: 3 such answers, all wrong; the 10 that summed per
    day first, all right). Sent back once before it runs, both readings said."""
    if name not in ("execute_sql", "export_excel") or not PER_DAY.search(question or ""):
        return None
    req = args.get("request") if isinstance(args.get("request"), dict) else args
    sql = str((req or {}).get("sql") or "")
    from sqlglot import exp

    tree = _parse(sql)
    if tree is None or not any(True for _ in tree.find_all(exp.Avg)) or DAY_STEP.search(sql):
        return None
    return ("tool error (not run: average per day): the question asks for an average per day, and this query "
            "averages the records themselves (AVG over every row: several a day, one per book, trader, order...). An "
            "average per day of a total is each day's total averaged over the days: SUM(x) / COUNT(DISTINCT the day), "
            "or AVG over a per-day SUM (GROUP BY the day). If the average of the records is meant, send this same "
            "call again unchanged.")


LOW_FIRST = {"min", "minimum", "lowest", "least", "smallest"}
HIGH_FIRST = {"max", "maximum", "highest", "largest", "biggest", "peak", "top"}


def extreme_mismatch(sql: str) -> str | None:
    """A column named for one extreme computed with the other: MAX(value) / 2^30 AS min_mem_gib for "the lowest
    available memory" (95.95 GiB, the highest, for 2.56). The alias's first word only (max_duration_min is the
    longest in minutes; ts_at_max an earliest time)."""
    from sqlglot import exp

    tree = _parse(sql)
    if tree is None:
        return None
    for a in tree.find_all(exp.Alias):
        first = re.split(r"[^a-z]+", (a.alias or "").lower())[0] if a.alias else ""
        aggs = {type(x) for x in a.this.find_all(exp.Max, exp.Min)}
        if len(aggs) != 1:
            continue
        if first in LOW_FIRST and aggs == {exp.Max}:
            return f"MAX(...) AS {a.alias}"
        if first in HIGH_FIRST and aggs == {exp.Min}:
            return f"MIN(...) AS {a.alias}"
    return None


def extreme_refusal(name: str, args: dict) -> str | None:
    if name not in ("execute_sql", "export_excel"):
        return None
    req = args.get("request") if isinstance(args.get("request"), dict) else args
    found = extreme_mismatch(str((req or {}).get("sql") or ""))
    if not found:
        return None
    return (f"tool error (not run: the other extreme): this query computes {found}: the name says one extreme and the "
            "aggregate gives the other (MAX for a minimum, MIN for a maximum). Use the aggregate the question asks "
            "for. If this is meant, send this same call again unchanged.")


def bucket_grain(sql: str) -> str | None:
    m = TRUNC.search(sql or "")
    if not m:
        return None
    grain = next(g for g in m.groups() if g)
    return grain.lower()


def time_from_bucket(question: str, answer: str, queries: list[str]) -> tuple[str, str] | None:
    """(the time the answer gives, the bucket of the queries) when a time of day was asked, every query that read
    times grouped them by hour or more, and the answer's time is a bucket's start (04:00 for an hour)."""
    if not TIME_ASKED.search(question or "") or not queries:
        return None
    grains = [bucket_grain(q) for q in queries]
    if not grains or any(g is None for g in grains):
        return None                                    # a query read the moments themselves
    grain = grains[-1]
    for h, mi in CLOCK.findall(answer or ""):
        if grain in ("hour", "day", "week", "month") and mi == "00":
            return f"{int(h):02d}:{mi}", grain
    return None


# ------------------------------------------------------------------------------------------------------------------
# A join that repeats rows: SUM(o.AMOUNT) over orders JOIN returns counts an order once per return (0.9.3, C).

def fanout_joins(sql: str) -> list[tuple[str, str, str, str]]:
    """(the table whose rows are summed, the joined table, its key in the join, how it is aggregated) for each
    aggregate (SUM, AVG, COUNT of rows, not DISTINCT) over a column of one table of a JOIN, for every other table
    joined on equal keys: if that table has several rows for a key, the summed rows repeat. Columns without their
    table's alias are left out (whose they are is not said)."""
    from sqlglot import exp

    tree = _parse(sql or "")
    if tree is None:
        return []
    out: list[tuple[str, str, str, str]] = []
    ctes = {c.alias_or_name for c in tree.find_all(exp.CTE)}       # (a WITH name is no table to probe)
    for select in tree.find_all(exp.Select):
        joins = select.args.get("joins") or []
        if not joins:
            continue
        frm = select.args.get("from") or select.args.get("from_")
        tables: dict[str, str] = {}
        for t in ([frm.this] if frm is not None else []) + [j.this for j in joins]:
            if isinstance(t, exp.Table) and t.name and t.name not in ctes:
                tables[(t.alias_or_name or t.name)] = t.name
        if len(tables) < 2:
            continue
        keys: dict[str, set[str]] = {}            # alias of a joined table -> its columns in the join conditions
        for j in joins:
            on = j.args.get("on")
            for eq in (on.find_all(exp.EQ) if on is not None else []):
                cols = [c for c in (eq.this, eq.expression) if isinstance(c, exp.Column) and c.table]
                if len(cols) == 2 and cols[0].table != cols[1].table:
                    for c in cols:
                        keys.setdefault(c.table, set()).add(c.name)
        first = next(iter(tables))
        for agg in select.find_all(exp.Sum, exp.Avg, exp.Count):
            if agg.find_ancestor(exp.Select) is not select:
                continue                           # (an aggregate of an inner query: its own joins)
            inner = agg.this
            if isinstance(agg, exp.Count) and (agg.args.get("distinct") or isinstance(inner, exp.Distinct)):
                continue                           # COUNT(DISTINCT key): repeats do not count twice
            cols = list(agg.find_all(exp.Column))
            if isinstance(agg, exp.Count) and (isinstance(inner, exp.Star) or not cols):
                owners = {first}                   # COUNT(*): the rows of the table queried first
            else:
                owners = {c.table for c in cols if c.table}
                if not owners or len(owners) != len({c.table for c in cols}) or "" in owners:
                    continue
            how = type(agg).__name__.upper()
            for owner in owners:
                for other, ks in keys.items():
                    if other != owner and other in tables and owner in tables:
                        out.append((tables[owner], tables[other], sorted(ks)[0], how))
    return list(dict.fromkeys(out))


def fanout_refusal(sql: str, repeated: "Callable[[str, str], int | None]") -> str | None:
    """The reason to send a query back, when one of its joins repeats the rows it sums: `repeated(table, key)` gives
    how many keys have several rows in that table (0: none; None: not known)."""
    for owner, other, key, how in fanout_joins(sql):
        try:
            n = repeated(other, key)
        except Exception:  # pylint: disable=broad-except   (not probed: no finding)
            n = None
        if n:
            return (f"tool error (not run: the join repeats rows): {other} has several rows for some {key} ({n} "
                    f"{key} values or more), so each row of {owner} is counted once per row of {other} with its "
                    f"{key}: {how} over the join counts it several times. Aggregate {other} first (a subquery grouped "
                    f"by {key}), or keep {owner} alone with \"{key}\" IN (SELECT \"{key}\" FROM \"{other}\" WHERE "
                    "...). If each of your rows has one match there, send this same call again unchanged.")
    return None
