"""The same error again (0.9.6): in the lab's chats, 499 answers got one error two times or more, up to 19 times (a
field misnamed again and again, a chart config refused again, every raw query of a table refused by its source). For
the data tools, the second error of a kind says that changing other details does not fix it; exactly the same error
text three times from one tool on one table (the source fails whatever the query: "No mapping found for [_shard_doc]")
stops that tool there for the answer. A chart's config refused lists other points each time: never stopped. The
closest fields of a table are said with "does not exist"."""

import json

from test_agent_loop import agent_with, call, say

from supagent.agent import call_table, error_signature
from supagent.tools_superset import closest_columns


def col_error(name: str, table: str = "jobs") -> str:
    return json.dumps({"success": False, "error": f'ProgrammingError: Column "{name}" does not exist in "{table}". '
                                                  "Available: APPLICATION, STATUS_INFO, JOB_NAME, @timestamp"})


def q(sql: str) -> dict:
    return {"request": {"database_id": 1, "sql": sql}}


def test_the_signature_leaves_out_the_details():
    a = error_signature("execute_sql", q('SELECT "STATUS" FROM "jobs"'), col_error("STATUS"))
    b = error_signature("execute_sql", q('SELECT "STATE" FROM "jobs" WHERE x = 1'), col_error("STATE"))
    c = error_signature("execute_sql", q('SELECT "STATE" FROM "runs"'), col_error("STATE", "runs"))
    assert a == b and a != c and a[1] == "jobs"
    assert call_table({"chart_id": 12}) == "chart_id 12" and call_table({}) == ""


SOURCE_FAILS = json.dumps({"success": False, "error": "ProgrammingError: OpenSearch rejected the request: "
                           "query_shard_exception: No mapping found for [_shard_doc] in order to sort on"})


def test_the_source_failing_whatever_the_query_is_stopped(ctx, no_ledger, monkeypatch):
    sqls = [f'SELECT "{n}" FROM "books" LIMIT 100000' for n in ("NAME", "TITLE", "NAME, TITLE", "REGION")]
    replies = [call("execute_sql", q(x)) for x in sqls] + [call("execute_sql", q('SELECT COUNT(*) FROM "runs"'))] + \
        [say("The rows of books could not be read (the source fails); runs has 3.")] * 3

    def results(name, args):
        if '"runs"' in args["request"]["sql"]:
            return json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 3}], "row_count": 1})
        return SOURCE_FAILS

    a, ran = agent_with(monkeypatch, replies, results=results)
    a.ask("List the names and titles of the books.")
    tools = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"]
    assert "The same error as 1 earlier call" in tools[1]
    assert "same error 3 times from execute_sql on books: execute_sql is not run on books again" in tools[2]
    assert tools[3].startswith("tool error (not run: the same error 3 times)")
    assert len(ran) == 4 and ran[-1][1]["request"]["sql"].endswith('"runs"')


def test_a_field_misnamed_again_is_said_not_stopped(ctx, no_ledger, monkeypatch):
    sqls = [f'SELECT "{n}", COUNT(*) FROM "jobs" GROUP BY 1' for n in ("STATUS", "STATE", "JOB_STATUS", "RESULT")]
    replies = [call("execute_sql", q(x)) for x in sqls] + [call("execute_sql", q('SELECT COUNT(*) FROM "runs"'))] + \
        [say("The status field could not be read: 3 runs.")] * 3

    def results(name, args):
        sql = args["request"]["sql"]
        if '"runs"' in sql:
            return json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 3}], "row_count": 1})
        return col_error(sql.split('"')[1])

    a, ran = agent_with(monkeypatch, replies, results=results)
    a.ask("How many jobs per status?")
    tools = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"]
    assert "The same error as 1 earlier call" in tools[1] and "The same error as 3 earlier call" in tools[3]
    assert not any("not run: the same error" in t for t in tools)          # each a different name: all run
    assert len(ran) == 5                             # (the closest field is said by execute_sql itself: below)


def test_the_checks_own_refusals_are_never_stopped(ctx, no_ledger, monkeypatch):
    """A check that sends a call back (the period, a rule) says how to fix it: the third such refusal does not stop
    the table; only the note is added."""
    from supagent.agent import Agent

    replies = [call("execute_sql", q(f'SELECT COUNT(*) FROM "jobs" WHERE d = {i}')) for i in range(4)] + \
        [say("No figure: the period could not be read.")] * 3
    a, ran = agent_with(monkeypatch, replies)
    monkeypatch.setattr(Agent, "_refusal", lambda self, name, args: "tool error (not run: period): use the day asked")
    a.ask("How many jobs yesterday?")
    tools = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"]
    assert not any("not run: the same error" in t for t in tools)
    assert any("The same error as" in t for t in tools[1:])


def test_closest_fields_of_a_missing_column():
    said = closest_columns('ProgrammingError: Column "STATUS" does not exist in "jobs". Available: APPLICATION, '
                           "STATUS_INFO, JOB_NAME, @timestamp")
    assert '"STATUS_INFO"' in said and "APPLICATION" not in said
    said = closest_columns('Column \\"operation\\" does not exist in \\"spans\\". Available: operationName, duration')
    assert said.index('"operationName"') < said.index('"duration"') if '"duration"' in said else '"operationName"' in said
    assert closest_columns("ProgrammingError: syntax error") == ""


def test_a_chart_config_refused_again_is_neither_said_nor_stopped(ctx, no_ledger, monkeypatch):
    bad = json.dumps({"error": "invalid chart config: fix these points and call the tool again", "points": ["x"]})
    replies = [call("generate_chart", {"dataset_id": 4, "config": {"k": i}}) for i in range(4)] + [say("Saved.")] * 3
    a, ran = agent_with(monkeypatch, replies, results=lambda n, args: bad)
    a.names = a.names | {"generate_chart"}
    a.ask("Make a bar chart of the jobs per application.")
    tools = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"]
    assert not any("The same error as" in t or "not run: the same error" in t for t in tools)
