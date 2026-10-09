"""The system around a question (0.9): what the team's categories, the interactions drawn between their values
and the catalog say about the parts a question names, put together without the LLM and given with the question.

A question about "the batch of the billing applications" names a value of the categories. From it: what the
value consists of (the applications of a family, the servers of a pool), what those depend on, run on, read,
call (one step further for what they wait for), where each kind of part is in the data (the fields and metric
labels its category is read from), how the tables join, which field holds the usual value of a measure, and the
health checks. An investigation starts from this picture instead of discovering the system query by query, and
a plain count starts with the right values ("billing applications" = the three that are part of it).

Nothing here is about a domain: everything is read from the deployment's own categories (knowledge.facets), the
interactions of its system map (knowledge.sysmap) and its catalog.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any

from superset import db

log = logging.getLogger(__name__)
SEEDS = 4                 # values of the question the picture is built from
MEMBERS = 12              # parts of a named value shown by name
ACTORS = 10               # values whose interactions are read
TARGETS = 8               # per kind of interaction
FURTHER = 8               # values followed one step further
BRIEF_CHARS = 4600
ABOUT_CHARS = 700         # what the categories are, in the picture
FOLLOW_CHARS = 900        # what to do on the interactions of the question's parts (their long explanations)
ROUTER_CHARS = 500        # what the question names, for the router
SCOPE_CHARS = 700
ATOM = re.compile(r"[A-Za-z0-9À-ÿ_][A-Za-z0-9À-ÿ_.:/\-]*")
OUT = {"depends_on": "depend on", "runs_on": "run on", "reads_from": "read from", "sends_to": "send data to",
       "calls": "call", "triggers": "trigger", "monitors": "monitor", "about": "relate to", "link": "are linked to"}
ONE = {"depends_on": "depends on", "runs_on": "runs on", "reads_from": "reads from", "sends_to": "sends data to",
       "calls": "calls", "triggers": "triggers", "monitors": "monitors", "about": "relates to", "link": "is linked to"}
IN = {"depends_on": "needed by", "runs_on": "what runs on them", "reads_from": "read by", "sends_to": "receive data from",
      "calls": "called by", "triggers": "triggered by", "monitors": "monitored by", "about": "related",
      "link": "linked from"}
FOLLOWED = ("depends_on", "reads_from", "runs_on", "calls", "sends_to", "link")   # what a slowdown or a delay can
#                                       come from (0.9.6: a link a person drew is followed from its start to its end)
USUAL_NAME = re.compile(r"^(avg|average|mean|usual|baseline|median|typical)[_ ]", re.I)
_CACHE: dict[str, Any] = {"stamp": None, "graph": None, "fields": {}}
_LOCK = threading.Lock()


def _graph() -> dict[str, Any]:
    """The approved values with their names, what each is part of and consists of, and the interactions drawn
    between them; read again when the knowledge changed."""
    from supagent.knowledge.facets import editable
    from supagent.knowledge.freshness import stamp
    from supagent.models import Facet, Link

    s = stamp()
    with _LOCK:
        if _CACHE["graph"] is not None and _CACHE["stamp"] == s:
            return _CACHE["graph"]
    cats = list(editable())
    values: dict[int, dict[str, Any]] = {}
    names: dict[str, list[int]] = {}
    children: dict[int, list[int]] = {}
    from supagent.knowledge.facets import PART_OF, part_of_map

    parts = part_of_map()                             # what each is part of: links of kind part_of (0.9.6)
    for f in db.session.query(Facet).filter(Facet.status == "approved", Facet.facet.in_(cats)):
        values[f.id] = {"id": f.id, "cat": f.facet, "name": f.value, "about": (f.description or "").strip(),
                        "parents": list(parts.get(f.id, []))}
        for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
            n = " ".join(n.lower().split())
            if len(n) >= 2:
                names.setdefault(n, []).append(f.id)
    for v in values.values():
        v["parents"] = [p for p in v["parents"] if p in values and p != v["id"]]
        for p in v["parents"]:
            children.setdefault(p, []).append(v["id"])
    out_links: dict[int, list[tuple[str, int, str]]] = {}
    in_links: dict[int, list[tuple[str, int, str]]] = {}
    long: dict[tuple[int, str, int], str] = {}        # what to do when following an interaction (its long explanation)
    from supagent.knowledge.sysmap import generic

    rows = db.session.query(Link.a_ref, Link.b_ref, Link.kind, Link.note, Link.detail, Link.both_ways).filter(
        Link.a_ref.like("facet:%"), Link.b_ref.like("facet:%"), Link.status == "approved", Link.kind != PART_OF)
    for a_ref, b_ref, kind, note, detail, both in rows:
        a, b = a_ref.split(":", 1)[1], b_ref.split(":", 1)[1]
        if a.isdigit() and b.isdigit() and int(a) in values and int(b) in values:
            kind = "link" if generic(kind) else kind      # a person's link: "is linked to", with what it is
            ways = [(int(a), int(b)), (int(b), int(a))] if both else [(int(a), int(b))]
            for x, y in ways:
                out_links.setdefault(x, []).append((kind, y, (note or "").strip()))
                in_links.setdefault(y, []).append((kind, x, (note or "").strip()))
                if (detail or "").strip():
                    long[(x, kind, y)] = " ".join(detail.split())
    loose, slips = loose_index(names)
    g = {"values": values, "names": names, "children": children, "out": out_links, "in": in_links, "rank": cats,
         "long": long, "loose": loose, "slips": slips}
    with _LOCK:
        _CACHE.update(stamp=s, graph=g)
    return g


def named(text: str, g: dict[str, Any] | None = None, loose: bool = False) -> list[int]:
    """The values a text names, in its order: a value's name or one of its other names written as words of
    their own (the longest name wins: "risk engine" before "risk"); a name that is a common word counts only
    written as the value is (NOVA, not "nova"). (0.10.4) `loose` (a question): also written with other separators
    ("node exporter", node_exporter, nodeexporter for node-exporter) or misspelled by a letter missing, one too many
    or two swapped (6 letters or more, one value only, never a plural)."""
    from supagent.knowledge.describe import STOP

    g = g or _graph()
    atoms = [(m.group(0).rstrip(".:/-"), m.start()) for m in ATOM.finditer(text or "")]
    atoms = [(a, at) for a, at in atoms if a]
    found: list[int] = []
    i = 0
    while i < len(atoms):
        hit = 0
        for n in range(min(5, len(atoms) - i), 0, -1):
            words = [a for a, _at in atoms[i:i + n]]
            key = " ".join(w.lower() for w in words)
            ids = g["names"].get(key)
            if not ids and loose:
                ids = _loosely(key, n, g)
            if not ids:
                continue
            if n == 1 and (len(key) < 3 or key in STOP) and not any(g["values"][x]["name"] == words[0] for x in ids):
                continue
            found += [x for x in ids if x not in found]
            hit = n
            break
        i += hit or 1
    return found


LOOSE = re.compile(r"[\s_.\-/]+")


def loose_index(names: dict[str, list[int]]) -> tuple[dict[str, list[int]], dict[str, set[int]]]:
    """(0.10.4) The values by their names without separators ("node exporter", node_exporter, nodeexporter are
    node-exporter), and by those names with a letter missing or two swapped (6 letters or more)."""
    loose: dict[str, list[int]] = {}
    for n, ids in names.items():
        k = LOOSE.sub("", n)
        if len(k) >= 4:
            for i in ids:
                if i not in loose.setdefault(k, []):
                    loose[k].append(i)
    slips: dict[str, set[int]] = {}
    for k, ids in loose.items():
        if len(k) >= 6:
            for v in {k[:i] + k[i + 1:] for i in range(len(k))} | \
                    {k[:i] + k[i + 1] + k[i] + k[i + 2:] for i in range(len(k) - 1) if k[i] != k[i + 1]}:
                slips.setdefault(v, set()).update(ids)
    return loose, slips


def _loosely(key: str, n: int, g: dict[str, Any]) -> list[int]:
    """(0.10.4) The values a question's words name written another way: the same letters without separators, else
    (one word of 6 letters or more) a letter missing, one too many or two swapped, when one value only is so named."""
    from supagent.knowledge.describe import STOP

    k = LOOSE.sub("", key)
    if len(k) < 4 or (n == 1 and key in STOP):
        return []
    ids = (g.get("loose") or {}).get(k) or []
    if ids or n > 1 or len(k) < 6 or not k.isalpha():
        return list(ids)
    cands = set((g.get("slips") or {}).get(k) or set())          # a letter missing in the word, two swapped
    for j in range(len(k)):                                       # a letter too many in the word (a name of 6
        if len(k) - 1 >= 6:                                       # letters or more: "cached" is no "cache")
            cands.update((g.get("loose") or {}).get(k[:j] + k[j + 1:]) or [])
    plurals = {x for x in cands if any(LOOSE.sub("", nm) + s == k for nm in [g["values"][x]["name"]] for s in ("s", "es"))}
    cands -= plurals
    return sorted(cands) if len(cands) == 1 else []


def says_something(i: int, g: dict[str, Any]) -> bool:
    """A value with a description, something it is part of or consists of, or an interaction: a part of the
    system. One that has none of these is a word of the question."""
    v = g["values"][i]
    return bool(v["about"] or v["parents"] or g["children"].get(i) or g["out"].get(i) or g["in"].get(i))


def _first_sentence(text: str, chars: int = 150) -> str:
    s = re.split(r"(?<=[.!?])\s", " ".join((text or "").split()), maxsplit=1)[0]
    return s[:chars].rstrip(" .") + ("…" if len(s) > chars else "")


def _fields_of(cats: list[str], names: dict[str, list[str]]) -> dict[str, list[str]]:
    """Where each category is in the data the user may query: the fields and the metric labels its values are
    read from (categories.fields), else where its named values are found among the learned values."""
    from supagent.knowledge.facets import field_matches, field_rules
    from supagent.knowledge.resolve import _databases, value_rows
    from supagent.models import KObject, Source

    databases = _databases()
    by_source = {s.id: next((d for d in databases if d.id == s.database_id), None) for s in db.session.query(Source)}
    by_source = {sid: d for sid, d in by_source.items() if d is not None}
    out: dict[str, list[str]] = {}
    if not by_source:
        return out
    rules = [(c, rx) for c, rx in field_rules()]
    if rules:
        # every field and label of the dictionary is looked at (tens of thousands on a platform): once per state of
        # the knowledge and set of databases, whatever the question
        from supagent.knowledge.freshness import stamp

        key = (stamp(), tuple(sorted(d.id for d in by_source.values())), tuple((c, rx.pattern) for c, rx in rules))
        with _LOCK:
            known = _CACHE["fields"].get(key)
        if known is None:
            fields: dict[tuple[str, int, str], list[str]] = {}
            labels: dict[tuple[str, int, str], list[str]] = {}
            rows = db.session.query(KObject.source_id, KObject.kind, KObject.parent, KObject.name).filter(
                KObject.kind.in_(("field", "label")), KObject.gone_at.is_(None), KObject.source_id.in_(list(by_source)))
            for sid, kind, parent, name in rows:
                for cat, rx in rules:
                    if field_matches(rx, name or ""):
                        (fields if kind == "field" else labels).setdefault((cat, by_source[sid].id, name), []).append(parent or "")
            known = {}
            for (cat, dbid, name), tables in sorted(fields.items()):
                known.setdefault(cat, []).append(f'field "{name}" of {_some(sorted(set(tables)), 4)} (database {dbid})')
            for (cat, dbid, name), metrics in sorted(labels.items()):
                known.setdefault(cat, []).append(f'label {name} of {len(set(metrics))} metric(s) such as '
                                                 f'{_some(sorted(set(metrics)), 3)} (database {dbid})')
            with _LOCK:
                _CACHE["fields"] = {key: known}
        out.update({c: list(v) for c, v in known.items() if c in cats})
    todo = {c: names.get(c, [])[:3] for c in cats if c not in out and names.get(c)}
    if todo:
        tokens = [t for ts in todo.values() for t in ts]
        places = value_rows(tokens, list(by_source.values()))
        for cat, ts in todo.items():
            seen: list[str] = []
            for t in ts:
                for (dbid, kind, name), parents in sorted((places.get(t) or {}).items()):
                    what = (f'field "{name}" of {_some(sorted(set(parents)), 3)}' if kind == "field" else
                            f"label {name} of {len(set(parents))} metric(s) such as {_some(sorted(set(parents)), 3)}")
                    line = f"{what} (database {dbid})"
                    if line not in seen:
                        seen.append(line)
            if seen:
                out[cat] = seen[:4]
    return out


def _some(items: list[str], n: int) -> str:
    return ", ".join(items[:n]) + (f" and {len(items) - n} more" if len(items) > n else "")


def _joins(tables: set[str]) -> list[str]:
    """How these tables join the others, and which fields hold a usual value (the catalog)."""
    from supagent.tools import _catalog

    cat = _catalog()
    lines: list[str] = []
    indices = cat.get("indices") or {}
    for t in sorted(tables):
        spec = indices.get(t) or {}
        for rel in (spec.get("relationships") or [])[:6]:
            keys = ", ".join(f'"{a}" = "{b}"' for a, b in (rel.get("keys") or {}).items())
            if rel.get("to") and keys:
                lines.append(f'{t} -> {rel["to"]} on {keys}' + (f' ({rel["description"]})' if rel.get("description") else ""))
        for name, fs in (spec.get("fields") or {}).items():
            if not isinstance(fs, dict):
                continue
            if fs.get("usual_of"):
                lines.append(f'"{name}" of {t} is the usual value of "{fs["usual_of"]}" in the same document '
                             f'(compare_groups measure: ratio({fs["usual_of"]}, {name}))')
            elif USUAL_NAME.match(name) and fs.get("description"):
                lines.append(f'"{name}" of {t} holds a usual value: {_first_sentence(str(fs["description"]), 120)}')
    for rel in ((cat.get("metrics") or {}).get("label_relationships") or [])[:8]:
        if rel.get("index") in tables and rel.get("label") and rel.get("field"):
            lines.append(f'metric label {rel["label"]} = "{rel["field"]}" of {rel["index"]}')
    return list(dict.fromkeys(lines))


def _log_tables(tables: set[str]) -> list[str]:
    """The tables among these that hold lines of text (logs, events, messages: a message field), with their
    message and level fields: what compare_logs reads."""
    from supagent.tools import _level_field, _message_field

    out = []
    for t in sorted(tables):
        msg = _message_field(t)
        if msg:
            lvl = _level_field(t)
            out.append(f'{t} (its text: "{msg}"' + (f', its level: "{lvl}"' if lvl else "") + ")")
    return out


def _tables_of(lines: dict[str, list[str]]) -> set[str]:
    from supagent.tools import _catalog

    known = set((_catalog().get("indices") or {}))
    text = " ".join(x for xs in lines.values() for x in xs)
    return {t for t in known if t in text}


def build(question: str, full: bool = True) -> dict[str, Any] | None:
    """The picture of a question: None when it names no value of the categories. `full`: the interactions,
    the data places and the joins (an investigation); else only what the named values consist of. The lines
    come in the order they matter when room is short: what is named, what it depends on and uses, where it is in
    the data with the joins and the usual values, one step further, the health checks, then what depends on it."""
    g = _graph()
    if not g["values"]:
        return None
    V, kids = g["values"], g["children"]
    seeds = [s for s in named(question, g, loose=True) if says_something(s, g)][:SEEDS]
    if not seeds:
        return None
    rank = {c: i for i, c in enumerate(g["rank"])}
    head: list[str] = []
    actors: list[int] = []
    mentioned: dict[str, list[str]] = {}

    def see(i: int) -> str:
        v = V[i]
        if v["name"] not in mentioned.setdefault(v["cat"], []):
            mentioned[v["cat"]].append(v["name"])
        return v["name"]

    def some(ids: list[int], n: int) -> str:
        return ", ".join(see(i) for i in ids[:n]) + (f" and {len(ids) - n} more" if len(ids) > n else "")

    for s in seeds:
        v = V[s]
        line = f'- {see(s)} ({v["cat"]})'
        if v["about"]:
            line += f': {_first_sentence(v["about"])}'
        if v["parents"]:
            line += ". Part of " + ", ".join(f'{see(p)} ({V[p]["cat"]})' for p in v["parents"][:4])
        parts = sorted(kids.get(s, []), key=lambda i: (rank.get(V[i]["cat"], 99), V[i]["name"].lower()))
        if parts:
            by_cat: dict[str, list[int]] = {}
            for i in parts:
                by_cat.setdefault(V[i]["cat"], []).append(i)
            line += ". Its parts: " + "; ".join(f"{c}s {some(ids, MEMBERS)}" for c, ids in by_cat.items())
            actors += [i for i in parts if i not in actors]
        else:
            actors.append(s)
        head.append(line + ".")
    out: dict[str, Any] = {"seeds": [V[s]["name"] for s in seeds], "lines": head}
    if not full:
        return out if any(kids.get(s) for s in seeds) else None
    actors = actors[:ACTORS]
    everyone = len(actors)
    who = "They" if everyone > 1 else V[actors[0]]["name"]
    further: list[int] = []
    uses: list[str] = []
    used_by: list[str] = []
    for links, incoming in ((g["out"], False), (g["in"], True)):
        by_kind: dict[str, dict[int, dict[str, Any]]] = {}
        for a in actors:
            for kind, b, note in links.get(a, []):
                if b in actors and incoming:
                    continue                       # between the actors: said once, the way it was drawn
                slot = by_kind.setdefault(kind, {}).setdefault(b, {"who": [], "notes": []})
                slot["who"].append(a)
                if note and note not in slot["notes"]:
                    slot["notes"].append(note)
        for kind in sorted(by_kind, key=lambda k: FOLLOWED.index(k) if k in FOLLOWED else 9):
            targets = by_kind[kind]
            bits = []
            for b, slot in list(targets.items())[:TARGETS]:
                extra = []
                if 1 < everyone != len(slot["who"]):
                    extra.append("only " + _some([V[a]["name"] for a in slot["who"]], 3))
                if slot["notes"]:
                    extra.append("; ".join(slot["notes"][:2])[:110])
                bits.append(f'{see(b)} ({V[b]["cat"]}' + (": " + ", ".join(extra) if extra else "") + ")")
                if not incoming and kind in FOLLOWED and b not in further and b not in actors:
                    further.append(b)
            more = f" and {len(targets) - TARGETS} more" if len(targets) > TARGETS else ""
            if incoming:
                used_by.append(f"- {IN.get(kind, kind)[0].upper() + IN.get(kind, kind)[1:]}: " + "; ".join(bits) + more + ".")
            else:
                verb = OUT.get(kind, kind) if everyone > 1 else ONE.get(kind, kind)
                uses.append(f"- {who} {verb}: " + "; ".join(bits) + more + ".")
    through: list[str] = []                        # a server: what runs on the groups it is part of (an inventory's)
    for a in actors:
        for p in V[a]["parents"]:
            runs = [x for k, x, _n in g["in"].get(p, []) if k == "runs_on" and x not in actors]
            if runs:
                through.append(f'{see(runs[0]) if len(runs) == 1 else some(runs, 8)} run'
                               f'{"s" if len(runs) == 1 else ""} on {V[a]["name"]} through its group {see(p)}')
    if through:
        used_by.insert(0, "- What runs on it through its groups: " + "; ".join(through[:6]) + ".")
    steps = []
    for b in further[:FURTHER]:                    # one step further: what they wait for, and what it consists of
        bits = []
        for kind in FOLLOWED:
            ts = [t for k, t, _n in g["out"].get(b, []) if k == kind and t not in actors]
            if ts:
                bits.append(f"{ONE[kind]} {some(ts, 6)}")
        parts = kids.get(b, [])
        if parts:
            bits.append(f'has {len(parts)} {V[parts[0]]["cat"]}(s): {some(parts, 3)}')
        if bits:
            steps.append(f'{V[b]["name"]} ' + ", ".join(bits))
    further_line = ["- One step further: " + "; ".join(steps) + "."] if steps else []
    # what to do when following them: the interactions' long explanations (the team's or the AI's), the ones an
    # investigation follows first (what they depend on, read, run on, call)
    follow, room = [], FOLLOW_CHARS
    rank_kind = {k: i for i, k in enumerate(FOLLOWED)}
    for a, kind, b in sorted(((a, k, t) for a in actors for k, t, _n in g["out"].get(a, [])),
                             key=lambda x: (rank_kind.get(x[1], 9), V[x[0]]["name"].lower())):
        text = g.get("long", {}).get((a, kind, b))
        if not text:
            continue
        bit = f'{V[a]["name"]} {ONE.get(kind, kind)} {V[b]["name"]}: {text}'
        if len(bit) > room:
            break
        follow.append(bit)
        room -= len(bit)
    follow_line = ["- What to do when following them (the map's explanations): " + " | ".join(follow)] if follow else []
    data: list[str] = []
    try:
        places = _fields_of(sorted(mentioned, key=lambda c: rank.get(c, 99)), mentioned)
    except Exception:  # pylint: disable=broad-except   (the picture without the data places)
        log.warning("supagent brief: the data places: not read", exc_info=True)
        db.session.rollback()
        places = {}
    try:                                              # what the team says each category is (categories.about)
        from supagent.knowledge.facets import about

        said = about()
    except Exception:  # pylint: disable=broad-except
        said = {}
    kinds = [f"{c}: {said[c]}" for c in sorted(mentioned, key=lambda c: rank.get(c, 99)) if said.get(c)]
    if kinds:
        data.append("- What these categories are: " + "; ".join(kinds)[:ABOUT_CHARS] + ".")
    if places:
        data.append("- In the data: " + "; ".join(f"{c}s: " + " and ".join(ps[:3]) for c, ps in places.items()) + ".")
        try:
            joins = _joins(_tables_of(places))
        except Exception:  # pylint: disable=broad-except
            joins = []
        if joins:
            data.append("- Joins and usual values (the catalog): " + "; ".join(joins[:10]) + ".")
        try:
            logs = _log_tables(_tables_of(places))
        except Exception:  # pylint: disable=broad-except
            logs = []
        if logs:
            data.append("- Their logs (compare_logs): " + "; ".join(logs[:4]) + ".")
    try:
        from supagent.tools import _catalog

        checks = list((_catalog().get("checks") or {}))
    except Exception:  # pylint: disable=broad-except
        checks = []
    checks_line = ["- Health checks (check_health): " + _some(checks, 16) + "."] if checks else []
    # the first steps of an investigation need the data places, the joins and the usual values: before what is
    # one step further (system_links gives it again)
    out.update(lines=head + uses + data + follow_line + further_line + checks_line + used_by, places=places,
               further=[V[b]["name"] for b in further])
    return out


CONNECTION = re.compile(r"(?i)\b(where|which (hosts?|servers?|nodes?|machines?)|runs?\s+on|running\s+on|hosted|deployed|"
                        r"depends?|dependenc\w*|calls?|called|uses?|used by|talks?\s+to|connect\w*|sends?|sent|"
                        r"reads?\s+from|writes?\s+to|logs?\s+go|go(es)?\s+down|is\s+down|are\s+down|down\b|"
                        r"affected|impact\w*|upstream|downstream|behind|in front|flow|path|route[sd]?|between|linked|"
                        r"relation\w*|o[uù]\s|tourne|d[ée]pend|appelle|utilise|envoie|lit\s|tombe|impact)")


def connection_question(question: str) -> bool:
    """A question about how parts are connected (where something runs, what it calls or uses, where its data or logs
    go, what a failure reaches): the system map's interactions answer it, not only what the named parts consist of."""
    return bool(CONNECTION.search(question or ""))


