"""What a value is, written for the values of the categories that have no description (0.10.5, the user's request of 8
October 2026: what people add by hand, values and links, is understood by itself).

A value with no description (one a person added included) gets one written by the AI from what is known of it, and
from that only: the sentences of the documents, guides and Context pages that name it, the parts it is linked to
(with their explanations), what it is part of, where the data has it (the labels and fields that hold its name, in
which database). A value with none of these gets nothing: there is nothing to say it from. What a person wrote is
never written over; a description the AI wrote says so (the value's `suggested` "description_by": "llm", shown on
the System map) until a person saves another one.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from superset import db

log = logging.getLogger(__name__)

BATCH = 8                    # values per call
CHARS = 400                  # a description's length at most
SYSTEM = ("You write what each part of an IT platform is, for the people and the agent who investigate problems on "
          "it. For each part given (its name, its category, the sentences of the documents that name it, the parts it "
          "is linked to, what it is part of, where the data has it), write one plain sentence: what it is and what it "
          "does, from what is given only. When what is given does not say what it is or does (the part only named in "
          "passing, or only its category), give no description for it. Never add a technology, a host, a team, a "
          "figure, a role or a purpose that is not given (what a part manages, represents or is for, when no line "
          "says it). Keep every link's direction: \"A calls B\" is said of B as \"called by A\", never \"calls A\".")
# (0.10.6) a description that says nothing of the part, or that turns a given link round, is not kept
EMPTY_WORDS = {"a", "an", "the", "is", "are", "of", "value", "values", "category", "categories", "part", "parts", "it",
               "its", "them", "and", "that", "which", "this", "in", "to", "by"}
VERB_OF = {"calls": "calls", "called by": "calls", "depends on": "depends on", "depended on by": "depends on",
           "sends data to": "sends data to", "receives data from": "sends data to", "reads from": "reads from",
           "read by": "reads from", "runs on": "runs on", "monitors": "monitors", "monitored by": "monitors",
           "triggers": "triggers", "triggered by": "triggers"}
TOOL = {"type": "function", "function": {
    "name": "descriptions",
    "description": "The descriptions of the parts given, by their number (none for a part nothing given describes).",
    "parameters": {"type": "object", "properties": {"descriptions": {"type": "array", "items": {
        "type": "object", "properties": {"n": {"type": "integer"}, "description": {"type": "string"}},
        "required": ["n", "description"]}}}, "required": ["descriptions"]}}}


def wanted(limit: int = 200) -> list[Any]:
    """The approved values of the parts' categories with no description, 3 letters or more (0.10.6: not the subjects,
    topics the knowledge is about: what they hold says what they are)."""
    from supagent.knowledge.facets import editable
    from supagent.models import Facet

    parts = [c for c in editable() if c != "subject"]       # (0.10.6) the parts' categories: a subject is a topic
    rows = (db.session.query(Facet).filter(Facet.status == "approved", Facet.facet.in_(parts))
            .order_by(Facet.id).all())
    return [f for f in rows if not (f.description or "").strip() and len(f.value or "") >= 3][:limit]


def _known(f: Any, said: list[tuple[str, str, str]], names: dict[int, str]) -> list[str]:
    """What is known of a value, as lines for the LLM (empty: nothing to describe it from)."""
    from supagent.knowledge.sysmap import INTERACTIONS
    from supagent.models import Link

    lines = [f'"{sentence[:300]}" ({title})' for _ref, title, sentence in said[:3]]
    ref = f"facet:{f.id}"
    for x in db.session.query(Link).filter((Link.a_ref == ref) | (Link.b_ref == ref), Link.status == "approved").limit(12):
        other = x.b_ref if x.a_ref == ref else x.a_ref
        try:
            name = names.get(int(other.split(":", 1)[1]))
        except (ValueError, IndexError):
            name = None
        if not name:
            continue
        what = "is part of" if x.kind == "part_of" else INTERACTIONS.get(x.kind, x.kind)
        line = f"{f.value} {what} {name}" if x.a_ref == ref else f"{name} {what} {f.value}"
        lines.append(line + (f" ({x.note[:150]})" if x.note else ""))
    try:
        from supagent.knowledge.valueindex import places

        for p in places([f.value])[:4]:
            lines.append(f"in the data: the {p.get('kind')} {p.get('name')} of {p.get('database')} holds it")
    except Exception:  # pylint: disable=broad-except   (no data, or no user to read it as: said without it)
        db.session.rollback()
    return lines


def says_something(about: str, value: str, category: str) -> bool:
    """(0.10.6) A description that says more than the part's name and category ("X is a value of the category
    subject", "It is read by Other." are not kept: they say nothing of the part)."""
    text = about.lower()
    if re.match(r"(it|they|this|these)\b", text) or "a value of the category" in text:
        return False
    for phrase in sorted(VERB_OF, key=len, reverse=True):      # a link's words alone ("sends data to it") say nothing
        text = text.replace(phrase, " ")
    words = [w for w in (x.strip("._-") for x in re.findall(r"[a-z0-9][a-z0-9_.-]*", text))
             if w and w not in EMPTY_WORDS and w not in value.lower().split() and w != category.lower()]
    return len(words) >= 2


