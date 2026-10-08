"""(0.10.0, after the measurement) Each kind of link explained as what it is (the explanations were asked as flows for
every kind: a part that runs on a server "waited for the health of" the other servers), and superset supagent
interactions --explain [--again]: the missing explanations at once, the AI's own written again (an admin's words
stay), continuing where the last run stopped."""

from __future__ import annotations


def test_interactions_explain_writes_the_explanations_alone(app, monkeypatch):
    from click.testing import CliRunner

    from supagent import cli

    got: dict = {}
    monkeypatch.setattr("supagent.knowledge.interactions.explain",
                        lambda llm, seconds, limit, again, kinds: got.update(seconds=seconds, limit=limit, again=again,
                                                                             kinds=kinds) or {"explained": 3})
    monkeypatch.setattr("supagent.knowledge.interactions.run", lambda *a, **k: got.update(read=True) or {})
    monkeypatch.setattr("supagent.llm.LLM", lambda *a, **k: object())
    monkeypatch.setattr("supagent.knowledge.facets.review_counts", lambda: {})
    with app.app_context():
        res = CliRunner().invoke(cli.interactions, ["--explain", "--minutes", "20", "--limit", "500"],
                                 obj=None, catch_exceptions=False)
    assert res.exit_code == 0, res.output
    assert got == {"seconds": 1200.0, "limit": 500, "again": False, "kinds": None} and '"explained": 3' in res.output
    with app.app_context():
        res = CliRunner().invoke(cli.interactions, ["--explain", "--again", "--kinds", "runs_on, monitors"],
                                 obj=None, catch_exceptions=False)
    assert res.exit_code == 0, res.output
    assert got["again"] is True and got["kinds"] == ("runs_on", "monitors")


def test_each_kind_of_link_is_explained_as_what_it_is():
    """(0.10.1) The explanations were written as flows for every kind: a part that runs on a server was said to "wait
    for the health of" the other servers of its list. The prompt says what each kind means and that an interaction
    is explained from its own two parts only."""
    from supagent.knowledge import interactions as I

    text = I.EXPLAIN_SYSTEM
    assert "runs on: the second is the place the first runs on" in text
    assert "monitors: what the first watches on the second" in text
    assert "never name a part that is not one of its two parts" in text
    assert "for runs on, what the first part is or does on that place" in I.EXPLAIN_SHORT_SAYS
    assert "a place the first runs on: the place's health" in I.EXPLAIN_LONG_SAYS
    props = I.EXPLAIN_TOOL["function"]["parameters"]["properties"]["explanations"]["items"]["properties"]
    assert props["short"]["description"] == I.EXPLAIN_SHORT_SAYS and props["long"]["description"] == I.EXPLAIN_LONG_SAYS
    reading = I.TOOL["function"]["parameters"]["properties"]["interactions"]["items"]["properties"]
    assert reading["short"]["description"] == I.SHORT_SAYS and "runs on" not in I.SHORT_SAYS   # the reading: as in 0.10.0


def _llm_answering(explanations_for):
    class FakeLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages, tools=None, max_tokens=None):
            self.calls += 1
            lines = [l for l in messages[-1]["content"].splitlines() if l[:1].isdigit()]
            items = []
            for line in lines:
                n = int(line.split(".", 1)[0])
                got = explanations_for(line)
                if got:
                    items.append({"n": n, "short": got[0], "long": got[1]})
            import json as _json

            return {"tool_calls": [{"function": {"name": "explanations",
                                                 "arguments": _json.dumps({"explanations": items})}}]}
    return FakeLLM()


def test_again_writes_again_only_what_the_ai_wrote_alone(app):
    """(0.10.1) --explain --again: the explanations the AI wrote alone are written again in place; an admin's words
    and a link an admin and the AI explained together are kept; the next run continues after the last one, and the
    pass ends by starting over."""
    from superset.extensions import db

    from supagent.knowledge import interactions as I
    from supagent.models import Facet, Link, Meta

    with app.app_context():
        a = Facet(facet="application", value="Brinepump", status="approved", source="admin")
        b = Facet(facet="server", value="brine-host-01", status="approved", source="admin")
        c = Facet(facet="component", value="Saltledger", status="approved", source="admin")
        db.session.add_all([a, b, c])
        db.session.flush()
        ai = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind="runs_on", status="approved",
                  note="waits for the health of brine-host-02", detail="old flow wording", explained_by="llm")
        admin = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{c.id}", kind="sends_to", status="approved",
                     note="the admin's words", detail="the admin's long words", explained_by="admin")
        both = Link(a_ref=f"facet:{c.id}", b_ref=f"facet:{b.id}", kind="runs_on", status="approved",
                    note="the admin's short", detail="the AI's long", explained_by="admin and the AI")
        db.session.add_all([ai, admin, both])
        db.session.commit()
        try:
            llm = _llm_answering(lambda line: ("its pump runs there", "Check brine-host-01's health, resources and "
                                               "restarts; when it is down, Brinepump stops."))
            out = I.explain(llm, seconds=60, limit=200, again=True)
            db.session.expire_all()
            assert out["written_again"] == 1 and out.get("done") is True
            assert db.session.get(Link, ai.id).note == "its pump runs there"
            assert db.session.get(Link, admin.id).note == "the admin's words"
            assert db.session.get(Link, both.id).detail == "the AI's long"
            assert db.session.get(Meta, I.AGAIN_KEY) is None              # the pass is over: the next starts over

            failing = _llm_answering(lambda line: None)                   # the LLM gives nothing: kept as it was
            I.explain(failing, seconds=60, limit=200, again=True)
            db.session.expire_all()
            assert db.session.get(Link, ai.id).note == "its pump runs there"
        finally:
            db.session.query(Link).filter(Link.id.in_([ai.id, admin.id, both.id])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_([a.id, b.id, c.id])).delete(synchronize_session=False)
            db.session.query(Meta).filter(Meta.key == I.AGAIN_KEY).delete(synchronize_session=False)
            db.session.commit()


