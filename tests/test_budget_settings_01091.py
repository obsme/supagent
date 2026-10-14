"""(0.10.9.1) What the agent gives the LLM is settable for each context profile (the small model's, 32k-64k tokens per
request; the big model's, 128k or more): budget.short.<size>, budget.long.<size>, empty for the profile's own. A size
set for the profile in use wins over agent.compact_at / search.prompt_chars (one value for both profiles, as in
0.10.9), which win over the profile's own; a big-model size a person typed is used as typed; when the big profile
applies, the share of its window its older results are cut from and the window assumed are settings too. The
Settings page shows the sizes in use and warns when they may not fit the model's window."""
from __future__ import annotations

import pytest

from conftest import login


@pytest.fixture()
def clean(ctx, monkeypatch):
    from supagent import budget, settings

    touched: list[str] = []

    def put(key, value):
        touched.append(key)
        settings.set_value(key, value)

    yield put
    for key in set(touched):
        settings.set_value(key, None)


def test_every_size_is_a_setting_of_each_profile(ctx):
    from supagent import budget, settings

    for prof in ("short", "long"):
        for name in budget.NAMES:
            spec = settings.BY_KEY[f"budget.{prof}.{name}"]
            assert spec.kind == "int" and spec.default is None and spec.help
    for key in ("budget.long_from_tokens", "budget.long_cut_share", "budget.long_assumed_tokens"):
        assert key in settings.BY_KEY
    assert "budget.short.memory_chars" not in settings.BY_KEY          # it limits nothing since 0.10.9
    assert settings.BY_KEY["budget.long_from_tokens"].default == 100_000


def test_a_profile_s_setting_wins_over_the_one_for_both_which_wins_over_its_own(clean, monkeypatch):
    from supagent import budget

    monkeypatch.setattr(budget, "window", lambda: 65536)               # a small model: the short profile
    assert budget.size("search_chars") == 2500
    clean("search.prompt_chars", 4000)                                 # the 0.10.9 way: both profiles
    assert budget.size("search_chars") == 4000
    assert budget.size_for("search_chars", "long") == 4000
    clean("budget.short.search_chars", 3000)                           # the small model's own setting wins
    assert budget.size("search_chars") == 3000
    assert budget.size_for("search_chars", "long") == 4000             # the big model's untouched
    clean("budget.long.search_chars", 20000)
    assert budget.size_for("search_chars", "long") == 20000
    assert budget.size("search_chars") == 3000


def test_a_big_model_size_typed_is_not_scaled_only_its_own_is(clean, monkeypatch):
    from supagent import budget

    monkeypatch.setattr(budget, "window", lambda: 262144)              # 256k: the long sizes one and a half
    assert budget.profile() == "long"
    assert budget.size("tool_chars") == 48000 and budget.size("history_chars") == 18000
    clean("budget.long.tool_chars", 40000)
    assert budget.size("tool_chars") == 40000                          # as typed
    assert budget.size("history_chars") == 18000


def test_empty_is_the_profile_s_own_and_zero_is_a_size(clean, monkeypatch):
    from supagent import budget

    monkeypatch.setattr(budget, "window", lambda: 131072)
    clean("budget.long.search_chars", 12000)
    clean("budget.long.search_chars", None)                            # emptied: the profile's own again
    assert budget.size("search_chars") == 10000
    clean("budget.long.compact_at", 0)                                 # 0: older results cut only when full
    assert budget.size("compact_at") == 0
    clean("agent.compact_at", 0)
    assert budget.size_for("compact_at", "short") == 0                 # the setting for both, as in 0.10.9


def test_when_the_big_profile_applies_and_its_cut_are_settings(clean, monkeypatch):
    from supagent import budget

    monkeypatch.setattr(budget, "window", lambda: 65536)
    assert budget.profile() == "short"
    clean("budget.long_from_tokens", 60000)                            # a 64k server now counts as big
    assert budget.profile() == "long"
    assert budget.size("compact_at") == int(0.6 * 65536)
    clean("budget.long_cut_share", 0.5)
    assert budget.size("compact_at") == int(0.5 * 65536)
    clean("budget.long_from_tokens", None)
    monkeypatch.setattr(budget, "window", lambda: None)                # no window stated: a forced big profile
    clean("agent.context_profile", "long")
    assert budget.size("search_chars") == 10000                        # made for 131,072 tokens
    clean("budget.long_assumed_tokens", 262144)
    assert budget.size("search_chars") == 15000


def test_the_report_shows_both_profiles_what_is_set_and_warns_when_it_may_not_fit(clean, monkeypatch):
    from supagent import budget

    monkeypatch.setattr(budget, "window", lambda: 65536)
    rep = budget.report()
    assert rep["profile"] == "short" and rep["window"] == 65536
    assert set(rep["sizes"]) == {"short", "long"} and set(rep["sizes"]["short"]) == set(budget.NAMES)
    assert rep["sizes"]["short"]["search_chars"] == 2500 and rep["sizes"]["long"]["search_chars"] == 5000
    assert rep["estimate"]["start_tokens"] > rep["estimate"]["instructions_tokens"] > 0
    assert rep["estimate"]["warnings"] == []                            # 0.10.9's sizes fit a 64k model
    clean("agent.compact_at", 30000)
    rep = budget.report()
    assert rep["set"]["short"]["compact_at"] == "agent.compact_at" and rep["sizes"]["long"]["compact_at"] == 30000
    clean("budget.short.compact_at", 70000)                             # cut after the window is full
    rep = budget.report()
    assert rep["set"]["short"]["compact_at"] == "budget.short.compact_at"
    assert any("after the model's 65,536 are full" in w for w in rep["estimate"]["warnings"])
    assert "WARNING" in budget.described()
    clean("budget.short.tool_chars", 80000)                              # one result: a third of the window
    assert any("one tool result" in w for w in budget.report()["estimate"]["warnings"])
    lines = budget.table()
    assert lines[0].startswith("small model (short, in use)") and "compact_at 70,000*" in lines[0]
    assert lines[1].startswith("big model (long)")


def test_the_settings_page_gets_the_sizes_and_an_empty_box_stays_unset(app, ctx, clean, monkeypatch):
    from supagent import budget, settings

    monkeypatch.setattr(budget, "window", lambda: 65536)
    client = app.test_client()
    login(client, "admin")
    got = client.get("/supagent/admin/api/settings").get_json()
    assert got["budget"]["profile"] == "short" and got["budget"]["sizes"]["short"]["history_chars"] == 3000
    keys = {s["key"] for s in got["settings"]}
    assert "budget.long.llm_context_chars" in keys
    clean("budget.short.history_chars", None)
    r = client.post("/supagent/admin/api/settings", json={"settings": {"budget.short.history_chars": ""}}).get_json()
    assert settings.explicit("budget.short.history_chars") is None     # an empty box: the profile's own
    r = client.post("/supagent/admin/api/settings", json={"settings": {"budget.short.history_chars": "2000"}}).get_json()
    assert r["budget"]["sizes"]["short"]["history_chars"] == 2000
    assert budget.size("history_chars") == 2000
