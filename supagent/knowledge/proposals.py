"""What the documents and the code state, proposed for the categories and the System map (0.10, the user's request
of 6 October 2026: the wiki, the repositories' code and files, the catalog understood, their parts, links and
categories proposed, compared with what exists, each with approval).

From the understanding (knowledge.understand: who calls whom, what reads or writes what, what runs where, which
indices and metrics are whose):
  values  the parts they name that are no value yet, in the category their kind says: a service an application; a
          database, a cache or a tool a component; a host the deployment's server category (none: not proposed);
          their other names (a repository's, a telemetry name) as synonyms
  links   between values: calls, sends data to, reads from, depends on, runs on, monitors; a server part of its
          group (an inventory's host in its group: the servers grouped as the inventory groups them)
  items   a part's indices and metrics (what it logs to, emits, writes, is watched by) given to it
Each waits in To review with where it was read (the line of a file, the sentence of a page, the arrow of a
diagram). Compared with what exists:
  - stated again: confirmed (where it was read is kept with it), nothing proposed
  - a learned link the other way round (the code says a calls b, a link says b calls a): its removal proposed
  - what the documents proposed before and no longer state: a proposal withdrawn; an approved link, its removal
    proposed (never removed alone)
A value, a link or an item a person refused is never proposed again; nothing a person made is changed.
"""

from __future__ import annotations

from collections import Counter

import logging
import re
from typing import Any

from superset import db

from supagent.knowledge.sysmap import worded

log = logging.getLogger(__name__)

SOURCE = "docs"
STATE_KEY = "proposals_state"   # how many facts the last reading gave (supagent_meta)
SHRUNK = 0.5                    # fewer than half of them now (a document not fetched a moment): nothing withdrawn
LINK_OF = {"calls": "calls", "sends_to": "sends_to", "reads_from": "reads_from", "uses": "depends_on",
           "runs_on": "runs_on", "monitors": "monitors", "in_group": "part_of", "routes_to": "calls",
           "part_of": "part_of"}                       # (0.10.10) "X is a module of Y": a system and its parts
# (0.10.9) what a table of hosts says of each host besides what runs there: its power, its network ports, its owner: a
# link in words, as a person draws it on the map (the same link when one did), from the host to a value of the
# deployment's category for it (by the category's name; none: no link proposed)
WORDED = {"powered_by": "powered by", "connects_to": "connects to", "owned_by": "owned by"}
LINK_OF.update({verb: worded(words) for verb, words in WORDED.items()})
TEAMS = re.compile(r"\bteams?\b|owners?|squads?|tribes?|crews?|guilds?|[ée]quipes?", re.I)
INFRA_CATEGORY = {"power": re.compile(r"power|\bpdus?\b|\bups\b|electric", re.I),
                  "port": re.compile(r"switch\s*ports?|network\s*ports?|\bports?\b", re.I),
                  "team": TEAMS, "owner": TEAMS}
HOSTS_SAY = ("power", "port", "team")   # what a table of hosts says of its host ("owner": a table of parts' team)


def _infra(r: dict[str, Any]) -> bool:
    """(0.10.9) A host's power, network port or owner (a page's table of hosts), a part's owning team (a table of
    parts); an owner that is no team (a person's name) stays a fact of the Context pages, no link."""
    return r["kind"] in WORDED and r.get("obj_kind") in INFRA_CATEGORY
