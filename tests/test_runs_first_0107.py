"""(0.10.7) "What was the average duration of the jobs of an application on a day?" (then "and the longest one?"):
the data block listed the duration metrics around the index of the runs, one with an AI note "divide the sum by the
count", and the agent took the metric (an average over its samples) for the runs' average, then the longest from its
buckets. For statistics of single runs the index of the runs comes first, with a line saying what each gives."""
from __future__ import annotations


def test_the_runs_index_first_for_statistics_of_runs(ctx, monkeypatch):
    from supagent.knowledge import excluded, resolve

    class D:
        id, database_name, backend = 1, "Jobs", "osagg"

    class M:
        id, database_name, backend = 2, "Metrics", "promagg"

    cands = [{"kind": "metric", "name": "job_duration_seconds_sum", "database": M(), "metric_type": "counter",
              "about": "Sum of durations. Divide by the count metric to calculate the average job duration.",
              "ai": True},
             {"kind": "index", "name": "jobs", "database": D(), "time_field": "ts",
              "about": "Job executions, one document per job run: application, duration, status"}]
    monkeypatch.setattr(resolve, "resolve", lambda q: list(cands))
    monkeypatch.setattr(resolve, "values_lines", lambda q: [])
    monkeypatch.setattr(resolve, "_sql", lambda c: "SELECT ...")
    monkeypatch.setattr(excluded, "is_excluded", lambda *a: False)
    monkeypatch.setattr(excluded, "of_table", lambda *a: [])
    text = resolve.where_block("What was the average duration of the jobs of app A on 22 September?")
    assert text.index('index "jobs"') < text.index('metric "job_duration_seconds_sum"')
    assert "Statistics of single runs" in text
    other = resolve.where_block("How many jobs failed on 22 September?")
    assert "Statistics of single runs" not in other
    assert other.index('metric "job_duration_seconds_sum"') < other.index('index "jobs"')   # as ranked
