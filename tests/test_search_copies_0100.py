"""(0.10.0) A page several documents read (0.10's crawl follows links across a wiki's spaces: each space's document
held every page) came back once per document: a search's first six were two pages three times. Its section is kept
once, and the cap of pieces per page counts the page whatever document read it."""

from __future__ import annotations


def _piece(doc: int, page: str, section: int, url: str, text: str = "x") -> dict:
    return {"ref": f"doc:{doc}#{page}-{section}", "kind": "doc", "text": f"Source: {url}\n{text}"}


def test_the_same_page_read_by_three_documents_comes_once(app):
    from supagent.knowledge.search import capped

    u1, u2, u3 = "https://wiki/p/1", "https://wiki/p/2", "https://wiki/p/3"
    found = [_piece(1, "aa", 0, u1), _piece(2, "aa", 0, u1), _piece(3, "aa", 0, u1),
             _piece(1, "bb", 0, u2), _piece(2, "bb", 0, u2), _piece(3, "bb", 0, u2),
             _piece(1, "aa", 1, u1), _piece(2, "aa", 2, u1), _piece(1, "cc", 0, u3)]
    with app.app_context():
        got = [(f["ref"].split("#")[1], f["text"].split("\n")[0]) for f in capped(found, 6)]
    assert got == [("aa-0", f"Source: {u1}"), ("bb-0", f"Source: {u2}"), ("aa-1", f"Source: {u1}"),
                   ("cc-0", f"Source: {u3}")]               # u1's third section: over the cap of its page


def test_pieces_without_an_address_and_other_kinds_are_as_before(app):
    from supagent.knowledge.search import capped

    found = [{"ref": "doc:4#0", "kind": "doc", "text": "an uploaded document"},
             {"ref": "doc:5#0", "kind": "doc", "text": "another uploaded document"},
             {"ref": "entry:7#0", "kind": "glossary", "text": "a term"},
             {"ref": "entry:7#1", "kind": "glossary", "text": "another term"},
             {"ref": "entry:7#2", "kind": "glossary", "text": "a third term"}]
    with app.app_context():
        refs = [f["ref"] for f in capped(found, 6)]
    assert refs == ["doc:4#0", "doc:5#0", "entry:7#0", "entry:7#1", "entry:7#2"]
