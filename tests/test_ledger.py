"""The work ledger of a big request (0.9.2): tasks, notes and results kept by the system so that a long answer loses
neither its context nor the work left to do."""

from __future__ import annotations

import json

from test_agent_loop import agent_with, call, say

FINDINGS = json.dumps({"conclusion": (
    "In the order of the stages, START_TIME is the first that is clearly off. What stands out, that stage first: "
    "(1) rows past READY_TIME and not yet at START_TIME then (above usual in total): on \"APPLICATION\", concentrated "
    "on APP_A (52 against 0 usually) above usual, while the 1 other value(s) are as usual (the same values for: rows "
    "that had reached START_TIME by then (slightly below usual in total)). (2) avg seconds from READY_TIME to "
    "START_TIME (above usual in total): on \"POOL\", concentrated on POOL_7 (x1.4 its usual) above usual.")})


def test_the_plan_is_merged_by_title_one_task_in_progress_results_attached_by_the_system():
    from supagent.ledger import Ledger

    led = Ledger("Revenue, orders and returns of the week, per country?")
    led.plan([{"title": "Revenue per country", "status": "in_progress"}, {"title": "Orders per country", "status": "pending"},
              "Returns per country"])
    assert [t.status for t in led.tasks] == ["in_progress", "pending", "pending"] and led.tasks[2].by == "model"
    led.attach("execute_sql", json.dumps({"success": True, "rows": [{"COUNTRY": "DE", "rev": 10.5}], "row_count": 1}))
    assert led.tasks[0].results == ["execute_sql: 1 row(s): COUNTRY=DE, rev=10.5"]       # the tool's, not the model's
    led.plan([{"title": "revenue per COUNTRY", "status": "done", "note": "DE first"},
              {"id": 2, "title": "Orders per country", "status": "in_progress"}])
    assert [t.status for t in led.tasks] == ["done", "in_progress", "pending"] and led.tasks[0].note == "DE first"
    led.plan([{"title": "Returns per country", "status": "in_progress"}])               # one at a time
    assert [t.status for t in led.tasks] == ["done", "pending", "in_progress"]
    led.attach("execute_sql", "tool error (not run): no such column")
    assert led.tasks[2].results[-1].startswith("execute_sql: tool error")
    assert [t.id for t in led.open()] == [2, 3] and [t.id for t in led.unworked()] == [2]
    assert "[x] 1. Revenue per country -> DE first" in led.render() and "1 of 3 tasks done" in led.reminder()
    led.plan("not json at all\n- Refunds per country")                                 # a list said as text
    assert led.tasks[-1].title == "Refunds per country"
    state = led.state()
    assert state["tasks"][0] == {"id": 1, "title": "Revenue per country", "status": "done", "note": "DE first",
                                 "by": "model", "keys": [], "results": ["execute_sql: 1 row(s): COUNTRY=DE, rev=10.5"]}


def test_the_findings_of_compare_groups_become_tasks_and_must_be_explained_or_ruled_out():
    from supagent.ledger import Ledger, findings

    found = findings(FINDINGS)
    assert [k for _t, k in found] == [["APP_A"], ["POOL_7"]]                             # nested parentheses kept
    assert found[0][0].startswith("rows past READY_TIME and not yet at START_TIME")
    led = Ledger("Why are the jobs late?")
    led.seed_investigation()
    made = led.seed_findings(FINDINGS)
    assert [t.title[:22] for t in made] == ["Explain or rule out: r", "Explain or rule out: a"]
    assert [t.id for t in led.uncovered("APP_A waited for its feed.")] == [made[1].id]  # POOL_7 not said
    led.plan([{"id": made[1].id, "title": made[1].title, "status": "dropped", "note": "the pool is full every night"}])
    assert led.uncovered("APP_A waited for its feed.") == []                           # ruled out: fine
    assert led.seed_findings(FINDINGS) == [] or all(t.id in (6, 7) for t in led.tasks[5:])   # never twice


