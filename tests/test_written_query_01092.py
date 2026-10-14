"""(0.10.9.2) An answer that writes out the query its figures claim, without calling the tool, has that query run at
once and its answer written from the rows: no second LLM request asking for the call first (on the lab's model that
request took about two minutes and wrote the same query again)."""
from __future__ import annotations

WRITTEN = ("The revenue per channel:\n\n```sql\nSELECT \"CHANNEL\", SUM(\"AMOUNT\") AS revenue FROM \"shop-orders\" "
           "WHERE \"DAY\" = '2026-09-23' GROUP BY \"CHANNEL\"\n```\n\n| CHANNEL | revenue |\n| --- | --- |\n"
           "| WEB | 32942.79 |\n| MOBILE | 15000.00 |")


def test_a_query_written_in_the_answer_is_run_at_once(ctx, monkeypatch):
    from supagent.agent import Agent
    from test_agent_loop import agent_with, say

    monkeypatch.setattr(Agent, "_database_of", lambda self, table: 7)
    a, ran = agent_with(monkeypatch, [say(WRITTEN), say("A had 3 and B had 2 (from the rows).")])
    answer, trace = a.ask("What was the revenue per channel on 23 September?")
    assert [n for n, _a in ran] == ["execute_sql"]
    assert ran[0][1]["request"]["database_id"] == 7 and "SUM(\"AMOUNT\")" in ran[0][1]["request"]["sql"]
    assert len(a.llm.seen) == 2                          # the answer, then the one from the rows: no request between
    assert "required" not in a.llm.choices               # never asked again for the call
    assert answer.startswith("A had 3 and B had 2")
    assert not any(m.get("role") == "assistant" and "```sql" in str(m.get("content") or "") for m in a.llm.seen[-1])


def test_a_written_query_of_an_unknown_table_is_still_sent_back(ctx, monkeypatch):
    from supagent.agent import Agent
    from test_agent_loop import agent_with, call, say

    monkeypatch.setattr(Agent, "_database_of", lambda self, table: None)
    a, ran = agent_with(monkeypatch, [say(WRITTEN), call("execute_sql", {"request": {"database_id": 1, "sql": "SELECT 1"}}),
                                      say("Done from the rows.")])
    answer, _trace = a.ask("What was the revenue per channel on 23 September?")
    assert len(a.llm.seen) == 3 and ran                  # no database to run it on: asked for the call, as before
    assert answer == "Done from the rows."
