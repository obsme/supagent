"""(0.10.9.2, the user's request of 14 October: "optimize the weak spot") What each of the deployment's own
categories holds, read the way a person reads it:
  - by its NAME when the name says it ("server", "host group", "platform service", "team", "data store"): as before;
  - else by what its DESCRIPTION defines it as: the head noun of its first phrase, the gloss in brackets right after
    it, else what follows a first colon ("box: a machine (a virtual machine or a server) by its hostname" holds
    servers; "fleet: an Ansible inventory group: ..." groups; "landscape: a deployment stage" environments);
  - else by where the person nested it (a category inside a category of groups holds their hosts).
The filing's rules that tell a category's kind by its name (servers, groups, teams, services, the hosts' software,
databases, brokers...) read `kind_name(c)`: the category's own name when that name says a kind, else the usual name
of what its description says it holds ("server", "server group", "team"...). That usual name is read by those rules
only: never stored, shown or returned as a category. A description that defines nothing changes nothing."""

from __future__ import annotations

import re
import time
from functools import lru_cache
from typing import Any

# what a category holds -> the usual name the name rules know it by
ROLE_NAME = {"host": "server", "group": "server group", "vip": "vip", "balancer": "load balancer",
             "namespace": "namespace", "cluster": "cluster", "store": "database", "cache": "cache",
             "messaging": "queue", "broker": "message broker", "object": "object store", "job": "scheduled job",
             "external": "external service", "team": "team", "domain": "domain", "service": "microservice",
             "application": "application", "environment": "environment", "dashboard": "dashboard",
             "alert": "alert rule", "certificate": "certificate", "dns": "dns record",
             "own service": "platform service", "software": "installed software", "monitoring": "monitoring",
             "library": "library", "power": "power supply", "port": "switch port"}
# words of descriptions only (the parts' sentences keep placing.CONCEPTS): what the name rules know by other words
EXTRA: dict[str, tuple[str, ...]] = {
    "own service": ("internal service", "internal services", "backend service", "backend services",
                    "back-end service", "back-end services", "shared service", "shared services", "platform service",
                    "platform services", "core service", "core services", "technical service", "technical services",
                    "service interne", "services internes", "service partagé", "services partagés"),
    "software": ("software", "softwares", "installed software", "package", "packages", "utility", "utilities",
                 "logiciel", "logiciels", "paquet", "paquets", "progiciel", "progiciels"),
    "monitoring": ("monitoring tool", "monitoring tools", "monitoring system", "monitoring systems",
                   "observability tool", "observability tools", "outil de supervision", "outils de supervision"),
    "library": ("library", "libraries", "framework", "frameworks", "dependency", "dependencies", "bibliothèque",
                "bibliothèques"),
    "power": ("power supply", "power supplies", "power distribution unit", "pdu", "pdus", "ups"),
    "port": ("switch port", "switch ports", "network port", "network ports"),
    "host": ("serveur", "serveurs", "hôte", "hôtes", "machine virtuelle", "machines virtuelles", "rechner",
             "servidor", "servidores"),
    "group": ("groupe", "groupes", "groupe d'inventaire", "groupes d'inventaire", "gruppe", "gruppen", "grupo",
              "grupos"),
    "environment": ("environnement", "environnements", "umgebung", "umgebungen", "entorno", "entornos"),
    "team": ("équipe", "équipes", "equipe", "equipes", "equipo", "equipos"),
    "store": ("base de données", "bases de données", "base de donnees", "datenbank", "datenbanken",
              "base de datos", "bases de datos"),
    "messaging": ("file d'attente", "files d'attente"),
    "external": ("prestataire", "prestataires", "fournisseur", "fournisseurs", "partenaire", "partenaires",
                 "anbieter", "proveedor", "proveedores"),
    "application": ("site web", "sites web", "produit", "produits", "anwendung", "anwendungen", "aplicación",
                    "aplicaciones"),
    "domain": ("domaine", "domaines", "bereich", "bereiche"),
    "job": ("tâche planifiée", "tâches planifiées", "traitement batch", "traitements batch"),
}
ARTICLES = {"a", "an", "the", "one", "un", "une", "le", "la", "les", "l", "des", "ein", "eine", "einen", "der",
            "die", "das", "el", "los", "las", "uno", "una"}
