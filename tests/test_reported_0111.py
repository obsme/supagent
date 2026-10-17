"""The defects the 0.11.0 review reported only: each test fails without its fix."""

from __future__ import annotations

import pytest

from test_grafana_rules_01010 import _draft, grafana  # noqa: F401  (the fixture)

from supagent import grafana as G


@pytest.fixture()
def rls_base(ctx, tmp_path):
    """A SQLite database with a dataset under a row-level security filter for the user rp_rls (team a only) and one
    without; all removed after the test."""
    import sqlite3

    from superset.connectors.sqla.models import RowLevelSecurityFilter, SqlaTable, TableColumn
    from superset.extensions import db, security_manager as sm
    from superset.models.core import Database

    path = str(tmp_path / "squads.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE squads_rls (team TEXT, amount INTEGER)")
    con.execute("CREATE TABLE open_rows (team TEXT)")
    con.executemany("INSERT INTO squads_rls VALUES (?, ?)", [("a", 1), ("b", 2), ("b", 3)])
    con.executemany("INSERT INTO open_rows VALUES (?)", [("b",), ("b",)])
    con.commit()
    con.close()
    base = Database(database_name="reported-rls-db", sqlalchemy_uri=f"sqlite:///{path}")
    db.session.add(base)
    db.session.flush()
    tables = [SqlaTable(table_name=name, schema="main", database=base,
                        columns=[TableColumn(column_name="team", type="TEXT")]) for name in ("squads_rls", "open_rows")]
    db.session.add_all(tables)
    db.session.flush()
    role = sm.find_role("reported_rls_role") or sm.add_role("reported_rls_role")
    for t in tables:
        sm.add_permission_role(role, sm.add_permission_view_menu("datasource_access", t.get_perm()))
    sm.add_permission_role(role, sm.add_permission_view_menu("database_access", base.perm))
    if sm.find_user(username="rp_rls") is None:
        sm.add_user("rp_rls", "rp", "rls", "rp_rls@example.com", [sm.find_role("Gamma"), role],
                    password="test-password-1")
    rule = RowLevelSecurityFilter(name="reported only team a", filter_type="Regular", clause="team = 'a'",
                                  tables=[tables[0]], roles=[role])
    db.session.add(rule)
    db.session.commit()
    ids = (rule.id, [t.id for t in tables], base.id)
    yield base
    db.session.rollback()
    db.session.delete(db.session.get(RowLevelSecurityFilter, ids[0]))
    for tid in ids[1]:
        db.session.delete(db.session.get(SqlaTable, tid))
    db.session.delete(db.session.get(Database, ids[2]))
    db.session.commit()


def test_the_tools_that_write_their_own_sql_do_not_read_around_row_level_security(rls_base):
    """compare_groups, what_they_share, records_about, repeated_keys... run their SQL on the database's own
    connection: a query of a dataset with RLS filters for the user is refused there too (in their threads as well),
    another runs as before."""
    import threading

    from superset.extensions import db
    from superset.models.core import Database

    from supagent import tools as T
    from supagent.security import acting_as

    base_id = rls_base.id
    with acting_as("rp_rls"):
        base = db.session.get(Database, base_id)
        assert T.repeated_keys(base, "squads_rls", "team") is None      # not read: not known
        assert T.repeated_keys(base, "open_rows", "team") == 1
        with T._rls_connection(base) as conn:
            with pytest.raises(T.ToolError, match="row-level security"):
                conn.cursor().execute('SELECT "team", COUNT(*) FROM "squads_rls" GROUP BY 1')
            cur = conn.cursor()
            cur.execute('SELECT COUNT(*) FROM "open_rows"')
            assert cur.fetchall() == [(2,)]
            said: list[str] = []
            shared = conn.cursor()
            db.session.commit()             # (as compare_groups does before its threads: the datasets expire)

            def other_thread() -> None:     # (compare_groups' threads: no app context there)
                try:
                    shared.execute('SELECT * FROM squads_rls')
                except T.ToolError as ex:
                    said.append(str(ex))

            th = threading.Thread(target=other_thread)
            th.start()
            th.join()
            assert said and "row-level security" in said[0]
    T._REPEATS.clear()
    with acting_as("admin"):
        assert T.repeated_keys(db.session.get(Database, base_id), "squads_rls", "team") == 1
    with acting_as("rp_rls"):                                               # nor what was kept for another user
        assert T.repeated_keys(db.session.get(Database, base_id), "squads_rls", "team") is None


