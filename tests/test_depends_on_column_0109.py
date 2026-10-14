"""(0.10.9) A table's "Depends on" column says what its row's part needs, from the dependent's side: it was read as
calls ("alertmanager depends on prometheus" became alertmanager calls prometheus, when prometheus sends its alerts to
alertmanager). It is a dependency now, in the page's own direction (a flow known the other way round is no reason to
drop it: that flow may be the one read wrong)."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_prose_010 import facts
from test_second_pass_0105 import _clean, _repo, _state


def test_a_depends_on_column_is_a_dependency_not_a_call(ctx):
    text = ("Component | Hosts | Depends on\nzqalert | obs-1 | zqprom, zqmailer\nzqapi | api-1 | zqdb\n"
            "zqprom | obs-1 | None\n")
    t = facts(text, parts=("zqalert", "zqprom", "zqmailer", "zqapi", "zqdb"))
    assert {("zqalert", "uses", "zqprom"), ("zqalert", "uses", "zqmailer"), ("zqapi", "uses", "zqdb")} <= t
    assert not any(v == "calls" for _s, v, _o in t)
    t = facts("Service | Calls\nzqapi | zqdb\n", parts=("zqapi", "zqdb"))
    assert ("zqapi", "calls", "zqdb") in t                                  # a "Calls" column: calls, as before


PAGE = {
    "README.md": "# Components\n\n| Component | Hosts | Depends on |\n|---|---|---|\n"
                 "| zqalert | obs-1 | zqprom |\n| zqapi | api-1 | zqdb |\n\n"
                 "# Alerting\n\nzqprom sends to zqalert.\n",
}


def test_a_dependency_is_exported_as_one(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.models import Facet

    made = [Facet(facet="application", value=v, status="approved", source="admin")
            for v in ("zqalert", "zqprom", "zqapi", "zqdb")]
    db.session.add_all(made)
    db.session.commit()
    before, d = _state(), _repo(PAGE, name="zqobs")
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert ("zqprom", "sends_to", "zqalert") in rels
        assert ("zqalert", "uses", "zqprom") in rels and ("zqapi", "uses", "zqdb") in rels   # as the page says
        assert ("zqalert", "calls", "zqprom") not in rels
    finally:
        _clean(before, [d])
        for f in made:
            db.session.delete(f)
        db.session.commit()
