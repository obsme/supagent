"""A question about an earlier answer ("create the chart in Superset of that finding"): the agent
sees the queries that gave that answer's rows, with their database and time window (a query only
written in the answer's text did not run), and looks for the data of the question it refers to. A
finding that is a calculation is saved as a virtual dataset, then charted; the tool checks the
user's right to create datasets, and gives back the same dataset when asked again."""

from __future__ import annotations

import json
import sqlite3

import pytest

from test_knowledge import world  # noqa: F401  (the fixture)

from test_agent_loop import agent_with, call, say
from test_stop import FakeAgent

PROMQL = '100 * (1 - avg by (instance) (rate(node_cpu_seconds_total{instance="srv-amer-002:9100",mode="idle"}[5m])))'
FINDING = {"tool": "promql_query", "sql": PROMQL, "database": "Prometheus", "database_id": 3,
           "start": "2026-09-24 18:00", "end": "2026-09-25 06:00", "step": "5m",
           "columns": ["ts", "instance", "value"], "rows": [["2026-09-24 18:00", "srv-amer-002:9100", 12.1]],
           "row_count": 144, "truncated": False}
PROBE = {"tool": "promql_query", "sql": PROMQL.replace(":9100", ""), "database": "Prometheus", "database_id": 3,
         "columns": ["ts"], "rows": [], "row_count": 0, "truncated": False}
JOBS = {"tool": "execute_sql", "sql": "SELECT APP, COUNT(*) n FROM jobs GROUP BY 1", "database": "OpenSearch",
        "database_id": 1, "columns": ["APP", "n"], "rows": [["A", 3]], "row_count": 1, "truncated": False}
FOLLOW_UP = "According to that finding, please create the chart in Superset."


def test_the_queries_of_an_answer_are_the_ones_that_gave_its_rows(ctx):
    from supagent.runner import queries_of

    out = queries_of([FINDING, PROBE])
    assert out == [{"tool": "promql_query", "database": "Prometheus", "database_id": 3, "start": "2026-09-24 18:00",
                    "end": "2026-09-25 06:00", "step": "5m", "query": PROMQL, "columns": ["ts", "instance", "value"],
                    "rows": 144}]                                   # the empty probe is not the finding
    assert len(queries_of([JOBS, FINDING, JOBS])) == 2               # the last two
    assert len(queries_of([dict(JOBS, sql="SELECT " + "x, " * 400 + "1")])[0]["query"]) == 700


def test_the_last_answers_go_with_their_queries(app, monkeypatch):
    from superset.extensions import db, security_manager as sm

    from supagent import runner
    from supagent.knowledge import experience, generic
    from supagent.models import Conversation, Message

    seen: dict = {}

    class Capture(FakeAgent):
        stop = False

        def ask(self, question, history=None):
            seen["history"], seen["question"] = history, question
            return super().ask(question, history)

    with app.app_context():
        conv = Conversation(user_id=sm.find_user(username="alice").id, title="CPU")
        db.session.add(conv)
        db.session.flush()
        for role, content, results in (("user", "How many jobs per application?", None),
                                       ("assistant", "A: 3.", [JOBS]),
                                       ("user", "Show me the CPU usage of host srv-amer-002 over the last 12 hours.", None),
                                       ("assistant", "CPU climbed from 12% to 42%.", [PROBE, FINDING]),
                                       ("user", "Thanks!", None),
                                       ("assistant", "You are welcome.", None),
                                       ("user", FOLLOW_UP, None)):
            db.session.add(Message(conversation_id=conv.id, role=role, content=content, status="done", results=results))
        answer = Message(conversation_id=conv.id, role="assistant", status="pending", steps=[])
        db.session.add(answer)
        db.session.commit()
        monkeypatch.setattr("supagent.agent.Agent", type("Agent", (Capture,), {"message_id": answer.id}))
        monkeypatch.setattr(generic, "generalize", lambda *a, **k: {})
        monkeypatch.setattr(experience, "learn_from_answer", lambda *a, **k: None)
        runner.run_answer(answer.id)
    history = seen["history"]
    assert seen["question"] == FOLLOW_UP and [h["role"] for h in history] == ["user", "assistant"] * 3
    assert [bool(h.get("queries")) for h in history] == [False, True, False, True, False, False]
    assert history[3]["queries"][0]["query"] == PROMQL and history[3]["queries"][0]["start"] == "2026-09-24 18:00"


