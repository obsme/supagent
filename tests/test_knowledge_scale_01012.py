"""(0.10.12) The work after a save follows what was saved, not the whole knowledge: the knowledge store reads the
pieces of the kinds a save changed (a learned answer, an entry, one document), never every piece of a wiki of
thousands of pages; a document's own pieces are its scope. A repository of scripts, custom folders and libraries is read
(its code by default, its scripts without an extension known by their #! line); a wiki of thousands of pages is
summarized by its central pages and the relations its pages state, not by its first page."""
from __future__ import annotations

from test_docs_readers import env, servers  # noqa: F401  (the fixtures)


def test_the_store_reads_only_the_kinds_saved(ctx):
    from superset.extensions import db

    from supagent.knowledge import pgstore
    from supagent.models import Chunk

    rows = [Chunk(ref=r, kind=r.split(":")[0], title=r, text=f"text of {r}", content_hash=r)
            for r in ("recipe:98801", "recipe:98802", "entry:98807", "doc:98803#a", "doc:98803#b", "doc:988031#a",
                      "doc:98803_x#a", "memory:98804")]
    db.session.add_all(rows)
    db.session.commit()
    try:
        def refs(prefixes):
            return sorted(r["ref"] for r in pgstore._chunk_rows(None, prefixes) if r["ref"] in {c.ref for c in rows})

        assert refs(("recipe:",)) == ["recipe:98801", "recipe:98802"]
        assert refs(("doc:98803#",)) == ["doc:98803#a", "doc:98803#b"]        # not doc:988031, not doc:98803_x
        assert refs(("entry:", "memory:")) == ["entry:98807", "memory:98804"]
        assert len(refs(None)) == len(rows)                                     # no scope: every piece
        assert pgstore._like("doc:3_x%") == "doc:3\\_x\\%%"
    finally:
        for c in rows:
            db.session.delete(c)
        db.session.commit()


