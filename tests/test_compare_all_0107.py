"""(0.10.7, M3-0107n C13.4) "Compare with <another application>." after the average duration, the longest and the count over one hour of
another application's jobs: the answer compared the last measure only (the count over one hour), the average asked
first left out. A comparison that names no measure, after a chat of several, is given every measure asked so far."""
from __future__ import annotations

HISTORY = [{"role": "user", "content": "What was the average duration of the ZQA jobs on 2 October, in minutes?"},
           {"role": "assistant", "content": "The average duration of the ZQA jobs on 2 October was **5.1 minutes**."},
           {"role": "user", "content": "And the longest one?"},
           {"role": "assistant", "content": "The longest ZQA job ran **798.8 minutes**."},
           {"role": "user", "content": "How many of them ran for more than one hour?"},
           {"role": "assistant", "content": "**192 ZQA jobs** ran for more than one hour."}]


def test_a_bare_comparison_is_given_every_measure_of_the_chat(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    from supagent.agent import COMPARE_BARE

    a, _ran = agent_with(monkeypatch, [say("ZQB: average 4.2 minutes, longest 310.5 minutes, 78 over one hour.")] * 4)
    a.ask("Compare with ZQB.", HISTORY)
    asked = [m["content"] for m in a.llm.seen[0] if m["role"] == "user"][-1]
    assert "compares with ZQB without naming a measure" in asked
    assert all(q in asked for q in ("average duration of the ZQA jobs", "And the longest one?",
                                    "ran for more than one hour"))
    b, _ran = agent_with(monkeypatch, [say("ZQB: 78 jobs over one hour.")] * 4)
    b.ask("Compare the jobs over one hour with ZQB, per day?", HISTORY)       # a measure named: nothing added
    assert "without naming a measure" not in [m["content"] for m in b.llm.seen[0] if m["role"] == "user"][-1]
    assert COMPARE_BARE.match("Compare avec ZQB") and not COMPARE_BARE.match("Compare latency with errors")
