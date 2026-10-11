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

import re
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


# (0.10.8, the team: "when given a server or component name, the search should manage capital and lower cases and
# special characters") a value written another way than the data writes it ('HOST-A-07', 'host_a_07',
# 'Host A 7' for host-a-07): rewritten as the data writes it before the query runs, when only one value of the
# field (or of the metric's label) is written so; an exact match is never touched
def loose(value: Any) -> str:
    """A name without case, separators or leading zeros: host-a-07, HOST_A_7 and "host a 007" are one."""
    text = re.sub(r"[\s_.\-/:]+", "-", str(value).strip().lower()).strip("-")
    return re.sub(r"\d+", lambda m: str(int(m.group())), text)


# (0.10.8, the team: a server is named by its full name in the data and by its short one in a question) a field or
# label that holds hosts: a host is found by its full name, its short name and its address with a port, whichever
# is asked (web01, web01.corp.example, web01:9100), never another host of the same short name
HOST_FIELD = re.compile(r"(?:^|[_.\s])(?:hosts?|hostnames?|nodes?|nodename|instance|servers?|servername|machine|fqdn|"
                        r"vm|computer|device|target|upstream|peer)(?:$|[_.\s])", re.I)


DNS_NAME = re.compile(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)*")     # a host's name: labels of letters, digits, - and _


def host_key(value: Any) -> str:
    """A host as named, in lower case, without a final dot or a port: web01.corp.example of
    WEB01.corp.example:9100."""
    return re.sub(r":\d+$", "", str(value).strip().lower().rstrip("."))


def same_host(a: Any, b: Any) -> bool:
    """web01, WEB01, web01.corp.example and web01:9100 name one host (one name is the first labels of
    the other); web01.corp.example and web01.dmz.example do not, nor 10.0.0 and 10.0.0.1."""
    x, y = host_key(a), host_key(b)
    if not x or not y:
        return False
    if loose(x) == loose(y):
        return True
    if not DNS_NAME.fullmatch(x) or not DNS_NAME.fullmatch(y):
        return False
    p, q = sorted((x.split("."), y.split(".")), key=len)
    return len(p) < len(q) and bool(re.search(r"[a-z]", p[0])) and \
        [loose(w) for w in p] == [loose(w) for w in q[:len(p)]]


def host_aliases(name: Any) -> list[str]:
    """The shorter names of a host, in lower case: web01.corp.example and web01 for web01.corp.example:9100;
    none for a plain name or an IP address."""
    key, said = host_key(name), str(name).strip().lower()
    if not DNS_NAME.fullmatch(key):
        return []
    labels = key.split(".")
    out = [key] if key != said else []
    if len(labels) > 1 and re.search(r"[a-z]", labels[0]):
        out.append(labels[0])
    return [a for a in dict.fromkeys(out) if len(a) >= 2]


def names_hit(labels: dict, wanted: set[str]) -> set[str]:
    """The names of `wanted` (lower case) that a series' labels hold: as written, in another case or with other
    separators, and a host by its full name, its short name or its address (web01 for a label
    instance="web01.corp.example:9100")."""
    out: set[str] = set()
    for k, v in (labels or {}).items():
        v = str(v)
        for w in wanted:
            if w == v.lower() or loose(w) == loose(v) or (HOST_FIELD.search(str(k)) and same_host(w, v)):
                out.add(w)
    return out


def spellings(names: list[str], known: list[str] | set[str], limit: int = 12) -> list[str]:
    """The values of `known` written otherwise than these names but naming them (another case, other separators, a
    host's full name, short name or address), at most `limit`: what a field of records writes them as."""
    out: list[str] = []
    for k in known:
        k = str(k)
        if k not in names and any(loose(n) == loose(k) or same_host(n, k) for n in names):
            out.append(k)
            if len(out) >= limit:
                break
    return out


def _known(objects: list[Any]) -> set[str]:
    return {str(v) for o in objects for v in ((o.stats or {}).get("values") or []) if v not in (None, "")}


