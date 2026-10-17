"""(0.11.1) The reader of documents and repositories on what a team writes at scale: a heading, a front matter's key,
a secret's value or a scrape target followed by a long run of spaces read in linear time (the patterns backtracked
over the run: a minute for one line of 100,000 spaces), the same names and headings read as before."""
from __future__ import annotations

import time

SPACES = " " * 60000


def _unit(path, text, kind="file", title=None):
    from supagent.knowledge.understand import discover

    u = {"ukey": path, "path": path, "kind": kind, "title": title or path, "text": text, "meta": {}}
    u["found"] = discover(u)
    return u


def test_a_heading_followed_by_a_long_run_of_spaces_is_read_in_linear_time(ctx):
    from supagent.knowledge.understand import Names, _outline, facts_of

    text = "# Ledger API   \n\nThe ledger keeps the entries.\n\n## Tail" + SPACES + "end\n\n### Quote API (app-1)  \n"
    t0 = time.time()
    u = _unit("docs/ledger.md", text)
    heads = _outline(text, "markdown")
    facts_of(_unit("p1", text, kind="page", title="Catalogue"), None, Names(), {})
    assert time.time() - t0 < 3
    assert u["found"]["heading"] == "Ledger API"                   # its trailing spaces taken off, as before
    assert [h["name"] for h in heads][::2] == ["Ledger API", "Quote API (app-1)"]
    assert heads[1]["name"].startswith("Tail ") and len(heads[1]["name"]) == 200   # (a heading's 200 first)


def test_a_value_or_a_front_matter_key_followed_by_a_long_run_of_spaces_is_read_in_linear_time(ctx):
    from supagent.knowledge.docs import _secret_maps, repo_page
    from supagent.knowledge.understand import Names, facts_of

    t0 = time.time()
    masked, n = _secret_maps("app_secrets:\n  prod: 9bf8c1d2e3f4a5b6" + SPACES + "x\n  dev: 7a6b5c4d3e2f1a0b   \n")
    _url, title, _body = repo_page("http://repo", "README.md", "---\ntitle: Ledger   \ndescription: The entries"
                                   + SPACES + "kept\n---\n# Other\n")
    scrape = ("scrape_configs:\n  - job_name: ledger\n    static_configs:\n      - targets: [ledger-01:9100" + SPACES
              + ", ledger-02:9100   ]\n      - targets:\n        - ledger-03:9100" + SPACES + "\n")
    got = {(f["subject"], f["obj"]) for f in facts_of(_unit("prometheus/prometheus.yml", scrape), None, Names(), {})
           if f["verb"] == "scrapes"}
    assert time.time() - t0 < 3
    assert n == 2 and "prod: ***" in masked and "dev: ***" in masked
    assert title == "Ledger (README.md)"
    assert got == {("ledger", "ledger-01"), ("ledger", "ledger-02"), ("ledger", "ledger-03")}


def test_an_inventory_of_ten_thousand_hosts_is_read_in_linear_time_with_each_hosts_line(ctx):
    from supagent.knowledge.projects import _yaml_inventory

    text = ("all:\n  children:\n    web:\n      hosts:\n" + "".join(f"        web-{i:05d}:\n" for i in range(5000))
            + "    db:\n      hosts:\n"
            + "".join(f"        db-{i:05d}:\n          ansible_host: 10.0.{i // 250}.{i % 250}\n" for i in range(5000))
            + "    ranged:\n      hosts:\n        \"app-[01:03]\":\n        'one-off':\n")
    t0 = time.time()
    inv = _yaml_inventory("inventories/prod/hosts.yml", text)
    assert time.time() - t0 < 4                                     # (it took 8 s, a minute at 20,000)
    assert len(inv.all_hosts()) == 10004
    assert (inv.groups["web"]["line"], inv.groups["db"]["line"]) == (3, 5005)
    assert inv.groups["web"]["hosts"]["web-04999"] == 5004 and inv.groups["db"]["hosts"]["db-00001"] == 5009
    assert inv.groups["ranged"]["hosts"] == {"app-01": 15009, "app-02": 15009, "app-03": 15009, "one-off": 15010}


