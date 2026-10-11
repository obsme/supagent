"""(0.10.7) What the failure of a place that holds servers reaches (a rack: "if it loses power, which stores go down,
which applications depend on them?" had only the rack's parts, and the impact of three of its servers per call):
its servers, what runs only on them (goes down with it), what runs on other servers too (may go on), then what
depends on those; what uses a server itself (a database archiving its WAL to it); a person's link said with its own
words, and one that only looks at a part (a dashboard that shows it) not taken for a use. A part's own links read
"depends on", not "depend ons"."""

from __future__ import annotations


def test_a_rack_down_and_what_uses_a_server(app):
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import brief
    from supagent.models import Facet, Link

    with app.app_context():
        before = settings.get("categories.custom")
        settings.set_value("categories.custom", ["server", "rack", "switch", "switch port", "cache", "dashboard",
                                                 "database"])
        kinds = {"zqrack": "rack", "zqs-01": "server", "zqs-02": "server", "zqs-99": "server", "zqtor": "switch",
                 "zqtor p1": "switch port", "zqcache": "cache", "zqbroker": "component", "zqapp": "application",
                 "zqweb": "application", "zqdash": "dashboard", "zqdb": "database", "zqvm-01": "server",
                 "zqpay": "application", "zqcore p2": "switch port"}
        made = [Facet(facet=c, value=n, status="approved", source="admin") for n, c in kinds.items()]
        db.session.add_all(made)
        db.session.flush()
        r = {f.value: f"facet:{f.id}" for f in made}

        def ln(a, kind, b, note=None):
            return Link(a_ref=r[a], b_ref=r[b], kind=kind, note=note, status="approved", source="docs")

        links = [ln("zqs-01", "part_of", "zqrack"), ln("zqs-02", "part_of", "zqrack"), ln("zqtor", "part_of", "zqrack"),
                 ln("zqtor p1", "part_of", "zqtor"), ln("zqs-01", "link:aa000001", "zqtor p1", "connects to"),
                 ln("zqcache", "runs_on", "zqs-01"), ln("zqbroker", "runs_on", "zqs-02"),
                 ln("zqbroker", "runs_on", "zqs-99"), ln("zqapp", "depends_on", "zqcache"),
                 ln("zqweb", "calls", "zqapp"), ln("zqdash", "link:aa000002", "zqcache", "shows"),
                 ln("zqdb", "link:aa000003", "zqs-02", "archives WAL to"),
                 ln("zqvm-01", "runs_on", "zqs-01"), ln("zqpay", "runs_on", "zqvm-01"),   # a VM on a server of it
                 ln("zqtor", "link:aa000004", "zqcore p2", "uplinked to"), ln("zqs-02", "link:aa000005", "zqdash",
                                                                               "owned by")]   # outside: an uplink
        db.session.add_all(links)
        db.session.commit()
        brief._CACHE["stamp"] = None
        try:
            rack = brief.links_of(["zqrack"])["if_it_fails"]["zqrack"]
            assert rack["servers_in_it"].startswith("2: ")
            assert rack["goes_down_with_it (runs only on its servers)"] == [
                "zqcache (cache) on zqs-01", "zqvm-01 (server) on zqs-01", "zqpay (application) on zqvm-01"]
            assert rack["may_go_on (runs on other servers too)"] == [
                "zqbroker (component) on zqs-02; also runs on zqs-99"]
            assert "zqapp (application) depends on zqcache" in rack["then_through_them"]
            assert "zqweb (application) calls zqapp" in rack["and_further"]
            said = str(rack)
            assert "zqdash" not in said                                  # it shows the cache: not a use
            assert rack["uses_it"] == ["zqdb (database) archives WAL to zqs-02"]   # what uses one of its servers
            assert rack["it_depends_on (outside it)"] == ["zqtor (switch) uplinked to zqcore p2 (switch port)"]
            server = brief.links_of(["zqs-02"])["if_it_fails"]["zqs-02"]
            assert "zqdb (database) archives WAL to zqs-02" in server["uses_it"]
            assert "depends on" in brief.links_of(["zqapp"])["parts"][0]["it"]   # not "depend ons"
            assert "zqcache" not in brief.links_of(["zqapp"]).get("if_it_fails", {})   # an application: no impact
        finally:
            ids = [f.id for f in made]
            db.session.query(Link).filter(Link.a_ref.in_([f"facet:{i}" for i in ids])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            settings.set_value("categories.custom", before)
            brief._CACHE["stamp"] = None
