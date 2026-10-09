"""What the learning may name, where it files it, and the subjects' links (0.10.6.2, the team's reports of 9 October
2026: values proposed as long phrases, monitoring tools, infrastructure services and Java libraries proposed as
applications, subjects linked to nothing).

A value the learning proposes in a category of parts or of subjects (an application, a component, a subject, the
deployment's own categories filled by hand) is a name:
  - categories.learned_max_chars characters at most (30) and categories.learned_max_words words at most (3; a name
    joined by - _ or . is one word): a longer one is a sentence or a description, not proposed
  - no sentence: no , ; : ! ? nor a full stop between words, no brackets nor quotes, not starting with an article
    or a determiner (the, a, our, every...), no verb of a sentence (is, are, has, can, should...)
  - a host's full name (svc.namespace.svc.cluster.local, db-01.example.net) over the limit: its first label, the
    full name kept as another name
Never checked: a value that exists already (a person's, the catalog's, one approved before), a server's or a
group's name (an inventory names them, long or not), the values read in the data's fields.

What a part is, by its name and the AI's description of it when it gave one:
  - a library or a framework the code is built with (log4j, jackson-databind, spring-boot-starter-web, lodash, a
    name ending -lib, -sdk, -common, -utils...): no part of the running system, not proposed (a category of the
    deployment's named like libraries takes it)
  - a monitoring tool (Prometheus, Grafana, Zabbix, an exporter...): the deployment's monitoring category when it
    has one (monitoring, observability, monitoring tool...), else a component
  - an infrastructure service (DNS, LDAP, a proxy, a message broker, a CI server, a vault, an application server)
    or a database server: the deployment's category for them when it has one, else a component
  - anything else: an application, as before
What waits in To review from an older reading is put right the same way at the next learning (settle): a
proposal with a name that is no name, or a library, withdrawn; a tool proposed as an application, moved. A value a
person approved, edited or refused is never changed.

The subjects' links: an item the AI classified under a subject and under a part (an application, a component) is
about both. An approved part and an approved subject that three items or more are about together (a fifth of the
items of one of them at least: a part on every page is no subject's) are proposed linked (the part "relates to" the
subject, source "subjects"), the parts most often with it first, ten per subject at most; the texts they share are
the link's evidence. A link refused is not proposed again; a proposal the items no longer support is withdrawn. They
are drawn on the System map; the agent's paths (impact, chains, leads) do not go through a subject.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from superset import db

log = logging.getLogger(__name__)

MAX_CHARS = 30
MAX_WORDS = 3
SUBJECT_LINKS = "subjects"         # the source of a subject's links (no reading withdraws them but this one)
MIN_SHARED = 3                     # items about both, at least
SHARE = 0.2                        # ... and this share of the items of one of the two at least
PER_SUBJECT = 10                   # parts linked to one subject at most
DETERMINERS = {"a", "an", "the", "this", "that", "these", "those", "our", "your", "their", "its", "my", "every",
               "each", "all", "any", "some", "no", "le", "la", "les", "un", "une", "des", "ce", "cette", "ces",
               "chaque", "tous", "toutes", "notre", "nos", "votre", "vos", "leur", "leurs"}
VERBS = {"is", "are", "was", "were", "be", "been", "being", "has", "have", "had", "does", "do", "did", "can", "could",
         "will", "would", "shall", "should", "must", "may", "might", "est", "sont", "peut", "doit"}
SENTENCE = re.compile(r"[,;:!?\"“”«»()\[\]{}<>|]|\.(\s|$)")
DOTTED = re.compile(r"^[A-Za-z0-9][\w-]*(\.[\w-]+)+$")
# what a part is, by its name (a word of it: a name ending -db is a database, node-exporter a monitoring tool)
LIBRARY = re.compile(
    r"^(?:log4j2?|slf4j(?:-[\w-]+)?|logback(?:-[\w-]+)?|commons-[\w-]+|apache-commons(?:-[\w-]+)?|jackson(?:-[\w-]+)?|"
    r"gson|guava|spring(?:-boot|-cloud|-data|-security|-kafka|-web|-framework)?(?:-starter)?(?:-[\w-]+)?|"
    r"spring framework|spring boot|hibernate(?:-[\w-]+)?|mybatis(?:-[\w-]+)?|junit\d*(?:-[\w-]+)?|testng|"
    r"mockito(?:-[\w-]+)?|assertj(?:-[\w-]+)?|hamcrest|lombok|netty(?:-[\w-]+)?|okhttp\d*|retrofit\d*|"
    r"resilience4j(?:-[\w-]+)?|hystrix|micrometer(?:-[\w-]+)?|dropwizard(?:-[\w-]+)?|jersey(?:-[\w-]+)?|"
    r"jaxb(?:-[\w-]+)?|jakarta(?:[.-][\w.-]+)?|javax(?:[.-][\w.-]+)?|servlet-api|reactor-[\w-]+|rxjava\d*|"
    r"vertx(?:-[\w-]+)?|vert\.x|akka(?:-[\w-]+)?|kafka-clients|kafka-streams|ojdbc\d*|[\w-]+-jdbc|jdbc(?:-[\w-]+)?|"
    r"(?:postgresql|mysql|mariadb|mongodb|mssql|oracle)-(?:jdbc|driver|connector)[\w-]*|flyway(?:-[\w-]+)?|"
    r"liquibase(?:-[\w-]+)?|quartz-scheduler|itext\w*|bouncycastle|bcprov[\w-]*|"
    r"joda-time|protobuf(?:-[\w-]+)?|grpc-(?:java|netty|stub|protobuf)[\w-]*|avro|swagger(?:-[\w-]+)?|"
    r"springdoc(?:-[\w-]+)?|openapi-generator|mapstruct|wiremock|testcontainers(?:-[\w-]+)?|selenium(?:-[\w-]+)?|"
    r"jjwt|java-jwt|caffeine|ehcache\d*|jedis|lettuce(?:-core)?|redisson|aws-sdk(?:-[\w-]+)?|azure-sdk(?:-[\w-]+)?|"
    r"lodash|axios|jquery|react(?:-dom|-router)?|angular(?:-[\w-]+)?|vuex?|webpack|babel(?:-[\w-]+)?|typescript|"
    r"numpy|pandas|scipy|urllib3|flask|django|sqlalchemy|pydantic|fastapi|boto3|botocore|pytest|"
    r"[\w-]+-(?:lib|libs|library|sdk|commons?|utils?|starter|parent|bom|dto|shared-lib))$", re.I)
#   (not a name ending -model, -driver, nor quartz: a team's risk model service, a platform of that name)
LIBRARY_SAID = re.compile(r"\b(librar(?:y|ies)|framework|sdk|jar|driver|plugin|dependency|npm package|python package|"
                          r"java package|maven artifact|toolkit)\b", re.I)
PART_SAID = re.compile(r"\b(application|app|service|server|daemon|job|batch|portal|website|platform|api|gateway|"
                       r"worker|engine)\b", re.I)
MONITORING = re.compile(
    r"(^|[\W_])(prometheus|alertmanager|grafana|thanos|mimir|cortex|victoria-?metrics|loki|promtail|jaeger|zipkin|"
    r"opentelemetry|otel|kibana|logstash|filebeat|metricbeat|auditbeat|packetbeat|winlogbeat|fluentd|fluent-?bit|"
    r"telegraf|graphite|statsd|collectd|nagios|icinga2?|zabbix|prtg|centreon|checkmk|check-mk|sensu|datadog|"
    r"new-?relic|dynatrace|appdynamics|splunk|sumo-?logic|sentry|pagerduty|opsgenie|uptime-?kuma|blackbox|cadvisor|"
    r"kube-state-metrics|pushgateway|graylog|elastalert|cloudwatch|instana|wavefront|signalfx|honeycomb|"
    r"lightstep|solarwinds|netdata|munin|cacti|observium|librenms|smokeping|nxlog|syslog-ng|apm|monitoring|"
    r"observability|exporter|grafana-agent)($|[\W_])", re.I)
MONITORING_SAID = re.compile(r"\b(monitor(?:ing|s)?|observability|metrics? (?:collector|server|store)|alerting|"
                             r"dashboards? tool|log (?:shipper|collector|aggregator))\b", re.I)
DATABASE = re.compile(
    r"(^|[\W_])(postgres(?:ql)?|pg|mysql|mariadb|oracle-?db|mssql|sql-?server|db2|mongo(?:db)?|cassandra|"
    r"scylla(?:db)?|couchbase|couchdb|neo4j|clickhouse|timescale(?:db)?|influx(?:db)?|elasticsearch|opensearch|solr|"
    r"sybase|informix|teradata|snowflake|bigquery|redshift|hbase|druid|cockroach(?:db)?|yugabyte(?:db)?|tidb|"
    r"sqlite|db|database|pgbouncer|patroni)($|[\W_])", re.I)
INFRASTRUCTURE = re.compile(
    r"(^|[\W_])(dns|bind9|unbound|coredns|powerdns|ntp|chrony|ldap|openldap|active-?directory|kerberos|keycloak|"
    r"freeipa|vault|consul|etcd|zookeeper|nomad|kubernetes|k8s|openshift|rancher|harbor|nexus|artifactory|jenkins|"
    r"gitlab(?:-runner)?|bamboo|teamcity|sonarqube|argo-?cd|ansible|awx|terraform|puppet(?:server)?|saltstack|"
    r"vmware|vsphere|esxi|vcenter|proxmox|openstack|ceph|nfs|glusterfs|minio|s3|nginx|haproxy|envoy|traefik|istio|"
    r"linkerd|f5|bigip|httpd|squid|load-?balancer|firewall|vpn|bastion|jump-?host|smtp|postfix|exim|sendmail|"
    r"mail-?relay|kafka|rabbitmq|activemq|artemis|ibm-?mq|mqseries|nats|pulsar|redis|memcached|veeam|bacula|"
    r"commvault|netbackup|control-?m|autosys|rundeck|dhcp|cobbler|netbox|tomcat|jboss|wildfly|weblogic|websphere|"
    r"jetty|ingress(?:-nginx)?|cert-?manager|external-dns|docker-registry|gitea|cache|queue|broker|proxy)($|[\W_])",
    re.I)
INFRASTRUCTURE_SAID = re.compile(r"\b(infrastructure|middleware|message broker|load balancer|reverse proxy|"
                                 r"directory service|application server|ci server|backup (?:server|tool))\b", re.I)
# the deployment's own categories for them (a name of its own; none: a component)
OWN = {"library": re.compile(r"^(librar(?:y|ies)|frameworks?|dependenc(?:y|ies))$", re.I),
       "monitoring": re.compile(r"^(monitoring|observability|supervision)(?: (?:tools?|systems?|stack|platform|"
                                r"solutions?))?$|^(?:monitoring |observability )?tools?$", re.I),
       "infrastructure": re.compile(r"^(infra|infrastructure|platform|middleware)(?: (?:services?|components?|"
                                    r"tools?))?$|^(?:technical|shared|core) services?$", re.I),
       "database": re.compile(r"^(databases?|data ?stores?|datastores?)$", re.I)}


def _setting(key: str, default: int) -> int:
    try:
        from supagent import settings

        return max(1, int(settings.get(key) or default))
    except Exception:  # pylint: disable=broad-except   (outside an app: the default)
        return default


def max_chars() -> int:
    return _setting("categories.learned_max_chars", MAX_CHARS)


def max_words() -> int:
    return _setting("categories.learned_max_words", MAX_WORDS)


def checked(category: str | None, name: Any) -> tuple[str | None, list[str], str]:
    """A name the learning would give a new value of `category`: (the name, its other names, "") or (None, [], why
    not). A server's or a group's category, or one read from the data's fields, takes any name."""
    raw = " ".join(str(name or "").split()).strip("`*_'\" ")
    if not raw:
        return None, [], "empty"
    if not gated(category):
        return raw[:128], [], ""
    others: list[str] = []
    limit = max_chars()
    if len(raw) > limit and DOTTED.match(raw):           # a host's full name: its first label
        first = raw.split(".", 1)[0]
        if len(first) >= 2 and any(ch.isalpha() for ch in first):
            raw, others = first, [raw[:128]]
    if len(raw) > limit:
        return None, [], f"longer than {limit} characters"
    if SENTENCE.search(raw):
        return None, [], "a phrase (its punctuation)"
    words = raw.split()
    if len(words) > max_words():
        return None, [], f"a phrase (more than {max_words()} words)"
    low = [w.lower() for w in words]
    if len(words) > 1 and low[0] in DETERMINERS:
        return None, [], "a phrase (it starts with an article)"
    if any(w in VERBS for w in low):
        return None, [], "a phrase (a verb)"
    return raw, others, ""


