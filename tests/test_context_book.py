"""The Context as a book (0.9.6, the user's request): sections and pages related to each other, downloaded as a PDF
like a book with a summary and a table of contents. Parts (functional, technical), chapters by the kind of page,
numbers across the book, a summary of every page in a line, the related pages of each page."""

import io
import types
import zipfile


def page(pid, section, slug, title, content, refs=(), dbs=()):
    return types.SimpleNamespace(id=pid, section=section, slug=slug, title=title, content=content,
                                 sources=[{"ref": r, "title": r} for r in refs], database_ids=list(dbs))


PAGES = [
    page(1, "functional", "overview", "How the system works", "The shop sells online. Orders go to billing.",
         refs=("doc:1", "doc:2")),
    page(2, "functional", "application-billing", "Application BILLING", "BILLING sends the invoices every night.",
         refs=("doc:2",), dbs=(3,)),
    page(3, "functional", "glossary", "Glossary", "- **COB**: close of business."),
    page(4, "technical", "architecture", "Technical overview", "BILLING reads the orders database.", refs=("doc:1",)),
    page(5, "technical", "data-sources-orders", "Data source: Orders (osagg)", "The orders index.", dbs=(3,)),
    page(6, "technical", "inventory-orders", "Inventory: Orders (osagg)", "Servers of the orders.", dbs=(3,)),
    page(7, "technical", "something-else", "A page of no chapter", "Other."),
]


def test_parts_chapters_numbers_summary(ctx):
    from supagent.knowledge.context import book, lead

    b = book(PAGES)
    titles = [(part["title"], [(c["number"], c["title"], [e["number"] for e in c["pages"]]) for c in part["chapters"]])
              for part in b["parts"]]
    assert titles == [("Functional", [("1", "Overview", ["1.1"]), ("2", "Applications", ["2.1"]),
                                      ("3", "Glossary, rules and facts", ["3.1"])]),
                      ("Technical", [("4", "Architecture", ["4.1"]), ("5", "Data sources", ["5.1"]),
                                     ("6", "Inventories", ["6.1"]), ("7", "Other pages", ["7.1"])])]
    assert b["numbers"][2] == "2.1" and b["numbers"][7] == "7.1"
    assert "2.1 Application BILLING: BILLING sends the invoices every night." in b["summary"]
    assert lead("## Head\n\n- **One** [E1] thing here. And more.") == "One thing here."


def test_related_pages(ctx):
    from supagent.knowledge.context import book

    rel = book(PAGES)["related"]
    assert rel[2][0] in (5, 6, 1, 4)                       # its database's pages, the pages naming it
    assert 4 in rel[2] and 1 in rel[2]                     # the architecture names BILLING; the overview shares a source
    assert 5 in rel[6] and 6 in rel[5]                     # the same database
    assert 3 not in rel[2] and rel[3] == []                # the glossary shares nothing


def test_the_book_exported(app):
    from superset.extensions import db

    from conftest import login
    from supagent.models import ContextPage

    with app.app_context():
        made = [ContextPage(section="functional", slug="overview", title="How the system works", kind="summary",
                            content="The shop sells online. BILLING sends the invoices.", database_ids=[], version=1),
                ContextPage(section="functional", slug="application-billing", title="Application BILLING", kind="summary",
                            content="BILLING sends the invoices every night.", database_ids=[], version=1)]
        db.session.add_all(made)
        db.session.commit()
        ids = [p.id for p in made]
    try:
        with app.test_client() as c:
            login(c, "alice")
            full = c.get("/supagent/dictionary/api/context?full=1").get_json()["pages"]
            mine = {p["title"]: p for p in full}
            assert mine["Application BILLING"]["number"] == "2.1" and mine["How the system works"]["chapter"] == "1 Overview"
            assert ids[0] in mine["Application BILLING"]["related"]
            docx = c.get("/supagent/dictionary/api/context/export.docx")
            body = zipfile.ZipFile(io.BytesIO(docx.data)).read("word/document.xml").decode()
            for text in ("Summary", "This book in short", "Part I - Functional", "1 Overview", "1.1 How the system works",
                         "2.1 Application BILLING", "Related pages:"):
                assert text in body, text
            pdf = c.get("/supagent/dictionary/api/context/export.pdf")
            assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF") and b"/Outlines" in pdf.data
    finally:
        with app.app_context():
            db.session.query(ContextPage).filter(ContextPage.id.in_(ids)).delete(synchronize_session=False)
            db.session.commit()
