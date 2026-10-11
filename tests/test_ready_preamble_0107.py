"""(0.10.7) An investigation's answer began "I have all the information needed to write the complete answer. The
investigation is thorough ... No additional tool calls are needed.": the model about its work, not for the user."""

from __future__ import annotations


def test_a_ready_statement_before_the_answer_is_removed():
    from supagent.agent import without_preamble

    body = "## Root cause\n\nThe queue's consumer was redeployed with a bad setting; its errors began with it."
    lead = ("I have all the information needed to write the complete answer. The investigation is thorough with "
            "clear evidence from logs, metrics and records. No additional tool calls are needed.\n\n")
    assert without_preamble(lead + body) == body
    assert without_preamble("No further tool calls are needed.\n\n" + body) == body
    kept = "I have enough data on 3 days: the queue grew on each.\n\n" + body       # a figure: it is the answer
    assert without_preamble(kept) == kept
    assert without_preamble(body) == body
