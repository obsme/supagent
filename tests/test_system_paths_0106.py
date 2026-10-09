"""(0.10.6) system_links with a depth gives the map's paths in one call: what the parts lead to (each step a link,
where the last one runs) and what leads to them (the impact of a failure), without circles."""

from __future__ import annotations


def test_the_paths_from_and_to_a_part(app):
    from superset.extensions import db

    from supagent.knowledge import brief
    from supagent.models import Facet, Link

    with app.app_context():
        names = ("zqvip", "zqweb", "zqapi", "zqcache", "zqdb", "zqapp-01")
        made = [Facet(facet="application" if n in ("zqweb", "zqapi") else "component", value=n, status="approved",
                      source="admin") for n in names]
        db.session.add_all(made)
        db.session.flush()
        r = {f.value: f"facet:{f.id}" for f in made}
        links = [Link(a_ref=r["zqvip"], b_ref=r["zqweb"], kind="routes_to", status="approved", source="docs"),
                 Link(a_ref=r["zqweb"], b_ref=r["zqapi"], kind="calls", status="approved", source="docs"),
                 Link(a_ref=r["zqapi"], b_ref=r["zqcache"], kind="depends_on", status="approved", source="docs"),
                 Link(a_ref=r["zqapi"], b_ref=r["zqdb"], kind="reads_from", status="approved", source="docs"),
                 Link(a_ref=r["zqdb"], b_ref=r["zqapi"], kind="sends_to", status="approved", source="docs"),   # a circle
                 Link(a_ref=r["zqdb"], b_ref=r["zqapp-01"], kind="runs_on", status="approved", source="docs")]
        db.session.add_all(links)
        db.session.commit()
        brief._CACHE["stamp"] = None
        try:
            one = brief.links_of(["zqapi"])
            assert "paths" not in one                                        # depth 1: as before
            res = brief.links_of(["zqapi"], depth=3)
            down, up = res["paths"]["leads_to"], res["paths"]["led_from"]
            assert "zqapi reads from zqdb (runs on zqapp-01)" in down and "zqapi depends on zqcache" in down
            assert "zqweb calls zqapi > zqvip routes to zqweb" in up or any(
                c.startswith("zqweb calls zqapi > zqvip") for c in up), up
            assert all(c.count("zqapi") <= 2 for c in down + up)             # no circle walked
        finally:
            ids = [f.id for f in made]
            db.session.query(Link).filter(Link.a_ref.in_([f"facet:{i}" for i in ids])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            brief._CACHE["stamp"] = None


def test_what_a_server_down_reaches(app):
    """A server's failure reaches what runs on it and on the group it is part of, and what depends on those."""
    from superset.extensions import db

    from supagent.knowledge import brief
    from supagent.models import Facet, Link

    from supagent import settings

    with app.app_context():
        before = settings.get("categories.custom")
        settings.set_value("categories.custom", ["server"])
        kinds = {"zqweb2": "application", "zqapi2": "application", "zqpg2": "component", "zqdbgrp": "server",
                 "zqdb-01": "server", "zqlog2": "component", "zqdb-02": "server"}
        made = [Facet(facet=c, value=n, status="approved", source="admin") for n, c in kinds.items()]
        db.session.add_all(made)
        db.session.flush()
        r = {f.value: f"facet:{f.id}" for f in made}
        links = [Link(a_ref=r["zqweb2"], b_ref=r["zqapi2"], kind="calls", status="approved", source="docs"),
                 Link(a_ref=r["zqapi2"], b_ref=r["zqpg2"], kind="reads_from", status="approved", source="docs"),
                 Link(a_ref=r["zqpg2"], b_ref=r["zqdbgrp"], kind="runs_on", status="approved", source="docs"),
                 Link(a_ref=r["zqlog2"], b_ref=r["zqdb-01"], kind="runs_on", status="approved", source="docs"),
                 Link(a_ref=r["zqdb-01"], b_ref=r["zqdbgrp"], kind="part_of", status="approved", source="docs"),
                 Link(a_ref=r["zqlog2"], b_ref=r["zqdb-02"], kind="runs_on", status="approved", source="docs"),
                 Link(a_ref=r["zqdb-02"], b_ref=r["zqdbgrp"], kind="part_of", status="approved", source="docs")]
        db.session.add_all(links)
        db.session.commit()
        brief._CACHE["stamp"] = None
        try:
            one = brief.links_of(["zqdb-01"])["paths"]["led_from"]        # a server: its impact at depth 1 too
            assert any("zqapi2 reads from zqpg2" in c for c in one), one
            assert "paths" not in brief.links_of(["zqapi2"])               # a part at depth 1: as before
            up = brief.links_of(["zqdb-01"], depth=3)["paths"]["led_from"]
            assert "zqlog2 runs on zqdb-01" in up
            assert any(c.startswith("zqdb-01 is part of zqdbgrp > zqpg2 runs on zqdbgrp > zqapi2 reads from zqpg2")
                       for c in up), up
            assert any("zqweb2 calls zqapi2" in c for c in up), up       # the group's step is free of the depth
            down = brief.links_of(["zqdb-01"])["if_it_fails"]["zqdb-01"]   # in the words of an answer
            assert down["runs_on_it"] == ["zqlog2 (component; also runs on zqdb-02)"]   # it may go on there
            assert list(down["runs_on_its_group (may go on on the group's other servers)"].values()) == [
                ["zqpg2 (component)"]]
            assert down["then_through_them"] == ["zqapi2 (application) reads from zqpg2"]
            assert down["and_further"] == ["zqweb2 (application) calls zqapi2"]
            assert "if_it_fails" not in brief.links_of(["zqapi2"], depth=2)  # not a server
            pg_on_member = Link(a_ref=r["zqpg2"], b_ref=r["zqdb-01"], kind="runs_on", status="approved", source="docs")
            db.session.add(pg_on_member)
            db.session.commit()
            brief._CACHE["stamp"] = None
            grp = brief.links_of(["zqdbgrp"])["if_it_fails"]["zqdbgrp"]      # a group: what runs on its servers too
            assert grp["runs_on_it"] == ["zqpg2 (component)"], grp           # its own member is no elsewhere
            one = brief.links_of(["zqdb-01"])["if_it_fails"]["zqdb-01"]
            assert "zqpg2 (component)" in one["runs_on_it"], one              # nor its own group
            db.session.delete(pg_on_member)
            db.session.commit()
            brief._CACHE["stamp"] = None
            grp = brief.links_of(["zqdbgrp"])["if_it_fails"]["zqdbgrp"]
            assert grp["runs_on_it"] == ["zqpg2 (component)"] and grp["runs_on_its_servers"] == {
                "zqdb-01": ["zqlog2 (component)"], "zqdb-02": ["zqlog2 (component)"]}    # each server's own
        finally:
            ids = [f.id for f in made]
            db.session.query(Link).filter(Link.a_ref.in_([f"facet:{i}" for i in ids])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            settings.set_value("categories.custom", before)
            brief._CACHE["stamp"] = None


def test_a_category_name_lists_its_values_and_the_search_has_the_category(app):
    """The agent goes on from a category ("which applications...?"): system_links of its name lists its values; the
    search has a piece per category with its values."""
    from superset.extensions import db

    from supagent.knowledge import brief
    from supagent.knowledge.index import _map_pieces
    from supagent.models import Facet

    with app.app_context():
        made = [Facet(facet="application", value=n, status="approved", source="admin") for n in ("0zqa1", "0zqa2")]
        db.session.add_all(made)
        db.session.commit()
        brief._CACHE["stamp"] = None
        try:
            res = brief.links_of(["applications"])
            listed = res["categories_listed"]["application"]
            assert {"0zqa1", "0zqa2"} <= set(listed["values"]) and listed["count"] >= 2 and not res.get("not_in_the_map")
            assert brief.category_named("the servers", brief._graph()) in (None, "server")
            piece = next(p for p in _map_pieces() if p["ref"] == "map:category:application")
            assert "0zqa1" in piece["text"] and "0zqa2" in piece["text"] and piece["kind"] == "map"
        finally:
            db.session.query(Facet).filter(Facet.id.in_([f.id for f in made])).delete(synchronize_session=False)
            db.session.commit()
            brief._CACHE["stamp"] = None

