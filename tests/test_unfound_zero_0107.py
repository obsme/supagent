"""(0.10.7, obs7dev-j) "How many errors did the orchestrator log on the 30th?" answered "**0** errors": its name was
refused before running as no value of the service field of the one log index that has one (its values: another
service), then searched in the log lines' text, which found nothing. A zero said when a value the question names was
refused so, and no query found it as a value of another field (or written another way), is sent back once: a text
search that finds nothing does not count records; where its records are is looked for, or their absence said."""
from __future__ import annotations

import json

REFUSED = ("tool error (not run: value): \"svc.name\" of logs-a has no value 'zqu-orch' (its values: zqu-shop), so this "
           "condition counts nothing. Use one of its values or the field that holds it.")
Q = "How many errors did zqu-orch log on 30 September?"


def step(sql: str, status: str = "done", result: str = "") -> dict:
    return {"tool": "execute_sql", "called": "execute_sql", "status": status,
            "args": {"request": {"database_id": 1, "sql": sql}}, "result": result}


def test_a_zero_for_a_name_no_field_holds():
    from supagent.agent import unfound_zero

    refused = step("SELECT COUNT(*) FROM \"logs-a\" WHERE \"svc.name\" = 'zqu-orch'", "error", REFUSED)
    text = step("SELECT COUNT(*) FROM \"logs-a\" WHERE \"body\" LIKE '%zqu-orch%' AND \"level\" = 'ERROR'")
    zero = "There were **0** errors logged by zqu-orch on September 30."
    assert unfound_zero(zero, [refused, text], Q) == ("zqu-orch", "svc.name", "logs-a")
    again = step("SELECT COUNT(*) FROM \"logs-a\" WHERE \"svc.name\" = 'zqu-orch'")        # sent again unchanged:
    assert unfound_zero(zero, [refused, again], Q) == ("zqu-orch", "svc.name", "logs-a")   # still no value of it
    other = step("SELECT COUNT(*) FROM \"logs-b\" WHERE \"app\" = 'zqu-orch' AND \"level\" = 'error'")
    assert unfound_zero(zero, [refused, other], Q) is None             # found as a value of another field: its 0
    cased = step("SELECT COUNT(*) FROM \"logs-a\" WHERE \"svc.name\" = 'ZQU-ORCH'")
    assert unfound_zero(zero, [refused, cased], Q) is None             # written as the data writes it
    assert unfound_zero("No logs of zqu-orch are collected: no index holds them.", [refused, text], Q) is None
    assert unfound_zero(zero, [refused, text], "How many errors were logged on 30 September?") is None


def test_the_zero_is_sent_back_once(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    def results(name, args):
        sql = (args.get("request") or {}).get("sql", "")
        if "\"svc.name\" = 'zqu-orch'" in sql:
            return REFUSED
        return json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 0}], "row_count": 1})

    exact = {"request": {"database_id": 1, "sql": "SELECT COUNT(*) AS n FROM \"logs-a\" WHERE \"svc.name\" = 'zqu-orch'"}}
    like = {"request": {"database_id": 1, "sql": "SELECT COUNT(*) AS n FROM \"logs-a\" WHERE \"body\" LIKE '%zqu-orch%'"}}
    zero = say("There were **0** errors logged by zqu-orch on 30 September.")
    honest = say("No logs of zqu-orch are collected: logs-a holds zqu-shop's only, and no other index has it.")
    a, ran = agent_with(monkeypatch, [call("execute_sql", exact), call("execute_sql", like), zero, honest, honest],
                        results=results)
    answer, trace = a.ask(Q, [])
    assert answer.startswith("No logs of zqu-orch") and len(ran) == 2
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user"]
    assert any("'zqu-orch' is no value of \"svc.name\" in logs-a" in c for c in sent)
