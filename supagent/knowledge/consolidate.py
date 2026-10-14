"""(0.10.9.2, the team's report of 12 October 2026: hundreds of values to review that name the same things with
slightly different names) One value per thing: the learning's proposals that name the same thing as another value
are found and put together before they wait in To review.

Every value of the categories gets name keys, made without any service (no LLM, no embeddings): its name folded
(accents, case, separators, camelCase, a plural), the usual abbreviations written out (svc, db, mgmt, k8s...), the
environment's and the version's words taken off (payment-service-prd, payments v2), the name without its spaces.
Two names are the same thing when:
  - strong: they fold the same, write out the same, or are the same without spaces (Payment Service,
    payment_service, PaymentService, payment-svc);
  - an environment or a version apart (billing-prd, billing v2) in a category of parts (never a server's: db-prd-01
    and db-stg-01 are two hosts);
  - a typo apart: two letters swapped, a letter added or left out inside a long word (paymnet, notifcation);
and never when the numbers in them differ (srv-01, srv-02; app2, app3), nor a server's names that differ in any word
(srv-a-1, srv-01). A pair only a looser key joins (one letter changed in a long word,
the name without its generic words, an acronym, most of the words shared) is a doubt: the LLM is asked about small groups of
such names (learn.merge_llm_calls per run, 0: none); its answer is checked (names from the group only).

What is done with a group:
  - learning's proposals only (the documents', the AI's, the data's): put together at once into one proposal, the
    others' names kept as its other names, their items and links moved to it (nobody approved them);
  - a value a person approved or made, and proposals of it: each proposal waits as "the same as" that value (To
    review merges them in one click, all at once with "Merge them all"); learn.merge_duplicates = auto merges a
    strong one at once;
  - two values people approved: never merged here (To review's warnings say "one thing written two ways").
The name kept: a person's value, else the data's name (what the systems call it), else the most said, the shortest
without an environment's or a version's word.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from difflib import SequenceMatcher
from typing import Any, Callable, Iterable

from superset import db

log = logging.getLogger(__name__)

# the usual short forms of a part's name (written out before comparing); kept generic: no team's own words
ABBREV = {"svc": "service", "svcs": "services", "srvc": "service", "app": "application", "apps": "applications",
          "db": "database", "dbs": "databases", "mgmt": "management", "mgt": "management", "mgr": "manager",
          "cfg": "config", "conf": "config", "configuration": "config", "notif": "notification",
          "notifs": "notifications", "msg": "message", "msgs": "messages", "info": "information",
          "k8s": "kubernetes", "kube": "kubernetes", "gw": "gateway", "lb": "loadbalancer", "mq": "queue",
          "repo": "repository", "repos": "repositories", "auth": "authentication", "authn": "authentication",
          "authz": "authorization", "admin": "administration", "adm": "administration", "mon": "monitoring",
          "sched": "scheduler", "proc": "processing", "pmt": "payment", "pymt": "payment", "acct": "account",
          "accts": "accounts", "cust": "customer", "inv": "inventory", "ord": "order", "env": "environment",
          "dev": "development", "devel": "development", "prd": "production", "prod": "production",
          "stg": "staging", "stage": "staging", "tst": "test", "qual": "qualification", "qualif": "qualification",
          "preprod": "preproduction", "pprod": "preproduction", "rec": "recette"}
ENV = {"production", "staging", "development", "test", "testing", "uat", "qa", "preproduction", "qualification",
       "recette", "integration", "sandbox", "demo", "dr", "drp", "pra", "local", "lab", "prd", "stg", "dev", "prod"}
GENERIC = {"service", "services", "application", "applications", "api", "apis", "server", "servers", "system",
           "systems", "platform", "module", "modules", "component", "components", "tool", "tools", "app",
           "backend", "back", "end", "the", "le", "la", "les", "de", "du", "des", "of", "and", "et", "for", "pour"}
ARTICLES = {"the", "le", "la", "les", "l", "der", "die", "das", "el", "los", "il", "lo"}
VERSION_TOKEN = re.compile(r"^v\d+[a-z]?$|^\d+(?:\.\d+)+$|^r\d+$")
SERVERISH = re.compile(r"server|host|node|machine|instance|\bvm|pod|container", re.I)
TYPO_MIN = 7                   # a typo in a word of this many letters at least (shorter: two different words)
GROUP_MAX = 12                 # names shown to the LLM at once
DESCRIBE = 160                 # characters of a value's description shown with it
ASKED = "consolidate_asked"    # supagent_meta: the groups of names the LLM was asked about ({signature: day})
ASKED_MAX = 20000


@lru_cache(maxsize=1 << 16)
def fold(name: str) -> str:
    """Lower case, no accent, words apart (camelCase, separators), one space between them."""
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", s)   # PaymentService, HTTPServer
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


def _single(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(name: str, literal: bool = False) -> list[str]:
    """The name's words, written out (abbreviations) and in the singular; `literal`: as written (a host's name:
    box-01 and boxes-01, ops-01 and operations-01 are other hosts), only the numbers' leading zeros taken off."""
    out = []
    for w in fold(name).split():
        w = w if literal else ABBREV.get(w, w)
        out.extend((lambda x: x if literal else _single(x))(re.sub(r"(?<![\d])0+(?=\d)", "", x))   # node-01: node 1
                   for x in w.split())
    return out


