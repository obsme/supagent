"""(0.10.10) Dashboards for Grafana, never written by the agent alone: a draft names an existing folder of Browse (by its
path, title or UID; two of a title: its path is asked; the settings' default or allowed folders), its panels are
checked (metrics the datasource has, Grafana's panel types and units, numbers), where it fits is given (the folders
whose dashboards are about the same things), and an admin's approval creates it as a new dashboard only (never a
patch, an overwrite, a dashboard outside a folder or of another UID) and reads it back. A question naming Grafana is
never offered Superset's dashboard makers. Invented names only."""
from __future__ import annotations

import pytest

from supagent import grafana as G

METRICS = {"zqx_requests_total", "zqx_errors_total", "zqx_latency_seconds_bucket", "zqx_cache_hits_total"}
FOLDERS = [{"uid": "zf1", "title": "Zqx services", "type": "dash-folder"},
           {"uid": "zf2", "title": "Payments", "type": "dash-folder", "folderUid": "zf1", "folderTitle": "Zqx services"},
           {"uid": "zf3", "title": "Zqx platform", "type": "dash-folder"},
           {"uid": "zf4", "title": "Payments", "type": "dash-folder"}]
BOARDS = [{"uid": "b1", "title": "Zqx checkout overview", "type": "dash-db", "folderUid": "zf1",
           "folderTitle": "Zqx services", "tags": ["checkout"]},
          {"uid": "b2", "title": "Zqx cache", "type": "dash-db", "folderUid": "zf3", "folderTitle": "Zqx platform"}]


@pytest.fixture()
def grafana(ctx, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.models import GrafanaAction

    conf = {"grafana.mcp_url": "http://mcp.invalid/mcp", "grafana.url": "https://grafana.invalid",
            "grafana.datasource": "prom1", "grafana.writes": True, "grafana.cache_seconds": 0,
            "grafana.dashboard_folder": "", "grafana.dashboard_folders": [], "grafana.alert_folder": "zf3"}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: conf[k] if k in conf else real(k))
    monkeypatch.setattr(G, "_setting", lambda k, d=None: conf.get(k, d))
    calls: list[tuple[str, dict]] = []
    made: dict[str, dict] = {}
    state = {"refuse_write": None}

    async def fake_call(url, headers, tool, args, timeout):
        calls.append((tool, args))
        if tool == "search_folders":
            return {"dashboards": FOLDERS}
        if tool == "search_dashboards":
            rows = BOARDS + [{"uid": u, "title": d["dashboard"]["title"], "type": "dash-db",
                              "folderUid": d["meta"]["folderUid"]} for u, d in made.items()]
            q, f = str(args.get("query") or "").lower(), args.get("folderUid")
            return [r for r in rows if (not q or q in r["title"].lower()) and (not f or r.get("folderUid") == f)]
        if tool == "list_datasources":
            return [{"uid": "prom1", "name": "Zqx metrics", "type": "prometheus"},
                    {"uid": "logs1", "name": "Zqx logs", "type": "loki"}]
        if tool == "list_prometheus_metric_names":
            name = args["regex"].strip("^$").replace("\\", "")
            return [name] if name in METRICS else []
        if tool == "get_dashboard_by_uid":
            if args["uid"] in made:
                return made[args["uid"]]
            raise G.GrafanaError("dashboard not found")
        if tool == "update_dashboard":
            if state["refuse_write"]:
                raise G.GrafanaError(state["refuse_write"])
            d = args["dashboard"]
            made[d["uid"]] = {"dashboard": d, "meta": {"folderUid": args["folderUid"]}}
            return {"status": "success", "uid": d["uid"]}
        raise AssertionError(f"unexpected tool {tool}")

    monkeypatch.setattr(G, "_call", fake_call)
    G._CACHE.clear()
    db.session.query(GrafanaAction).delete()
    db.session.commit()
    yield conf, calls, made, state
    db.session.query(GrafanaAction).delete()
    db.session.commit()
    G._CACHE.clear()