def brief_block(question: str, full: bool = True) -> str:
    """The picture as a block of the prompt ("" when the question names no value of the categories)."""
    try:
        b = build(question, full)
    except Exception:  # pylint: disable=broad-except   (the agent answers without it)
        log.warning("supagent brief: not built", exc_info=True)
        db.session.rollback()
        return ""
    if not b or not b["lines"]:
        return ""
    from supagent import settings

    limit = ("; when a link's explanation says what to check on a part with a limit, read those metrics over the period "
             "and compare their highest or lowest value with that limit, with its time: the team's health checks may "
             "need a breach to last") if settings.get("agent.link_limit_hint") else ""   # (0.10.4, off until measured)
    head = ("\n\nThe system around this question (from the team's categories, the interactions of the system map and "
            "the catalog: names are exact; start from it, and follow it when a finding points to another part"
            + limit + "):" if full else "\n\nWhat the question names (from the team's categories: names are exact):")
    budget = BRIEF_CHARS if full else SCOPE_CHARS
    kept, used = [], 0
    for line in b["lines"]:
        if used + len(line) > budget and kept:
            break
        kept.append(line[:budget])
        used += len(line)
    return head + "\n" + "\n".join(kept)


def named_line(question: str) -> str:
    """What the question names, in a line, for the router: each part with its category and what it is, then what
    those categories are ("" when it names no part). Short: the router's call is before every answer."""
    try:
        g = _graph()
        ids = [i for i in named(question, g, loose=True) if says_something(i, g)][:SEEDS]
        if not ids:
            return ""
        from supagent.knowledge.facets import about

        said = about()
    except Exception:  # pylint: disable=broad-except   (the router decides without it)
        db.session.rollback()
        return ""
    V = g["values"]
    parts = []
    for i in ids:
        v = V[i]
        what = _first_sentence(v["about"], 90) if v["about"] else ""
        parts.append(f'{v["name"]} ({v["cat"]}' + (f": {what}" if what else "") + ")")
    cats = [f'{c} = {said[c]}' for c in dict.fromkeys(V[i]["cat"] for i in ids) if said.get(c)]
    text = "The question names these parts of the system (the team's categories): " + "; ".join(parts) + "."
    if cats:
        text += " Categories: " + "; ".join(cats) + "."
    return text[:ROUTER_CHARS]