DETERMINERS = ARTICLES | {"their", "its", "our", "your", "his", "her", "this", "these", "those", "some", "every",
                          "each", "all", "any", "son", "sa", "ses", "leur", "leurs", "notre", "nos", "votre", "vos",
                          "ce", "cette", "ces"}
# where a head noun phrase ends: a preposition, a relative word, a verb of what follows ("software installed on")
STOPS = {"of", "for", "in", "on", "at", "with", "from", "to", "by", "into", "onto", "inside", "within", "outside",
         "beyond", "behind", "under", "over", "across", "between", "among", "without", "via", "per", "about",
         "against", "after", "before", "around", "through", "toward", "towards", "that",
         "which", "who", "whom", "where", "whose", "when", "while", "holding", "holds", "carrying", "carries",
         "serving", "serves", "running", "runs", "run", "used", "uses", "installed", "kept", "keeps", "deployed",
         "made", "hosted", "provided", "offered", "owned", "managed", "written", "built", "called", "named", "such",
         "dedicated", "located", "placed", "assigned", "connected", "attached", "mounted", "configured", "exposed",
         "reachable", "available", "responsible", "able", "seen", "known", "given", "shared", "operated",
         "like", "as", "is", "are", "de", "du", "d", "pour", "dans", "sur", "avec", "qui", "que", "où", "dont",
         "par", "chez", "entre", "sans", "selon", "vers", "sous", "hors", "von", "für", "mit", "im", "auf", "del",
         "para", "en", "con",
         "we", "you", "they", "it", "he", "she", "i", "nous", "vous", "ils", "elles", "on", "wir"}   # a new clause
JOINS = {"or", "and", "ou", "et", "oder", "und", "o", "y"}
# a service run by others: a category of services that are not the system's own
EXTERNAL_CUE = re.compile(r"(?i)\b(?:someone else|somebody else|others|outside|external|third[- ]part(?:y|ies)|"
                          r"vendors?|providers?|partners?|suppliers?|saas|another (?:company|agency|organi[sz]ation|"
                          r"team's)|externes?|prestataires?|fournisseurs?|partenaires?|hors)\b")
SERVICE_WORDS = {"service", "services", "prestation", "prestations", "dienst", "dienste", "servicio", "servicios"}
GENERIC_HEADS = {"engine", "engines", "tool", "tools", "solution", "solutions", "technology", "technologies",
                 "instance", "instances", "moteur", "moteurs", "outil", "outils"}   # say their kind by the words before
# a phrase written in French puts its head noun first ("un serveur physique"): told by its little words
FRENCH = {"un", "une", "le", "la", "les", "l", "des", "du", "de", "d", "et", "ou", "par", "pour", "qui", "que", "dans",
          "sur", "avec", "leur", "leurs", "son", "sa", "ses", "est", "sont", "au", "aux", "en"}
ENGLISH = {"a", "an", "the", "of", "and", "or", "by", "for", "that", "which", "who", "in", "on", "with", "its",
           "their", "is", "are", "to", "from"}
COLLECTIVE = {"set", "sets", "collection", "collections", "ensemble", "ensembles", "farm", "farms", "bunch"}
TOKEN = re.compile(r"[a-zà-ÿ0-9]+(?:[-.][a-zà-ÿ0-9]+)*|[():;,]")
NESTED = {"group": "host", "environment": "group", "broker": "messaging", "cluster": "namespace",
          "application": "service"}   # what a category nested in another holds, when nothing else says it


def _tokens(text: str) -> list[str]:
    return TOKEN.findall(str(text or "").lower().replace("’", "'").replace("'", " "))


