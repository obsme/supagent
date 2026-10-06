"""0.9.5: one table for each set of documents. A family of rolled-over indices and an alias on all of them are one
table; an alias on the newest index only (a write alias) is a part of it, never a table of its own; a data stream
is said to be one (its backing indices, its generations deleted by retention); an alias with a filter (fewer
documents) and an alias on several unrelated indices stay tables of their own."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)


class Meta:
    def __init__(self, indices):
        self.indices = indices


class Conn:
    """The connector as the learner sees it: the indices each name reads (its mapping) and its documents."""

    def __init__(self, reads, docs):
        self.reads, self.docs, self.asked = reads, docs, []
        conn = self

        class Transport:
            @staticmethod
            def count(name, query):
                conn.asked.append(name)
                return conn.docs[name]

        self.transport = Transport()

    def table_meta(self, name):
        return Meta(self.reads[name]) if name in self.reads else None


SPANS = ["jaeger-span-000001", "jaeger-span-000002", "jaeger-span-000003"]
BACKING = [f".ds-ss4o_logs-default-namespace-00000{g}" for g in range(2, 8)]


def _run(monkeypatch, kinds, objects, families, reads, docs, known=(), datasets=()):
    from supagent.knowledge import containers

    monkeypatch.setattr(containers, "container_kinds", lambda conn: kinds)
    return containers.one_table_each(Conn(reads, docs), objects, families, set(known), set(datasets))


def test_a_family_its_read_alias_and_its_write_alias_are_one_table(world, monkeypatch):  # noqa: F811
    kinds = {**{i: "index" for i in SPANS}, "jaeger-span-read": "alias", "jaeger-span-write": "alias",
             "ss4o_logs-default-namespace": "data_stream"}
    objects = {"jaeger-span-*": SPANS[-1], "jaeger-span-read": "jaeger-span-read", "jaeger-span-write": "jaeger-span-write",
               "ss4o_logs-default-namespace": "ss4o_logs-default-namespace"}
    reads = {"jaeger-span-read": SPANS, "jaeger-span-write": SPANS[-1:], "ss4o_logs-default-namespace": BACKING}
    docs = {"jaeger-span-*": 26222, "jaeger-span-read": 26222, "jaeger-span-write": 4222}
    left, said = _run(monkeypatch, kinds, objects, {"jaeger-span-*": SPANS}, reads, docs)
    assert sorted(left) == ["jaeger-span-read", "ss4o_logs-default-namespace"]          # one table for the spans
    assert said["jaeger-span-read"]["names"] == [{"name": "jaeger-span-*", "kind": "pattern"}]
    part = said["jaeger-span-read"]["parts"][0]
    assert (part["name"], part["indices"], part["of"], part["docs"], part["newest"]) == \
        ("jaeger-span-write", ["jaeger-span-000003"], 3, 4222, True)
    ds = said["ss4o_logs-default-namespace"]["data_stream"]
    assert (ds["backing"], ds["first"], ds["latest"], ds["gone_before"]) == (6, BACKING[0], BACKING[-1], 2)
    # the pattern already learned (or a dataset on it) keeps its name; the alias is then its other name
    left, said = _run(monkeypatch, kinds, objects, {"jaeger-span-*": SPANS}, reads, docs, datasets={"jaeger-span-*"})
    assert "jaeger-span-*" in left and "jaeger-span-read" not in left
    assert said["jaeger-span-*"]["names"] == [{"name": "jaeger-span-read", "kind": "alias"}]
    assert said["jaeger-span-*"]["parts"][0]["name"] == "jaeger-span-write"


def test_an_alias_with_a_filter_or_on_unrelated_indices_stays_a_table(world, monkeypatch):  # noqa: F811
    kinds = {"app-logs": "index", "sys-logs": "index", "all-logs": "alias", "app-errors": "alias",
             "customers_v3": "index", "customers": "alias"}
    objects = {k: k for k in kinds}
    reads = {"all-logs": ["app-logs", "sys-logs"], "app-errors": ["app-logs"], "customers": ["customers_v3"]}
    docs = {"app-logs": 900, "sys-logs": 300, "all-logs": 1200, "app-errors": 40, "customers_v3": 77, "customers": 77}
    left, said = _run(monkeypatch, kinds, objects, {}, reads, docs)
    assert sorted(left) == ["all-logs", "app-errors", "app-logs", "customers", "sys-logs"]   # the filter: fewer docs
    assert said["customers"]["names"] == [{"name": "customers_v3", "kind": "index"}]
    assert said["all-logs"]["alias"] == {"indices": 2, "first": "app-logs", "latest": "sys-logs"}
    assert "parts" not in said.get("all-logs", {}) and "names" not in said.get("app-logs", {})
    # names only, no alias nor data stream: nothing asked, nothing said
    from supagent.knowledge import containers

    monkeypatch.setattr(containers, "container_kinds", lambda conn: {})
    conn = Conn({}, {})
    assert containers.one_table_each(conn, {"a": "a", "b-*": "b-2"}, {"b-*": ["b-1", "b-2"]}, set(), set()) == \
        ({"a": "a", "b-*": "b-2"}, {}) and conn.asked == []


def test_what_the_agent_is_told(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.containers import lines
    from supagent.knowledge.describe import describe
    from supagent.knowledge.store import upsert
    from supagent.models import Run, Source
    from supagent.security import acting_as

    st = {"alias": {"indices": 3, "first": SPANS[0], "latest": SPANS[-1]},
          "names": [{"name": "jaeger-span-*", "kind": "pattern"}],
          "parts": [{"name": "jaeger-span-write", "indices": SPANS[-1:], "of": 3, "docs": 4222, "newest": True,
                     "from": "2026-09-26 15:33"}]}
    said = lines(st, "jaeger-span-read")
    assert said[0] == 'an alias on 3 indices (jaeger-span-000001 .. jaeger-span-000003): "jaeger-span-read" reads them all'
    assert said[1] == ('the same documents as "jaeger-span-*" (other names of this table: count once, never add them)')
    assert said[2] == ('"jaeger-span-write" is an alias on only 1 of its 3 indices (the newest: jaeger-span-000003): '
                       '4,222 documents from 2026-09-26 15:33, not the history: count and compare on "jaeger-span-read"')
    ds = lines({"data_stream": {"backing": 6, "first": BACKING[0], "latest": BACKING[-1], "gone_before": 2}},
               "ss4o_logs-default-namespace")
    assert ds == ["a data stream: its documents are in 6 hidden backing indices, rolled over "
                  "(.ds-ss4o_logs-default-namespace-000002 .. .ds-ss4o_logs-default-namespace-000007); its generations "
                  "before 000002 were deleted (retention): no data before its first document; query "
                  "\"ss4o_logs-default-namespace\", it reads them all (never a backing index)"]
    run, src = db.session.query(Run).first(), db.session.query(Source).first()
    upsert(run, src, "index", "", "jaeger-span-read", {"stats": {"docs": 26222, **st}})
    db.session.commit()
    with acting_as("admin"):
        text = describe(name="jaeger-span-write") or ""
    assert text.startswith("('jaeger-span-write' is not a table of its own: it reads the documents of "
                           "'jaeger-span-read', or a part of them; below: 'jaeger-span-read')")
    assert "Index jaeger-span-read" in text and "no index or metric named" not in text


def test_the_same_values_in_another_database_are_not_told_as_a_join(world):  # noqa: F811
    """Two OpenSearch databases (two clusters): the values a field shares with an index of the other one are said,
    with its database, as values to match, never as a join (no SQL reads both)."""
    from superset.extensions import db

    from supagent.knowledge.describe import _join_lines
    from supagent.knowledge.store import source_for, upsert
    from supagent.models import Relation, Run

    from test_knowledge import _database

    run = db.session.query(Run).first()
    s_jobs = world["s_jobs"]
    cluster = _database("cmdb cluster", "osagg://127.0.0.1:9201/")
    try:
        s_cmdb = source_for(cluster)
        node = upsert(run, s_jobs, "field", "jobs", "NODE", {"data_type": "keyword"})
        host = upsert(run, s_cmdb, "field", "assets", "name", {"data_type": "keyword"})
        other = upsert(run, s_jobs, "field", "servers", "NODE", {"data_type": "keyword"})
        db.session.commit()
        rels = [(Relation(a_id=node.id, b_id=host.id, relation="same_values", origin="learned", confidence=0.9,
                          evidence={"common": 12}), node, host),
                (Relation(a_id=node.id, b_id=other.id, relation="same_values", origin="learned", confidence=0.9,
                          evidence={"common": 9}), node, other)]
        lines = _join_lines("jobs", rels, set(), set())
    finally:                                          # (the other tests know the databases of the fixture only)
        from supagent.models import KObject, Source

        db.session.rollback()
        db.session.query(KObject).filter(KObject.source_id.in_(
            [s.id for s in db.session.query(Source).filter_by(database_id=cluster.id)])).delete(synchronize_session=False)
        db.session.query(Source).filter_by(database_id=cluster.id).delete()
        db.session.delete(cluster)
        db.session.commit()
    assert '  same values as assets in database "cmdb cluster" (another database: no SQL joins them; query each, then ' \
           'match the values): "NODE" = "name" (12 values in common) (measured)' in lines
    assert '  joins servers on "NODE" (9 values in common) (measured)' in lines
    assert not any(line.startswith("  joins assets") for line in lines)


def test_a_classification_limit_of_zero_gives_no_item_to_the_llm(world, monkeypatch):  # noqa: F811
    """learn.classify_per_run = 0 (a learning meant to read the data only) was read as 400: the LLM was called."""
    from supagent import settings
    from supagent.knowledge import learner as L

    assert L.classify_limit(25) == 25 and L.classify_limit(0) == 0
    settings.set_value("learn.classify_per_run", 0)
    try:
        assert L.classify_limit() == 0
        called = []
        monkeypatch.setattr("supagent.knowledge.facets.classify", lambda *a, **k: called.append(1) or {})
        monkeypatch.setattr(L, "_from_data", lambda steps, seconds: {})
        for key in ("learn.interactions", "learn.interactions_logs", "learn.interactions_explain"):
            if any(s.key == key for s in settings.SPECS):
                settings.set_value(key, False)

        class Steps:
            def begin(self, *a, **k):
                pass

            def end(self, **k):
                pass

            def update(self, **k):
                pass

        out = L._categories(1, Steps(), 30.0, L.classify_limit())
        assert called == [] and out["classified"] == {"off": "learn.classify_per_run = 0"}
    finally:
        for key in ("learn.classify_per_run", "learn.interactions", "learn.interactions_logs", "learn.interactions_explain"):
            if any(s.key == key for s in settings.SPECS):
                settings.set_value(key, None)


def test_an_instance_label_written_host_port_meets_the_host_fields(world):  # noqa: F811
    """Prometheus' instance (db-pg-01:9187, vm-pay-01:9100) and the logs' host.name (db-pg-01, vm-pay-01) are the same
    hosts: related by the host part, said with the way to filter."""
    from superset.extensions import db

    from supagent.knowledge.relations import learn_relations, without_ports
    from supagent.knowledge.store import upsert
    from supagent.models import Relation, Run

    assert without_ports({"db-pg-01:9187", "vm-pay-01:9100", "10.0.3.12:9100"}) == {"db-pg-01", "vm-pay-01", "10.0.3.12"}
    assert without_ports({"https://paygw.example/health", "db-pg-01"}) is None
    assert without_ports({"sw-core-01", "db-pg-01:9100", "vm-pay-01:9100"}) == {"sw-core-01", "db-pg-01", "vm-pay-01"}
    run = db.session.query(Run).first()
    lb = upsert(run, world["s_prom"], "label", "node_cpu_seconds_total", "instance",
                {"data_type": "string", "stats": {"values": ["db-pg-01:9100", "vm-pay-01:9100", "k8s-node-01:9100"]}})
    f = upsert(run, world["s_jobs"], "field", "app-logs", "host.name",
               {"data_type": "keyword", "stats": {"values": ["db-pg-01", "vm-pay-01"]}})
    db.session.commit()
    learn_relations()
    rel = db.session.query(Relation).filter(((Relation.a_id == lb.id) & (Relation.b_id == f.id)) |
                                            ((Relation.a_id == f.id) & (Relation.b_id == lb.id))).one()
    assert rel.evidence["common"] == 2 and rel.evidence["port_stripped"] is True


def test_the_kind_of_a_table_counts_in_the_topic(world):  # noqa: F811
    """"the logs of the database server": the log tables, whose names and fields say nothing of logs, are found by
    their kind."""
    from supagent.knowledge.describe import _kind_text, _score, topic_words

    ws = topic_words("the logs of the database server")
    logs = {"kind": {"kind": "logs", "layout": "Logstash / Elastic Common Schema"}}
    assert _score(ws, "app-2026.09", "", "", _kind_text(logs)) > _score(ws, "app-2026.09", "", "", _kind_text({}))
    assert _score(topic_words("traces of checkout"), "jaeger", "", "", _kind_text({"kind": {"kind": "spans"}})) >= 1
