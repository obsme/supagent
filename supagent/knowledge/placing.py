"""(0.10.10, the team's report of 12 October: "the classifications should follow the principal categories I put in
place") Where a part the documents name is proposed: in the deployment's own category for what it is, when the
deployment has one, instead of the first server-like category for every group, VIP or namespace and "application"
for every topic, job, bucket or provider.

What a part is comes from three kinds of evidence, without any service (no LLM, no embeddings):
  - the words next to its name in the sentences that state it ("the topic X", "the cron job X", "X, the Ansible
    group of ..."): the strongest;
  - what the reading knows of it (an inventory's group, a host, a VIP, a namespace, a database...);
  - the shape of its name (a "-pg" or "-db" suffix, "vip-", a "-job" suffix, a dotted name published to);
each giving a concept (a host, a group, a queue, a store, a job, a provider...). The deployment's categories are read
the same way, from their names first and then from what categories.about says of them: the category whose name says
the concept is the one; when none does, the part goes where it went before (nothing is guessed)."""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable

# a concept and the words that say it (generic words of operations and architecture; the longest phrases first)
CONCEPTS: dict[str, tuple[str, ...]] = {
    "host": ("virtual machine", "virtual machines", "hostname", "server", "servers", "host", "hosts", "vm", "vms",
             "machine", "machines", "node", "nodes", "baremetal", "bare metal"),
    "group": ("inventory group", "host group", "server group", "ansible group", "group", "groups", "server pool",
              "server pools", "host pool", "host pools", "pool", "pools"),
    "vip": ("virtual ip", "virtual ips", "virtual address", "floating ip", "vip", "vips"),
    "balancer": ("load balancer", "load balancers"),
    "namespace": ("namespace", "namespaces"),
    "cluster": ("kubernetes cluster", "k8s cluster", "cluster", "clusters"),
    "store": ("data store", "data stores", "datastore", "database", "databases", "db", "dbs", "schema"),
    "cache": ("key-value store", "cache", "caches"),
    "messaging": ("topic", "topics", "queue", "queues", "stream", "streams", "exchange"),
    "broker": ("message broker", "event bus", "broker", "brokers"),
    "object": ("object storage", "object store", "object stores", "blob container", "blob containers", "blob storage",
               "bucket", "buckets", "file share", "file shares", "network share", "network shares"),
    "job": ("cron job", "cron jobs", "batch job", "batch jobs", "scheduled job", "scheduled jobs", "scheduled task",
            "scheduled tasks", "batch task", "batch tasks", "cron", "crontab", "job", "jobs",
            "batch"),
    "external": ("third-party", "third party", "third parties", "external service", "external services",
                 "external system", "external systems", "external api", "external apis", "provider",
                 "providers", "vendor", "vendors", "partner", "partners", "supplier", "saas"),
    "team": ("squad", "squads", "team", "teams", "crew", "tribe"),
    "domain": ("business line", "business lines", "line of business", "business domain", "business area",
               "business areas", "business unit", "business units", "domain", "domains", "service area",
               "service areas", "functional area", "functional areas", "area", "areas"),   # (0.10.9.3) areas
    "service": ("microservice", "microservices", "micro-service", "api", "apis", "worker", "workers", "consumer"),
    "application": ("application", "applications", "app", "apps", "system", "systems"),
    "environment": ("environment", "environments", "stage", "stages"),
    "dashboard": ("dashboard", "dashboards"),
    "alert": ("alerting rule", "alert rule", "alert rules", "alert", "alerts"),
    "certificate": ("tls certificate", "certificate", "certificates"),
    "dns": ("dns name", "dns names", "dns record", "domain name", "fqdn"),
}
PHRASES = sorted(((p, c) for c, ps in CONCEPTS.items() for p in ps), key=lambda pc: -len(pc[0]))
# what the reading calls a part -> its concept
KIND_CONCEPT = {"host": "host", "group": "group", "vip": "vip", "namespace": "namespace", "cluster": "cluster",
                "database": "store", "cache": "cache", "queue": "messaging", "topic": "messaging", "job": "job",
                "dashboard": "dashboard", "team": "team", "owner": "team", "object": "object", "external": "external",
                "stream": "messaging", "component": "service", "module": "service", "service": "service",
                "application": "application", "domain": "domain", "environment": "environment", "server pool": "group",
                "host group": "group", "platform": "application", "product line": "domain"}   # (0.10.10)
