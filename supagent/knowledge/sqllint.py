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

import json
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


def _and_leaves(node: Any) -> list:
    """The conditions of an AND chain, in order."""
    from sqlglot import exp

    return _and_leaves(node.this) + _and_leaves(node.expression) if isinstance(node, exp.And) else [node]


def grouped_alternatives(sql: str) -> str | None:
    """(0.10.7) The WHERE meant, when every alternative of an OR is written in parentheses and the conditions of all
    of them are joined with AND after the last one (or before the first): "(day 1) OR (day 2) AND <filters>" means
    "((day 1) OR (day 2)) AND <filters>": the first day's rows went unfiltered, and the answer took that total over
    the right one it had just read (resent unchanged, the query ran). The condition to write, or None."""
    from sqlglot import exp

    tree = _parse(sql)
    if tree is None:
        return None
    for clause in tree.find_all(exp.Where):
        if not isinstance(clause.this, exp.Or):
            continue
        branches, todo = [], [clause.this]
        while todo:                                    # the branches in order (left to right)
            node = todo.pop(0)
            if isinstance(node, exp.Or):
                todo = [node.this, node.expression] + todo
            else:
                branches.append(node)
        if len(branches) < 2:
            continue
        first, last = _and_leaves(branches[0]), _and_leaves(branches[-1])
        middle = branches[1:-1]
        if not all(isinstance(b, exp.Paren) for b in middle):
            continue
        sql_of = lambda n: n.sql(dialect="duckdb")  # noqa: E731
        if len(first) == 1 and isinstance(first[0], exp.Paren) and len(last) > 1 and isinstance(last[0], exp.Paren):
            alts = [first[0]] + middle + [last[0]]     # (a) OR (b) AND c
            return f"({' OR '.join(sql_of(a) for a in alts)}) AND " + " AND ".join(sql_of(c) for c in last[1:])
        if len(last) == 1 and isinstance(last[0], exp.Paren) and len(first) > 1 and isinstance(first[-1], exp.Paren):
            alts = [first[-1]] + middle + [last[0]]    # c AND (a) OR (b)
            return " AND ".join(sql_of(c) for c in first[:-1]) + f" AND ({' OR '.join(sql_of(a) for a in alts)})"
    return None


def or_and_refusal(name: str, args: dict) -> str | None:
    if name not in ("execute_sql", "export_excel", "chart_from_sql", "create_virtual_dataset", "save_sql_query"):
        return None
    req = args.get("request") if isinstance(args.get("request"), dict) else args
    sql = str((req or {}).get("sql") or "")
    meant = grouped_alternatives(sql)
    if meant:                                          # (0.10.7) never run as written: the meaning is plain
        return ("tool error (not run: AND before OR, the alternatives in parentheses): in this WHERE, AND binds "
                "before OR, so the conditions joined with AND apply to one alternative only and the other is counted "
                f"without them. Write the WHERE as: {meant[:900]}")
    branch = or_then_and(sql)
    if not branch:
        return None
    return ("tool error (not run: AND before OR): in this WHERE, AND binds before OR, so the conditions joined with "
            f"AND after the last OR apply to that branch only ({branch[:200]}): the other branches are counted "
            "without them. Put the alternatives in parentheses: WHERE (a OR b) AND c. If one branch alone is meant, "
            "send this same call again unchanged.")


def outer_join_undone(sql: str) -> tuple[str, str] | None:
    """(the condition, the table) when a WHERE condition on a column of the table a LEFT JOIN keeps optional drops the
    rows that have no match, as an inner join would ("FROM orders o LEFT JOIN returns r ... WHERE r.STATUS =
    'REFUNDED'": only the orders that have a refunded return, the total over all the orders lost). Not judged: IS NULL
    and IS NOT NULL (an anti-join, or rows dropped on purpose), a COALESCE of the column, a condition inside an OR."""
    from sqlglot import exp

    tree = _parse(sql)
    if tree is None:
        return None
    for sel in tree.find_all(exp.Select):
        optional = {}
        for j in sel.args.get("joins") or []:
            if (j.side or "").upper() == "LEFT" and isinstance(j.this, exp.Table):
                optional[j.this.alias_or_name] = j.this.name
        where = sel.args.get("where")
        if not optional or where is None:
            continue
        terms, todo = [], [where.this]
        while todo:
            node = todo.pop()
            if isinstance(node, exp.And):
                todo += [node.this, node.expression]
            elif isinstance(node, exp.Paren):
                todo.append(node.this)
            else:
                terms.append(node)
        for term in terms:
            if isinstance(term, (exp.Is, exp.Or)) or (isinstance(term, exp.Not) and isinstance(term.this, exp.Is)):
                continue
            if next(term.find_all(exp.Coalesce), None) is not None or next(term.find_all(exp.Or), None) is not None:
                continue
            cols = [c for c in term.find_all(exp.Column) if c.table in optional]
            if cols:
                return term.sql(dialect="duckdb"), optional[cols[0].table]
    return None


