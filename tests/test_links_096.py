"""The links of the System map (0.9.6, the user's request): "part of" is a link like the others (each with a short
explanation and what to do when following it, read from either end, several between two parts); what a value was
part of before becomes links at the upgrade; a link's removal is proposed (by an editor, or by the learning) and
decided by an AI Admin; a merge takes every link of the merged value along."""

from __future__ import annotations

import pytest

from conftest import PASSWORD, login, part_of, parts_of


@pytest.fixture()
def parts(app):
    from superset.extensions import db, security_manager as sm

    from supagent.cli import EDITOR_ROLE, ensure_roles
    from supagent.models import Facet, Link

    with app.app_context():
        ensure_roles(viewer_data=False)
        if sm.find_user(username="l_editor") is None:
            sm.add_user("l_editor", "l_editor", "Test", "l_editor@example.com", [sm.find_role(EDITOR_ROLE)],
                        password=PASSWORD)
        made = {}
        for cat, name in (("application", "PAYMENTS96"), ("application", "LEDGER96"), ("component", "gateway96"),
                          ("component", "kafka96")):
            made[name] = Facet(facet=cat, value=name, status="approved", source="admin")
            db.session.add(made[name])
        db.session.commit()
        ids = {k: v.id for k, v in made.items()}
        db.session.remove()
    yield ids
    with app.app_context():
        refs = [f"facet:{i}" for i in ids.values()]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(list(ids.values()))).delete(synchronize_session=False)
        db.session.commit()


def test_one_kind_of_relation_the_link(app, parts):
    """(the user, 2026-10-06: one type of relation) A link says what it is and what it does, goes one way or both,
    several between two parts; what the learning read ("part of", "runs on") is shown as a link described by it."""
    from superset.extensions import db

    from supagent.knowledge import sysmap

    with app.app_context():
        part_of(parts["gateway96"], parts["PAYMENTS96"])
        a = sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, "sends the payment events to", "admin",
                                    detail="a lag on kafka96 delays the ledger")
        b = sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, "reads its settings from", "admin",
                                    both_ways=True)
        with pytest.raises(ValueError, match="say what the link is"):
            sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, "", "admin")
        db.session.commit()
        assert a["id"] != b["id"] and a["kind"].startswith("link:") and b["both"]          # several, each its own
        mine = [x for x in sysmap.interactions() if parts["gateway96"] in (x["a"], x["b"])]
        said = {x["label"] for x in mine}
        assert said == {"belongs to", "sends the payment events to", "reads its settings from"}   # never "part of"
        m = sysmap.map_data(True)
        assert "inverse" not in m and "interactions" not in m                                # no kinds to choose
        gw = next(v for v in m["values"] if v["id"] == parts["gateway96"])
        assert gw["parents"] == [parts["PAYMENTS96"]]                        # (for the layout and who sees what)
        # turned around, then both ways
        r = sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, None, "admin", link_id=a["id"], reverse=True)
        assert (r["a"], r["b"], r["label"]) == (parts["kafka96"], parts["gateway96"], "sends the payment events to")
        listed = {x["id"]: x for x in sysmap.links_of_value(parts["gateway96"])}
        assert listed[a["id"]]["out"] is False and listed[b["id"]]["both"] and listed[b["id"]]["other"]["value"] == "kafka96"
        assert {x["label"] for x in listed.values()} >= {"belongs to", "reads its settings from"}


def test_the_agent_reads_a_link_by_what_it_says(app, parts):
    from superset.extensions import db

    from supagent.knowledge import brief, sysmap

    with app.app_context():
        sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, "sends the payment events to", "admin",
                                detail="when kafka96 lags, the gateway's events arrive late", both_ways=True)
        db.session.commit()
        brief._CACHE["graph"] = None
        g = brief._graph()
        out = [(k, t, n) for k, t, n in g["out"].get(parts["gateway96"], [])]
        back = [(k, t, n) for k, t, n in g["out"].get(parts["kafka96"], [])]
        assert ("link", parts["kafka96"], "sends the payment events to") in out
        assert ("link", parts["gateway96"], "sends the payment events to") in back              # both ways: both ends
        assert brief.ONE["link"] == "is linked to"


def test_what_was_part_of_becomes_links_at_the_upgrade(app, parts):
    from superset.extensions import db

    from supagent.models import Facet, Link, _parts_as_links

    with app.app_context():
        gw = db.session.get(Facet, parts["gateway96"])
        kafka = db.session.get(Facet, parts["kafka96"])
        gw.parents = [parts["PAYMENTS96"], 99999999]                       # an id that no longer exists: left out
        kafka.suggested = {"parents": [parts["LEDGER96"]], "declined": [parts["PAYMENTS96"]],
                           "from": {str(parts["LEDGER96"]): "jobs: APPLICATION LEDGER96 with NODE kafka96"},
                           "same_as": parts["gateway96"]}
        db.session.commit()
        assert _parts_as_links() == 3
        db.session.commit()
        assert parts_of(gw) == [parts["PAYMENTS96"]]
        assert parts_of(kafka, ("proposed",)) == [parts["LEDGER96"]]
        refused = db.session.query(Link).filter(Link.a_ref == f"facet:{kafka.id}",
                                                Link.b_ref == f"facet:{parts['PAYMENTS96']}").one()
        assert refused.status == "rejected"                                 # not proposed again
        said = db.session.query(Link).filter(Link.a_ref == f"facet:{kafka.id}", Link.status == "proposed").one()
        assert "LEDGER96 with NODE" in said.evidence
        db.session.refresh(kafka)
        assert kafka.suggested == {"same_as": parts["gateway96"]}           # what is not a part stays
        assert gw.parents == [parts["PAYMENTS96"], 99999999]               # the column as it was (an older version)
        assert _parts_as_links() == 0                                      # once
        gw.parents, kafka.suggested = None, None
        db.session.commit()


