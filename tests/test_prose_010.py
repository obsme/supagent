"""(0.10) A team's pages read without an LLM: a sentence holding a dotted name (a host's, a file's) kept whole, every
host a part runs on, "a part on its hosts", the passive voice, a part named in two words, what watches what (only
with its subject named), a diagram's box with words around its part, a table's empty cell, a platform no host."""

from __future__ import annotations


def facts(text, hosts=(), parts=(), kind="page", title="Platform"):
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    n = Names()
    for h in hosts:
        n.hosts[norm(h)] = h
    own = {norm(p): p for p in parts}
    u = {"ukey": "p1", "path": "", "kind": kind, "title": title, "text": text, "meta": {}}
    u["found"] = discover(u)
    return {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, None, n, own)}


def test_a_sentence_with_a_dotted_name_is_read_whole(ctx):
    from supagent.knowledge.understand import _sentences

    got = [s for _a, s in _sentences("The agent runs on app-1 and ships the logs to the collector on logs.example.net "
                                     "(port 5044). Version 2.0.1 is deployed.")]
    assert got[0].startswith("The agent runs on app-1") and got[1] == "Version 2.0.1 is deployed."


def test_every_host_of_a_list_and_a_part_on_its_hosts(ctx):
    t = facts("The shipper runs on app-1, app-2 and app-3 and ships the logs to the collector on logs-01.",
              hosts=("app-1", "app-2", "app-3", "logs-01"), parts=("shipper", "collector"))
    assert {("shipper", "runs_on", "app-1"), ("shipper", "runs_on", "app-3"), ("shipper", "sends_to", "collector"),
            ("collector", "runs_on", "logs-01")} <= t
    assert ("shipper", "runs_on", "logs-01") not in t
    t = facts("The routers on node-1 and node-2 send queries to the index.", hosts=("node-1", "node-2"),
              parts=("routers", "index"))
    assert ("routers", "runs_on", "node-2") in t


def test_the_passive_voice_and_a_name_in_two_words(ctx):
    t = facts("The settled orders are published by the order writer to the archive (vault-db). "
              "The dashboard is read by the report builder. The portal is published by the proxy.",
              parts=("orderwriter", "vault-db", "dashboard", "report-builder", "portal", "proxy"))
    assert ("orderwriter", "sends_to", "vault-db") in t
    assert ("report-builder", "reads_from", "dashboard") in t
    assert ("proxy", "calls", "portal") in t


def test_what_watches_what_only_with_its_subject(ctx):
    t = facts("The prober also checks the payment backends. Check the cache before a restart.",
              parts=("prober", "payment", "cache"))
    assert ("prober", "monitors", "payment") in t
    assert not any(v == "monitors" and o == "cache" for _s, v, o in t)


def test_a_diagram_box_names_its_part_and_users_are_no_part(ctx):
    text = ("```mermaid\nflowchart LR\n  users[Customers] --> lb[Balancer on lb-1]\n  lb --> app[shop: app-1, app-2]\n"
            "  app --> db[(orders on db-1)]\n```\n")
    t = facts(text, hosts=("lb-1", "app-1", "app-2", "db-1"), parts=("balancer", "shop"))
    assert ("balancer", "calls", "shop") in t and ("shop", "calls", "orders") in t or \
        ("shop", "uses", "orders") in t
    assert not any(s == "Customers" or o == "Customers" for s, _v, o in t)


def test_a_tables_empty_cell_and_a_platform(ctx):
    text = ("Service | Runs on | Calls | Owner\n--- | --- | --- | ---\nindexer | idx-01 |  | team-a\n"
            "api | Kubernetes (prod) | indexer | team-b\nbatch | vm-batch-01 | | team-c\n")
    t = facts(text, hosts=("idx-01", "vm-batch-01"), parts=("indexer", "api", "batch"))
    assert ("indexer", "runs_on", "idx-01") in t and ("api", "calls", "indexer") in t
    assert ("batch", "runs_on", "vm-batch-01") in t                    # a host's name starting with vm-
    assert not any(o.lower().startswith(("kubernetes", "| team", "team-")) for _s, v, o in t if v != "owned_by")


def test_the_object_of_a_verb_is_no_subject_and_documentation_is_no_call(ctx):
    t = facts("The second server runs an Nginx webserver and pushes the access logs into the index.",
              parts=("nginx", "index"))
    assert not any(s == "nginx" for s, _v, _o in t)
    from supagent.knowledge.understand import DOC_HOSTS

    for host in ("docs.example.org", "github.com", "bugs.launchpad.net", "raw.githubusercontent.com"):
        assert DOC_HOSTS.search(host), host
    for host in ("api.github.com", "payments.internal", "orders-db"):
        assert not DOC_HOSTS.search(host), host
