"""(0.10.10, the team's request of 14 October: "use the MCP server of our central Grafana to check dashboards,
visualizations, rules and alerts, understand the dashboards and visualizations, build a Context from them like the
Superset dashboards, and set up alert rules from the rules we put in the catalog or in memory") Grafana through its
MCP server (mcp-grafana, streamable HTTP; grafana.mcp_url).

* Only the tools named here are ever called: READ_TOOLS, and alerting_rules_write with operation create only, from
  an admin's approval (grafana_rules). What else the server offers (an arbitrary API request, dashboard, datasource,
  folder, plugin and contact point writes, silences, deletes) is never reached through supagent, whatever a question
  or a text read in Grafana says. The server itself is best run with --disable-write wherever it only needs to read.
* What the agent reads is condensed here: a dashboard's panels (those inside collapsed rows too) with their queries,
  units and thresholds; a rule's condition, labels, state and who is notified; never the raw JSON. Every text written
  in Grafana (titles, descriptions, annotations) is given as what Grafana says, quoted: data, never instructions.
* Reads are cached grafana.cache_seconds per caller's credentials; a write empties the cache.
* Who may use it: the agent's users with one of grafana.roles (empty: every user of the agent); the server's
  credentials are the same for all of them (a service account), or each user's when grafana.user_tokens says so."""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import json
import logging
import re
import threading
import time
from typing import Any

log = logging.getLogger(__name__)

READ_TOOLS = frozenset({"search_dashboards", "get_dashboard_by_uid", "get_dashboard_summary",
                        "get_dashboard_panel_queries", "list_datasources", "alerting_rules_read",
                        "alerting_manage_routing", "search_folders", "query_prometheus",
                        "list_prometheus_metric_names", "list_prometheus_label_values", "generate_deeplink",
                        "list_dashboard_versions"})
WRITE_TOOLS = frozenset({"alerting_rules_write", "update_dashboard"})
WRITE_OPERATIONS = frozenset({"create"})          # never update, delete: a person does that in Grafana
DASHBOARD_UID = "sa-d-"                            # the UIDs of the dashboards supagent creates
TEXT_CHARS = 600                                  # of a description or an annotation given to the agent
_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, Any]] = {}


class GrafanaError(RuntimeError):
    """What the MCP server or Grafana answered when a call failed (said to the user as it is)."""


def _setting(key: str, default: Any = None) -> Any:
    try:
        from supagent import settings

        value = settings.get(key)
    except Exception:  # pylint: disable=broad-except   (no application, no settings table yet)
        return default
    return default if value in (None, "") else value


NO_MCP_PACKAGE = ("the Python package mcp is not installed where Superset runs: pip install \"mcp>=1.20,<2\" (or "
                  "supagent[grafana]); Grafana's MCP server is read through it")


def configured() -> bool:
    return bool(str(_setting("grafana.mcp_url", "") or "").strip())


def check() -> dict[str, Any]:
    """(0.10.11) The Settings page's test: the MCP server answers and reaches Grafana (its datasources), and
    grafana.datasource is one of them. {"ok": ..., "said": ...}; never raises."""
    try:
        got = call("list_datasources", {}, cached=False)
    except GrafanaError as ex:
        return {"ok": False, "said": str(ex)}
    rows = got if isinstance(got, list) else (got.get("datasources") or []) if isinstance(got, dict) else []
    rows = [r for r in rows if isinstance(r, dict)]
    said = f"Grafana answers through its MCP server: {len(rows)} datasource{'' if len(rows) == 1 else 's'}"
    ds = str(_setting("grafana.datasource", "") or "").strip()
    if not ds:
        return {"ok": True, "said": said + "; set grafana.datasource (the UID of the Prometheus or Mimir datasource "
                                           "of the rules and panels)"}
    one = next((r for r in rows if ds in (str(r.get("uid") or ""), str(r.get("name") or ""))), None)
    if one is None:
        return {"ok": False, "said": said + f"; grafana.datasource {ds!r} is none of them (UIDs: "
                                            f"{', '.join(str(r.get('uid')) for r in rows[:10])})"}
    return {"ok": True, "said": said + f"; grafana.datasource is {one.get('name')} ({one.get('type')})"}


def allowed(user: Any = None) -> bool:
    """Whether this Superset user may read Grafana through the agent (grafana.roles; empty: every user)."""
    roles = {str(r).strip() for r in (_setting("grafana.roles", []) or []) if str(r).strip()}
    if not roles:
        return True
    names = {getattr(r, "name", "") for r in (getattr(user, "roles", None) or [])}
    return bool(names & roles)


def _headers() -> dict[str, str]:
    out: dict[str, str] = {}
    token = str(_setting("grafana.mcp_token", "") or "").strip()
    if token:
        out["Authorization"] = f"Bearer {token}"
    grafana_token = str(_setting("grafana.grafana_token", "") or "").strip()
    if grafana_token:                         # (streamable HTTP only: the server uses it for this request)
        out["X-Grafana-Service-Account-Token"] = grafana_token
    return out


