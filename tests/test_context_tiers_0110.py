"""(0.11.0) The agent's context in tiers (the owner's request of 2026-10-17): what the team keeps first, each said once
(a copy or a text said whole by another left out, never two texts that differ in what they say); then the chat, the
newest messages first, whole exchanges, in the room left; then the documentation: the LLM context's lines about the
question, never the whole page, nothing given twice."""
from __future__ import annotations

import json

import pytest

from test_context_profile_01091 import _evidence


@pytest.mark.parametrize("a,b,one", [
    ("Always give durations in minutes, please.", "Give durations in minutes", True),
    ("Durations in minutes", "Give the durations in minutes", True),
    ("Use UTC for all times.", "use utc for all times", True),
    ("Give durations in minutes", "Give durations in seconds", False),          # a unit: never one
    ("Give durations in minutes for the desk Y", "Give durations in minutes", False),   # a condition added
    ("Give durations in minutes on desk Y", "Give durations in minutes", False),
    ("Report sizes in GiB, not GB", "Report sizes in GiB", False),             # a negation added
    ("Don't give durations in minutes", "Give durations in minutes", False),  # (review) "n't" is "not"
    ("Do not include VAT, do not count refunds", "Do not include VAT, count refunds", False),
    ("Failed job durations in minutes", "Job durations in minutes", False),     # a qualifier: another subject
    ("latency > 500 ms", "latency < 500 ms", False),                          # an operator
    ("status != 200", "status = 200", False),
    ("UTC -2", "UTC +2", False),                                              # a sign
    ("Revenue must be net", "Revenue may be net", False),                    # a modal verb
    ("Filter status 'FAILED'", "Filter status 'failed'", False),             # a quoted value as written
    ("A depends on B", "B depends on A", False),                               # the order says who depends
    ("The orders-db primary is db-a", "The orders-db primary is db-b", False),  # a name of the data
    ("Use UTC for all times.", "All times are in UTC", False),                 # alike: To review, not merged
])
def test_two_texts_are_one_only_when_they_say_the_same(a, b, one):
    from supagent.knowledge.contextplan import same, says

    assert same(a, b) is one and (says(a, b) or says(b, a)) is one


def test_copies_are_given_once():
    from supagent.knowledge.contextplan import unique

    keys, dropped = unique([(1, "Durations of the jobs in minutes"), (2, "Give durations in seconds"),
                            (3, "Show the durations of the jobs in minutes"), (4, "durations of the jobs in minutes"),
                            (5, "Don't give durations of the jobs in minutes")])
    assert keys == [1, 2, 3, 5] and dropped == {4: 1}                        # "show": another word, kept
    keys, dropped = unique([(1, "Count the refunds apart"), (2, "Give durations in minutes"),
                            (3, "Don't count the refunds apart")], said=["Always count the refunds apart."])
    assert keys == [2, 3] and dropped == {1: "said"}


def test_many_memories_are_compared_at_once():
    import time

    from supagent.knowledge.contextplan import unique

    items = [(i, f"Rule {i}: the batch {i % 97} durations in minutes for team {i % 13}") for i in range(3000)]
    t0 = time.time()
    keys, _dropped = unique(items + [(9999, items[5][1])])
    assert time.time() - t0 < 1.0 and 9999 not in keys and len(keys) == 3000      # one pass, no pairs