def test_the_agent_sees_what_that_finding_was(ctx, monkeypatch):
    from supagent.agent import HISTORY_CHARS, Agent
    from supagent.runner import queries_of

    subjects: list[str] = []
    a, _ran = agent_with(monkeypatch, [say("Saved."), say("Saved.")])
    monkeypatch.setattr(Agent, "_question_blocks", lambda self, q, shown=None: subjects.append(q) or "")
    earlier = "Show me the CPU usage of host srv-amer-002 over the last 12 hours."
    answer = "CPU climbed from 12% to 42%.\n\n```sql\nSELECT cpu_busy_pct FROM x\n```"
    history = [{"role": "user", "content": earlier},
               {"role": "assistant", "content": answer, "queries": queries_of([PROBE, FINDING])}]
    a.ask(FOLLOW_UP, history)
    sent = a.llm.seen[0]
    assert next(m["content"] for m in sent if m["role"] == "assistant") == answer   # the answer as it was
    asked = sent[-1]["content"]                                       # with the new question: what it ran
    assert asked.endswith(FOLLOW_UP) and "only written in an answer's text did not run" in asked
    assert f'- the answer to "{earlier}":' in asked
    assert ("promql_query on database 'Prometheus' (id 3), from 2026-09-24 18:00 to 2026-09-25 06:00, step 5m: "
            + PROMQL + " -> columns ts, instance, value") in asked
    assert subjects == [f"{earlier}\n{FOLLOW_UP}"]                   # where the data is: the finding's question

    subjects.clear()
    b, _ = agent_with(monkeypatch, [say("12 jobs."), say("12 jobs.")])
    monkeypatch.setattr(Agent, "_question_blocks", lambda self, q, shown=None: subjects.append(q) or "")
    b.ask("How many jobs failed on 23 September?", history)          # a new question: its own data
    assert subjects == ["How many jobs failed on 23 September?"]

    c, _ = agent_with(monkeypatch, [say("ok"), say("ok")])
    c.ask(FOLLOW_UP, [{"role": "user", "content": earlier},
                      {"role": "assistant", "content": "x" * 5000, "queries": queries_of([FINDING])}])
    assert len(next(m["content"] for m in c.llm.seen[0] if m["role"] == "assistant")) == HISTORY_CHARS
    assert PROMQL in c.llm.seen[0][-1]["content"]
    d, _ = agent_with(monkeypatch, [say("ok"), say("ok"), say("ok")])      # (no count: asked for one)
    d.ask("How many jobs failed?", [])                                # a first question: nothing added
    assert d.llm.seen[0][-1]["content"].endswith("How many jobs failed?") and "computed from" not in d.llm.seen[0][-1]["content"]


def test_follow_up_questions_are_recognised():
    from supagent.agent import refers_back

    for q in (FOLLOW_UP, "Save it as a chart in Superset", "Do the same for srv-emea-001",
              "Crée ce graphique dans Superset", "Crée le graphique de ce résultat dans Superset"):
        assert refers_back(q), q
    for q in ("How many jobs failed this week?", "Show the CPU usage of srv-amer-002 over the last 12 hours",
              "Combien de jobs ont échoué cette semaine ?", "How many jobs failed on 23 September?"):
        assert not refers_back(q), q


# ------------------------------------------------------------------------------------------------ #
@pytest.fixture()
def local_db(app, tmp_path):
    """A SQLite database the agent may use, with a small table of samples."""
    from superset.connectors.sqla.models import SqlaTable
    from superset.extensions import db
    from superset.models.core import Database

    from supagent import settings

    path = tmp_path / "samples.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE samples (ts TEXT, node TEXT, value REAL)")
    con.executemany("INSERT INTO samples VALUES (?, ?, ?)",
                    [("2026-09-24 18:00:00", "srv-amer-002", 12.5), ("2026-09-24 19:00:00", "srv-amer-002", 20.0)])
    con.commit()
    con.close()
    with app.app_context():
        d = Database(database_name="samples-test", sqlalchemy_uri=f"sqlite:///{path}")
        db.session.add(d)
        db.session.commit()
        database_id = d.id
        settings.set_value("agent.databases", ["samples-test"])
    yield database_id
    with app.app_context():
        settings.set_value("agent.databases", [])
        for ds in db.session.query(SqlaTable).filter(SqlaTable.database_id == database_id):
            db.session.delete(ds)
        db.session.delete(db.session.get(Database, database_id))
        db.session.commit()


def test_a_finding_is_saved_as_a_virtual_dataset_once(app, local_db, monkeypatch):
    from supagent.security import acting_as
    from supagent.tools_superset import VirtualDatasetRequest, create_virtual_dataset

    sql = "SELECT ts, node, value FROM samples WHERE node = 'srv-amer-002'"
    ask = lambda q, name="CPU busy % srv-amer-002": create_virtual_dataset(   # noqa: E731
        VirtualDatasetRequest(database_id=local_db, sql=q, name=name))
    with app.app_context():
        with acting_as("admin"):
            first = ask(sql + ";")
            assert not first.get("error"), first
            assert [c["name"] for c in first["columns"]] == ["ts", "node", "value"]
            assert first["time_column"] == "ts" and first["reused"] is False   # charts filter on it
            again = ask(sql)                                              # a retry: the same dataset
            assert again["dataset_id"] == first["dataset_id"] and again["reused"] is True
            other = ask("SELECT ts, value FROM samples")
            assert other["name"] == "CPU busy % srv-amer-002 (2)" and other["dataset_id"] != first["dataset_id"]
            from superset.extensions import security_manager

            monkeypatch.setattr(security_manager, "can_access_database", lambda database: False)
            refused = ask("SELECT ts, value FROM promql('up')")
            assert "promql() reads the whole database" in refused["error"]
        with acting_as("alice"):                                           # Gamma + AI Agent: no dataset writes
            assert "Dataset write permission" in ask(sql)["error"]


