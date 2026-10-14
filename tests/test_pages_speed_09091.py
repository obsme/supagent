"""(0.10.9.1) The Data dictionary's pages on a big deployment: the settings read once for a page (settings.memo); what
To review and the map compute from the whole knowledge kept until the knowledge changes (knowledge.pagecache: a
stamp every process reads, written after any commit that changes what they read, one row or many at once, or by a
run); the map's to-do list asked once the map is drawn. A decision taken since, on any web worker, is never shown
again."""

from __future__ import annotations

import json

import sqlalchemy as sa
from test_knowledge import world  # noqa: F401  (jobs: NODE srv-1..4; metrics: node_cpu_seconds_total node srv-1,2,3,9)


def test_the_settings_are_read_once_for_a_page(ctx):
    from flask import g
    from sqlalchemy import event
    from superset.extensions import db

    from supagent import settings

    said: list[str] = []

    def count(_conn, _cursor, statement, *_a):  # noqa: ANN001
        if "supagent_setting" in statement:                                # (not the pool's own "SELECT 1")
            said.append(statement)

    settings.set_value("agent.ledger", False, by="admin")
    event.listen(db.engine, "before_cursor_execute", count)
    try:
        with settings.memo():
            first = len(said)
            assert first == 1                                              # every stored setting in one query
            for _ in range(20):
                assert settings.get("agent.ledger") is False
                assert settings.get("agent.max_steps") == 16                # at its default: no row, no query
            assert len(said) == first
            db.session.rollback()                                          # plain values: not expired by it
            assert settings.get("agent.ledger") is False and len(said) == first
            settings.set_value("agent.ledger", True, by="admin")           # written during the page: read as written
            assert settings.get("agent.ledger") is True
        assert getattr(g, settings._MEMO, None) is None
        n = len(said)
        assert settings.get("agent.ledger") is True and len(said) == n + 1  # outside: read from the database
    finally:
        event.remove(db.engine, "before_cursor_execute", count)
        settings.set_value("agent.ledger", None, by="admin")


def test_what_the_pages_compute_is_kept_until_the_knowledge_changes(ctx):
    from superset.extensions import db

    from supagent.knowledge import pagecache
    from supagent.models import Facet, Meta, Recipe, Run

    pagecache.clear()
    calls: list[int] = []

    def compute() -> int:
        calls.append(1)
        return len(calls)

    assert pagecache.cached("t", compute) == 1
    assert pagecache.cached("t", compute) == 1                             # nothing changed: kept
    f = Facet(facet="component", value="pagecache-one", status="proposed", source="admin")
    db.session.add(f)
    db.session.commit()                                                    # a row, through the session
    assert pagecache.cached("t", compute) == 2
    db.session.query(Facet).filter(Facet.id == f.id).update({"status": "approved"}, synchronize_session=False)
    db.session.commit()                                                    # rows at once: none in the session
    assert pagecache.cached("t", compute) == 3
    db.session.query(Facet).filter(Facet.id == f.id).update({"description": "x"}, synchronize_session=False)
    db.session.rollback()                                                  # not committed: nothing changed
    assert pagecache.cached("t", compute) == 3
    with db.engine.begin() as con:                                         # another process's change: its stamp
        con.execute(sa.text("UPDATE supagent_meta SET value = :v WHERE key = :k"), {"v": "elsewhere", "k": pagecache.KEY})
    assert pagecache.cached("t", compute) == 4
    run = Run(kind="learn", reason="test", status="done")                  # a run: what only a run writes
    db.session.add(run)
    db.session.commit()
    assert pagecache.cached("t", compute) == 5
    path = Recipe(question="A batch is late", tool="investigation", query="Problem: ...", signature="pagecache-p1",
                  status="helpful", generic=True)
    db.session.add(path)
    db.session.commit()                                                    # an investigation path waits
    assert pagecache.cached("t", compute) == 6
    db.session.add(Meta(key="pagecache-test", value="1"))                  # supagent_meta (a layout, a hint, a
    db.session.commit()                                                    # warning set aside): read at each request
    assert pagecache.cached("t", compute) == 6
    assert pagecache.cached("t", compute, ttl=0) == 7                      # too old
    for x in (f, run, path):
        db.session.delete(x)
    db.session.query(Meta).filter(Meta.key == "pagecache-test").delete(synchronize_session=False)
    db.session.commit()