def test_the_chat_is_fitted_newest_first_in_whole_exchanges():
    from supagent.knowledge.contextplan import fit_history

    h = [{"role": "user", "content": "q1"}, {"role": "assistant", "content": "a" * 1000},
         {"role": "user", "content": "q2"}, {"role": "assistant", "content": "b" * 1000},
         {"role": "user", "content": "q3"}, {"role": "assistant", "content": ""},      # an answer not written yet
         {"role": "assistant", "content": "c" * 500}]
    assert fit_history(h, 10 ** 6, 3000) == [x for x in h if x["content"]]          # room: all of it
    got = fit_history(h, 1600, 3000)
    assert [x["content"][:2] for x in got] == ["q2", "bb", "q3", "cc"]              # never an answer alone first
    assert [x["content"][:2] for x in fit_history(h, 0, 3000)] == ["q3", "cc"]       # the last exchange always
    assert len(fit_history(h, 1600, 100)) == 6                                       # counted as each is cut
    two = [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "x" * 900},
           {"role": "assistant", "content": "y" * 900}]
    assert [x["content"][:2] for x in fit_history(two, 0, 3000)] == ["u1", "xx", "yy"]   # (review) its question kept
    failed = [{"role": "user", "content": "u1"}, {"role": "assistant", "content": "a1"},
              {"role": "user", "content": "u2"}, {"role": "assistant", "content": "a2"},
              {"role": "user", "content": "u3 (its answer failed)"}]
    assert [x["content"][:2] for x in fit_history(failed, 0, 3000)] == ["u2", "a2", "u3"]   # the last answered one
    assert fit_history([{"role": "assistant", "content": "hello"}, {"role": "user", "content": "q"}], 10 ** 6, 99) == \
        [{"role": "user", "content": "q"}]                                         # never an answer first


def _page() -> str:
    from supagent.knowledge.llm_context import filtered, pages

    return filtered(pages(_evidence())[0]["content"], {1, 2}, ("## Rules of the team",), entries=True)


def test_the_llm_context_gives_its_lines_about_the_question_only(ctx):
    from supagent.knowledge.contextplan import excerpt

    page = _page()
    assert "<!-- e:2 -->" in page                                   # the entry a line says, kept for the agent
    got = excerpt(page, "What was the net revenue last week?", 10000)
    assert "Net revenue" in got and "<!--" not in got
    assert "salaries" not in got and "Payslip" not in got           # nothing the question asks of
    assert excerpt(page, "Hello, who are you?", 10000) == ""        # nothing about the question: nothing
    assert excerpt(page, "What was the net revenue?", 10000, shown_ids=[2]) == ""      # given by the search
    assert excerpt(page, "What was the net revenue?", 10000, shown_titles=["Net revenue"]) == ""
    whole = excerpt(page, "How many orders were refunded, and the payroll of the salaries?", 10000)
    assert "orders" in whole and "salaries" in whole
    assert len(excerpt(page, "How many orders were refunded, and the payroll of the salaries?", 120)) <= 120
    db = excerpt(page, "Anything new there?", 10000, databases=["shop"])
    assert "`orders`" in db and "salaries" not in db                # the main data of the database asked about


def test_memories_are_given_once(ctx):
    from superset import security_manager
    from superset.extensions import db

    from supagent.knowledge.memory import add, prompt_block
    from supagent.models import Memory

    user = security_manager.find_user("admin") or db.session.query(security_manager.user_model).first()
    made = [add(user.id, "Give durations in minutes", kind="preference"),
            add(user.id, "Always give durations in minutes, please.", kind="preference"),
            add(user.id, "Give durations in seconds for the jobs", kind="preference"),
            add(user.id, "Count the refunds apart", kind="rule")]
    try:
        shown: set[str] = set()
        text = prompt_block(user.id, shown, said=["Always count the refunds apart."])
        assert text.count("durations in minutes") == 1                       # the copy: once
        assert "durations in seconds for the jobs" in text                   # another unit: kept
        assert "refunds apart" not in text                                   # a rule of the team says it
        assert {f"memory:{m.id}" for m in made} <= shown                     # none found again by the search
        before = prompt_block(user.id, set())                                # without the tiers: as before
        assert before.count("durations in minutes") == 2 and "refunds apart" in before
    finally:
        db.session.query(Memory).filter(Memory.id.in_([m.id for m in made])).delete(synchronize_session=False)
        db.session.commit()