def outer_join_refusal(name: str, args: dict) -> str | None:
    if name not in ("execute_sql", "export_excel", "chart_from_sql", "create_virtual_dataset", "save_sql_query"):
        return None
    try:
        from supagent import settings

        if not settings.get("agent.outer_join_check"):
            return None
    except Exception:  # pylint: disable=broad-except   (no app: as the default)
        pass
    req = args.get("request") if isinstance(args.get("request"), dict) else args
    found = outer_join_undone(str((req or {}).get("sql") or ""))
    if not found:
        return None
    cond, table = found
    return (f"tool error (not run: a LEFT JOIN made inner): the condition {cond[:160]} is in WHERE and reads {table}, "
            "the side of the LEFT JOIN that may have no row: the rows without a match are dropped, as with an inner "
            "join (a total over all the rows becomes a total over the rows that have one). Put the condition in the ON "
            f"of the join (LEFT JOIN {table} ... ON ... AND {cond[:80]}), or inside the aggregate (SUM(CASE WHEN ... "
            "THEN ... END)). If only the rows with a match are meant, send this same call again unchanged.")


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
    if tree is None or not any(True for _ in tree.find_all(exp.Avg)):
        return None
    if DAY_STEP.search(sql):
        daily = _daily_avg(tree)                         # (0.10.7) the day's step averages an amount's records
        if not daily:
            return None
        return (f"tool error (not run: average per day): the question asks for an average per day, and this query's "
                f"per-day step averages each day's records (AVG({daily}) grouped by the day: several records a day, "
                f"one per book, trader, order...), so the result is an average of averages. A day's figure of an "
                f"amount is the SUM of its records: AVG over the per-day SUM(x) (GROUP BY the day), or SUM(x) / "
                f"COUNT(DISTINCT the day). If each day's average record is meant, send this same call again unchanged.")
    return ("tool error (not run: average per day): the question asks for an average per day, and this query "
            "averages the records themselves (AVG over every row: several a day, one per book, trader, order...). An "
            "average per day of a total is each day's total averaged over the days: SUM(x) / COUNT(DISTINCT the day), "
            "or AVG over a per-day SUM (GROUP BY the day). If the average of the records is meant, send this same "
            "call again unchanged.")


AMOUNT = re.compile(r"pnl|p_?l\b|amount|amt|revenue|sales|turnover|volume|qty|quantity|notional|cost|fee|spend|"
                    r"profit|loss|margin|income|expense|orders?\b|count|errors?\b|requests?\b|bytes", re.I)
DAY_COLUMN = re.compile(r"date|cob|day|_dt\b|\bdt\b|\bts\b|time", re.I)


def _daily_avg(tree) -> str | None:
    """(0.10.7) The amount a query's per-day step averages ("SELECT day, AVG(amount) ... GROUP BY day" under an AVG
    over the days: an average of each day's average record, M1-0107m): the column, or None. Only amounts (a PnL, a
    revenue, a count of orders): a latency, a load or a price averaged per day is each day's figure."""
    from sqlglot import exp

    for sel in tree.find_all(exp.Select):
        group = sel.args.get("group")
        if not group or not any(DAY_COLUMN.search(g.sql()) for g in group.expressions):
            continue
        for avg in sel.find_all(exp.Avg):
            if avg.find_ancestor(exp.Select) is not sel:
                continue                                 # (an AVG of a query inside this one)
            cols = [c.name for c in avg.find_all(exp.Column)]
            if cols and all(AMOUNT.search(c) for c in cols):
                return cols[0]
    return None


