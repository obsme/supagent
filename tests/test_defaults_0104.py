"""(0.10.4) The agent changes measured with more silent mistakes on a held set ship off: the agent answers as 0.10.0
did unless an administrator turns them on."""
from __future__ import annotations


def test_the_measured_agent_changes_are_off_by_default(ctx):
    from supagent import settings
    from supagent.settings import SPECS

    defaults = {s.key: s.default for s in SPECS}
    for key in ("agent.correction_check", "agent.claimed_query_check", "agent.bare_doubt_check", "agent.announce_ing",
                "agent.link_limit_hint", "tools.brief_crossings"):
        assert defaults[key] is False, key


def test_an_announced_step_in_ing_is_seen_only_when_turned_on(ctx):
    from supagent import settings
    from supagent.agent import announces_action

    said = 'Let me also try searching for "risk" to see the other dashboards.'
    assert announces_action(said) is None
    settings.set_value("agent.announce_ing", True)
    try:
        assert announces_action(said)
    finally:
        settings.set_value("agent.announce_ing", False)


def test_the_brief_head_says_nothing_of_link_limits_by_default(ctx, monkeypatch):
    from supagent.knowledge import brief

    monkeypatch.setattr(brief, "build", lambda q, full=True: {"lines": ["x calls y"]})
    assert "highest or lowest value" not in brief.brief_block("why is x slow?")
    settings_on = __import__("supagent.settings", fromlist=["x"])
    settings_on.set_value("agent.link_limit_hint", True)
    try:
        assert "highest or lowest value" in brief.brief_block("why is x slow?")
    finally:
        settings_on.set_value("agent.link_limit_hint", False)
