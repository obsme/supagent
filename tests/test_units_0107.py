"""(0.10.7) "The lowest free space was 53.69 GiB (53,687,091,200 bytes)": the bytes divided by 10^9 and written GiB (a
GiB is 1024^3 bytes: 50.00 GiB). Sent back once with the right value."""
from __future__ import annotations

import json

from supagent.agent import binary_misread


def _trace(*values: float) -> list[dict]:
    rows = [{"t": "2026-09-24 03:00", "min_bytes": v} for v in values]
    return [{"tool": "execute_sql", "called": "execute_sql", "status": "done",
             "result": json.dumps({"success": True, "rows": rows})}]


def test_a_gib_computed_with_decimal_factors():
    why = binary_misread("The lowest free space was **53.69 GiB** (53,687,091,200 bytes).", _trace(53687091200.0))
    assert why and "50.00 GiB" in why and "1024^3" in why
    assert binary_misread("It went down to 5.37 GiB.", _trace(5.36870912e9))     # a result written 5.36870912e+09


def test_right_or_other_sizes_pass():
    assert binary_misread("The lowest free space was **50.00 GiB** (53,687,091,200 bytes).", _trace(53687091200.0)) is None
    assert binary_misread("The lowest free space was 53.69 GB.", _trace(53687091200.0)) is None   # decimal, said so
    assert binary_misread("It used 12 GiB of 16 GiB.", _trace(3.5)) is None                        # no bytes behind it
    assert binary_misread("No size here.", _trace(53687091200.0)) is None


def test_the_answer_written_again_after_it_says_nothing_of_the_check(ctx, monkeypatch):
    """(0.10.7) "You're right, let me correct the memory values to GiB." opened the answer written again after the
    units check (2 of 726 open answers): the words about a check go after any check of the answer."""
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "min_bytes"}], "rows": [{"min_bytes": 53687091200.0}],
                       "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": "SELECT MIN(\"free_bytes\") AS min_bytes FROM \"zq-disks\""}}
    wrong = say("The lowest free space was **53.69 GiB** (53,687,091,200 bytes).")
    again = say("You're right, let me correct the value to GiB.\n\nThe lowest free space was **50.00 GiB** "
                "(53,687,091,200 bytes).")
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), wrong, again, again], results=lambda n, args: rows)
    answer, _trace = a.ask("What was the lowest free space of the disks?", [])
    assert answer.startswith("The lowest free space was **50.00 GiB**") and "You're right" not in answer


def test_an_answer_written_before_the_calls_ran_out_is_given(ctx, monkeypatch):
    """(0.10.7, obs7dev-m) The model wrote an answer, a check sent it back, the calls ran out on more lookups and the
    model wrote nothing at the end: the user got "the model wrote no text" and a raw result. The latest answer it
    wrote is given then, with the usual marks."""
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "min_bytes"}], "rows": [{"min_bytes": 53687091200.0}],
                       "row_count": 1})
    first = ("The lowest free space of the zq disks was **53.69 GiB** (53,687,091,200 bytes), on the data volume of "
             "the first database server, during the nightly backup window. The other volumes stayed well above it: "
             "the logs volume and the system volume kept more than half of their space free during the whole day.")
    replies = [call("execute_sql", {"request": {"database_id": 1, "sql": "SELECT MIN(\"free_bytes\") AS min_bytes "
                                                                         "FROM \"zq-disks\""}}), say(first)]
    replies += [call("execute_sql", {"request": {"database_id": 1, "sql": f"SELECT MIN(\"free_bytes\") AS min_bytes "
                                                                           f"FROM \"zq-disks\" LIMIT {n}"}})
                for n in range(1, 12)]
    replies += [say(""), say(""), say("")]
    a, ran = agent_with(monkeypatch, replies, results=lambda n, args: rows)
    answer, _trace = a.ask("What was the lowest free space of the disks?", [])
    assert answer.startswith("The lowest free space of the zq disks was") and "wrote no text" not in answer
    assert "the tool calls of one answer were used up" in answer


def test_a_correction_asks_for_the_whole_answer_again(ctx):
    """(0.10.7, obs7dev-o) The root cause of a checkout's errors (the pods killed for memory, the version that leaked)
    was sent back for its sizes written GiB with decimal factors; the model wrote again the sizes only, and the root
    cause was lost (then repeated by the follow-up). A check that corrects one detail asks for the whole answer."""
    from supagent import agent as A

    for nudge in (A.BINARY_NUDGE, A.COUNT_NUDGE, A.ABSENT_ZERO_NUDGE):
        assert "write the whole answer again" in nudge
    said = A.BINARY_NUDGE.format(said="53.69 GiB", raw=53687091200.0, k=3, dec="GB", unit="GiB", right=50.0)
    assert "(not only the sizes)" in said and said.endswith("this check.)")


def test_a_step_announced_at_the_end_does_not_replace_the_answer(ctx, monkeypatch):
    """(0.10.7, obs7dev-q) The answer was sent back by a check, the calls ran out, and the last text only announced a
    step ("Let me also get the max memory in GiB:"): that was the whole answer the user got. The answer written
    before is given instead of an announced step."""
    from test_agent_loop import agent_with, call, say

    from supagent.agent import STEP_ONLY

    assert STEP_ONLY.match("Let me also get the max memory in GiB:")
    assert not STEP_ONLY.match("The cache's memory was halved at 10:12.\nLet me know if you need more.")
    rows = json.dumps({"success": True, "columns": [{"name": "min_bytes"}], "rows": [{"min_bytes": 53687091200.0}],
                       "row_count": 1})
    first = ("No: the nightly warnings of the zq cache come every night at 02:00 and stop by 03:00, as on every day of "
             "the week before. The problem of that morning began at 10:12 with the change that halved the cache's "
             "memory to **53.69 GiB** (53,687,091,200 bytes) and ended at 11:02 when it was put back: its misses rose "
             "from 20 % to 85 % in that hour only, the nightly ones staying at 21 to 27 %.")
    replies = [call("execute_sql", {"request": {"database_id": 1, "sql": "SELECT MIN(\"free_bytes\") AS min_bytes "
                                                                         "FROM \"zq-disks\""}}), say(first)]
    replies += [call("execute_sql", {"request": {"database_id": 1, "sql": f"SELECT MIN(\"free_bytes\") AS min_bytes "
                                                                           f"FROM \"zq-disks\" LIMIT {n}"}})
                for n in range(1, 12)]
    replies += [say("Let me also get the max memory in GiB:")] * 4
    a, ran = agent_with(monkeypatch, replies, results=lambda n, args: rows)
    answer, _trace = a.ask("zq warns every night about its cache. Was that related to the morning's problem?", [])
    assert answer.startswith("No: the nightly warnings") and "Let me also get" not in answer
