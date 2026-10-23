"""(0.11.8.3) SQLAlchemy-Utils walks every object of the session after each flush for its aggregated attributes; none
is declared in Superset nor in supagent, and a learning holding a wiki's facts, values and links spent most of its time
there (one walk per link proposed). The walk is skipped while no aggregated attribute is declared, and made as before as
soon as one is."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session


@pytest.fixture()
def walks(ctx, monkeypatch):
    n = {"walks": 0}
    real = Session.__iter__

    def counted(self):
        n["walks"] += 1
        return real(self)
    monkeypatch.setattr(Session, "__iter__", counted)
    return n


def _flush_one() -> None:
    from superset.extensions import db

    from supagent.models import Meta

    db.session.add(Meta(key="test-aggregates-guard", value="1"))
    db.session.flush()
    db.session.rollback()


def test_no_walk_of_the_session_while_no_aggregated_attribute_is_declared(walks):
    from sqlalchemy_utils import aggregates

    assert not aggregates.manager.generator_registry
    _flush_one()
    assert walks["walks"] == 0


def test_the_walk_is_made_as_soon_as_an_aggregated_attribute_is_declared(walks, monkeypatch):
    from sqlalchemy_utils import aggregates

    from supagent.models import Meta

    monkeypatch.setitem(aggregates.manager.generator_registry, Meta, [])
    _flush_one()
    assert walks["walks"] >= 1
