"""(0.10.2) What would confuse the agent or the search, said with a proposed fix: one name for two things, one thing
written two ways, a value named by a common word, the map in a circle, documents holding the same pages, a glossary
term defined twice differently."""

from __future__ import annotations


def test_the_checks_say_why_and_what_to_do(app):
    from superset.extensions import db

    from supagent.knowledge import lint as L
    from supagent.models import Doc, Entry, Facet

    with app.app_context():
        made = [Facet(facet="server", value="Harbor", status="approved", source="data"),
                Facet(facet="application", value="harbor", status="proposed", source="docs"),
                Facet(facet="component", value="db", status="approved", source="admin"),
                Facet(facet="application", value="Tideledger", status="approved", source="admin")]
        pages = [{"url": f"https://wiki.example/p/{i}", "title": f"Page {i}"} for i in range(6)]
        docs = [Doc(kind="url", url="https://wiki.example/a", title="Space A", pages=pages, enabled=True),
                Doc(kind="url", url="https://wiki.example/b", title="Space B", pages=pages[1:], enabled=True)]
        terms = [Entry(title="Glossary one", classification="glossary", fmt="yaml", enabled=True,
                       content="late report: a report delivered after its deadline\n"),
                 Entry(title="Glossary two", classification="glossary", fmt="yaml", enabled=True,
                       content="late report: a report delivered after 18:00\n")]
        db.session.add_all(made + docs + terms)
        db.session.commit()
        try:
            got = {(w["kind"], w["subject"]) for w in L.warnings()}
            assert ("same_name", "Harbor") in got or ("same_name", "harbor") in got
            assert not any(k == "generic_name" for k, _s in got)                  # off by default (measured)
            generic = {(w["kind"], w["subject"]) for w in L.generic_name()}
            assert ("generic_name", "db") in generic and ("generic_name", "Tideledger") not in generic
            assert ("shared_pages", "Space A / Space B") in got
            assert ("two_meanings", "late report") in got
            w = [x for x in L.warnings() if x["kind"] == "shared_pages"][0]
            assert "hold the same 5 pages" in w["why"]
            assert w["fix"].startswith("Disable “Space B”")          # every page it holds, the first one reads
            w = [x for x in L.warnings() if x["kind"] == "same_name"][0]      # an approved server, a proposed app
            assert "is a server already and is proposed as an application" in w["why"], w
            assert w["merge"] == [{"from": made[1].id, "into": made[0].id,
                                   "label": "Merge the application “harbor” into the server"}]
        finally:
            for x in made + docs + terms:
                db.session.delete(x)
            db.session.commit()


def test_to_review_lists_the_warnings_and_sets_one_aside(app):
    from superset.extensions import db

    from conftest import login
    from supagent.models import Facet, Meta

    with app.app_context():
        f = Facet(facet="component", value="ingest-gw", status="approved", source="admin")
        g = Facet(facet="component", value="Ingest GW", status="proposed", source="llm")
        db.session.add_all([f, g])
        db.session.commit()
        try:
            c = app.test_client()
            login(c, "admin")
            d = c.get("/supagent/admin/api/review").get_json()
            mine = [w for w in d["warnings"] if w["kind"] == "two_ways" and w["subject"] == "ingest-gw / Ingest GW"]
            assert mine and d["counts"]["warnings"] >= 1 and "What" not in mine[0]["why"][:4]
            assert c.post("/supagent/admin/api/lint/dismiss", json={"key": mine[0]["key"]}).status_code == 200
            d = c.get("/supagent/admin/api/review").get_json()
            assert not [w for w in d["warnings"] if w["key"] == mine[0]["key"]]       # set aside: not said again
            d = c.get("/supagent/admin/api/review?q=nothing-like-this").get_json()
            assert d["counts"]["warnings"] == 0                                       # the filter applies
        finally:
            db.session.delete(f)
            db.session.delete(g)
            db.session.query(Meta).filter(Meta.key == "lint_dismissed").delete(synchronize_session=False)
            db.session.commit()


