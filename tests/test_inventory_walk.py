"""0.9.5: what an inventory (a CMDB) says the parts stand on, read when asked: the walk from the services down to
their nodes, the rack and the switch port, what the names share below them; records_about looks for the records of
those parts too; the record tables' fields that name a part are searched (a text field with a keyword subfield)."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)

ROWS = [
    {"name": "checkout", "table": "cmdb", "aliases": ["shop-checkout"], "raw": {
        "type": "service", "runs_on": '["k8s-node-01", "k8s-node-02"]', "depends_on": '["inventory", "orders-db"]',
        "owner": "hugo"}},
    {"name": "inventory", "table": "cmdb", "aliases": ["stock"], "raw": {
        "type": "service", "runs_on": '["k8s-node-02", "k8s-node-03"]', "depends_on": '["orders-db"]'}},
    {"name": "orders-db", "table": "cmdb", "aliases": [], "raw": {"type": "database", "runs_on": '["db-pg-01"]'}},
    {"name": "k8s-node-01", "table": "cmdb", "aliases": [], "raw": {"type": "host", "rack": "A",
                                                                    "connected_to": "sw-core-01:xe-0/0/1"}},
    {"name": "k8s-node-02", "table": "cmdb", "aliases": [], "raw": {"type": "host", "rack": "B",
                                                                    "connected_to": "sw-core-01:xe-0/0/2"}},
    {"name": "k8s-node-03", "table": "cmdb", "aliases": [], "raw": {"type": "host", "rack": "B",
                                                                    "connected_to": "sw-core-01:xe-0/0/2"}},
    {"name": "db-pg-01", "table": "cmdb", "aliases": [], "raw": {"type": "host", "rack": "A",
                                                                 "connected_to": "sw-core-01:xe-0/0/1"}},
    {"name": "sw-core-01", "table": "cmdb", "aliases": [], "raw": {"type": "switch"}},
]


def test_the_walk_down_from_the_services(world, monkeypatch):  # noqa: F811
    from supagent.knowledge import inventory as I

    inv = I.build([dict(r, raw=dict(r["raw"])) for r in ROWS])
    assert inv["relations"] == {"runs_on": "runs_on", "depends_on": "depends_on", "connected_to": "connected_to"}
    monkeypatch.setattr(I, "load", lambda: inv)
    w = I.walk(["stock", "shop-checkout"])                       # by their other names too
    inv_part = w["parts"]["inventory"]
    assert inv_part["is"] == "inventory (type service)"
    assert "inventory runs on k8s-node-02 (rack B, type host) (runs_on)" in inv_part["stands_on"]
    assert "k8s-node-02 connected to sw-core-01 (type switch) port xe-0/0/2 (connected_to)" in inv_part["stands_on"]
    assert "checkout depends on it (depends_on)" in inv_part["named_by"]
    assert {"k8s-node-02", "sw-core-01 port xe-0/0/2", "orders-db"} <= set(w["in_common_below"])
    assert I.walk(["nothing-here"]) is None
    node = I.walk(["k8s-node-03"])["parts"]["k8s-node-03"]
    assert node["named_by"] == ["inventory runs on it (runs_on)"]
    assert set(I.below(["inventory"])) == {"orders-db", "k8s-node-02", "k8s-node-03", "db-pg-01", "sw-core-01"}


def test_the_record_tables_search_the_fields_that_name_a_part(world):  # noqa: F811
    """An OpenSearch text field with a keyword subfield (the changes' target) was read as prose and only the first
    two such fields by name were searched (author, change_id): a change on the switch was never found."""
    from superset.extensions import db

    from supagent import tools
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    run, src = db.session.query(Run).first(), world["s_jobs"]
    upsert(run, src, "index", "", "itsm-changes", {"stats": {"time_field": "start"}})
    for f, card in (("author", 3), ("change_id", 4), ("status", 1), ("target", 4), ("type", 3), ("description", 4)):
        upsert(run, src, "field", "itsm-changes", f, {"data_type": "text", "stats": {"cardinality": card}})
    db.session.commit()
    found = {t: (k, x) for t, k, x in tools._record_tables()}
    keys, texts = found["itsm-changes"]
    assert keys[0] == "target" and "status" not in keys and "type" not in keys and "description" not in keys
    assert texts == ["description"]
