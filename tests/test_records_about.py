"""records_about: what was recorded about parts of the system before the effect began (candidate C), the change
behind a cause found on the part named as the cause, not only on the applications asked."""

from __future__ import annotations

from test_groups import world  # noqa: F401  (the lab databases)
from test_groups_all_090 import night  # noqa: F401  (the runs and the changes of a night)


def test_the_records_of_the_parts_named(night, app):  # noqa: F811
    from superset.extensions import db

    from supagent import tools as T
    from supagent.models import KObject, Source
    from supagent.security import acting_as

    night.con.execute("INSERT INTO \"changes\" VALUES ('2026-09-22 23:40:00', 'srv-3', 'Kernel patch and reboot of srv-3', "
                      "'CHG-8')")
    with app.app_context():
        src = db.session.query(Source).first()
        made = [KObject(source_id=src.id, kind="field", name="TARGET", parent="changes", data_type="keyword", stats={}),
                KObject(source_id=src.id, kind="field", name="WHAT", parent="changes", data_type="text", stats={})]
        db.session.add_all(made)
        db.session.commit()
        try:
            assert [t for t, _k, _x in T._record_tables()] == ["changes"]
            with acting_as("admin"):
                one = T.records_about(names=["srv-3"], until="2026-09-23 00:10")
                app_too = T.records_about(names=["BILLING", "srv-3"], until="2026-09-23 00:10", days=2)
                none = T.records_about(names=["srv-9"], until="2026-09-23 00:10")
                empty = T.records_about(names=[], until="2026-09-23 00:10")
        finally:
            for o in made:
                db.session.delete(o)
            db.session.commit()
    assert "error" not in one, one
    table = one["tables"][0]
    assert table["table"] == "changes" and table["records"] == 1 and table["latest"][0]["TICKET"] == "CHG-8"
    assert "\"TARGET\" IN ('srv-3')" in table["sql"] and "LIKE '%srv-3%'" in table["sql"]
    assert app_too["tables"][0]["records"] == 2                    # CHG-8, and CHG-7 (BILLING 2.0, the evening before)
    assert none["tables"][0]["records"] == 0                        # nothing recorded on it: said, a finding too
    assert "error" in empty


def test_the_deeper_step_points_to_it():
    from supagent import agent
    from supagent.ledger import INVESTIGATION_TASKS

    assert "records_about" in agent.TOOLS_OF["investigation"] and "records_about" in INVESTIGATION_TASKS[-1]
    assert any("records_about with the parts you blame" in str(v) for k, v in vars(agent).items() if k.isupper())


def test_a_record_table_that_is_a_pattern(app, monkeypatch):
    """(0.10.7) A record table read through an index pattern (k8s-events-*) was checked as a field name: records_about
    failed whole ("not a field name: 'k8s-events-*'") and the investigation found no change at all."""
    import datetime as dt

    from superset.extensions import security_manager

    from supagent import tools as T

    class Db:
        id = 1

    monkeypatch.setattr(T, "_table_database", lambda table, _x: Db())
    monkeypatch.setattr(T, "_time_field", lambda table, _x: "firstTimestamp")
    monkeypatch.setattr(security_manager, "raise_for_access", lambda **kw: None)
    sent = []

    def run(sql, described=False):
        sent.append(sql)
        return [(0,)]

    with app.app_context():
        out = T._records(run, "k8s-events-*", Db(), "(\"reason\" IN ('x'))", dt.datetime(2026, 9, 28, 14, 0), 2)
    assert out == {"table": "k8s-events-*", "since": "2026-09-26 14:00", "records": 0}
    assert sent and 'FROM "k8s-events-*"' in sent[0]


def test_the_records_begun_just_after_the_time_given(night, app):  # noqa: F811
    """(0.10.7) A slowdown from 14:05 asked "until 12:00": the change begun at 14:00 was not found. The records begun
    in the hours just after the time given are listed apart."""
    from superset.extensions import db

    from supagent import tools as T
    from supagent.models import KObject, Source
    from supagent.security import acting_as

    night.con.execute("INSERT INTO \"changes\" VALUES ('2026-09-23 01:30:00', 'srv-5', 'Export run on srv-5', 'CHG-9')")
    with app.app_context():
        src = db.session.query(Source).first()
        made = [KObject(source_id=src.id, kind="field", name="TARGET", parent="changes", data_type="keyword", stats={}),
                KObject(source_id=src.id, kind="field", name="WHAT", parent="changes", data_type="text", stats={})]
        db.session.add_all(made)
        db.session.commit()
        try:
            with acting_as("admin"):
                got = T.records_about(names=["srv-5"], until="2026-09-23 00:10", days=1)
        finally:
            for o in made:
                db.session.delete(o)
            db.session.commit()
    table = got["tables"][0]
    assert table["records"] == 0 and table["just_after"][0]["TICKET"] == "CHG-9", table
    assert "just_after" in got["note"]
