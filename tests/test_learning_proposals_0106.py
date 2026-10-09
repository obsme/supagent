"""(0.10.6) What the LLM proposes is said by the texts: on a lab map its classification said 33 parts "belong to" a web
application that no sentence put them in, its reading of the texts wrote "db-01 runs on postgresql" from "the
PostgreSQL instance on db-01", a flow to a server and a subject (a topic) as a part of a flow; and it proposed subjects
named after approved parts ("ceph-mds" an application and a proposed subject)."""

from __future__ import annotations

import json

from test_brief import system  # noqa: F401  (Billing = Invoicing + Payments, grid-a, ledger db)
from test_decider import lab  # noqa: F401
from test_facets import world  # noqa: F401  (an entry, categories)


def test_no_part_of_from_the_llm_without_a_sentence(world):
    from superset.extensions import db

    from supagent.knowledge import facets as F
    from supagent.models import Facet, Link

    web = F._ensure("application", "zqweb", "approved", "admin")
    db_ = F._ensure("component", "zqstore", "approved", "admin")
    db.session.commit()
    batch = [{"ref": f"entry:{world['entry']}", "hash": "h",
              "text": "The zqweb tier serves the pages. zqstore keeps the orders."}]
    F.apply({"items": [], "new_values": [], "known_value_parents": [{"value": "zqstore", "part_of": ["zqweb"]}]},
            batch, {})
    assert db.session.query(Link).filter(Link.a_ref == f"facet:{db_.id}", Link.b_ref == f"facet:{web.id}").count() == 0
    batch[0]["text"] += " zqstore is part of the zqweb stack."
    F.apply({"items": [], "new_values": [], "known_value_parents": [{"value": "zqstore", "part_of": ["zqweb"]}]},
            batch, {})
    x = db.session.query(Link).filter(Link.a_ref == f"facet:{db_.id}", Link.b_ref == f"facet:{web.id}").one()
    assert x.status == "proposed" and "zqstore is part of the zqweb stack." in x.evidence


def test_a_subject_named_as_an_approved_part_is_that_part(world):
    from superset.extensions import db

    from supagent.knowledge import facets as F
    from supagent.models import Facet, Tag

    app_ = F._ensure("application", "zq-mds", "approved", "admin")
    db.session.commit()
    ref = f"entry:{world['entry']}"
    F.apply({"items": [{"ref": ref, "subjects": ["zq-mds"], "confidence": "high"}], "new_values": [
        {"facet": "subject", "value": "zq-mds"}]}, [{"ref": ref, "hash": "h", "text": ""}], {})
    assert db.session.query(Facet).filter(Facet.facet == "subject", Facet.value == "zq-mds").count() == 0
    assert db.session.query(Tag).filter(Tag.ref == ref, Tag.facet_id == app_.id).count() == 1


def test_one_name_one_value_across_the_batches_of_a_run(world):
    """A value proposed under one category is the value of its name: the next batch's same name in another category
    is that value (no twin to merge in To review); a topic is no server's twin."""
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import facets as F
    from supagent.models import Facet, Tag

    ref = f"entry:{world['entry']}"
    batch = [{"ref": ref, "hash": "h", "text": ""}]
    F.apply({"items": [], "new_values": [{"facet": "application", "value": "zqledger"}]}, batch, {})
    F.apply({"items": [{"ref": ref, "components": ["zqledger"], "confidence": "high"}],
             "new_values": [{"facet": "component", "value": "zqledger"}]}, batch, {})
    rows = db.session.query(Facet).filter(Facet.value == "zqledger").all()
    assert [(f.facet, f.status) for f in rows] == [("application", "proposed")]
    assert db.session.query(Tag).filter(Tag.ref == ref, Tag.facet_id == rows[0].id).count() == 1
    before = settings.get("categories.custom")
    settings.set_value("categories.custom", ["server"])
    try:
        F._ensure("server", "zqbackup", "proposed", "docs")
        F.apply({"items": [], "new_values": [{"facet": "subject", "value": "zqbackup"}]}, batch, {})
        assert db.session.query(Facet).filter(Facet.facet == "subject", Facet.value == "zqbackup").count() == 1
    finally:
        db.session.query(Facet).filter(Facet.value == "zqbackup").delete(synchronize_session=False)
        db.session.commit()
        settings.set_value("categories.custom", before)


class Reader:
    def __init__(self, found):
        self.found = found

    def chat(self, messages, tools=None, max_tokens=None):
        return {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "interactions", "arguments": json.dumps({"interactions": self.found})}}]}


def test_the_llm_reading_keeps_directions_and_parts(system):  # noqa: F811
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import facets as F
    from supagent.knowledge import interactions as I
    from supagent.models import Classified, Doc, Link

    before = settings.get("categories.custom")
    settings.set_value("categories.custom", ["server"])
    srv = F._ensure("server", "zqdb-01", "approved", "admin")
    pg = F._ensure("component", "zqpg", "approved", "admin")
    api = F._ensure("application", "zqapi", "approved", "admin")
    topic = F._ensure("subject", "zqtopic", "approved", "admin")
    text = ("The zqpg instance on zqdb-01 is the primary. zqapi reads its rows from zqdb-01 every hour. "
            "zqapi is about zqtopic and calls zqpg for each order.")
    d = Doc(kind="upload", title="Runbook", content=text * 2, enabled=True, status="ok")
    db.session.add(d)
    db.session.commit()
    found = [{"from": "zqdb-01", "kind": "runs_on", "to": "zqpg", "quote": "The zqpg instance on zqdb-01 is the primary."},
             {"from": "zqapi", "kind": "reads_from", "to": "zqdb-01", "quote": "zqapi reads its rows from zqdb-01 every hour."},
             {"from": "zqapi", "kind": "depends_on", "to": "zqtopic", "quote": "zqapi is about zqtopic and calls zqpg for each order."},
             {"from": "zqapi", "kind": "calls", "to": "zqpg", "quote": "The zqpg instance on zqdb-01 is the primary."},
             {"from": "zqapi", "kind": "calls", "to": "zqpg", "quote": "zqapi is about zqtopic and calls zqpg for each order."}]
    try:
        I.run(Reader(found), seconds=60)
        got = {(x.a_ref, x.kind, x.b_ref) for x in db.session.query(Link).filter(Link.source == "llm")}
        r = lambda f: f"facet:{f.id}"                                      # noqa: E731
        assert (r(pg), "runs_on", r(srv)) in got and (r(srv), "runs_on", r(pg)) not in got   # turned the right way
        assert not any(b == r(srv) and k == "reads_from" for _a, k, b in got)              # a flow to a server
        assert not any(r(topic) in (a, b) for a, _k, b in got)                             # a topic
        assert (r(api), "calls", r(pg)) in got                                             # named both: kept
    finally:
        db.session.query(Link).filter(Link.source == "llm").delete(synchronize_session=False)
        db.session.query(Doc).filter(Doc.id == d.id).delete(synchronize_session=False)
        db.session.query(Classified).delete(synchronize_session=False)
        db.session.commit()
        settings.set_value("categories.custom", before)
