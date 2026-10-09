"""(0.10) The System map in the search: an approved value with its description, its other names, what it is part
of and every approved link with the link's explanations is a piece of its own, so that a search for a part or for
how parts connect finds the map's words; a proposed or rejected value and a link not approved are not searched."""

from __future__ import annotations


def test_the_map_values_and_their_explained_links_are_searched(app):
    from superset.extensions import db

    from supagent.knowledge.index import pieces
    from supagent.models import Facet, Link

    with app.app_context():
        a = Facet(facet="application", value="Ledgerline", status="approved", source="admin",
                  description="Books every settled payment.", synonyms=["LL"])
        b = Facet(facet="component", value="Vaultstore", status="approved", source="admin")
        c = Facet(facet="application", value="Platformx", status="approved", source="admin")
        d = Facet(facet="component", value="Draftthing", status="proposed", source="llm")
        db.session.add_all([a, b, c, d])
        db.session.flush()
        db.session.add_all([
            Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind="sends_to", status="approved",
                 note="writes the settled orders", detail="every night, one batch per bank"),
            Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{c.id}", kind="part_of", status="approved"),
            Link(a_ref=f"facet:{d.id}", b_ref=f"facet:{b.id}", kind="calls", status="approved"),
            Link(a_ref=f"facet:{b.id}", b_ref=f"facet:{c.id}", kind="calls", status="proposed", note="never shown")])
        db.session.commit()
        try:
            got = {p["ref"]: p for p in pieces(("map:",))}
            led, vault, plat = got[f"map:{a.id}"], got[f"map:{b.id}"], got[f"map:{c.id}"]
            assert "Books every settled payment." in led["text"] and "Also called: LL" in led["text"]
            assert "Part of: Platformx" in led["text"] and "Has as parts: Ledgerline" in plat["text"]
            line = "Ledgerline sends to Vaultstore: writes the settled orders every night, one batch per bank"
            assert line in led["text"] and line in vault["text"]                # both ways
            assert f"map:{d.id}" not in got and "Draftthing" not in vault["text"]  # proposed value: not searched
            assert "never shown" not in vault["text"]                            # proposed link: not searched
        finally:
            db.session.query(Link).filter(Link.a_ref.in_([f"facet:{x.id}" for x in (a, b, c, d)])).delete(
                synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_([x.id for x in (a, b, c, d)])).delete(synchronize_session=False)
            db.session.commit()


def test_an_approved_link_is_found_by_the_next_search(app):
    from superset.extensions import db

    from supagent.knowledge import index as I
    from supagent.models import Chunk, Facet, Link

    with app.app_context():
        a = Facet(facet="application", value="Quillpost", status="approved", source="admin")
        b = Facet(facet="component", value="Inkwellqueue", status="approved", source="admin")
        db.session.add_all([a, b])
        db.session.flush()
        x = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind="sends_to", status="proposed",
                 note="hands over the stamped letters")
        db.session.add(x)
        db.session.commit()
        try:
            I.refresh_map()                                              # (the map's pieces written: the link proposed)
            def piece(ref):
                row = db.session.query(Chunk).filter(Chunk.ref == ref).first()
                return row.text if row is not None else ""

            assert "stamped letters" not in piece(f"map:{a.id}")
            x.status = "approved"                                       # an admin approves it
            db.session.commit()
            assert I._MAP_CHANGED[0] is True
            I.refresh_map()                                              # (what the next search does first)
            assert "hands over the stamped letters" in piece(f"map:{a.id}")
            assert I._MAP_CHANGED[0] is False
        finally:
            db.session.query(Link).filter(Link.id == x.id).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_([a.id, b.id])).delete(synchronize_session=False)
            db.session.commit()
            I.refresh_map()


def test_the_search_writes_the_map_again_first():
    import inspect

    from supagent.knowledge import search as S

    assert "refresh_map()" in inspect.getsource(S.search)


def test_a_change_made_in_another_process_is_searched_too(app):
    """(0.10.1) The chat's answers run in the Celery workers: an approval made in the web server must reach their
    next search, through the stamp in supagent_meta, not only the process that made it."""
    from superset.extensions import db

    from supagent.knowledge import index as I
    from supagent.models import Chunk, Facet, Link, Meta

    with app.app_context():
        a = Facet(facet="application", value="Harborledger", status="approved", source="admin")
        b = Facet(facet="component", value="Tidecache", status="approved", source="admin")
        db.session.add_all([a, b])
        db.session.flush()
        x = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind="reads_from", status="approved",
                 note="reads the tide tables")
        db.session.add(x)
        db.session.commit()
        try:
            I.refresh_map()
            stamp = db.session.get(Meta, I.MAP_KEY)
            assert stamp is not None and stamp.value                   # written after the commit
            before = stamp.value

            x.note = "reads the harbour's tide tables every hour"      # changed in "the web server"...
            db.session.commit()
            db.session.expire_all()
            assert db.session.get(Meta, I.MAP_KEY).value != before
            I._MAP_CHANGED[0] = False                                  # ... this process (a "worker") did not see it
            I._MAP_SEEN["at"] = 0.0                                    # (its stamp read again now)
            assert I.refresh_map() is not None                         # the stamp says: written again
            row = db.session.query(Chunk).filter(Chunk.ref == f"map:{a.id}").first()
            assert row is not None and "every hour" in row.text
            assert I.refresh_map() is None                             # nothing new: nothing written

            now = db.session.get(Meta, I.MAP_KEY).value
            x.note = "never committed"
            db.session.flush()
            db.session.rollback()                                      # a change rolled back: no stamp
            db.session.expire_all()
            assert db.session.get(Meta, I.MAP_KEY).value == now
        finally:
            db.session.rollback()
            db.session.query(Link).filter(Link.id == x.id).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_([a.id, b.id])).delete(synchronize_session=False)
            db.session.commit()
            I.refresh_map()