def _run(coro: Any, timeout: float) -> Any:
    """An async call from a web or worker thread (a loop of its own, in a thread of its own); the caller waits
    `timeout` seconds at most (the call itself is bounded by grafana.timeout: its thread ends soon after)."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(asyncio.run, coro).result(timeout=timeout)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _decode(tool: str, res: Any) -> Any:
    texts = [getattr(c, "text", "") or "" for c in (res.content or [])]
    body = "\n".join(t for t in texts if t)
    if res.isError:
        raise GrafanaError(body[:1500] or f"{tool} failed")
    try:
        return json.loads(body) if body.strip()[:1] in ("{", "[") else body
    except ValueError:
        return body


async def _call(url: str, headers: dict[str, str], tool: str, args: dict[str, Any], timeout: float) -> Any:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async with streamablehttp_client(url, headers=headers, timeout=timeout, sse_read_timeout=timeout) as (read, write,
                                                                                                       _sid):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout)
            res = await asyncio.wait_for(session.call_tool(tool, args), timeout)
    return _decode(tool, res)


async def _call_batch(url: str, headers: dict[str, str], items: list[tuple[str, dict[str, Any]]], timeout: float,
                      concurrency: int) -> list[Any]:
    """Several calls on one session, `concurrency` at a time; a failed one gives its GrafanaError (not raised)."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    gate = asyncio.Semaphore(max(1, concurrency))
    async with streamablehttp_client(url, headers=headers, timeout=timeout, sse_read_timeout=timeout) as (read, write,
                                                                                                       _sid):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout)

            async def one(tool: str, args: dict[str, Any]) -> Any:
                async with gate:
                    try:
                        return _decode(tool, await asyncio.wait_for(session.call_tool(tool, args), timeout))
                    except GrafanaError as ex:
                        return ex
                    except Exception as ex:  # pylint: disable=broad-except
                        return GrafanaError(f"{tool}: {type(ex).__name__}: {str(ex)[:300]}")

            return list(await asyncio.gather(*(one(t, a) for t, a in items)))


def call(tool: str, args: dict[str, Any] | None = None, *, cached: bool = True) -> Any:
    """One MCP tool of the allowed ones (GrafanaError on a refusal or a failure)."""
    args = dict(args or {})
    if tool == "alerting_rules_write" and str(args.get("operation")) not in WRITE_OPERATIONS:
        raise GrafanaError(f"{tool} {args.get('operation')!r}: not done through supagent")
    if tool == "update_dashboard":                # a new dashboard of supagent's only, in a folder: never a patch,
        d = args.get("dashboard")                 # an overwrite or another dashboard
        args.pop("userId", None)
        if ("uid" in args or "operations" in args or args.get("overwrite") is not False or not isinstance(d, dict)
                or not str(d.get("uid") or "").startswith(DASHBOARD_UID) or "id" in d or "version" in d
                or not str(args.get("folderUid") or "").strip()):
            raise GrafanaError("update_dashboard: only a new dashboard of supagent's, in a folder, is created through "
                               "supagent (never a change of an existing one)")
    if tool in WRITE_TOOLS:
        cached = False
    elif tool not in READ_TOOLS:
        raise GrafanaError(f"{tool}: not a tool supagent calls")
    url = str(_setting("grafana.mcp_url", "") or "").strip()
    if not url:
        raise GrafanaError("no Grafana MCP server is set (grafana.mcp_url)")
    headers = _headers()
    key = hashlib.sha256(json.dumps([url, sorted(headers.items()), tool, args], sort_keys=True, default=str)
                         .encode()).hexdigest()
    ttl = float(_setting("grafana.cache_seconds", 60) or 0)
    if cached and ttl > 0:
        with _LOCK:
            hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    timeout = float(_setting("grafana.timeout", 20) or 20)
    try:
        out = _run(_call(url, headers, tool, args, timeout), timeout + 5)
    except GrafanaError:
        raise
    except ImportError as ex:                     # (0.10.10) said as what to install, not as a server not answering
        raise GrafanaError(NO_MCP_PACKAGE) from ex
    except Exception as ex:  # pylint: disable=broad-except
        raise GrafanaError(f"the Grafana MCP server did not answer {tool}: {type(ex).__name__}: {str(ex)[:300]}")
    if tool in WRITE_TOOLS:
        with _LOCK:
            _CACHE.clear()
    elif cached and ttl > 0:
        with _LOCK:
            if len(_CACHE) > 2000:
                _CACHE.clear()
            _CACHE[key] = (time.time(), out)
    return out


