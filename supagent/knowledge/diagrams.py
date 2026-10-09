"""The diagrams of the team's documents read as what they draw (0.10): the boxes (its parts) and the arrows between
them (how they interact), from the diagram's own source, no image recognition needed:

  draw.io     an attachment of a Confluence page (the draw.io app's macro), a .drawio file of a repository: the
              mxfile's pages, compressed as the app saves them (deflate, base64, URL-encoding) or not
  Gliffy      a Confluence page's Gliffy attachment (JSON): its shapes and lines
  Mermaid     a ```mermaid block of a Markdown file, a code macro of a page: flowcharts' arrows
  PlantUML    an @startuml block: the arrows of component and sequence diagrams

Each gives its parts and its arrows (with their labels), and a text: "Diagram <name>: A -> B (label); ...", that the
search keeps with its page and the understanding reads as stated interactions. A file from another system is data: its
size is bounded, an XML that declares a DOCTYPE is not read, nothing in it is ever run.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
import zlib
from html import unescape
from typing import Any

MAX_BYTES = 4 * 1024 * 1024     # a diagram's source at most
MAX_EDGES = 400                 # arrows kept of one diagram
LABEL_CHARS = 120


def _clean(label: Any) -> str:
    """A box's or an arrow's text without its HTML (draw.io keeps rich text as HTML)."""
    s = unescape(re.sub(r"<br\s*/?>|</(?:div|p)>", " ", str(label or ""), flags=re.I))
    s = re.sub(r"<[^>]+>", "", s)
    return " ".join(s.split())[:LABEL_CHARS]


def _xml(text: str) -> Any:
    if len(text) > MAX_BYTES or re.search(r"<!DOCTYPE|<!ENTITY", text[:4096], re.I):
        raise ValueError("not read: too large, or an XML that declares a DOCTYPE")
    try:
        from defusedxml import ElementTree as ET     # when Superset's environment has it
    except ImportError:                              # expat (2.4+) bounds entity expansion; no DOCTYPE allowed above
        from xml.etree import ElementTree as ET      # nosec B405
    return ET.fromstring(text)                       # nosec B314


def _inflate(data: str) -> str:
    """A draw.io page's compressed model: base64, raw deflate, URL-encoded."""
    raw = base64.b64decode(data.strip())
    for wbits in (-15, 15):
        try:
            out = zlib.decompress(raw, wbits)
            break
        except zlib.error:
            continue
    else:
        raise ValueError("not a compressed draw.io page")
    return urllib.parse.unquote(out.decode("utf-8", errors="replace"))


def drawio(text: str, name: str = "") -> dict[str, Any]:
    """The parts and arrows of a draw.io file (one or more pages; each page's model compressed or not)."""
    root = _xml(text)
    models = []
    if root.tag == "mxGraphModel":
        models.append(root)
    for page in root.iter("diagram"):
        inner = list(page)
        if inner and inner[0].tag == "mxGraphModel":
            models.append(inner[0])
        elif (page.text or "").strip():
            models.append(_xml(_inflate(page.text)))
    nodes: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []
    for model in models:
        cells = list(model.iter("mxCell")) + [c for o in model.iter("object") for c in o.iter("mxCell")]
        labels = {}
        for o in model.iter("object"):               # a box with data: its label on the object
            for c in o.iter("mxCell"):
                labels[o.get("id") or c.get("id")] = o.get("label") or ""
        for c in cells:
            cid = c.get("id") or ""
            if c.get("vertex") == "1":
                label = _clean(labels.get(cid) or c.get("value"))
                if label:
                    nodes[cid] = label
        for c in cells:
            if c.get("edge") == "1" and c.get("source") in nodes and c.get("target") in nodes:
                edges.append((nodes[c.get("source")], nodes[c.get("target")], _clean(labels.get(c.get("id")) or c.get("value"))))
    return _result("draw.io", name, list(dict.fromkeys(nodes.values())), edges)


