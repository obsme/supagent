"""(0.10.7) A follow-up that names its subject as a possessive and asks another measure ("What was queue-b's average
wait that day?" after "Which consumer had the most failures?") is about the subject, not about the failures the
previous question kept to; that question's own narrowing is told by its queries (no earlier answer kept its rows with
that condition), whatever words it used. Asked back instead of deciding, or asked back again word for word for a new
question: sent back."""

from __future__ import annotations

FIRST = "How many messages did queue-b receive on 3 March?"
RATE = "What was its failure rate?"
MOST = "Which consumer had the most failures?"
Q1 = ["SELECT COUNT(*) FROM msgs WHERE QUEUE = 'queue-b' AND ts >= '2031-03-03' AND ts < '2031-03-04'"]
Q2 = ["SELECT 100.0 * COUNT(*) FILTER (WHERE STATUS IN ('FAILED', 'EXPIRED')) / COUNT(*) FROM msgs WHERE "
      "QUEUE = 'queue-b' AND ts >= '2031-03-03' AND ts < '2031-03-04'"]
Q3 = ["SELECT CONSUMER, COUNT(*) FROM msgs WHERE QUEUE = 'queue-b' AND STATUS IN ('FAILED', 'EXPIRED') AND "
      "ts >= '2031-03-03' AND ts < '2031-03-04' GROUP BY CONSUMER ORDER BY 2 DESC"]
NOW = ["SELECT AVG(WAIT_MS) / 1000.0 FROM msgs WHERE QUEUE = 'queue-b' AND ts >= '2031-03-03' AND ts < '2031-03-04'"]


def test_a_named_subject_with_another_measure_is_not_the_previous_narrowing(ctx):
    from supagent.knowledge.carry import dropped

    q = "What was queue-b's average wait that day, in seconds?"
    assert dropped(q, Q3, NOW, MOST, [FIRST, RATE], Q1 + Q2) == []
    assert [c.column for c in dropped(q, Q3, NOW, MOST, [FIRST, RATE])] == ["STATUS"]   # (no earlier queries: as before)
    # the same name with no other measure: the narrowing goes on ("And queue-c's?" = queue-c's most failures)
    other = ["SELECT CONSUMER, COUNT(*) FROM msgs WHERE QUEUE = 'queue-c' AND ts >= '2031-03-03' AND "
             "ts < '2031-03-04' GROUP BY CONSUMER ORDER BY 2 DESC"]
    assert [c.column for c in dropped("And queue-c's?", Q3, other, MOST, [FIRST, RATE], Q1 + Q2)] == ["STATUS"]
    # a narrowing an earlier answer already kept its rows with is the chat's: carried
    failed_first = ["SELECT COUNT(*) FROM msgs WHERE QUEUE = 'queue-b' AND STATUS IN ('FAILED', 'EXPIRED') AND "
                    "ts >= '2031-03-03' AND ts < '2031-03-04'"]
    assert [c.column for c in dropped(q, Q3, NOW, MOST, [FIRST, RATE], failed_first)] == ["STATUS"]
    # "of them": the previous rows themselves
    assert [c.column for c in dropped("What was queue-b's average wait of them?", Q3, NOW, MOST, [FIRST, RATE],
                                      Q1 + Q2)] == ["STATUS"]


def test_a_measures_own_conditions_are_not_the_rows_kept():
    from supagent.knowledge.carry import _without_measures
    from supagent.knowledge.conditions import sql_conditions

    cols = {c.column for c in sql_conditions(_without_measures(Q2[0]))}
    assert "STATUS" not in cols and "QUEUE" in cols
    case = ("SELECT SUM(CASE WHEN STATUS = 'FAILED' THEN 1 ELSE 0 END) FROM msgs WHERE QUEUE = 'queue-b'")
    assert {c.column for c in sql_conditions(_without_measures(case))} == {"QUEUE"}


def test_the_carry_checks_say_to_decide():
    from supagent.agent import CARRY_HALF_NUDGE, CARRY_NUDGE

    assert "do not ask the user" in CARRY_NUDGE and "do not ask the user" in CARRY_HALF_NUDGE


def test_a_question_back_asked_again_for_a_new_question_is_sent_back(ctx, monkeypatch):
    import json

    from supagent.agent import REPEATED_NUDGE
    from test_agent_loop import agent_with, call, say

    back = ("I need to know the scope before I answer. The previous questions were about queue-b on 3 March.\n"
            "1. Whether it is still about queue-b only, or every queue of the broker\n"
            "2. Whether it is still about 3 March, or another period of the month\n"
            "Could you tell me which queue and which period you mean, so that I count the right messages?")
    rows = json.dumps({"success": True, "rows": [{"avg_wait_s": 1.25}], "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": NOW[0]}}
    a, _ran = agent_with(monkeypatch, [call("execute_sql", sql), say(back), say("Its average wait was 1.25 s.")],
                         results=lambda n, args: rows)
    chat = [{"role": "user", "content": MOST}, {"role": "assistant", "content": back}]    # its last answer: asked back
    answer, _trace = a.ask("What was queue-b's average wait that day, in seconds?", chat)
    assert answer.startswith("Its average wait was 1.25 s")
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user" and m["content"].startswith("(Check")]
    assert sent and sent[0].startswith(REPEATED_NUDGE.split("{question}")[0])
