"""(0.10.12) A follow-up answered twice without a query, its SQL written in the text with a figure no query gave
("And on the 23rd?" after a describe_data lookup): the query it wrote is run and the answer is written from its rows
(0.10.7 ran it only when nothing at all had run; a lookup before it left the invented figure, marked)."""
from __future__ import annotations

import json

from test_agent_loop import agent_with, call, say

ROWS = json.dumps({"success": True, "columns": [{"name": "revenue"}], "rows": [{"revenue": 47942.79}], "row_count": 1})
WRITTEN = ("The revenue on 23 September was **56,760.22 EUR**.\n\n```sql\nSELECT SUM(\"AMOUNT\") AS revenue FROM "
           "\"sales\" WHERE \"DAY\" = '2026-09-23'\n```")


def test_the_query_written_after_a_lookup_is_run(ctx, monkeypatch):
    from supagent.agent import Agent

    monkeypatch.setattr(Agent, "_database_of", lambda self, table: 1)
    a, ran = agent_with(monkeypatch, [call("describe_data", {"index": "sales"}), say(WRITTEN), say(WRITTEN),
                                      say("The revenue on 23 September was 47,942.79 EUR."),
                                      say("The revenue on 23 September was 47,942.79 EUR.")],
                        results=lambda name, args: ROWS)
    answer, _trace = a.ask("What was the revenue on 23 September?")
    assert any(name == "execute_sql" for name, _args in ran)
    assert "47,942.79" in answer and "56,760.22" not in answer