@lru_cache(maxsize=1)
def _phrases() -> dict[str, list[tuple[tuple[str, ...], str]]]:
    """Every phrase that says what a category holds, by its first word, the longest first."""
    from supagent.knowledge.placing import CONCEPTS

    out: dict[str, list[tuple[tuple[str, ...], str]]] = {}
    for table in (CONCEPTS, EXTRA):
        for concept, ps in table.items():
            for p in ps:
                t = tuple(_tokens(p))
                if t:
                    out.setdefault(t[0], []).append((t, concept))
    for v in out.values():
        v.sort(key=lambda pc: -len(pc[0]))
    return out


def _matches(toks: list[str]) -> list[tuple[int, int, str]]:
    """(start, end, concept) of the phrases a text says, each word in one phrase only (the longest first)."""
    table, out, i = _phrases(), [], 0
    while i < len(toks):
        for t, concept in table.get(toks[i], ()):
            if tuple(toks[i:i + len(t)]) == t:
                out.append((i, i + len(t), concept))
                i += len(t)
                break
        else:
            i += 1
    return out


def _head(seg: list[str]) -> str | None:
    """What a phrase defines its subject as (a concept), or None: what its HEAD NOUN says (the last noun of the noun
    phrase in English: a "product team" is a team, a "web application firewall" a firewall, no application; the first
    in French: "un serveur physique"), else the gloss in brackets right after it, else the other heads it is joined to
    ("a database or a key-value store"). A head that is only "software" or "service" takes the kind its words before
    it say ("database server software": a database's; a place's word says where it runs: "host software"); a bare
    "service": an outside one when the phrase says others run it, else the system's own; "a set of servers": their
    group."""
    found = _matches(seg)
    covered = {k for s, e, _c in found for k in range(s, e)}
    french = sum(w in FRENCH for w in seg) > sum(w in ENGLISH for w in seg)
    i = 0
    while i < len(seg) and seg[i] in DETERMINERS:
        i += 1
    spans: list[tuple[int, int]] = []
    start, gloss = i, None
    while i < len(seg):
        w = seg[i]
        if i in covered:
            i += 1
            continue
        if w == "(":
            spans.append((start, i))
            close = seg.index(")", i) if ")" in seg[i:] else len(seg)
            gloss = (i + 1, close)
            break
        if w in JOINS:
            spans.append((start, i))
            i += 1
            while i < len(seg) and seg[i] in DETERMINERS:
                i += 1
            start = i
            continue
        if w in (",", ";", ":", ")") or w in STOPS or (w in DETERMINERS and i > start):
            spans.append((start, i))
            if w in ("of", "de", "des", "du", "d") and i - start == 1 and seg[start] in COLLECTIVE:
                after = [c for a, _b, c in found if a > i]
                if after and after[0] == "host":
                    return "group"
            break
        i += 1
    else:
        spans.append((start, len(seg)))
    for s, e in spans[:1] + ([gloss] if gloss else []) + spans[1:]:
        if e <= s:
            continue
        said = sorted((a, b, c) for a, b, c in found if a >= s and b <= e)
        head = [x for x in said if x[0] == s] if french else [x for x in said if x[1] == e]
        if head:
            kind = head[0][2]
            if kind == "software":                       # "database server software": a database's; a place's
                before = [c for _a, _b, c in said if c not in PLACES and c != "software"]   # word says where it
                return before[0] if before else "software"                                  # runs ("host software")
            return kind
        word = seg[s] if french else seg[e - 1]
        if word in GENERIC_HEADS and said:               # "a relational database engine", "a database instance":
            return said[0][2]                            # what its words before it say
        if word in SERVICE_WORDS:
            before = [c for _a, _b, c in said if c not in PLACES]
            if before:                                   # "a database service": a database's
                return before[0]
            return "external" if EXTERNAL_CUE.search(" ".join(seg)) else "own service"
    if gloss is None and "(" in seg:                      # a gloss of the whole phrase, after it ("the people who
        k = seg.index("(")                                # answer for a product (a team)"): one noun phrase, never
        inner = seg[k + 1:seg.index(")", k)] if ")" in seg[k:] else seg[k + 1:]   # a list of examples ("(an API,
        listed = bool(set(inner) & (JOINS | {",", ";"})) or (inner[:1] and inner[0] in EXAMPLE)   # a worker, a UI)")
        if inner and "(" not in inner and not listed:
            return _head(inner)
    return None


