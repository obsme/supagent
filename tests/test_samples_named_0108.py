"""(0.10.8) An answer on a gauge's data refused each new query that counted its samples (COUNT(*) AS sample_count with
its MIN and MAX), three refusals and thirteen calls for a simple question. A count its query names as samples runs;
a count named as what the question counts is still sent back."""

from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)

Q = "How many servers had blocked processes on 2 March?"


def test_a_count_named_as_samples_runs(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.experience import count_of_counter
    from supagent.knowledge.store import upsert

    upsert(world["run"], world["s_prom"], "metric", "", "node_procs_blocked", {"metric_type": "gauge",
                                                                              "stats": {"series": 4}})
    db.session.commit()
    metrics = world["metrics"]
    named = ("SELECT node, COUNT(*) AS sample_count, MIN(value) AS lo, MAX(value) AS hi FROM \"node_procs_blocked\" "
             "WHERE ts >= TIMESTAMP '2031-03-02 00:00' AND ts < TIMESTAMP '2031-03-03 00:00' GROUP BY node")
    assert count_of_counter(metrics, named, Q) is None
    assert count_of_counter(metrics, named.replace("AS sample_count", "AS points"), Q) is None
    counted = named.replace("AS sample_count", "AS servers")
    said = count_of_counter(metrics, counted, Q)
    assert said and said.startswith("tool error (not run: samples)")


def test_a_rate_summed_inside_a_case_is_no_count(world):  # noqa: F811
    from supagent.knowledge.experience import rate_as_count

    case = ("SELECT application, SUM(CASE WHEN code = '503' THEN rate ELSE 0 END) AS n FROM \"node_procs_blocked\" "
            "WHERE ts >= TIMESTAMP '2031-03-02 00:00' GROUP BY application")
    said = rate_as_count(world["metrics"], case, "How many requests ended with a 503 on 2 March, per application?")
    assert said and said.startswith("tool error (not run: rate)")
    assert rate_as_count(world["metrics"], case.replace("rate ELSE", "increase ELSE"), "How many requests?") is None
