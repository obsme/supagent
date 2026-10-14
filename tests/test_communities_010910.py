"""(0.10.10, the owner's request of 13 October: the full picture of the System map) What a part is made of, as pages
and tables write it (a module of a service, a service made of modules, a module's service in a table of modules);
the communities of the map (a system and its parts with what mostly it uses, a place and its hosts, what holds them,
the teams), their facts pages, and the map-wide questions answered from them."""

from __future__ import annotations

import pytest

PFX = "zqm"


class _Names:
    hosts: dict = {}


@pytest.mark.parametrize("sentence,want", [
    ("orders-api is a microservice of the Order Desk application.", [("orders-api", "Order Desk")]),
    ("Order Desk (OD) is an application of the retail business line.", [("Order Desk", "retail")]),
    ("rate-worker is a module of the rating hub platform service.", [("rate-worker", "rating hub")]),
    ("Order Desk is made of the microservices orders-api, orders-ui and orders-sync.",
     [("orders-api", "Order Desk"), ("orders-ui", "Order Desk"), ("orders-sync", "Order Desk")]),
    ("Applications of retail: order desk, Stock Keeper.", [("order desk", "retail"), ("Stock Keeper", "retail")]),
    ("orders-sync est un module de Order Desk.", [("orders-sync", "Order Desk")]),
    ("orders-ui fait partie du service Order Desk.", [("orders-ui", "Order Desk")]),
    ("orders-api is part of Order Desk.", [("orders-api", "Order Desk")]),
    ("orders-api is not part of Order Desk.", []),                     # denied
    ("The ops crew is a member of the platform team.", []),            # a team owns, it holds no parts
    ("This is part of the problem.", []),
])
def test_what_a_part_is_part_of(sentence, want):
    import re

    from supagent.knowledge.understand import _memberships

    found = [(m.start(), m.group(0), m.group(0)) for m in re.finditer(r"[a-z]+-[a-z]+", sentence)]
    assert _memberships(sentence, found, _Names(), unit_part="") == want


def test_a_label_list_belongs_to_its_page():
    from supagent.knowledge.understand import _memberships

    s = "Modules: orders-api, orders-ui."
    found = [(9, "orders-api", "orders-api"), (21, "orders-ui", "orders-ui")]
    assert _memberships(s, found, _Names(), unit_part="Order Desk") == [("orders-api", "Order Desk"),
                                                                        ("orders-ui", "Order Desk")]


def test_it_is_the_part_the_page_is_about():
    import re

    from supagent.knowledge.understand import _memberships

    s = "It consists of the rooms par1-room-1, par1-room-2."
    found = [(m.start(), m.group(0), m.group(0)) for m in re.finditer(r"par1-room-\d", s)]
    assert _memberships(s, found, _Names(), unit_part="dc-par1") == [("par1-room-1", "dc-par1"),
                                                                     ("par1-room-2", "dc-par1")]
    assert _memberships(s, found, _Names(), unit_part="") == []     # no page's part: nobody
    s2 = "It is a module of Order Desk."
    assert _memberships(s2, [], _Names(), unit_part="orders-api") == [("orders-api", "Order Desk")]


def test_a_table_of_modules_says_their_service_and_what_they_read_and_write(ctx):
    from supagent.knowledge.understand import Names, discover, facts_of

    text = ("| Module | Service | Writes | Reads |\n| --- | --- | --- | --- |\n"
            "| zqm-api | Order Desk | zqm.order.created | - |\n| zqm-sync | Order Desk | - | zqm.order.created |\n")
    hosts_text = "| Host | Service |\n| --- | --- |\n| zqm-vm-01 | zqm-api |\n"
    names = Names()
    names.add_part("zqm-api")
    names.add_part("zqm-sync")

    def facts(body):
        u = {"ukey": "page:1", "path": "", "kind": "page", "title": "Catalog", "text": body, "meta": {}}
        u["found"] = discover(u)
        return {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, None, names, {})}

    got = facts(text)
    assert ("zqm-api", "part_of", "Order Desk") in got and ("zqm-sync", "part_of", "Order Desk") in got
    assert ("zqm-api", "sends_to", "zqm.order.created") in got and ("zqm-sync", "reads_from", "zqm.order.created") in got
    assert not any(v == "part_of" for _s, v, _o in facts(hosts_text))     # a table of hosts: no whole


def _clean(db):
    from supagent.models import Facet, Link

    db.session.rollback()
    ids = [i for (i,) in db.session.query(Facet.id).filter(Facet.value.ilike(PFX + "%"))]
    refs = [f"facet:{i}" for i in ids]
    if ids:
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()


