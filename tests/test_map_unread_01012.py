"""(0.10.12) A question of how parts are linked, answered from an inventory table with no system_links call, is sent
back to read the System map ("which applications depend on them?" missed a link only the map has). A figure asked
("which team had the most breaches?", "how many ...?") answered from the data is not."""
from __future__ import annotations

from supagent.agent import Agent

SQL = [{"tool": "execute_sql", "called": "execute_sql", "status": "done", "args": {"sql": "SELECT name, depends_on FROM assets"},
        "result": '{"success": true, "rows": [{"name": "app-a", "depends_on": "store-1"}]}'}]


def _agent(monkeypatch):
    a = object.__new__(Agent)
    a.names = {"system_links", "execute_sql"}
    monkeypatch.setattr(Agent, "_specs_for", lambda self, q: [{"function": {"name": "system_links"}}])
    monkeypatch.setattr(Agent, "_investigating", lambda self, q: False)
    return a


def test_links_asked_and_only_a_table_read(ctx, monkeypatch):
    a = _agent(monkeypatch)
    assert a._map_unread("If rack r1 loses power, which data stores go down, and which applications depend on them?",
                         "store-1 goes down; app-a depends on it.", SQL)


def test_a_figure_asked_from_the_data(ctx, monkeypatch):
    a = _agent(monkeypatch)
    assert not a._map_unread("Which team had the most breaches among them?", "Team blue, 14 breaches.", SQL)
    assert not a._map_unread("How many applications depend on store-1?", "3 applications.", SQL)


def test_the_map_read(ctx, monkeypatch):
    a = _agent(monkeypatch)
    read = SQL + [{"tool": "system_links", "status": "done", "args": {}, "result": "store-1 <- app-a"}]
    assert not a._map_unread("Which applications depend on store-1?", "app-a depends on it.", read)