def test_continue_takes_up_the_open_tasks_with_the_notes_of_the_done_ones():
    from supagent.ledger import CONTINUE, Ledger

    first = Ledger("big")
    first.plan([{"title": "A", "status": "done", "note": "A is 3"}, {"title": "B", "status": "in_progress"}, "C"])
    nxt = Ledger("continue")
    assert CONTINUE.match("Continue please") and CONTINUE.match("vas-y") and not CONTINUE.match("Why is it late?")
    assert CONTINUE.match("ok, carry on") and CONTINUE.match("Continue the investigation.")
    assert not CONTINUE.match("Next, show me the failed jobs.") and not CONTINUE.match("Continue with the revenue of May")
    assert nxt.take_up(first.state())
    assert [(t.title, t.status) for t in nxt.tasks] == [("A", "done"), ("B", "pending"), ("C", "pending")]
    assert nxt.tasks[0].note == "A is 3" and not Ledger("x").take_up({"tasks": [{"title": "A", "status": "done"}]})


def test_an_investigation_gets_its_steps_and_findings_as_tasks_and_is_sent_back_for_a_finding_it_skips(ctx, monkeypatch):
    from supagent.agent import LEDGER_NUDGE

    cg = {"request": {"table": "jobs"}}
    wp = {"tasks": [{"title": "The facts", "status": "in_progress"}]}
    replies = [call("work_plan", wp), call("compare_groups", cg),
               say("The jobs of APP_A are late: they waited for their feed."),                 # POOL_7 not explained
               say("The jobs of APP_A are late: they waited for their feed. POOL_7 is full every night: ruled out.")]
    a, ran = agent_with(monkeypatch, replies, results=lambda n, args: FINDINGS)
    a.names = a.names | {"compare_groups"}
    answer, trace = a.ask("Why are the jobs late this morning?")
    first = a.llm.seen[0]
    assert "keep a work plan" in first[-1]["content"] and "[ ] 5. Deeper:" in first[-1]["content"]
    assert [n for n, _a in ran] == ["compare_groups"]                                   # work_plan: the system's own
    tools = [m["content"] for m in a.llm.seen[2] if m["role"] == "tool"]
    assert tools[0].startswith("Work plan kept") and "Added to your work plan" in tools[1]
    nudges = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith(LEDGER_NUDGE[:40])]
    assert len(nudges) == 1 and "(on POOL_7: avg seconds from READY_TIME" in nudges[0] and "on APP_A" not in nudges[0]
    assert [t.title for t in a.ledger.tasks][0].startswith("The facts: compare_groups")    # "The facts": the seeded one
    assert answer.startswith("The jobs of APP_A are late") and "ruled out" in answer
    last = trace[-1]
    assert last["tool"] == "work_plan" and any(t["keys"] == ["POOL_7"] for t in last["ledger"]["tasks"])
    assert last["ledger"]["tasks"][0]["status"] == "in_progress" and "compare_groups:" in json.dumps(last["ledger"])


def test_a_request_of_many_parts_gets_an_empty_plan_and_its_own_tasks_are_checked(ctx, monkeypatch):
    from supagent.agent import LEDGER_NUDGE

    wp = {"tasks": [{"title": "Revenue of the week", "status": "in_progress"}, {"title": "Orders of the week"},
                    {"title": "Refunds of the week"}]}
    sql = {"request": {"database_id": 1, "sql": "SELECT SUM(x) FROM orders"}}
    replies = [call("work_plan", wp), call("execute_sql", sql), say("Revenue: 3."), say("Revenue: 3. A and B too.")]
    a, _ran = agent_with(monkeypatch, replies)
    a.ask("Give me the revenue, the orders, the refunds and the returns of the week, and the share of each country.")
    assert "keep a work plan" in a.llm.seen[0][-1]["content"]
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith(LEDGER_NUDGE[:40])]
    assert len(sent) == 1 and "task 2 (Orders of the week) has no result" in sent[0] and "task 1" not in sent[0]