def test_chart_anomalies_tells_nothing_of_a_dashboard_or_chart_the_user_may_not_see(ctx):
    """A dashboard or chart the user may not see is not there for chart_anomalies: its title is not given in "where",
    and the answer is the same as for a title nobody gave (no telling whether it exists)."""
    import json

    from superset.connectors.sqla.models import SqlaTable
    from superset.extensions import db
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice

    from supagent.security import acting_as
    from supagent.tools import chart_anomalies

    base = Database(database_name="reported-hidden-db", sqlalchemy_uri="sqlite://")
    db.session.add(base)
    db.session.flush()
    table = SqlaTable(table_name="reported_payroll", database=base)
    db.session.add(table)
    db.session.flush()
    chart = Slice(slice_name="Zircon payroll chart", datasource_type="table", datasource_id=table.id,
                  viz_type="table", params=json.dumps({"viz_type": "table"}))
    board = Dashboard(dashboard_title="Zircon payroll board", published=True, slices=[chart])
    db.session.add_all([chart, board])
    db.session.commit()
    ids = (base.id, table.id, chart.id, board.id)
    try:
        def said(**kw):
            with acting_as("alice"):
                return chart_anomalies(**kw)

        for key in ("Zircon payroll board", "zircon payroll", str(ids[3])):
            out = said(dashboard=key)
            assert "Zircon" not in json.dumps(out.get("where", "")), out
            assert out == said(dashboard="Quartz absent board") | {
                "error": said(dashboard="Quartz absent board")["error"].replace("Quartz absent board", key)}, out
        for key in ("Zircon payroll chart", str(ids[2])):
            out = said(chart=key)
            assert "Zircon" not in json.dumps(out.get("where", "")), out
            assert out == {"error": said(chart="Quartz absent chart")["error"].replace("Quartz absent chart", key)}
        with acting_as("admin"):
            assert "Zircon payroll board" in chart_anomalies(dashboard="Zircon payroll board")["where"]
    finally:
        db.session.rollback()
        db.session.query(Dashboard).filter(Dashboard.id == ids[3]).delete(synchronize_session=False)
        db.session.query(Slice).filter(Slice.id == ids[2]).delete(synchronize_session=False)
        db.session.query(SqlaTable).filter(SqlaTable.id == ids[1]).delete(synchronize_session=False)
        db.session.query(Database).filter(Database.id == ids[0]).delete(synchronize_session=False)
        db.session.commit()


def test_a_bound_at_24_00_or_on_no_such_day_breaks_no_check_of_the_call(monkeypatch):
    """'2026-09-23 24:00:00' (the next day's 00:00) and '2026-09-31 05:00' (no such day) raised ValueError in the
    agent's checks before a query runs, and every check of that call was skipped: they are read as no bound."""
    import datetime as dt

    from supagent.knowledge import period as P

    assert P._literals("SELECT 1 FROM t WHERE ts >= '2026-09-23 10:00' AND ts < '2026-09-23 24:00:00'") == \
        [dt.datetime(2026, 9, 23, 10), dt.datetime(2026, 9, 24)]
    assert P._literals("WHERE ts >= '2026-09-31 05:00' AND ts < '2026-09-23 10:75' OR ts < '9999-12-31 24:00'") == []
    assert P.window_reading("SELECT 1 FROM t WHERE ts >= '2026-09-23 00:00' AND ts < '2026-09-23 24:00:00'",
                            (dt.datetime(2026, 9, 23), dt.datetime(2026, 9, 24))) == "in"
    monkeypatch.setattr(P, "_day_fields", lambda tables: {"BOOK_DAY"})
    monkeypatch.setattr(P, "osagg_reads_days", lambda: True)
    for sql in ("SELECT COUNT(*) FROM ledger WHERE \"BOOK_DAY\" >= '2026-09-31 05:00'",
                "SELECT COUNT(*) FROM ledger WHERE \"BOOK_DAY\" < '2026-09-23 24:00'",
                "SELECT COUNT(*) FROM ledger WHERE \"BOOK_DAY\" BETWEEN '2026-09-22 00:00' AND '2026-02-30 05:00'"):
        assert P.day_time_bound(sql, {"ledger"}) is None, sql
    assert "holds days" in P.day_time_bound("SELECT COUNT(*) FROM ledger WHERE \"BOOK_DAY\" >= '2026-09-23 05:00'",
                                            {"ledger"})


