"""(0.10.10, the team's request of 14 October: the dashboards and visualizations listed in Documents and sites, each
one read by the agent or not, all deactivated then a few activated, their last modified dates to choose from) The
list is recorded from Grafana's reading (dashboards, panels, folder, last modified, by whom); a dashboard switched off
has no page from then on (deleted at once, never waiting in To review), the agent's tools neither list nor read it,
its panels are not watched; a panel switched off leaves its dashboard's page; Deactivate all makes the new ones wait;
the checks that keep Grafana safe still see every dashboard; only an admin changes what is read. Invented names
only."""
from __future__ import annotations

import copy

import pytest

from supagent import grafana as G
from test_grafana_pages_01010 import BOARD, CONF, grafana  # noqa: F401  (the fixture: a fake MCP server)

OTHER = {"dashboard": {
    "uid": "zqx-old", "title": "Zqx old checks", "panels": [
        {"id": 3, "type": "stat", "title": "Zqx legacy queue", "datasource": {"type": "prometheus", "uid": "prom1"},
         "targets": [{"refId": "A", "expr": 'sum(zqx_queue_depth{service="zqx-legacy"})'}]}]},
    "meta": {"folderUid": "zqxf", "url": "/d/zqx-old/zqx-old", "updated": "2026-01-05T08:00:00Z",
             "updatedBy": "someone"}}


@pytest.fixture()
def two(grafana, monkeypatch):  # noqa: F811
    """The fake Grafana with a second dashboard; the list and its settings cleaned after."""
    from superset.extensions import db

    from supagent import settings
    from supagent.models import ContextPage, DashItem, Setting

    boards = {"zqx-shop": grafana["board"], "zqx-old": copy.deepcopy(OTHER)}
    real = G._call

    async def fake_call(url, headers, tool, args, timeout):
        if tool == "search_dashboards":
            rows = [{"uid": "zqxf", "title": "Zqx team", "type": "dash-folder"}]
            for uid, b in boards.items():
                rows.append({"uid": uid, "title": b["dashboard"]["title"], "type": "dash-db", "folderUid": "zqxf",
                             "folderTitle": "Zqx team", "url": f"/d/{uid}/x"})
            q = str(args.get("query") or "").lower()
            return [r for r in rows if not q or q in r["title"].lower() or r["type"] == "dash-folder"]
        if tool == "get_dashboard_by_uid":
            if args["uid"] not in boards:
                raise G.GrafanaError("not found")
            return boards[args["uid"]]
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
    grafana["boards"] = boards
    yield grafana
    db.session.query(DashItem).delete(synchronize_session=False)
    db.session.query(Setting).filter(Setting.key.in_(["grafana.read_new", "osd.read_new"])).delete(
        synchronize_session=False)
    db.session.query(ContextPage).filter(ContextPage.slug.like("grafana-%")).delete(synchronize_session=False)
    db.session.commit()
    settings.clear_cache() if hasattr(settings, "clear_cache") else None


def _rows(kind="dashboard", **kw):
    from supagent import dashlist

    return {r["ref"]: r for r in dashlist.rows("grafana", kind=kind, **kw)["rows"]}


def _item(ref):
    from superset.extensions import db

    from supagent.models import DashItem

    return db.session.query(DashItem).filter(DashItem.source == "grafana", DashItem.ref == ref).one()


def test_the_reading_records_the_list_with_its_dates(two):
    from supagent import dashlist
    from supagent.knowledge import grafana_pages as GP

    pages, _keep, stats = GP.pages()
    assert {p["slug"] for p in pages} >= {"grafana-dashboard-zqx-shop", "grafana-dashboard-zqx-old"}
    assert stats["list"]["new"] == 5                       # 2 dashboards, 3 panels (one inside a collapsed row)
    boards = _rows()
    assert boards["zqx-old"]["updated_at"] == "2026-01-05T08:00:00Z" and boards["zqx-old"]["updated_by"] == "someone"
    assert boards["zqx-shop"]["folder"] == "Zqx team" and boards["zqx-shop"]["children"] == 2
    assert list(boards) == ["zqx-shop", "zqx-old"]          # last modified first
    panels = _rows(kind="kids")
    assert panels["zqx-shop/5"]["title"] == "Zqx p95" and panels["zqx-shop/5"]["folder"] == "Latency"
    assert panels["zqx-shop/1"]["link"].endswith("viewPanel=1") and panels["zqx-shop/1"]["dashboard"] == "Zqx shop"
    s = dashlist.summary("grafana")
    assert (s["dashboards"], s["dashboards_read"], s["kids"], s["kids_read"]) == (2, 2, 3, 3)
    assert _rows(q="legacy", kind="kids").keys() == {"zqx-old/3"}


