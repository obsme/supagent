"""The three roles of 0.9.6 (supagent init): AI Admin (everything), AI Editor (charts, dashboards, datasets explored,
SQL Lab, the knowledge written; no settings, no deletion), AI Viewer (read and chat; nothing changed). Superset's own
roles they are made from as they are: Gamma may create charts and dashboards, so the Viewer is Gamma without any
permission that changes something. A matrix of what each may do, over HTTP."""

import pytest

from conftest import PASSWORD, login


@pytest.fixture(scope="module")
def roles(app):
    from superset.extensions import db, security_manager as sm

    from supagent.cli import ADMIN_ROLE, EDITOR_ROLE, VIEWER_ROLE, ensure_roles

    with app.app_context():
        got = ensure_roles(viewer_data=False)
        for name, role in (("r_admin", ADMIN_ROLE), ("r_editor", EDITOR_ROLE), ("r_viewer", VIEWER_ROLE)):
            if sm.find_user(username=name) is None:
                sm.add_user(name, name, "Test", f"{name}@example.com", [sm.find_role(role)], password=PASSWORD)
        db.session.commit()
        db.session.remove()
    return got


def perms(app, name):
    from superset.extensions import security_manager as sm

    with app.app_context():
        return {(p.permission.name, p.view_menu.name) for p in sm.find_role(name).permissions}


def test_what_each_role_holds(app, roles):
    from supagent.cli import ADMIN_ROLE, EDITOR_ROLE, VIEWER_ROLE, WRITE_LIKE

    viewer, editor, admin = perms(app, VIEWER_ROLE), perms(app, EDITOR_ROLE), perms(app, ADMIN_ROLE)
    changes = [p for p in viewer if WRITE_LIKE.search(p[0]) and "favorite" not in p[0].lower()
               and p != ("can_write", "AIAgent")]          # (that one is asking in the chat)
    assert changes == [], changes[:5]                       # nothing that changes anything
    assert ("can_write", "Chart") not in viewer and ("can_write", "Dashboard") not in viewer
    assert ("can_read", "Chart") in viewer and ("can_read", "Dashboard") in viewer
    assert ("can_read", "AIAgent") in viewer and ("can_write", "AIAgent") in viewer     # the chat
    assert not {p for p in viewer if p[1] == "AIAgentAdmin"}
    assert ("all_datasource_access", "all_datasource_access") not in viewer             # data: not by default
    assert ("can_write", "Chart") in editor and ("can_write", "Dashboard") in editor
    assert ("can_edit", "AIAgentAdmin") in editor and ("can_read", "AIAgentAdmin") in editor
    assert ("can_write", "AIAgentAdmin") not in editor and ("can_delete", "AIAgentAdmin") not in editor
    assert not [p for p in editor if "delete" in p[0].lower()]
    assert {("can_write", "AIAgentAdmin"), ("can_delete", "AIAgentAdmin"), ("can_edit", "AIAgentAdmin")} <= admin


def test_the_viewers_data_only_when_asked(app, roles):
    from supagent.cli import VIEWER_ROLE, ensure_roles

    with app.app_context():
        ensure_roles(viewer_data=True)
    assert ("all_datasource_access", "all_datasource_access") in perms(app, VIEWER_ROLE)


MATRIX = [
    # (what, method, url, json, {role: allowed})
    ("chat: list my conversations", "GET", "/supagent/api/conversations", None,
     {"r_viewer": True, "r_editor": True, "r_admin": True}),
    ("dictionary page", "GET", "/supagent/dictionary/", None, {"r_viewer": True, "r_editor": True, "r_admin": True}),
    ("knowledge read: the catalog", "GET", "/supagent/admin/api/entries", None,
     {"r_viewer": False, "r_editor": True, "r_admin": True}),
    ("knowledge written: a catalog entry", "POST", "/supagent/admin/api/entries",
     {"title": "Roles test entry", "text": "An entry written by the roles test.", "classification": "guide"},
     {"r_viewer": False, "r_editor": True, "r_admin": True}),
    ("settings read", "GET", "/supagent/admin/api/settings", None, {"r_viewer": False, "r_editor": False, "r_admin": True}),
    ("settings page", "GET", "/supagent/admin/", None, {"r_viewer": False, "r_editor": False, "r_admin": True}),
    ("learning started", "POST", "/supagent/admin/api/learn", {}, {"r_viewer": False, "r_editor": False, "r_admin": None}),
    ("the dictionary's writes: a learned answer changed", "POST", "/supagent/dictionary/api/recipes/999999",
     {"title": "x"}, {"r_viewer": False, "r_editor": None, "r_admin": None}),
    ("the dictionary's writes: a Context page edited", "POST", "/supagent/dictionary/api/context/999999",
     {"content": "x"}, {"r_viewer": False, "r_editor": None, "r_admin": None}),
    ("the Context built", "POST", "/supagent/dictionary/api/context/build", {},
     {"r_viewer": False, "r_editor": False, "r_admin": None}),
    ("Superset: a chart created", "POST", "/api/v1/chart/", {"slice_name": "x", "viz_type": "table",
                                                            "datasource_id": 999999, "datasource_type": "table"},
     {"r_viewer": False, "r_editor": None, "r_admin": None}),
]


@pytest.mark.parametrize("who", ["r_viewer", "r_editor", "r_admin"])
def test_the_matrix(app, roles, who):
    with app.test_client() as c:
        login(c, who)
        for what, method, url, body, allowed in MATRIX:
            if body and "title" in body:                # an entry of each role's own
                body = {**body, "title": f"{body['title']} {who}"}
            r = c.open(url, method=method, json=body)
            want = allowed[who]
            if want is None:                    # allowed; the request itself may still be refused for its content
                assert r.status_code not in (401, 403), (who, what, r.status_code)
            elif want:
                assert r.status_code in (200, 201, 302), (who, what, r.status_code, r.get_data(as_text=True)[:200])
            else:
                assert r.status_code in (302, 401, 403, 404), (who, what, r.status_code)


def test_an_editor_may_not_delete(app, roles):
    """The catalog entry the editor wrote: deleting it is an admin's."""
    with app.test_client() as c:
        login(c, "r_editor")
        made = c.post("/supagent/admin/api/entries", json={"title": "Roles test to delete", "text": "x y z",
                                                           "classification": "guide"}).get_json()
        eid = (made.get("entry") or {}).get("id")
        assert eid
        assert c.delete(f"/supagent/admin/api/entries/{eid}?version=1").status_code in (401, 403)
    with app.test_client() as c:
        login(c, "r_admin")
        assert c.delete(f"/supagent/admin/api/entries/{eid}?version=1").status_code == 200


def test_a_role_with_the_settings_keeps_the_knowledge(app, roles):
    from superset.extensions import db, security_manager as sm

    from supagent.cli import ensure_roles

    with app.app_context():
        role = sm.find_role("Custom knowledge admins") or sm.add_role("Custom knowledge admins")
        sm.add_permission_role(role, sm.find_permission_view_menu("can_write", "AIAgentAdmin"))
        db.session.commit()
        ensure_roles()
        got = {p.permission.name for p in sm.find_role("Custom knowledge admins").permissions
               if p.view_menu.name == "AIAgentAdmin"}
        assert {"can_write", "can_read", "can_edit", "can_delete"} <= got
