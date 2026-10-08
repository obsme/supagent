"""(0.10) What the documents and the code state, read without an LLM: a repository's own service (its workload) and
its other names, the services it calls, the database it writes (on its host), the cache it reads, the metrics it
registers (as the data names them), a shipper's indices, a scrape job's target, a diagram's arrows, a page's
sentences and tables; each pair of parts one way (the strongest source's), every source kept; units read again only
when their text changes."""

from __future__ import annotations

import pytest

from test_docs_readers import env  # noqa: F401  (the fixture)

LEDGER = {
    "README.md": "# ledger-api\n\nThe ledger service keeps the accounts' entries.\n\n- Metrics: `ledger_entries_total` "
                 "(entries written)\n  and the HTTP histogram `http_request_seconds`.\n",
    "app/clients.py": 'import httpx\nBILLING_URL = "http://billing.apps.svc:8080"\n\n\ndef bill(x):\n'
                      '    return httpx.post(f"{BILLING_URL}/bill", json=x)\n',
    "app/db.py": 'from sqlalchemy import create_engine, text\nENGINE = create_engine("postgresql://ledger:'
                 'not-a-real-pw@db-01:5432/journal")\n\n\ndef save(e):\n    with ENGINE.begin() as c:\n'
                 '        c.execute(text("INSERT INTO entries (id) VALUES (:i)"), {"i": e})\n',
    "app/cache.py": 'import redis\nR = redis.Redis(host="ledger-cache", port=6379)\n\n\ndef last(k):\n'
                    '    return R.get(k)\n',
    "app/metrics.py": 'from prometheus_client import Counter\nENTRIES = Counter("ledger_entries", "entries", ["kind"])\n',
    "deploy/deployment.yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: ledger\n  namespace: apps\n"
                              "spec:\n  template:\n    spec:\n      containers:\n        - name: ledger\n          env:\n"
                              "            - {name: OTEL_SERVICE_NAME, value: ledger-api}\n",
    "docs/flows.md": "# Flows\n\n```mermaid\ngraph LR\n  ledger --> billing\n  billing --> notifier\n```\n",
}
PLATFORM = {
    "fluent-bit/fluent-bit.conf": "[INPUT]\n    Name tail\n    Path /var/log/containers/*_apps_*.log\n\n[OUTPUT]\n"
                                  "    Name opensearch\n    Logstash_Format On\n    Logstash_Prefix applogs\n",
    "prometheus/prometheus.yml": "scrape_configs:\n  - job_name: postgres\n    static_configs: [{targets: ['db-01:9187']}]\n"
                                 "  - job_name: ledger\n    static_configs: [{targets: ['app-host-07:8080']}]\n",
    "k8s/billing.yaml": "apiVersion: apps/v1\nkind: Deployment\nmetadata: {name: billing, namespace: apps}\n",
}


@pytest.fixture()
def world(env, monkeypatch):
    """Two repositories and a wiki page read as documents, the data's names (an index, metrics, hosts)."""
    from superset.extensions import db
    from superset.models.core import Database

    from supagent.knowledge.store import source_for
    from supagent.models import Doc, KFact, KObject, KUnit

    dbo = Database(database_name="logs and metrics", sqlalchemy_uri="promagg://127.0.0.1:1/prometheus")
    db.session.add(dbo)
    db.session.commit()
    src = source_for(dbo)
    objs = [KObject(source_id=src.id, kind="index", parent="", name="applogs-*"),
            KObject(source_id=src.id, kind="metric", parent="", name="ledger_entries_total"),
            KObject(source_id=src.id, kind="metric", parent="", name="pg_up"),
            KObject(source_id=src.id, kind="family", parent="", name="http_request_seconds"),
            KObject(source_id=src.id, kind="label", parent="pg_up", name="instance", stats={"values": ["db-01:9187"]})]
    db.session.add_all(objs)
    docs = []
    for repo, files in (("ledger-api", LEDGER), ("platform", PLATFORM)):
        content, pages, at = [], [], 0
        for path, text in files.items():
            block = f"# {path}\n{text}"
            if content:
                at += 2
            pages.append({"url": f"https://git.example.com/projects/P/repos/{repo}/browse/{path}", "title": path,
                          "chars": len(block), "at": at, "path": path, "commit": "c1"})
            content.append(block)
            at += len(block)
        docs.append(Doc(kind="url", url=f"https://git.example.com/projects/P/repos/{repo}/browse", status="ok",
                        enabled=True, content="\n\n".join(content), pages=pages))
    page = ("ledger calls billing and writes the journal database.\nService | Runs on | Owner\n"
            "Ledger service | app-host-07 | team-books\n")
    docs.append(Doc(kind="url", url="https://wiki.example.com/display/OPS/Ledger", status="ok", enabled=True,
                    content="# Ledger service\n" + page, pages=[{"url": "https://wiki.example.com/x/1", "id": "1",
                    "title": "Ledger service", "chars": len("# Ledger service\n" + page), "at": 0, "links": ["2"]}]))
    db.session.add_all(docs)
    db.session.commit()
    yield docs
    for d in docs:
        db.session.query(KUnit).filter(KUnit.doc_id == d.id).delete()
        db.session.delete(d)
    for o in objs:
        db.session.delete(o)
    db.session.delete(src)
    db.session.delete(dbo)
    db.session.query(KFact).delete()
    db.session.commit()


