"""(0.10.10, the team's request of 14 October: "the agent can create a dashboard and visualisation in Grafana as well and
put it in the right folder in Browse") Dashboards for Grafana, never written by the agent alone, as the alert rules
are (grafana_rules):

1. a draft (grafana_draft_dashboard, users who may edit the team's knowledge): a title, the folder it goes to in
   Browse (one that exists, by its UID, its title or its path "Parent / Child"; one of grafana.dashboard_folders when
   that is set; none named: grafana.dashboard_folder), its panels (a type, PromQL queries, a unit, thresholds), a
   description and tags. Checked: every metric every query reads exists in the datasource (none is guessed), the
   panel types and units are Grafana's, at most 24 panels of 6 queries each, the folder has no dashboard of that
   title. The folders whose dashboards are about the same things are given with the draft (where it fits): the
   folder is never chosen silently, the draft names it. Stored for an admin in To review with its UID (from its
   source and its content: asked twice, the first draft is found, not made again).
2. approval (an admin, grafana.writes on, the spec unchanged): checked again (the folder is there, no dashboard of
   that UID or title in it), created with update_dashboard as a new dashboard only (overwrite false, never a patch of
   an existing one: grafana.call refuses anything else), read back and compared.

A new dashboard only: an existing one (anyone's) is never changed, no folder is created."""
from __future__ import annotations

import datetime as dt

import hashlib
import json
import math
import re
from typing import Any

from supagent import grafana as G
from supagent.grafana_rules import TITLE_OK, RuleError, _hash, _known_metric, _now, _source, metrics_of

PANEL_TYPES = frozenset({"timeseries", "stat", "gauge", "bargauge", "table", "piechart", "barchart", "heatmap",
                         "histogram", "text"})
TYPE_WORDS = {"time series": "timeseries", "graph": "timeseries", "line": "timeseries", "lines": "timeseries",
              "single stat": "stat", "singlestat": "stat", "number": "stat", "bar": "barchart",
              "bar chart": "barchart", "bars": "barchart", "pie": "piechart", "pie chart": "piechart",
              "bar gauge": "bargauge"}
UNITS = frozenset("""none short percent percentunit s ms us ns m h d dtdurations bytes decbytes bits decbits bps Bps
binBps KBs MBs reqps rps wps rpm ops opm iops cps hertz celsius fahrenheit watt kwatt volt amp currencyUSD currencyEUR
sci""".split())
COLORS = ("orange", "red", "dark-red", "purple")
MAX_PANELS = 24
MAX_QUERIES = 6
WIDE = {"timeseries", "barchart", "heatmap", "histogram", "table", "piechart", "text"}
STOP = frozenset("""the and for per with from into over under total sum count rate seconds second bytes ratio share
dashboard panel grafana metrics metric value values by of in on to a an is are""".split())


def _metrics(expr: str) -> list[str]:
    from supagent.grafana_rules import metrics_of

    return metrics_of(expr)


def _datasource(ref: str) -> str:
    """A Prometheus datasource's UID: the one named (its UID or name), else the settings' one."""
    from supagent.grafana_rules import _datasource as default

    ref = str(ref or "").strip()
    if not ref:
        return default()
    rows = G.call("list_datasources", {})
    rows = rows if isinstance(rows, list) else (rows.get("datasources") if isinstance(rows, dict) else None) or []
    for r in rows:
        if isinstance(r, dict) and ref in (str(r.get("uid")), str(r.get("name"))):
            if "prometheus" not in str(r.get("type") or "").lower():
                raise RuleError(f"the datasource {ref!r} is no Prometheus one: the panels' queries are PromQL")
            return str(r.get("uid"))
    raise RuleError(f"no datasource {ref!r} in Grafana")


def resolve_folder(ref: str) -> dict[str, str]:
    """A folder by its UID, its title or its path ("Parent / Child"); RuleError when none or several match."""
    from supagent import settings

    ref = " ".join(str(ref or "").split())
    if not ref:
        ref = str(settings.get("grafana.dashboard_folder") or "").strip()
        if not ref:
            raise RuleError("which folder of Grafana does the dashboard go to? (grafana_folders lists them with "
                            "their dashboards: the one whose dashboards are about the same thing)")
    every = G.folders(cached=False)
    low = re.sub(r"\s*/\s*", "/", ref.lower().strip(" /"))
    hits = [f for f in every if f["uid"] == ref] or [      # by its path or its title: a name two folders have
        f for f in every if re.sub(r"\s*/\s*", "/", f["path"].lower()) == low or f["title"].lower() == low]
    if not hits:
        raise RuleError(f"no Grafana folder {ref!r}: " + "; ".join(f["path"] for f in every[:30]))
    if len(hits) > 1:
        raise RuleError(f"several folders are titled {ref!r}: " + "; ".join(f["path"] for f in hits) +
                        " (name it by its path)")
    allowed = {str(x).strip() for x in (settings.get("grafana.dashboard_folders") or []) if str(x).strip()}
    if allowed and hits[0]["uid"] not in allowed:
        raise RuleError(f"the folder {hits[0]['path']!r} is not one the agent's dashboards may go to "
                        "(grafana.dashboard_folders)")
    return hits[0]


