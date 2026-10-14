"""(0.10.9.1) The context profiles (short: the sizes of 0.10.8 for a model of 32k-64k tokens; long: grown with a window
of 128k or more), memories given whole and first and never left out, a request to remember kept as written, and the
LLM context the learning writes in a full and a light version, given only for the user's databases."""
from __future__ import annotations

import pytest


def test_the_short_profile_is_the_sizes_of_before(ctx, monkeypatch):
    from supagent import agent, budget, settings, tools

    monkeypatch.setattr(budget, "window", lambda: 65536)              # the lab's servers: 65,536 tokens per request
    assert budget.profile() == "short"
    assert agent.MAX_TOOL_CHARS == budget.size("tool_chars") == 8000
    assert agent.TOOL_CHARS == {"describe_data": budget.size("describe_chars"),
                                "compare_groups": budget.size("compare_chars")} == {"describe_data": 16000,
                                                                                    "compare_groups": 12000}
    assert agent.HISTORY_CHARS == budget.size("history_chars") == 3000
    assert agent.RULES_NEAR_CHARS == budget.size("rules_near_chars") == 1500
    assert agent.RULE_CHARS == budget.size("rule_chars") == 1500
    assert agent.SHRUNK == agent.shrunk() == (1500, 500)
    assert tools.GROUP_CHARS == budget.size("group_chars") == 6500
    assert settings.BY_KEY["agent.compact_at"].default == budget.size("compact_at") == 24000
    assert settings.BY_KEY["search.prompt_chars"].default == budget.size("search_chars") == 2500
    assert settings.BY_KEY["memory.prompt_chars"].default == budget.size("memory_chars") == 2000
    assert budget.size("piece_chars") == budget.size("context_chars") == 450


def test_the_long_profile_grows_with_the_window_and_a_person_s_setting_wins(ctx, monkeypatch):
    from supagent import budget, settings

    monkeypatch.setattr(budget, "window", lambda: 131072)
    assert budget.profile() == "long"
    assert budget.size("compact_at") == int(0.6 * 131072)
    assert budget.size("search_chars") == 10000 and budget.size("context_chars") == 4800
    assert budget.size("tool_chars") == 32000
    monkeypatch.setattr(budget, "window", lambda: 262144)              # 256k: one and a half of the 128k sizes
    assert budget.size("search_chars") == 15000 and budget.size("compact_at") == int(0.6 * 262144)
    settings.set_value("agent.compact_at", 50000)
    try:
        assert budget.size("compact_at") == 50000                    # set by a person: theirs, in any profile
        settings.set_value("agent.context_profile", "short")
        assert budget.profile() == "short" and budget.size("search_chars") == 2500
    finally:
        settings.set_value("agent.compact_at", None)
        settings.set_value("agent.context_profile", None)
    monkeypatch.setattr(budget, "window", lambda: 65536)
    settings.set_value("agent.context_profile", "long")              # forced long on a 64k server: half the sizes
    try:
        assert budget.size("search_chars") == 5000 and budget.size("compact_at") == int(0.6 * 65536)
    finally:
        settings.set_value("agent.context_profile", None)


@pytest.mark.parametrize("message,kept", [
    ("Remember that the amounts are in kEUR", "the amounts are in kEUR"),
    ("Retiens que les montants sont en kEUR.", "les montants sont en kEUR."),
    ("Keep in mind: the night batch ends at 06:00\nand restarts at 07:00", "the night batch ends at 06:00\nand restarts at 07:00"),
    ("remember what we found yesterday?", None),
    ("Remember that the amounts are in kEUR and show me yesterday's total", None),
    ("Remember that X is the main book. What was its total yesterday", None),
    ("What do you remember about the batch?", None),
])
def test_a_request_to_remember_is_kept_as_written(message, kept):
    from supagent.knowledge.memory import remember_request

    assert remember_request(message) == kept


def test_memories_are_given_whole_first_and_never_left_out(ctx):
    from superset.extensions import db
    from superset import security_manager

    from supagent.knowledge.memory import add, prompt_block, remember_now
    from supagent.models import Memory

    user = security_manager.find_user("admin") or db.session.query(security_manager.user_model).first()
    long_one = "The weekly report is built from three sources:\n- the orders\n- the refunds\n" + "x " * 1500
    made = [add(user.id, f"code{i}x{i * 7} stands for region{i * 3}", kind="fact") for i in range(20)]
    made.append(add(user.id, long_one, kind="rule"))
    kept = remember_now(user.id, "Remember that the amounts of the report are in kEUR")
    try:
        assert kept is not None and kept.text == "the amounts of the report are in kEUR" and kept.status == "active"
        block = prompt_block(user.id)
        assert all(f"code{i}x{i * 7} stands for region{i * 3}" in block for i in range(20))   # none left out
        assert "three sources:\n  - the orders\n  - the refunds" in block              # whole, its lines kept
        assert ("x " * 1500).strip() in block
        assert "the amounts of the report are in kEUR" in block                      # at once
    finally:
        for m in made + [kept]:
            if m is not None:
                db.session.delete(db.session.get(Memory, m.id))
        db.session.commit()


