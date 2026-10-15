"""(0.10.10) Alert rules for Grafana are never written by the agent: a draft is checked (the folder, group, fixed labels
and datasource of the settings only, labels of the allowed keys, metrics the datasource has, a number, a bounded
"for"), stored for an admin, created only on approval with grafana.writes on and its spec unchanged, then read back.
A second draft of the same rule finds the first. Invented names only."""
from __future__ import annotations

import pytest

from supagent import grafana as G

METRICS = {"zqx_requests_total", "zqx_errors_total", "zqx_queue_depth"}


@pytest.fixture()
def grafana(ctx, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.models import GrafanaAction

    conf = {"grafana.mcp_url": "http://mcp.invalid/mcp", "grafana.alert_folder": "zqx-agent",
            "grafana.rule_group": "zqx-group", "grafana.datasource": "prom1",
            "grafana.rule_labels": {"managed_by": "supagent"}, "grafana.label_keys": ["severity", "team", "service"],
            "grafana.writes": True, "grafana.cache_seconds": 0}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: conf[k] if k in conf else real(k))
    monkeypatch.setattr(G, "_setting", lambda k, d=None: conf.get(k, d))
    calls: list[tuple[str, dict]] = []
    created: dict[str, dict] = {}

    async def fake_call(url, headers, tool, args, timeout):
        calls.append((tool, args))
        if tool == "list_prometheus_metric_names":
            name = args["regex"].strip("^$").replace("\\", "")
            return [name] if name in METRICS else []
        if tool == "query_prometheus":
            return {"data": {"result": [{"metric": {}, "value": [1, "0.08"]}]}}
        if tool == "alerting_manage_routing":
            return {"receiver": "zqx-default", "routes": [{"object_matchers": [["team", "=", "zqx"]],
                                                           "receiver": "zqx-team"}]}
        if tool == "alerting_rules_read":
            if args["operation"] == "get":
                return created.get(args["rule_uid"]) or {}
            return list(created.values())
        if tool == "alerting_rules_write":
            created[args["rule_uid"]] = {"uid": args["rule_uid"], "title": args["title"], "folder_uid": args["folder_uid"],
                                         "rule_group": args["rule_group"], "condition": args["condition"],
                                         "for": args["for"], "labels": args["labels"], "data": args["data"]}
            return {"uid": args["rule_uid"]}
        raise AssertionError(f"unexpected tool {tool}")

    monkeypatch.setattr(G, "_call", fake_call)
    G._CACHE.clear()
    db.session.query(GrafanaAction).delete()
    db.session.commit()
    yield conf, calls, created
    db.session.query(GrafanaAction).delete()
    db.session.commit()
    G._CACHE.clear()


def test_the_metrics_a_query_reads():
    from supagent.grafana_rules import metrics_of

    assert metrics_of('sum(rate(zqx_errors_total{code=~"5.."}[5m])) / sum(rate(zqx_requests_total[5m]))') == \
        ["zqx_errors_total", "zqx_requests_total"]
    assert metrics_of("histogram_quantile(0.95, sum by (le) (rate(zqx_latency_bucket[5m])))") == ["zqx_latency_bucket"]
    assert metrics_of("max_over_time(zqx_queue_depth[10m]) > bool 3") == ["zqx_queue_depth"]


def _draft(**kw):
    from supagent import grafana_rules as R

    args = dict(title="Zqx errors above 5%", query="sum(rate(zqx_errors_total[5m])) / sum(rate(zqx_requests_total[5m]))",
                operator="gt", threshold=0.05, hold="10m", severity="critical", team="zqx", summary="Errors are high",
                source="chat", requested_by="admin")
    args.update(kw)
    return R.draft(**args)


def test_a_draft_takes_its_folder_group_and_fixed_labels_from_the_settings(grafana):
    _conf, calls, created = grafana
    out = _draft()
    assert out["drafted"] and out["preview"]["value now"] == [0.08] and out["preview"]["would fire now"] is True
    assert out["preview"]["notified"] == ["zqx-team"]
    from superset.extensions import db

    from supagent.models import GrafanaAction

    row = db.session.get(GrafanaAction, out["drafted"])
    assert row.status == "proposed" and row.spec["folder_uid"] == "zqx-agent" and row.spec["rule_group"] == "zqx-group"
    assert row.spec["labels"] == {"severity": "critical", "team": "zqx", "managed_by": "supagent"}
    assert row.spec["for"] == "600s" and row.spec["datasource"] == "prom1"
    assert not created and not [c for c in calls if c[0] == "alerting_rules_write"]      # nothing written yet


