"""(0.10.9) An open question ("What is the number of errors?") was asked back with no call, as wanted, but with kinds of
data as choices ("pricing errors, job failures, HTTP errors") instead of the System map's parts the note gave; another
put its long list of choices after the question. The question back is sent back once to name some of the parts, and a
question written first with its choices listed under it (a long list too) is a question back, the question moved last."""

from __future__ import annotations

PARTS = {"application": ["app-a", "app-b", "app-c"], "component": ["db-x"]}


def test_a_question_back_naming_no_part_is_sent_back_once(ctx, monkeypatch):
    from supagent.knowledge import ambiguity
    from test_agent_loop import agent_with, say

    monkeypatch.setattr(ambiguity, "map_parts", lambda: PARTS)
    kinds = "Which errors do you mean: the pricing errors, the job failures or the HTTP errors?"
    parts = "Which part do you mean: app-a, app-b, app-c or db-x (or all of them), and for which day?"
    a, ran = agent_with(monkeypatch, [say(kinds), say(parts), say(parts)])
    answer, _trace = a.ask("What is the number of errors?")
    assert answer.startswith(parts) and ran == []
    told = [m["content"] for m in a.llm.seen[1] if m["role"] == "user"][-1]
    assert "app-a, app-b, app-c, db-x" in told


def test_parts_named_or_another_kind_keep_the_answer():
    from supagent.agent import open_parts_unnamed

    unclear = {"kind": "open", "parts": PARTS}
    assert open_parts_unnamed(unclear, "Which errors: pricing, jobs or HTTP?") == "app-a, app-b, app-c, db-x"
    assert open_parts_unnamed(unclear, "Which part: App-A or db-x?") == ""
    assert open_parts_unnamed({"kind": "choice"}, "Which one?") == ""


def test_a_long_list_of_choices_under_the_question_puts_the_question_last():
    from supagent.agent import question_last

    options = "\n".join(f"{i}. **Option {i}**: the counter of failed requests number {i}, with its labels" for i in range(18))
    text = "Which of these do you mean, and for which day?\n" + options
    assert len(text) > 1200                                       # longer than a question back used to be moved at
    assert question_last(text).endswith("Which of these do you mean, and for which day?")
