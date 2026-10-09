"""(0.10.2) What in the knowledge would confuse the agent or the search, found and said with a proposed fix (the user's
request of 7 October 2026: "when a content can make the agent and the search confused ... a warning in To review that
the approver can see and analyse, with a proposed solution"). Each check is deterministic (no LLM) and says why:

  same_name     one name for two things: a value in two categories (a server group and an application both "web"):
                a question naming it cannot be told apart -> rename one with what it is, or merge them
  two_ways      one thing written two ways in a category ("web-shop" and "webshop", "order" and "orders"): what is
                known of it is split between the two -> merge one into the other (one click), its name kept as a
                synonym
  generic_name  a value named by a common word or two letters ("app", "db", "web"): the search finds the word in many
                texts that are not about it -> a name that says which one it is, the word kept as a synonym (OFF:
                not among the default checks, see CHECKS)
  loop          the System map in a circle (A part of B and B part of A; A runs on B and B runs on A): the agent
                cannot say which holds which -> reject the wrong link
  shared_pages  documents holding the same pages (a wiki given as one document per space, read to the last page
                its links lead to): every page cut and embedded again per document -> one document per wiki
  two_meanings  a glossary term defined twice, differently: the agent may count by either -> keep one definition

    superset supagent lint [--json]
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from superset import db

GENERIC = {"app", "apps", "application", "applications", "service", "services", "server", "servers", "data", "db",
           "database", "databases", "web", "api", "apis", "test", "tests", "prod", "production", "dev", "main",
           "default", "system", "systems", "platform", "monitoring", "storage", "network", "backend", "frontend",
           "core", "common", "all", "other", "misc", "general", "host", "hosts", "node", "nodes", "cluster", "job",
           "jobs", "log", "logs", "metric", "metrics", "user", "users", "admin", "client", "worker", "workers"}
SHARED_PAGES = 5          # two documents holding this many pages of the same address (or half the smaller one's)
SAID = 4                  # names said in a warning's text at most


def _norm(name: str) -> str:
    return re.sub(r"[\s_.-]+", " ", str(name or "").strip().lower())


def _compact(name: str) -> str:
    return re.sub(r"[\W_]+", "", str(name or "").lower())


def _said(names: list[str]) -> str:
    shown = [f"“{n}”" for n in names[:SAID]] + ([f"{len(names) - SAID} more"] if len(names) > SAID else [])
    return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]


def _a(word: str) -> str:
    return ("an " if str(word)[:1].lower() in "aeiou" else "a ") + str(word)


def _parents() -> dict[int, list[str]]:
    """value id -> the values it is part of on the map (approved links), the widest category first."""
    from supagent.knowledge.facets import rank
    from supagent.models import Facet, Link

    vals = {i: (c, v) for i, c, v in db.session.query(Facet.id, Facet.facet, Facet.value)}
    out: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for a, b in db.session.query(Link.a_ref, Link.b_ref).filter(
            Link.kind == "part_of", Link.status == "approved", Link.a_ref.like("facet:%"), Link.b_ref.like("facet:%")):
        try:
            child, parent = int(a[6:]), int(b[6:])
        except ValueError:
            continue
        if parent in vals:
            out[child].append((rank(vals[parent][0]), vals[parent][1]))
    return {k: [v for _r, v in sorted(set(ps))] for k, ps in out.items()}


def same_name() -> list[dict[str, Any]]:
    from supagent.models import Facet

    by: dict[str, list[Any]] = defaultdict(list)
    for f in db.session.query(Facet).filter(Facet.status.in_(("approved", "proposed"))):
        by[_norm(f.value)].append(f)
    from supagent.knowledge.datalinks import SERVERISH
    from supagent.knowledge.interactions import TOPICS

    out = []
    for key, fs in sorted(by.items()):
        cats = sorted({f.facet for f in fs})
        if len(cats) < 2:
            continue
        topics = [f for f in fs if f.facet in TOPICS]
        places = [f for f in fs if SERVERISH.search(f.facet or "")]
        if topics and places and len(topics) + len(places) == len(fs):
            continue                            # (0.10.6) a topic and a server or a group of one name ("monitoring"):
            #                                     two things, which the classification keeps apart
        name = fs[0].value
        approved = [f for f in fs if f.status == "approved"]
        proposed = [f for f in fs if f.status != "approved"]
        w = {"kind": "same_name", "subject": name, "refs": [f"facet:{f.id}" for f in fs],
             "why": f"“{name}” is a value of {', '.join(cats[:-1])} and of {cats[-1]}: a question that names it cannot "
                    f"be told apart, and the search gives both",
             "fix": f"Rename one with what it is ({_said([f'{name} {c}' for c in cats])}), “{name}” kept among its "
                    f"synonyms; if they are the same thing, merge one into the other"}
        if len(approved) == 1 and proposed:     # proposed again in another category: what it holds would split
            keep = approved[0]
            w["why"] = (f"“{name}” is {_a(keep.facet)} already and is proposed as "
                        f"{' and '.join(_a(c) for c in sorted({f.facet for f in proposed}))}: approved, what is known "
                        f"of it would be split between them, and a question naming it gets both")
            w["fix"] = (f"If it is the same thing, merge the proposal into the {keep.facet} “{keep.value}” (or reject "
                        f"it); if it is another thing, rename the proposal with what it is before approving it")
            w["merge"] = [{"from": f.id, "into": keep.id,
                           "label": f"Merge the {f.facet} “{f.value}” into the {keep.facet}"} for f in proposed]
            w["reject"] = [{"facet": f.id, "label": f"Reject the {f.facet} “{f.value}”"} for f in proposed]  # (0.10.6)
        out.append(w)
    return out


def two_ways() -> list[dict[str, Any]]:
    """One thing perhaps written two ways in one category: the same letters and digits (case, spaces, dashes apart),
    or a name and its plural. A value the map puts inside the other, or running on it, is another thing (a host
    "lbserver" in its group "lb_servers"): left out."""
    from supagent.models import Facet, Link, Tag

    counts = Counter(fid for (fid,) in db.session.query(Tag.facet_id).filter(Tag.status == "approved"))
    facets = {f.id: f for f in db.session.query(Facet).filter(Facet.status.in_(("approved", "proposed")))}
    by: dict[tuple[str, str], list[int]] = defaultdict(list)
    for f in facets.values():
        key = _compact(f.value)
        if key:
            by[(f.facet, key)].append(f.id)
    pairs = [(ids[0], other) for ids in by.values() for other in ids[1:]]
    for (cat, key), ids in list(by.items()):
        if len(key) < 4 or key[-1].isdigit():
            continue
        for plural in (key + "s", key + "es", key[:-1] + "ies" if key.endswith("y") else None):
            pairs += [(ids[0], other) for other in by.get((cat, plural), [])] if plural else []
    if not pairs:
        return []
    near = {x for pair in pairs for x in pair}
    links = []
    for a, b in db.session.query(Link.a_ref, Link.b_ref).filter(
            Link.kind.in_(("part_of", "runs_on")), Link.status.in_(("approved", "proposed")),
            Link.a_ref.like("facet:%"), Link.b_ref.like("facet:%")):
        try:
            x, y = int(a[6:]), int(b[6:])
        except ValueError:
            continue
        if x in near and y in near:
            links.append((x, y))
    group = {x: x for x in near}

    def root(x: int) -> int:
        while group[x] != x:
            group[x] = group[group[x]]
            x = group[x]
        return x

    for a, b in pairs:
        group[root(b)] = root(a)
    inside = {x for x, y in links if root(x) == root(y)}   # inside, or running on, another of the group's
    groups: dict[int, list[Any]] = defaultdict(list)
    for x in sorted(near):
        if x not in inside:
            groups[root(x)].append(facets[x])
    out = []
    for fs in groups.values():
        if len(fs) < 2:
            continue
        keep = sorted(fs, key=lambda f: (f.status != "approved", -counts.get(f.id, 0), f.id))[0]
        rest = [f for f in fs if f is not keep]
        names = [keep.value] + [f.value for f in rest]
        out.append({"kind": "two_ways", "subject": " / ".join(names), "refs": [f"facet:{f.id}" for f in fs],
                    "why": f"the {keep.facet} values {_said(names)} look like one name written {len(names)} ways: if "
                           f"they are one thing, what is known of it is split between them and a question finds one",
                    "fix": f"If they are one thing, merge {_said([f.value for f in rest])} into “{keep.value}” (the "
                           f"one with the most items), the other way{'s' if len(rest) > 1 else ''} kept among its "
                           f"synonyms; if not, rename one so that the two are told apart",
                    "merge": [{"from": f.id, "into": keep.id, "label": f"Merge “{f.value}” into “{keep.value}”"}
                              for f in rest]})
    return out


def generic_name() -> list[dict[str, Any]]:
    from supagent.models import Facet

    parents = _parents()
    out = []
    for f in db.session.query(Facet).filter(Facet.status == "approved").order_by(Facet.facet, Facet.value):
        key = _norm(f.value)
        if key in GENERIC or len(key.replace(" ", "")) <= 2:
            up = parents.get(f.id) or []
            example = (f"“{up[0]} {f.value}”" if up else f"its team, application or place with it: “<team> {f.value}”")
            out.append({"kind": "generic_name", "subject": f.value, "refs": [f"facet:{f.id}"],
                        "why": f"the {f.facet} “{f.value}” is named by a common word: the search finds it in many texts "
                               f"that are not about it, and a question using the word is read as naming it",
                        "fix": f"Give it a name that says which one it is ({example}), “{f.value}” kept among its "
                               f"synonyms"})
    return out


def loops() -> list[dict[str, Any]]:
    """The map in a circle: values part of each other (A part of B, B part of A, or longer), a part running on what
    runs on it."""
    from supagent.models import Facet, Link

    names = dict(db.session.query(Facet.id, Facet.value))
    edges: dict[str, dict[int, dict[int, int]]] = {"part_of": defaultdict(dict), "runs_on": defaultdict(dict)}
    for lid, a, b, kind in db.session.query(Link.id, Link.a_ref, Link.b_ref, Link.kind).filter(
            Link.kind.in_(tuple(edges)), Link.status.in_(("approved", "proposed")), Link.a_ref.like("facet:%"),
            Link.b_ref.like("facet:%")):
        try:
            x, y = int(a[6:]), int(b[6:])
        except ValueError:
            continue
        if x in names and y in names:
            edges[kind][x][y] = lid
    out = []
    for x, ys in sorted(edges["runs_on"].items()):
        for y, lid in sorted(ys.items()):
            back = edges["runs_on"].get(y, {}).get(x)
            if back is not None and (x < y or x == y):
                out.append({"kind": "loop", "subject": f"{names[x]} / {names[y]}",
                            "refs": sorted({f"link:{lid}", f"link:{back}"}),
                            "keep": [{"label": f"Keep “{names[x]} runs on {names[y]}”", "reject": back},   # (0.10.6)
                                     {"label": f"Keep “{names[y]} runs on {names[x]}”", "reject": lid}],
                            "why": f"the map says “{names[x]}” runs on “{names[y]}” and “{names[y]}” runs on "
                                   f"“{names[x]}”: the agent cannot say which is the place",
                            "fix": "Keep the link whose direction is true (what runs, on its place) and reject the "
                                   "other"})
    for comp in _circles(edges["part_of"]):
        member = set(comp)
        refs = sorted({f"link:{lid}" for x in comp for y, lid in edges["part_of"][x].items() if y in member})
        said = [names[x] for x in comp]
        ids = [(x, y, lid) for x in comp for y, lid in edges["part_of"][x].items() if y in member]
        out.append({"kind": "loop", "subject": " / ".join(said[:SAID]), "refs": refs,
                    "keep": [{"label": f"Reject “{names[x]} is part of {names[y]}”", "reject": lid}     # (0.10.6)
                             for x, y, lid in ids[:6]],
                    "why": (f"the map says “{said[0]}” is part of itself" if len(comp) == 1 else
                            f"the map says {_said(said)} are part of each other: the agent cannot say which holds "
                            f"which, and a count by one of them counts the others' parts again"),
                    "fix": "Reject the link that is wrong (a part is inside the other, not both ways)"})
    return out


def _circles(graph: dict[int, dict[int, int]]) -> list[list[int]]:
    """The circles of a directed graph: its strongly connected parts of two values or more, and a value linked to
    itself (Tarjan's, without recursion)."""
    index: dict[int, int] = {}
    low: dict[int, int] = {}
    on, stack, out = set(), [], []
    count = 0
    for start in list(graph):
        if start in index:
            continue
        work = [(start, iter(graph.get(start, {})))]
        index[start] = low[start] = count
        count += 1
        stack.append(start)
        on.add(start)
        while work:
            node, it = work[-1]
            nxt = next(it, None)
            if nxt is not None:
                if nxt not in index:
                    index[nxt] = low[nxt] = count
                    count += 1
                    stack.append(nxt)
                    on.add(nxt)
                    work.append((nxt, iter(graph.get(nxt, {}))))
                elif nxt in on:
                    low[node] = min(low[node], index[nxt])
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    x = stack.pop()
                    on.discard(x)
                    comp.append(x)
                    if x == node:
                        break
                if len(comp) > 1 or node in graph.get(node, {}):
                    out.append(sorted(comp))
    return out


def shared_pages() -> list[dict[str, Any]]:
    from supagent.knowledge.docs import reader_of
    from supagent.models import Doc

    docs = sorted(db.session.query(Doc).filter(Doc.enabled.is_(True), Doc.kind == "url"), key=lambda d: d.id)
    urls = {d.id: {str(p.get("url")) for p in d.pages or [] if isinstance(p, dict) and p.get("url")} for d in docs}
    group = {d.id: d.id for d in docs}

    def root(x: int) -> int:
        while group[x] != x:
            group[x] = group[group[x]]
            x = group[x]
        return x

    for i, a in enumerate(docs):
        for b in docs[i + 1:]:
            common = urls[a.id] & urls[b.id]
            small = min(len(urls[a.id]), len(urls[b.id])) or 1
            if len(common) >= SHARED_PAGES or (common and len(common) * 2 >= small):
                group[root(b.id)] = root(a.id)
    groups: dict[int, list[Any]] = defaultdict(list)
    for d in docs:
        groups[root(d.id)].append(d)
    out = []
    for fs in groups.values():
        if len(fs) < 2:
            continue
        held = Counter(u for d in fs for u in urls[d.id])
        common = sum(1 for n in held.values() if n > 1)
        titles = [d.title or d.url for d in fs]
        first, later = fs[0], fs[1:]
        nothing_own = [d.title or d.url for d in later if urls[d.id] and all(held[u] > 1 for u in urls[d.id])
                       and urls[d.id] <= set().union(*(urls[o.id] for o in fs if o.id < d.id))]
        wiki = all(reader_of(d) in ("confluence", "web") for d in fs)
        if nothing_own:
            one = len(nothing_own) == 1
            fix = (f"Disable {_said(nothing_own)}: every page {'it holds' if one else 'they hold'} is read by a "
                   f"document before {'it' if one else 'them'} (or give {'it an address' if one else 'them addresses'}"
                   f" of {'its' if one else 'their'} own)")
        elif wiki:
            fix = (f"Read {_said([d.title or d.url for d in later])} again (Documents): a page several documents reach "
                   f"is then read by the first one only (“{first.title or first.url}”); or keep one document per wiki "
                   f"(its home page: its links lead to the other pages)")
        else:
            fix = "Keep one of them, or give them addresses that do not overlap"
        copies = [d for d in later if (d.title or d.url) in nothing_own]
        out.append({"kind": "shared_pages", "subject": " / ".join(titles), "refs": [f"doc:{d.id}" for d in fs],
                    "disable": [{"doc": d.id, "label": f"Disable “{d.title or d.url}”"} for d in copies],   # (0.10.6)
                    "why": f"the documents {_said(titles)} hold the same {common} page{'s' if common > 1 else ''}: "
                           f"each copy is cut and embedded again, and each document's Context page tells them again",
                    "fix": fix})
    return out


def two_meanings() -> list[dict[str, Any]]:
    from supagent.knowledge.glossary import entry_terms
    from supagent.models import Entry

    said: dict[str, list[tuple[Any, str, str]]] = defaultdict(list)
    for e in db.session.query(Entry).filter(Entry.enabled.is_(True), Entry.classification == "glossary"):
        for _ref, term, definition in entry_terms(e):
            said[_norm(term)].append((e, term, " ".join(str(definition or "").split())))
    out = []
    for key, items in sorted(said.items()):
        meanings = {re.sub(r"[^\w]+", " ", d.lower()).strip() for _e, _t, d in items}
        if len(meanings) < 2:
            continue
        term = items[0][1]
        shown = "; ".join(f"“{d[:120]}” ({e.title})" for e, _t, d in items[:3])
        out.append({"kind": "two_meanings", "subject": term, "refs": sorted({f"entry:{e.id}" for e, _t, _d in items}),
                    "why": f"“{term}” is defined {len(items)} times, differently: {shown}: the agent may count by "
                           f"either",
                    "fix": "Keep one definition (edit the other entry, or disable it); a term used two ways gets two "
                           "names"})
    return out


# generic_name is not among them: measured on a lab's knowledge (7 October 2026, pre-registered) it was wrong on
# most of its warnings there, all topics named by their own word ("monitoring", "jobs"): turned off until a version
# measured on other material says otherwise
CHECKS = (same_name, two_ways, loops, shared_pages, two_meanings)
DISMISSED = "lint_dismissed"     # supagent_meta: the warnings an approver set aside (their keys)


def dismissed() -> set[str]:
    import json

    from supagent.models import Meta

    row = db.session.get(Meta, DISMISSED)
    try:
        return set(json.loads(row.value)) if row is not None and row.value else set()
    except ValueError:
        return set()


def dismiss(key: str) -> None:
    """A warning set aside: not said again (until what it is about changes its key)."""
    import json

    from supagent.models import Meta

    keys = sorted(dismissed() | {key})[-5000:]
    row = db.session.get(Meta, DISMISSED)
    if row is None:
        db.session.add(Meta(key=DISMISSED, value=json.dumps(keys)))
    else:
        row.value = json.dumps(keys)
    db.session.commit()


def warnings(with_dismissed: bool = False) -> list[dict[str, Any]]:
    """Every warning, by check (a check that fails says so and the others go on), each with its key; the ones an
    approver set aside left out."""
    out: list[dict[str, Any]] = []
    for check in CHECKS:
        try:
            out += check()
        except Exception as ex:  # pylint: disable=broad-except
            db.session.rollback()
            out.append({"kind": "error", "subject": check.__name__, "refs": [], "why": str(ex)[:300], "fix": ""})
    for w in out:
        w["key"] = f"{w['kind']}:{_norm(w['subject'])}:{','.join(sorted(w.get('refs') or []))}"[:500]
    if not with_dismissed:
        gone = dismissed()
        out = [w for w in out if w["key"] not in gone]
    return out