def test_the_dataset_tool_is_offered_for_charts_and_suggested_when_a_field_is_missing(ctx, monkeypatch):
    import json

    from supagent.agent import Agent

    a = object.__new__(Agent)
    a.rich, a.wants_saved_chart = True, False
    a.specs = [{"function": {"name": n}} for n in ("execute_sql", "create_virtual_dataset", "generate_chart")]
    names = lambda q: [s["function"]["name"] for s in a._specs_for(q)]   # noqa: E731
    assert names("How many jobs failed yesterday?") == ["execute_sql"]
    a.wants_saved_chart = True
    assert "create_virtual_dataset" in names(FOLLOW_UP)

    b, _ran = agent_with(monkeypatch, [say("ok")])
    b.names |= {"create_virtual_dataset"}
    monkeypatch.setattr(b.guard, "_dataset", lambda ident: ({"ts", "node_cpu", "value"}, set()))
    _name, _args, content = b.guard.before("generate_chart", {"request": {
        "dataset_id": 6, "save_chart": True, "chart_name": "CPU",
        "config": {"chart_type": "xy", "kind": "line", "x": {"name": "ts"},
                   "y": [{"name": "cpu_busy_pct", "aggregate": "AVG"}]}}})
    details = json.loads(content)["details"]
    assert any("unknown column 'cpu_busy_pct'" in d for d in details)
    assert any("create_virtual_dataset" in d for d in details)


def test_the_cpu_usage_hint_is_the_busy_share_not_the_cores(ctx):
    from supagent.knowledge.resolve import _sql

    cpu = _sql({"name": "node_cpu_seconds_total", "metric_type": "counter", "labels": ["cpu", "mode", "node"]})
    assert "100 * SUM(rate) FILTER (WHERE mode <> 'idle') / SUM(rate) AS busy_pct" in cpu
    assert "SUM(rate) AS per_second" in _sql({"name": "http_requests_total", "metric_type": "counter",
                                               "labels": ["code", "node"]})


def test_a_promql_dataset_needs_the_findings_window(app, local_db):
    from supagent.security import acting_as
    from supagent.tools_superset import VirtualDatasetRequest, create_virtual_dataset

    with app.app_context(), acting_as("admin"):
        out = create_virtual_dataset(VirtualDatasetRequest(
            database_id=local_db, sql="SELECT ts, node, value FROM promql('100 * avg by (node) (up)')", name="up"))
        assert "needs the finding's time window" in out["error"]      # a chart grouped by node would fail


def test_the_datasets_of_tries_that_did_not_make_the_chart_are_dropped(app, local_db):
    import json

    from superset.connectors.sqla.models import SqlaTable
    from superset.extensions import db

    from supagent.security import acting_as
    from supagent.tools_superset import VirtualDatasetRequest, create_virtual_dataset, drop_unused_datasets

    def made(sql, name):
        res = create_virtual_dataset(VirtualDatasetRequest(database_id=local_db, sql=sql, name=name))
        return {"tool": "create_virtual_dataset", "status": "done", "result": json.dumps(res)}, res["dataset_id"]

    with app.app_context(), acting_as("admin"):
        (try1, first), (try2, second) = made("SELECT ts FROM samples", "try"), made("SELECT ts, value FROM samples", "try")
        failed = {"tool": "generate_chart", "status": "error", "args": {"request": {"dataset_id": first}}}
        chart = {"tool": "generate_chart", "status": "done",
                 "args": {"request": {"dataset_id": second, "save_chart": True}}}
        assert drop_unused_datasets([try1, failed, try2]) == []         # no chart saved: nothing deleted
        assert drop_unused_datasets([try1, failed, try2, chart]) == [first]
        assert db.session.get(SqlaTable, first) is None and db.session.get(SqlaTable, second) is not None


def test_an_osagg_dataset_with_order_by_is_wrapped():
    from supagent.tools_superset import osagg_safe

    sql = 'SELECT "APP", COUNT(*) AS n FROM "jobs" GROUP BY "APP" ORDER BY n DESC'
    assert osagg_safe(sql, "osagg") == f"SELECT * FROM ({sql}) AS agent_query"      # LIMIT 0 goes outside
    assert osagg_safe('SELECT "APP", COUNT(*) FROM "jobs" GROUP BY 1', "osagg") == 'SELECT "APP", COUNT(*) FROM "jobs" GROUP BY 1'
    assert osagg_safe(sql, "promagg") == sql


def test_the_agent_has_every_tool_and_no_helper_as_a_tool():
    from supagent import tools, tools_superset  # noqa: F401  (registers the tools)

    names = set(tools.mcp.tools)
    assert {"execute_sql", "list_databases", "list_datasets", "get_dataset_info", "create_virtual_dataset",
            "describe_data", "search_knowledge", "export_excel", "chart_image", "send_email", "promql_query",
            "check_health", "compare_to_usual", "data_changes"} <= names
    assert not {"osagg_safe", "latest_tries", "name_results"} & names


