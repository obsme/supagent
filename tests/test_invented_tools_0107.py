"""(0.10.7, the open obs runs) "If <a cache server> goes down, what is affected?" and "What does a request go through
before it reaches <a part>?" were answered from system_links, under headings ("**Routing layer**", "**Alerts**",
"**Direct dependencies**"): the check of names no tool gave took the headings for names, made a tool compulsory, and
the model wrote in circles (30,000 characters) after seven of those send-backs, none of them an invented name. The
check is for an answer no tool result stands behind: no tool, or only a search that found nothing."""
from __future__ import annotations

import json

INVENTED = "which no tool returned in this answer"
LINKS = json.dumps({"part": "zq-gw", "routes": [["zq-gw", "zq-api", "zq-db"]], "if_it_fails": ["zq-api", "zq-db"]})


def sent_back(llm) -> bool:
    return any(INVENTED in str(m.get("content")) for m in llm.seen[-1] if m["role"] == "user")


def test_an_answer_built_from_the_map_is_not_checked_for_its_headings(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    said = ("**Routing layer**\n\nA request goes through zq-gw, then zq-api, then zq-db.\n\n**Alerts**\n\n"
            "- **Direct**: zq-api stops answering.")
    a, ran = agent_with(monkeypatch, [call("system_links", {"name": "zq-gw"}), say(said)],
                        results=lambda n, args: LINKS)
    a.names = a.names | {"system_links"}
    answer, _trace = a.ask("If zq-gw goes down, what is affected?")
    assert answer.startswith("**Routing layer**") and len(ran) == 1 and not sent_back(a.llm)


def test_names_with_no_tool_or_a_search_that_found_nothing_are_still_sent_back(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    made_up = say("The people who run zq-gw are:\n\n1. **Tracy**\n2. **Alice**")
    rows = json.dumps({"success": True, "columns": [{"name": "OWNER"}], "rows": [{"OWNER": "T37"}], "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": "SELECT \"OWNER\" FROM \"assets\" WHERE \"NAME\" = 'zq-gw'"}}
    empty = json.dumps({"query": "zq-gw owners", "results": []})
    a, ran = agent_with(monkeypatch, [call("search_knowledge", {"query": "zq-gw owners"}), made_up,
                                      call("execute_sql", sql), say("T37 runs zq-gw.")],
                        results=lambda n, args: empty if n == "search_knowledge" else rows)
    a.names = a.names | {"search_knowledge"}
    answer, _trace = a.ask("Who runs zq-gw?")
    assert answer.startswith("T37 runs zq-gw.") and [n for n, _args in ran] == ["search_knowledge", "execute_sql"]
    assert a.llm.choices[-2] == "required"                              # the step after the send-back reads them
