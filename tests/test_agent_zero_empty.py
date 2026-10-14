"""(0.10.9.1) A real 0 in a query's result called "no data" (and asked back): the answer is sent back once."""
from __future__ import annotations

import json


def _trace(row):
    return [{"tool": "execute_sql", "status": "done", "args": {"request": {"sql": "SELECT SUM(x) AS total_failed"}},
             "result": json.dumps({"success": True, "rows": [row] if row is not None else [], "row_count": 1})}]


SAID = ("I checked the counter of failed orders on 25 September, but the metric had no data collected for that date: "
        "I cannot provide a count. Would you like me to look at another day?")


def test_a_zero_row_called_no_data_is_sent_back():
    from supagent.agent import EMPTY_ZERO_NUDGE, zero_called_empty

    got = zero_called_empty(SAID, _trace({"total_failed": 0.0}))
    assert got and got[1] == "total_failed"
    assert "real zero" in EMPTY_ZERO_NUDGE.format(said=got[0], col=got[1])


def test_an_answer_that_gives_the_zero_is_kept():
    from supagent.agent import zero_called_empty

    assert zero_called_empty("**0** orders failed on 25 September (no data issue).",
                             _trace({"total_failed": 0})) is None
    assert zero_called_empty("No orders failed: the count is zero.", _trace({"total_failed": 0})) is None


def test_an_empty_or_missing_result_is_no_real_zero():
    from supagent.agent import zero_called_empty

    assert zero_called_empty(SAID, _trace({"total_failed": None})) is None
    assert zero_called_empty(SAID, _trace(None)) is None
    assert zero_called_empty(SAID, _trace({"total_failed": 3})) is None
    assert zero_called_empty(SAID, []) is None
