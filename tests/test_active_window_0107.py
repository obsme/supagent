"""(0.10.7) An investigation read the alerts that STARTED in its window; an alert raised the day before and still
firing that morning (the warning that explained the outage) was never read. Records with a start and an end are
read by their overlap with the window: such a query is sent back once with that condition."""

from __future__ import annotations


def test_records_with_a_start_and_an_end_are_read_by_their_overlap(ctx, monkeypatch):
    from supagent.knowledge import period

    monkeypatch.setattr(period, "_date_fields", lambda tables: {"alerts": ["startsAt", "endsAt"],
                                                               "events": ["opened_at"]} if tables else {})
    sql = lambda where: {"request": {"database_id": 1, "sql": f'SELECT alertname FROM "alerts" WHERE {where}'}}  # noqa
    said = period.active_refusal("execute_sql", sql("startsAt >= TIMESTAMP '2031-03-03 00:00' AND "
                                                   "startsAt < TIMESTAMP '2031-03-03 12:00'"))
    assert said and "(not run: active in the window)" in said
    assert "startsAt < '2031-03-03 12:00' AND (endsAt > '2031-03-03 00:00' OR endsAt IS NULL)" in said
    assert period.active_refusal("execute_sql", sql("startsAt < '2031-03-03 12:00' AND endsAt > '2031-03-03 00:00'")) \
        is None                                                                    # the overlap: as asked
    assert period.active_refusal("execute_sql", sql("startsAt >= '2031-03-03 00:00'")) is None   # no window
    one = {"request": {"sql": "SELECT * FROM \"events\" WHERE opened_at >= '2031-03-03' AND opened_at < '2031-03-04'"}}
    assert period.active_refusal("execute_sql", one) is None                      # no end time: events
    assert period.active_refusal("describe_data", {"index": "alerts"}) is None
    assert period.START_FIELD.match("startsAt") and period.END_FIELD.match("endsAt")
    assert period.START_FIELD.match("started_at") and period.END_FIELD.match("resolved_at")
    assert not period.START_FIELD.match("start_of_week") and not END_FIELD_ok("weekend")


def END_FIELD_ok(name: str) -> bool:
    from supagent.knowledge.period import END_FIELD

    return bool(END_FIELD.match(name))


def test_only_an_investigation_is_sent_back(ctx, monkeypatch):
    import json

    from supagent.knowledge import period
    from test_agent_loop import agent_with, call, say

    monkeypatch.setattr(period, "_date_fields", lambda tables: {"alerts": ["startsAt", "endsAt"]} if tables else {})
    q = {"request": {"database_id": 1, "sql": "SELECT alertname FROM \"alerts\" WHERE startsAt >= '2031-03-03 00:00' "
                                               "AND startsAt < '2031-03-03 12:00'"}}
    rows = json.dumps({"success": True, "columns": [{"name": "alertname"}], "rows": [{"alertname": "A1"}],
                       "row_count": 1})
    a, ran = agent_with(monkeypatch, [call("execute_sql", q), say("One alert: A1.")], results=lambda n, args: rows)
    a.ask("Which alerts started on 3 March 2031 before noon?")
    assert len(ran) == 1                                                          # a list asked: as written


def test_said_once_per_answer(ctx, monkeypatch):
    from supagent.knowledge import period
    from test_agent_loop import agent_with

    monkeypatch.setattr(period, "_date_fields", lambda tables: {"alerts": ["startsAt", "endsAt"]} if tables else {})
    a, _ran = agent_with(monkeypatch, [])
    a.open_question, a._active_told = True, False
    q = lambda d: {"request": {"sql": f"SELECT 1 FROM \"alerts\" WHERE startsAt >= '{d} 00:00' AND startsAt < '{d} 09:00'"}}  # noqa
    assert a._active_in_window("execute_sql", q("2031-03-03"))
    assert a._active_in_window("execute_sql", q("2031-03-04")) is None          # once: the next query runs
