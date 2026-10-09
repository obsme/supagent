"""0.9: check_health says of each breach whether it is new or happens in the same window on most of the previous
days (an alert that fires every night is not what changed today), and lists the new ones first."""

from __future__ import annotations

import datetime as dt
import types

from test_knowledge import world  # noqa: F401  (the fixture)

DAY = 86_400_000
T0 = int(dt.datetime(2026, 9, 24, 2, 0, tzinfo=dt.timezone.utc).timestamp() * 1000)


class _Series:
    def __init__(self, node: str, values: list[float], start: int, step: int) -> None:
        self.labels = {"__name__": "mem_available_pct", "node": node}
        self.points = [(start + i * step, v) for i, v in enumerate(values)]


class _Conn:
    zone = types.SimpleNamespace(utc_ms=lambda d: int(d.replace(tzinfo=dt.timezone.utc).timestamp() * 1000),
                                 local=lambda ms: dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).replace(tzinfo=None))

    def __init__(self, no_data_days=()) -> None:
        self.calls, self.no_data_days = [], set(no_data_days)
        self.client = types.SimpleNamespace(query_range=self.query_range)

    def query_range(self, expr, start, end, step):
        k = round((T0 - (start - step)) / DAY)             # 0 = the window asked, 1.. = the days before
        self.calls.append((expr, k))
        if k in self.no_data_days:
            return []
        n = (end - start) // step + 1
        low, fine = [5.0] * n, [60.0] * n
        return [_Series("srv-noisy", low, start, step),                    # short of memory every night
                _Series("srv-new", low if k == 0 else fine, start, step),  # only tonight
                _Series("srv-ok", fine, start, step)]

    def close(self):
        pass


def _catalog(monkeypatch, tools):
    monkeypatch.setattr(tools, "_catalog", lambda: {"checks": {
        "memory_low": {"promql": "mem_available_pct", "below": 12, "for": "10m", "unit": "%",
                       "description": "memory almost full"},
        "cpu_saturated": {"promql": "cpu_pct", "above": 500, "description": "never breached here"}}})


def test_a_breach_is_new_or_usual(world, monkeypatch):  # noqa: F811
    from supagent import tools
    from supagent.security import acting_as

    conn = _Conn()
    _catalog(monkeypatch, tools)
    monkeypatch.setattr(tools, "_metrics_database", lambda ref: world["metrics"])
    monkeypatch.setattr(tools, "_promagg_connection", lambda database: conn)
    with acting_as("admin"):
        out = tools.check_health("2026-09-24 02:00", "2026-09-24 05:00")
    assert [(b["labels"]["node"], b["earlier_days"], b.get("usual", False)) for b in out["breaches"]] == [
        ("srv-new", "0 of the 7 previous days", False), ("srv-noisy", "7 of the 7 previous days", True)]
    assert out["note"].startswith("1 of the 2 breach(es) also happen in this window on most of the previous days")
    # only the check that breached is run again on the earlier days
    assert sorted(k for expr, k in conn.calls if "mem_available_pct" in expr) == [0, 1, 2, 3, 4, 5, 6, 7]
    assert [k for expr, k in conn.calls if "cpu_pct" in expr] == [0]


def test_days_without_data_do_not_count_and_no_breach_costs_nothing(world, monkeypatch):  # noqa: F811
    from supagent import tools
    from supagent.security import acting_as

    conn = _Conn(no_data_days=(2, 3, 4, 5, 6, 7))                 # one earlier day only: too few to call anything usual
    _catalog(monkeypatch, tools)
    monkeypatch.setattr(tools, "_metrics_database", lambda ref: world["metrics"])
    monkeypatch.setattr(tools, "_promagg_connection", lambda database: conn)
    with acting_as("admin"):
        out = tools.check_health("2026-09-24 02:00", "2026-09-24 05:00")
        quiet = tools.check_health("2026-09-24 02:00", "2026-09-24 05:00", checks=["cpu_saturated"])
    noisy = next(b for b in out["breaches"] if b["labels"]["node"] == "srv-noisy")
    assert noisy["earlier_days"] == "1 of the 1 previous days" and "usual" not in noisy and out["note"] == ""
    assert quiet["note"] == "no breach" and [k for expr, k in conn.calls if "cpu_pct" in expr] == [0, 0]


class _SpikeConn(_Conn):
    """A load that crosses its limit for one step only: no breach for a check that needs 10 minutes."""

    def query_range(self, expr, start, end, step):
        self.calls.append((expr, 0))
        n = (end - start) // step + 1
        spike = [1.0] * n
        spike[n // 2] = 2.9
        s = _Series("srv-a", spike, start, step)
        s.labels = {"__name__": "node_load1", "node": "srv-a"}
        other = _Series("srv-b", [1.0] * n, start, step)
        other.labels = {"__name__": "node_load1", "node": "srv-b"}
        return [s, other]


def test_a_brief_crossing_of_a_named_server_is_shown_not_counted(world, monkeypatch):  # noqa: F811
    """(0.10.4) The team's check needs 10 minutes above 2; the server went to 2.9 for one step: no breach, but the
    crossing is given (worst value and time) when the servers are named: a System map link may call any load above 2
    too high."""
    from supagent import tools
    from supagent.security import acting_as

    from supagent import settings

    monkeypatch.setattr(tools, "_catalog", lambda: {"checks": {
        "load_high": {"promql": "node_load1", "above": 2, "for": "10m", "description": "load too high"}}})
    monkeypatch.setattr(tools, "_metrics_database", lambda ref: world["metrics"])
    monkeypatch.setattr(tools, "_promagg_connection", lambda database: _SpikeConn())
    with acting_as("admin"):
        off = tools.check_health("2026-09-24 02:00", "2026-09-24 05:00", entities=["srv-a", "srv-b"])
        settings.set_value("tools.brief_crossings", True)    # (off by default in 0.10.4: not measured enough)
        try:
            named = tools.check_health("2026-09-24 02:00", "2026-09-24 05:00", entities=["srv-a", "srv-b"])
            everyone = tools.check_health("2026-09-24 02:00", "2026-09-24 05:00")
        finally:
            settings.set_value("tools.brief_crossings", False)
    assert "brief_crossings" not in off and off["note"] == "no breach"
    assert named["breach_count"] == 0 and [(x["labels"]["node"], x["worst"]) for x in named["brief_crossings"]] == [
        ("srv-a", 2.9)]
    assert "brief_crossings: 1 threshold(s) crossed" in named["note"]
    assert "brief_crossings" not in everyone and everyone["note"] == "no breach"     # only for named entities