def test_a_whole_catalog_of_the_wrong_shape_is_refused_not_a_server_error(ctx):
    """POST /api/catalog with indices: [a] (a list where a mapping is expected) raised AttributeError, a 500:
    refused with a CatalogError (a 400) as an entry of the wrong shape is, nothing saved."""
    from superset.extensions import db

    from supagent.knowledge.catalog import CatalogError, import_catalog
    from supagent.models import Entry

    before = db.session.query(Entry).count()
    for text in ("indices: [orders_ix]", "metrics: [up]", "metrics:\n  tables: [up, node_load1]",
                 "indices: some sentence"):
        with pytest.raises(CatalogError):
            import_catalog(text, by="tester")
    assert db.session.query(Entry).count() == before


def test_a_limit_that_is_no_whole_number_is_a_tool_error():
    """LIMIT 1.5 raised ValueError (an internal error to the model) instead of a ToolError it can act on."""
    from supagent.tools import ToolError, _check_select

    for sql in ("SELECT a FROM t LIMIT 1.5", "SELECT a FROM t LIMIT 1e3"):
        with pytest.raises(ToolError, match="whole number"):
            _check_select(sql, 10)
    assert _check_select("SELECT a FROM t LIMIT 5", 10)[1] == 5


def test_an_export_file_is_attached_only_by_the_user_who_made_it(ctx, tmp_path, monkeypatch):
    """The export folder is shared: another user could attach (send_email) a user's file by its 6-character id or
    its name. A file is now its maker's: for anyone else it is not there, said as for a file that does not exist."""
    import os
    import sqlite3

    from superset.extensions import db
    from superset.models.core import Database

    from supagent import settings
    from supagent import tools as T
    from supagent.security import acting_as

    monkeypatch.setattr(T, "_export_dir", lambda: str(tmp_path / "exports"))
    path = str(tmp_path / "parts.db")
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE parts (code TEXT)")
    con.execute("INSERT INTO parts VALUES ('p-1')")
    con.commit()
    con.close()
    base = Database(database_name="reported-export-db", sqlalchemy_uri=f"sqlite:///{path}")
    db.session.add(base)
    db.session.commit()
    base_id = base.id
    settings.set_value("agent.databases", ["reported-export-db"])
    try:
        with acting_as("admin"):
            made = T.export_excel("SELECT code FROM parts", database=base_id, file_name="parts list")
            assert made.get("id"), made
            assert T._export_file(made["id"], (".xlsx",)) == made["path"]
        for key in (made["id"], os.path.basename(made["path"]), made["path"]):
            with acting_as("alice"):
                with pytest.raises(T.ToolError) as theirs:
                    T._export_file(key, (".xlsx",))
                with pytest.raises(T.ToolError) as nobody:
                    T._export_file(key.replace(made["id"], "abcdef"), (".xlsx",))
            assert str(theirs.value) == str(nobody.value).replace("abcdef", made["id"])
    finally:
        settings.set_value("agent.databases", None)
        db.session.rollback()
        db.session.delete(db.session.get(Database, base_id))
        db.session.commit()


