"""(0.11.8.3) A removed wiki page is left unfetched only when its removal keeps every one of its links: a hub page
with more links than are kept (200) is fetched as before, so the pages behind its later links are still read (one
link into many spaces); a removal kept by 0.11.8.2 (its links, without saying whether they were cut) is fetched once
more and kept again; the list of a document's pages sends the removals without the links they keep."""
from __future__ import annotations

import test_confluence_removed_01182 as M
from test_confluence_removed_01182 import _titles, wiki  # noqa: F401  (the fixture)


def _doc(w, max_pages: int = 300):
    from superset.extensions import db

    from supagent.models import Doc

    d = Doc(kind="url", url=f"{w.base}/wiki/spaces/OPS/pages/1/Home", reader="confluence", max_pages=max_pages)
    db.session.add(d)
    db.session.commit()
    return d


def _hub(monkeypatch) -> None:
    """Hub (page 2) links to 249 pages that are gone, then (the 250th link) to Far: the only way to Far."""
    hub = "".join(f'<p><ac:link><ri:page ri:content-title="Gone {i:03d}" /></ac:link></p>' for i in range(249))
    hub += '<p><ac:link><ri:page ri:space-key="FAR" ri:content-title="Far" /></ac:link></p>'
    monkeypatch.setitem(M.BODY, "2", "<p>Hub of the old pages.</p>" + hub)


def test_a_removed_hub_whose_last_link_is_the_only_way_to_a_page_still_leads_to_it(wiki, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import docs as D

    _hub(monkeypatch)
    w = wiki()
    d = _doc(w)
    D.refresh(d)
    assert "Far" in _titles(d)
    D.exclude_page(d, "admin", page_id="2")
    db.session.commit()
    D.refresh(d)
    assert "Far" in _titles(d) and "Hub" not in _titles(d)


def test_a_page_with_more_links_than_kept_says_so_and_its_removal_is_fetched_as_before(wiki, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import docs as D

    _hub(monkeypatch)
    w = wiki()
    d = _doc(w)
    D.refresh(d)
    meta = next(p for p in d.pages if p["title"] == "Hub")
    assert meta.get("links_more") is True and len(meta["links"]) == D.LINKS_KEPT
    assert not any(p.get("links_more") for p in d.pages if p["title"] != "Hub")
    D.exclude_page(d, "admin", page_id="2")
    db.session.commit()
    gone = D.excluded_pages(d)[0]
    assert gone.get("links_more") is True and not D.links_whole(gone)
    w.got.clear()
    D.refresh(d)
    assert w.fetched("2") == 1 and "Hub" not in _titles(d)


def test_a_page_linking_one_page_many_times_keeps_it_once(wiki, monkeypatch):
    from supagent.knowledge import docs as D

    monkeypatch.setitem(M.BODY, "2", "<p>Hub.</p>" + '<p><ac:link><ri:page ri:space-key="FAR" ri:content-title="Far"'
                        ' /></ac:link></p>' * 250)
    w = wiki()
    d = _doc(w)
    D.refresh(d)
    meta = next(p for p in d.pages if p["title"] == "Hub")
    assert meta["links"] == ["5"] and "links_more" not in meta


def test_a_removal_kept_by_0_11_8_2_is_fetched_once_more_and_kept_again(wiki):
    from superset.extensions import db

    from supagent.knowledge import docs as D

    w = wiki()
    d = _doc(w)
    D.refresh(d)
    d.auth = {"excluded": [{"key": "id:2", "url": f"{w.base}/wiki/spaces/OPS/pages/2/Hub", "title": "Hub",
                            "by": "admin", "at": "2026-10-22T18:00:00", "links": ["5"], "space": "OPS"}]}
    db.session.commit()
    w.got.clear()
    D.refresh(d)
    assert w.fetched("2") == 1 and _titles(d) == ["Far", "Home", "Ops", "Ops child"]
    gone = D.excluded_pages(d)[0]
    assert gone.get("links_v") == D.LINKS_V and D.links_whole(gone)
    w.got.clear()
    D.refresh(d)
    assert w.fetched("2") == 0 and _titles(d) == ["Far", "Home", "Ops", "Ops child"]


def test_a_removal_made_after_a_reading_of_this_version_is_never_fetched(wiki):
    from superset.extensions import db

    from supagent.knowledge import docs as D

    w = wiki()
    d = _doc(w)
    D.refresh(d)
    assert D.read_log(d.id).get("links_v") == D.LINKS_V
    D.exclude_page(d, "admin", page_id="2")
    db.session.commit()
    assert D.links_whole(D.excluded_pages(d)[0])
    w.got.clear()
    D.refresh(d)
    assert w.fetched("2") == 0 and _titles(d) == ["Far", "Home", "Ops", "Ops child"]


def test_the_pages_list_sends_the_removals_without_the_links_they_keep(app):
    from superset.extensions import db

    from conftest import login
    from supagent.models import Doc

    entry = {"key": "id:9", "url": "https://wiki.example.com/x/9", "title": "Old", "by": "admin", "at": "2026-10-22"}
    with app.app_context():
        d = Doc(kind="url", url="https://wiki.example.com/x", max_pages=10, pages=[],
                auth={"excluded": [{**entry, "links": [str(i) for i in range(200)], "space": "X", "links_v": 2}]})
        db.session.add(d)
        db.session.commit()
        doc_id = d.id
        db.session.remove()
    try:
        c = app.test_client()
        login(c, "admin")
        assert c.get(f"/supagent/admin/api/docs/{doc_id}/pages").get_json()["excluded"] == [entry]
    finally:
        with app.app_context():
            db.session.delete(db.session.get(Doc, doc_id))
            db.session.commit()
            db.session.remove()
