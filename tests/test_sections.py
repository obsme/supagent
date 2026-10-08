"""Documents cut at their sections (0.9.6): each piece of a Markdown text (a document's page, a Context page, a guide)
under the headings it is part of, a section and the sections after it together while they fit, a section too long cut
in parts that keep its headings, headings inside code not read as headings; a repository's Markdown file named by its
front matter's title (or its first heading) with its path, its front matter not searched as text."""

from __future__ import annotations

PAGE = """# Bulk API

The Bulk API performs several operations in one request.

## Endpoints

```
POST /_bulk
# not a heading: a comment in a code block
```

## Query parameters

""" + "A parameter that changes how the request is run. " * 40 + """

### Refresh

Whether to refresh the shards. {: .note}

## Routing {#routing}

Routing sends a document to a shard.
"""


def test_sections_and_their_headings(ctx):
    from supagent.knowledge.index import sections

    got = sections(PAGE)
    assert [p for p, _t in got] == [["Bulk API"], ["Bulk API", "Endpoints"], ["Bulk API", "Query parameters"],
                                    ["Bulk API", "Query parameters", "Refresh"], ["Bulk API", "Routing"]]
    assert "# not a heading" in got[1][1]                      # a code block's line stays in its section
    assert got[4][1].startswith("## Routing {#routing}")       # the text kept as written, the attribute out of the name
    assert sections("no heading here") == [([], "no heading here")]


def test_pieces_cut_at_sections_keep_their_headings(ctx):
    from supagent.knowledge.index import split_sections

    parts = split_sections(PAGE, size=1500)
    labels = [w for w, _t in parts]
    assert all(len(t) <= 1500 + 50 for _w, t in parts)
    assert labels[0].startswith("Bulk API")
    assert any(w.startswith("Bulk API › Query parameters") for w in labels)   # the long section, in parts
    long_parts = [t for w, t in parts if w == "Bulk API \u203a Query parameters"]
    assert len(long_parts) >= 2 and all("parameter" in t for t in long_parts)
    joined = "\n".join(t for _w, t in parts)
    for needle in ("POST /_bulk", "Whether to refresh", "Routing sends"):
        assert needle in joined                                   # nothing lost
    assert split_sections("plain text " * 10) == [("", ("plain text " * 10).strip())]


def test_a_short_section_goes_with_the_next(ctx):
    from supagent.knowledge.index import split_sections

    text = "# Guide\n\n## A\n\nshort.\n\n## B\n\n" + "b words here. " * 30
    parts = split_sections(text)
    assert len(parts) == 1 and "short." in parts[0][1] and "b words" in parts[0][1]
    assert parts[0][0].startswith("Guide")


def test_titles_of_the_pieces(ctx):
    from supagent.knowledge.index import _titled

    assert _titled("Docs › Bulk API", "Bulk API › Endpoints") == "Docs › Bulk API › Endpoints"
    assert _titled("Docs", "") == "Docs"
    assert _titled("Docs", "x" * 900, " (ops)").endswith(" (ops)") and len(_titled("Docs", "x" * 900, " (ops)")) <= 480


def test_a_repository_markdown_page(ctx):
    from supagent.knowledge.docs import repo_page

    text = "---\nlayout: default\ntitle: Bulk\ndescription: \"Many operations in one request\"\nnav_order: 20\n---\n\n# Bulk API\nBody."
    url, title, body = repo_page("https://git/x/bulk.md", "api/bulk.md", text)
    assert title == "Bulk (api/bulk.md)" and body.startswith("Many operations in one request\n\n# Bulk API")
    assert "nav_order" not in body and "layout" not in body
    _u, title, body = repo_page("u", "guide.md", "# Restarting a node\n\nSteps.")
    assert title == "Restarting a node (guide.md)" and body.startswith("# Restarting")
    _u, title, body = repo_page("u", "notes.txt", "---\ntitle: x\n---\nplain")
    assert title == "notes.txt" and body.startswith("---")       # not Markdown: as it is