def test_a_chart_of_a_period_needs_its_date_filter(app, local_db, monkeypatch):
    import types

    from superset.connectors.sqla.models import SqlaTable, TableColumn
    from superset.extensions import db

    from supagent.agent import Agent, ChartGuard

    with app.app_context():
        ds = SqlaTable(table_name="samples", database_id=local_db, main_dttm_col="ts")
        ds.columns = [TableColumn(column_name="ts", is_dttm=True, type="TEXT"),
                      TableColumn(column_name="node", type="TEXT"), TableColumn(column_name="value", type="REAL")]
        db.session.add(ds)
        db.session.commit()
        a = object.__new__(Agent)
        a.question, a.names = "CPU per server on 24 September, as a saved bar chart", {"generate_chart"}
        a.superset = types.SimpleNamespace(available=True, error=None, call=lambda n, args: "{}")
        guard = ChartGuard(a)
        config = {"chart_type": "xy", "x": {"name": "node"}, "y": [{"name": "value", "aggregate": "SUM"}], "kind": "bar"}
        assert 'no filter on the time column "ts"' in guard._period_missing(ds.id, config)[0]
        dated = dict(config, filters=[{"column": "ts", "op": ">=", "value": "2026-09-24 00:00"}])
        assert guard._period_missing(ds.id, dated) == []
        a.question = "CPU per server, as a saved bar chart"                     # no period asked: fine
        assert guard._period_missing(ds.id, config) == []


def test_the_agent_is_told_what_a_saved_chart_returns(ctx):
    import json
    import types

    from supagent.agent import Agent, ChartGuard

    a = object.__new__(Agent)
    a.names = {"get_chart_data", "update_chart"}
    rows = [{"APP": f"A{i}", "failed": 10 - i} for i in range(10)]
    a.superset = types.SimpleNamespace(available=True,
                                       call=lambda name, args: json.dumps({"data": rows, "row_count": 10}))
    guard = ChartGuard(a)
    out = guard.after("update_chart", {"request": {"identifier": 7, "config": {}}}, json.dumps({"success": True}))
    assert "(the saved chart 7 returns 10 row(s) now; first: APP=A0, failed=10" in out


def test_a_saved_chart_needs_a_name(ctx):
    import types

    from supagent.agent import Agent, ChartGuard

    a = object.__new__(Agent)
    a.names, a.question = {"generate_chart"}, "failed jobs per app"
    a.superset = types.SimpleNamespace(available=False, call=lambda n, args: "{}")
    guard = ChartGuard(a)
    guard.parse = None
    guard._dataset = lambda ident: None
    config = {"chart_type": "xy", "x": {"name": "APP"}, "y": [{"name": "n", "aggregate": "SUM"}], "kind": "bar"}
    _n, _a, refused = guard.before("generate_chart", {"request": {"dataset_id": None, "config": config,
                                                                 "save_chart": True}})
    assert refused and "needs a chart_name" in refused
    _n, _a, fine = guard.before("generate_chart", {"request": {"dataset_id": None, "config": config,
                                                              "save_chart": True, "chart_name": "Failed jobs - 23 Sep"}})
    assert fine is None
    # the name the request gave ("save it as 'X'"): filled in, not refused (a model sent the same nameless call 8 times)
    a.question = "Make a table chart of the failed jobs per app and save it as 'Failed jobs per app - 23 Sep'."
    req = {"dataset_id": None, "config": config, "save_chart": True}
    _n, args, named = guard.before("generate_chart", {"request": req})
    assert named is None and args["request"]["chart_name"] == "Failed jobs per app - 23 Sep"


def test_a_chart_said_renamed_with_no_call_is_a_claimed_change():
    from supagent.agent import CHART_CHANGE_CLAIM, action_claim

    said = 'The chart has been renamed to "Sold orders per day". It is available at: /explore/?slice_id=395.'
    assert CHART_CHANGE_CLAIM.search(said) and action_claim(said, []) == (
        "the chart was changed", "update_chart with generate_preview false")
    assert CHART_CHANGE_CLAIM.search("Le graphique a été renommé « Commandes ».")


def test_update_chart_cannot_change_the_dataset(ctx):
    import types

    from supagent.agent import Agent, ChartGuard

    a = object.__new__(Agent)
    a.names, a.question = {"update_chart"}, "change it to 23 September"
    a.superset = types.SimpleNamespace(available=False, call=lambda n, args: "{}")
    guard = ChartGuard(a)
    _n, _a, refused = guard.before("update_chart", {"request": {"identifier": 7, "dataset_id": 55, "config": {}}})
    assert refused and "cannot change the dataset" in refused and "add_chart_to_existing_dashboard" in refused