def test_a_learned_way_is_given_once():
    from supagent.agent import _distinct_recipes

    rs = [{"id": 1, "query": "SELECT  count(*) FROM orders", "tool": "execute_sql", "database_id": 1},
          {"id": 2, "query": "select count(*) from orders", "tool": "execute_sql", "database_id": 1},
          {"id": 3, "query": "SELECT 1", "tool": "execute_sql", "database_id": 1},
          {"id": 4, "query": "select count(*) from orders", "tool": "execute_sql", "database_id": 2}]   # another db
    assert [r["id"] for r in _distinct_recipes(rs)] == [1, 3, 4]


def test_the_prompt_in_tiers(ctx, monkeypatch):
    import types

    from superset.extensions import db

    from supagent import budget, settings
    from supagent.agent import LLM_CONTEXT_HEAD, LLM_EXCERPT_HEAD, Agent
    from supagent.knowledge import llm_context as L
    from supagent.knowledge.context import _hash, save_page
    from supagent.models import ContextPage
    from supagent.security import acting_as

    for page in L.pages(_evidence()):
        save_page(page, "facts", _hash([page["content"]]))
    db.session.commit()
    monkeypatch.setattr("supagent.security.visible_databases", lambda: {1, 2})
    monkeypatch.setattr(budget, "window", lambda: 131072)
    history = []
    for i in range(30):
        history += [{"role": "user", "content": f"question {i} " + "q" * 3000},
                    {"role": "assistant", "content": f"answer {i} " + "a" * 12000}]
    try:
        with acting_as("admin"):
            agent = Agent("admin", rich_results=True, llm=types.SimpleNamespace())
            try:
                msgs = agent.prompt("What was the net revenue last week?", history)
                assert LLM_CONTEXT_HEAD not in msgs[0]["content"]          # not whole in the instructions
                assert LLM_EXCERPT_HEAD.strip() in msgs[-1]["content"] and "Net revenue" in msgs[-1]["content"]
                assert "salaries" not in msgs[-1]["content"]
                chat = msgs[1:-1]
                assert chat[0]["role"] == "user" and chat[-1]["content"].startswith("answer 29")
                assert 2 <= len(chat) < 60                                 # the newest that fit the room
                size = sum(len(m["content"]) for m in msgs) + agent._specs_chars()
                assert size <= budget.start_room() + budget.size("search_chars") + 20000
                assert agent.chat_left_out == 40 - len(chat)                # of the last 40 (HISTORY_MESSAGES)
                assert "sum(amount) of the paid orders" not in agent.support.text   # the excerpt: no support of its own
                settings.set_value("agent.context_tiers", False)            # off: as 0.10.12
                msgs = agent.prompt("What was the net revenue last week?", history)
                assert LLM_CONTEXT_HEAD in msgs[0]["content"] and LLM_EXCERPT_HEAD.strip() not in msgs[-1]["content"]
                assert len(msgs) == 2 + 40
            finally:
                settings.set_value("agent.context_tiers", None)
                agent.close()
    finally:
        db.session.query(ContextPage).filter(ContextPage.slug.in_((L.SLUG_FULL, L.SLUG_LIGHT))).delete()
        db.session.commit()


def _page_saved(extra_entries=()):
    from superset.extensions import db

    from supagent.knowledge import llm_context as L
    from supagent.knowledge.context import _hash, save_page

    ev = _evidence()
    ev["entries"] = ev["entries"] + list(extra_entries)
    for page in L.pages(ev):
        save_page(page, "facts", _hash([page["content"]]))
    db.session.commit()


def _drop_pages():
    from superset.extensions import db

    from supagent.knowledge import llm_context as L
    from supagent.models import ContextPage

    db.session.query(ContextPage).filter(ContextPage.slug.in_((L.SLUG_FULL, L.SLUG_LIGHT))).delete()
    db.session.commit()