def links_kept(about: str, value: str, lines: list[str]) -> bool:
    """(0.10.6) A description that says a given link the other way round is not kept: a line "B calls X" and no line
    "X calls B", the description "X ... calls B"."""
    said = set()
    for line in lines:
        for phrase, verb in VERB_OF.items():
            if phrase == verb and f" {verb} " in f" {line} ":
                a, b = line.split(f" {verb} ", 1)
                said.add((a.strip().lower(), verb, re.sub(r"\s*\(.*$", "", b).strip().lower()))
    me = value.lower()
    text = " " + about.lower() + " "
    for (a, verb, b) in list(said):
        other = b if a == me else a if b == me else None
        if not other:
            continue
        for phrase, v in VERB_OF.items():
            if v != verb or f" {phrase} {other}" not in text:
                continue
            active = phrase == verb                        # "calls B" said of X: X calls B
            if active and a != me and (me, verb, other) not in said:
                return False
            if not active and b != me and (other, verb, me) not in said:
                return False
    return True


def _descriptions(msg: dict[str, Any]) -> list[dict[str, Any]]:
    for tc in msg.get("tool_calls") or []:
        if (tc.get("function") or {}).get("name") == "descriptions":
            try:
                args = json.loads((tc.get("function") or {}).get("arguments") or "{}")
            except ValueError:
                return []
            items = args.get("descriptions") if isinstance(args, dict) else None
            return [x for x in items or [] if isinstance(x, dict)]
    return []


def describe_values(llm: Any, seconds: float = 120.0, limit: int = 200) -> dict[str, Any]:
    """The values with no description described, BATCH at a time, until `seconds`; the next run continues."""
    from supagent.knowledge.stopping import check
    from supagent.knowledge.sysmap import hints
    from supagent.models import Facet

    t0 = time.time()
    out: dict[str, Any] = {"described": 0, "nothing_known": 0, "calls": 0}
    todo = wanted(limit)
    if not todo:
        return out
    names = {i: v for i, v in db.session.query(Facet.id, Facet.value)}
    said = hints({f.id: f for f in todo})
    ready = []
    for f in todo:
        lines = _known(f, said.get(f.id, []), names)
        if lines:
            ready.append((f, lines))
        else:
            out["nothing_known"] += 1
    for start in range(0, len(ready), BATCH):
        if time.time() - t0 > seconds:
            out["left"] = len(ready) - start
            break
        check()
        batch = ready[start:start + BATCH]
        text = "\n".join(f"{n}. {f.value} (a value of the category {f.facet}). Known: " + "; ".join(lines)
                         for n, (f, lines) in enumerate(batch, 1))
        try:
            msg = llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "Parts:\n" + text}],
                           tools=[TOOL], max_tokens=1500)
        except Exception as ex:  # pylint: disable=broad-except
            log.warning("supagent value_about: %s", str(ex)[:300])
            out["error"] = str(ex)[:300]
            break
        out["calls"] += 1
        for d in _descriptions(msg):
            n, about = d.get("n"), " ".join(str(d.get("description") or "").split())[:CHARS]
            if not isinstance(n, int) or not 1 <= n <= len(batch) or len(about) < 12 or about.upper() == "NONE":
                continue
            f, given = batch[n - 1]
            if not says_something(about, f.value, f.facet) or not links_kept(about, f.value, given):
                out["not_kept"] = out.get("not_kept", 0) + 1
                continue
            db.session.refresh(f)
            if (f.description or "").strip():            # (a person wrote one meanwhile: theirs stays)
                continue
            f.description = about
            f.suggested = {**(f.suggested or {}), "description_by": "llm"}
            out["described"] += 1
        db.session.commit()
    return out
