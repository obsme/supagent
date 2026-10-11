"""(0.10.8) "How many orders were placed between 08:00 and 08:45?" asked as increase(x[45m]) over 08:00..08:45: a range
of points, each looking 45 minutes back (before 08:00 too), and the answer said a busier hour's figure. A windowed
function whose window is the whole period asked is one instant at the period's end."""

from __future__ import annotations

import datetime as dt
import types

from test_knowledge import world  # noqa: F401  (the fixture)


class _Conn:
    zone = types.SimpleNamespace(utc_ms=lambda d: int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000),
                                 local=lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).replace(tzinfo=None))

    def __init__(self) -> None:
        self.calls = []
        self.client = types.SimpleNamespace(query_range=self.query_range, query=self.query)

    def _one(self, at):
        return [types.SimpleNamespace(labels={"__name__": "orders_total", "shop": "s1"}, points=[(at, 11.0)])]

    def query_range(self, expr, start, end, step):
        self.calls.append("range")
        return self._one(end)

    def query(self, expr, at):
        self.calls.append("instant")
        return self._one(at)

    def list_tables(self):
        return ["orders_total"]

    def close(self):
        pass


def _run(world, monkeypatch, expr):  # noqa: F811
    from supagent import tools
    from supagent.security import acting_as

    conn = _Conn()
    monkeypatch.setattr(tools, "_metrics_database", lambda ref: world["metrics"])
    monkeypatch.setattr(tools, "_promagg_connection", lambda database: conn)
    with acting_as("admin"):
        out = tools.promql_query(expr, start="2031-03-02 08:00", end="2031-03-02 08:45")
    return out, conn.calls


def test_a_window_as_long_as_the_period_is_read_at_its_end(world, monkeypatch):  # noqa: F811
    from supagent.tools import WINDOW_NOTE

    out, calls = _run(world, monkeypatch, 'sum(increase(orders_total{state="placed"}[45m]))')
    assert calls[0] == "instant" and out["step"] == "instant" and out["note"] == WINDOW_NOTE
    assert out["start"] == out["end"] == "2031-03-02 08:45"


def test_other_windows_stay_a_range(world, monkeypatch):  # noqa: F811
    out, calls = _run(world, monkeypatch, "sum(rate(orders_total[5m]))")
    assert calls[0] == "range" and "note" not in out
    out, calls = _run(world, monkeypatch, "orders_total")
    assert calls[0] == "range" and "note" not in out