INPUT_KINDS = ("depends_on", "reads_from", "link")  # what a part takes in (and what sends data to it); a link a person
#                                                     drew: what it points to (both ways: both ends)


def inputs_of(names: list[str], hops: int = 2, limit: int = 14) -> list[tuple[str, str, str]]:
    """(an input, its category, the part it feeds) for these parts, up to `hops` steps up the system map: what they
    depend on, read from, or receive data from. What rows that were late before they were ready waited for. A part
    that has members (a family, a group of applications) stands for its members."""
    g = _graph()
    V = g["values"]
    frontier: list[int] = []
    for raw in names[:8]:
        for i in (named(str(raw), g) or g["names"].get(" ".join(str(raw).lower().split()), []))[:2]:
            takes_in = any(kind in INPUT_KINDS for kind, _b, _n in g["out"].get(i, []))
            frontier += [i] if takes_in or not g["children"].get(i) else g["children"][i][:12]
    seen, out = set(frontier), []
    for _ in range(max(1, hops)):
        nxt: list[int] = []
        for i in frontier:
            ups = [b for kind, b, _n in g["out"].get(i, []) if kind in INPUT_KINDS]
            ups += [a for kind, a, _n in g["in"].get(i, []) if kind == "sends_to"]
            for b in ups:
                if b not in seen:
                    seen.add(b)
                    nxt.append(b)
                    out.append((V[b]["name"], V[b]["cat"], V[i]["name"]))
        frontier = nxt
        if len(out) >= limit or not frontier:
            break
    return out[:limit]


