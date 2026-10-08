"""(0.10) Context pages from what the documents and the code state: a page per part they describe (its code, what it
uses and what uses it, its data, the pages about it, each statement with where it was read), per repository and per
wiki space; facts pages (no LLM), in the search like every Context page, shown to who may query the data they name."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_understand_010 import world  # noqa: F401  (two repositories and a wiki page)


def test_a_page_per_part_repository_and_wiki_space(world):  # noqa: F811
    from supagent.knowledge import understand as U
    from supagent.knowledge.context_docs import pages

    U.run(reason="test")
    got = {p["title"]: p for p in pages()}
    ledger = got["Part: ledger"]["content"]
    assert "Also named: ledger-api" in ledger
    assert "## Its code" in ledger and "ledger-api" in ledger.split("## Its code", 1)[1]
    uses = ledger.split("## What it uses", 1)[1]
    assert "calls **billing** (code" in uses and "app/clients.py" in uses       # where it was read
    assert "sends data to **journal**" in uses and "reads from **ledger-cache**" in uses
    assert "emits metric `ledger_entries_total`" in ledger.split("## Its data", 1)[1]
    assert got["Part: ledger"]["database_ids"]                                    # it names that database's data
    assert "**ledger** calls it" in got["Part: billing"]["content"]               # what uses it
    repos = [t for t in got if t.startswith("Repository: ")]
    assert len(repos) == 2 and "python" in got[repos[0]]["content"] + got[repos[1]]["content"]
    wiki = [t for t in got if t.startswith("Wiki: ")]
    assert wiki and "Ledger service" in got[wiki[0]]["content"]


def test_the_pages_are_written_and_searched(world, monkeypatch):  # noqa: F811
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import understand as U
    from supagent.knowledge.context import build_context
    from supagent.models import Chunk, ContextPage, Run

    before = {i for (i,) in db.session.query(ContextPage.id)}
    try:
        db.session.query(Run).filter(Run.status == "running").update({"status": "done"})
        db.session.commit()
        monkeypatch.setattr(settings, "get", lambda k, _g=settings.get: False if k == "charts.scan" else _g(k))
        U.run(reason="test")
        out = build_context(reason="test", llm=False)
        assert out["status"] in ("done", "partial"), out
        page = db.session.query(ContextPage).filter(ContextPage.slug == "parts-ledger").one()
        assert page.kind == "facts" and "calls **billing**" in (page.content or page.proposed_content or "")
        pieces = db.session.query(Chunk).filter(Chunk.ref.like(f"context:{page.id}%")).all()
        assert pieces and any("billing" in (c.text or "") for c in pieces)
    finally:                                                      # every page the build made, with its pieces
        db.session.rollback()
        for p in db.session.query(ContextPage).filter(ContextPage.id.notin_(list(before) or [-1])):
            db.session.query(Chunk).filter(Chunk.ref.like(f"context:{p.id}%")).delete(synchronize_session=False)
            db.session.delete(p)
        db.session.commit()
