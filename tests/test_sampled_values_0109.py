"""(0.10.9) An index learned on a sample of its documents (the first documents of each shard: a big index) knows the
values of its fields that the sample held: a rare value (an error state of an incident's hours) may be missing. Its
lists were read as every value: the rule check took a team rule for another table's when the sample missed the
rule's value, the governed plan's check refused it, and the dictionary, the search's pieces and the Context pages
gave the sample as the field's values. Now they say "seen in a sample" and nothing is refused for it."""

from __future__ import annotations

import pytest


@pytest.fixture()
def sampled(world, app):  # noqa: F811
    from superset.extensions import db

    from supagent.models import KObject, Source

    src = db.session.query(Source).first()
    ix = KObject(source_id=src.id, kind="index", name="zqruns", stats={"docs": 50000, "sampled_docs": 20000})
    f = KObject(source_id=src.id, kind="field", parent="zqruns", name="OUTCOME", data_type="keyword",
                stats={"values": ["DONE", "SKIPPED"], "cardinality": 2})
    db.session.add_all([ix, f])
    db.session.commit()
    yield ix, f
    db.session.delete(f)
    db.session.delete(ix)
    db.session.commit()


from test_knowledge import world  # noqa: E402,F401  (the fixture)


def test_a_sampled_field_never_says_a_value_is_impossible(sampled):
    from superset.extensions import db

    from supagent.knowledge.rulecheck import value_possible

    ix, _f = sampled
    assert value_possible("zqruns", "OUTCOME", "DONE") is True
    assert value_possible("zqruns", "OUTCOME", "ERROR") is None            # a rare value the sample missed: maybe
    ix.stats = {"docs": 50000, "sampled_docs": 50000}                      # learned on all its documents
    db.session.commit()
    assert value_possible("zqruns", "OUTCOME", "ERROR") is False


def test_the_dictionary_and_the_search_say_a_sample_is_a_sample(sampled):
    from supagent.knowledge.describe import _field_line
    from supagent.knowledge.values import learned_whole

    ix, f = sampled
    assert not learned_whole(ix.stats) and learned_whole({"docs": 10, "sampled_docs": 10})
    assert "values seen in a sample (others may exist): DONE, SKIPPED" in _field_line(f, sampled=True)
    assert '"OUTCOME" (keyword) values: DONE, SKIPPED' in _field_line(f)
    from supagent.knowledge.index import _object_pieces

    piece = next(p for p in _object_pieces({ix.id}) if "zqruns" in str(p))
    assert "OUTCOME: DONE, SKIPPED (seen in a sample; others may exist)" in str(piece)
