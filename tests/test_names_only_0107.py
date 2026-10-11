"""(0.10.7, obs7dev-x) "Which metrics compare the checkout pods' memory with their limit?": the first query of their
values was sent back (names asked), then the model wrote another query (a column fixed) and four more ran: 7 calls,
over the question's budget of 6, the names right. Each new query of values is sent back (two at most); the same
query sent again runs (when its values are needed to tell which ones)."""
from __future__ import annotations

import json


def test_each_new_query_of_values_is_sent_back_for_names_asked(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    q = lambda sql: {"request": {"database_id": 2, "sql": sql}}  # noqa: E731
    rows = json.dumps({"success": True, "columns": [{"name": "pod"}], "rows": [{"pod": "p1"}], "row_count": 1})
    named = say("mem_usage and mem_limit: the pods' usage and limit.")
    a, ran = agent_with(monkeypatch, [call("execute_sql", q("SELECT pod, AVG(value) FROM mem_usage GROUP BY pod")),
                                      call("execute_sql", q("SELECT DISTINCT pod FROM mem_usage")),
                                      call("execute_sql", q("SELECT DISTINCT pod FROM mem_limit")),
                                      named, named, named], results=lambda n, args: rows)
    answer, trace = a.ask("Which metrics compare the pods' memory with their limit?", [])
    assert answer.startswith("mem_usage and mem_limit") and str(trace).count("names asked") == 2
    assert len(ran) == 1                                          # the third new query: two refusals at most
    b, ran_b = agent_with(monkeypatch, [call("execute_sql", q("SELECT 1 FROM mem_usage")),
                                        call("execute_sql", q("SELECT 1 FROM mem_usage")), named, named, named],
                          results=lambda n, args: rows)
    b.ask("Which metrics compare the pods' memory with their limit?", [])
    assert len(ran_b) == 1                                        # sent again unchanged: it runs
