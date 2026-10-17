"""(0.10.9.1) The LLM context: what the team's knowledge says, written by the learning for the agent's model and given
with every question. Two versions, two pages of the Context (technical): "llm-context", the full one, given to a model
that reads 128k tokens or more per request (the long context profile), and "llm-context-light", given to a model of
32k-64k (the short profile). Both are written from the catalog (the team's rules, glossary, formulas and facts), the
data dictionary's main indices and metrics with their meaning and fields, the links between the databases and the
questions answered well before (the history of Helpful answers). No LLM.

A section or a line about one database carries its marker (an HTML comment: not shown on the page): a user's question
is given only what the databases they may query hold. A person may edit either page (Context): the learning then keeps
their version, and the agent is given it."""
from __future__ import annotations

import logging
import re
from typing import Any

from superset import db

log = logging.getLogger(__name__)

SLUG_FULL, SLUG_LIGHT = "llm-context", "llm-context-light"
SECTION = "technical"
DB_MARK = re.compile(r"\s*<!-- db:([\d,]+) -->\s*$")
# how much of each kind of knowledge each version holds; the sections in the order they are given (what the data is
# first; the team's rules last: the agent's instructions give them apart, the page shows them for people)
LIGHT = {"main": 10, "about": 120, "answers": 10, "relations": 8, "entry": 160, "catalog": 300, "fields": False,
         "total": 6000}
FULL = {"main": 10 ** 6, "about": 1200, "answers": 200, "relations": 400, "entry": 2000, "catalog": 6000,
        "fields": True, "total": 120000}
OWN_KINDS = ("rule", "guide", "glossary", "formula", "index", "metrics")
RETRY_S = 600.0            # a build that failed is not tried again by every question before this long
_FAILED: dict[str, float] = {"at": 0.0}


def _mark(ids: Any) -> str:
    ids = sorted({int(i) for i in (ids if isinstance(ids, (list, tuple, set)) else [ids]) if i is not None})
    return f" <!-- db:{','.join(map(str, ids))} -->" if ids else ""


def _emark(e: dict[str, Any]) -> str:
    """(0.11.0) The catalog entry a line says (an HTML comment, before the database's): a question given that entry
    already (the knowledge found) is not given the line again."""
    return f" <!-- e:{int(e['id'])} -->" if e.get("id") is not None else ""


def _page(ev: dict[str, Any], full: bool) -> dict[str, Any]:
    from supagent.knowledge.context import clip

    lim = FULL if full else LIGHT
    names = {i: d["name"] for i, d in ev["databases"].items()}
    title = "LLM context (full)" if full else "LLM context (light)"
    head = [f"# {title}", "", "What the team's knowledge says, written by the learning for the AI model and given with "
            "every question (" + ("the full version: a model of 128k tokens or more" if full else
                                  "the light version: a model of 32k-64k tokens") + "). The data dictionary, the "
            "documents and the knowledge search hold more; the data itself is the truth for any figure."]
    entries = ev.get("entries") or []
    sections: list[list[str]] = []

    def entries_of(heading: str, kinds: tuple[str, ...] | None, chars: int) -> None:
        chosen = [e for e in entries if (e["classification"] in kinds if kinds else e["classification"] not in OWN_KINDS)]
        if chosen:
            sections.append(["", f"## {heading}", ""] + [
                f"- {e['title']}: {clip(' '.join(str(e.get('content') or '').split()), chars)}" + _emark(e) +
                _mark(e.get("database_id")) for e in sorted(chosen, key=lambda x: str(x["title"]).lower())])

    for dbid, d in sorted(ev["databases"].items(), key=lambda x: str(x[1]["name"]).lower()):
        lines = ["", f"## Data: {d['name']} ({d['backend']}){_mark(dbid)}", ""]
        for m in (d.get("main") or [])[:lim["main"]]:
            about = " ".join(str(m.get("about") or "").split())
            lines.append(f"- {m['kind']} `{m['name']}`" + (f": {clip(about, lim['about'])}" if about else ""))
        if d.get("others") and lim["main"] < 10 ** 6:
            lines.append(f"- ... and {d['others']:,} more (the data dictionary has every one)")
        for f in (d.get("fields") or []) if lim["fields"] else []:
            shown = "; ".join(f"`{x['name']}`" + (f" ({x['type']})" if x.get("type") else "") +
                              (f": {clip(' '.join(str(x['about']).split()), 160)}" if x.get("about") else "") +
                              (f" [{', '.join(x['values'])}]" if x.get("values") else "")
                              for x in f.get("shown") or [])
            if shown:
                lines.append(f"- the {f['child']}s of {f['kind']} `{f['name']}` ({f['total']:,}): {shown}")
        sections.append(lines)
    entries_of("Catalog: the indices and tables as the team describes them", ("index",), lim["catalog"])
    entries_of("Catalog: the metrics as the team describes them", ("metrics",), lim["catalog"])
    entries_of("Glossary", ("glossary",), lim["entry"])
    entries_of("Formulas", ("formula",), lim["entry"])
    relations = (ev.get("relations") or [])[:lim["relations"]]
    if relations:
        sections.append(["", "## Links between the data", ""] + [
            f"- `{r['a']}` ({names.get(r['a_db'], r['a_db'])}) and `{r['b']}` ({names.get(r['b_db'], r['b_db'])})"
            + _mark([r["a_db"], r["b_db"]]) for r in relations])
    answers = (ev.get("answers") or [])[:lim["answers"]]
    if answers:
        sections.append(["", "## Questions answered well before (the team marked the answer Helpful)", ""] + [
            f"- {clip(' '.join(str(a.get('question') or '').split()), 240)}" +
            (f" (with {a['tool']})" if a.get("tool") else "") + _mark(a.get("database_id")) for a in answers])
    entries_of("Other notes of the catalog", None, lim["entry"])
    lines = list(head)
    used = sum(len(x) + 1 for x in lines)
    for sec in sections:                         # within the version's size: whole lines, the first sections first;
        if used + sum(len(x) + 1 for x in sec[:4]) - 1 > lim["total"]:     # (0.11.1) a section only with its first
            continue                             # line (a heading with nothing under it said the data held nothing)
        for line in sec:
            if used + len(line) > lim["total"]:
                break
            lines.append(line)
            used += len(line) + 1
    rules = [e for e in entries if e["classification"] in ("rule", "guide")]
    if rules:                                    # last, whole: the agent's instructions give them apart
        lines += ["", "## Rules of the team", ""] + [
            f"- {e['title']}: {clip(' '.join(str(e.get('content') or '').split()), FULL['entry'])}" +
            _mark(e.get("database_id")) for e in sorted(rules, key=lambda x: str(x["title"]).lower())]
    return {"section": SECTION, "slug": SLUG_FULL if full else SLUG_LIGHT, "title": title,
            "content": "\n".join(lines).strip(), "database_ids": sorted(ev["databases"]),
            "sources": [{"ref": f"entry:{e['id']}", "title": e["title"]} for e in entries][:200]}