def call_many(items: list[tuple[str, dict[str, Any]]], concurrency: int = 4) -> list[Any]:
    """Several reads (the nightly Context build: every dashboard, every rule) on one MCP session, `concurrency` at a
    time, cached as call() caches; each result in order, a GrafanaError (not raised) for a call that failed. Reads
    only: a write goes through call()."""
    for tool, _args in items:
        if tool not in READ_TOOLS:
            raise GrafanaError(f"{tool}: not a tool supagent reads with")
    url = str(_setting("grafana.mcp_url", "") or "").strip()
    if not url:
        raise GrafanaError("no Grafana MCP server is set (grafana.mcp_url)")
    headers = _headers()
    ttl = float(_setting("grafana.cache_seconds", 60) or 0)
    keys = [hashlib.sha256(json.dumps([url, sorted(headers.items()), t, dict(a or {})], sort_keys=True, default=str)
                           .encode()).hexdigest() for t, a in items]
    out: list[Any] = [None] * len(items)
    todo = []
    now = time.time()
    with _LOCK:
        for i, k in enumerate(keys):
            hit = _CACHE.get(k) if ttl > 0 else None
            if hit and now - hit[0] < ttl:
                out[i] = hit[1]
            else:
                todo.append(i)
    if todo:
        timeout = float(_setting("grafana.timeout", 20) or 20)
        waves = -(-len(todo) // max(1, concurrency))
        try:
            got = _run(_call_batch(url, headers, [(items[i][0], dict(items[i][1] or {})) for i in todo], timeout,
                                   concurrency), timeout * waves + 10)
        except Exception as ex:  # pylint: disable=broad-except   (the session itself failed: every call did)
            got = [GrafanaError(f"the Grafana MCP server did not answer: {type(ex).__name__}: {str(ex)[:300]}")] * len(todo)
        with _LOCK:
            for i, res in zip(todo, got):
                out[i] = res
                if ttl > 0 and not isinstance(res, GrafanaError):
                    if len(_CACHE) > 2000:
                        _CACHE.clear()
                    _CACHE[keys[i]] = (time.time(), res)
    return out


# --------------------------------------------------------------------------------------------------------------- #
# what the agent reads, condensed
# --------------------------------------------------------------------------------------------------------------- #

def said(text: Any, chars: int = TEXT_CHARS) -> str | None:
    """A text written in Grafana, given as data: one line, cut, None when empty."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    return t if len(t) <= chars else t[:chars].rsplit(" ", 1)[0] + " ..."


def link(path: str | None) -> str | None:
    base = str(_setting("grafana.url", "") or "").rstrip("/")
    if not path:
        return None
    return path if path.startswith("http") or not base else base + "/" + path.lstrip("/")


def dashboards(query: str = "", tag: str = "", folder: str = "", limit: int = 30,
               cached: bool = True, everything: bool = False) -> list[dict[str, Any]]:
    """Dashboards whose title has the words of `query` (Grafana's search), with a tag, in a folder (its UID or its
    title); `cached` False: as Grafana has them now (before a write). (0.10.10) Those the agent reads (dashlist);
    `everything`: every one (the checks that keep Grafana safe: a duplicate title, a folder)."""
    from supagent import dashlist

    r = None if everything else dashlist.reading("grafana")
    args: dict[str, Any] = {"limit": max(1, min(int(limit or 30), 100))}
    if query:
        args["query"] = query
    if tag:
        args["tag"] = [tag]
    if folder:
        args["folderUid"] = _folder_uid(folder)
    raw = call("search_dashboards", args, cached=cached)
    rows = raw.get("dashboards") if isinstance(raw, dict) else raw
    out = []
    for d in rows or []:
        if not isinstance(d, dict) or d.get("type") not in (None, "dash-db"):
            continue
        if r is not None and not r.dashboard(d.get("uid")):
            continue                                      # not read (deactivated in Documents and sites)
        out.append({k: v for k, v in {
            "uid": d.get("uid"), "title": d.get("title"), "folder": d.get("folderTitle") or d.get("folderUid"),
            "tags": d.get("tags") or None, "description (as written in Grafana)": said(d.get("description"), 300),
            "link": link(d.get("url"))}.items() if v})
    return out


def _folder_uid(folder: str) -> str:
    """A folder's UID from its UID or its title (as given when no folder matches)."""
    f = str(folder or "").strip()
    if not f:
        return f
    try:
        raw = call("search_folders", {"query": f})
    except GrafanaError:
        return f
    rows = raw if isinstance(raw, list) else ((raw.get("folders") or raw.get("dashboards")) if isinstance(raw, dict)
                                              else None) or []
    for r in rows:
        if isinstance(r, dict) and (r.get("uid") == f or str(r.get("title") or "").lower() == f.lower()):
            return str(r.get("uid") or f)
    return f


def _thresholds(fc: dict[str, Any]) -> list[str]:
    steps = (((fc.get("defaults") or {}).get("thresholds") or {}).get("steps")) or []
    out = []
    for s in steps:
        if isinstance(s, dict) and s.get("value") is not None:
            out.append(f"{s.get('color')} from {s.get('value')}")
    return out


def _panels(panels: list[Any], row: str | None = None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in panels or []:
        if not isinstance(p, dict):
            continue
        if p.get("type") == "row":
            out += _panels(p.get("panels") or [], row=str(p.get("title") or "") or None)
            continue
        fc = p.get("fieldConfig") or {}
        ds = p.get("datasource") if isinstance(p.get("datasource"), dict) else {}
        queries = []
        for t in p.get("targets") or []:
            if not isinstance(t, dict) or t.get("hide"):
                continue
            q = t.get("expr") or t.get("query") or t.get("rawSql") or t.get("expression") or t.get("stringInput")
            tds = t.get("datasource") if isinstance(t.get("datasource"), dict) else ds
            if q or t.get("scenarioId"):
                queries.append({k: v for k, v in {
                    "query": str(q or t.get("scenarioId"))[:1500], "datasource": (tds or {}).get("uid"),
                    "kind": (tds or {}).get("type"), "legend": t.get("legendFormat")}.items() if v})
        out.append({k: v for k, v in {
            "id": p.get("id"), "title": p.get("title"), "type": p.get("type"), "row": row,
            "description (as written in Grafana)": said(p.get("description"), 300),
            "unit": (fc.get("defaults") or {}).get("unit"), "thresholds": _thresholds(fc) or None,
            "queries": queries or None}.items() if v not in (None, "", [])})
    return out


def folders(cached: bool = True) -> list[dict[str, str]]:
    """Every folder: its UID, title, parent's UID and path ("Parent / Child"), by path (one search)."""
    raw = call("search_folders", {"query": ""}, cached=cached)
    rows = raw if isinstance(raw, list) else ((raw.get("folders") or raw.get("dashboards")) if isinstance(raw, dict)
                                              else None) or []
    rows = [r for r in rows if isinstance(r, dict) and r.get("uid") and r.get("type") in (None, "dash-folder")]
    by_uid = {str(r["uid"]): r for r in rows}

    def path(uid: str, depth: int = 0) -> str:
        r = by_uid.get(uid) or {}
        parent = str(r.get("folderUid") or "")
        mine = str(r.get("title") or uid)
        return (path(parent, depth + 1) + " / " + mine) if parent and parent in by_uid and depth < 8 else mine

    out = [{"uid": u, "title": str(r.get("title") or ""), "parent": str(r.get("folderUid") or ""), "path": path(u)}
           for u, r in by_uid.items()]
    return sorted(out, key=lambda f: f["path"].lower())


def folder_titles() -> dict[str, str]:
    """Every folder's title by its UID (one search, cached; empty when Grafana does not answer)."""
    try:
        return {f["uid"]: f["title"] for f in folders()}
    except GrafanaError:
        return {}


def condense(raw: Any, folders: dict[str, str] | None = None) -> dict[str, Any]:
    """A dashboard as the agent reads it (get_dashboard_by_uid's answer); `folders`: the folders' titles by UID
    (read when not given: a dashboard's answer names its folder by UID only)."""
    d = raw.get("dashboard") if isinstance(raw, dict) and isinstance(raw.get("dashboard"), dict) else raw
    meta = raw.get("meta") if isinstance(raw, dict) and isinstance(raw.get("meta"), dict) else {}
    if not isinstance(d, dict):
        return {}
    folder = meta.get("folderTitle")
    if not folder and meta.get("folderUid"):
        folder = (folder_titles() if folders is None else folders).get(str(meta["folderUid"])) or meta["folderUid"]
    variables = []
    for v in ((d.get("templating") or {}).get("list") or []):
        if isinstance(v, dict):
            q = v.get("query")
            q = q.get("query") if isinstance(q, dict) else q
            variables.append({k: x for k, x in {"name": v.get("name"), "type": v.get("type"),
                                                 "query": str(q)[:300] if q else None}.items() if x})
    panels = _panels(d.get("panels") or [])
    if not panels and isinstance(d.get("elements"), dict):        # a dashboard of schema v2
        panels = _panels_v2(d)
    return {k: v for k, v in {
        "uid": d.get("uid"), "title": d.get("title"), "folder": folder,
        "tags": d.get("tags") or None, "description (as written in Grafana)": said(d.get("description")),
        "variables": variables or None, "panels": panels,
        "link": link(meta.get("url") or (f"/d/{d['uid']}" if d.get("uid") else None)),
        "version": d.get("version"), "updated": meta.get("updated"),
        "updated_by": meta.get("updatedBy")}.items() if v not in (None, "", [])}


def _panels_v2(d: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for key, el in (d.get("elements") or {}).items():
        spec = (el or {}).get("spec") or {}
        queries = []
        for q in (((spec.get("data") or {}).get("spec") or {}).get("queries") or []):
            qs = ((q or {}).get("spec") or {}).get("query") or {}
            body = (qs.get("spec") or {}) if isinstance(qs, dict) else {}
            expr = body.get("expr") or body.get("query") or body.get("rawSql")
            if expr:
                queries.append({"query": str(expr)[:1500], "datasource": ((qs.get("datasource") or {}).get("name")),
                                "kind": qs.get("group")})
        viz = (spec.get("vizConfig") or {})
        out.append({k: v for k, v in {"id": spec.get("id") or key, "title": spec.get("title"),
                                      "type": viz.get("group") or viz.get("kind"),
                                      "description (as written in Grafana)": said(spec.get("description"), 300),
                                      "queries": queries or None}.items() if v not in (None, "", [])})
    return out


def dashboard(ref: str) -> dict[str, Any]:
    """One dashboard by its UID or its title (the one search finds of that title); (0.10.10) one the agent reads,
    without its panels not read (dashlist)."""
    from supagent import dashlist

    ref = str(ref or "").strip()
    if not ref:
        raise GrafanaError("which dashboard? (its title or its UID)")
    r = dashlist.reading("grafana")
    raw = None
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,40}", ref):
        if not r.dashboard(ref) and ref in r.flags:
            raise GrafanaError("this dashboard is not read by the agent (deactivated in Documents and sites): say so")
        try:
            raw = call("get_dashboard_by_uid", {"uid": ref})
        except GrafanaError:
            raw = None
    if not raw:
        every = dashboards(query=ref, limit=10, everything=True)
        found = [d for d in every if r.dashboard(d.get("uid"))]
        exact = [d for d in found if str(d.get("title") or "").lower() == ref.lower()]
        pick = exact or found
        if not pick and every:                            # (0.10.10) there, but switched off: said so
            raise GrafanaError("this dashboard is not read by the agent (deactivated in Documents and sites): say so")
        if not pick:
            raise GrafanaError(f"no Grafana dashboard titled {ref!r}")
        if len(pick) > 1 and not exact:
            return {"several dashboards match": [{"uid": d.get("uid"), "title": d.get("title"),
                                                  "folder": d.get("folder")} for d in pick[:10]]}
        raw = call("get_dashboard_by_uid", {"uid": pick[0]["uid"]})
    d = condense(raw)
    if d.get("uid") and not r.dashboard(d["uid"]):
        raise GrafanaError("this dashboard is not read by the agent (deactivated in Documents and sites): say so")
    return dashlist.without_unread(d, r)


STATES = ("firing", "pending", "normal", "recovering", "nodata", "error")


def alert_rules(state: str = "", query: str = "", folder: str = "", labels: dict[str, str] | None = None,
                limit: int = 100, cached: bool = True) -> list[dict[str, Any]]:
    """Alert rules with their state; a state (firing, pending, normal, nodata, error), words of their titles, a
    folder, labels (team=x): only those. `cached` False: as Grafana has them now (before a write)."""
    args: dict[str, Any] = {"operation": "list", "limit_alerts": 5, "rule_limit": max(1, min(int(limit or 100), 200))}
    st = str(state or "").strip().lower()
    if st:
        args["states"] = [s for s in re.split(r"[\s,]+", st) if s in STATES] or [st]
    if query:
        args["search_rule_name"] = query
    if folder:
        args["folder_uid"] = _folder_uid(folder)
    if labels:
        sel = ", ".join(f'{k}="{v}"' for k, v in labels.items() if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(k)))
        if sel:
            args["label_selectors"] = ["{" + sel + "}"]
    raw = call("alerting_rules_read", args, cached=cached)
    rows = raw if isinstance(raw, list) else (raw.get("rules") if isinstance(raw, dict) else None) or []
    return [_rule_line(r) for r in rows if isinstance(r, dict)]


def _rule_line(r: dict[str, Any]) -> dict[str, Any]:
    ann = r.get("annotations") if isinstance(r.get("annotations"), dict) else {}
    alerts = []
    for a in (r.get("alerts") or [])[:5]:
        if isinstance(a, dict):
            alerts.append({k: v for k, v in {"state": a.get("state"), "since": a.get("activeAt") or a.get("active_at"),
                                             "labels": a.get("labels"), "value": a.get("value")}.items() if v})
    return {k: v for k, v in {
        "uid": r.get("uid"), "title": r.get("title"), "state": r.get("state"), "health": r.get("health"),
        "folder": r.get("folder_title") or r.get("folder_uid"), "group": r.get("rule_group"), "for": r.get("for"),
        "labels": r.get("labels") or None, "summary (as written in Grafana)": said(ann.get("summary"), 300),
        "description (as written in Grafana)": said(ann.get("description"), 300),
        "runbook": ann.get("runbook_url"), "last evaluation": r.get("last_evaluation"),
        "alerts": alerts or None}.items() if v not in (None, "", [])}


def alert_rule(uid: str) -> dict[str, Any]:
    """One alert rule read whole: its queries, condition, labels, state, and who is notified."""
    raw = call("alerting_rules_read", {"operation": "get", "rule_uid": str(uid or "").strip(), "limit_alerts": 20})
    r = raw.get("rule") if isinstance(raw, dict) and isinstance(raw.get("rule"), dict) else raw
    if not isinstance(r, dict):
        raise GrafanaError(f"no alert rule {uid!r}")
    out = _rule_line(r)
    config = r.get("configuration") if isinstance(r.get("configuration"), dict) else r
    data = config.get("data") or []
    out["queries"] = [q for q in (_rule_query(x) for x in data if isinstance(x, dict)) if q] or None
    out["condition"] = config.get("condition")
    out["when no data"] = config.get("no_data_state") or config.get("noDataState")
    labels = r.get("labels") if isinstance(r.get("labels"), dict) else {}
    try:
        out["notified"] = notified({**labels, "alertname": str(r.get("title") or "")})
    except GrafanaError:
        pass
    return {k: v for k, v in out.items() if v not in (None, "", [])}


def _rule_query(x: dict[str, Any]) -> dict[str, Any] | None:
    model = x.get("model") if isinstance(x.get("model"), dict) else {}
    ref = x.get("refId") or model.get("refId")
    if (x.get("datasourceUid") or x.get("datasource_uid")) == "__expr__":
        kind = model.get("type")
        conds = model.get("conditions") or []
        ev = (conds[0] or {}).get("evaluator", {}) if conds else {}
        text = f"{kind} of {model.get('expression')}" + (f": {ev.get('type')} {ev.get('params')}" if ev else "")
        return {"ref": ref, "expression": text}
    q = model.get("expr") or model.get("query") or model.get("stringInput")
    return {"ref": ref, "query": str(q)[:1500] if q else None,
            "datasource": x.get("datasourceUid") or x.get("datasource_uid")}


def routing() -> dict[str, Any]:
    """Who gets the alerts: the notification policies (matchers -> contact point) and the contact points."""
    tree = call("alerting_manage_routing", {"operation": "get_notification_policies"})
    points = call("alerting_manage_routing", {"operation": "get_contact_points"})
    rows = points if isinstance(points, list) else (points.get("contact_points") if isinstance(points, dict) else
                                                    None) or []
    return {"policies": _routes(tree), "contact points": [
        {k: v for k, v in {"name": p.get("name"), "type": p.get("type")}.items() if v}
        for p in rows if isinstance(p, dict)]}


def _routes(node: Any, depth: int = 0) -> list[dict[str, Any]]:
    if not isinstance(node, dict) or depth > 6:
        return []
    ms = node.get("object_matchers") or node.get("matchers") or []
    when = [" ".join(map(str, m)) if isinstance(m, list) else str(m) for m in ms]
    row = {"when": when or (["(everything else)"] if depth == 0 else []), "to": node.get("receiver"),
           "continue": True if node.get("continue") else None}
    out = [{k: v for k, v in row.items() if v}]
    for child in node.get("routes") or []:
        out += _routes(child, depth + 1)
    return out


def notified(labels: dict[str, str], tree: Any = None) -> list[str]:
    """The contact points an alert of these labels reaches, by the notification policy tree (first matching route
    at each level, "continue" going on; the default otherwise); `tree`: the tree read already."""
    if tree is None:
        tree = call("alerting_manage_routing", {"operation": "get_notification_policies"})
    out: list[str] = []

    def match(m: Any) -> bool:
        if isinstance(m, list) and len(m) == 3:
            k, op, v = (str(x) for x in m)
        else:
            mm = re.match(r'^\s*([\w.]+)\s*(=~|!~|!=|=)\s*"?(.*?)"?\s*$', str(m))
            if not mm:
                return False
            k, op, v = mm.groups()
        have = str(labels.get(k, ""))
        if op == "=":
            return have == v
        if op == "!=":
            return have != v
        try:
            hit = re.fullmatch(v, have) is not None
        except re.error:
            return False
        return hit if op == "=~" else not hit

    def walk(node: dict[str, Any], inherited: str | None) -> bool:
        receiver = node.get("receiver") or inherited
        matched_child = False
        for child in node.get("routes") or []:
            if not isinstance(child, dict):
                continue
            ms = child.get("object_matchers") or child.get("matchers") or []
            if all(match(m) for m in ms):
                walk(child, receiver)
                matched_child = True
                if not child.get("continue"):
                    break
        if not matched_child and receiver and receiver not in out:
            out.append(receiver)
        return True

    if isinstance(tree, dict):
        walk(tree, None)
    return out


# --------------------------------------------------------------------------------------------------------------- #
# (0.10.10) what the panels show: the observability of production and the investigations
# --------------------------------------------------------------------------------------------------------------- #
VARIABLE_DEFAULTS = (("$__rate_interval", "5m"), ("${__rate_interval}", "5m"), ("$__interval", "1m"),
                     ("${__interval}", "1m"), ("$__range", "1h"), ("${__range}", "1h"))
STEP = re.compile(r"^\s*(\S+) from (-?[0-9.]+(?:e[+-]?\d+)?)\s*$", re.I)


def series(raw: Any) -> list[dict[str, Any]]:
    """The series of an instant query's answer: [{"labels": {...}, "value": float}] (none: no data then)."""
    rows = raw.get("data") if isinstance(raw, dict) else raw
    if isinstance(rows, dict):                       # the Prometheus API's own shape
        rows = rows.get("result")
    out = []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict):
            continue
        v = r.get("value")
        try:
            num = float(v[1]) if isinstance(v, (list, tuple)) and len(v) > 1 else float(v)
        except (TypeError, ValueError):
            continue
        if num == num:                               # NaN left out
            out.append({"labels": r.get("metric") if isinstance(r.get("metric"), dict) else {}, "value": num})
    return out


