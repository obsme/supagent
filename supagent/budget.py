"""(0.10.9.1) How much of the model's context the agent fills, in two profiles: the SMALL model's ("short": a model
of 32k to 64k tokens per request, the sizes 0.10.8 and 0.10.9 were measured with) and the BIG model's ("long": a
window of 100k tokens or more, 128k or 256k, its sizes grown with the window). agent.context_profile: auto (by the
window the LLM's server states per request, kept in the LLM's profile, or agent.context_tokens), short or long.

Every size is a setting of each profile, budget.short.<size> and budget.long.<size>, empty for the profile's own:
    a size a person set for the profile in use wins;
    else one set the 0.10.9 way, for both profiles (agent.compact_at, search.prompt_chars);
    else the profile's own: the small model's as below, the big model's grown with the window (a size a person typed
    is used as typed, never scaled).
The window from which the big profile applies (budget.long_from_tokens), the share of the window from which its
older results are cut (budget.long_cut_share) and the window of a big profile forced on a server that states none
(budget.long_assumed_tokens) are settings too.

    size("compact_at")      prompt tokens from which the older tool results of an answer are cut (0: only when full)
    size("search_chars")    characters of knowledge given with a question
    size("piece_chars")     of each piece of that knowledge
    size("context_chars")   of each Context section (the learned Context: its part about the question when short,
                            the whole section when long)
    size("memory_chars")    characters of memories counted as theirs (no longer a limit: every memory is given
                            whole, first, on top of the knowledge found for the question; not a setting)
    size("llm_context_chars") of the LLM context the learning writes, given with every question (its light version
                            when short, its full version when long)
    size("tool_chars")      of a tool's result (describe_data, compare_groups: their own)
    size("history_chars")   of each earlier message of the chat
    size("rules_near_chars"), size("rule_chars"), size("group_chars"), size("shrunk_first"), size("shrunk_second")
"""
from __future__ import annotations

import json
import time
from typing import Any

LONG_AT = 100_000          # tokens per request from which the long profile applies (auto): budget.long_from_tokens
ASSUMED_LONG = 131_072     # the window of a forced long profile when the server states none: budget.long_assumed_tokens
COMPACT_SHARE = 0.6        # of the window, from which the older results are cut (long): models read a very long
#                            prompt worse well before their limit; budget.long_cut_share
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
           "memory_chars": "memory.prompt_chars"}            # the 0.10.9 settings: one value for both profiles
PROFILES = ("short", "long")
# what each size settable per profile controls (the Settings page; memory_chars limits nothing since 0.10.9: not one)
ABOUT: dict[str, str] = {
    "compact_at": "Prompt tokens of an answer from which the older tool results are cut to their first lines (then "
                  "again at half as much more), the work plan given again: models read a long context worse well "
                  "before its end. 0: only when the context is full",
    "search_chars": "Characters of knowledge found for the question (data dictionary, catalog, team's answers, "
                    "documents, System map) given with it",
    "piece_chars": "Characters of each piece of that knowledge",
    "context_chars": "Characters of each section of the learned Context given with the question (the small model: "
                     "its part about the question; the big one: the section, up to this size)",
    "llm_context_chars": "Characters of the LLM context the learning writes, given with every question (the big "
                         "model: its full version; the small one: its light version, only when agent.llm_context "
                         "is set on)",
    "tool_chars": "Characters of a tool's result (a query's rows, a search's findings)",
    "describe_chars": "Characters of a description of the data (describe_data)",
    "compare_chars": "Characters of a comparison of groups (compare_groups)",
    "history_chars": "Characters of each earlier message of the chat",
    "rules_near_chars": "Characters of the team's rules given in full with the question (when they take more, the "
                        "agent is told to apply the rules of its instructions)",
    "rule_chars": "Characters of one of the team's rules",
    "group_chars": "Characters of a comparison of logs between groups",
    "shrunk_first": "Characters an older tool result keeps at the first cut",
    "shrunk_second": "Characters an older tool result keeps at the second cut",
}
NAMES: tuple[str, ...] = tuple(ABOUT)
UNIT = {"compact_at": "prompt tokens"}            # the others: characters
CHARS_PER_TOKEN = 4        # the estimate of the Settings page and test-llm: about four characters a token
START_SHARE = 0.5          # warned when the start of an answer may take more of the window than this
RESULT_SHARE = 0.25        # warned when one tool result may take more of the window than this
READ_S = 30.0              # the LLM's stored profile read again at most this often
_SEEN: dict[str, Any] = {"at": 0.0, "window": None}


