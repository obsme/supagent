"""(0.10.8, the team's request of 11 October) A server is named by its full name in the data (web01.corp.example) and
by its short one in a question (web01), or the other way, or by its address with a port (web01:9100, a metric's
instance): the query found nothing, the map did not know it, the health checks matched no series and the records
of changes were not found. A host is found by any of its names, whichever is asked and whichever the data writes;
never another host of the same short name (web01.dmz.example), never a value of a field that holds no hosts."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)


def _hosts(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.store import upsert

    upsert(world["run"], world["s_jobs"], "field", "jobs", "HOST",
           {"data_type": "keyword", "stats": {"cardinality": 4, "values": [
               "web01.corp.example", "web02.corp.example", "db01.corp.example", "db01.dmz.example"]}})
    upsert(world["run"], world["s_jobs"], "field", "jobs", "LOGGER",
           {"data_type": "keyword", "stats": {"cardinality": 1, "values": ["com.example.Billing"]}})
    upsert(world["run"], world["s_prom"], "label", "node_load1", "instance",
           {"stats": {"cardinality": 2, "values": ["web01.corp.example:9100", "web02:9100"]}})
    db.session.commit()


def test_one_host_by_any_of_its_names():
    from supagent.knowledge.values import host_aliases, same_host

    assert same_host("web01", "web01.corp.example") and same_host("WEB01", "web01.corp.example:9100")
    assert same_host("web01.corp", "web01.corp.example") and same_host("web01.corp.example.", "web01:9100")
    assert same_host("web1", "web01.corp.example")                         # a leading zero, as for any name
    assert not same_host("web01.corp.example", "web01.dmz.example")        # another host of that short name
    assert not same_host("web01", "web010.corp.example") and not same_host("10.0.0", "10.0.0.1")
    assert host_aliases("web01.corp.example:9100") == ["web01.corp.example", "web01"]
    assert host_aliases("web01") == [] and host_aliases("10.0.0.1") == []
    assert host_aliases("rack 4.2") == [] and not same_host("rack 4", "rack 4.2")      # not a host's name


def test_a_host_named_otherwise_is_queried_as_the_data_writes_it(world):  # noqa: F811
    from supagent.knowledge.values import respell_promql, respell_sql

    _hosts(world)
    q = 'SELECT COUNT(*) FROM "jobs" WHERE "HOST" = \'{}\''
    assert respell_sql(q.format("web01")) == (q.format("web01.corp.example"), [("web01", "web01.corp.example")])
    assert respell_sql(q.format("WEB02"))[0] == q.format("web02.corp.example")
    assert respell_sql(q.format("db01.dmz"))[0] == q.format("db01.dmz.example")
    for same in ("db01", "db01.dmz.example", "web03"):                    # two hosts, as written, no host: untouched
        assert respell_sql(q.format(same)) == (q.format(same), [])
    other = 'SELECT COUNT(*) FROM "jobs" WHERE "LOGGER" = \'com\''         # a field of no hosts: untouched
    assert respell_sql(other) == (other, [])
    expr, changes = respell_promql('avg_over_time(node_load1{instance="web01"}[1h])')
    assert 'instance="web01.corp.example:9100"' in expr and changes
    assert 'instance="web02:9100"' in respell_promql('node_load1{instance="web02.corp.example"}')[0]


def test_a_comparison_of_a_table_is_respelled_too(world):  # noqa: F811
    from supagent.knowledge.values import respell

    _hosts(world)
    args = {"table": "jobs", "start": "2026-09-01 00:00", "end": "2026-09-02 00:00", "where": "\"HOST\" = 'web02'"}
    assert respell("compare_logs", args) == [("web02", "web02.corp.example")]
    assert args["where"] == "\"HOST\" = 'web02.corp.example'"
    focus = {"table": "jobs", "start": "s", "end": "e", "focus": "\"HOST\" IN ('web01', 'web02.corp.example')"}
    respell("what_they_share", focus)
    assert focus["focus"] == "\"HOST\" IN ('web01.corp.example', 'web02.corp.example')"


def test_the_map_finds_a_server_by_any_of_its_names():
    from supagent.knowledge.brief import _host_aliases, loose_index, named

    values = {1: {"id": 1, "cat": "server", "name": "web01.corp.example"},
              2: {"id": 2, "cat": "server", "name": "db01"},
              3: {"id": 3, "cat": "server", "name": "app01.corp.example"},
              4: {"id": 4, "cat": "server", "name": "app01.dmz.example"},
              5: {"id": 5, "cat": "application", "name": "billing.api"},
              6: {"id": 6, "cat": "server", "name": "graph.corp.example"}}
    names = {v["name"].lower(): [i] for i, v in values.items()}
    for alias, ids in _host_aliases(values, {}).items():
        names.setdefault(alias, ids)
    loose, slips = loose_index(names)
    g = {"names": names, "values": values, "loose": loose, "slips": slips}
    assert named("is web01 up?", g, loose=True) == [1]
    assert named("errors on db01.corp.example today", g, loose=True) == [2]
    assert named("errors on db01:9100", g, loose=True) == [2]
    assert named("is app01.corp.example down?", g, loose=True) == [3]
    assert sorted(named("is app01 down?", g, loose=True)) == [3, 4]         # two servers of that name: both said
    assert named("is billing slow?", g, loose=True) == []                   # not a server: no short name
    assert named("show the graph of the errors", g, loose=True) == []       # a word of every question: not a name
    assert named("is graph.corp.example up?", g, loose=True) == [6]


def test_health_checks_and_records_match_a_host_by_any_name():
    from supagent.knowledge.values import names_hit, spellings

    assert names_hit({"instance": "web01.corp.example:9100", "job": "node"}, {"web01"}) == {"web01"}
    assert names_hit({"nodename": "WEB01"}, {"web01.corp.example"}) == {"web01.corp.example"}
    assert names_hit({"instance": "web01.dmz.example:9100"}, {"web01.corp.example"}) == set()
    assert names_hit({"job": "Billing-API"}, {"billing api"}) == {"billing api"}
    assert names_hit({"job": "billing.api"}, {"billing"}) == set()          # not a host label: the name as written
    assert spellings(["web01"], ["web01.corp.example", "web02.corp.example", "WEB01", "web01"]) == \
        ["web01.corp.example", "WEB01"]


def test_the_value_search_and_the_empty_result_say_how_the_data_writes_it(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import valueindex as V
    from supagent.knowledge.empty import _value_hint
    from supagent.knowledge.store import upsert
    from supagent.security import acting_as

    _hosts(world)
    upsert(world["run"], world["s_jobs"], "field", "jobs", "ALERT_INSTANCE",     # an alert writes the short name,
           {"data_type": "keyword", "stats": {"cardinality": 1, "values": ["web01"]}})   # the metrics name:port
    db.session.commit()
    V._CACHE.update(stamp=None, values=None, parents=None)
    with acting_as("admin"):
        text = V.where("how busy was web02 yesterday")[0]["text"]
        assert "field HOST of index jobs (jobs) written “web02.corp.example”" in text
        assert "label instance of metric node_load1 (metrics) written “web02:9100”" in text
        assert "web01.dmz.example" not in V.where("web01.corp.example")[0]["text"]
        text = V.where("how busy was web01 yesterday")[0]["text"]                 # one writes it as asked: the others too
        assert "field ALERT_INSTANCE of index jobs (jobs)" in text
        assert "label instance of metric node_load1 (metrics) written “web01.corp.example:9100”" in text
        assert {p["written"] for p in V.places(["web01"])} >= {"web01", "web01.corp.example", "web01.corp.example:9100"}
    hint = _value_hint("HOST", ["db01"], {"cardinality": 4, "values": [
        "web01.corp.example", "db01.corp.example", "db01.dmz.example"]}, "osagg")
    assert "'db01' is written 'db01.corp.example' or 'db01.dmz.example'" in hint
