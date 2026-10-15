"""(0.10.10, the team's request of 14 October: "create and set up an alert rule based on the rules we will put in
the catalog or in memory") Alert rules for Grafana, never written by the agent alone:

1. a draft (grafana_draft_alert_rule): the agent gives the rule's fields read from a rule the team wrote (an active
   team memory of kind rule, an enabled catalog entry of classification rule or checks) or asked for in a chat:
   its title, its PromQL query, an operator and a number, how long it must hold, labels of the allowed keys, a
   summary. What the draft may never choose comes from the settings: the folder (grafana.alert_folder), the rule
   group and its interval, the fixed labels, the datasource. Checked: every metric the query reads exists in the
   datasource (none is guessed), the threshold is a number, "for" is at most a day, the texts are short, no rule of
   that UID or of that title is in the folder already. The rule's UID comes from its source and the source's text:
   asked twice, the same draft is found, not made again. Stored with its spec's hash, the query's value now and
   who would be notified, for an admin in To review;
2. approval (approve): only an admin, only with grafana.writes on; the spec must still have its hash; checked
   again; then created with alerting_rules_write (create only) and read back: what Grafana holds is compared with
   the draft, the result kept with who approved it and when. Rejected: kept as rejected.

Texts read in Grafana, the catalog or a memory are data: nothing in them chooses a folder, deletes or changes
anything (the only write is the approved create of the approved spec)."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import re
from typing import Any

from supagent import grafana as G

OPERATORS = {"gt": "gt", ">": "gt", "above": "gt", "over": "gt", "more": "gt", "greater": "gt",
             "lt": "lt", "<": "lt", "below": "lt", "under": "lt", "less": "lt", "fewer": "lt"}
DURATION = re.compile(r"^\s*(\d{1,5})\s*(s|m|h)\s*$", re.I)
MAX_FOR_S = 24 * 3600
LABEL_VALUE = re.compile(r"^[A-Za-z0-9_.:/@ -]{1,64}$")
TITLE_OK = re.compile(r"^[^\x00-\x1f<>{}]{3,190}$")
RULE_WORDS = re.compile(r"(?i)\b(alert\w*|alarm\w*|notify|notif\w*|page|threshold|above|below|exceeds?|more than|"
                        r"less than|over|under|for (?:\d+|more than)|seuil|alerte\w*|d[ée]passe)\b")
# what PromQL names that is no metric: its functions, keywords, aggregations' clauses
PROMQL_WORDS = frozenset("""sum avg min max count group stddev stdvar topk bottomk quantile count_values by without on
ignoring group_left group_right bool and or unless offset rate irate increase delta idelta deriv predict_linear
histogram_quantile label_replace label_join abs ceil floor round clamp clamp_max clamp_min time timestamp vector
scalar absent absent_over_time changes resets sort sort_desc exp ln log2 log10 sqrt sgn day_of_month day_of_week
day_of_year days_in_month hour minute month year avg_over_time min_over_time max_over_time sum_over_time
count_over_time quantile_over_time stddev_over_time stdvar_over_time last_over_time present_over_time
holt_winters double_exponential_smoothing limitk limit_ratio inf nan""".split())


class RuleError(ValueError):
    """Why a draft or an approval was refused (said as it is)."""


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)


def metrics_of(expr: str) -> list[str]:
    """The metric names a PromQL expression reads (functions, keywords, label names and durations left out)."""
    t = re.sub(r'"(?:[^"\\]|\\.)*"', " ", str(expr or ""))          # strings
    t = re.sub(r"\{[^{}]*\}", " ", t)                                 # label matchers
    t = re.sub(r"\[[^\[\]]*\]", " ", t)                               # ranges, subqueries
    t = re.sub(r"\b(by|without|on|ignoring|group_left|group_right)\s*\([^()]*\)", " ", t, flags=re.I)
    out = []
    for m in re.finditer(r"(?<![\w:.])([A-Za-z_:][A-Za-z0-9_:]*)(?![A-Za-z0-9_:])(?!\s*\()", t):
        name = m.group(1)
        if name.lower() in PROMQL_WORDS or re.fullmatch(r"\d+[smhdwy]?", name):
            continue
        if name not in out:
            out.append(name)
    return out


def _labels(given: dict[str, Any]) -> dict[str, str]:
    from supagent import settings

    keys = {str(k).strip() for k in (settings.get("grafana.label_keys") or []) if str(k).strip()}
    out: dict[str, str] = {}
    for k, v in given.items():
        v = " ".join(str(v or "").split())
        if not v:
            continue
        if k not in keys:
            raise RuleError(f"a label {k!r} is not one a draft may set (grafana.label_keys: {sorted(keys)})")
        if not LABEL_VALUE.fullmatch(v):
            raise RuleError(f"the label {k}={v!r}: letters, digits and . : / @ - _ only, 64 at most")
        out[k] = v
    fixed = settings.get("grafana.rule_labels") or {}
    for k, v in (fixed.items() if isinstance(fixed, dict) else []):
        out[str(k)] = str(v)                                   # the fixed labels win
    return out


def _source(source: str) -> tuple[str, str]:
    """(the source's reference, its text): an active team memory of kind rule, an enabled catalog entry of
    classification rule or checks, or a chat."""
    from superset import db

    from supagent.models import Entry, Memory

    s = str(source or "").strip().lower()
    m = re.fullmatch(r"(memory|catalog):(\d+)", s)
    if s in ("", "chat"):
        return "chat", ""
    if not m:
        raise RuleError("source: memory:<id>, catalog:<id> or chat")
    kind, num = m.group(1), int(m.group(2))
    if kind == "memory":
        row = db.session.get(Memory, num)
        if row is None or row.scope != "team" or row.status != "active":
            raise RuleError(f"no active team memory {num}")
        return f"memory:{num}", row.text or ""
    row = db.session.get(Entry, num)
    if row is None or row.deleted_at is not None or not row.enabled:
        raise RuleError(f"no enabled catalog entry {num}")
    return f"catalog:{num}", f"{row.title}\n{row.content or ''}"


# how long a rule's condition must hold, as its text says it ("for 10 minutes", "during 5m", "pendant 2 h"): not a
# threshold in seconds ("p95 above 2 s")
HOLD_WORDS = re.compile(r"(?i)\b(?:for|during|lasting|within|pendant|durant)\s+(?:more than\s+|at least\s+|over\s+|"
                        r"plus de\s+)?(\d{1,5})\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hours?|heures?)\b")


def _hold_of(text: str) -> set[int]:
    """The holds a rule's text says (for 10 minutes, during 1h), in seconds."""
    unit = {"s": 1, "m": 60, "h": 3600}
    return {int(n) * unit[u[0].lower()] for n, u in HOLD_WORDS.findall(str(text or ""))}


# (0.10.10) what every alert rule says (how bad, how long, which way, who is told): never what tells one team rule
# from another (gq1 W10: "team", "warning" and the same ten minutes tied a load rule to the 5xx share's)
RULE_GENERIC = frozenset("""alert alerting alarm rule notify notification severity warning critical info page paging
when stay goe goes above below over under exceed more less than greater fewer higher lower high low drop minute hour
longer least most fire firing threshold create set team""".split())
TEAM_BEFORE = re.compile(r"(?i)\b([a-z0-9][\w-]{1,40})\s+team\b")              # "the shop team"
TEAM_AFTER = re.compile(r"(?i)\bteam\s*[:=]?\s*([a-z0-9][\w-]{1,40})")             # "team: shop", "team shop"
NOT_A_TEAM = frozenset("""when if the is are that who whose for with and or rule rules of on in to a an notify notifies
alert alerts page pages tell inform call our your their my whole same other each every this that""".split())
# a threshold the text says: a number of its own (not the 5 of 5xx, the 95 of p95, the 1 of node_load1), a percent
# when it says so
THRESHOLD = re.compile(r"(?i)(?<![\w.])(\d+(?:\.\d+)?)(?:\s*(%|percent\b|per\s*cent\b|pct\b))?(?![\w.])")
UPWARD = re.compile(r"(?i)\b(above|over|exceed\w*|more than|greater than|higher than|rises?|goes up)\b")
DOWNWARD = re.compile(r"(?i)\b(below|under|less than|fewer than|lower than|drops?|falls?|goes down)\b")


def _team_spans(text: str) -> list[tuple[int, int, str]]:
    """Where a rule's text names a team ("the shop team", "team: shop"): (start, end, its name)."""
    out = []
    for rx in (TEAM_BEFORE, TEAM_AFTER):
        for m in rx.finditer(str(text or "")):
            if m.group(1).lower() not in NOT_A_TEAM:
                out.append((m.start(), m.end(), m.group(1).lower()))
    return out


def _teams_named(text: str) -> set[str]:
    from supagent.grafana_dashboards import _words

    out: set[str] = set()
    for _a, _b, name in _team_spans(text):
        out |= _words(name) or {name}
    return out


def _without_teams(text: str) -> str:
    t = str(text or "")
    gone = set()
    for a, b, _name in _team_spans(t):
        gone.update(range(a, b))
    return "".join(" " if i in gone else c for i, c in enumerate(t))


def _thresholds(text: str) -> set[float]:
    """The thresholds a rule's text can mean: its numbers that are no duration and no part of a name; a percent as
    said and divided by 100."""
    out: set[float] = set()
    for n, pct in THRESHOLD.findall(HOLD_WORDS.sub(" ", str(text or ""))):
        out.add(float(n))
        if pct:
            out.add(float(n) / 100)
    return out


def matching_source(title: str, summary: str, description: str, number: float, seconds: int,
                    operator: str = "", team: str = "") -> dict | None:
    """(0.10.10) The one team rule a draft asked in a chat clearly comes from, else None (none, or several: never
    chosen by chance). Clearly: two words of what is measured in common (not the words every rule says, not its
    team's name), its threshold, its hold when the rule says one, its direction when it says one, and no other team
    named than the draft's."""
    from supagent.grafana_dashboards import _words

    def measured(*texts: str) -> set[str]:
        return _words(*(_without_teams(t) for t in texts)) - RULE_GENERIC

    want = measured(title, summary, description)
    mine = (_words(team) or {str(team).strip().lower()}) if str(team or "").strip() else set()
    hits = []
    for s in sources(limit=200):
        text = s.get("text") or ""
        if len(want & measured(text)) < 2:
            continue
        if not any(abs(n - number) < 1e-9 * max(1.0, abs(number)) for n in _thresholds(text)):
            continue
        holds = _hold_of(text)
        if holds and seconds not in holds:
            continue
        up, down = bool(UPWARD.search(text)), bool(DOWNWARD.search(text))
        if operator and up != down and operator != ("gt" if up else "lt"):
            continue
        named = _teams_named(text)
        if mine and named and not mine & named:
            continue
        hits.append(s)
    return hits[0] if len(hits) == 1 else None


def sources(query: str = "", limit: int = 40, panels: bool = False) -> list[dict[str, Any]]:
    """The team's rules that read as alert rules: active team memories of kind rule and enabled catalog entries of
    classification rule or checks whose text speaks of an alert, a threshold or a notification; `panels`: with the
    team's Grafana panels that already show the same measure (their queries: what a draft should reuse)."""
    from superset import db

    from supagent.models import Entry, Memory

    q = str(query or "").lower().strip()
    out = []
    for m in db.session.query(Memory).filter(Memory.scope == "team", Memory.status == "active",
                                             Memory.kind == "rule").order_by(Memory.id):
        if RULE_WORDS.search(m.text or "") and (not q or q in (m.text or "").lower()):
            out.append({"source": f"memory:{m.id}", "text": G.said(m.text, 800)})
    for e in db.session.query(Entry).filter(Entry.deleted_at.is_(None), Entry.enabled.is_(True),
                                            Entry.classification.in_(("rule", "checks"))).order_by(Entry.id):
        text = f"{e.title}: {e.content or ''}"
        if RULE_WORDS.search(text) and (not q or q in text.lower()):
            out.append({"source": f"catalog:{e.id}", "title": e.title, "text": G.said(text, 800)})
    out = out[:limit]
    if panels:
        for x in out:
            try:
                like = G.similar_panels(x.get("text"), limit=2)
            except G.GrafanaError:
                like = []
            if like:
                x["the team's Grafana already shows it"] = [
                    {k: v for k, v in p.items() if k in ("dashboard", "panel", "queries", "link")} for p in like]
    return out


def _hash(spec: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()


def _datasource() -> str:
    from supagent import settings

    ds = str(settings.get("grafana.datasource") or "").strip()
    if ds:
        return ds
    rows = G.call("list_datasources", {"type": "prometheus"})
    rows = rows if isinstance(rows, list) else (rows.get("datasources") if isinstance(rows, dict) else None) or []
    uids = [r.get("uid") for r in rows if isinstance(r, dict) and r.get("uid")]
    if len(uids) != 1:
        raise RuleError("which datasource do the alert rules query? set grafana.datasource (its UID)" +
                        (f": Grafana has {len(uids)} Prometheus datasources" if uids else ""))
    return str(uids[0])


def _known_metric(ds: str, name: str) -> bool:
    raw = G.call("list_prometheus_metric_names", {"datasourceUid": ds, "regex": f"^{re.escape(name)}$", "limit": 5})
    rows = raw if isinstance(raw, list) else (raw.get("metrics") or raw.get("names") if isinstance(raw, dict) else
                                              None) or []
    return name in [str(x) for x in rows]


# (0.10.10, gq1d D09) what Prometheus says of a query it cannot parse ("bad_data: ... parse error: unexpected <aggr:GROUP>")
PROMQL_INVALID = re.compile(r"(?i)parse error|bad_data|expected type .{0,40} vector|unknown function|unexpected <")


def promql_problem(ds: str, expr: str) -> str | None:
    """Why a draft's query is no valid PromQL, as the datasource says when the query runs once (an instant query):
    None when it runs (with or without data), or when the datasource cannot be asked (nothing then refused)."""
    try:
        G.call("query_prometheus", {"datasourceUid": ds, "expr": expr, "endTime": "now", "queryType": "instant"},
               cached=False)
    except G.GrafanaError as ex:
        if PROMQL_INVALID.search(str(ex)):
            return G.said(str(ex), 300)
    return None


PROMQL_HINT = ('write it in PromQL: a selector with its range for rate/increase, e.g. sum(rate(a_metric{label="x"}[5m])), '
               "an aggregation by labels with by (label), never SQL (GROUP BY, SELECT, WHERE)")


def _value_now(ds: str, expr: str) -> list[float] | None:
    try:
        raw = G.call("query_prometheus", {"datasourceUid": ds, "expr": expr, "endTime": "now",
                                          "queryType": "instant"}, cached=False)
    except G.GrafanaError:
        return None
    vals: list[float] = []
    text = json.dumps(raw)
    for m in re.finditer(r'"value"\s*:\s*\[\s*[\d.e+]+\s*,\s*"([^"]+)"\s*\]', text):
        try:
            vals.append(float(m.group(1)))
        except ValueError:
            pass
    if not vals:
        for m in re.finditer(r'"(?:Value|value)"\s*:\s*(-?[\d.]+(?:e[+-]?\d+)?)', text):
            vals.append(float(m.group(1)))
    return vals


def draft(*, title: str, query: str, operator: str, threshold: float, hold: str = "5m", severity: str = "",
          team: str = "", service: str = "", environment: str = "", summary: str = "", description: str = "",
          runbook_url: str = "", source: str = "chat", requested_by: str = "") -> dict[str, Any]:
    """Check and store a draft (see the module); the existing draft or rule when this one was asked before."""
    from superset import db

    from supagent import settings
    from supagent.models import GrafanaAction

    folder = str(settings.get("grafana.alert_folder") or "").strip()
    if not folder:
        raise RuleError("no folder is set for the agent's alert rules (grafana.alert_folder): an admin sets one first")
    title = " ".join(str(title or "").split())
    if not TITLE_OK.fullmatch(title):
        raise RuleError("a title of 3 to 190 characters, no brackets")
    expr = " ".join(str(query or "").split())
    if not expr or len(expr) > 2000:
        raise RuleError("the rule's PromQL query (2000 characters at most)")
    op = OPERATORS.get(str(operator or "").strip().lower())
    if op is None:
        raise RuleError("operator: gt (above) or lt (below)")
    try:
        number = float(threshold)
    except (TypeError, ValueError):
        raise RuleError("the threshold: a number") from None
    if not math.isfinite(number):
        raise RuleError("the threshold: a finite number")
    m = DURATION.fullmatch(str(hold or "0s"))
    seconds = int(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2).lower()] if m else -1
    if not 0 <= seconds <= MAX_FOR_S:
        raise RuleError("how long it must hold: a duration like 30s, 5m or 2h, a day at most")
    labels = _labels({"severity": severity, "team": team, "service": service, "environment": environment})
    ann = {k: v for k, v in {"summary": G.said(summary, 500), "description": G.said(description, 1500)}.items() if v}
    if runbook_url:
        if not re.fullmatch(r"https?://[^\s<>\"]{3,500}", str(runbook_url).strip()):
            raise RuleError("runbook_url: an http(s) address")
        ann["runbook_url"] = str(runbook_url).strip()
    ref, text = _source(source)
    matched = None
    if ref == "chat":                                     # (0.10.10) a team rule the chat names: its source
        found = matching_source(title, summary, description, number, seconds, op, team)
        if found:
            ref, text = _source(found["source"])
            matched = ref
    ds = _datasource()
    names = metrics_of(expr)
    if not names:
        raise RuleError("the query reads no metric")
    unknown = [n for n in names if not _known_metric(ds, n)]
    if unknown:
        raise RuleError(f"the datasource has no metric {', '.join(unknown)}: find the right one in the data "
                        "dictionary (never guess a metric)")
    bad = promql_problem(ds, expr)
    if bad:
        raise RuleError(f"the query is not valid PromQL ({bad}): {PROMQL_HINT}")
    if ref != "chat":                                     # (0.10.10) the same team rule asked again (other
        made = db.session.query(GrafanaAction).filter(      # words, another query of the same metrics): its draft
            GrafanaAction.kind == "create_rule", GrafanaAction.status.in_(("proposed", "created")),   # waiting, or
            GrafanaAction.source == ref).order_by(GrafanaAction.id.desc()).all()                      # the rule made
        same = [w for w in made if set(metrics_of(str((w.spec or {}).get("query") or ""))) & set(names)]
        live = None
        for w in same:
            if w.status == "proposed":
                return {"already": "drafted from the same team rule, waiting for an admin's approval",
                        "draft": w.id, "rule_uid": w.grafana_uid, "title": w.title, "source": ref}
            if live is None:                              # made: still in Grafana? (deleted there: draft again)
                live = {str(r.get("uid")) for r in G.alert_rules(folder=folder, limit=200, cached=False)}
            if w.grafana_uid in live:
                return {"already": "created in Grafana from the same team rule", "draft": w.id,
                        "rule_uid": w.grafana_uid, "title": w.title, "source": ref}
    seed = (f"{ref}\n{' '.join(text.lower().split())}\n" + json.dumps([expr, op, number], default=str)) \
        if ref != "chat" else json.dumps([title, expr, op, number, seconds], default=str)   # a source of several
    #                                                                                         rules: one UID each
    uid = "sa-" + hashlib.sha256(seed.encode()).hexdigest()[:20]
    group = str(settings.get("grafana.rule_group") or "supagent").strip() or "supagent"
    spec = {"uid": uid, "title": title, "folder_uid": folder, "rule_group": group,
            "datasource": ds, "query": expr,
            "operator": op, "threshold": number, "for": f"{seconds}s", "labels": labels, "annotations": ann,
            "no_data_state": "NoData", "exec_err_state": "Error"}
    before = db.session.query(GrafanaAction).filter(GrafanaAction.grafana_uid == uid).order_by(
        GrafanaAction.id.desc()).first()
    if before is not None and before.status in ("proposed", "created"):
        return {"already": "drafted, waiting for an admin's approval" if before.status == "proposed" else
                "created in Grafana", "draft": before.id, "rule_uid": uid, "title": before.title}
    existing = G.alert_rules(folder=folder, limit=200, cached=False)
    if any(r.get("uid") == uid for r in existing):
        return {"already": "in Grafana", "rule_uid": uid}
    same = [r for r in existing if str(r.get("title") or "").lower() == title.lower()]
    if same:
        raise RuleError(f"the folder has a rule titled {title!r} already (UID {same[0].get('uid')})")
    values = _value_now(ds, expr)
    fires = None if not values else any((v > number) if op == "gt" else (v < number) for v in values)
    try:
        notified = G.notified({**labels, "alertname": title})
    except G.GrafanaError:
        notified = None
    preview = {"value now": values[:10] if values else "no data now", "would fire now": fires,
               "notified": notified, "metrics": names}
    prior = next((w for w in db.session.query(GrafanaAction).filter(
        GrafanaAction.kind == "create_rule", GrafanaAction.status == "proposed", GrafanaAction.source == ref)
        if str(w.title or "").lower() == title.lower()), None)
    if prior is not None:                                 # (0.10.10) a draft of that title corrected: replaced
        row = prior
        row.grafana_uid, row.spec, row.spec_hash, row.preview = uid, spec, _hash(spec), preview
        row.source_text, row.requested_by, row.requested_at = text[:4000] or None, requested_by or None, _now()
    else:
        row = GrafanaAction(kind="create_rule", status="proposed", title=title, grafana_uid=uid, spec=spec,
                            spec_hash=_hash(spec), source=ref, source_text=text[:4000] or None, preview=preview,
                            requested_by=requested_by or None)
        db.session.add(row)
    db.session.commit()
    out = {"drafted": row.id, "rule_uid": uid, "rule": described(spec), "preview": preview,
           "next": "an admin approves it in Data dictionary -> To review; Grafana has nothing until then"}
    if prior is not None:
        out["replaced"] = "the earlier draft of that title (not approved yet): one draft, the newer one"
    if matched:
        out["from the team's rule"] = f"{matched}: {G.said(text, 300)}"
    try:
        like = [p for p in G.similar_panels(title, summary, text, limit=2)
                if not any(set(metrics_of(q)) & set(names) for q in p.get("queries") or [])]
    except G.GrafanaError:
        like = []
    if like:
        out["the team's Grafana shows this measure otherwise"] = [
            {k: v for k, v in p.items() if k in ("dashboard", "panel", "queries")} for p in like]
        out["note"] = ("the team's dashboards compute what may be the same measure with other metrics: if so, draft "
                       "again with their query (the same title replaces this draft), and say which you used")
    return out


def described(spec: dict[str, Any]) -> str:
    sign = ">" if spec.get("operator") == "gt" else "<"
    return (f"{spec.get('title')}: alert when {spec.get('query')} {sign} {spec.get('threshold')} for "
            f"{spec.get('for')}, labels {spec.get('labels')}, in folder {spec.get('folder_uid')}, group "
            f"{spec.get('rule_group')}")


def payload(spec: dict[str, Any]) -> dict[str, Any]:
    """alerting_rules_write's create arguments for a spec (query A, its last value B, the threshold C)."""
    return {"operation": "create", "rule_uid": spec["uid"], "title": spec["title"], "folder_uid": spec["folder_uid"],
            "rule_group": spec["rule_group"], "condition": "C", "for": spec["for"], "labels": spec["labels"],
            "annotations": spec["annotations"], "no_data_state": spec["no_data_state"],
            "exec_err_state": spec["exec_err_state"], "org_id": 1, "disable_provenance": True,
            "data": [{"refId": "A", "datasourceUid": spec["datasource"], "relativeTimeRange": {"from": 600, "to": 0},
                      "model": {"refId": "A", "expr": spec["query"], "instant": True}},
                     {"refId": "B", "datasourceUid": "__expr__",
                      "model": {"refId": "B", "type": "reduce", "expression": "A", "reducer": "last"}},
                     {"refId": "C", "datasourceUid": "__expr__",
                      "model": {"refId": "C", "type": "threshold", "expression": "B",
                                "conditions": [{"evaluator": {"type": spec["operator"],
                                                              "params": [spec["threshold"]]}}]}}]}


def _compare(spec: dict[str, Any], got: Any) -> list[str]:
    """What Grafana holds against the draft (the rule as read: flat, under "rule", its data under "configuration");
    a read-back that cannot be compared says so, never fails the approval made."""
    try:
        r = got.get("rule") if isinstance(got, dict) and isinstance(got.get("rule"), dict) else got
        r = r if isinstance(r, dict) else {}
        config = r.get("configuration") if isinstance(r.get("configuration"), dict) else r
        diffs = []
        for k, want in (("title", spec.get("title")), ("folder_uid", spec.get("folder_uid")),
                        ("rule_group", spec.get("rule_group")), ("condition", "C")):
            have = r.get(k) if r.get(k) is not None else config.get(k)
            if str(have) != str(want):
                diffs.append(f"{k}: {have!r} for {want!r}")
        labels = r.get("labels") if isinstance(r.get("labels"), dict) else {}
        for k, v in spec["labels"].items():
            if str(labels.get(k)) != str(v):
                diffs.append(f"label {k}: {labels.get(k)!r} for {v!r}")
        data = [d for d in (config.get("data") or r.get("data") or []) if isinstance(d, dict)]
        models = [d.get("model") if isinstance(d.get("model"), dict) else {} for d in data]
        if spec["query"] not in [m.get("expr") for m in models]:
            diffs.append("the query differs")
        evaluators = [((m.get("conditions") or [None])[0] or {}).get("evaluator") or {} for m in models
                      if m.get("type") == "threshold" and isinstance(m.get("conditions"), list)]
        ev = evaluators[0] if evaluators and isinstance(evaluators[0], dict) else {}
        try:
            first = [float(x) for x in (ev.get("params") or [])][:1]
        except (TypeError, ValueError):
            first = []
        if ev.get("type") != spec["operator"] or first != [spec["threshold"]]:
            diffs.append("the threshold differs")
        return diffs
    except Exception as ex:  # pylint: disable=broad-except   (the rule is made: say what could not be read)
        return [f"the rule read back could not be compared: {type(ex).__name__}"]


def approve(action_id: int, by: str, shown_hash: str | None = None) -> dict[str, Any]:
    """An admin's approval: checked again, created in Grafana, read back (see the module). `shown_hash`: the spec's
    hash the admin was shown (To review sends it): another one is refused."""
    from superset import db

    from supagent import settings
    from supagent.models import GrafanaAction

    row = db.session.get(GrafanaAction, int(action_id))
    if row is None or row.status != "proposed":
        raise RuleError("no draft waiting for approval")
    if shown_hash is not None and shown_hash != row.spec_hash:
        raise RuleError("the draft is not the one shown: reload To review")
    if not settings.get("grafana.writes"):
        raise RuleError("creating alert rules and dashboards in Grafana is off (grafana.writes): the draft stays")
    spec = dict(row.spec or {})
    if _hash(spec) != row.spec_hash:
        raise RuleError("the draft changed after it was drafted: draft it again")
    if row.kind == "create_dashboard":                # (a dashboard: grafana_dashboards)
        from supagent import grafana_dashboards

        return grafana_dashboards.approve_row(row, by)
    if spec.get("folder_uid") != str(settings.get("grafana.alert_folder") or "").strip():
        raise RuleError("the folder of the settings changed since the draft: draft it again")
    existing = G.alert_rules(folder=spec["folder_uid"], limit=200, cached=False)
    if any(r.get("uid") == spec["uid"] or str(r.get("title") or "").lower() == spec["title"].lower()
           for r in existing):
        row.status, row.decided_by, row.decided_at = "failed", by, _now()
        row.result = {"error": "a rule of that UID or title is in the folder already"}
        db.session.commit()
        raise RuleError("a rule of that UID or title is in the folder already")
    try:
        G.call("alerting_rules_write", payload(spec))
    except G.GrafanaError as ex:
        row.status, row.decided_by, row.decided_at, row.result = "failed", by, _now(), {"error": str(ex)[:1500]}
        db.session.commit()
        raise RuleError(f"Grafana refused it: {ex}") from None
    try:                                              # made: a read-back that fails leaves it made, said so
        got = G.call("alerting_rules_read", {"operation": "get", "rule_uid": spec["uid"]}, cached=False)
        diffs = _compare(spec, got)
    except G.GrafanaError as ex:
        got, diffs = {}, [f"not read back: {str(ex)[:300]}"]
    got = got if isinstance(got, dict) else {}
    row.status, row.decided_by, row.decided_at = "created", by, _now()
    row.result = {"rule_uid": spec["uid"], "read back": {k: got.get(k) for k in
                                                         ("title", "folder_uid", "rule_group", "for", "labels")},
                  "differences": diffs}
    db.session.commit()
    return {"created": spec["uid"], "differences": diffs, "link": G.link(f"/alerting/grafana/{spec['uid']}/view")}


def reject(action_id: int, by: str, why: str = "") -> dict[str, Any]:
    from superset import db

    from supagent.models import GrafanaAction

    row = db.session.get(GrafanaAction, int(action_id))
    if row is None or row.status != "proposed":
        raise RuleError("no draft waiting for approval")
    row.status, row.decided_by, row.decided_at = "rejected", by, _now()
    row.result = {"why": G.said(why, 500)} if why else None
    db.session.commit()
    return {"rejected": row.id}


def pending(limit: int = 50) -> list[dict[str, Any]]:
    """The drafts waiting for an admin (To review)."""
    from superset import db

    from supagent.models import GrafanaAction

    from supagent import grafana_dashboards

    rows = db.session.query(GrafanaAction).filter(GrafanaAction.status == "proposed").order_by(
        GrafanaAction.id.desc()).limit(limit)
    return [{"id": r.id, "kind": r.kind or "create_rule", "title": r.title,
             "rule": (grafana_dashboards.described if r.kind == "create_dashboard" else described)(r.spec or {}),
             "spec": r.spec, "spec_hash": r.spec_hash, "source": r.source, "source_text": r.source_text,
             "preview": r.preview, "requested_by": r.requested_by, "requested_at": r.requested_at} for r in rows]
