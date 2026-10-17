"""(0.11.0) The final release's smaller requests: the Servers card shows the disk Superset is on; the learning's
history purged after its days; backups cleaned by count and age (and the files a stopped backup left); a backup
restored from a file brought from elsewhere; To review warns of duplicates."""
from __future__ import annotations

import os


def test_the_disk_shown_is_the_one_superset_is_on(monkeypatch, tmp_path):
    from supagent import hoststats as H

    mounts = [("/dev/sda1", "/", "ext4"), ("/dev/sdb1", "/data", "xfs"), ("tmpfs", "/run", "tmpfs"),
              ("/dev/sdc1", "/data/archive", "xfs")]
    assert H._mount_of("/data/superset/home", mounts) == "/data"
    assert H._mount_of("/data/archive/x", mounts) == "/data/archive"
    assert H._mount_of("/data", mounts) == "/data" and H._mount_of("/database", mounts) == "/"
    assert H._mount_of("/opt/venv", mounts) == "/"
    monkeypatch.setenv("SUPERSET_HOME", str(tmp_path))
    disks = H._disks()
    assert 1 <= len(disks) <= 2
    holds = [w for d in disks for w in d["holds"]]
    assert sorted(holds) == sorted(["Superset's home", "its installation"])
    for d in disks:
        assert d["total"] > 0 and 0 <= d["pct"] <= 100 and d["free"] <= d["total"]


