"""(0.10.9.1) A field or a metric the team deactivates in the Data dictionary: the agent and the search never see it
nor use it, the learning leaves it deactivated, a query naming it is sent back."""
from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)
from test_search import clean_knowledge  # noqa: F401  (the fixture)


def test_a_deactivated_metric_and_its_labels_are_hidden_kept_and_refused(clean_knowledge, app):
    from superset.extensions import db

    from supagent.knowledge import deactivate as D
    from supagent.knowledge.store import upsert
    from supagent.models import KObject

    m = db.session.query(KObject).filter_by(kind="metric").first()
    assert m is not None
    labels = db.session.query(KObject).filter_by(kind="label", parent=m.name, source_id=m.source_id).all()
    n = D.set_active(m, False)
    db.session.commit()
    assert n == 1 + len(labels) and D.is_deactivated(m)
    live = db.session.query(KObject).filter(KObject.gone_at.is_(None), KObject.name == m.name).count()
    assert live == 0                                       # every reader of the live objects leaves it out
    from supagent.models import Source

    src = db.session.get(Source, m.source_id)
    upsert(None, src, "metric", "", m.name, {"metric_type": m.metric_type})   # the learning sees it again
    db.session.commit()
    assert D.is_deactivated(db.session.get(KObject, m.id))  # still deactivated
    sql = {"request": {"database_id": 1, "sql": f'SELECT SUM(value) FROM "{m.name}"'}}
    said = D.refusal("execute_sql", sql)
    assert said and said.startswith("tool error (not run: deactivated)") and m.name in said
    assert D.refusal("execute_sql", {"request": {"database_id": 1, "sql": 'SELECT 1 FROM "other_table"'}}) is None
    D.set_active(m, True)
    db.session.commit()
    assert db.session.get(KObject, m.id).gone_at is None
    assert all(db.session.get(KObject, x.id).gone_at is None for x in labels)


def test_editors_deactivate_and_activate_from_the_dictionary(clean_knowledge, app):
    from superset.extensions import db

    from supagent.models import KObject
    from conftest import login

    f = db.session.query(KObject).filter_by(kind="field").first()
    if f is None:
        f = db.session.query(KObject).filter_by(kind="label").first()
    oid = f.id
    with app.app_context(), app.test_client() as c:
        login(c, "admin")
        r = c.post(f"/supagent/dictionary/api/objects/{oid}", json={"active": False})
        assert r.status_code == 200 and r.get_json()["deactivated"] is True, r.get_data(as_text=True)[:300]
    db.session.expire_all()
    from supagent.knowledge.deactivate import is_deactivated

    assert is_deactivated(db.session.get(KObject, oid))
