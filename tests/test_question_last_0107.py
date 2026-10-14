"""(0.10.7) "Show me the late ones from yesterday.": the agent asked back with its question first and the readings
listed under it; neither the agent nor the checks took that for a question back (they read the last line)."""
from __future__ import annotations

from supagent.agent import asks_back, question_last


def test_the_question_back_goes_after_its_readings():
    first = ("When you say \"the late ones\", which of these do you mean?\n\n1. **Shipments** delivered after their "
             "promised date\n2. **Reports** delivered after their deadline\n3. **Batch jobs** that ran late")
    out = question_last(first)
    assert asks_back(out) and out.endswith("which of these do you mean?")
    assert out.startswith("1. **Shipments**") and "3. **Batch jobs** that ran late" in out
    intro = ("You mention the late ones without saying which. Could you clarify which of these you'd like to see?\n\n"
             "1. Late reports\n2. Late shipments")
    assert asks_back(question_last(intro))


def test_anything_else_stays():
    done = "Which of these do you mean?\n\n1. Shipments\n2. Reports\n\nShipments: 12 were late yesterday."
    assert question_last(done) == done                   # a result after the list: not only a question back
    asked = "1. Shipments\n2. Reports\n\nWhich of these do you mean?"
    assert question_last(asked) == asked                  # already last
    answer = "There were 12 late shipments yesterday."
    assert question_last(answer) == answer


def test_an_answer_that_stopped_in_the_middle():
    """(0.10.7) "The metrics that show the database-side impact are in **Observ" was the whole answer (13 tokens)."""
    from supagent.agent import cut_short

    assert cut_short("The metrics that show the database-side impact are in **Observ")
    assert cut_short("Several reasons (the first one", None) and cut_short("A long answer.", "length")
    assert not cut_short("4 times: the pods were killed twice each.")
    assert not cut_short("No data for it.") and not cut_short("Yes, **orders-db** was fine.")


def test_a_simple_question_searches_the_knowledge_once(ctx, monkeypatch):
    """(0.10.7) "How many payment authorizations ended in an error?": three describe_data and two search_knowledge
    before the query, over the question's budget of calls."""
    from test_agent_loop import agent_with, call, say

    from supagent import agent as agent_mod

    a, ran = agent_with(monkeypatch, [call("search_knowledge", {"query": "payment errors"}),
                                      call("search_knowledge", {"query": "payment logs"}),
                                      say("81 authorizations ended in an error.")] + [say("No query ran.")] * 4)
    a.names = a.names | {"search_knowledge"}
    a.ask("How many payment authorizations ended in an error yesterday?")
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"]
    assert any(c.startswith(agent_mod.SEARCH_ONCE[:40]) for c in sent), sent


def test_a_simple_question_lists_no_databases_after_reading_the_dictionary(ctx, monkeypatch):
    """(0.10.7, obs7dev-k) "How many payment authorizations ended in an error ...?": the metric found by the first
    read, then the databases listed and three log indices queried before it (11 calls, over a simple question's
    budget). After a dictionary read and before any query, list_databases is refused once: the reads give each
    table's database."""
    from test_agent_loop import agent_with, call, say

    from supagent import agent as agent_mod

    a, ran = agent_with(monkeypatch, [call("describe_data", {"topic": "payment errors"}), call("list_databases", {}),
                                      call("list_databases", {}), say("81 authorizations ended in an error.")] +
                        [say("No query ran.")] * 4)
    a.names = a.names | {"describe_data", "list_databases"}
    a.ask("How many payment authorizations ended in an error yesterday?")
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"]
    assert sum(c.startswith(agent_mod.LISTED_ENOUGH[:40]) for c in sent) == 1, sent      # once: sent again, it runs


def test_an_answer_cut_in_a_table_or_a_code_block(ctx):
    """(0.10.7, obs7dev-n) "Which metrics show it?" was answered with the first metric and its table, cut at "| 15"
    (555 characters, the other metrics never said): a table row or a code block left open ends an answer cut in the
    middle, whatever its length."""
    from supagent.agent import cut_short

    head = "## The metrics that show it\n\nThe first one moved most:\n\n" + "The values rose all afternoon. " * 12
    assert cut_short(head + "\n\n| Time | Value |\n|------|-------|\n| 14:00 | 0 |\n| 15")
    assert cut_short(head + "\n\n```sql\nSELECT MAX(value) FROM zq")
    assert not cut_short(head + "\n\n| Time | Value |\n|------|-------|\n| 14:00 | 0 |")
    assert not cut_short(head + "\n\n```sql\nSELECT 1\n```\n\nThat is all.")


def test_a_question_back_with_a_lead_in_and_a_closing_request_ends_with_its_question():
    """(0.10.9.2) "How many requests failed?" asked back with the question first, then "For example, are you looking
    for:", the readings, and "Please specify the component and the time range." last: a question back the user and the
    checks did not see as one (its last line was no question)."""
    text = ("Which service's failed requests would you like me to count, and for what time period?\n\n"
            "For example, are you looking for:\n*   **Orders** (failed vs. placed)?\n*   **Billing API** requests?\n"
            "*   **All services** combined?\n\n"
            "Please specify the component and the time range (e.g., today, yesterday, last 24 hours).")
    out = question_last(text)
    assert asks_back(out) and out.endswith("and for what time period?")
    assert "For example, are you looking for:" in out and "Please specify the component" in out
    para = ("Several kinds of errors are kept. To give you the right number, could you say which kind and for which "
            "period (today, yesterday)?\n\nThe sources are:\n*   **Application errors**: failures of the applications."
            "\n*   **Job errors**: errors of the batch jobs.\n*   **All of them**: one total.")
    out = question_last(para)
    assert asks_back(out) and out.endswith("for which period (today, yesterday)?")
    done = ("Which kind do you mean?\n\nThe sources are:\n* Application errors\n* Job errors\n\n"
            "Application errors: 12 yesterday.")
    assert question_last(done) == done                    # a result after the list: no question back
