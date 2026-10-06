"""Links read from the data (0.9.6, the user's request): a metric's series carrying a server label with a component
label, or a tenant with its servers, link them at once (with where it was seen); an index's documents propose them;
a data link the data stops showing is proposed for removal, never removed alone."""

from __future__ import annotations

import datetime as dt

import pytest


@pytest.fixture()
def cats(app, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.models import Facet, KObject, Link, Source

    conf = {"categories.custom": ["server", "disk"],
            "categories.fields": {"application": r"^(tenant_name|application)$", "component": r"^(component|job)$",
                                  "server": r"^(instance|node)$", "disk": r"^(device)$"},
            "categories.label_links": True, "categories.data_link_days": 21, "categories.relation_min_docs": 5}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    with app.app_context():
        made = {}
        for cat, name in (("application", "PAYMENTSDL"), ("component", "kafkadl"), ("component", "apidl"),
                          ("server", "srvdl-1"), ("server", "srvdl-2"), ("disk", "sdadl")):
            made[name] = Facet(facet=cat, value=name, status="approved", source="data")
            db.session.add(made[name])
        src = db.session.query(Source).filter_by(database_name="datalinks test").first()
        if src is None:
            src = Source(database_id=987096, database_name="datalinks test", backend="promagg")
            db.session.add(src)
        db.session.commit()
        ids = {k: v.id for k, v in made.items()}
        yield {"ids": ids, "source": src.id, "conf": conf}
    with app.app_context():
        refs = [f"facet:{i}" for i in ids.values()]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(KObject).filter(KObject.name.in_(["dl_metric_total", "dl-jobs"])).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(list(ids.values()))).delete(synchronize_session=False)
        db.session.commit()


def test_the_kind_follows_the_categories(app, cats):
    from supagent.knowledge.datalinks import kind_of

    with app.app_context():
        assert kind_of("component", "server") == ("runs_on", "component", "server")       # a component on a server
        assert kind_of("server", "component") == ("runs_on", "component", "server")
        assert kind_of("disk", "server") == ("part_of", "disk", "server")                 # a disk of a server
        assert kind_of("application", "server") == ("part_of", "server", "application")   # a server of a tenant
        assert kind_of("application", "component") == ("part_of", "component", "application")


def test_a_metrics_labels_link_the_server_its_components_and_its_tenant(app, cats):
    from superset.extensions import db

    from supagent.knowledge import datalinks, sysmap
    from supagent.models import KObject

    series = [{"__name__": "dl_metric_total", "instance": "srvdl-1", "component": "kafkadl", "tenant_name": "PAYMENTSDL"},
              {"__name__": "dl_metric_total", "instance": "srvdl-1", "component": "apidl", "tenant_name": "PAYMENTSDL"},
              {"__name__": "dl_metric_total", "instance": "srvdl-2", "component": "kafkadl", "tenant_name": "PAYMENTSDL",
               "device": "sdadl"}]
    with app.app_context():
        pairs = datalinks.label_pairs(series)
        got = {(p["parent"][1], p["child"][1]) for p in pairs}
        assert ("tenant_name", "component") in got and ("component", "instance") in got
        m = KObject(source_id=cats["source"], kind="metric", name="dl_metric_total", parent="",
                    stats={"category_pairs": [{**p, "at": "2026-10-05T10:00:00"} for p in pairs]})
        db.session.add(m)
        db.session.commit()
        out = datalinks.apply()
        db.session.commit()
        assert out["linked"] >= 6
        ids = cats["ids"]
        links = {(x["a"], x["kind"], x["b"]) for x in sysmap.interactions()}
        assert (ids["kafkadl"], "runs_on", ids["srvdl-1"]) in links and (ids["apidl"], "runs_on", ids["srvdl-1"]) in links
        assert (ids["kafkadl"], "runs_on", ids["srvdl-2"]) in links
        assert (ids["srvdl-1"], "part_of", ids["PAYMENTSDL"]) in links and (ids["sdadl"], "part_of", ids["srvdl-2"]) in links
        kafka_on = next(x for x in sysmap.interactions() if (x["a"], x["b"]) == (ids["kafkadl"], ids["srvdl-1"]))
        assert kafka_on["source"] == "data" and "instance srv-1" in kafka_on["evidence"].replace("component kafka with ", "") \
            or "srvdl-1" in kafka_on["evidence"]
        again = datalinks.apply()                                  # seen again: nothing new
        assert again["linked"] == 0 and again["seen"] >= 6