def grouped_fixed(sql: str) -> list[tuple[str, str]]:
    """(0.10.7) The columns a query groups by and keeps at one value (WHERE "BOOK" = 'ALL' ... GROUP BY "BOOK"):
    (column, value). Its result can only be that value."""
    from sqlglot import exp

    tree = _parse(sql)
    sel = tree if isinstance(tree, exp.Select) else (tree.find(exp.Select) if tree is not None else None)
    if sel is None or not sel.args.get("group") or not sel.args.get("where"):
        return []
    items = sel.expressions
    grouped = set()
    for g in sel.args["group"].expressions:
        if isinstance(g, exp.Literal) and g.is_int and 0 < int(g.this) <= len(items):
            g = items[int(g.this) - 1].unalias()
        if isinstance(g, exp.Column):
            grouped.add(g.name.lower())

    def conjuncts(node: Any) -> list[Any]:
        return conjuncts(node.left) + conjuncts(node.right) if isinstance(node, exp.And) else [node]

    out = []
    for c in conjuncts(sel.args["where"].this):
        c = c.unnest() if isinstance(c, exp.Paren) else c
        if isinstance(c, exp.EQ) and isinstance(c.left, exp.Column) and isinstance(c.right, exp.Literal) and \
                c.left.name.lower() in grouped:
            out.append((c.left.name, c.right.name))
    return out


def grouped_fixed_refusal(question: str, name: str, args: dict) -> str | None:
    """(0.10.7) "Which books breached their limit most often?" ran GROUP BY "BOOK" with "BOOK" = 'ALL' kept from the
    question before (about desks), and answered with that one row: a column the question asks about, grouped and
    kept at one value, is sent back once before it runs."""
    if name not in ("execute_sql", "export_excel"):
        return None
    req = args.get("request") if isinstance(args.get("request"), dict) else args
    asked = (question or "").lower()
    for col, value in grouped_fixed(str((req or {}).get("sql") or "")):
        word = col.lower().replace("_", " ")
        if re.search(rf"\b{re.escape(word)}(?:e?s)?\b", asked):
            return (f"tool error (not run: grouped and kept at one value): this query groups by \"{col}\" and keeps "
                    f"only \"{col}\" = '{value}': its result can only be '{value}', where the question asks about the "
                    f"{word} values. A condition of an earlier query (another question) is not this one's: remove "
                    "it (or keep what the question means, e.g. leave out a total row). If the question does mean "
                    "that one value, send this same call again unchanged.")
    return None


# (0.10.8) "Which book lost the most money on 22 September?" answered from the single row with the lowest PnL (one
# trader's), the book's rows never summed: a question of which <part> has the most or the least
WHICH_EXTREME = re.compile(r"\bwhich\s+([a-z][a-z_-]{2,}?)(?:e?s)?\b[^?.;]{0,80}?\b(?:the\s+)?(?:most|least|highest|lowest|"
                           r"biggest|largest|smallest|worst|best|top)\b", re.I)


def per_part_note(question: str, args: dict, result: str) -> str | None:
    """(0.10.8) A question of which <part> has the most or the least of something, answered by a query of single rows
    (nothing grouped nor aggregated) whose rows name one part several times: said with the result (one part's rows
    are summed per part before the comparison; nothing is refused: a table of one row per part is not concerned)."""
    m = WHICH_EXTREME.search(question or "")
    if not m:
        return None
    from sqlglot import exp

    req = args.get("request") if isinstance(args.get("request"), dict) else args
    tree = _parse(str((req or {}).get("sql") or ""))
    if tree is None or tree.find(exp.Group) or tree.find(exp.AggFunc) or tree.find(exp.Window):
        return None
    word = m.group(1).lower().replace("-", " ").replace("_", " ")
    part = next((c.name for c in tree.find_all(exp.Column)
                 if c.name.lower().replace("_", " ") in (word, word + "s", word + "es", word.rstrip("s"))), None)
    if part is None:
        return None
    try:
        rows = (json.loads(result) or {}).get("rows") or []
    except (ValueError, TypeError, AttributeError):
        return None
    counts: dict[str, int] = {}
    for r in rows[:200]:
        if isinstance(r, dict) and r.get(part) is not None:
            counts[str(r[part])] = counts.get(str(r[part]), 0) + 1
    many = sorted(((n, v) for v, n in counts.items() if n > 1), reverse=True)
    if not many:
        return None
    said = ", ".join(f"{v} {n} times" for n, v in many[:3])
    return (f"\n(Note: \"{part}\" repeats in these rows ({said}): the question asks which {word} has the most or the "
            f"least, so each {word}'s rows are summed (or counted, averaged: what the question means) per {word} "
            f"(GROUP BY \"{part}\") before the comparison, unless the single rows are what it compares.)")


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


