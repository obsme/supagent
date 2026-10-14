"""(0.10.10, the owner's request of 13 October 2026: the full picture of the System map for the agent and the Context)
Communities of the System map and their pages: the GraphRAG idea (communities of an entity graph, a report per
community at several levels, map-wide questions answered from them) for a map people curate, without any service:

  level 1, a system: a value made of parts (a platform service and its modules, an application and its components,
           a cluster and its streams) with what mostly it uses (the stores its parts depend on, the streams they
           write, the jobs that read its data); a place: a value made of hosts (a group of servers, a cluster of
           namespaces);
  level 2, what holds them: what systems are part of (a domain, a product line), a team (what it owns), what places
           are part of (an environment);
  what nobody organized: communities of its links (Louvain, in pure Python), level 1 too.

Each community gets a facts page of the Context (no LLM): what it is, its parts, where they run in each environment,
its data, what it calls and what uses it, its owner, its jobs; written again only when what it says changes, never
over a page a person edited. overview() answers map-wide questions from the same structures ("what is affected if X
is down", "what does team T own", "where does S run in prod", "who reads Q"): offline, not a tool of the agent yet."""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from typing import Any

log = logging.getLogger(__name__)

FLOW_WEIGHT = {"depends_on": 2, "sends_to": 2, "reads_from": 1, "calls": 1, "link": 1, "monitors": 0, "runs_on": 0}
MAX_LISTED = 60            # names listed per line of a page
MAX_PAGES = 400            # community pages at most
OWNED = re.compile(r"\bowned by\b|\bowner\b", re.I)


def _concept_of(g: dict[str, Any]) -> dict[str, str]:
    from supagent import settings
    from supagent.knowledge.placing import affinity

    about = settings.get("categories.about") or {}
    out: dict[str, str] = {}
    for v in g["values"].values():
        c = v["cat"]
        if c not in out:
            a = affinity(c, about.get(c, ""))
            out[c] = a.most_common(1)[0][0] if a else ""
    return out


def _owner_links(g: dict[str, Any]) -> dict[int, list[int]]:
    """What owns each value: an approved link "owned by" (its words, or the kind of those words)."""
    from superset import db

    from supagent.knowledge.sysmap import worded
    from supagent.models import Link

    if "owners" in g:
        return g["owners"]
    out: dict[int, list[int]] = defaultdict(list)
    for a, links in g["out"].items():
        for kind, b, note in links:
            if kind == "owned_by" or (kind == "link" and OWNED.search(note or "")):
                out[a].append(b)
    kinds = {worded("owned by"), "owned_by"}
    for a_ref, b_ref in db.session.query(Link.a_ref, Link.b_ref).filter(Link.kind.in_(list(kinds)),
                                                                        Link.status == "approved"):
        a, b = a_ref.split(":", 1)[1], b_ref.split(":", 1)[1]
        if a.isdigit() and b.isdigit() and int(a) in g["values"] and int(b) in g["values"] and int(b) not in out[int(a)]:
            out[int(a)].append(int(b))
    g["owners"] = out
    return out


ATTACHED = {"store", "cache", "messaging", "broker", "object", "job", "external", "dashboard", "alert"}