def test_the_learning_history_is_kept_for_its_days(ctx):
    import datetime as dt

    from superset.extensions import db

    from supagent.knowledge.history import purge
    from supagent.models import Change, Run

    now = dt.datetime.utcnow()
    made = [Run(kind="learn", status="done", started_at=now - dt.timedelta(days=50), finished_at=now - dt.timedelta(days=50)),
            Run(kind="learn", status="done", started_at=now - dt.timedelta(days=40), finished_at=now - dt.timedelta(days=40)),
            Run(kind="learn", status="done", started_at=now - dt.timedelta(days=2), finished_at=now - dt.timedelta(days=2)),
            Run(kind="zzbackup", status="done", started_at=now - dt.timedelta(days=90), finished_at=now - dt.timedelta(days=90)),
            Run(kind="learn", status="running", started_at=now - dt.timedelta(days=60))]
    db.session.add_all(made)
    db.session.commit()
    db.session.add(Change(run_id=made[0].id, change="new", detail={}, at=now - dt.timedelta(days=50)))
    db.session.add(Change(run_id=made[2].id, change="new", detail={}, at=now - dt.timedelta(days=2)))
    db.session.commit()
    ids = [r.id for r in made]
    try:
        assert purge(0) == {"runs": 0, "changes": 0}                            # 0: kept for ever
        out = purge(30)
        left = {r.id for r in db.session.query(Run).filter(Run.id.in_(ids))}
        assert ids[0] not in left and ids[1] not in left                       # finished 50 and 40 days ago
        assert ids[2] in left                                                  # two days ago
        assert ids[3] in left                                                  # the last of its kind, however old
        assert ids[4] in left                                                  # still going: never removed
        assert out["runs"] >= 2 and out["changes"] >= 1
        assert db.session.query(Change).filter(Change.run_id == ids[2]).count() == 1
    finally:
        db.session.query(Change).filter(Change.run_id.in_(ids)).delete(synchronize_session=False)
        db.session.query(Run).filter(Run.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()


def test_backups_are_cleaned_by_number_and_age(ctx, tmp_path):
    import datetime as dt
    import time

    from supagent import settings
    from supagent.knowledge import backup

    settings.set_value("backup.dir", str(tmp_path))
    try:
        now = dt.datetime(2026, 10, 17, 12, 0, 0)
        names = [f"supagent-knowledge-{(now - dt.timedelta(days=d)):%Y%m%d-%H%M%S}.zip" for d in (0, 5, 20, 31, 45)]
        for n in names + ["supagent-knowledge-20260901-010000-before-restore.zip"]:
            (tmp_path / n).write_bytes(b"x")
        left = tmp_path / "supagent-knowledge-20261016-010000.zip.part"
        left.write_bytes(b"x")
        old = time.time() - 2 * 86400
        os.utime(left, (old, old))
        fresh = tmp_path / "supagent-knowledge-20261017-115900.zip.part"           # a backup being written now
        fresh.write_bytes(b"x")
        settings.set_value("backup.keep", 14)
        settings.set_value("backup.keep_days", 30)
        gone = set(backup.prune(now))
        assert gone == {names[3], names[4], "supagent-knowledge-20260901-010000-before-restore.zip", left.name}
        assert fresh.exists() and (tmp_path / names[0]).exists() and (tmp_path / names[2]).exists()
        settings.set_value("backup.keep", 1)
        assert set(backup.prune(now)) == {names[1], names[2]}                    # by number: the newest stays
        settings.set_value("backup.keep_days", 1)
        assert backup.prune(now + dt.timedelta(days=400)) == []                  # the newest is always kept
    finally:
        for k in ("backup.dir", "backup.keep", "backup.keep_days"):
            settings.set_value(k, None)


def test_a_backup_brought_from_elsewhere_is_kept_only_when_it_is_one(ctx, tmp_path):
    import io
    import json
    import zipfile

    import pytest

    from supagent import settings
    from supagent.knowledge import backup
    from supagent.models import SCHEMA_VERSION

    settings.set_value("backup.dir", str(tmp_path))
    try:
        good = io.BytesIO()
        with zipfile.ZipFile(good, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": 1, "schema": SCHEMA_VERSION, "supagent": "0.10.12",
                                                    "created_at": "2026-10-10T01:00:00",
                                                    "parts": {"memory": {"supagent_memory": 3}}}))
            z.writestr("memory/supagent_memory.jsonl", "")
        good.seek(0)
        saved = backup.save_upload(good, "mine.zip")
        assert backup.NAME.match(saved["name"]) and saved["name"].endswith("-uploaded.zip")
        assert saved["parts"] == {"memory": 3} and backup.path_of(saved["name"])
        assert [b["name"] for b in backup.listing()] == [saved["name"]]
        with pytest.raises(ValueError):
            backup.save_upload(io.BytesIO(b"not a zip at all"), "x.zip")
        later = io.BytesIO()
        with zipfile.ZipFile(later, "w") as z:
            z.writestr("manifest.json", json.dumps({"format": 99, "schema": SCHEMA_VERSION + 5, "parts": {"memory": {}}}))
        later.seek(0)
        with pytest.raises(ValueError, match="later version"):
            backup.save_upload(later, "new.zip")
        with pytest.raises(ValueError, match="larger"):
            backup.save_upload(io.BytesIO(b"x" * 3000), "big.zip", limit=1000)
        assert sorted(p.name for p in tmp_path.iterdir()) == [saved["name"]]   # nothing else kept
    finally:
        settings.set_value("backup.dir", None)


def test_usage_buckets_follow_summer_time():
    import datetime as dt
    from zoneinfo import ZoneInfo

    from supagent.knowledge.usage import _bucket, _zone

    paris, plus2 = _zone("Europe/Paris"), dt.timedelta(minutes=120)
    assert _zone("Not/AZone") is None and _zone("") is None
    assert _bucket(dt.datetime(2026, 10, 24, 22, 30), "hour", plus2, paris) == "2026-10-25 00:00"   # CEST
    assert _bucket(dt.datetime(2026, 10, 25, 2, 30), "hour", plus2, paris) == "2026-10-25 03:00"    # CET since 01:00 UTC
    assert _bucket(dt.datetime(2026, 10, 25, 2, 30), "hour", plus2) == "2026-10-25 04:30"[:13] + ":00"  # the offset alone
    assert isinstance(paris, ZoneInfo)


