"""(0.11.8.3) A document's Delete and a page's Remove wait at most views.LOCK_WAIT for the rows a learning holds
(PostgreSQL's lock_timeout): past it they answer 409 with what happened (nothing deleted, try again in a minute) and
the document stays as it was, instead of waiting until a browser or a proxy gives up with nothing said."""
from __future__ import annotations

import pytest
import sqlalchemy as sa


class _Orig(Exception):
    pgcode = "55P03"                                   # lock_not_available, as psycopg2 raises it


def _timed_out(*_a, **_k):
    raise sa.exc.OperationalError("DELETE FROM supagent_doc", {}, _Orig("canceling statement due to lock timeout"))


@pytest.fixture()
def doc(app):
    from superset.extensions import db

    from supagent.models import Doc

    with app.app_context():
        d = Doc(kind="url", url="https://wiki.example.com/busy", max_pages=10, status="ok", content="# A\nAlpha",
                pages=[{"url": "https://wiki.example.com/busy/a", "title": "A", "chars": 9, "at": 0, "id": "7"}])
        db.session.add(d)
        db.session.commit()
        doc_id = d.id
        db.session.remove()
    yield doc_id
    with app.app_context():
        d = db.session.get(Doc, doc_id)
        if d is not None:
            db.session.delete(d)
            db.session.commit()
        db.session.remove()


def test_a_delete_that_waits_too_long_for_a_learning_says_so_and_keeps_the_document(app, doc, monkeypatch):
    from superset.extensions import db

    from conftest import login
    from supagent import views
    from supagent.models import Doc

    c = app.test_client()
    login(c, "admin")
    monkeypatch.setattr(db.session, "delete", _timed_out)
    r = c.delete(f"/supagent/admin/api/docs/{doc}")
    assert r.status_code == 409 and r.get_json()["error"] == views.BUSY.format("deleted")
    monkeypatch.undo()
    with app.app_context():
        assert db.session.get(Doc, doc) is not None
        db.session.remove()
    assert c.delete(f"/supagent/admin/api/docs/{doc}").get_json() == {"deleted": doc}


def test_a_remove_that_waits_too_long_says_so_and_keeps_the_page(app, doc, monkeypatch):
    from superset.extensions import db

    from conftest import login
    from supagent import views
    from supagent.knowledge import docs as D
    from supagent.models import Doc

    c = app.test_client()
    login(c, "admin")
    monkeypatch.setattr(D, "exclude_pages", _timed_out)
    monkeypatch.setattr(D, "exclude_page", _timed_out)
    for body in ({"pages": [{"page_id": "7"}]}, {"page_id": "7"}):
        r = c.post(f"/supagent/admin/api/docs/{doc}/pages/remove", json=body)
        assert r.status_code == 409 and r.get_json()["error"] == views.BUSY.format("removed")
    with app.app_context():
        assert [p["title"] for p in db.session.get(Doc, doc).pages] == ["A"]
        db.session.remove()


def test_another_database_error_is_not_taken_for_a_lock(app):
    from supagent import views

    other = sa.exc.OperationalError("x", {}, Exception("server closed the connection unexpectedly"))
    assert not views._lock_timed_out(other)
    assert views._lock_timed_out(sa.exc.OperationalError("x", {}, _Orig()))
