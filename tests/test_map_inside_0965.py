"""(0.9.6.5) A category drawn inside another on the System map (categories.inside, else the category a
categories.qualified one is named after): never inside itself nor in a loop; renamed and removed with the
category; display only: what the agent reads does not change."""

from __future__ import annotations

from test_brief import system  # noqa: F401  (the fixture: Billing = Invoicing + Payments, grid-a, ledger db)
from test_dictionary_080 import _client
from test_knowledge import world  # noqa: F401

API = "/supagent/admin/api/facets/categories"


def test_a_category_is_drawn_inside_another(system, app):  # noqa: F811
    from supagent import settings
    from supagent.knowledge import facets as F

    try:
        with app.app_context():
            settings.set_value("categories.qualified", {"service": "server"})
            assert F.inside() == {"service": "server"}                  # named after its server: inside it
        with _client(app, "admin") as c:
            r = c.post(API, json={"name": "server", "inside": "pool"}).get_json()
            assert {x["name"]: x["inside"] for x in r["categories"]}["server"] == "pool"
            loop = c.post(API, json={"name": "pool", "inside": "service"})  # service in server in pool: not both ways
            assert loop.status_code == 400 and "already" in loop.get_json()["error"]
            assert c.post(API, json={"name": "pool", "inside": "pool"}).status_code == 400
            assert c.post(API, json={"name": "pool", "inside": "nothing"}).status_code == 400
            assert c.post(API, json={"name": "service", "inside": ""}).status_code == 200   # a column of its own
            cats = {x["name"]: x for x in c.get("/supagent/dictionary/api/map").get_json()["categories"]}
            assert cats["server"]["inside"] == "pool" and cats["service"]["inside"] == ""
        with _client(app, "alice") as c:                            # who is not an admin: not changed
            assert c.post(API, json={"name": "service", "inside": "server"}).status_code == 403
        with app.app_context():
            assert F.inside() == {"server": "pool"}
            settings.set_value("categories.inside", {"server": "pool", "pool": "server"})   # a loop written by hand
            assert F.inside() == {}                                     # drawn as columns of their own
            settings.set_value("categories.inside", {"server": "pool"})
        with _client(app, "admin") as c:                            # renamed: the setting follows
            assert c.post(API, json={"name": "pool", "rename": "grid"}).status_code == 200
        with app.app_context():
            assert F.inside() == {"server": "grid", "service": "server"}     # (service: from categories.qualified)
            assert settings.get("categories.qualified") == {"service": "server"}
            F._rename_inside("grid", None, "admin")                   # removed: what named it goes
            assert F.inside() == {"service": "server"} and settings.get("categories.inside") == {}
        with _client(app, "admin") as c:
            assert c.post(API, json={"name": "grid", "rename": "pool"}).status_code == 200
    finally:
        with app.app_context():
            settings.set_value("categories.inside", None)
            settings.set_value("categories.qualified", None)


def test_what_the_agent_reads_does_not_change(system, app):  # noqa: F811
    from supagent import settings
    from supagent.knowledge import brief
    from supagent.knowledge import facets as F

    try:
        with app.app_context():
            brief._CACHE.update(stamp=None, graph=None)
            values, graph = F.system_map(), brief._graph()
            settings.set_value("categories.inside", {"server": "pool", "service": "server"})
            brief._CACHE.update(stamp=None, graph=None)
            assert F.inside() == {"server": "pool", "service": "server"}
            assert F.system_map() == values and brief._graph() == graph
    finally:
        with app.app_context():
            settings.set_value("categories.inside", None)
            brief._CACHE.update(stamp=None, graph=None)