def test_a_chart_change_is_saved_and_an_unsaved_preview_is_never_called_a_change(ctx):
    """"Make it a pie chart instead.": Superset's update_chart only makes an unsaved preview by default (the saved
    chart keeps its type), and the answer said "The chart has been updated to a pie chart" (0.9.1, two runs out of
    two). The change is saved unless the user asks for a preview; a preview's result says it is not saved; an answer
    that says the chart changed with no change saved is marked."""
    import json
    import types

    from supagent.agent import Agent, ChartGuard, claims_check

    a = object.__new__(Agent)
    a.names, a.question = {"update_chart"}, "Make it a pie chart instead."
    a.superset = types.SimpleNamespace(available=False, call=lambda n, args: "{}")
    guard = ChartGuard(a)
    guard.parse = None
    guard._dataset = lambda ident: None
    args = {"request": {"identifier": 7, "config": {"chart_type": "pie"}}}
    _n, sent, refused = guard.before("update_chart", args)
    assert refused is None and sent["request"]["generate_preview"] is False
    a.question = "Show me a preview of it as a pie chart, without saving."
    args = {"request": {"identifier": 7, "config": {"chart_type": "pie"}}}
    _n, sent, _r = guard.before("update_chart", args)
    assert "generate_preview" not in sent["request"]                      # Superset's default: a preview
    a.question = "Make it a pie chart."
    _n, sent, _r = guard.before("update_chart", {"request": {"identifier": 7, "config": {}, "generate_preview": True}})
    assert sent["request"]["generate_preview"] is True                    # said by the model: kept
    preview = json.dumps({"chart": {"id": 7, "viz_type": "echarts_timeseries_bar", "form_data_key": "k",
                                    "is_unsaved_state": True}})
    out = guard.after("update_chart", {"request": {"identifier": 7}}, preview)
    assert "NOT SAVED" in out and "generate_preview false" in out
    trace = [{"tool": "update_chart", "status": "done", "args": {"request": {"identifier": 7}}, "result": out}]
    note = claims_check("The chart has been updated to a pie chart.", trace)
    assert "the saved chart was not changed" in note
    saved = json.dumps({"chart": {"id": 7, "viz_type": "pie", "is_unsaved_state": False}})
    trace = [{"tool": "update_chart", "status": "done", "args": {"request": {"identifier": 7}}, "result": saved}]
    assert claims_check("The chart has been updated to a pie chart.", trace) == ""
    assert "the saved chart was not changed" in claims_check("I changed the chart to a pie chart.", [])


def test_a_time_column_a_chart_filter_cannot_name_asks_for_a_dataset(app, local_db):
    import types

    from superset.connectors.sqla.models import SqlaTable, TableColumn
    from superset.extensions import db

    from supagent.agent import Agent, ChartGuard

    with app.app_context():
        ds = SqlaTable(table_name="samples", database_id=local_db, main_dttm_col="@timestamp_date")
        ds.columns = [TableColumn(column_name="@timestamp_date", is_dttm=True, type="TEXT"),
                      TableColumn(column_name="node", type="TEXT")]
        db.session.add(ds)
        db.session.commit()
        a = object.__new__(Agent)
        a.question, a.names = "failed jobs per node on 23 September", set()
        guard = ChartGuard(a)
        msg = guard._period_missing(ds.id, {"chart_type": "xy", "x": {"name": "node"}})[0]
        assert "cannot be used in a chart filter" in msg and "create_virtual_dataset" in msg


def test_the_same_saving_call_is_not_made_again(ctx, monkeypatch):
    import json

    from test_agent_loop import agent_with, call, say

    same = {"request": {"identifier": 124, "config": {"chart_type": "xy"}, "generate_preview": False}}
    a, ran = agent_with(monkeypatch, [call("update_chart", same), call("update_chart", same), say("Done.")],
                        results=lambda n, args: json.dumps({"success": True}))
    a.names |= {"update_chart"}
    a.ask("Change chart 124")
    assert len(ran) == 1                                                # the second one: "already made"


def test_earlier_answers_named_by_their_place_are_a_follow_up():
    """"What is the ratio of the first to the second?" after two revenue questions was routed to a new subject and
    answered with a temperature over a latency. The first/the second, the former/the latter, both of them, du premier
    au second, les deux chiffres refer to the answers before; "the first trade of the day" does not."""
    from supagent.agent import refers_back

    assert refers_back("What is the ratio of the first to the second?")
    assert refers_back("And the latter?") and refers_back("Compare both of them.")
    assert refers_back("Quel est le rapport du premier au second ?") and refers_back("Et les deux chiffres ensemble ?")
    assert not refers_back("What was the first trade of the day?")
    assert not refers_back("Which desk was second in September?")
    assert not refers_back("How many orders were sold in the first week?")


def test_a_question_back_that_offers_to_keep_or_drop_the_question_before_is_answered(ctx, monkeypatch):
    """"I meant the ones delivered that day." after "How many shipments were late on 22 September?" was answered with
    "the late shipments delivered on 22 September, or all of them?": the follow-up keeps what the question before
    said, so the question back is sent back once with a query made compulsory. A question back that offers nothing
    of the question before, or one at the start of a conversation, is left alone."""
    from supagent.agent import KEEP_ASK_NUDGE
    from supagent.knowledge.resolve import keep_or_drop

    before = "How many shipments were late on 22 September?"
    ask = ("Do you want the count of **late shipments delivered on 22 September**, or **all shipments delivered on 22 "
           "September** (late or on time)?")
    assert keep_or_drop(before, ask) == ["shipments", "late", "september"]
    assert keep_or_drop(before, "Which carrier do you mean?") is None                     # nothing to keep or drop
    assert keep_or_drop("", ask) is None
    assert keep_or_drop("Combien de colis étaient en retard le 22 septembre ?",
                        "Voulez-vous les colis en retard livrés ce jour-là, ou tous les colis livrés ce jour-là ?") \
        == ["colis", "retard"]
    sql = {"request": {"database_id": 1, "sql": "SELECT COUNT(*) AS n FROM shipments"}}
    rows = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 81}], "row_count": 1})
    a, ran = agent_with(monkeypatch, [say(ask), call("execute_sql", sql), say("81 late shipments were delivered on 22 "
                                                                               "September.")], results=lambda n, args: rows)
    out, _trace = a.ask("I meant the ones delivered that day.",
                        [{"role": "user", "content": before}, {"role": "assistant", "content": "37 shipments were late."}])
    assert out.startswith("81 late shipments") and ran and ran[0][0] == "execute_sql"
    sent = [m["content"] for m in a.llm.seen[1] if m["role"] == "user"]
    assert sent[-1] == KEEP_ASK_NUDGE.format(words="shipments, late, september")
    b, _ = agent_with(monkeypatch, [say(ask)] * 3)
    assert b.ask("How many shipments were late on 22 September?")[0] == ask                # a first question: asked


