"""(0.11.1) The Context's writer for a new member of the team: the relations diagram draws one box per part (however
the documents spell it), the evidence carries no counts the page would repeat, and what the LLM writes is checked
before it is saved (citations to evidence that exists, no counts of objects or pages, "In short" first, names not in
the evidence said in the build's steps)."""

from __future__ import annotations

from test_context import shared  # noqa: F401  (the fixture)
from test_knowledge import world  # noqa: F401  (the fixture)


def _lines(block: str) -> list[str]:
    return [ln for ln in block.strip("`\n").splitlines()[2:] if ln]


def test_the_diagram_draws_one_box_per_part_however_it_is_spelled(ctx):
    from supagent.knowledge.context import DIAGRAM_HEAD, diagram_block

    rels = [{"a": "web-shop", "verb": "calls", "b": "checkout-api (prod)", "pages": 9},
            {"a": "Checkout API", "verb": "reads_from", "b": "orders_db", "pages": 5},
            {"a": "checkout_api", "verb": "uses", "b": "orders-db", "pages": 3},       # the same two parts again
            {"a": "checkout-api", "verb": "calls", "b": "payment-gw", "pages": 2},
            {"a": "orders-db", "verb": "runs_on", "b": "orders_db (prod)", "pages": 1}]  # a part on itself: no line
    block = diagram_block(rels)
    assert block.startswith("```text\n" + DIAGRAM_HEAD + "\n")
    lines = _lines(block)
    assert lines == ["web-shop -> Checkout API : calls",                # the plain spelling, never "(prod)"'s
                     "Checkout API -> orders_db : reads from, uses",    # one line for one pair of parts
                     "Checkout API -> payment-gw : calls"]
    nodes = {x for ln in lines for x in ln.split(" : ")[0].split(" -> ")}
    assert nodes == {"web-shop", "Checkout API", "orders_db", "payment-gw"}


def test_the_diagram_keeps_few_parts_and_the_most_stated_relations(ctx):
    from supagent.knowledge.context import DIAGRAM_NODES, diagram_block

    rels = [{"a": "hub", "verb": "calls", "b": f"svc-{i:02d}", "pages": 100 - i} for i in range(40)]
    lines = _lines(diagram_block(rels))
    nodes = {x for ln in lines for x in ln.split(" : ")[0].split(" -> ")}
    assert len(nodes) <= DIAGRAM_NODES and "hub -> svc-00 : calls" in lines and "hub -> svc-39 : calls" not in lines


def test_the_evidence_of_a_summary_says_no_count_the_page_would_repeat(ctx):
    import json
    import re

    from supagent.knowledge import context as C

    texts, pages, at = [], [], 0
    for i in range(2000):                                           # a wiki bigger than a summary's room
        block = f"# Note {i}\nShop notes {i}. " + ("The cart calls the pricing service." if i == 7 else "Routine.")
        at += 2 if texts else 0
        pages.append({"id": str(i), "title": f"Note {i}", "space": "SHOP", "at": at, "chars": len(block),
                      "links": ["7"] if i % 2 else []})
        texts.append(block)
        at += len(block)
    wiki = {"id": 1, "title": "Shop wiki", "content": "\n\n".join(texts), "pages": pages}
    rels = [{"a": "cart", "verb": "calls", "b": "pricing", "pages": 12},
            {"a": "pricing", "verb": "runs_on", "b": "shop-cluster", "pages": 1}]
    ev = {"databases": {}, "inventory": {}, "relations": [], "entries": [], "answers": [], "memory": [],
          "docs": [wiki], "part_relations": rels}
    overview = {s["slug"]: s for s in C.summary_specs(ev)}["overview"]
    said = json.dumps(overview["evidence"]) + overview["brief"]
    assert not re.search(r"\b\d[\d,]* pages?\b", said) and "how many" not in overview["brief"]
    assert "cart calls pricing" in said and "- Note 7: " in said      # the relations and the central page, uncounted


EVIDENCE = [{"id": f"E{i}", "ref": f"doc:{i}", "title": f"Note {i}", "text": "cart calls pricing; pricing reads stock-db"}
            for i in range(1, 6)]


def test_a_citation_to_no_evidence_is_left_out(ctx):
    from supagent.knowledge.context import check_page

    page, notes = check_page("In short: the shop sells [E1].\n\nIt pays at the end [E9]. It ships [E2, E7].",
                             EVIDENCE)
    assert page == "In short: the shop sells [E1].\n\nIt pays at the end. It ships [E2]."
    assert notes == ["citations to no evidence left out: E7, E9"]


