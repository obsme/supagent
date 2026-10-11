"""(0.10.7, obs7dev-l) "How many times were the pods killed for memory that morning?" after the root cause of the
morning's errors was found: its queries read the kills, and the answer was the root cause's whole report again, word
for word, the count never said. A follow-up's answer that is the previous answer written again (from its first line)
is sent back once, with the question it has to answer."""
from __future__ import annotations

import json

REPORT = """## Root cause: zqp errors on 2 October around 09:00

### What happened
Between 09:00 and 09:40 the zqp service returned errors: its pods were killed for memory.
- **zqp-a1**: killed at 09:00 and 09:29
- **zqp-b2**: killed at 09:02 and 09:33

### Timeline
- **09:00**: the first kill of zqp-a1, its memory at its limit
- **09:03**: the alert on the error rate of zqp fired
- **09:29-09:33**: the second round of kills, both pods
- **09:38**: the alert on the error rate of zqp resolved

### Memory
The working set of zqp-a1 grew from 1.21 GiB at 08:00 to 1.50 GiB at 08:59, its limit, without falling back: a leak.

### Root cause
The memory leak came with the version deployed on 30 September at 18:00, the day before: its memory grew from the
deployment on, until the limit of its containers was reached in the morning.

### What was ruled out
- The disk pressure of another node: zqp's pods do not run on it.
- The database: no alert and no error of it during that time.

### Impact
The errors lasted until 09:40; the pods were restarted and killed again."""
Q = "How many times were the zqp pods killed for memory that morning?"


def test_the_previous_answer_written_again(ctx):
    from supagent.agent import repeats_previous

    assert repeats_previous(REPORT, REPORT)
    assert repeats_previous(REPORT.replace("until 09:40", "up to 09:40"), REPORT)      # a line changed: still it
    assert not repeats_previous("The zqp pods were killed **4 times** that morning: zqp-a1 at 09:00 and 09:29, "
                                "zqp-b2 at 09:02 and 09:33.", REPORT)
    assert not repeats_previous(REPORT, "")                                             # no answer before
    count_first = "The zqp pods were killed 4 times that morning, twice each:\n" + REPORT
    assert not repeats_previous(count_first, REPORT)    # the count first, then the report: an answer
    short = "\n".join(REPORT.splitlines()[:6]) + "\nzqp-a1 was killed twice, at 09:00 and 09:29."
    assert not repeats_previous(short, REPORT)          # the previous frame kept for a new fact: an answer


def test_it_is_sent_back_once_with_the_question(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "pod"}, {"name": "reason"}, {"name": "at"}],
                       "rows": [{"pod": "zqp-a1", "reason": "OOMKilling", "at": "2026-10-02 09:00:00"},
                                {"pod": "zqp-b2", "reason": "OOMKilling", "at": "2026-10-02 09:02:00"},
                                {"pod": "zqp-a1", "reason": "OOMKilling", "at": "2026-10-02 09:29:00"},
                                {"pod": "zqp-b2", "reason": "OOMKilling", "at": "2026-10-02 09:33:00"}],
                       "row_count": 4})
    sql = {"request": {"database_id": 1, "sql": "SELECT \"pod\", \"reason\", \"at\" FROM \"k8s-events\" WHERE "
                                                 "\"reason\" = 'OOMKilling' AND \"at\" >= '2026-10-02 08:00' AND "
                                                 "\"at\" < '2026-10-02 12:00'"}}
    history = [{"role": "user", "content": "The zqp service returned errors on 2 October around 09:00. Find the root "
                                           "cause."},
               {"role": "assistant", "content": REPORT}]
    count = say("The zqp pods were killed **4 times** for memory that morning: zqp-a1 at 09:00 and 09:29, zqp-b2 at "
                "09:02 and 09:33.")
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), say(REPORT), count, count], results=lambda n, args: rows)
    answer, _trace = a.ask(Q, history)
    assert answer.startswith("The zqp pods were killed **4 times**") and len(ran) == 1
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user"]
    assert any("your previous answer written again" in c and Q in c for c in sent)
    b, _ran = agent_with(monkeypatch, [call("execute_sql", sql), say(REPORT), say(REPORT), say(REPORT)],
                         results=lambda n, args: rows)
    again, _t = b.ask(Q, history)
    assert again.startswith("## Root cause")                         # once: the second one is kept as it is
