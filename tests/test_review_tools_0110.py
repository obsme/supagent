"""The 0.11.0 review of the question path's tools: each test fails without its fix."""

from __future__ import annotations

import pytest


def test_select_into_is_refused():
    """SELECT ... INTO is written again as CREATE TABLE ... AS SELECT: never run as a SELECT."""
    from supagent.tools import ToolError, _check_select

    for sql in ("SELECT * INTO copied FROM t", "SELECT a, b INTO TEMP copied FROM t WHERE a > 1"):
        with pytest.raises(ToolError):
            _check_select(sql, 10)
    assert _check_select("SELECT a FROM t", 10)[0].startswith("SELECT")


@pytest.fixture()
def roles(app):
    """An AI Editor (edits the knowledge, deletes none) and an AI Viewer (writes for themselves only); their notes
    removed after the test."""
    from superset.extensions import db, security_manager as sm

    from supagent.cli import EDITOR_ROLE, VIEWER_ROLE, ensure_roles

    with app.app_context():
        ensure_roles()
        for name, role in (("rv_editor", EDITOR_ROLE), ("rv_viewer", VIEWER_ROLE)):
            if sm.find_user(username=name) is None:
                sm.add_user(name, name, "Test", f"{name}@example.com", [sm.find_role("Gamma"), sm.find_role(role)],
                            password="test-password-1")
        db.session.commit()
        db.session.remove()
    yield
    with app.app_context():
        from supagent.models import Chunk, Note

        db.session.query(Note).delete()
        db.session.query(Chunk).filter(Chunk.ref.like("note:%")).delete(synchronize_session=False)
        db.session.commit()
        db.session.remove()


def test_another_persons_note_is_deleted_by_the_agent_only_with_the_right_to_delete(app, roles):
    """As on the notes page: an AI Editor changes a team note, deletes only their own; an admin deletes it."""
    from supagent import tools as T
    from supagent.security import acting_as

    with app.app_context():
        with acting_as("alice"):
            n = T.add_note("Release freeze on Friday 17:00")["saved"]
        with acting_as("rv_editor"):
            assert "error" in T.delete_note(n["id"], confirmed=True)
            assert T.read_note(n["id"])["note"]["id"] == n["id"]
        with acting_as("admin"):
            assert T.delete_note(n["id"], confirmed=True)["deleted"]["id"] == n["id"]


def test_a_viewer_shares_no_note_through_the_agent(app, roles):
    """An AI Viewer writes notes for themselves only: the agent does not make one the team's either."""
    from supagent import tools as T
    from supagent.security import acting_as

    with app.app_context():
        with acting_as("rv_viewer"):
            mine = T.add_note("My own reminder: rotate the keys", personal=True)["saved"]
            assert "error" in T.change_note(mine["id"], personal=False)
            assert T.read_note(mine["id"])["note"]["for"] == "its author only"
        with acting_as("alice"):
            assert "error" in T.read_note(mine["id"])


def test_a_catalog_entry_of_the_wrong_shape_is_refused_and_never_breaks_the_catalog(ctx):
    """A metrics entry whose tables are a list, or an index entry whose index is a sentence, is refused when saved;
    one saved before is left out of the catalog (an error said) instead of breaking it for every user."""
    from superset.extensions import db

    from supagent.knowledge.catalog import CatalogError, conflicts, load_catalog, parse_entry
    from supagent.knowledge.curated import catalog_texts
    from supagent.knowledge.freshness import touch
    from supagent.models import Entry

    for kind, text in (("metrics", "tables: [up, node_load1]"), ("index", "jobs: the jobs index"),
                       ("metrics", "tables:\n  up: whether the target answers"),
                       ("index", "jobs:\n  fields: [STATUS, APPLICATION]")):
        with pytest.raises(CatalogError):
            parse_entry(kind, "yaml", text)
    assert parse_entry("metrics", "yaml", "up:\n  description: whether the target answers") == \
        {"tables": {"up": {"description": "whether the target answers"}}}
    bad = Entry(title="a list of metrics", classification="metrics", fmt="yaml", content="tables: [up, node_load1]",
                enabled=True)
    good = Entry(title="the jobs index", classification="index", fmt="yaml",
                 content="jobs:\n  description: the batch jobs", enabled=True)
    db.session.add_all([bad, good])
    touch()
    db.session.commit()
    try:
        assert "jobs" in load_catalog()["indices"]
        assert ("index", "", "jobs") in catalog_texts()
        assert "a list of metrics" in [e["entry"] for e in conflicts()["errors"]]
    finally:
        db.session.query(Entry).filter(Entry.id.in_([bad.id, good.id])).delete(synchronize_session=False)
        touch()
        db.session.commit()


def test_a_day_at_the_end_of_the_calendar_breaks_no_chat():
    """A day whose next or previous day is past the calendar (9999-12-31 and the day after) is no day named: the
    chat's later questions read it again and must not fail on it."""
    import datetime as dt

    from supagent.knowledge import period as P

    today = dt.date(2026, 10, 17)
    assert P.days_named("Jobs on 9999-12-31 and the day after?", today) == [dt.date(9999, 12, 31)]
    assert P.has_period("What about 0001-01-01 and the day before?", today)
    assert P.day_ranges("from 30 to 31 December 9999", today) == []
    assert P.period_window("Jobs on 9999-12-31?", today) is None
    P.follow_up_text("And the day after?", ["jobs on 9999-12-31?"], today)
    assert P.period_window("Jobs on 2026-10-15?", today) == (dt.datetime(2026, 10, 15), dt.datetime(2026, 10, 16))


