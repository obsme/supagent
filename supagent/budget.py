"""(0.10.9.1) How much of the model's context the agent fills: the SHORT profile (a model of 32k to 64k tokens per
request: the sizes of 0.10.8, unchanged) or the LONG one (a window of 100k tokens or more: 128k, 256k), its sizes
grown with the window. agent.context_profile: auto (by the window the LLM's server states per request, kept in the
LLM's profile, or agent.context_tokens), short or long. A size a person set (agent.compact_at, search.prompt_chars,
memory.prompt_chars) wins over the profile's.

    size("compact_at")      prompt tokens from which the older tool results of an answer are cut
    size("search_chars")    characters of knowledge given with a question
    size("piece_chars")     of each piece of that knowledge
    size("context_chars")   of each Context section (the learned Context: its part about the question when short,
                            the whole section when long)
    size("memory_chars")    characters of memories a question is given before the other knowledge gives way (every
                            memory is given whole, whatever its length)
    size("llm_context_chars") of the LLM context the learning writes, given with every question (its light version
                            when short, its full version when long)
    size("tool_chars")      of a tool's result (describe_data, compare_groups: their own)
    size("history_chars")   of each earlier message of the chat
    size("rules_near_chars"), size("rule_chars"), size("group_chars"), size("shrunk_first"), size("shrunk_second")
"""
from __future__ import annotations

import time
from typing import Any

LONG_AT = 100_000          # tokens per request from which the long profile applies (auto)
ASSUMED_LONG = 131_072     # the window of a forced long profile when the server states none
COMPACT_SHARE = 0.6        # of the window, from which the older results are cut (long): models read a very long
#                            prompt worse well before their limit
SHORT: dict[str, int] = {"compact_at": 24000, "search_chars": 2500, "piece_chars": 450, "context_chars": 450,
                         "llm_context_chars": 6000,
                         "memory_chars": 2000, "tool_chars": 8000, "describe_chars": 16000,
                         "compare_chars": 12000, "history_chars": 3000, "rules_near_chars": 1500,
                         "rule_chars": 1500, "group_chars": 6500, "shrunk_first": 1500, "shrunk_second": 500}
# the long profile's sizes for a window of 128k tokens, grown or shrunk with the window (half of them at 64k, one and a
# half at 256k and more: a model finds a fact in a very long prompt worse than in a short one, so what is given grows
# less than the window); never below the short profile's
LONG_WINDOW = 131_072
LONG: dict[str, int] = {"search_chars": 10000, "piece_chars": 1800, "context_chars": 4800, "memory_chars": 8000,
                        "llm_context_chars": 120000,
                        "tool_chars": 32000, "describe_chars": 48000, "compare_chars": 36000,
                        "history_chars": 12000, "rules_near_chars": 6000, "rule_chars": 6000, "group_chars": 19500,
                        "shrunk_first": 6000, "shrunk_second": 2000}
SCALE = (0.5, 1.5)         # the least and the most the long sizes are scaled by the window
SETTING = {"compact_at": "agent.compact_at", "search_chars": "search.prompt_chars",
           "memory_chars": "memory.prompt_chars"}
READ_S = 30.0              # the LLM's stored profile read again at most this often
_SEEN: dict[str, Any] = {"at": 0.0, "window": None}


def window() -> int | None:
    """Tokens of the model's context per request: agent.context_tokens when a person set it, else what the LLM's
    server states (its profile: vLLM's max_model_len, llama.cpp's context per slot), else None."""
    from supagent import settings

    try:
        mine = int(settings.get("agent.context_tokens") or 0)
    except Exception:  # pylint: disable=broad-except   (no settings table yet)
        mine = 0
    if mine > 0:
        return mine
    now = time.time()
    if now - _SEEN["at"] > READ_S:
        from supagent.llm import stored_profile

        prof = stored_profile() or {}
        try:
            _SEEN["window"] = int(prof.get("context") or 0) or None
        except (TypeError, ValueError):
            _SEEN["window"] = None
        _SEEN["at"] = now
    return _SEEN["window"]


def profile() -> str:
    """short or long."""
    from supagent import settings

    try:
        choice = str(settings.get("agent.context_profile") or "auto").strip().lower()
    except Exception:  # pylint: disable=broad-except
        choice = "auto"
    if choice in ("short", "long"):
        return choice
    w = window()
    return "long" if w and w >= LONG_AT else "short"


def size(name: str) -> int:
    """A size of what the agent gives the LLM, for this model's profile (see the module's doc)."""
    key = SETTING.get(name)
    if key:
        from supagent import settings

        try:
            mine = settings.explicit(key)
        except Exception:  # pylint: disable=broad-except
            mine = None
        if mine is not None:
            return int(mine)
    if profile() == "short":
        return SHORT[name]
    w = window() or ASSUMED_LONG
    if name == "compact_at":
        return max(SHORT[name], int(COMPACT_SHARE * w))
    scale = min(max(w / LONG_WINDOW, SCALE[0]), SCALE[1])
    return max(SHORT[name], int(LONG[name] * scale))


def described() -> str:
    """For the Settings page and test-llm: the profile in use and why."""
    w = window()
    p = profile()
    return (f"{p} ({'the model reads ' + format(w, ',') + ' tokens per request' if w else 'the context is not stated'}"
            f"; older results cut from {size('compact_at'):,} prompt tokens, {size('search_chars'):,} characters "
            f"of knowledge, Context sections up to {size('context_chars'):,} characters)")
