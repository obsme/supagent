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
# (0.10.7) the map's explanations the AI wrote, said so where the agent reads them ("What does our runbook say to check
# when <an alert> fires?": the AI's advice on following the alert's link to the part it watches was given as the
# runbook's steps, the runbook's own steps, found by the same search, left out)
AI_EXPLAINED = "explained by the AI"
_CACHE: dict[str, Any] = {"stamp": None, "graph": None, "fields": {}}
_LOCK = threading.Lock()


def ai_explained(who: str | None) -> str:
    """(0.10.7) What the agent is told of who wrote a link's explanations: "explained by the AI" (the AI alone),
    "explained by the team and the AI" (the AI completed a person's); "" for a person's own words."""
    who = (who or "").strip()
    if who == "llm":
        return AI_EXPLAINED
    return "explained by the team and the AI" if who.endswith(" and the AI") else ""


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
    synonyms: dict[int, list[str]] = {}
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
        synonyms[f.id] = [str(x) for x in (f.synonyms or [])]
    for alias, ids in _host_aliases(values, synonyms).items():   # (0.10.8) a server by its short name too
        names.setdefault(alias, ids)
    for alias, ids in _qualified_aliases(values, synonyms).items():   # (0.10.9.1) "pool-a (production)" asked as
        names.setdefault(alias, ids)                                  # pool-a
    for v in values.values():
        v["parents"] = [p for p in v["parents"] if p in values and p != v["id"]]
        for p in v["parents"]:
            children.setdefault(p, []).append(v["id"])
    out_links: dict[int, list[tuple[str, int, str]]] = {}
    in_links: dict[int, list[tuple[str, int, str]]] = {}
    long: dict[tuple[int, str, int], str] = {}        # what to do when following an interaction (its long explanation)
    from supagent.knowledge.sysmap import generic

    from supagent.knowledge.interactions import TOPICS

    subjects: dict[int, list[int]] = {}               # (0.10.6.2) a part's subjects and a subject's parts: said,
    long_by: dict[tuple[int, str, int], str] = {}     # (0.10.7) who wrote it, when the AI did
    rows = db.session.query(Link.a_ref, Link.b_ref, Link.kind, Link.note, Link.detail, Link.both_ways,
                            Link.explained_by).filter(
        Link.a_ref.like("facet:%"), Link.b_ref.like("facet:%"), Link.status == "approved", Link.kind != PART_OF)
    for a_ref, b_ref, kind, note, detail, both, who in rows:
        a, b = a_ref.split(":", 1)[1], b_ref.split(":", 1)[1]
        if a.isdigit() and b.isdigit() and int(a) in values and int(b) in values:
            if kind == "about" and (values[int(a)]["cat"] in TOPICS or values[int(b)]["cat"] in TOPICS):
                for x, y in ((int(a), int(b)), (int(b), int(a))):   # never a path: a subject ties every part it
                    if y not in subjects.setdefault(x, []):         # is about to every other one
                        subjects[x].append(y)
                continue
            kind = "link" if generic(kind) else kind      # a person's link: "is linked to", with what it is
            ways = [(int(a), int(b)), (int(b), int(a))] if both else [(int(a), int(b))]
            for x, y in ways:
                out_links.setdefault(x, []).append((kind, y, (note or "").strip()))
                in_links.setdefault(y, []).append((kind, x, (note or "").strip()))
                if (detail or "").strip():
                    long[(x, kind, y)] = " ".join(detail.split())
                    if ai_explained(who):
                        long_by[(x, kind, y)] = ai_explained(who)
    loose, slips = loose_index(names)
    g = {"values": values, "names": names, "children": children, "out": out_links, "in": in_links, "rank": cats,
         "long": long, "long_by": long_by, "loose": loose, "slips": slips, "subjects": subjects}
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
            if not ids and loose and n == 2 and all(w.isalpha() for w in words):
                ids = g["names"].get(" ".join(reversed(key.split())))   # (0.10.10) "the quokka team": team quokka
            if not ids and n == 1:                     # (0.10.8) web01.corp.example, web01:9100 asked, the
                ids = _by_host(key, g)                 # server named web01 on the map
            if not ids:
                continue
            if n == 1 and (len(key) < 3 or key in STOP) and not any(g["values"][x]["name"] == words[0] for x in ids):
                continue
            found += [x for x in ids if x not in found]
            hit = n
            break
        i += hit or 1
    return found