@pytest.fixture()
def landscape(ctx, monkeypatch):
    """A service of two modules on a group of two hosts, its store and its stream; another service reading the
    stream; a team owning the first service; a domain holding both."""
    from superset.extensions import db

    from supagent import settings

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: ["server"] if key == "categories.custom" else real(key))

    from supagent.knowledge.facets import PART_OF
    from supagent.knowledge.freshness import touch
    from supagent.knowledge.sysmap import worded
    from supagent.models import Facet, Link

    _clean(db)
    v = {}
    for cat, name in (("application", "desk"), ("component", "desk-api"), ("component", "desk-sync"),
                      ("application", "audit"), ("component", "audit-reader"), ("component", "desk-pg"),
                      ("component", "desk.created"), ("server", "grp-web"), ("server", "vm-01"), ("server", "vm-02"),
                      ("subject", "retail"), ("component", "crew")):
        f = Facet(facet=cat, value=f"{PFX}-{name}", status="approved", source="admin")
        db.session.add(f)
        db.session.flush()
        v[name] = f.id

    def link(a, kind, b, note=None):
        db.session.add(Link(a_ref=f"facet:{v[a]}", b_ref=f"facet:{v[b]}", kind=kind, status="approved", source="admin",
                            note=note))

    link("desk-api", PART_OF, "desk")
    link("desk-sync", PART_OF, "desk")
    link("audit-reader", PART_OF, "audit")
    link("vm-01", PART_OF, "grp-web")
    link("vm-02", PART_OF, "grp-web")
    link("desk-api", "runs_on", "grp-web")
    link("desk-api", "depends_on", "desk-pg")
    link("desk-sync", "sends_to", "desk.created")
    link("audit-reader", "reads_from", "desk.created")
    link("desk", worded("owned by"), "crew", note="owned by")
    db.session.commit()
    touch()
    yield v
    _clean(db)


def test_the_communities_of_the_map(landscape):
    from supagent.knowledge import communities as C

    v = landscape
    c = C.build()
    assert set(c["systems"][v["desk"]]) == {v["desk"], v["desk-api"], v["desk-sync"], v["desk-pg"], v["desk.created"]}
    assert set(c["systems"][v["audit"]]) >= {v["audit"], v["audit-reader"]}
    assert set(c["places"][v["grp-web"]]) == {v["grp-web"], v["vm-01"], v["vm-02"]}
    assert c["teams"][v["crew"]] == [v["desk"]]
    page = C.system_page(v["desk"], __import__("supagent.knowledge.brief", fromlist=["_graph"])._graph(), c)
    text = page["content"]
    assert f"Owned by: {PFX}-crew" in text and f"{PFX}-desk-api ({'component'}): runs on {PFX}-grp-web" in text
    assert f"{PFX}-audit-reader (of {PFX}-audit) reads from {PFX}-desk.created" in text   # what uses it


@pytest.mark.parametrize("question,want", [
    (f"If {PFX}-desk-pg is down, which systems are affected?", {f"{PFX}-desk"}),
    (f"Which systems does {PFX}-crew own?", {f"{PFX}-desk"}),
    (f"Which parts read {PFX}-desk.created?", {f"{PFX}-audit-reader"}),
    (f"Where does {PFX}-desk run?", {f"{PFX}-grp-web"}),
])
def test_map_wide_questions(landscape, question, want):
    from supagent.knowledge.communities import overview

    assert set(overview(question)["answer"]) == want


def test_louvain_finds_two_groups():
    from supagent.knowledge.communities import louvain

    out = {1: [], 2: [], 3: [], 4: [], 5: [], 6: []}
    for a, b in ((1, 2), (2, 3), (1, 3), (4, 5), (5, 6), (4, 6), (3, 4)):
        out[a].append(("calls", b, ""))
    groups = sorted(sorted(c) for c in louvain([1, 2, 3, 4, 5, 6], {"out": out}))
    assert groups == [[1, 2, 3], [4, 5, 6]]


