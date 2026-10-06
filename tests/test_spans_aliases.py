"""0.9.5: what the data itself says of the platform's parts: the calls the span tables show (spans), the names an
inventory gives as one thing (aliases), and a merged name that the next learning does not bring back (seed)."""

from __future__ import annotations

import pytest
from test_knowledge import world  # noqa: F401  (the fixture)


@pytest.fixture()
def conf(monkeypatch):
    from supagent import settings

    c = {"categories.review_all": False}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: c[key] if key in c else real(key))
    return c


def _values(*names, synonyms=None):
    from superset.extensions import db

    from supagent.models import Facet, Link

    db.session.query(Link).delete()
    db.session.query(Facet).filter(Facet.facet == "application").delete()
    out = {}
    for n in names:
        f = Facet(facet="application", value=n, status="approved", source="data", synonyms=(synonyms or {}).get(n))
        db.session.add(f)
        db.session.flush()
        out[n] = f
    db.session.commit()
    return out


def _fields(table, names, parent_kind="index"):
    from superset.extensions import db

    from supagent.knowledge.store import upsert
    from supagent.models import Run, Source

    run = db.session.query(Run).first()
    src = db.session.query(Source).first()
    upsert(run, src, parent_kind, "", table, {"stats": {"docs": 100, "time_field": "startTimeMillis"}})
    for n in names:
        upsert(run, src, "field", table, n, {"data_type": "keyword", "stats": {}})
    db.session.commit()


def test_the_span_tables_and_their_calls_drawn_on_the_map(world, conf, monkeypatch):  # noqa: F811
    """A Jaeger span table (span id, parent id, service, peer, duration in microseconds) is read; its calls between
    the services' values are drawn as interactions "calls" with how many and how long, through a value's synonyms;
    a pair under 5 calls a day, or a name no value has, is not drawn; nothing is drawn twice; an admin's interaction
    is left as it is; with an admin reviewing what the learning finds, the calls wait in To review."""
    import datetime as dt

    from superset.extensions import db

    from supagent.knowledge import spans
    from supagent.models import Link

    _fields("traces-*", ["traceID", "spanID", "parentSpanID", "process.serviceName", "tag.peer@service", "duration",
                         "startTimeMillis"])
    found = [t for t in spans.layouts() if t["table"] == "traces-*"]
    assert len(found) == 1 and found[0]["service"] == "process.serviceName" and found[0]["peer"] == "tag.peer@service"
    assert found[0]["ms"] == 1e-3 and found[0]["time"] == "startTimeMillis"            # Jaeger: microseconds
    assert not [t for t in spans.layouts() if t["table"] == "jobs"]                    # no span ids: not a span table
    v = _values("frontend", "checkout", "orders-db", synonyms={"checkout": ["shop-checkout"]})
    when = {"start": dt.datetime(2026, 9, 26, 11), "end": dt.datetime(2026, 9, 27, 11)}
    calls = {("frontend", "shop-checkout"): {"n": 40, "ms": 795.0, "how": "parent", **when},
             ("shop-checkout", "orders-db"): {"n": 30, "ms": 39.8, "how": "peer", **when},
             ("frontend", "orders-db"): {"n": 3, "ms": 5.0, "how": "peer", **when},
             ("batch", "orders-db"): {"n": 50, "ms": 9.0, "how": "peer", **when}}
    monkeypatch.setattr(spans, "_calls", lambda t, hours: calls)
    out = spans.run()
    links = {(x.a_ref, x.b_ref): x for x in db.session.query(Link).filter(Link.kind == "calls")}
    co, fe, odb = v["checkout"].id, v["frontend"].id, v["orders-db"].id
    assert set(links) == {(f"facet:{fe}", f"facet:{co}"), (f"facet:{co}", f"facet:{odb}")}
    x = links[(f"facet:{fe}", f"facet:{co}")]
    assert x.status == "approved" and x.source == "spans" and x.note == "frontend calls shop-checkout (40 calls in a day, about 795 ms each)"
    assert "40 child spans of shop-checkout under spans of frontend in traces-*" in x.evidence
    assert "client spans of shop-checkout naming orders-db as their peer" in links[(f"facet:{co}", f"facet:{odb}")].evidence
    assert out["written"] == 2 and "batch -> orders-db" in out["unmapped"]
    assert spans.run()["written"] == 0                                                   # nothing drawn twice
    admin = links[(f"facet:{co}", f"facet:{odb}")]
    admin.source, admin.note, admin.explained_by = "admin", "writes the orders", "admin"
    db.session.commit()
    spans.run()
    assert db.session.get(Link, admin.id).note == "writes the orders"                    # the admin's: left alone
    db.session.query(Link).delete()
    db.session.commit()
    conf["categories.review_all"] = True
    spans.run()
    assert {x.status for x in db.session.query(Link).filter(Link.kind == "calls")} == {"proposed"}


