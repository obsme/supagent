"""(0.10.8) "How many of its failures were timeouts?" counted with a word searched in a text field (LIKE '%timeout%'),
which found none, and answered "none (0 out of ...)": TIMEOUT is a value of another field of the same table. A zero
from such a search, when the word is a learned value of another field no query used, is sent back once."""

from __future__ import annotations

import json

from test_knowledge import world  # noqa: F401  (the fixture)

ZERO = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 0}], "row_count": 1})


def _step(sql, result=ZERO):
    return {"tool": "execute_sql", "status": "done", "args": {"request": {"database_id": 1, "sql": sql}},
            "result": result}


def test_a_zero_from_a_text_search_for_a_value_of_another_field(world):  # noqa: F811
    from superset.extensions import db

    from supagent.agent import zero_by_text
    from supagent.knowledge.store import upsert

    upsert(world["run"], world["s_jobs"], "field", "jobs", "FAIL_KIND",
           {"data_type": "keyword", "stats": {"cardinality": 3, "values": ["TIMEOUT", "OOM", "CRASH"]}})
    db.session.commit()
    like = 'SELECT COUNT(*) AS n FROM "jobs" WHERE "STATE" = \'FAILED\' AND "NOTE" LIKE \'%timeout%\''
    said = "None of its failures were timeouts (0 out of 12)."
    assert zero_by_text(said, [_step(like)]) == ("timeout", "NOTE", "TIMEOUT", "FAIL_KIND", "jobs")
    kind = 'SELECT COUNT(*) AS n FROM "jobs" WHERE "STATE" = \'FAILED\' AND "FAIL_KIND" = \'TIMEOUT\''
    assert zero_by_text(said, [_step(like), _step(kind)]) is None                  # that field was used
    some = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 4}], "row_count": 1})
    assert zero_by_text("4 of them were timeouts.", [_step(like, some)]) is None    # not a zero
    other = 'SELECT COUNT(*) AS n FROM "jobs" WHERE "NOTE" LIKE \'%disk%\''
    assert zero_by_text("No failure mentions the disk.", [_step(other)]) is None   # no field holds the word
