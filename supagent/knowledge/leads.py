"""What an investigation blames, checked against the system (0.9).

An investigation's answer that names a part of the system as the cause (a server, a pool, a service, a feed...)
must tie it to what the question is about. The check is plain: the part is tied when the system map links it to
the question's parts within two steps (what they run on, depend on, read, call, consist of, are part of), or when
a result of the answer's own queries on those parts shows it. A part that is neither (servers of another pool
that had an alert that night) is sent back once, then marked: the cause of somebody else's problem.

It judges nothing else: whether a tied part really is the cause stays the investigation's own work.
"""

from __future__ import annotations

import json
import re
from typing import Any

BLAME = re.compile(r"\b(caus\w*|because|due to|root cause|explain\w*|responsible|led to|leads? to|driven by|culprit|"
                   r"result(?:s|ed)? (?:of|from)|origin\w*|trigger\w*|slow(?:s|ed|ing)? (?:down )?|"
                   r"[àa] cause|provoqu\w*|responsable|en raison|d[ûu] [àa])\b", re.I)
RULED = re.compile(r"\b(not|no|n't|unrelated|ruled out|rule[sd]? out|without|normal|unaffected|independent\w*|"
                   r"coincid\w*|separate\w*|unlikely|however|but|although|though|cannot|pas|aucun\w*|sans|"
                   r"hors de cause|[ée]cart[ée]e?s?)\b", re.I)
HEADING = re.compile(r"^\s*(#{1,6}\s|\*\*[^*]+\*\*\s*:?\s*$|[^.!?]{3,80}:\s*$)")
ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
RANGE = re.compile(r"\b([A-Za-z][A-Za-z_\-]*?)(\d+)\s*(?:-|–|to|through|à)\s*(?:\1)?(\d+)\b")
HOPS = 2
# (0.10.7) a table of change records: changes, deployments, releases, incidents (an ITSM's, a CI's)
RECORD_TABLE = re.compile(r'\bfrom\s+\\?"?[\w.*-]*(?:change|deploy|release|itsm|incident|rollout|maintenance)', re.I)
QUERY_TOOLS = ("execute_sql", "compare_groups", "compare_logs", "export_excel")


def _expanded(line: str) -> str:
    """"srv-901-904", "srv101 to srv104": the names of the range, written out (at most 20)."""
    def names(m: re.Match) -> str:
        prefix, a, b = m.group(1), m.group(2), m.group(3)
        if len(b) < len(a):
            b = a[:len(a) - len(b)] + b
        lo, hi = int(a), int(b)
        if not 0 < hi - lo <= 20:
            return m.group(0)
        return ", ".join(f"{prefix}{i:0{len(a)}d}" for i in range(lo, hi + 1))

    return RANGE.sub(names, line)