def test_a_simple_question_has_no_plan_and_the_setting_turns_it_off(ctx, monkeypatch):
    from supagent import settings

    a, _ran = agent_with(monkeypatch, [call("execute_sql", {"request": {"database_id": 1, "sql": "SELECT 1"}}),
                                       say("A: 3, B: 2.")])
    a.ask("How many jobs per application?")
    assert a.ledger is None and "work plan" not in a.llm.seen[0][-1]["content"]
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: False if key == "agent.ledger" else real(key))
    b, _ran = agent_with(monkeypatch, [say("They waited for their feed.")] * 3)
    b.ask("Why are the jobs late this morning?")
    assert b.ledger is None and "work plan" not in b.llm.seen[0][-1]["content"]


def test_continue_in_the_next_message_takes_up_the_plan_and_a_shortened_conversation_gets_it_back(ctx, monkeypatch):
    from supagent.llm import LLMError
    from supagent.ledger import Ledger

    before = Ledger("Revenue, orders and refunds of the week?")
    before.plan([{"title": "Revenue", "status": "done", "note": "3,000 EUR"}, {"title": "Orders"}, {"title": "Refunds"}])
    history = [{"role": "user", "content": "Revenue, orders and refunds of the week?"},
               {"role": "assistant", "content": "Revenue: 3,000 EUR. The calls ran out: orders and refunds remain.",
                "ledger": before.state()}]
    sql = {"request": {"database_id": 1, "sql": "SELECT COUNT(*) FROM orders"}}
    big = "x" * 9000
    replies = [call("work_plan", {"tasks": [{"title": "Orders", "status": "in_progress"}]}), call("execute_sql", sql),
               LLMError("HTTP 400: the request exceeds the available context size"),
               say("Orders: 12. Refunds: 4 (Revenue 3,000 EUR)."), say("Orders: 12. Refunds: not counted yet.")]
    a, _ran = agent_with(monkeypatch, replies, results=lambda n, args: json.dumps({"success": True, "rows": [
        {"n": 12, "pad": big}], "row_count": 1}))
    a.ask("Continue", history)
    assert [t.title for t in a.ledger.tasks] == ["Revenue", "Orders", "Refunds"] and a.ledger.tasks[0].note == "3,000 EUR"
    assert "[ ] 3. Refunds" in a.llm.seen[0][-1]["content"]
    after = [m["content"] for m in a.llm.seen[3] if m["role"] == "user" and "Your work plan (kept by the system)" in
             m["content"]]                                               # after the context was full: the plan again
    assert after and "[>] 2. Orders" in after[-1] and "execute_sql: 1 row(s): n=12" in after[-1]
    assert "task 3 (Refunds) has no result" in a.llm.seen[-1][-1]["content"]


def test_a_task_rewritten_with_its_number_is_the_same_task():
    """The model rewrote the seeded steps in the question's language with their numbers ("1. Les faits : ..."): they
    became five more tasks and the seeded ones stayed open. A leading number (or an id) is the task of that number."""
    from supagent.ledger import Ledger, SPEC

    assert "id" in SPEC["function"]["parameters"]["properties"]["tasks"]["items"]["properties"]
    led = Ledger("Pourquoi le batch est-il en retard ?")
    led.seed_investigation()
    led.plan([{"title": "1. Les faits : compare_groups sur le scope", "status": "done", "note": "READY_TIME en retard"},
              {"id": 2, "title": "Où : le champ", "status": "in_progress"}, {"title": "6. Vérifier la licence"}])
    assert [(t.id, t.status) for t in led.tasks] == [(1, "done"), (2, "in_progress"), (3, "pending"), (4, "pending"),
                                                     (5, "pending"), (6, "pending")]
    assert led.tasks[0].note == "READY_TIME en retard" and led.tasks[5].title == "Vérifier la licence"