def _words(*texts: Any) -> set[str]:
    """The meaningful words of texts, as compared: CamelCase and letters-digits split (Checkout5xxShareHigh: checkout
    5xx share high), a plural's s dropped (errors: error)."""
    out: set[str] = set()
    for t in texts:
        t = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Za-z])(?=[0-9])", " ", str(t or ""))
        for w in re.split(r"[^a-z0-9]+", t.lower()):
            if len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
                w = w[:-1]
            if len(w) >= 3 and w not in STOP and not w.isdigit():
                out.add(w)
    return out


def where_it_fits(words: set[str], limit: int = 3) -> list[dict[str, Any]]:
    """The folders whose dashboards (titles, tags) and own title share the most words with a dashboard's: (path,
    uid, the words, the dashboards that have them), best first."""
    from supagent.knowledge.grafana_pages import _all_dashboards

    try:
        boards, _ = _all_dashboards(1000)
        every = {f["uid"]: f for f in G.folders()}
    except G.GrafanaError:
        return []
    score: dict[str, float] = {}
    why: dict[str, set[str]] = {}
    which: dict[str, list[str]] = {}
    for uid, f in every.items():
        shared = words & _words(f["title"])
        if shared:
            score[uid] = score.get(uid, 0) + 2 * len(shared)
            why.setdefault(uid, set()).update(shared)
    for b in boards:
        uid = str(b.get("folderUid") or "")
        if uid not in every:
            continue
        shared = words & (_words(b.get("title")) | _words(*(b.get("tags") or [])))
        if shared:
            score[uid] = score.get(uid, 0) + 2 * len(shared)
            why.setdefault(uid, set()).update(shared)
            which.setdefault(uid, []).append(str(b.get("title")))
    best = sorted(score, key=lambda u: (-score[u], every[u]["path"]))[:limit]
    return [{"folder": every[u]["path"], "uid": u, "shares": sorted(why[u]),
             "its dashboards": which.get(u, [])[:5]} for u in best]


def _panel(p: Any, i: int, ds: str) -> dict[str, Any]:
    if not isinstance(p, dict):
        raise RuleError(f"panel {i}: an object with a title, a type and its queries")
    title = " ".join(str(p.get("title") or "").split())
    if not TITLE_OK.fullmatch(title):
        raise RuleError(f"panel {i}: a title of 3 to 190 characters")
    kind = " ".join(str(p.get("type") or "timeseries").lower().split())
    kind = TYPE_WORDS.get(kind, kind)
    if kind not in PANEL_TYPES:
        raise RuleError(f"panel {title!r}: the type {kind!r} is none of " + ", ".join(sorted(PANEL_TYPES)))
    out: dict[str, Any] = {"title": title, "type": kind}
    if kind == "text":
        content = str(p.get("content") or p.get("description") or "").strip()
        if not content or len(content) > 2000:
            raise RuleError(f"panel {title!r}: a text panel's content, 2000 characters at most")
        out["content"] = content
        return out
    queries = p.get("queries") if p.get("queries") is not None else [p.get("query")]
    queries = [" ".join(str(q or "").split()) for q in (queries if isinstance(queries, list) else [queries])]
    queries = [q for q in queries if q]
    if not queries or len(queries) > MAX_QUERIES:
        raise RuleError(f"panel {title!r}: 1 to {MAX_QUERIES} PromQL queries")
    names: list[str] = []
    for q in queries:
        if len(q) > 2000:
            raise RuleError(f"panel {title!r}: a query of 2000 characters at most")
        found = metrics_of(q)
        if not found:
            raise RuleError(f"panel {title!r}: the query {q!r} reads no metric")
        names += [n for n in found if n not in names]
    unknown = [n for n in names if not _known_metric(ds, n)]
    if unknown:
        raise RuleError(f"panel {title!r}: the datasource has no metric {', '.join(unknown)}: find the right one in "
                        "the data dictionary (never guess a metric)")
    from supagent.grafana_rules import PROMQL_HINT, promql_problem

    for q in queries:                                 # (0.10.10, gq1d D09) a query Prometheus cannot parse: refused
        bad = promql_problem(ds, q)
        if bad:
            raise RuleError(f"panel {title!r}: the query {q!r} is not valid PromQL ({bad}): {PROMQL_HINT}")
    out["queries"] = queries
    legends = p.get("legends") or p.get("legend") or []
    legends = legends if isinstance(legends, list) else [legends]
    legends = [str(x or "")[:100] for x in legends][:len(queries)]
    if any(legends):
        out["legends"] = legends + [""] * (len(queries) - len(legends))
    unit = str(p.get("unit") or "").strip()
    if unit:
        if unit not in UNITS:
            raise RuleError(f"panel {title!r}: the unit {unit!r} is none of Grafana's: " + ", ".join(sorted(UNITS)))
        out["unit"] = unit
    steps = p.get("thresholds") or []
    steps = steps if isinstance(steps, list) else [steps]
    try:
        values = [float(x) for x in steps]
    except (TypeError, ValueError):
        raise RuleError(f"panel {title!r}: thresholds are numbers") from None
    if any(not math.isfinite(v) for v in values) or len(values) > len(COLORS):
        raise RuleError(f"panel {title!r}: at most {len(COLORS)} finite thresholds")
    if values:
        out["thresholds"] = sorted(values)
    desc = G.said(p.get("description"), 300)
    if desc:
        out["description"] = desc
    out["metrics"] = names
    return out