def test_to_review_warns_of_duplicates(ctx):
    from superset import security_manager
    from superset.extensions import db

    from supagent.knowledge.lint import duplicates
    from supagent.knowledge.memory import add
    from supagent.models import Entry, Memory, Recipe

    user = security_manager.find_user("admin") or db.session.query(security_manager.user_model).first()
    mems = [Memory(user_id=user.id, scope="user", kind="preference", status="active", source="manual",
                   text="Give the durations of the batch jobs in minutes"),       # copies made by edits, imports,
            Memory(user_id=user.id, scope="user", kind="preference", status="active", source="manual",   # restores
                   text="Always give the durations of the batch jobs in minutes, please."),
            Memory(user_id=user.id, scope="user", kind="preference", status="active", source="manual",
                   text="Give the durations of the batch jobs in seconds"),
            Memory(user_id=None, scope="team", kind="rule", status="active", source="manual",
                   text="Count the refunds of the web shop apart"),
            Memory(user_id=user.id, scope="user", kind="rule", status="active", source="manual",
                   text="count the refunds of the web shop apart.")]
    db.session.add_all(mems)
    db.session.commit()
    ents = [Entry(title="Refund rule", classification="rule", content="Count the refunds of the shop apart from the sales",
                  enabled=True, version=1),
            Entry(title="Refund rule", classification="rule", content="Count the refunds of the shop apart from the sales",
                  enabled=True, version=1)]
    recs = [Recipe(question="How many orders yesterday?", query="SELECT count(*) FROM orders", status="helpful",
                   tool="execute_sql", database_id=1, uses=3),
            Recipe(question="Orders of yesterday, how many?", query="select  COUNT(*) from orders", status="confirmed",
                   tool="execute_sql", database_id=1, uses=1)]
    db.session.add_all(ents + recs)
    db.session.commit()
    try:
        ws = duplicates()
        copies = [w for w in ws if w["subject"].startswith("memory said") and f"memory:{mems[0].id}" in w["refs"]]
        assert len(copies) == 1 and copies[0]["remove"][0]["memory"] == mems[1].id     # the newer is the copy
        alike = [w for w in ws if w["subject"] == "alike memories" and f"memory:{mems[2].id}" in w["refs"]]
        assert alike and "remove" not in alike[0]                                         # another unit: a person decides
        team = [w for w in ws if w["subject"].startswith("memory said") and f"memory:{mems[3].id}" in w["refs"]]
        assert team and team[0]["remove"][0]["memory"] == mems[4].id                      # a person's copy of the team's
        ent = [w for w in ws if w["subject"].startswith("entry said")]
        assert ent and ent[0]["remove"][0]["entry"] == ents[1].id
        assert ent[0]["remove"][0]["values"]["enabled"] is False and ent[0]["remove"][0]["values"]["title"] == "Refund rule"
        rec = [w for w in ws if w["subject"] == "learned answer said twice"]
        assert rec and rec[0]["remove"][0]["recipe"] == recs[0].id                       # the confirmed one is kept
    finally:
        db.session.query(Memory).filter(Memory.id.in_([m.id for m in mems])).delete(synchronize_session=False)
        db.session.query(Entry).filter(Entry.id.in_([e.id for e in ents])).delete(synchronize_session=False)
        db.session.query(Recipe).filter(Recipe.id.in_([r.id for r in recs])).delete(synchronize_session=False)
        db.session.commit()


