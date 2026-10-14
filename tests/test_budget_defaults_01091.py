"""(0.10.9.1) The sizes of what the agent gives the LLM, by context profile, with nothing set by a person: exactly
the sizes 0.10.9 was measured with (computed by 0.10.9's own code, C' 4073711), at the usual windows of a model (32k,
64k, 128k, 256k tokens per request, or not stated) and for each choice of agent.context_profile (auto, short, long).
Settable sizes must not move a default."""
from __future__ import annotations

import pytest

# "<agent.context_profile>@<tokens per request the server states>": (the profile used, every size)
SIZES_0109 = {
    'auto@131072': ('long', {'compact_at': 78643, 'compare_chars': 36000, 'context_chars': 4800, 'describe_chars': 48000, 'group_chars': 19500, 'history_chars': 12000, 'llm_context_chars': 120000, 'memory_chars': 8000, 'piece_chars': 1800, 'rule_chars': 6000, 'rules_near_chars': 6000, 'search_chars': 10000, 'shrunk_first': 6000, 'shrunk_second': 2000, 'tool_chars': 32000}),
    'auto@262144': ('long', {'compact_at': 157286, 'compare_chars': 54000, 'context_chars': 7200, 'describe_chars': 72000, 'group_chars': 29250, 'history_chars': 18000, 'llm_context_chars': 180000, 'memory_chars': 12000, 'piece_chars': 2700, 'rule_chars': 9000, 'rules_near_chars': 9000, 'search_chars': 15000, 'shrunk_first': 9000, 'shrunk_second': 3000, 'tool_chars': 48000}),
    'auto@32768': ('short', {'compact_at': 24000, 'compare_chars': 12000, 'context_chars': 450, 'describe_chars': 16000, 'group_chars': 6500, 'history_chars': 3000, 'llm_context_chars': 6000, 'memory_chars': 2000, 'piece_chars': 450, 'rule_chars': 1500, 'rules_near_chars': 1500, 'search_chars': 2500, 'shrunk_first': 1500, 'shrunk_second': 500, 'tool_chars': 8000}),
    'auto@65536': ('short', {'compact_at': 24000, 'compare_chars': 12000, 'context_chars': 450, 'describe_chars': 16000, 'group_chars': 6500, 'history_chars': 3000, 'llm_context_chars': 6000, 'memory_chars': 2000, 'piece_chars': 450, 'rule_chars': 1500, 'rules_near_chars': 1500, 'search_chars': 2500, 'shrunk_first': 1500, 'shrunk_second': 500, 'tool_chars': 8000}),
    'auto@None': ('short', {'compact_at': 24000, 'compare_chars': 12000, 'context_chars': 450, 'describe_chars': 16000, 'group_chars': 6500, 'history_chars': 3000, 'llm_context_chars': 6000, 'memory_chars': 2000, 'piece_chars': 450, 'rule_chars': 1500, 'rules_near_chars': 1500, 'search_chars': 2500, 'shrunk_first': 1500, 'shrunk_second': 500, 'tool_chars': 8000}),
    'short@131072': ('short', {'compact_at': 24000, 'compare_chars': 12000, 'context_chars': 450, 'describe_chars': 16000, 'group_chars': 6500, 'history_chars': 3000, 'llm_context_chars': 6000, 'memory_chars': 2000, 'piece_chars': 450, 'rule_chars': 1500, 'rules_near_chars': 1500, 'search_chars': 2500, 'shrunk_first': 1500, 'shrunk_second': 500, 'tool_chars': 8000}),
    'short@262144': ('short', {'compact_at': 24000, 'compare_chars': 12000, 'context_chars': 450, 'describe_chars': 16000, 'group_chars': 6500, 'history_chars': 3000, 'llm_context_chars': 6000, 'memory_chars': 2000, 'piece_chars': 450, 'rule_chars': 1500, 'rules_near_chars': 1500, 'search_chars': 2500, 'shrunk_first': 1500, 'shrunk_second': 500, 'tool_chars': 8000}),
    'short@32768': ('short', {'compact_at': 24000, 'compare_chars': 12000, 'context_chars': 450, 'describe_chars': 16000, 'group_chars': 6500, 'history_chars': 3000, 'llm_context_chars': 6000, 'memory_chars': 2000, 'piece_chars': 450, 'rule_chars': 1500, 'rules_near_chars': 1500, 'search_chars': 2500, 'shrunk_first': 1500, 'shrunk_second': 500, 'tool_chars': 8000}),
    'short@65536': ('short', {'compact_at': 24000, 'compare_chars': 12000, 'context_chars': 450, 'describe_chars': 16000, 'group_chars': 6500, 'history_chars': 3000, 'llm_context_chars': 6000, 'memory_chars': 2000, 'piece_chars': 450, 'rule_chars': 1500, 'rules_near_chars': 1500, 'search_chars': 2500, 'shrunk_first': 1500, 'shrunk_second': 500, 'tool_chars': 8000}),
    'short@None': ('short', {'compact_at': 24000, 'compare_chars': 12000, 'context_chars': 450, 'describe_chars': 16000, 'group_chars': 6500, 'history_chars': 3000, 'llm_context_chars': 6000, 'memory_chars': 2000, 'piece_chars': 450, 'rule_chars': 1500, 'rules_near_chars': 1500, 'search_chars': 2500, 'shrunk_first': 1500, 'shrunk_second': 500, 'tool_chars': 8000}),
    'long@131072': ('long', {'compact_at': 78643, 'compare_chars': 36000, 'context_chars': 4800, 'describe_chars': 48000, 'group_chars': 19500, 'history_chars': 12000, 'llm_context_chars': 120000, 'memory_chars': 8000, 'piece_chars': 1800, 'rule_chars': 6000, 'rules_near_chars': 6000, 'search_chars': 10000, 'shrunk_first': 6000, 'shrunk_second': 2000, 'tool_chars': 32000}),
    'long@262144': ('long', {'compact_at': 157286, 'compare_chars': 54000, 'context_chars': 7200, 'describe_chars': 72000, 'group_chars': 29250, 'history_chars': 18000, 'llm_context_chars': 180000, 'memory_chars': 12000, 'piece_chars': 2700, 'rule_chars': 9000, 'rules_near_chars': 9000, 'search_chars': 15000, 'shrunk_first': 9000, 'shrunk_second': 3000, 'tool_chars': 48000}),
    'long@32768': ('long', {'compact_at': 24000, 'compare_chars': 18000, 'context_chars': 2400, 'describe_chars': 24000, 'group_chars': 9750, 'history_chars': 6000, 'llm_context_chars': 60000, 'memory_chars': 4000, 'piece_chars': 900, 'rule_chars': 3000, 'rules_near_chars': 3000, 'search_chars': 5000, 'shrunk_first': 3000, 'shrunk_second': 1000, 'tool_chars': 16000}),
    'long@65536': ('long', {'compact_at': 39321, 'compare_chars': 18000, 'context_chars': 2400, 'describe_chars': 24000, 'group_chars': 9750, 'history_chars': 6000, 'llm_context_chars': 60000, 'memory_chars': 4000, 'piece_chars': 900, 'rule_chars': 3000, 'rules_near_chars': 3000, 'search_chars': 5000, 'shrunk_first': 3000, 'shrunk_second': 1000, 'tool_chars': 16000}),
    'long@None': ('long', {'compact_at': 78643, 'compare_chars': 36000, 'context_chars': 4800, 'describe_chars': 48000, 'group_chars': 19500, 'history_chars': 12000, 'llm_context_chars': 120000, 'memory_chars': 8000, 'piece_chars': 1800, 'rule_chars': 6000, 'rules_near_chars': 6000, 'search_chars': 10000, 'shrunk_first': 6000, 'shrunk_second': 2000, 'tool_chars': 32000}),
}


@pytest.mark.parametrize("case", sorted(SIZES_0109))
def test_the_defaults_are_the_sizes_0109_was_measured_with(ctx, monkeypatch, case):
    from supagent import budget, settings

    choice, w = case.split("@")
    monkeypatch.setattr(budget, "window", lambda: None if w == "None" else int(w))
    settings.set_value("agent.context_profile", None if choice == "auto" else choice)
    try:
        used, sizes = SIZES_0109[case]
        assert budget.profile() == used
        assert {n: budget.size(n) for n in sizes} == sizes
    finally:
        settings.set_value("agent.context_profile", None)