PANELS = [{"title": "Zqx checkout requests", "type": "time series", "queries": ["sum(rate(zqx_requests_total[5m]))"],
           "unit": "reqps"},
          {"title": "Zqx checkout error ratio", "type": "stat", "unit": "percentunit", "thresholds": [0.05, 0.02],
           "query": "sum(rate(zqx_errors_total[5m])) / sum(rate(zqx_requests_total[5m]))"}]


def _draft(**kw):
    from supagent import grafana_dashboards as D

    args = dict(title="Zqx checkout health", panels=PANELS, folder="Zqx services", source="chat",
                requested_by="admin")
    args.update(kw)
    return D.draft(**args)


def test_a_draft_is_checked_built_and_stored_nothing_written(grafana):
    from superset.extensions import db

    from supagent.models import GrafanaAction

    _conf, calls, made, _state = grafana
    out = _draft()
    row = db.session.get(GrafanaAction, out["drafted"])
    assert row.kind == "create_dashboard" and row.status == "proposed" and row.grafana_uid.startswith("sa-d-")
    d = row.spec["dashboard"]
    assert row.spec["folder_uid"] == "zf1" and row.spec["folder"] == "Zqx services" and d["uid"] == row.grafana_uid
    p1, p2 = d["panels"]
    assert p1["type"] == "timeseries" and p1["gridPos"] == {"x": 0, "y": 0, "w": 12, "h": 8}
    assert p1["targets"][0] == {"refId": "A", "expr": "sum(rate(zqx_requests_total[5m]))", "legendFormat": "__auto",
                                "datasource": {"type": "prometheus", "uid": "prom1"}}
    assert p2["gridPos"] == {"x": 12, "y": 0, "w": 6, "h": 5}
    assert p2["fieldConfig"]["defaults"]["thresholds"]["steps"] == [
        {"color": "green", "value": None}, {"color": "orange", "value": 0.02}, {"color": "red", "value": 0.05}]
    assert "supagent" in d["tags"] and d["time"] == {"from": "now-6h", "to": "now"}
    fits = out["preview"]["where it fits"]
    assert fits[0]["folder"] == "Zqx services" and "checkout" in fits[0]["shares"] and out["preview"]["fits best"]
    assert not made and not [c for c in calls if c[0] == "update_dashboard"]


def test_the_folder_by_path_title_or_uid(grafana):
    from supagent import grafana_dashboards as D
    from supagent.grafana_rules import RuleError

    conf, _calls, _made, _state = grafana
    assert D.resolve_folder("Zqx services / Payments")["uid"] == "zf2"
    assert D.resolve_folder("zqx services/payments")["uid"] == "zf2"
    assert D.resolve_folder("zf3")["path"] == "Zqx platform"
    with pytest.raises(RuleError, match="several folders are titled 'Payments'"):
        D.resolve_folder("Payments")
    with pytest.raises(RuleError, match="no Grafana folder 'Nowhere'"):
        D.resolve_folder("Nowhere")
    with pytest.raises(RuleError, match="which folder"):
        D.resolve_folder("")
    conf["grafana.dashboard_folder"] = "zf3"
    assert D.resolve_folder("")["uid"] == "zf3"                         # the settings' default
    conf["grafana.dashboard_folders"] = ["zf3"]
    with pytest.raises(RuleError, match="grafana.dashboard_folders"):
        D.resolve_folder("Zqx services")


def test_a_folder_other_than_where_it_fits_is_said(grafana):
    out = _draft(folder="Zqx platform")
    assert not out["preview"]["fits best"] and "Zqx services" in out["note"]


