"""(0.9.6.6) Three roles only, Admin, Editor and Viewer: supagent's AI roles merged into Superset's Admin, Alpha and
Gamma, these two renamed; Superset's role sync makes Editor and Viewer where it made Alpha and Gamma; a configuration
that names a role that would go stops it; --undo gives every user's roles back."""

from __future__ import annotations

import pytest

from conftest import login


@pytest.fixture()
def three(app):
    """The AI roles as 0.9.6 makes them; whatever a test did, the roles as they were at the end."""
    from superset.extensions import db, security_manager as sm

    from supagent import roles as R
    from supagent.cli import ensure_roles

    with app.app_context():
        ensure_roles()
        alpha = sm.find_role("Alpha")
        u = sm.find_user(username="erin") or sm.add_user("erin", "erin", "Test", "erin@example.com",
                                                          [alpha, sm.find_role("AI Editor")], password="test-password-1")
        db.session.commit()
        before = {x.username: sorted(r.name for r in x.roles) for x in db.session.query(sm.user_model)}
    yield before
    with app.app_context():
        if R.simple():
            R.undo("test")
        db.session.commit()


def _names(sm, db):
    return {r.name for r in db.session.query(sm.role_model)}


def test_what_would_change_and_what_stops_it(app, three):
    from superset.extensions import db, security_manager as sm

    from supagent import roles as R

    with app.app_context():
        p = R.plan()
        assert ["Alpha", "Editor"] in p["rename"] and ["Gamma", "Viewer"] in p["rename"]
        assert p["merge"]["AI Editor"]["to"] == "Editor" and "erin" in p["merge"]["AI Editor"]["users"]
        assert {"Alpha", "Gamma", "AI Viewer"} <= _names(sm, db)          # nothing changed
        app.config["AUTH_USER_REGISTRATION_ROLE"] = "Gamma"                # new users get Gamma: it would go
        try:
            with pytest.raises(R.RolesError) as e:
                R.apply("test", force=True)
            assert "AUTH_USER_REGISTRATION_ROLE names Gamma: write Gamma -> Viewer there first" in str(e.value)
        finally:
            app.config.pop("AUTH_USER_REGISTRATION_ROLE", None)
        assert {"Alpha", "Gamma"} <= _names(sm, db) and not R.simple()


def test_admin_editor_viewer_only_and_back(app, three):
    from superset.extensions import db, security_manager as sm

    from supagent import roles as R
    from supagent.views import ChatView

    with app.app_context():
        gamma_id = sm.find_role("Gamma").id
        R.apply("test")
        names = _names(sm, db)
        assert {"Admin", "Editor", "Viewer"} <= names
        assert not names & {"Alpha", "Gamma", "AI Admin", "AI Editor", "AI Viewer", "AI Agent"}
        assert sm.find_role("Viewer").id == gamma_id                       # the same role, renamed
        assert sorted(r.name for r in sm.find_user(username="erin").roles) == ["Editor"]
        alice = {r.name for r in sm.find_user(username="alice").roles}         # (Gamma and AI Agent before)
        assert "Viewer" in alice and not alice & {"Gamma", "AI Agent"}
        sm.sync_role_definitions()                                         # superset init
        db.session.commit()
        names = _names(sm, db)
        assert "Alpha" not in names and "Gamma" not in names               # not made again
        editor, viewer = sm.find_role("Editor"), sm.find_role("Viewer")
        assert not [p for p in editor.permissions if "delete" in p.permission.name.lower()]
        assert not [p for p in viewer.permissions if p.permission.name.startswith(("can_write", "can_delete"))
                    and p.view_menu.name != ChatView.class_permission_name]            # (writing in the chat: its own)
        chat = sm.find_permission_view_menu("can_read", ChatView.class_permission_name)
        assert chat in editor.permissions and chat in viewer.permissions
        assert [p for p in editor.permissions if p.permission.name == "can_write" and p.view_menu.name == "Chart"]
        carol = sm.find_user(username="carol") or sm.add_user("carol", "carol", "Test", "carol@example.com", [viewer],
                                                              password="test-password-1")
        db.session.commit()
    with app.test_client() as c:                                          # a Viewer chats
        login(c, "carol")
        assert c.get("/supagent/").status_code == 200 and c.get("/supagent/dictionary/").status_code == 200
        assert c.get("/supagent/admin/").status_code in (302, 403)             # the settings: admins only
    with app.app_context():
        R.undo("test")
        names = _names(sm, db)
        assert {"Alpha", "Gamma", "AI Admin", "AI Editor", "AI Viewer", "AI Agent"} <= names
        assert not names & {"Editor", "Viewer"} and not R.simple()
        now = {x.username: sorted(r.name for r in x.roles) for x in db.session.query(sm.user_model)}
        assert {k: v for k, v in now.items() if k in three} == three       # every user's roles as they were
        assert now["carol"] == ["AI Viewer", "Gamma"]                      # made since: its supagent role too
        db.session.delete(sm.find_user(username="carol"))
        db.session.commit()