MEMBERS_MAX = 16      # a part made of more parts than this is not expanded (a subject of forty applications)


def members(names: list[str]) -> dict[str, list[str]]:
    """{a named part: the parts it consists of} for the named parts the system map says are made of other parts (a
    pool's servers, a cluster's nodes), by name: what the health checks and the records of such a part are looked
    for on too (agent.with_parts). A part with more than MEMBERS_MAX parts is left as it is (name the ones meant)."""
    g = _graph()
    V = g["values"]
    out: dict[str, list[str]] = {}
    for raw in names[:8]:
        for i in (named(str(raw), g) or g["names"].get(" ".join(str(raw).lower().split()), []))[:1]:
            kids = [k for k in dict.fromkeys(g["children"].get(i, [])) if k != i]
            if kids and len(kids) <= MEMBERS_MAX:
                out[V[i]["name"]] = [V[k]["name"] for k in kids]
    return out


CHAINED = ("depends_on", "reads_from", "calls", "sends_to", "triggers", "routes_to", "link")   # a flow, a route
CHAIN_MAX = 40                  # chains given, each way


def chains(ids: list[int], g: dict[str, Any], depth: int) -> dict[str, list[str]]:
    """(0.10.6) The paths of the map from these parts, `depth` links at most (the user: "follow many paths while
    investigating"): "leads_to", what each part depends on, calls, reads, sends to, routes to, and so on further,
    each a chain "a calls b > b reads from c" with where its last part runs; "led_from", what leads to them, the same
    way back (what a failure of theirs reaches): what runs on them (a server's parts), the whole they are part of (a
    server's group: what runs on the group; an application's service: the application), free of the depth, and what
    depends on those. A part already in a chain ends it (no circle)."""
    V = g["values"]

    def where(i: int) -> str:
        on = [V[b]["name"] for k, b, _n in g["out"].get(i, []) if k == "runs_on"][:3]
        return f" (runs on {', '.join(on)})" if on else ""

    def verb(k: str) -> str:
        return ONE.get(k, "is linked to" if str(k).startswith("link") else str(k).replace("_", " "))

    def nexts(i: int, back: bool, seen: list[int]) -> list[tuple[int, str, bool]]:
        """(the next part, the step's words, whether the step counts in the depth)"""
        if not back:
            return [(b, f'{V[i]["name"]} {verb(k)} {V[b]["name"]}', True) for k, b, _n in g["out"].get(i, [])
                    if (k in CHAINED or str(k).startswith("link")) and b not in seen]
        out = [(a, f'{V[a]["name"]} {verb(k)} {V[i]["name"]}', True) for k, a, _n in g["in"].get(i, [])
               if (k in CHAINED or k == "runs_on" or str(k).startswith("link")) and a not in seen]
        out += [(w, f'{V[i]["name"]} is part of {V[w]["name"]}', False) for w in V[i].get("parents", [])
                if w in V and w not in seen]
        return out

    def ended(steps: list[str], last: int) -> str:
        return " > ".join(steps) + ("" if " runs on " in steps[-1] else where(last))

    out: dict[str, list[str]] = {"leads_to": [], "led_from": []}
    for key, back in (("leads_to", False), ("led_from", True)):
        got = out[key]
        stack = [(i, [i], [], 0) for i in ids]
        while stack and len(got) < CHAIN_MAX:
            i, seen, steps, hops = stack.pop(0)
            nxt = nexts(i, back, seen)
            if not nxt:
                if steps:
                    got.append(ended(steps, i))
                continue
            for b, step, counts in nxt:
                n = hops + (1 if counts else 0)
                if n >= depth and counts:
                    got.append(ended(steps + [step], b))
                else:
                    stack.append((b, seen + [b], steps + [step], n))
                if len(got) >= CHAIN_MAX:
                    break
    return {k: v for k, v in out.items() if v}