def _evaluable(expr: str) -> str | None:
    """A panel's query as it can be run on its own: Grafana's interval variables at their usual values, a matcher on a
    dashboard variable as any value; None when a variable is left (it needs the dashboard's choice)."""
    q = str(expr or "")
    for var, value in VARIABLE_DEFAULTS:
        q = q.replace(var, value)
    q = re.sub(r'(=~?|!~|!=)\s*"(?:\$\{?\w+(?::\w+)?\}?|\[\[\w+\]\])"', '=~".*"', q)
    return None if "$" in q or "[[" in q else " ".join(q.split())


def _color(value: float, steps: list[str]) -> tuple[str | None, str | None]:
    """(the color a panel gives this value by its thresholds, the step reached: "red from 0.05"): below every step,
    the panel's base color (green); no thresholds: no color (the value only)."""
    if not steps:
        return None, None
    color, reached = "green (below its thresholds)", None
    for s in steps:
        m = STEP.match(str(s))
        if m and value >= float(m.group(2)):
            color, reached = m.group(1), str(s)
    return color, reached


IDENTITY_LABELS = frozenset({"service", "service_name", "exported_service", "job", "app", "application", "component",
                             "instance", "pod", "container", "host", "hostname", "node", "namespace", "deployment",
                             "cluster", "datname", "database", "db", "team", "k8s_app"})