FLOWS = ("calls", "sends_to", "reads_from", "depends_on")
# (0.10.10) where each end of a fact stands: a place parts run on, an end of a flow, an owner
# (0.10.10) what a name said once on one page is not proposed as: a part, a place, or a kind only a word next to it
# says (the members of "Modules: a, b", "Domain: x"); a datastore, a topic or a job a table or a script says it is
NUMBERED_HOST = re.compile(r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*[-_.]?\d{1,4}[a-z]?")   # (0.10.9.3) clinic-app-01,
#                                                  db02, meet-jvb-1: a server's name, not a word of a sentence
SAID_ONCE_KINDS = ("part", "host", "group", "vip", "component", "module", "service", "application", "platform",
                   "product line", "domain", "environment", "server pool", "host group", "namespace", "cluster")
PLACE_WORD_KINDS = ("server pool", "host group", "namespace", "cluster", "environment")
ROLES = {"runs_on": ("flow", "place"), "in_group": ("place", "place"), "part_of": (None, "whole"),
         "calls": ("flow", "flow"),
         "sends_to": ("flow", "flow"), "reads_from": ("flow", "flow"), "uses": ("flow", "flow"),
         "monitors": ("flow", "flow"), "routes_to": ("place", "flow")}
STORE_NAME = re.compile(r"(?:^|[-_])(?:db|database|cache|queue|bus|broker|store|storage|sessions)$|db$")   # (0.10.6)
#   what holds data or messages, by its name (ordersdb, event-bus, photo-store): read and written, it calls no one
CONFIDENCE = {"code": 0.95, "config": 0.9, "inferred": 0.8, "diagram": 0.8, "table": 0.75, "doc": 0.7, "wiki": 0.7,
              "llm": 0.6}
# (0.10.9.2, the team's report of 12 October: 500 applications to review, read from thousands of pages) a part no value
# names yet is proposed when something more than one sentence says it: the code, a configuration, what follows from
# them, a diagram, the data; else learn.new_part_min_units documents or pages at least (2). A name one page says
# once stays in the search (its page is found), no value
STRONG = {"code", "config", "inferred", "diagram", "table", "data"}
# a part that is a store or a tool of the platform, by its name: a component rather than an application
TECHNICAL = re.compile(r"(^|[\W_])(db|database|postgres(ql)?|pg|mysql|mariadb|oracle|mongo(db)?|redis|memcached|cache|"
                       r"kafka|rabbit(mq)?|queue|topic|broker|zookeeper|etcd|s3|bucket|minio|elastic(search)?|"
                       r"opensearch|loki|prometheus|mimir|grafana|alertmanager|fluent-?bit|fluentd|logstash|filebeat|"
                       r"vector|otel|collector|jaeger|tempo|nginx|haproxy|envoy|ingress|exporter)($|[\W_])", re.I)


def _norm(name: str) -> str:
    return " ".join(str(name or "").lower().replace("_", "-").split())


_SHAPED: set[str] = set()   # (0.10.10) values this proposals run filed by their name's shape alone (weak)


def _category(kind: str, name: str, said: Any = None, published: bool = False, named: Any = None,
              only_end: bool = False) -> str | None:
    """The category a new part is proposed in (see the module); None: not proposed. (0.10.10) The deployment's own
    category for what the part is (placing: the words next to its name, what the reading knows of it, its name's
    shape), when it has one; else as before."""
    from supagent import settings
    from supagent.knowledge.catkind import kind_name, serverish
    from supagent.knowledge.facets import editable
    from supagent.knowledge.placing import best_category, choose

    from supagent.knowledge.naming import filed

    cats = list(editable())
    about = settings.get("categories.about") or {}
    own_cats = set(settings.get("categories.custom") or [])
    if kind and kind not in ("part", "host", "group", "vip", "namespace", "cluster") and kind not in INFRA_CATEGORY:
        direct = next((c for c in cats if c in own_cats and   # (0.10.10) the documents say what it
                       _norm(kind_name(c)) in (_norm(kind), _norm(kind) + "s", _norm(re.sub(r"s$", "", kind)))), None)
        if direct:                                         # is ("the following components:", "Domain: x") and the
            return direct                                  # person has a category of that very name
    if kind == "environment":                              # (0.10.10) an inventory's environment: the person's
        from supagent.knowledge.placing import best_category as _best   # category for environments, else a group
        own_env = _best("environment", cats, about)
        if own_env:
            return own_env
        kind = "group"
    if named:                                              # (0.10.10) the page names the category next to it ("the
        from supagent.knowledge.placing import HOSTISH, affinity   # X platform service", "the queue X")
        top = named.most_common(2)
        if top and (len(top) == 1 or top[0][1] > top[1][1]) and top[0][0] in cats:
            c = top[0][0]
            a = affinity(c, about.get(c, ""))
            place = serverish(c) or (a.most_common(1)[0][0] in HOSTISH if a else False)
            if place == (kind in ("host", "vip", "group", "namespace", "cluster")):
                return c
    if kind in ("host", "vip", "group", "namespace", "cluster"):   # (0.10.4) a VIP: an address, with the servers
        hosts = [c for c in cats if serverish(c)]
        base = next((c for c in hosts if re.fullmatch(r"(servers?|hosts?|vms?|virtual machines?|machines?|nodes?)",
                                                      kind_name(c).strip(), re.I)), hosts[0] if hosts else None)
        return choose(base, kind, name, said, [c for c in cats if c != "subject"], about, published)
    if kind in INFRA_CATEGORY:                             # (0.10.9) a power supply, a switch port, a team: the
        return next((c for c in cats if INFRA_CATEGORY[kind].search(kind_name(c))), None)   # deployment's category,
    #                                                                                                  else none
    if kind in ("database", "cache", "object", "topic", "queue", "stream", "job") or TECHNICAL.search(name):
        base = "component" if "component" in cats else None   # (data and jobs: no application)
    else:
        base = "application" if "application" in cats else None
    # (0.10.6.2) a monitoring tool, an infrastructure service or a database server no application (the
    # deployment's category for them, else a component); a library or a framework no part (naming.filed)
    to, what = filed(base, name, None, cats) if base else (None, None)
    if to is None and what == "library":
        return None
    own = choose(None, kind, name, said, [c for c in cats if c not in ("subject", "application", "component")],
                 about, published)
    from supagent.knowledge.placing import KIND_CONCEPT

    if own is not None and not sum((said or {}).values()) and not KIND_CONCEPT.get(kind or ""):
        _SHAPED.add(_norm(name))                           # (only its name's shape said it: "x-batch" a job)
    if own is None and to == "application" and only_end and kind == "part" and not sum((said or {}).values()) and \
            any(best_category(c, cats, about) for c in ("external", "object", "messaging", "store")):
        return None                                        # (0.10.10) only read from or written to (it does nothing
    #                                                        itself), of no kind its pages say, where the deployment
    #                                                        files such things elsewhere: no application
    if own is None and to == "application" and "application" not in own_cats:
        from supagent.knowledge.facets import inside

        wholes = set(inside().values())                    # a category holding categories is a whole (a system of
        #                                                    microservices): its parts find their own category through
        #                                                    the nesting; a place's "site": none; (0.10.9.2) each
        #                                                    category by its name or what its description says
        services = [c for c in cats if c in own_cats and SERVICE_CATEGORY.search(kind_name(c)) and
                    not serverish(c) and not NOT_OWN_SERVICE.search(kind_name(c)) and c not in wholes and
                    (not BARE_SITE.search(kind_name(c)) or WEB_WORDS.search(about.get(c) or ""))]
        if len(services) == 1 and not _person_uses("application"):
            return services[0]                             # (0.10.10) the person files the system's applications
        #                                                    in their one category of services ("platform service")
        mine = best_category("application", services, about) if len(services) > 1 else None
        if mine and not _person_uses("application"):       # (0.10.9.2) several: the one its name or description
            return mine                                    # says is for what users use ("product": "what the
    return own or to                                       # community uses: a web application, ...")


SERVICE_CATEGORY = re.compile(r"\b(services?|applications?|apps?|systems?|platforms?|products?|sites?|websites?|"
                              r"portals?)$", re.I)   # (0.10.9.2) a site, a portal: what users use; its
BARE_SITE = re.compile(r"(?<!web)(?<!web )\bsites?$", re.I)   # (0.10.9.2) "site" alone: a web site only when its
WEB_WORDS = re.compile(r"(?i)\b(?:web|website|portal|api|application|app|users?|public|online|internet)\b")   # say so
#                                       head noun ("platform service"; a "service area" is an area)
# (0.10.10) a category of services that are not the system's own: never where its applications go
NOT_OWN_SERVICE = re.compile(r"\b(external|third[- ]?part(?:y|ies)|partners?|vendors?|providers?|suppliers?|saas|"
                             r"cloud|public|legacy|retired|shared)\b", re.I)
_USES: dict[str, tuple[float, bool]] = {}


def _person_uses(category: str) -> bool:
    """(0.10.10) A person approved a value in this category (read again at most every minute)."""
    import time

    from supagent.models import Facet

    at, used = _USES.get(category, (0.0, False))
    if time.time() - at > 60:
        used = db.session.query(Facet.id).filter(Facet.facet == category, Facet.status == "approved").first() \
            is not None
        _USES[category] = (time.time(), used)
    return used


def _refile_inside() -> int:
    """(0.10.10) The person's nesting of categories says what a part of a value is: a learned application or
    component that is part of a value whose category holds exactly one category inside it (modules inside the
    platform services, streams inside the messaging clusters) goes to that one; a person's value never moves."""
    from supagent.knowledge.facets import PART_OF, inside, same_name
    from supagent.models import Facet, Link

    kids: dict[str, list[str]] = {}
    for k, p in inside().items():
        kids.setdefault(p, []).append(k)
    if not kids:
        return 0
    n = 0
    for x in db.session.query(Link).filter(Link.kind == PART_OF, Link.status.in_(("proposed", "approved"))):
        if not (x.a_ref.startswith("facet:") and x.b_ref.startswith("facet:")):
            continue
        part, whole = db.session.get(Facet, int(x.a_ref[6:])), db.session.get(Facet, int(x.b_ref[6:]))
        if part is None or whole is None or part.facet not in ("application", "component"):
            continue
        if part.status != "proposed" or part.reviewed_by is not None or part.source not in ("docs", "llm", "data"):
            continue
        ks = kids.get(whole.facet) or []
        if len(ks) != 1 or db.session.query(Facet.id).filter(Facet.facet == ks[0], same_name(Facet.value, part.value)
                                                            ).first() is not None:
            continue
        part.facet = ks[0]
        n += 1
    if n:
        db.session.flush()
    return n


def _refile_wholes() -> int:
    """(0.10.10) The person's nesting says what a whole is too: a learned value its parts are part of, the parts filed in
    a category held inside another (topics inside the event buses, servers inside the pools, components inside the
    applications), goes to that one when most of its parts say so; a person's value never moves."""
    from collections import Counter

    from supagent.knowledge.facets import PART_OF, inside, same_name
    from supagent.models import Facet, Link

    parent = inside()
    if not parent:
        return 0
    votes: dict[int, Counter] = {}
    for x in db.session.query(Link).filter(Link.kind == PART_OF, Link.status.in_(("proposed", "approved"))):
        if not (x.a_ref.startswith("facet:") and x.b_ref.startswith("facet:")):
            continue
        part = db.session.get(Facet, int(x.a_ref[6:]))
        if part is not None and part.facet in parent:
            votes.setdefault(int(x.b_ref[6:]), Counter())[parent[part.facet]] += 1
    n = 0
    for wid, c in votes.items():
        whole = db.session.get(Facet, wid)
        if whole is None or whole.status != "proposed" or whole.reviewed_by is not None or \
                whole.source not in ("docs", "llm", "data") or whole.facet not in ("application", "component"):
            continue                                       # (only a whole left where nothing said what it is: a
            #                                                server's group, rack or VIP each stays where it was put)
        top = c.most_common(2)
        if len(top) > 1 and top[0][1] == top[1][1]:
            continue
        target = top[0][0]
        if whole.facet == target or db.session.query(Facet.id).filter(Facet.facet == target,
                                                                       same_name(Facet.value, whole.value)).first():
            continue
        whole.facet = target
        n += 1
    if n:
        db.session.flush()
    return n


GENERIC_CATS = ("application", "component")
NOT_SYSTEM_CONCEPTS = {"host", "group", "vip", "namespace", "cluster", "balancer", "store", "cache", "messaging",
                       "broker", "object", "job", "external", "team", "domain", "environment", "dashboard", "alert",
                       "certificate", "dns"}


def _system_pair() -> tuple[str, str] | None:
    """(0.10.10) The person's one nesting of systems and their parts (application > component, system >
    microservice, platform service > module): two of the person's categories, neither a place nor data; none when
    there are several or none."""
    from supagent import settings
    from supagent.knowledge.facets import inside
    from supagent.knowledge.placing import affinity

    own = set(settings.get("categories.custom") or [])
    about = settings.get("categories.about") or {}

    def kind(c: str) -> str:
        a = affinity(c, about.get(c, ""))
        return a.most_common(1)[0][0] if a else ""

    pairs = [(p, c) for c, p in inside().items() if c in own and p in own and
             kind(c) not in NOT_SYSTEM_CONCEPTS and kind(p) not in NOT_SYSTEM_CONCEPTS]
    return pairs[0] if len(pairs) == 1 else None


def _refile_structure() -> int:
    """(0.10.10) A learned whole of learned parts both left in the generic categories (nothing said what either is)
    goes to the person's one nesting of systems and their parts: the whole to the outer category, its parts to the
    inner one (a part its name's shape alone filed elsewhere too: "x-batch", one of x's parts); a person's value
    never moves."""
    from supagent.knowledge.facets import PART_OF, same_name
    from supagent.models import Facet, Link

    pair = _system_pair()
    if pair is None:
        return 0
    outer, inner = pair
    kids: dict[int, list[Any]] = {}
    for x in db.session.query(Link).filter(Link.kind == PART_OF, Link.status.in_(("proposed", "approved"))):
        if x.a_ref.startswith("facet:") and x.b_ref.startswith("facet:"):
            part = db.session.get(Facet, int(x.a_ref[6:]))
            if part is not None and (part.facet in GENERIC_CATS + (inner,) or _norm(part.value) in _SHAPED):
                kids.setdefault(int(x.b_ref[6:]), []).append(part)

    def learned(f: Any) -> bool:
        return f.status == "proposed" and f.reviewed_by is None and f.source in ("docs", "llm", "data")

    n = 0
    for wid, parts in kids.items():
        whole = db.session.get(Facet, wid)
        if whole is None or len(parts) < 2 or not (whole.facet == outer or (whole.facet in GENERIC_CATS and
                                                                            learned(whole))):
            continue
        if whole.facet != outer and not db.session.query(Facet.id).filter(Facet.facet == outer,
                                                                         same_name(Facet.value, whole.value)).first():
            whole.facet = outer
            n += 1
        for part in parts:
            if part.facet != inner and learned(part) and not db.session.query(Facet.id).filter(
                    Facet.facet == inner, same_name(Facet.value, part.value)).first():
                part.facet = inner
                n += 1
    _SHAPED.clear()                                       # (this run's shapes only)
    if n:
        db.session.flush()
    return n


def _rank(f: Any) -> tuple:
    """(0.10.6) Which of the values of one name a fact is about: not refused, approved, then the oldest."""
    return (f.status == "rejected", f.status != "approved", f.id or 0)


def _llm_proposal(f: Any) -> bool:
    """(0.10.6) A value the AI proposed and nobody approved, edited nor refused yet."""
    return f.status == "proposed" and f.source == "llm"


def _evidence(r: dict[str, Any]) -> str:
    where = r.get("where") or ""
    return (f'{r.get("quote") or ""} ({where}{"; " if where else ""}{", ".join(r.get("sources") or [])})')[:2000]


def _confidence(r: dict[str, Any]) -> float:
    return max([CONFIDENCE.get(s, 0.6) for s in r.get("sources") or []] or [0.6])


def _quote_of(evidence: str | None) -> str:
    """A link's evidence without its "(where; sources)" tail: the words a document said."""
    e = (evidence or "").strip()
    if e.endswith(")"):
        depth = 0
        for i in range(len(e) - 1, -1, -1):
            depth += {")": 1, "(": -1}.get(e[i], 0)
            if depth == 0:
                return e[:i].rstrip()
    return e


def still_written(evidence: str | None) -> bool:
    """(0.10.5) Whether the words a learned link was read from are still in an enabled document (its first and last
    ten words, whatever the line breaks between them): then the reading changed (a name approved since, read in the
    same sentence), not what the documents say, and its removal is not proposed: only a document updated or removed
    proposes one (the user's rule of 8 October)."""
    from supagent.models import Doc

    words = _quote_of(evidence).split()
    if len(words) < 3:
        return False

    def pattern(ws: list[str]) -> str:
        return "%" + "%".join(w.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for w in ws) + "%"

    q = db.session.query(Doc.id).filter(Doc.enabled.is_(True))
    for ws in ([words[:10], words[-10:]] if len(words) > 10 else [words]):
        q = q.filter(Doc.content.like(pattern(ws), escape="\\"))
    try:
        return q.first() is not None
    except Exception:  # pylint: disable=broad-except   (a database that cannot match the pattern: as before)
        db.session.rollback()
        return False


def propose(dry_run: bool = False) -> dict[str, Any]:
    """The proposals made again from what the documents and the code state now (see the module). Counts."""
    from supagent.knowledge.facets import editable, merge_value, suggest_link
    from supagent.knowledge.understand import export
    from supagent.models import Facet, KObject, Link, Tag

    g = export()
    _SHAPED.clear()
    out = {"values": 0, "links": 0, "confirmed": 0, "removals": 0, "withdrawn": 0, "items": 0, "not placed": 0}
    if not dry_run:                                       # (0.10.6.2) what waits from an older reading, put right
        from supagent.knowledge.naming import tidy

        out.update({k: v for k, v in tidy().items() if v})
    import json as _json

    from supagent.models import Meta

    now = len(g.get("relations") or []) + len(g.get("data_links") or [])
    row = db.session.get(Meta, STATE_KEY)
    try:
        before = int((_json.loads(row.value) if row is not None and row.value else {}).get("facts") or 0)
    except (ValueError, TypeError, AttributeError):
        before = 0
    shrunk = before >= 10 and now < before * SHRUNK      # what the documents state did not vanish at once: wait
    if shrunk:
        out["kept: fewer facts read than before"] = f"{now} of {before}"
    from supagent.knowledge.interactions import TOPICS

    cats = set(editable())
    values: dict[str, Facet] = {}
    topics: dict[str, list[Facet]] = {}                   # (0.10.6) the subjects: topics, never a link's end
    for f in db.session.query(Facet).filter(Facet.facet.in_(list(cats))).order_by(Facet.id):
        for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
            key = _norm(n)
            if not key:
                continue
            if f.facet in TOPICS:
                if f.status != "rejected" and f not in topics.get(key, []):
                    topics.setdefault(key, []).append(f)
                continue
            if key not in values or _rank(f) < _rank(values[key]):   # (0.10.6) a part a person approved before a
                values[key] = f                                      # proposed one of the same name, then the oldest
    aliases: dict[str, set[str]] = {}
    for a in g.get("aliases") or []:
        aliases.setdefault(_norm(a["part"]), set()).add(a["name"])
    # an inventory's group named like a part (a group "web" and an application "web"): two values, the group's
    # "web (group)"
    rels = g.get("relations") or []
    groups = {_norm(r["to"]) for r in rels if r["kind"] == "in_group" or
              (r["kind"] == "runs_on" and r.get("obj_kind") == "group")}
    partish = {_norm(r["from"]) for r in rels if r["kind"] not in ("in_group", "alias") and r["kind"] not in WORDED} | \
        {_norm(r["to"]) for r in rels if r["kind"] in LINK_OF and r["kind"] not in ("in_group", "runs_on") and
         r["kind"] not in WORDED}
    from supagent.knowledge.catkind import serverish

    servers = {_norm(f.value) for f in values.values() if f.status == "approved" and serverish(f.facet)}
    vips = {_norm(r["from"]) for r in rels if r["kind"] == "routes_to"}
    kept_topics = {k for k, fs in topics.items() if not all(_llm_proposal(f) for f in fs)}
    env_levels = {_norm(re.sub(r"^.*\(([^()]+)\)\s*$", r"\1", str(r["from"]))) for r in rels   # (0.10.10) what an
                  if r["kind"] == "in_group" and re.search(r"\(([^()]+)\)\s*$", str(r["from"])) and   # inventory's
                  _norm(re.sub(r"^.*\(([^()]+)\)\s*$", r"\1", str(r["from"]))) == _norm(r["to"])}  # groups are kept
    #                                                       per: "web (orders PRD)" in "orders PRD", an environment
    clash = (groups & (partish | set(topics))) - servers - vips - env_levels   # (0.10.5) a group already on the map
    #                                                       as a server
    #                                                       stays itself; a VIP is an address with its servers, not a
    #                                                       group to rename; (0.10.6) a group named like a subject
    #                                                       ("monitoring", a topic): "monitoring (group)"

    def as_group(name: str) -> str:
        return f"{name} (group)" if _norm(name) in clash else name

    def ends(r: dict[str, Any]) -> tuple[str, str]:
        if r["kind"] == "in_group":
            return (as_group(r["from"]) if _norm(r["from"]) in groups else r["from"]), as_group(r["to"])
        if r["kind"] == "runs_on" and r.get("obj_kind") == "group":
            return r["from"], as_group(r["to"])
        return r["from"], r["to"]

    # (0.10.9) a device the reading names as a power supply or a switch (a powered_by target, a port's switch) is no
    # host: an asset register's row for it ("Asset | Hostname | Owner": a PDU, a switch) gives it no owner link
    power_dev = {_norm(r["to"]) for r in rels if r["kind"] == "powered_by"}
    switch_dev = {_norm(str(r["to"]).split(" ")[0]) for r in rels if r["kind"] == "connects_to"}

    def device_row(r: dict[str, Any]) -> bool:
        """A table of hosts' row about a device: a power supply keeps its own supply (a PDU on its UPS), nothing else."""
        if r["kind"] not in WORDED or r.get("obj_kind") not in HOSTS_SAY:
            return False
        a = _norm(r["from"])
        return r["kind"] != "powered_by" if a in power_dev else a in switch_dev

    rels = [r for r in rels if not device_row(r)]
    # (0.10.10) the specific link over the general one: a flow to a whole (a message broker, an event bus) when the
    # same part flows the same way to a part of it (one of its topics) is that flow said less precisely: not proposed
    held_in: dict[str, set[str]] = {}
    for r in rels:
        if r["kind"] == "part_of":
            held_in.setdefault(_norm(r["to"]), set()).add(_norm(r["from"]))
    flows = {(_norm(r["from"]), r["kind"], _norm(r["to"])) for r in rels if r["kind"] in ("sends_to", "reads_from")}
    rels = [r for r in rels if not (r["kind"] in ("sends_to", "reads_from") and any(
        (_norm(r["from"]), r["kind"], x) in flows for x in held_in.get(_norm(r["to"]), ())))]
    # (0.10.9.2) what says each name: the pages and files (units), the kinds of source
    evidence: dict[str, tuple[set[Any], set[str]]] = {}
    statements: dict[str, set[str]] = {}                  # (0.10.9.3) the sentences and rows that say each name

    def note(name: str, r: dict[str, Any]) -> None:
        units, sources = evidence.setdefault(_norm(name), (set(), set()))
        units.update(r.get("unit_ids") or ())            # (the pages and files: export()'s unit ids)
        sources.update(r.get("sources") or ())
        statements.setdefault(_norm(name), set()).update(r.get("said") or ())

    for r in rels:
        for end in ends(r):
            note(end, r)
    for d in g.get("data_links") or []:
        evidence.setdefault(_norm(d["part"]), (set(), set()))[1].add("data")
    try:
        from supagent import settings as _settings

        min_units = max(1, int(_settings.get("learn.new_part_min_units") or 2))
    except Exception:  # pylint: disable=broad-except
        min_units = 2

    placed_on = {_norm(r["to"]) for r in rels if r["kind"] == "runs_on"}   # (0.10.9.3) where a part runs

    def established(key: str) -> bool:
        units, sources = evidence.get(key, (set(), set()))
        return bool(sources & STRONG) or len(units) >= min_units or len(statements.get(key, ())) >= 2 or \
            (key in placed_on and bool(NUMBERED_HOST.fullmatch(key)))   # a numbered server a part runs on
        #   (0.10.9.3) never from one sentence of one page; two of its sentences or rows (six services calling a
        #   config server, each in its own row of one page) say it

    kind_of: dict[str, str] = {}                          # what each part is, as the facts name it
    word_kind: dict[str, str] = {}                        # (0.10.10) what a word next to it says ("the following
    for r in rels:                                        # components:"): weaker than what its data says it is
        if r["kind"] == "is_a" and r["to"] in SAID_ONCE_KINDS:
            word_kind[_norm(r["from"])] = r["to"]
        elif r["kind"] == "is_a":                         # (0.10.10) what a table's kind column or a job's script
            kind_of[_norm(r["from"])] = r["to"]           # says it is (a job, a database, a topic, a bucket)
    for r in rels:
        a, b = ends(r)
        if r["kind"] == "is_a":
            continue
        if r["kind"] == "in_group":                       # an inventory's host in its group: both servers
            kind_of[_norm(a)] = "host" if kind_of.get(_norm(a)) != "group" else "group"   # (a VIP's servers grouped
            kind_of[_norm(b)] = "vip" if _norm(b) in vips else "environment" if _norm(b) in env_levels \
                else "group"                              # under it: a VIP is an address); (0.10.10) an inventory's
            continue                                      # the group: the deployment's category for groups, else a
            #                                               server one
        if r["kind"] == "routes_to":                      # (0.10.4) a VIP: an address, with the servers; (0.10.10)
            kind_of[_norm(a)] = "vip"                     # the deployment's category for VIPs, else a server one
        if r["kind"] in WORDED:                           # (0.10.9) a host's power, ports, owner: a host (a part's
            if _norm(a) in power_dev and kind_of.get(_norm(a)) in (None, "part"):   # owner: itself; a power
                kind_of[_norm(a)] = "power"                 # supply's own supply: a power device)
            elif r.get("obj_kind") in HOSTS_SAY and kind_of.get(_norm(a)) in (None, "part"):
                kind_of[_norm(a)] = "host"
            if not _infra(r):
                continue
        kind_of.setdefault(_norm(a), "part")
        if r["kind"] in LINK_OF:
            k = "group" if r.get("obj_kind") == "group" else str(r.get("obj_kind")) if r["kind"] == "runs_on" and \
                r.get("obj_kind") in ("namespace", "cluster", "environment") else "host" if r["kind"] == "runs_on" else \
                str(r.get("obj_kind") or "part")
            kind_of[_norm(b)] = k if kind_of.get(_norm(b)) in (None, "part") or (   # (0.10.10) a namespace, a group
                kind_of.get(_norm(b)) == "host" and k in ("namespace", "group", "cluster")) else kind_of[_norm(b)]
    for d in g.get("data_links") or []:
        kind_of.setdefault(_norm(d["part"]), "part")
    for k, v in word_kind.items():                        # (a database of a URL stays one, listed as a component;
        if kind_of.get(k) in (None, "part") or (kind_of.get(k) == "host" and v in PLACE_WORD_KINDS):   # a "server
            kind_of[k] = v                                # pool" its list says over a plain "runs on" place)
    for r in rels:                                        # (0.10.9.1) a part that runs on a place of the system is
        if r["kind"] == "runs_on" and kind_of.get(_norm(r["from"])) == "external":   # its own, whatever address a
            kind_of[_norm(r["from"])] = "part"            # page gives it

    if not dry_run and not shrunk:                         # (0.10.9.2) what waits from an older reading and one page
        from supagent.knowledge.naming import withdraw    # says once: withdrawn (it comes back if more say it)

        approved_ends = {r for (a, b) in db.session.query(Link.a_ref, Link.b_ref).filter(Link.status == "approved")
                         for r in (a, b)}
        for f in {id(f): f for f in values.values()}.values():
            if (f.status != "proposed" or f.source != SOURCE or f.reviewed_by is not None
                    or f"facet:{f.id}" in approved_ends):
                continue
            names = [f.value] + [str(x) for x in (f.synonyms or [])]
            if any(established(_norm(n)) or kind_of.get(_norm(n), "part") not in SAID_ONCE_KINDS
                   for n in names):
                continue
            for k in [k for k, v in values.items() if v is f]:
                values.pop(k, None)
            withdraw(f)
            out["withdrawn: said once in one page"] = out.get("withdrawn: said once in one page", 0) + 1
        db.session.flush()

    merged: set[int] = set()

    def ai_subjects_into(key: str, part: Facet) -> None:
        """(0.10.6) The subjects the AI proposed with the name of a part the code, a configuration or a page names
        (it read the name before they did): that part, with what they were given; a person's subject stays, and a
        server is no topic's twin."""
        if dry_run or key in kept_topics or serverish(part.facet):
            return
        for t in topics.pop(key, []):
            if t.id in merged:                            # (one of its other names merged it already)
                continue
            merged.add(t.id)
            merge_value(t, part)
            out["subjects the AI proposed: the part"] = out.get("subjects the AI proposed: the part", 0) + 1

    from supagent.knowledge.placing import cues as cue_words

    from supagent.knowledge.placing import named_categories

    near: dict[str, Any] = {}                             # (0.10.10) the words next to each name in its sentences
    near_cat: dict[str, Any] = {}                         # and the deployment's categories written next to it
    cat_list = sorted(cats)
    from supagent.knowledge.consolidate import keys as name_keys

    def cue_key(name: str) -> str:                        # (0.10.10) a name's cues, however it is written
        return name_keys(name)["written"] or _norm(name)

    for r in rels:
        for end in (r["from"], r["to"]):
            if r.get("quote"):
                c = cue_words(r["quote"], end)
                if c:
                    near.setdefault(cue_key(end), Counter()).update(c)
                nc = named_categories(r["quote"], end, cat_list)
                if nc:
                    near_cat.setdefault(cue_key(end), Counter()).update(nc)
    published = {_norm(r["to"]) for r in rels if r["kind"] in ("sends_to", "reads_from")}
    acting = {_norm(r["from"]) for r in rels if r["kind"] != "part_of"}   # (0.10.10) what calls, runs, reads...
    from supagent.knowledge.consolidate import keys as name_keys

    def written_key(name: str, host: bool) -> str:        # (0.10.9.2) a name written another way (case, separators,
        return ("h|" + name_keys(name, "server")["written"]) if host else ("p|" + name_keys(name)["written"])
    #                                                       camelCase, a plural, a short form): that value; a host's
    written: dict[str, Facet] = {}                        # or a group's name as written (db, databases: two groups)
    for key, f in values.items():
        for nm in {key, f.value, *[str(x) for x in (f.synonyms or [])]}:   # (0.10.10) as written: ConsentManager is
            k = written_key(nm, serverish(f.facet))      # "consent manager", not "consentmanager"
            if k not in written or _rank(f) < _rank(written[k]):
                written[k] = f

    from supagent import settings as _cfg
    from supagent.knowledge.placing import HOSTISH, affinity

    about_of = _cfg.get("categories.about") or {}
    concept_of: dict[str, str] = {}                       # (0.10.10) what each category is (its name, its words)

    def concept(cat: str) -> str:
        if cat not in concept_of:
            a = affinity(cat, about_of.get(cat, ""))
            concept_of[cat] = a.most_common(1)[0][0] if a else ""
        return concept_of[cat]

    homonyms: dict[str, list[Facet]] = {}                 # (0.10.10) one name, several things (a namespace, a domain)
    for f in db.session.query(Facet).filter(Facet.facet.in_(list(cats)), Facet.status != "rejected"):
        if f.facet in TOPICS:
            continue
        for n in [f.value] + [str(x) for x in (f.synonyms or [])]:
            homonyms.setdefault(_norm(n), [])
            if f not in homonyms[_norm(n)]:
                homonyms[_norm(n)].append(f)
    qualified: dict[str, set[str]] = {}                   # "x (repo prod)", "x (repo uat)": x's qualified names
    for r in rels:
        for end in ends(r):
            if re.search(r"\s\([^()]+\)$", end) and not end.endswith("(group)"):
                qualified.setdefault(_norm(re.sub(r"\s*\([^()]+\)$", "", end)), set()).add(_norm(end))
    FITS = {"place": lambda c: c in HOSTISH, "owner": lambda c: c == "team",
            "whole": lambda c: c not in HOSTISH and c != "team",
            "flow": lambda c: c not in HOSTISH and c not in ("team", "domain", "environment")}

    from supagent.knowledge.facets import inside as _inside

    holders = set(_inside().values())                     # (0.10.10) the categories the person nests others in
    by_word: dict[str, list[Any]] = {}

    def variant_of(name: str) -> Any:
        """(0.10.10) The one value already there that a name said once is another writing of (the merge engine's
        sure kinds of sameness: the same words, a typo, an environment's word), else None."""
        from supagent.knowledge.consolidate import same, words

        if not by_word:
            for f in {id(v): v for v in values.values()}.values():
                ws = words(f.value)
                if ws:
                    by_word.setdefault(ws[0], []).append(f)
        ws = words(name)
        found = {f.id: f for f in by_word.get(ws[0], []) if f.status != "rejected" and
                 same(name, f.value, f.facet) in ("strong", "noenv", "typo")} if ws else {}
        return next(iter(found.values())) if len(found) == 1 else None

    def value_of(name: str, role: str | None = None, prefer: str | None = None) -> Facet | None:
        key = _norm(name)
        f = values.get(key) or written.get(written_key(name, kind_of.get(key, "part") != "part"))
        if role and len(homonyms.get(key, [])) > 1:      # (0.10.10) the one of its name that fits where it is said
            fit = [h for h in homonyms[key] if FITS[role](concept(h.facet))]
            if fit:
                f = min(fit, key=_rank)
        if role == "flow" and f is not None and concept(f.facet) in ("team", "domain", "environment"):
            return None                                   # (0.10.10) only a domain, a team or an environment of that
        #                                                   name: nothing it runs on, calls, reads or writes (no link)
        if role == "whole":                               # (0.10.10) "part of the marketing domain": the value of
            if prefer:                                    # that category (made when none), never the group or the
                f = next((h for h in homonyms.get(key, []) if h.facet == prefer), None)   # namespace of the name
                if f is None and values.get(key) is not None and values[key].facet == prefer:
                    f = values[key]
            elif f is not None and not FITS["whole"](concept(f.facet)) and f.status != "rejected" and \
                    f.facet not in holders:               # (0.10.10) a category the person nests others in (the
                return None                               # streams inside a cluster): a whole by the person's design;
                #                                           no category said and only a place of that name: no link
        bare = _norm(re.sub(r"\s*\([^()]+\)$", "", name))
        if (f is None or f.status == "proposed") and bare != key and role == "place" and \
                len(qualified.get(bare, ())) <= 1:        # (0.10.10) "x (group)", "x (repo prod)": a person's group
            fit = [h for h in homonyms.get(bare, []) if concept(h.facet) in HOSTISH and   # named x (one
                   h.status == "approved"]                                                # environment's x only)
            if fit:
                person = min(fit, key=_rank)
                if f is not None and f.id != person.id and not dry_run:   # the learning's own name of it: the same
                    sug = dict(f.suggested or {})                          # as the person's (To review merges it)
                    if sug.get("same_as") != person.id:
                        f.suggested = {**sug, "same_as": person.id, "same_by": "learning", "same_why": "strong"}
                f = person
        if f is not None:
            if f.status == "rejected":
                return None
            ai_subjects_into(key, f)
            return f
        if key in kept_topics:                            # (0.10.6) a subject a person approved or made: the name of
            out["a subject's name: no part"] = out.get("a subject's name: no part", 0) + 1   # a topic, no part (a
            return None                                   # person decides; To review is no place for a twin)
        if kind_of.get(key, "part") in SAID_ONCE_KINDS and not established(key):   # (0.10.9.2)
            #   says it once: the search keeps it (a power device, a switch port, a team, a VIP: what its words make
            #   it, kept); (0.10.10) another writing of a value already there (prepaid_wallet, Idenitty Hub) is that
            #   value: its links go to it, nothing new proposed
            twin = variant_of(name)
            if twin is not None:
                values[key] = twin
                return None if twin.status == "rejected" else twin
            out["said once in one page: not proposed"] = out.get("said once in one page: not proposed", 0) + 1
            return None
        bare = _norm(re.sub(r"\s*\(group\)$", "", name))
        cat = _category(kind_of.get(key, "part"), name, near.get(cue_key(bare)), bare in published,
                        near_cat.get(cue_key(bare)),
                        only_end=bare in published and bare not in acting and key not in acting)
        if role == "whole":                               # (0.10.10) a whole: the category its sentence says, else
            cat = prefer if prefer and prefer in cats else cat   # the chooser's, never a place's
            if cat and (serverish(cat) or concept(cat) in HOSTISH):
                return None
        if cat is None:
            from supagent.knowledge.naming import kind_of as what_part

            if what_part(name) == "library":
                out["a library: no part"] = out.get("a library: no part", 0) + 1
            else:
                out["not placed"] += 1
            return None
        from supagent.knowledge.naming import checked

        shown, others, _why = checked(cat, name)          # (0.10.6.2) a name, not a phrase, not over the limit
        if shown is None:
            out["no name: not proposed"] = out.get("no name: not proposed", 0) + 1
            return None
        other_thing = _norm(shown) != key and _norm(shown) in clash   # (0.10.10) "sso (group)" shown "sso" in a
        #                                                   group category: the part "sso" is another thing
        if _norm(shown) != key and values.get(_norm(shown)) is not None and not other_thing:   # its short name's
            twin = values[_norm(shown)]                                                          # value: that one
            values[key] = twin
            return None if twin.status == "rejected" else twin
        same = db.session.query(Facet).filter(Facet.facet == cat, Facet.value == shown[:128]).first()
        if same is not None:                              # (0.10.10) that very value exists (a whole read twice)
            homonyms.setdefault(key, [])
            if same not in homonyms[key]:
                homonyms[key].append(same)
            return None if same.status == "rejected" else same
        f = Facet(facet=cat, value=shown[:128], status="proposed", source=SOURCE,
                  synonyms=sorted({a for a in aliases.get(key, ()) if _norm(a) != _norm(shown)} | set(others)) or None,
                  origins=["read in the documents and the code"])
        if not dry_run:
            db.session.add(f)
            db.session.flush()
            ai_subjects_into(key, f)
        if values.get(key) is None or role != "whole":   # (0.10.10) a whole beside a place of its name: both kept
            values[key] = f
        homonyms.setdefault(key, []).append(f)
        if not other_thing and (values.get(_norm(shown)) is None or role != "whole"):
            values[_norm(shown)] = f
        for x in ((name,) if other_thing else (shown, name)):
            written.setdefault(written_key(x, serverish(cat)), f)
        out["values"] += 1
        return f

    from supagent.knowledge.sysmap import kept_reasons, propose_drop

    kept = kept_reasons()                                 # (0.10.5) the reasons a person answered Keep to
    stated: set[tuple[int, int, str]] = set()
    said = {(_norm(x), _norm(y), LINK_OF.get(r["kind"])) for r in rels for x, y in [ends(r)]}   # (0.10.5) both
    for r in rels:                                        # ways stated: neither is the other one reversed
        kind = LINK_OF.get(r["kind"])
        if kind is None or (r["kind"] in WORDED and not _infra(r)):
            continue
        if _infra(r):                                     # (0.10.9) a host's power, port, owner with nowhere to go
            b = value_of(ends(r)[1], "owner" if r.get("obj_kind") in ("team", "owner") else None)   # (no category
            a = value_of(ends(r)[0]) if b is not None else None   # for it: no link, and no server proposed for it)
        else:
            ra, rb = ROLES.get(r["kind"], (None, None))
            prefer = None
            if r["kind"] == "part_of" and r.get("quote"):     # (0.10.10) "... of the payments domain": a domain
                said_cat = named_categories(r["quote"], ends(r)[1], cat_list).most_common(1)
                prefer = said_cat[0][0] if said_cat else None
            a, b = value_of(ends(r)[0], ra), value_of(ends(r)[1], rb, prefer)
        if a is None or b is None or a.id == b.id or dry_run:
            continue
        routing = r["kind"] == "routes_to" or any(concept(x.facet) in ("vip", "balancer") for x in (a, b))
        if (kind in FLOWS or kind == "monitors") and not routing and any(   # (a VIP's pool: its servers' group)
                x.status == "approved" and not FITS["flow"](concept(x.facet)) and concept(x.facet) != "host"
                for x in (a, b)):
            out["not a flow's end (what a person filed it as)"] = out.get("not a flow's end (what a person filed it "
                                                                         "as)", 0) + 1
            continue                                      # (0.10.10) "calls" a namespace, a group, a team, a domain
        stated.add((a.id, b.id, kind))
        if kind in FLOWS:                                  # a learned link the other way round: its removal proposed;
            back = (db.session.query(Link).filter(Link.a_ref == f"facet:{b.id}", Link.b_ref == f"facet:{a.id}",
                                                  Link.kind == kind, Link.status == "approved").first())
            person = back is not None and (back.source == "admin" or
                                           bool(back.explained_by and back.explained_by not in ("llm", "data")))
            strong = bool(set(r.get("sources") or []) & {"code", "config"})    # (0.10.5) a person's: only when the
            if back is not None and not back.both_ways and not back.proposed_drop and \
                    (_norm(ends(r)[1]), _norm(ends(r)[0]), kind) not in said and (   # code or a configuration
                    (person and strong) or (not person and back.source in ("llm", "data", SOURCE))):   # says so
                where = f" ({r.get('where')})" if r.get("where") else ""
                if propose_drop(back, f"the documents and the code state the other way: {r['from']} {kind} {r['to']}"
                                + where, kept):
                    out["removals"] += 1
        same = (db.session.query(Link).filter(Link.a_ref == f"facet:{a.id}", Link.b_ref == f"facet:{b.id}",
                                              Link.kind == kind).first())
        if same is not None:
            if same.status != "rejected":
                out["confirmed"] += 1
                if not same.evidence:
                    same.evidence = _evidence(r)
            continue
        if kind in FLOWS and not set(r.get("sources") or []) & {"code", "config"}:
            if db.session.query(Link.id).filter(Link.a_ref == f"facet:{b.id}", Link.b_ref == f"facet:{a.id}",
                                                Link.kind.in_(list(FLOWS)), Link.status == "approved").first():
                out["the other way approved"] = out.get("the other way approved", 0) + 1   # (0.10.6) pages write
                continue                                   # "talks to" both ways: no reversed link from their words
            if kind == "calls" and STORE_NAME.search(_norm(a.value)) and not STORE_NAME.search(_norm(b.value)):
                out["a store calls no one"] = out.get("a store calls no one", 0) + 1   # (0.10.6) "ridesdb / Talks
                continue                                   # to: rental-api": its clients use it, it calls none
        if (r["kind"] in ("calls", "sends_to", "reads_from", "uses", "runs_on")) and _norm(b.value) in vips:
            out["to a VIP: its service"] = out.get("to a VIP: its service", 0) + 1   # (0.10.6) a VIP is an address:
            continue                                       # the service behind it gets the link (the reading adds it)
        if r["kind"] in ("calls", "sends_to", "reads_from", "uses") and serverish(a.facet) and \
                a.status == "approved":                    # (a VIP's routes_to is no flow: it stays)
            out["a server is no flow's subject"] = out.get("a server is no flow's subject", 0) + 1
            continue                                       # (0.10.6) a server or a group: where parts run
        if suggest_link(a.id, b.id, kind, SOURCE, _evidence(r), _confidence(r), note=WORDED.get(r["kind"])):
            out["links"] += 1
    if not dry_run and not shrunk:                       # what the documents proposed before and no longer state
        import datetime as _dt

        from supagent.knowledge.understand import TEXTS_KEY

        stamp = _dt.datetime.utcnow()
        texts = db.session.get(Meta, TEXTS_KEY)
        try:
            texts_at = _dt.datetime.fromisoformat(texts.value) if texts is not None and texts.value else None
        except ValueError:
            texts_at = None
        for x in db.session.query(Link).filter(Link.source == SOURCE, Link.a_ref.like("facet:%"),
                                               Link.b_ref.like("facet:%")):
            try:
                key = (int(x.a_ref.split(":", 1)[1]), int(x.b_ref.split(":", 1)[1]), x.kind)
            except ValueError:
                continue
            if key in stated:
                x.seen_at = stamp                          # (0.10.5) when the documents stated it last
                continue
            if x.status == "proposed":
                if x.explained_by:                         # (0.11.0) a person corrected it in To review (its kind,
                    continue                               # its direction, its words): theirs to decide, never withdrawn
                db.session.delete(x)
                out["withdrawn"] += 1
            elif x.status == "approved" and not x.proposed_drop:
                if (x.seen_at is not None and texts_at is not None and texts_at <= x.seen_at) or \
                        still_written(x.evidence):         # (0.10.5) no text changed since it was stated, or its
                    out["still written"] = out.get("still written", 0) + 1   # words are still in a document: the
                    continue                               # reading moved (a name approved since), not the documents
                if propose_drop(x, "no document nor code states it any more", kept):
                    out["removals"] += 1
    if not dry_run:                                      # (0.10.5) a sentence denying a link or putting it in the
        strong = {(_norm(r["from"]), _norm(r["to"])) for r in rels   # past: its removal proposed with the sentence,
                  if set(r.get("sources") or []) & {"code", "config"}}   # unless the code or a configuration states it
        for d in g.get("denied") or []:
            kind = LINK_OF.get(d["kind"])
            a, b = values.get(_norm(d["from"])), values.get(_norm(d["to"]))
            if kind is None or a is None or b is None or "rejected" in (a.status, b.status) or \
                    (_norm(d["from"]), _norm(d["to"])) in strong:
                continue
            family = FLOWS if kind in FLOWS else (kind,)
            for x in db.session.query(Link).filter(Link.a_ref == f"facet:{a.id}", Link.b_ref == f"facet:{b.id}",
                                                   Link.kind.in_(family), Link.status == "approved",
                                                   Link.proposed_drop.is_(None)):
                if propose_drop(x, f'a document says it does not hold any more: "{d["quote"]}" ({d["where"]})', kept):
                    out["removals"] += 1
    objects: dict[tuple[str, str], int] = {}
    for oid, kind, name in db.session.query(KObject.id, KObject.kind, KObject.name).filter(
            KObject.kind.in_(("index", "metric", "family")), KObject.gone_at.is_(None)):
        objects.setdefault((kind, name), oid)
    given: set[tuple[str, int]] = set()
    for d in g.get("data_links") or []:
        okind = d.get("object_kind")
        oid = objects.get((okind, d["object"])) or objects.get(("family", d["object"]))
        if oid is None:
            continue
        f = value_of(d["part"])
        if f is None or dry_run:
            continue
        ref = f"object:{oid}"
        given.add((ref, f.id))
        have = db.session.query(Tag).filter(Tag.ref == ref, Tag.facet_id == f.id).first()
        if have is not None:
            if have.status != "rejected":
                out["confirmed"] += 1
            continue
        db.session.add(Tag(ref=ref, facet_id=f.id, source=SOURCE, status="proposed", confidence=_confidence(d)))
        out["items"] += 1
    if not dry_run:
        if not shrunk:
            for t in db.session.query(Tag).filter(Tag.source == SOURCE, Tag.status == "proposed"):
                if (t.ref, t.facet_id) not in given:
                    db.session.delete(t)
                    out["withdrawn"] += 1
        refiled = _refile_inside()
        if refiled:
            out["parts filed in their whole's own category"] = refiled
        refiled = _refile_wholes()
        if refiled:
            out["wholes filed in their parts' own category"] = refiled
        refiled = _refile_structure()
        if refiled:
            out["systems and their parts filed by the person's nesting"] = refiled
        state = _json.dumps({"facts": max(now, before) if shrunk else now})
        if row is None:
            db.session.add(Meta(key=STATE_KEY, value=state))
        else:
            row.value = state
        db.session.commit()
    else:
        db.session.rollback()
    return out