def test_a_document_write_gives_the_store_its_own_scope(ctx, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import index
    from supagent.models import Chunk

    seen = []
    monkeypatch.setattr(index, "_store_sync", lambda prefixes: seen.append(prefixes))
    monkeypatch.setattr(index, "pieces", lambda prefixes=None: iter([
        {"ref": "doc:9#p1", "kind": "doc", "title": "Page one", "text": "new text"}]))
    old = Chunk(ref="doc:9#p2", kind="doc", title="Page two", text="gone", content_hash="x")
    db.session.add(old)
    db.session.commit()
    try:
        out = index.sync(("doc:9#",))
        assert out["added"] == 1 and out["removed"] == 1
        assert seen == [("doc:9#",)]                     # one document: the store reads its pieces, not every doc:
    finally:
        db.session.query(Chunk).filter(Chunk.ref.like("doc:9#%")).delete(synchronize_session=False)
        db.session.commit()


# --------------------------------------------------------------------------------------------- #
# repositories of scripts, custom folders and libraries
# --------------------------------------------------------------------------------------------- #
def test_the_scripts_and_libraries_of_a_repository_are_read():
    from supagent.knowledge import docs as D

    for path in ("ops/backup", "deploy/run-all", "lib/custom/helpers.py", "libs/net/util.pl", "build/deploy.sh",
                 "puppet/site.pp", "salt/top.sls", "jobs/cleanup.ksh", "db/schema.ddl", "cron/rotate"):
        assert D.wanted_file(path, "code"), path
    for path in ("build/classes/App.class", "build/lib/pkg/mod.py", "vendor/lib/a.go", "LICENSE", "ops/CHANGELOG",
                 "ops/id_rsa", "ops/secret-token", "node_modules/x/index.js"):
        assert not D.wanted_file(path, "code"), path
    assert not D.wanted_file("ops/backup", "docs")                     # the documentation only: no code
    assert D.maybe_script("ops/backup") and not D.maybe_script("scripts/rotate")   # bin/, scripts/: scripts anyway
    assert D.shebang_kept("ops/backup", "#!/bin/bash\nrsync -a /data /backup\n")
    assert not D.shebang_kept("ops/data", "1,2,3\n4,5,6\n")             # no #!: not a script, not kept
    assert D.shebang_kept("scripts/rotate", "logrotate -f /etc/logrotate.conf\n")


def test_a_repository_without_documentation_has_its_code_read(env, servers):
    from test_docs_0961 import Repo

    from supagent.knowledge import docs as D

    repo = Repo({"ops/backup": "#!/bin/bash\nrsync -a /srv/app db-01:/backup\n", "ops/notes": "1,2,3\n",
                 "lib/net/check.py": "def ping(host):\n    return host\n", "build/ci.sh": "#!/bin/sh\nmake test\n"}, "c1")
    s = servers(repo.route)
    d = _doc_with(s, {"type": "bearer", "files": "docs"})               # documentation asked: there is none
    out = D.refresh(d)
    assert out["status"] == "ok", out
    assert sorted(p["path"] for p in d.pages) == ["build/ci.sh", "lib/net/check.py", "ops/backup"]   # not ops/notes
    assert "rsync -a /srv/app db-01:/backup" in d.content
    d2 = _doc_with(s, {"type": "bearer"})                                # nothing said: the code too (0.10.12)
    assert D.files_of(d2) == "code" and D.refresh(d2)["status"] == "ok"


def _doc_with(s, auth):
    from test_docs_readers import SECRET, _doc

    return _doc(f"{s.base}/bb/projects/OPS/repos/app/browse", max_pages=50, auth=auth, secret=SECRET)


# --------------------------------------------------------------------------------------------- #
# the Context summary of a wiki of thousands of pages
# --------------------------------------------------------------------------------------------- #
def _wiki(n: int) -> dict:
    texts, pages, at = [], [], 0
    for i in range(n):
        body = f"Page {i} of the operations wiki. " + ("Billing runs on cluster-a and calls ledger. " if i == 4321 else
                                                         f"Routine notes number {i}. ") * 5
        block = f"# Page {i}\n{body}"
        if texts:
            at += 2
        links = ["4321"] if i % 3 == 0 and i != 4321 else []           # most pages link to page 4321
        pages.append({"id": str(i), "title": f"Page {i}", "space": "OPS", "at": at, "chars": len(block),
                      "links": links})
        texts.append(block)
        at += len(block)
    return {"id": 1, "title": "Operations wiki", "content": "\n\n".join(texts), "pages": pages}


def test_a_wiki_is_summarized_by_its_central_pages_not_its_first_one():
    from supagent.knowledge import context as C

    d = _wiki(5000)
    out = C._digest(d, 12000)
    assert len(out) <= 12000 and out.startswith("5000 pages (spaces: OPS)")
    first = out.splitlines()[1]
    assert first.startswith("- Page 4321 (1667 pages link to it): ") and "calls ledger" in first   # the hub first
    small = {"id": 2, "title": "Runbook", "content": "Short runbook text.", "pages": []}
    assert C._digest(small, 3000) == "Short runbook text."


def test_the_summaries_get_the_relations_the_documents_state(ctx):
    from superset.extensions import db

    from supagent.knowledge import context as C
    from supagent.models import Doc, KFact, KUnit

    doc = Doc(kind="url", url="https://wiki.example.com/ops", title="Operations wiki", status="ok", enabled=True,
              content="x", pages=[])
    db.session.add(doc)
    db.session.flush()
    units = []
    for i in range(3):
        u = KUnit(doc_id=doc.id, ukey=f"p{i}", kind="page", title=f"Page {i}")
        db.session.add(u)
        db.session.flush()
        units.append(u)
    for u in units:
        db.session.add(KFact(unit_id=u.id, subject="Billing", verb="calls", obj="Ledger", source="wiki"))
    db.session.add(KFact(unit_id=units[0].id, subject="Ledger", verb="runs_on", obj="cluster-a", source="wiki"))
    db.session.add(KFact(unit_id=units[1].id, subject="Billing", verb="mentions", obj="Ledger", source="wiki"))
    db.session.commit()
    try:
        rels = C._part_relations()
        assert rels[:2] == [{"a": "Billing", "verb": "calls", "b": "Ledger", "pages": 3},
                            {"a": "Ledger", "verb": "runs_on", "b": "cluster-a", "pages": 1}]
        assert C._relation_lines(rels[:2]) == ["Billing calls Ledger (3 pages)", "Ledger runs on cluster-a (1 page)"]
        ev = {"databases": {}, "inventory": {}, "relations": [], "entries": [], "answers": [], "memory": [],
              "docs": [_wiki(5000)], "part_relations": rels}
        specs = {s["slug"]: s for s in C.summary_specs(ev)}
        evidence = specs["overview"]["evidence"]
        stated = [e for e in evidence if e["ref"] == "facts"]
        assert stated and "Billing calls Ledger (3 pages)" in stated[0]["relations"]
        doc_text = [e for e in evidence if e["ref"] == "doc:1"][0]["text"]
        assert doc_text.startswith("5000 pages") and "Page 4321" in doc_text and len(doc_text) <= C.DOCS_CHARS
    finally:
        db.session.query(KUnit).filter(KUnit.doc_id == doc.id).delete(synchronize_session=False)
        db.session.delete(doc)
        db.session.commit()