def test_a_count_of_objects_or_pages_is_left_out_and_other_figures_stay(ctx):
    from supagent.knowledge.context import check_page

    text = ("In short: the shop sells online [E1].\n\n"
            "There are 42 servers. The cart calls pricing [E2].\n"
            "The wiki holds 5,000 pages [E3].\n"
            "The wiki (about 5,000 pages) explains the checkout [E1].\n"
            "There are 3 services: cart, pricing and stock.\n"
            "- 1,234 metrics are learned.\n"
            "- Jobs restart at 02:00 and logs are kept for 30 days.\n"
            "- The API listens on port 8080 and writes 1 document per order.\n"
            "| part | servers |\n|---|---|\n| cart | 4 servers |")
    page, notes = check_page(text, EVIDENCE)
    assert page.splitlines() == ["In short: the shop sells online [E1].", "",
                                 "The cart calls pricing [E2].",
                                 "The wiki explains the checkout [E1].",
                                 "The services: cart, pricing and stock.",
                                 "- Jobs restart at 02:00 and logs are kept for 30 days.",
                                 "- The API listens on port 8080 and writes 1 document per order.",
                                 "| part | servers |", "|---|---|", "| cart | 4 servers |"]   # a table as written
    assert notes and notes[0].startswith("counts left out: There are 42 servers.")


def test_in_short_comes_first_and_a_page_without_it_is_said(ctx):
    from supagent.knowledge.context import check_page

    text = ("# How the system works\n\n## What it does\n\nThe cart calls pricing [E1].\n\n"
            "## In short\n\nThe shop sells online: the cart prices each order [E2].\n\n## Applications\n\nThe cart.")
    page, notes = check_page(text, EVIDENCE)
    assert page.startswith("In short: The shop sells online: the cart prices each order [E2].\n\n## What it does")
    assert "# How the system works" not in page and "## In short" not in page and page.endswith("## Applications\n\nThe cart.")
    assert notes == ['"In short" moved first']
    bold = "## What it does\n\nThe cart calls pricing.\n\n**In short**: the shop sells."
    assert check_page(bold, EVIDENCE)[0].startswith("**In short**: the shop sells.\n\n## What it does")
    plain = "## What it does\n\nThe cart calls pricing [E1]."
    assert check_page(plain, EVIDENCE) == (plain, ['no "In short" paragraph'])       # said, never rewritten


def test_not_known_yet_keeps_the_first_points_and_unknown_names_are_said(ctx):
    from supagent.knowledge.context import NOT_KNOWN_POINTS, check_page

    text = ("In short: the shop [E1].\n\n## Not known yet\n\n" + "\n".join(f"- point {i}" for i in range(1, 9)) +
            "\n\n## Links\n\nThe `cart` calls `Pricing` and `cart-gateway-v2` [E1].")
    page, notes = check_page(text, EVIDENCE)
    assert "- point 5" in page and "- point 6" not in page and page.endswith("[E1].") and NOT_KNOWN_POINTS == 5
    assert notes == ["not known yet: 3 points left out", "names not in the evidence: `cart-gateway-v2`"]


def test_write_summary_saves_the_checked_page_and_says_what_changed(ctx):
    from test_context_complete import Scripted

    from supagent.knowledge.context import write_summary

    llm = Scripted([("## What it does\n\nIt sells [E1]. There are 42 servers.\n\nIn short: the shop [E4].", "stop")])
    spec = {"title": "Overview", "brief": "Explain.", "evidence": [{"ref": "doc:1", "title": "Runbook", "text": "x"}]}
    out = write_summary(spec, llm)
    assert out["content"] == "In short: the shop.\n\n## What it does\n\nIt sells [E1]."
    assert [c.split(":")[0] for c in out["checks"]] == ["citations to no evidence left out", "counts left out",
                                                        '"In short" moved first']


def test_the_build_says_which_pages_its_checks_changed(shared):
    from supagent.knowledge.context import build_context

    out = build_context(reason="test")
    step = {s["step"]: s for s in out["steps"]}["summary pages (LLM)"]
    assert step["checked"] == step["llm_calls"] and step["checked_pages"]         # the fake LLM writes no In short
    assert any(p.startswith("How the system works: ") and 'no "In short" paragraph' in p for p in step["checked_pages"])


def test_the_writer_asks_for_tables_one_name_per_part_and_a_short_not_known_yet(ctx):
    from supagent.knowledge.context import PROMPT, summary_specs

    ev = {"databases": {}, "inventory": {}, "relations": [], "entries": [], "answers": [], "memory": [],
          "docs": [{"id": 1, "title": "Runbook", "content": "The cart calls pricing.", "pages": []}], "part_relations": []}
    specs = {s["slug"]: s for s in summary_specs(ev)}
    assert "one table, a row per application" in specs["overview"]["brief"]
    assert "never a list per domain" in specs["overview"]["brief"]
    assert "one table, a row per data source" in specs["architecture"]["brief"]
    assert "## Not known yet: at most five points" in specs["architecture"]["brief"]
    said = PROMPT.format(title="T", brief="B")
    assert "the same way every time" in said and "(only the ids given)" in said and "say a thing once" in said
    assert "draw none yourself" in said and "counts of" in said and said.endswith("The page: T. B")


