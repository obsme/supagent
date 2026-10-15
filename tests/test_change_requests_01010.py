"""(0.10.10, gate 1 gq2 H09) Asked to delete an existing Grafana alert rule, the agent showed the rule and said "you
can delete it via the API", never that it cannot: it only reads Grafana and OpenSearch Dashboards (and drafts NEW
Grafana rules and dashboards for an admin's approval). A question that names one of them (set up here) and asks to
change something there is sent back once when the answer does not say plainly it cannot. Never for a question that
names a draft, asks to create, names neither system, or when Grafana is not set up."""
from __future__ import annotations

TOOLS = ["grafana_dashboards", "grafana_dashboard", "grafana_alerts", "osd_dashboards", "osd_dashboard",
         "execute_sql"]
SHOWN = "Here is the rule: Zqx queue too deep, folder Zqx platform, hold 5m."


def _agent(monkeypatch, tools=TOOLS):
    from supagent.agent import Agent
    from test_agent_loop import agent_with

    a, _ran = agent_with(monkeypatch, [])
    monkeypatch.setattr(Agent, "_route_intents", lambda self: set())
    a.specs = [{"function": {"name": n}} for n in tools]
    return a


def test_change_requests_are_said_impossible(ctx, monkeypatch):
    a = _agent(monkeypatch)
    fire = ["Could you disable the Grafana rule 'Zqx queue too deep' for the weekend?",
            "Please move the Grafana dashboard 'Zqx shop' into the folder Zqx platform.",
            "Mute the Grafana alert 'Zqx errors' for an hour.",
            "Supprime le tableau de bord OpenSearch Dashboards 'Zqx ops'."]
    for q in fire:
        got = a._change_unrefused(q, SHOWN, [])
        assert got, q
    assert a._change_unrefused(fire[3], SHOWN, [])[0] == "OpenSearch Dashboards"
    assert "draft a new alert rule" in a._change_unrefused(fire[0], SHOWN, [])[1]
    assert a._change_unrefused(fire[0], "I can't disable rules in Grafana; an admin can pause it there.", []) is None


def test_not_for_reads_creations_drafts_or_other_systems(ctx, monkeypatch):
    a = _agent(monkeypatch)
    for q in ("Which Grafana rule changed most recently?",
              "Create a Grafana alert rule when zqx errors exceed 5%.",
              "Change the threshold of the draft to 5% in Grafana.",
              "What changed in the zqx checkout this morning?",
              "Delete the old rows of the zqx table.",
              "Set up in Grafana the alert rule from our team rule about the zqx error share."):   # a share: a noun
        assert a._change_unrefused(q, SHOWN, []) is None, q
    made = [{"tool": "grafana_draft_alert_rule", "called": "grafana_draft_alert_rule", "status": "done",
             "result": '{"drafted": 4}'}]
    assert a._change_unrefused("Modify the Grafana rule 'Zqx queue too deep': 10 minutes instead.", SHOWN, made) is None
    no_grafana = _agent(monkeypatch, tools=["execute_sql"])
    assert no_grafana._change_unrefused("Mute the Grafana alert 'Zqx errors' for an hour.", SHOWN, []) is None


def test_the_answer_is_sent_back_once(ctx, monkeypatch):
    from supagent import settings
    from supagent.agent import CHANGE_NUDGE
    from test_agent_loop import agent_with, call, say

    rule = '{"rules": [{"title": "Zqx queue too deep", "folder": "Zqx platform", "for": "5m"}]}'
    a, _ran = agent_with(monkeypatch, [call("grafana_alerts", {"query": "Zqx queue too deep"}), say(SHOWN),
                                       say("I cannot pause rules in Grafana: an admin can, there.")] +
                         [say("Done.")] * 3, results=lambda n, args: rule)
    a.specs = [{"function": {"name": n}} for n in TOOLS]
    a.names = a.names | set(TOOLS)
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k, *x: False if k == "agent.ledger" else real(k, *x))
    text, _steps = a.ask("Pause the Grafana alert rule 'Zqx queue too deep' until Friday.")
    told = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user"]
    assert sum(CHANGE_NUDGE.split("{")[0] in t for t in told) == 1 and "cannot" in text
