"""A Context page's change waits for a person (0.9.6): the agent's new version of a page that exists is a proposal
(the page shown stays); the next one replaces it, keeping what it said that the new one does not ("left out"); a page
whose subject is gone is proposed for removal. Approve, or keep the page as it is."""

import pytest

from conftest import login

V1 = "## Overview\n- The billing service sends invoices every night at 02:00.\n- Payments are retried three times."
V2 = "## Overview\n- The billing service sends invoices every night at 03:00.\n- Refunds go through the gateway."
V3 = "## Overview\n- The billing service sends invoices every night at 03:00.\n- Exports run on Sundays only."


@pytest.fixture()
def page(ctx):
    from superset import db

    from supagent import settings
    from supagent.knowledge.context import save_page
    from supagent.models import ContextPage

    settings.set_value("context.review", True)
    db.session.query(ContextPage).filter(ContextPage.slug == "review-test").delete()
    db.session.commit()
    spec = {"section": "technical", "slug": "review-test", "title": "Review test", "sources": [], "database_ids": []}
    assert save_page({**spec, "content": V1}, "summary", "h1") == "written"
    p = db.session.query(ContextPage).filter_by(slug="review-test").one()
    yield spec, p.id
    db.session.query(ContextPage).filter(ContextPage.slug == "review-test").delete()
    db.session.commit()


def test_statements_and_compare(ctx):
    from supagent.knowledge.context import compare, statements

    assert statements("## Head\n- **One** fact here [E1].\n\n- Two facts are here.") == ["one fact here", "two facts are here"]
    c = compare(V1, V2)
    assert "refunds go through the gateway" in c["added"] and "payments are retried three times" in c["dropped"]


def test_a_change_is_proposed_then_replaced_then_approved(page):
    from superset import db

    from supagent.knowledge.context import proposals, review, save_page
    from supagent.models import ContextPage

    spec, pid = page
    assert save_page({**spec, "content": V2}, "summary", "h2") == "proposed"
    p = db.session.get(ContextPage, pid)
    assert p.content == V1 and p.proposed_content == V2                       # the page shown stays
    assert "payments are retried three times" in p.compared["obsolete"]
    assert save_page({**spec, "content": V2}, "summary", "h2") == "unchanged"   # the same proposal again
    assert save_page({**spec, "content": V3}, "summary", "h3") == "proposed"  # the next one replaces it
    p = db.session.get(ContextPage, pid)
    assert p.proposed_content == V3 and p.compared["replaced"] == 1
    assert "refunds go through the gateway" in p.compared["left_out"]          # said before, not now: not lost
    listed = [x for x in proposals() if x["id"] == pid][0]
    assert listed["what"] == "change" and listed["left_out"]
    review(pid, "approve", "editor1")
    p = db.session.get(ContextPage, pid)
    assert p.content == V3 and p.proposed_content is None and p.reviewed_by == "editor1" and p.version == 2


def test_kept_as_it_is_and_the_evidence_coming_back(page):
    from superset import db

    from supagent.knowledge.context import review, save_page
    from supagent.models import ContextPage

    spec, pid = page
    save_page({**spec, "content": V2}, "summary", "h2")
    review(pid, "reject", "editor1")
    p = db.session.get(ContextPage, pid)
    assert p.content == V1 and p.proposed_content is None
    save_page({**spec, "content": V2}, "summary", "h2")
    assert save_page({**spec, "content": V1}, "summary", "h1") == "unchanged"  # back to what the page says
    assert db.session.get(ContextPage, pid).proposed_content is None


