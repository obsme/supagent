"""(0.10.7) "Did the frontend deployment of that afternoon play a role?" was answered with the whole investigation
again and "the frontend deployment likely exacerbated the problem" (a decoy: its slow spans were the checkout's,
seen from upstream); "Which metrics show it on the database side?" was answered with three metrics named from the
data block, none read (the ones that moved were others)."""
from __future__ import annotations

import json

from test_agent_loop import agent_with, call, say


def test_a_suspect_given_a_part_with_a_hedge():
    from supagent.agent import SUSPECT_ASKED, suspect_confirmed

    q = "Did the frontend deployment of that afternoon play a role?"
    assert SUSPECT_ASKED.search(q) and SUSPECT_ASKED.search("Was the cache involved in the failures?")
    assert not SUSPECT_ASKED.search("Which trader contributed the most to the official PnL?")   # no yes or no
    said = ("## Root cause\nThe export held long transactions. The **web deployment** likely exacerbated the problem "
            "by introducing less efficient request handling.")
    assert suspect_confirmed(q, said)
    assert not suspect_confirmed(q, "No: there is no evidence that the web deployment contributed; the errors name "
                                    "the database.")
    assert not suspect_confirmed(q, "No. The deployment is unlikely to have contributed: its error rate did not move.")


def test_which_metrics_show_it_is_read_from_the_data(ctx, monkeypatch):
    from supagent.agent import SHOW_NUDGE

    named = say("The database side shows in **db_deadlocks**, **db_commits** and **db_rollbacks**.")
    rows = json.dumps({"success": True, "columns": [{"name": "t"}, {"name": "max_tx_s"}],
                       "rows": [{"t": "14:00", "max_tx_s": 4740}], "row_count": 1})
    a, ran = agent_with(monkeypatch, [named, call("execute_sql", {"sql": "SELECT MAX(value) FROM tx_duration"}),
                                      say("The longest open transaction reached 4740 s at 14:00 (tx_duration)."),
                                      say("The longest open transaction reached 4740 s at 14:00 (tx_duration).")],
                        results=lambda n, args: rows)
    history = [{"role": "user", "content": "The shop was slow on the 28th in the afternoon. What was the cause?"},
               {"role": "assistant", "content": "A long export held transactions open on the orders database from "
                                                "14:00 to 15:20; the shop's inserts waited for its locks."}]
    answer, _trace = a.ask("Which metrics show it on the database side?", history)
    sent = [m["content"] for m in a.llm.seen[1] if m["role"] == "user"]
    assert SHOW_NUDGE in sent and "required" in a.llm.choices and len(ran) == 1
    assert answer.startswith("The longest open transaction reached 4740 s")


def test_which_metrics_asks_for_names_not_values():
    """"Which metrics compare the pods' memory with their limit?" took eight calls (three failed queries of values
    nobody asked for): such a question gets the note to name them from the dictionary."""
    from supagent.agent import FIGURE_WORDS, SHOW_ASKED, WHICH_DATA_ASKED

    def noted(q: str) -> bool:
        return bool(WHICH_DATA_ASKED.search(q)) and not FIGURE_WORDS.search(q) and not SHOW_ASKED.search(q)

    assert noted("Which metrics compare the pods' memory with their limit?")
    assert noted("What fields hold the user of a session?")
    assert not noted("Which metrics show it on the database side?")             # evidence: read from the data
    assert not noted("Which metrics went over their limit on 28 September?")     # a period: figures
    assert not noted("How many orders were placed yesterday?")