IMPACT_MAX = 30                 # parts listed as reached, per server or group


def impact(places: list[int], g: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """(0.10.6) What the failure of a server or a group reaches, in the words an answer takes ("if db-01 is down,
    which applications stop working?" was answered with what runs on db-01: the applications depending on those
    were in the chains of "led_from", not read): what runs on it (with where else it runs: it may go on there), on
    its servers (a group), on the group it is part of (it may go on on the group's other servers), then what
    depends on, calls, reads from or sends to those, and what does so to these, each with the step that reaches it."""
    from supagent.knowledge.datalinks import SERVERISH

    V = g["values"]

    def label(i: int) -> str:
        return f'{V[i]["name"]} ({V[i]["cat"]})'

    def on(i: int) -> list[int]:
        return [a for k, a, _n in g["in"].get(i, []) if k == "runs_on"]

    def placed(a: int, here: int) -> str:            # a part that runs elsewhere too may go on there: not on
        mine = {here, *V[here].get("parents", []), *g["children"].get(here, [])}   # what fails with it (its own
        other = [V[b]["name"] for k, b, _n in g["out"].get(a, []) if k == "runs_on" and b not in mine][:3]  # group,
        return f'{V[a]["name"]} ({V[a]["cat"]}; also runs on {", ".join(other)})' if other else label(a)  # members)

    res: dict[str, dict[str, Any]] = {}
    for p in places[:3]:
        seen = {p}
        mine = [a for a in on(p) if a not in seen]
        seen.update(mine)
        groups: dict[str, list[int]] = {}
        for w in V[p].get("parents", []):
            if w in V and w not in seen and SERVERISH.search(V[w]["cat"] or ""):
                theirs = [a for a in on(w) if a not in seen]
                seen.update(theirs)
                if theirs:
                    groups[V[w]["name"]] = theirs
        members: dict[str, list[int]] = {}           # a group: what runs on each of its servers
        for c in g["children"].get(p, [])[:20]:
            if c in V and SERVERISH.search(V[c]["cat"] or ""):
                theirs = [a for a in on(c) if a not in mine and a != p]
                if theirs:
                    members[V[c]["name"]] = theirs
        seen.update(a for ids in members.values() for a in ids)
        item: dict[str, Any] = {}
        if mine:
            item["runs_on_it"] = [placed(a, p) for a in mine[:IMPACT_MAX]]
        if members:
            item["runs_on_its_servers"] = {c: [label(a) for a in ids[:IMPACT_MAX]] for c, ids in members.items()}
        if groups:
            item["runs_on_its_group (may go on on the group's other servers)"] = {
                w: [label(a) for a in ids[:IMPACT_MAX]] for w, ids in groups.items()}
        frontier = list(dict.fromkeys(mine + [a for ids in members.values() for a in ids]
                                      + [a for ids in groups.values() for a in ids]))
        for key in ("then_through_them", "and_further"):
            reached, nxt = [], []
            for b in frontier:
                for k, a, _n in g["in"].get(b, []):
                    if (k in CHAINED or str(k).startswith("link")) and a not in seen and len(reached) < IMPACT_MAX:
                        seen.add(a)
                        nxt.append(a)
                        verb = ONE.get(k, "is linked to" if str(k).startswith("link") else str(k).replace("_", " "))
                        reached.append(f'{label(a)} {verb} {V[b]["name"]}')
            if reached:
                item[key] = reached
            frontier = nxt
        if item:
            res[V[p]["name"]] = item
    return res


CATEGORY_VALUES = 80             # the values a category's listing gives


def category_named(raw: str, g: dict[str, Any]) -> str | None:
    """(0.10.6) The category a name is ("application", "applications", "the servers"), or None."""
    w = " ".join(re.sub(r"^(the|all|every|our|which)\s+", "", str(raw).strip().lower()).split())
    have = {c.lower() for c in g.get("rank") or []}
    for c in (w, w[:-1] if w.endswith("s") else w, w[:-2] if w.endswith("es") else w):
        if c in have:
            return c
    return None


def category_values(cat: str, g: dict[str, Any]) -> dict[str, Any]:
    """(0.10.6) A category of the System map as the agent goes on from it: what it is, its values (the ones of
    another value of it named "a > b"), and how many."""
    from supagent.knowledge.facets import about, inside

    V = g["values"]
    mine = sorted((v for v in V.values() if v["cat"] == cat), key=lambda v: v["name"].lower())
    ids = {v["id"] for v in mine}

    def label(v: dict[str, Any]) -> str:
        ups = [V[p]["name"] for p in v["parents"] if p in ids][:1]
        return f"{ups[0]} > {v['name']}" if ups else v["name"]

    out: dict[str, Any] = {"values": [label(v) for v in mine][:CATEGORY_VALUES], "count": len(mine)}
    said = about(True).get(cat)
    if said:
        out["what"] = said
    if inside().get(cat):
        out["inside"] = inside()[cat]
    if len(mine) > CATEGORY_VALUES:
        out["note"] = f"the first {CATEGORY_VALUES} of {len(mine)}: search_knowledge finds the others by their words"
    return out


def links_of(names: list[str], depth: int = 1) -> dict[str, Any]:
    """What the system map says of these parts (the tool system_links): each one's category, what it is, what it
    is part of and consists of, its interactions both ways, where its category is in the data; (0.10.6) with
    `depth` 2 or 3, the chains of links from them and to them (chains())."""
    g = _graph()
    V, kids = g["values"], g["children"]
    out: list[dict[str, Any]] = []
    unknown: list[str] = []
    cats: dict[str, list[str]] = {}
    listed: dict[str, Any] = {}
    for raw in names[:8]:
        ids = named(str(raw), g) or g["names"].get(" ".join(str(raw).lower().split()), [])
        cat = None if ids else category_named(str(raw), g)
        if cat:                                       # (0.10.6) a category's name: its values, to go on from
            listed[cat] = category_values(cat, g)
            continue
        if not ids:
            unknown.append(str(raw))
            continue
        for i in ids[:2]:
            v = V[i]
            cats.setdefault(v["cat"], []).append(v["name"])
            item: dict[str, Any] = {"name": v["name"], "category": v["cat"]}
            if v["about"]:
                item["what"] = v["about"][:300]
            if v["parents"]:
                item["part_of"] = [f'{V[p]["name"]} ({V[p]["cat"]})' for p in v["parents"][:6]]
            parts = kids.get(i, [])
            if parts:
                item["parts"] = [f'{V[p]["name"]} ({V[p]["cat"]})' for p in parts[:40]]
                if len(parts) > 40:
                    item["parts_total"] = len(parts)
            follow: list[str] = []
            for key, links, verbs in (("it", g["out"], OUT), ("others", g["in"], IN)):
                rel: dict[str, list[str]] = {}
                for kind, b, note in links.get(i, [])[:40]:
                    label = (verbs.get(kind, kind) + "s") if key == "it" else verbs.get(kind, kind)
                    rel.setdefault(label, []).append(f'{V[b]["name"]} ({V[b]["cat"]})' + (f": {note[:120]}" if note else ""))
                    text = g.get("long", {}).get((i, kind, b) if key == "it" else (b, kind, i))
                    if text and len(follow) < 8:
                        a_, b_ = (V[i]["name"], V[b]["name"]) if key == "it" else (V[b]["name"], V[i]["name"])
                        follow.append(f"{a_} {ONE.get(kind, kind)} {b_}: {text[:400]}")
                if rel:
                    item[key] = rel
            if follow:
                item["what_to_do_when_following"] = follow
            out.append(item)
    res: dict[str, Any] = {"parts": out}
    if listed:
        res["categories_listed"] = listed
    ids = [i for raw in names[:8] for i in (named(str(raw), g) or g["names"].get(" ".join(str(raw).lower().split()), []))[:2]]
    from supagent.knowledge.datalinks import SERVERISH   # (0.10.6) a server or a group named: what its failure

    places = [i for i in ids if SERVERISH.search(V[i]["cat"] or "")]   # reaches comes with it ("if db-01 is down,
    if depth and int(depth) > 1 and out:                                # which applications stop?": what runs on it
        paths = chains(ids, g, min(int(depth), 4))                      # was not the answer)
        if paths:
            res["paths"] = paths
    elif places:
        led = chains(places, g, 2).get("led_from")
        if led:
            res["paths"] = {"led_from": led}
    reach = impact(places, g) if places else {}
    if reach:
        res["if_it_fails"] = reach
    if unknown:
        res["not_in_the_map"] = unknown
    try:
        places = _fields_of(list(cats), cats)
    except Exception:  # pylint: disable=broad-except
        db.session.rollback()
        places = {}
    if places:
        res["in_the_data"] = places
        joins = _joins(_tables_of(places))
        if joins:
            res["joins_and_usual_values"] = joins[:12]
    try:
        from supagent.knowledge.facets import about

        said = about()
        kinds = {c: said[c] for c in cats if said.get(c)}
        if kinds:
            res["categories"] = kinds
    except Exception:  # pylint: disable=broad-except
        db.session.rollback()
    return res
