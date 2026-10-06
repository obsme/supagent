"""Wipe what the learning made, to make it again (0.9.6.7, the user's request of 6 October 2026: "a procedure to wipe
the data we have and do again the Context, the categories and their descriptions, the links and their
descriptions").

  context      the Context pages the agent wrote (a page a person wrote stays), with their search pieces and what
               was linked to them
  categories   the values of the categories the learning read or proposed (from the data, by the LLM) with what they
               were given (the items' categories) and their links; every item is classified again; a value a person
               added stays, with its description, and keeps the items a person gave it (the LLM's are made again)
  links        the links of the System map the learning read or proposed, with their descriptions; a link a person
               drew, or whose description a person wrote, stays
  everything   (--all) what people made goes too: every value, link and Context page, the categories' descriptions

The categories themselves (their names, fields, what is inside what) stay: they are settings people chose. A backup
of the knowledge is made first: superset supagent restore <its name> --parts categories,context --yes puts it back.
Then (the CLI says it): superset supagent learn, classify, interactions --again, context --build --force.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import or_

from superset import db

log = logging.getLogger(__name__)

PEOPLE = ("admin", "seed")          # a value added by a person, or from what people wrote (the catalog)


class ResetError(Exception):
    pass


def _by_person(link: Any) -> bool:
    """A link a person drew, or whose description a person wrote."""
    return link.source == "admin" or bool(link.explained_by and link.explained_by not in ("llm", "data"))


def _scope(context: bool, categories: bool, links: bool, everything: bool) -> dict[str, Any]:
    """The rows that go {"pages": [...], "values": [...], "links": [...], "tags": [...]} and the counts of what stays."""
    from supagent.models import ContextPage, Facet, Link, Tag

    out: dict[str, Any] = {"pages": [], "values": [], "links": [], "tags": [], "kept": {}}
    if context:
        pages = db.session.query(ContextPage).all()
        out["pages"] = [p for p in pages if everything or (p.author or "agent") == "agent"]
        out["kept"]["context pages a person wrote"] = len(pages) - len(out["pages"])
    gone_values: set[int] = set()
    if categories:
        values = db.session.query(Facet).all()
        out["values"] = [f for f in values if everything or (f.source or "") not in PEOPLE]
        gone_values = {f.id for f in out["values"]}
        out["kept"]["values a person added"] = len(values) - len(out["values"])
        tags = db.session.query(Tag).all()
        out["tags"] = [t for t in tags if everything or t.facet_id in gone_values or (t.source or "") != "admin"]
        out["kept"]["items a person gave a value"] = len(tags) - len(out["tags"])
    refs = {f"facet:{i}" for i in gone_values} | {f"context:{p.id}" for p in out["pages"]}
    seen: set[int] = set()
    for x in db.session.query(Link).filter(or_(Link.a_ref.like("facet:%"), Link.b_ref.like("facet:%"),
                                               Link.a_ref.like("context:%"), Link.b_ref.like("context:%"))):
        touches = x.a_ref in refs or x.b_ref in refs
        learned = links and x.a_ref.startswith("facet:") and x.b_ref.startswith("facet:") and (everything or not _by_person(x))
        if (touches or learned) and x.id not in seen:
            seen.add(x.id)
            out["links"].append(x)
    if links:
        drawn = db.session.query(Link).filter(Link.a_ref.like("facet:%"), Link.b_ref.like("facet:%")).count()
        out["kept"]["links a person drew or described"] = drawn - sum(
            1 for x in out["links"] if x.a_ref.startswith("facet:") and x.b_ref.startswith("facet:"))
    return out


def plan(context: bool, categories: bool, links: bool, everything: bool = False) -> dict[str, Any]:
    """What would go and what would stay (nothing is changed)."""
    from supagent.models import Classified

    s = _scope(context, categories, links, everything)
    out = {"context pages": len(s["pages"]), "values": len(s["values"]), "items given a value": len(s["tags"]),
           "links": len(s["links"]), "kept": s["kept"]}
    if categories:
        out["items classified (all classified again)"] = db.session.query(Classified).count()
    if everything and categories:
        from supagent.knowledge.facets import about

        out["descriptions of categories"] = len(about())
    db.session.rollback()
    return out


def run(context: bool, categories: bool, links: bool, everything: bool = False, by: str = "") -> dict[str, Any]:
    """A backup, then the wipe (see the module). Raises ResetError when the backup was not made."""
    from supagent import settings
    from supagent.knowledge import sysmap
    from supagent.knowledge.backup import run_backup
    from supagent.knowledge.facets import forget_live
    from supagent.knowledge.freshness import touch
    from supagent.models import Chunk, Classified, Facet

    if not (context or categories or links):
        raise ResetError("say what to wipe: --context, --categories, --links")
    saved = run_backup(reason="before-reset", by=by)
    if saved.get("status") != "done":
        raise ResetError(f"the backup was not made ({saved.get('status')}: {saved.get('reason') or saved.get('error')}):"
                         " nothing was wiped")
    s = _scope(context, categories, links, everything)
    out = {"backup": saved.get("name"), "context pages": len(s["pages"]), "values": len(s["values"]),
           "items given a value": len(s["tags"]), "links": len(s["links"])}
    for x in s["links"]:
        db.session.delete(x)
    for t in s["tags"]:
        db.session.delete(t)
    if categories:
        out["items classified"] = db.session.query(Classified).delete(synchronize_session=False)
        for f in db.session.query(Facet).filter(Facet.suggested.isnot(None)):
            f.suggested = None                            # what the LLM suggested: proposed again if still true
        for f in s["values"]:
            db.session.delete(f)
        if everything:
            settings.set_value("categories.about", None, by=by or "reset")
    for p in s["pages"]:
        db.session.query(Chunk).filter(or_(Chunk.ref == f"context:{p.id}",
                                           Chunk.ref.like(f"context:{p.id}#%"))).delete(synchronize_session=False)
        db.session.delete(p)
    touch()
    db.session.commit()
    forget_live()
    if categories:
        sysmap.forget_hints()
    log.info("supagent reset by %s: %s", by or "?", out)
    return out


NEXT = """Next, to make them again (each can take a while on a big platform):
  superset supagent learn                      the values read in the data's fields and labels, their links
  superset supagent classify                   the items given their categories (the LLM), the relations texts state
  superset supagent interactions --again       the links the documents, guides, Context pages and notes state
  superset supagent context --build --force    the Context written again
Then Data dictionary -> To review: approve the values and links proposed (categories.review_all on).
Back as before: superset supagent restore {backup} --parts categories,context --yes"""
