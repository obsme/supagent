"""(0.10.7, obs7dev-s) "<A service> warns about its cache miss ratio every night. Was that related to the problem of
<a day> in the morning?" was answered "Yes" from the incident's own spike at 10:00; the nightly bumps the queries had
returned (02:00, every day) were never looked at. A question of whether something that recurs was related to a
problem, whose answer never speaks of its recurrence, is sent back once to compare with the other nights."""
from __future__ import annotations

import json

Q = "Zq-inv warns about its cache miss ratio every night. Was that related to the problem of 2 October in the morning?"
YES = ("Yes: the cache miss ratio warning on 2 October in the morning was directly related to the problem that day: "
       "the misses of zq-cache rose to 75 per second at 10:00, and zq-inv's latency with them.")
NO = ("No: zq-inv's warning comes every night at 02:00, with the same misses as on the other nights; the problem of 2 "
      "October came from the change at 10:12 that halved zq-cache's memory.")


def test_a_recurrence_never_compared_is_sent_back_once(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    from supagent.agent import RECURRING_NUDGE

    rows = json.dumps({"success": True, "columns": [{"name": "day"}, {"name": "misses_at_two"}, {"name": "misses_at_ten"}],
                       "rows": [{"day": "2026-10-01", "misses_at_two": 5.3, "misses_at_ten": 9.3},
                                {"day": "2026-10-02", "misses_at_two": 5.3, "misses_at_ten": 75.0}], "row_count": 2})
    sql = {"request": {"database_id": 2, "sql": "SELECT day, misses_at_two, misses_at_ten FROM zq_cache_misses_by_day"}}
    a, _ran = agent_with(monkeypatch, [call("execute_sql", sql), say(YES), say(NO)], results=lambda n, args: rows)
    answer, _trace = a.ask(Q)
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user"]
    assert answer.startswith("No: zq-inv's warning comes every night")
    assert any(RECURRING_NUDGE.format(unit="night") in c for c in sent)
    b, _ran = agent_with(monkeypatch, [call("execute_sql", sql), say(NO)], results=lambda n, args: rows)
    answer, _trace = b.ask(Q)
    assert answer.startswith("No:") and not b.usage.get("nudges")       # the nights compared: nothing to send back
