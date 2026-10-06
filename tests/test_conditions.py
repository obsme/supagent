"""Every condition of a query comes from what was said: the question and the chat, the team's words, the
documents found, the formulas of the instructions, the rows an earlier query of the answer gave. A
condition the model adds by itself ("late" jobs counted among the successful ones only) is sent back before
the query runs; sent again unchanged, the query runs and the answer says the condition nobody asked for."""

from __future__ import annotations

import json

from supagent.knowledge.conditions import build, call_conditions, note, refusal, sql_conditions, unsaid

QUESTION = "According to our SLA note, how many BILLING jobs were late on 23 September?"
BLOCKS = ("What this user and the team asked to remember:\n- (team, fact) The critical applications are BILLING and "
          "PAYROLL (field APPLICATION).\n\nWhere the data is:\n- field \"STATUS\" (keyword; values: FAILED, KILLED, "
          "RUNNING, SUCCESS) of index \"jobs\" in database 1\n\nBackground:\n- [index] index jobs: fields: STATUS: "
          "FAILED, SUCCESS\n- [doc] SLA note: a job is late when it runs more than 45 minutes, that is DURATION_S > "
          "2700.\n\n(Now: Thursday 2026-09-24 23:30.)\n" + QUESTION)
SYSTEM = "Rules... CPU usage = busy %: 100 * SUM(rate) FILTER (WHERE mode <> 'idle') / SUM(rate)."


def _support(question=QUESTION, blocks=BLOCKS, history=()):
    messages = [{"role": "system", "content": SYSTEM}, *history, {"role": "user", "content": blocks}]
    return build(messages, [question, "The critical applications are BILLING and PAYROLL."])


def _sql(sql):
    return {"request": {"database_id": 1, "sql": sql}}


LATE = ('SELECT COUNT(*) FROM "jobs" WHERE "APPLICATION" = \'BILLING\' AND "DURATION_S" > 2700 AND '
        '"ts" >= \'2026-09-23 00:00\' AND "ts" < \'2026-09-24 00:00\'')


def test_a_condition_nobody_asked_for_is_found(ctx):
    s = _support()
    assert refusal(s, "execute_sql", _sql(LATE)) is None
    added = refusal(s, "execute_sql", _sql(LATE + ' AND "STATUS" = \'SUCCESS\''))
    assert added.startswith("tool error (not run: a condition nobody asked for)") and "STATUS = 'SUCCESS'" in added
    # the dictionary's list of every status is not a source; "45 minutes" is 2,700 seconds
    longer = QUESTION.replace("late", "longer than 45 minutes")
    assert refusal(_support(longer, longer), "execute_sql",
                   _sql('SELECT COUNT(*) FROM "jobs" WHERE "DURATION_S" > 2700')) is None
    assert unsaid(sql_conditions('SELECT COUNT(*) FROM "jobs" WHERE "APPLICATION" IN (\'BILLING\', \'ORDERS\')'),
                  s)[0].values == ["BILLING", "ORDERS"]                    # ORDERS: nobody said it


