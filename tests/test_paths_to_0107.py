"""(0.10.7) "What does a request to the site go through before it reaches the payment gateway?": system_links with
`to` gives the routes from a part to another, each step a link, the shortest first, distinct routes only (a route
that is another one with a detour is left out), two links between the same parts said together."""

from __future__ import annotations


def test_the_routes_from_a_part_to_another(app):
    from superset.extensions import db

    from supagent.knowledge import brief
    from supagent.models import Facet, Link

    with app.app_context():
        names = ("zrsite", "zrvip", "zredge", "zrweb", "zrcart", "zrpay", "zrgw", "zrapi", "zrdash")
        made = [Facet(facet="application", value=n, status="approved", source="admin") for n in names]
        db.session.add_all(made)
        db.session.flush()
        r = {f.value: f"facet:{f.id}" for f in made}

        def ln(a, kind, b, note=None):
            return Link(a_ref=r[a], b_ref=r[b], kind=kind, note=note, status="approved", source="docs")

        links = [ln("zrsite", "link:bb000001", "zrvip", "resolves to"), ln("zrvip", "link:bb000002", "zredge", "routes to"),
                 ln("zrvip", "calls", "zredge"), ln("zredge", "calls", "zrapi"), ln("zrapi", "calls", "zrgw"),
                 ln("zrapi", "calls", "zrpay"), ln("zredge", "calls", "zrweb"), ln("zrweb", "calls", "zrcart"),
                 ln("zrcart", "calls", "zrpay"), ln("zrpay", "calls", "zrgw"),
                 ln("zrdash", "link:bb000003", "zrgw", "shows")]
        db.session.add_all(links)
        db.session.commit()
        brief._CACHE["stamp"] = None
        try:
            got = brief.links_of(["zrsite"], to="zrgw")["paths_to"]["zrgw"]
            assert got[0] == ("zrsite resolves to zrvip > zrvip routes to / calls zredge > zredge calls zrapi > "
                              "zrapi calls zrgw")
            assert any("zredge calls zrweb > zrweb calls zrcart > zrcart calls zrpay > zrpay calls zrgw" in p
                       for p in got), got
            assert not any("zrapi calls zrpay" in p for p in got)       # a detour of the first route
            assert brief.links_of(["zrgw"], to="zrsite")["paths_to"]["zrsite"].startswith("no path")
            both = brief.links_of(["zrsite", "zrpay"], to="zrgw")["paths_to"]["zrgw"]   # from each named part apart:
            assert both["from zrpay"] == ["zrpay calls zrgw"]                          # a direct link hides no route
            assert any("zrweb calls zrcart" in p for p in both["from zrsite"]), both
            assert brief.links_of(["zrsite"], to="zrnowhere")["paths_to"] == {"zrnowhere": "not in the map"}
            deep = brief.links_of(["zrsite", "zrpay"], depth=3, to="zrgw")    # (obs7dev: after the parts and the
            assert list(deep)[0] == "paths_to"                                # chains every way, past the result's
            assert all(len(v) <= brief.TO_CHAINS + 1 for v in (deep.get("paths") or {}).values())   # size: unread)
            nowhere = brief.links_of(["zrsite"], depth=3, to="zrnowhere")                # a name not in the map:
            assert list(nowhere)[0] != "paths_to" and "paths_to" in nowhere            # no route first, nothing cut
        finally:
            ids = [f.id for f in made]
            db.session.query(Link).filter(Link.a_ref.in_([f"facet:{i}" for i in ids])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
            brief._CACHE["stamp"] = None


def test_a_question_of_what_a_request_goes_through_gets_the_note():
    from supagent.agent import ROUTE_ASKED

    assert ROUTE_ASKED.search("What does a request to the site go through before it reaches the gateway?")
    assert ROUTE_ASKED.search("How does the mobile app reach the database?")
    assert not ROUTE_ASKED.search("How many requests failed yesterday?")
