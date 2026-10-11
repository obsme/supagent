"""(0.10.7, a user's wiki) "the wiki documents ... sometimes does not read the full url inside the wiki": the pages a
wiki page links to by a full address were left out when the address was another name of the same wiki (the site's
own URL, as its API says it, while the document reads it through another address), the same wiki over http or with
its port written, a short link (…/x/AbCd), a link by title in viewpage.action, or a link of the storage format by
address (ri:url) or by the page's id (ri:content-entity); and a link's full address was lost from the text when its
words did not say it. What a reading leaves out (and the limit of pages reached) is kept for the list of pages."""
from __future__ import annotations

import base64

import pytest
from test_docs_readers import HTML, SECRET, _doc, _html, env, servers  # noqa: F401  (fixtures and helpers)


def tiny(pid: int) -> str:
    """Confluence's short link of a page id: its 8 bytes little-endian in base64, '/' '+' as '-' '_', no padding."""
    code = base64.b64encode(int(pid).to_bytes(8, "little")).decode().rstrip("=").rstrip("A")
    return code.replace("/", "-").replace("+", "_")


def test_a_short_link_names_its_page(app):
    from supagent.knowledge.docs import tiny_page_id

    assert tiny(65540) == "BAAB" and tiny_page_id("BAAB") == "65540"
    for pid in (1, 98307, 123456789, 2 ** 40 + 7):
        assert tiny_page_id(tiny(pid)) == str(pid)
    assert tiny_page_id("not*base64") is None


@pytest.mark.parametrize("href,web,bases,want", [
    ("http://wiki.example.com/confluence/display/OPS/Page+A", "https://wiki.example.com/confluence", (),
     ("title", "Page A", "OPS")),                                                    # http: the same wiki
    ("https://wiki.example.com:443/display/OPS/Page+A", "https://wiki.example.com", (), ("title", "Page A", "OPS")),
    ("https://wiki.example.com/spaces/OPS/pages/123/X", "http://10.0.0.5:8090", ("https://wiki.example.com",),
     ("id", "123")),                                                                 # the site's own URL (API base)
    ("https://other.example.com/display/OPS/Page+A", "https://wiki.example.com", (), None),
    ("https://wiki.example.com/x/BAAB", "https://wiki.example.com", (), ("id", "65540")),
    ("https://wiki.example.com/confluence/x/BAAB", "https://wiki.example.com/confluence", (), ("id", "65540")),
    ("https://wiki.example.com/display/x/Title", "https://wiki.example.com", (), ("title", "Title", "x")),   # no short link
    ("/pages/viewpage.action?spaceKey=OPS&title=Page+C", "https://wiki.example.com", (), ("title", "Page C", "OPS")),
    ("/pages/viewpage.action?pageId=77&src=contextnavpagetreemode", "https://wiki.example.com", (), ("id", "77")),
])
def test_every_way_a_page_names_another_page_of_its_wiki(app, href, web, bases, want):
    from supagent.knowledge.docs import _href_target

    assert _href_target(href, web + "/display/OPS/Home", web, bases) == want


def test_the_storage_links_by_address_and_by_id_and_the_addresses_said(app):
    from supagent.knowledge.docs import html_to_text, read_storage

    got = read_storage('<p>See <ac:link><ri:url ri:value="https://wiki.example.com/display/OPS/Restart"/>'
                       '<ac:plain-text-link-body><![CDATA[the restart page]]></ac:plain-text-link-body></ac:link>, '
                       '<ac:link><ri:content-entity ri:content-id="4711"/></ac:link> and '
                       '<a href="https://grafana.example.com/d/abc">the dashboard</a> or '
                       '<a href="https://status.example.com">https://status.example.com</a>.</p>')
    assert "https://wiki.example.com/display/OPS/Restart" in got["links"] and got["ids"] == ["4711"]
    assert "the restart page (https://wiki.example.com/display/OPS/Restart)" in got["text"]
    assert "the dashboard (https://grafana.example.com/d/abc)" in got["text"]
    assert got["text"].count("https://status.example.com") == 1                     # its words say it: once
    _title, text, _links = html_to_text('<p><a href="/docs/a.html">a page</a> and <a href="mailto:x@example.com">mail</a></p>')
    assert text == "a page and mail"                                                   # a relative link: its words


