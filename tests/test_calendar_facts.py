"""The calendar facts of an investigation's days the team's knowledge speaks of (candidate C)."""

from __future__ import annotations

import datetime as dt


def test_the_facts_of_a_day():
    from supagent.knowledge.calendar_facts import days_of, facts

    third = dict(facts(dt.date(2026, 8, 21)))                  # a Friday, the 21st: the third of August
    assert "the third Friday of August" in third and "3rd friday" in third["the third Friday of August"]
    end = [f for f, _p in facts(dt.date(2026, 9, 30))]          # Wednesday 30 September
    assert "the last business day of the month" in end and "the last business day of the quarter" in end
    assert "the first business day of the month" in [f for f, _p in facts(dt.date(2026, 6, 1))]
    assert days_of("Why is the night batch late this morning?", dt.date(2026, 8, 24)) == \
        [dt.date(2026, 8, 24), dt.date(2026, 8, 21)]               # Monday, and the Friday before (D-1)


def test_only_knowledge_that_says_the_fact_is_given():
    from supagent.knowledge.calendar_facts import documented, note

    docs = [{"title": "Monthly expiry", "text": "On the third Friday of each month the equity derivatives expire: "
                                                "about 60% more trades, the night batch runs longer."},
            {"title": "Friday checks", "text": "Every Friday the backups are verified."}]
    lines = documented("Why are the jobs longer than usual this morning?", dt.date(2026, 8, 24), lambda q: docs)
    assert len(lines) == 1 and lines[0].startswith("Friday 21 August 2026 is the third Friday of August")
    assert "Monthly expiry" in lines[0] and "Friday checks" not in lines[0]
    assert "is the explanation" in note(lines)
    assert documented("Why are the jobs late?", dt.date(2026, 8, 26), lambda q: docs) == []   # not such a day


def test_an_investigation_gets_them_with_the_question(ctx, monkeypatch):
    from test_agent_loop import agent_with, say

    from supagent.knowledge import calendar_facts

    monkeypatch.setattr(calendar_facts, "documented", lambda q, today, search=None: ["Friday 21 August 2026 is the "
                        "third Friday of August; the team's knowledge speaks of such a day: Monthly expiry"])
    a, _ran = agent_with(monkeypatch, [say("ok")] * 3)
    msgs = a.prompt("Why is the night batch late this morning?", [])
    assert "The calendar of the days looked at" in msgs[-1]["content"]
    b, _ran = agent_with(monkeypatch, [say("ok")] * 3)
    assert "The calendar of the days" not in b.prompt("How many jobs ran yesterday?", [])[-1]["content"]
