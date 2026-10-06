"""(0.9.6, F03) A part made of other parts is looked at with them: a pool named to check_health has its servers'
breaches too (each said as found through the pool), a pool named to records_about has its servers' changes and
alerts too (agent.with_parts). A live answer stopped at "the pool is saturated": it checked the pool, never the four
servers of it that had not come back after a kernel patch."""

from __future__ import annotations

import contextlib
import datetime as dt

import pytest

from conftest import part_of
from test_groups import world  # noqa: F401  (the lab databases)
from test_groups_all_090 import night  # noqa: F401  (the runs and the changes of a night)


def make_pool():
    """POOL96 made of srv-3 and srv-amer-002; BIG96 made of more parts than are expanded (in the caller's app
    context): the ids, to remove."""
    from superset.extensions import db

    from supagent.knowledge import brief
    from supagent.models import Facet

    made = {n: Facet(facet=c, value=n, status="approved", source="admin")
            for c, n in (("application", "POOL96"), ("component", "srv-3"), ("component", "srv-amer-002"),
                         ("application", "BIG96"))}
    db.session.add_all(made.values())
    db.session.flush()
    part_of(made["srv-3"], made["POOL96"])
    part_of(made["srv-amer-002"], made["POOL96"])
    many = [Facet(facet="component", value=f"m96-{i}", status="approved", source="admin")
            for i in range(brief.MEMBERS_MAX + 1)]
    db.session.add_all(many)
    db.session.flush()
    for f in many:
        part_of(f, made["BIG96"])
    db.session.commit()
    brief._CACHE["graph"] = None
    return [f.id for f in [*made.values(), *many]]


def drop(ids):
    from superset.extensions import db

    from supagent.knowledge import brief
    from supagent.models import Facet, Link

    db.session.rollback()
    refs = [f"facet:{i}" for i in ids]
    db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
    db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
    brief._CACHE["graph"] = None


@pytest.fixture()
def pool(app):
    with app.app_context():
        ids = make_pool()
    yield
    with app.app_context():
        drop(ids)


def test_the_parts_of_a_named_part(app, pool):
    from supagent.knowledge import brief

    with app.app_context():
        assert brief.members(["POOL96"]) == {"POOL96": ["srv-3", "srv-amer-002"]}
        assert brief.members(["pool96", "srv-3"]) == {"POOL96": ["srv-3", "srv-amer-002"]}   # a server: no parts
        assert brief.members(["BIG96"]) == {}                   # more parts than MEMBERS_MAX: the names are needed
        assert brief.members(["nothing-known"]) == {}


class Zone:
    def utc_ms(self, d):
        return int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000)

    def local(self, ms):
        return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)


def health_world(monkeypatch):
    from supagent import tools

    class S:
        def __init__(self, labels, values, t0, step):
            self.labels = labels
            self.points = [(t0 + i * step, v) for i, v in enumerate(values)]

    class Conn:
        zone = Zone()

        class client:  # noqa: N801
            @staticmethod
            def query_range(expr, a, b, step):
                if a < 1790000000000:                 # the earlier days: nothing (the breach is new)
                    return []
                return [S({"node": "srv-amer-002", "dc": "NYC1"}, [95, 97, 96, 40], a, step),   # a node exporter:
                        S({"node": "srv-emea-041", "dc": "PAR1"}, [99, 99, 99, 99], a, step),   # its node, no pool
                        S({"pool": "POOL96"}, [91, 50, 50, 50], a, step)]

        def close(self):
            pass

    monkeypatch.setattr(tools, "_as_user", lambda: contextlib.nullcontext((None, None)))
    monkeypatch.setattr(tools, "_catalog", lambda: {"checks": {"cpu_saturation": {"promql": "cpu", "above": 90}}})
    monkeypatch.setattr(tools, "_metrics_database", lambda ref: type("D", (), {"database_name": "metrics"})())
    monkeypatch.setattr(tools, "_promagg_connection", lambda d: Conn())
    return tools


def test_a_pool_named_to_the_health_checks_has_its_servers_checked(app, pool, monkeypatch):
    from supagent import settings

    tools = health_world(monkeypatch)
    with app.app_context():
        got = tools.check_health("2026-09-24 00:00", "2026-09-24 08:00", entities=["POOL96"])
        assert got["parts_added"] == {"POOL96": ["srv-3", "srv-amer-002"]} and "parts_added" in got["note"]
        by_node = {b["labels"].get("node", "(pool)"): b for b in got["breaches"]}
        assert set(by_node) == {"srv-amer-002", "(pool)"}                  # not the other pool's server
        assert by_node["srv-amer-002"]["via"] == "POOL96"                  # found through the pool, said so
        assert "via" not in by_node["(pool)"]                              # the pool's own breach
        named = tools.check_health("2026-09-24 00:00", "2026-09-24 08:00", entities=["POOL96", "srv-amer-002"])
        assert all("via" not in b for b in named["breaches"])              # named itself: not "via"
        real = settings.get
        monkeypatch.setattr(settings, "get", lambda k: False if k == "agent.with_parts" else real(k))
        off = tools.check_health("2026-09-24 00:00", "2026-09-24 08:00", entities=["POOL96"])
        assert "parts_added" not in off and [b["labels"] for b in off["breaches"]] == [{"pool": "POOL96"}]


def test_a_pool_named_to_the_records_has_its_servers_records(night, app, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent import settings, tools as T
    from supagent.models import KObject, Source
    from supagent.security import acting_as

    night.con.execute("INSERT INTO \"changes\" VALUES ('2026-09-22 23:40:00', 'srv-3', 'Kernel patch and reboot of srv-3', "
                      "'CHG-8')")
    with app.app_context():
        src = db.session.query(Source).first()
        made = [KObject(source_id=src.id, kind="field", name="TARGET", parent="changes", data_type="keyword", stats={}),
                KObject(source_id=src.id, kind="field", name="WHAT", parent="changes", data_type="text", stats={})]
        db.session.add_all(made)
        db.session.commit()
        ids = make_pool()
        try:
            with acting_as("admin"):
                got = T.records_about(names=["POOL96"], until="2026-09-23 00:10", days=1)
                real = settings.get
                monkeypatch.setattr(settings, "get", lambda k: False if k == "agent.with_parts" else real(k))
                off = T.records_about(names=["POOL96"], until="2026-09-23 00:10", days=1)
        finally:
            drop(ids)
            for o in made:
                db.session.delete(o)
            db.session.commit()
    assert "error" not in got, got
    assert got["also_what_they_stand_on"] == ["srv-3", "srv-amer-002"] and "made of" in got["note"]
    table = got["tables"][0]
    assert table["records"] == 1 and table["latest"][0]["TICKET"] == "CHG-8"       # the server's patch, by the pool
    assert off["tables"][0]["records"] == 0 and "also_what_they_stand_on" not in off
