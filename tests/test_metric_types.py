"""0.9.5: when no metadata gives a metric's type, its samples of the last day say what the name cannot: a count
without "_total" only increases (its value is a total since a restart, not the number asked); a "_count" that goes
down as well as up is a level (the connections now), not a count."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)


def test_the_samples_say_a_count_or_a_level(world):  # noqa: F811
    from supagent.knowledge.learn_metrics import _stat_query, data_says, probes_type

    assert data_says("nginx_ingress_controller_requests", "gauge", 2793.0, 0.0) == {"increases_only": 2793}
    assert data_says("pg_stat_activity_count", "summary", 2112.0, 1089.0) == {"goes_down": 1089, "changes": 2112}
    assert data_says("node_load1", "gauge", 7129.0, 3569.0) is None                    # a gauge: as it is
    assert data_says("jvm_gc_pause_seconds_count", "summary", 1438.0, 0.0) is None      # it counts: as it is
    assert data_says("ifOperStatus", "gauge", 4.0, 0.0) is None                         # too few changes
    assert data_says("pg_database_size_bytes", "gauge", 900.0, 0.0) is None             # a size: never asked
    assert not probes_type("pg_database_size_bytes", "gauge") and not probes_type("checkout_orders_total", "counter")
    # asked with its statistics (one request per metric, as before)
    q = _stat_query('{__name__="ifHCInOctets"}', "gauge", "ifHCInOctets", "24h", probe=True)
    assert 'sum(changes({__name__="ifHCInOctets"}[24h]))' in q and 'sum(resets({__name__="ifHCInOctets"}[24h]))' in q
    assert "min_over_time" in q and "changes" not in _stat_query('{__name__="x"}', "gauge", "x", "24h")


def test_what_the_agent_is_told(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.describe import _metric_lines
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    run, src = db.session.query(Run).first(), world["s_prom"]
    up = upsert(run, src, "metric", "", "ifHCInOctets", {"metric_type": "gauge", "stats": {
        "series": 4, "data_says": {"increases_only": 4314}}})
    level = upsert(run, src, "metric", "", "pg_stat_activity_count", {"metric_type": "gauge", "stats": {
        "series": 6, "min": 0, "max": 41, "avg": 12.5, "window": "24h", "data_says": {"goes_down": 1089, "changes": 2112}}})
    db.session.commit()
    a = "\n".join(_metric_lines(up, [], {}, None, None, False, src))
    assert "its values only increased over a day (4,314 changes, never down)" in a
    assert "promql_query increase(ifHCInOctets[1h])" in a and "never its value (a total since a restart)" in a
    b = "\n".join(_metric_lines(level, [], {}, None, None, False, src))
    assert "a level, not a count: its values go down as well as up (1,089 decreases in a day)" in b
    assert "never rate or increase" in b


def test_the_usual_latency_of_each_service_from_its_histogram(world):  # noqa: F811
    """Three full days before the data's last day: the median of each day's p50, p95 and requests per service (an
    incident day does not make the usual); the line says it is a usual, by which label, of which days."""
    from superset.extensions import db

    from supagent.knowledge import metricusual as MU
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    run, src = db.session.query(Run).first(), world["s_prom"]
    m = upsert(run, src, "metric", "", "http_server_request_duration_seconds_bucket", {
        "metric_type": "histogram", "stats": {"labels": ["le", "service_name", "job"], "data_from": "2026-09-23 17:03",
                                               "data_to_ms": 1790505780000}})          # 2026-09-27 11:03 UTC
    db.session.commit()
    assert [(x.name, s) for x, s in MU.histograms()] == [("http_server_request_duration_seconds_bucket", "service_name")]

    class S:
        def __init__(self, svc, values):
            self.labels, self.points = {"service_name": svc}, [(0, v) for v in values]

    asked = []

    class Client:
        @staticmethod
        def query_range(expr, start, end, step, timeout=None):
            asked.append((expr, start, end, step))
            if "histogram_quantile(0.5" in expr:
                return [S("shop-checkout", [0.45, 0.46, 2.1]), S("inventory", [0.026, 0.025, 0.027])]
            if "histogram_quantile(0.95" in expr:
                return [S("shop-checkout", [0.96, 0.97, 10.0]), S("inventory", [0.05, 0.049, float("nan")])]
            return [S("shop-checkout", [10005.9, 9900.9, 6996.4]), S("inventory", [10005.9, 9900.9, 6995.9])]

    class Conn:
        client = Client()

    u = MU.learn(Conn(), m, "service_name")
    assert (u["from"], u["to"], u["days"], u["label"]) == ("2026-09-24", "2026-09-26", 3, "service_name")
    assert asked[0][1:] == (1790294400000, 1790467200000, 86_400_000)                   # 25 Sep .. 27 Sep 00:00 UTC
    co = u["services"]["shop-checkout"]
    assert (co["p50_s"], co["p95_s"], co["requests_day"]) == (0.46, 0.97, 9900.9)        # the incident day: not usual
    assert u["services"]["inventory"]["p95_s"] == 0.0495                                  # (a day without a value left out)
    line = MU.line(u)
    assert line.startswith("usual (the median of the 3 days from 2026-09-24 to 2026-09-26, by service_name;")
    assert "shop-checkout: p50 460 ms, p95 970 ms, 9,901 requests a day" in line


def test_a_lone_count_is_not_a_family_part():
    """pg_stat_activity_count has no _sum nor _bucket: its type is asked of its samples (the name itself was taken
    for its sibling)."""
    from supagent.knowledge.learn_metrics import family_part

    names = {"pg_stat_activity_count", "jvm_gc_pause_seconds_count", "jvm_gc_pause_seconds_sum",
             "http_server_request_duration_seconds_bucket", "http_server_request_duration_seconds_count"}
    assert not family_part("pg_stat_activity_count", names)
    assert family_part("jvm_gc_pause_seconds_count", names) and family_part("jvm_gc_pause_seconds_sum", names)
    assert family_part("http_server_request_duration_seconds_count", names)
    assert not family_part("node_load1", names)


def test_the_value_of_a_metric_that_only_increases_is_never_summed(world):  # noqa: F811
    """SUM(value) of nginx_ingress_controller_requests (a request total read as a gauge: no _total, no metadata)
    gave 159 million requests for 77,676: refused, with the increase to count instead."""
    from superset.extensions import db

    from supagent.knowledge.experience import guard_sql
    from supagent.knowledge.store import upsert
    from supagent.models import Run

    run, src = db.session.query(Run).first(), world["s_prom"]
    upsert(run, src, "metric", "", "nginx_ingress_controller_requests", {"metric_type": "gauge", "stats": {
        "data_says": {"increases_only": 2779}}})
    upsert(run, src, "metric", "", "node_load1", {"metric_type": "gauge", "stats": {}})
    db.session.commit()
    why = guard_sql(world["metrics"], "SELECT SUM(value) FROM \"nginx_ingress_controller_requests\" "
                                      "WHERE service = 'frontend'")
    assert why.startswith("refused before running: nginx_ingress_controller_requests only increases")
    assert "sum(increase(nginx_ingress_controller_requests[1d]))" in why and "MAX(value) - MIN(value)" in why
    assert guard_sql(world["metrics"], "SELECT AVG(value) FROM \"node_load1\"") is None
    assert guard_sql(world["metrics"], "SELECT MAX(value) - MIN(value) FROM \"nginx_ingress_controller_requests\"") is None