def test_a_step_rewritten_in_the_models_words_is_the_same_task():
    """CT200, an investigation: the model gave the five steps its own details, no ids, no numbers ("The facts:
    compare_groups on <its jobs>", "Check the cause: <a pool>"): five more tasks, the seeded ones stayed open, and 10
    of its 31 calls were plan updates. The label of a step (before ":", else its first three words) is that step."""
    from supagent.ledger import Ledger

    led = Ledger("Why were the jobs late?")
    led.seed_investigation()
    led.plan([{"title": "The facts: compare_groups on the D-1 jobs to see what is off", "status": "done", "note": "82 waiting"},
              {"title": "Where: identify which field and values hold the change", "status": "done", "note": "one pool"},
              {"title": "Why: check what the jobs depend on", "status": "in_progress"},
              {"title": "Check the cause: saturation of that pool", "status": "pending"},
              {"title": "Deeper: check the changes before the start", "status": "pending"},
              {"title": "Confirm the alert and rule out the others", "status": "pending"}])
    assert [(t.id, t.status) for t in led.tasks] == [(1, "done"), (2, "done"), (3, "in_progress"), (4, "pending"),
                                                     (5, "pending"), (6, "pending")]
    assert led.tasks[0].note == "82 waiting" and led.tasks[5].title == "Confirm the alert and rule out the others"
    # two findings of the system share their label: a rewritten one matches neither (a task of its own)
    a, b = led.add("Explain or rule out: rows waiting on one pool", by="system"), \
        led.add("Explain or rule out: a version slower", by="system")
    led.plan([{"title": "Explain or rule out: the pool", "status": "done"}])
    assert a.status == "pending" and b.status == "pending" and led.tasks[-1].title == "Explain or rule out: the pool"


def test_the_deeper_step_of_an_investigation_is_asked_for_unless_nothing_is_wrong(ctx, monkeypatch):
    """The answers found the cause and guessed what was behind it (a routine release) instead of reading what changed
    on the part they blamed: the seeded step "Deeper" still open is sent back once with the other gaps; an answer that
    finds nothing wrong, or a documented effect, has nothing behind it to look for."""
    from supagent.agent import LEDGER_NUDGE
    from test_agent_loop import agent_with, call, say

    cg = {"request": {"table": "jobs"}}
    plan = {"tasks": [{"id": 1, "title": "The facts", "status": "done", "note": "late"}]}
    replies = [call("work_plan", plan), call("compare_groups", cg)] + \
        [say("The jobs wait: the licence server ran out of tokens.")] * 4      # (other checks may ask too)
    a, _ran = agent_with(monkeypatch, replies, results=lambda n, args: '{"conclusion": "nothing numbered"}')
    a.names = a.names | {"compare_groups"}
    a.ask("Why are the jobs late this morning?")
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith(LEDGER_NUDGE[:40])]
    assert len(sent) == 1 and "task 5 (what changed behind the cause" in sent[0]
    b, _ran = agent_with(monkeypatch, [call("compare_groups", cg), say("Nothing is unusual: the batch is on time.")],
                         results=lambda n, args: '{"conclusion": "nothing numbered"}')
    b.names = b.names | {"compare_groups"}
    b.ask("Why are the jobs late this morning?")
    assert not b.usage.get("nudges")


def test_the_plan_comes_with_the_last_calls(ctx, monkeypatch):
    from supagent.agent import LAST_CALLS
    from test_agent_loop import agent_with, call, say

    sql = [{"request": {"database_id": 1, "sql": f"SELECT {i} AS n"}} for i in range(19)]
    a, _ran = agent_with(monkeypatch, [call("execute_sql", q) for q in sql] + [say("The cause is in the results above.")] * 3)
    a.ask("Why did the jobs fail?")
    told = [m for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith(LAST_CALLS)]
    assert told and "Your work plan (kept by the system)" in told[0]["content"] and "[ ] 5. Deeper" in told[0]["content"]


def test_a_turn_that_only_keeps_the_plan_is_not_one_of_the_calls(ctx, monkeypatch):
    """The investigation budget counts turns: on the 152, four of six investigations hit it after 4 to 8 turns spent
    only on work_plan. Such a turn gives its turn back (FREE_PLAN_TURNS at most); a plan update sent with another
    call counts as before."""
    from supagent import agent as agent_mod

    wp1 = {"tasks": [{"title": "Revenue of the week", "status": "in_progress"}]}
    wp2 = {"tasks": [{"title": "Revenue of the week", "status": "done", "note": "3"}]}
    sql = {"request": {"database_id": 1, "sql": "SELECT SUM(x) FROM orders"}}
    q = "Give me the revenue, the orders, the refunds and the returns of the week, and the share of each country."
    replies = [call("work_plan", wp1), call("execute_sql", sql), call("work_plan", wp2), say("Revenue: 3.")]
    a, ran = agent_with(monkeypatch, replies)
    a.max_steps = 2                                   # a request of many parts: 3 turns
    answer, _trace = a.ask(q)
    out_of_turns = lambda x: any(str(m.get("content")).startswith(agent_mod.OUT_OF_STEPS) for m in x.llm.seen[-1])  # noqa: E731
    assert answer.startswith("Revenue: 3.") and len(ran) == 1 and not out_of_turns(a)   # 2 turns given back
    monkeypatch.setattr(agent_mod, "FREE_PLAN_TURNS", 0)
    b, _ran = agent_with(monkeypatch, replies + [say("What was done: the revenue, 3.")])
    b.max_steps = 2
    b.ask(q)
    assert out_of_turns(b)                                      # without it: out of turns after the third


