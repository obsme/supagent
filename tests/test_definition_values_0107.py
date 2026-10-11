"""(0.10.7) A term the team defined with some values of a field, computed with more values of that field: a wider rule
of the team put in place of the definition (agent.definition_links, by code)."""

from __future__ import annotations

import json

TERM = {"term": "fill rate", "definition": "The shipments dispatched in a week divided by the requests of that week, "
        "for the same warehouse."}
WIDE = ("SELECT COUNT(*) FROM \"shipments\" WHERE \"STAGE\" IN ('DISPATCHED', 'PACKED') AND \"WEEK\" = '2031-W05'")
ONE = "SELECT COUNT(*) FROM \"shipments\" WHERE \"STAGE\" = 'DISPATCHED' AND \"WEEK\" = '2031-W05'"
CHAIN = ("SELECT COUNT(*) FROM shipments s WHERE (s.\"STAGE\" = 'DISPATCHED' OR s.\"STAGE\" = 'PACKED') AND "
         "\"WEEK\" = '2031-W05'")
NOT_IN = "SELECT COUNT(*) FROM \"shipments\" WHERE \"STAGE\" NOT IN ('CANCELLED', 'LOST') AND \"WEEK\" = '2031-W05'"


def test_a_definition_value_taken_with_others_is_found(monkeypatch):
    from supagent.knowledge import definitions, glossary

    monkeypatch.setattr(glossary, "found", lambda q: [TERM] if "fill rate" in q.lower() else [])
    q = "What was the fill rate of the north warehouse in week 5?"
    found = definitions.widened(q, [WIDE])
    assert found and found[0] is TERM and "'PACKED'" in found[1] and "'DISPATCHED'" in found[1]
    assert definitions.widened(q, [CHAIN])                                     # F = 'A' OR F = 'B'
    assert definitions.widened(q, [ONE]) is None                               # the defined value alone
    assert definitions.widened(q, [WIDE, ONE]) is None                         # the last query decides
    assert definitions.widened(q, [ONE, WIDE])
    assert definitions.widened(q, [NOT_IN]) is None                            # values left out: not this
    assert definitions.widened("How many shipments were packed?", [WIDE]) is None     # no such term
    assert definitions.widened("And in week 6?", [WIDE]) is None               # no term, no question understood
    assert definitions.widened("And in week 6?", [WIDE], intent="What was the fill rate in week 6?")
    other = {"term": "pack rate", "definition": "The shipments packed in a week divided by its requests."}
    monkeypatch.setattr(glossary, "found", lambda q: [TERM, other])
    assert definitions.widened("The fill rate and the pack rate of week 5?", [WIDE]) is None   # both asked
    assert definitions.widened("The fill rate of week 5, packed ones too?", [WIDE]) is None    # the question says it
    loose = {"term": "fill rate", "definition": "How well the warehouse kept up with the requests: shipments dispatched."}
    monkeypatch.setattr(glossary, "found", lambda q: [loose])
    assert definitions.widened(q, [WIDE]) is None                              # says what it means, not what it counts
    monkeypatch.setattr(glossary, "found", lambda q: [TERM])                    # found by a shared word only
    assert definitions.widened("And the dispatch delay?", [WIDE]) is None      # not the term itself


def test_values_are_named_as_words():
    from supagent.knowledge.definitions import _conditions, _said_in

    assert _said_in("DISPATCHED", "the shipments dispatched in a week")
    assert not _said_in("DISPATCH", "the shipments dispatched in a week")       # a word, not a part of one
    assert _said_in("CLOSED_WON", "the deals closed won in the quarter")
    assert _said_in("EU", "the EU requests") and not _said_in("US", "requests sent to us")   # short: as written
    assert _conditions("SELECT 1 FROM t WHERE x IN ('A', 'B') AND y = 'C'") == [("x", ["A", "B"]), ("y", ["C"])]
    assert _conditions(NOT_IN) == [("WEEK", ["2031-W05"])]


def test_the_answer_is_sent_back_once(ctx, monkeypatch):
    from supagent.agent import DEFINITION_NUDGE
    from supagent.knowledge import glossary
    from test_agent_loop import agent_with, call, say

    monkeypatch.setattr(glossary, "found", lambda q: [TERM] if "fill rate" in q.lower() else [])
    from supagent.agent import Agent

    wider = "\n\nA rule of the team: shipments count when their STAGE is DISPATCHED or PACKED."
    rows = lambda n, args: json.dumps({"success": True, "row_count": 1, "rows": [  # noqa: E731
        {"fill_rate": 0.52 if "PACKED" in args["request"]["sql"] else 0.41}]})
    sql = lambda s: {"request": {"database_id": 1, "sql": s}}  # noqa: E731
    replies = [call("execute_sql", sql(WIDE)), say("The fill rate was 0.52."),
               call("execute_sql", sql(ONE)), say("The fill rate was 0.41.")]
    a, _ran = agent_with(monkeypatch, replies, results=rows)

    def blocks(self, q, shown=None):                   # the wider rule given with the question (the team's words)
        self.people_words = wider
        return wider

    monkeypatch.setattr(Agent, "_question_blocks", blocks)
    answer, _trace = a.ask("What was the fill rate in week 2031-W05?")
    assert answer.startswith("The fill rate was 0.41") and a.usage.get("nudges") == 1
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith("(Check")]
    assert sent and sent[0].startswith(DEFINITION_NUDGE.split("{term}")[0]) and "'PACKED'" in sent[0]