def gated(category: str | None) -> bool:
    """Whether the learning's new values of this category are checked as names: not a server's, a group's or an
    address's category (an inventory names them), not one of the deployment's own read from the data's fields (an
    environment, a tenant: the data's values); the built-in ones always (the AI and the documents propose them)."""
    from supagent.knowledge.datalinks import SERVERISH

    c = str(category or "")
    if not c or c == "aspect" or SERVERISH.search(c):
        return False
    try:
        from supagent.knowledge.facets import BUILTIN, field_rules

        return c in BUILTIN or c not in {cat for cat, _rx in field_rules()}
    except Exception:  # pylint: disable=broad-except
        return True


def kind_of(name: Any, description: str | None = None) -> str | None:
    """What a part is by its name (and what the AI said it is): library, monitoring, database, infrastructure, or
    None (an application, as far as its name tells)."""
    n = " ".join(str(name or "").lower().replace("_", "-").split())
    said = str(description or "")
    if not n:
        return None
    if LIBRARY.match(n) or (LIBRARY_SAID.search(said) and not PART_SAID.search(said)):
        return "library"
    head = " ".join(said.split()[:3])                    # "Prometheus instance for...": what it is, said first
    if MONITORING.search(n) or (said and (MONITORING_SAID.search(said) or MONITORING.search(head))
                                and not DATABASE.search(n)):
        return "monitoring"
    if DATABASE.search(n):
        return "database"
    if INFRASTRUCTURE.search(n) or (said and INFRASTRUCTURE_SAID.search(said)):
        return "infrastructure"
    return None


