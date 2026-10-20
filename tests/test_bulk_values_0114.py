"""(0.11.4) The user's request: values of the categories changed in bulk from the Categories page (put in a category or
a subcategory, the same link from each to one value), the same description written on many links, and what was
refused before kept out of the way in To review, with a way to add some back.

The traps checked: a value refused before with the same name in the target category (one value of a name in a
category: the move failed on it), a link already there keeps what a person wrote on it, a bulk description changes
nothing but the descriptions, a refused item never counts as waiting, and a refused link comes back only when both
its parts are in use."""

from __future__ import annotations

import pytest

from conftest import login

MAP = "/supagent/dictionary/api/map"
ADMIN = "/supagent/admin/api"


@pytest.fixture()
def cats(ctx, monkeypatch):
    """Two categories of one's own, "exporter" drawn inside "component" (a subcategory)."""
    from supagent import settings

    conf = {"categories.custom": ["exporter", "server"], "categories.inside": {"exporter": "component"}}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    return conf


def _values(*rows):
    from superset.extensions import db

    from supagent.models import Facet

    made = [Facet(facet=c, value=v, status=st, source="admin") for c, v, st in rows]
    db.session.add_all(made)
    db.session.commit()
    return made


def _drop(*ids):
    from sqlalchemy import or_

    from superset.extensions import db

    from supagent.models import Facet, Link, Tag

    refs = [f"facet:{i}" for i in ids]
    db.session.query(Link).filter(or_(Link.a_ref.in_(refs), Link.b_ref.in_(refs))).delete(synchronize_session=False)
    db.session.query(Tag).filter(Tag.facet_id.in_(list(ids))).delete(synchronize_session=False)
    db.session.query(Facet).filter(Facet.id.in_(list(ids))).delete(synchronize_session=False)
    db.session.commit()


def test_values_put_in_a_subcategory_at_once(cats):
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Facet

    a, b, c, p, d, there = _values(("component", "node_exporter", "approved"), ("component", "blackbox", "approved"),
                                   ("component", "snmp", "approved"), ("component", "redis_exp", "proposed"),
                                   ("component", "Cadvisor", "approved"), ("exporter", "cadvisor", "approved"))
    ids = [a.id, b.id, c.id, p.id, d.id, there.id]
    try:
        r = sysmap.move_values([a.id, str(b.id), p.id, d.id, there.id, a.id, "x"], "exporter", "admin")
        assert r["moved"] == 3 and r["there"] == 1 and r["inside"] == "component"     # a proposed value moves too
        assert [(x["value"], "already" in x["why"]) for x in r["skipped"]] == [("Cadvisor", True)]   # said, not merged
        facet = dict(db.session.query(Facet.id, Facet.facet).filter(Facet.id.in_(ids)).all())
        assert facet[a.id] == facet[b.id] == facet[p.id] == "exporter" and facet[c.id] == "component"
        assert facet[d.id] == "component"
        r = sysmap.move_values([a.id, b.id], "component", "admin")              # and back
        assert r["moved"] == 2 and not r["skipped"]
        for bad in (([a.id], "aspect"), ([a.id], "nowhere"), ([], "exporter"), ("1,2", "exporter"),
                    (list(range(1, sysmap.BULK + 2)), "exporter")):
            with pytest.raises(ValueError):
                sysmap.move_values(bad[0], bad[1], "admin")
    finally:
        _drop(*ids)


