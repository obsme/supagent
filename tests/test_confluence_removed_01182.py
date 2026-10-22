"""(0.11.8.2) A wiki with many pages removed (the owner: "2k removed, 3k active ... the reading takes so much time"): a
removed Confluence page is not fetched again once its links are kept with its removal (the pages under it and the
pages it links to are still read); a page removed before 0.11.8.2 is fetched once more, its links kept then; a link
by the title of a page already met costs no request; a document deleted while it is read stops its reading, said,
without an error."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
import sqlalchemy as sa

TITLES = {"1": ("Home", "OPS"), "2": ("Hub", "OPS"), "3": ("Ops", "OPS"), "4": ("Ops child", "OPS"),
          "5": ("Far", "FAR")}
CHILDREN = {"1": ["2", "3"], "3": ["4"]}
BODY = {"1": '<p>Home of the team.</p><p><ac:link><ri:page ri:content-title="Hub" /></ac:link></p>',
        "2": '<p>Hub of the old pages.</p><p><ac:link><ri:page ri:space-key="FAR" ri:content-title="Far" />'
             "</ac:link></p>",
        "3": "<p>The Ops page.</p>", "4": "<p>The page under Ops.</p>", "5": "<p>Far, linked from the Hub only.</p>"}


class Wiki:
    """A Confluence REST API (/wiki/rest/api/content): the pages above, what was asked kept; `on_page(id)` called
    when a page is fetched by its id."""

    def __init__(self, on_page=None) -> None:
        self.got: list[tuple[str, dict]] = []
        self.on_page = on_page
        wiki = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                u = urlparse(self.path)
                q = {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
                wiki.got.append((u.path, q))
                status, body = wiki.route(u.path, q)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def page(self, pid: str, body: bool = True) -> dict:
        title, space = TITLES[pid]
        item = {"id": pid, "type": "page", "title": title, "status": "current",
                "_links": {"webui": f"/spaces/{space}/pages/{pid}/{title.replace(' ', '+')}",
                           "base": self.base + "/wiki"}}
        if body:
            item.update(body={"storage": {"value": BODY[pid], "representation": "storage"}}, version={"number": 1},
                        space={"key": space})
        return item

    def route(self, path: str, q: dict) -> tuple[int, dict]:
        api = "/wiki/rest/api/content"
        if path == api and q.get("title"):
            found = [k for k, (t, s) in TITLES.items() if t == q["title"] and s == q.get("spaceKey")]
            return 200, {"results": [self.page(k) for k in found], "_links": {"base": self.base + "/wiki"}}
        rest = path[len(api) + 1:].split("/") if path.startswith(api + "/") else []
        if not rest or rest[0] not in TITLES:
            return 404, {"statusCode": 404}
        if rest[1:] == ["child", "page"]:
            return 200, {"results": [self.page(k, body=False) for k in CHILDREN.get(rest[0], [])],
                         "_links": {"base": self.base + "/wiki"}}
        if len(rest) == 1:
            if self.on_page is not None:
                self.on_page(rest[0])
            return 200, self.page(rest[0])
        return 404, {"statusCode": 404}

    def fetched(self, pid: str) -> int:
        return sum(1 for p, _q in self.got if p == f"/wiki/rest/api/content/{pid}")

    def by_title(self, title: str) -> int:
        return sum(1 for p, q in self.got if p == "/wiki/rest/api/content" and q.get("title") == title)

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def wiki(ctx, monkeypatch):
    from superset.extensions import db

    from supagent import settings
    from supagent.models import Chunk, Doc

    over = {"docs.allowed_domains": ["127.0.0.1"]}
    real_get = settings.get
    monkeypatch.setattr(settings, "get", lambda k: over[k] if k in over else real_get(k))
    before = {i for (i,) in db.session.query(Doc.id)}
    made: list[Wiki] = []

    def make(on_page=None) -> Wiki:
        made.append(Wiki(on_page))
        return made[-1]

    yield make
    for w in made:
        w.close()
    db.session.rollback()
    for d in db.session.query(Doc).filter(Doc.id.notin_(before or {-1})):
        db.session.query(Chunk).filter(Chunk.ref.like(f"doc:{d.id}#%")).delete(synchronize_session=False)
        db.session.delete(d)
    db.session.commit()


def _doc(w: Wiki):
    from superset.extensions import db

    from supagent.models import Doc

    d = Doc(kind="url", url=f"{w.base}/wiki/spaces/OPS/pages/1/Home", reader="confluence", max_pages=50)
    db.session.add(d)
    db.session.commit()
    return d


def _titles(d) -> list[str]:
    return sorted(p["title"] for p in d.pages or [])


def test_a_link_by_the_title_of_a_page_met_costs_no_request(wiki):
    from supagent.knowledge import docs as D

    w = wiki()
    d = _doc(w)
    out = D.refresh(d)
    assert out["status"] == "ok" and _titles(d) == ["Far", "Home", "Hub", "Ops", "Ops child"], out
    assert w.by_title("Hub") == 0 and w.fetched("2") == 1    # listed under Home, then fetched by its id only
    assert w.by_title("Far") == 1                            # met through its link alone: asked by its title


def test_a_removed_page_is_not_fetched_again_and_the_pages_it_leads_to_are_still_read(wiki):
    from superset.extensions import db

    from supagent.knowledge import docs as D

    w = wiki()
    d = _doc(w)
    D.refresh(d)
    D.exclude_page(d, "admin", page_id="2")
    db.session.commit()
    gone = D.excluded_pages(d)[0]
    assert gone["space"] == "OPS" and gone["links"] == ["5"]     # its link to Far, as the id it turned out to be
    w.got.clear()
    out = D.refresh(d)
    assert out["status"] == "ok" and _titles(d) == ["Far", "Home", "Ops", "Ops child"], out
    assert w.fetched("2") == 0                                   # not fetched again
    assert ("/wiki/rest/api/content/2/child/page", {"limit": str(D.CHILDREN_LIST), "start": "0"}) in w.got
    why = [k["why"] for k in D.read_log(d.id)["skipped"] if k["title"] == "Hub"]
    assert why and why[0].startswith("removed by a person")


def test_a_page_removed_before_keeps_its_links_at_its_next_reading(wiki):
    from superset.extensions import db

    from supagent.knowledge import docs as D

    w = wiki()
    d = _doc(w)
    D.refresh(d)
    d.auth = {"excluded": [{"key": "id:2", "url": f"{w.base}/wiki/spaces/OPS/pages/2/Hub", "title": "Hub",
                            "by": "admin", "at": "2026-10-01T00:00:00"}]}     # as 0.11.8.1 kept it: no links
    db.session.commit()
    w.got.clear()
    D.refresh(d)
    assert w.fetched("2") == 1 and _titles(d) == ["Far", "Home", "Ops", "Ops child"]   # read once more, not kept
    gone = D.excluded_pages(d)[0]
    assert gone["links"] == ["5"] and gone["space"] == "OPS" and gone["by"] == "admin"
    w.got.clear()
    D.refresh(d)
    assert w.fetched("2") == 0 and _titles(d) == ["Far", "Home", "Ops", "Ops child"]


def test_a_document_deleted_while_it_is_read_stops_its_reading(wiki, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import docs as D
    from supagent.models import Doc

    monkeypatch.setattr(D, "WATCH_SECONDS", 0)
    engine, holder = db.engine, {}

    def delete_it(pid: str) -> None:              # a person deletes the wiki while its page 3 is read
        if pid == "3" and "id" in holder:
            with engine.begin() as con:
                con.execute(sa.text("DELETE FROM supagent_doc WHERE id = :i"), {"i": holder["id"]})

    w = wiki(delete_it)
    d = _doc(w)
    holder["id"] = d.id
    out = D.refresh(d)
    assert out["status"] == "deleted" and out["error"] is None and out["id"] == holder["id"], out
    assert w.fetched("4") == 0                                    # stopped: the pages after it not fetched
    assert db.session.query(Doc).filter(Doc.id == holder["id"]).count() == 0


def test_a_document_deleted_at_the_end_of_its_reading_is_not_saved_without_an_error(wiki):
    from superset.extensions import db

    from supagent.knowledge import docs as D
    from supagent.models import Doc

    engine, holder = db.engine, {}

    def delete_it(pid: str) -> None:              # deleted while its last page is read (the watch not yet due)
        if pid == "4" and "id" in holder:
            with engine.begin() as con:
                con.execute(sa.text("DELETE FROM supagent_doc WHERE id = :i"), {"i": holder["id"]})

    w = wiki(delete_it)
    d = _doc(w)
    holder["id"] = d.id
    out = D.refresh(d)
    assert out["status"] == "deleted" and out["error"] is None, out
    assert db.session.query(Doc).filter(Doc.id == holder["id"]).count() == 0