QUALIFIED = re.compile(r"^(.+?)\s+\(([^()]+)\)$")       # "pool-a (production)", "web (ops prod)", "billing (group)"


def _qualified_aliases(values: dict[int, dict[str, Any]], synonyms: dict[int, list[str]]) -> dict[str, list[int]]:
    """(0.10.9.1) A value named with an environment or "group" between brackets ("pool-a (production)", "web (ops
    prod)": an inventory group of one environment) is asked without it ("what runs on pool-a?"): the name without
    the brackets names every value written so (the group of each environment). A name of the map's own is never
    taken, nor a word of every question."""
    from supagent.knowledge.consolidate import ENV, GENERIC, words
    from supagent.knowledge.describe import STOP

    out: dict[str, list[int]] = {}
    for v in values.values():
        for n in [v["name"]] + synonyms.get(v["id"], []):
            m = QUALIFIED.match(" ".join(str(n).lower().split()))
            if not m or len(m.group(1)) < 3 or m.group(1) in STOP or m.group(1) in GENERIC:
                continue
            said = set(words(m.group(2)))
            if (said & ENV or said <= {"group", "groupe", "groups"}) and v["id"] not in out.setdefault(m.group(1), []):
                out[m.group(1)].append(v["id"])
    return {a: ids for a, ids in out.items() if ids}


def _host_aliases(values: dict[int, dict[str, Any]], synonyms: dict[int, list[str]]) -> dict[str, list[int]]:
    """(0.10.8, the team: a server is named by its full name in the data and by its short one in a question) the
    shorter names of the servers of the map (web01 for web01.corp.example, for web01:9100), each with the
    servers named so: a name of the map's own is never taken."""
    from supagent.knowledge import ambiguity, resolve
    from supagent.knowledge.catkind import serverish
    from supagent.knowledge.describe import STOP
    from supagent.knowledge.values import host_aliases

    common = STOP | resolve.GENERIC | ambiguity.GENERIC   # a word of every question never names a server (graph for
    out: dict[str, list[int]] = {}                        # graph.corp.example: "show the graph of the errors")
    for v in values.values():
        if serverish(v["cat"]):                          # (0.10.9.2) by its name or what its description says
            for n in [v["name"]] + synonyms.get(v["id"], []):
                for alias in host_aliases(n):
                    if alias not in common and v["id"] not in out.setdefault(alias, []):
                        out[alias].append(v["id"])
    return {a: ids for a, ids in out.items() if ids}


def _by_host(key: str, g: dict[str, Any]) -> list[int]:
    """(0.10.8) The servers of the map a full name or an address names (web01.corp.example, web01:9100 for a
    server named web01), never another server of the same short name (web01.dmz.example)."""
    from supagent.knowledge.catkind import serverish
    from supagent.knowledge.values import host_aliases, same_host

    out: list[int] = []
    for alias in host_aliases(key):
        for x in g["names"].get(alias, []):
            v = g["values"].get(x) or {}
            if x not in out and serverish(v.get("cat")) and same_host(key, v.get("name", "")):
                out.append(x)
    return out


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
        by = g.get("long_by", {}).get((a, kind, b))
        bit = f'{V[a]["name"]} {ONE.get(kind, kind)} {V[b]["name"]}' + (f" ({by})" if by else "") + f": {text}"
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
    try:                                              # (0.10.7) where the servers the parts run on are in the data
        hosts = _servers_in_data(seeds, g)            # ("which user held the long transaction?": the database's own
    except Exception:  # pylint: disable=broad-except   logs on its server named it; the answer said none had it)
        log.warning("supagent brief: the servers' data places: not read", exc_info=True)
        db.session.rollback()
        hosts = ""
    if hosts:
        data.insert(0, hosts)
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


