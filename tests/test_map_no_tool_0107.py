"""(0.10.7, obs7dev-u) "Which applications consume the <topic> events, directly or through the mirror in <a site>?"
was answered from the prompt's knowledge with no tool, sent back ("you called no tool"), and answered again with no
tool: the consumers behind the mirror were missed. A question of the system map answered with no tool is sent back
with a tool compulsory: the map is its data."""
from __future__ import annotations

import json


def test_a_map_question_answered_with_no_tool_must_call_one(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    links = json.dumps({"part": "zq.orders", "consumers": ["zq-loyalty", "zq-mirror"],
                        "through": {"zq-mirror": ["zq-invoicing", "zq-analytics"]}})
    a, ran = agent_with(monkeypatch, [say("zq.orders is consumed by zq-loyalty and zq-mirror."),
                                      call("system_links", {"name": "zq.orders"}),
                                      say("zq-loyalty and, through zq-mirror, zq-invoicing and zq-analytics.")],
                        results=lambda n, args: links)
    a.names = a.names | {"system_links"}
    answer, _trace = a.ask("Which applications consume the zq.orders events, directly or through the mirror?")
    assert answer.startswith("zq-loyalty and, through zq-mirror") and [n for n, _a in ran] == ["system_links"]
    assert a.llm.choices[:2] == [None, "required"]


def test_the_investigation_asks_for_the_trigger_of_a_change_made_hours_before():
    """(obs7dev-u W07.1) a change of the day before 18:00 blamed for errors that began at 09:00, what began at 09:00 (a
    coupon campaign's orders) never looked for: the instructions ask for the trigger of a fault that waited."""
    from supagent.agent import SECTIONS

    text = " ".join(SECTIONS["investigation"].split())
    assert "made hours before the effect explains it only with what set it off then" in text