def test_the_light_llm_context_never_ends_a_section_at_its_heading(ctx):
    from supagent.knowledge.llm_context import LIGHT, pages

    about = "Holds one record per order of the shop with its state, its amount and the customer who placed it. " * 2
    ev = {"databases": {i: {"name": f"Shop data {i}", "backend": "postgresql", "others": 0, "fields": [],
                            "main": [{"kind": "index", "name": f"orders_{i}_{k}", "about": about} for k in range(10)]}
                        for i in range(1, 8)},
          "entries": [{"id": 1, "title": "Order", "classification": "glossary", "content": "A purchase.",
                       "database_id": None}], "relations": [], "answers": []}
    light = next(p for p in pages(ev) if p["slug"] == "llm-context-light")["content"]
    assert len(light) <= LIGHT["total"] + 200
    blocks = [b for b in light.split("\n\n") if b.strip()]
    for i, b in enumerate(blocks):
        if b.startswith("## "):
            assert i + 1 < len(blocks) and not blocks[i + 1].startswith("## "), b     # each heading has its lines


def test_a_wiki_space_page_lists_its_central_pages_first_and_no_counts(app):
    import re
    from types import SimpleNamespace as N

    from supagent.knowledge.context_docs import WIKI_PAGES, _space_pages

    entries = [{"id": str(i), "title": f"Note {i}", "space": "SHOP", "links": ["30"] if i != 30 else ["1"],
                "diagram_edges": [["cart", "pricing"]] * 7 if i == 30 else []} for i in range(60)]
    doc = N(id=1, title="Shop wiki", url="u1", pages=entries)
    units = [N(id=100 + i, doc_id=1, ukey=p["id"], kind="page") for i, p in enumerate(entries)]
    about = {"pricing": {100, 101, 102}, "cart": {103}}
    with app.app_context():
        page = _space_pages({1: doc}, units, about, {"pricing": "pricing", "cart": "cart"})[0]["content"]
    listed = [ln for ln in page.splitlines() if ln.startswith("- Note ")]
    assert listed[0] == "- Note 30 (links to: Note 1) (with a diagram)"            # the page all the others link to
    assert len(listed) == WIKI_PAGES and "- ... the other pages: Documents and sites" in page
    assert "pricing, cart." in page                                                   # the most described first
    assert not re.search(r"\d+ (?:pages?|arrows)\b", page)


def test_an_application_page_gets_the_relations_of_every_spelling_of_its_name(ctx):
    from supagent.knowledge.context import PROMPT, summary_specs

    ev = {"databases": {1: {"name": "Shop data", "backend": "postgresql", "categories": {}}},
          "relations": [], "entries": [], "answers": [], "memory": [],
          "inventory": {"Applications": {1: {"holders": ["field app of orders"], "values": ["billing-service"],
                                             "partial": False}}},
          "docs": [{"id": 1, "title": "Runbook", "content": "billing-service sends invoices.", "pages": []}],
          "part_relations": [{"a": "Billing_Service (prod)", "verb": "calls", "b": "ledger", "pages": 3},
                             {"a": "ledger", "verb": "runs_on", "b": "billing-service", "pages": 2},
                             {"a": "cart", "verb": "calls", "b": "pricing", "pages": 9}]}
    app = {s["slug"]: s for s in summary_specs(ev)}["application-billing-service"]
    assert [r["b"] for r in app["diagram"]] == ["ledger", "billing-service"]          # both spellings, not the cart's
    assert "servers, values" in PROMPT and "the Inventory pages" in PROMPT


def test_the_checks_keep_what_a_count_introduces_and_leave_no_empty_section(ctx):
    from supagent.knowledge.context import check_page

    text = ("## Overview\n\nIn short: there are 42 servers behind the shop [E1].\n\n## Data\n\n"
            "The data dictionary holds 1,234 metrics; the main ones are cart_orders and pricing_time [E2].")
    page, notes = check_page(text, EVIDENCE)
    assert page == ("In short: there are servers behind the shop [E1].\n\n## Data\n\n"     # never dropped; no empty
                    "The data dictionary holds metrics; the main ones are cart_orders and pricing_time [E2].")
    assert notes[-1] == '"In short" moved first'
    empty = "## What it does\n\nIt sells.\n\n## In short\n\n## Applications\n\nThe cart."
    page, notes = check_page(empty, EVIDENCE)                                      # a heading with nothing under it
    assert notes == ['no "In short" paragraph', "no citation"] and page.startswith("## What it does")