def gliffy(text: str, name: str = "") -> dict[str, Any]:
    """The shapes and lines of a Gliffy diagram (JSON): a line's ends are the shapes its constraints name."""
    if len(text) > MAX_BYTES:
        raise ValueError("not read: too large")
    data = json.loads(text)
    objects: list[dict[str, Any]] = []

    def walk(items: Any) -> None:
        for o in items or []:
            if isinstance(o, dict):
                objects.append(o)
                walk(o.get("children"))

    walk(((data.get("stage") or {}).get("objects")) if isinstance(data, dict) else [])
    nodes: dict[str, str] = {}
    for o in objects:
        texts = [((c.get("graphic") or {}).get("Text") or {}).get("html") for c in o.get("children") or []
                 if isinstance(c, dict)]
        own = ((o.get("graphic") or {}).get("Text") or {}).get("html")
        label = _clean(own or next((t for t in texts if t), ""))
        if label and ((o.get("graphic") or {}).get("type") != "Line"):
            nodes[str(o.get("id"))] = label
    edges = []
    for o in objects:
        if (o.get("graphic") or {}).get("type") == "Line":
            cons = o.get("constraints") or {}
            a = ((cons.get("startConstraint") or {}).get("StartPositionConstraint") or {}).get("nodeId")
            b = ((cons.get("endConstraint") or {}).get("EndPositionConstraint") or {}).get("nodeId")
            if str(a) in nodes and str(b) in nodes:
                label = next((_clean(((c.get("graphic") or {}).get("Text") or {}).get("html"))
                              for c in o.get("children") or [] if isinstance(c, dict)), "")
                edges.append((nodes[str(a)], nodes[str(b)], label))
    return _result("Gliffy", name, list(dict.fromkeys(nodes.values())), edges)


# Mermaid flowcharts: A --> B, A -->|label| B, A -- label --> B, A -.-> B, A ==> B, A[Text] --> B(Text),
# A --> B --> C (a chain), A & B --> C & D (each to each)
MERMAID_ARROW = re.compile(r"\s*(?:<)?(?:--+|==+|-\.+-?)(?:\s+([^-=>|]+?)\s+(?:--+|==+|-\.+-?))?>?\s*(?:\|([^|]*)\|)?\s*")
# a node and its text in any shape: A[t], A(t), A([t]), A[[t]], A[(t)] (a database), A((t)), A{t}, A{{t}}, A>t], A[/t/]
MERMAID_NODE = re.compile(r"^\s*([A-Za-z0-9_.:-]+)\s*(?:[\[\(\{>]+[/\\]?\s*\"?(.*?)\"?\s*[/\\]?[\]\)\}]+)?\s*$")


def mermaid(text: str, name: str = "") -> dict[str, Any]:
    """The arrows of a Mermaid flowchart (graph / flowchart); other kinds of diagram give no arrow."""
    labels: dict[str, str] = {}
    edges: list[tuple[str, str, str]] = []
    for line in (text or "").splitlines()[:5000]:
        line = line.strip().rstrip(";")
        if not line or line.startswith(("%%", "graph", "flowchart", "classDef", "class ", "style ", "subgraph",
                                        "end", "linkStyle", "click ")):
            continue
        parts = MERMAID_ARROW.split(line)          # group, label, label, group, label, label, group...
        if len(parts) < 4:
            continue
        groups, arrows = parts[0::3], list(zip(parts[1::3], parts[2::3]))
        sides: list[list[str]] = []
        for g in groups:
            ids = []
            for spec in re.split(r"\s*&\s*", g or ""):
                m = MERMAID_NODE.match(spec)
                if m:
                    ids.append(m.group(1))
                    if m.group(2):
                        labels[m.group(1)] = _clean(m.group(2))
                    labels.setdefault(m.group(1), m.group(1))
            sides.append(ids)
        for k, (inline, piped) in enumerate(arrows):
            if k + 1 < len(sides):
                for a in sides[k]:
                    for b in sides[k + 1]:
                        edges.append((a, b, _clean(piped or inline or "")))
    edges = [(labels.get(a, a), labels.get(b, b), lab) for a, b, lab in edges]
    return _result("Mermaid", name, list(dict.fromkeys([x for e in edges for x in e[:2]])), edges)