@pytest.mark.parametrize("kw,why", [
    ({"query": "sum(rate(zqx_unknown_total[5m]))"}, "no metric zqx_unknown_total"),
    ({"operator": "about"}, "operator"),
    ({"threshold": "high"}, "number"),
    ({"hold": "3d"}, "a day at most"),
    ({"team": "zqx; drop"}, "letters, digits"),
    ({"title": "x"}, "3 to 190"),
    ({"runbook_url": "javascript:alert(1)"}, "http"),
    ({"source": "memory:999999"}, "no active team memory"),
])
def test_what_a_draft_refuses(grafana, kw, why):
    from supagent import grafana_rules as R

    with pytest.raises(R.RuleError, match=why):
        _draft(**kw)


def test_a_label_key_outside_the_allowed_ones_is_refused(grafana):
    from supagent import grafana_rules as R

    with pytest.raises(R.RuleError, match="label 'environment'"):
        _draft(environment="prod")             # not in this deployment's grafana.label_keys


def test_no_folder_set_no_draft(grafana):
    from supagent import grafana_rules as R

    conf, _calls, _created = grafana
    conf["grafana.alert_folder"] = ""
    with pytest.raises(R.RuleError, match="grafana.alert_folder"):
        _draft()


def test_the_same_rule_drafted_twice_is_found_not_made_again(grafana):
    from superset.extensions import db

    from supagent.models import GrafanaAction, Memory

    m = Memory(scope="team", status="active", kind="rule", text="Alert the zqx team when zqx errors pass 5% for 10 minutes")
    db.session.add(m)
    db.session.commit()
    try:
        first = _draft(source=f"memory:{m.id}")
        again = _draft(source=f"memory:{m.id}", title="Zqx error ratio too high")      # worded otherwise
        assert again["already"].startswith("drafted") and again["draft"] == first["drafted"]
        assert db.session.query(GrafanaAction).count() == 1
    finally:
        db.session.delete(m)
        db.session.commit()


def test_approval_creates_exactly_the_draft_and_reads_it_back(grafana):
    from supagent import grafana_rules as R

    _conf, calls, created = grafana
    out = _draft()
    done = R.approve(out["drafted"], "admin")
    writes = [a for t, a in calls if t == "alerting_rules_write"]
    assert len(writes) == 1 and writes[0]["operation"] == "create" and writes[0]["folder_uid"] == "zqx-agent"
    assert writes[0]["rule_uid"] == out["rule_uid"] and done["created"] == out["rule_uid"] and done["differences"] == []
    cond = writes[0]["data"][2]["model"]["conditions"][0]["evaluator"]
    assert cond == {"type": "gt", "params": [0.05]}
    with pytest.raises(R.RuleError, match="no draft waiting"):
        R.approve(out["drafted"], "admin")                          # once only


def test_approval_reads_the_folder_as_it_is_now(grafana):
    """A rule a person made in the folder since the draft stops the approval, though the draft's read is cached."""
    from supagent import grafana_rules as R

    conf, calls, created = grafana
    conf["grafana.cache_seconds"] = 60
    out = _draft()
    created["by-a-person"] = {"uid": "by-a-person", "title": "Zqx errors above 5%"}
    with pytest.raises(R.RuleError, match="in the folder already"):
        R.approve(out["drafted"], "admin")
    assert not [c for c in calls if c[0] == "alerting_rules_write"]


def test_approval_refused_with_writes_off_or_a_changed_spec(grafana):
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import GrafanaAction

    conf, calls, _created = grafana
    out = _draft()
    conf["grafana.writes"] = False
    with pytest.raises(R.RuleError, match="grafana.writes"):
        R.approve(out["drafted"], "admin")
    conf["grafana.writes"] = True
    row = db.session.get(GrafanaAction, out["drafted"])
    row.spec = {**row.spec, "folder_uid": "General"}                 # changed after the draft
    db.session.commit()
    with pytest.raises(R.RuleError, match="changed after it was drafted"):
        R.approve(out["drafted"], "admin")
    assert not [c for c in calls if c[0] == "alerting_rules_write"]


