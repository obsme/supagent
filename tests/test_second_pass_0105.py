"""(0.10.5) A second learning over the map the first made, every proposal approved and no document changed, proposes
nothing and removes nothing: the servers a person approved stay servers (no page's subject, no part, no group renamed
"(group)"), a table's "Target Group" says where a role runs (its "all": every server, no value), a server named after
its service hides no part's name, "(... on host)" reads the hosts in its brackets only, both ways stated is no link
reversed, a commented target is scraped by no one, a diagram's "Services" box is no part, and a playbook written as
a stream of YAML documents is read. A learned link whose words are still in a document is never proposed for removal
(the reading moved, not the documents); once the document drops them, its removal is proposed."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_prose_010 import facts

REPO = {
    "inventories/production/hosts": "[zqcache]\nzqcache-1 ansible_host=10.9.0.5\n\n[zqapp]\nzqapp-1 ansible_host=10.9.0.7\n"
                                    "\n[zqmon]\nzqmon-1 ansible_host=10.9.0.8\n",
    "playbooks/site.yml": "---\n# the platform's playbook\n---\n- hosts: zqcache\n  roles: [zqredis]\n\n- hosts: zqapp\n"
                          "  roles: [zqorders]\n\n- hosts: zqmon\n  roles: [prometheus]\n\n- hosts: all\n"
                          "  roles: [node_exporter]\n",
    "roles/zqorders/templates/zqorders.env.j2": "# the orders service\nREDIS_URL=redis://zqcache-1:6379/0\n",
    "roles/prometheus/templates/prometheus.yml.j2": "scrape_configs:\n  - job_name: node\n    static_configs:\n"
                                                    "      - targets: ['zqapp-1:9100', 'zqcache-1:9100']\n"
                                                    "#      - targets: ['zqold-1:9100']\n",
    "README.md": "# Ops\n\n| Role | Target Group | Notes |\n|---|---|---|\n| zqredis | zqcache | sessions |\n"
                 "| zqorders | zqapp | the orders API |\n| node_exporter | all | host metrics |\n",
}


def _repo(files, name="zqops"):
    from superset.extensions import db

    from supagent.models import Doc

    content, pages, at = [], [], 0
    for path, text in files.items():
        block = f"# {path}\n{text}"
        if content:
            at += 2
        pages.append({"url": f"https://git.example.com/projects/P/repos/{name}/browse/{path}", "title": path,
                      "chars": len(block), "at": at, "path": path, "commit": "c1"})
        content.append(block)
        at += len(block)
    d = Doc(kind="url", url=f"https://git.example.com/projects/P/repos/{name}/browse", status="ok", enabled=True,
            content="\n\n".join(content), pages=pages)
    db.session.add(d)
    db.session.commit()
    return d


def _state():
    from superset.extensions import db

    from supagent.models import Facet, Link

    return {i for (i,) in db.session.query(Facet.id)}, {i for (i,) in db.session.query(Link.id)}


def _clean(before, docs):
    from superset.extensions import db

    from supagent.models import Doc, Facet, KFact, KUnit, Link

    db.session.rollback()
    facets, links = before
    db.session.query(Link).filter(Link.id.notin_(links or {-1})).delete(synchronize_session=False)
    db.session.query(Facet).filter(Facet.id.notin_(facets or {-1})).delete(synchronize_session=False)
    for d in docs:
        units = db.session.query(KUnit.id).filter(KUnit.doc_id == d.id)
        db.session.query(KFact).filter(KFact.unit_id.in_(units)).delete(synchronize_session=False)
        db.session.query(KUnit).filter(KUnit.doc_id == d.id).delete(synchronize_session=False)
        db.session.query(Doc).filter(Doc.id == d.id).delete(synchronize_session=False)
    db.session.commit()


def _approve_all():
    from superset.extensions import db

    from supagent.models import Facet, Link

    for f in db.session.query(Facet).filter(Facet.status == "proposed"):
        f.status = "approved"
    for x in db.session.query(Link).filter(Link.status == "proposed"):
        x.status = "approved"
    db.session.commit()


def test_a_second_learning_over_the_approved_map_proposes_and_removes_nothing(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet, Link

    before, d = _state(), _repo(REPO)
    try:
        U.run(reason="test")
        first = propose()
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert ("zqredis", "runs_on", "zqcache (zqops production)") in rels and \
            ("zqorders", "runs_on", "zqapp (zqops production)") in rels   # the stream read (0.10.6.2: an inventory
        #                                                       kept in an environment's folder: its groups are that one's)
        assert not any(k == "runs_on" and b == "all" for _a, k, b in rels)          # "all": every server, no value
        assert not any(b == "zqold-1" for _a, _k, b in rels)                        # a commented target
        assert first["values"] and first["links"]
        _approve_all()
        values = {(f.facet, f.value) for f in db.session.query(Facet)}
        U.run(reason="test")
        again = propose()
        assert (again["values"], again["links"], again["removals"]) == (0, 0, 0), again
        assert {(f.facet, f.value) for f in db.session.query(Facet)} == values      # no "(group)" renamed
        assert not db.session.query(Link).filter(Link.proposed_drop.isnot(None)).count()
    finally:
        _clean(before, [d])


def test_a_learned_link_still_written_is_kept_and_proposed_for_removal_once_its_document_drops_it(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose, still_written
    from supagent.models import Doc, Facet, Link

    from supagent.knowledge.proposals import STATE_KEY
    from supagent.models import Meta

    db.session.query(Meta).filter(Meta.key == STATE_KEY).delete(synchronize_session=False)   # (another test's count
    before = _state()                                                    # of facts: "fewer than before", nothing done)
    text = "Notes. The zqledger hands the day's totals to zqbooks every night, by a path nobody reads.\n"
    d = Doc(kind="upload", title="zq notes", enabled=True, status="ok", content=text)
    db.session.add(d)
    a = Facet(facet="application", value="zqledger", status="approved", source="docs")
    b = Facet(facet="application", value="zqbooks", status="approved", source="docs")
    db.session.add_all([a, b])
    db.session.flush()
    x = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind="sends_to", status="approved", source="docs",
             evidence="The zqledger hands the day's totals to zqbooks every night, by a path nobody reads. "
                      "(zq notes; doc)")
    db.session.add(x)
    db.session.commit()
    try:
        assert still_written(x.evidence) and not still_written("zqledger never wrote this sentence anywhere (x; doc)")
        U.run(reason="test")
        out = propose()
        assert db.session.get(Link, x.id).proposed_drop is None and out.get("still written", 0) >= 1
        d.content = "Notes. The day's totals are no longer handed over.\n"           # the document drops the words
        db.session.commit()
        U.run(reason="test")
        propose()
        assert "no document nor code states it any more" in (db.session.get(Link, x.id).proposed_drop or "")
    finally:
        _clean(before, [d])


def test_both_ways_stated_is_no_link_reversed(env):  # noqa: F811
    from superset.extensions import db

    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Doc, Facet, Link

    before = _state()
    d = Doc(kind="upload", title="zq flows", enabled=True, status="ok",
            content="The zqfront service calls zqback for the prices. zqback calls zqfront back for the sessions.\n")
    db.session.add(d)
    a = Facet(facet="application", value="zqfront", status="approved", source="docs")
    b = Facet(facet="application", value="zqback", status="approved", source="docs")
    db.session.add_all([a, b])
    db.session.flush()
    there = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind="calls", status="approved", source="docs")
    back = Link(a_ref=f"facet:{b.id}", b_ref=f"facet:{a.id}", kind="calls", status="approved", source="docs")
    db.session.add_all([there, back])
    db.session.commit()
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"]) for r in U.export()["relations"]}
        assert ("zqfront", "calls", "zqback") in rels and ("zqback", "calls", "zqfront") in rels
        propose()
        assert db.session.get(Link, there.id).proposed_drop is None
        assert db.session.get(Link, back.id).proposed_drop is None
    finally:
        _clean(before, [d])


def test_servers_are_where_parts_run_never_what_a_sentence_is_about(ctx):
    from supagent.knowledge.understand import EVERY_SERVER, Names, _page_owner, norm

    n = Names()
    n.hosts[norm("storage")] = "storage"                                           # an approved group of servers
    n.add_part("prometheus")
    assert n.part("storage") == "storage" and n.service("storage") is None
    assert _page_owner("storage Prometheus", n, {}) == "prometheus"
    assert all(EVERY_SERVER.fullmatch(x) for x in ("all", "All hosts", "every node", "*", "all (prod)"))
    assert not any(EVERY_SERVER.fullmatch(x) for x in ("allure", "alloy", "all-1"))
    # a server named after its service hides no part's name; "(... on host)" reads the hosts in its brackets only
    t = facts("The media relays (sfu) run on sfu-node-01 and sfu-node-02.", hosts=("sfu-node-01", "sfu-node-02"),
              parts=("sfu",))
    assert {("sfu", "runs_on", "sfu-node-01"), ("sfu", "runs_on", "sfu-node-02")} <= t
    t = facts("```mermaid\ngraph LR\n  lb[HAProxy on lb1] --> web\n  web --> db[(shopdb on dbsrv1)]\n  web --> web1\n```\n",
              hosts=("dbsrv1", "lb1", "web1"), parts=("db", "web"))
    assert ("db", "runs_on", "dbsrv1") in t and not any(a == "db" and b in ("lb1", "web1") for a, _k, b in t)
    t = facts("```mermaid\ngraph LR\n  A[Services] -->|OTLP| B[OTel Collector]\n```\n", parts=("otel-collector",))
    assert not any("Services" in (a, b) for a, _k, b in t)                        # a box for every service


def test_a_stream_of_yaml_documents_is_read(ctx):
    from supagent.knowledge.projects import _yaml

    assert _yaml("---\n# the playbook\n---\n- hosts: web\n  roles: [nginx]\n") == [{"hosts": "web", "roles": ["nginx"]}]
    assert _yaml("- hosts: a\n  roles: [x]\n---\n- hosts: b\n  roles: [y]\n") == [{"hosts": "a", "roles": ["x"]},
                                                                                  {"hosts": "b", "roles": ["y"]}]
    assert _yaml("a: 1\n") == {"a": 1} and _yaml("# nothing\n") is None and _yaml("a: [") is None


def test_a_denial_stays_in_its_clause(ctx):
    t = facts("Orders never talk to a database directly: they ask quotes.", parts=("orders", "quotes"))
    assert ("orders", "calls", "quotes") in t and ("orders", "not_calls", "quotes") not in t
    t = facts("The billing job never calls stripe any more; it calls payfast.", parts=("billing-job", "stripe", "payfast"))
    assert ("billing-job", "not_calls", "stripe") in t and not any(o == "payfast" for _s, v, o in t if v.startswith("not_"))


def test_a_commented_target_is_scraped_by_no_one_and_each_target_is_quoted_on_its_line(ctx):
    from supagent.knowledge.understand import Names, discover, facts_of

    text = ("scrape_configs:\n  # the server itself\n  - job_name: 'prometheus'\n    static_configs:\n"
            "      - targets: ['localhost:9090']\n  # every server\n  - job_name: 'node'\n    static_configs:\n"
            "      - targets: ['app-1:9100']\n#      - targets: ['old-1:9100']\n")
    u = {"ukey": "f1", "path": "prometheus/prometheus.yml", "kind": "file", "title": "prometheus.yml", "text": text,
         "meta": {}}
    u["found"] = discover(u)
    got = facts_of(u, None, Names(), {})
    t = {(f["subject"], f["verb"], f["obj"]) for f in got}
    assert ("node", "scrapes", "app-1") in t and not any(o in ("old-1", "localhost") for _s, _v, o in t)
    assert "app-1:9100" in next(f for f in got if f["obj"] == "app-1")["quote"]