def test_a_value_refused_before_with_the_same_name_takes_no_place(cats):
    """The table holds one value of a name in a category: a refused one there made the move fail at the save (an
    error 500 on the map's drag, the same in bulk). It goes now, what was refused with it kept on the moved value."""
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Facet, Link, Tag

    a, old, other, b, old_b = _values(("component", "node_exporter", "approved"),
                                      ("exporter", "node_exporter", "rejected"), ("server", "srv-01", "approved"),
                                      ("component", "pushgateway", "approved"), ("exporter", "pushgateway", "rejected"))
    ids = [a.id, old.id, other.id, b.id, old_b.id]
    db.session.add_all([Tag(ref="dataset:1", facet_id=old.id, status="rejected"),
                        Link(a_ref=f"facet:{old.id}", b_ref=f"facet:{other.id}", kind="runs_on", status="rejected")])
    db.session.commit()
    try:
        r = sysmap.move_value(a.id, "exporter", "admin")                         # the map's drag
        assert r["moved"] and db.session.get(Facet, old.id) is None
        assert db.session.query(Tag.status).filter(Tag.facet_id == a.id, Tag.ref == "dataset:1").scalar() == "rejected"
        refused = db.session.query(Link).filter(Link.a_ref == f"facet:{a.id}", Link.b_ref == f"facet:{other.id}").one()
        assert refused.status == "rejected"                                      # still not proposed again
        r = sysmap.move_values([b.id], "exporter", "admin")                      # the same in bulk
        assert r["moved"] == 1 and db.session.get(Facet, old_b.id) is None
        assert db.session.get(Facet, b.id).facet == "exporter"
    finally:
        _drop(*ids)


def test_one_link_from_many_values_to_one(cats):
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Link

    a, b, c, p, target = _values(("server", "srv-01", "approved"), ("server", "srv-02", "approved"),
                                 ("server", "srv-03", "approved"), ("server", "srv-04", "proposed"),
                                 ("component", "node_exporter", "approved"))
    ids = [a.id, b.id, c.id, p.id, target.id]
    kind = sysmap.worded("is scraped by")
    mine = Link(a_ref=f"facet:{b.id}", b_ref=f"facet:{target.id}", kind=kind, status="approved", source="admin",
                note="Is scraped by", detail="what a person wrote", explained_by="carol")
    gone = Link(a_ref=f"facet:{c.id}", b_ref=f"facet:{target.id}", kind=kind, status="rejected", source="llm")
    db.session.add_all([mine, gone])
    db.session.commit()
    try:
        r = sysmap.link_many([a.id, b.id, c.id, p.id, target.id], target.id, "  is scraped   by ",
                             "check its /metrics", "out", "admin")
        assert r["made"] == 2 and r["had"] == 1 and len(r["ids"]) == 2
        why = {x["value"]: x["why"] for x in r["skipped"]}
        assert "approve it first" in why["srv-04"] and "itself" in why["node_exporter"]
        mine = db.session.get(Link, mine.id)
        assert (mine.note, mine.detail, mine.explained_by) == ("Is scraped by", "what a person wrote", "carol")
        made = db.session.query(Link).filter(Link.id.in_(r["ids"])).all()
        assert {x.a_ref for x in made} == {f"facet:{a.id}", f"facet:{c.id}"}
        assert all(x.status == "approved" and x.note == "is scraped by" and x.detail == "check its /metrics"
                   and x.b_ref == f"facet:{target.id}" and not x.both_ways for x in made)
        assert gone.id in r["ids"]                                               # refused before: a person's now
        r = sysmap.link_many([a.id], target.id, "is scraped by", "", "both", "admin")
        mine_a = next(x for x in made if x.a_ref == f"facet:{a.id}")
        assert r["made"] == 0 and r["had"] == 1 and db.session.get(Link, mine_a.id).both_ways is True
        r = sysmap.link_many([a.id], target.id, "is scraped by", "", "in", "admin")   # both ways already: had
        assert r["made"] == 0 and r["had"] == 1
        r = sysmap.link_many([a.id], target.id, "sends alerts to", "", "in", "admin")   # from it to each
        x = db.session.get(Link, r["ids"][0])
        assert (x.a_ref, x.b_ref) == (f"facet:{target.id}", f"facet:{a.id}")
        for bad in (([a.id], target.id, "", "out"), ([a.id], target.id, "x", "sideways"), ([a.id], p.id, "x", "out")):
            with pytest.raises(ValueError):
                sysmap.link_many(bad[0], bad[1], bad[2], "", bad[3], "admin")
        out = sysmap.remove_links(r["ids"] + [mine.id])                          # taken back (an admin's)
        assert out["removed"] == 2 and db.session.get(Link, mine.id) is None
    finally:
        _drop(*ids)