# the shape of a name (weak): its last word or its first
SHAPES = [(re.compile(r"[-_](pg|postgres|mysql|mariadb|mongo|tsdb|db|oracle|sql)\d*$", re.I), "store"),
          (re.compile(r"[-_](cache|redis|memcached?)\d*$", re.I), "cache"),
          (re.compile(r"^vip[-_]|[-_]vip$", re.I), "vip"),
          (re.compile(r"[-_](job|cron|batch)$", re.I), "job"),
          (re.compile(r"^s3://", re.I), "object")]
DOTTED = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*){1,3}$")
TLD = re.compile(r"\.(internal|local|lan|corp|com|net|org|io|example|intra|prod|cloud)$", re.I)
WORDS = 4                                        # words before a name read as its noun ("the Ansible group X")
CUE, KIND, SHAPE = 3, 2, 1                       # the weights of the three kinds of evidence


def _name_rx(name: str) -> str:
    """(0.10.10) A name as a sentence may write it: its words joined by a space, a dash, an underscore or nothing
    ("rating engine", "rating-engine", "Rating_Engine", "RatingEngine"), never inside a longer name."""
    words = [w for w in re.split(r"[\s_-]+|(?<=[a-z0-9])(?=[A-Z])", str(name or "").strip()) if w]
    body = r"[\s_-]?".join(re.escape(w.lower()) for w in words) if len(words) > 1 else re.escape(str(name).lower())
    return r"(?<![\w.-])" + body + r"(?![\w-])"


def phrases(text: str) -> Counter:
    """The concepts a text says (each phrase once, the longest first: "cron job" is a job, not a job and a cron)."""
    low = " " + re.sub(r"[^a-z0-9.:/-]+", " ", str(text or "").lower()) + " "
    out: Counter = Counter()
    for p, c in PHRASES:
        pat = re.compile(r"(?<=[ ])" + re.escape(p) + r"(?=[ ])")
        if pat.search(low):
            out[c] += 1
            low = pat.sub(" # ", low)
    return out


def affinity(category: str, about: str = "") -> Counter:
    """What a category of the deployment is: the concepts its name says (x3), then its description (x1)."""
    out = Counter({c: 3 * n for c, n in phrases(category.replace("_", " ")).items()})
    for c, n in phrases(about or "").items():
        out[c] += n
    return out


def best_category(concept: str, cats: Iterable[str], about: dict[str, str] | None = None) -> str | None:
    """The deployment's category for a concept: the one whose NAME says it (the description breaks a tie), else
    none."""
    about = about or {}
    scored = []
    for c in cats:
        a = affinity(c, about.get(c, ""))
        named = phrases(c.replace("_", " ")).get(concept, 0)
        if named:
            # the concept said by the name, then fewer other concepts in the name (a "data store" over an
            # "object store" for a store: object said first), then the description
            others = sum(1 for k in phrases(c.replace("_", " ")) if k != concept)
            scored.append((named, -others, a.get(concept, 0), -len(c), c))
    if scored:
        return max(scored)[-1]
    described = [c for c in cats if defining(about.get(c, "")).get(concept)]   # (0.10.10) no name says it: the
    return described[0] if len(described) == 1 else None                        # one category its description
    #                       defines as it ("project: a tenant project (a namespace)"), never one that only
    #                       mentions it ("host farm: a farm of worker hosts" is no worker)


def defining(text: str) -> Counter:
    """(0.10.10) The concepts a description defines its category as: its head noun phrase and a parenthesis right
    after it ("a tenant project (a namespace) of a cluster": namespace; "a farm of worker hosts": a farm), and
    the head of what follows a first colon ("a datastore: a database or a key-value store holding ...")."""
    t = str(text or "")
    m0 = re.match(r"\s*([^:;]{1,60}):\s*(.+)$", t, re.S)
    out: Counter = Counter()
    for part in ([m0.group(1)] + ([m0.group(2)] if re.match(r"(?i)\s*(?:a|an|one)\s", m0.group(2)) else [])
                 if m0 else [t]):                     # (what follows the colon defines it when it says "a ...": "the
        #                                               applications that serve one business" are its content)
        m = re.match(r"\s*(?P<head>[^:;,(]*?)(?=\s+(?:of|for|in|on|at|with|from|that|which|who|where|whose|holding|"
                     r"carrying|serving|running|used)\b|\s*[:;,(]|$)\s*(?:\((?P<also>[^)]{1,40})\))?", part, re.I)
        if m:
            out.update(phrases(m.group("head") + " " + (m.group("also") or "")))
    return out


AFTER = ("job", "team", "domain", "group", "store", "messaging", "object", "cluster", "namespace", "broker",
         "external")                             # a noun after a name says what it is ("X cron job", "X squad")