@pytest.mark.parametrize("sentence,title,want", [
    ("fiber-orders is owned by the field tribe.", "", [("fiber-orders", "field tribe")]),
    ("The care squad owns ticket-desk and chat-router.", "", [("ticket-desk", "care squad"), ("chat-router", "care squad")]),
    ("It owns ticket-desk, chat-router.", "Care Tribe", [("ticket-desk", "Care Tribe"), ("chat-router", "Care Tribe")]),
    ("It owns ticket-desk.", "Release notes", []),                          # no team's page: nobody
    ("fiber-orders est géré par l'équipe terrain.", "", [("fiber-orders", "équipe terrain")]),
    ("fiber-orders is owned by Alice Martin.", "", []),                     # a person: no team on the map
])
def test_who_owns_a_part(sentence, title, want):
    import re

    from supagent.knowledge.understand import _ownerships

    found = [(m.start(), m.group(0), m.group(0)) for m in re.finditer(r"[a-z]+-[a-z]+", sentence)]
    assert _ownerships(sentence, found, "", title) == want


@pytest.mark.parametrize("sentence,want", [
    ("Identity Hub (IH) is described below.", [("Identity Hub", "IH")]),
    ("The Access Ordering (AO) service.", [("Access Ordering", "AO")]),
    ("IH (Identity Hub) runs the logins.", [("Identity Hub", "IH")]),
    ("Postgres (v15) on db-01.", []),
    ("Order Desk (OD2) is old.", []),
])
def test_initials_a_sentence_defines(sentence, want):
    from supagent.knowledge.understand import _abbreviations

    assert _abbreviations(sentence) == want


def test_a_datastore_named_by_its_server_and_a_table_of_stores(ctx):
    from supagent.knowledge.understand import Names, discover, facts_of

    names = Names()
    names.add_part("zqm-api")
    names.add_part("zqm-desk")

    def facts(body, kind="file", path="zqm-api/config/application.yml", title="application.yml"):
        u = {"ukey": "x:1", "path": path, "kind": kind, "title": title, "text": body, "meta": {}}
        u["found"] = discover(u)
        return {(f["subject"], f["verb"], f["obj"], f["obj_kind"]) for f in facts_of(u, "zqm-api", names, {})}

    got = facts("spring:\n  data:\n    mongodb:\n      uri: mongodb://zqm-mongo.db.internal:27017/app\n")
    assert any(o == "zqm-mongo" and k == "database" for _s, _v, o, k in got), got
    got = facts("datasource:\n  url: jdbc:oracle:thin:@//zqm-ora.db.internal:1521/zqm\n")
    assert any(o == "zqm-ora" and k == "database" for _s, _v, o, k in got), got
    page = ("| Datastore | Engine | Host | Service |\n| --- | --- | --- | --- |\n"
            "| zqm-pg2 | PostgreSQL 16 | zqm-db-01 | zqm-desk |\n")
    got = facts(page, kind="page", path="", title="Datastores")
    assert ("zqm-desk", "uses", "zqm-pg2", "database") in got and ("zqm-pg2", "runs_on", "zqm-db-01", "host") in got, got
    got = facts("zqm-desk stores its data in the datastore zqm-cass2.", kind="page", path="", title="zqm-desk")
    assert any(s == "zqm-desk" and o == "zqm-cass2" for s, _v, o, _k in got), got


def test_a_word_is_no_initials():
    """(0.10.10) A part whose initials are ON is named by "ON", never by the word "on"."""
    from supagent.knowledge.understand import Names, _named_all

    names = Names()
    names.add_part("outage-notifier", "ON")
    names.add_part("zqm-api")
    s = "The VIP routes to zqm-api on the pool; ON pages the on-call."
    got = [w for _at, w, _p in _named_all(s, names, {})]
    assert "on" not in got and "ON" in got and "zqm-api" in got


def test_what_a_jobs_script_writes_and_the_names_a_page_defines(ctx):
    from supagent.knowledge.understand import Names, discover, facts_of, introduced_names

    names = Names()
    u = {"ukey": "f:1", "path": "tasks/zqm-nightly-export.sh", "kind": "file", "title": "zqm-nightly-export.sh",
         "text": "#!/bin/sh\npsql -c 'copy ...' > /tmp/x.csv\naz storage blob upload -c zqm-exports-b -f /tmp/x.csv\n"
                 "aws s3 cp s3://zqm-feeds/in.csv /tmp/in.csv\n", "meta": {}}
    u["found"] = discover(u)
    got = {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, "batch-repo", names, {})}
    assert ("zqm-nightly-export", "sends_to", "zqm-exports-b") in got, got
    assert ("zqm-nightly-export", "reads_from", "zqm-feeds") in got, got
    text = ("card acquirer: an API of a partner company. Owner: the platform team. "
            "The blob container zqm-archive-a: the archive of the desk.")
    assert introduced_names(text) == ["zqm-archive-a", "card acquirer"]
