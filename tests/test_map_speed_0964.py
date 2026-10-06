"""(0.9.6.4) The System map without reading the texts in its request: the sentences that say what each part is are
read in the background and kept in the database for every process (found as the one expression of the names found
them before, every name read), what exists now read once per item and kept a moment, the map answering when its
to-do list cannot be read."""

from __future__ import annotations

import random
import re

import pytest

NAMES_RX = r"(?<![\w-])(%s)(?![\w-])"


def _expression(names):
    return re.compile(NAMES_RX % "|".join(re.escape(n) for n in sorted({n.lower() for n in names}, key=len,
                                                                         reverse=True)), re.I)


def _random_text(rng, names, n_words=60):
    words = ["the", "and", "runs", "on", "writes", "reads", "a", "of", "to", "service", "gateway", "api", "batch",
             "x", "é", "café", "data", "db", "01", "-", "_", "node", "order", "pay"]
    seps = [" ", " ", " ", ", ", ". ", "-", "_", ".", "/", ":", "(", ")", "\n", "  ", "'", "#", "**"]
    out = []
    for _ in range(n_words):
        r = rng.random()
        if r < 0.25:
            n = rng.choice(names)
            out.append(rng.choice([n, n.upper(), n.title(), n.capitalize()]))
        elif r < 0.35:
            out.append(rng.choice(names) + rng.choice(["x", "-x", "_1", "s", ""]))
        else:
            out.append(rng.choice(words))
        out.append(rng.choice(seps))
    return "".join(out)


def test_the_names_are_found_as_the_one_expression_found_them():
    from supagent.knowledge.sysmap import WORDISH, _Matcher

    rng = random.Random(964)
    pool = ["payment gateway", "payment", "gateway", "order-api", "order", "api", "db-01", "db-01.example",
            "pay_batch", "x-ray", "node", "node.js", ".net", "c++", "café", "le café", "batch job", "job",
            "srv-0001", "srv-00", "a.b", "data lake", "lake", "order api", "api-gw"]
    for _ in range(400):
        names = rng.sample(pool, rng.randint(1, len(pool)))
        m, rx = _Matcher(names), _expression(names)
        for _k in range(5):
            text = _random_text(rng, names)
            want = [(x.start(), x.end(), x.group(1).lower()) for x in rx.finditer(text)]
            assert m.find(text) == want, (names, text)
            low = text.lower()
            words = set(WORDISH.findall(low))
            assert m.find(text, low, words) == want
            assert m.may(words) or not want


def _old_found(rows, names):
    """0.9.6.3's reading of the texts (every name missing, fewer than 2,000), for the comparison."""
    from supagent.knowledge.sysmap import CITES, HINT_CHARS, _score, _sentences

    missing = sorted({n.lower() for n in names}, key=len, reverse=True)
    found = {n: [] for n in missing}
    rx = _expression(missing)
    for ref, kind, title, text in rows:
        if not rx.search(text or ""):
            continue
        for sentence in _sentences(text or ""):
            sentence = CITES.sub("", sentence).strip()
            hits = list(rx.finditer(sentence))
            if not hits:
                continue
            named = {m.group(1).lower() for m in rx.finditer(sentence)}
            if len(named) >= 3 or sentence.count(",") >= 5:
                continue
            if len(sentence) < 25 or sentence.strip(" .:").lower() in named:
                continue
            for m in hits:
                got = found[m.group(1).lower()]
                if any(x[1] == ref and x[3] == sentence for x in got):
                    continue
                short = sentence[:HINT_CHARS] + ("…" if len(sentence) > HINT_CHARS else "")
                got.append((_score(sentence, m.start(), m.end(), kind or ""), ref, title or ref, short))
    return {n: [[ref, title, s] for _sc, ref, title, s in sorted(got, key=lambda x: -x[0])[:3]]
            for n, got in found.items()}


@pytest.fixture()
def texts(ctx):
    """Documents, guides and Context pages naming parts (as subjects, in lists, under headings, with citations)."""
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Chunk

    rng = random.Random(4)
    names = ["Kelvora gateway", "kelvora", "Tamsin batch", "tamsin-api", "Orvel ledger", "orvel", "Quenby cache",
             "zentra.db", "Brisk router", "brisk"]
    verbs = ["authorizes the cards", "is the nightly job", "stores the entries", "handles the refunds",
             "runs the reports", ": the cache of the prices", "sends the invoices", "reads the queue"]
    rows = []
    for i in range(160):
        parts = []
        for _k in range(rng.randint(2, 6)):
            n = rng.choice(names)
            r = rng.random()
            if r < 0.5:
                parts.append(f"{rng.choice(['The ', '', 'A '])}{n} {rng.choice(verbs)}"
                             f"{rng.choice(['', ' [E1]', ' [S2, S3]'])}.")
            elif r < 0.65:
                parts.append("Known parts: " + ", ".join(rng.sample(names, 4)) + ".")
            elif r < 0.75:
                parts.append(f"# {n}")
            elif r < 0.82:
                parts.append(f"- **{n}** {rng.choice(verbs)} every hour and keeps {rng.randint(2, 90)} days of it "
                             "for the audits of the year.")
            elif r < 0.88:                               # a long sentence (kept cut), said twice in the text
                long = f"{n} {rng.choice(verbs)} " + "and keeps the records of the past weeks " * 7 + "."
                parts += [long, long]
            elif r < 0.94:                               # the name twice, its second place the better one
                parts.append(f"See {n}, then {n} handles the cards of the night.")
            else:
                parts.append(f"When {n} stops, {rng.choice(names)} waits; see the runbook of the team on call.")
        rows.append(Chunk(ref=f"{rng.choice(['doc', 'guide', 'context'])}:{9600 + i // 4}#{i % 4}",
                          kind=rng.choice(["doc", "guide", "context"]), title=f"Text {i}", text="\n".join(parts)))
    db.session.add_all(rows)
    db.session.commit()
    sysmap.forget_hints()
    yield names
    db.session.query(Chunk).filter(Chunk.id.in_([c.id for c in rows])).delete(synchronize_session=False)
    db.session.commit()
    sysmap.forget_hints()