TIMEISH = re.compile(r"(?:^|_)(?:ts|time|timestamp|date|day|hour|minute|week|month|year|bucket|period)(?:$|_)|^@",
                     re.I)


def ranked_by_label(sql: str) -> tuple[str, int] | None:
    """(0.10.12) (the label, the limit) when a query keeps its first few groups (LIMIT 5 or less) ordered by a label it
    groups by, not by the figure it computes: "ORDER BY 1 ASC LIMIT 1" over (node, MIN(value)) gave the first server
    by name (srv-amer-000, 89.78 GiB) for "the server with the least available memory" (srv-apac-009, 10.25 GiB).
    A time bucket is not a label here (the first days of a period are asked that way)."""
    from sqlglot import exp

    tree = _parse(sql)
    sel = tree if isinstance(tree, exp.Select) else (tree.find(exp.Select) if tree is not None else None)
    if sel is None or not sel.args.get("group") or not sel.args.get("order") or not sel.args.get("limit"):
        return None
    try:
        n = int(sel.args["limit"].expression.this)
    except (AttributeError, TypeError, ValueError):
        return None
    exprs = list(sel.expressions)
    if n > 5 or not any(e.find(exp.AggFunc) for e in exprs):
        return None
    key = sel.args["order"].expressions[0].this
    target = None
    if isinstance(key, exp.Literal) and not key.is_string and str(key.this).isdigit():
        i = int(key.this) - 1
        target = exprs[i] if 0 <= i < len(exprs) else None
    elif isinstance(key, exp.Column):
        target = next((e for e in exprs if (e.alias_or_name or "").lower() == key.name.lower()), key)
    if target is None or target.find(exp.AggFunc) or not isinstance(target.unalias(), exp.Column):
        return None
    name = target.alias_or_name or ""
    if not name or TIMEISH.search(name):
        return None
    return name, n


def ranked_refusal(name: str, args: dict) -> str | None:
    if name not in ("execute_sql", "export_excel"):
        return None
    req = args.get("request") if isinstance(args.get("request"), dict) else args
    found = ranked_by_label(str((req or {}).get("sql") or ""))
    if not found:
        return None
    label, n = found
    return (f"tool error (not run: ranked by name): this query keeps its first {n} row(s) ordered by {label}, a label "
            "it groups by, not by the figure it computes: the first row is not the most or the least. Order by the "
            "figure (its alias, DESC for the most, ASC for the least). If this is meant, send this same call again "
            "unchanged.")


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


# (0.10.7) a value asked at a moment: "the memory use at 09:30" (not "around", "between", "from")
AT_MOMENT = re.compile(r"(?<!around )(?<!about )(?<!between )(?<!from )(?<!after )(?<!before )(?<!until )\bat\s+(\d{1,2})"
                       r"(?::(\d{2})|\s*h(\d{2})?)\b", re.I)
AVERAGED = re.compile(r"\b(?:AVG|MEAN)\s*\(", re.I)     # a level averaged (a count summed per hour: that hour)


def value_at_moment(question: str, queries: list[str]) -> tuple[str, str] | None:
    """(0.10.7) (the moment asked, the bucket) when the question asks a value at a time of day ("What was the
    memory use of the cache at 09:30?") and every query that read it averaged it over buckets of an hour or more:
    the average of the hour is not the value at the moment when it moves within the hour (a level rising fast)."""
    m = AT_MOMENT.search(question or "")
    if not m or TIME_ASKED.search(question or "") or not queries:
        return None
    hour, minute = int(m.group(1)), m.group(2) or m.group(3) or "00"
    if hour > 23:
        return None
    reading = [q for q in queries if re.search(r"\bSELECT\b", q or "", re.I)]
    if not reading or not all(bucket_grain(q) in ("hour", "day", "week", "month") and AVERAGED.search(q)
                              for q in reading):
        return None                                    # a query read the samples themselves
    return f"{hour:02d}:{minute}", bucket_grain(reading[-1])


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
