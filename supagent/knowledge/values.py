"""A query that compares a field with a value the field does not have (the classic pipeline).

"What share of the orders were express?" was counted with a channel field = 'EXPRESS', when express is a true/false
field of its own and the channel field holds other values: 0 %, and the answer went on to explain the 0 with a team
note. A status that only another index has (a refund status looked for in the orders), a status the field does not
use (closed for tickets that are open or resolved): a comparison (=, IN, <>, NOT IN) of a field with a text it never
holds, by the values the dictionary learned, counts nothing (or leaves out nothing). The call is sent back once
before it runs, with the field's values and the field (or the value of another field) that holds that text, if one
does. Sent again unchanged, it runs (a value added since the learning).

Only fields whose list of values is whole: the index was learned on all its documents (sampled_docs >= docs), and
no field of the same name in the query's other indices has the value (a join: the condition may be on that one) or
lacks a list. Only small vocabularies (at most 25 values: statuses, channels, desks, countries), not hosts, ids or
change targets, where a value the dictionary has not seen yet is ordinary (an incident's new host). Not for open
questions (investigations): looking a value up and finding nothing is an answer there. Case does not matter here
(the empty-result hint says how a value is written).
"""

from __future__ import annotations

from typing import Any

from superset import db

OPS = ("=", "IN", "<>", "!=", "NOT IN", "NOT =")
SHOWN = 12
VOCABULARY = 25     # a small fixed vocabulary (statuses, channels, desks, countries); not hosts, ids, targets


def unknown(sql: str) -> list[dict[str, Any]]:
    """[{table, field, value, op, values, elsewhere}] of the comparisons with a value the field does not have."""
    from supagent.knowledge.conditions import sql_conditions
    from supagent.knowledge.rulecheck import _tables
    from supagent.models import KObject

    tables = _tables(sql or "")
    if not tables:
        return []
    conds = [c for c in sql_conditions(sql) if c.op in OPS and c.values and all(isinstance(v, str) for v in c.values)]
    if not conds:
        return []
    fields = (db.session.query(KObject).filter(KObject.kind == "field", KObject.parent.in_(list(tables)),
                                               KObject.gone_at.is_(None)).all())
    indices = {o.name: o for o in db.session.query(KObject).filter(KObject.kind == "index",
                                                                   KObject.name.in_(list(tables)),
                                                                   KObject.gone_at.is_(None))}
    out: list[dict[str, Any]] = []
    for c in conds:
        same = [o for o in fields if o.name.lower() == c.column.lower()]
        if not same or any(not isinstance((o.stats or {}).get("values"), list) for o in same):
            continue                                       # a field with no list may hold it
        if any(len((o.stats or {}).get("values") or []) > VOCABULARY for o in same):
            continue                                       # hosts, ids, targets: new ones come every day
        if not all(_whole(indices.get(o.parent)) for o in same):
            continue                                       # learned on a sample: a rare value may be missing
        held = {str(v).lower() for o in same for v in (o.stats or {}).get("values") or []}
        f = same[0]
        for v in c.values:
            low = str(v).lower()
            if not low or low in held:
                continue
            elsewhere = [o.name for o in fields if o.parent == f.parent and o.name.lower() != f.name.lower() and
                         (o.name.lower() == low or low in {str(x).lower() for x in (o.stats or {}).get("values") or []})]
            out.append({"table": f.parent, "field": f.name, "value": v, "op": c.op,
                        "values": [str(x) for x in (f.stats or {}).get("values") or []], "elsewhere": elsewhere})
    return out


def _whole(index: Any) -> bool:
    st = (index.stats or {}) if index is not None else {}
    docs, seen = st.get("docs"), st.get("sampled_docs")
    return bool(docs) and seen is not None and seen >= docs


def refusal(tool: str, args: dict) -> str | None:
    """Why this query is sent back (once): a field compared with a value it does not have."""
    from supagent.knowledge.excluded import query_texts
    from supagent.knowledge.period import SQL_TOOLS

    if tool not in SQL_TOOLS:
        return None
    for sql in [q for q in query_texts(args) if q]:
        found = unknown(sql)
        if not found:
            continue
        u = found[0]
        vals = u["values"]
        shown = ", ".join(vals[:SHOWN]) + (f", ... ({len(vals)} values)" if len(vals) > SHOWN else "")
        where = ""
        for other in u["elsewhere"][:2]:
            where += (f" {u['value']} is a field of {u['table']} of its own (\"{other}\")." if other.lower() == str(u['value']).lower()
                      else f" '{u['value']}' is a value of \"{other}\" in {u['table']}.")
        effect = "leaves out nothing" if u["op"] in ("<>", "!=", "NOT IN", "NOT =") else "counts nothing"
        return (f"tool error (not run: value): \"{u['field']}\" of {u['table']} has no value '{u['value']}' (its values: "
                f"{shown}), so this condition {effect}.{where} Use one of its values or the field that holds it. If "
                f"'{u['value']}' is meant (a value added since the data dictionary learned it), send this same call "
                f"again unchanged.")
    return None