@pytest.mark.parametrize("kw,why", [
    ({"panels": [{"title": "Zqx refunds", "queries": ["sum(rate(zqx_refunds_total[5m]))"]}]}, "no metric zqx_refunds"),
    ({"panels": [{"title": "Zqx requests", "type": "radar", "queries": ["zqx_requests_total"]}]}, "the type 'radar'"),
    ({"panels": [{"title": "Zqx requests", "unit": "furlongs", "queries": ["zqx_requests_total"]}]}, "furlongs"),
    ({"panels": [{"title": "Zqx requests", "thresholds": ["high"], "queries": ["zqx_requests_total"]}]}, "numbers"),
    ({"panels": [{"title": "Zqx notes", "type": "text"}]}, "content"),
    ({"panels": [{"title": "Zqx requests", "queries": ["zqx_requests_total"]}] * 25}, "24 panels"),
    ({"panels": []}, "panels"),
    ({"datasource": "Zqx logs"}, "no Prometheus one"),
    ({"time_from": "yesterday"}, "time_from"),
    ({"title": "Zqx checkout overview"}, "has a dashboard titled"),        # a person's dashboard of that title
])
def test_what_a_draft_refuses(grafana, kw, why):
    from supagent.grafana_rules import RuleError

    with pytest.raises(RuleError, match=why):
        _draft(**kw)


def test_approval_creates_one_new_dashboard_and_reads_it_back(grafana):
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import GrafanaAction

    _conf, calls, made, _state = grafana
    out = _draft()
    done = R.approve(out["drafted"], "admin")
    writes = [a for t, a in calls if t == "update_dashboard"]
    assert len(writes) == 1 and writes[0]["overwrite"] is False and writes[0]["folderUid"] == "zf1"
    assert "uid" not in writes[0] and "operations" not in writes[0]
    assert done["created"] == out["dashboard_uid"] and done["differences"] == [] and done["folder"] == "Zqx services"
    assert list(made) == [out["dashboard_uid"]]
    assert db.session.get(GrafanaAction, out["drafted"]).status == "created"
    again = _draft()                                            # asked again: found, not made again
    assert again["already"] and not [d for d in db.session.query(GrafanaAction) if d.id != out["drafted"]]
    with pytest.raises(R.RuleError, match="no draft waiting"):
        R.approve(out["drafted"], "admin")


def test_a_refused_write_leaves_the_draft_failed(grafana):
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import GrafanaAction

    _conf, _calls, made, state = grafana
    out = _draft()
    state["refuse_write"] = "403 Forbidden: you do not have permission to save to this folder"
    with pytest.raises(R.RuleError, match="Grafana refused it: 403"):
        R.approve(out["drafted"], "admin")
    row = db.session.get(GrafanaAction, out["drafted"])
    assert row.status == "failed" and "403" in row.result["error"] and not made


def test_a_person_s_dashboard_of_that_title_made_meanwhile_stops_the_approval(grafana):
    from supagent import grafana_rules as R

    _conf, calls, made, _state = grafana
    out = _draft(title="Zqx checkout latency")
    BOARDS.append({"uid": "b9", "title": "Zqx checkout latency", "type": "dash-db", "folderUid": "zf1"})
    try:
        with pytest.raises(R.RuleError, match="has a dashboard titled"):
            R.approve(out["drafted"], "admin")
    finally:
        BOARDS.pop()
    assert not made and not [c for c in calls if c[0] == "update_dashboard"]


@pytest.mark.parametrize("args", [
    {"uid": "b1", "operations": [{"op": "remove", "path": "$.panels[0]"}]},                       # a patch
    {"dashboard": {"uid": "sa-d-x", "title": "t"}, "folderUid": "zf1", "overwrite": True},         # an overwrite
    {"dashboard": {"uid": "sa-d-x", "title": "t"}, "overwrite": False},                            # no folder
    {"dashboard": {"uid": "b1", "title": "t"}, "folderUid": "zf1", "overwrite": False},            # another's UID
    {"dashboard": {"uid": "sa-d-x", "id": 7, "title": "t"}, "folderUid": "zf1", "overwrite": False},
])
def test_no_change_of_an_existing_dashboard_goes_through(grafana, args):
    _conf, calls, _made, _state = grafana
    with pytest.raises(G.GrafanaError, match="only a new dashboard"):
        G.call("update_dashboard", args)
    assert calls == []