def build(uid: str, title: str, description: str, tags: list[str], time_from: str, ds: str,
          panels: list[dict[str, Any]]) -> dict[str, Any]:
    """The dashboard's JSON (classic, version 1 of the schema: every Grafana reads it), laid out two by two (a stat or a
    gauge a quarter wide)."""
    out_panels = []
    x = y = row_h = 0
    for i, p in enumerate(panels, start=1):
        w, h = (24, 4) if p["type"] == "text" else (12, 8) if p["type"] in WIDE else (6, 5)
        if x + w > 24:
            x, y, row_h = 0, y + row_h, 0
        panel: dict[str, Any] = {"id": i, "type": p["type"], "title": p["title"],
                                 "gridPos": {"x": x, "y": y, "w": w, "h": h}}
        x, row_h = x + w, max(row_h, h)
        if p.get("description"):
            panel["description"] = p["description"]
        if p["type"] == "text":
            panel["options"] = {"mode": "markdown", "content": p["content"]}
        else:
            source = {"type": "prometheus", "uid": ds}
            defaults: dict[str, Any] = {}
            if p.get("unit"):
                defaults["unit"] = p["unit"]
            if p.get("thresholds"):
                defaults["thresholds"] = {"mode": "absolute", "steps": [{"color": "green", "value": None}] + [
                    {"color": COLORS[k], "value": v} for k, v in enumerate(p["thresholds"])]}
            legends = p.get("legends") or [""] * len(p["queries"])
            panel.update({"datasource": source, "fieldConfig": {"defaults": defaults, "overrides": []},
                          "options": {},
                          "targets": [{"refId": chr(ord("A") + k), "expr": q, "datasource": source,
                                       "legendFormat": legends[k] or "__auto"} for k, q in enumerate(p["queries"])]})
        out_panels.append(panel)
    return {"uid": uid, "title": title, "description": description, "tags": tags, "schemaVersion": 41,
            "editable": True, "time": {"from": time_from, "to": "now"}, "timezone": "browser",
            "annotations": {"list": []}, "templating": {"list": []}, "panels": out_panels}


