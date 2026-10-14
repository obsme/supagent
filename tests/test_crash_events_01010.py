"""(0.10.10) A crash said in an answer whose reason no query read: the pod's events (OOMKilled, Evicted, a failed probe)
were never looked at, so the cause the answer gives is a guess; the agent is sent back once to read them."""

from __future__ import annotations


def _trace(*tables):
    return [{"tool": "execute_sql", "status": "done",
             "args": {"request": {"database_id": 1, "sql": f'SELECT COUNT(*) FROM "{t}" WHERE "pod" = \'x\''}}}
            for t in tables]


def test_a_crash_with_a_guessed_cause_and_the_events_unread(ctx, monkeypatch):
    from supagent import agent

    monkeypatch.setattr(agent, "_event_tables", lambda: ["kube-events-*"])
    answer = "Pod web-7f9 entered a crash loop due to timeout errors from the payment gateway."
    got = agent.crash_unread(answer, _trace("app-logs", "spans-*"))
    assert got and got[0].lower().startswith("crash loop") and got[1] == "kube-events-*"


def test_no_check_once_the_events_were_read_or_the_reason_given(ctx, monkeypatch):
    from supagent import agent

    monkeypatch.setattr(agent, "_event_tables", lambda: ["kube-events-*"])
    answer = "Pod web-7f9 entered a crash loop due to timeouts."
    assert agent.crash_unread(answer, _trace("app-logs", "kube-events-*")) is None    # the events were read
    assert agent.crash_unread(answer, _trace("app-logs", "kube-events-2026.10.02")) is None   # an index of the pattern
    assert agent.crash_unread("The pods were killed: OOMKilled at 09:00.", _trace("app-logs")) is None   # its reason
    assert agent.crash_unread("Errors rose at 09:00 on checkout.", _trace("app-logs")) is None   # no crash said


def test_no_check_without_any_table_of_events(ctx, monkeypatch):
    from supagent import agent

    monkeypatch.setattr(agent, "_event_tables", lambda: [])
    assert agent.crash_unread("The pod crashed twice.", _trace("app-logs")) is None


def test_tables_read_by_queries_and_by_table_arguments(ctx):
    from supagent.agent import _tables_read

    trace = _trace("app-logs") + [{"tool": "compare_logs", "status": "done", "args": {"table": "Svc-Logs-*"}},
                                  {"tool": "describe_data", "status": "done", "args": {"index": "kube-events-*"}}]
    assert _tables_read(trace) == {"app-logs", "svc-logs-*", "kube-events-*"}