def blaming_lines(answer: str) -> list[str]:
    """The lines of an answer that say what the cause is: a sentence with a word of cause and none that rules
    out, and the items listed under a heading or a lead-in that says so ("Root cause:", "driven by:")."""
    out: list[str] = []
    under = False
    for raw in (answer or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if HEADING.match(line) and not ITEM.match(line):
            under = bool(BLAME.search(line)) and not RULED.search(line)
            continue
        if under and not RULED.search(line):
            out.append(line)
            continue
        for s in re.split(r"(?<=[.!?])\s+", line):
            if BLAME.search(s) and not RULED.search(s):
                out.append(s)
    return out


def reachable(start: list[int], g: dict[str, Any], hops: int = HOPS) -> set[int]:
    """The values within `hops` steps of these on the system map, whatever the way (it depends on them or they
    on it, it is part of them or they of it)."""
    V, kids = g["values"], g["children"]
    seen, level = set(start), list(start)
    for _ in range(hops):
        nxt: list[int] = []
        for i in level:
            near = [b for _k, b, _n in g["out"].get(i, [])] + [a for _k, a, _n in g["in"].get(i, [])]
            near += list(V[i]["parents"]) + list(kids.get(i, []))
            for j in near:
                if j in V and j not in seen:
                    seen.add(j)
                    nxt.append(j)
        level = nxt
    return seen


DISPLAYS = ("dashboard", "dashboards", "panel", "panels", "chart", "charts")


def can_fail(i: int, g: dict[str, Any]) -> bool:
    """(0.10.7) A value of the map an answer can blame: a part of the system, not a topic (a subject, an aspect: the
    word of "stock levels" blamed the subject stock, sixteen times on the obs lab) nor a value that only watches
    others (its every link "monitors": a monitoring job named after what it watches) or shows them (a dashboard of
    the parts it links to: "Redis (dashboard)" was blamed for the caches' evictions)."""
    from supagent.knowledge.interactions import TOPICS

    v = g["values"][i]
    if v.get("cat") in TOPICS:
        return False
    if str(v.get("cat") or "").strip().lower() in DISPLAYS or \
            re.search(r"\((?:dashboards?|panels?|charts?)\)\s*$", str(v.get("name") or ""), re.I):
        return False
    own = g["out"].get(i, [])                          # what it does: a part only watched by others can fail (a
    return not (own and all(k == "monitors" for k, _o, _n in own) and not g["in"].get(i)   # watcher part of a
                and not g["children"].get(i))         # monitoring system is still a watcher)


def untied(question: str, answer: str, trace: list[dict]) -> tuple[list[str], str]:
    """(the parts the answer blames that nothing ties to the question's parts, the question's parts by name);
    ([], "") when the question names no part, or the answer blames none."""
    from supagent.knowledge.brief import _graph, named

    g = _graph()
    V = g["values"]

    def bare(i: int) -> bool:
        """A word of the map that is no part of the system: no description, part of nothing, nothing part of it,
        no interaction (a category of the catalog kept as a subject: "Batch", "memory", "cache"). Nothing can
        tie it or fail to."""
        v = V[i]
        return not (v.get("about") or v.get("parents") or g["children"].get(i) or g["out"].get(i) or g["in"].get(i))

    seeds = [i for i in named(question, g, loose=True) if not bare(i)]
    if not seeds:
        return [], ""
    actors = list(seeds)
    for s in seeds:
        actors += [i for i in g["children"].get(s, []) if i not in actors]
    blamed: list[int] = []
    for line in blaming_lines(answer):
        for i in named(_expanded(line), g):
            if i not in blamed and not bare(i) and can_fail(i, g):
                blamed.append(i)
    if not blamed:
        return [], ""
    near = reachable(actors, g)
    scope = {V[i]["name"].lower() for i in actors}
    shown = ""                                           # what the answer's queries on those parts returned
    for t in trace:
        if t.get("status") != "done" or (t.get("called") or t.get("tool")) not in QUERY_TOOLS:
            continue
        asked = json.dumps(t.get("args") or {}, default=str).lower()
        if any(n in asked for n in scope):
            shown += "\n" + str(t.get("full") or t.get("result") or "")
    names = []
    for i in blamed:
        name = V[i]["name"]
        if i in near or re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", shown, re.I):
            continue
        names.append(name)
    return (names, ", ".join(V[s]["name"] for s in seeds[:3])) if names else ([], "")


def unlooked(answer: str, trace: list[dict], question: str = "") -> list[str]:
    """(0.10.7) The parts the answer blames whose records it never looked up (records_about, or a query naming them):
    neither they nor what they run on, what runs on them, what they are part of or consist of (obs7dev-h: the cache's
    evictions blamed, its maxmemory change never read: changes looked up on the database only, an older change of the
    database named "a contributing factor"). At most three names; [] when every blamed part was looked up."""
    from supagent.knowledge.brief import _graph, named

    g = _graph()
    V = g["values"]
    victims = set(named(question or "", g, loose=True))          # what the question names: what suffered, no cause
    for s in list(victims):
        victims |= set(g["children"].get(s, []))
    blamed: list[int] = []
    for line in blaming_lines(answer):
        for i in named(_expanded(line), g):
            if i in V and i not in blamed and i not in victims and can_fail(i, g):
                blamed.append(i)
    if not blamed:
        return []
    looked = ""                                          # the change records looked up: records_about, and the
    for t in trace:                                      # queries of a table of changes, deployments, incidents
        tool = t.get("called") or t.get("tool")
        if t.get("status") != "done":
            continue
        args = json.dumps(t.get("args") or {}, default=str).lower()
        if tool == "records_about" or (tool in QUERY_TOOLS and RECORD_TABLE.search(args)):
            looked += "\n" + args + "\n" + str(t.get("result") or "")[:4000].lower()
    if not looked:
        return []                                        # no record looked up at all: other checks say so

    def seen(i: int) -> bool:
        return re.search(r"(?<![\w-])" + re.escape(V[i]["name"].lower()) + r"(?![\w-])", looked) is not None

    out = []
    for i in blamed:
        near = {i, *V[i].get("parents", []), *g["children"].get(i, [])}
        near |= {b for k, b, _n in g["out"].get(i, []) if k == "runs_on"}
        near |= {a for k, a, _n in g["in"].get(i, []) if k == "runs_on"}
        if not any(seen(j) for j in near if j in V):
            out.append(V[i]["name"])
    return out[:3]


# (0.10.7) a question of what a failure reaches: "if X goes down, what is affected?", "which applications depend on
# it if the rack loses power?", "what would break with a failure of X?"
IMPACT_ASKED = re.compile(
    r"\b(?:if|when|should|in case|once)\b[^?.;]{0,80}\b(?:go(?:es)? down|fails?|loses?|is (?:down|lost|unavailable|"
    r"unreachable|offline|shut down|rebooted)|crash(?:es)?|stops?|breaks?|dies|shuts? down|reboots?)\b|"
    r"\b(?:failure|outage|loss|crash|shutdown) of\b|"
    r"\b(?:what|which)\b[^?.;]{0,60}\b(?:would|will|could)\b[^?.;]{0,30}\b(?:be )?(?:affected|impacted|break|stop|"
    r"fail|go down)\b|"
    r"\bsi\b[^?.;]{0,80}\b(?:tombe|est en panne|plante|perd|s'arr[êe]te)\b", re.I)
# what goes down with a failure in system_links' if_it_fails (what may go on elsewhere is not counted)
REACH_KEYS = ("runs_on_it", "runs_on_its_servers", "goes_down_with_it", "uses_it", "then_through_them", "and_further")


def _reached(item: dict[str, Any]) -> list[tuple[str, str]]:
    """(name, line) of each part one place's failure reaches (an if_it_fails item of system_links); a part that also
    runs elsewhere may go on there: left out."""
    out: list[tuple[str, str]] = []
    for key, val in item.items():
        if str(key).split(" (", 1)[0] not in REACH_KEYS:     # (runs_on_its_group: what may go on, not counted)
            continue
        lines = [x for v in val.values() for x in (v if isinstance(v, list) else [v])] if isinstance(val, dict) \
            else (val if isinstance(val, list) else [val])
        for line in lines:
            line = str(line)
            name = line.split(" (", 1)[0].strip()
            if name and "also runs on" not in line and all(n != name for n, _l in out):
                out.append((name, line))
    return out


def reach_unsaid(question: str, answer: str, reach: dict[str, Any] | None) -> list[str]:
    """(0.10.7) "If cache-01 goes down, what is affected?": system_links said what its failure reaches (the cache on
    it, the application that depends on the cache, the one that calls that application); the answer named the first
    two (obs7dev-j). The lines of the parts reached that the answer does not name; [] when the question asks no
    failure's reach or no system_links of the answer said one (`reach`: its if_it_fails, by place)."""
    if not reach or not answer or not IMPACT_ASKED.search(question or ""):
        return []
    text = answer.lower()
    out: list[str] = []
    for item in reach.values():
        if not isinstance(item, dict):
            continue
        for name, line in _reached(item):
            if line not in out and not re.search(r"(?<![\w-])" + re.escape(name.lower()) + r"(?![\w-])", text):
                out.append(line)
    return out