def _get(key: str, default: Any) -> Any:
    from supagent import settings

    try:
        v = settings.get(key)
    except Exception:  # pylint: disable=broad-except   (no settings table yet, or outside an app)
        return default
    return default if v in (None, "") else v


def _mine(key: str) -> int | None:
    """The value a person set for a setting of a size, else None."""
    from supagent import settings

    try:
        v = settings.explicit(key)
    except Exception:  # pylint: disable=broad-except
        return None
    if v in (None, ""):
        return None
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return None


def long_from() -> int:
    """Tokens per request from which the big model's profile applies (auto)."""
    return int(_get("budget.long_from_tokens", LONG_AT))


def long_assumed() -> int:
    """The window of a big model's profile forced on a server that states none."""
    return int(_get("budget.long_assumed_tokens", ASSUMED_LONG))


def long_cut_share() -> float:
    """The share of the window from which the big model's older results are cut, unless its compact_at is set."""
    v = float(_get("budget.long_cut_share", COMPACT_SHARE))
    return min(max(v, 0.05), 1.0)


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
    if choice in PROFILES:
        return choice
    w = window()
    return "long" if w and w >= long_from() else "short"


def default_size(name: str, prof: str, w: int | None = None) -> int:
    """A profile's own size (nothing set by a person): the small model's, or the big model's for the window `w`
    (None: the model's, else the window assumed)."""
    if prof == "short":
        return SHORT[name]
    w = w or window() or long_assumed()
    if name == "compact_at":
        return max(SHORT[name], int(long_cut_share() * w))
    scale = min(max(w / LONG_WINDOW, SCALE[0]), SCALE[1])
    return max(SHORT[name], int(LONG[name] * scale))


def size_for(name: str, prof: str, w: int | None = None) -> int:
    """The size `name` of the profile `prof`: the profile's setting, else the 0.10.9 setting of both, else its own."""
    if name in ABOUT:
        mine = _mine(f"budget.{prof}.{name}")
        if mine is not None:
            return mine
    key = SETTING.get(name)
    if key:
        mine = _mine(key)
        if mine is not None:
            return mine
    return default_size(name, prof, w)


def size(name: str) -> int:
    """A size of what the agent gives the LLM, for this model's profile (see the module's doc)."""
    return size_for(name, profile())


def _fixed_chars() -> int:
    """Characters of what every answer starts with whatever the sizes: the instructions and the tools' descriptions
    (the longest kind of question's instructions; the tools this server offers)."""
    try:
        from supagent import agent, tools

        text = agent.CORE + agent.RICH + agent.OSAGG_RULES + agent.PROMAGG_RULES
        text += max(agent.SECTIONS.values(), key=len) if agent.SECTIONS else ""
        specs = [t.spec() for t in tools.mcp.tools.values()]
        return len(text) + len(json.dumps(specs, default=str))
    except Exception:  # pylint: disable=broad-except
        return 0