def test_a_suspect_cause_confirmed_by_its_timing_alone_is_sent_back():
    """"Was it the deployment of that morning?" answered yes because the deployment came just before the failures
    (their errors said the payment provider timed out): a coincidence taken for a cause; a state question ("was that
    unusual?", "is the database overloaded?") is not a cause proposed, and a yes on the failures' own evidence stands."""
    from supagent.agent import SUSPECT_NUDGE, suspect_confirmed

    yes = ("Yes, it was the deployment that morning: CHG-1180 for checkout from 08:55 to 09:02. This deployment occurred "
           "just before the checkout failures.")
    assert suspect_confirmed("Was it the deployment of that morning?", yes)
    assert suspect_confirmed("And the disk alert on the payment server, was it related?",
                             "Yes, the disk alert was related: it fired at the same time.")
    assert suspect_confirmed("Est-ce que c'était le déploiement ?", "Oui, le déploiement a eu lieu juste avant les erreurs.")
    assert not suspect_confirmed("Was that unusual compared with the other days of that week?",
                                 "Yes, at the same time the other days had half as many.")
    assert not suspect_confirmed("Is the orders database overloaded?", "Yes, just before the peak it was.")
    assert not suspect_confirmed("Was it the deployment of that morning?",
                                 "No: the failures were the payment provider's timeouts, from 09:10, after it ended.")
    assert not suspect_confirmed("Was it related to the firmware change?",
                                 "Yes: the errors on xe-0/0/2 began at 06:50 and the switch logs name the port.")
    assert "a suspect, not a proof" in SUSPECT_NUDGE and "what they point at" in SUSPECT_NUDGE


def test_a_summary_asked_after_a_chat_is_not_a_new_investigation(monkeypatch):
    """"Give me a two-line summary for the incident ticket" after a chat that found the cause: "incident" made it an
    investigation (twenty calls re-investigating); the same words as a first question still investigate."""
    from supagent.agent import SUMMARY_ASKED, Agent

    a = Agent.__new__(Agent)
    monkeypatch.setattr(Agent, "_route_intents", lambda self: set())
    q = "Give me a two-line summary for the incident ticket."
    a.intent_text = "Did anything change on that switch recently?\n" + q
    assert SUMMARY_ASKED.search(q) and not a._investigating(q)
    a.intent_text = q                                            # a first question: as before
    assert a._investigating(q)
    a.intent_text = "What do the failing calls have in common?\nWhy did the switch port fail?"
    assert a._investigating("Why did the switch port fail?")      # a follow-up asking why: an investigation


def test_the_work_said_aloud_before_a_question_asked_back_is_not_for_the_user():
    """The model's reasoning about a check ("The tool is telling me I added a condition...") came to the user before
    the question it asked back: only the question is kept."""
    from supagent.agent import without_preamble

    text = ("The tool is telling me I added a condition (http_response_status_code >= 400) that wasn't asked for. The "
            "question asks \"how many of them failed\" but doesn't define what \"failed\" means.\n\n"
            "Looking at the available metrics again:\n- `checkout_orders_total` has a `status` label\n\n"
            "The question is ambiguous. I should ask for clarification.\n\nLet me ask the user to clarify:\n\n"
            "What do you mean by \"failed\" requests? HTTP requests with an error status, or failed orders?")
    out = without_preamble(text)
    assert out.startswith("What do you mean by") and "tool is telling me" not in out
    plain = "Which day do you mean: the 25th or the 26th?"
    assert without_preamble(plain) == plain
    told = "Let me ask: which day do you mean?\nThe 25th or the 26th?"     # no work aloud before: kept as written
    assert without_preamble(told) == told


