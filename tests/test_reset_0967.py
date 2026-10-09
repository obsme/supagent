"""(0.9.6.7) What the learning made wiped to be made again (the Context, the categories' values, the map's links):
what people made stays, a backup is made first, and the backup puts everything back."""

from __future__ import annotations


def test_a_wipe_keeps_what_people_made_and_the_backup_puts_it_back(ctx, tmp_path):
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import reset as R
    from supagent.knowledge.backup import run_restore
    from supagent.models import Classified, ContextPage, Facet, Link, Run, Tag

    settings.set_value("backup.dir", str(tmp_path))
    db.session.query(Run).filter(Run.status == "running").update({"status": "done"})   # (another test's run)
    db.session.commit()
    names = ["zz-kept-app", "zz-kept-db", "zz-learned-app", "zz-data-comp"]
    try:
        mine = Facet(facet="application", value=names[0], status="approved", source="admin", description="Written by a person")
        mine2 = Facet(facet="application", value=names[1], status="approved", source="admin")
        learned = Facet(facet="application", value=names[2], status="approved", source="llm", description="the LLM's")
        data = Facet(facet="component", value=names[3], status="approved", source="data")
        db.session.add_all([mine, mine2, learned, data])
        db.session.flush()
        links = {"drawn": Link(a_ref=f"facet:{mine.id}", b_ref=f"facet:{mine2.id}", kind="link:abcd1234", status="approved",
                               source="admin", note="sends the files to"),
                 "described": Link(a_ref=f"facet:{mine2.id}", b_ref=f"facet:{mine.id}", kind="depends_on",
                                   status="approved", source="llm", note="waits for its data", explained_by="alice"),
                 "learned": Link(a_ref=f"facet:{mine.id}", b_ref=f"facet:{mine2.id}", kind="calls", status="approved",
                                 source="llm"),
                 "to a learned value": Link(a_ref=f"facet:{data.id}", b_ref=f"facet:{mine.id}", kind="runs_on",
                                            status="approved", source="admin", note="runs on")}
        tags = {"given by a person": Tag(ref="doc:9901#0", facet_id=mine.id, source="admin", status="approved"),
                "by the LLM": Tag(ref="doc:9901#1", facet_id=mine.id, source="llm", status="approved"),
                "of a learned value": Tag(ref="doc:9901#2", facet_id=learned.id, source="llm", status="approved")}
        pages = {"agent": ContextPage(section="technical", slug="zz-agent-page", title="Written by the agent", content="x",
                                      author="agent"),
                 "person": ContextPage(section="technical", slug="zz-person-page", title="Written by a person",
                                       content="y", author="alice")}
        db.session.add_all([*links.values(), *tags.values(), *pages.values(),
                            Classified(ref="doc:9901#0", content_hash="h")])
        db.session.commit()
        ids = {"links": {k: x.id for k, x in links.items()}, "tags": {k: t.id for k, t in tags.items()},
               "pages": {k: p.id for k, p in pages.items()}}

        p = R.plan(context=True, categories=True, links=True)
        assert p["kept"]["values a person added"] >= 2 and p["kept"]["context pages a person wrote"] >= 1
        assert db.session.query(Facet).filter(Facet.value.in_(names)).count() == 4     # nothing changed
        out = R.run(context=True, categories=True, links=True, by="test")
        assert out["backup"] and out["values"] >= 1

        left = {f.value: f for f in db.session.query(Facet).filter(Facet.value.in_(names))}
        # (0.10.4) the data's value stays: a link a person drew rests on it
        assert set(left) == {names[0], names[1], names[3]} and left[names[0]].description == "Written by a person"
        kept_links = {k for k, i in ids["links"].items() if db.session.get(Link, i) is not None}
        assert kept_links == {"drawn", "described", "to a learned value"}
        assert {k for k, i in ids["tags"].items() if db.session.get(Tag, i) is not None} == {"given by a person"}
        assert {k for k, i in ids["pages"].items() if db.session.get(ContextPage, i) is not None} == {"person"}
        assert db.session.query(Classified).count() == 0              # every item classified again

        back = run_restore(out["backup"], ["categories", "context"], by="test")
        assert back["status"] == "done"
        assert db.session.query(Facet).filter(Facet.value.in_(names)).count() == 4
        assert all(db.session.get(Link, i) is not None for i in ids["links"].values())
        assert all(db.session.get(ContextPage, i) is not None for i in ids["pages"].values())
        assert db.session.query(Classified).filter(Classified.ref == "doc:9901#0").count() == 1
    finally:
        db.session.rollback()
        f_ids = [i for (i,) in db.session.query(Facet.id).filter(Facet.value.in_(names))]
        refs = [f"facet:{i}" for i in f_ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Tag).filter(Tag.ref.like("doc:9901#%")).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(f_ids or [-1])).delete(synchronize_session=False)
        db.session.query(ContextPage).filter(ContextPage.slug.in_(["zz-agent-page", "zz-person-page"])).delete(
            synchronize_session=False)
        db.session.query(Classified).filter(Classified.ref == "doc:9901#0").delete(synchronize_session=False)
        db.session.commit()
        settings.set_value("backup.dir", None)


def test_the_command_says_what_would_go_and_changes_nothing(app):
    from superset.extensions import db

    from supagent.cli import supagent
    from supagent.models import Facet

    with app.app_context():
        before = db.session.query(Facet).count()
    r = app.test_cli_runner().invoke(supagent, ["reset-knowledge", "--categories", "--links"])
    assert r.exit_code == 0, r.output
    assert "goes: values:" in r.output and "stays: values a person added:" in r.output
    assert "Nothing was changed: add --yes" in r.output
    assert app.test_cli_runner().invoke(supagent, ["reset-knowledge"]).exit_code != 0     # say what to wipe
    with app.app_context():
        assert db.session.query(Facet).count() == before
