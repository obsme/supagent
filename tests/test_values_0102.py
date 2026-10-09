"""(0.10.2) A question that names a value of the data (a server, a status) gets first which metrics' labels and
indices' fields hold it, and the category value named so: a metric's piece listed a label's values only when it had
a few, a server among hundreds was never found by its name. Only the databases the user may query; a value half the
data holds says nothing; a number alone is no value."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (jobs: NODE srv-1..4; metrics: node_cpu_seconds_total node srv-1,2,3,9)


def test_a_value_names_the_labels_and_fields_that_hold_it(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import valueindex as V
    from supagent.knowledge.search import search
    from supagent.models import Facet
    from supagent.security import acting_as

    f = Facet(facet="server", value="srv-3", status="approved", source="data")
    db.session.add(f)
    db.session.commit()
    V._CACHE.update(stamp=None, values=None, parents=None)
    try:
        with acting_as("admin"):
            got = search("how busy was SRV-3 yesterday", k=6)
            first = got[0]
            assert first["kind"] == "value" and first["title"] == "Where the value SRV-3 is"
            assert "label node of metric node_cpu_seconds_total (metrics)" in first["text"]
            assert "field NODE of index jobs (jobs)" in first["text"]
            assert "In the categories: server srv-3." in first["text"]
            assert not any(p["kind"] == "value" for p in search("the jobs of last week", k=6))
            assert not any(p["kind"] == "value" for p in search("node 2", k=6))     # 2: a number alone
        with acting_as("alice"):                                                      # alice: the jobs database only
            text = search("srv-9 and srv-3", k=6)[0]["text"]
            assert "node_cpu_seconds_total" not in text and "field NODE of index jobs" in text
    finally:
        db.session.delete(f)
        db.session.commit()


def test_a_value_most_of_the_data_holds_says_nothing(world, monkeypatch):  # noqa: F811
    from supagent.knowledge import valueindex as V
    from supagent.security import acting_as

    monkeypatch.setattr(V, "COMMON", 1)                  # srv-1 is held by two names: too common here
    V._CACHE.update(stamp=None, values=None, parents=None)
    with acting_as("admin"):
        assert V.where("srv-1") == [] and V.where("srv-9")[0]["ref"] == "value:srv-9"


def test_a_label_of_many_metrics_is_one_entry(world):  # noqa: F811
    """A label kept once per metric (thousands of metrics have "instance"): one entry per (name, value), the metrics
    named apart, a few of them said."""
    from superset.extensions import db

    from supagent.knowledge import valueindex as V
    from supagent.knowledge.store import upsert
    from supagent.security import acting_as

    for i in range(5):
        upsert(world["run"], world["s_prom"], "metric", "", f"node_extra_{i}", {"metric_type": "gauge"})
        upsert(world["run"], world["s_prom"], "label", f"node_extra_{i}", "node",
               {"data_type": "string", "stats": {"cardinality": 1, "values": ["srv-9"]}})
    db.session.commit()
    V._CACHE.update(stamp=None, values=None, parents=None)
    values, parents = V._index()
    assert len(values["srv-9"]) == 1                                  # one label name, one source
    with acting_as("admin"):
        text = V.where("srv-9")[0]["text"]
    assert "label node of metrics node_cpu_seconds_total, node_extra_0, node_extra_1 and 3 more (metrics)" in text


def test_a_value_written_otherwise_and_a_category_value_by_its_other_name(world):  # noqa: F811
    """"web shop", "WEB_SHOP" find the data's "Web-Shop"; a category value named by one of its other names gets where
    it is in the data, written as the data writes it; a value of the categories the data does not hold, nothing."""
    from superset.extensions import db

    from supagent.knowledge import valueindex as V
    from supagent.knowledge.search import search
    from supagent.knowledge.store import upsert
    from supagent.models import Facet
    from supagent.security import acting_as

    upsert(world["run"], world["s_prom"], "metric", "", "http_requests_total", {"metric_type": "counter"})
    upsert(world["run"], world["s_prom"], "label", "http_requests_total", "service",
           {"data_type": "string", "stats": {"cardinality": 2, "values": ["Web-Shop", "ledger-api"]}})
    f = Facet(facet="application", value="ledger-api", synonyms=["general ledger"], status="approved", source="admin")
    g = Facet(facet="application", value="Quarry", status="approved", source="admin")
    db.session.add_all([f, g])
    db.session.commit()
    V._CACHE.update(stamp=None, values=None, parents=None)
    try:
        with acting_as("admin"):
            for q in ("errors of the web shop today", "WEB_SHOP errors"):
                p = V.where(q)
                assert p and "label service of metric http_requests_total (metrics) written “Web-Shop”" in p[0]["text"], (q, p)
            p = V.where("latency of the general ledger")
            assert p[0]["title"] == "Where ledger-api (application) is in the data", p
            assert "label service of metric http_requests_total (metrics) written “ledger-api”" in p[0]["text"]
            assert V.where("what does Quarry do") == []                    # not in the data: nothing
            got = search("errors of the web shop", k=4)
            assert got[0]["kind"] == "value" and len([x for x in got if x["kind"] != "value"]) <= 4
            pl = V.places(["ledger-api", "general ledger"])
            assert pl == [{"kind": "label", "name": "service", "database": "metrics", "written": "ledger-api",
                           "of": ["http_requests_total"], "count": 1}]
        with acting_as("alice"):                                          # the jobs database only
            assert V.places(["ledger-api"]) == [] and V.where("web shop") == []
    finally:
        db.session.delete(f)
        db.session.delete(g)
        db.session.commit()


def test_a_part_of_the_map_says_where_it_is_in_the_data(world):  # noqa: F811
    """The Categories page's links of a part (GET map/links?id=) say where it is in the data the user may query."""
    from superset.extensions import db

    from conftest import login
    from supagent.knowledge import valueindex as V
    from supagent.models import Facet

    f = Facet(facet="server", value="SRV-3", synonyms=["third node"], status="approved", source="data")
    db.session.add(f)
    db.session.commit()
    V._CACHE.update(stamp=None, values=None, parents=None)
    try:
        from flask import current_app

        c = current_app.test_client()
        login(c, "admin")
        r = c.get(f"/supagent/dictionary/api/map/links?id={f.id}")
        d = r.get_json()
        assert r.status_code == 200 and "data" in d, (r.status_code, r.get_data(as_text=True)[:300])
        got = {(p["kind"], p["name"], p["written"]) for p in d["data"]}
        assert got == {("label", "node", "srv-3"), ("field", "NODE", "srv-3")}, d["data"]
        from flask import g

        for k in ("_login_user", "user"):                                  # (the test's context holds g open)
            g.pop(k, None)
        c = current_app.test_client()
        login(c, "alice")                                                  # the jobs database only
        d = c.get(f"/supagent/dictionary/api/map/links?id={f.id}").get_json()
        assert [(p["kind"], p["name"]) for p in d.get("data") or []] == [("field", "NODE")], d
    finally:
        db.session.delete(f)
        db.session.commit()