def test_a_dashboard_switched_off_leaves_at_once_and_is_hidden_from_the_tools(two):
    from superset.extensions import db

    from supagent import dashlist, settings
    from supagent.knowledge import grafana_pages as GP
    from supagent.models import ContextPage

    GP.refresh(llm=False)
    assert db.session.query(ContextPage).filter(ContextPage.slug == "grafana-dashboard-zqx-old").count() == 1
    real = settings.get
    try:
        settings.get = lambda k: True if k == "context.review" else real(k)      # review on: still deleted at once
        done = dashlist.set_active("grafana", [_item("zqx-old").id], False, "admin")
        assert done["off"] == ["zqx-old"] and done["changed"] == 1
        out = dashlist.pages_follow("grafana", done, dispatch=False)
        assert out["pages_removed"] == 1
        assert db.session.query(ContextPage).filter(ContextPage.slug == "grafana-dashboard-zqx-old").count() == 0
        GP.refresh(llm=False)                                                    # the next reading: no page again
        assert db.session.query(ContextPage).filter(ContextPage.slug == "grafana-dashboard-zqx-old").count() == 0
    finally:
        settings.get = real
    assert [d["uid"] for d in G.dashboards()] == ["zqx-shop"]                     # the agent's list
    assert {d["uid"] for d in G.dashboards(everything=True)} == {"zqx-shop", "zqx-old"}   # a draft's safety checks
    with pytest.raises(G.GrafanaError, match="not read by the agent"):
        G.dashboard("zqx-old")
    with pytest.raises(G.GrafanaError, match="not read by the agent"):
        G.dashboard("Zqx old checks")
    assert _rows()["zqx-old"]["read"] is False and _rows(state="unread").keys() == {"zqx-old"}
    assert not _rows(kind="kids")["zqx-old/3"]["read"]                           # its panel: not read either
    from supagent import tools_grafana as T
    from supagent.security import acting_as

    with acting_as("admin"):                       # (oq1 O5) "there is no dashboard titled ..." of one switched off
        asked = T.grafana_dashboards(query="Zqx old checks")
        assert asked["dashboards"] == [] and asked["not read by the agent"]["named by the question"] == ["Zqx old checks"]
        every = T.grafana_dashboards()
        assert every["not read by the agent"]["count"] == 1 and "named by the question" not in every["not read by the agent"]


def test_a_panel_switched_off_leaves_its_dashboard_page_and_the_watch(two):
    from supagent import dashlist
    from supagent.knowledge import grafana_pages as GP

    GP.pages()
    done = dashlist.set_active("grafana", [_item("zqx-shop/1").id], False, "admin")
    assert done["again"] == ["zqx-shop"] and done["off"] == []
    pages, _keep, _stats = GP.pages(only={"zqx-shop"})
    assert [p["slug"] for p in pages] == ["grafana-dashboard-zqx-shop"]          # that page alone, no rules
    text = pages[0]["content"]
    assert "Zqx p95" in text and "Zqx error ratio" not in text
    d = G.dashboard("zqx-shop")
    assert [p["title"] for p in d["panels"]] == ["Zqx p95"]
    assert d["panels not read (deactivated in Documents and sites)"] == 1