def test_a_check_that_fails_never_costs_the_page(ctx, monkeypatch):
    from test_context_complete import Scripted

    from supagent.knowledge import context as C

    def broken(*a, **k):
        raise ValueError("a check's bug")

    monkeypatch.setattr(C, "check_page", broken)
    llm = Scripted([("In short: the shop [E1].", "stop")])
    out = C.write_summary({"title": "Overview", "brief": "Explain.", "evidence": [{"ref": "doc:1", "title": "R"}]}, llm)
    assert out["content"] == "In short: the shop [E1]." and out["checks"] == ["checks not done: ValueError"]


def test_a_diagram_the_llm_drew_is_left_out_and_a_query_is_kept(ctx):
    from supagent.knowledge.context import check_page

    text = ("In short: the shop [E1].\n\n## Relations diagram\n\n```mermaid\ngraph LR\n  cart --> pricing\n```\n\n"
            "## Chain\n\nThe cart calls pricing [E2].\n\n```text\nflowchart LR\ncart --> stock\n```\n\n"
            "## Its data\n\n```sql\nSELECT state, count(*) FROM orders GROUP BY state\n```")
    page, notes = check_page(text, EVIDENCE)
    assert page == ("In short: the shop [E1].\n\n## Chain\n\nThe cart calls pricing [E2].\n\n## Its data\n\n"
                    "```sql\nSELECT state, count(*) FROM orders GROUP BY state\n```")
    assert notes == ["a diagram the LLM drew left out (the page draws the relations itself)"]


def test_a_paragraph_cites_each_source_once_at_its_end(ctx):
    from supagent.knowledge.context import check_page

    text = ("In short: the shop sells [E1]. It ships [E1]. It bills [E1, E2].\n\n"
            "- the cart [E1]\n- pricing [E1]\n\n| part | source |\n|---|---|\n| cart | [E1] |\n| stock | [E1] |")
    page, notes = check_page(text, EVIDENCE)
    assert page.splitlines()[0] == "In short: the shop sells. It ships. It bills [E1, E2]."
    assert "- the cart [E1]\n- pricing [E1]" in page and "| stock | [E1] |" in page       # a list, a table: as written
    assert notes == ["citations said again in a paragraph left out: 2"]


def test_a_part_written_two_ways_is_said(ctx):
    from supagent.knowledge.context import check_page

    text = ("In short: the `checkout-api` takes the orders [E1].\n\n## Chain\n\nThe **Cart** sends to checkout_api, "
            "the cart's prices come from pricing [E2].\n\n```sql\nSELECT * FROM checkout_apis\n```")
    page, notes = check_page(text, [{"id": "E1", "text": "checkout-api checkout_api cart pricing"}] * 2)
    assert page == text and notes == ["one part, several names: checkout-api / checkout_api"]     # said, not rewritten


def test_a_count_left_out_never_takes_the_paragraph_s_source_with_it(ctx):
    from supagent.knowledge.context import check_page

    page, _notes = check_page("In short: the shop [E2].\n\nIt sells and ships. There are 42 servers [E1].", EVIDENCE)
    assert page.endswith("\n\nIt sells and ships [E1].")
    page, _notes = check_page("In short: the shop [E2].\n\nIt sells [E1]. There are 42 servers [E1].", EVIDENCE)
    assert page.endswith("\n\nIt sells [E1].")
    page, _notes = check_page("In short: the shop [E2].\n\nThere are 42 servers [E3]. It sells [E1].", EVIDENCE)
    assert page.endswith("\n\nIt sells [E1, E3].")
    page, notes = check_page("**In short**: the cart [E1]. It ships [E1].\n\n**Cart** calls pricing [E2]. It pays [E2].",
                             EVIDENCE)                                              # a paragraph opening in bold
    assert page == "**In short**: the cart. It ships [E1].\n\n**Cart** calls pricing. It pays [E2]."


def test_a_page_with_evidence_and_no_citation_is_said(ctx):
    from supagent.knowledge.context import PROMPT, check_page

    page, notes = check_page("In short, the shop sells parts.\n\n## What it does\n\nIt sells parts.",
                             [{"id": "E1", "text": "the shop sells parts"}])
    assert "no citation" in notes and "after each table" in PROMPT
    _page, notes = check_page("In short, the shop sells parts [E1].", [{"id": "E1", "text": "the shop sells parts"}])
    assert "no citation" not in notes