def test_what_was_said_in_other_words_is_found(ctx):
    def ok(question, sql, blocks=None, tool="execute_sql"):
        s = _support(question, blocks if blocks is not None else question)
        return refusal(s, tool, _sql(sql) if tool != "promql_query" else {"expr": sql}) is None

    assert ok("How many jobs failed yesterday?", 'SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'FAILED\'')
    assert ok("Show me the errors of BILLING", 'SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'FAILED\' AND '
                                               '"APPLICATION" = \'BILLING\'')
    assert ok("Failed jobs in production", 'SELECT COUNT(*) FROM "jobs" WHERE "ENV" = \'PROD\'')
    assert ok("How many jobs completed?", 'SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'SUCCESS\'')
    assert ok("HTTP 5xx errors per app", "SELECT app, SUM(increase) FROM http_requests_total WHERE code LIKE '5%' "
                                         "GROUP BY app")
    assert ok("Availability (not 5xx) per app", "SELECT app, SUM(increase) FILTER (WHERE code NOT LIKE '5%') FROM "
                                                "http_requests_total GROUP BY app")
    assert ok("Peak JVM heap per application", "SELECT app, MAX(value) FROM jvm_used WHERE area = 'heap' GROUP BY app")
    assert ok("CPU busy of srv-a", "SELECT 100 * SUM(rate) FILTER (WHERE mode <> 'idle') / SUM(rate) FROM cpu "
                                   "WHERE node = 'srv-a'", blocks="")        # the formula of the instructions
    assert ok("Relaunched jobs yesterday", 'SELECT COUNT(*) FROM "jobs" WHERE "RELAUNCHED" = true')
    assert ok("Jobs of the critical applications", 'SELECT COUNT(*) FROM "jobs" WHERE "APPLICATION" IN '
                                                   "('BILLING', 'PAYROLL')")   # the memory
    assert ok("CPU of fed-a", 'avg(temp{__tenant_id__="fed-a"})', tool="promql_query")
    assert ok("Errors of BILLING on 23 September", 'SELECT COUNT(*) FROM "jobs" WHERE "POSITION_DATE" = 20260923 '
                                                   "AND \"STATUS\" = 'FAILED'")      # a date: the period check
    assert not ok("How many jobs ran longer than 45 minutes?", "SELECT COUNT(*) FROM dur_bucket WHERE le = '3600'")
    assert not ok("How many jobs ran yesterday?", 'SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'SUCCESS\'')
    assert not ok("How many jobs ran yesterday?", 'SELECT COUNT(*) FROM "jobs" WHERE "ENV" = \'PROD\'')
    assert not ok("Jobs per server", 'SELECT "NODE", COUNT(*) FROM "jobs" GROUP BY 1 HAVING COUNT(*) > 100')


def test_what_an_earlier_query_of_the_answer_gave_is_said_too(ctx):
    s = _support("CPU busy % of the 2 servers with the most failed jobs", "")
    cpu = "SELECT node, AVG(busy) FROM cpu WHERE node IN ('srv-a', 'srv-b') GROUP BY node"
    assert refusal(s, "execute_sql", _sql(cpu))                             # not yet found
    s.add_result(json.dumps({"rows": [{"NODE": "srv-a", "failed": 43}, {"NODE": "srv-b", "failed": 42}]}))
    assert unsaid(call_conditions("execute_sql", _sql(cpu)), s) == []
    listed = _support("How many jobs ran?", "")
    listed.add_result(json.dumps({"rows": [{"STATUS": "SUCCESS"}, {"STATUS": "FAILED"}]}))   # a list of values
    assert refusal(listed, "execute_sql", _sql('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'SUCCESS\''))


def test_lists_charts_and_the_note(ctx):
    s = _support()
    assert call_conditions("execute_sql", _sql('SELECT DISTINCT "STATUS" FROM "jobs"')) == []   # looking, not counting
    chart = {"request": {"dataset_id": 1, "config": {"filters": [{"column": "STATUS", "op": "=", "value": "SUCCESS"}]}}}
    assert refusal(s, "generate_chart", chart)
    trace = [{"tool": "execute_sql", "status": "done", "args": _sql(LATE + ' AND "STATUS" = \'SUCCESS\'')}]
    assert note(s, trace).startswith("\n\n(Check: this answer counts only STATUS = 'SUCCESS'")
    assert note(s, [{"tool": "execute_sql", "status": "done", "args": _sql(LATE)}]) == ""