def _literal(category: str) -> bool:
    """(0.10.10) A category of places an inventory names (servers, hosts, groups, VIPs, namespaces, clusters): its
    names are identities, compared as written (web and web-prod, uat_app (ops uat) and ops uat are two); (0.10.9.2)
    what the category holds, by its name or its description (catkind)."""
    from supagent.knowledge.catkind import kind_name

    return _literal_kind(kind_name(category))


@lru_cache(maxsize=1024)
def _literal_kind(c: str) -> bool:
    from supagent.knowledge.placing import HOSTISH, phrases

    return bool(SERVERISH.search(c)) or bool(set(phrases(c)) & (HOSTISH | {"messaging"}))   # (and the streams,
    #                                                       topics, queues: orders.created and orders.rated are two)


INSTANCES = {"store", "cache", "object", "messaging", "broker", "job", "dns", "certificate"}


def _instances(category: str) -> bool:
    """(0.10.10) A category of things made once per environment (databases, caches, buckets, topics, jobs, DNS names,
    certificates): an environment's word in a name makes another one."""
    from supagent.knowledge.catkind import kind_name

    return _instances_kind(kind_name(category))


@lru_cache(maxsize=1024)
def _instances_kind(c: str) -> bool:
    from supagent.knowledge.placing import phrases

    return bool(set(phrases(c)) & INSTANCES)


QUALIFIED = re.compile(r"^(.+?)\s*\(([^()]+)\)\s*$")


def _qualifier(a: str, b: str, category: str = "") -> bool:
    """(0.10.10) `b` is what qualifies `a` in its parentheses ("web (ops prod)" and "ops prod", "orders-api (Order
    Desk)" and "Order Desk"): the thing and what it is in are two; not when one of them is the other's initials
    ("Order Desk (OD)" and "OD": one thing, two names)."""
    m = QUALIFIED.match(str(a or "").strip())
    if not m:
        return False
    head, q = m.group(1), m.group(2)
    if keys(q, category)["written"] != keys(b, category)["written"]:
        return False
    return not (_abbreviates(q, head) or _abbreviates(head, q))


@lru_cache(maxsize=1 << 16)
def digits(name: str, category: str = "") -> tuple[str, ...]:
    """The numbers in a name (srv-01 -> ("1",)): two names with other numbers are two things. Read in its words
    written out (k8s: kubernetes), a part's without its version's (billing v2: billing)."""
    host = _literal(category)
    ws = words(name, literal=host)
    if not host:
        ws = [w for w in ws if not VERSION_TOKEN.match(w)]
    return tuple(str(int(d)) for w in ws for d in re.findall(r"\d+", w))


@lru_cache(maxsize=1 << 16)
def keys(name: str, category: str = "") -> dict[str, str]:
    """The name's keys (see the module): strong ones (folded, written out, compact), noenv (a part's category
    only), the looser ones (core, acronym)."""
    host = _literal(category)
    ws = words(name, literal=host)
    out = {"folded": fold(name), "written": " ".join(ws), "compact": "".join(ws)}
    if not host:
        noenv = [w for w in ws if w not in ENV]
        if noenv and noenv != ws:
            out["noenv"] = " ".join(noenv)
        nover = [w for w in (noenv or ws) if not VERSION_TOKEN.match(w)]
        if nover and nover != (noenv or ws):
            out["nover"] = " ".join(nover)                # (payments-api v1 / v2: maybe two things: a doubt)
        core = [w for w in (nover or noenv or ws) if w not in GENERIC]
        if core and core != (nover or noenv or ws):
            out["core"] = " ".join(core)
    return out