def test_what_changed_is_answered_with_the_changes_found():
    """"What changed on sw-core-01 this week?" found the firmware change and answered with the port's errors."""
    import json

    from supagent.agent import CHANGES_NUDGE, changes_unsaid

    rows = [{"change_id": "CHG-1185", "description": "firmware 4.2.1 -> 4.2.3 on sw-core-01", "target": "sw-core-01"}]
    trace = [{"tool": "execute_sql", "status": "done", "args": {"request": {
        "sql": 'SELECT * FROM "itsm-changes" WHERE "target" = \'sw-core-01\''}}, "result": json.dumps({"rows": rows})}]
    errors = "Input errors on sw-core-01 spiked from 07:00, right after the upgrade window."
    said = changes_unsaid("What changed on sw-core-01 this week?", errors, trace)
    assert said == "CHG-1185 (firmware 4.2.1 -> 4.2.3 on sw-core-01)"
    assert changes_unsaid("What changed on sw-core-01 this week?", "CHG-1185 (firmware 4.2.3) on 27 Sep.", trace) is None
    assert changes_unsaid("How many errors on sw-core-01?", errors, trace) is None          # not a question of changes
    alerts = [{"tool": "execute_sql", "status": "done", "args": {"request": {"sql": 'SELECT * FROM "alerts"'}},
               "result": json.dumps({"rows": [{"id": "ALR-17", "summary": "x"}]})}]
    assert changes_unsaid("What changed on sw-core-01 this week?", errors, alerts) is None   # not a change table
    assert "{found}" in CHANGES_NUDGE


def test_a_follow_up_keeps_the_chats_period(world, monkeypatch):  # noqa: F811
    """"What do the failing calls have in common?" after "...this morning": its queries counted the failing spans of
    every day (two incidents mixed); one query with a time condition: the period is in hand."""
    from superset.extensions import db

    from supagent import settings
    from supagent.agent import PERIOD_KEPT_NUDGE, Agent, chat_period
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    settings.set_value("agent.now", "2026-09-27 11:00")
    try:
        earlier = ["Which application logged the most ERROR lines this morning?", "On which pods and nodes?"]
        assert chat_period("What do the failing calls have in common?", earlier) == earlier[0]
        assert chat_period("And yesterday?", earlier) is None               # a period of its own
        assert chat_period("Which application logged the most errors?", []) is None
        run, src = db.session.query(Run).first(), world["s_jobs"]
        upsert(run, src, "index", "", "spans", {"stats": {"time_field": "startTimeMillis"}})
        db.session.commit()
        a = Agent.__new__(Agent)
        a.chat_period = earlier[0]
        every = [{"tool": "execute_sql", "status": "done", "args": {"request": {
            "sql": 'SELECT COUNT(*) FROM "spans" WHERE "tag.error" = \'true\''}}}]
        assert a._period_lost(every) == ["spans"]
        kept = every + [{"tool": "execute_sql", "status": "done", "args": {"request": {
            "sql": 'SELECT COUNT(*) FROM "spans" WHERE "startTimeMillis" >= TIMESTAMP \'2026-09-27 00:00\''}}}]
        assert a._period_lost(kept) is None
        a.chat_period = None
        assert a._period_lost(every) is None
        assert "{asked}" in PERIOD_KEPT_NUDGE and "{tables}" in PERIOD_KEPT_NUDGE
    finally:
        settings.set_value("agent.now", None)


def test_the_chats_period_is_not_asked_when_the_chat_read_every_day_itself(world):  # noqa: F811
    from superset.extensions import db

    from supagent.agent import Agent
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    run, src = db.session.query(Run).first(), world["s_jobs"]
    upsert(run, src, "index", "", "spans", {"stats": {"time_field": "startTimeMillis"}})
    db.session.commit()
    a = Agent.__new__(Agent)
    a.chat_period = "How many failed calls this morning?"
    a.prev_queries = ['SELECT COUNT(*) FROM "spans" WHERE "tag.error" = \'true\'']
    every = [{"tool": "execute_sql", "status": "done", "args": {"request": {
        "sql": 'SELECT "operationName", COUNT(*) FROM "spans" WHERE "tag.error" = \'true\' GROUP BY 1'}}}]
    assert a._period_lost(every) is None


def test_a_question_back_before_looking_at_a_part_the_map_knows(monkeypatch):
    """"How many errors did the payment service log yesterday?" asked back between checkout and payment-legacy
    with no look at the map, which knew payment as one service also called payment-legacy."""
    from supagent.agent import MAP_ASK_NUDGE, Agent
    from supagent.knowledge import brief

    g = {"values": {1: {"id": 1, "cat": "application", "name": "payment"}, 2: {"id": 2, "cat": "subject", "name": "jobs"}},
         "names": {"payment": [1], "payment-legacy": [1], "jobs": [2]}}
    monkeypatch.setattr(brief, "_graph", lambda: g)
    a = Agent.__new__(Agent)
    assert a._map_named("How many errors did the payment service log yesterday?") == \
        ("payment", "application; also called payment-legacy")
    assert a._map_named("How many errors did payment-legacy log?") == ("payment-legacy", "application; also called payment")
    assert a._map_named("What was the average duration of the jobs?") is None        # a topic, not a part
    assert a._map_named("How many repayments?") is None                                 # inside a word: not named
    assert "{name}" in MAP_ASK_NUDGE and "{what}" in MAP_ASK_NUDGE