PHRASE_OF = {p: c for p, c in PHRASES}


def cues(quote: str, name: str) -> Counter:
    """The concepts the noun right before a name ("the topic X", "the Ansible group X") or right after it ("X cron
    job", "X squad", "X business line") says in a sentence; never words further away (a page's "the payments domain
    consists of A, B" says nothing of A)."""
    if not quote or not name:
        return Counter()
    low = str(quote).lower()
    out: Counter = Counter()
    found = list(re.finditer(_name_rx(name), low))
    if len(found) != 1:
        return out                               # twice in one sentence ("sso runs on the group sso"): which one?
    for m in found:                              # (the words up to a punctuation only: "hosts: x" is a key)
        before = re.findall(r"[a-z0-9-]+", re.split(r"[^a-z0-9\s-]", low[:m.start()])[-1])[-3:]
        for k in (3, 2, 1):
            if len(before) >= k and " ".join(before[-k:]) in PHRASE_OF:
                out[PHRASE_OF[" ".join(before[-k:])]] += 1
                break
        after = re.findall(r"[a-z0-9-]+", re.split(r"[^a-z0-9\s-]", low[m.end():])[0])[:2]
        for k in (2, 1):
            c = PHRASE_OF.get(" ".join(after[:k])) if len(after) >= k else None
            if c in AFTER:
                out[c] += 1
                break
    return out


def shape(name: str, published: bool = False) -> Counter:
    """The concepts a name's shape says (a dotted name a part publishes to or consumes from: a topic)."""
    out: Counter = Counter()
    for rx, c in SHAPES:
        if rx.search(str(name or "").strip()):
            out[c] += 1
    if published and DOTTED.match(str(name or "").strip()) and not TLD.search(str(name).strip()):
        out["messaging"] += 1
    return out


HOSTISH = {"host", "group", "vip", "namespace", "cluster", "balancer"}


def concept(kind: str | None, said: Counter | None, name: str, published: bool = False) -> str | None:
    """What a part is, all evidence weighed (None: nothing says it). What the reading knows bounds what the words
    may say: a host or a group the inventory names stays a place parts run on (a group, a VIP, a namespace...), a
    part that runs on places is no place itself (an application and its Ansible group of the same name)."""
    score: Counter = Counter()
    place = KIND_CONCEPT.get(kind or "") in HOSTISH
    for c, n in (said or Counter()).items():
        if (c in HOSTISH) == place:
            score[c] += CUE * min(n, 3)
    if kind and KIND_CONCEPT.get(kind):
        score[KIND_CONCEPT[kind]] += KIND
    for c, n in shape(name, published).items():
        if (c in HOSTISH) == place:
            score[c] += SHAPE * n
    if not score:
        return None
    top = score.most_common(2)
    if len(top) > 1 and top[0][1] == top[1][1]:
        return None                                  # two things said as strongly: where it went before
    return top[0][0]


def choose(base: str | None, kind: str | None, name: str, said: Counter | None, cats: list[str],
           about: dict[str, str] | None = None, published: bool = False) -> str | None:
    """The category a part is proposed in: the deployment's own for what it is, else `base` (as before)."""
    c = concept(kind, said, name, published)
    if c is None:
        return base
    own = best_category(c, cats, about)
    return own or base


def named_categories(quote: str, name: str, cats: list[str]) -> Counter:
    """(0.10.10) A category of the deployment written right next to a name in a sentence ("the X platform service",
    "the stream X", "le service X"): the page says it; the strongest evidence of all."""
    if not quote or not name:
        return Counter()
    low = str(quote).lower()
    found = list(re.finditer(_name_rx(name), low))
    if len(found) != 1:
        return Counter()
    m = found[0]
    before = re.findall(r"[a-z0-9-]+", re.split(r"[^a-z0-9\s-]", low[:m.start()])[-1])[-3:]
    after = re.findall(r"[a-z0-9-]+", re.split(r"[^a-z0-9\s-]", low[m.end():])[0])[:3]
    forms = {}
    for c in cats:
        if c in ("subject", "aspect"):
            continue
        for f in (c.lower(), c.lower() + "s", c.lower() + "es"):
            forms.setdefault(f, c)
    out: Counter = Counter()
    for k in (3, 2, 1):
        if len(after) >= k and " ".join(after[:k]) in forms:
            out[forms[" ".join(after[:k])]] += 1
            break
    for k in (3, 2, 1):
        if len(before) >= k and " ".join(before[-k:]) in forms:
            out[forms[" ".join(before[-k:])]] += 1
            break
    return out