def test_the_draft_tool_for_editors_and_admins(grafana):
    from supagent import tools_grafana as T
    from supagent.security import acting_as

    with acting_as("alice"):
        out = T.grafana_draft_dashboard(title="Zqx checkout health", panels=PANELS, folder="Zqx services")
    assert isinstance(out, str) and out.startswith("tool error: only an admin or an editor")
    with acting_as("admin"):
        out = T.grafana_draft_dashboard(title="Zqx checkout health", panels=PANELS, folder="Zqx services")
        folders = T.grafana_folders()
    assert out["drafted"]
    paths = {f["path"]: f["dashboards"] for f in folders["folders"]}
    assert paths["Zqx services / Payments"] == [] and paths["Zqx services"] == ["Zqx checkout overview [checkout]"]


def test_a_dashboard_in_grafana_is_never_one_of_supersets(monkeypatch):
    from supagent.agent import INTENT_TOOLS, Agent

    a = object.__new__(Agent)
    a.rich, a.wants_saved_chart = True, False
    a.specs = [{"type": "function", "function": {"name": n}} for n in sorted(INTENT_TOOLS)]
    monkeypatch.setattr(Agent, "_route_intents", lambda self: set())

    def offered(q):
        return {s["function"]["name"] for s in a._specs_for(q)}

    grafana = offered("Create a dashboard in Grafana of the zqx checkout latency")
    assert "grafana_draft_dashboard" in grafana and "grafana_folders" in grafana
    assert not grafana & {"generate_dashboard", "add_chart_to_existing_dashboard"}
    superset = offered("Create a dashboard of the zqx checkout latency")
    assert "generate_dashboard" in superset and "grafana_draft_dashboard" not in superset
    assert "generate_dashboard" in offered("Make a Superset dashboard like the Grafana one of the zqx checkout")



def test_superset_dashboards_stay_offered_when_grafana_is_not(monkeypatch):
    from supagent.agent import INTENT_TOOLS, Agent

    a = object.__new__(Agent)
    a.rich, a.wants_saved_chart = True, False
    a.specs = [{"type": "function", "function": {"name": n}} for n in sorted(INTENT_TOOLS)
               if not n.startswith("grafana_")]                                  # no Grafana set up
    monkeypatch.setattr(Agent, "_route_intents", lambda self: set())
    offered = {s["function"]["name"] for s in a._specs_for("Create a dashboard of the alerts firing per zqx service")}
    assert "generate_dashboard" in offered
    offered = {s["function"]["name"] for s in a._specs_for("Create a dashboard in Grafana of the zqx alerts")}
    assert "generate_dashboard" in offered                                      # Grafana named, but not set up


TEAM_BOARD = {"dashboard": {"uid": "b1", "title": "Zqx checkout overview", "panels": [
    {"id": 1, "type": "timeseries", "title": "Checkout requests per second",
     "datasource": {"type": "prometheus", "uid": "prom1"},
     "targets": [{"refId": "A", "expr": 'sum(rate(zqx_requests_total{service="zqx-checkout"}[5m]))'}]}]},
    "meta": {"folderUid": "zf1"}}
RULES = [{"uid": "r1", "title": "Zqx checkout traffic gone", "folder_uid": "zf3", "state": "normal",
          "configuration": {"data": [{"refId": "A", "datasourceUid": "prom1",
                                      "model": {"expr": "sum(rate(zqx_requests_total[5m])) < 1"}}]}},
         {"uid": "r2", "title": "Zqx cache cold", "folder_uid": "zf3", "state": "normal",
          "configuration": {"data": [{"refId": "A", "datasourceUid": "prom1",
                                      "model": {"expr": "sum(rate(zqx_cache_hits_total[5m])) < 1"}}]}}]


@pytest.fixture()
def team(grafana, monkeypatch):
    """The fixture's Grafana with a team dashboard read whole and two alert rules."""
    real = G._call

    async def fake_call(url, headers, tool, args, timeout):
        if tool == "get_dashboard_by_uid" and args["uid"] == "b1":
            return TEAM_BOARD
        if tool == "alerting_rules_read":
            if args["operation"] == "get":
                return next(r for r in RULES if r["uid"] == args["rule_uid"])
            return [{k: v for k, v in r.items() if k != "configuration"} for r in RULES]
        return await real(url, headers, tool, args, timeout)

    async def fake_batch(url, headers, items, timeout, concurrency):
        out = []
        for t, a in items:
            try:
                out.append(await fake_call(url, headers, t, a, timeout))
            except G.GrafanaError as ex:
                out.append(ex)
        return out

    monkeypatch.setattr(G, "_call", fake_call)
    monkeypatch.setattr(G, "_call_batch", fake_batch)
    G._CACHE.clear()
    return grafana