def test_a_rejected_draft_is_kept_rejected(grafana):
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import GrafanaAction

    out = _draft()
    R.reject(out["drafted"], "admin", "not now")
    assert db.session.get(GrafanaAction, out["drafted"]).status == "rejected"
    assert R.pending() == []


def test_the_teams_rules_that_read_as_alert_rules(grafana):
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import Entry, Memory

    rows = [Memory(scope="team", status="active", kind="rule", text="Alert when zqx queue depth exceeds 500 for 5m"),
            Memory(scope="team", status="active", kind="rule", text="Always answer in French"),
            Memory(scope="user", status="active", kind="rule", text="Alert me when zqx errors pass 1%"),
            Entry(title="Zqx checks", classification="checks", content="Notify the zqx team when errors pass 2%",
                  enabled=True)]
    db.session.add_all(rows)
    db.session.commit()
    try:
        found = R.sources()
        texts = " | ".join(f["text"] for f in found)
        assert "queue depth exceeds 500" in texts and "errors pass 2%" in texts
        assert "French" not in texts and "Alert me" not in texts                  # no alert / not the team's
    finally:
        for r in rows:
            db.session.delete(r)
        db.session.commit()


def test_the_draft_tool_is_for_admins_only(grafana):
    from supagent import tools_grafana as T
    from supagent.security import acting_as

    _conf, calls, _created = grafana
    args = dict(title="Zqx queue deep", query="max(zqx_queue_depth)", operator="gt", threshold=500, hold="5m",
                team="zqx")
    with acting_as("alice"):
        out = T.grafana_draft_alert_rule(**args)
    assert isinstance(out, str) and out.startswith("tool error: only an admin") and calls == []
    with acting_as("admin"):
        out = T.grafana_draft_alert_rule(**args)
    assert out["drafted"] and not [c for c in calls if c[0] == "alerting_rules_write"]


def test_grafana_roles_limit_who_reads_grafana(grafana):
    from supagent import tools_grafana as T
    from supagent.security import acting_as

    conf, calls, _created = grafana
    conf["grafana.roles"] = ["Admin"]
    conf["grafana.cache_seconds"] = 0
    assert not T.usable_for("alice") and T.usable_for("admin") and not T.usable_for("no-such-user")
    with acting_as("alice"):
        assert T.grafana_alerts(state="firing").startswith("tool error: the user's roles may not read Grafana")
    assert calls == []
    with acting_as("admin"):
        assert T.grafana_alerts(state="firing")["count"] == 0
    assert [c[0] for c in calls] == ["alerting_rules_read"]


def test_only_an_admin_decides_through_the_api(grafana):
    from conftest import login
    from flask import current_app
    from superset.extensions import db

    from supagent.models import GrafanaAction

    _conf, _calls, created = grafana
    first, second = _draft(), _draft(title="Zqx queue deep", query="max(zqx_queue_depth)", threshold=500)
    with current_app.app_context():             # a g of each user's own (the test's open context would be reused)
        c = current_app.test_client()
        login(c, "alice")
        r = c.post(f"/supagent/admin/api/grafana/{first['drafted']}", json={"decision": "approve"})
        assert r.status_code in (401, 403) and not created
    with current_app.app_context():
        c = current_app.test_client()
        login(c, "admin")
        r = c.post(f"/supagent/admin/api/grafana/{first['drafted']}", json={"decision": "maybe"})
        assert r.status_code == 400, (r.status_code, r.get_data(as_text=True)[:300])
        r = c.post(f"/supagent/admin/api/grafana/{second['drafted']}", json={"decision": "reject", "why": "later"})
        assert r.status_code == 200 and r.get_json() == {"rejected": second["drafted"]}
        shown = {d["id"]: d["spec_hash"] for d in c.get("/supagent/admin/api/review").get_json()["grafana"]}
        r = c.post(f"/supagent/admin/api/grafana/{first['drafted']}", json={"decision": "approve"})
        assert r.status_code == 400 and "spec_hash" in r.get_json()["error"]                 # what was shown, named
        r = c.post(f"/supagent/admin/api/grafana/{first['drafted']}", json={"decision": "approve", "spec_hash": "x"})
        assert r.status_code == 400 and "not the one shown" in r.get_json()["error"] and not created
        r = c.post(f"/supagent/admin/api/grafana/{first['drafted']}",
                   json={"decision": "approve", "spec_hash": shown[first["drafted"]]})
        assert r.status_code == 200 and r.get_json()["created"] == first["rule_uid"], r.get_data(as_text=True)
        r = c.post(f"/supagent/admin/api/grafana/{first['drafted']}",
                   json={"decision": "approve", "spec_hash": shown[first["drafted"]]})
        assert r.status_code == 400 and "no draft waiting" in r.get_json()["error"]
    assert list(created) == [first["rule_uid"]]
    db.session.expire_all()
    assert db.session.get(GrafanaAction, first["drafted"]).decided_by == "admin"
    assert db.session.get(GrafanaAction, second["drafted"]).status == "rejected"


