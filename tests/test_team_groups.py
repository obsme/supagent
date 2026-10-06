"""Teams are Superset's groups (0.9.6, FAB 5: users belong to groups): a note or a memory may be for one group, read
by its members (and an admin), found by the search for them only; an AI Viewer writes for themselves only."""

import pytest

from conftest import PASSWORD, login


@pytest.fixture(scope="module")
def team(app):
    from flask_appbuilder.security.sqla.models import Group
    from superset.extensions import db, security_manager as sm

    from supagent.cli import VIEWER_ROLE, ensure_roles

    with app.app_context():
        ensure_roles()
        grp = db.session.query(Group).filter_by(name="payments-team").first() or Group(name="payments-team",
                                                                                       label="Payments team")
        db.session.add(grp)
        db.session.flush()
        alice = sm.find_user(username="alice")
        if grp not in alice.groups:
            alice.groups.append(grp)
        if sm.find_user(username="g_viewer") is None:
            sm.add_user("g_viewer", "g", "viewer", "g_viewer@example.com", [sm.find_role(VIEWER_ROLE)],
                        password=PASSWORD)
        db.session.commit()
        gid = grp.id
        db.session.remove()
    return gid


def test_a_groups_note_is_read_by_its_members(app, team):
    with app.test_client() as c:
        login(c, "alice")
        groups = c.get("/supagent/api/sharing").get_json()
        assert groups["can_share"] and {"id": team, "name": "payments-team"} in groups["groups"]
        r = c.post("/supagent/api/notes", json={"text": "Payments: the refund batch moves to 22:00.", "scope": "group",
                                                "group_id": team})
        assert r.status_code == 200 and r.get_json()["note"]["group"] == "payments-team"
        nid = r.get_json()["note"]["id"]
        mine = [n["id"] for n in c.get("/supagent/api/notes").get_json()["notes"]]
        assert nid in mine
        bad = c.post("/supagent/api/notes", json={"text": "x", "scope": "group", "group_id": 999999})
        assert bad.status_code == 400 and "no group" in bad.get_json()["error"]
    with app.test_client() as c:
        login(c, "bob")                                         # not in the group
        assert nid not in [n["id"] for n in c.get("/supagent/api/notes").get_json()["notes"]]


def test_the_search_finds_a_groups_note_for_its_members_only(app, team):
    from superset.extensions import db, security_manager as sm

    from supagent.knowledge import notes as N
    from supagent.security import group_scopes

    with app.test_request_context():
        from flask import g

        n = N.add(sm.find_user(username="alice").id, "Group search check: the settlement file is late on Fridays.",
                  scope="group", group_id=team)
        piece = next(p for p in N.pieces() if p["ref"].startswith(f"note:{n.id}#"))
        assert piece["scope"] == f"g{team}" and piece["user_id"] is None
        g.user = sm.find_user(username="alice")
        assert f"g{team}" in group_scopes()
        g.user = sm.find_user(username="bob")
        assert group_scopes() == []
        db.session.rollback()


def test_a_viewer_writes_for_themselves_only(app, team):
    with app.test_client() as c:
        login(c, "g_viewer")
        assert c.get("/supagent/api/sharing").status_code in (401, 403)      # the page: "for me only"
        r = c.post("/supagent/api/notes", json={"text": "A team note from a viewer", "scope": "team"})
        assert r.status_code == 403
        r = c.post("/supagent/api/notes", json={"text": "My own note, as a viewer", "scope": "user"})
        assert r.status_code == 200 and r.get_json()["note"]["scope"] == "user"
        assert c.post("/supagent/api/memory", json={"text": "Team: durations in minutes", "scope": "team"}).status_code == 403
        assert c.post("/supagent/api/memory", json={"text": "Me: durations in minutes", "scope": "user"}).status_code == 200


def test_a_groups_memory_goes_to_its_members(app, team):
    from superset.extensions import db, security_manager as sm

    from supagent.knowledge.memory import add, memories_for

    with app.app_context():
        alice, bob = sm.find_user(username="alice"), sm.find_user(username="bob")
        m = add(alice.id, "Payments team: amounts in thousands of euros", scope="group", group_id=team,
                approved_by="alice")
        assert m is not None and m.scope == "group" and m.status == "active"
        assert m.id in [x.id for x in memories_for(alice.id, groups=[team])]
        assert m.id not in [x.id for x in memories_for(bob.id, groups=[])]
        db.session.rollback()