def filed(category: str, name: Any, description: str | None = None, cats: list[str] | None = None
          ) -> tuple[str | None, str | None]:
    """The category a part named so goes to when the learning proposes it in `category`: (the category, what it
    is), the category None for a library with no category of its own. Only an application or a component is
    filed again; the deployment's own categories and the subjects keep what they are given."""
    if category not in ("application", "component"):
        return category, None
    kind = kind_of(name, description)
    if kind is None:
        return category, None
    if cats is None:
        from supagent.knowledge.facets import editable

        cats = list(editable())
    own = next((c for c in cats if OWN[kind].match(c)), None)
    if kind == "library":
        return own, kind
    if own:
        return own, kind
    if kind in ("database", "infrastructure") and category == "component":
        return category, kind
    return ("component" if "component" in cats else category), kind


def withdraw(f: Any) -> None:
    """A proposal of the learning taken back: what was proposed with it goes, what was refused about it too (it was
    never anyone's), and the value."""
    from sqlalchemy import or_

    from supagent.knowledge.facets import drop_with_value
    from supagent.models import Link, Tag

    drop_with_value(f)
    ref = f"facet:{f.id}"
    db.session.query(Link).filter(or_(Link.a_ref == ref, Link.b_ref == ref)).delete(synchronize_session=False)
    db.session.query(Tag).filter(Tag.facet_id == f.id).delete(synchronize_session=False)
    db.session.delete(f)