def test_the_agent_sends_it_back_then_marks_it(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    ASKED = "How many BILLING jobs ran longer than 45 minutes on 23 September?"     # noqa: N806
    rows = lambda n, args: json.dumps({"success": True, "columns": ["n"], "rows": [{"n": 337}]})  # noqa: E731
    added = _sql(LATE + ' AND "STATUS" = \'SUCCESS\'')
    a, ran = agent_with(monkeypatch, [call("execute_sql", added), call("execute_sql", _sql(LATE)),
                                      say("337 BILLING jobs were late on 23 September.")], results=rows)
    answer, trace = a.ask(ASKED)
    assert ran == [("execute_sql", _sql(LATE))] and answer == "337 BILLING jobs were late on 23 September."
    assert "a condition nobody asked for" in trace[0]["result"]
    b, ran = agent_with(monkeypatch, [call("execute_sql", added), call("execute_sql", added),
                                      say("337 BILLING jobs were late on 23 September.")], results=rows)
    answer, _trace = b.ask(ASKED)
    assert ran == [("execute_sql", added)] and "(Check: this answer counts only STATUS = 'SUCCESS'" in answer
    c, ran = agent_with(monkeypatch, [call("execute_sql", added), say("Nothing unusual.")], results=rows)
    c.ask("Is everything normal with the BILLING jobs right now?")        # an open question: its own choices
    assert ran == [("execute_sql", added)]


def test_more_of_what_was_found_or_said(ctx):
    s = _support("CPU busy % per hour of the 2 busiest servers", "")
    cpu = _sql("SELECT node, AVG(busy) FROM cpu WHERE node IN ('srv-a', 'srv-b') GROUP BY node")
    s.add_result(json.dumps({"series": [{"labels": {"node": "srv-a"}, "max": 91.0, "values": [["t", 91.0]]},
                                        {"labels": {"node": "srv-b"}, "max": 88.0, "values": [["t", 88.0]]}]}))
    assert refusal(s, "execute_sql", cpu) is None                          # the servers of a PromQL result
    cut = _support("Load of the servers with the most failed jobs", "")
    cut.add_result('{"rows": [{"NODE": "srv-a", "failed": 50}, {"NODE": "srv-b", "failed": 4')   # cut at 4000
    assert refusal(cut, "execute_sql", cpu) is None
    apps = _support("Excel extract of the failed jobs of today with the team of each application", "")
    apps.add_result(json.dumps({"rows": [{"APPLICATION": "BILLING"}, {"APPLICATION": "ORDERS"}]}),
                    "SELECT DISTINCT \"APPLICATION\" FROM \"jobs\" WHERE \"STATUS\" = 'FAILED'")   # a filtered list
    assert refusal(apps, "execute_sql", _sql("SELECT \"APPLICATION\", \"TEAM\" FROM \"apps\" WHERE \"APPLICATION\" "
                                             "IN ('BILLING', 'ORDERS')")) is None
    assert refusal(_support("How many jobs succeeded on 23 September?", ""), "execute_sql",
                   _sql('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'SUCCESS\'')) is None
    assert call_conditions("execute_sql", _sql("SELECT COUNT(*) FROM information_schema.tables WHERE "
                                               "table_schema = 'default'")) == []


def test_a_value_with_an_underscore_found_earlier(ctx):
    s = _support("Excel extract of the failed jobs with the team of each application", "")
    s.add_result(json.dumps({"rows": [{"APPLICATION": "BILLING_API"}]}),
                 "SELECT DISTINCT \"APPLICATION\" FROM \"jobs\" WHERE \"STATUS\" = 'FAILED'")
    assert refusal(s, "execute_sql", _sql("SELECT \"TEAM\" FROM \"apps\" WHERE \"APPLICATION\" = 'BILLING_API'")) is None


def test_each_condition_is_sent_back_once(ctx, monkeypatch):
    s = _support("How many jobs ran longer than 45 minutes on 23 September?", "")
    both = refusal(s, "execute_sql", _sql("SELECT SUM(increase) FROM dur_bucket WHERE le IN ('1800', '3600')"))
    assert "le IN '1800', '3600'" in both and "histogram bucket (le)" in both
    assert refusal(s, "execute_sql", _sql("SELECT SUM(increase) FROM dur_bucket WHERE le = '3600'")) is None
    assert refusal(s, "execute_sql", _sql("SELECT SUM(increase) FROM dur_bucket WHERE le <> '3600'"))  # the other side
    assert refusal(s, "execute_sql", _sql('SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'SUCCESS\''))
    from test_agent_loop import agent_with, call, say

    rows = lambda n, args: json.dumps({"success": True, "columns": ["n"], "rows": [{"n": 337}]})  # noqa: E731
    first, variant = _sql(LATE + ' AND "STATUS" = \'SUCCESS\''), _sql(LATE + ' AND "STATUS" IN (\'SUCCESS\')')
    a, ran = agent_with(monkeypatch, [call("execute_sql", first), call("execute_sql", variant),
                                      say("337 BILLING jobs were late on 23 September.")], results=rows)
    answer, _trace = a.ask("How many BILLING jobs ran longer than 45 minutes on 23 September?")
    assert ran == [("execute_sql", variant)] and "(Check: this answer counts only STATUS IN 'SUCCESS'" in answer


def test_durations_in_words_ranks_and_french_flags_are_said(ctx):
    """Seventeen of eighteen stored answers marked "a condition nobody asked for" were right: "more than one hour"
    written <duration in seconds> > 3600 (an hour in words: no number), WHERE rn = 1 on the query's own ROW_NUMBER() (a
    rank, not a data value), RELAUNCHED = true for "relancée". Said now; a condition nobody said is still found."""
    def ok(question, sql):
        return refusal(_support(question, question), "execute_sql", _sql(sql)) is None

    assert ok("How many of them ran for more than one hour?", 'SELECT COUNT(*) FROM "jobs" WHERE "DURATION_S" > 3600')
    assert ok("How many ran for more than an hour?", 'SELECT COUNT(*) FROM "jobs" WHERE "DURATION_S" > 3600')
    assert ok("Combien ont duré plus d'une demi-heure ?", 'SELECT COUNT(*) FROM "jobs" WHERE "DURATION_S" > 1800')
    assert not ok("How many ran for more than an hour?", 'SELECT COUNT(*) FROM "jobs" WHERE "DURATION_S" > 5400')
    top = ('SELECT * FROM (SELECT "TRADER", SUM("PNL") AS pnl, ROW_NUMBER() OVER (ORDER BY SUM("PNL") DESC) AS rn '
           'FROM "pnl" GROUP BY 1) t WHERE rn <= 3')
    assert ok("Who were the top 3 traders?", top)
    assert not ok("Who were the top 3 traders?", top + " AND \"TRADER\" <> 'TR001'")      # a data condition still
    assert [c.said() for c in sql_conditions('SELECT COUNT(*) FILTER (WHERE "EXPRESS" = true) AS express FROM "o"')] \
        == ["EXPRESS = True"]                         # a field named like the alias its own query computes
    assert ok("Quelle part des jobs du 23 septembre a été relancée ?",
              'SELECT COUNT(*) FILTER (WHERE "RELAUNCHED" = true) FROM "jobs"')
    assert not ok("Quelle part des jobs du 23 septembre a échoué ?",
                  'SELECT COUNT(*) FILTER (WHERE "RELAUNCHED" = true) FROM "jobs"')


def test_a_count_said_in_words_supports_its_condition(ctx):
    """dev4 G04.1 (D's final run): "How many customers placed more than one sold order in September?" counted with
    HAVING COUNT(*) > 1 inside the outer COUNT was refused as "a condition nobody asked for" (a number in words was
    read only before a time unit), the model removed it as told and answered 6,154 for 2,899. A number said in words
    anywhere in the question supports that number (not its unit factors); a condition on another number still not."""
    def ok(question, sql):
        return refusal(_support(question, question), "execute_sql", _sql(sql)) is None

    q = "How many customers placed more than one sold order in September?"
    sql = 'SELECT COUNT(*) FROM (SELECT "CUSTOMER_ID" FROM "orders" GROUP BY "CUSTOMER_ID" HAVING COUNT(*) > 1)'
    assert ok(q, sql)
    assert ok("Which desks traded at least twice with CPTY_1?", 'SELECT "DESK" FROM "t" GROUP BY 1 HAVING COUNT(*) >= 2')
    assert ok("Combien de clients ont passé plus de deux commandes ?",
              'SELECT COUNT(*) FROM (SELECT "C" FROM "o" GROUP BY 1 HAVING COUNT(*) > 2)')
    assert not ok(q, 'SELECT COUNT(*) FROM (SELECT "CUSTOMER_ID" FROM "orders" GROUP BY 1 HAVING COUNT(*) > 3)')
    assert not ok("How many jobs ran for more than one hour?", 'SELECT COUNT(*) FROM "jobs" WHERE "RETRIES" > 7')


def test_a_memory_that_applies_when_the_user_says_x_is_no_support_without_x(ctx):
    """"When the user says 'NOVA', filter by APPLICATION='NOVA'" (a real user's memory): a question that does not
    say NOVA gets no NOVA filter from it; one that says NOVA does."""
    from supagent.knowledge.conditions import untriggered

    block = ("What this user and the team asked to remember (...):\n- (this user, rule) When the user says 'NOVA', "
             "filter by APPLICATION='NOVA'.\n- (team, fact) Jobs run in PROD and UAT.")
    assert "NOVA" not in untriggered(block, "Which error category caused the most job failures?")
    assert "Jobs run in PROD and UAT" in untriggered(block, "Which error category caused the most job failures?")
    assert "NOVA" in untriggered(block, "How many NOVA jobs failed?")
    assert "NOVA" not in untriggered("- (this user, rule) Quand l'utilisateur dit « NOVA », filtrer APPLICATION='NOVA'.",
                                      "Combien de jobs ont échoué ?")
    q = "Which error category caused the most job failures in PROD on 23 September?"
    s = build([{"role": "user", "content": block + "\n" + q}], [q, block])
    sql = ('SELECT "ERROR_CATEGORY", COUNT(*) FROM "jobs" WHERE "STATUS" = \'FAILED\' AND "ENV" = \'PROD\' '
           'AND "APPLICATION" = \'NOVA\' GROUP BY 1')
    assert [c.said() for c in unsaid(sql_conditions(sql), s)] == ["APPLICATION = 'NOVA'"]
    q2 = "How many NOVA jobs failed in PROD?"
    s2 = build([{"role": "user", "content": block + "\n" + q2}], [q2, block])
    assert unsaid(sql_conditions(sql), s2) == []


def test_failing_says_an_error_flag_and_a_status_class():
    """"How many of them failed?" counted with http_response_status_code >= 400, "the failing calls" kept with
    tag.error = 'true': both were sent back as conditions nobody asked for (0.9.5)."""
    from supagent.knowledge.conditions import Support, _value_said

    s = Support()
    s.add("And how many of them failed?", people=True)
    assert _value_said(400.0, "http_response_status_code", s) and _value_said(500.0, "tag.http@status_code", s)
    assert not _value_said(404.0, "http_response_status_code", s)          # a code of its own: to be said
    assert not _value_said(400.0, "amount", s)                             # not a status field
    f = Support()
    f.add("What do the failing calls have in common?", people=True)
    assert _value_said("true", "tag.error", f)
    n = Support()
    n.add("How many calls were there yesterday?", people=True)
    assert not _value_said("true", "tag.error", n) and not _value_said(400.0, "http_response_status_code", n)


def test_a_value_an_investigation_tool_found_supports_its_condition():
    """records_about named the switch behind the alerts (sw-core-01): the next query filtered on it was refused as a
    condition nobody asked for (0.9.5); what the investigation tools find is said for the next queries."""
    from supagent.agent import FINDING_TOOLS
    from supagent.knowledge.conditions import Support, _value_said

    s = Support()
    s.add("What was the most frequent error of the inventory service this morning?", people=True)
    assert not _value_said("sw-core-01:%", "instance", s)
    s.add_finding('{"tables": [{"table": "alerts", "records": 3, "latest": [{"alertname": "SwitchPortErrors", '
                  '"labels.instance": "sw-core-01", "labels.ifName": "xe-0/0/2", "max_ms": 4997}]}]}')   # (as the loop)
    assert _value_said("sw-core-01:%", "instance", s) and _value_said("xe-0/0/2", "ifName", s)
    assert not _value_said(4997.0, "duration_ms", s)            # a finding's figure never makes a threshold asked
    assert not _value_said("4997", "duration_ms", s) and 4997.0 not in s.numbers
    t = Support()
    t.add_finding("not json: the switch sw-core-01 had 4997 errors")
    assert _value_said("sw-core-01", "instance", t) and not _value_said(4997.0, "errors", t)
    assert "records_about" in FINDING_TOOLS and "describe_data" not in FINDING_TOOLS
