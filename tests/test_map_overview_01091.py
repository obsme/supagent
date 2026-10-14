"""(0.10.9.1) Map-wide questions: an environment's group asked without its brackets ("what runs on pool-a?" for
"pool-a (production)"), the environment the question names picked among them, and a team asked for read as an owner
question whatever its verb ("who looks after X", "which team runs X")."""
from __future__ import annotations

import pytest


def _values(*names):
    return {i: {"id": i, "name": n, "cat": "server group"} for i, n in enumerate(names, 1)}


def test_a_group_of_one_environment_is_named_without_its_brackets(ctx):
    from supagent.knowledge.brief import _qualified_aliases

    values = _values("pool-a (production)", "pool-a (staging)", "web (ops prod)", "billing (group)",
                     "catalog (beta)", "the (production)")
    got = _qualified_aliases(values, {})
    assert got["pool-a"] == [1, 2]
    assert got["web"] == [3] and got["billing"] == [4]
    assert "catalog" not in got and "the" not in got          # not an environment; a word of every question


@pytest.mark.parametrize("question,expected", [
    ("Which team takes care of the payment gateway?", "owner"),
    ("Who looks after the search index?", "owner"),
    ("Who operates the message bus?", "owner"),
    ("Which teams run the ledger?", "owner"),
    ("What runs on pool-a?", "placement"),
    ("Who consumes the orders topic?", "readers"),
    ("Who uses the address registry?", "callers"),
    ("Which systems go down if the cache fails?", "impact"),
    ("Which team is affected when the billing database is down?", "impact"),
])
def test_the_kind_of_a_map_wide_question(question, expected):
    from supagent.knowledge.communities import intent_of

    assert intent_of(question) == expected


def test_the_environment_the_question_names_picks_the_group():
    from supagent.knowledge.communities import _env_pick

    values = _values("pool-a (production)", "pool-a (staging)", "orders")
    assert _env_pick([1, 2, 3], "What runs on pool-a in prod?", values) == [1, 3]
    assert _env_pick([1, 2, 3], "What runs on pool-a on staging?", values) == [2, 3]
    assert _env_pick([1, 2, 3], "What runs on pool-a?", values) == [1, 2, 3]