def test_the_same_description_on_many_links(cats):
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Link

    a, b, target = _values(("server", "srv-11", "approved"), ("server", "srv-12", "approved"),
                           ("component", "node_exporter_2", "approved"))
    ids = [a.id, b.id, target.id]
    one = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{target.id}", kind="link:abc", status="approved", note="old",
               detail="keep me", source="llm", both_ways=False)
    two = Link(a_ref=f"facet:{target.id}", b_ref=f"facet:{b.id}", kind="depends_on", status="proposed", source="llm")
    item = Link(a_ref="dataset:7", b_ref=f"facet:{b.id}", kind="about", status="approved", note="untouched")
    db.session.add_all([one, two, item])
    db.session.commit()
    try:
        r = sysmap.describe_links([one.id, two.id, item.id], "is scraped by", "", "admin")
        assert r["described"] == 2 and [x["id"] for x in r["skipped"]] == [item.id]
        one, two, item = (db.session.get(Link, x.id) for x in (one, two, item))
        assert (one.note, one.detail, one.kind, one.status, one.a_ref, one.b_ref) == (
            "is scraped by", "keep me", "link:abc", "approved", f"facet:{a.id}", f"facet:{target.id}")
        assert (two.note, two.status, two.kind, two.a_ref) == ("is scraped by", "proposed", "depends_on", f"facet:{target.id}")
        assert one.explained_by == "admin" and item.note == "untouched"
        sysmap.describe_links([one.id], "", "check the exporter's port", "admin")
        assert (db.session.get(Link, one.id).note, db.session.get(Link, one.id).detail) == (
            "is scraped by", "check the exporter's port")
        with pytest.raises(ValueError):
            sysmap.describe_links([one.id], " ", "", "admin")
    finally:
        db.session.delete(db.session.get(Link, item.id))
        db.session.commit()
        _drop(*ids)


def test_the_bulk_actions_for_who_edits_the_map(app):
    from superset.extensions import db

    from supagent.models import Facet, Link

    with app.app_context():
        from supagent import settings

        settings.set_value("categories.custom", ["exporter"], by="admin")
        made = [Facet(facet="component", value=v, status="approved", source="admin")
                for v in ("bulk-a", "bulk-b", "bulk-target")]
        db.session.add_all(made)
        db.session.commit()
        a, b, t = (f.id for f in made)
        db.session.remove()
    try:
        c = app.test_client()
        login(c, "admin")
        r = c.post(MAP, json={"move_values": {"ids": [a, b], "facet": "exporter"}})
        assert r.status_code == 200 and r.get_json()["moved"] == 2, r.get_data(as_text=True)
        r = c.post(MAP, json={"link_many": {"ids": [a, b], "to": t, "note": "is scraped by", "way": "out"}})
        assert r.status_code == 200 and r.get_json()["made"] == 2, r.get_data(as_text=True)
        links = r.get_json()["ids"]
        r = c.post(MAP, json={"describe_links": {"ids": links, "detail": "check its port"}})
        assert r.status_code == 200 and r.get_json()["described"] == 2
        r = c.post(MAP, json={"link_many": {"ids": [a], "to": t, "note": ""}})
        assert r.status_code == 400 and "say what the link is" in r.get_json()["error"]
        viewer = app.test_client()
        login(viewer, "alice")
        for body in ({"move_values": {"ids": [a], "facet": "component"}}, {"remove_links": {"ids": links}},
                     {"describe_links": {"ids": links, "note": "x"}}):
            assert viewer.post(MAP, json=body).status_code == 403
        r = c.post(MAP, json={"remove_links": {"ids": links}})
        assert r.status_code == 200 and r.get_json()["removed"] == 2
    finally:
        with app.app_context():
            from supagent import settings

            db.session.query(Link).filter(Link.b_ref == f"facet:{t}").delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_([a, b, t])).delete(synchronize_session=False)
            db.session.commit()
            settings.set_value("categories.custom", None, by="admin")
            db.session.remove()