def test_a_catalog_entry_of_two_rules_gives_two_drafts(grafana):
    from superset.extensions import db

    from supagent.models import Entry, GrafanaAction

    e = Entry(title="Zqx checks", classification="checks", enabled=True,
              content="Notify the zqx team when errors pass 2%; page them when the queue depth exceeds 500")
    db.session.add(e)
    db.session.commit()
    try:
        one = _draft(source=f"catalog:{e.id}", query="sum(rate(zqx_errors_total[5m])) / sum(rate(zqx_requests_total[5m]))",
                     threshold=0.02)
        two = _draft(source=f"catalog:{e.id}", title="Zqx queue deep", query="max(zqx_queue_depth)", threshold=500)
        again = _draft(source=f"catalog:{e.id}", title="Zqx queue too deep", query="max(zqx_queue_depth)", threshold=500)
        assert one["drafted"] and two["drafted"] and one["rule_uid"] != two["rule_uid"]
        assert again["draft"] == two["drafted"] and db.session.query(GrafanaAction).count() == 2
    finally:
        db.session.delete(e)
        db.session.commit()


def test_a_rule_made_but_not_read_back_stays_made(grafana):
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import GrafanaAction

    _conf, _calls, created = grafana
    out = _draft()
    real = G._call

    async def no_read_back(url, headers, tool, args, timeout):
        if tool == "alerting_rules_read" and args.get("operation") == "get":
            raise G.GrafanaError("timeout")
        return await real(url, headers, tool, args, timeout)

    G._call = no_read_back
    try:
        done = R.approve(out["drafted"], "admin")
    finally:
        G._call = real
    row = db.session.get(GrafanaAction, out["drafted"])
    assert row.status == "created" and done["differences"][0].startswith("not read back") and created


def test_a_read_back_of_another_shape_is_compared(grafana):
    from supagent import grafana_rules as R

    out = _draft()
    from superset.extensions import db

    from supagent.models import GrafanaAction

    spec = db.session.get(GrafanaAction, out["drafted"]).spec
    flat = R.payload(spec)
    wrapped = {"rule": {"uid": spec["uid"], "title": spec["title"], "folder_uid": spec["folder_uid"],
                        "rule_group": spec["rule_group"], "labels": spec["labels"],
                        "configuration": {"condition": "C", "data": flat["data"]}}}
    assert R._compare(spec, wrapped) == []
    assert R._compare(spec, {"labels": "odd", "data": [{"model": {"type": "threshold", "conditions": [None]}}]})
    assert R._compare(spec, None)                                   # never raises: says what differs


def test_the_caller_waits_the_timeout_at_most():
    import asyncio
    import time

    t0 = time.time()
    with pytest.raises(Exception):
        G._run(asyncio.sleep(5), 0.5)
    assert time.time() - t0 < 2


def test_a_chat_draft_of_a_team_rule_takes_its_source_and_is_never_drafted_twice(grafana):
    """(0.10.10, gq1 W01/W02) The agent drafted a team rule as a chat one, then a second time worded otherwise: the
    rule the chat names is found (two words and its number or its hold in common), the second draft finds the first."""
    from superset.extensions import db

    from supagent.models import GrafanaAction, Memory

    m = Memory(scope="team", status="active", kind="rule",
               text="Alert the zqx team (severity critical) when the zqx error share stays above 5% for 10 minutes")
    db.session.add(m)
    db.session.commit()
    try:
        first = _draft(title="Zqx error share above 5%")                       # source chat
        row = db.session.get(GrafanaAction, first["drafted"])
        assert row.source == f"memory:{m.id}" and first["from the team's rule"].startswith(f"memory:{m.id}:")
        again = _draft(title="ZqxErrorShareHigh", threshold=5, hold="10m",       # other words, other scale
                       query="sum(rate(zqx_errors_total[5m])) / sum(rate(zqx_requests_total[5m])) * 100")
        assert again["already"].startswith("drafted from the same team rule") and again["draft"] == first["drafted"]
        assert db.session.query(GrafanaAction).count() == 1
    finally:
        db.session.delete(m)
        db.session.commit()