def build(g: dict[str, Any] | None = None) -> dict[str, Any]:
    """The communities (see the module): {"systems", "places", "holders", "teams", "environments", "loose", "of"}:
    each community {"root": id or None, "members": [ids], "kind"}; "of": a value's level-1 community."""
    from supagent.knowledge.brief import _graph
    from supagent.knowledge.placing import HOSTISH

    g = g or _graph()
    values, children = g["values"], g["children"]
    concept = _concept_of(g)

    def hostish(i: int) -> bool:
        return concept.get(values[i]["cat"], "") in HOSTISH

    from supagent.knowledge.facets import inside

    part_cats = set(inside())                             # categories whose values are parts of others' values

    def attachable(i: int) -> bool:                       # (0.10.10) data and jobs join a system by its flows; a
        c = values[i]["cat"]                              # part of no known whole (a module) or another system's
        k = concept.get(c, "")                            # application never does
        if k in ATTACHED:
            return True
        return c not in part_cats and k not in ("service", "application", "team", "domain", "environment")

    def leaf(i: int) -> bool:
        return not [k for k in children.get(i, []) if k in values and not hostish(k)]

    systems: dict[int, set[int]] = {}
    places: dict[int, set[int]] = {}
    for i in values:
        kids = [k for k in children.get(i, []) if k in values]
        if not kids:
            continue
        if all(hostish(k) for k in kids):
            places[i] = {i, *kids}                        # a group of hosts, a cluster of namespaces
        elif all(leaf(k) for k in kids if not hostish(k)):
            systems[i] = {i, *[k for k in kids if not hostish(k)]}
    of: dict[int, int] = {}
    for root, members in systems.items():
        for m in members:
            of.setdefault(m, root)
    for root, members in places.items():
        for m in members:
            of.setdefault(m, root)
    # what mostly a system uses: the values of no structure linked by flows to its members (twice: the jobs on a
    # store attach after the store)
    for _round in range(2):
        votes: dict[int, Counter] = defaultdict(Counter)
        for a, links in g["out"].items():
            for kind, b, note in links:
                w = FLOW_WEIGHT.get(kind, 0)
                if not w or a not in values or b not in values or (kind == "link" and OWNED.search(note or "")):
                    continue                              # (an owner is no part of what it owns)
                if of.get(a) in systems and b not in of and not values[b]["parents"] and not hostish(b) and \
                        attachable(b):
                    votes[b][of[a]] += w                  # what a system's part uses, writes, reads
                if of.get(b) in systems and a not in of and not values[a]["parents"] and not hostish(a) and \
                        attachable(a):
                    votes[a][of[b]] += 1 if kind != "reads_from" else 2   # a job reading a system's store
        for v, c in votes.items():
            root, _n = c.most_common(1)[0]
            of[v] = root
            systems[root].add(v)
    # streams written by a system's parts are its own as well (they also belong to their cluster)
    for a, links in g["out"].items():
        for kind, b, _note in links:
            if kind == "sends_to" and of.get(a) in systems and b in values and not hostish(b):
                systems[of[a]].add(b)
    # level 2: what holds systems and places
    holders: dict[int, set[int]] = defaultdict(set)
    for root in systems:
        for p in values[root]["parents"]:
            holders[p].add(root)
    environments: dict[int, set[int]] = defaultdict(set)
    for root in places:
        for p in values[root]["parents"]:
            environments[p].add(root)
    teams: dict[int, set[int]] = defaultdict(set)
    owners = _owner_links(g)
    for root, members in systems.items():                 # a system's owner: its own, else its parts' owners
        for t in owners.get(root, []) or [t for m in members for t in owners.get(m, [])]:
            teams[t].add(root)
    # what nobody organized: communities of the links between values of no community
    rest = [i for i in values if i not in of and i not in holders and i not in teams and i not in environments
            and not hostish(i)]
    loose = louvain(rest, g)
    return {"systems": {r: sorted(m) for r, m in systems.items()}, "places": {r: sorted(m) for r, m in places.items()},
            "holders": {r: sorted(m) for r, m in holders.items()}, "teams": {r: sorted(m) for r, m in teams.items()},
            "environments": {r: sorted(m) for r, m in environments.items()},
            "loose": [sorted(c) for c in loose if len(c) > 1], "of": of}


def louvain(nodes: list[int], g: dict[str, Any], rounds: int = 10) -> list[set[int]]:
    """Communities of the links between `nodes` (one level of Louvain's modularity moves; pure Python)."""
    keep = set(nodes)
    adj: dict[int, Counter] = defaultdict(Counter)
    for a, links in g["out"].items():
        for _kind, b, _note in links:
            if a in keep and b in keep and a != b:
                adj[a][b] += 1
                adj[b][a] += 1
    if not adj:
        return []
    m2 = sum(sum(c.values()) for c in adj.values())       # twice the edges
    com = {n: n for n in adj}
    deg = {n: sum(c.values()) for n, c in adj.items()}
    tot = Counter({n: deg[n] for n in adj})
    for _r in range(rounds):
        moved = False
        for n in sorted(adj):
            here = com[n]
            tot[here] -= deg[n]
            links_to: Counter = Counter()
            for x, w in adj[n].items():
                links_to[com[x]] += w
            best, gain = here, 0.0
            for c, w in links_to.items():
                d = w - tot[c] * deg[n] / m2
                if d > gain + 1e-12 or (abs(d - gain) <= 1e-12 and c == here):
                    best, gain = c, d
            com[n] = best
            tot[best] += deg[n]
            moved |= best != here
        if not moved:
            break
    out: dict[int, set[int]] = defaultdict(set)
    for n, c in com.items():
        out[c].add(n)
    return list(out.values())


# ------------------------------------------------------------------------------------------------- the pages
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:90] or "x"