def test_what_was_refused_is_listed_apart_and_comes_back(app):
    from superset.extensions import db

    from supagent.models import Facet, Link

    import datetime as dt

    with app.app_context():
        rows = [Facet(facet="component", value=v, status=st, source="llm", reviewed_by="admin",
                      reviewed_at=dt.datetime.utcnow())
                for v, st in (("refused-a", "rejected"), ("refused-b", "rejected"), ("in-use-c", "approved"),
                              ("Refused-C", "rejected"), ("in-use-d", "approved"))]
        db.session.add_all(rows)
        db.session.commit()
        ra, rb, c_, rc, d_ = (f.id for f in rows)
        l_ok = Link(a_ref=f"facet:{c_}", b_ref=f"facet:{d_}", kind="depends_on", status="rejected", source="llm")
        l_end = Link(a_ref=f"facet:{rb}", b_ref=f"facet:{d_}", kind="depends_on", status="rejected", source="llm")
        db.session.add_all([l_ok, l_end])
        db.session.commit()
        lok, lend = l_ok.id, l_end.id
        db.session.query(Facet).filter(Facet.id == c_).update({"value": "refused-c"})   # a value in use, same name
        db.session.commit()
        db.session.remove()
    try:
        c = app.test_client()
        login(c, "admin")
        before = c.get(f"{ADMIN}/review").get_json()["waiting"]
        d = c.get(f"{ADMIN}/review/refused?q=refused").get_json()
        vals = {v["value"]: v for v in d["values"]}
        assert {"refused-a", "refused-b", "Refused-C"} <= set(vals)
        assert vals["Refused-C"]["in_use"]["id"] == c_ and vals["refused-a"]["in_use"] is None
        links = {x["id"]: x for x in c.get(f"{ADMIN}/review/refused?what=links").get_json()["links"]}
        assert links[lok]["why_not"] == "" and "refused-b" in links[lend]["why_not"]
        assert "values" not in c.get(f"{ADMIN}/review/refused?what=links").get_json()
        assert c.get(f"{ADMIN}/review").get_json()["waiting"] == before          # never counted as waiting
        # added again: a link only with both its parts in use, a value only with no other of its name in use
        assert c.post(f"{ADMIN}/links/{lend}", json={"status": "approved"}).status_code == 409
        assert c.post(f"{ADMIN}/facets/{rc}", json={"status": "approved"}).status_code == 409
        r = c.post(f"{ADMIN}/links/{lok}", json={"status": "proposed"})
        assert r.status_code == 200 and r.get_json()["status"] == "proposed"     # back in To review
        assert c.post(f"{ADMIN}/facets/{ra}", json={"status": "proposed"}).get_json()["status"] == "proposed"
        assert c.post(f"{ADMIN}/facets/{rb}", json={"status": "approved"}).get_json()["status"] == "approved"
        assert c.post(f"{ADMIN}/links/{lend}", json={"status": "approved"}).status_code == 200
        after = c.get(f"{ADMIN}/review").get_json()
        assert after["counts"]["values"] >= 1 and after["counts"]["links"] >= 1
        assert c.post(f"{ADMIN}/links/{lend}", json={"status": "proposed"}).get_json()["status"] == "approved"
        viewer = app.test_client()
        login(viewer, "alice")
        assert viewer.get(f"{ADMIN}/review/refused").status_code in (401, 403)
    finally:
        with app.app_context():
            db.session.query(Link).filter(Link.id.in_([lok, lend])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_([ra, rb, c_, rc, d_])).delete(synchronize_session=False)
            db.session.commit()
            db.session.remove()