def _servers_in_data(seeds: list[int], g: dict[str, Any], servers: int = 3, per: int = 3) -> str:
    """(0.10.7) Where the servers the named parts run on are in the data: the fields of indices holding their names
    (their own logs, jobs and records), a line for the picture."""
    from supagent.knowledge.valueindex import places as value_places

    V = g["values"]
    hosts: list[int] = []
    for s in seeds:
        for k, b, _n in g["out"].get(s, []):
            if k == "runs_on" and b in V and _serverish(b, g) and not any(
                    c in V and _serverish(c, g) for c in g["children"].get(b, [])):
                hosts.append(b)
    bits = []
    for b in list(dict.fromkeys(hosts))[:servers]:
        found = [p for p in value_places([V[b]["name"]]) if p["kind"] == "field"][:per]
        if found:
            bits.append(f'{V[b]["name"]}: ' + ", ".join(
                f'field "{p["name"]}" of {", ".join(p["of"][:2])} ({p["database"]})' for p in found))
    return ("- Where the servers they run on are in the data (their own logs and records): " + "; ".join(bits) + "."
            if bits else "")


def server_places(question: str, servers: int = 3, per: int = 3, logs_only: bool = False) -> list[tuple[str, str, list[str]]]:
    """(0.10.7) (server, field, tables) of where the servers the question's parts run on are in the data: the fields of
    indices that hold the servers' names (their own logs and records), as _servers_in_data says them; `logs_only`: the
    log indices among them (their kind detected as logs), not an inventory or the alerts that name the server."""
    from supagent.knowledge.valueindex import places as value_places
    from supagent.models import KObject

    def is_log(table: str) -> bool:
        ix = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == table,
                                               KObject.gone_at.is_(None)).first()
        kind = (ix.stats or {}).get("kind") if ix is not None else None
        return isinstance(kind, dict) and kind.get("kind") == "logs"

    g = _graph()
    V = g["values"]
    hosts: list[int] = []
    for s in [i for i in named(question, g) if says_something(i, g)][:SEEDS]:
        for k, b, _n in g["out"].get(s, []):
            if k == "runs_on" and b in V and _serverish(b, g) and not any(
                    c in V and _serverish(c, g) for c in g["children"].get(b, [])):
                hosts.append(b)
    out: list[tuple[str, str, list[str]]] = []
    for b in list(dict.fromkeys(hosts))[:servers]:
        found = [p for p in value_places([V[b]["name"]]) if p["kind"] == "field"]
        for p in found if logs_only else found[:per]:
            tables = [str(t) for t in p["of"] if not logs_only or is_log(str(t))]
            if tables:
                out.append((V[b]["name"], str(p["name"]), tables))
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
TO_CHAINS = 6                   # (0.10.7) with a route asked (to): the other chains given, each way


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
HELD_MAX = 200                  # (0.10.7) servers looked at under a place that holds servers (a rack, a room...)
HELD_SHOWN = 40                 # and named


def _serverish(i: int, g: dict[str, Any]) -> bool:
    from supagent.knowledge.catkind import serverish

    return serverish(g["values"][i]["cat"])


def held(p: int, g: dict[str, Any]) -> tuple[list[int], list[int]]:
    """(0.10.7) The servers a place holds (a rack, a room, a datacenter, a cluster) and its other parts inside (its
    switches, a cluster's namespaces, a broker's topics): its parts, their parts... down to four levels; a group of
    servers among them is opened to its servers; a server's own parts (its filesystems) are not looked into."""
    V, servers, inner, seen, frontier = g["values"], [], [], {p}, [p]
    for _level in range(4):
        nxt = []
        for i in frontier:
            for c in g["children"].get(i, []):
                if c in seen or c not in V:
                    continue
                seen.add(c)
                group = _serverish(c, g) and any(k in V and _serverish(k, g) for k in g["children"].get(c, []))
                if _serverish(c, g) and not group:
                    servers.append(c)
                else:
                    nxt.append(c)
                    if not group:
                        inner.append(c)
        frontier = nxt
        if len(servers) >= HELD_MAX or len(inner) >= HELD_MAX * 4 or not frontier:
            break
    return servers[:HELD_MAX], inner


def is_place(i: int, g: dict[str, Any]) -> bool:
    """(0.10.7) What a failure question can be about: a server, a group of servers, or what holds servers."""
    return _serverish(i, g) or bool(held(i, g)[0])