def pages(ev: dict[str, Any]) -> list[dict[str, Any]]:
    """The two versions from the learning's evidence (context.collect())."""
    return [_page(ev, True), _page(ev, False)]


def build() -> int:
    """Both versions written now (when the learning has not written them yet): how many pages were written."""
    from supagent.knowledge.context import _hash, collect, save_page

    ev = collect()
    n = 0
    for page in pages(ev):
        save_page(page, "facts", _hash([page["title"], page["content"], page["database_ids"]]))
        n += 1
    db.session.commit()
    return n


RULES_HEADING = "## Rules of the team"     # given apart with the agent's instructions: not twice


E_MARK = re.compile(r"\s*<!-- e:\d+ -->")


def filtered(markdown: str, allowed: set[int], leave_out: tuple[str, ...] = (), entries: bool = False) -> str:
    """The text a user may be given: the sections and lines of the databases they may not query left out (and the
    sections whose headings `leave_out` names), the markers removed ((0.11.0) the entries' kept with `entries`: the
    agent leaves out the lines of the entries the knowledge found gave)."""
    out: list[str] = []
    skip = False
    for line in (markdown or "").splitlines():
        m = DB_MARK.search(line)
        ids = {int(x) for x in m.group(1).split(",") if x} if m else set()
        text = DB_MARK.sub("", line) if m else line
        if line.startswith("## "):
            skip = bool(ids) and not ids <= allowed or text.strip() in leave_out
            if not skip:
                out.append(text)
            continue
        if skip or (ids and not ids <= allowed):
            continue
        out.append(text if entries else E_MARK.sub("", text))
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _cut(text: str, limit: int) -> str:
    """Within `limit` characters, cut at the end of a line (never in a line's middle)."""
    if len(text) <= limit:
        return text
    at = text.rfind("\n", 0, limit)
    return text[: at if at > 0 else limit].rstrip() + "\n- ... (more in the data dictionary and the knowledge search)"


def page_text() -> str:
    """(0.11.0) The LLM context this user may be given, whole (the agent takes the lines about the question from it:
    knowledge.contextplan.excerpt): as for_prompt, uncut."""
    return for_prompt(cut=False, entries=True)


def for_prompt(cut: bool = True, entries: bool = False) -> str:
    """The LLM context for this user's question: the full page for a model of the long context profile, the light one
    for a short profile's when agent.llm_context is set on (else none), only what the databases they may query hold,
    within size("llm_context_chars"). Written now when the learning has not written it yet; a page a person refused
    (rejected) is not given."""
    from supagent import settings

    if not settings.get("agent.llm_context"):
        return ""
    from supagent.budget import profile, size
    from supagent.models import ContextPage
    from supagent.security import visible_databases

    long = profile() == "long"
    if not long and settings.explicit("agent.llm_context") is None:
        return ""      # (0.10.9.3) a model of 32k-64k tokens: the light version only when a person sets it on (with it,
    #                    the lab's 64k model answered some follow-ups from it without a query: A/B of 2026-10-13)
    slug = SLUG_FULL if long else SLUG_LIGHT

    def page() -> Any:
        return (db.session.query(ContextPage).filter(ContextPage.section == SECTION, ContextPage.slug == slug)
                .one_or_none())

    p = page()
    if p is None:
        import time

        if time.time() - _FAILED["at"] < RETRY_S:
            return ""
        try:
            build()
        except Exception:  # pylint: disable=broad-except   (the question is answered without it)
            db.session.rollback()
            _FAILED["at"] = time.time()
            log.warning("supagent: the LLM context could not be written", exc_info=True)
            return ""
        p = page()
    if p is None or not p.content or p.kind == "rejected":
        return ""
    text = filtered(p.content, set(visible_databases()), (RULES_HEADING,), entries=entries)
    return _cut(text, size("llm_context_chars")) if cut else text
