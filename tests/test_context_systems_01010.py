"""(0.10.10, the team's request of 14 October: the agent's context well organized, no confusion) A question that
names one dashboard system (Superset, Grafana, OpenSearch Dashboards) is offered only that system's chart and
dashboard tools and instructions: "OpenSearch Dashboards" is a product's name, not Superset dashboards asked; a
question that names none keeps every system's reading tools. In an investigation with OpenSearch Dashboards set up,
the agent is told how the team's visualizations help."""
from __future__ import annotations

import types

SUPERSET = ["list_dashboards", "get_dashboard_info", "generate_dashboard", "list_charts", "generate_chart",
            "get_chart_info", "get_chart_data"]
GRAFANA = ["grafana_dashboards", "grafana_dashboard", "grafana_draft_dashboard", "grafana_folders", "grafana_alerts",
           "grafana_watch"]
OSD = ["osd_dashboards", "osd_dashboard"]
COMMON = ["execute_sql", "describe_data", "search_knowledge", "compare_to_usual"]


def _agent(monkeypatch, question: str):
    from supagent.agent import Agent

    a = object.__new__(Agent)
    a.rich, a.wants_saved_chart, a.intent_text = True, False, question
    a.specs = [{"function": {"name": n}} for n in SUPERSET + GRAFANA + OSD + COMMON]
    a.superset = types.SimpleNamespace(available=True, error=None)
    monkeypatch.setattr(Agent, "_route_intents", lambda self: set())
    return a


def _offered(a, q):
    return {s["function"]["name"] for s in a._specs_for(q)}


def test_the_product_name_asks_no_superset_dashboard():
    from supagent.agent import intents, named_systems

    q = "Which OpenSearch Dashboards visualization shows the checkout errors?"
    assert "osd" in intents(q) and "charts" not in intents(q)
    assert named_systems(q) == {"osd"} and named_systems("Show me the Superset dashboard about orders") == {"superset"}
    assert named_systems("Which dashboards show the checkout errors?") == set()
    assert "charts" in intents("Which dashboards show the checkout errors?")


def test_one_system_named_is_offered_its_own_tools_only(ctx, monkeypatch):
    q = "Show me the Superset dashboard about orders."
    got = _offered(_agent(monkeypatch, q), q)
    assert {"list_dashboards", "get_dashboard_info"} <= got and not got & set(GRAFANA + OSD)
    q = "Which Grafana dashboards show the checkout latency?"
    got = _offered(_agent(monkeypatch, q), q)
    assert {"grafana_dashboards", "grafana_dashboard"} <= got and not got & set(SUPERSET + OSD)
    q = "Which OpenSearch Dashboards visualization shows the checkout errors?"
    got = _offered(_agent(monkeypatch, q), q)
    assert {"osd_dashboards", "osd_dashboard"} <= got and not got & set(SUPERSET + GRAFANA)
    q = "Which dashboards show the checkout errors?"                       # none named: every system's reading
    got = _offered(_agent(monkeypatch, q), q)
    assert {"list_dashboards", "grafana_dashboards", "osd_dashboards"} <= got


def test_a_follow_up_keeps_the_system_its_chat_named(ctx, monkeypatch):
    a = _agent(monkeypatch, "Which Grafana dashboards show the checkout latency?\nAnd which one shows the payments?")
    got = _offered(a, "And which one shows the payments?")
    assert "grafana_dashboards" in got and not got & {"list_dashboards", "osd_dashboards"}


def test_the_instructions_follow_the_system_named(ctx, monkeypatch):
    from supagent.agent import OSD_SECTION, SECTIONS

    q = "Which OpenSearch Dashboards visualization shows the checkout errors?"
    text = _agent(monkeypatch, q)._system(q)
    assert SECTIONS["charts"] not in text                                  # never Superset's saving instructions
    q = "Show me the Superset dashboard about orders and save a chart of its orders by day."
    assert SECTIONS["charts"] in _agent(monkeypatch, q)._system(q)
    q = "Why was the zqx checkout slow this morning?"
    a = _agent(monkeypatch, q)
    assert OSD_SECTION in a._system(q)                                     # set up here: how the team measures
    a.specs = [s for s in a.specs if not s["function"]["name"].startswith("osd_")]
    assert OSD_SECTION not in a._system(q)                                 # not set up: not said


def test_a_system_named_but_not_set_up_filters_nothing(ctx, monkeypatch):
    q = "Make a Grafana dashboard of the checkout errors."
    a = _agent(monkeypatch, q)
    a.specs = [s for s in a.specs if not s["function"]["name"].startswith("grafana_")]   # no Grafana here
    got = _offered(a, q)
    assert "generate_dashboard" in got                                    # Superset's own stay offered