def _wiki(prefix: str, holder: dict):
    """A Confluence whose API gives its own URL as another name (holder["alias"]), and pages that link to each
    other in every way: 100 links to 101 (by the alias, over the alias's https), 102 (a short link), 103 (by title in
    viewpage.action), 104 (by id in the storage format), 105 (ri:url); 106 is a link to a page that does not exist."""
    titles = {"100": "Home", "101": "Restart", "102": "Pools", "103": "Page C", "104": "Alerts", "105": "Old runs"}

    def body(pid: str) -> str:
        if pid != "100":
            return f"<p>The page {titles[pid]}.</p>"
        alias = holder["alias"]
        return (f'<p>Start here.</p><a href="{alias}/display/OPS/Restart">restart</a> '
                f'<a href="{holder["base"]}{prefix}/x/{tiny(102)}">pools</a> '
                f'<a href="{prefix}/pages/viewpage.action?spaceKey=OPS&amp;title=Page+C">c</a> '
                '<ac:link><ri:content-entity ri:content-id="104"/></ac:link> '
                f'<ac:link><ri:url ri:value="{alias}/display/OPS/Old+runs"/></ac:link> '
                f'<a href="{holder["base"]}{prefix}/spaces/OPS/pages/106/Gone">gone</a>')

    def page(pid: str) -> dict:
        return {"id": pid, "type": "page", "title": titles[pid], "space": {"key": "OPS"}, "version": {"number": 1},
                "body": {"storage": {"value": body(pid), "representation": "storage"}},
                "_links": {"webui": f"/display/OPS/{titles[pid].replace(' ', '+')}", "base": holder["alias"]}}

    def route(path, q, h):
        if h.get("authorization") != f"Bearer {SECRET}":
            return 401, {}, {"statusCode": 401}
        api = prefix + "/rest/api"
        rest = path[len(api):] if path.startswith(api) else ""
        if rest.endswith("/child/page"):
            return 200, {}, {"results": [], "size": 0, "_links": {"base": holder["alias"]}}
        if rest.startswith("/content/"):
            pid = rest.split("/")[2]
            return (200, {}, page(pid)) if pid in titles else (404, {}, {"statusCode": 404})
        if rest == "/content" and q.get("title"):
            found = [k for k, v in titles.items() if v == q["title"] and q.get("spaceKey") == "OPS"]
            return 200, {}, {"results": [page(k) for k in found], "size": len(found), "_links": {"base": holder["alias"]}}
        return 404, {}, {"statusCode": 404}

    return route


def test_a_wiki_read_to_every_page_its_links_name_and_what_was_not_read(env, servers, app):  # noqa: F811
    from test_dictionary_080 import _client

    from supagent.knowledge import docs as D

    holder: dict = {"alias": "https://wiki.example.test/confluence"}
    s = servers(_wiki("/confluence", holder))
    holder["base"] = s.base
    d = _doc(f"{s.base}/confluence/pages/viewpage.action?pageId=100", max_pages=20, auth={"type": "bearer"},
             secret=SECRET)
    out = D.refresh(d)
    assert out["status"] == "ok", out
    assert sorted(p["title"] for p in d.pages) == ["Alerts", "Home", "Old runs", "Page C", "Pools", "Restart"]
    log = D.read_log(d.id)
    assert log["read"] == 6 and not log["limit_reached"] and log["not_read"] == 1
    assert log["skipped"][0]["url"] == "page 106" and log["skipped"][0]["why"].startswith("not read")
    with _client(app, "admin") as c:
        got = c.get(f"/supagent/admin/api/docs/{d.id}/pages").get_json()
        assert len(got["pages"]) == 6 and got["last_reading"]["not_read"] == 1
        listed = next(x for x in c.get("/supagent/admin/api/docs").get_json()["docs"] if x["id"] == d.id)
        assert listed["read"] == {"not_read": 1, "left": 0, "limit_reached": False}
    few = _doc(f"{s.base}/confluence/pages/viewpage.action?pageId=100", max_pages=2, auth={"type": "bearer"},
               secret=SECRET)
    D.refresh(few)
    log = D.read_log(few.id)
    assert log["limit_reached"] and log["left"] >= 3 and log["max_pages"] == 2      # the limit said, with what is left


def test_a_site_read_over_its_links_written_another_way(env, servers):  # noqa: F811
    from supagent.knowledge import docs as D

    pages = {"/docs/index.html": _html("Index", '<a href="HTTP://127.0.0.1:{port}/docs/a.html">A</a> '
                                                 '<a href="b.html#part">B</a> <a href="/other/c.html">C</a> '
                                                 '<a href="d.html">D</a>'),
             "/docs/a.html": _html("A", "<p>page a</p>"), "/docs/b.html": _html("B", "<p>page b</p>"),
             "/docs/d.html": _html("D", "<p>page d</p>"), "/other/c.html": _html("C", "<p>page c</p>")}
    port: dict = {}

    def route(path, q, h):
        if path not in pages:
            return 404, {}, "no"
        return 200, HTML, pages[path].replace("{port}", str(port["p"]))

    s = servers(route)
    port["p"] = s.server.server_address[1]
    d = _doc(f"{s.base}/docs/index.html", max_pages=10)
    assert D.refresh(d)["status"] == "ok"
    assert [p["title"] for p in d.pages] == ["Index", "A", "B", "D"]                # C: outside the folder
    assert all(p["url"].startswith(s.base) for p in d.pages)                         # one way of writing the site
    two = _doc(f"{s.base}/docs/index.html", max_pages=2)
    D.refresh(two)
    log = D.read_log(two.id)
    assert log["limit_reached"] and log["left"] == 2
