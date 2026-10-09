"""(0.10) A wiki read to the last page its links lead to (by title, in its space or another one, by their address on
the same site; never another site), each page keeping the pages it links to, its images' text and its diagrams'
arrows; the diagrams read from their source (draw.io compressed or not, Gliffy, Mermaid, PlantUML), an XML that
declares a DOCTYPE never read; every page's secrets masked."""

from __future__ import annotations

import base64
import json
import urllib.parse
import zlib

import pytest

from test_docs_readers import _doc, env, servers  # noqa: F401  (the fixtures)


def _drawio(cells: list[tuple[str, str]], edges: list[tuple[str, str, str]], compressed: bool = True) -> str:
    xml = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    xml += [f'<mxCell id="{i}" value="{v}" vertex="1" parent="1"/>' for i, v in cells]
    xml += [f'<mxCell id="e{k}" value="{lab}" edge="1" parent="1" source="{a}" target="{b}"/>'
            for k, (a, b, lab) in enumerate(edges)]
    model = f'<mxGraphModel><root>{"".join(xml)}</root></mxGraphModel>'
    if not compressed:
        return f'<mxfile><diagram name="p">{model}</diagram></mxfile>'
    z = zlib.compressobj(9, zlib.DEFLATED, -15)
    packed = z.compress(urllib.parse.quote(model, safe="").encode()) + z.flush()
    return f'<mxfile><diagram name="p">{base64.b64encode(packed).decode()}</diagram></mxfile>'


def test_the_diagrams_are_read_from_their_source(ctx):
    from supagent.knowledge import diagrams as G

    cells = [("a", "web &lt;b&gt;tier&lt;/b&gt;"), ("b", "api"), ("c", "ledger db"), ("d", "")]
    edges = [("a", "b", "HTTPS"), ("b", "c", "SQL"), ("b", "d", "nothing")]
    for compressed in (True, False):
        d = G.drawio(_drawio(cells, edges, compressed), "overview")
        assert d["edges"] == [["web tier", "api", "HTTPS"], ["api", "ledger db", "SQL"]]   # (an empty box: none)
        assert d["text"] == "draw.io diagram overview: web tier -> api (HTTPS); api -> ledger db (SQL)."
    with pytest.raises(ValueError, match="DOCTYPE"):
        G.drawio('<!DOCTYPE x [<!ENTITY a "aaaa">]><mxfile/>')
    with pytest.raises(ValueError):
        G.drawio("<mxfile>" + "x" * (G.MAX_BYTES + 1) + "</mxfile>")
    m = G.mermaid("graph LR\n  W[Web front] -->|HTTP| A(API)\n  A --> Q & R\n  X & Y --> Z --> V\n  P -- uses --> S")
    assert m["edges"] == [["Web front", "API", "HTTP"], ["API", "Q", ""], ["API", "R", ""], ["X", "Z", ""],
                          ["Y", "Z", ""], ["Z", "V", ""], ["P", "S", "uses"]]
    p = G.plantuml('@startuml\ncomponent "Ledger DB" as led\n[api] --> [queue] : publish\napi -> led : SQL\n@enduml')
    assert p["edges"] == [["api", "queue", "publish"], ["api", "Ledger DB", "SQL"]]
    gl = {"stage": {"objects": [
        {"id": 1, "graphic": {"type": "Shape"}, "children": [{"graphic": {"Text": {"html": "<p>api</p>"}}}]},
        {"id": 2, "graphic": {"type": "Shape", "Text": {"html": "queue"}}},
        {"id": 3, "graphic": {"type": "Line"}, "constraints": {
            "startConstraint": {"StartPositionConstraint": {"nodeId": 1}},
            "endConstraint": {"EndPositionConstraint": {"nodeId": 2}}}}]}}
    assert G.gliffy(json.dumps(gl), "g")["edges"] == [["api", "queue", ""]]
    md = "Intro\n```mermaid\ngraph TD\n  a --> b\n```\n```plantuml\n@startuml\nb -> c\n@enduml\n```"
    assert [d["kind"] for d in G.in_text(md)] == ["Mermaid", "PlantUML"]


def test_a_page_keeps_its_links_images_and_diagrams(ctx):
    from supagent.knowledge.docs import read_storage

    r = read_storage('<p>See <ac:link><ri:page ri:content-title="Runbook" /></ac:link> and '
                     '<ac:link><ri:page ri:content-title="Rules" ri:space-key="GOV" />'
                     '<ac:plain-text-link-body><![CDATA[the rules]]></ac:plain-text-link-body></ac:link>, '
                     '<a href="/wiki/spaces/OPS/pages/42/Other">other</a>.</p>'
                     '<ac:image ac:alt="Rack layout"><ri:attachment ri:filename="racks.png" /></ac:image>'
                     '<ac:structured-macro ac:name="drawio"><ac:parameter ac:name="diagramName">flows'
                     '</ac:parameter></ac:structured-macro>'
                     '<ac:structured-macro ac:name="code"><ac:parameter ac:name="language">mermaid</ac:parameter>'
                     '<ac:plain-text-body><![CDATA[graph LR\n a --> b]]></ac:plain-text-body></ac:structured-macro>')
    assert "See Runbook and the rules, other." in r["text"]          # a link with no text reads as its page
    assert "[image racks.png: Rack layout]" in r["text"] and "flows" not in r["text"]
    assert r["pages"] == [("Runbook", None), ("Rules", "GOV")] and r["links"] == ["/wiki/spaces/OPS/pages/42/Other"]
    assert r["images"] == [{"alt": "Rack layout", "title": "", "file": "racks.png"}]
    assert [(d["kind"], d["name"]) for d in r["diagrams"]] == [("draw.io", "flows"), ("Mermaid", "")]
    assert "a --> b" in r["diagrams"][1]["source"]


