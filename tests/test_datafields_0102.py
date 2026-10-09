"""(0.10.2) Where a category is in the data, proposed from its values: a label or a field holding several values of a
category, not read for it yet, proposed in To review; read (categories.fields), the agent knows where the category
is and the learning reads its other values; set aside, not proposed again. A label holding a few of its many values
is not the category's."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (jobs: NODE srv-1..4; metrics: node_cpu_seconds_total node srv-1,2,3,9)


def test_a_label_holding_a_category_is_proposed_read_and_set_aside(world):  # noqa: F811
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import datafields as D, valueindex as V
    from supagent.knowledge.facets import editable, field_rules
    from supagent.models import Facet, Meta
    from supagent.security import acting_as

    made = [Facet(facet="server", value=f"srv-{i}", status="approved", source="admin") for i in (1, 2, 3)]
    db.session.add_all(made)
    db.session.commit()
    V._CACHE.update(stamp=None, values=None, parents=None)
    before = settings.get("categories.fields")
    try:
        with acting_as("admin"):
            ps = D.proposals()
            assert [(p["category"], p["name"].lower(), p["held"], p["of"]) for p in ps] == [("server", "node", 3, 3)], ps
            p = ps[0]
            assert p["other_values"] == ["srv-4", "srv-9"] and len(p["where"]) == 2      # the label and the field
            assert "label node of 1 metric such as node_cpu_seconds_total (metrics)" in p["why"]
            assert "field NODE of 1 index such as jobs (jobs)" in p["why"]
            r = D.decide("server", p["name"], True, "admin")
            assert "server" in editable() and any(c == "server" and rx.match("NODE") for c, rx in field_rules())
            assert r["read"] and D.proposals() == []                                     # read for it now
            settings.set_value("categories.fields", before, by="admin")
            D.decide("server", p["name"], False, "admin")
            assert D.proposals() == []                                                   # set aside
        with acting_as("alice"):                                                         # the jobs database only
            db.session.query(Meta).filter(Meta.key == D.DISMISSED).delete(synchronize_session=False)
            db.session.commit()
            ps = D.proposals()
            assert len(ps) == 1 and ps[0]["where"] == ["field NODE of 1 index such as jobs (jobs)"], ps
    finally:
        settings.set_value("categories.fields", before, by="admin")
        db.session.query(Meta).filter(Meta.key == D.DISMISSED).delete(synchronize_session=False)
        for f in made:
            db.session.delete(f)
        db.session.commit()


def test_a_few_of_many_values_is_not_the_category(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import datafields as D, valueindex as V
    from supagent.knowledge.store import upsert
    from supagent.models import Facet
    from supagent.security import acting_as

    upsert(world["run"], world["s_prom"], "metric", "", "probe_success", {"metric_type": "gauge"})
    upsert(world["run"], world["s_prom"], "label", "probe_success", "target",
           {"data_type": "string", "stats": {"values": ["alpha-app", "beta-app", "gamma-app"] +
                                                      [f"host-{i:03d}" for i in range(60)]}})
    made = [Facet(facet="application", value=v, status="approved", source="admin")
            for v in ("alpha-app", "beta-app", "gamma-app")]
    db.session.add_all(made)
    db.session.commit()
    V._CACHE.update(stamp=None, values=None, parents=None)
    try:
        with acting_as("admin"):
            assert [p for p in D.proposals() if p["category"] == "application"] == []   # 3 of 63: not its values
    finally:
        for f in made:
            db.session.delete(f)
        db.session.commit()


def test_to_review_lists_where_the_categories_are_in_the_data(world):  # noqa: F811
    from flask import current_app
    from superset.extensions import db

    from conftest import login
    from supagent import settings
    from supagent.knowledge import datafields as D, valueindex as V
    from supagent.models import Facet, Meta

    made = [Facet(facet="server", value=f"srv-{i}", status="approved", source="admin") for i in (1, 2, 3)]
    db.session.add_all(made)
    db.session.commit()
    V._CACHE.update(stamp=None, values=None, parents=None)
    before = settings.get("categories.fields")
    try:
        c = current_app.test_client()
        login(c, "admin")
        d = c.get("/supagent/admin/api/review").get_json()
        assert d["counts"]["fields"] == 1 and d["fields"][0]["subject"].startswith("server")
        r = c.post("/supagent/admin/api/fields/decide", json={"category": "server", "name": d["fields"][0]["name"],
                                                                "read": True})
        assert r.status_code == 200 and r.get_json()["read"], r.get_data(as_text=True)
        d = c.get("/supagent/admin/api/review").get_json()
        assert d["counts"]["fields"] == 0
    finally:
        settings.set_value("categories.fields", before, by="admin")
        db.session.query(Meta).filter(Meta.key == D.DISMISSED).delete(synchronize_session=False)
        for f in made:
            db.session.delete(f)
        db.session.commit()