def _about(subject: str, d: dict[str, Any], p: dict[str, Any]) -> int:
    """How well a panel is about a subject: the part its queries select (a service, job, pod, host... label: 2),
    else its titles and its dashboard's (1); a panel that selects another part is not about it (0)."""
    words = [w for w in re.split(r"[\s,;]+", str(subject or "").lower()) if len(w) >= 2]
    if not words:
        return 1
    parts = []
    for q in p.get("queries") or []:
        parts += [v.lower() for k, v in re.findall(r'([A-Za-z_]\w*)\s*=~?\s*"([^"]*)"', str(q.get("query") or ""))
                  if k.lower() in IDENTITY_LABELS]
    if parts:
        return 2 if all(any(w in v for v in parts) for w in words) else 0
    titles = " ".join(str(x or "") for x in (d.get("title"), p.get("title"), p.get("row"), d.get("folder"))).lower()
    return 1 if all(w in titles for w in words) else 0


def _at(at: str) -> str:
    """`now` (and now-2h) as the agent's clock says when it is fixed (agent.now: demos on old data), else as given."""
    import datetime as dt

    fixed = str(_setting("agent.now", "") or "").strip()
    m = re.fullmatch(r"now(?:-(\d{1,4})([smhdw]))?", at)
    if not fixed or not m:
        return at
    try:
        base = dt.datetime.fromisoformat(fixed).astimezone()
    except ValueError:
        return at
    unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days", "w": "weeks"}
    if m.group(1):
        base -= dt.timedelta(**{unit[m.group(2)]: int(m.group(1))})
    return base.isoformat(timespec="seconds")


