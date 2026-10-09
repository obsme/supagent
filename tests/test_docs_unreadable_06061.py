"""(0.10.6.1) A wiki document failed whole ("…/rest/api/content: HTTP 404: not found, or not visible to this
document's sign-in", 0 pages) when one page it leads to could not be read. Every page that can be read is read; one
that cannot (404, 403, asked to sign in, not text) is skipped and counted, the crawl goes on through the others and
their links; a page whose title says "deprecated" is not read, nor the pages it leads to; a page with no text is not
kept, the pages under it and its links are followed. The document's first page must be readable (else its error)."""
from __future__ import annotations

from test_docs_readers import HTML, _doc, _html, env, servers  # noqa: F401  (fixtures)

PAGES = {   # id: (title, body, children)
    "100": ("Runbooks", '<p>How the batch runs.</p><ac:link><ri:page ri:space-key="HIDDEN" ri:content-title="Secret page"/>'
                        '</ac:link><ac:link><ri:page ri:content-title="Pools"/></ac:link>', ["101", "102", "103", "104"]),
    "101": ("Restart", "<p>Restart the pool.</p>", []),
    "102": ("Gone", None, []),                                   # listed under 100, its content answers 404
    "103": ("Old runbook (DEPRECATED)", "<p>Do not use.</p>", ["105"]),
    "104": ("Folder", "", ["106"]),                              # no text: the page under it is still read
    "105": ("Under the deprecated one", "<p>Old steps.</p>", []),
    "106": ("Alerts", "<p>The alerts of the batch.</p>", []),
    "107": ("Pools", "<p>The pools and their sizes.</p>", []),
}


def _wiki(prefix: str, start_404: bool = False):
    def item(pid: str) -> dict:
        title, body, _kids = PAGES[pid]
        return {"id": pid, "type": "page", "title": title, "_links": {"webui": f"/display/OPS/{title.replace(' ', '+')}"},
                "body": {"storage": {"value": body or "", "representation": "storage"}}, "version": {"number": 1},
                "space": {"key": "OPS"}}

    def route(path, q, h):
        api = prefix + "/rest/api"
        if not path.startswith(api):
            return 404, {}, {"statusCode": 404}
        rest = path[len(api):]
        if rest.startswith("/content/") and rest.endswith("/child/page"):
            kids = PAGES.get(rest.split("/")[2], (None, None, []))[2]
            return 200, {}, {"results": [{"id": k, "title": PAGES[k][0]} for k in kids], "size": len(kids),
                             "_links": {}}
        if rest.startswith("/content/"):
            pid = rest.split("/")[2]
            if pid not in PAGES or PAGES[pid][1] is None or (start_404 and pid == "100"):
                return 404, {}, {"statusCode": 404}
            return 200, {}, item(pid)
        if rest == "/content" and q.get("title"):
            if q.get("spaceKey") == "HIDDEN":
                return 404, {}, {"statusCode": 404, "message": "No space with key : HIDDEN"}
            found = [k for k, v in PAGES.items() if v[0] == q["title"]]
            return 200, {}, {"results": [item(k) for k in found], "size": len(found), "_links": {}}
        return 404, {}, {"statusCode": 404}

    return route


def test_the_pages_that_can_be_read_are_read(env, servers):
    from supagent.knowledge import docs as D

    s = servers(_wiki("/wiki"))
    d = _doc(f"{s.base}/wiki/pages/viewpage.action?pageId=100", max_pages=20)
    out = D.refresh(d)
    assert out["status"] == "ok", out
    titles = [p["title"] for p in d.pages]
    assert titles[0] == "Runbooks" and {"Restart", "Alerts", "Pools"} <= set(titles), titles
    assert not {"Gone", "Old runbook (DEPRECATED)", "Under the deprecated one", "Folder", "Secret page"} & set(titles)
    assert out["skipped"] >= 4                                   # 404, the hidden space, deprecated, empty
    asked = {r["path"] for r in s.got}
    assert f"/wiki/rest/api/content/105" not in asked            # nothing under a deprecated page is read


def test_the_first_page_must_be_readable(env, servers):
    from supagent.knowledge import docs as D

    s = servers(_wiki("/wiki", start_404=True))
    d = _doc(f"{s.base}/wiki/pages/viewpage.action?pageId=100", max_pages=20)
    D.refresh(d)
    assert d.status == "error" and "HTTP 404" in d.error


def test_a_site_page_that_cannot_be_read_is_skipped(env, servers):
    from supagent.knowledge import docs as D

    pages = {"/docs/": _html("Guide", '<p>Start here.</p><a href="/docs/a.html">a</a> <a href="/docs/missing.html">m</a>'
                                      ' <a href="/docs/old.html">o</a> <a href="/docs/empty.html">e</a>'),
             "/docs/a.html": _html("Install", "<p>How to install.</p>"),
             "/docs/old.html": _html("Deprecated: the old way", '<p>Old.</p><a href="/docs/older.html">x</a>'),
             "/docs/older.html": _html("Older", "<p>Older still.</p>"),
             "/docs/empty.html": _html("Index", '<a href="/docs/b.html"><img src="b.png"></a>'),
             "/docs/b.html": _html("Upgrade", "<p>How to upgrade.</p>")}

    def route(path, q, h):
        return (200, HTML, pages[path]) if path in pages else (404, HTML, "not here")

    s = servers(route)
    d = _doc(f"{s.base}/docs/", max_pages=20)
    out = D.refresh(d)
    assert out["status"] == "ok", out
    titles = [p["title"] for p in d.pages]
    assert titles[0] == "Guide" and {"Install", "Upgrade"} <= set(titles) and \
        not {"Deprecated: the old way", "Older", "Index"} & set(titles), titles
    assert out["skipped"] >= 3                                   # missing, deprecated, empty
    gone = servers(lambda path, q, h: (404, HTML, "not here"))
    bad = _doc(f"{gone.base}/docs/", max_pages=5)
    D.refresh(bad)
    assert bad.status == "error"


def test_a_seeded_value_removed_stays_removed(ctx):
    """The values seeded at the start (the catalog's categories) can be removed (status rejected) and the learning's
    seeding never brings one back."""
    from superset.extensions import db

    from supagent.knowledge.facets import seed
    from supagent.models import Entry, Facet

    e = Entry(title="A guide for the hotfix test", classification="guide", fmt="text", content="text",
              category="zz-hotfix-subject")
    db.session.add(e)
    db.session.commit()
    try:
        seed()
        f = db.session.query(Facet).filter(Facet.facet == "subject", Facet.value == "zz-hotfix-subject").one()
        assert f.source == "seed" and f.status == "approved"
        f.status = "rejected"
        db.session.commit()
        seed()
        assert db.session.get(Facet, f.id).status == "rejected"
    finally:
        db.session.query(Facet).filter(Facet.value == "zz-hotfix-subject").delete(synchronize_session=False)
        db.session.delete(db.session.get(Entry, e.id))
        db.session.commit()