def test_a_warning_set_aside_on_another_worker_is_not_shown_again(app, monkeypatch):
    from superset.extensions import db

    from conftest import login
    from supagent.knowledge import lint, pagecache
    from supagent.models import Facet, Meta

    with app.app_context():
        pagecache.clear()
        f = Facet(facet="component", value="relay-gw", status="approved", source="admin")
        h = Facet(facet="component", value="Relay GW", status="proposed", source="llm")
        db.session.add_all([f, h])
        db.session.commit()
        try:
            c = app.test_client()
            login(c, "admin")
            assert c.get("/supagent/admin/api/review?limit=1").get_json()["counts"]["warnings"] >= 1   # the badge
            computed: list[int] = []
            real = lint.warnings

            def counted(*a, **k):  # noqa: ANN001
                computed.append(1)
                return real(*a, **k)

            monkeypatch.setattr(lint, "warnings", counted)
            d = c.get("/supagent/admin/api/review").get_json()            # the tab, right after: what was kept
            assert computed == []
            mine = [w for w in d["warnings"] if w["kind"] == "two_ways" and w["subject"] == "relay-gw / Relay GW"]
            assert mine, d["warnings"]
            n = d["counts"]["warnings"]
            with db.engine.begin() as con:                                 # set aside by another web worker
                con.execute(sa.text("INSERT INTO supagent_meta (key, value) VALUES (:k, :v)"),
                            {"k": lint.DISMISSED, "v": json.dumps([mine[0]["key"]])})
            d = c.get("/supagent/admin/api/review").get_json()
            assert not [w for w in d["warnings"] if w["key"] == mine[0]["key"]] and d["counts"]["warnings"] == n - 1
        finally:
            db.session.delete(f)
            db.session.delete(h)
            db.session.query(Meta).filter(Meta.key == lint.DISMISSED).delete(synchronize_session=False)
            db.session.commit()


def test_where_the_categories_are_is_kept_per_set_of_databases_and_decisions_apply_at_once(world):  # noqa: F811
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import datafields as D, pagecache, valueindex as V
    from supagent.models import Facet, Meta
    from supagent.security import acting_as

    made = [Facet(facet="server", value=f"srv-{i}", status="approved", source="admin") for i in (1, 2, 3)]
    db.session.add_all(made)
    db.session.commit()
    V._CACHE.update(stamp=None, values=None, parents=None)
    pagecache.clear()
    before = settings.get("categories.fields")
    try:
        with acting_as("admin"):
            mine = D.for_review()
            assert len(mine) == 1 and len(mine[0]["where"]) == 2             # the label and the field
        with acting_as("alice"):                                           # the jobs database only: her own
            hers = D.for_review()
            assert len(hers) == 1 and hers[0]["where"] == ["field NODE of 1 index such as jobs (jobs)"], hers
        with acting_as("admin"):
            assert len(D.for_review()[0]["where"]) == 2
            with db.engine.begin() as con:                                 # read from, by another web worker
                fields = dict(before) if isinstance(before, dict) else {}
                fields["server"] = f"^{mine[0]['name']}$"
                con.execute(sa.text("UPDATE supagent_setting SET value = :v WHERE key = 'categories.fields'"),
                            {"v": json.dumps(fields)})
                if not con.execute(sa.text("SELECT 1 FROM supagent_setting WHERE key = 'categories.fields'")).first():
                    con.execute(sa.text("INSERT INTO supagent_setting (key, value) VALUES ('categories.fields', :v)"),
                                {"v": json.dumps(fields)})
            db.session.expire_all()
            assert D.for_review() == []
            settings.set_value("categories.fields", before, by="admin")
            assert len(D.for_review()) == 1
            with db.engine.begin() as con:                                 # set aside, by another web worker
                con.execute(sa.text("INSERT INTO supagent_meta (key, value) VALUES (:k, :v)"),
                            {"k": D.DISMISSED, "v": json.dumps([f"server:{mine[0]['name'].lower()}"])})
            assert D.for_review() == []
    finally:
        settings.set_value("categories.fields", before, by="admin")
        db.session.query(Meta).filter(Meta.key == D.DISMISSED).delete(synchronize_session=False)
        for f in made:
            db.session.delete(f)
        db.session.commit()


def test_the_map_asks_its_to_do_list_after_drawing(app):
    """The page script: the list is fetched once the map is drawn and kept on the page (a quiet reload of the map
    does not drop it); the map's signature no longer holds it."""
    import os

    import supagent

    js = open(os.path.join(os.path.dirname(supagent.__file__), "static", "supagent", "sysmap.js"), encoding="utf-8").read()
    assert 'S.dict("GET", "map/missing")' in js and "st.missing = " in js
    assert "d.missing" not in js and "st.data.missing" not in js
