"""What a Helpful answer leaves for next time, written by the agent from the whole discussion (0.9.6).

An answer marked Helpful became a learned answer as it ran: its generic question, its final query and its path (every
step as the tools were called, the repeats counted). A person reviewing it read the run, not the way to answer. The
agent now reads the whole discussion (the user's messages, the answer) and the steps that worked (the failed ones and
the repeats left out), and writes what to keep: a title, a description (what it answers, when to reuse it), the steps
in order (each once) and the tasks (the checks to do each time). No value of that one case stays (a day, a name, an
id: "the day asked", "a given server"); a step naming data the answer never used is left out. A person corrects it in
To review before confirming it; the agent is given it with the similar questions that follow.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from typing import Any

from superset import db

log = logging.getLogger(__name__)

STEPS, TASKS, TEXT = 8, 6, 300
PROMPT = """You keep how a data assistant answered a question, for its team, so that the next similar question is
answered the same way, quickly. You are given the discussion (the user's messages, the final answer) and the steps
that worked, in order (failed and repeated tries already left out). Write JSON only:
{"title": "two to six words",
 "description": "one to three sentences: what this answers, and when to reuse it",
 "steps": ["the steps that reach the answer, in order, each once, each a short sentence naming the data used (table or
            metric, fields or labels) and what is done with it (filter, group, compare, check)"],
 "tasks": ["the checks to do each time: a team rule applied, the period to state, a unit, what to say when nothing is
           found"]}
At most 8 steps and 6 tasks. Generic: no value of this one case (no day, date, name of a server, application, job,
customer, no id, no figure): say "the day asked", "a given server". Only what the discussion and the steps show: no step,
data or check of your own. Same language as the user's messages."""


def _clean(items: Any, limit: int) -> list[str]:
    out: list[str] = []
    for x in items if isinstance(items, list) else []:
        t = " ".join(str(x or "").split())[:TEXT]
        if t and t.lower() not in {o.lower() for o in out}:
            out.append(t)
    return out[:limit]


IDENT = re.compile(r"`([^`]+)`|\"([^\"]{2,})\"|\b([A-Za-z][\w@]*[_.\-][\w@.\-]*[A-Za-z0-9])\b")


def _grounded(step: str, seen: str) -> bool:
    """A step names only data the answer used (its identifiers are in its calls or in the discussion)."""
    for m in IDENT.finditer(step):
        name = next(g for g in m.groups() if g)
        if name.lower() not in seen:
            return False
    return True


def steps_that_worked(trace: list[dict]) -> list[str]:
    """The answer's successful calls, in order, each once: the tool and what it was asked (its query as written)."""
    out: list[str] = []
    for t in trace:
        if t.get("status") != "done":
            continue
        tool = t.get("called") or t.get("tool")
        if tool in ("work_plan", "understood"):
            continue
        args = t.get("args") or {}
        req = args.get("request") if isinstance(args.get("request"), dict) else args
        what = (req or {}).get("sql") or (req or {}).get("expr") or json.dumps(args, ensure_ascii=False, default=str)
        line = f"{tool}: {' '.join(str(what).split())[:600]}"
        if line not in out:
            out.append(line)
    return out[:20]


def summarize(question: str, earlier: list[str], answer: str, trace: list[dict], llm: Any = None) -> dict | None:
    """{"title", "description", "how": [steps], "tasks": [checks]} of a Helpful answer, or None (no LLM answer)."""
    from supagent.knowledge.generic import _parse, case_values, leaks
    from supagent.llm import LLM

    worked = steps_that_worked(trace)
    lines = [f"Earlier user message: {e[:500]}" for e in (earlier or [])[-5:] if e]
    lines.append(f"Last user message: {(question or '')[:1500]}")
    lines.append(f"Final answer: {(answer or '')[:2500]}")
    lines.append("Steps that worked:\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(worked)))
    hard, soft = case_values([question] + list(earlier or []), " ".join(worked))
    try:
        client = llm or LLM()
        messages = [{"role": "system", "content": PROMPT}, {"role": "user", "content": "\n".join(lines)}]
        data = _parse(client.chat(messages, max_tokens=700).get("content") or "")
        if not data:
            return None
        text = json.dumps(data, ensure_ascii=False)
        left = leaks(text, hard | soft)
        if left:                                       # once: the values of this one case taken out
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": "These values of this one case are still there: " + ", ".join(left)
                          + ". Replace each one by its kind (the day asked, a given server, a given application); keep "
                          "only a fixed code that defines what is counted (a status). Give the JSON again."}]
            again = _parse(client.chat(messages, max_tokens=700).get("content") or "")
            data = again or data
    except Exception as ex:  # pylint: disable=broad-except   (the learned answer stays as it ran)
        log.warning("supagent: the Helpful answer's summary not written: %s", str(ex)[:200])
        return None
    seen = (" ".join(worked) + " " + " ".join([question] + list(earlier or [])) + " " + (answer or "")).lower()

    def scrub(t: str) -> str:
        for v in leaks(t, hard):                         # ids, numbers and dates never stay
            t = re.sub(r"(?<![\w-])" + re.escape(v) + r"(?![\w-])", "a given value", t, flags=re.I)
        return t

    how = [scrub(s) for s in _clean(data.get("steps"), STEPS) if _grounded(s, seen)]
    tasks = [scrub(s) for s in _clean(data.get("tasks"), TASKS) if _grounded(s, seen)]
    title = scrub(" ".join(str(data.get("title") or "").split()).strip(" ."))[:80]
    description = scrub(" ".join(str(data.get("description") or "").split()))[:600]
    if not (title or description or how):
        return None
    return {"title": title, "description": description, "how": how, "tasks": tasks}


def keep(recipe: Any, summary: dict | None, by: str = "agent") -> bool:
    """The summary on the learned answer, unless a person wrote it (theirs stays)."""
    if not summary or (recipe.summary_by and recipe.summary_by != "agent" and by == "agent"):
        return False
    recipe.title, recipe.description = summary.get("title") or None, summary.get("description") or None
    recipe.how, recipe.tasks = summary.get("how") or [], summary.get("tasks") or []
    recipe.summary_by, recipe.summary_at = by, dt.datetime.utcnow()
    db.session.commit()
    return True


def brief(recipe: Any) -> str:
    """The summary as the agent is given it with a similar question ("" when none)."""
    if not (recipe.title or recipe.description or recipe.how):
        return ""
    out = f"{recipe.title or ''}" + (f": {recipe.description}" if recipe.description else "")
    if recipe.how:
        out += " Steps: " + " ".join(f"{i + 1}) {s}" for i, s in enumerate(recipe.how))
    if recipe.tasks:
        out += " Checks: " + "; ".join(recipe.tasks)
    return out.strip()