def test_the_schema_version_is_never_lowered(ctx):
    """An older supagent started on a newer one's database (a rollback) wrote its own lower version: the newer one,
    upgraded again, re-ran the migrations of the versions in between. The stored version now never goes down."""
    from superset.extensions import db

    from supagent.models import SCHEMA_VERSION, Meta, create_or_upgrade

    row = db.session.get(Meta, "schema_version")
    row.value = str(SCHEMA_VERSION + 5)
    db.session.commit()
    try:
        assert create_or_upgrade() == (SCHEMA_VERSION + 5, SCHEMA_VERSION + 5)
        assert db.session.get(Meta, "schema_version").value == str(SCHEMA_VERSION + 5)
    finally:
        db.session.rollback()
        db.session.get(Meta, "schema_version").value = str(SCHEMA_VERSION)
        db.session.commit()
    assert create_or_upgrade() == (SCHEMA_VERSION, SCHEMA_VERSION)


def test_a_token_in_an_extra_header_is_masked_where_secrets_are(ctx, capsys):
    """llm.extra_headers is no secret, yet a token put in a header was printed by `superset supagent settings`, shown
    by describe() and kept in backups: its values are masked there, written back masked they keep the value stored,
    and the LLM calls still send it."""
    import json

    from supagent import settings
    from supagent.cli import _print_settings
    from supagent.knowledge.backup import _settings_rows

    token = "Bearer tok-7f3a9c2e51"
    settings.set_value("llm.extra_headers", {"Authorization": token, "X-Tenant": "blue"})
    try:
        shown = {r["key"]: r for r in settings.describe()}["llm.extra_headers"]["value"]
        assert "tok-7f3a9c2e51" not in json.dumps(shown) and set(shown) == {"Authorization", "X-Tenant"}
        _print_settings()
        printed = capsys.readouterr().out
        assert "llm.extra_headers" in printed and "tok-7f3a9c2e51" not in printed
        assert "tok-7f3a9c2e51" not in json.dumps(_settings_rows())
        settings.set_value("llm.extra_headers", shown)                 # the settings page saved as shown
        assert settings.get("llm.extra_headers") == {"Authorization": token, "X-Tenant": "blue"}
        settings.set_value("llm.extra_headers", {"Authorization": settings.MASKED, "X-Tenant": "green",
                                                 "X-Unknown": settings.MASKED})
        assert settings.get("llm.extra_headers") == {"Authorization": token, "X-Tenant": "green"}
    finally:
        settings.set_value("llm.extra_headers", None)


def test_the_llm_test_shows_nothing_of_the_middleware_token(monkeypatch):
    """`superset supagent test-llm` and the admin page's test button printed the token's first 6 characters."""
    import json

    from supagent import llm as L

    token = "Zq8Xw3mKp9Lr2Tv"
    monkeypatch.setattr(L, "middleware_token", lambda cfg: token)
    monkeypatch.setattr(L.LLM, "chat", lambda self, messages, **kw: {"content": "OK"})
    monkeypatch.setattr(L.LLM, "probe", lambda self: {})
    monkeypatch.setattr(L, "adapt", lambda base, model: None)
    out = L.LLM(L.LLMConfig(base_url="http://llm.invalid/v1", model="m1", auth="middleware")).check()
    said = json.dumps(out)
    assert out["answer"] == "OK" and "token" in out
    assert not any(token[:n] in said for n in range(3, len(token) + 1)), out


def test_a_group_memory_is_indexed_for_its_group_as_a_group_note_is(ctx):
    """A group's memory was indexed with the scope "group", which no user's search scopes hold ("g<id>"): the
    search store never showed it to the group's members. It is now indexed as a group's note is."""
    from superset.extensions import db

    from supagent.knowledge.index import _memory_pieces
    from supagent.knowledge.notes import pieces as note_pieces
    from supagent.models import Memory, Note

    mem = Memory(scope="group", group_id=4242, user_id=1, kind="rule", text="Rollouts of the billing team wait for "
                 "the change board", status="active")
    note = Note(scope="group", group_id=4242, user_id=1, text="The change board meets on Tuesdays")
    db.session.add_all([mem, note])
    db.session.commit()
    try:
        m_piece = next(p for p in _memory_pieces() if p["ref"] == f"memory:{mem.id}")
        n_piece = next(p for p in note_pieces() if p["ref"].startswith(f"note:{note.id}#"))
        assert m_piece["scope"] == n_piece["scope"] == "g4242"
        assert m_piece["user_id"] is None and "group" in m_piece["title"]
    finally:
        db.session.delete(mem)
        db.session.delete(note)
        db.session.commit()