def test_a_merge_takes_every_link_along(app, parts):
    from superset.extensions import db

    from supagent.knowledge import facets as F, sysmap
    from supagent.models import Facet

    with app.app_context():
        part_of(parts["kafka96"], parts["PAYMENTS96"])
        part_of(parts["gateway96"], parts["PAYMENTS96"])
        sysmap.save_interaction(parts["kafka96"], parts["LEDGER96"], "sends_to", "the events", "admin")
        sysmap.save_interaction(parts["gateway96"], parts["kafka96"], "calls", "", "admin")
        db.session.commit()
        F.merge_value(db.session.get(Facet, parts["kafka96"]), db.session.get(Facet, parts["gateway96"]))
        db.session.commit()
        mine = [(x["kind"], x["a"], x["b"]) for x in sysmap.interactions() if parts["gateway96"] in (x["a"], x["b"])]
        assert sorted(mine) == [("part_of", parts["gateway96"], parts["PAYMENTS96"]),
                                ("sends_to", parts["gateway96"], parts["LEDGER96"])]   # once; no link to itself


def test_a_removal_is_proposed_and_an_admin_decides(app, parts):
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Link

    with app.app_context():
        x = sysmap.save_interaction(parts["gateway96"], parts["kafka96"], "sends_to", "the events", "admin")
        db.session.commit()
    with app.test_client() as c:
        login(c, "l_editor")
        assert c.post("/supagent/dictionary/api/map", json={"remove_interaction": x["id"]}).status_code == 403
        r = c.post("/supagent/dictionary/api/map", json={"propose_removal": {"id": x["id"], "why": "kafka96 is gone"}})
        assert r.status_code == 200 and r.get_json()["proposed"]["drop"] == "kafka96 is gone"
        d = c.get("/supagent/dictionary/api/map").get_json()
        assert next(y for y in d["links"] if y["id"] == x["id"])["drop"] == "kafka96 is gone"   # still drawn
        assert c.post("/supagent/dictionary/api/map", json={"removal": {"id": x["id"], "remove": True}}).status_code == 403
    with app.test_client() as c:
        login(c, "admin")
        rv = c.get("/supagent/admin/api/review").get_json()
        assert any(y["id"] == x["id"] and y["why"] == "kafka96 is gone" for y in rv["removals"])
        assert rv["counts"]["removals"] >= 1
        assert c.post("/supagent/dictionary/api/map", json={"removal": {"id": x["id"], "remove": False}}).get_json()["decided"]
    with app.app_context():
        kept = db.session.get(Link, x["id"])
        assert kept is not None and kept.proposed_drop is None              # kept: the proposal gone
        sysmap.propose_removal(x["id"], "the sentence it was read from is gone", "learning")
    with app.test_client() as c:
        login(c, "admin")
        assert c.post("/supagent/dictionary/api/map", json={"removal": {"id": x["id"], "remove": True}}).get_json()["decided"]
    with app.app_context():
        assert db.session.get(Link, x["id"]) is None


def test_an_edited_description_never_lets_a_new_link_overwrite_it(app, parts):
    """A link drawn as "sends files", described "sends reports" since: drawing "sends files" again makes a second link
    (its kind follows its description); describing it like another link of the same two parts is refused."""
    from superset.extensions import db

    from supagent.knowledge import sysmap

    with app.app_context():
        first = sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, "sends files", "admin")
        sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, "sends reports", "admin", link_id=first["id"])
        again = sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, "sends files", "admin")
        db.session.commit()
        assert again["id"] != first["id"]
        said = sorted(x["label"] for x in sysmap.links_of_value(parts["gateway96"]))
        assert said == ["sends files", "sends reports"]                  # nothing lost
        with pytest.raises(ValueError, match="joins these parts already"):
            sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, "Sends  Files", "admin", link_id=first["id"])


def test_the_investigations_follow_a_link_a_person_drew(app, parts):
    """Drawn from the gateway to kafka: kafka is what the gateway takes in (followed from its start to its end);
    both ways: from either end."""
    from superset.extensions import db

    from supagent.knowledge import brief, sysmap

    with app.app_context():
        x = sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, "takes the events from", "admin")
        db.session.commit()
        brief._CACHE["graph"] = None
        assert [n for n, _c, _f in brief.inputs_of(["gateway96"])] == ["kafka96"]
        assert brief.inputs_of(["kafka96"]) == []                         # one way: not from its end
        sysmap.save_interaction(parts["gateway96"], parts["kafka96"], None, None, "admin", link_id=x["id"], both_ways=True)
        db.session.commit()
        brief._CACHE["graph"] = None
        assert [n for n, _c, _f in brief.inputs_of(["kafka96"])] == ["gateway96"]
