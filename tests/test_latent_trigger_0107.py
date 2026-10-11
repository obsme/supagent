"""(0.10.7, obs7dev W07.1 on two builds) "<A service> returned errors on <a day> around 09:00. Find the root cause."
answered with the version deployed the evening before (OOM kills, the change record), nothing said of what began at
09:00 (a promotion's orders that set the leak off); a sentence in the instructions did not change it. An
investigation's answer that blames a change made hours before the effect began, and names nothing that began then,
is sent back once to look for it."""
from __future__ import annotations

Q = "Zq-shop returned errors on 2 October around 09:00. Find the root cause."
BLAMED = ("## Root cause: zq-shop 2.4 ran out of memory\n\n| Time | Event |\n|---|---|\n"
          "| **2026-10-01 18:00** | CHG-9: zq-shop deployed from 2.3 to **2.4** |\n| 09:00 | zq-shop-a OOMKilled |\n"
          "| 09:38 | Rollback to 2.3 |\n\nThe deployment of 2.4 brought a memory leak.")


def test_a_change_of_the_evening_before_without_its_trigger():
    from supagent.agent import latent_unexplained

    assert latent_unexplained(Q, BLAMED, 2026) == ("on 2026-10-01 at 18:00", "02 October 09:00", 15)
    said = BLAMED + "\nThe promotion that started at 09:00 tripled the orders and set the leak off."
    assert latent_unexplained(Q, said, 2026) is None                         # the trigger said
    nothing = BLAMED + "\nNothing else began at 09:00: the leak grew until the limit."
    assert latent_unexplained(Q, nothing, 2026) is None                      # said that nothing began then
    close = BLAMED.replace("2026-10-01 18:00", "2026-10-02 08:40")
    assert latent_unexplained(Q, close, 2026) is None                        # 20 minutes before: the change itself
    assert latent_unexplained("Why did zq-shop fail?", BLAMED, 2026) is None  # no onset in the question


def test_it_is_sent_back_once(ctx, monkeypatch):
    import json

    from test_agent_loop import agent_with, call, say

    from supagent.agent import Agent

    monkeypatch.setattr(Agent, "_investigating", lambda self, q: True)
    monkeypatch.setattr(Agent, "_new_ledger", lambda self, q, h, b: None)          # no work plan in this test
    events = json.dumps({"success": True, "columns": [{"name": "at"}, {"name": "what"}], "rows": [
        {"at": "2026-10-01 18:00", "what": "CHG-9 zq-shop 2.3 -> 2.4"}, {"at": "2026-10-02 09:00", "what": "OOMKilled"},
        {"at": "2026-10-02 09:38", "what": "rollback to 2.3"}], "row_count": 3})
    coupons = json.dumps({"success": True, "columns": [{"name": "coupon"}, {"name": "first"}],
                          "rows": [{"coupon": "ZQ50", "first": "2026-10-02 09:00"}], "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": "SELECT at, what FROM zq_events WHERE at >= '2026-10-01'"}}
    sql2 = {"request": {"database_id": 1, "sql": "SELECT coupon, MIN(at) AS first FROM zq_orders GROUP BY coupon"}}
    found = BLAMED + "\nThe ZQ50 promotion that started at 09:00 set the leak off."
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), say(BLAMED), call("execute_sql", sql2)] + [say(found)] * 3,
                        results=lambda n, args: coupons if "coupon" in str(args) else events)
    answer, _trace = a.ask(Q)
    assert "ZQ50 promotion" in answer and len(ran) == 2
    assert any("hours before the effect began" in str(m["content"]) for m in a.llm.seen[-1] if m["role"] == "user")