def test_what_a_part_stands_on_keeps_a_cmdb_name_with_spaces_whole(ctx, monkeypatch):
    from supagent.knowledge import inventory as I

    rows = [{"name": "Ledger Service", "table": "cmdb", "aliases": ["ledger"], "raw": {
                "runs_on": '["Node 7", "node-8"]', "depends_on": '["Main Ledger DB"]'}},
            {"name": "Node 7", "table": "cmdb", "aliases": [], "raw": {"connected_to": "Core Switch 1:ge-1/0/7",
                                                                        "rack": "Rack 12"}},
            {"name": "node-8", "table": "cmdb", "aliases": [], "raw": {"connected_to": "Core Switch 1:ge-1/0/8"}},
            {"name": "Main Ledger DB", "table": "cmdb", "aliases": [], "raw": {"runs_on": '["node-8"]'}},
            {"name": "Core Switch 1", "table": "cmdb", "aliases": [], "raw": {"type": "switch"}}]
    inv = I.build(rows)
    monkeypatch.setattr(I, "load", lambda: inv)
    assert I.below(["ledger"]) == ["Node 7", "node-8", "Main Ledger DB", "Core Switch 1"]
    assert I.below(["Ledger Service", "Node 7"]) == ["node-8", "Main Ledger DB", "Core Switch 1"]
    assert "Ledger Service runs on Node 7 (rack Rack 12) (runs_on)" in I.walk(["ledger"])["parts"]["Ledger Service"][
        "stands_on"]
    assert I.below(["nothing-here"]) == []


def _facts(path, text, me, parts=(), hosts=()):
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    n = Names()
    for p in parts:
        n.add_part(p)
    for h in hosts:
        n.hosts[norm(h)] = h
    u = {"ukey": path, "path": path, "kind": "file", "title": path, "text": text, "meta": {}}
    u["found"] = discover(u)
    return {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, me, n, {}) if f["verb"] in ("calls", "runs_on")}


def test_a_traefik_service_s_server_is_that_service_on_its_server(ctx):
    yml = ("---\nhttp:\n  services:\n    quote:\n      loadBalancer:\n        passHostHeader: true\n        servers:\n"
           "          - url: \"http://quote-1.lan.internal:8000\"\n"
           "          - url: \"http://quote-2.lan.internal:8000\"\n"
           "    ledger:\n      loadBalancer:\n        servers:\n        - url: \"http://ledger-1.lan.internal/\"\n")
    got = _facts("files/edge-proxy/rules/services.yml", yml, "edge-proxy", parts=["quote"],
                 hosts=["quote-1.lan.internal", "quote-2.lan.internal", "ledger-1.lan.internal"])
    assert {("edge-proxy", "calls", "quote"), ("quote", "runs_on", "quote-1.lan.internal"),
            ("quote", "runs_on", "quote-2.lan.internal")} <= got
    assert ("edge-proxy", "calls", "quote-1.lan.internal") not in got       # the service's own address: no other end
    assert ("edge-proxy", "calls", "ledger-1.lan.internal") in got          # a service no one knows: as before
    toml = ("[http.services]\n  [http.services.quote.loadBalancer]\n    [[http.services.quote.loadBalancer.servers]]\n"
            "      url = \"http://quote-1.lan.internal:8000/\"\n")
    got = _facts("edge-proxy/dynamic.toml", toml, "edge-proxy", parts=["quote"], hosts=["quote-1.lan.internal"])
    assert ("edge-proxy", "calls", "quote") in got and ("edge-proxy", "calls", "quote-1.lan.internal") not in got
    plain = "backends:\n  quote:\n    servers:\n      - url: \"http://quote-1.lan.internal:8000\"\n"   # no balancer
    got = _facts("app/settings.yml", plain, "shopfront", parts=["quote"], hosts=["quote-1.lan.internal"])
    assert ("edge-proxy", "calls", "quote") not in got and ("shopfront", "calls", "quote") not in got