def test_again_continues_after_the_last_one_written(app, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import interactions as I
    from supagent.models import Facet, Link, Meta

    monkeypatch.setattr(I, "EXPLAIN_BATCH", 2)
    with app.app_context():
        fs = [Facet(facet="application", value=f"Tidewheel{i}", status="approved", source="admin") for i in range(4)]
        db.session.add_all(fs)
        db.session.flush()
        links = [Link(a_ref=f"facet:{fs[i].id}", b_ref=f"facet:{fs[i + 1].id}", kind="calls", status="approved",
                      note="old", detail="old long", explained_by="llm") for i in range(3)]
        db.session.add_all(links)
        db.session.commit()
        try:
            llm = _llm_answering(lambda line: ("new", "new long"))
            out = I.explain(llm, seconds=60, limit=2, again=True)       # the first two only
            db.session.expire_all()
            assert out["written_again"] == 2 and not out.get("done")
            assert db.session.get(Meta, I.AGAIN_KEY).value == str(links[1].id)
            assert db.session.get(Link, links[2].id).note == "old"
            out = I.explain(llm, seconds=60, limit=2, again=True)       # the next run: the third, then done
            db.session.expire_all()
            assert out["written_again"] == 1 and out.get("done") is True
            assert db.session.get(Link, links[2].id).note == "new"
        finally:
            db.session.query(Link).filter(Link.id.in_([x.id for x in links])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_([x.id for x in fs])).delete(synchronize_session=False)
            db.session.query(Meta).filter(Meta.key == I.AGAIN_KEY).delete(synchronize_session=False)
            db.session.commit()


def test_again_of_some_kinds_keeps_the_others(app):
    """--explain --again --kinds runs_on,monitors: the kinds an older prompt explained as flows are written again, the
    flows the team already has keep their explanations; the pass of these kinds has a cursor of its own."""
    from superset.extensions import db

    from supagent.knowledge import interactions as I
    from supagent.models import Facet, Link, Meta

    with app.app_context():
        a = Facet(facet="application", value="Kelpgate", status="approved", source="admin")
        b = Facet(facet="server", value="kelp-host-01", status="approved", source="admin")
        c = Facet(facet="component", value="Kelpstore", status="approved", source="admin")
        db.session.add_all([a, b, c])
        db.session.flush()
        place = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{b.id}", kind="runs_on", status="approved",
                     note="waits for kelp-host-01", detail="flow wording", explained_by="llm")
        flow = Link(a_ref=f"facet:{a.id}", b_ref=f"facet:{c.id}", kind="sends_to", status="approved",
                    note="writes the harvest there", detail="the team's good flow wording", explained_by="llm")
        db.session.add_all([place, flow])
        db.session.commit()
        try:
            llm = _llm_answering(lambda line: ("its gateway runs there", "Check kelp-host-01's health and restarts."))
            out = I.explain(llm, seconds=60, limit=200, again=True, kinds=("runs_on", "monitors"))
            db.session.expire_all()
            assert out["written_again"] == 1 and out.get("done") is True
            assert db.session.get(Link, place.id).note == "its gateway runs there"
            assert db.session.get(Link, flow.id).note == "writes the harvest there"
            assert db.session.get(Meta, I._again_key(("runs_on", "monitors"))) is None
        finally:
            db.session.query(Link).filter(Link.id.in_([place.id, flow.id])).delete(synchronize_session=False)
            db.session.query(Facet).filter(Facet.id.in_([a.id, b.id, c.id])).delete(synchronize_session=False)
            db.session.query(Meta).filter(Meta.key.like(I.AGAIN_KEY + "%")).delete(synchronize_session=False)
            db.session.commit()
