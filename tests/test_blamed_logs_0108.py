"""(0.10.8) An investigation found the change behind a failure (a new version of the part its callers' errors named)
and never read that part's own lines: the error it logged was not said. When the answer blames a part that a field
of a log table it queried names, and no query of that table kept that part, it is sent back once to read them."""

from __future__ import annotations

ANSWER = ("The orders failed this afternoon.\n\n## Root cause\nThe deployment of a new version of svc-b: svc-b returned "
          "errors to svc-a, which failed the orders; the rollback ended it.")


def _trace(*services):
    return [{"tool": "execute_sql", "status": "done", "args": {"request": {"database_id": 1, "sql": (
        f"SELECT body, COUNT(*) FROM \"app-logs\" WHERE \"service.name\" = '{s}' GROUP BY body")}}} for s in services]


def _agent(monkeypatch, investigating=True):
    from supagent.agent import Agent
    from supagent.knowledge import carry
    from test_agent_loop import agent_with

    a, _ran = agent_with(monkeypatch, [])
    monkeypatch.setattr(Agent, "_investigating", lambda self, q: investigating)
    monkeypatch.setattr(carry, "field_values", lambda tables: {"svc-a": "service.name", "svc-b": "service.name",
                                                               "node-7": "host.name"} if tables else {})
    return a


def test_the_blamed_part_whose_lines_were_never_read(ctx, monkeypatch):
    a = _agent(monkeypatch)
    q = "Why did the orders fail this afternoon?"
    assert a._blamed_logs_unread(q, ANSWER, _trace("svc-a")) == ("svc-b", "app-logs", "service.name")
    assert a._blamed_logs_unread(q, ANSWER, _trace("svc-a", "svc-b")) is None              # its lines were read
    assert a._blamed_logs_unread(q, ANSWER, []) is None                                   # no log table queried


def test_not_for_a_question_that_is_no_investigation(ctx, monkeypatch):
    a = _agent(monkeypatch, investigating=False)
    assert a._blamed_logs_unread("How many orders failed?", ANSWER, _trace("svc-a")) is None


def test_the_answer_is_sent_back_to_read_them(ctx, monkeypatch):
    import json

    from supagent.agent import Agent, BLAMED_LOGS_NUDGE
    from supagent.knowledge import carry
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "body"}, {"name": "n"}],
                       "rows": [{"body": "call failed", "n": 9}], "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": "SELECT body, COUNT(*) AS n FROM \"app-logs\" WHERE \"service.name\" = "
                                                 "'svc-a' GROUP BY body"}}
    again = {"request": {"database_id": 1, "sql": "SELECT body, COUNT(*) AS n FROM \"app-logs\" WHERE "
                                                   "\"service.name\" = 'svc-b' GROUP BY body"}}
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), say(ANSWER), call("execute_sql", again),
                                      say(ANSWER + " svc-b logged: call failed (9 lines).")] + [say("Done.")] * 4,
                        results=lambda n, args: rows)
    monkeypatch.setattr(Agent, "_investigating", lambda self, q: True)
    monkeypatch.setattr(carry, "field_values", lambda tables: {"svc-a": "service.name", "svc-b": "service.name"})
    from supagent import settings

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k, *x: False if k == "agent.ledger" else real(k, *x))   # no work plan
    a.ask("Why did the orders fail this afternoon?")
    told = [m["content"] for seen in a.llm.seen for m in seen if m["role"] == "user"]
    assert any(BLAMED_LOGS_NUDGE.split("{")[0] in t for t in told) and len(ran) == 2