def test_documents_are_indexed_section_by_section(ctx):
    from superset.extensions import db

    from supagent.knowledge.index import _doc_pieces
    from supagent.models import Doc

    d = Doc(kind="url", title="Ops docs", url="https://git/ops", status="ok", enabled=True,
            content="# Restart\n\n## Before\n\nDrain the node.\n\n## After\n\nCheck the health.",
            pages=None)
    db.session.add(d)
    db.session.flush()
    try:
        mine = [p for p in _doc_pieces() if p["ref"].startswith(f"doc:{d.id}#")]
        assert mine and mine[0]["title"].startswith("Ops docs › Restart")
        assert "Drain the node." in mine[0]["text"] and "Check the health." in "".join(p["text"] for p in mine)
    finally:
        db.session.rollback()


def test_a_search_gives_two_pieces_of_a_page_at_most(ctx):
    from supagent.knowledge.search import capped, page_of

    found = [{"ref": f"doc:1#{i}", "text": f"Source: https://x/a.md\npart {i}"} for i in range(4)] + \
            [{"ref": "doc:1#9", "text": "Source: https://x/b.md\nother page"}, {"ref": "entry:3#0", "text": "a"},
             {"ref": "entry:3#1", "text": "b"}, {"ref": "entry:3#2", "text": "c"}]
    got = [f["ref"] for f in capped(found, 10)]
    assert got == ["doc:1#0", "doc:1#1", "doc:1#9", "entry:3#0", "entry:3#1"]
    assert page_of("doc:1#4", "Source: https://x/a.md\n...") == "doc:1 https://x/a.md"
    assert page_of("context:5#2", "Source: no") == "context:5"


def test_the_agent_reads_the_part_of_a_piece_its_words_are_in(ctx):
    from supagent.knowledge.search import excerpt

    text = "Source: https://x/bulk.md\n" + "Intro sentence about nothing. " * 60 + \
        "\nThe refresh parameter makes the changes visible to search. " + "Closing words here. " * 40
    got = excerpt(text, "refresh parameter", 400)
    assert got.startswith("Source: https://x/bulk.md\n") and "refresh parameter" in got and len(got) <= 420
    assert "…" in got
    assert excerpt("short text", "anything", 400) == "short text"


def test_web_and_confluence_headings_stay_headings(ctx):
    from supagent.knowledge.docs import html_to_text, storage_to_text
    from supagent.knowledge.index import split_sections

    title, text, _links = html_to_text("<html><head><title>Runbook</title></head><body><nav><h2>Menu</h2></nav>"
                                        "<h1>Restart</h1><p>Plan it.</p><h2>Before</h2><p>Drain the <b>node</b>.</p>"
                                        "</body></html>")
    assert title == "Runbook" and text == "# Restart\nPlan it.\n## Before\nDrain the node."
    assert [w for w, _t in split_sections(text)] == ["Restart"]          # short sections go together
    assert storage_to_text("<h3>Rollback</h3><p>Steps</p>") == "### Rollback\nSteps"


def test_the_terms_of_a_glossary_are_never_capped():
    """(0.9.8) A team's glossary is one entry with a section per term: the cap of two pieces of a page let two terms
    through and left out the one that said which orders are sold."""
    from supagent.knowledge.search import capped

    found = [{"ref": f"entry:9#term-{i}", "kind": "glossary", "text": f"term {i}"} for i in range(4)] + \
        [{"ref": f"doc:1#{i}", "kind": "doc", "text": "Source: https://x/a.md\n..."} for i in range(4)]
    got = [f["ref"] for f in capped(found, 8)]
    assert [r for r in got if r.startswith("entry:9")] == [f"entry:9#term-{i}" for i in range(4)]   # every term
    assert len([r for r in got if r.startswith("doc:1")]) == 2                                      # a page: two
