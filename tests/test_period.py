"""The period of the question is the period of the queries: a date or a period in the question needs a filter
on the time of the data (the index's time field, ts for metrics), not on business dates unless asked; one
whole day needs the whole of that day. Sent back once. A reply to the agent's question back comes with the
question it answers; a chart asked for the top N that shows more is said NOT DONE; "n1-n5" of given names
is not a name of the model's own."""

from __future__ import annotations

import datetime as dt
import json
import types

from test_knowledge import world  # noqa: F401  (the fixture)

TODAY = dt.date(2026, 9, 24)


def test_the_days_of_a_question():
    from supagent.knowledge.period import days_named, has_period, whole_day

    d23 = dt.date(2026, 9, 23)
    assert days_named("How many jobs failed on 23 September?", TODAY) == [d23]
    assert days_named("Failures on September 23rd and on 2026-09-16", TODAY) == [d23, dt.date(2026, 9, 16)]
    assert days_named("Combien de jobs ont échoué le 23 septembre ?", TODAY) == [d23]
    assert days_named("How many jobs failed yesterday?", TODAY) == [d23]
    assert whole_day("How many batch jobs failed on 23 September?", TODAY) == d23
    assert whole_day("How many jobs failed during the night batch window on 23 September?", TODAY) is None
    assert whole_day("Failed jobs on 23 September between 02:00 and 06:00", TODAY) is None
    assert whole_day("Failed jobs on 23 September compared with the previous weeks", TODAY) is None
    assert whole_day("Failed jobs on 23 September vs 16 September", TODAY) is None
    assert has_period("What happened last week?", TODAY) and has_period("Is it normal right now?", TODAY)
    assert not has_period("What does the application BILLING do, and on which servers do its jobs run?", TODAY)


def _sql(sql: str) -> dict:
    return {"request": {"database_id": 1, "sql": sql}}


