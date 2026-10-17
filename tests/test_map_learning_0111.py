"""(0.11.1) The System map's learning: an approved learned link no longer stated is looked for in the documents in ONE
reading of them (not one LIKE over every document per link, minutes on a wiki of tens of thousands of pages), with
the same answer: its words still written somewhere (in order, case aside, the first and last ten of a long quote),
its removal not proposed; gone from every enabled document, proposed."""

from __future__ import annotations

from sqlalchemy import event

from test_docs_readers import env  # noqa: F401  (the fixture)


def _docs_read(fn):
    """How many statements read the documents' table while fn runs, and fn's result."""
    from superset.extensions import db

    seen = []

    def count(_conn, _cursor, statement, *_a):
        if "supagent_doc" in statement and statement.lstrip().upper().startswith("SELECT"):
            seen.append(statement)

    engine = db.session.get_bind()
    event.listen(engine, "before_cursor_execute", count)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return len(seen), result


def test_the_documents_are_read_once_for_all_the_links_to_check(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.proposals import still_written_all
    from supagent.models import Doc

    pages = [Doc(kind="upload", title=f"qv notes {i}", enabled=True, status="ok",
                 content=f"Notes {i}. The qvledger{i} hands the totals to qvbooks{i} every night.\n") for i in range(6)]
    off = Doc(kind="upload", title="qv old notes", enabled=False, status="ok",
              content="The qvarchive sends its files to qvtape every week.\n")
    db.session.add_all(pages + [off])
    db.session.commit()
    evidences = [f"The qvledger{i} hands the totals to qvbooks{i} every night. (qv notes {i}; doc)" for i in range(6)]
    evidences += ["THE QVLEDGER3 hands the TOTALS to qvbooks3 (qv notes 3; doc)",          # case aside
                  "qvbooks2 hands the totals to qvledger2 every night (x; doc)",           # not in that order
                  "The qvarchive sends its files to qvtape every week. (qv old notes; doc)",   # a disabled document
                  "qvledger1 hands (x; doc)",                                               # too few words to say
                  "Notes 4. The qvledger4 hands the totals to qvbooks4 every night, then the qvbooks4 files them "
                  "away (x; doc)"]                                  # its last ten words written nowhere
    n, got = _docs_read(lambda: still_written_all(evidences))
    assert got == [True] * 7 + [False, False, False, False], got
    assert n == 1, n                                                  # one reading of the documents, not eleven


def test_propose_reads_the_documents_once_for_every_approved_link_no_longer_stated(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import STATE_KEY, propose
    from supagent.models import Doc, Facet, Link, Meta

    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
    d = Doc(kind="upload", title="qw notes", enabled=True, status="ok",
            content="Notes. The qwfront0 asks the qwback0 for prices; the qwfront1 asks the qwback1 for stock.\n")
    db.session.add(d)
    made = []
    for i in range(5):
        a = Facet(facet="application", value=f"qwfront{i}", status="approved", source="docs")
        b = Facet(facet="application", value=f"qwback{i}", status="approved", source="docs")
        db.session.add_all([a, b])
        db.session.flush()
        made += [a, b]
        made.append(Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind="depends_on", status="approved",
                         source="docs", evidence=f"the qwfront{i} asks the qwback{i} for prices every hour of the "
                                                 f"day (qw notes; doc)" if i > 1 else
                         f"The qwfront{i} asks the qwback{i} for {'prices' if i == 0 else 'stock'} (qw notes; doc)"))
        db.session.add(made[-1])
    db.session.commit()
    links = [x for x in made if isinstance(x, Link)]
    try:
        U.run(reason="test")
        n, out = _docs_read(propose)
        drops = {x.id: db.session.get(Link, x.id).proposed_drop for x in links}
        assert [bool(drops[x.id]) for x in links] == [False, False, True, True, True], drops   # 0, 1 still written
        assert out.get("still written", 0) >= 2 and out["removals"] >= 3, out
        assert n <= 3, n         # the reading of the documents' texts, not one more statement per link to check
    finally:
        db.session.rollback()
        for x in links:
            db.session.query(Link).filter(Link.id == x.id).delete(synchronize_session=False)
        for f in made:
            if isinstance(f, Facet):
                db.session.query(Facet).filter(Facet.id == f.id).delete(synchronize_session=False)
        db.session.commit()


def test_what_the_documents_say_is_another_organizations_is_never_filed_as_the_systems_own_service(env):  # noqa: F811
    from supagent.knowledge.proposals import _category

    env["categories.custom"] = ["qx area", "qx crew", "platform service", "server group", "server"]
    env["categories.about"] = {"platform service": "a service of the platform that users or other services rely on",
                               "server": "a server by its hostname"}
    env["categories.inside"] = {}
    assert _category("external", "qxoutside") is None        # an address of another company: no value of the system
    assert _category("part", "qxinside") == "platform service"   # the system's own part: as before
    env["categories.custom"] = env["categories.custom"] + ["partner api"]
    env["categories.about"] = dict(env["categories.about"], **{"partner api": "a service of another company we call"})
    assert _category("external", "qxoutside") == "partner api"   # the person's category for such things


def _state():
    from superset.extensions import db

    from supagent.models import Facet, Link

    return {i for (i,) in db.session.query(Facet.id)}, {i for (i,) in db.session.query(Link.id)}


def _clean(before, docs):
    from superset.extensions import db

    from supagent.models import Doc, Facet, KFact, KUnit, Link

    db.session.rollback()
    facets, links = before
    db.session.query(Link).filter(Link.id.notin_(links or {-1})).delete(synchronize_session=False)
    db.session.query(Facet).filter(Facet.id.notin_(facets or {-1})).delete(synchronize_session=False)
    for d in docs:
        units = db.session.query(KUnit.id).filter(KUnit.doc_id == d.id)
        db.session.query(KFact).filter(KFact.unit_id.in_(units)).delete(synchronize_session=False)
        db.session.query(KUnit).filter(KUnit.doc_id == d.id).delete(synchronize_session=False)
        db.session.query(Doc).filter(Doc.id == d.id).delete(synchronize_session=False)
    db.session.commit()


CATS = {"categories.custom": ["business line", "crew", "microservice", "store"],
        "categories.inside": {"microservice": "application"},
        "categories.about": {"business line": "a business line: the applications that serve one business function",
                             "crew": "a crew: the team that builds and runs some applications",
                             "microservice": "a deployable service of an application (an API, a worker)",
                             "store": "a database holding an application's data"}}


def test_a_whole_is_filed_by_the_category_any_of_its_sentences_names_not_only_the_first_read(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import STATE_KEY, propose
    from supagent.models import Doc, Facet, Meta

    env.update(CATS)
    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
    before = _state()
    pages = [Doc(kind="upload", title="qy repair line", enabled=True, status="ok",
                 content="# Repair line\n\nApplications of qyrepair: qydepot.\n"),
             Doc(kind="upload", title="qy depot", enabled=True, status="ok",
                 content="# Depot\n\nqydepot is an application of the qyrepair business line.\n\n"
                         "qyorders is a microservice of the qydepot application.\n\n"
                         "qystock is a microservice of the qydepot application.\n"),
             Doc(kind="upload", title="qy parts", enabled=True, status="ok",
                 content="# Parts\n\nqyorders is part of qydepot.\n\nqystock is part of qydepot.\n")]
    db.session.add_all(pages)
    db.session.commit()
    try:
        U.run(reason="test")
        propose()
        filed = {f.value: f.facet for f in db.session.query(Facet).filter(Facet.id.notin_(before[0] or {-1}))}
        assert filed.get("qyrepair") == "business line", filed      # the second sentence names its category
        assert filed.get("qydepot") == "application", filed   # an application, not one of its own microservices
    finally:
        _clean(before, pages)


def test_a_value_with_parts_of_its_own_is_never_moved_down_among_its_wholes_parts(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.proposals import _refile_inside
    from supagent.models import Facet, Link

    env.update(CATS)
    before = _state()
    line = Facet(facet="application", value="qzfleet", status="proposed", source="docs")      # a line filed wrong
    app = Facet(facet="application", value="qztracker", status="proposed", source="docs")     # its application
    part = Facet(facet="application", value="qzgate", status="proposed", source="docs")       # the app's part
    db.session.add_all([line, app, part])
    db.session.flush()
    db.session.add_all([Link(a_ref=f"facet:{app.id}", b_ref=f"facet:{line.id}", kind="part_of", status="proposed",
                             source="docs"),
                        Link(a_ref=f"facet:{part.id}", b_ref=f"facet:{app.id}", kind="part_of", status="proposed",
                             source="docs")])
    db.session.commit()
    try:
        _refile_inside()
        assert db.session.get(Facet, app.id).facet == "application"      # it has a part: no microservice
        assert db.session.get(Facet, part.id).facet == "microservice"    # its part: one of its microservices
    finally:
        _clean(before, [])


def test_an_environment_goes_to_the_category_whose_description_names_it(env):  # noqa: F811
    from supagent.knowledge.naming import checked
    from supagent.knowledge.proposals import _category

    env["categories.custom"] = ["estate", "host set", "server"]
    env["categories.about"] = {"estate": "an estate: prod, preprod or int",
                               "host set": "an inventory group of hosts of one estate",
                               "server": "a server by its hostname"}
    env["categories.inside"] = {"host set": "estate", "server": "host set"}
    for name in ("prod", "preprod", "int"):
        assert _category("environment", name) == "estate", name   # the person listed it there
        assert checked("estate", name)[0] == name, name            # a common word, yet a name of that category
    assert checked("host set", "web")[0] == "web"                   # a group's name: as before
    env["categories.custom"] = env["categories.custom"] + ["qz store"]
    env["categories.about"] = dict(env["categories.about"], **{"qz store": "a database or a cache of a service"})
    assert checked("qz store", "database")[0] is None              # a kind word its description says: no name
    assert _category("environment", "qzlab") != "estate"            # a name the description does not list: as before


def test_a_server_is_part_of_its_environment_through_its_group_not_once_more_directly(env, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import STATE_KEY, propose
    from supagent.models import Facet, Link, Meta

    env.update({"categories.custom": ["environment", "server group", "server"],
                "categories.inside": {"server group": "environment", "server": "server group"},
                "categories.about": {"environment": "an environment: prod or staging",
                                     "server group": "an inventory group: the servers of one role",
                                     "server": "a server by its hostname"}})
    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)
    before = _state()

    def rel(a, b, line):                                   # what an inventory of one environment says
        return {"from": a, "kind": "in_group", "to": b, "obj_kind": "group", "sources": {"config"}, "units": {1},
                "quote": f"{a.split()[0]}:", "where": "inventories/prod/hosts.yml",
                "said": {f"1|{a.split()[0]}: {line}"}}

    rels = []
    for i, host in enumerate(("qzweb-01", "qzweb-02", "qzdb-01")):
        group = "qzweb (prod)" if "web" in host else "qzdata (prod)"
        rels += [rel(host, group, i), rel(host, "qzfront (prod)", i) if "web" in host else rel(host, group, i),
                 rel(host, "prod", i)]
    rels += [rel("qzweb (prod)", "qzfront (prod)", 10), rel("qzweb (prod)", "prod", 11),
             rel("qzfront (prod)", "prod", 12), rel("qzdata (prod)", "prod", 13)]
    monkeypatch.setattr(U, "export", lambda *a, **k: {"relations": rels, "data_links": [], "denied": []})
    try:
        propose()
        name = {f.id: (f.facet, f.value) for f in db.session.query(Facet).filter(Facet.id.notin_(before[0] or {-1}))}
        rows = [(name.get(int(x.a_ref[6:])), name.get(int(x.b_ref[6:])))
                for x in db.session.query(Link).filter(Link.kind == "part_of", Link.id.notin_(before[1] or {-1}))]
        rows = [(a, b) for a, b in rows if a and b]
        servers = [(a[1], b) for a, b in rows if a[0] == "server"]
        assert servers and not [x for x in servers if x[1][0] == "environment"], rows   # through its groups
        assert {g for h, (c, g) in servers if h == "qzweb-01"} == {"qzweb (prod)", "qzfront (prod)"}, rows   # a
        #                                                           group inside a group: a member of both, kept
        assert {(a[1], b[1]) for a, b in rows if a[0] == "server group" and b[0] == "environment"} >= \
            {("qzfront (prod)", "prod"), ("qzdata (prod)", "prod")}, rows
    finally:
        _clean(before, [])


def test_a_tribe_named_in_french_is_the_same_tribe(ctx):
    from supagent.knowledge.consolidate import same

    assert same("tribu qzcare tribe", "Qzcare Tribe", "tribe") == "strong"     # "géré par la tribu qzcare tribe"
    assert same("la tribu Qzcare", "the Qzcare tribe", "tribe") == "strong"
    assert same("tribu qzcare", "tribu qzpay", "tribe") == ""                  # two tribes stay two