def estimate(prof: str, w: int | None) -> dict[str, Any]:
    """(an estimate, about four characters a token) What an answer of the profile starts with and the largest tool
    result, in tokens, against the window `w`; the warnings when they may not fit."""
    from supagent import settings

    s = {n: size_for(n, prof, w) for n in NAMES}
    try:
        llm_ctx = bool(settings.get("agent.llm_context")) and (
            prof == "long" or settings.explicit("agent.llm_context") is not None)
    except Exception:  # pylint: disable=broad-except
        llm_ctx = prof == "long"
    fixed = _fixed_chars()
    start = fixed + s["search_chars"] + s["rules_near_chars"] + (s["llm_context_chars"] if llm_ctx else 0)

    def tok(chars: int) -> int:
        return int(round(chars / CHARS_PER_TOKEN))

    out: dict[str, Any] = {"start_tokens": tok(start), "instructions_tokens": tok(fixed),
                           "largest_result_tokens": tok(max(s["tool_chars"], s["describe_chars"], s["compare_chars"])),
                           "cut_at_tokens": s["compact_at"], "warnings": []}
    if not w:
        return out
    if out["start_tokens"] > START_SHARE * w:
        out["warnings"].append(f"an answer starts with about {out['start_tokens']:,} tokens (instructions, tools, "
                               f"knowledge, rules{', LLM context' if llm_ctx else ''}) of the model's {w:,}: little "
                               "room left for the results")
    if out["largest_result_tokens"] > RESULT_SHARE * w:
        out["warnings"].append(f"one tool result may take about {out['largest_result_tokens']:,} tokens of the "
                               f"model's {w:,}")
    if s["compact_at"] and s["compact_at"] >= w:
        out["warnings"].append(f"older results are cut from {s['compact_at']:,} prompt tokens: after the model's "
                               f"{w:,} are full")
    elif s["compact_at"] and 1.5 * s["compact_at"] >= w:
        out["warnings"].append(f"the second cut of the older results ({int(1.5 * s['compact_at']):,} prompt "
                               f"tokens) comes after the model's {w:,} are full")
    return out


def report() -> dict[str, Any]:
    """For the Settings page and test-llm: the profile in use and why, the window, both profiles' sizes (in use and
    their own), where each comes from, and the estimate of what the profile in use gives against the window."""
    w = window()
    p = profile()
    out: dict[str, Any] = {"profile": p, "window": w, "long_from": long_from(), "names": list(NAMES),
                           "about": ABOUT, "unit": UNIT, "sizes": {}, "defaults": {}, "set": {}}
    for q in PROFILES:
        wq = w if q == "short" else (w or long_assumed())
        out["sizes"][q] = {n: size_for(n, q, wq) for n in NAMES}
        out["defaults"][q] = {n: default_size(n, q, wq) for n in NAMES}
        out["set"][q] = {n: ("budget." + q + "." + n if _mine(f"budget.{q}.{n}") is not None else
                             SETTING[n] if n in SETTING and _mine(SETTING[n]) is not None else None) for n in NAMES}
    out["estimate"] = estimate(p, w)
    return out


def described() -> str:
    """For the Settings page and test-llm: the profile in use and why, in one line, with what may not fit."""
    w = window()
    p = profile()
    est = estimate(p, w)
    text = (f"{p} ({'the model reads ' + format(w, ',') + ' tokens per request' if w else 'the context is not stated'}"
            f"; older results cut from {size('compact_at'):,} prompt tokens, {size('search_chars'):,} characters "
            f"of knowledge, Context sections up to {size('context_chars'):,} characters; an answer starts with about "
            f"{est['start_tokens']:,} tokens, an estimate)")
    if est["warnings"]:
        text += "; WARNING: " + "; ".join(est["warnings"])
    return text


def table() -> list[str]:
    """For test-llm: both profiles' sizes, one line each, the profile in use marked; * = set by a person."""
    rep = report()
    lines = []
    for q in PROFILES:
        mark = ", in use" if q == rep["profile"] else ""
        label = "small model" if q == "short" else "big model"
        parts = [f"{n} {rep['sizes'][q][n]:,}" + ("*" if rep["set"][q][n] else "") for n in NAMES]
        lines.append(f"{label} ({q}{mark}): " + ", ".join(parts))
    lines.append("* set by a person (budget.<profile>.<size>, or agent.compact_at / search.prompt_chars for both)")
    return lines