# (0.10.7) a person's link whose start looks at, describes, guards or owns its end: the end's failure does not reach
# its start (a dashboard that shows a database is not down with it; "secured by", "protected by" are uses)
NOT_A_USE = re.compile(r"^(?:shows?|displays?|graphs?|charts?|plots?|documents?|describes?|explains?|monitors?|"
                       r"watch(?:es)?|observes?|alerts? on|scrapes?|probes?|checks?|secures?|protects?|guards?|owns?|"
                       r"owned by|maintained by|managed by|operated by|run by|supported by)\b", re.I)


def _said(k: str, note: str) -> str:
    """A link in words: a person's link with its own words ("archives WAL to"), else its kind's."""
    if str(k).startswith("link") and note and len(note) <= 60:
        return note
    return ONE.get(k, "is linked to" if str(k).startswith("link") else str(k).replace("_", " "))


def _users(b: int, g: dict[str, Any]) -> list[tuple[int, str]]:
    """What uses b: the links to it that a failure of b reaches (a flow, a route, a person's link but one that only
    looks at, guards or owns it), with their words."""
    out = []
    for k, a, n in g["in"].get(b, []):
        if k in CHAINED or str(k).startswith("link"):
            w = _said(k, n)
            if not (str(k).startswith("link") and NOT_A_USE.match(w)):
                out.append((a, w))
    return out


def held_upstream(p: int, g: dict[str, Any], limit: int = 16) -> list[str]:
    """(0.10.7) What a place that holds servers depends on outside it: the links of the place and of its parts inside
    (its switches, not its servers' own) to parts outside it (a rack's power units, its top-of-rack switches' uplinks to
    the core): where a cause shared by all its servers is ("many servers of one rack logged receive errors": the
    uplink's port), each with its words; links that only show or own a part are not dependencies."""
    V = g["values"]
    servers, inner = held(p, g)
    if not servers:
        return []
    inside = {p, *servers, *inner}
    out: list[str] = []
    for a in [p] + [i for i in inner if not _serverish(i, g)]:
        for k, b, n in g["out"].get(a, []):
            if b in inside or b not in V or not (k in CHAINED or str(k).startswith("link")):
                continue
            w = _said(k, n)
            if str(k).startswith("link") and NOT_A_USE.match(w):
                continue
            out.append(f'{V[a]["name"]} ({V[a]["cat"]}) {w} {V[b]["name"]} ({V[b]["cat"]})')
            if len(out) >= limit:
                return out
    return out


def _held_impact(p: int, g: dict[str, Any], label: Any) -> tuple[dict[str, Any], list[int], set[int]]:
    """(0.10.7) What the failure of a place that holds servers reaches ("if the rack loses power, which stores go
    down?" had only the rack's parts, and the impact of three of its servers per call): its servers, what runs only
    on them (goes down with it) and what runs on others too (may go on there), the groups its servers are part of."""
    V = g["values"]
    servers, inner = held(p, g)
    here, within = set(servers), {p, *inner}
    item: dict[str, Any] = {}
    if not servers:
        return item, [], set()
    names = [V[s]["name"] for s in servers]
    item["servers_in_it"] = f"{len(servers)}{'+' if len(servers) >= HELD_MAX else ''}: " + \
        ", ".join(names[:HELD_SHOWN]) + (", ..." if len(servers) > HELD_SHOWN else "")

    def inside(t: int) -> bool:                     # a place a part runs on that fails with p
        if t in within or t in here:
            return True
        kids = [k for k in g["children"].get(t, []) if k in V and _serverish(k, g)]
        return bool(kids) and all(k in here for k in kids)

    runs: dict[int, list[int]] = {}                  # what runs on its servers, on it, on its parts (a namespace)
    todo = servers + [p] + inner
    for _round in range(3):
        for s in todo:
            for k, a, _n in g["in"].get(s, []):
                if k == "runs_on" and a != p and a not in within and s not in runs.get(a, []):
                    runs.setdefault(a, []).append(s)
        todo = [a for a in runs if a not in here and _serverish(a, g)
                and not [b for k, b, _n in g["out"].get(a, []) if k == "runs_on" and not inside(b)]]
        here.update(todo)                            # a server that runs only there (a VM on its hypervisors) goes
        if not todo:                                 # down with it, and so does what runs only on that one
            break
    down, on = [], []
    for a, where in runs.items():
        other = [V[b]["name"] for k, b, _n in g["out"].get(a, []) if k == "runs_on" and not inside(b)]
        on_what = ", ".join(V[s]["name"] for s in where[:4]) + (", ..." if len(where) > 4 else "")
        if other:
            on.append((a, f"{label(a)} on {on_what}; also runs on {', '.join(other[:3])}"))
        else:
            down.append((a, f"{label(a)} on {on_what}"))
    if down:
        item["goes_down_with_it (runs only on its servers)"] = [t for _a, t in down[:IMPACT_MAX]]
    if on:
        item["may_go_on (runs on other servers too)"] = [t for _a, t in on[:IMPACT_MAX]]
    groups: dict[int, int] = {}
    for s in servers:
        for w in V[s].get("parents", []):
            if w != p and w in V and w not in here and _serverish(w, g):
                groups[w] = groups.get(w, 0) + 1
    shares = []
    for w, n in groups.items():
        total = len([k for k in g["children"].get(w, []) if k in V and _serverish(k, g)])
        if total:
            shares.append((n / max(total, 1), f"{label(w)}: {n} of its {total} servers here"))
    if shares:
        item["its_servers_are_in (groups)"] = [t for _r, t in sorted(shares, key=lambda x: -x[0])[:12]]
    return item, [a for a, _t in down] + [a for a, _t in on], set(runs) | here | within