def watch(subject: str = "", dashboard: str = "", at: str = "now", limit: int = 24) -> dict[str, Any]:
    """What the team's Grafana shows about a subject (the panels whose queries select it, or titled with it) or on
    one dashboard, at `at` (now, now-2h, an RFC3339 time): each panel's query run then, its value against the panel's
    thresholds (the color it shows), and the alert rules firing or pending about the subject (their state now)."""
    at = str(at or "now").strip()
    if not re.fullmatch(r"now(-\d{1,4}[smhdw])?|\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})",
                        at):
        raise GrafanaError("at: now, now-2h or a time like 2026-10-02T09:00:00Z")
    at = _at(at)
    if dashboard:
        one = dashboard_full(dashboard)
        if "several dashboards match" in one:
            return one                               # several of that title: listed, ask which
        boards = [one]
    else:
        from supagent.knowledge.grafana_pages import _all_dashboards

        from supagent import dashlist

        r = dashlist.reading("grafana")
        found, folders = _all_dashboards(5000)
        found = [b for b in found if r.dashboard(b.get("uid"))][:int(_setting("grafana.max_dashboards", 300) or 300)]
        raws = call_many([("get_dashboard_by_uid", {"uid": str(b["uid"])}) for b in found])
        boards = []
        for b, raw in zip(found, raws):
            if isinstance(raw, GrafanaError) or not raw:
                continue
            d = condense(raw, folders)
            d["folder"] = b.get("folderTitle") or d.get("folder")
            boards.append(dashlist.without_unread(d, r))   # (0.10.10) only what the agent reads
    picked = []
    for d in boards:
        for p in d.get("panels") or []:
            score = _about(subject, d, p) if not dashboard else 1
            if score and p.get("queries"):
                picked.append((score, d, p))
    picked.sort(key=lambda x: -x[0])
    default_ds = str(_setting("grafana.datasource", "") or "")
    todo, skipped = [], 0
    for _score, d, p in picked[:max(1, limit)]:
        for q in p.get("queries") or []:
            if q.get("kind") and "prometheus" not in str(q.get("kind")):
                continue
            expr = _evaluable(q.get("query"))
            ds = str(q.get("datasource") or default_ds)
            if expr is None or not ds or "$" in ds:
                skipped += 1
                continue
            todo.append((d, p, expr, ds))
    answers = call_many([("query_prometheus", {"datasourceUid": ds, "expr": expr, "endTime": at,
                                               "queryType": "instant"}) for _d, _p, expr, ds in todo])
    panels = []
    for (d, p, expr, _ds), raw in zip(todo, answers):
        row: dict[str, Any] = {"dashboard": d.get("title"), "panel": p.get("title"), "unit": p.get("unit"),
                               "query": expr, "link": d.get("link")}
        if isinstance(raw, GrafanaError):
            row["error"] = str(raw)[:200]
        else:
            got = series(raw)
            if not got:
                row["value"] = "no data then"
            else:
                top = sorted(got, key=lambda x: -x["value"])[:5]
                for s in top:
                    color, reached = _color(s["value"], p.get("thresholds") or [])
                    if color:
                        s.update(color=color, **({"threshold": reached} if reached else {}))
                row["series"] = top
                row["color"] = top[0].get("color")
        panels.append({k: v for k, v in row.items() if v not in (None, "", [])})
    rank = {"red": 0, "dark-red": 0, "orange": 1, "yellow": 2}
    panels.sort(key=lambda r: (rank.get(str(r.get("color")), 3), str(r.get("dashboard")), str(r.get("panel"))))
    alerts = []
    try:
        for r in alert_rules(state="firing,pending", limit=200):
            text = " ".join([str(r.get("title") or "")] + [str(v) for v in (r.get("labels") or {}).values()]).lower()
            if all(w in text for w in re.split(r"[\s,;]+", str(subject or "").lower()) if len(w) >= 2):
                alerts.append(r)
    except GrafanaError as ex:
        alerts = [{"error": str(ex)[:200]}]
    return {k: v for k, v in {
        "at": at, "subject": subject or None, "dashboard": dashboard or None, "panels": panels,
        "panels not run": (f"{skipped} quer{'ies' if skipped != 1 else 'y'} need the dashboard's variables or "
                           "another datasource") if skipped else None,
        "alerts firing or pending": alerts}.items() if v not in (None, "")}