def draft(*, title: str, panels: list[Any], folder: str = "", description: str = "", tags: Any = None,
          time_from: str = "now-6h", datasource: str = "", source: str = "chat", requested_by: str = "") -> dict:
    """Check and store a dashboard's draft (see the module); the existing draft or dashboard when asked before."""
    from superset import db

    from supagent.models import GrafanaAction

    title = " ".join(str(title or "").split())
    if not TITLE_OK.fullmatch(title):
        raise RuleError("a title of 3 to 190 characters, no brackets")
    if not isinstance(panels, list) or not panels:
        raise RuleError("the dashboard's panels: a list of objects (title, type, queries, unit, thresholds)")
    if len(panels) > MAX_PANELS:
        raise RuleError(f"{MAX_PANELS} panels at most")
    if not re.fullmatch(r"now-\d{1,4}[mhdwMy]", str(time_from or "now-6h").strip()):
        raise RuleError("time_from: like now-6h, now-24h or now-7d")
    tags = tags if isinstance(tags, list) else ([tags] if tags else [])
    tags = [t for t in (re.sub(r"[^\w .:/-]", "", str(x)).strip()[:40] for x in tags) if t][:8]
    if "supagent" not in tags:
        tags.append("supagent")
    where = resolve_folder(folder)
    ds = _datasource(datasource)
    parsed = [_panel(p, i, ds) for i, p in enumerate(panels, start=1)]
    ref, text = _source(source)
    body = [{k: v for k, v in p.items() if k != "metrics"} for p in parsed]
    seed = (f"{ref}\n{' '.join(text.lower().split())}\n" + json.dumps(sorted(q for p in body for q in p.get("queries")
                                                                            or []))) \
        if ref != "chat" else json.dumps([title.lower(), where["uid"], body], sort_keys=True, default=str)
    uid = G.DASHBOARD_UID + hashlib.sha256(seed.encode()).hexdigest()[:20]
    before = db.session.query(GrafanaAction).filter(GrafanaAction.grafana_uid == uid).order_by(
        GrafanaAction.id.desc()).first()
    if before is not None and before.status in ("proposed", "created"):
        return {"already": "drafted, waiting for an admin's approval" if before.status == "proposed" else
                "created in Grafana", "draft": before.id, "dashboard_uid": uid, "title": before.title}
    try:
        G.call("get_dashboard_by_uid", {"uid": uid}, cached=False)
        return {"already": "in Grafana", "dashboard_uid": uid, "link": G.link(f"/d/{uid}")}
    except G.GrafanaError:
        pass
    same = [d for d in G.dashboards(query=title, folder=where["uid"], limit=50, cached=False, everything=True)
            if str(d.get("title") or "").lower() == title.lower()]
    if same:
        raise RuleError(f"the folder {where['path']!r} has a dashboard titled {title!r} already "
                        f"(UID {same[0].get('uid')}): another title, or that dashboard")
    names = sorted({n for p in parsed for n in p.get("metrics") or []})
    labels = [v for p in parsed for q in p.get("queries") or [] for _k, _op, v in
              re.findall(r'([A-Za-z_]\w*)\s*(=~|!~|!=|=)\s*"([^"]*)"', q)]
    fits = where_it_fits(_words(title, *(p["title"] for p in parsed), *(n.replace("_", " ") for n in names),
                                *labels))
    dashboard = build(uid, title, G.said(description, 500) or "", tags, str(time_from).strip(), ds, parsed)
    spec = {"uid": uid, "title": title, "folder_uid": where["uid"], "folder": where["path"], "datasource": ds,
            "dashboard": dashboard}
    preview = {"folder": where["path"], "panels": [
        {k: v for k, v in {"title": p["title"], "type": p["type"], "unit": p.get("unit"),
                           "thresholds": p.get("thresholds"), "queries": p.get("queries")}.items() if v}
        for p in parsed], "metrics": names, "where it fits": fits,
        "fits best": bool(fits) and fits[0]["uid"] == where["uid"]}
    prior = next((w for w in db.session.query(GrafanaAction).filter(
        GrafanaAction.kind == "create_dashboard", GrafanaAction.status == "proposed")
        if str(w.title or "").lower() == title.lower() and (w.spec or {}).get("folder_uid") == where["uid"]), None)
    if prior is not None:                     # (0.10.10) a draft of that title in that folder corrected: replaced
        row = prior
        row.grafana_uid, row.spec, row.spec_hash, row.preview = uid, spec, _hash(spec), preview
        row.source, row.source_text, row.requested_by = ref, text[:4000] or None, requested_by or None
        row.requested_at = dt.datetime.utcnow()
    else:
        row = GrafanaAction(kind="create_dashboard", status="proposed", title=title, grafana_uid=uid, spec=spec,
                            spec_hash=_hash(spec), source=ref, source_text=text[:4000] or None, preview=preview,
                            requested_by=requested_by or None)
        db.session.add(row)
    db.session.commit()
    out = {"drafted": row.id, "dashboard_uid": uid, "dashboard": described(spec), "preview": preview,
           "next": "an admin approves it in Data dictionary -> To review; Grafana has nothing until then"}
    if prior is not None:
        out["replaced"] = "the earlier draft of that title in that folder (not approved yet): one draft, the newer one"
    notes = []
    if fits and not preview["fits best"]:     # (0.10.10) said even when the user chose the folder
        notes.append(f"the dashboards about the same things are in {fits[0]['folder']!r}, not in {where['path']!r}: "
                     "tell the user (they may prefer it there)")
    try:
        like = []
        for p in parsed:
            for q in G.similar_panels(title, p["title"], limit=2):
                if not any(set(_metrics(x)) & set(p.get("metrics") or []) for x in q.get("queries") or []) and \
                        q not in like:
                    like.append({k: v for k, v in q.items() if k in ("dashboard", "panel", "queries")})
    except G.GrafanaError:
        like = []
    if like:
        out["the team's Grafana shows these measures otherwise"] = like[:3]
        notes.append("the team's dashboards compute what may be the same measure with other metrics: if so, draft "
                     "again with their queries (the same title and folder replace this draft), and say which you used")
    if notes:
        out["note"] = " ".join(notes)
    return out


