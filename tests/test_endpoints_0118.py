"""(0.11.8) A server's name written with its port (Prometheus' instance "web01:9100") is no server (the user's request
of 22 October 2026): its host is the server, the value a component on it, what it is said by the metrics it ships
(node_* -> the node-exporter of web01); the values filed as servers before are moved, a person's value stays."""
from __future__ import annotations

import pytest


def test_the_host_and_what_ships_the_metrics():
    from supagent.knowledge.facets import host_of, shipped_by

    assert host_of("web01:9100") == "web01" and host_of("web01.corp.example:9187") == "web01.corp.example"
    assert host_of("10.0.0.5:9100") == "10.0.0.5"
    assert host_of("web01") is None and host_of("http://web01:80") is None and host_of("web01:99999") is None
    assert shipped_by(["node_cpu_seconds_total", "node_load1", "up", "go_goroutines"]) == ("node-exporter", "node_*")
    assert shipped_by(["pg_up", "pg_stat_activity_count", "process_cpu_seconds_total"]) == ("postgres-exporter", "pg_*")
    assert shipped_by(["mysql_up", "mysql_global_status_threads_connected"]) == ("mysqld-exporter", "mysql_*")
    assert shipped_by(["orders_requests_total", "orders_errors_total", "up"]) == (None, "orders_*")
    assert shipped_by(["up", "scrape_duration_seconds", "go_goroutines"]) == (None, None)


@pytest.fixture()
def eps(app, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.models import Facet, KObject, Link, Source

    conf = {"categories.custom": ["server"],
            "categories.fields": {"application": r"^(application)$", "component": r"^(component|job)$",
                                  "server": r"^(instance)$"},
            "categories.label_links": True, "categories.review_all": False}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    names = ["srvep-1", "srvep-2", "srvep-3", "srvep-1:9100", "srvep-2:9100", "srvep-1:9187", "srvep-4:9100",
             "srvep-5:8080", "node-exporter", "postgres-exporter"]
    def clear() -> None:
        ids = [f.id for f in db.session.query(Facet).filter(Facet.value.in_(names + ["srvep-job"]))]
        refs = [f"facet:{i}" for i in ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
        for o in db.session.query(Source).filter_by(database_id=987118):
            db.session.query(KObject).filter(KObject.source_id == o.id).delete(synchronize_session=False)
        db.session.commit()

    with app.app_context():
        clear()
        src = db.session.query(Source).filter_by(database_id=987118).first()
        if src is None:
            src = Source(database_id=987118, database_name="endpoints test", backend="promagg")
            db.session.add(src)
            db.session.flush()
        series = {"node_cpu_seconds_total": ["srvep-1:9100", "srvep-2:9100"],
                  "node_memory_MemAvailable_bytes": ["srvep-1:9100", "srvep-2:9100"],
                  "up": ["srvep-1:9100", "srvep-2:9100", "srvep-1:9187"], "pg_up": ["srvep-1:9187"],
                  "pg_stat_activity_count": ["srvep-1:9187"], "go_goroutines": ["srvep-1:9187"],
                  "orders_total": ["srvep-3"]}
        for metric, values in series.items():
            db.session.add(KObject(source_id=src.id, kind="label", name="instance", parent=metric,
                                   stats={"values": values}))
        db.session.add(Facet(facet="server", value="srvep-4:9100", status="approved", source="data"))  # before 0.11.8
        db.session.add(Facet(facet="server", value="srvep-5:8080", status="approved", source="admin"))  # by hand
        db.session.commit()
        yield {"source": src.id}
    with app.app_context():
        clear()


def test_a_server_name_with_its_port_is_a_component_on_that_server(app, eps):
    from superset.extensions import db

    from supagent.knowledge import facets as F
    from supagent.models import Facet, Link

    with app.app_context():
        n = F.seed()
        by = {(f.facet, f.value): f for f in db.session.query(Facet).filter(
            Facet.value.like("srvep%") | Facet.value.in_(["node-exporter", "postgres-exporter"]))}
        assert {("server", "srvep-1"), ("server", "srvep-2"), ("server", "srvep-3")} <= set(by)
        assert ("server", "srvep-1:9100") not in by and ("component", "srvep-1:9100") in by
        assert by[("component", "srvep-1:9100")].description == \
            "The node-exporter of srvep-1 (port 9100): it ships the node_* metrics."
        assert by[("component", "srvep-1:9187")].description.startswith("The postgres-exporter of srvep-1 (port 9187)")
        assert n["endpoints"] == 3 and n["moved_endpoints"] == 1
        links = {(x.a_ref, x.kind, x.b_ref) for x in db.session.query(Link).filter(Link.status == "approved")}
        ep, host = by[("component", "srvep-1:9100")].id, by[("server", "srvep-1")].id
        assert (f"facet:{ep}", "runs_on", f"facet:{host}") in links
        assert (f"facet:{ep}", "part_of", f"facet:{by[('component', 'node-exporter')].id}") in links
        assert ("component", "srvep-4:9100") in by and ("server", "srvep-4:9100") not in by   # filed before: moved
        assert ("server", "srvep-5:8080") in by                                                # a person's: stays
        again = F.seed()                                                                        # nothing new
        assert again["moved_endpoints"] == 0
        assert db.session.query(Facet).filter(Facet.value == "srvep-1:9100").count() == 1


def test_a_series_pair_with_a_server_written_with_its_port_links_its_host(app, eps):
    from superset.extensions import db

    from supagent.knowledge import datalinks
    from supagent.models import Facet, KObject, Link

    with app.app_context():
        job = Facet(facet="component", value="srvep-job", status="approved", source="data")
        srv = Facet(facet="server", value="srvep-1", status="approved", source="data")
        db.session.add_all([job, srv])
        db.session.flush()
        pairs = datalinks.label_pairs([{"__name__": "node_load1", "instance": "srvep-1:9100", "job": "srvep-job"}])
        db.session.add(KObject(source_id=eps["source"], kind="metric", name="node_load1", parent="",
                               stats={"category_pairs": [{**p, "at": "2026-10-22T08:00:00"} for p in pairs]}))
        db.session.commit()
        try:
            datalinks.apply()
            db.session.commit()
            assert db.session.query(Link).filter(Link.a_ref == f"facet:{job.id}", Link.b_ref == f"facet:{srv.id}",
                                                 Link.kind == "runs_on").count() == 1
        finally:
            db.session.query(Link).filter(Link.a_ref == f"facet:{job.id}").delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id == job.id).delete(synchronize_session=False)
            db.session.commit()
