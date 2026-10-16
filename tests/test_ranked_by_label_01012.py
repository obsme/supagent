"""(0.10.12) A query that keeps its first rows ordered by a label it groups by, not by the figure it computes, is sent
back before it runs: "ORDER BY 1 ASC LIMIT 1" over (node, MIN(value)) gave the first server by name for "the server
with the least available memory". A time bucket, an order by the figure, a long list: left alone."""
from __future__ import annotations

from supagent.knowledge.sqllint import ranked_by_label, ranked_refusal

BY_NAME = 'SELECT "host", MIN(value) AS low FROM "mem_available" WHERE ts >= \'2031-03-02\' GROUP BY 1 ORDER BY 1 ASC LIMIT 1'


def test_first_rows_by_the_label():
    assert ranked_by_label(BY_NAME) == ("host", 1)
    assert ranked_by_label('SELECT app, COUNT(*) AS n FROM jobs GROUP BY app ORDER BY app LIMIT 3') == ("app", 3)


def test_left_alone():
    assert ranked_by_label('SELECT "host", MIN(value) AS low FROM t GROUP BY 1 ORDER BY 2 ASC LIMIT 1') is None
    assert ranked_by_label('SELECT "host", MIN(value) AS low FROM t GROUP BY 1 ORDER BY low ASC LIMIT 1') is None
    assert ranked_by_label('SELECT day, SUM(x) AS s FROM t GROUP BY day ORDER BY day LIMIT 3') is None
    assert ranked_by_label('SELECT app, COUNT(*) AS n FROM t GROUP BY app ORDER BY app LIMIT 50') is None
    assert ranked_by_label('SELECT app, region FROM t ORDER BY app LIMIT 1') is None


def test_refusal_text():
    said = ranked_refusal("execute_sql", {"request": {"database_id": 1, "sql": BY_NAME}})
    assert said and "ordered by host" in said and "send this same call again unchanged" in said
    assert ranked_refusal("execute_sql", {"sql": 'SELECT "host", MIN(value) AS low FROM t GROUP BY 1 ORDER BY 2 LIMIT 1'}) is None
