"""(0.10.7, obs7dev-m) "Which servers of rack <r> had network receive errors on <a day> between <two times>?": the
queries found the servers (the receive errors' counter, the inventory's rack); the check of named values took
"network" for the value network of the inventory's team field and sent the answer back asking for team =
'network', and the answer went to the network team's switches. A value's word that the question writes as part of
the name of a table the queries read, with the word after it or before it in that name, is no value."""
from __future__ import annotations

from test_knowledge import world  # noqa: F401  (the fixture)


def test_a_word_of_a_queried_tables_name_is_no_value(world):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge.named import unused
    from supagent.knowledge.store import upsert
    from supagent.models import KObject

    upsert(world["run"], world["s_jobs"], "field", "jobs", "TEAM",
           {"data_type": "keyword", "stats": {"cardinality": 2, "values": ["infra", "network"]}})
    db.session.commit()
    try:
        assets = 'SELECT "NAME" FROM "jobs" WHERE "RACK" = \'r-1\''
        errs = ('SELECT "instance", SUM(rate) FROM "zq_network_receive_errs_total" WHERE ts >= TIMESTAMP '
                '\'2026-09-27 06:40\' GROUP BY "instance"')
        q = "Which servers of rack r-1 had network receive errors on 27 September between 06:40 and 07:35?"
        assert unused(q, [assets, errs]) == []
        assert unused("How many network servers are in rack r-1?", [assets, errs]) == [("network", "TEAM", "jobs")]
        assert unused(q, [assets]) == [("network", "TEAM", "jobs")]    # the counter not read: its name is not there
    finally:
        db.session.query(KObject).filter(KObject.name == "TEAM").delete()
        db.session.commit()
