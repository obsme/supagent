"""(0.10.11.1) The fast patch: several pages of a document removed at once (one rebuild of its text, the others in
place, the missing ones said); the chats listed and deleted from the command line (with their messages, files and
examples); the servers' CPU, memory and disks read from /proc and shown per host and component."""
from __future__ import annotations

import json

from test_doc_page_remove_09091 import PAGES, _blocks, _site


def test_several_pages_removed_at_once(ctx, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import docs as D
    from supagent.models import Doc, KFact, KUnit

    _site(monkeypatch)
    doc = Doc(kind="url", url="https://wiki.example.com/ops/a", max_pages=10)
    db.session.add(doc)
    db.session.commit()
    try:
        assert D.refresh(doc)["pages"] == 4
        for p in doc.pages:
            u = KUnit(doc_id=doc.id, ukey=p["url"], kind="page", title=p["title"], url=p["url"])
            db.session.add(u)
            db.session.flush()
            db.session.add(KFact(unit_id=u.id, subject=p["title"], verb="mentions", obj="x", source="rules"))
        db.session.commit()
        out = D.exclude_pages(doc, "admin", [{"url": "https://wiki.example.com/ops/b"},
                                             {"url": "https://wiki.example.com/ops/d"},
                                             {"url": "https://wiki.example.com/ops/zz"}])
        db.session.commit()
        assert [r["title"] for r in out["removed"]] == ["Bravo", "Delta"] and out["missing"] == ["https://wiki.example.com/ops/zz"]
        assert out["pages"] == 2 and out["units"] == 2 and out["facts"] == 2
        assert [p["title"] for p in doc.pages] == ["Alpha", "Charlie"] and "QZX_RELAY" not in doc.content
        assert [b.split("\n")[0] for b in _blocks(doc)] == ["# Alpha", "# Charlie"]
        assert sorted(e["key"] for e in D.excluded_pages(doc)) == ["url:https://wiki.example.com/ops/b",
                                                                   "url:https://wiki.example.com/ops/d"]
        assert D.refresh(doc)["pages"] == 2                       # never read again
    finally:
        db.session.query(KUnit).filter(KUnit.doc_id == doc.id).delete(synchronize_session=False)
        db.session.delete(doc)
        db.session.commit()


def test_the_pages_route_takes_a_list(app, monkeypatch):
    from superset.extensions import db

    from conftest import login
    from supagent.knowledge import docs as D
    from supagent.models import Doc

    _site(monkeypatch)
    with app.app_context():
        doc = Doc(kind="url", url="https://wiki.example.com/ops/a", max_pages=10)
        db.session.add(doc)
        db.session.commit()
        D.refresh(doc)
        doc_id = doc.id
        db.session.remove()
    try:
        c = app.test_client()
        login(c, "admin")
        r = c.post(f"/supagent/admin/api/docs/{doc_id}/pages/remove",
                   json={"pages": [{"url": "https://wiki.example.com/ops/b"}, {"url": "https://wiki.example.com/ops/c"}]})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.get_json()["pages"] == 2 and len(r.get_json()["removed"]) == 2
        d = c.get(f"/supagent/admin/api/docs/{doc_id}/pages").get_json()
        assert sorted(e["title"] for e in d["excluded"]) == ["Bravo", "Charlie"]
        assert c.post(f"/supagent/admin/api/docs/{doc_id}/pages/remove",
                      json={"pages": [{"url": "https://wiki.example.com/ops/zz"}]}).status_code == 400
        c2 = app.test_client()
        login(c2, "alice")
        assert c2.post(f"/supagent/admin/api/docs/{doc_id}/pages/remove",
                       json={"pages": [{"url": "https://wiki.example.com/ops/a"}]}).status_code in (401, 403)
    finally:
        with app.app_context():
            db.session.delete(db.session.get(Doc, doc_id))
            db.session.commit()
            db.session.remove()


def test_chats_listed_and_deleted(ctx):
    from superset.extensions import db, security_manager

    from supagent import chats
    from supagent.models import Conversation, File, Message

    user = security_manager.find_user(username="admin")
    conv = Conversation(user_id=user.id, title="anomalies of a dashboard")
    db.session.add(conv)
    db.session.flush()
    m = Message(conversation_id=conv.id, role="assistant", content="x" * 1000, status="done",
                results=[{"rows": [[i, i * 2] for i in range(500)], "columns": ["a", "b"], "row_count": 500}])
    db.session.add(m)
    db.session.flush()
    db.session.add(File(message_id=m.id, name="r.xlsx", mime="application/octet-stream", size=3, data=b"abc"))
    db.session.commit()
    cid, mid = conv.id, m.id
    row = next(r for r in chats.listed(user.id) if r["id"] == cid)
    assert row["user"] == "admin" and row["messages"] == 1 and row["bytes"] > 5000 and row["running"] == 0
    assert chats.delete([cid, 999999999]) == 1
    assert db.session.get(Conversation, cid) is None
    assert db.session.query(Message).filter_by(conversation_id=cid).count() == 0
    assert db.session.query(File).filter_by(message_id=mid).count() == 0


def test_conversations_command(app):
    from superset.extensions import db, security_manager

    from supagent.cli import conversations_cmd
    from supagent.models import Conversation

    with app.app_context():
        user = security_manager.find_user(username="admin")
        conv = Conversation(user_id=user.id, title="to delete from the command line")
        db.session.add(conv)
        db.session.commit()
        cid = conv.id
        db.session.remove()
    runner = app.test_cli_runner()
    out = runner.invoke(conversations_cmd, ["--user", "admin"])
    assert out.exit_code == 0 and "to delete from the command line" in out.output
    out = runner.invoke(conversations_cmd, ["--delete", str(cid)])
    assert out.exit_code == 0 and "Nothing was changed" in out.output
    out = runner.invoke(conversations_cmd, ["--delete", str(cid), "--yes"])
    assert out.exit_code == 0 and "Deleted 1 chat" in out.output
    out = runner.invoke(conversations_cmd, ["--delete", str(cid), "--yes"])        # gone: said, nothing deleted
    assert out.exit_code == 0 and f"No chat {cid}." in out.output and "Nothing to delete." in out.output
    with app.app_context():
        assert db.session.get(Conversation, cid) is None
        db.session.remove()


def test_host_sample_and_roles():
    from supagent import hoststats as H

    assert H.role_of(["/venv/bin/gunicorn", "-w", "4", "superset.app:create_app()"]) == "web"
    assert H.role_of(["/venv/bin/celery", "--app=superset.tasks.celery_app:app", "worker"]) == "worker"
    assert H.role_of(["/venv/bin/celery", "--app=superset.tasks.celery_app:app", "beat"]) == "beat"
    assert H.role_of(["/venv/bin/superset", "supagent", "conversations"]) is None
    assert H.role_of(["/venv/bin/superset", "run", "-p", "8088"]) == "web"
    first, cpu = H.sample()
    second, _ = H.sample(cpu)
    assert first["mem_total"] > 0 and 0 <= first["mem_pct"] <= 100 and first["cpus"] >= 1
    assert first["disks"] and all(d["holds"] and d["mount"].startswith("/") for d in first["disks"])   # (0.11.0)
    assert second["cpu_pct"] is None or 0 <= second["cpu_pct"] <= 100
    assert json.loads(json.dumps(second))["superset"]["count"] >= 0


def test_hosts_read_back(ctx):
    import datetime as dt

    from superset.extensions import db

    from supagent import hoststats as H
    from supagent.models import Meta

    now = dt.datetime.utcnow().isoformat(timespec="seconds")
    old = (dt.datetime.utcnow() - dt.timedelta(hours=1)).isoformat(timespec="seconds")
    rows = [Meta(key="host:srv-a:web", value=json.dumps({"host": "srv-a", "role": "web", "last": {"at": now, "cpu_pct": 12.5},
                                                         "history": [{"at": now, "cpu": 12.5}]})),
            Meta(key="host:srv-a:worker", value=json.dumps({"host": "srv-a", "role": "worker", "last": {"at": old}})),
            Meta(key="host:srv-b:beat", value=json.dumps({"host": "srv-b", "role": "beat", "last": {"at": now}}))]
    db.session.add_all(rows)
    db.session.commit()
    try:
        got = {h["host"]: h for h in H.hosts()}
        assert got["srv-a"]["roles"]["web"]["alive"] and not got["srv-a"]["roles"]["worker"]["alive"]
        assert got["srv-a"]["last"]["cpu_pct"] == 12.5 and got["srv-a"]["history"]
        assert set(got["srv-b"]["roles"]) == {"beat"}
    finally:
        for r in rows:
            db.session.delete(r)
        db.session.commit()


def _log_rows(n: int, width: int) -> list:
    return [[f"2026-10-02 10:{i % 60:02d}:00", "checkout", "ERROR " + "timeout upstream " * (width // 17), i] for i in range(n)]


def test_page_results_are_bounded():
    from supagent import pagekeep as P

    heavy = [{"tool": "execute_sql", "sql": f"SELECT * FROM logs -- {k}", "columns": ["ts", "service", "message", "n"],
              "rows": _log_rows(5000, 3000), "row_count": 5000, "truncated": True} for k in range(6)]
    out, changed = P.fit_results(heavy)
    size = len(json.dumps(out))
    assert changed and size <= P.RESULTS_BYTES * 1.05, size
    for r in out:
        assert r["row_count"] == 5000 and r["truncated"] and r["cut_for_page"] and r[P.FIT] == 1
        assert 0 < len(r["rows"]) < 5000 and all(len(row[2]) <= P.CELL_CHARS + 2 for row in r["rows"])
    again, changed = P.fit_results(out)
    assert not changed and again == out                    # bounded once: read again as it is
    small = [{"columns": ["app", "n"], "rows": [["A", 7], ["B", 5]], "row_count": 2, "truncated": False}]
    fitted, changed = P.fit_results(small)
    assert changed and fitted[0]["rows"] == [["A", 7], ["B", 5]] and not fitted[0]["truncated"] and "cut_for_page" not in fitted[0]
    long = [{"columns": ["message", "n"], "rows": [["x" * 9000, 1], ["y", 2]], "row_count": 2, "truncated": False}]
    cells = P.fit_results(long)[0][0]
    assert len(cells["rows"]) == 2 and not cells["truncated"] and cells["cut_for_page"] and len(cells["rows"][0][0]) <= P.CELL_CHARS + 2
    wide = [{"columns": [f"c{i}" for i in range(300)], "rows": [list(range(300))], "row_count": 1}]
    assert len(P.fit_results(wide)[0][0]["columns"]) == P.RESULT_COLUMNS == len(P.fit_results(wide)[0][0]["rows"][0])


def test_steps_are_bounded():
    from supagent import pagekeep as P

    steps = [{"tool": "execute_sql", "status": "done", "args": {"request": {"sql": "SELECT " + "x, " * 20000}},
              "result": "r" * 5000, "found": [{"kind": "doc", "title": "t" * 5000}] * 500},
             {"tool": "work_plan", "status": "done", "args": {"tasks": ["a"]}, "result": "ok"}]
    out = P.fit_steps(steps)
    assert len(json.dumps(out[0]["args"])) <= P.ARGS_CHARS + 50 and len(out[0]["result"]) == 1500
    assert len(out[0]["found"]) == P.STEP_LIST and len(out[0]["found"][0]["title"]) <= P.TEXT_CHARS + 2
    assert out[1] == steps[1]


def test_a_heavy_chat_opens_bounded_and_is_kept_so(app):
    from superset.extensions import db, security_manager as sm

    from conftest import login
    from supagent import pagekeep as P
    from supagent.models import Conversation, Message

    with app.app_context():
        u = sm.find_user(username="alice")
        conv = Conversation(user_id=u.id, title="anomalies")
        db.session.add(conv)
        db.session.flush()
        ids = []
        for k, rows in enumerate((_log_rows(3, 50), _log_rows(10, 50), _log_rows(2500, 2500))):
            db.session.add(Message(conversation_id=conv.id, role="user", content=f"question {k}", status="done"))
            m = Message(conversation_id=conv.id, role="assistant", status="done", content="# Found\n" + "x" * (100_000 if k == 2 else 10),
                        steps=[{"tool": "execute_sql", "status": "done", "args": {"sql": "SELECT " + "y" * 50_000}}],
                        results=[{"tool": "execute_sql", "sql": "SELECT *", "columns": ["ts", "service", "message", "n"],
                                  "rows": rows, "row_count": len(rows), "truncated": False}])
            db.session.add(m)
            db.session.flush()
            ids.append(m.id)
        db.session.commit()
        cid = conv.id
        db.session.remove()
    with app.test_client() as c:
        login(c, "alice")
        data = c.get(f"/supagent/api/conversations/{cid}").get_json()
        answers = [m for m in data["messages"] if m["role"] == "assistant"]
        assert answers[0]["results"] == [] and answers[0]["results_later"] is True     # the earliest: when asked
        assert answers[1]["results"][0]["rows"] == _log_rows(10, 50) and not answers[1].get("results_later")
        assert answers[2]["results"] == [] and answers[2]["results_later"] is True     # 6 MB kept before: when asked
        assert len(answers[2]["content"]) > 100_000 and len(answers[2]["html"]) < 70_000   # drawn: its beginning
        assert len(json.dumps(answers[2]["steps"][0]["args"])) <= P.ARGS_CHARS + 50
        last = c.get(f"/supagent/api/messages/{ids[2]}").get_json()["results"][0]          # asked: bounded, kept so
        assert last["cut_for_page"] and last["row_count"] == 2500 and len(json.dumps(last)) <= P.RESULT_BYTES * 1.05
        early = c.get(f"/supagent/api/messages/{ids[0]}").get_json()
        assert early["results"][0]["rows"] == _log_rows(3, 50)
        again = c.get(f"/supagent/api/conversations/{cid}").get_json()                   # light now: with the chat
        assert again["messages"][-1]["results"][0]["cut_for_page"] and not again["messages"][-1].get("results_later")
    with app.app_context():
        kept = db.session.get(Message, ids[2]).results                    # saved bounded: the next opening is light
        assert kept[0][P.FIT] == 1 and len(json.dumps(kept)) <= P.RESULT_BYTES * 1.05
        db.session.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
        db.session.query(Conversation).filter(Conversation.id == cid).delete(synchronize_session=False)
        db.session.commit()
        db.session.remove()


def test_a_host_reads_back_its_own_history(ctx):
    from superset.extensions import db

    from supagent import hoststats as H
    from supagent.models import Meta

    rows = [Meta(key="host:srv-z:beat", value=json.dumps({"history": [{"at": "2026-10-16T10:00:00", "cpu": 99.0}]})),
            Meta(key="host:srv-y:web", value=json.dumps({"history": [{"at": "2026-10-16T10:05:00", "cpu": 7.0}]}))]
    db.session.add_all(rows)
    db.session.commit()
    try:
        assert H._history(db.engine, "host:srv-y:web") == [{"at": "2026-10-16T10:05:00", "cpu": 7.0}]
        assert H._history(db.engine, "host:srv-x:web") == []
    finally:
        for r in rows:
            db.session.delete(r)
        db.session.commit()


def test_a_long_query_is_kept_whole_for_helpful(app):
    """(0.10.11.2) The steps are stored whole: Helpful keeps the answer's SQL as an example, whatever its length (the
    page gets a cut copy)."""
    from superset.extensions import db, security_manager as sm

    from conftest import login
    from supagent.models import Conversation, Example, Message
    from supagent.pagekeep import ARGS_CHARS
    from supagent.runner import _steps_for_page

    sql = "SELECT app, COUNT(*) AS n FROM jobs WHERE " + " OR ".join(f"name = 'job-{i:05d}'" for i in range(400)) + " GROUP BY app"
    assert len(sql) > 5000
    trace = [{"tool": "execute_sql", "status": "done", "seconds": 1.0, "result": "{}",
              "args": {"request": {"sql": sql, "database_id": 1}}}]
    steps = _steps_for_page(trace)
    assert steps[0]["args"]["request"]["sql"] == sql                      # stored whole
    with app.app_context():
        u = sm.find_user(username="alice")
        conv = Conversation(user_id=u.id, title="jobs per application")
        db.session.add(conv)
        db.session.flush()
        db.session.add(Message(conversation_id=conv.id, role="user", content="How many jobs per application?", status="done"))
        m = Message(conversation_id=conv.id, role="assistant", status="done", content="7 and 5.", steps=steps,
                    results=[])
        db.session.add(m)
        db.session.commit()
        cid, mid = conv.id, m.id
        db.session.remove()
    try:
        with app.test_client() as c:
            login(c, "alice")
            page = c.get(f"/supagent/api/messages/{mid}").get_json()
            assert len(json.dumps(page["steps"][0]["args"])) <= ARGS_CHARS + 50      # the page's copy: cut
            assert c.post(f"/supagent/api/messages/{mid}/feedback", json={"value": 1}).get_json()["example_kept"]
        with app.app_context():
            assert db.session.query(Example).filter_by(message_id=mid).one().sql == sql   # the example: whole
    finally:
        with app.app_context():
            db.session.query(Example).filter_by(message_id=mid).delete(synchronize_session=False)
            db.session.query(Message).filter(Message.conversation_id == cid).delete(synchronize_session=False)
            db.session.query(Conversation).filter(Conversation.id == cid).delete(synchronize_session=False)
            db.session.commit()
            db.session.remove()