def test_deactivate_all_then_some_and_the_new_ones_wait(two):
    from supagent import dashlist
    from supagent.knowledge import grafana_pages as GP

    GP.pages()
    done = dashlist.set_all("grafana", False, "admin")
    assert sorted(done["off"]) == ["zqx-old", "zqx-shop"] and done["read_new"] is False
    assert not dashlist.read_new("grafana")
    dashlist.set_active("grafana", [_item("zqx-shop").id], True, "admin")
    two["boards"]["zqx-new"] = {"dashboard": {"uid": "zqx-new", "title": "Zqx new", "panels": []},
                                "meta": {"folderUid": "zqxf", "updated": "2026-10-14T09:00:00Z"}}
    pages, _keep, stats = GP.pages()
    assert {p["slug"] for p in pages if p["slug"].startswith("grafana-dashboard-")} == {"grafana-dashboard-zqx-shop"}
    assert _rows()["zqx-new"]["active"] is False and stats["not read (Documents and sites)"] == 2
    done = dashlist.set_matching("grafana", True, "admin", q="new")              # "Activate the 1 shown"
    assert done["items"] == 1 and done["again"] == ["zqx-new"]
    dashlist.set_all("grafana", True, "admin")
    assert dashlist.read_new("grafana") and all(r["active"] for r in _rows().values())


def test_a_dashboard_gone_keeps_its_flag_and_a_failed_read_marks_nothing_gone(two):
    from supagent import dashlist
    from supagent.knowledge import grafana_pages as GP

    GP.pages()
    dashlist.set_active("grafana", [_item("zqx-old").id], False, "admin")
    gone = two["boards"].pop("zqx-old")
    GP.pages()
    assert "zqx-old" not in _rows() and dashlist.summary("grafana")["gone"] == 2   # the dashboard and its panel
    two["boards"]["zqx-old"] = gone
    GP.pages()
    assert _rows()["zqx-old"]["active"] is False                                   # back: still off
    two["fail"].add(("get_dashboard_by_uid", "zqx-shop"))
    GP.pages()
    assert {"zqx-shop/1", "zqx-shop/5"} <= set(_rows(kind="kids"))                 # its panels not marked gone


def test_the_watch_runs_only_the_panels_read(two, monkeypatch):
    from supagent import dashlist
    from supagent.knowledge import grafana_pages as GP

    GP.pages()
    dashlist.set_active("grafana", [_item("zqx-shop/1").id], False, "admin")
    asked = []
    real = G._call

    async def fake_call(url, headers, tool, args, timeout):
        if tool == "query_prometheus":
            asked.append(args["expr"])
            return {"data": []}
        if tool == "alerting_rules_read":
            return []
        return await real(url, headers, tool, args, timeout)

    async def fake_batch(url, headers, items, timeout, concurrency):
        return [await fake_call(url, headers, t, a, timeout) for t, a in items]

    monkeypatch.setattr(G, "_call", fake_call)
    monkeypatch.setattr(G, "_call_batch", fake_batch)
    monkeypatch.setattr(G, "_setting", lambda k, d=None: {**CONF, "grafana.datasource": "prom1"}.get(k, d))
    out = G.watch(subject="zqx")
    assert asked and not any("zqx_requests_total" in e for e in asked)          # the error ratio panel: off
    assert {p["panel"] for p in out["panels"]} <= {"Zqx p95", "Zqx legacy queue"}


def test_only_an_admin_changes_what_is_read(two):
    from conftest import login
    from flask import current_app

    from supagent.knowledge import grafana_pages as GP

    GP.pages()
    item = _item("zqx-old")
    with current_app.app_context():             # a g of each user's own (the test's open context would be reused)
        c = current_app.test_client()
        login(c, "alice")
        r = c.post("/supagent/admin/api/dashlist/grafana/set", json={"ids": [item.id], "active": False})
        assert r.status_code in (401, 403)
    with current_app.app_context():
        c = current_app.test_client()
        login(c, "admin")
        listed = c.get("/supagent/admin/api/dashlist").get_json()
        g_src = next(x for x in listed["sources"] if x["source"] == "grafana")
        assert listed["can_change"] and g_src["dashboards"] == 2 and g_src["kid"] == "panels"
        rows = c.get("/supagent/admin/api/dashlist/grafana?sort=title").get_json()["rows"]
        assert [x["title"] for x in rows] == ["Zqx old checks", "Zqx shop"]
        kids = c.get("/supagent/admin/api/dashlist/grafana/children?ref=zqx-shop").get_json()["rows"]
        assert {k["title"] for k in kids} == {"Zqx error ratio", "Zqx p95"}
        r = c.post("/supagent/admin/api/dashlist/grafana/set", json={"ids": [item.id], "active": False})
        assert r.status_code == 200 and r.get_json()["off"] == ["zqx-old"], r.get_data(as_text=True)[:300]
        assert c.post("/supagent/admin/api/dashlist/grafana/all", json={"active": "no"}).status_code == 400
        assert c.post("/supagent/admin/api/dashlist/nowhere/all", json={"active": True}).status_code == 400
        r = c.post("/supagent/admin/api/dashlist/grafana/default", json={"active": False})
        assert r.status_code == 200 and r.get_json() == {"read_new": False}


