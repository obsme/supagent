"""(0.10.12) A last text that only says the work is done ("The answer is complete. All tasks have been done.", after the
plan's last update) is never the answer: the answer written before it (with a plan update or a call) is given, or
the model is asked once for the whole answer."""
from __future__ import annotations

import json

from supagent.agent import DONE_NUDGE, says_done_only

from test_agent_loop import agent_with, call, say

ROWS = json.dumps({"success": True, "columns": [{"name": "APP"}, {"name": "n"}],
                   "rows": [{"APP": "A", "n": 1204}, {"APP": "B", "n": 877}], "row_count": 2})
WRITTEN = ("Application A had 1,204 runs and application B had 877 in the period asked, so A ran the most. The runs "
           "of A came in two bursts and the runs of B were spread over the day; both counts come from the run table "
           "for the period, grouped by application, and no other application had a run in that period, so the two "
           "applications above are the whole list for it.")


def test_says_done_only():
    assert says_done_only("The answer is complete. All tasks have been done.")
    assert says_done_only("All tasks in the plan are done.")
    assert says_done_only("I have answered the question above.")
    assert says_done_only("La réponse est complète.")
    assert not says_done_only("No, the frontend deployment did not play a role. The investigation is complete.")
    assert not says_done_only("The answer is complete: 464.1 ms p95 for shop-checkout.")
    assert not says_done_only("Done.")
    assert not says_done_only("")


def test_the_answer_written_with_a_call_is_given(ctx, monkeypatch):
    with_call = call("execute_sql", {"sql": "SELECT app, count(*) FROM runs GROUP BY app"})
    with_call["content"] = WRITTEN
    a, ran = agent_with(monkeypatch, [call("execute_sql", {"sql": "SELECT app, count(*) FROM runs GROUP BY app"}),
                                      with_call, say("The answer is complete. All tasks have been done.")],
                        results=lambda name, args: ROWS)
    answer, _trace = a.ask("Which application ran the most?")
    assert "Application A had 1,204 runs" in answer
    assert "The answer is complete" not in answer


def test_nothing_written_before_it_is_asked_once(ctx, monkeypatch):
    a, _ran = agent_with(monkeypatch, [call("execute_sql", {"sql": "SELECT app, count(*) FROM runs GROUP BY app"}),
                                       say("All tasks have been done."), say(WRITTEN)], results=lambda name, args: ROWS)
    answer, _trace = a.ask("Which application ran the most?")
    assert "Application A had 1,204 runs" in answer
    assert any(m["role"] == "user" and m["content"] == DONE_NUDGE for m in a.llm.seen[-1])


NARRATION = ("Found 1,204 runs of application A and 877 of application B so far; the runs of A came in two bursts "
             "and the runs of B were spread over the day. Next I will read the logs of A around the bursts to see "
             "what the runs waited for, then the logs of B, and compare both with the usual day before writing the "
             "answer for the user.")


def test_out_of_calls_never_gives_the_text_written_with_calls(ctx, monkeypatch):
    """The out-of-calls summary reads only an answer written alone (as in 0.10.11): text sent with a call is often
    mid-work narration ("Found ..., next I will read the logs"), never given as the answer there."""
    def with_text(n):
        m = call("execute_sql", {"sql": f"SELECT app, count(*) FROM runs WHERE n > {n} GROUP BY app"})
        m["content"] = NARRATION
        return m
    a, ran = agent_with(monkeypatch, [with_text(n) for n in range(10)] + [say("Let me read the logs of A next:")] * 4,
                        results=lambda name, args: ROWS)
    answer, _trace = a.ask("Which application ran the most each day?")
    assert len(a.llm.seen) == 11               # ten steps, then the summary after the last call
    assert NARRATION not in answer