def test_the_page_stays_support_and_is_given_without_the_search(ctx, monkeypatch):
    """(review) The page's quoted values count as said whether or not a line of it was given; the lines are given
    with the search turned off too; the room the chat gets counts the tools this question is sent."""
    import types

    from supagent import budget, settings
    from supagent.agent import LLM_EXCERPT_HEAD, Agent
    from supagent.security import acting_as

    _page_saved([{"id": 9, "title": "Settled", "classification": "glossary", "content": "a ticket in state 'settled' "
                  "is closed", "database_id": 1}])
    monkeypatch.setattr("supagent.security.visible_databases", lambda: {1, 2})
    monkeypatch.setattr(budget, "window", lambda: 131072)
    try:
        with acting_as("admin"):
            agent = Agent("admin", rich_results=True, llm=types.SimpleNamespace())
            try:
                msgs = agent.prompt("What is the weather like?")
                assert LLM_EXCERPT_HEAD.strip() not in msgs[-1]["content"]        # nothing about the question
                assert "settled" in agent.support.text                             # its quoted values: support
                settings.set_value("search.enabled", False)
                msgs = agent.prompt("What was the net revenue last week?")
                assert LLM_EXCERPT_HEAD.strip() in msgs[-1]["content"] and "Net revenue" in msgs[-1]["content"]
                settings.set_value("search.enabled", None)
                monkeypatch.setattr(budget, "window", lambda: None)               # a server that states none
                chat = [{"role": "user", "content": "How many orders yesterday?"},
                        {"role": "assistant", "content": "There were 1,204 orders yesterday. " * 40},
                        {"role": "user", "content": "And the day before?"},
                        {"role": "assistant", "content": "There were 1,180 orders the day before. " * 40}]
                msgs = agent.prompt("And refunded?", chat)
                assert len(msgs) == 2 + 4                                           # the whole chat kept
                assert agent._specs_chars("And refunded?") < len(json.dumps(agent.specs, default=str))
            finally:
                settings.set_value("search.enabled", None)
                agent.close()
    finally:
        _drop_pages()


def test_the_prompt_gives_what_the_team_keeps_once(ctx, monkeypatch):
    """Through the prompt itself: a memory that says a rule of the team is not given again, two copies of a memory
    are given once, two memories alike but not the same are both given; off, as 0.10.12 (all of them)."""
    import types

    from superset import security_manager
    from superset.extensions import db

    from supagent import settings
    from supagent.agent import Agent
    from supagent.knowledge.memory import add
    from supagent.models import Memory
    from supagent.security import acting_as

    rule = {"id": 990001, "title": "Refunds", "category": "", "text": "Always count the refunds apart."}
    monkeypatch.setattr("supagent.knowledge.catalog.rules", lambda: [rule])
    monkeypatch.setattr("supagent.security.visible_databases", lambda: {1, 2})
    user = security_manager.find_user("admin") or db.session.query(security_manager.user_model).first()
    made = [add(user.id, "Count the refunds apart", kind="rule"),
            add(user.id, "Give durations in minutes", kind="preference"),
            add(user.id, "Always give durations in minutes, please.", kind="preference"),
            add(user.id, "Give durations in minutes for the jobs", kind="preference")]
    ids = [m.id for m in made]
    try:
        with acting_as("admin"):
            agent = Agent("admin", rich_results=True, llm=types.SimpleNamespace())
            try:
                text = " ".join(m["content"] for m in agent.prompt("What was the net revenue last week?"))
                assert text.count("refunds apart") == 2                     # the rule and its reminder, no memory
                assert text.count("durations in minutes") == 2              # the copy once, the jobs' one kept
                assert "durations in minutes for the jobs" in text
                settings.set_value("agent.context_tiers", False)            # off: every memory, as 0.10.12
                text = " ".join(m["content"] for m in agent.prompt("What was the net revenue last week?"))
                assert text.count("refunds apart") == 3 and text.count("durations in minutes") == 3
            finally:
                settings.set_value("agent.context_tiers", None)
                agent.close()
    finally:
        db.session.query(Memory).filter(Memory.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
