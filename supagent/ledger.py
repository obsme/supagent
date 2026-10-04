"""The work ledger of a big request (0.9.2): its tasks, notes and results kept by the system, outside the
conversation, so that a long answer loses neither its context nor the work left to do.

A big request is an investigation, a question of many parts (several figures, a report) or several charts and a
dashboard (agent.ledger). The agent gets a tool, work_plan: it writes the request's tasks first, then marks the one it
works on (in_progress) and each one done with a one-line note of what it found, or dropped with the reason; the whole
list is given each time. The system:
  - attaches to the task in progress a digest of every tool result (what was called, what it gave): the results
    are the tools', never the model's words;
  - seeds an investigation's tasks (the facts, where, why, the check of the cause, what changed behind it) and adds
    one task per finding of compare_groups (explain it or rule it out);
  - reminds the model of the plan every few calls, gives the plan again when the conversation was shortened (the
    model's context was full) and when the calls run out;
  - before the answer: the tasks still open with no result, and the findings the answer does not mention, are sent
    back once (do them, or say why not);
  - shows the ledger in the answer's steps and keeps it with the answer: "continue" in the next message takes the
    open tasks up again.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

STATUSES = ("pending", "in_progress", "done", "dropped")
MAX_TASKS = 12
TITLE_CHARS = 160
NOTE_CHARS = 300
DIGEST_CHARS = 260
RESULTS_KEPT = 4               # digests kept per task (the latest)
REMIND_EVERY = 5               # tool calls without a plan update before a one-line reminder
FINDINGS = 4                   # tasks made from the first findings of compare_groups

SPEC = {"type": "function", "function": {
    "name": "work_plan",
    "description": (
        "Your plan for this request, kept by the system: a checklist of its tasks (each figure asked, each check, each "
        "lead to follow). Call it FIRST with every task (status pending), then again to set the task you work on to "
        "in_progress, and each one to done with a one-line note of what it found (or dropped with the reason). Give "
        "the whole list each time (same titles). After the first call, send each update in the same message as your "
        "next tool call (both calls at once), never as a step of its own. The system attaches the results of your "
        "tools to the task in progress and gives the plan back when the conversation gets long: answer from it."),
    "parameters": {"type": "object", "properties": {"tasks": {"type": "array", "items": {
        "type": "object", "properties": {
            "id": {"type": "integer", "description": "the number of a task already in the plan (keep it)"},
            "title": {"type": "string", "description": "what to do, short"},
            "status": {"type": "string", "enum": list(STATUSES)},
            "note": {"type": "string", "description": "done: what it found, in one line; dropped: why"}},
        "required": ["title", "status"]}}}, "required": ["tasks"]}}}

RULES = ("This is a big request: keep a work plan. Call work_plan first with its tasks (one per figure asked, check "
         "to make or lead to follow), mark the task you work on in_progress and each task done with what it found "
         "(or dropped with why), and answer only when every task is done or dropped: the answer covers each task. "
         "A task already in the plan keeps its number (give its id); add only what the plan does not have. After the "
         "first call, send each plan update together with your next tool call, in the same message.")

INVESTIGATION_TASKS = (
    "The facts: compare_groups on the question's scope (what is off against the usual, the stages)",
    "Where: the field and the values that hold the change",
    "Why: what the late or slow rows wait for, run on, depend on (capacity, inputs, servers, versions, logs)",
    "Check the cause on the same rows and time; rule out what does not match",
    "Deeper: the change or record behind the cause (changes, releases, alerts before the effect began)",
)
# "continue", "go on", "ok, carry on please", "vas-y, termine": a short message that only says to go on (not "Next,
# show me the ...": a question of its own)
CONTINUE = re.compile(r"^\W*(?:ok(?:ay)?\W+|yes\W+|oui\W+|d'accord\W+)?(?:please\W+)?(?:continue[sz]?|go on|carry on|keep going|"
                      r"proceed|finish(?: it| the rest)?|do the rest|the rest|vas-y|poursuis|termine)(?:\W+(?:please|"
                      r"stp|s'il te pla[iî]t|with the rest|the work|the investigation|l'investigation|le reste))*\W*$",
                      re.I)
MARK = re.compile(r"\((\d{1,2})\)\s")
CONCENTRATED = re.compile(r"concentrated on ([^\s,;()]+)|on \"([^\"]+)\"", re.I)


@dataclass
class Task:
    id: int
    title: str
    status: str = "pending"
    note: str = ""
    results: list[str] = field(default_factory=list)
    by: str = "model"                  # "model" (work_plan) or "system" (seeded)
    keys: list[str] = field(default_factory=list)    # a finding's values: the answer must say them

    def line(self, results: bool = True) -> str:
        mark = {"pending": "[ ]", "in_progress": "[>]", "done": "[x]", "dropped": "[-]"}[self.status]
        text = f"{mark} {self.id}. {self.title}"
        if self.note:
            text += f" -> {self.note}"
        if results and self.results:
            text += "".join(f"\n      result: {r}" for r in self.results[-2:])
        return text


def _label(title: str) -> str:
    """A task's name without its details: before ":" ("The facts: ..."), else its first three words."""
    title = title or ""
    head = title.split(":")[0] if ":" in title[:40] else " ".join(title.split()[:3])
    return re.sub(r"\W+", " ", head).strip().lower()