def test_an_inventory_makes_the_names_of_one_thing_one_value(world, conf, monkeypatch):  # noqa: F811
    """A CMDB lists checkout with its other names: the values the data gave for those names become one value (the
    row's own name kept, the others its synonyms, the interactions drawn on them moved); a row whose names give one
    value changes nothing; with an admin reviewing, the merge is only suggested ("same as"). The aliases field comes
    back from the database as a list, a JSON list in a string, or one name."""
    from superset.extensions import db

    from supagent.knowledge import aliases
    from supagent.models import Facet, Link

    assert aliases._names('["shop-checkout", "checkout-svc"]') == ["shop-checkout", "checkout-svc"]
    assert aliases._names("payment-legacy") == ["payment-legacy"] and aliases._names(None) == []
    assert aliases._names(["a", None, ""]) == ["a"]
    _fields("assets", ["name", "aliases", "owner"])
    assert [t["table"] for t in aliases.tables()] == ["assets"]
    v = _values("checkout", "shop-checkout", "payment-legacy", "frontend")
    db.session.add(Link(a_ref=f"facet:{v['frontend'].id}", b_ref=f"facet:{v['shop-checkout'].id}", kind="calls",
                        source="spans", status="approved"))
    db.session.commit()
    monkeypatch.setattr(aliases, "groups", lambda t: [["checkout", "shop-checkout", "checkout-svc"],
                                                      ["payment", "payment-legacy"]])
    conf["categories.review_all"] = True
    out = aliases.run()
    assert out["suggested"] == ["shop-checkout = checkout"] and out["merged"] == []
    assert db.session.get(Facet, v["shop-checkout"].id).suggested["same_as"] == v["checkout"].id
    conf["categories.review_all"] = False
    out = aliases.run()
    assert out["merged"] == ["shop-checkout -> checkout"] and out["groups"] == 1          # payment: one value only
    co = db.session.query(Facet).filter(Facet.value == "checkout").one()
    assert co.synonyms == ["shop-checkout"] and db.session.query(Facet).filter(Facet.value == "shop-checkout").first() is None
    moved = db.session.query(Link).filter(Link.kind == "calls").one()
    assert moved.b_ref == f"facet:{co.id}"                                                # drawn on the value now


def test_a_name_merged_into_a_value_is_not_brought_back_by_the_next_learning(world, conf, monkeypatch):  # noqa: F811
    """The data still writes "shop-checkout" after it was merged into checkout (by an admin, or by an inventory):
    the next learning finds it as checkout's synonym (where it is in the data joins checkout's origins) instead of
    making it a value again."""
    from superset.extensions import db

    from supagent.knowledge import facets as F
    from supagent.models import Facet

    v = _values("checkout", synonyms={"checkout": ["shop-checkout"]})
    monkeypatch.setattr(F, "data_values", lambda: ({
        ("application", "checkout"): {"value": "checkout", "origins": ["field kubernetes.labels.app of logs-*"]},
        ("application", "shop-checkout"): {"value": "shop-checkout", "origins": ["field process.serviceName of traces-*"]},
        ("application", "inventory"): {"value": "inventory", "origins": ["field kubernetes.labels.app of logs-*"]}}, 2))
    monkeypatch.setattr(F, "relations_from_data", lambda: 0)
    F.seed()
    names = {f.value for f in db.session.query(Facet).filter(Facet.facet == "application")}
    assert names == {"checkout", "inventory"}
    co = db.session.get(Facet, v["checkout"].id)
    assert co.origins == ["field kubernetes.labels.app of logs-*", "field process.serviceName of traces-*"]


def test_the_names_of_one_service_are_told_by_the_pods_they_share():
    """shop-checkout (OpenTelemetry) and checkout (Kubernetes) run on the same pods: one service; a sidecar in every
    pod, and two services of one host, are never merged."""
    from supagent.knowledge.podnames import groups

    pods = {"checkout-7d9f8b-c3xrs", "checkout-7d9f8b-h5jlk"}
    otel = ("otel", "pod", {"shop-checkout": set(pods)})
    fluent = ("fluent", "pod", {"checkout": set(pods), "inventory": {"inventory-5f4d7c-b9pqe"},
                                "istio-proxy": set(pods) | {"inventory-5f4d7c-b9pqe", "frontend-6b7c9d-q8wzr"}})
    jaeger = ("jaeger", "host", {"shop-checkout": set(pods), "payment": {"vm-pay-01"}})
    ecs = ("ecs", "host", {"payment-legacy": {"vm-pay-01"}, "postgresql": {"db-pg-01"}, "pgbouncer": {"db-pg-01"}})
    assert sorted(map(sorted, groups([otel, fluent, jaeger, ecs]))) == [["checkout", "shop-checkout"],
                                                                          ["payment", "payment-legacy"]]
    # one host carrying two services in a table: none of them is told by it
    shared = ("ecs", "host", {"payment-legacy": {"vm-pay-01"}, "batch-agent": {"vm-pay-01"}})
    assert groups([jaeger, shared]) == []