def _names(ids: Any, g: dict[str, Any], limit: int = MAX_LISTED) -> str:
    names = sorted({g["values"][i]["name"] for i in ids if i in g["values"]}, key=str.lower)
    more = f" and {len(names) - limit} more" if len(names) > limit else ""
    return ", ".join(names[:limit]) + more


def _env_of(i: int, g: dict[str, Any], places: dict[int, list[int]]) -> str:
    """The environment a place belongs to (its parent), else ""."""
    v = g["values"].get(i)
    if v is None:
        return ""
    for p in v["parents"]:
        if p in g["values"]:
            return g["values"][p]["name"]
    return ""


def _where(members: list[int], g: dict[str, Any], c: dict[str, Any]) -> dict[str, set[int]]:
    """Where a system's parts run, per environment ("" when the place has none)."""
    out: dict[str, set[int]] = defaultdict(set)
    for m in members:
        for kind, b, _note in g["out"].get(m, []):
            if kind == "runs_on" and b in g["values"]:
                out[_env_of(b, g, c["places"])].add(b)
    return out


def system_page(root: int, g: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    v = g["values"][root]
    members = c["systems"][root]
    parts = [m for m in members if m in g["children"].get(root, [])]
    rest = [m for m in members if m != root and m not in parts]
    owners = _owner_links(g).get(root, [])
    lines = [f"# {v['name']}", "", f"A {v['cat']}" + (f": {v['about']}" if v["about"] else "") + "."]
    if v["parents"]:
        lines.append(f"Part of: {_names(v['parents'], g)}.")
    if owners:
        lines.append(f"Owned by: {_names(owners, g)}.")
    if parts:
        lines += ["", f"## Its parts ({len(parts)})"]
        for m in sorted(parts, key=lambda i: g["values"][i]["name"].lower()):
            on = [b for k, b, _n in g["out"].get(m, []) if k == "runs_on"]
            lines.append(f"- {g['values'][m]['name']} ({g['values'][m]['cat']})" + (f": runs on {_names(on, g)}" if on else ""))
    where = _where([root, *parts], g, c)
    if where:
        lines += ["", "## Where it runs"]
        for env in sorted(where, key=lambda e: (e == "", e)):
            lines.append(f"- {env or 'no environment said'}: {_names(where[env], g)}")
    if rest:
        by_cat: dict[str, list[int]] = defaultdict(list)
        for m in rest:
            by_cat[g["values"][m]["cat"]].append(m)
        lines += ["", "## Its data and jobs"]
        for cat in sorted(by_cat):
            lines.append(f"- {cat}: {_names(by_cat[cat], g)}")
    out_lines, in_lines = [], []
    inside = set(members)
    for m in sorted(inside):
        for kind, b, note in g["out"].get(m, []):
            if b not in inside and b in g["values"] and kind not in ("runs_on",) and not OWNED.search(note or ""):
                other = c["of"].get(b)
                tail = f" (of {g['values'][other]['name']})" if other is not None and other != b and other in g["values"] else ""
                out_lines.append(f"- {g['values'][m]['name']} {kind.replace('_', ' ')} {g['values'][b]['name']}{tail}")
        for kind, a, note in g["in"].get(m, []):
            if a not in inside and a in g["values"] and kind not in ("runs_on",) and not OWNED.search(note or ""):
                other = c["of"].get(a)
                tail = f" (of {g['values'][other]['name']})" if other is not None and other != a and other in g["values"] else ""
                in_lines.append(f"- {g['values'][a]['name']}{tail} {kind.replace('_', ' ')} {g['values'][m]['name']}")
    if out_lines:
        lines += ["", "## What it uses outside", *sorted(set(out_lines))[:MAX_LISTED]]
    if in_lines:
        lines += ["", "## What uses it", *sorted(set(in_lines))[:MAX_LISTED]]
    return {"section": "technical", "slug": f"system-{_slug(v['name'])}-{root}", "title": f"System: {v['name']}",
            "content": "\n".join(lines) + "\n", "database_ids": [], "sources": []}


def holder_page(root: int, kind: str, g: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    v = g["values"][root]
    held = c[kind][root]
    word = {"holders": "systems", "teams": "systems it owns", "environments": "places in it"}[kind]
    lines = [f"# {v['name']}", "", f"A {v['cat']}" + (f": {v['about']}" if v["about"] else "") + ".", "",
             f"## Its {word} ({len(held)})"]
    for r in sorted(held, key=lambda i: g["values"][i]["name"].lower()):
        sub = c["systems"].get(r) or c["places"].get(r) or []
        parts = [m for m in sub if m in g["children"].get(r, [])]
        owners = _owner_links(g).get(r, [])
        lines.append(f"- {g['values'][r]['name']} ({g['values'][r]['cat']}, {len(parts)} parts"
                     + (f", owned by {_names(owners, g)}" if owners and kind != "teams" else "") + ")")
    return {"section": "technical" if kind == "environments" else "functional",
            "slug": f"{ {'holders': 'domain', 'teams': 'team', 'environments': 'environment'}[kind]}-{_slug(v['name'])}-{root}",
            "title": f"{ {'holders': 'Domain', 'teams': 'Team', 'environments': 'Environment'}[kind]}: {v['name']}",
            "content": "\n".join(lines) + "\n", "database_ids": [], "sources": []}


def pages() -> list[dict[str, Any]]:
    """The facts pages of the communities (see the module), the biggest systems first."""
    from supagent.knowledge.brief import _graph

    g = _graph()
    c = build(g)
    out = [system_page(r, g, c) for r in sorted(c["systems"], key=lambda r: -len(c["systems"][r]))]
    for kind in ("holders", "teams", "environments"):
        out += [holder_page(r, kind, g, c) for r in sorted(c[kind], key=lambda r: -len(c[kind][r]))]
    return out[:MAX_PAGES]


# ------------------------------------------------------------------------------------------------- map-wide questions
INTENTS = [   # (intent, words of the question)
    ("impact", re.compile(r"\b(down|fails?|failure|outage|breaks?|affected|impact|impacted)\b", re.I)),
    ("owner", re.compile(r"\b(own|owns|owned|ownership|owners?|maintains?|maintained|maintainers?|accountable|"
                         r"responsible|in\s+charge)\b", re.I)),   # (0.10.10) "who maintains X", "what is T accountable for"
    ("readers", re.compile(r"\b(read|reads|consume|consumes|consumers?|subscribe|subscribes|listens?|listeners?)\b",
                           re.I)),
    ("writers", re.compile(r"\b(write|writes|publish|publishes|producers?)\b", re.I)),
    ("callers", re.compile(r"\b(call|calls|use|uses|depends?\s+on|relies\s+on|rely\s+on)\b", re.I)),
    ("placement", re.compile(r"\b(where|run|runs|hosted|deployed)\b", re.I)),
    ("members", re.compile(r"\b(make up|made of|consists?|belong|in the)\b", re.I)),
]


def _anchors(question: str, g: dict[str, Any]) -> list[int]:
    """The values the question names (the longest names first)."""
    from supagent.knowledge.brief import named

    return named(question, g, loose=True)                 # (0.10.10) "pharmacy wholesaler" for pharmacy-wholesaler


def _which(anchors: list[int], question: str, intent: str, g: dict[str, Any], c: dict[str, Any]) -> list[int]:
    """Of the values a question names, for a name several values carry (a team, a business line and a group of one
    name): the one of the category the question writes next to it, else the one the question's intent needs (a
    team for "own", what holds systems for "make up", a place for "run on")."""
    from supagent.knowledge.placing import named_categories

    values = g["values"]
    by_name: dict[str, list[int]] = defaultdict(list)
    for a in anchors:
        if a in values:
            by_name[values[a]["name"].lower()].append(a)
    cats = sorted({v["cat"] for v in values.values()})
    out: list[int] = []
    for name, ids in by_name.items():
        if len(ids) > 1:
            said = named_categories(question, name, cats)
            pick = [i for i in ids if values[i]["cat"] in said] if said else []
            if not pick:
                need = {"owner": c["teams"], "members": {**c["holders"], **c["systems"], **c["environments"]},
                        "placement": {**c["systems"], **c["places"]}}.get(intent)
                pick = [i for i in ids if need is not None and i in need]
            ids = pick or ids
        out += ids
    return out


def overview(question: str) -> dict[str, Any]:
    """A map-wide question answered from the communities (see the module): {"intent", "anchors", "answer": [names],
    "level": "system" | "part", "why"}."""
    from supagent.knowledge.brief import _graph

    g = _graph()
    c = build(g)
    values = g["values"]
    anchors = _anchors(question, g)
    intent = next((name for name, rx in INTENTS if rx.search(question or "")), "members")
    anchors = _which(anchors, question, intent, g, c)
    systems_asked = bool(re.search(r"\b(systems?|services?|applications?|platform)\b", question or "", re.I))
    out: set[int] = set()
    why = ""

    def system_of(i: int) -> int:
        return c["of"].get(i, i)

    for a in anchors:
        if intent == "impact":
            users = {x for k, x, _n in g["in"].get(a, []) if k in ("depends_on", "reads_from", "runs_on", "calls")}
            wholes = {system_of(u) for u in users}
            parts_asked = _categories_named(question, {values[u]["cat"] for u in users if u in values}) - \
                {values[w]["cat"] for w in wholes if w in values}
            out |= users if parts_asked and not systems_asked else wholes   # (0.10.10) "what breaks": the systems
            #                                                       their parts make up, unless the parts are asked
            why = "what depends on it, reads it, runs on it or calls it"
        elif intent == "owner":
            if a in c["teams"]:
                out |= set(c["teams"].get(a, []))
                why = "the systems it owns"
            else:                                         # (0.10.10) "who maintains X": the team that owns X (its
                owners = _owner_links(g)                  # system's, else its parts')
                root = system_of(a)
                found = owners.get(a, []) or owners.get(root, []) or \
                    [t for m in c["systems"].get(root, []) for t in owners.get(m, [])]
                out |= set(found)
                why = "the team that owns it"
        elif intent == "readers":
            out |= {x for k, x, _n in g["in"].get(a, []) if k == "reads_from"}
            why = "what reads from it"
        elif intent == "writers":
            out |= {x for k, x, _n in g["in"].get(a, []) if k == "sends_to"}
            why = "what writes to it"
        elif intent == "callers":
            users = {x for k, x, _n in g["in"].get(a, []) if k in ("calls", "depends_on")}
            out |= {system_of(u) for u in users} if systems_asked else users
            why = "what calls or uses it"
        elif intent == "placement":
            if a in c["systems"]:
                parts = [m for m in c["systems"][a] if m == a or m in g["children"].get(a, [])]
                where = _where(parts, g, c)
                env = _env_named(question, [e for e in where if e])
                every = set().union(*where.values()) if where else set()
                out |= where.get(env, set()) if env else (_named_env_places(question, every, g) or every)
                why = f"where its parts run{' in ' + env if env else ''}"
            else:
                users = {x for k, x, _n in g["in"].get(a, []) if k == "runs_on"}
                out |= {system_of(u) for u in users} if systems_asked else users
                why = "what runs on it"
        else:
            held = c["holders"].get(a) or c["teams"].get(a) or c["environments"].get(a) or c["systems"].get(a) or []
            out |= set(held) - {a}
            why = "what it holds"
    said = _categories_named(question, {values[i]["cat"] for i in out if i in values})
    if said:                                              # (0.10.10) "on which host groups", "which platform
        out = {i for i in out if i in values and values[i]["cat"] in said}   # services": those only
    return {"intent": intent, "anchors": [values[a]["name"] for a in anchors if a in values],
            "answer": sorted({values[i]["name"] for i in out if i in values}, key=str.lower), "why": why}


def _env_named(question: str, envs: list[str]) -> str | None:
    """(0.10.10) The environment a question names among the places' environments: by the words that tell them apart
    ("in prod": "infra prod", not "infra preprod"; production, prd and prod are one word), else None."""
    from supagent.knowledge.consolidate import words

    if not envs:
        return None
    sets = {e: set(words(e)) for e in envs}
    common = set.intersection(*sets.values()) if len(sets) > 1 else set()
    asked = set(words(question or ""))
    hits = [(len((ws - common) & asked), e) for e, ws in sets.items() if (ws - common) and (ws - common) <= asked]
    hits.sort(reverse=True)
    return hits[0][1] if hits and (len(hits) == 1 or hits[0][0] > hits[1][0]) else None


def _named_env_places(question: str, places: set[int], g: dict[str, Any]) -> set[int]:
    """(0.10.10) The places whose own name says the environment the question asks about ("in prod": prod_web, not
    preprod_web nor int_web), when their environment is no value of the map."""
    from supagent.knowledge.consolidate import ENV, words

    env_words = set(ENV) | {w for e in ENV for w in words(e)}
    asked = {w for w in words(question or "") if w in env_words}
    if not asked:
        return set()
    return {p for p in places if p in g["values"] and asked & set(words(g["values"][p]["name"]))}


def _categories_named(question: str, cats: set[str]) -> set[str]:
    """(0.10.10) The categories of the answer a question names ("host groups", "a platform service")."""
    low = " " + re.sub(r"[^a-z0-9]+", " ", str(question or "").lower()) + " "
    return {c for c in cats if re.search(r" " + re.escape(c.lower()) + r"(?:s|es)? ", low)}