METRIC_NAME = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]{0,200}")


def team_panels() -> list[dict[str, Any]]:
    """(0.10.10) Every panel of the dashboards the agent reads (dashlist), with its dashboard, folder, queries and
    link: what finds the panels of a measure or of a metric (one read of each dashboard, grafana.max_dashboards)."""
    from supagent import dashlist
    from supagent.knowledge.grafana_pages import _all_dashboards

    r = dashlist.reading("grafana")
    found, folders = _all_dashboards(5000)
    found = [b for b in found if r.dashboard(b.get("uid"))][:int(_setting("grafana.max_dashboards", 300) or 300)]
    raws = call_many([("get_dashboard_by_uid", {"uid": str(b["uid"])}) for b in found])
    out: list[dict[str, Any]] = []
    for b, raw in zip(found, raws):
        if isinstance(raw, GrafanaError) or not raw:
            continue
        d = dashlist.without_unread(condense(raw, folders), r)
        for p in d.get("panels") or []:
            out.append({k: v for k, v in {
                "dashboard": d.get("title"), "folder": b.get("folderTitle") or d.get("folder"),
                "panel": p.get("title"), "row": p.get("row"),
                "description (as written in Grafana)": p.get("description (as written in Grafana)"),
                "queries": [str(q.get("query")) for q in p.get("queries") or [] if q.get("query")],
                "link": d.get("link")}.items() if v not in (None, "", [])})
    return out