def test_a_report_is_sent_only_to_the_allowed_domains(ctx):
    """tools.email_allowed_domains holds for a scheduled report as for an e-mail sent now."""
    import json

    from superset.connectors.sqla.models import SqlaTable
    from superset.extensions import db
    from superset.models.core import Database
    from superset.models.slice import Slice
    from superset.reports.models import ReportSchedule

    from supagent import settings
    from supagent.security import acting_as
    from supagent.tools import ReportRequest, create_report

    base = Database(database_name="review-report-db", sqlalchemy_uri="sqlite://")
    db.session.add(base)
    db.session.flush()
    table = SqlaTable(table_name="review_sales", database=base)
    db.session.add(table)
    db.session.flush()
    chart = Slice(slice_name="Review sales chart", datasource_type="table", datasource_id=table.id, viz_type="table",
                  params=json.dumps({"viz_type": "table"}))
    db.session.add(chart)
    db.session.commit()
    ids = (base.id, table.id, chart.id)
    settings.set_value("tools.email_allowed_domains", ["example.com"])
    try:
        with acting_as("admin"):
            refused = create_report(ReportRequest(name="review weekly", chart_id=ids[2],
                                                  email_recipients=["boss@elsewhere.test"]))
        assert "only these domains are allowed" in refused.get("error", "")
        assert db.session.query(ReportSchedule).filter(ReportSchedule.name == "review weekly").count() == 0
    finally:
        settings.set_value("tools.email_allowed_domains", None)
        db.session.rollback()
        for report in db.session.query(ReportSchedule).filter(ReportSchedule.name == "review weekly"):
            db.session.delete(report)
        db.session.query(Slice).filter(Slice.id == ids[2]).delete(synchronize_session=False)
        db.session.query(SqlaTable).filter(SqlaTable.id == ids[1]).delete(synchronize_session=False)
        db.session.query(Database).filter(Database.id == ids[0]).delete(synchronize_session=False)
        db.session.commit()


def test_a_dataset_with_row_level_security_for_the_user_is_not_read_around_it(ctx, tmp_path):
    """The agent's SQL runs on the database's own connection, which applies no row-level security: a query that
    reads a dataset with RLS filters for this user is refused (its chart applies them); another runs as before."""
    import sqlite3

    from superset.connectors.sqla.models import RowLevelSecurityFilter, SqlaTable, TableColumn
    from superset.extensions import db, security_manager as sm
    from superset.models.core import Database

    from supagent import settings
    from supagent.security import acting_as
    from supagent.tools_superset import ExecuteSqlRequest, execute_sql

    path = str(tmp_path / "teams.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE teams_rls (team TEXT, amount INTEGER)")
    con.execute("CREATE TABLE plain (team TEXT)")
    con.executemany("INSERT INTO teams_rls VALUES (?, ?)", [("a", 1), ("b", 2), ("b", 3)])
    con.execute("INSERT INTO plain VALUES ('b')")
    con.commit()
    con.close()
    base = Database(database_name="review-rls-db", sqlalchemy_uri=f"sqlite:///{path}")
    db.session.add(base)
    db.session.flush()
    tables = [SqlaTable(table_name=name, schema="main", database=base,
                        columns=[TableColumn(column_name="team", type="TEXT")]) for name in ("teams_rls", "plain")]
    db.session.add_all(tables)
    db.session.flush()
    role = sm.find_role("review_rls_role") or sm.add_role("review_rls_role")
    for t in tables:
        sm.add_permission_role(role, sm.add_permission_view_menu("datasource_access", t.get_perm()))
    if sm.find_user(username="rv_rls") is None:
        sm.add_user("rv_rls", "rv", "rls", "rv_rls@example.com", [sm.find_role("Gamma"), role],
                    password="test-password-1")
    rule = RowLevelSecurityFilter(name="review only team a", filter_type="Regular", clause="team = 'a'",
                                  tables=[tables[0]], roles=[role])
    db.session.add(rule)
    db.session.commit()
    ids = (rule.id, [t.id for t in tables], base.id)
    settings.set_value("agent.databases", ["review-rls-db"])
    try:
        with acting_as("rv_rls"):
            refused = execute_sql(ExecuteSqlRequest(database_id=ids[2], sql="SELECT team, amount FROM teams_rls"))
            plain = execute_sql(ExecuteSqlRequest(database_id=ids[2], sql="SELECT team FROM plain"))
        assert refused["success"] is False and "row-level security" in refused["error"], refused
        assert plain["success"] is True and plain["rows"] == [{"team": "b"}], plain
    finally:
        settings.set_value("agent.databases", None)
        db.session.rollback()
        db.session.delete(db.session.get(RowLevelSecurityFilter, ids[0]))
        for tid in ids[1]:
            db.session.delete(db.session.get(SqlaTable, tid))
        db.session.delete(db.session.get(Database, ids[2]))
        db.session.commit()


def test_a_chat_with_a_day_at_the_end_of_the_calendar_reads_its_next_question(ctx):
    """What the agent reads of a chat's earlier questions for the next one (its period, whether it adds to the one
    before) does not fail on such a day."""
    from supagent.agent import adds_to, chat_period

    earlier = ["Jobs on 9999-12-31 and the day after?"]
    chat_period("How many failed?", earlier)
    adds_to("And the day after?", earlier[0], earlier)
