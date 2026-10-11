"""(0.10.8) "Which applications consume the <topic> events, directly or through the mirror?" answered from the summary
given with the question (one describe_data call, no system_links): two consumers of five missed. A question of how
parts are linked, answered with no call of the map's tool, is sent back once with that tool to call."""

from __future__ import annotations

import json

Q = "Which applications consume the topic-x events, directly or through the mirror?"
FOUND = json.dumps({"links": [{"from": "app-a1", "kind": "consumes", "to": "topic-x"},
                              {"from": "app-c3", "kind": "consumes", "to": "mirror-of-topic-x"}]})


def _agent(monkeypatch, replies):
    from supagent.agent import Agent
    from test_agent_loop import agent_with

    rows = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 12}], "row_count": 1})
    a, ran = agent_with(monkeypatch, replies, results=lambda n, args: rows if n == "execute_sql" else FOUND)
    a.names = a.names | {"system_links", "describe_data"}
    monkeypatch.setattr(Agent, "_specs_for", lambda self, q: [{"function": {"name": "system_links"}}])
    return a, ran


def test_an_answer_of_links_from_the_summary_reads_the_map_first(ctx, monkeypatch):
    from test_agent_loop import call, say

    a, ran = _agent(monkeypatch, [call("describe_data", {"topic": "topic-x consumers"}), say("app-a1 consumes it."),
                                  call("system_links", {"names": ["topic-x"]}),
                                  say("app-a1 consumes it directly, app-c3 through the mirror.")])
    answer, _trace = a.ask(Q)
    assert answer.startswith("app-a1 consumes it directly") and [r[0] for r in ran] == ["describe_data", "system_links"]


def test_not_when_the_map_was_read_or_the_question_is_of_other_things(ctx, monkeypatch):
    from test_agent_loop import call, say

    a, ran = _agent(monkeypatch, [call("system_links", {"names": ["topic-x"]}), say("app-a1 and app-c3 consume it.")])
    assert a.ask(Q)[0].startswith("app-a1 and app-c3") and len(ran) == 1
    sql = {"request": {"database_id": 1, "sql": "SELECT COUNT(*) AS n FROM orders"}}
    a, ran = _agent(monkeypatch, [call("execute_sql", sql), say("12 orders were placed.")])
    assert a.ask("How many orders were placed on 2 March?")[0].startswith("12 orders") and len(ran) == 1


def test_not_for_a_count_or_an_answer_from_the_data(ctx, monkeypatch):
    from test_agent_loop import call, say

    a, ran = _agent(monkeypatch, [call("describe_data", {"topic": "orders"}), say("4 orders were affected.")] +
                    [say("4 orders were affected.")] * 4)
    assert a.ask("How many orders were affected by the outage?")[0].startswith("4 orders") and \
        [r[0] for r in ran] == ["describe_data"]
    sql = {"request": {"database_id": 1, "sql": "SELECT COUNT(*) AS n FROM consumed"}}
    a, ran = _agent(monkeypatch, [call("execute_sql", sql), say("12 messages were consumed.")])
    assert a.ask("Which topics were consumed most yesterday?")[0].startswith("12 messages") and len(ran) == 1