def test_off_they_wait_and_an_index_proposes(app, cats):
    from superset.extensions import db

    from supagent.knowledge import datalinks
    from supagent.models import KObject, Link

    with app.app_context():
        cats["conf"]["categories.label_links"] = False
        pairs = datalinks.label_pairs([{"instance": "srvdl-1", "component": "kafkadl"}])
        db.session.add(KObject(source_id=cats["source"], kind="metric", name="dl_metric_total", parent="",
                               stats={"category_pairs": pairs}))
        db.session.add(KObject(source_id=cats["source"], kind="index", name="dl-jobs", parent="", stats={
            "category_pairs": [{"parent": ["application", "APPLICATION"], "child": ["component", "JOB"],
                                "pairs": [["PAYMENTSDL", "apidl", 40], ["PAYMENTSDL", "kafkadl", 2]]}]}))
        db.session.commit()
        out = datalinks.apply()
        db.session.commit()
        ids = cats["ids"]
        rows = {(x.a_ref, x.kind, x.b_ref): x.status for x in db.session.query(Link).filter(Link.source == "data")}
        assert rows[(f"facet:{ids['kafkadl']}", "runs_on", f"facet:{ids['srvdl-1']}")] == "proposed"
        assert rows[(f"facet:{ids['apidl']}", "part_of", f"facet:{ids['PAYMENTSDL']}")] == "proposed"
        assert (f"facet:{ids['kafkadl']}", "part_of", f"facet:{ids['PAYMENTSDL']}") not in rows    # 2 documents: < 5
        assert out["proposed"] == 2 and out["linked"] == 0


def test_a_data_link_not_seen_for_long_is_proposed_for_removal(app, cats):
    from superset.extensions import db

    from supagent.knowledge import datalinks
    from supagent.models import Link

    with app.app_context():
        ids = cats["ids"]
        old = Link(a_ref=f"facet:{ids['apidl']}", b_ref=f"facet:{ids['srvdl-2']}", kind="runs_on", status="approved",
                   source="data", evidence="dl_metric_total: instance srvdl-2 with component apidl in 1 series",
                   seen_at=dt.datetime.utcnow() - dt.timedelta(days=40))
        mine = Link(a_ref=f"facet:{ids['apidl']}", b_ref=f"facet:{ids['srvdl-1']}", kind="depends_on", status="approved",
                    source="admin", seen_at=None)
        db.session.add_all([old, mine])
        db.session.commit()
        out = datalinks.apply()
        db.session.commit()
        assert out["stale"] == 1
        db.session.refresh(old)
        db.session.refresh(mine)
        assert old.proposed_drop.startswith("not seen in the data since") and old.status == "approved"   # still used
        assert mine.proposed_drop is None                         # a person's link: never by the data


def test_a_disk_is_named_after_its_server(app, cats):
    """categories.qualified {"disk": "server"}: every server has its own sda; the value is "<server> <disk>", part of
    the server, made from what the series carry together (never a lone "sda" for every server)."""
    from superset.extensions import db

    from supagent.knowledge import datalinks, sysmap
    from supagent.models import Facet, KObject

    with app.app_context():
        cats["conf"]["categories.qualified"] = {"disk": "server"}
        series = [{"instance": "srvdl-1", "device": "sdq"}, {"instance": "srvdl-2", "device": "sdq"}]
        db.session.add(KObject(source_id=cats["source"], kind="metric", name="dl_metric_total", parent="",
                               stats={"category_pairs": datalinks.label_pairs(series)}))
        db.session.commit()
        out = datalinks.apply()
        db.session.commit()
        assert out["qualified_values"] == 2
        made = {f.value: f for f in db.session.query(Facet).filter(Facet.facet == "disk", Facet.value.like("srvdl-%"))}
        assert set(made) == {"srvdl-1 sdq", "srvdl-2 sdq"}
        assert db.session.query(Facet).filter(Facet.facet == "disk", Facet.value == "sdq").first() is None
        links = {(x["a"], x["kind"], x["b"]) for x in sysmap.interactions()}
        assert (made["srvdl-1 sdq"].id, "part_of", cats["ids"]["srvdl-1"]) in links
        assert (made["srvdl-2 sdq"].id, "part_of", cats["ids"]["srvdl-2"]) in links
        from supagent.models import Link

        refs = [f"facet:{f.id}" for f in made.values()]
        db.session.query(Link).filter(Link.a_ref.in_(refs)).delete(synchronize_session=False)
        for f in made.values():
            db.session.delete(f)
        db.session.commit()