def test_a_full_sync_reads_one_documents_text_at_a_time(ctx):
    """_doc_pieces read every document with its whole text (a wiki's pages joined) in one query, all held in memory
    at once on a full sync: the texts are now read one document at a time, the pieces the same."""
    import re

    from sqlalchemy import event
    from superset.extensions import db

    from supagent.knowledge.index import _doc_pieces
    from supagent.models import Doc

    docs = [Doc(kind="upload", title=f"Runbook {c}", content=f"# Runbook {c}\n\nRestart the {c} queue first.",
                enabled=True) for c in ("amber", "cobalt", "violet")]
    db.session.add_all(docs)
    db.session.commit()
    ids = {d.id for d in docs}
    seen: list[str] = []

    def heard(_conn, _cursor, statement, *_args):
        if re.search(r"supagent_doc\.content\b", statement) and re.search(r"\bSELECT\b", statement, re.I):
            seen.append(statement)

    engine = db.session.get_bind()
    event.listen(engine, "before_cursor_execute", heard)
    try:
        db.session.expire_all()
        pieces = [p for p in _doc_pieces(ids)]
    finally:
        event.remove(engine, "before_cursor_execute", heard)
        for d in db.session.query(Doc).filter(Doc.id.in_(ids)):
            db.session.delete(d)
        db.session.commit()
    assert sorted(p["title"] for p in pieces) == ["Runbook amber", "Runbook cobalt", "Runbook violet"], pieces
    texts = [s for s in seen if re.search(r"\bSELECT\b[\s\S]*supagent_doc\.content[\s\S]*\bFROM\b", s, re.I)
             and not re.search(r"supagent_doc\.content IS NOT NULL", s.split("FROM", 1)[0], re.I)]
    assert texts and all(re.search(r"WHERE supagent_doc\.id = ", s) for s in texts), seen


def test_grafana_panels_under_an_open_row_are_that_rows():
    """(a) Grafana puts the panels of an open (not collapsed) row after it, at the top level: they are that row's."""
    from supagent.grafana import _panels

    got = _panels([{"id": 1, "type": "stat", "title": "Before any row"},
                   {"id": 2, "type": "row", "title": "Queues", "collapsed": False, "panels": []},
                   {"id": 3, "type": "timeseries", "title": "Queue depth"},
                   {"id": 4, "type": "row", "title": "Workers", "collapsed": True,
                    "panels": [{"id": 5, "type": "timeseries", "title": "Busy workers"}]},
                   {"id": 6, "type": "row", "title": "Disks", "collapsed": False},
                   {"id": 7, "type": "gauge", "title": "Disk use"}])
    assert [(p["title"], p.get("row")) for p in got] == [("Before any row", None), ("Queue depth", "Queues"),
                                                         ("Busy workers", "Workers"), ("Disk use", "Disks")]


def test_grafana_interval_variables_are_replaced_whole():
    """(b) $__interval_ms became 1m_ms: a variable is replaced only as a whole name."""
    from supagent.grafana import _evaluable

    assert _evaluable("rate(zqx_hits_total[$__rate_interval])") == "rate(zqx_hits_total[5m])"
    assert _evaluable("rate(zqx_hits_total[$__interval]) * $__interval_ms") is None     # $__interval_ms: no default
    assert _evaluable("increase(zqx_hits_total[${__range}])") == "increase(zqx_hits_total[1h])"


def test_a_label_value_with_a_quote_or_a_backslash_is_escaped_in_the_selector(monkeypatch):
    """(d) A " or a \\ in a label value ended the selector's string (or broke it)."""
    from supagent import grafana as G

    sent: list[dict] = []
    monkeypatch.setattr(G, "call", lambda tool, args=None, cached=True: (sent.append(args), [])[1])
    G.alert_rules(labels={"team": 'zqx "core"', "path": "C:\\zqx"})
    assert sent[0]["label_selectors"] == ['{team="zqx \\"core\\"", path="C:\\\\zqx"}']