def _clip(text: Any, n: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def digest(tool: str, content: str) -> str:
    """What a tool gave, in a line: a query's row count and first rows, a comparison's conclusion, an error."""
    text = content or ""
    if text.startswith("tool error") or text.startswith("unknown tool"):
        return _clip(f"{tool}: {text}", DIGEST_CHARS)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return _clip(f"{tool}: {text}", DIGEST_CHARS)
    if not isinstance(data, dict):
        return _clip(f"{tool}: {text}", DIGEST_CHARS)
    if data.get("success") is False or (data.get("error") and not data.get("rows")):
        return _clip(f"{tool}: error {data.get('error')}", DIGEST_CHARS)
    for key in ("conclusion", "summary", "verdict", "answer"):
        if isinstance(data.get(key), str) and data[key].strip():
            return _clip(f"{tool}: {data[key]}", DIGEST_CHARS)
    rows = data.get("rows") if isinstance(data.get("rows"), list) else data.get("data")
    if isinstance(rows, list):
        n = data.get("row_count", len(rows))
        first = "; ".join(", ".join(f"{k}={v}" for k, v in list(r.items())[:5]) if isinstance(r, dict) else str(r)
                          for r in rows[:3])
        return _clip(f"{tool}: {n} row(s): {first}", DIGEST_CHARS)
    return _clip(f"{tool}: {text}", DIGEST_CHARS)


def findings(content: str) -> list[tuple[str, list[str]]]:
    """The numbered findings of a compare_groups result ("(1) rows past READY_TIME ...: on \"APP\", concentrated on X
    ... (2) ..."): (a short title, the values it names). The markers are taken in their order (1, 2, 3...): a
    finding's own parentheses are no marker."""
    try:
        data = json.loads(content)
    except (ValueError, TypeError):
        return []
    text = data.get("conclusion") if isinstance(data, dict) else None
    if not isinstance(text, str):
        return []
    marks, n = [], 1
    for m in MARK.finditer(text):
        if int(m.group(1)) == n:
            marks.append(m)
            n += 1
    out = []
    for i, m in enumerate(marks):
        body = " ".join(text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)].split())
        keys = [a for a, _b in CONCENTRATED.findall(body) if a]
        title = body.split(" (the same values for")[0].split(", while ")[0]
        out.append((_clip(title, TITLE_CHARS), list(dict.fromkeys(keys))))
    return out[:FINDINGS]


