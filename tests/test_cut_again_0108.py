"""(0.10.8) An answer cut in the middle was asked again once and came back cut again ("| Hour | ... | Sep 27"): its
context, near the model's limit, left it no room to write. Cut a second time, the older tool results are cut short
and the answer is asked once more."""

from __future__ import annotations

import json

BIG = json.dumps({"success": True, "columns": [{"name": "t"}, {"name": "v"}],
                  "rows": [{"t": f"2031-03-02 {h:02d}:00", "v": h} for h in range(24)] * 20, "row_count": 480})


def test_cut_twice_the_older_results_are_shortened(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    sql = lambda k: {"request": {"database_id": 1, "sql": f"SELECT t, v FROM m{k}"}}  # noqa: E731
    cut = "## Metrics\n\n| t | v |\n|---|---|\n| 2031-03-02 00:00 | 0"
    whole = "## Metrics\n\n| t | v |\n|---|---|\n| 2031-03-02 00:00 | 0 |\n\nThe values grew every hour."
    a, _ran = agent_with(monkeypatch, [call("execute_sql", sql(1)), call("execute_sql", sql(2)),
                                       call("execute_sql", sql(3)), say(cut), say(cut), say(whole)] + [say(whole)] * 3,
                         results=lambda n, args: BIG)
    answer, _trace = a.ask("How did the values move on 2 March?")
    assert answer.startswith(whole)
    seen = a.llm.seen[-1]
    tools = [m for m in seen if m["role"] == "tool"]
    assert any("[shortened" in str(m["content"]) for m in tools[:-1]) and "[shortened" not in str(tools[-1]["content"])
