"""(0.10.6) A question about how the system is built (its parts, a chain, what a failure reaches) gets the System map,
the documents and the Context first: the data's objects lower and no "where the value is" first (on a lab map, "How
does a user request reach the database?" got "Where the value user is", request metrics and charts first); a
question about figures or the data's objects keeps them."""

from __future__ import annotations


def test_which_questions_are_about_the_systems_build(ctx):
    from supagent.knowledge.search import structural

    for q in ("How does a user request reach the database? Give the chain of parts.",
              "Alert emails do not arrive: which parts are involved, in order?",
              "Which applications make up the ticketing platform?", "What does the api depend on?",
              "If the message queue goes down, which services are affected?", "Which servers make up the risk grid?",
              "If db-01 is down, which applications stop working?"):
        assert structural(q), q
    for q in ("Which metric measures the duration of the jobs?", "How many orders failed yesterday?",
              "In which field of the jobs index is the server name?", "What is the revenue of 23 September?",
              "Which jobs had the most errors today?",
              "Which server had the least available memory on 23 September, and how low did it go?",
              "Break that official PnL down by attribution component."):
        assert not structural(q), q


def test_a_structure_question_gets_the_datas_objects_after_the_other_pieces_and_no_value_first(ctx, monkeypatch):
    from supagent.knowledge import search as S

    monkeypatch.setattr(S, "_values", lambda q, kinds, skip: [{"ref": "value:x", "kind": "value", "title": "v",
                                                               "text": ""}])
    pieces = [{"ref": f"r{i}", "kind": kd, "title": f"t{i}", "text": ""} for i, kd in
              enumerate(("metric", "index", "chart", "doc", "map", "metric", "context", "doc"))]
    monkeypatch.setattr(S, "_search", lambda query, k, kinds, lower, skip, n=None: list(pieces))
    monkeypatch.setattr("supagent.knowledge.index.refresh_map", lambda: None)
    monkeypatch.setattr(S.settings, "get", lambda key: {"search.top_k": 4, "search.values": True}.get(key, False))
    got = S.search("Which parts are involved, in order, when an alert is sent?", rerank=False)
    assert [f["kind"] for f in got] == ["doc", "map", "context", "doc"]          # the data's objects after them
    got = S.search("How many alerts were sent yesterday?", rerank=False)
    assert got[0]["kind"] == "value" and [f["kind"] for f in got[1:3]] == ["metric", "index"]   # figures: as before