class Ledger:
    def __init__(self, request: str) -> None:
        self.request = request
        self.tasks: list[Task] = []
        self.unfiled: list[str] = []
        self.calls_since_update = 0
        self.updates = 0

    # ------------------------------------------------------------------ writing
    def _find(self, title: str, ident: Any = None, loose: bool = False) -> Task | None:
        if ident is not None:
            for t in self.tasks:
                if str(t.id) == str(ident):
                    return t
        key = re.sub(r"\W+", " ", title or "").strip().lower()
        if not key:
            return None
        for t in self.tasks:
            if re.sub(r"\W+", " ", t.title).strip().lower() == key:
                return t
        if len(key.split()) >= 2:                      # "The facts" for the seeded "The facts: compare_groups ..."
            for t in self.tasks:
                if re.sub(r"\W+", " ", t.title.split(":")[0]).strip().lower() == key:
                    return t
        # a step of the system's plan written in the model's words ("The facts: compare_groups on <its scope>",
        # "Check the cause: pool saturation on ..."): the same label, when one system task has it
        # (the model's plan only: two findings of the system share their label and stay two tasks)
        label = _label(title) if loose else ""
        same = [t for t in self.tasks if t.by == "system" and _label(t.title) == label] if label else []
        return same[0] if len(same) == 1 else None

    def add(self, title: str, by: str = "model", keys: list[str] | None = None, status: str = "pending") -> Task | None:
        title = _clip(title, TITLE_CHARS)
        if not title:
            return None
        found = self._find(title)
        if found is not None:
            return found
        if len(self.tasks) >= MAX_TASKS:
            return None
        t = Task(id=len(self.tasks) + 1, title=title, status=status, by=by, keys=list(keys or []))
        self.tasks.append(t)
        return t

    def plan(self, items: Any) -> str:
        """The model's work_plan call: its tasks merged in (by id or title), statuses and notes updated."""
        self.updates += 1
        self.calls_since_update = 0
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except ValueError:
                items = [x.strip(" -*") for x in items.splitlines() if x.strip()]
        for item in items if isinstance(items, list) else []:
            if isinstance(item, str):
                item = {"title": item}
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or item.get("task") or "").strip()
            ident = item.get("id")
            numbered = re.match(r"^\s*(\d{1,2})\s*[.):-]\s+(.+)$", title)
            if numbered:                               # "1. Les faits : ..." for task 1: the same task, its words
                title = numbered.group(2).strip()
                if ident is None and any(str(x.id) == numbered.group(1) for x in self.tasks):
                    ident = numbered.group(1)
            t = self._find(title, ident, loose=True) or self.add(title)
            if t is None:
                continue
            status = str(item.get("status") or "").strip().lower().replace(" ", "_").replace("-", "_")
            if status in STATUSES:
                if status == "in_progress":          # one task in progress at a time
                    for other in self.tasks:
                        if other is not t and other.status == "in_progress":
                            other.status = "pending"
                t.status = status
            if item.get("note"):
                t.note = _clip(item["note"], NOTE_CHARS)
        return "Work plan kept (the results of your tools go to the task in progress):\n" + self.render()

    def seed_investigation(self) -> None:
        for title in INVESTIGATION_TASKS:
            self.add(title, by="system")

    def seed_findings(self, content: str) -> list[Task]:
        made = []
        for title, keys in findings(content):
            t = self.add(f"Explain or rule out: {title}", by="system", keys=keys)
            if t is not None:
                made.append(t)
        return made

    def take_up(self, state: dict | None) -> bool:
        """The open tasks of an earlier answer's ledger ("continue"), with the notes of the done ones."""
        tasks = (state or {}).get("tasks") or []
        open_ = [t for t in tasks if t.get("status") in ("pending", "in_progress")]
        if not open_:
            return False
        for t in tasks:
            if t.get("status") == "done" and t.get("note"):
                self.add(t.get("title", ""), by=t.get("by", "model"), status="done")
                self.tasks[-1].note = _clip(t["note"], NOTE_CHARS)
        for t in open_:
            self.add(t.get("title", ""), by=t.get("by", "model"), keys=t.get("keys"))
        return True

    def attach(self, tool: str, content: str) -> None:
        """A tool's result, as a digest, on the task in progress (else kept apart, given with the plan)."""
        if tool == SPEC["function"]["name"]:
            return
        self.calls_since_update += 1
        line = digest(tool, content)
        current = next((t for t in self.tasks if t.status == "in_progress"), None)
        if current is None:
            self.unfiled = (self.unfiled + [line])[-RESULTS_KEPT:]
            return
        current.results = (current.results + [line])[-RESULTS_KEPT:]

    # ------------------------------------------------------------------ reading
    def open(self) -> list[Task]:
        return [t for t in self.tasks if t.status in ("pending", "in_progress")]

    def unworked(self) -> list[Task]:
        """Open tasks with no result attached: what was not looked at."""
        return [t for t in self.open() if not t.results]

    def uncovered(self, answer: str) -> list[Task]:
        """The findings (with values) the answer does not mention and that are not dropped."""
        low = (answer or "").lower()
        return [t for t in self.tasks if t.keys and t.status != "dropped"
                and not any(k.lower() in low for k in t.keys)]

    def render(self, results: bool = True, max_chars: int = 2500) -> str:
        lines = [t.line(results) for t in self.tasks]
        if results and self.unfiled:
            lines.append("results not attached to a task (none was in progress): " + " | ".join(self.unfiled[-2:]))
        text = "\n".join(lines) or "(no task yet)"
        if len(text) > max_chars:
            text = "\n".join(t.line(False) for t in self.tasks)[:max_chars]
        return text

    def reminder(self) -> str:
        done = sum(t.status in ("done", "dropped") for t in self.tasks)
        cur = next((t for t in self.tasks if t.status == "in_progress"), None)
        nxt = next((t for t in self.tasks if t.status == "pending"), None)
        parts = [f"{done} of {len(self.tasks)} tasks done"]
        if cur:
            parts.append(f"in progress: {cur.id}. {cur.title}")
        if nxt:
            parts.append(f"next: {nxt.id}. {nxt.title}")
        return "(Work plan: " + "; ".join(parts) + ". Update it with work_plan when a task is done.)"

    def state(self) -> dict:
        return {"request": _clip(self.request, 300),
                "tasks": [{"id": t.id, "title": t.title, "status": t.status, "note": t.note, "by": t.by,
                           "keys": t.keys, "results": t.results[-2:]} for t in self.tasks]}