def test_the_sentences_are_the_ones_found_before(texts):
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Chunk

    rows = (db.session.query(Chunk.ref, Chunk.kind, Chunk.title, Chunk.text)
            .filter(Chunk.kind.in_(sysmap.HINT_KINDS)).order_by(Chunk.id).all())
    every = {n.lower() for n in texts}
    got, read = sysmap._scan(every, every)
    assert read == len(rows)
    assert got == _old_found(rows, texts)
    assert sum(1 for h in got.values() if h) >= 8                   # most names have their sentence


def test_the_map_reads_no_text_in_its_request(ctx, texts, monkeypatch):
    """The page's request reads the copy kept in the database; the job (here run by hand) reads the texts."""
    from sqlalchemy import event
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Facet

    vals = [Facet(facet="application", value=n, status="approved", source="admin") for n in texts[:4]]
    db.session.add_all(vals)
    db.session.commit()
    statements, poked = [], []
    monkeypatch.setitem(ctx.config, "SUPAGENT_MAP_HINTS_BACKGROUND", True)
    monkeypatch.setattr(sysmap, "_poke", lambda soon: poked.append(soon))

    def keep(conn, cursor, statement, params, context, many):   # noqa: ARG001
        statements.append(statement)

    event.listen(db.engine, "before_cursor_execute", keep)
    try:
        first = sysmap.map_data(True)
        assert poked == [True]                                     # names not read yet: the job asked for
        assert not [v for v in first["values"] if v["id"] in {x.id for x in vals} and v["hint"]]
        assert not [s for s in statements if "supagent_chunk.text" in s]
        event.remove(db.engine, "before_cursor_execute", keep)
        out = sysmap.refresh_hints()                               # the job
        assert out["read"] >= 160 and out["names"] >= 4
        event.listen(db.engine, "before_cursor_execute", keep)
        statements.clear()
        then = sysmap.map_data(True)
        mine = {v["id"]: v for v in then["values"] if v["id"] in {x.id for x in vals}}
        assert sum(1 for v in mine.values() if v["hint"]) >= 3     # the page shows them at its next reading
        assert not [s for s in statements if "supagent_chunk.text" in s]
        assert poked[-1] is False                                  # nothing new: asked whether the texts changed
    finally:
        if event.contains(db.engine, "before_cursor_execute", keep):
            event.remove(db.engine, "before_cursor_execute", keep)
        db.session.query(Facet).filter(Facet.id.in_([v.id for v in vals])).delete(synchronize_session=False)
        db.session.commit()