def test_a_summary_page_ends_with_the_relations_the_documents_state(ctx):
    import types

    from supagent.knowledge.context import DIAGRAM_HEAD, diagram_block, write_summary

    rels = [{"a": "web-shop", "verb": "calls", "b": "checkout-api", "pages": 9},
            {"a": "checkout-api", "verb": "reads_from", "b": "orders-db", "pages": 4},
            {"a": "checkout-api", "verb": "reads_from", "b": "orders-db", "pages": 1},      # said again: once
            {"a": "a -> b", "verb": "calls", "b": "x", "pages": 1},                          # never a broken line
            {"a": "checkout-api", "verb": "reads_from", "b": "orders-db (prod)", "pages": 1}]   # the same part
    block = diagram_block(rels)
    assert block.startswith("```text\n" + DIAGRAM_HEAD + "\n") and block.endswith("\n```")
    assert "web-shop -> checkout-api : calls" in block and "checkout-api -> orders-db : reads from" in block
    assert block.count("orders-db") == 1 and "a -> b ->" not in block
    assert diagram_block(rels[:1]) == ""                                                  # one relation: no diagram

    class LLM:
        last_usage, last_finish = {"prompt_tokens": 10, "completion_tokens": 5}, "stop"

        def chat(self, messages, max_tokens=0):
            assert "draw none yourself" in messages[0]["content"]                         # the prompt says so
            assert "counts of" in messages[0]["content"]                                  # and what to leave out
            return {"content": "In short: the shop.\n\n## What it does\n\nIt sells. [E1]"}

    spec = {"title": "How the system works", "brief": "Explain.", "evidence": [{"ref": "doc:1", "title": "d", "text": "x"}],
            "diagram": rels}
    page = write_summary(spec, LLM())
    assert page["content"].startswith("In short") and "## Relations diagram" in page["content"]
    assert page["content"].rstrip().endswith("```")
    spec["diagram"] = []
    assert "## Relations diagram" not in write_summary(spec, LLM())["content"]


def test_a_nul_in_a_file_and_a_refused_file_never_stop_the_reading():
    import requests

    from supagent.knowledge.docs import DocError, _join, _transient

    content, pages = _join([("u1", "a\x00b", "x\x00y", {"path": "a.sql"}), ("u2", "t", "fine", {"path": "b.md"})])
    assert "\x00" not in content and pages[0]["title"] == "ab" and pages[1]["at"] == pages[0]["chars"] + 2
    assert _transient(DocError("repo: HTTP 503 Service Unavailable")) and _transient(DocError("HTTP 429: slow down"))
    assert _transient(requests.exceptions.ConnectionError("reset")) and not _transient(DocError("HTTP 404 Not Found"))


def test_the_daily_backup_is_due_by_the_server_s_date_and_not_by_a_file_brought(ctx, tmp_path):
    import datetime as dt

    from supagent import settings
    from supagent.knowledge import backup

    settings.set_value("backup.dir", str(tmp_path))
    settings.set_value("backup.hour", 0)
    try:
        now = dt.datetime.now()
        stamp = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        (tmp_path / f"supagent-knowledge-{stamp}-uploaded.zip").write_bytes(b"x")
        assert backup.due(now)                                     # a file brought today is no backup of today
        (tmp_path / f"supagent-knowledge-{stamp}.zip").write_bytes(b"x")
        assert not backup.due(now)
    finally:
        settings.set_value("backup.dir", None)
        settings.set_value("backup.hour", None)


def test_a_long_run_that_says_it_is_alive_is_not_taken_for_dead_and_gone_hosts_go(ctx):
    import datetime as dt
    import json

    from superset.extensions import db

    from supagent import hoststats as H
    from supagent.knowledge.learner import last_alive, running_run
    from supagent.models import Meta, Run

    now = dt.datetime.utcnow()
    r = Run(kind="context", reason="test", status="running", started_at=now - dt.timedelta(hours=5),
            stats={"beat": (now - dt.timedelta(minutes=2)).isoformat(timespec="seconds")})
    db.session.add(r)
    db.session.add(Meta(key="host:old-box:web", value=json.dumps({"last": {"at": (now - dt.timedelta(days=9)).isoformat()}})))
    db.session.add(Meta(key="host:new-box:web", value=json.dumps({"last": {"at": now.isoformat()}})))
    db.session.commit()
    try:
        assert last_alive(r) > now - dt.timedelta(minutes=5)
        assert running_run() is not None and running_run().id == r.id          # five hours old, alive: still running
        assert db.session.get(Run, r.id).status == "running"
        assert H.purge_gone() == 1 and db.session.get(Meta, "host:new-box:web") is not None
    finally:
        db.session.query(Run).filter(Run.id == r.id).delete()
        db.session.query(Meta).filter(Meta.key.like("host:%-box:web")).delete(synchronize_session=False)
        db.session.commit()
