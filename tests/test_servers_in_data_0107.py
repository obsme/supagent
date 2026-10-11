"""(0.10.7) "Which database user and which application held the long transaction?": the database's own logs on its
server named them; the answer said no data held them. The picture says where the servers a part runs on are in the
data (the fields that hold their names)."""
from __future__ import annotations


def test_where_the_servers_a_part_runs_on_are(monkeypatch):
    from supagent.knowledge import brief, valueindex

    g = {"values": {1: {"id": 1, "cat": "database", "name": "db1", "parents": []},
                    2: {"id": 2, "cat": "server", "name": "host-a", "parents": []},
                    3: {"id": 3, "cat": "server group", "name": "grp", "parents": []},
                    4: {"id": 4, "cat": "server", "name": "host-b", "parents": [3]}},
         "children": {3: [4]}, "out": {1: [("runs_on", 2, ""), ("runs_on", 3, "")]}, "in": {}}
    seen = []

    def places(names):
        seen.extend(names)
        return [{"kind": "field", "name": "host.name", "database": "Logs", "written": names[0], "of": ["logs-*"],
                 "count": 1}] if names == ["host-a"] else []
    monkeypatch.setattr(valueindex, "places", places)
    line = brief._servers_in_data([1], g)
    assert line == ('- Where the servers they run on are in the data (their own logs and records): host-a: field '
                    '"host.name" of logs-* (Logs).')
    assert seen == ["host-a"]                          # a group of servers is not a server of its own