def test_out_of_calls_the_answer_keeps_what_the_plan_found(ctx, monkeypatch):
    """Two investigations of the team comparison ran out of calls with the cause in their plan's notes and answered
    nothing ("The model wrote no text") or "Let me check ...". Out of calls, the model gets its plan, and when it
    still writes nothing or only announces a step, the answer is what the plan's done tasks noted, said as such."""
    from supagent import agent as agent_mod

    monkeypatch.setattr(agent_mod, "FREE_PLAN_TURNS", 0)
    wp = {"tasks": [{"title": "Revenue of the week", "status": "done", "note": "3 EUR, all from shop A"},
                    {"title": "Refunds of the week", "status": "in_progress"}]}
    sql = {"request": {"database_id": 1, "sql": "SELECT SUM(x) FROM orders"}}
    q = "Give me the revenue, the orders, the refunds and the returns of the week, and the share of each country."
    for last in ("", "I have the revenue. Let me check the refunds now."):
        a, _ran = agent_with(monkeypatch, [call("work_plan", wp), call("execute_sql", sql), call("execute_sql", sql),
                                           say(last)])
        a.max_steps = 2                                   # 3 turns, then out of calls
        answer, _trace = a.ask(q)
        assert "Revenue of the week: 3 EUR, all from shop A" in answer and "Not checked: Refunds of the week" in answer
        assert "Your work plan (kept by the system)" in a.llm.seen[-1][-1]["content"]   # given its plan first
    b, _ran = agent_with(monkeypatch, [call("work_plan", wp), call("execute_sql", sql), call("execute_sql", sql),
                                       say("The revenue was 3 EUR; the refunds were not reached.")])
    b.max_steps = 2
    answer, _trace = b.ask(q)
    assert answer.startswith("The revenue was 3 EUR; the refunds were not reached.")       # its own answer: kept


def test_a_long_conversation_is_shortened_early_with_its_plan(ctx, monkeypatch):
    """Past agent.compact_at prompt tokens the older tool results are cut to their first lines and the plan is given
    again, once per level, long before the context is full (models read long contexts worse)."""
    from supagent import agent as agent_mod

    big = "R" * 6000
    wp = {"tasks": [{"title": "Revenue of the week", "status": "in_progress"}]}
    q = "Give me the revenue, the orders, the refunds and the returns, and the share of each country."
    sqls = [{"request": {"database_id": 1, "sql": f"SELECT SUM(x) AS part_{i} FROM orders"}} for i in range(6)]
    replies = [call("work_plan", wp)] + [call("execute_sql", x) for x in sqls] + [say("Revenue: 3.")]
    a, _ran = agent_with(monkeypatch, replies, results=lambda n, args: big)
    used = iter([1000, 9000, 26000, 27000, 28000, 37000, 38000, 39000, 39500, 40000])
    real_chat = a.llm.chat

    def chat(*args, **kw):
        out = real_chat(*args, **kw)
        a.llm.last_usage = {**a.llm.last_usage, "prompt_tokens": next(used)}
        return out

    monkeypatch.setattr(a.llm, "chat", chat)
    answer, _trace = a.ask(q)
    last = a.llm.seen[-1]
    notes = [m["content"] for m in last if m["role"] == "user" and m["content"].startswith("(The conversation was getting long")]
    assert len(notes) == 2 and "Your work plan (kept by the system)" in notes[0]       # at 26K, then at 37K (>36K)
    cut = [m for m in last if m["role"] == "tool" and "[shortened" in str(m["content"])]
    whole = [m for m in last if m["role"] == "tool" and "[shortened" not in str(m["content"])
             and len(str(m["content"])) > 2000]                     # the latest ones, as the tool gave them
    assert cut and len(whole) >= agent_mod.COMPACT_KEPT - 1 and answer.startswith("Revenue: 3.")