def _evidence():
    return {"databases": {1: {"name": "shop", "backend": "postgresql", "main": [
                {"kind": "index", "name": "orders", "about": "One row per order. Its status says paid or refunded."}],
                "others": 0, "fields": [{"kind": "index", "name": "orders", "child": "field", "total": 2, "shown": [
                    {"name": "status", "type": "keyword", "about": "paid or refunded", "values": ["paid", "refunded"]},
                    {"name": "amount", "type": "double", "about": "in EUR", "values": []}]}]},
                          2: {"name": "payroll", "backend": "postgresql", "main": [
                {"kind": "index", "name": "salaries", "about": "One row per salary paid."}], "others": 0,
                "fields": []}},
            "entries": [{"id": 1, "title": "Refunds", "classification": "rule", "content": "Count refunds apart.",
                         "database_id": None},
                        {"id": 2, "title": "Net revenue", "classification": "formula",
                         "content": "SUM(amount) of the paid orders minus the refunds", "database_id": 1},
                        {"id": 3, "title": "Payslip", "classification": "glossary", "content": "A salary's record.",
                         "database_id": 2}],
            "relations": [{"a": "orders.customer", "a_db": 1, "b": "salaries.employee", "b_db": 2, "origin": "x"}],
            "answers": [{"id": 1, "question": "How many orders were refunded yesterday?", "tool": "execute_sql",
                         "database_id": 1},
                        {"id": 2, "question": "What was the payroll of March?", "tool": "execute_sql",
                         "database_id": 2}]}


def test_the_llm_context_has_a_full_and_a_light_version_and_each_user_gets_their_databases():
    from supagent.knowledge.llm_context import filtered, pages

    full, light = pages(_evidence())
    assert full["slug"] == "llm-context" and light["slug"] == "llm-context-light"
    assert "`status` (keyword): paid or refunded [paid, refunded]" in full["content"]      # the fields: full only
    assert "`status`" not in light["content"]
    for page in (full, light):
        assert "Count refunds apart." in page["content"] and "Net revenue" in page["content"]
        mine = filtered(page["content"], {1})
        assert "orders" in mine and "How many orders were refunded" in mine and "Net revenue" in mine
        assert "salaries" not in mine and "payroll" not in mine and "Payslip" not in mine   # not their database
        assert "<!--" not in mine
        both = filtered(page["content"], {1, 2})
        assert "salaries" in both and "orders.customer" in both


def test_the_llm_context_is_given_by_the_profile_and_not_searched(ctx, monkeypatch):
    from superset.extensions import db

    from supagent import budget
    from supagent.knowledge import llm_context as L
    from supagent.knowledge.context import _hash, save_page
    from supagent.models import ContextPage

    for page in L.pages(_evidence()):
        save_page(page, "facts", _hash([page["content"]]))
    db.session.commit()
    monkeypatch.setattr("supagent.security.visible_databases", lambda: {1, 2})
    from supagent import settings

    try:
        monkeypatch.setattr(budget, "window", lambda: 65536)
        assert L.for_prompt() == ""                              # a 64k model: not given unless a person sets it on
        settings.set_value("agent.llm_context", True)
        light = L.for_prompt()
        settings.set_value("agent.llm_context", None)
        assert "LLM context (light)" in light and "`status`" not in light
        assert "Count refunds apart." not in light               # the rules: given apart with the instructions
        monkeypatch.setattr(budget, "window", lambda: 131072)
        assert "LLM context (full)" in L.for_prompt()
        from supagent.knowledge.index import _context_pieces

        assert not [x for x in _context_pieces() if "LLM context" in x["title"]]
    finally:
        db.session.query(ContextPage).filter(ContextPage.slug.in_(L.LLM_SLUGS if hasattr(L, "LLM_SLUGS") else
                                                                    (L.SLUG_FULL, L.SLUG_LIGHT))).delete()
        db.session.commit()


def test_a_profile_made_before_the_window_was_read_is_made_again(ctx, monkeypatch):
    import datetime

    from supagent import llm as L
    from supagent import settings

    settings.set_value("llm.base_url", "http://127.0.0.1:9/v1")
    settings.set_value("llm.model", "a-model")
    probed = []
    monkeypatch.setattr(L.LLM, "probe", lambda self, save=True: probed.append(1) or {"context": 131072})
    client = L.LLM()
    old = {"source": "probe", "base": client.base, "model": client.model,
           "at": datetime.datetime.utcnow().isoformat()}                     # 0.10.8's: fresh, but no window
    monkeypatch.setattr(L, "stored_profile", lambda: dict(old))
    assert L.ensure_profile() == {"context": 131072} and probed == [1]
    monkeypatch.setattr(L, "stored_profile", lambda: dict(old, context=65536))
    try:
        assert L.ensure_profile()["context"] == 65536 and probed == [1]       # with its window: kept
    finally:
        settings.set_value("llm.base_url", None)
        settings.set_value("llm.model", None)