def test_the_grafana_cache_drops_expired_answers_when_one_is_kept(monkeypatch):
    """(e) Expired answers stayed in the cache until 2000 keys: they are dropped when another is kept."""
    import time

    from supagent import grafana as G

    conf = {"grafana.mcp_url": "http://mcp.invalid/mcp", "grafana.cache_seconds": 60}
    monkeypatch.setattr(G, "_setting", lambda k, d=None: conf.get(k, d))
    monkeypatch.setattr(G, "_headers", lambda: {})

    async def fake_call(url, headers, tool, args, timeout):
        return {"answer": args}

    async def fake_batch(url, headers, items, timeout, concurrency):
        return [{"answer": args} for _tool, args in items]

    monkeypatch.setattr(G, "_call", fake_call)
    monkeypatch.setattr(G, "_call_batch", fake_batch)
    G._CACHE.clear()
    try:
        G._CACHE["stale"] = (time.time() - 3600, {"old": True})
        G.call("search_dashboards", {"query": "zqx"})
        assert "stale" not in G._CACHE and len(G._CACHE) == 1
        G._CACHE["stale"] = (time.time() - 3600, {"old": True})
        G.call_many([("search_dashboards", {"query": "zqx2"})])
        assert "stale" not in G._CACHE and len(G._CACHE) == 2
    finally:
        G._CACHE.clear()


def test_a_second_approval_of_a_grafana_draft_is_refused_while_the_first_runs(grafana, monkeypatch):
    """(c) approve read its row without a lock: a double click created the rule twice (and the second could write
    "failed" over "created"). The draft is claimed first: a second approval meanwhile finds no draft waiting."""
    from superset.extensions import db

    from supagent import grafana_rules as R
    from supagent.models import GrafanaAction

    _conf, calls, _created = grafana
    out = _draft()
    real_call, second, clicked = G.call, [], []
    monkeypatch.setattr(G, "alert_rules", lambda **kw: [])        # (Grafana's list not showing the first one yet)

    def call(tool, args=None, cached=True):
        if tool == "alerting_rules_write" and not clicked:         # the double click, while Grafana writes the first
            clicked.append(1)
            try:
                second.append(R.approve(out["drafted"], "admin"))
            except R.RuleError as ex:
                second.append(str(ex))
        return real_call(tool, args, cached=cached)

    monkeypatch.setattr(G, "call", call)
    done = R.approve(out["drafted"], "admin")
    assert done["created"] == out["rule_uid"]
    assert second == ["no draft waiting for approval"], second
    assert len([a for t, a in calls if t == "alerting_rules_write"]) == 1
    db.session.expire_all()
    assert db.session.get(GrafanaAction, out["drafted"]).status == "created"


def test_a_role_given_through_a_group_opens_grafana_and_osd(ctx, monkeypatch):
    """grafana.roles / osd.roles: a user who has the role only through a Superset group was refused (only the user's
    own roles were read)."""
    from flask_appbuilder.security.sqla.models import Group
    from superset.extensions import db, security_manager as sm

    from supagent import grafana as GR
    from supagent import osd as O

    conf = {"grafana.roles": ["Zqx Grafana readers"], "osd.roles": ["Zqx Grafana readers"]}
    monkeypatch.setattr(GR, "_setting", lambda k, d=None: conf.get(k, d))
    monkeypatch.setattr(O, "_setting", lambda k, d=None: conf.get(k, d))
    role = sm.find_role("Zqx Grafana readers") or sm.add_role("Zqx Grafana readers")
    user = sm.find_user(username="rp_grouped") or sm.add_user("rp_grouped", "rp", "grouped", "rp_grouped@example.com",
                                                              [sm.find_role("Gamma")], password="test-password-1")
    group = Group(name="zqx-observers", label="Zqx observers", roles=[role], users=[user])
    db.session.add(group)
    db.session.commit()
    try:
        assert GR.allowed(user) and O.allowed(user)
        assert not GR.allowed(sm.find_user(username="bob")) and not O.allowed(sm.find_user(username="bob"))
        assert not GR.allowed(None)
    finally:
        db.session.delete(group)
        db.session.commit()
