"""(0.9.6.9) The System map edited where it is drawn, each change saved at once: a value added (inside another
one), put inside another (moved, copied, taken out; never inside what is inside it), taken off the map (who may
delete); a category made (a subcategory inside another), moved inside another or out."""

from __future__ import annotations

import pytest

from test_dictionary_080 import _client

API = "/supagent/dictionary/api/map"


@pytest.fixture()
def editor(app):
    """A user who may edit the knowledge, not delete it (AI Editor)."""
    from superset.extensions import db, security_manager as sm

    from supagent.cli import ensure_roles

    with app.app_context():
        ensure_roles()
        if sm.find_user(username="edna") is None:
            sm.add_user("edna", "edna", "Test", "edna@example.com", [sm.find_role("Gamma"), sm.find_role("AI Editor")],
                        password="test-password-1")
        db.session.commit()
    yield "edna"


def _parents(app, fid):
    from supagent.knowledge.facets import part_of_map

    with app.app_context():
        return part_of_map().get(fid, [])


def test_values_added_put_inside_and_taken_off(app, editor):
    from superset.extensions import db

    from supagent import settings
    from supagent.models import Facet, Link

    made: list[int] = []
    try:
        with _client(app, editor) as c:
            srv = c.post(API, json={"add_value": {"facet": "application", "value": "zz-edit-app"}}).get_json()
            made.append(srv["id"])
            other = c.post(API, json={"add_value": {"facet": "application", "value": "zz-edit-app-2"}}).get_json()
            made.append(other["id"])
            comp = c.post(API, json={"add_value": {"facet": "component", "value": "zz-edit-comp",
                                                   "inside": srv["id"]}}).get_json()   # added inside it
            made.append(comp["id"])
            assert _parents(app, comp["id"]) == [srv["id"]]
            dup = c.post(API, json={"add_value": {"facet": "component", "value": "ZZ-EDIT-COMP"}})
            assert dup.status_code == 400 and "already" in dup.get_json()["error"]
            r = c.post(API, json={"inside": {"id": comp["id"], "parent": other["id"], "mode": "copy"}}).get_json()
            assert r["parents"] == [srv["id"], other["id"]]                                # inside both
            r = c.post(API, json={"inside": {"id": comp["id"], "parent": srv["id"], "mode": "move"}}).get_json()
            assert r["parents"] == [srv["id"]]                     # moved: out of the other application
            loop = c.post(API, json={"inside": {"id": srv["id"], "parent": comp["id"], "mode": "move"}})
            assert loop.status_code == 400 and "not both ways" in loop.get_json()["error"]
            r = c.post(API, json={"inside": {"id": comp["id"], "parent": srv["id"], "mode": "out"}}).get_json()
            assert r["parents"] == []
            assert c.post(API, json={"remove_value": comp["id"]}).status_code == 403      # an editor does not delete
            values = {v["id"]: v for v in c.get(API).get_json()["values"]}
            assert comp["id"] in values and values[comp["id"]]["value"] == "zz-edit-comp"
        with _client(app, "alice") as c:                          # who may not edit the knowledge
            assert c.post(API, json={"add_value": {"facet": "application", "value": "zz-nope"}}).status_code == 403
        with _client(app, "admin") as c:
            assert c.post(API, json={"remove_value": comp["id"]}).get_json()["status"] == "rejected"
            assert comp["id"] not in {v["id"] for v in c.get(API).get_json()["values"]}   # off the map
    finally:
        with app.app_context():
            refs = [f"facet:{i}" for i in made]
            db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_(made or [-1])).delete(synchronize_session=False)
            db.session.commit()
            settings.set_value("categories.custom", [x for x in settings.get("categories.custom") or []
                                                     if not str(x).startswith("zz")])


def test_categories_made_and_moved_on_the_map(app, editor):
    from supagent import settings
    from supagent.knowledge import facets as F

    try:
        with _client(app, editor) as c:
            r = c.post(API, json={"add_category": {"name": "zz rack"}}).get_json()
            assert r == {"name": "zz rack", "inside": ""}
            r = c.post(API, json={"add_category": {"name": "zz slot", "inside": "zz rack"}}).get_json()
            assert r == {"name": "zz slot", "inside": "zz rack"}                          # a subcategory
            assert c.post(API, json={"add_category": {"name": "zz rack"}}).status_code == 400
            back = c.post(API, json={"category_inside": {"name": "zz rack", "inside": "zz slot"}})
            assert back.status_code == 400 and "not both ways" in back.get_json()["error"]
            assert c.post(API, json={"category_inside": {"name": "zz slot", "inside": ""}}).get_json()["inside"] == ""
            cats = {x["name"]: x for x in c.get(API).get_json()["categories"]}
            assert "zz rack" in cats and cats["zz slot"]["inside"] == ""
        with app.app_context():
            assert "zz rack" in F.editable() and F.inside().get("zz slot") is None
    finally:
        with app.app_context():
            settings.set_value("categories.custom", [x for x in settings.get("categories.custom") or []
                                                     if not str(x).startswith("zz")])
            settings.set_value("categories.inside", None)
