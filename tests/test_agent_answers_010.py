"""(0.10) The agent's last message pointing back to an answer written earlier in the turn keeps that answer."""

from __future__ import annotations


def test_an_answer_written_beside_a_tool_call_is_not_lost(ctx):
    from supagent.agent import restore_earlier

    earlier = "HAProxy on lb1 sends the traffic to web1 and web2; they use the orders database on db1. " * 3
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"},
                {"role": "assistant", "content": earlier, "tool_calls": [{"function": {"name": "list_databases"}}]},
                {"role": "tool", "content": "[]"},
                {"role": "assistant", "content": "The answer above was based on the documentation."}]
    out = restore_earlier("The answer above was based on the documentation.", messages, 2)
    assert out.startswith("HAProxy on lb1") and out.endswith("documentation.")
    assert restore_earlier("web1 and web2.", messages, 2) == "web1 and web2."      # an answer of its own: kept as is