def tidy() -> dict[str, int]:
    """What waits in To review from an older reading, put right (see the module): the learning's proposals only
    (the AI's, the documents'), never a value a person approved, edited or refused."""
    from supagent.knowledge.facets import editable
    from supagent.models import Facet

    out = {"withdrawn_names": 0, "withdrawn_libraries": 0, "moved_tools": 0}
    cats = list(editable())
    rows = (db.session.query(Facet).filter(Facet.status == "proposed", Facet.source.in_(("llm", "docs")),
                                           Facet.facet.in_(cats), Facet.reviewed_by.is_(None)).order_by(Facet.id).all())
    taken = {(f.facet, f.value.lower()) for f in db.session.query(Facet.facet, Facet.value)}
    for f in rows:
        name, others, _why = checked(f.facet, f.value)
        if name is None or (name != f.value and (f.facet, name.lower()) in taken):
            withdraw(f)                                  # no name, or the short name's value exists: its twin
            out["withdrawn_names"] += 1
            continue
        if name != f.value:
            taken.add((f.facet, name.lower()))
            f.synonyms = sorted(set(f.synonyms or []) | set(others)) or None
            f.value = name
        to, kind = filed(f.facet, f.value, f.description, cats)
        if kind is None or to == f.facet:
            continue
        if to is None:
            withdraw(f)
            out["withdrawn_libraries"] += 1
            continue
        if (to, f.value.lower()) in taken:               # the other category has it: the proposal is a twin
            withdraw(f)
            out["withdrawn_names"] += 1
            continue
        taken.discard((f.facet, f.value.lower()))
        taken.add((to, f.value.lower()))
        f.facet = to
        f.origins = ((f.origins or []) + [f"a {kind} tool or service by its name, not an application"
                                          if kind != "database" else "a database by its name, not an application"])[-10:]
        out["moved_tools"] += 1
    db.session.flush()
    return out


