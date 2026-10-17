"""(0.11.0) The review of the learning and the System map: each test a defect found, failing before its fix."""

from __future__ import annotations


def test_forgetting_the_learned_keeps_what_a_person_did_on_the_map(ctx):
    """forget-learned: an index a person gave a value on the System map (or refused there) is kept as the dictionary
    page's work is: its learned facts go, the person's item stays on the map (a relearned index of a new id would
    leave it pointing at nothing, and a refused one proposed again)."""
    from superset.extensions import db

    from supagent.knowledge.forget import forget
    from supagent.models import Facet, KObject, Source, Tag

    src = Source(database_id=990_101, database_name="forget review db", backend="osagg")
    db.session.add(src)
    db.session.flush()
    given, refused, learned = (KObject(source_id=src.id, kind="index", parent="", name=n, stats={"docs": 1})
                               for n in ("orders-*", "audit-*", "noise-*"))
    db.session.add_all([given, refused, learned])
    app = Facet(facet="application", value="forget review app", status="approved", source="admin")
    db.session.add(app)
    db.session.flush()
    tags = [Tag(ref=f"object:{given.id}", facet_id=app.id, source="admin", status="approved", reviewed_by="admin"),
            Tag(ref=f"object:{refused.id}", facet_id=app.id, source="llm", status="rejected", reviewed_by="admin"),
            Tag(ref=f"object:{learned.id}", facet_id=app.id, source="llm", status="proposed")]
    db.session.add_all(tags)
    db.session.commit()
    try:
        (row,) = forget(["forget review db"], apply=True)
        left = {o.name: o for o in db.session.query(KObject).filter(KObject.source_id == src.id)}
        assert set(left) == {"orders-*", "audit-*"} and row["kept"] == 2
        assert left["orders-*"].stats is None                       # its learned facts go
        assert {t.ref for t in db.session.query(Tag).filter(Tag.facet_id == app.id, Tag.status != "proposed")} == \
            {f"object:{given.id}", f"object:{refused.id}"}
        (everything,) = forget(["forget review db"], everything=True, apply=True)
        assert db.session.query(KObject).filter(KObject.source_id == src.id).count() == 0
    finally:
        db.session.rollback()
        db.session.query(Tag).filter(Tag.facet_id == app.id).delete(synchronize_session=False)
        db.session.query(KObject).filter(KObject.source_id == src.id).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id == app.id).delete(synchronize_session=False)
        db.session.query(Source).filter(Source.id == src.id).delete(synchronize_session=False)
        db.session.commit()


def test_activating_an_index_again_brings_back_only_the_fields_it_took(ctx):
    """Data dictionary: a field the team deactivated on its own stays deactivated when its index is deactivated and
    activated again (activating the index brings back only the fields it took with it)."""
    from superset.extensions import db

    from supagent.knowledge.deactivate import is_deactivated, set_active
    from supagent.models import KObject, Meta, Source

    src = Source(database_id=990_102, database_name="deactivate review db", backend="osagg")
    db.session.add(src)
    db.session.flush()
    index = KObject(source_id=src.id, kind="index", parent="", name="people-*")
    secret, plain = (KObject(source_id=src.id, kind="field", parent="people-*", name=n) for n in ("ssn", "city"))
    db.session.add_all([index, secret, plain])
    db.session.commit()
    try:
        assert set_active(secret, False) == 1                     # the team: never use this field
        db.session.commit()
        assert set_active(index, False) == 2                      # the index and the field it takes with it
        db.session.commit()
        assert set_active(index, True) == 2
        db.session.commit()
        assert not is_deactivated(index) and not is_deactivated(plain)
        assert is_deactivated(db.session.get(KObject, secret.id))  # deactivated on its own: it stays so
        # an index deactivated before the fields it took were written down: all of them come back, as before
        set_active(index, False)
        db.session.commit()
        db.session.query(Meta).filter(Meta.key == "deactivated_with").delete(synchronize_session=False)
        db.session.commit()
        assert set_active(index, True) == 3
        assert not is_deactivated(secret) and not is_deactivated(plain)
    finally:
        db.session.rollback()
        db.session.query(KObject).filter(KObject.source_id == src.id).delete(synchronize_session=False)
        db.session.query(Source).filter(Source.id == src.id).delete(synchronize_session=False)
        db.session.query(Meta).filter(Meta.key == "deactivated_with").delete(synchronize_session=False)
        db.session.commit()


def test_a_value_is_found_by_its_name_not_by_a_pattern(ctx):
    """A name with "_" or "%" is matched as written, whatever its case: a server "db_1" added on the map is not
    refused as the existing "db01", and a refused "db01" is not renamed "db_1" and approved; the learning's "db_1"
    is not filed as "db01"."""
    from superset.extensions import db

    from supagent.knowledge.facets import _ensure
    from supagent.knowledge.sysmap import add_value
    from supagent.models import Facet

    made: list[int] = []
    try:
        old = Facet(facet="component", value="db01", status="approved", source="admin")
        db.session.add(old)
        db.session.commit()
        made.append(old.id)
        new = add_value("component", "db_1", None, "admin")
        made.append(new["id"])
        assert new["id"] != old.id and new["value"] == "db_1"
        assert db.session.get(Facet, old.id).value == "db01"
        refused = Facet(facet="component", value="db02", status="rejected", source="llm")
        db.session.add(refused)
        db.session.commit()
        made.append(refused.id)
        again = add_value("component", "db_2", None, "admin")
        made.append(again["id"])
        assert again["id"] != refused.id
        assert (db.session.get(Facet, refused.id).value, db.session.get(Facet, refused.id).status) == ("db02", "rejected")
        learned = _ensure("component", "db%", "proposed", "llm")
        made.append(learned.id)
        assert learned.id not in (old.id, new["id"]) and learned.value == "db%"
        assert _ensure("component", "DB_1", "proposed", "llm").id == new["id"]      # its case: the same value
        accented = Facet(facet="component", value="Équipe réseau", status="approved", source="admin")
        db.session.add(accented)
        db.session.commit()
        made.append(accented.id)
        assert _ensure("component", "Équipe réseau", "proposed", "llm").id == accented.id   # itself, not a twin
        try:
            add_value("component", "Équipe réseau", None, "admin")
            raise AssertionError("an existing value added again")
        except ValueError as ex:
            assert "already" in str(ex)
    finally:
        db.session.rollback()
        db.session.query(Facet).filter(Facet.id.in_(made or [-1])).delete(synchronize_session=False)
        db.session.commit()