def _respelled(value: str, known: set[str], hosts: bool = False) -> str | None:
    if not value or value in known:
        return None
    hits = {k for k in known if k.lower() == value.lower()} or {k for k in known if loose(k) == loose(value)}
    if not hits and hosts:                              # web01 <-> web01.corp.example, web01:9100
        hits = {k for k in known if same_host(value, k)}
        port = re.search(r":\d+$", value.strip())
        if len(hits) > 1 and port:                      # web01:9100 asked: the address of that port
            hits = {k for k in hits if k.strip().endswith(port.group(0))} or hits
    return next(iter(hits)) if len(hits) == 1 else None


def respell_sql(sql: str) -> tuple[str, list[tuple[str, str]]]:
    """(the query, [(as written, as the data writes it)]) for the strings compared (=, IN, <>, NOT IN) with a field
    of the query's tables or a label of its metrics."""
    from supagent.knowledge.conditions import sql_conditions
    from supagent.knowledge.rulecheck import _tables
    from supagent.models import KObject

    tables = _tables(sql or "")
    if not tables:
        return sql, []
    try:
        conds = [c for c in sql_conditions(sql) if c.op in OPS and c.values and all(isinstance(v, str) for v in c.values)]
    except Exception:  # pylint: disable=broad-except   (a query the parser cannot read runs as written)
        return sql, []
    if not conds:
        return sql, []
    objects = (db.session.query(KObject).filter(KObject.kind.in_(("field", "label")), KObject.parent.in_(list(tables)),
                                                KObject.gone_at.is_(None)).all())
    changes: list[tuple[str, str]] = []
    for c in conds:
        known = _known([o for o in objects if o.name.lower() == c.column.lower()])
        for v in c.values:
            new = _respelled(v, known, hosts=bool(HOST_FIELD.search(c.column)))
            if new and (v, new) not in changes:
                changes.append((v, new))
    for old, new in changes:
        sql = sql.replace(f"'{old}'", f"'{new}'")
    return sql, changes


def respell_promql(expr: str) -> tuple[str, list[tuple[str, str]]]:
    """The same for the label matchers of a PromQL expression (label="value", label!="value")."""
    from supagent.models import KObject

    metrics = set(re.findall(r"\b([a-zA-Z_:][a-zA-Z0-9_:]*)\s*\{", expr or ""))
    pairs = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*!?=\s*\"([^\"]*)\"", expr or "")
    if not metrics or not pairs:
        return expr, []
    objects = (db.session.query(KObject).filter(KObject.kind == "label", KObject.parent.in_(sorted(metrics)),
                                                KObject.gone_at.is_(None)).all())
    changes: list[tuple[str, str]] = []
    for label, v in pairs:
        new = _respelled(v, _known([o for o in objects if o.name == label]), hosts=bool(HOST_FIELD.search(label)))
        if new and (v, new) not in changes:
            changes.append((v, new))
    for old, new in changes:
        expr = expr.replace(f'"{old}"', f'"{new}"')
    return expr, changes


def respell(tool: str, args: dict) -> list[tuple[str, str]]:
    """The call's values written as the data writes them, in place: [(as written, as the data writes it)]."""
    req = args.get("request") if isinstance(args.get("request"), dict) else args
    changes: list[tuple[str, str]] = []
    if isinstance(req.get("sql"), str):
        req["sql"], changes = respell_sql(req["sql"])
    elif tool in ("promql_query", "compare_to_usual") and isinstance(req.get("expr") or req.get("promql"), str):
        key = "expr" if isinstance(req.get("expr"), str) else "promql"
        req[key], changes = respell_promql(req[key])
    elif isinstance(req.get("table"), str):            # the conditions of a table's comparison (where, focus)
        for key in ("where", "focus"):
            cond = req.get(key)
            if not isinstance(cond, str) or not cond.strip():
                continue
            _sql, mine = respell_sql(f'SELECT * FROM "{req["table"].strip(chr(34))}" WHERE {cond}')
            for old, new in mine:
                cond = cond.replace(f"'{old}'", f"'{new}'")
                if (old, new) not in changes:
                    changes.append((old, new))
            req[key] = cond
    return changes