def _wiki(base_holder: dict):
    """A Confluence (Data Center) whose pages lead to each other: home -> child A; A links by title to B (under a
    page nobody links to), B by address to C (another space); C links to another site. A draws a draw.io diagram."""
    page = {}

    def add(pid, space, title, parent, body, attachments=()):
        page[pid] = {"id": pid, "space": space, "title": title, "parent": parent, "body": body,
                     "attachments": list(attachments)}

    add(1, "OPS", "Home", None, "<p>Start.</p>")
    add(2, "OPS", "Guide", 1, '<p>Read <ac:link><ri:page ri:content-title="Deep page" /></ac:link>.</p>'
        '<ac:structured-macro ac:name="drawio"><ac:parameter ac:name="diagramName">flows</ac:parameter>'
        '</ac:structured-macro>',
        [("flows.drawio", _drawio([("w", "web"), ("a", "api")], [("w", "a", "HTTP")]))])
    add(9, "OPS", "Attic", None, "<p>Old.</p>")
    add(3, "OPS", "Deep page", 9, '<p>Then <a href="/wiki/spaces/GOV/pages/4/Rules">the rules</a>. '
        "Admin password: Sup3r-S3cret-Val</p>")
    add(4, "GOV", "Rules", None, '<p>Done. <a href="https://elsewhere.example.com/x">elsewhere</a></p>')

    def route(path, q, h):
        api = "/wiki/rest/api/content"
        base = base_holder["base"] + "/wiki"

        def js(p):
            return {"id": str(p["id"]), "type": "page", "title": p["title"], "space": {"key": p["space"]},
                    "version": {"number": 3}, "body": {"storage": {"value": p["body"]}},
                    "_links": {"webui": f"/spaces/{p['space']}/pages/{p['id']}", "base": base}}

        if path == api and q.get("title"):
            found = [p for p in page.values() if p["space"] == q.get("spaceKey") and p["title"] == q["title"]]
            return 200, {}, {"results": [js(p) for p in found], "_links": {"base": base}}
        if path.startswith(api + "/"):
            parts = path[len(api) + 1:].split("/")
            p = page.get(int(parts[0])) if parts[0].isdigit() else None
            if p is None:
                return 404, {}, {"message": "no"}
            if len(parts) == 1:
                return 200, {}, js(p)
            if parts[1:] == ["child", "page"]:
                return 200, {}, {"results": [{"id": str(k["id"])} for k in page.values() if k["parent"] == p["id"]],
                                 "_links": {"base": base}}
            if parts[1:] == ["child", "attachment"]:
                return 200, {}, {"results": [{"title": n, "_links": {"download": f"/download/attachments/{p['id']}/{n}"}}
                                             for n, _d in p["attachments"]]}
        if path.startswith("/wiki/download/attachments/"):
            pid, _, name = path[len("/wiki/download/attachments/"):].partition("/")
            data = dict(page[int(pid)]["attachments"]).get(name)
            return (200, {"Content-Type": "application/xml"}, data) if data else (404, {}, "no")
        return 404, {}, "no"

    return route


def test_a_wiki_is_read_to_the_last_page_its_links_lead_to(env, servers):
    from supagent.knowledge import docs as D

    holder: dict = {}
    s = servers(_wiki(holder))
    holder["base"] = s.base
    d = _doc(f"{s.base}/wiki/spaces/OPS/pages/1/Home", max_pages=20)
    out = D.refresh(d)
    assert out["status"] == "ok", out
    assert [p["title"] for p in d.pages] == ["Home", "Guide", "Deep page", "Rules"]   # Attic: nothing leads there
    by = {p["title"]: p for p in d.pages}
    assert by["Guide"]["links"] == ["3"] and by["Deep page"]["links"] == ["4"] and by["Rules"]["space"] == "GOV"
    assert by["Guide"]["diagram_edges"] == [["web", "api", "HTTP"]]
    assert "draw.io diagram flows: web -> api (HTTP)." in d.content
    assert "Sup3r-S3cret-Val" not in d.content and "password: ***" in d.content     # a page's secret masked
    assert not any("elsewhere" in r["path"] for r in s.got)                         # another site: never
    small = _doc(f"{s.base}/wiki/spaces/OPS/pages/1/Home", max_pages=2)
    d.enabled = False                                                 # (0.10.1: else its pages are the first's)
    D.refresh(small)
    assert [p["title"] for p in small.pages] == ["Home", "Guide"]                   # pages at most


def test_a_systemd_unit_is_read_with_the_code(ctx):
    from supagent.knowledge.docs import wanted_file

    assert wanted_file("deploy/api.service", "code") and wanted_file("deploy/api.timer", "code")
    assert not wanted_file("deploy/api.service")                                    # documentation only: not code