def test_the_one_said_and_all_of_them_counted(world):  # noqa: F811
    """"How many tickets did the team open last Friday?": the tickets have three teams, the query counted them all
    (4, the two teams that opened some on Friday together)."""
    from superset.extensions import db

    from supagent.agent import WHICH_NUDGE, Agent
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    run, src = db.session.query(Run).first(), world["s_jobs"]
    upsert(run, src, "index", "", "tickets", {"stats": {"time_field": "OPENED_TIME"}})
    upsert(run, src, "field", "tickets", "TEAM", {"data_type": "keyword", "stats": {
        "values": ["GENERAL_CARE", "LOGISTICS_CARE", "PAYMENTS_CARE"]}})
    db.session.commit()
    a = Agent.__new__(Agent)
    q = "How many tickets did the team open last Friday?"
    total = [{"tool": "execute_sql", "status": "done", "args": {"request": {
        "sql": 'SELECT COUNT(*) FROM "tickets" WHERE "OPENED_TIME" >= \'2026-09-18\''}}}]
    assert a._which_one(q, total) == ("team", "TEAM", ["GENERAL_CARE", "LOGISTICS_CARE", "PAYMENTS_CARE"])
    grouped = [{"tool": "execute_sql", "status": "done", "args": {"request": {
        "sql": 'SELECT "TEAM", COUNT(*) FROM "tickets" GROUP BY 1'}}}]
    assert a._which_one(q, grouped) is None                                 # per team already
    assert a._which_one("How many tickets did the PAYMENTS_CARE team open?", total) is None    # named
    assert a._which_one("How many tickets did the teams open?", total) is None                # all of them
    assert "{noun}" in WHICH_NUDGE and "{values}" in WHICH_NUDGE


def test_a_follow_up_reading_days_outside_the_chats_period_is_sent_back_once(monkeypatch):
    """(0.9.7) After "...this morning", a follow-up whose queries read from three days before (another day's events
    taken for this morning's): sent back once to keep the chat's period. Not when a query reads the period, when the
    question asks for a comparison or what is usual, nor with the setting off."""
    import datetime as dt

    from supagent import agent as A, settings
    from supagent.knowledge.period import period_window, window_reading

    today = dt.date(2030, 1, 17)
    window = period_window("How many requests failed this morning?", today)
    assert window == (dt.datetime(2030, 1, 17), dt.datetime(2030, 1, 18))
    assert period_window("And on 14 January?", today) == (dt.datetime(2030, 1, 14), dt.datetime(2030, 1, 15))
    assert period_window("over the last hours", today) is None
    wide = 'SELECT COUNT(*) FROM "calls" WHERE "ts" >= \'2030-01-14 00:00\' AND "failed" = true'
    near = 'SELECT COUNT(*) FROM "calls" WHERE "ts" >= \'2030-01-17 00:00\' AND "ts" < \'2030-01-17 11:00\''
    eve = 'SELECT COUNT(*) FROM "calls" WHERE "ts" >= \'2030-01-16 20:00\''           # the evening before: in
    other = 'SELECT COUNT(*) FROM "calls" WHERE "ts" >= \'2030-01-16 09:00\' AND "ts" < \'2030-01-16 11:00\''
    assert (window_reading(wide, window), window_reading(near, window), window_reading(eve, window)) == \
        ("wider", "in", "in")
    assert window_reading(other, window) is None                       # the day before, close by: not judged
    real = settings.get
    conf = {"agent.period_window_check": True}
    monkeypatch.setattr(settings, "get", lambda k: conf[k] if k in conf else real(k))
    monkeypatch.setattr(A, "now", lambda: dt.datetime(2030, 1, 17, 11, 0))
    a = A.Agent.__new__(A.Agent)
    a.chat_period = "How many requests failed this morning?"
    done = lambda sql: {"tool": "execute_sql", "status": "done", "args": {"request": {"sql": sql}}}
    assert a._period_widened("What do those requests share?", [done(wide)]) == "2030-01-14 00:00"
    assert a._period_widened("What do those requests share?", [done(wide), done(near)]) is None   # in hand
    assert a._period_widened("What do those requests share?", [done(wide), done(other)]) == "2030-01-14 00:00"
    assert a._period_widened("Is that more than usual?", [done(wide)]) is None                    # a comparison
    conf["agent.period_window_check"] = False
    assert a._period_widened("What do those requests share?", [done(wide)]) is None
    assert "{first}" in A.PERIOD_WIDENED_NUDGE and "{asked}" in A.PERIOD_WIDENED_NUDGE


def test_a_follow_up_that_reads_wider_on_purpose_is_left_alone(monkeypatch):
    """Its own recent past, a state, a summary: reading the days before the chat's period is what it asks."""
    import datetime as dt

    from supagent import agent as A, settings

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: True if k == "agent.period_window_check" else real(k))
    monkeypatch.setattr(A, "now", lambda: dt.datetime(2030, 1, 17, 11, 0))
    a = A.Agent.__new__(A.Agent)
    a.chat_period = "How many requests failed this morning?"
    wide = [{"tool": "execute_sql", "status": "done", "args": {"request": {
        "sql": 'SELECT COUNT(*) FROM "changes" WHERE "ts" >= \'2030-01-10 00:00\''}}}]
    for q in ("Did anything change on that router recently?", "Is the queue overloaded?",
              "Give me a two-line summary for the ticket."):
        assert a._period_widened(q, wide) is None, q
    assert a._period_widened("Which hosts did those requests run on?", wide) == "2030-01-10 00:00"