def test_one_thing_written_two_ways_is_merged_in_one_click(app):
    from superset.extensions import db

    from supagent.knowledge import lint as L
    from supagent.models import Facet, Link, Tag

    with app.app_context():
        made = [Facet(facet="application", value="Web Shop", status="approved", source="admin"),
                Facet(facet="application", value="web-shop", status="approved", source="data"),
                Facet(facet="application", value="invoice", status="proposed", source="llm"),
                Facet(facet="application", value="invoices", status="approved", source="data"),
                Facet(facet="server", value="websh0p", status="approved", source="data"),
                Facet(facet="component", value="node-a1", status="approved", source="data"),
                Facet(facet="component", value="node-a1s", status="approved", source="data"),
                Facet(facet="server", value="gwservers", status="approved", source="docs"),
                Facet(facet="server", value="gw_servers", status="approved", source="docs"),
                Facet(facet="server", value="gwserver", status="approved", source="docs")]
        db.session.add_all(made)
        db.session.flush()
        tags = [Tag(ref=f"doc:{i}", facet_id=made[1].id, status="approved") for i in range(3)]
        inside = Link(a_ref=f"facet:{made[9].id}", b_ref=f"facet:{made[8].id}", kind="part_of", status="approved",
                      source="docs")                   # a host in its group: not the group written another way
        db.session.add_all(tags + [inside])
        db.session.commit()
        try:
            ws = {w["subject"]: w for w in L.warnings() if w["kind"] == "two_ways"}
            assert set(ws) == {"web-shop / Web Shop", "invoices / invoice", "gwservers / gw_servers"}, ws
            w = ws["web-shop / Web Shop"]                       # the one with the most items is kept
            assert w["merge"] == [{"from": made[0].id, "into": made[1].id, "label": "Merge “Web Shop” into “web-shop”"}]
            assert ws["invoices / invoice"]["merge"][0]["into"] == made[3].id   # the approved one is kept
            c = app.test_client()
            from conftest import login
            login(c, "admin")
            r = c.post(f"/supagent/admin/api/facets/{made[0].id}", json={"merge_into": made[1].id})
            assert r.status_code == 200, r.get_data(as_text=True)
            db.session.expire_all()
            assert "Web Shop" in (db.session.get(Facet, made[1].id).synonyms or [])
            assert "web-shop / Web Shop" not in {w["subject"] for w in L.warnings()}
        finally:
            db.session.rollback()
            for x in db.session.query(Link).filter(Link.id == inside.id):
                db.session.delete(x)
            for t in db.session.query(Tag).filter(Tag.ref.in_([f"doc:{i}" for i in range(3)])):
                db.session.delete(t)
            for f in made:
                x = db.session.get(Facet, f.id)
                if x is not None:
                    db.session.delete(x)
            db.session.commit()


def test_the_map_in_a_circle_and_a_generic_name_under_its_parent(app):
    from superset.extensions import db

    from supagent.knowledge import lint as L
    from supagent.models import Facet, Link

    with app.app_context():
        made = [Facet(facet="application", value="Lumen", status="approved", source="admin"),
                Facet(facet="component", value="Quillon", status="approved", source="admin"),
                Facet(facet="server", value="sx-1", status="approved", source="data"),
                Facet(facet="server", value="sx-2", status="approved", source="data"),
                Facet(facet="component", value="api", status="approved", source="admin")]
        db.session.add_all(made)
        db.session.flush()
        a, b, s1, s2, api = (f"facet:{f.id}" for f in made)
        links = [Link(a_ref=a, b_ref=b, kind="part_of", status="approved", source="docs"),
                 Link(a_ref=b, b_ref=a, kind="part_of", status="proposed", source="llm"),
                 Link(a_ref=s1, b_ref=s2, kind="runs_on", status="approved", source="docs"),
                 Link(a_ref=s2, b_ref=s1, kind="runs_on", status="proposed", source="llm"),
                 Link(a_ref=api, b_ref=a, kind="part_of", status="approved", source="docs")]
        db.session.add_all(links)
        db.session.commit()
        try:
            ws = L.warnings()
            loops = {w["subject"]: w for w in ws if w["kind"] == "loop"}
            assert "Lumen / Quillon" in loops and "sx-1 / sx-2" in loops, loops
            assert loops["Lumen / Quillon"]["refs"] == sorted(f"link:{x.id}" for x in links[:2])
            assert "runs on" in loops["sx-1 / sx-2"]["why"] and "reject the other" in loops["sx-1 / sx-2"]["fix"]
            g = [w for w in L.generic_name() if w["subject"] == "api"][0]     # (off by default; still said right)
            assert "“Lumen api”" in g["fix"]                    # the value it is part of says which one it is
            assert L._circles({1: {2: 0}, 2: {3: 0}, 3: {1: 0}, 4: {4: 0}, 5: {1: 0}}) == [[1, 2, 3], [4]]
        finally:
            for x in links:
                db.session.delete(x)
            for f in made:
                db.session.delete(f)
            db.session.commit()


def test_documents_holding_the_same_pages_are_one_warning(app):
    from superset.extensions import db

    from supagent.knowledge import lint as L
    from supagent.models import Doc

    with app.app_context():
        pages = [{"url": f"https://wiki.example/q/{i}", "title": f"Page {i}"} for i in range(30)]
        docs = [Doc(kind="url", url="https://wiki.example/q/0", title="Ops", pages=pages[:20], enabled=True),
                Doc(kind="url", url="https://wiki.example/q/10", title="Dev", pages=pages[10:30], enabled=True),
                Doc(kind="url", url="https://wiki.example/q/15", title="Team", pages=pages[15:25] + pages[:1],
                    enabled=True)]
        db.session.add_all(docs)
        db.session.commit()
        try:
            ws = [w for w in L.warnings() if w["kind"] == "shared_pages"]
            assert len(ws) == 1 and ws[0]["subject"] == "Ops / Dev / Team", ws
            assert "hold the same 16 pages" in ws[0]["why"]           # 10-24 and the first: held twice or more
            assert ws[0]["fix"].startswith("Disable “Team”")          # all its pages, Ops and Dev read before it
            docs[2].enabled = False
            db.session.commit()
            ws = [w for w in L.warnings() if w["kind"] == "shared_pages"]
            assert ws[0]["fix"].startswith("Read “Dev” again"), ws    # read again: the first one keeps the pages
        finally:
            for d in docs:
                db.session.delete(d)
            db.session.commit()