def described(spec: dict[str, Any]) -> str:
    panels = (spec.get("dashboard") or {}).get("panels") or []
    return (f"{spec.get('title')}: a dashboard of {len(panels)} panel{'s' if len(panels) != 1 else ''} "
            f"({', '.join(str(p.get('title')) for p in panels[:8])}) in the folder {spec.get('folder')}")


def _compare(spec: dict[str, Any], got: Any) -> list[str]:
    diffs = []
    meta = got.get("meta") if isinstance(got, dict) and isinstance(got.get("meta"), dict) else {}
    d = G.condense(got, folders={})
    if str(d.get("title")) != spec["title"]:
        diffs.append(f"title {d.get('title')!r}")
    if str(meta.get("folderUid") or "") != spec["folder_uid"]:
        diffs.append(f"folder {meta.get('folderUid')!r}")
    want = (spec.get("dashboard") or {}).get("panels") or []
    have = d.get("panels") or []
    if len(have) != len(want):
        diffs.append(f"{len(have)} panels for {len(want)}")
    for w, h in zip(want, have):
        if str(h.get("title")) != w["title"] or str(h.get("type")) != w["type"]:
            diffs.append(f"panel {w['title']!r}: {h.get('title')!r} ({h.get('type')})")
        exprs = [q.get("query") for q in h.get("queries") or []]
        for t in w.get("targets") or []:
            if t["expr"] not in exprs:
                diffs.append(f"panel {w['title']!r}: the query {t['expr']!r} differs")
    return diffs


def approve_row(row: Any, by: str) -> dict[str, Any]:
    """An admin's approval of a dashboard's draft (grafana_rules.approve checked it is waiting, writes are on and its
    spec unchanged): checked again, created, read back."""
    from superset import db

    spec = dict(row.spec or {})

    def fail(why: str) -> RuleError:
        row.status, row.decided_by, row.decided_at = "failed", by, _now()
        row.result = {"error": why[:1500]}
        db.session.commit()
        return RuleError(why)

    try:
        here = resolve_folder(spec["folder_uid"])
    except RuleError as ex:
        raise fail(f"the folder: {ex}") from None
    try:
        G.call("get_dashboard_by_uid", {"uid": spec["uid"]}, cached=False)
        raise fail("a dashboard of that UID is in Grafana already")
    except G.GrafanaError:
        pass
    same = [d for d in G.dashboards(query=spec["title"], folder=here["uid"], limit=50, cached=False, everything=True)
            if str(d.get("title") or "").lower() == spec["title"].lower()]
    if same:
        raise fail(f"the folder has a dashboard titled {spec['title']!r} already (UID {same[0].get('uid')})")
    try:
        G.call("update_dashboard", {"dashboard": spec["dashboard"], "folderUid": here["uid"], "overwrite": False,
                                    "message": f"created by supagent, approved by {by}"})
    except G.GrafanaError as ex:
        raise fail(f"Grafana refused it: {ex}") from None
    try:                                              # made: a read-back that fails leaves it made, said so
        diffs = _compare(spec, G.call("get_dashboard_by_uid", {"uid": spec["uid"]}, cached=False))
    except G.GrafanaError as ex:
        diffs = [f"not read back: {str(ex)[:300]}"]
    except Exception as ex:  # pylint: disable=broad-except
        diffs = [f"the dashboard read back could not be compared: {type(ex).__name__}"]
    row.status, row.decided_by, row.decided_at = "created", by, _now()
    row.result = {"dashboard_uid": spec["uid"], "folder": here["path"], "differences": diffs}
    db.session.commit()
    return {"created": spec["uid"], "folder": here["path"], "differences": diffs, "link": G.link(f"/d/{spec['uid']}")}
