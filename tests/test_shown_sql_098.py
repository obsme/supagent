"""(0.9.8) An answer that shows a query as the one behind its figures when no call ran it (the figures of two other
queries, a joined query written in the text): sent back once to run it; a template (placeholders), a question that
asks for the SQL, a query that was run (spaces and case aside): nothing said; still shown after: marked."""

from supagent.agent import SHOWN_SQL_NOTE, SHOWN_SQL_NUDGE, shown_not_run, unsupported_answer, unsupported_note


def done(sql):
    return {"tool": "execute_sql", "called": "execute_sql", "status": "done", "args": {"request": {"sql": sql}}}


RAN = [done('SELECT SUM("PRICE") FROM "subscriptions" WHERE "START" >= \'2030-01-01\''),
       done('SELECT SUM("FEE") FROM "cancellations" WHERE "DAY" >= \'2030-01-01\'')]
SHOWN = ('Net: 1,234.\n\nThe SQL query run was:\n```sql\nSELECT SUM(s."PRICE") - SUM(c."FEE") FROM "subscriptions" s '
         'LEFT JOIN "cancellations" c ON c."SUB_ID" = s."SUB_ID"\n```')


def test_a_query_shown_that_no_call_ran(app):
    with app.app_context():
        assert shown_not_run(SHOWN, RAN)
        assert unsupported_answer(SHOWN, RAN, "What was the net amount in January?") == SHOWN_SQL_NUDGE
        assert unsupported_note(SHOWN, RAN, "What was the net amount in January?") == SHOWN_SQL_NOTE


def test_what_is_not_judged(app):
    same = 'Total: 99.\n\n```sql\nselect sum("PRICE")   from "subscriptions" where "START" >= \'2030-01-01\';\n```'
    assert not shown_not_run(same, RAN)                                           # the query run, written otherwise
    template = 'To get it:\n```sql\nSELECT SUM("FEE") FROM "cancellations" WHERE "DAY" >= \'<start>\'\n```'
    assert not shown_not_run(template, RAN)                                       # a template
    with app.app_context():
        assert unsupported_answer(SHOWN, RAN, "Which SQL query gives the net amount?") != SHOWN_SQL_NUDGE   # asked
    assert not shown_not_run(SHOWN, [])                                           # no query ran: another check


def test_the_check_has_its_setting(app, monkeypatch):
    from supagent import settings

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: False if k == "agent.shown_sql_check" else real(k))
    with app.app_context():
        assert unsupported_answer(SHOWN, RAN, "What was the net amount in January?") != SHOWN_SQL_NUDGE