def test_a_page_gone_is_proposed_for_removal_and_only_an_admin_removes_it(app):
    from superset import db
    from superset.extensions import security_manager as sm

    from conftest import PASSWORD
    from supagent import settings
    from supagent.cli import ensure_roles
    from supagent.knowledge.context import drop_pages, save_page
    from supagent.models import ContextPage

    with app.app_context():
        settings.set_value("context.review", True)
        db.session.query(ContextPage).filter(ContextPage.slug == "gone-test").delete()
        db.session.commit()
        save_page({"section": "technical", "slug": "gone-test", "title": "Gone test", "sources": [],
                   "database_ids": [], "content": V1}, "summary", "g1")
        keep = {(p.section, p.slug) for p in db.session.query(ContextPage) if p.slug != "gone-test"}
        drop_pages(keep=keep)                                                    # its subject is gone
        pid = db.session.query(ContextPage).filter_by(slug="gone-test").one().id
        assert db.session.get(ContextPage, pid).proposed_drop is True
        ensure_roles()
        if sm.find_user(username="c_editor") is None:
            sm.add_user("c_editor", "c", "editor", "c_editor@example.com", [sm.find_role("AI Editor")],
                        password=PASSWORD)
        db.session.commit()
        db.session.remove()
    with app.test_client() as c:
        login(c, "c_editor")
        assert c.post(f"/supagent/admin/api/context/{pid}/review", json={"action": "approve"}).status_code == 403
    with app.test_client() as c:
        login(c, "admin")
        r = c.post(f"/supagent/admin/api/context/{pid}/review", json={"action": "approve"})
        assert r.status_code == 200 and r.get_json() == {"removed": pid}, (r.status_code, r.get_data(as_text=True)[:300])


def test_a_proposal_edited_before_it_is_approved(page):
    """The person's text is shown; the agent proposes again only with new evidence, and what of the person's text its
    proposal drops is listed (obsolete in the page shown)."""
    from superset import db

    from supagent.knowledge.context import review, save_page
    from supagent.models import ContextPage

    spec, pid = page
    save_page({**spec, "content": V2}, "summary", "h2")
    mine = V2 + "\n- The finance team checks the refunds every Monday."
    out = review(pid, "approve", "editor2", content=mine)
    p = db.session.get(ContextPage, pid)
    assert out["edited"] and p.content == mine.strip() and p.edited_by == "editor2" and p.proposed_content is None
    assert save_page({**spec, "content": V2}, "summary", "h2") == "unchanged"     # the same evidence: nothing
    assert save_page({**spec, "content": V3}, "summary", "h3") == "proposed"
    p = db.session.get(ContextPage, pid)
    assert "the finance team checks the refunds every monday" in p.compared["obsolete"]
    out = review(pid, "approve", "editor2")                                       # approved as proposed
    assert not out["edited"] and db.session.get(ContextPage, pid).edited_by is None


def test_the_two_versions_line_by_line_and_word_by_word(ctx):
    """The side-by-side view of To review (the user's request: the old version and what changed, red and green)."""
    from supagent.knowledge.context import diff_rows

    rows = diff_rows("## Billing\n- Invoices at 02:00 by the batch.\n- Payments are retried three times.\n- Same.",
                     "## Billing\n- Invoices at 03:00 by the new batch.\n- Refunds go through the gateway.\n- Same.\n- Added.")
    ops = [r["op"] for r in rows]
    assert ops == ["same", "mod", "del", "add", "same", "add"]
    mod = rows[1]
    assert ["del", "02:00"] in mod["old_parts"] and ["ins", "03:00"] in mod["new_parts"] and ["ins", "new "] in mod["new_parts"]
    assert rows[2]["old"].startswith("- Payments") and rows[2]["n"] is None      # rewritten: removed whole, then added
    assert rows[5] == {"op": "add", "o": None, "n": 5, "old": None, "new": "- Added."}
    assert all(r["op"] == "add" for r in diff_rows("", "a\nb"))                  # a new page: all added
    assert all(r["op"] == "del" for r in diff_rows("a\nb", ""))                  # a removal: all removed


def test_the_changes_of_an_edited_text(app):
    from superset import db

    from supagent.knowledge.context import save_page
    from supagent.models import ContextPage

    with app.app_context():
        db.session.query(ContextPage).filter(ContextPage.slug == "diff-api-test").delete()
        db.session.commit()
        save_page({"section": "technical", "slug": "diff-api-test", "title": "Diff API test", "sources": [],
                   "database_ids": [], "content": "- one\n- two"}, "summary", "x1")
        pid = db.session.query(ContextPage).filter_by(slug="diff-api-test").one().id
        db.session.remove()
    with app.test_client() as c:
        login(c, "admin")
        r = c.post(f"/supagent/admin/api/context/{pid}/diff", json={"content": "- one\n- two and three"})
        assert r.status_code == 200 and [x["op"] for x in r.get_json()["diff"]] == ["same", "mod"]
        assert c.post(f"/supagent/admin/api/context/{pid}/diff", json={}).status_code == 400
    with app.app_context():                     # (the other tests count the pages)
        db.session.query(ContextPage).filter(ContextPage.slug == "diff-api-test").delete()
        db.session.commit()
        db.session.remove()