def test_two_team_rules_that_both_match_are_never_chosen_by_chance(grafana):
    from superset.extensions import db

    from supagent.models import GrafanaAction, Memory

    rows = [Memory(scope="team", status="active", kind="rule", text="Alert the zqx team when zqx errors pass 5% for 10 minutes"),
            Memory(scope="team", status="active", kind="rule", text="Page the zqx on-call when zqx errors pass 5% for 10 minutes")]
    db.session.add_all(rows)
    db.session.commit()
    try:
        out = _draft(title="Zqx errors above 5%")
        assert db.session.get(GrafanaAction, out["drafted"]).source == "chat" and "from the team's rule" not in out
    finally:
        for r in rows:
            db.session.delete(r)
        db.session.commit()


def test_a_corrected_draft_of_the_same_title_replaces_the_first(grafana):
    """(0.10.10, gq1d D02's class for rules) The agent corrects its draft in the same turn: one draft, the newer one."""
    from superset.extensions import db

    from supagent.models import GrafanaAction

    first = _draft(title="Zqx queue too deep", query="max(zqx_queue_depth)", threshold=500)
    second = _draft(title="Zqx queue too deep", query="max_over_time(zqx_queue_depth[5m])", threshold=500)
    assert second["drafted"] == first["drafted"] and second["replaced"].startswith("the earlier draft")
    row = db.session.get(GrafanaAction, first["drafted"])
    assert db.session.query(GrafanaAction).count() == 1 and row.spec["query"] == "max_over_time(zqx_queue_depth[5m])"
    assert row.spec_hash != first.get("spec_hash")                     # what an admin approves is the newer spec


def test_a_team_rule_already_made_in_grafana_is_not_drafted_again(grafana):
    """(0.10.10, gq1 W02 after A1) The rule drafted from a team rule was approved and made: asked again (other words,
    another query of the same metric), it is said made, no second draft; deleted in Grafana since: drafted again."""
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import GrafanaAction, Memory

    _conf, _calls, created = grafana
    m = Memory(scope="team", status="active", kind="rule",
               text="Alert the zqx team (severity critical) when the zqx error share stays above 5% for 10 minutes")
    db.session.add(m)
    db.session.commit()
    try:
        first = _draft(title="Zqx error share above 5%")
        R.approve(first["drafted"], "admin")
        again = _draft(title="Zqx Error Share High", threshold=5,
                       query="sum(rate(zqx_errors_total[5m])) / sum(rate(zqx_requests_total[5m])) * 100")
        assert again["already"] == "created in Grafana from the same team rule" and again["draft"] == first["drafted"]
        assert db.session.query(GrafanaAction).count() == 1
        created.clear()                                                    # someone deleted it in Grafana
        third = _draft(title="Zqx Error Share High", threshold=5,
                       query="sum(rate(zqx_errors_total[5m])) / sum(rate(zqx_requests_total[5m])) * 100")
        assert third.get("drafted") and db.session.query(GrafanaAction).count() == 2
    finally:
        db.session.delete(m)
        db.session.commit()


