"""Rows late before they could run waited for their inputs, not for a slot (candidate C): the first stage
compare_groups finds off, before the stage the rows start at, and an answer that blames capacity is sent back once."""

from __future__ import annotations

import json

from test_agent_loop import agent_with, call, say

STAGES = ["SCHEDULED_TIME: rows that had reached it: 120 (as usual)",
          "READY_TIME (its inputs ready): rows that had reached it: 38 against 120 usually",
          "START_TIME: rows that had reached it: 36 against 118 usually",
          "END_TIME: rows that had reached it: 30 against 110 usually"]


def result(first: str) -> str:
    return json.dumps({"conclusion": f"In the order of the stages, {first} is the first that is clearly off: what is "
                                     "late after it may only be late in its wake. What stands out ...",
                       "stages": STAGES})


def test_the_first_stage_off_before_the_rows_run():
    from supagent.knowledge.groups import before_start

    assert before_start(result("READY_TIME")) == "READY_TIME"            # not ready: waiting for inputs
    assert before_start(result("START_TIME")) is None                   # ready, not started: a wait for capacity
    assert before_start(result("END_TIME")) is None                     # started, longer
    assert before_start("Nothing stands out: every measure is as usual.") is None
    assert before_start(json.dumps({"conclusion": result("READY_TIME")})) is None    # no stages: not said


def test_capacity_named_as_a_cause():
    from supagent.agent import capacity_blamed

    assert capacity_blamed("Cause identifiée : saturation du pool GRID_A.")
    assert capacity_blamed("The jobs are late because the pool is full: 40 of 40 slots taken.")
    assert not capacity_blamed("The cause is the positions feed, 238 minutes late. The pool was not saturated.")
    assert not capacity_blamed("Cause: the late feed; capacity was fine.")
    assert not capacity_blamed("The queue backlog is as usual for this hour.")
    assert capacity_blamed("The root cause is a grid queue saturation caused by the upstream jobs.")
    assert not capacity_blamed("Root cause: a server left the cache cluster at 00:25, reducing cache capacity.")
    # French, and the negation of another clause (a live answer of candidate C: "causé", "car")
    assert capacity_blamed("Le retard est causé par une saturation du pool GRID_A qui retarde le démarrage des jobs.")
    assert capacity_blamed("Les jobs ne démarrent pas car le pool est saturé : aucun n'a encore de START_TIME.")
    assert not capacity_blamed("Le pool n'était pas saturé : ce n'est pas la cause.")
    assert not capacity_blamed("Ce n'est pas une saturation du pool qui explique le retard.")
    assert not capacity_blamed("The jobs waited for their inputs, not for slots: the feed was late, which caused it.")
    # capacity as an effect, or "du" (an article, not "dû")
    assert not capacity_blamed("Queue saturation is not the primary cause: the buildup is typical for this hour.")
    assert not capacity_blamed("The pool was saturated (40/40 slots), but this was a consequence, not the cause.")
    assert not capacity_blamed("Les jobs en étape PRICING restent bloqués, occupant les 32 slots du pool.")


def test_a_full_pool_blamed_for_rows_not_ready_is_sent_back_once(ctx, monkeypatch):
    from supagent import settings
    from supagent.agent import STAGE_NUDGE

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: False if key == "agent.ledger" else real(key))
    blamed = say("The night jobs are late because the pool GRID_A is saturated.")
    fixed = say("The night jobs waited for their inputs: the positions feed arrived late.")
    a, _ran = agent_with(monkeypatch, [call("compare_groups", {"request": {"table": "jobs"}}), blamed, fixed],
                         results=lambda n, args: result("READY_TIME"))
    a.names = a.names | {"compare_groups"}
    answer, _trace = a.ask("Why are the night jobs late this morning?")
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith("(Check before")]
    assert sent == [STAGE_NUDGE.format(stage="READY_TIME")] and answer.startswith("The night jobs waited for their inputs")
    b, _ran = agent_with(monkeypatch, [call("compare_groups", {"request": {"table": "jobs"}}), blamed],
                         results=lambda n, args: result("START_TIME"))
    b.names = b.names | {"compare_groups"}
    answer, _trace = b.ask("Why are the night jobs late this morning?")
    assert answer.startswith("The night jobs are late because the pool") and not b.usage.get("nudges")   # ready, waiting