def test_a_query_that_misses_the_period_is_sent_back(world):
    from supagent.knowledge.period import refusal

    q = "How many jobs failed on 23 September?"
    day = "\"ts\" >= '2026-09-23 00:00' AND \"ts\" < '2026-09-24 00:00'"
    assert refusal(q, "execute_sql", _sql(f'SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'FAILED\' AND {day}'),
                   TODAY) is None
    no_time = refusal(q, "execute_sql", _sql('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'FAILED\''), TODAY)
    assert no_time.startswith("tool error (not run: period)") and 'time field "ts" of jobs' in no_time
    business = refusal(q, "execute_sql", _sql('SELECT COUNT(*) FROM "jobs" WHERE "POSITION_LABEL" = \'D-1\''), TODAY)
    assert "position (business) date" in business
    assert refusal("How many jobs of the position date D-1 failed?", "execute_sql",
                   _sql('SELECT COUNT(*) FROM "jobs" WHERE "POSITION_LABEL" = \'D-1\''), TODAY) is None
    night = refusal(q, "create_virtual_dataset", _sql(
        "SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '2026-09-23 00:00' AND \"ts\" < '2026-09-23 06:00'"), TODAY)
    assert "covers only 00:00 to 06:00" in night
    other = refusal(q, "execute_sql", _sql(
        "SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '2026-09-24 00:00' AND \"ts\" < '2026-09-25 00:00'"), TODAY)
    assert "this query's dates are 2026-09-24, 2026-09-25" in other
    assert refusal(q, "execute_sql", _sql(
        "SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" BETWEEN '2026-09-23 00:00:00' AND '2026-09-23 23:59:59'"),
        TODAY) is None
    assert refusal(q, "execute_sql", _sql('SELECT DISTINCT "NODE" FROM "jobs"'), TODAY) is None     # values listed
    assert refusal(q, "execute_sql", _sql('SELECT * FROM "jobs" LIMIT 10'), TODAY) is None           # a look
    assert refusal(q, "execute_sql", _sql('SELECT * FROM "jobs" WHERE "STATUS" = \'FAILED\' LIMIT 10'), TODAY)
    assert refusal("Which servers run the jobs?", "execute_sql", _sql('SELECT COUNT(*) FROM "jobs"'), TODAY) is None
    cpu = refusal("CPU busy % yesterday", "execute_sql", _sql('SELECT AVG(value) FROM "node_cpu_seconds_total"'),
                  TODAY)
    assert 'time field "ts" of node_cpu_seconds_total' in cpu
    assert refusal(q, "list_charts", {}, TODAY) is None


def test_the_checks_before_a_call_say_every_reason_at_once(world, monkeypatch):
    from test_agent_loop import agent_with, call, say

    from supagent.knowledge import period

    monkeypatch.setattr(period, "_now", lambda: dt.datetime(2026, 9, 24, 23, 30))
    bad = _sql('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'FAILED\'')
    good = _sql("SELECT COUNT(*) FROM \"jobs\" WHERE \"STATUS\" = 'FAILED' AND \"ts\" >= '2026-09-23 00:00' AND "
                "\"ts\" < '2026-09-24 00:00'")
    a, ran = agent_with(monkeypatch, [call("execute_sql", bad), call("execute_sql", good), say("12 jobs failed.")],
                        results=lambda n, args: json.dumps({"success": True, "columns": ["n"], "rows": [{"n": 12}]}))
    answer, trace = a.ask("How many jobs failed on 23 September?")
    assert answer == "12 jobs failed." and ran == [("execute_sql", good)]
    assert "not run: period" in trace[0]["result"]


def test_a_reply_to_a_question_back_comes_with_the_question(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    a, _ran = agent_with(monkeypatch, [say("BILLING_API had 358 failed jobs.")])
    history = [{"role": "user", "content": "Show me the errors of BILLING_API on 23 September."},
               {"role": "assistant", "content": "Do you mean the failed jobs, or the HTTP 5xx errors of its service?"}]
    msgs = a.prompt("The failed jobs.", history)
    last = msgs[-1]["content"]
    assert "Show me the errors of BILLING_API on 23 September." in last
    assert 'You asked: "Do you mean the failed jobs, or the HTTP 5xx errors of its service?" My reply: The failed ' \
           "jobs." in last
    assert a.intent_text.startswith("Show me the errors of BILLING_API") and "23 September" in a.question
    plain = a.prompt("How many jobs failed on 23 September?", [
        {"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hello! What do you want to know?"}])
    assert plain[-1]["content"].endswith("How many jobs failed on 23 September?")


def test_a_chart_asked_for_the_top_n_that_shows_more_is_not_done(ctx):
    from supagent.agent import ChartGuard, categories, top_n, wanted_top

    z = "In the dashboard, change the bar chart to show only the 5 applications with the most failures"
    y = "a line chart of the CPU busy % per hour of the 5 busiest servers and a bar chart per application"
    assert wanted_top("APPLICATION", top_n(z)) == 5 and wanted_top("node", top_n(y)) == 5
    assert wanted_top("APPLICATION", top_n(y)) is None and wanted_top("APPLICATION", top_n("Failed jobs")) is None
    rows = [{"APPLICATION": f"APP{i}", "SUM(failed)": 10 - i} for i in range(10)]
    assert categories(rows) == ("APPLICATION", 10)
    assert categories([{"__timestamp": "2026-09-23T00:00:00", "srv-1": 3}]) == (None, 0)
    agent = types.SimpleNamespace(question=z, superset=types.SimpleNamespace(
        available=True, call=lambda name, args: json.dumps({"data": rows, "row_count": 10})))
    note = ChartGuard(agent).shows(141)
    assert "NOT DONE: the question asks for 5 and this chart shows 10 APPLICATION values" in note
    agent.question = "Change the bar chart title"
    assert "NOT DONE" not in ChartGuard(agent).shows(141)


def test_a_range_of_given_names_is_not_a_name_of_its_own():
    from supagent.grounding import ungrounded

    msgs = [{"role": "user", "content": "Which nodes?"},
            {"role": "tool", "content": json.dumps({"rows": [{"node": f"n{i}"} for i in range(1, 6)]})}]
    assert ungrounded("The nodes are n1-n5.", msgs) == []
    assert ungrounded("The nodes are n1-n9.", msgs) == ["n1-n9"]


def test_how_many_answered_with_shares_only_is_sent_back_once(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    from supagent.agent import COUNT_NUDGE, missing_count

    q = "What was the availability of each HTTP service, and how many 5xx errors did each one have?"
    assert missing_count(q, "A: 1.00% of errors, 99.00% available.")
    assert not missing_count(q, "A: 1.00% of errors (51,986 errors), 99.00% available.")
    assert not missing_count("How many jobs failed on 23 September?", "None failed on 23 September.")
    assert not missing_count("What was the availability?", "A: 99.00% available.")
    assert missing_count("How many jobs failed on 23 September?", "On 2026-09-23 at 02:00, see srv-amer-002.")
    rows = lambda n, args: json.dumps({"success": True, "columns": ["app", "pct", "n"],  # noqa: E731
                                       "rows": [{"app": "A", "pct": 1.0, "n": 51986}]})
    a, _ran = agent_with(monkeypatch, [call("execute_sql", {"request": {"database_id": 1, "sql": "SELECT 1"}}),
                                       say("A: 1.00% of errors."), say("A: 51,986 errors, 1.00% of the requests.")],
                         results=rows)
    answer, _trace = a.ask(q)
    assert answer.startswith("A: 51,986 errors") and COUNT_NUDGE in [m["content"] for m in a.llm.seen[-1]]


def test_a_list_continued_past_the_results_is_cut_after_the_check(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    from supagent.agent import without_extrapolation

    text = ("BILLING runs on 200 servers:\n- `srv-amer-000`\n- `srv-amer-001`\n- ... continuing up to `srv-amer-199`\n"
            "Some jobs have no server.")
    cut, left = without_extrapolation(text, ["srv-amer-199"])
    assert "srv-amer-199" not in cut and "srv-amer-001" in cut and left == []
    assert without_extrapolation("It runs on srv-x-9.", ["srv-x-9"]) == ("It runs on srv-x-9.", ["srv-x-9"])  # no range
    rows = lambda n, args: json.dumps({"success": True, "columns": ["NODE"],  # noqa: E731
                                       "rows": [{"NODE": "srv-amer-000"}, {"NODE": "srv-amer-001"}]})
    a, _ran = agent_with(monkeypatch, [call("execute_sql", {"request": {"database_id": 1, "sql": "SELECT 1"}}),
                                       say(text), say(text)], results=rows)
    answer, _trace = a.ask("On which servers do the BILLING jobs run?")
    assert "srv-amer-199" not in answer and "(Check:" not in answer and answer.startswith("BILLING runs on 200")


def test_a_short_reply_after_an_answer_completes_the_question(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    a, _ran = agent_with(monkeypatch, [say("ok")])
    history = [{"role": "user", "content": "Show me the errors of BILLING_API on 23 September."},
               {"role": "assistant", "content": "BILLING_API had 358 errors. (Not read for this answer: ...)"}]
    last = a.prompt("The failed jobs.", history)[-1]["content"]
    assert last.endswith("Show me the errors of BILLING_API on 23 September.\n(About your answer above: The failed "
                         "jobs.) Answer my question again with this.")
    fresh = a.prompt("Show me the dashboards.", history)[-1]["content"]
    assert fresh.endswith("Show me the dashboards.")


def test_a_span_of_days_is_queried_exactly(world):
    from supagent.knowledge.period import ranges_named, refusal

    q = ("Weekly review for the week of 14 to 20 September, compared with the week of 7 to 13 September: jobs per "
         "business line.")
    assert ranges_named(q, TODAY) == [(dt.datetime(2026, 9, 14), dt.datetime(2026, 9, 21)),
                                      (dt.datetime(2026, 9, 7), dt.datetime(2026, 9, 14))]
    week = lambda a, b: _sql(f"SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '{a}' AND \"ts\" < '{b}'")  # noqa: E731
    assert refusal(q, "execute_sql", week("2026-09-14 00:00", "2026-09-21 00:00"), TODAY) is None
    assert refusal(q, "execute_sql", week("2026-09-07 00:00", "2026-09-14 00:00"), TODAY) is None
    late = refusal(q, "execute_sql", week("2026-09-14 00:00", "2026-09-21 06:00"), TODAY)
    assert "covers 2026-09-14 00:00 to 2026-09-21 06:00" in late
    assert refusal(q + " And the previous 4 weeks?", "execute_sql", week("2026-08-17 00:00", "2026-09-14 00:00"),
                   TODAY) is None                                                               # another span
    assert refusal("Jobs from 14 to 20 September between 02:00 and 06:00", "execute_sql",
                   week("2026-09-14 02:00", "2026-09-20 06:00"), TODAY) is None               # hours: not whole days


def test_a_follow_up_restating_the_chats_results_needs_no_new_query(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    history = [{"role": "user", "content": "Show me the errors of BILLING_API on 23 September."},
               {"role": "assistant", "content": "BILLING_API had 358 failed jobs on 23 September. (Not read for this "
                                                "answer: BILLING_API is also a value of the label app of 2 metrics.)"}]
    a, _ran = agent_with(monkeypatch, [say("BILLING_API had 358 failed jobs on 23 September.")])
    answer, _trace = a.ask("The failed jobs.", history)
    assert answer == "BILLING_API had 358 failed jobs on 23 September." and not a.usage.get("nudges")
    b, _ran = agent_with(monkeypatch, [say("BILLING_API had 412 failed jobs.")] * 3)
    answer, _trace = b.ask("The failed jobs.", history)                  # a number of its own: sent back, marked
    assert b.usage.get("nudges") and "(Check:" in answer


def test_a_follow_up_is_grounded_in_the_previous_answer_only(ctx, monkeypatch):
    """A follow-up answered without a query passes when it restates the previous answer; a number found only in an
    older answer of the subject (a limit, another book's figure) is no answer: sent back for a query."""
    from test_agent_loop import agent_with, say

    history = [{"role": "user", "content": "What is the VaR limit of the desk?"},
               {"role": "assistant", "content": "The VaR limit of the desk is 10,000 EUR."},
               {"role": "user", "content": "Which book lost the most on 22 September?"},
               {"role": "assistant", "content": "EQ_BOOK_A lost the most on 22 September: -248,707 EUR."}]
    a, _ran = agent_with(monkeypatch, [say("The VaR of that book was 10,000 EUR.")] * 3)
    a.ask("What was that book's VaR?", history)
    assert a.usage.get("nudges")                                         # a figure of an older answer: a query
    b, _ran = agent_with(monkeypatch, [say("EQ_BOOK_A lost 248,707 EUR on 22 September.")])
    b.ask("How much did it lose?", history)
    assert not b.usage.get("nudges")                                     # the previous answer, restated


def test_a_follow_up_naming_what_no_tool_gave_is_sent_back_then_must_call_a_tool(ctx, monkeypatch):
    """"Which traders work on it?" after the book that lost the most: answered with no tool, "1. **Tracy** 2. **Alice**
    3. **Bob**" passed as a follow-up restating the chat (no number, no name with a digit; 0.9.1). Names the previous
    answer does not hold take the exemption away; given again with no query, a tool call is made compulsory once."""
    import json

    from test_agent_loop import agent_with, call, say

    history = [{"role": "user", "content": "Which book lost the most money on 22 September, in official PnL?"},
               {"role": "assistant", "content": "**EQ_BOOK_A** lost the most on 22 September: -248,707 EUR."}]
    made_up = say("The traders who work on the **EQ_BOOK_A** book are:\n\n1. **Tracy**\n2. **Alice**\n3. **Bob**")
    sql = {"request": {"database_id": 1, "sql": "SELECT DISTINCT \"TRADER\" FROM \"pnl\" WHERE \"BOOK\" = 'EQ_BOOK_A'"}}
    rows = json.dumps({"success": True, "columns": [{"name": "TRADER"}], "rows": [{"TRADER": "T37"}, {"TRADER": "T38"}],
                       "row_count": 2})
    a, ran = agent_with(monkeypatch, [made_up, made_up, call("execute_sql", sql), say("T37 and T38 work on EQ_BOOK_A.")],
                        results=lambda n, args: rows)
    answer, _trace = a.ask("Which traders work on it?", history)
    assert answer == "T37 and T38 work on EQ_BOOK_A." and len(ran) == 1
    assert a.llm.choices == [None, None, "required", None]               # compulsory once, after two answers
    restated = say("**EQ_BOOK_A** lost 248,707 EUR on 22 September.")
    b, _ran = agent_with(monkeypatch, [restated])
    b.ask("How much did it lose?", history)
    assert not b.usage.get("nudges") and b.llm.choices == [None]         # the previous answer, restated: as before


def test_a_follow_up_naming_a_value_no_query_used_needs_its_own_query(ctx, monkeypatch):
    """"And the flash PnL?" after the official PnL of a desk: answered with no tool, the official figure given again
    as the flash one (no number or name new to the chat: it passed as a restating follow-up, 0.9.2 candidate A).
    FLASH is a value of a field of the table the previous answer read, and no query of it used it: another figure,
    its own query (compulsory after the answer sent back)."""
    import json

    from test_agent_loop import agent_with, call, say

    from supagent.knowledge import carry

    values = {"flash": "PNL_STATUS", "official": "PNL_STATUS", "restated": "PNL_STATUS", "eq_book_a": "BOOK"}
    monkeypatch.setattr(carry, "field_values", lambda tables: values if "pnl" in tables else {})
    prev = ("SELECT SUM(\"PNL_TOTAL\") FROM \"pnl\" WHERE \"DESK\" = 'EQ_DESK' AND \"PNL_STATUS\" IN ('OFFICIAL', "
            "'RESTATED') AND \"COB_DATE\" >= '2026-09-22' AND \"COB_DATE\" < '2026-09-23'")
    history = [{"role": "user", "content": "What was the official PnL of the EQ_DESK desk on 22 September?"},
               {"role": "assistant", "content": "The official PnL of EQ_DESK on 22 September was 567,189 EUR.",
                "queries": [{"query": prev}]}]
    assert carry.new_values("And the flash PnL?", [history[0]["content"], history[1]["content"]], [prev]) == \
        ["flash (PNL_STATUS)"]
    assert carry.new_values("And the official one by book?", [history[0]["content"]], [prev]) == []   # used before
    assert carry.new_values("And the flash PnL?", ["the flash was 576,885 EUR"], [prev]) == []        # in the answer
    made_up = say("The flash PnL of EQ_DESK on 22 September was 567,189 EUR as well.")
    sql = {"request": {"database_id": 1, "sql": prev.replace("IN ('OFFICIAL', 'RESTATED')", "= 'FLASH'")}}
    rows = json.dumps({"success": True, "columns": [{"name": "total"}], "rows": [{"total": 576885.24}], "row_count": 1})
    a, ran = agent_with(monkeypatch, [made_up, call("execute_sql", sql), say("The flash PnL was 576,885 EUR.")],
                        results=lambda n, args: rows)
    answer, _trace = a.ask("And the flash PnL?", history)
    assert a.new_values == ["flash (PNL_STATUS)"] and a.asks_new and not a.follow_up
    assert answer == "The flash PnL was 576,885 EUR." and len(ran) == 1
    assert a.llm.choices == [None, "required", None]                     # its own query, compulsory after the nudge
    restated = say("The official PnL of EQ_DESK on 22 September was 567,189 EUR.")
    b, _ran = agent_with(monkeypatch, [restated])
    b.ask("Was that the official figure?", history)
    assert not b.new_values and not b.usage.get("nudges")                # the chat's own figure: as before


def test_figures_no_query_gave_make_a_tool_call_compulsory(ctx, monkeypatch):
    """"Back to srv-x-9: what was its highest 1-minute load that day?" answered "1.16" with no query, sent back, then
    given again (0.9.1: only marked). With no query in the answer, the numbers check makes the next call compulsory."""
    import json

    from test_agent_loop import agent_with, call, say

    history = [{"role": "user", "content": "Which server had the least available memory on 23 September?"},
               {"role": "assistant", "content": "srv-x-9, at 10.2 GiB."}]
    q = {"request": {"database_id": 2, "sql": "SELECT MAX(value) FROM node_load1 WHERE node = 'srv-x-9'"}}
    rows = json.dumps({"success": True, "columns": [{"name": "max"}], "rows": [{"max": 4.53}], "row_count": 1})
    a, ran = agent_with(monkeypatch, [say("srv-x-9 had a highest 1-minute load of 1.16 that day.")] * 2 +
                        [call("execute_sql", q), say("srv-x-9's highest 1-minute load that day was 4.53.")],
                        results=lambda n, args: rows)
    answer, _trace = a.ask("Back to srv-x-9: what was its highest 1-minute load that day?", history)
    assert answer.startswith("srv-x-9's highest 1-minute load that day was 4.53.") and len(ran) == 1
    assert "required" in a.llm.choices
    from supagent import settings

    real = settings.get
    off, _ran = agent_with(monkeypatch, [say("srv-x-9 had a highest 1-minute load of 1.16 that day.")] * 3)
    monkeypatch.setattr(settings, "get", lambda key: False if key == "agent.force_tool" else real(key))
    off.ask("Back to srv-x-9: what was its highest 1-minute load that day?", history)
    assert "required" not in off.llm.choices                             # agent.force_tool off: never compulsory


def test_a_no_such_field_follow_up_is_sent_back_even_with_the_previous_figures(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    history = [{"role": "user", "content": "How many trades did the desk do on 23 September?"},
               {"role": "assistant", "content": "The desk did 93 trades on 23 September."}]
    a, _ran = agent_with(monkeypatch, [say("The data does not contain a voice field for the 93 trades. Which field "
                                           "do you mean?")] * 3)
    a.ask("How many of them were booked by voice?", history)
    assert a.usage.get("nudges")                                         # looked up first, not waved through


def test_a_follow_up_with_another_day_is_not_answered_from_the_chat(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    history = [{"role": "user", "content": "How many jobs failed on 23 September?"},
               {"role": "assistant", "content": "5,939 jobs failed on 23 September."}]
    a, _ran = agent_with(monkeypatch, [say("5,939 jobs failed on 22 September.")] * 3)
    answer, _trace = a.ask("And on 22 September?", history)
    assert a.usage.get("nudges") and "(Check:" in answer                 # another day: its own query
    b, _ran = agent_with(monkeypatch, [say("ok")])
    last = b.prompt("The CPU of srv-amer-002 yesterday.", history)[-1]["content"]
    assert last.endswith("The CPU of srv-amer-002 yesterday.")          # a new question, not a completion


def test_a_date_alone_on_a_field_with_times_is_sent_back(world, monkeypatch):
    """A date field whose values carry a time (stored at 00:00 UTC, read at 02:00 here by osagg before 0.2.10; or
    real times) finds nothing with = '2026-09-23': sent back once with the day's range; a field of dates alone
    passes. (osagg 0.2.10 and later compare such a field as dates: test_a_field_of_days_is_compared_with_dates.)"""
    from superset.extensions import db

    from supagent.knowledge import period
    from supagent.knowledge.period import refusal
    from supagent.models import KObject

    monkeypatch.setattr(period, "osagg_reads_days", lambda: False)

    src = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == "jobs").one().source_id
    timed = KObject(source_id=src, kind="field", parent="jobs", name="RUN_DATE", data_type="date",
                    stats={"min": "2026-07-01 02:00", "max": "2026-09-25 02:00"})
    plain = KObject(source_id=src, kind="field", parent="jobs", name="COB", data_type="date",
                    stats={"min": "2026-07-01", "max": "2026-09-25 00:00"})
    db.session.add_all([timed, plain])
    db.session.commit()
    try:
        q = "How many jobs ran on 23 September?"
        back = refusal(q, "execute_sql", _sql('SELECT COUNT(*) FROM "jobs" WHERE "RUN_DATE" = \'2026-09-23\''), TODAY)
        assert back.startswith("tool error (not run: date)") and "\"RUN_DATE\" < '2026-09-24'" in back
        assert "e.g. 2026-09-25 02:00" in back
        inlist = refusal(q, "execute_sql", _sql('SELECT COUNT(*) FROM "jobs" WHERE RUN_DATE IN (\'2026-09-23\')'), TODAY)
        assert inlist and "not run: date" in inlist
        for typed in ("DATE '2026-09-23'", "TIMESTAMP '2026-09-23 00:00:00'"):   # the retail lab: = DATE '...'
            back = refusal(q, "execute_sql", _sql(f'SELECT COUNT(*) FROM "jobs" WHERE "RUN_DATE" = {typed}'), TODAY)
            assert back and "not run: date" in back, typed
        instant = refusal(q, "execute_sql", _sql("SELECT COUNT(*) FROM \"jobs\" WHERE \"RUN_DATE\" = TIMESTAMP "
                                                 "'2026-09-23 02:00:00' AND \"ts\" >= '2026-09-23 00:00' AND \"ts\" < "
                                                 "'2026-09-24 00:00'"), TODAY)
        assert "not run: date" not in (instant or "")                      # an instant: meant
        ranged = refusal(q, "execute_sql", _sql(
            "SELECT COUNT(*) FROM \"jobs\" WHERE \"RUN_DATE\" >= '2026-09-23' AND \"RUN_DATE\" < '2026-09-24' "
            "AND \"ts\" >= '2026-09-23 00:00' AND \"ts\" < '2026-09-24 00:00'"), TODAY)
        assert ranged is None
        assert "not run: date" not in (refusal(q, "execute_sql", _sql(
            "SELECT COUNT(*) FROM \"jobs\" WHERE \"COB\" = '2026-09-23' AND \"ts\" >= '2026-09-23 00:00' "
            "AND \"ts\" < '2026-09-24 00:00'"), TODAY) or "")                   # dates alone: equality works
    finally:
        db.session.delete(timed)
        db.session.delete(plain)
        db.session.commit()


def _shipments(world):
    """A shipments index with four dates; its learned time field is DELIVERED_TIME (the first in name order)."""
    from superset.extensions import db
    from superset.models.core import Database

    from supagent.knowledge.store import source_for, upsert
    from supagent.models import Run

    run = Run(kind="learn", reason="test")
    db.session.add(run)
    db.session.commit()
    jobs = db.session.query(Database).filter(Database.database_name == "jobs").one()
    s = source_for(jobs)
    upsert(run, s, "index", "", "shipments", {"stats": {"docs": 1000, "time_field": "DELIVERED_TIME"}})
    for name in ("DELIVERED_TIME", "SHIPPED_TIME", "ORDER_DATE", "PROMISED_DATE"):
        upsert(run, s, "field", "shipments", name, {"data_type": "date", "stats": {"filled_pct": 100.0}})
    upsert(run, s, "field", "shipments", "CARRIER", {"data_type": "keyword", "stats": {"values": ["FASTPOST"]}})
    db.session.commit()


def test_the_time_the_question_names_is_the_time_of_its_period(world):
    from supagent.knowledge.period import named_time_fields, ranges_named, refusal, whole_day

    _shipments(world)
    q = "Among the parcels shipped on 17 and 18 September, which carrier had the most late deliveries, and how many?"
    assert whole_day(q, TODAY) is None                                  # two days, not the 18th
    assert ranges_named(q, TODAY) == [(dt.datetime(2026, 9, 17), dt.datetime(2026, 9, 19))]
    assert named_time_fields(q, {"shipments"}) == {"shipments": {"SHIPPED_TIME"}}
    period = "'2026-09-17 00:00' AND \"{f}\" < '2026-09-19 00:00'"
    by = 'SELECT "CARRIER", COUNT(*) FROM "shipments" WHERE "LATE" = true AND "{f}" >= ' + period + ' GROUP BY "CARRIER"'
    wrong = refusal(q, "execute_sql", _sql(by.format(f="DELIVERED_TIME")), TODAY)
    assert wrong.startswith("tool error (not run: period)") and '"SHIPPED_TIME" of shipments' in wrong
    assert "puts the period on DELIVERED_TIME" in wrong
    assert refusal(q, "execute_sql", _sql(by.format(f="SHIPPED_TIME")), TODAY) is None
    both = ("How many of the LYON warehouse's orders of 22 September were shipped only on 24 September or later?")
    assert named_time_fields(both, {"shipments"}) == {"shipments": {"ORDER_DATE", "SHIPPED_TIME"}}
    assert refusal(both, "execute_sql", _sql("SELECT COUNT(*) FROM \"shipments\" WHERE \"ORDER_DATE\" >= '2026-09-22 "
                                             "00:00' AND \"ORDER_DATE\" < '2026-09-23 00:00' AND \"SHIPPED_TIME\" >= "
                                             "'2026-09-24 00:00'"), TODAY) is None
    plain = "What is the average delivery time of FASTPOST parcels in September, in days?"
    assert named_time_fields(plain, {"shipments"}) == {}                # "delivery time" names the measure here
    assert refusal(plain, "execute_sql", _sql("SELECT AVG(\"DELIVERY_DAYS\") FROM \"shipments\" WHERE \"CARRIER\" = "
                                              "'FASTPOST' AND \"DELIVERED_TIME\" >= '2026-09-01 00:00' AND "
                                              "\"DELIVERED_TIME\" < '2026-10-01 00:00'"), TODAY) is None
    assert named_time_fields("How many parcels were delivered on 23 September?", {"shipments"}) == \
        {"shipments": {"DELIVERED_TIME"}}


def test_the_period_on_a_joined_index_or_another_date_is_a_period(world):
    """Two refusals that sent right queries back (and the model then narrowed them wrongly): the period on the
    joined orders' time (the parcels of the orders placed that week), and on another date of the index than its
    time field when the question names neither."""
    from superset.extensions import db
    from superset.models.core import Database

    from supagent.knowledge.period import refusal
    from supagent.knowledge.store import source_for, upsert
    from supagent.models import Run

    _shipments(world)
    run = db.session.query(Run).first()
    s = source_for(db.session.query(Database).filter(Database.database_name == "jobs").one())
    upsert(run, s, "index", "", "orders", {"stats": {"docs": 1000, "time_field": "ORDER_TIME"}})
    for name in ("ORDER_TIME", "ORDER_DATE"):
        upsert(run, s, "field", "orders", name, {"data_type": "date", "stats": {"filled_pct": 100.0}})
    db.session.commit()
    q = "How many parcels of the orders placed from 14 to 20 September were delivered late?"
    join = ('SELECT COUNT(*) FROM "shipments" s JOIN "orders" o ON s."ORDER_ID" = o."ORDER_ID" WHERE {period} '
            's."LATE" = true')
    week = "{f} >= '2026-09-14 00:00' AND {f} < '2026-09-21 00:00' AND"
    assert refusal(q, "execute_sql", _sql(join.format(period=week.format(f='o."ORDER_TIME"'))), TODAY) is None
    assert refusal(q, "execute_sql", _sql(join.format(period=week.format(f='s."ORDER_DATE"'))), TODAY) is None
    none = refusal(q, "execute_sql", _sql(join.format(period="")), TODAY)
    assert none and none.startswith("tool error (not run: period)")
    other = refusal(q, "execute_sql", _sql(join.format(period=week.format(f='s."SHIPPED_TIME"'))), TODAY)
    assert other and "not run: period" in other                         # a time the words do not name
    plain = "Which carrier had the most late parcels on 22 September?"   # no time named: the index's time field
    by = 'SELECT "CARRIER", COUNT(*) FROM "shipments" WHERE "LATE" = true {period} GROUP BY "CARRIER"'
    day = "AND \"{f}\" >= '2026-09-22 00:00' AND \"{f}\" < '2026-09-23 00:00'"
    shipped = _sql(by.format(period=day.format(f="SHIPPED_TIME")))
    assert refusal(plain, "execute_sql", _sql(by.format(period=day.format(f="DELIVERED_TIME"))), TODAY) is None
    assert "not run: period" in refusal(plain, "execute_sql", shipped, TODAY)       # another event's date
    prior = [by.format(period=day.format(f="SHIPPED_TIME"))]                        # the previous answer's date:
    assert refusal(plain, "execute_sql", shipped, TODAY, prior=prior) is None       # the follow-up's period too
    assert "not run: period" in refusal(plain, "execute_sql", _sql(by.format(period="")), TODAY, prior=prior)
    sold = "How many were sold on 21 September?"                                    # a date of the same event
    assert refusal(sold, "execute_sql", _sql("SELECT COUNT(*) FROM \"orders\" WHERE \"ORDER_DATE\" >= '2026-09-21' "
                                             "AND \"ORDER_DATE\" < '2026-09-22'"), TODAY) is None
    from supagent.knowledge.period import named_time_fields

    assert named_time_fields("I meant the ones delivered that day.", {"shipments"}) == {"shipments": {"DELIVERED_TIME"}}
    grouped = ('SELECT DATE_TRUNC(\'day\', "SHIPPED_TIME") AS d, COUNT(*) FROM "shipments" WHERE "LATE" = true '
               'GROUP BY DATE_TRUNC(\'day\', "SHIPPED_TIME")')                # shown, not filtered
    assert "not run: period" in refusal(plain, "execute_sql", _sql(grouped), TODAY)


def test_a_time_field_that_names_no_event_takes_the_tables_own_dates(world):
    """The changes of an investigation are indexed with @timestamp_date; "what changed before it began?" filtered on
    CHANGE_TIME was refused 26 times in the stored investigations (38 refusals, all on such a field)."""
    from superset.extensions import db
    from superset.models.core import Database

    from supagent.knowledge.period import refusal
    from supagent.knowledge.store import source_for, upsert
    from supagent.models import Run

    run = Run(kind="learn", reason="test")
    db.session.add(run)
    db.session.commit()
    s = source_for(db.session.query(Database).filter(Database.database_name == "jobs").one())
    upsert(run, s, "index", "", "changes", {"stats": {"docs": 100, "time_field": "@timestamp_date"}})
    for name in ("@timestamp_date", "CHANGE_TIME"):
        upsert(run, s, "field", "changes", name, {"data_type": "date", "stats": {"filled_pct": 100.0}})
    db.session.commit()
    q = "Which changes were made on 22 September?"
    on_change = ("SELECT \"CHANGE_ID\" FROM \"changes\" WHERE \"CHANGE_TIME\" >= '2026-09-22 00:00' AND "
                 "\"CHANGE_TIME\" < '2026-09-23 00:00'")
    assert refusal(q, "execute_sql", _sql(on_change), TODAY) is None
    assert "not run: period" in refusal(q, "execute_sql", _sql("SELECT \"CHANGE_ID\" FROM \"changes\" WHERE "
                                                                "\"TARGET\" = 'X'"), TODAY)   # no date at all


def test_each_day_the_question_names_has_its_field():
    """The retail lab's D4: two dates, each with its event: the period of 22 September is the orders' day."""
    import datetime as dt

    from supagent.knowledge.period import named_days

    fields = ["ORDER_DATE", "SHIPPED_TIME", "DELIVERED_TIME"]
    q = "How many of the LYON warehouse's orders of 22 September were shipped only on 24 September or later?"
    assert named_days(q, fields, TODAY) == {dt.date(2026, 9, 22): {"ORDER_DATE"}, dt.date(2026, 9, 24): {"SHIPPED_TIME"}}
    assert named_days("Parcels shipped 17-18 September and delivered late?", fields, TODAY) == {
        dt.date(2026, 9, 17): {"SHIPPED_TIME"}, dt.date(2026, 9, 18): {"SHIPPED_TIME"}}
    assert named_days("How many parcels on 23 September?", fields, TODAY) == {}


def test_an_index_takes_its_datasets_main_time_column(world):
    from superset.connectors.sqla.models import SqlaTable
    from superset.extensions import db
    from superset.models.core import Database

    from supagent.knowledge.learn_indices import prefer_dataset_time

    jobs = db.session.query(Database).filter(Database.database_name == "jobs").one()
    fstats = {"DELIVERED_TIME": {"type": "date", "min": "2026-08-28", "max": "2026-09-24"},
              "SHIPPED_TIME": {"type": "date", "min": "2026-08-27", "max": "2026-09-25"}, "CARRIER": {"type": "keyword"}}
    info = {"time_field": "DELIVERED_TIME", "time_range": ["2026-08-28", "2026-09-24"]}
    prefer_dataset_time(info, fstats, jobs.id, ("shipments",))
    assert info["time_field"] == "DELIVERED_TIME"                       # no dataset: the rule's choice
    ds = SqlaTable(table_name="shipments", database_id=jobs.id, main_dttm_col="SHIPPED_TIME")
    db.session.add(ds)
    db.session.commit()
    try:
        prefer_dataset_time(info, fstats, jobs.id, ("shipments",))
        assert info == {"time_field": "SHIPPED_TIME", "time_range": ["2026-08-27", "2026-09-25"],
                        "time_field_from": "dataset"}
        from supagent.knowledge.learn_indices import dataset_time_now   # learned before: at once, not at the
        from supagent.knowledge.store import source_for, upsert            # next profile
        from supagent.models import Run

        src = source_for(jobs)
        run = db.session.query(Run).first()
        idx = upsert(run, src, "index", "", "shipments", {"stats": {"time_field": "DELIVERED_TIME",
                                                                     "time_range": ["2026-08-28", "2026-09-24"]}})
        made = [idx] + [upsert(run, src, "field", "shipments", n, {"data_type": st["type"], "stats": {
            k: v for k, v in st.items() if k != "type"}}) for n, st in fstats.items()]
        db.session.commit()
        assert dataset_time_now(idx, src, jobs.id, ("shipments",))
        assert (idx.stats["time_field"], idx.stats["time_range"]) == ("SHIPPED_TIME", ["2026-08-27", "2026-09-25"])
        assert not dataset_time_now(idx, src, jobs.id, ("shipments",))
        for o in made:
            db.session.delete(o)
        db.session.commit()
        ds.main_dttm_col = "CARRIER"                                     # not a date of the index: not taken
        db.session.commit()
        other = {"time_field": "DELIVERED_TIME"}
        prefer_dataset_time(other, fstats, jobs.id, ("shipments",))
        assert other == {"time_field": "DELIVERED_TIME"}
    finally:
        db.session.delete(ds)
        db.session.commit()


def test_a_month_is_a_months_name():
    from supagent.knowledge.period import days_named, has_period

    def d(m, n):
        return dt.date(2026, m, n)

    assert days_named("Which are the top 5 markets by sales?", TODAY) == []          # not 5 March
    assert days_named("We made 3 decisions and 10 junior hires; 2 augmented, 5 novices, 7 decimals", TODAY) == []
    assert not has_period("Which are the top 5 markets by sales?", TODAY)
    assert days_named("le 3 juin, le 4 sept., le 12 févr. et le 10 mars 2026", TODAY) == [d(6, 3), d(9, 4), d(2, 12),
                                                                                         d(3, 10)]
    assert days_named("on the 23rd of September", TODAY) == [d(9, 23)]
    assert days_named("Sept 23 and Dec. 1", TODAY) == [d(9, 23), d(12, 1)]
    assert days_named("le 1er août et le 15 août", TODAY) == [d(8, 1), d(8, 15)]


def test_a_day_said_relative_to_another_needs_one():
    from supagent.knowledge.period import anchor_of, days_named

    d22, d23 = dt.date(2026, 9, 22), dt.date(2026, 9, 23)
    assert days_named("And on the 23rd?", TODAY, anchor=d22) == [d23]
    assert days_named("Et le 23 ?", TODAY, anchor=d22) == [d23]
    assert days_named("And the day before?", TODAY, anchor=d23) == [d22]
    assert days_named("Et la veille ?", TODAY, anchor=d23) == [d22]
    assert days_named("And the next day?", TODAY, anchor=d22) == [d23]
    assert days_named("And on the 23rd?", TODAY) == []                               # no day to be relative to
    assert days_named("And the 2nd?", TODAY) == []
    assert days_named("What is the 3rd largest order of 22 September?", TODAY) == [d22]      # a rank, not a day
    assert days_named("How many failed the day before yesterday?", TODAY) == [d22]           # today - 2
    assert days_named("Failed jobs on 23 September compared with the day before", TODAY) == [d23, d22]
    assert days_named("the day before 23 September", TODAY) == [d22, d23]
    assert anchor_of(["How many orders on 22 September?", "And on the 23rd?"], TODAY) == d23
    assert anchor_of(["Which application failed most?"], TODAY) is None


def test_a_follow_up_puts_its_own_day_in_the_earlier_question():
    from supagent.knowledge.period import follow_up_text, named_among, whole_day

    night = ["How many parcels were shipped on 22 September during the night?"]
    t = follow_up_text("And on the 23rd?", night, TODAY)
    assert t.startswith("How many parcels were shipped on 23 September 2026 during the night?")
    assert whole_day(t, TODAY) is None                                  # the night stays: not the whole day
    t = follow_up_text("And on the 23rd?", ["How many parcels were shipped on 22 September?"], TODAY)
    assert whole_day(t, TODAY) == dt.date(2026, 9, 23)
    assert named_among(t, ["ORDER_DATE", "SHIPPED_TIME"]) == {"SHIPPED_TIME"}        # the event next to the day
    assert follow_up_text("And per carrier?", night, TODAY) is None                  # no day of its own
    assert follow_up_text("And the day before?", night + ["And on the 23rd?"], TODAY).startswith(
        "How many parcels were shipped on 22 September 2026 during the night?")
    assert follow_up_text("And last week?", ["How many orders on 22 September?"], TODAY) == \
        "How many orders on last week?\nAnd last week?"
    assert follow_up_text("And on the 24th?", ["Orders from 22 to 23 September?"], TODAY) is None     # a span
    assert follow_up_text("And the 2nd?", ["Which application failed most?"], TODAY) is None


def test_a_follow_up_for_another_day_is_checked_on_that_day(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    history = [{"role": "user", "content": "How many parcels were shipped on 22 September?"},
               {"role": "assistant", "content": "412 parcels were shipped on 22 September."}]
    a, _ran = agent_with(monkeypatch, [say("412 parcels were shipped on 22 September.")] * 3)
    answer, _trace = a.ask("And on the 23rd?", history)
    assert a.asks_new and not a.follow_up and a.usage.get("nudges") and "(Check:" in answer   # its own query
    assert a.intent_text.startswith("How many parcels were shipped on 22 September?")        # what it is about
    assert a.period_text.startswith("How many parcels were shipped on 23 September 2026?")   # the day it asks
    b, _ran = agent_with(monkeypatch, [say("ok")])
    b.prompt("And per carrier?", history)
    assert not b.asks_new and b.period_text == b.intent_text                          # the earlier day stays


def test_that_day_is_the_day_named_before():
    from supagent.knowledge.period import days_named, follow_up_text, named_among

    d22 = dt.date(2026, 9, 22)
    assert days_named("I meant the ones delivered that day.", TODAY, anchor=d22) == [d22]
    assert days_named("Et ce jour-là ?", TODAY, anchor=d22) == [d22]
    assert days_named("How many orders on the same day last week?", TODAY, anchor=d22) == []   # another day
    t = follow_up_text("I meant the ones delivered that day.", ["How many late shipments were there on 22 September?"],
                       TODAY)
    assert t.endswith("I meant the ones delivered 22 September 2026.")
    assert named_among(t, ["SHIPPED_TIME", "DELIVERED_TIME"]) == {"DELIVERED_TIME"}      # the follow-up's event


def test_a_question_that_goes_on_from_the_last_exchange_is_a_follow_up(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    from supagent.agent import refers_back
    from supagent.knowledge.topics import Decision

    assert refers_back("What was its failure rate?") and refers_back("Quel est son taux d'échec ?")
    assert refers_back("And their total notional?") and refers_back("How many of its failures were timeouts?")
    assert not refers_back("Which servers exceeded their memory limit yesterday?")       # its own antecedent
    assert not refers_back("Did any desk breach its VaR limit on 23 September?")
    assert not refers_back("Quels serveurs ont dépassé leur limite mémoire hier ?")
    history = [{"role": "user", "content": "How many pricing requests of pricer-eq failed on 22 September?"},
               {"role": "assistant", "content": "37 requests failed."}]
    a, _ran = agent_with(monkeypatch, [say("ok")])
    a.subject = Decision(1, "no subject of its own")
    a.prompt("Which error code came up most often?", history)
    assert a.intent_text.startswith("How many pricing requests of pricer-eq failed")     # its context
    b, _ran = agent_with(monkeypatch, [say("ok")])
    b.subject = Decision(1, "the same data")                                            # a new question
    b.prompt("Which error code came up most often?", history)
    assert b.intent_text == "Which error code came up most often?"


def test_an_upper_bound_at_the_next_midnight_on_a_field_of_days_is_sent_back(world):
    """BETWEEN ... AND '2026-09-21' (or <= '2026-09-21 00:00') on a field that holds days takes in the whole 21st
    (measured through osagg: an upper bound at a midnight counts the rows of that day too); for "14 to 20
    September" it adds a day. Sent back once; the same bound on a field of instants passes (the next midnight is
    before that day's rows)."""
    from superset.extensions import db

    from supagent.knowledge.period import refusal
    from supagent.models import KObject

    src = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == "jobs").one().source_id
    days = KObject(source_id=src, kind="field", parent="jobs", name="RUN_DATE", data_type="date",
                   stats={"min": "2026-07-01 02:00", "max": "2026-09-25 02:00"})
    db.session.add(days)
    db.session.commit()
    try:
        q = "How many jobs ran from 14 to 20 September?"
        sql = lambda w: _sql(f'SELECT COUNT(*) FROM "jobs" WHERE {w} AND "ts" >= \'2026-09-14\' AND "ts" < \'2026-09-21\'')  # noqa: E731
        back = refusal(q, "execute_sql", sql("\"RUN_DATE\" BETWEEN '2026-09-14' AND '2026-09-21'"), TODAY)
        assert back and "BETWEEN and <= include their last value" in back and "< '2026-09-21'" in back
        back = refusal(q, "execute_sql", sql("\"RUN_DATE\" <= '2026-09-21 00:00'"), TODAY)
        assert back and "BETWEEN and <= include" in back
        assert refusal(q, "execute_sql", sql("\"RUN_DATE\" <= '2026-09-20'"), TODAY) is None     # the last day: right
        alone = lambda w: _sql(f'SELECT COUNT(*) FROM "jobs" WHERE {w}')  # noqa: E731   (0.9.8: no other bound)
        named = "How many jobs were run from 14 to 20 September?"             # its words name RUN_DATE
        assert refusal(named, "execute_sql", alone("\"RUN_DATE\" BETWEEN '2026-09-14' AND '2026-09-20'"), TODAY) is None
        assert refusal(named, "execute_sql", alone("\"RUN_DATE\" >= '2026-09-14' AND \"RUN_DATE\" <= '2026-09-20'"),
                       TODAY) is None
        assert refusal(named, "execute_sql", alone("\"RUN_DATE\" BETWEEN '2026-09-15' AND '2026-09-20'"), TODAY)
        assert refusal(q, "execute_sql", sql("\"ts\" <= '2026-09-21 00:00'"), TODAY) is None     # instants (ts)
    finally:
        db.session.delete(days)
        db.session.commit()


def test_a_field_of_days_is_compared_with_dates(world, monkeypatch):
    """A field that holds days, learned as 2026-07-01 02:00 .. 2026-09-25 02:00 (midnight UTC shown in Paris), is
    compared by osagg as dates at 00:00 (measured: COB_DATE = '2026-09-23' is the 23rd's 96 rows; >= '2026-09-22
    02:00' AND < '2026-09-23 02:00' is the 23rd's rows, not the 22nd's). Answers copied the 02:00 onto their bounds
    and moved the period by a day (the first day of a month left out, another day read). Such a bound is sent back
    once with dates; an equality with a date is not refused; describe_data shows the field's range as dates."""
    from superset.extensions import db

    from supagent.knowledge import period
    from supagent.knowledge.describe import _field_line
    from supagent.knowledge.period import as_day, day_stats, day_time_bound, refusal
    from supagent.models import KObject

    monkeypatch.setattr(period, "osagg_reads_days", lambda: True)       # osagg 0.2.10 and later

    assert day_stats({"min": "2026-07-01 02:00", "max": "2026-09-25 02:00"})
    assert day_stats({"min": "2026-07-01", "max": "2026-09-25"})
    assert not day_stats({"min": "2026-07-01 02:00", "max": "2026-09-25 14:37"})
    assert as_day("2026-09-01 02:00") == "2026-09-01" and as_day("2026-08-31 22:00") == "2026-09-01"
    src = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == "jobs").one().source_id
    days = KObject(source_id=src, kind="field", parent="jobs", name="RUN_DATE", data_type="date",
                   stats={"min": "2026-07-01 02:00", "max": "2026-09-25 02:00"})
    db.session.add(days)
    db.session.commit()
    try:
        q = "How many jobs ran in September?"
        back = refusal(q, "execute_sql", _sql("SELECT COUNT(*) FROM \"jobs\" WHERE \"RUN_DATE\" >= '2026-09-01 02:00' "
                                              "AND \"RUN_DATE\" < '2026-10-01 02:00'"), TODAY)
        assert back and "holds days" in back and "the rows of 2026-09-01 are left out" in back
        assert "\"RUN_DATE\" >= '2026-09-01' AND \"RUN_DATE\" < '2026-09-02'" in back
        back = day_time_bound("SELECT 1 FROM \"jobs\" WHERE \"RUN_DATE\" >= '2026-09-01' AND "
                              "\"RUN_DATE\" < TIMESTAMP '2026-10-01 02:00:00'", {"jobs"})
        assert back and "the rows of 2026-10-01 are taken in" in back
        back = day_time_bound("SELECT 1 FROM \"jobs\" WHERE \"RUN_DATE\" BETWEEN '2026-09-22 02:00' AND "
                              "'2026-09-23 02:00'", {"jobs"})
        assert back and "left out" in back
        assert day_time_bound("SELECT 1 FROM \"jobs\" WHERE \"RUN_DATE\" >= '2026-09-01 00:00' AND "
                              "\"RUN_DATE\" <= '2026-09-30 23:59:59'", {"jobs"}) is None        # whole days
        assert day_time_bound("SELECT 1 FROM \"jobs\" WHERE \"ts\" >= '2026-09-01 02:00'", {"jobs"}) is None  # instants
        one = _sql("SELECT COUNT(*) FROM \"jobs\" WHERE \"RUN_DATE\" = '2026-09-23' AND \"ts\" >= '2026-09-23' "
                   "AND \"ts\" < '2026-09-24'")
        assert refusal("How many jobs ran on 23 September?", "execute_sql", one, TODAY) is None   # = a date: right
        line = _field_line(days)
        assert "range 2026-07-01 .. 2026-09-25 (days" in line and "02:00" not in line
        monkeypatch.setattr(period, "osagg_reads_days", lambda: False)  # an older osagg: 02:00 is the day's time
        assert day_time_bound("SELECT 1 FROM \"jobs\" WHERE \"RUN_DATE\" >= '2026-09-01 02:00'", {"jobs"}) is None
        assert "02:00" in _field_line(days)
    finally:
        db.session.delete(days)
        db.session.commit()


def test_a_question_about_the_future_answered_with_past_figures_says_so(ctx, monkeypatch):
    """"How much revenue will we make next week?" answered with last week's revenue and no word that the data cannot
    tell the future (a main-suite answer of 0.9.3): sent back once. An answer that says it, or queries that read the
    future period (parcels promised for tomorrow: data about the future), pass."""
    from test_agent_loop import agent_with, call, say

    from supagent.knowledge.period import future_start, future_unsaid

    today = dt.date(2030, 1, 9)                                                     # a Wednesday
    last_week = ["SELECT SUM(\"AMOUNT\") FROM \"orders\" WHERE \"DAY\" >= '2030-01-01' AND \"DAY\" < '2030-01-08'"]
    q = "How much revenue will we make next week?"
    assert future_start(q, today) == dt.date(2030, 1, 14)
    assert future_unsaid(q, "Last week's revenue was 404,290.94 EUR.", last_week, today) == dt.date(2030, 1, 14)
    assert future_unsaid(q, "The data cannot tell next week's revenue; last week's was 404,290.94 EUR.", last_week,
                         today) is None
    promised = ["SELECT COUNT(*) FROM \"parcels\" WHERE \"PROMISED\" >= '2030-01-10' AND \"PROMISED\" < '2030-01-11'"]
    assert future_unsaid("How many parcels are promised for tomorrow?", "41 parcels.", promised, today) is None
    assert future_unsaid("What was the revenue last week?", "404,290.94 EUR.", last_week, today) is None
    assert future_start("Quel sera le chiffre d'affaires la semaine prochaine ?", today) == dt.date(2030, 1, 14)
    sql = {"request": {"database_id": 1, "sql": last_week[0]}}
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), say("Last week's revenue was 404,290.94 EUR."),
                                      say("The data cannot tell next week's revenue; last week's was 404,290.94 EUR.")])
    answer, _trace = a.ask(q)
    assert answer.startswith("The data cannot tell next week's revenue") and a.usage.get("nudges")


def test_a_weekday_named_with_last_or_on_is_that_day(world):
    """"How many support tickets were opened last Monday?" on a Thursday was counted on the Tuesday (the model's
    weekday arithmetic): "last/this past/on <weekday>", "lundi dernier", "ce lundi" name the most recent one before
    today, and the period check holds the query to it. A bare weekday ("the expiry Monday effect", "every Monday")
    names no day."""
    from supagent.knowledge.period import days_named, refusal

    thursday = dt.date(2030, 1, 10)
    assert days_named("How many jobs ran last Monday?", thursday) == [dt.date(2030, 1, 7)]
    assert days_named("Combien de jobs lundi dernier ?", thursday) == [dt.date(2030, 1, 7)]
    assert days_named("And this past Friday?", thursday) == [dt.date(2030, 1, 4)]
    assert days_named("last Thursday?", thursday) == [dt.date(2030, 1, 3)]                  # a week ago, not today
    assert days_named("the expiry Monday effect", thursday) == [] and days_named("Jobs every Monday", thursday) == []
    today = dt.date(2026, 9, 24)                                                             # the fixture's data
    wrong = _sql("SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '2026-09-22' AND \"ts\" < '2026-09-23'")
    back = refusal("How many jobs ran last Monday?", "execute_sql", wrong, today)
    assert back and "2026-09-21" in back
    right = _sql("SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '2026-09-21' AND \"ts\" < '2026-09-22'")
    assert refusal("How many jobs ran last Monday?", "execute_sql", right, today) is None


def test_a_window_around_the_day_is_a_comparison_for_an_open_question(world):
    """"Why did the desk lose money on COB 22 September?": its queries compare the 22nd with the days around it
    (dates 15 and 23); the period check refused them as "another day". For an open question (why, is it usual) a
    window that holds the day passes; for a count of that day it is refused as several days, said so."""
    from supagent.knowledge.period import refusal

    today = dt.date(2026, 9, 24)
    around = _sql("SELECT \"ts\", COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '2026-09-15' AND \"ts\" < '2026-09-23' GROUP BY 1")
    assert refusal("Why did so many jobs fail on 22 September?", "execute_sql", around, today, comparing=True) is None
    back = refusal("How many jobs failed on 22 September?", "execute_sql", around, today)
    assert back and "several days" in back and "2026-09-22 00:00" in back
    other = _sql("SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '2026-09-15' AND \"ts\" < '2026-09-16'")
    assert "this query's dates are" in (refusal("Why did so many jobs fail on 22 September?", "execute_sql", other,
                                               today, comparing=True) or "")             # not around it: another day


def test_an_end_of_day_at_23_59_is_the_span_s_own_end(world):
    """"from 1 to 20 September" written BETWEEN '...-01 00:00' AND '...-20 23:59': the end of the 20th, the span's own
    end. It was refused as a boundary a few hours off, and the model then wrote '...-21 00:00' (the whole 21st on a
    field of days: 888 for 831)."""
    from supagent.knowledge.period import refusal

    today = dt.date(2026, 9, 24)
    q = "How many jobs ran from 14 to 20 September?"
    end_of_day = _sql("SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" BETWEEN '2026-09-14 00:00' AND '2026-09-20 23:59'")
    assert refusal(q, "execute_sql", end_of_day, today) is None
    short = _sql("SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '2026-09-14 00:00' AND \"ts\" < '2026-09-20 00:00'")
    assert refusal(q, "execute_sql", short, today)                                          # a day short: refused


def test_last_weekend_is_the_saturday_and_sunday_before(world):  # noqa: F811
    """"How many support tickets were opened last weekend?" asked on Wednesday 23 September: 19 and 20 September (a
    model counted 20 and 21, Sunday and Monday, and no check knew the weekend)."""
    import datetime as dt

    from supagent.knowledge.period import has_period, ranges_named, refusal

    wed = dt.date(2026, 9, 23)
    assert ranges_named("How many tickets were opened last weekend?", wed) == [
        (dt.datetime(2026, 9, 19), dt.datetime(2026, 9, 21))]
    assert ranges_named("Combien de tickets le week-end dernier ?", wed) == [
        (dt.datetime(2026, 9, 19), dt.datetime(2026, 9, 21))]
    sun = dt.date(2026, 9, 20)
    assert ranges_named("last weekend", sun) == [(dt.datetime(2026, 9, 12), dt.datetime(2026, 9, 14))]
    assert ranges_named("this weekend", sun) == [(dt.datetime(2026, 9, 19), dt.datetime(2026, 9, 21))]
    assert ranges_named("this weekend", wed) == []                    # still to come: not a span of the data
    assert has_period("tickets of last weekend", wed)
    week = lambda a, b: _sql(f"SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '{a}' AND \"ts\" < '{b}'")  # noqa: E731
    q = "How many jobs failed last weekend?"
    why = refusal(q, "execute_sql", week("2026-09-20 00:00", "2026-09-22 00:00"), wed)
    assert why and "2026-09-19 00:00 to 2026-09-21 00:00" in why
    assert refusal(q, "execute_sql", week("2026-09-19 00:00", "2026-09-21 00:00"), wed) is None


def test_this_week_and_last_month_are_calendar_spans(world):  # noqa: F811
    """"How many support tickets were opened this week?" asked on Thursday 24 September: from Monday 21 (a model
    counted from Tuesday 22, called Monday); a query near the span but off is sent back, the last 7 days are not."""
    import datetime as dt

    from supagent.knowledge.period import calendar_named, ranges_named, refusal

    thu = dt.date(2026, 9, 24)
    assert calendar_named("tickets opened this week", thu) == [(dt.datetime(2026, 9, 21), dt.datetime(2026, 9, 28))]
    assert calendar_named("tickets opened last week", thu) == [(dt.datetime(2026, 9, 14), dt.datetime(2026, 9, 21))]
    assert calendar_named("revenue last month", thu) == [(dt.datetime(2026, 8, 1), dt.datetime(2026, 9, 1))]
    assert calendar_named("revenue this month", thu) == [(dt.datetime(2026, 9, 1), dt.datetime(2026, 10, 1))]
    assert calendar_named("the last weekend", thu) == [] and calendar_named("the last weeks", thu) == []
    assert calendar_named("cette semaine", thu) == [(dt.datetime(2026, 9, 21), dt.datetime(2026, 9, 28))]
    week = lambda a, b: _sql(f"SELECT COUNT(*) FROM \"jobs\" WHERE \"ts\" >= '{a}' AND \"ts\" < '{b}'")  # noqa: E731
    q = "How many jobs failed this week?"
    assert refusal(q, "execute_sql", week("2026-09-22 00:00", "2026-09-29 00:00"), thu)       # from Tuesday: off
    assert refusal(q, "execute_sql", week("2026-09-21 00:00", "2026-09-25 00:00"), thu) is None       # up to today
    assert refusal(q, "execute_sql", week("2026-09-21 00:00", "2026-09-28 00:00"), thu) is None       # the whole week
    assert refusal("How many jobs failed in the last 7 days?", "execute_sql", week("2026-09-17 00:00", "2026-09-24 00:00"),
                   thu) is None
    assert ranges_named("jobs last week", thu) == [(dt.datetime(2026, 9, 14), dt.datetime(2026, 9, 21))]