def test_a_corrected_dashboard_draft_replaces_the_first_of_its_title_and_folder(grafana):
    """(0.10.10, gq1d D02) The agent drafted the same dashboard twice in one turn, corrected: one draft, the newer."""
    from superset.extensions import db

    from supagent.models import GrafanaAction

    first = _draft()
    second = _draft(panels=[PANELS[0]])
    assert second["drafted"] == first["drafted"] and second["replaced"].startswith("the earlier draft")
    assert db.session.query(GrafanaAction).count() == 1
    assert len(db.session.get(GrafanaAction, first["drafted"]).spec["dashboard"]["panels"]) == 1
    other = _draft(folder="Zqx platform")                                  # another folder: another draft
    assert other["drafted"] != first["drafted"] and db.session.query(GrafanaAction).count() == 2


def test_the_folder_where_such_dashboards_are_is_said_even_when_the_user_chose_another(grafana):
    """(0.10.10, gq1d D09) The user names a folder; the dashboards about the same things are elsewhere: said."""
    out = _draft(folder="Zqx platform")
    assert "are in 'Zqx services', not in 'Zqx platform'" in out["note"] and "tell the user" in out["note"]


def test_the_team_s_panel_of_the_same_measure_is_named_when_the_draft_reads_another_metric(team):
    out = _draft(title="Zqx checkout requests per second", panels=[
        {"title": "Checkout requests per second", "type": "timeseries", "queries": ["sum(rate(zqx_cache_hits_total[5m]))"]}])
    like = out["the team's Grafana shows these measures otherwise"]
    assert like[0]["panel"] == "Checkout requests per second" and "zqx_requests_total" in like[0]["queries"][0]
    assert "draft again with their queries" in out["note"]
    same = _draft(title="Zqx checkout rps", panels=[
        {"title": "Checkout requests per second", "type": "timeseries",
         "queries": ['sum(rate(zqx_requests_total{service="zqx-checkout"}[5m]))']}])
    assert "the team's Grafana shows these measures otherwise" not in same


def test_which_panels_and_alert_rules_read_a_metric(team):
    """(0.10.10, gq1 R09) "Which panels or alert rules read metric X": every panel and rule of that metric."""
    from supagent import tools_grafana as T
    from supagent.security import acting_as

    out = G.uses("zqx_requests_total")
    assert [p["panel"] for p in out["panels"]] == ["Checkout requests per second"]
    assert [r["title"] for r in out["alert rules"]] == ["Zqx checkout traffic gone"]
    assert G.uses("zqx_latency_seconds_count")["count"] == {"panels": 0, "alert rules": 0}
    with pytest.raises(G.GrafanaError, match="metric's name"):
        G.uses("zqx requests; drop")
    with acting_as("admin"):
        assert T.grafana_metric_uses("zqx_cache_hits_total")["alert rules"][0]["title"] == "Zqx cache cold"


def test_a_panel_query_prometheus_cannot_parse_is_refused(grafana, monkeypatch):
    """(0.10.10, gq1d D09) A panel's query written like SQL ("SUM(rate(x)) GROUP BY 1") was drafted: a dashboard of
    a panel in error. The query is run once; Prometheus' own reason refuses it, with how to write it."""
    from superset.extensions import db

    from supagent import grafana_dashboards as D
    from supagent.models import GrafanaAction
    from test_grafana_rules_01010 import _picky

    _picky(monkeypatch)
    bad = [{"title": "Zqx requests per second", "type": "timeseries",
            "queries": ["SUM(rate(zqx_requests_total[5m])) GROUP BY 1"]}]
    with pytest.raises(D.RuleError, match="panel 'Zqx requests per second'.*not valid PromQL"):
        _draft(panels=bad)
    assert db.session.query(GrafanaAction).count() == 0

