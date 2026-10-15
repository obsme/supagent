"""(0.10.10, gq1w X5) "Why was the shop checkout slow this morning?" was answered from the logs alone: the team's
Grafana, set up here, was never looked at (its p95 panel in red at that time, an alert firing). An investigation or
a question of health whose answer called neither grafana_watch nor grafana_alerts is sent back once to look; never
when Grafana is not set up for the user, nor for a follow-up that asks a count."""

from __future__ import annotations

WHY = "Why was the zqx checkout slow this morning?"
ANSWER = "## Root cause\nThe zqx checkout pods were killed for memory at 09:00, 09:02 and 09:29."
LOOKED = [{"tool": "grafana_watch", "status": "done", "args": {"about": "zqx checkout"}}]
SQL = [{"tool": "execute_sql", "status": "done", "args": {"request": {"database_id": 1, "sql": "SELECT 1"}}}]


def test_an_investigation_that_never_looked_at_grafana(ctx, monkeypatch):
    from supagent.agent import Agent
    from test_agent_loop import agent_with

    a, _ran = agent_with(monkeypatch, [])
    monkeypatch.setattr(Agent, "_route_intents", lambda self: set())
    a.intent_text = WHY
    a.names = a.names | {"grafana_watch", "grafana_alerts"}
    assert a._grafana_unlooked(WHY, SQL) is True
    assert a._grafana_unlooked(WHY, SQL + LOOKED) is False                         # it looked
    assert a._grafana_unlooked("How many orders were placed this morning?", SQL) is False   # no investigation
    count = "How many times were the pods killed that morning?"
    a.intent_text = f"{WHY}\n{count}"
    assert a._grafana_unlooked(count, SQL) is False                                # its follow-up count
    a.intent_text = WHY
    a.names = {"execute_sql"}
    assert a._grafana_unlooked(WHY, SQL) is False                                  # no Grafana here


def test_the_answer_is_sent_back_once_to_look(ctx, monkeypatch):
    import json

    from supagent import settings
    from supagent.agent import GRAFANA_NUDGE, Agent
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 4}], "row_count": 1})
    watch = json.dumps({"panels": [{"dashboard": "Zqx shop", "panel": "Checkout p95", "value": 1.2, "state": "red"}]})
    a, ran = agent_with(monkeypatch, [call("execute_sql", {"request": {"database_id": 1, "sql": "SELECT 4 AS n"}}),
                                      say(ANSWER), call("grafana_watch", {"about": "zqx checkout"}),
                                      say(ANSWER + " Grafana: the checkout p95 panel was red (1.2 s).")] +
                        [say("Done.")] * 4, results=lambda n, args: watch if n == "grafana_watch" else rows)
    a.names = a.names | {"grafana_watch", "grafana_alerts"}
    monkeypatch.setattr(Agent, "_investigating", lambda self, q: True)
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k, *x: False if k == "agent.ledger" else real(k, *x))   # no work plan
    a.ask(WHY)
    told = [m["content"] for seen in a.llm.seen for m in seen if m["role"] == "user"]
    assert sum(GRAFANA_NUDGE in t for t in told) >= 1 and [n for n, _ in ran] == ["execute_sql", "grafana_watch"]
    last = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user"]
    assert sum(GRAFANA_NUDGE in t for t in last) == 1                             # once: not asked again
