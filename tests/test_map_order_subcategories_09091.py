"""(0.10.9.1) The System map edited by hand: a value's box moves up and down its column only, the order a person
gives a list is kept for everyone (layout "order"); a subcategory made at once ("+" on a category's name) and values
dropped into it (move_value: never merged away, a name already there is said); the learning does not propose again,
in the category above, a value the data names that a person put in a subcategory."""

from __future__ import annotations

import os

from test_knowledge import world  # noqa: F401


def test_the_order_given_by_hand_is_kept_and_checked(ctx):
    from supagent.knowledge import sysmap

    out = sysmap.save_layout({"order": {"server": [3, "1", 2, 3, "x", -4], "in:12": [], "": [5], "k" * 90: [7]},
                              "positions": {"9": [10, 20]}}, "admin")
    assert out["order"]["server"] == [3, 1, 2]                    # ids only, once each
    assert "in:12" not in out["order"] and "" not in out["order"]
    assert out["order"]["k" * 64] == [7]                          # a list's name: 64 characters at most
    assert sysmap.layout()["order"] == out["order"]
    many = sysmap.save_layout({"order": {f"in:{i}": [i] for i in range(sysmap.ORDER_SCOPES + 20)}}, "admin")
    assert len(many["order"]) == sysmap.ORDER_SCOPES
    sysmap.save_layout({}, "admin")


def test_a_value_dropped_into_a_subcategory_and_back(ctx, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import sysmap
    from supagent.models import Facet

    conf = {"categories.custom": ["server", "db server"], "categories.inside": {"db server": "server"}}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    a = Facet(facet="server", value="nodeq-01", status="approved", source="admin", synonyms=["nq1"])
    b = Facet(facet="db server", value="NQ1", status="approved", source="admin")
    c = Facet(facet="server", value="nodeq-02", status="approved", source="admin")
    p = Facet(facet="server", value="nodeq-03", status="proposed", source="data")
    db.session.add_all([a, b, c, p])
    db.session.commit()
    try:
        r = sysmap.move_value(c.id, "db server", "admin")
        assert r["moved"] and r["from"] == "server" and r["inside"] == "server"
        assert db.session.get(Facet, c.id).facet == "db server"
        r = sysmap.move_value(c.id, "server", "admin")                       # back on its category's name
        assert r["moved"] and db.session.get(Facet, c.id).facet == "server"
        try:                                                                  # a value of that name there already:
            sysmap.move_value(a.id, "db server", "admin")                     # said, both kept
            raise AssertionError("moved over a value of the same name")
        except ValueError as ex:
            assert "NQ1" in str(ex) and "merge" in str(ex)
        assert db.session.get(Facet, a.id).facet == "server" and db.session.get(Facet, b.id) is not None
        for bad in ((p.id, "db server"), (c.id, "aspect"), (c.id, "nowhere")):
            try:
                sysmap.move_value(bad[0], bad[1], "admin")
                raise AssertionError(f"moved {bad}")
            except ValueError:
                pass
    finally:
        for f in (a, b, c, p):
            db.session.delete(db.session.get(Facet, f.id))
        db.session.commit()


def test_the_map_moves_a_value_for_who_edits_it(app, monkeypatch):
    from superset.extensions import db

    from conftest import login
    from supagent.models import Facet

    with app.app_context():
        from supagent import settings

        settings.set_value("categories.custom", ["server", "db server"], by="admin")
        settings.set_value("categories.inside", {"db server": "server"}, by="admin")
        f = Facet(facet="server", value="nodeq-07", status="approved", source="admin")
        db.session.add(f)
        db.session.commit()
        fid = f.id
        db.session.remove()
    try:
        c = app.test_client()
        login(c, "admin")
        r = c.post("/supagent/dictionary/api/map", json={"move_value": {"id": fid, "facet": "db server"}})
        assert r.status_code == 200 and r.get_json()["facet"] == "db server", r.get_data(as_text=True)
        r = c.post("/supagent/dictionary/api/map", json={"layout": {"order": {"server": [fid]}}})
        assert r.status_code == 200 and r.get_json()["layout"]["order"] == {"server": [fid]}
        c2 = app.test_client()
        login(c2, "alice")                                                   # a viewer: the map is read only
        assert c2.post("/supagent/dictionary/api/map",
                       json={"move_value": {"id": fid, "facet": "server"}}).status_code == 403
    finally:
        with app.app_context():
            from supagent import settings
            from supagent.knowledge import sysmap

            db.session.delete(db.session.get(Facet, fid))
            db.session.commit()
            sysmap.save_layout({}, "admin")
            settings.set_value("categories.inside", None, by="admin")
            settings.set_value("categories.custom", None, by="admin")
            db.session.remove()


def test_the_learning_does_not_propose_again_a_value_put_in_a_subcategory(world, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import facets as F, sysmap
    from supagent.models import Facet, KObject, Source

    conf = {"categories.custom": ["server", "db server"], "categories.inside": {"db server": "server"},
            "categories.fields": {"server": r"^(node|host)$"}}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    src = db.session.query(Source).first()
    idx = KObject(source_id=src.id, kind="index", name="ops-tasks", parent="")
    fld = KObject(source_id=src.id, kind="field", name="NODE", parent="ops-tasks",
                  stats={"values": ["srvq-01", "srvq-02", "srvq-03"]})
    db.session.add_all([idx, fld])
    db.session.commit()
    before = {i for (i,) in db.session.query(Facet.id)}
    try:
        F.seed()
        made = {f.value: f for f in db.session.query(Facet).filter(Facet.value.in_(["srvq-01", "srvq-02", "srvq-03"]))}
        assert set(made) == {"srvq-01", "srvq-02", "srvq-03"} and made["srvq-02"].facet == "server"
        made["srvq-02"].status = "approved"
        db.session.commit()
        sysmap.move_value(made["srvq-02"].id, "db server", "admin")           # a person puts it in the subcategory
        again = F.seed()
        assert again["proposed"] == 0
        rows = db.session.query(Facet).filter(Facet.value == "srvq-02").all()
        assert [(f.facet, f.status) for f in rows] == [("db server", "approved")]
        assert any("field NODE of ops-tasks" in o for o in rows[0].origins or [])   # where the data names it, kept
    finally:                                       # every value the learning made here (the world's fields too)
        db.session.query(Facet).filter(Facet.id.notin_(before or {-1})).delete(synchronize_session=False)
        db.session.delete(fld)
        db.session.delete(idx)
        db.session.commit()


def test_the_map_page_moves_boxes_up_and_down_only():
    """The page script: a value's box is dragged on y only and dropped in its list, on a subcategory or back; the
    boxes are no longer placed anywhere (layout positions are not drawn); "+" on a category's name in Edit."""
    import supagent

    js = open(os.path.join(os.path.dirname(supagent.__file__), "static", "supagent", "sysmap.js"), encoding="utf-8").read()
    drag = js[js.index("  function dragBox(g, n) {"):js.index("  /* where a dragged box would go")]
    assert "n.x =" not in drag and "n.y = Math.round(Math.max(start.top, Math.min(start.bottom" in drag
    assert "st.positions[" not in js.replace("st.positions = lay.positions", "")
    assert "move_value: { id: n.id, facet: facet }" in js and "order: st.order" in js
    assert "map-addsub" in js and "newSubcategory(h.cat)" in js and "add_category: { name: name.value, inside: parent }" in js
    sig = js[js.index("  function signature(d)"):js.index("  function setState(")]
    assert "d.layout.order" in sig and "d.layout.positions" not in sig      # another admin's order is seen