@lru_cache(maxsize=1 << 16)
def acronyms(name: str) -> frozenset[str]:
    """The initials of every run of two words or more of a name (acme order management system: oms, acme...)."""
    ws = [w for w in fold(name).split() if w.isalpha()]
    return frozenset("".join(w[0] for w in ws[i:j]) for i in range(len(ws)) for j in range(i + 2, len(ws) + 1))


def _abbreviates(short: str, long: str) -> bool:
    """A word of one name is the initials of words of the other (OMS, order management system)."""
    tokens = [w for w in fold(short).split() if w.isalpha() and 2 <= len(w) <= 6]
    return bool(tokens) and bool(set(tokens) & acronyms(long))


def _typo(a: str, b: str) -> str:
    """Two words a typo apart: "typo" (two letters swapped, a letter added or left out inside the word, in words of
    TYPO_MIN letters or more), "doubt" (one letter changed: loader, leader), "" (else; a letter more at the end is
    another word: trade, trader)."""
    if min(len(a), len(b)) < TYPO_MIN - 1 or max(len(a), len(b)) < TYPO_MIN or abs(len(a) - len(b)) > 1 or a == b \
            or not (a.isalpha() and b.isalpha()):
        return ""
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return "doubt" if diff[0] > 0 else ""
        swapped = len(diff) == 2 and diff[1] == diff[0] + 1 and a[diff[0]] == b[diff[1]] and a[diff[1]] == b[diff[0]]
        return "typo" if swapped else ""
    s, t = (a, b) if len(a) < len(b) else (b, a)
    return "typo" if any(t[:i] + t[i + 1:] == s for i in range(1, len(t) - 1)) else ""


def _typo_words(a: list[str], b: list[str]) -> str:
    """The names' words the same but one pair a typo apart (see _typo)."""
    if len(a) != len(b):
        return ""
    diff = [(x, y) for x, y in zip(a, b) if x != y]
    return _typo(*diff[0]) if len(diff) == 1 else ""


# (0.10.9.2) a team's word in the languages a wiki is written in ("the Security team", "l'équipe Sécurité")
TEAM_WORDS = {"team", "equipe", "equipo", "squad", "squadra", "crew", "tribe", "mannschaft"}
TEAM_GLUE = {"of", "de", "du", "des", "d", "del", "der", "des"}


@lru_cache(maxsize=1 << 14)
def team_core(name: str) -> tuple[str, ...] | None:
    """(0.10.9.2) A team's name without its team word and its articles ("l'équipe Plateforme": ("plateforme",)),
    None for a name with no team word."""
    ws = words(name)
    if not any(w in TEAM_WORDS for w in ws):
        return None
    core = tuple(w for w in ws if w not in TEAM_WORDS and w not in ARTICLES and w not in TEAM_GLUE)
    return core or None


def _cognate(x: str, y: str) -> bool:
    """(0.10.9.2) One word in two languages: sécurité and security, plateforme and platform, méthodes and methods
    (5 letters or more, the same start, near the same letters)."""
    return min(len(x), len(y)) >= 5 and x[:2] == y[:2] and SequenceMatcher(None, x, y).ratio() >= 0.85


