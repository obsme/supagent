"""(0.10.6) A metric's usage lines (how to compute it) are kept whole in the knowledge given with a question: the
window around the question's words cut "SQL: a counter: use the column rate or increase, never SUM" when the
labels' descriptions were long, and a count of requests was summed from the per-second rate."""

from __future__ import annotations

LONG = """metric zq_requests_total (counter, count)
Requests of the zq services per service, method and code (counter)
also called: requests, errors, 5xx
labels: service (Names the service that answered the request. It tells the services of the platform apart, each one with its own name and owner): zqa, zqb, zqc; code (The status code of the answer. 200 is a success, 4xx a client error, 5xx a server error that the team follows): 200, 404, 503
SQL: a counter: use the column rate (per second) or increase (per time bucket); value is cumulative, never SUM or AVG it
formulas (catalog): errors_5xx = SUM(increase) FILTER (WHERE code LIKE '5%')"""


def test_usage_lines_kept_whole(app):
    from supagent.knowledge.search import USAGE_CHARS, excerpt, usage_apart

    with app.app_context():
        _check(USAGE_CHARS, excerpt, usage_apart)


def _check(USAGE_CHARS, excerpt, usage_apart):  # noqa: N803
    body, usage = usage_apart(LONG)
    assert usage.startswith("SQL: a counter") and "errors_5xx = SUM(increase)" in usage and len(usage) <= USAGE_CHARS
    assert "SQL:" not in body and "formulas (catalog)" not in body and "labels: service" in body
    assert len(excerpt(body, "How many requests ended with a 503 error per service?", 450 - len(usage))) <= 460
    short = "metric zq_up (gauge)\nSQL: a gauge: AVG or MAX it"
    assert usage_apart(short) == (short, "")            # a piece that fits: unchanged
    assert usage_apart("metric zq_x\n" + "words " * 100) == ("metric zq_x\n" + "words " * 100, "")   # no usage line


def test_label_descriptions_give_their_room():
    """When the usage lines are cut, the room is taken from the labels' descriptions: the labels and values stay."""
    from supagent.knowledge.search import LABEL_ABOUT

    t = ("labels: service (Names the service that answered the request. It tells the services apart): zqa, zqb; "
         "code (The status code of the answer): 200, 503\nmetric zq_requests_total (counter, count)")
    out = LABEL_ABOUT.sub(r"\1", t)
    assert "labels: service: zqa, zqb; code: 200, 503" in out and "(counter, count)" in out