def test_the_last_calls_are_said_once_when_plan_turns_move_the_end(ctx, monkeypatch):
    """A plan-only turn at the end gives its turn back: "the last calls" is still said once, not at every turn
    the end moves by one."""
    from supagent.agent import LAST_CALLS
    from test_agent_loop import agent_with, call, say

    sql = [{"request": {"database_id": 1, "sql": f"SELECT {i} AS n"}} for i in range(18)]
    wp = [{"tasks": [{"title": f"Step {k}", "status": "in_progress"}]} for k in range(4)]
    a, _ran = agent_with(monkeypatch, [call("execute_sql", q) for q in sql] + [call("work_plan", w) for w in wp]
                         + [say("The cause is in the results above.")] * 3)
    a.ask("Why did the jobs fail?")
    told = [m for m in a.llm.seen[-1] if m["role"] == "user" and str(m["content"]).startswith(LAST_CALLS)]
    assert len(told) == 1


def test_an_answer_whose_time_is_up_answers_with_what_it_found(ctx, monkeypatch):
    """agent.answer_seconds: on a slow LLM server an investigation ran past the harness's 45 minutes and gave no
    answer at all (its plan's notes held the cause). Past the time, two calls are left, then the answer."""
    from supagent import agent as agent_mod, settings
    from test_agent_loop import agent_with, call, say

    clock = {"t": 1000.0}
    monkeypatch.setattr(agent_mod.time, "time", lambda: clock["t"])
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: 60 if key == "agent.answer_seconds" else real(key))
    sql = [{"request": {"database_id": 1, "sql": f"SELECT {i} AS n"}} for i in range(12)]
    a, ran = agent_with(monkeypatch, [call("execute_sql", q) for q in sql] + [say("What was found: 5 and 6.")] * 3)

    real_call = a._call

    def timed(name, args):                               # each call: 25 s
        clock["t"] += 25
        return real_call(name, args)

    monkeypatch.setattr(a, "_call", timed)
    answer, _trace = a.ask("Why did the jobs fail?")
    told = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and str(m["content"]).startswith(agent_mod.TIME_UP)]
    assert len(told) == 1 and len(ran) <= 6 and answer.strip()     # 12 calls scripted: it stopped, with an answer


def test_past_its_time_an_answer_is_marked_not_sent_back(ctx, monkeypatch):
    """Past agent.answer_seconds the checks no longer send the answer back (each costs a turn; a live run went on
    20 minutes past the time, sent back by one check after another): what they would send back is marked."""
    from supagent import agent as agent_mod, settings
    from test_agent_loop import agent_with, call, say

    clock = {"t": 1000.0}
    monkeypatch.setattr(agent_mod.time, "time", lambda: clock["t"])
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: 60 if key == "agent.answer_seconds" else real(key))
    sql = [{"request": {"database_id": 1, "sql": f"SELECT {i} AS n"}} for i in range(3)]
    a, _ran = agent_with(monkeypatch, [call("execute_sql", q) for q in sql]
                         + [say("Found 4,567 failed jobs and 8,912 retries.")] * 3)
    real_call = a._call

    def timed(name, args):
        clock["t"] += 25
        return real_call(name, args)

    monkeypatch.setattr(a, "_call", timed)
    answer, _trace = a.ask("How many jobs failed and how many were retried?")
    after = a.llm.seen[-1]
    sent_back = [m for m in after if m["role"] == "user" and str(m["content"]).startswith("(Check before")]
    assert answer.startswith("Found 4,567 failed jobs") and "(Check:" in answer and not sent_back
    assert len(a.llm.seen) == 4                          # 3 calls, then the answer: no turn more