def same(a: str, b: str, category: str = "") -> str:
    """How sure two names are one thing: "strong", "noenv", "typo", "doubt" (a looser key) or "" (two things)."""
    if digits(a, category) != digits(b, category):
        return ""
    ka, kb = keys(a, category), keys(b, category)
    if ka["folded"] == kb["folded"] or ka["written"] == kb["written"] or ka["compact"] == kb["compact"]:
        return "strong"
    ta, tb = team_core(a), team_core(b)                   # (0.10.9.2) a team named in two languages: the Security
    if ta and tb and not _literal(category):              # team and l'équipe Sécurité
        if ta == tb:
            return "strong"
        if len(ta) == len(tb) and all(x == y or _cognate(x, y) for x, y in zip(ta, tb)):
            return "typo"
    if _literal(category):
        return ""                                         # a host's name is its identity: srv-a-1 is not srv-01
    if _qualifier(a, b, category) or _qualifier(b, a, category):
        return ""                                         # a thing and what it is in: x (shop) and shop
    if _instances(category) and {w for w in ka["written"].split() if w in ENV} != \
            {w for w in kb["written"].split() if w in ENV}:
        return ""                                         # a staging database is another one (orders_db and
    #                                                       stg_orders_db); an application is one thing everywhere
    wa, wb = ka["written"].split(), kb["written"].split()
    ea, eb = {w for w in wa if w in ENV}, {w for w in wb if w in ENV}
    if ea and eb and ea != eb:
        return ""                                         # two environments' own: x-prod and x-staging are two
    oa, ob = sorted(w for w in wa if w not in ARTICLES), sorted(w for w in wb if w not in ARTICLES)
    if len(oa) >= 2 and oa == ob and all(" " in n.strip() and not re.search(r"[-_./:\d]", n) for n in (a, b)):
        return "strong"                                   # (0.10.10) the same words in another order, written as
    #                                                       words ("Team Quokka", "Quokka team"); never identifiers
    #                                                       (ups-x1-a-b and ups-x1-b-a are two)
    na, nb = ka.get("noenv", ka["written"]), kb.get("noenv", kb["written"])
    if na == nb:
        return "noenv"
    typo = _typo_words(wa, wb)
    if typo:
        return typo
    apart = [(x, y) for x, y in zip(wa, wb) if x != y] if len(wa) == len(wb) else []
    if len(apart) == 1 and all(w.isalpha() and w not in ENV and w not in GENERIC for w in apart[0]) \
            and max(map(len, apart[0])) < TYPO_MIN:
        return ""                                         # another short word: cart, card; loader, leader
    if len(apart) == 1 and not _typo(*apart[0]) and any(len(w) >= 3 and w.isalpha() and w not in ENV and
                                                        w not in GENERIC for w in apart[0]):
        return ""                                         # (0.10.10) another word of its own: api-x-writer and
    #                                                       porti-x-writer, x-updated and x-rated are two things
    if ka.get("nover", na) == kb.get("nover", nb):
        return "doubt"
    ca, cb = ka.get("core", ka.get("nover", na)), kb.get("core", kb.get("nover", nb))
    if ca and cb and ca == cb:
        return "doubt"
    if (len(a.split()) < len(b.split()) and _abbreviates(a, b)) or (len(b.split()) < len(a.split()) and _abbreviates(b, a)):
        return "doubt"
    sa, sb = set(ka["written"].split()), set(kb["written"].split())
    if len(sa | sb) >= 3 and len(sa & sb) / len(sa | sb) >= 0.6 and len(sa & sb) >= 2:
        return "doubt"
    small, big = (sa, sb) if len(sa) < len(sb) else (sb, sa)
    if small and small < big and len(big - small) == 1 and any(len(w) >= 6 and w.isalpha() and w not in GENERIC
                                                                   for w in small):
        return "doubt"                                    # one word more (billing, legacy-billing): maybe its own
    if min(len(ka["compact"]), len(kb["compact"])) >= 10 and \
            SequenceMatcher(None, ka["compact"], kb["compact"]).ratio() >= 0.9:
        return "doubt"
    return ""


# ------------------------------------------------------------------------------------------------- the values
def _family(category: str) -> str:
    """Values of these categories are compared together (the same thing proposed as an application and as a
    component); others within their category."""
    return "parts" if category in ("application", "component") else category


def _names(f: Any) -> list[str]:
    return [f.value] + [str(x) for x in (f.synonyms or []) if str(x).strip()]


def _person(f: Any) -> bool:
    return f.status == "approved" or f.source == "admin" or f.reviewed_by is not None


def _learned(f: Any) -> bool:
    """A proposal of the learning nobody touched (the documents', the AI's, the data's)."""
    return f.status == "proposed" and f.reviewed_by is None and f.source in ("docs", "llm", "data", "seed")


