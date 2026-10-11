"""(0.10.7, obs7dev-m) "How many requests ended in an error ...?" was answered right in ten calls (budget six): the
dictionary's entry of the counter that counts them gave its result label the values of the hour sampled when learning
(ok, declined), error being only in an incident's hours; the agent concluded the counter could not count errors and
went to the logs. describe_data of one metric says the values of its small labels in all its data that the dictionary
lacks ("also in its data: error")."""
from __future__ import annotations

import types

from test_knowledge import world  # noqa: F401  (the fixture)


def test_the_label_line_says_the_values_of_its_whole_data(ctx):
    from supagent.knowledge.describe import _metric_lines
    from supagent.models import KObject

    m = KObject(kind="metric", name="zq_requests_total", metric_type="counter", stats={})
    result = KObject(kind="label", name="result", stats={"values": ["ok", "declined"]})
    zone = KObject(kind="label", name="zone", stats={})
    src = types.SimpleNamespace(id=-1, database_id=None)
    lines = _metric_lines(m, [result, zone], {}, None, None, True, src,
                          live={"result": ["ok", "declined", "error"], "zone": ["z1", "z2"]})
    labels = next(x for x in lines if x.strip().startswith("labels:"))
    assert "result: ok, declined (also in its data: error)" in labels
    assert "zone: (also in its data: z1, z2)" in labels                  # nothing learned: what the data holds
    before = _metric_lines(m, [result, zone], {}, None, None, True, src)
    assert "result: ok, declined" in "".join(before) and "also in its data" not in "".join(before)


def test_the_values_are_read_for_one_metric_only(ctx, monkeypatch):
    from supagent import tools

    class Conn:
        closed = 0

        def table_meta(self, name):
            return types.SimpleNamespace(labels=["result"]) if name == "zq_requests_total" else None

        def close(self):
            Conn.closed += 1

    monkeypatch.setattr(tools, "_metrics_database", lambda ref: object())
    monkeypatch.setattr(tools, "_promagg_connection", lambda db: Conn())
    monkeypatch.setattr(tools, "_metric_profile", lambda conn, name, labels:
                        {"result": ["ok", "declined", "error"], "__range__": ["2026-09-01 00:00", "2026-09-30 00:00"]})
    assert tools._label_values_of("zq_requests_total") == {"zq_requests_total": {"result": ["ok", "declined", "error"]}}
    assert tools._label_values_of("zq-logs") == {} and tools._label_values_of(None) == {}   # an index; no name
    assert Conn.closed == 2

    def broken(db):
        raise RuntimeError("no metrics database")

    monkeypatch.setattr(tools, "_promagg_connection", broken)
    assert tools._label_values_of("zq_requests_total") == {}             # not readable: the dictionary alone


def test_a_metric_found_by_the_search_says_the_values_of_its_whole_data(ctx, monkeypatch):
    """(obs7dev-s) the counter's piece said its result label held approved and declined: the errors were looked for
    in the logs and the traces first, five calls."""
    from test_judge_010 import piece

    from supagent import tools
    from supagent.knowledge import search as S

    found = piece("object:292")
    found.update({"kind": "metric", "title": "metric zq_authorizations_total",
                  "text": "metric zq_authorizations_total (counter)\nlabels: result (approved or declined): approved, "
                          "declined"})
    monkeypatch.setattr(S, "search", lambda q, k=None, kinds=None, **kw: [found])
    monkeypatch.setattr(tools, "_as_user", lambda: __import__("contextlib").nullcontext())
    monkeypatch.setattr(tools, "_label_values_of", lambda name: {name: {"result": ["approved", "declined", "error"],
                                                                         "zone": ["z1"]}})
    out = tools.search_knowledge("zq authorizations error result", kind="metric")
    assert out["results"][0]["text"].endswith("(also in its data: result: error; zone: z1)")
    monkeypatch.setattr(tools, "_label_values_of", lambda name: {})       # not readable: the piece as it was
    assert "also in its data" not in tools.search_knowledge("zq authorizations", kind="metric")["results"][0]["text"]


def test_the_prompts_block_and_a_topics_metrics_say_the_values_of_their_whole_data(ctx, monkeypatch):
    """(the class of obs7dev-s's W09.1) every place that shows a metric's labels to the agent says the values of
    their whole data: the prompt's knowledge block (its first metric pieces) and describe_data of a topic (its first
    metrics), as the search tool and describe_data of one metric do."""
    from test_judge_010 import piece

    from supagent import tools
    from supagent.knowledge import describe as D
    from supagent.knowledge import search as S

    found = piece("object:292")
    found.update({"kind": "metric", "title": "metric zq_authorizations_total",
                  "text": "metric zq_authorizations_total (counter)\nlabels: result: approved, declined"})
    monkeypatch.setattr(S, "search", lambda q, k=None, kinds=None, **kw: [found])
    monkeypatch.setattr(tools, "_as_user", lambda: __import__("contextlib").nullcontext())
    monkeypatch.setattr(tools, "_label_values_of", lambda name: {name: {"result": ["approved", "declined", "error"]}})
    block = S.knowledge_block("How many zq authorizations ended in an error?", set())
    assert "(also in its data: result: error)" in block


def test_a_topics_first_metrics_say_the_values_of_their_whole_data(world, monkeypatch):  # noqa: F811
    from supagent.knowledge.describe import describe

    calls: list = []

    def live(name):
        calls.append(name)
        return {name: {"mode": ["idle", "user", "steal"]}}

    from supagent.security import acting_as

    with acting_as("admin"):
        text = describe("cpu seconds per mode", None, live=live)
    assert "(also in its data: steal)" in text and calls == ["node_cpu_seconds_total"]