def test_a_chat_rule_of_another_measure_never_takes_a_team_rule_as_its_source(grafana):
    """(0.10.10, gq1 W10) A rule asked in the chat for another measure and another team took the team's 5xx rule as
    its source: "team", "warning" and the same ten minutes in common. The words every rule says, the team's name,
    the digits inside names (5xx, p95, node_load1) and a hold alone never tie a draft to a team rule."""
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import GrafanaAction, Memory

    m = Memory(scope="team", status="active", kind="rule",
               text="Alert the zqx team (severity warning) when the zqx 5xx share stays above 3% for 10 minutes")
    db.session.add(m)
    db.session.commit()
    try:
        load = _draft(title="High node load on zqxplat", query="max(zqx_queue_depth)", threshold=8, hold="10m",
                      severity="warning", team="zqxplat", summary="node load above 8 for 10 minutes, team zqxplat")
        assert db.session.get(GrafanaAction, load["drafted"]).source == "chat" and "from the team's rule" not in load
        p95 = _draft(title="Zqx p95 latency high", query="max(zqx_queue_depth)", threshold=3, hold="10m",
                     severity="warning", team="zqx", summary="the zqx p95 stays above 3 s for 10 minutes")
        assert db.session.get(GrafanaAction, p95["drafted"]).source == "chat"          # same team, number, hold
        five = _draft(title="Zqx 5xx share above 5%", threshold=0.05, hold="10m", team="zqx",
                      summary="the zqx 5xx share above 5% for 10 minutes")
        assert db.session.get(GrafanaAction, five["drafted"]).source == "chat"         # the 5 of 5xx is no threshold
        held = _draft(title="Zqx 5xx share above 3%", threshold=0.03, hold="5m", team="zqx",
                      summary="the zqx 5xx share above 3% for 5 minutes")
        assert db.session.get(GrafanaAction, held["drafted"]).source == "chat"         # another hold: another rule
        down = _draft(title="Zqx 5xx share below 3%", operator="lt", threshold=0.03, hold="10m", team="zqx",
                      summary="the zqx 5xx share below 3% for 10 minutes")
        assert db.session.get(GrafanaAction, down["drafted"]).source == "chat"         # the other way
        same = _draft(title="Zqx 5xx share above 3%", threshold=0.03, hold="10m", team="zqx",
                      summary="the zqx share of 5xx responses above 3% for 10 minutes")
        assert db.session.get(GrafanaAction, same["drafted"]).source == f"memory:{m.id}"   # the team rule itself
    finally:
        db.session.delete(m)
        db.session.commit()


def test_what_a_rule_text_says_of_its_threshold_and_hold():
    from supagent.grafana_rules import _hold_of, _teams_named, _thresholds

    text = "Alert the shop team (severity warning) when the checkout's 5xx share stays above 3% for 10 minutes"
    assert _thresholds(text) == {3.0, 0.03} and _hold_of(text) == {600} and _teams_named(text) == {"shop"}
    assert _thresholds("p95 above 1.5 s for 10 minutes") == {1.5} and _hold_of("p95 above 2 s") == set()
    assert _thresholds("zqx_node_load1 above 8 during 5m") == {8.0} and _hold_of("above 8 during 5m") == {300}
    assert _thresholds("errors above 5 percent") == {5.0, 0.05}
    assert _teams_named("Notify team: payments when ...") == {"payment"}
    assert _teams_named("Alert the zqx team platform when ...") == {"zqx", "platform"}


BAD_PROMQL = 'querying Prometheus instant: bad_data: invalid parameter "query": 1:41: parse error: unexpected <aggr:GROUP>'


def _picky(monkeypatch):
    """The datasource refuses a query it cannot parse, as Prometheus says it through the MCP server."""
    real = G._call

    async def picky(url, headers, tool, args, timeout):
        if tool == "query_prometheus" and "GROUP BY" in str(args.get("expr")):
            raise G.GrafanaError(BAD_PROMQL)
        return await real(url, headers, tool, args, timeout)

    monkeypatch.setattr(G, "_call", picky)


def test_a_rule_query_prometheus_cannot_parse_is_refused(grafana, monkeypatch):
    """(0.10.10, gq1d D09's class) A query written like SQL ("SUM(rate(x)) GROUP BY 1") is refused with
    Prometheus' own reason and how to write it; nothing is drafted."""
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import GrafanaAction

    _picky(monkeypatch)
    with pytest.raises(R.RuleError, match="not valid PromQL.*parse error.*sum\\(rate"):
        _draft(query="SUM(rate(zqx_errors_total[5m])) GROUP BY 1")
    assert db.session.query(GrafanaAction).count() == 0
    assert _draft(query="sum(rate(zqx_errors_total[5m]))")["drafted"]           # a valid query: drafted


def test_a_missing_mcp_package_is_said_as_what_to_install(grafana, monkeypatch):
    async def no_package(url, headers, tool, args, timeout):
        raise ModuleNotFoundError("No module named 'mcp'")

    monkeypatch.setattr(G, "_call", no_package)
    with pytest.raises(G.GrafanaError, match='pip install "mcp>=1.20,<2"'):
        G.call("search_dashboards", {"query": "x"}, cached=False)