def _blocks(values: list[Any]) -> dict[str, list[Any]]:
    """Candidates pairs come from shared keys (a name's every key, its other names' too): no all-pairs compare."""
    out: dict[str, list[Any]] = defaultdict(list)
    for f in values:
        seen: set[str] = set()
        for n in _names(f):
            ks = keys(n, f.facet)
            for kind in ("written", "compact", "noenv", "nover", "core"):
                if ks.get(kind) and (kind, ks[kind]) not in seen:
                    seen.add((kind, ks[kind]))
                    out[f"{_family(f.facet)}|{ks[kind]}"].append(f)
            for w in ks["written"].split():                   # a word they share (blocks of more than 200: none)
                if len(w) >= 3 and w not in GENERIC and w not in ENV and ("word", w) not in seen:
                    seen.add(("word", w))
                    out[f"{_family(f.facet)}|w:{w}"].append(f)
            for acr in acronyms(n) | {w for w in fold(n).split() if w.isalpha() and 2 <= len(w) <= 6}:
                if ("acr", acr) not in seen:                  # OMS meets order management system
                    seen.add(("acr", acr))
                    out[f"{_family(f.facet)}|a:{acr}"].append(f)
            if team_core(n) and ("team", "") not in seen:   # (0.10.9.2) the teams: compared together (their
                seen.add(("team", ""))                        # names in two languages share no key)
                out[f"{_family(f.facet)}|team"].append(f)
            comp = ks["compact"]
            if len(comp) >= TYPO_MIN:                     # a typo keeps either half of a long name
                for part in (comp[: len(comp) // 2], comp[len(comp) // 2:]):
                    if ("half", part) not in seen:
                        seen.add(("half", part))
                        out[f"{_family(f.facet)}|~{part}"].append(f)
    return {k: v for k, v in out.items() if 1 < len({id(x) for x in v}) <= 200}


def _pair(a: Any, b: Any) -> str:
    best = ""
    rank = {"strong": 4, "noenv": 3, "typo": 2, "doubt": 1, "": 0}
    cat = a.facet if a.facet == b.facet else ""
    for x in _names(a):
        for y in _names(b):
            s = same(x, y, cat or a.facet)
            if rank[s] > rank[best]:
                best = s
                if s == "strong":
                    return s
    return best


class _Union:
    def __init__(self) -> None:
        self.up: dict[int, int] = {}

    def find(self, x: int) -> int:
        self.up.setdefault(x, x)
        while self.up[x] != x:
            self.up[x] = self.up[self.up[x]]
            x = self.up[x]
        return x

    def join(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.up[max(ra, rb)] = min(ra, rb)


def _canonical(group: list[Any], evidence: dict[int, int]) -> Any:
    """The value kept: a person's, else the data's name (what the systems call it), else a name with no
    environment's or version's word, written out (not svc, db...), the most used, the shortest."""
    def score(f: Any) -> tuple:
        ks = keys(f.value, f.facet)
        clean = "noenv" not in ks and "nover" not in ks
        short = ks["written"] != ks["folded"]             # a short form (svc, db, k8s): its written-out twin kept
        return (not _person(f), f.source != "data", not clean, short, -evidence.get(f.id, 0), len(f.value), f.id)
    return sorted(group, key=score)[0]


def _ask(llm: Any, names: list[tuple[int, str, str, str]]) -> list[list[int]]:
    """The LLM's groups of the names that are one thing (indexes into `names`), checked."""
    lines = [f"{i}. {n} ({cat}){': ' + d if d else ''}" for i, (_fid, n, cat, d) in enumerate(names)]
    msgs = [{"role": "system", "content": (
        "You decide which of these names, read in a company's documents, name the very same thing (the same "
        "application, service, component or tool), written differently. Names of different things that only share "
        "a word are different. Answer with JSON only: {\"groups\": [[i, j, ...], ...]}, each group the numbers of "
        "names that are one thing (two at least); a name in one group at most; no group when none are the same.")},
        {"role": "user", "content": "\n".join(lines)}]
    try:
        reply = llm.chat(msgs, max_tokens=600)
        text = reply.get("content") if isinstance(reply, dict) else str(reply)
        m = re.search(r"\{.*\}", re.sub(r"<think>.*?</think>", "", text or "", flags=re.S), re.S)
        got = json.loads(m.group(0)) if m else {}
    except Exception as ex:  # pylint: disable=broad-except   (no LLM, a bad answer: the doubt stays apart)
        log.info("supagent consolidate: the LLM's groups not read: %s", ex)
        return []
    out, used = [], set()
    for g in got.get("groups") or [] if isinstance(got, dict) else []:
        if not isinstance(g, list):
            continue
        idx = [i for i in g if isinstance(i, int) and 0 <= i < len(names) and i not in used]
        if len(set(idx)) >= 2:
            used.update(idx)
            out.append(sorted(set(idx)))
    return out


def _core(f: Any) -> str:
    ks = keys(f.value, f.facet)
    return ks.get("core") or ks.get("nover") or ks.get("noenv") or ks["written"]


def _signature(names: list[tuple[int, str, str, str]]) -> str:
    """The names asked together (their category and folded name): asked once."""
    return hashlib.sha1("|".join(sorted(f"{cat}:{fold(n)}" for _i, n, cat, _d in names)).encode()).hexdigest()[:16]


def _asked() -> dict[str, str]:
    from supagent.models import Meta

    row = db.session.get(Meta, ASKED)
    try:
        got = json.loads(row.value) if row is not None and row.value else {}
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def _remember(signatures: list[str]) -> None:
    import datetime as dt

    from supagent.models import Meta

    if not signatures:
        return
    asked = _asked()
    day = dt.date.today().isoformat()
    asked.update({sig: day for sig in signatures})
    keep = dict(sorted(asked.items(), key=lambda kv: kv[1])[-ASKED_MAX:])
    row = db.session.get(Meta, ASKED)
    if row is None:
        db.session.add(Meta(key=ASKED, value=json.dumps(keep)))
    else:
        row.value = json.dumps(keep)


def _wholes() -> dict[int, set[int]]:
    """(0.10.10) {value id: the values it is part of} from the map's part-of links (not refused)."""
    from supagent.knowledge.facets import PART_OF
    from supagent.models import Link

    out: dict[int, set[int]] = defaultdict(set)
    for a, b in db.session.query(Link.a_ref, Link.b_ref).filter(Link.kind == PART_OF, Link.status != "rejected"):
        if a.startswith("facet:") and b.startswith("facet:"):
            out[int(a[6:])].add(int(b[6:]))
    return out


def _never(fa: Any, fb: Any) -> bool:
    """(0.10.10) Two values whose names say they are two things, whatever an LLM answers: other numbers, other
    environments, a word of each of their own, a thing and its qualifier, names compared as written (hosts, groups,
    streams) that differ."""
    category = fa.facet if fa.facet == fb.facet else ""
    for a in _names(fa)[:4]:
        for b in _names(fb)[:4]:
            if same(a, b, category):
                return False                              # (one of their names is the other's: not never)
    a, b = fa.value, fb.value
    if digits(a, category) != digits(b, category) or _literal(category):
        return True
    ka, kb = keys(a, category)["written"].split(), keys(b, category)["written"].split()
    ea, eb = {w for w in ka if w in ENV}, {w for w in kb if w in ENV}
    if ea and eb and ea != eb:
        return True
    if _qualifier(a, b, category) or _qualifier(b, a, category):
        return True
    apart = [(x, y) for x, y in zip(ka, kb) if x != y] if len(ka) == len(kb) else []
    return len(apart) == 1 and not _typo(*apart[0]) and any(len(w) >= 3 and w.isalpha() and w not in ENV and
                                                            w not in GENERIC for w in apart[0])


def _apart_by_structure(a: int, b: int, wholes: dict[int, set[int]]) -> bool:
    """(0.10.10) Two values the map's structure keeps apart, whatever their names: one is part of the other (a module
    and its service), or each is part of another whole (two services' modules of the same shape)."""
    wa, wb = wholes.get(a, set()), wholes.get(b, set())
    return b in wa or a in wb or bool(wa and wb and not (wa & wb))


def _stems(values: list[Any]) -> dict[str, set[str]]:
    """(0.10.10) {a name's words but its last: the last words of the names written so}, over every value, kept when
    two names or more extend it ("order desk": adapter, consumer, ui): such a stem names a whole."""
    out: dict[str, set[str]] = defaultdict(set)
    for f in values:
        for n in _names(f)[:4]:
            ws = fold(n).split()
            if len(ws) >= 2 and ws[-1] not in GENERIC and ws[-1] not in ENV and not ws[-1].isdigit():
                out[" ".join(ws[:-1])].add(ws[-1])
    return {k: v for k, v in out.items() if len(v) >= 2}


def _extends(fa: Any, fb: Any, stems: dict[str, set[str]]) -> bool:
    """(0.10.10) One value's name is the other's and one word more, the other's a stem several names extend
    ("Order Desk" and "order-desk-adapter", beside "order-desk-ui"): a whole and one of its parts,
    two things whatever an LLM answers."""
    for a in _names(fa)[:4]:
        for b in _names(fb)[:4]:
            wa, wb = fold(a).split(), fold(b).split()
            for x, y in ((wa, wb), (wb, wa)):
                if len(x) == len(y) + 1 and x[:-1] == y and " ".join(y) in stems:
                    return True
    return False


def plan(values: Iterable[Any] | None = None, llm: Any = None, llm_calls: int = 0,
         evidence: dict[int, int] | None = None) -> dict[str, Any]:
    """The groups of values that are one thing (see the module), without changing anything: {"groups": [{"keep":
    value, "others": [values], "why": {id: kind}}], "doubts": n, "asked": n}."""
    from supagent.models import Facet

    if values is None:
        from supagent.knowledge.facets import editable

        values = db.session.query(Facet).filter(Facet.facet.in_(list(editable())), Facet.status != "rejected").all()
    values = [f for f in values if f.facet not in ("aspect",)]
    by_id = {f.id: f for f in values}
    evidence = evidence or {}
    wholes = _wholes()
    stems = _stems(values)
    u = _Union()
    why: dict[tuple[int, int], str] = {}
    doubts: dict[tuple[int, int], None] = {}
    done: set[tuple[int, int]] = set()
    for members in _blocks(values).values():
        uniq = list({f.id: f for f in members}.values())
        people = [f for f in uniq if _person(f)]
        others = [f for f in uniq if not _person(f)]
        for i, a in enumerate(others):                    # (two values people approved: never here)
            for b in others[i + 1:] + people:
                pair = (min(a.id, b.id), max(a.id, b.id))
                if pair in done:
                    continue
                done.add(pair)
                if _apart_by_structure(a.id, b.id, wholes) or _extends(a, b, stems):
                    continue                              # (0.10.10) a part and its whole, parts of two wholes
                s = _pair(a, b)
                if s in ("strong", "noenv", "typo"):
                    why[pair] = s
                    u.join(a.id, b.id)
                elif s == "doubt":
                    doubts[pair] = None
    asked, signatures = 0, []
    if llm is not None and llm_calls > 0 and doubts:
        pending = defaultdict(set)                       # a doubt's connected names, asked together
        du = _Union()
        for a, b in doubts:
            if u.find(a) != u.find(b):
                du.join(a, b)
        for a, b in doubts:
            pending[du.find(a)].update((a, b))
        chunks = []                                      # (a big one: names alike side by side, GROUP_MAX at once)
        for ids in pending.values():
            ids = sorted(ids, key=lambda i: (_family(by_id[i].facet), _core(by_id[i]), fold(by_id[i].value), i))
            for k in range(0, len(ids), GROUP_MAX):
                part = ids[k:k + GROUP_MAX]
                if len(part) > 1:
                    chunks.append(part)
        chunks.sort(key=lambda part: (-sum(not _person(by_id[i]) for i in part), part[0]))
        before = _asked()
        members: dict[int, set[int]] = {}
        for f in values:
            members.setdefault(u.find(f.id), set()).add(f.id)
        initials: dict[str, set[int]] = defaultdict(set)   # (0.10.10) the initials of each name: "tb" names two
        for f in values:                                  # values (ticket bridge, teams bridge): nobody's
            for n in _names(f):
                ws = [w for w in fold(n).split() if w.isalpha()]
                if len(ws) >= 2:
                    initials["".join(w[0] for w in ws)].add(f.id)

        def ambiguous(i: int) -> bool:
            return any(len(initials.get(fold(n).replace(" ", ""), set()) - {i}) >= 2 for n in _names(by_id[i])
                       if len(fold(n).replace(" ", "")) <= 5)

        def cannot(a: int, b: int) -> bool:
            ga, gb = members.get(u.find(a), {a}), members.get(u.find(b), {b})
            if any(ambiguous(x) for x in ga | gb):
                return True
            return any(_apart_by_structure(x, y, wholes) or _never(by_id[x], by_id[y]) or
                       _extends(by_id[x], by_id[y], stems) for x in ga for y in gb)

        for part in chunks:
            if asked >= llm_calls:
                break
            names = [(i, by_id[i].value, by_id[i].facet, " ".join(str(by_id[i].description or "").split())[:DESCRIBE])
                     for i in part]
            sig = _signature(names)
            if sig in before:
                continue                                  # asked at an earlier learning: its answer stands
            asked += 1
            signatures.append(sig)
            for g in _ask(llm, names):
                fids = [names[k][0] for k in g]
                people = [x for x in fids if _person(by_id[x])]
                if len(people) > 1:
                    continue
                for x in fids[1:]:
                    if cannot(fids[0], x):
                        continue                          # (0.10.10) the LLM's group never joins two values the
                    why[(min(fids[0], x), max(fids[0], x))] = "llm"   # names or the map keep apart (through a third)
                    ra, rb = u.find(fids[0]), u.find(x)
                    u.join(fids[0], x)
                    members[u.find(x)] = members.pop(ra, {ra}) | members.pop(rb, {rb})
    groups: dict[int, list[Any]] = defaultdict(list)
    for f in values:
        groups[u.find(f.id)].append(f)
    rank = {"strong": 4, "noenv": 3, "typo": 2, "llm": 1}
    own: dict[int, str] = {}                              # each value's strongest link; the group's weakest
    weakest: dict[int, str] = {}
    for (a, b), k in why.items():
        for x in (a, b):
            if rank[k] > rank.get(own.get(x, ""), 0):
                own[x] = k
        root = u.find(a)
        if root not in weakest or rank[k] < rank[weakest[root]]:
            weakest[root] = k
    out = []
    for root, members in groups.items():
        if len(members) < 2:
            continue
        keep = _canonical(members, evidence)
        others = [f for f in members if f.id != keep.id]
        out.append({"keep": keep, "others": others, "why": {f.id: own.get(f.id, "strong") for f in others},
                    "weakest": weakest.get(root, "strong")})
    return {"groups": out, "doubts": len(doubts), "asked": asked, "signatures": signatures}


def apply(result: dict[str, Any], mode: str = "propose", by: str = "learning") -> dict[str, int]:
    """What plan() found, done (see the module): learning's proposals put together; a proposal of a person's value
    waits as the same as it (mode "auto": a strong one merged at once). Counts."""
    from supagent.knowledge.facets import merge_value

    out = {"merged": 0, "same_as": 0, "kept_apart": 0}
    _remember(list(result.get("signatures") or []))      # (what the LLM was asked: not again)
    for g in result.get("groups") or []:
        keep = g["keep"]
        for f in g["others"]:
            if not _learned(f):
                out["kept_apart"] += 1                    # (a person's value in a group kept by another person's)
                continue
            if _learned(keep) or (mode == "auto" and g.get("weakest") == "strong"):
                merge_value(f, keep)
                if keep.status == "proposed":
                    keep.origins = (list(keep.origins or []) + [f"{f.value}: the same thing, read as another name"]
                                    )[-10:]
                out["merged"] += 1
            else:
                sug = dict(f.suggested or {})
                if sug.get("same_as") != keep.id:
                    sug["same_as"] = keep.id
                    sug["same_by"] = by
                    sug["same_why"] = g["why"].get(f.id, "strong")
                    f.suggested = sug
                    out["same_as"] += 1
    db.session.flush()
    return out


def run(llm: Any = None, llm_calls: int | None = None, mode: str | None = None, dry_run: bool = False
        ) -> dict[str, Any]:
    """One pass over the categories' values (the learning's step, the command): plan, then apply unless dry_run."""
    from supagent import settings
    from supagent.models import Link, Tag

    calls = int(settings.get("learn.merge_llm_calls") if llm_calls is None else llm_calls)
    mode = mode or str(settings.get("learn.merge_duplicates") or "propose")
    evidence: dict[int, int] = defaultdict(int)
    for (fid,) in db.session.query(Tag.facet_id).filter(Tag.status != "rejected"):
        evidence[fid] += 1
    for a, b in db.session.query(Link.a_ref, Link.b_ref).filter(Link.status != "rejected"):
        for r in (a, b):
            if r.startswith("facet:") and r[6:].isdigit():
                evidence[int(r[6:])] += 1
    if llm is None and calls > 0:
        try:
            from supagent.llm import LLM

            llm = LLM()
        except Exception:  # pylint: disable=broad-except
            llm = None
    result = plan(llm=llm, llm_calls=calls, evidence=evidence)
    counts = {"groups": len(result["groups"]), "doubts": result["doubts"], "asked": result["asked"],
              "values_in_groups": sum(1 + len(g["others"]) for g in result["groups"])}
    if not dry_run:
        counts.update(apply(result, mode=mode))
        db.session.commit()
    counts["examples"] = [[g["keep"].value] + [f.value for f in g["others"]][:5] for g in result["groups"][:10]]
    return counts


def merge_suggested(by: str, category: str | None = None) -> int:
    """To review's "Merge them all": every waiting proposal the learning found the same as another value, merged
    into it (one category, or all). How many."""
    from supagent.knowledge.facets import merge_value
    from supagent.models import Facet

    n = 0
    q = db.session.query(Facet).filter(Facet.status == "proposed", Facet.suggested.isnot(None))
    if category:
        q = q.filter(Facet.facet == category)
    for f in q.all():
        to_id = (f.suggested or {}).get("same_as")
        if not str(to_id or "").isdigit() or not (f.suggested or {}).get("same_by"):
            continue                                      # (the AI's own "same as" stays one by one)
        to = db.session.get(Facet, int(to_id))
        if to is None or to.status == "rejected" or to.id == f.id:
            continue
        merge_value(f, to)
        n += 1
    db.session.commit()
    return n


def _callable(x: Any) -> Callable[..., Any] | None:      # (for tests: a scripted LLM)
    return x if callable(getattr(x, "chat", None)) else None