def _titles(refs: list[str]) -> dict[str, str]:
    """What the items are, in a few words (their titles)."""
    from supagent.models import ContextPage, Doc, Entry, KObject, Memory, Note, Recipe

    models = {"entry": (Entry, "title"), "doc": (Doc, "title"), "context": (ContextPage, "title"),
              "note": (Note, "title"), "memory": (Memory, "text"), "recipe": (Recipe, "question"),
              "object": (KObject, "name")}
    out: dict[str, str] = {}
    wanted: dict[str, dict[int, str]] = {}
    for r in refs:
        kind, _, rest = r.partition(":")
        ident = rest.split("#", 1)[0]
        if kind in models and ident.isdigit():
            wanted.setdefault(kind, {})[int(ident)] = r
        elif kind == "family":
            out[r] = (rest.split(":", 1)[1] if ":" in rest else rest) + "_* metrics"
    for kind, ids in wanted.items():
        model, attr = models[kind]
        try:
            for o in db.session.query(model).filter(model.id.in_(list(ids))):
                out[ids[o.id]] = " ".join(str(getattr(o, attr, "") or "").split())[:80]
        except Exception:  # pylint: disable=broad-except
            db.session.rollback()
    return out


def subject_links(dry_run: bool = False) -> dict[str, int]:
    """The parts and the subjects the same items are about, proposed linked (see the module). Counts; `dry_run`
    counts what would be proposed and changes nothing."""
    from supagent.knowledge.datalinks import SERVERISH
    from supagent.knowledge.facets import base_ref, editable
    from supagent.models import Facet, Link, Tag

    cats = [c for c in editable() if c not in ("subject", "aspect") and not SERVERISH.search(c)]
    subjects = {f.id: f for f in db.session.query(Facet).filter(Facet.facet == "subject", Facet.status == "approved")}
    parts = {f.id: f for f in db.session.query(Facet).filter(Facet.facet.in_(cats), Facet.status == "approved")}
    out = {"proposed": 0, "withdrawn": 0, "largest": 0, "subjects": 0}
    if not subjects or not parts:
        return out
    on: dict[str, tuple[set[int], set[int]]] = {}
    for ref, fid in db.session.query(Tag.ref, Tag.facet_id).filter(Tag.status != "rejected",
                                                                   Tag.facet_id.in_(list(subjects) + list(parts))):
        s, p = on.setdefault(base_ref(ref), (set(), set()))
        (s if fid in subjects else p).add(fid)
    shared: dict[tuple[int, int], set[str]] = {}
    count: dict[int, int] = {}
    for ref, (ss, ps) in on.items():
        for x in ss | ps:
            count[x] = count.get(x, 0) + 1
        for s in ss:
            for p in ps:
                shared.setdefault((p, s), set()).add(ref)
    keep: dict[tuple[int, int], set[str]] = {}
    by_subject: dict[int, list[tuple[int, set[str]]]] = {}
    for (p, s), refs in shared.items():
        if len(refs) >= MIN_SHARED and len(refs) >= SHARE * min(count[p], count[s]):
            by_subject.setdefault(s, []).append((p, refs))
    for s, cands in by_subject.items():
        cands.sort(key=lambda x: (-len(x[1]), parts[x[0]].value.lower()))
        for p, refs in cands[:PER_SUBJECT]:
            keep[(p, s)] = refs
    out["subjects"] = len(by_subject)
    out["largest"] = max((min(len(c), PER_SUBJECT) for c in by_subject.values()), default=0)
    have = {(x.a_ref, x.b_ref): x for x in db.session.query(Link).filter(
        Link.kind == "about", Link.a_ref.like("facet:%"), Link.b_ref.like("facet:%"))}
    titles = _titles(sorted({r for refs in keep.values() for r in list(refs)[:40]})) if keep and not dry_run else {}
    for (p, s), refs in sorted(keep.items(), key=lambda x: (x[0][1], -len(x[1]), x[0][0])):
        a_ref, b_ref = f"facet:{p}", f"facet:{s}"
        if (a_ref, b_ref) in have or (b_ref, a_ref) in have:
            continue                                     # drawn, waiting, or refused: as it is
        out["proposed"] += 1
        if dry_run:
            continue
        named = [titles.get(r) or r for r in sorted(refs)][:3]
        P, S = parts[p].value, subjects[s].value
        db.session.add(Link(
            a_ref=a_ref, b_ref=b_ref, kind="about", status="proposed", source=SUBJECT_LINKS, confidence=0.7,
            note=f"its texts are about {S}"[:90],
            detail=(f"{len(refs)} texts the AI classified are about both {P} and {S}"
                    f" ({'; '.join(named)}). A question about {S} may concern {P}: its documents, its data and its "
                    f"health are where to look.")[:700],
            evidence=(f"{len(refs)} texts are about both: " + "; ".join(f'"{t}"' for t in named)
                      + " (the AI's classification of the texts)")[:2000]))
    for (a_ref, b_ref), x in have.items():               # a proposal the items no longer support: withdrawn
        if x.source != SUBJECT_LINKS or x.status != "proposed":
            continue
        try:
            key = (int(a_ref.split(":", 1)[1]), int(b_ref.split(":", 1)[1]))
        except ValueError:
            continue
        if key not in keep:
            out["withdrawn"] += 1
            if not dry_run:
                db.session.delete(x)
    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return out
