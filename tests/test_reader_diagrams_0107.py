"""(0.10.7) A diagram's source in a page or a file is read by the diagram reader only: read as sentences too, a
Mermaid source's lines ran into one another (a dot in a node's name, "orders.placed", ends no line) and an arrow's
label ("publishes / writes") linked its part to every part of the following lines ("checkout sends data to
cart-api, catalog-api, pricing-api ..." from a domain page of the test world)."""

from __future__ import annotations



def facts(text, parts=()):
    """The facts of a wiki page whose Mermaid macro the page's reading gave as its diagram's arrows (docs.py)."""
    import re

    from supagent.knowledge import diagrams as G
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    src = re.search(r"^graph LR\n(?:.*\n)*?(?=The checkout)", text, re.M).group(0)
    u = {"ukey": "p1", "path": "", "kind": "page", "title": "orders domain", "text": text,
         "meta": {"diagram_edges": G.mermaid(src, "")["edges"]}}
    u["found"] = discover(u)
    return {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, None, Names(), {norm(p): p for p in parts})}

PAGE = """The orders domain: taking an order. It is owned by the shop team.
### Flows
graph LR
checkout[checkout] --> inventory[inventory]
checkout[checkout] -->|SQL / db| orders_db[orders-db]
checkout[checkout] -->|publishes / writes| orders_placed[orders.placed]
checkout[checkout] -->|publishes / writes| orders_cancelled[orders.cancelled]
cart_api[cart-api] --> catalog_api[catalog-api]
cart_api[cart-api] --> pricing_api[pricing-api]
inventory[inventory] -->|publishes / writes| stock_reserved[stock.reserved]
returns_api[returns-api] --> order_history_api[order-history-api]
The checkout calls the payment service to authorize each order.
"""
PARTS = ("checkout", "inventory", "orders-db", "orders.placed", "orders.cancelled", "cart-api", "catalog-api",
         "pricing-api", "stock.reserved", "returns-api", "order-history-api", "payment")


def test_a_mermaid_source_in_a_page_is_no_sentence(ctx):
    t = facts(PAGE, parts=PARTS)
    # the arrows, from the diagram reader
    assert ("checkout", "sends_to", "orders.placed") in t and ("cart-api", "calls", "pricing-api") in t
    assert ("checkout", "calls", "inventory") in t
    # no part linked to the parts of the following lines
    assert not {("checkout", v, o) for v in ("sends_to", "calls") for o in ("cart-api", "catalog-api", "pricing-api",
                                                                             "returns-api")} & t
    assert ("inventory", "sends_to", "order-history-api") not in t
    # the sentence after the diagram is still read
    assert ("checkout", "calls", "payment") in t


def test_the_blanked_text_keeps_its_length_and_its_other_lines(ctx):
    from supagent.knowledge.understand import diagram_free

    text = PAGE + "```mermaid\nflowchart TD\n  a --> b\n```\nAfter.\n@startuml\nx -> y\n@enduml\nEnd."
    got = diagram_free(text)
    assert len(got) == len(text) and got.count("\n") == text.count("\n")
    assert "graph LR" not in got and "-->" not in got and "x -> y" not in got
    assert "The orders domain" in got and "calls the payment service" in got and "After." in got and "End." in got
    # a sentence with an arrow in prose is no diagram
    assert diagram_free("frontend → checkout → payment") == "frontend → checkout → payment"


def test_a_runs_on_cell_written_with_its_preposition(ctx):
    from test_prose_010 import facts as page_facts

    t = page_facts("Database | Engine | Group\nzq-pricing-db | PostgreSQL | on zq-shared-pg\n",
                   parts=("zq-pricing-db",))
    assert ("zq-pricing-db", "runs_on", "zq-shared-pg") in t and not any(o.startswith("on ") for _s, _v, o in t)


def test_a_file_named_after_a_part_speaks_for_it(ctx):
    from supagent.knowledge.understand import Names, file_part, norm

    n = Names()
    for p in ("prometheus-par1", "prometheus-ams1", "reporting-export", "checkout"):
        n.add_part(p)
    n.hosts[norm("db-pg-01")] = "db-pg-01"
    assert file_part("prometheus/prometheus-ams1.yml", n, {}) == "prometheus-ams1"
    assert file_part("jobs/reporting_export.py", n, {}) == "reporting-export"
    assert file_part("checkout/src/main/java/com/shop/checkout/CheckoutEvents.java", n, {}) == "checkout"
    assert file_part("core/db-pg-01.conf", n, {}) is None                  # a server's file: no part
    assert file_part("src/main.py", n, {}) is None and file_part("", n, {}) is None


def test_a_data_source_reads_the_part_its_address_names_not_its_type(ctx):
    from supagent.knowledge.understand import Names, _monitoring

    n = Names()
    for p in ("grafana", "mimir", "prometheus-par1"):
        n.add_part(p)
    n.alias["prometheus"] = "prometheus-par1"
    text = ("apiVersion: 1\ndatasources:\n  - name: Mimir\n    type: prometheus\n"
            "    url: http://mimir.int.shop.example/prometheus\n")
    got = {(a, v, b) for a, v, b, _pos in _monitoring(text, n, {}, "grafana")}
    assert ("grafana", "reads_from", "mimir") in got and ("grafana", "reads_from", "prometheus-par1") not in got