EXAMPLE = {"e.g", "eg", "such", "like", "including", "for", "par", "comme", "ex", "z.b"}


PLACES = {"host", "group", "vip", "namespace", "cluster", "balancer"}


@lru_cache(maxsize=4096)
def described(text: str) -> str | None:
    """What a category's description defines it as (a key of ROLE_NAME), or None: the head of its first phrase, else
    of what follows a first colon when that says "a ..." ("what the community uses: a web application")."""
    toks = _tokens(text)
    if not toks:
        return None
    segs = [toks]
    if ":" in toks[:16]:
        k = toks.index(":")
        after = toks[k + 1:]
        segs = [toks[:k]] + ([after] if after and after[0] in ("a", "an", "one", "un", "une", "ein", "eine") else [])
    for seg in segs:
        role = _head(seg)
        if role:
            return role
    return None


def _recognized(name: str) -> bool:
    """The name says a kind to one of the name rules (as before: nothing read in its description)."""
    from supagent.knowledge.datalinks import SERVERISH
    from supagent.knowledge.naming import OWN
    from supagent.knowledge.placing import phrases
    from supagent.knowledge.proposals import INFRA_CATEGORY, NOT_OWN_SERVICE, SERVICE_CATEGORY

    if name in ("subject", "application", "component", "aspect") or SERVERISH.search(name) or phrases(name):
        return True
    if any(rx.search(name) for rx in INFRA_CATEGORY.values()) or SERVICE_CATEGORY.search(name) or \
            NOT_OWN_SERVICE.search(name):
        return True
    return any(rx.match(name) for rx in OWN.values())


@lru_cache(maxsize=4096)
def _kind(name: str, about: str, parent: str, parent_about: str) -> str:
    if not name or _recognized(name):
        return name
    role = described(about)
    if role is None and parent:                          # nothing said: where the person nested it
        p = _kind(parent, parent_about, "", "")
        from supagent.knowledge.placing import phrases

        said = phrases(p)
        top = said.most_common(1)[0][0] if said else ("application" if p == "application" else None)
        role = NESTED.get(top or "")
    return ROLE_NAME.get(role or "", name)


_SEEN: list[Any] = [None, None]                        # (what the reading was keyed on, the person's maps)
FRESH_S = 30                                           # another process's change: read again within this


def _person() -> tuple[dict[str, str], dict[str, str]]:
    """The person's descriptions and nesting of categories ({} outside an application), read again when this process
    wrote a setting, when the knowledge changed (any process: freshness), at most every FRESH_S seconds, or when the
    settings reader itself was replaced (tests)."""
    try:
        from supagent import settings
        from supagent.knowledge.freshness import stamp

        key = (settings.get, settings.CHANGED[0], stamp(), int(time.time() // FRESH_S))
        if _SEEN[0] == key:
            return _SEEN[1]
        about = settings.get("categories.about")
        inside = settings.get("categories.inside")
    except Exception:  # pylint: disable=broad-except   (no application, no settings table yet)
        return {}, {}

    def norm(m: Any) -> dict[str, str]:
        return {" ".join(str(k).lower().split()): " ".join(str(v or "").split())
                for k, v in (m if isinstance(m, dict) else {}).items()}
    out = (norm(about), norm(inside))
    _SEEN[:] = [key, out]
    return out


def kind_name(category: Any) -> str:
    """The name the name rules read for a category: its own when it says a kind, else the usual name of what its
    description (else its nesting) says it holds; its own when nothing says it."""
    c = " ".join(str(category or "").lower().split())
    if not c:
        return c
    about, inside = _person()
    parent = inside.get(c, "")
    return _kind(c, about.get(c, ""), parent, about.get(parent, "") if parent else "")


def serverish(category: Any) -> bool:
    """A category of servers or of their groups (a place parts run on), by its name or what holds it."""
    from supagent.knowledge.datalinks import SERVERISH

    return bool(SERVERISH.search(kind_name(category)))
