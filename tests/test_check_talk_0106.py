"""(0.10.6) A reply to the no-tool check that speaks of the check instead of answering keeps the answer it was sent
on (main suite, "What does MTTR mean?": the glossary's definition was answered, the check sent it back, the reply
"No data query was needed as the question only asked for the definition of MTTR, which was provided based on the
team's glossary" became the answer, without the definition); a reply that answers is kept as before."""

from __future__ import annotations

from test_agent_loop import agent_with, say  # noqa: F401  (the scripted agent)


def test_a_reply_about_the_check_keeps_the_answer_before_it(ctx, monkeypatch):
    from supagent.agent import NO_TOOL_NUDGE

    first = "MTTR means the mean time to repair a failed job: from the failure to the job's successful run."
    meta = ("No data query was needed as the question only asked for the definition of MTTR, which was provided "
            "based on the team's glossary and documentation.")
    a, ran = agent_with(monkeypatch, [say(first), say(meta)])
    answer, _trace = a.ask("What does MTTR mean?", [])
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"] == NO_TOOL_NUDGE]
    assert sent and not ran
    assert answer.startswith("MTTR means the mean time to repair") and "No data query" not in answer


def test_a_reply_that_answers_again_is_kept(ctx, monkeypatch):
    first = "MTTR is mean time to repair."
    again = "MTTR means the mean time to repair a failed job, from its failure to its successful run."
    a, _ran = agent_with(monkeypatch, [say(first), say(again)])
    answer, _trace = a.ask("What does MTTR mean?", [])
    assert answer.startswith("MTTR means the mean time to repair a failed job")


def test_an_answer_with_figures_is_never_brought_back(ctx, monkeypatch):
    first = "There were 52 orders yesterday, 31 of them on the web."
    meta = "No data query was needed, as given above."
    a, _ran = agent_with(monkeypatch, [say(first), say(meta), say(meta)])
    answer, _trace = a.ask("How many orders were there yesterday?", [])
    assert "52 orders" not in answer