def _rel(g):
    return {(r["from"], r["kind"], r["to"]): r for r in g["relations"]}


def _data(g):
    return {(r["part"], r["kind"], r["object"]): r for r in g["data_links"]}


def test_what_the_documents_and_the_code_state(world):
    from supagent.knowledge import understand as U

    out = U.run(reason="test")
    assert out["analysed"] == len(LEDGER) + len(PLATFORM) + 1
    g = U.export()
    rel, data = _rel(g), _data(g)
    assert rel[("ledger", "calls", "billing")]["sources"] == ["code", "diagram", "wiki"]        # one pair, one way
    assert ("ledger", "sends_to", "journal") in rel                     # it INSERTs into it
    assert ("journal", "runs_on", "db-01") in rel                       # its URL's host
    assert ("ledger", "reads_from", "ledger-cache") in rel              # a Redis client that only gets
    assert ("billing", "calls", "notifier") in rel                      # the Mermaid diagram's arrows
    assert ("ledger", "runs_on", "app-host-07") in rel                  # the scrape job, and the page's table
    assert ("ledger", "owned_by", "team-books") in rel
    assert {"name": "ledger-api", "part": "ledger"} in g["aliases"]     # its telemetry and README names
    assert ("ledger", "emits", "ledger_entries_total") in data          # prometheus_client adds _total
    assert ("ledger", "emits", "http_request_seconds") in data          # the README's metrics, as the data names them
    assert ("fluent-bit", "writes", "applogs-*") in data                # Logstash_Format On + its prefix
    assert ("billing", "logs_to", "applogs-*") in data                  # its namespace's logs, collected
    assert ("journal", "watched_by", "pg_up") in data                   # the postgres job scrapes the db's host
    assert not any("not-a-real-pw" in (r.get("quote") or "") for r in g["relations"])
    assert [1, 2] in g["wiki_edges"]
    again = U.run(reason="test")
    assert again.get("analysed", 0) == 0 and again["unchanged"] == out["analysed"]   # nothing changed: nothing read


def test_a_unit_is_read_again_when_its_text_changes(world):
    from superset.extensions import db

    from supagent.knowledge import understand as U

    U.run(reason="test")
    d = world[0]
    d.content = d.content.replace("billing.apps.svc", "invoicing.apps.svc")
    d.pages = [dict(p, chars=p["chars"] + (len("invoicing") - len("billing")) if p["path"] == "app/clients.py" else
                    p["chars"], at=p["at"] + (len("invoicing") - len("billing")) if p["at"] > d.pages[1]["at"] else p["at"])
               for p in d.pages]
    db.session.commit()
    out = U.run(reason="test")
    assert out["analysed"] == 1
    assert ("ledger", "calls", "invoicing") in _rel(U.export())


def test_what_is_never_read_as_a_fact(ctx):
    from supagent.knowledge import understand as U

    names = U.Names()
    unit = {"text": '<project xmlns="http://maven.apache.org/POM/4.0.0"><artifactId>books</artifactId></project>',
            "path": "pom.xml", "kind": "file", "meta": {}}
    unit["found"] = U.discover(unit)
    assert not [f for f in U.facts_of(unit, "books", names, {}) if f["verb"] == "calls"]   # a namespace is no call
    q = {"text": "Look at rate(ledger_entries_total[5m]) when it rises.", "path": "runbook.md", "kind": "file",
         "meta": {}}
    q["found"] = U.discover(q)
    names.metrics["ledger_entries_total"] = "ledger_entries_total"
    assert not [f for f in U.facts_of(q, "billing", names, {}) if f["verb"] == "emits"]   # a query is no emission


def test_code_is_cut_at_its_declarations_and_each_piece_says_what_it_is_part_of(world):
    from supagent.knowledge import understand as U
    from supagent.knowledge.index import pieces, split_code

    U.run(reason="test")
    mine = [p for p in pieces(("doc:",)) if p["ref"].startswith(f"doc:{world[0].id}#")]
    db_piece = next(p for p in mine if "app/db.py" in p["title"])
    assert "save" in db_piece["title"]                                  # named by the function it holds
    assert "File app/db.py (python) of " in db_piece["text"] and "the code of ledger." in db_piece["text"]
    code = "import os\n\nX = 1\n\n\n@app.get('/a')\ndef a():\n    return 1\n\n\nclass B:\n    def m(self):\n        pass\n"
    parts = split_code(code, U._outline(code, "python"), size=40)
    assert [name for name, _t in parts] == ["", "a", "B, m"]   # (a method: a boundary, merged while small) and parts[1][1].startswith("@app.get('/a')")
