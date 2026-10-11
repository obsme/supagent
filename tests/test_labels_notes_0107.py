"""(0.10.7, obs7dev-q) "Which metrics compare the pods' memory with their limit?": after two describe_data calls the
answer named both metrics, each described in a list ("- **Purpose**: ...", "**Unit:** bytes"); the check of names no
tool gave took "Purpose" for a name and sent the right answer back; the model then wrote in circles, spoke of "notes"
that "have been removed" (its own repeated lines), and the check of notes claimed as done, twice, replaced the whole
answer by "I have not deleted any note". The keys of a list that describes things are labels, a key written with its
colon inside the bold too; what an answer says was done to a note is checked when the chat speaks of notes."""
from __future__ import annotations

import json


def test_the_keys_of_a_describing_list_are_no_names():
    from supagent.grounding import presented_names

    described = ("### zq_mem_used_bytes\n- **Purpose**: the memory the pod uses\n- **Type**: gauge\n"
                 "- **Unit**: bytes\n\n**Description:** the working set of each container")
    assert presented_names(described) == []
    assert presented_names("**Purpose:** the memory in use") == []           # the colon inside the bold
    assert presented_names("- **Tracy**: 4 trades\n- **Alice**: 2 trades") == ["Tracy", "Alice"]   # names still
    assert presented_names("**zq-node-17:** 3 restarts") == ["zq-node-17"]   # an identifier anywhere


def test_notes_are_checked_in_a_chat_about_notes():
    from supagent.agent import notes_in_play

    assert not notes_in_play(["What is the memory limit of the zq pods?"], [])
    assert notes_in_play(["Delete my note about the zq freeze."], [])
    assert notes_in_play(["yes", "Delete my note about the zq freeze."], [])  # the yes to a deletion
    assert notes_in_play(["yes"], [{"tool": "delete_note", "status": "done", "result": "{}"}])


def test_removed_lines_in_an_answer_on_metrics_are_no_deleted_note(ctx, monkeypatch):
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "pod"}, {"name": "limit_gib"}],
                       "rows": [{"pod": "zq-a1", "limit_gib": 2.0}], "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": "SELECT pod, MAX(value) / 1073741824 AS limit_gib FROM "
                                                 "zq_mem_limit_bytes GROUP BY pod"}}
    said = ("The memory limit of the zq pod zq-a1 is 2 GiB.\n\nNote: the repeated lines of the draft have been "
            "removed.")
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), say(said), say(said)], results=lambda n, args: rows)
    answer, _trace = a.ask("What is the memory limit of the zq pods?")
    assert answer.startswith("The memory limit of the zq pod zq-a1 is 2 GiB.") and len(ran) == 1
    assert "I have not deleted" not in answer and "(Check: no note" not in answer
    b, ran = agent_with(monkeypatch, [say("The personal note \"zq freeze\" has been deleted."),
                                      say("The personal note \"zq freeze\" has been deleted.")])
    answer, _trace = b.ask("Delete my personal note about the zq freeze.")
    assert answer.startswith("I have not deleted any note")                   # a chat about notes: as before