def impact(places: list[int], g: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """(0.10.6) What the failure of a server or a group reaches, in the words an answer takes ("if db-01 is down,
    which applications stop working?" was answered with what runs on db-01: the applications depending on those
    were in the chains of "led_from", not read): what runs on it (with where else it runs: it may go on there), on
    its servers (a group), on the group it is part of (it may go on on the group's other servers), then what
    depends on, calls, reads from or sends to those, and what does so to these, each with the step that reaches it.
    (0.10.7) A place that holds servers (a rack, a room, a cluster) too: _held_impact(); and what uses the place
    itself (a database archiving its WAL to a server), a person's link said with its own words."""
    from supagent.knowledge.catkind import serverish

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
        if not serverish(V[p]["cat"]):              # (0.10.7) a place that holds servers: a rack, a room...
            item, frontier, gone = _held_impact(p, g, label)
            up = held_upstream(p, g)
            if up:                                     # (0.10.7) what it stands on outside: power, uplinks
                item["it_depends_on (outside it)"] = up
            seen |= gone
            inner = held(p, g)
            uses = [(a, w, b) for b in [p] + inner[1] + inner[0] for a, w in _users(b, g) if a not in seen]
            if uses:
                item["uses_it"] = [f'{label(a)} {w} {V[b]["name"]}' for a, w, b in uses[:IMPACT_MAX]]
                seen.update(a for a, _w, _b in uses)
                frontier = frontier + [a for a, _w, _b in uses]
            _further(item, frontier, seen, g, label)
            if item:
                res[V[p]["name"]] = item
            continue
        mine = [a for a in on(p) if a not in seen]
        seen.update(mine)
        groups: dict[str, list[int]] = {}
        for w in V[p].get("parents", []):
            if w in V and w not in seen and serverish(V[w]["cat"]):
                theirs = [a for a in on(w) if a not in seen]
                seen.update(theirs)
                if theirs:
                    groups[V[w]["name"]] = theirs
        members: dict[str, list[int]] = {}           # a group: what runs on each of its servers
        for c in g["children"].get(p, [])[:20]:
            if c in V and serverish(V[c]["cat"]):
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
        uses = [(a, w) for a, w in _users(p, g) if a not in seen]    # (0.10.7) what uses the server itself (a
        if uses:                                                      # database archiving its WAL to it)
            item["uses_it"] = [f'{label(a)} {w} {V[p]["name"]}' for a, w in uses[:IMPACT_MAX]]
            seen.update(a for a, _w in uses)
        frontier = list(dict.fromkeys(mine + [a for ids in members.values() for a in ids]
                                      + [a for ids in groups.values() for a in ids] + [a for a, _w in uses]))
        _further(item, frontier, seen, g, label)
        if item:
            res[V[p]["name"]] = item
    return res


def _further(item: dict[str, Any], frontier: list[int], seen: set[int], g: dict[str, Any], label: Any) -> None:
    """What depends on, calls, reads or uses what a failure reached, then what does so to these."""
    V = g["values"]
    for key in ("then_through_them", "and_further"):
        reached, nxt = [], []
        for b in frontier:
            for a, w in _users(b, g):
                if a not in seen and len(reached) < IMPACT_MAX:
                    seen.add(a)
                    nxt.append(a)
                    reached.append(f'{label(a)} {w} {V[b]["name"]}')
        if reached:
            item[key] = reached
        frontier = nxt


CATEGORY_VALUES = 80             # the values a category's listing gives


def category_named(raw: str, g: dict[str, Any]) -> str | None:
    """(0.10.6) The category a name is ("application", "applications", "the servers"), or None."""
    w = " ".join(re.sub(r"^(the|all|every|our|which)\s+", "", str(raw).strip().lower()).split())
    have = {c.lower() for c in g.get("rank") or []}
    for c in (w, w[:-1] if w.endswith("s") else w, w[:-2] if w.endswith("es") else w):
        if c in have:
            return c
    return None


CHAT_VALUES = 3                 # (0.10.7) values of the chat a follow-up's category stands for, at most


def chat_values(question: str, history: list[dict] | None, n: int = CHAT_VALUES) -> list[str]:
    """(0.10.7) "Which metrics show it on the database side?" after answers about a database: a follow-up that names
    a category ("the database", "which servers") and no value of its own means the values of that category the chat
    named, the latest message first; [] when it names a value or no category."""
    g = _graph()
    if not g["values"] or any(says_something(i, g) for i in named(question, g)):
        return []
    have = {c.lower() for c in g.get("rank") or []}
    words = re.findall(r"[a-z][a-z-]*", (question or "").lower())
    cats = {c for w in words for c in (w, w[:-1] if w.endswith("s") else w, w[:-2] if w.endswith("es") else w)
            if c in have}
    joined = f' {" ".join(words)} '
    cats |= {c for c in have if " " in c and f" {c} " in joined}      # "message broker", "server group"
    if not cats:
        return []
    out: list[str] = []
    for h in reversed(history or []):
        for i in named(str(h.get("content") or ""), g):
            v = g["values"][i]
            if v["cat"] in cats and v["name"] not in out:
                out.append(v["name"])
    return out[:n]


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


PATH_STEPS = 8                  # (0.10.7) links of a path from one part to another at most
PATHS_SHOWN = 3                 # and paths given


def paths_between(src: list[int], dst: set[int], g: dict[str, Any]) -> list[str]:
    """(0.10.7) The routes from parts to another one over what flows (calls, routes, resolves, depends on, reads,
    sends, a person's link but one that only shows or owns), the shortest first, each step said with its words
    ("routes to / calls" for two links between the same parts): "what does a request to the site go through before
    it reaches the payment gateway?" (the map held routes of four and six links; the answer took one step of each).
    A route that is another one with a detour (all of its parts and more) is left out: the routes given go through
    different parts."""
    from collections import deque

    V = g["values"]

    def steps(a: int) -> dict[int, list[str]]:
        nxt: dict[int, list[str]] = {}
        for k, b, n in g["out"].get(a, []):
            if b not in V or not (k in CHAINED or str(k).startswith("link")):
                continue
            w = _said(k, n)
            if str(k).startswith("link") and NOT_A_USE.match(w):
                continue
            if w not in nxt.setdefault(b, []):
                nxt[b].append(w)
        return nxt

    passed: dict[int, int] = {}
    found: list[tuple[int, ...]] = []
    q = deque([(s,) for s in src if s in V])
    while q and len(found) < PATHS_SHOWN * 10:
        path = q.popleft()
        a = path[-1]
        if a in dst and len(path) > 1:
            found.append(path)
            continue
        passed[a] = passed.get(a, 0) + 1
        if passed[a] > PATHS_SHOWN * 4 or len(path) > PATH_STEPS:
            continue
        for b in steps(a):
            if b not in path:
                q.append(path + (b,))
    chosen: list[tuple[int, ...]] = []
    for p in found:                                     # the shortest first; a detour of a route given (all of its
        inner = set(p[1:-1])                            # parts and more, from the same start) is not another route
        if any(c[0] == p[0] and set(c[1:-1]) <= inner and (c[1:-1] or not p[1:-1]) for c in chosen):
            continue
        chosen.append(p)
        if len(chosen) == PATHS_SHOWN:
            break
    out = []
    for p in chosen:
        out.append(" > ".join(f'{V[a]["name"]} {" / ".join(steps(a).get(b, ["leads to"]))} {V[b]["name"]}'
                              for a, b in zip(p, p[1:])))
    return out


def links_of(names: list[str], depth: int = 1, to: str | None = None) -> dict[str, Any]:
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
                    label = ONE.get(kind, kind) if key == "it" else verbs.get(kind, kind)   # (0.10.7) "depends
                    #                                       on", "is linked to": "+ s" made "depend ons", "are linked tos"
                    rel.setdefault(label, []).append(f'{V[b]["name"]} ({V[b]["cat"]})' + (f": {note[:120]}" if note else ""))
                    edge = (i, kind, b) if key == "it" else (b, kind, i)
                    text = g.get("long", {}).get(edge)
                    if text and len(follow) < 8:
                        a_, b_ = (V[i]["name"], V[b]["name"]) if key == "it" else (V[b]["name"], V[i]["name"])
                        by = g.get("long_by", {}).get(edge)
                        follow.append(f"{a_} {ONE.get(kind, kind)} {b_}" + (f" ({by})" if by else "") +
                                      f": {text[:400]}")
                if rel:
                    item[key] = rel
            if follow:
                item["what_to_do_when_following"] = follow
            near = g.get("subjects", {}).get(i, [])          # (0.10.6.2) its subjects, or the parts about it
            if near:
                item["subjects" if V[i]["cat"] not in ("subject", "aspect") else "parts_about_it"] = \
                    [f'{V[x]["name"]} ({V[x]["cat"]})' for x in near[:20]]
            out.append(item)
    res: dict[str, Any] = {"parts": out}
    if listed:
        res["categories_listed"] = listed
    ids = [i for raw in names[:8] for i in (named(str(raw), g) or g["names"].get(" ".join(str(raw).lower().split()), []))[:2]]
    from supagent.knowledge.catkind import serverish   # (0.10.6) a server or a group named: what its failure

    places = [i for i in ids if serverish(V[i]["cat"]) or is_place(i, g)]   # ("if db-01 is down,
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
    if to:                                              # (0.10.7) the paths from the named parts to another one,
        ends = set(named(str(to), g) or g["names"].get(" ".join(str(to).lower().split()), []))   # from each apart
        if not ends:
            res["paths_to"] = {str(to): "not in the map"}
        else:
            routes: dict[str, Any] = {}
            for i in dict.fromkeys(ids):
                if i not in ends:
                    found = paths_between([i], ends, g)
                    routes[f'from {V[i]["name"]}'] = found or f"no path of {PATH_STEPS} links or fewer over what flows"
            if any(isinstance(r, list) for r in routes.values()):      # a part of the same name (a job) with no
                routes = {k: r for k, r in routes.items() if isinstance(r, list)}   # route: left out
            res["paths_to"] = {str(to): routes if len(routes) != 1 else next(iter(routes.values()))}
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
    return _summaries_first(res)


def _summaries_first(res: dict[str, Any]) -> dict[str, Any]:
    """(0.10.7) The route found to the part asked (paths_to) and what a failure reaches (if_it_fails) come first,
    and the chains every way are cut short when one of them is there: after the parts and some forty chains, they
    were past the 8,000 characters of a tool's result and never read (obs7dev: a route made up; "checkout calls
    inventory" missing from what a cache's server reaches). A route asked to a name not in the map stays last."""
    routes = res.get("paths_to")
    found = isinstance(routes, dict) and any(isinstance(v, (list, dict)) for v in routes.values())
    first = (["paths_to"] if found else []) + (["if_it_fails"] if res.get("if_it_fails") else [])
    if not first:
        return res
    for key in ("leads_to", "led_from"):
        if isinstance(res.get("paths"), dict) and len(res["paths"].get(key) or []) > TO_CHAINS:
            res["paths"][key] = res["paths"][key][:TO_CHAINS] + [
                f"... {len(res['paths'][key]) - TO_CHAINS} more chains (the summary above: {', '.join(first)})"]
    return {**{k: res[k] for k in first}, **{k: v for k, v in res.items() if k not in first}}
