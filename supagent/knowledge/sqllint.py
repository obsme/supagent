"""Mistakes a query shows by its own text (0.9.2), checked by code:

  - two result columns computed by the same aggregate under different names ("SUM(increase) AS errors_500,
    SUM(increase) AS total_requests"): one of them lost its own condition, and the answer then reads the total as the
    errors (the share next to it was right). Sent back before the query runs.
  - a time of day read from a time bucket: "At what time was it?" answered "04:00" from a query that grouped the
    samples by hour (the peak was at 04:26): the bucket's start is no moment. Sent back once after the answer.
"""

from __future__ import annotations

import re
from typing import Any

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