def test_the_backup_keeps_what_is_read(two):
    from supagent.knowledge import backup
    from supagent.models import DashItem

    assert DashItem in backup._models()["documents"]


def test_a_dashboard_read_without_a_date_takes_its_last_saved_version_s(two, monkeypatch):
    from supagent.knowledge import grafana_pages as GP

    asked = []
    real = G._call
    two["boards"]["zqx-old"]["meta"]["updated"] = "0001-01-01T00:00:00.000Z"     # what the MCP server answers

    async def fake_call(url, headers, tool, args, timeout):
        if tool == "list_dashboard_versions":
            asked.append(args)
            return [{"version": 4, "createdBy": "zqx-editor", "created": "2026-09-30T12:00:00Z", "message": ""},
                    {"version": 3, "createdBy": "someone", "created": "2026-09-01T12:00:00Z", "message": ""}]
        return await real(url, headers, tool, args, timeout)

    async def fake_batch(url, headers, items, timeout, concurrency):
        return [await fake_call(url, headers, t, a, timeout) for t, a in items]

    monkeypatch.setattr(G, "_call", fake_call)
    monkeypatch.setattr(G, "_call_batch", fake_batch)
    GP.listing()
    old = _rows()["zqx-old"]
    assert (old["updated_at"], old["updated_by"]) == ("2026-09-30T12:00:00Z", "zqx-editor")
    assert asked == [{"uid": "zqx-old", "limit": 1}]                       # only the one without a date
    assert _rows(kind="kids")["zqx-old/3"]["updated_at"] == "2026-09-30T12:00:00Z"


def test_the_search_pieces_follow_at_once_both_ways(two, monkeypatch):
    from superset.extensions import db

    from supagent import dashlist, settings
    from supagent.knowledge import grafana_pages as GP
    from supagent.knowledge.index import sync
    from supagent.models import Chunk, ContextPage

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: False if k == "knowledge.apply_background" else real(k))

    def pieces(slug):
        page = db.session.query(ContextPage).filter(ContextPage.slug == slug).one_or_none()
        if page is None:
            return None
        return db.session.query(Chunk).filter(Chunk.ref.like(f"context:{page.id}#%")).count()

    GP.refresh(llm=False)
    sync(("context:",))
    assert pieces("grafana-dashboard-zqx-old") > 0
    old = db.session.query(ContextPage).filter(ContextPage.slug == "grafana-dashboard-zqx-old").one().id
    done = dashlist.set_active("grafana", [_item("zqx-old").id], False, "admin")
    dashlist.pages_follow("grafana", done, dispatch=False)
    assert pieces("grafana-dashboard-zqx-old") is None
    assert db.session.query(Chunk).filter(Chunk.ref.like(f"context:{old}#%")).count() == 0      # gone with it
    done = dashlist.set_active("grafana", [_item("zqx-old").id], True, "admin")
    assert done["again"] == ["zqx-old"]
    out = dashlist.run_job("grafana", "pages", done["again"])        # what the background job does
    assert out["search"]["added"] > 0 and pieces("grafana-dashboard-zqx-old") > 0


def test_a_superset_visualization_question_is_not_an_osd_one(ctx):
    from supagent.agent import intents

    assert "osd" not in intents("Create a visualization of the orders per day and discover the busiest hour")
    assert "osd" in intents("Which saved search in Kibana lists the checkout errors?")