def test_the_copy_is_one_for_every_process(texts, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Chunk, Meta

    monkeypatch.setattr(sysmap, "PART_CHARS", 300)                 # several pieces
    texts = texts + ["Pellam queue"]                               # said nowhere yet
    sysmap.refresh_hints(texts)
    assert sysmap._snapshot()["names"]["pellam queue"] == []
    head = sysmap._head()
    assert head["parts"] > 2 and head["names"] >= len(texts)
    mine = dict(sysmap._SNAP)
    sysmap._SNAP.update(v=None, names={}, state=None)              # another process: reads the database
    assert sysmap._snapshot()["names"] == mine["names"]
    db.session.add(Chunk(ref="doc:9699#0", kind="doc", title="More", text="The Pellam queue holds the orders for an hour."))
    db.session.commit()
    again = sysmap.refresh_hints(texts)                            # the texts changed: all read again
    assert again["names"] >= len(texts)
    assert sysmap._snapshot()["names"]["pellam queue"][0][2] == "The Pellam queue holds the orders for an hour."
    keys = [k for (k,) in db.session.query(Meta.key).filter(Meta.key.startswith(sysmap.HINTS_PART))]
    new = sysmap._head()
    assert len(keys) == new["parts"] and all(k.startswith(f"{sysmap.HINTS_PART}{new['v']}:") for k in keys)
    assert sysmap.refresh_hints(texts) == {"read": 0, "unchanged": True}
    db.session.query(Chunk).filter_by(ref="doc:9699#0").delete()
    db.session.commit()


def test_every_name_is_read(ctx):
    """No limit of 2,000 names and no reading cut after 8 s: the shortest names of a big platform too."""
    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Chunk

    sysmap.forget_hints()
    names = [f"host-{i:05d}-long-name-{'x' * (i % 7)}" for i in range(2400)] + ["zq-a1", "zq-b2"]
    rows = [Chunk(ref="doc:9700#0", kind="doc", title="Hosts", text="The zq-a1 node keeps the backups of the week."),
            Chunk(ref="doc:9700#1", kind="doc", title="Hosts", text="zq-b2 is the spare node of the second room.")]
    db.session.add_all(rows)
    db.session.commit()
    try:
        out = sysmap.refresh_hints(names)
        assert out["names"] >= 2402
        known = sysmap._snapshot()["names"]
        assert known["zq-a1"][0][2] == "The zq-a1 node keeps the backups of the week."
        assert known["zq-b2"][0][2] == "zq-b2 is the spare node of the second room."
        assert known["host-00007-long-name-"] == []                # read, and said nowhere
    finally:
        db.session.query(Chunk).filter(Chunk.ref.in_(["doc:9700#0", "doc:9700#1"])).delete(synchronize_session=False)
        db.session.commit()
        sysmap.forget_hints()


def test_one_process_reads_at_a_time(texts):
    import time

    from superset.extensions import db

    from supagent.knowledge import sysmap
    from supagent.models import Meta

    row = db.session.get(Meta, sysmap.HINTS_LEASE) or Meta(key=sysmap.HINTS_LEASE)
    row.value = f"other-host:1|{time.time() + 60:.0f}"
    db.session.add(row)
    db.session.commit()
    assert sysmap.refresh_hints(texts) == {"read": 0, "busy": True}
    db.session.get(Meta, sysmap.HINTS_LEASE).value = f"other-host:1|{time.time() - 1:.0f}"   # it stopped
    db.session.commit()
    assert sysmap.refresh_hints(texts)["read"] > 0
    assert db.session.get(Meta, sysmap.HINTS_LEASE).value == ""     # given back


def test_what_exists_now_is_read_once_per_item(ctx):
    from superset.extensions import db

    from supagent.knowledge import facets
    from supagent.models import Chunk

    rows = [Chunk(ref="doc:9800#ab12-0", kind="doc", title="d", text="t"),
            Chunk(ref="doc:9800#ab12-1", kind="doc", title="d", text="t"),
            Chunk(ref="context:9801#0", kind="context", title="c", text="t"),
            Chunk(ref="entry:9802", kind="rule", title="e", text="t"),
            Chunk(ref="object:9803", kind="metric", title="o", text="t"),
            Chunk(ref="superset:9804", kind="chart", title="s", text="t")]
    db.session.add_all(rows)
    db.session.commit()
    ids = [c.id for c in rows]
    try:
        facets.forget_live()
        before = {r.split("#", 1)[0] for (r,) in db.session.query(Chunk.ref).filter(
            Chunk.ref.notlike("object:%"), Chunk.ref.notlike("superset:%"))}      # 0.9.6.3: every piece's ref
        got = facets._live_bases()
        assert got == before
        assert {"doc:9800", "context:9801", "entry:9802"} <= got and not {"object:9803", "superset:9804"} & got
        db.session.query(Chunk).filter(Chunk.ref == "entry:9802").delete()
        db.session.commit()
        assert "entry:9802" in facets._live_bases()                 # kept a moment (the map is read again soon)
        facets.forget_live()                                        # the indexing says it changed
        assert "entry:9802" not in facets._live_bases()
    finally:
        db.session.query(Chunk).filter(Chunk.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        facets.forget_live()


def test_the_map_answers_when_its_to_do_list_cannot_be_read(ctx, monkeypatch):
    from supagent.knowledge import readiness, sysmap

    def broken(*_a, **_k):
        raise RuntimeError("not readable")

    monkeypatch.setattr(readiness, "report", broken)
    out = sysmap.map_data(True)
    assert out["missing"] == [] and "values" in out


def test_the_job_reads_them_in_the_background(ctx, texts, monkeypatch):
    """The page's request starts the job (a thread of the process, its own session) and answers at once; the job
    keeps the sentences for the next reading."""
    from types import SimpleNamespace

    from superset.extensions import db

    from supagent.knowledge import sysmap

    monkeypatch.setitem(ctx.config, "SUPAGENT_MAP_HINTS_BACKGROUND", True)
    values = {1: SimpleNamespace(value=texts[0], description=None), 2: SimpleNamespace(value=texts[2], description=None)}
    monkeypatch.setattr(sysmap, "_wanted", lambda: {texts[0].lower(), texts[2].lower()})
    assert sysmap.hints(values) == {}                              # nothing kept yet: the page answers without
    db.session.rollback()
    job = sysmap._JOB["thread"]
    assert job is not None
    job.join(60)
    assert not job.is_alive()
    got = sysmap.hints(values)
    assert set(got) == {1, 2} and all(h[0][2] for h in got.values())
    assert sysmap._JOB["thread"] is job                            # asked a moment ago: not started again