PLANT_EDGE = re.compile(r"^\s*(\"[^\"]+\"|\[[^\]]+\]|[A-Za-z0-9_.:-]+)\s*(?:<?-+>|<?\.+>|-\[[^\]]*\]->|->>?|-->>?)\s*"
                        r"(\"[^\"]+\"|\[[^\]]+\]|[A-Za-z0-9_.:-]+)\s*(?::\s*(.*))?$")


def _plant_name(raw: str) -> str:
    """(0.10.6) A PlantUML box's name: its label's first line ("rider-web\\n(Node.js :3000)" -> rider-web)."""
    first = next((x for x in re.split(r"\\n|\n", str(raw or "").strip('"[]')) if x.strip()), "")
    return _clean(re.sub(r"<<[^>]*>>", "", first))


def plantuml(text: str, name: str = "") -> dict[str, Any]:
    """The arrows of a PlantUML diagram (components, sequences: A -> B : label); (0.10.6) a box holding other boxes
    ("component Balancers { component HAProxy }") stands, in an arrow, for the one box it holds, else for no one."""
    aliases: dict[str, str] = {}
    holds: dict[str, list[str]] = {}
    stack: list[str] = []
    for line in (text or "").splitlines()[:5000]:
        m = re.match(r"^\s*(?:component|node|database|queue|actor|participant|rectangle|cloud|frame|package)\s+"
                     r"(\"[^\"]+\"|\[[^\]]+\]|[\w.-]+)(?:\s+as\s+([\w.-]+))?", line, re.I)
        if m:
            key = m.group(2) or m.group(1).strip('"[]')
            aliases[key] = _plant_name(m.group(1))
            if stack:
                holds.setdefault(stack[-1], []).append(key)
            if line.rstrip().endswith("{"):
                stack.append(key)
        elif line.strip() == "}" and stack:
            stack.pop()
    edges = []
    for line in (text or "").splitlines()[:5000]:
        m = PLANT_EDGE.match(line)
        if m:
            ends = []
            for x in (m.group(1), m.group(2)):
                key = x.strip('"[]')
                inner = holds.get(key)
                if inner is not None:                       # a box of boxes: the one it holds, or no one
                    key = inner[0] if len(inner) == 1 else ""
                ends.append(aliases.get(key, _plant_name(key)) if key else "")
            edges.append((ends[0], ends[1], _clean(m.group(3) or "")))
    return _result("PlantUML", name, list(dict.fromkeys([x for e in edges for x in e[:2] if x])), edges)


def _result(kind: str, name: str, nodes: list[str], edges: list[tuple[str, str, str]]) -> dict[str, Any]:
    edges = list(dict.fromkeys(e for e in edges if e[0] and e[1] and e[0] != e[1]))[:MAX_EDGES]
    title = f"{kind} diagram {name}".strip() if name else f"{kind} diagram"
    lines = [f"{a} -> {b}" + (f" ({lab})" if lab else "") for a, b, lab in edges]
    text = f"{title}: " + ("; ".join(lines) if lines else ", ".join(nodes[:60])) + "." if (lines or nodes) else ""
    return {"kind": kind, "name": name, "nodes": nodes[:200], "edges": [list(e) for e in edges], "text": text}


BLOCK = re.compile(r"```\s*(mermaid|plantuml|puml)\s*\n(.*?)```|(@startuml.*?@enduml)", re.S | re.I)


def in_text(text: str) -> list[dict[str, Any]]:
    """The Mermaid and PlantUML diagrams written in a text (Markdown blocks, @startuml ... @enduml)."""
    out = []
    for m in BLOCK.finditer(text or ""):
        kind, body, uml = m.group(1), m.group(2), m.group(3)
        try:
            d = plantuml(uml or body) if uml or (kind or "").lower() in ("plantuml", "puml") else mermaid(body)
        except (ValueError, re.error):
            continue
        if d["edges"]:
            out.append(d)
    return out
