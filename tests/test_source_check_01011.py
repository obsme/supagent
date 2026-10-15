"""(0.10.11) The Settings page's "Test the connection" of Grafana (its MCP server) and OpenSearch Dashboards: what
answers, what is wrong when not, never an exception. Invented names only."""
from __future__ import annotations

from supagent import grafana as G
from supagent import osd as O


def test_grafana_check(monkeypatch):
    conf = {"grafana.mcp_url": "http://mcp.invalid/mcp", "grafana.datasource": "zqxprom"}
    monkeypatch.setattr(G, "_setting", lambda k, d=None: conf.get(k, d))
    rows = [{"uid": "zqxprom", "name": "Zqx Prometheus", "type": "prometheus"}, {"uid": "zqxlogs", "name": "L"}]
    monkeypatch.setattr(G, "call", lambda tool, args=None, cached=True: rows)
    out = G.check()
    assert out["ok"] and "2 datasources" in out["said"] and "Zqx Prometheus (prometheus)" in out["said"]
    conf["grafana.datasource"] = "nope"
    out = G.check()
    assert not out["ok"] and "'nope' is none of them" in out["said"] and "zqxprom" in out["said"]

    def down(tool, args=None, cached=True):
        raise G.GrafanaError("the Grafana MCP server does not answer")
    monkeypatch.setattr(G, "call", down)
    out = G.check()
    assert out == {"ok": False, "said": "the Grafana MCP server does not answer"}


def test_osd_check(monkeypatch):
    conf = {"osd.url": "http://osd.invalid:5601", "osd.tenant": "global"}
    monkeypatch.setattr(O, "_setting", lambda k, d=None: conf.get(k, d))
    monkeypatch.setattr(O, "_get", lambda path, params: {"total": 7, "saved_objects": [{"id": "a"}]})
    out = O.check()
    assert out == {"ok": True, "said": "OpenSearch Dashboards answers: 7 dashboards in the tenant global"}

    def refused(path, params):
        raise O.OSDError("OpenSearch Dashboards refused the sign-in (401)")
    monkeypatch.setattr(O, "_get", refused)
    assert O.check() == {"ok": False, "said": "OpenSearch Dashboards refused the sign-in (401)"}
