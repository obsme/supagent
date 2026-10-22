"""(0.11.8.1) The values filed in a server category with their port before 0.11.8 ("web01:9100") move to the
components whatever the learning read them from: the data, the AI's classification (source llm, approved or
waiting), the documents (docs); a person's value stays, and so does one a person put back in a server category
after the move, even while the data still reads it (no component of its name). A moved value runs on its host's
server value; what the AI wrote of it as a server goes unless a person reviewed it (approving is reviewing)."""
from __future__ import annotations

import pytest

NAMES = ["srvmv-1", "srvmv-1:9100", "srvmv-2:9100", "srvmv-3:9187", "srvmv-4:8080", "srvmv-5:9100", "srvmv-6:9100",
         "srvmv-4", "srvmv-5"]


@pytest.fixture()
def moved(app, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.models import Facet, Link

    conf = {"categories.custom": ["server"], "categories.fields": {"server": r"^(instance)$"},
            "categories.label_links": True, "categories.review_all": False}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))

    def clear() -> None:
        ids = [f.id for f in db.session.query(Facet).filter(Facet.value.in_(NAMES))]
        refs = [f"facet:{i}" for i in ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()

    with app.app_context():
        clear()
        mark = "(0.11.8) moved from server: a server's name with its port is a component on that server"
        db.session.add_all([
            Facet(facet="server", value="srvmv-1", status="approved", source="data"),
            Facet(facet="server", value="srvmv-1:9100", status="approved", source="llm",     # the AI's, approved
                  reviewed_by="admin", description="Approved as written by a person."),   # by a person
            Facet(facet="server", value="srvmv-2:9100", status="proposed", source="llm",     # the AI's, waiting
                  description="A Linux server of the platform."),
            Facet(facet="server", value="srvmv-3:9187", status="proposed", source="docs"),   # the documents'
            Facet(facet="server", value="srvmv-4:8080", status="approved", source="admin"),  # a person's
            Facet(facet="server", value="srvmv-5:9100", status="approved", source="data",    # moved, put back by a
                  origins=[mark]),                                                       # person
            Facet(facet="server", value="srvmv-6:9100", status="approved", source="llm"),    # a component of that
            Facet(facet="component", value="srvmv-6:9100", status="approved", source="data"),   # name exists
        ])
        db.session.commit()
        yield
    with app.app_context():
        clear()


def test_the_ais_and_the_documents_values_with_a_port_move_too(app, moved):
    from superset.extensions import db

    from supagent.knowledge import facets as F
    from supagent.models import Facet, Link

    with app.app_context():
        assert F._move_endpoints() >= 4
        db.session.commit()
        by = {(f.facet, f.value): f for f in db.session.query(Facet).filter(Facet.value.in_(NAMES))}
        for v in ("srvmv-1:9100", "srvmv-2:9100", "srvmv-3:9187", "srvmv-6:9100"):
            assert ("component", v) in by and ("server", v) not in by, v
        assert by[("component", "srvmv-1:9100")].status == "approved"
        assert by[("component", "srvmv-2:9100")].status == "proposed"                 # still waits for a person
        assert by[("component", "srvmv-1:9100")].description == "Approved as written by a person."   # a person's
        assert by[("component", "srvmv-2:9100")].description is None     # the AI's words of a server: the metrics'
        assert ("server", "srvmv-4:8080") in by and ("server", "srvmv-5:9100") in by     # a person's: stay
        assert db.session.query(Facet).filter(Facet.value == "srvmv-6:9100").count() == 1   # one: the component
        assert all(any(F.MOVED in str(o) for o in by[("component", v)].origins or [])
                   for v in ("srvmv-1:9100", "srvmv-6:9100"))
        links = {(x.a_ref, x.kind, x.b_ref) for x in db.session.query(Link).filter(Link.status == "approved")}
        assert (f"facet:{by[('component', 'srvmv-1:9100')].id}", "runs_on",
                f"facet:{by[('server', 'srvmv-1')].id}") in links                        # on its host
        assert F._move_endpoints() == 0                                                     # once
        back = by[("component", "srvmv-2:9100")]                                            # a person puts it back
        back.facet = "server"
        db.session.commit()
        assert F._move_endpoints() == 0
        db.session.commit()
        assert db.session.query(Facet).filter(Facet.facet == "server", Facet.value == "srvmv-2:9100").count() == 1


def test_without_label_links_the_host_link_waits_for_a_person(app, moved, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import facets as F
    from supagent.models import Facet, Link

    with app.app_context():
        get = settings.get
        monkeypatch.setattr(settings, "get", lambda key: False if key == "categories.label_links" else get(key))
        F._move_endpoints()
        db.session.commit()
        comp = db.session.query(Facet).filter(Facet.facet == "component", Facet.value == "srvmv-1:9100").one()
        host = db.session.query(Facet).filter(Facet.facet == "server", Facet.value == "srvmv-1").one()
        link = db.session.query(Link).filter(Link.a_ref == f"facet:{comp.id}", Link.b_ref == f"facet:{host.id}",
                                             Link.kind == "runs_on").one()
        assert link.status == "proposed"


def test_a_server_value_a_person_keeps_gets_no_component_of_its_name_while_the_data_reads_it(app, moved):
    from superset.extensions import db

    from supagent.knowledge import facets as F
    from supagent.models import Facet, KObject, Link, Source

    with app.app_context():
        had_exporter = db.session.query(Facet).filter(Facet.facet == "component",
                                                      Facet.value == "node-exporter").first() is not None
        src = Source(database_id=987119, database_name="endpoints kept test", backend="promagg")
        db.session.add(src)
        db.session.flush()
        db.session.add(KObject(source_id=src.id, kind="label", name="instance", parent="node_load1",
                               stats={"values": ["srvmv-4:8080", "srvmv-5:9100", "srvmv-1:9100"]}))
        db.session.commit()
        try:
            F.seed()
            db.session.commit()
            for v in ("srvmv-4:8080", "srvmv-5:9100"):      # a person's; moved and put back by a person: read in
                rows = db.session.query(Facet).filter(Facet.value == v).all()      # the data, still one server value
                assert [(f.facet, f.status) for f in rows] == [("server", "approved")], v
            comp = db.session.query(Facet).filter(Facet.facet == "component", Facet.value == "srvmv-1:9100").one()
            host = db.session.query(Facet).filter(Facet.facet == "server", Facet.value == "srvmv-1").one()
            assert db.session.query(Link).filter(Link.a_ref == f"facet:{comp.id}", Link.b_ref == f"facet:{host.id}",
                                                 Link.kind == "runs_on").count() == 1
        finally:
            db.session.query(KObject).filter(KObject.source_id == src.id).delete(synchronize_session=False)
            db.session.query(Source).filter(Source.id == src.id).delete(synchronize_session=False)
            if not had_exporter:
                ids = [f.id for f in db.session.query(Facet).filter(Facet.facet == "component",
                                                                     Facet.value == "node-exporter")]
                refs = [f"facet:{i}" for i in ids]
                db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(
                    synchronize_session=False)
                db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()


def test_what_ships_the_metrics_of_every_family():
    """(0.11.8.1) The owner's: not only web01:9100: blackbox, the mongodb, oracle and postgres exporters, Loki,
    Mimir, each on its own port, said by the metrics it ships."""
    from supagent.knowledge.facets import endpoint, what_ships

    assert what_ships(["node_load1", "node_cpu_seconds_total", "up"]) == ("node-exporter", "node_*", "exporter")
    assert what_ships(["pg_up", "pg_stat_database_numbackends"]) == ("postgres-exporter", "pg_*", "exporter")
    assert what_ships(["mongodb_up", "mongodb_connections"]) == ("mongodb-exporter", "mongodb_*", "exporter")
    assert what_ships(["oracledb_up", "oracledb_sessions_value"]) == ("oracledb-exporter", "oracledb_*", "exporter")
    assert what_ships(["blackbox_exporter_config_last_reload_successful", "blackbox_module_unknown_total",
                       "go_goroutines"]) == ("blackbox-exporter", "blackbox_*", "exporter")
    assert what_ships(["probe_success", "probe_duration_seconds"]) == ("blackbox-exporter", "probe_*", "probe")
    assert what_ships(["loki_ingester_streams_created_total", "loki_request_duration_seconds_count",
                       "go_goroutines"]) == ("loki", "loki_*", "own")
    assert what_ships(["cortex_ingester_active_series", "cortex_request_duration_seconds_count"]) == \
        ("mimir", "cortex_*", "own")
    assert what_ships(["cortex_ring_members", "cortex_kv_request_duration_seconds", "cortex_ring_tokens_total",
                       "loki_ingester_streams_created_total"]) == ("loki", "loki_*", "own")   # Loki 2's cortex_*
    assert what_ships(["orders_requests_total", "up"]) == (None, "orders_*", None)
    assert endpoint("db01:5432") == ("db01", "5432", False)
    assert endpoint("https://shop.example/health") == ("shop.example", None, True)
    assert endpoint("http://10.0.0.5:8080/metrics") == ("10.0.0.5", "8080", True)
    assert endpoint("db01") is None and endpoint("ftp://db01/x") is None


FAMILIES = {   # metric -> the instances that carry it: one server, a port per exporter or service; a probed target
    "node_load1": ["srvfam-1:9100"], "node_cpu_seconds_total": ["srvfam-1:9100"],
    "pg_up": ["srvfam-1:9187"], "pg_stat_database_numbackends": ["srvfam-1:9187"],
    "mongodb_up": ["srvfam-1:9216"], "mongodb_connections": ["srvfam-1:9216"],
    "oracledb_up": ["srvfam-1:9161"], "oracledb_sessions_value": ["srvfam-1:9161"],
    "loki_ingester_streams_created_total": ["srvfam-1:3100"], "loki_request_duration_seconds_count": ["srvfam-1:3100"],
    "cortex_ingester_active_series": ["srvfam-1:8080"], "cortex_request_duration_seconds_count": ["srvfam-1:8080"],
    "blackbox_exporter_config_last_reload_successful": ["srvfam-1:9115"], "blackbox_module_unknown_total": ["srvfam-1:9115"],
    "probe_success": ["srvfam-2:5432", "https://srvfam.example/health"],
    "probe_duration_seconds": ["srvfam-2:5432", "https://srvfam.example/health"],
    "go_goroutines": ["srvfam-1:9115", "srvfam-1:3100"], "up": ["srvfam-1:9100", "srvfam-1:9187"],
}
SHIPPERS = ["node-exporter", "postgres-exporter", "mongodb-exporter", "oracledb-exporter", "loki", "mimir",
            "blackbox-exporter"]


@pytest.fixture()
def families(app, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.models import Facet, KObject, Link, Source

    conf = {"categories.custom": ["server"], "categories.fields": {"server": r"^(instance)$"},
            "categories.label_links": True, "categories.review_all": False}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    with app.app_context():
        had = {f.value for f in db.session.query(Facet).filter(Facet.value.in_(SHIPPERS))}

    def clear() -> None:
        ids = [f.id for f in db.session.query(Facet).filter(
            Facet.value.like("srvfam%") | Facet.value.like("https://srvfam%") |
            (Facet.value.in_([s for s in SHIPPERS if s not in had])))]
        refs = [f"facet:{i}" for i in ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
        for s in db.session.query(Source).filter_by(database_id=987120):
            db.session.query(KObject).filter(KObject.source_id == s.id).delete(synchronize_session=False)
            db.session.delete(s)
        db.session.commit()

    with app.app_context():
        clear()
        src = Source(database_id=987120, database_name="endpoint families test", backend="promagg")
        db.session.add(src)
        db.session.flush()
        for metric, values in FAMILIES.items():
            db.session.add(KObject(source_id=src.id, kind="label", name="instance", parent=metric,
                                   stats={"values": values}))
        # what 0.11.8 left: the URL a server value, the probed target described as the blackbox exporter and part of it
        db.session.add(Facet(facet="server", value="https://srvfam.example/health", status="approved", source="data"))
        old = Facet(facet="component", value="srvfam-2:5432", status="approved", source="data",
                    description="The blackbox-exporter of srvfam-2 (port 5432): it ships the probe_* metrics.")
        bbx = db.session.query(Facet).filter(Facet.facet == "component", Facet.value == "blackbox-exporter").first()
        if bbx is None:
            bbx = Facet(facet="component", value="blackbox-exporter", status="approved", source="data")
        db.session.add_all([old, bbx])
        db.session.flush()
        db.session.add(Link(a_ref=f"facet:{old.id}", b_ref=f"facet:{bbx.id}", kind="part_of", status="approved",
                            source="data", evidence="srvfam-2:5432 ships the probe_* metrics: the blackbox-exporter"))
        db.session.commit()
        yield
    with app.app_context():
        clear()


def test_every_exporter_and_service_on_its_port_is_said_by_its_metrics(app, families):
    from superset.extensions import db

    from supagent.knowledge import facets as F
    from supagent.models import Facet, Link

    with app.app_context():
        F.seed()
        db.session.commit()
        comps = {f.value: f for f in db.session.query(Facet).filter(Facet.facet == "component")}
        servers = {f.value: f for f in db.session.query(Facet).filter(Facet.facet == "server")}
        said = {v: comps[v].description for v in comps if v.startswith(("srvfam", "https://srvfam"))}
        assert said == {
            "srvfam-1:9100": "The node-exporter of srvfam-1 (port 9100): it ships the node_* metrics.",
            "srvfam-1:9187": "The postgres-exporter of srvfam-1 (port 9187): it ships the pg_* metrics.",
            "srvfam-1:9216": "The mongodb-exporter of srvfam-1 (port 9216): it ships the mongodb_* metrics.",
            "srvfam-1:9161": "The oracledb-exporter of srvfam-1 (port 9161): it ships the oracledb_* metrics.",
            "srvfam-1:3100": "loki on srvfam-1 (port 3100): it ships its own loki_* metrics.",
            "srvfam-1:8080": "mimir on srvfam-1 (port 8080): it ships its own cortex_* metrics.",
            "srvfam-1:9115": "The blackbox-exporter of srvfam-1 (port 9115): it ships the blackbox_* metrics.",
            "srvfam-2:5432": "A component on srvfam-2 (port 5432), probed by the blackbox-exporter: its probe_* metrics.",
            "https://srvfam.example/health": "An address probed by the blackbox-exporter: its probe_* metrics.",
        }
        assert {v for v in servers if v.startswith(("srvfam", "https://srvfam"))} == {"srvfam-1", "srvfam-2"}
        links = {(x.a_ref, x.kind, x.b_ref) for x in db.session.query(Link).filter(Link.status != "rejected")}

        def ref(v: str, cat: str = "component") -> str:
            return f"facet:{(comps if cat == 'component' else servers)[v].id}"

        for v, part in (("srvfam-1:9100", "node-exporter"), ("srvfam-1:9161", "oracledb-exporter"),
                        ("srvfam-1:3100", "loki"), ("srvfam-1:8080", "mimir"), ("srvfam-1:9115", "blackbox-exporter")):
            assert (ref(v), "runs_on", ref("srvfam-1", "server")) in links, v
            assert (ref(v), "part_of", ref(part)) in links, v
        assert (ref("srvfam-2:5432"), "runs_on", ref("srvfam-2", "server")) in links
        assert not [x for x in links if x[0] == ref("srvfam-2:5432") and x[1] == "part_of"]   # 0.11.8's: gone
        assert not [x for x in links if x[0] == ref("https://srvfam.example/health") and x[1] == "part_of"]
        assert F.was_moved(comps["https://srvfam.example/health"])
