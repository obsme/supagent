"""(0.10.8) An answer began "Based on my investigation, I can now provide you with the answer:": the model about its
work, not for the user (0.10.7 removed "I have all the information needed ...")."""

from __future__ import annotations


def test_a_lead_that_announces_the_answer_is_removed():
    from supagent.agent import without_preamble

    body = "**The data holds no CPU figures for that service.** Its pods export no container metrics."
    assert without_preamble("Based on my investigation, I can now provide you with the answer:\n\n" + body) == body
    assert without_preamble("Here is the final answer.\n\n" + body) == body
    kept = "I can now say that 2 of its 3 pods restarted.\n\n" + body                 # a figure: it is the answer
    assert without_preamble(kept) == kept