def test_the_inputs_note_survives_a_long_result_and_its_logs_lead_joins_the_plan(ctx, monkeypatch):
    """The system's notes go after the result, the result cut to make room (a long comparison used to push them
    past the result limit, the logs lead first); the comparison's findings are still taken into the work plan (the
    note made the result unreadable as JSON), and what the inputs' logs say that they do not usually is a task the
    answer must explain or rule out."""
    from supagent import agent as A

    note = ('\n(The rows were late before they were ready: they waited for their inputs. What the system map says '
            'they take in: FEED_A (feed), which APP_Q takes in.)\n(What the logs of APP_UP on POOL_A say that they do '
            'not usually (applogs, read by the system): What the logs say that they do not usually: (1) "<name> still '
            'waiting for its inputs after # min: <name>" (WARN, 1974 lines, none on the earlier days).)')
    monkeypatch.setattr(A.Agent, "_inputs_note", lambda self, args, content="": note)
    big = json.loads(result("READY_TIME"))
    big["conclusion"] += (' (1) rows past SCHEDULED_TIME and not yet at READY_TIME then (above usual in total): on '
                          '"POOL", concentrated on POOL_A (82 against 0 usually) above usual.')
    big["padding"] = "x" * (A.TOOL_CHARS["compare_groups"] + 1000)  # a comparison longer than the result limit
    a, _ran = agent_with(monkeypatch, [call("compare_groups", {"request": {"table": "jobs"}})]
                         + [say("The jobs waited for FEED_A: APP_UP was still waiting for its inputs.")] * 3,
                         results=lambda n, args: json.dumps(big))
    a.names = a.names | {"compare_groups"}
    a.ask("Why are the night jobs late this morning?")
    got = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"][0]
    assert len(got) <= A.TOOL_CHARS["compare_groups"] + 50 and note in got and "...[truncated]" in got
    titles = [t.title for t in a.ledger.tasks]
    assert any(t.startswith("Explain or rule out: rows past SCHEDULED_TIME") for t in titles)          # the finding
    lead = next(t for t in a.ledger.tasks if "the logs of the inputs say" in t.title)
    assert "still waiting for its inputs" in lead.title and "waiting" in lead.keys
    assert lead not in a.ledger.uncovered("The jobs waited for FEED_A: APP_UP was still waiting for its inputs.")
    assert lead in a.ledger.uncovered("The pool was full.")


def test_logs_read_everywhere_while_the_change_is_in_one_pool_are_read_again_there(ctx, monkeypatch):
    """The first comparison says where the change is (on "POOL", concentrated on POOL_A); a compare_logs over every
    pool gets, once, the advice to read that pool's lines (the same lines of the other pools hid a new pattern)."""
    from supagent.knowledge import linkfinder

    monkeypatch.setattr(linkfinder, "log_tables", lambda: [
        {"table": "applogs", "owners": {"APPLICATION": "application", "POOL": "pool"}}])
    cg = json.loads(result("START_TIME"))                   # (ready, not started: no inputs note in this test)
    cg["conclusion"] += ' (1) rows past READY_TIME: on "POOL", concentrated on POOL_A (82 against 0 usually) above usual.'
    logs = {"conclusion": "Nothing new in the logs: every pattern of the window is there on the earlier days as much."}
    a, _ran = agent_with(monkeypatch, [call("compare_groups", {"request": {"table": "jobs"}}),
                                       call("compare_logs", {"table": "applogs", "start": "2026-09-07 00:00",
                                                             "end": "2026-09-08 04:40", "where": "\"APPLICATION\" IN ('A')"}),
                                       call("compare_logs", {"table": "applogs", "start": "2026-09-07 00:00",
                                                             "end": "2026-09-08 04:40", "where": "\"APPLICATION\" IN ('B')"})]
                         + [say("The rows of POOL_A wait.")] * 3,
                         results=lambda n, args: json.dumps(cg) if n == "compare_groups" else json.dumps(logs))
    a.names = a.names | {"compare_groups", "compare_logs"}
    a.ask("Why are the night jobs late this morning?")
    tools = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"]
    hinted = [t for t in tools if "concentrated on POOL = POOL_A" in t]
    assert len(hinted) == 1 and "\"POOL\" IN ('POOL_A')" in hinted[0] and hinted[0] is tools[1]