def _owners(text, parts=()):
    from supagent.knowledge.understand import Names, discover, facts_of

    n = Names()
    for p in parts:
        n.add_part(p)
    u = {"ukey": "p1", "path": "", "kind": "page", "title": "Components", "text": text, "meta": {}}
    u["found"] = discover(u)
    return {(f["subject"], f["obj"]) for f in facts_of(u, None, n, {}) if f["verb"] == "owned_by"}


def test_a_team_column_repeating_the_wholes_team_is_the_wholes_owner(ctx):
    parts = ["quote-api", "quote-ui", "quote-pdf", "ledger-sync", "Quote Desk", "Ledger"]
    table = ("| Component | App | Squad |\n|---|---|---|\n| quote-api | Quote Desk | pricing squad |\n"
             "| quote-ui | Quote Desk | pricing squad |\n| quote-pdf | Quote Desk | pricing squad |\n"
             "| ledger-sync | Ledger | books squad |\n")
    got = _owners(table, parts)
    assert got == {("Quote Desk", "pricing squad"), ("Ledger", "books squad")}   # each component: its app's squad
    own = table.replace("| quote-pdf | Quote Desk | pricing squad |", "| quote-pdf | Quote Desk | print squad |")
    got = _owners(own, parts)                                     # two squads in one app: each row's own owner
    assert ("quote-pdf", "print squad") in got and ("quote-api", "pricing squad") in got
    assert ("Quote Desk", "pricing squad") not in got
    boards = ("| Dashboard | Owning application | Team |\n|---|---|---|\n| quote-api | Quote Desk | pricing squad |\n"
              "| quote-ui | Quote Desk | pricing squad |\n")
    got = _owners(boards, parts)                                  # a table whose rows' whole is not read: as before
    assert got == {("quote-api", "pricing squad"), ("quote-ui", "pricing squad")}


def test_the_group_a_flows_end_runs_on_is_no_second_end_of_the_flow(ctx):
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    n = Names()
    for p in ("edge-router", "quote-api", "ledger-api", "grp-quote", "grp-books"):
        n.add_part(p)
    n.inventory_groups.update({norm("grp-quote"), norm("grp-books")})
    text = ("# Flows\n\nThe edge-router routes to quote-api on grp-quote.\n\n"
            "The ledger-api sends its entries to grp-books.\n")
    u = {"ukey": "p1", "path": "", "kind": "page", "title": "Flows", "text": text, "meta": {}}
    u["found"] = discover(u)
    got = {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, None, n, {})}
    assert ("edge-router", "calls", "quote-api") in got
    assert not [f for f in got if f[0] == "edge-router" and f[2] == "grp-quote"]   # where quote-api runs
    assert ("ledger-api", "sends_to", "grp-books") in got          # a group as the flow's own end: kept


def test_a_database_inside_a_shared_cluster_is_not_put_on_the_clusters_servers(ctx):
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    n = Names()
    for p in ("pg-common-1", "quotes-db", "books-db"):
        n.add_part(p)
    for h in ("dbs-01", "dbs-02", "dbs-03"):
        n.hosts[norm(h)] = h
    text = ("| Database | Engine | Servers | Group |\n|---|---|---|---|\n"
            "| pg-common-1 | PostgreSQL 16 | dbs-01, dbs-02 | pg_common |\n"
            "| quotes-db | PostgreSQL 16 database | dbs-01, dbs-02 | on pg-common-1 |\n"
            "| books-db | PostgreSQL 16 | dbs-03 | pg_books |\n")
    u = {"ukey": "p1", "path": "", "kind": "page", "title": "Data stores", "text": text, "meta": {}}
    u["found"] = discover(u)
    got = {(f["subject"], f["obj"]) for f in facts_of(u, None, n, {}) if f["verb"] == "runs_on"}
    assert {("pg-common-1", "dbs-01"), ("pg-common-1", "dbs-02"), ("books-db", "dbs-03")} <= got
    assert not [x for x in got if x[0] == "quotes-db"]             # the cluster's servers, not its own
