"""(0.10.7) A day said in several words ("the day before yesterday", "3 days ago", "last week"): the period check took
the words just before its last word ("the day before") for the event of the period, missed the verb before the whole
phrase, and asked for the table's other time. A day said in several words is one date phrase: the words before the
whole phrase name its event."""
from __future__ import annotations


def test_the_event_before_a_day_said_in_several_words(app):
    from supagent.knowledge.period import event_words, named_among

    fields = ["OPENED_TIME", "CLOSED_TIME"]
    for q in ("How many tickets were closed the day before yesterday?", "How many tickets were closed 3 days ago?",
              "How many tickets were closed last week?", "How many tickets were closed this morning?"):
        assert "closed" in event_words(q), q
        assert named_among(q, fields) == {"CLOSED_TIME"}, q
    assert named_among("How many tickets were opened yesterday?", fields) == {"OPENED_TIME"}   # as before