def similar_panels(*texts: Any, limit: int = 3) -> list[dict[str, Any]]:
    """(0.10.10) The panels of the team's dashboards whose titles share at least two meaningful words with these
    texts (a measure the team already shows), best first: their dashboard, title and queries."""
    from supagent.grafana_dashboards import _words

    want = _words(*texts)
    if len(want) < 2:
        return []
    scored = []
    for p in team_panels():
        common = want & _words(p.get("panel"), p.get("row"), p.get("description (as written in Grafana)"),
                               p.get("dashboard"))
        if len(common) >= 2 and p.get("queries"):
            scored.append((len(common), p, common))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("dashboard")), str(x[1].get("panel"))))
    return [{**p, "words in common": sorted(c)} for _n, p, c in scored[:max(1, limit)]]


def uses(metric: str, limit: int = 40) -> dict[str, Any]:
    """(0.10.10) The panels (of the dashboards the agent reads) and the alert rules whose queries read a metric (a
    histogram's _bucket, _count and _sum go together)."""
    from supagent.grafana_rules import metrics_of

    name = str(metric or "").strip()
    if not METRIC_NAME.fullmatch(name):
        raise GrafanaError("metric: a metric's name, as the data dictionary has it")
    names = {name}
    base = re.sub(r"_(bucket|count|sum)$", "", name)
    if base != name:
        names |= {base + "_bucket", base + "_count", base + "_sum"}
    panels = []
    for p in team_panels():
        hits = [q for q in p.get("queries") or [] if set(metrics_of(q)) & names]
        if hits:
            panels.append({**p, "queries": hits})
    listed = [r for r in alert_rules(limit=200) if r.get("uid")]
    full = call_many([("alerting_rules_read", {"operation": "get", "rule_uid": str(r["uid"]), "limit_alerts": 0})
                      for r in listed])
    rules = []
    for summary, raw in zip(listed, full):
        r = raw.get("rule") if isinstance(raw, dict) and isinstance(raw.get("rule"), dict) else raw
        if isinstance(r, GrafanaError) or not isinstance(r, dict):
            continue
        config = r.get("configuration") if isinstance(r.get("configuration"), dict) else r
        qs = [q.get("query") for q in (_rule_query(x) for x in config.get("data") or [] if isinstance(x, dict))
              if q and q.get("query")]
        hits = [q for q in qs if set(metrics_of(q)) & names]
        if hits:
            rules.append({k: v for k, v in {"title": summary.get("title"), "uid": summary.get("uid"),
                                            "folder": summary.get("folder"), "state": summary.get("state"),
                                            "queries": hits}.items() if v})
    return {"metric": name, "panels": panels[:limit], "alert rules": rules[:limit],
            "count": {"panels": len(panels), "alert rules": len(rules)}}


def dashboard_full(ref: str) -> dict[str, Any]:
    """dashboard() under another name (watch's argument `dashboard` hides it there)."""
    return dashboard(ref)
