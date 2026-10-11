"""(0.10.8, the team's request of 11 October) "What is the number of errors?" as the first message, with logs and
metrics of many applications and components: the agent made many calls over everything. A short first question asking
a measure of nothing named is asked back at once, with the main parts suggested (and a period when none is said)."""

from __future__ import annotations

PARTS = {"application": ["app-a", "app-b", "app-c"], "component": ["db-x"], "server": ["srv-1", "srv-2"]}


def _open(question, history=None, parts=PARTS):
    from supagent.knowledge.ambiguity import open_measure

    return open_measure(question, history, parts_of=lambda: parts)


def test_a_measure_of_nothing_named_is_asked_back():
    found = _open("What is the number of errors?")
    assert found and found["kind"] == "open" and found["said"] == "errors" and not found["period"]
    assert _open("what is the nulber of errors")                          # a word misspelled
    assert _open("How many failures yesterday?")["period"]
    assert _open("Combien d'erreurs aujourd'hui ?")


def test_not_when_something_is_named_said_before_or_too_few_parts():
    assert _open("How many errors did app-a log yesterday?") is None       # a part named
    assert _open("What is the number of errors?", [{"role": "user", "content": "How is app-b?"}]) is None
    assert _open("What is the number of errors?", parts={"application": ["app-a"]}) is None   # nothing to choose
    assert _open("How many orders were placed today?") is None             # no measure of failures, latency ...
    assert _open("What is the number of errors in the nightly batch of the finance team since Monday?") is None


def test_the_note_suggests_the_parts_and_a_period():
    from supagent.knowledge.ambiguity import note

    said = note(_open("What is the number of errors?"))
    assert said.startswith("(Ask back first") and "app-a, app-b, app-c" in said and "db-x" in said
    assert "which period" in said and "run no query" in said
    assert "which period" not in note(_open("How many errors yesterday?"))


def test_the_agent_asks_back_without_a_call(ctx, monkeypatch):
    from supagent.knowledge import ambiguity
    from test_agent_loop import agent_with, say

    monkeypatch.setattr(ambiguity, "map_parts", lambda: PARTS)
    back = "Which application or component do you mean (app-a, app-b, app-c, db-x, or all of them), and for which day?"
    a, ran = agent_with(monkeypatch, [say(back)] * 3)
    answer, _trace = a.ask("What is the number of errors?")
    first = next(m["content"] for m in a.llm.seen[0] if m["role"] == "user")
    assert "Ask back first" in first and answer.startswith(back) and ran == []
    assert a.llm.choices[0] == "none" and "ending with a question mark" in first   # asked back with no call
    statement = "There are errors in pricing, in the jobs and in HTTP requests. Please tell me which you mean."
    a, ran = agent_with(monkeypatch, [say(statement), say(back), say(back)])
    answer, _trace = a.ask("What is the number of errors?")
    assert answer.startswith(back) and ran == [] and a.llm.choices[:2] == ["none", "none"]   # sent back: no call still


def test_only_an_open_question_is_asked_back_with_no_call(ctx, monkeypatch):
    """A name several values match (or nothing to refer to) keeps its note and its check, its first turn free: only
    the open question, checked on the labs' question sets, gets a first turn with no call."""
    from supagent.knowledge import ambiguity
    from test_agent_loop import agent_with, say

    monkeypatch.setattr(ambiguity, "ask_first", lambda q, h: {"kind": "choice", "said": "the book", "field": "BOOK",
                                                             "candidates": ["B1", "B2"]})
    back = "Which book do you mean, B1 or B2?"
    a, _ran = agent_with(monkeypatch, [say(back)] * 3)
    a.ask("How did the book do yesterday?")
    assert a.llm.choices[0] is None


def test_metrics_asked_of_nothing_named_too():
    for q in ("What is the CPU usage?", "how is the memory?", "Show me the latency", "What is the disk usage today?",
              "Quelle est la charge ?", "what's the throughput", "How many pods are running?"):
        assert _open(q), q
    assert _open("What is the CPU usage of srv-1?") is None                  # a server named
    assert _open("What was the memory of app-b yesterday?") is None
    assert "srv-1, srv-2" in __import__("supagent.knowledge.ambiguity", fromlist=["note"]).note(_open("How is the load?"))
