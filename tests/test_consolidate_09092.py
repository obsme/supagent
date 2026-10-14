"""(0.10.9.2, the team's report of 12 October: hundreds of values to review naming the same things differently) One
value per thing: names written alike are one thing (case, separators, camelCase, a plural, a short form, an
environment's word, a typo), never two names with other numbers; the learning's proposals of one thing are put
together into one proposal; a proposal of a value a person has waits as "the same as" it (To review merges them
together); two values people approved are never merged here; the doubtful groups go to the LLM, whose answer is
checked."""

from __future__ import annotations

import pytest

from conftest import login

PFX = "zqc"


@pytest.mark.parametrize("a,b,cat,want", [
    ("payment-service", "Payment Service", "application", "strong"),
    ("payment-service", "payment_service", "application", "strong"),
    ("payment-service", "PaymentService", "application", "strong"),
    ("payment-service", "payment-svc", "application", "strong"),
    ("payment-service", "payments-service", "application", "strong"),
    ("k8s-cluster", "kubernetes cluster", "component", "strong"),
    ("checkout", "check-out", "application", "strong"),
    ("billing", "billing-prd", "application", "noenv"),
    ("Order Service", "order-service-prod", "application", "noenv"),
    ("payment-service", "paymnet-service", "application", "typo"),
    ("billing", "billing v2", "application", "doubt"),            # a version apart: maybe two things
    ("payments-api-v1", "payments-api-v2", "component", "doubt"),
    ("inventory", "inventory-api", "application", "doubt"),
    ("order management system", "OMS", "application", "doubt"),
    ("node-1", "node-01", "server", "strong"),
    ("srv-01", "srv-02", "server", ""),                          # other numbers: two things
    ("app2", "app3", "application", ""),
    ("db-prd-01", "db-stg-01", "server", ""),                    # a server's environment is no extra word
    ("node-1", "node-10", "server", ""),
    ("orders-api", "orders-worker", "application", ""),
    ("frontend", "backend", "application", ""),
    ("cart", "card", "application", ""),                         # a typo in a short name: two names
    ("cart-service", "card-service", "application", ""),
    ("notifcation-service", "notification-service", "application", "typo"),
    ("billling", "billing", "application", "typo"),
    ("loader-service", "leader-service", "application", ""),     # one letter changed in a short word
    ("ingestion-loader", "ingestion-leader", "component", ""),
    ("reconciler-service", "reconcilor-service", "application", "doubt"),   # one letter changed: the LLM says
    ("trade-service", "trader-service", "application", ""),       # a letter more at the end: another word
    ("pricer", "price", "application", ""),
    ("srv-a-1", "srv-01", "server", ""),                          # a host's every word is its identity
    ("SRV-01", "srv-1", "server", "strong"),
    ("box-01", "boxes-01", "server", ""),                         # a host's name: no plural, no short form
    ("ops-west-01", "operations_west1", "server", ""),
    ("k8s-east-prod", "k8s-east-staging", "component", ""),       # two environments' own: two things
    ("billing-prd", "billing-production", "application", "strong"),
    ("billing", "legacy-billing", "application", "doubt"),        # one word more: the LLM says
    ("payment", "payment-archive", "application", "doubt"),
    ("api", "public-api", "component", ""),                       # (a generic word alone shares nothing)
    ("uat_app (ops uat)", "ops uat", "ansible group", ""),        # (0.10.10) a group and its inventory: two
    ("uat_db (ops uat)", "ops uat", "ansible group", ""),
    ("web (ops prod)", "web", "ansible group", ""),               # a group's name is its identity, as written
    ("payments", "payment", "host group", ""),
    ("VIP-checkout", "vip checkout", "virtual ip", "strong"),
    ("orders-api (Order Desk)", "Order Desk", "application", ""),   # a part and what it is in: two
    ("Order Desk (OD)", "OD", "application", "doubt"),             # its initials in parentheses: maybe one
    ("orders_db", "stg_orders_db", "database", ""),                # a staging database is another database
    ("orders-cache", "orders-cache-prod", "cache", ""),
    ("orders_db", "orders-db", "database", "strong"),
    ("api-gatew-store-writer", "porti-gatew-store-writer", "component", ""),   # another word of its own: two
    ("access.ordering.updated", "access.ordering.rated", "stream", ""),         # a stream's name is its identity
    ("billing-api", "billing-service", "application", "doubt"),                # generic words only: maybe one
])
def test_names_written_alike(a, b, cat, want):
    from supagent.knowledge.consolidate import same

    assert same(a, b, cat) == want, (a, b, same(a, b, cat))


def _clean(db):
    from supagent.models import Facet, Link, Tag

    db.session.rollback()
    ids = [i for (i,) in db.session.query(Facet.id).filter(Facet.value.ilike(PFX + "%"))]
    refs = [f"facet:{i}" for i in ids]
    if ids:
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Tag).filter(Tag.facet_id.in_(ids)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()


def _add(db, facet, value, status="proposed", source="docs", **kw):
    from supagent.models import Facet

    f = Facet(facet=facet, value=value, status=status, source=source, **kw)
    db.session.add(f)
    db.session.flush()
    return f


def test_the_learnings_proposals_of_one_thing_become_one(ctx):
    from superset.extensions import db

    from supagent.knowledge import consolidate as C
    from supagent.models import Facet, Link, Tag

    _clean(db)
    a = _add(db, "application", f"{PFX}-payment-service")
    b = _add(db, "application", f"{PFX} Payment Service", source="llm")
    c = _add(db, "application", f"{PFX}_payment_svc")
    d = _add(db, "component", f"{PFX}PaymentService")          # the same thing proposed as a component too
    e = _add(db, "application", f"{PFX}-payment-service-prd")
    other = _add(db, "application", f"{PFX}-payment-gateway")  # another thing
    host1 = _add(db, "server", f"{PFX}-srv-01", source="data")
    host2 = _add(db, "server", f"{PFX}-srv-02", source="data")
    db.session.add(Tag(ref="doc:1", facet_id=c.id, status="proposed", confidence=0.8))
    db.session.add(Link(a_ref=f"facet:{d.id}", b_ref=f"facet:{other.id}", kind="calls", status="proposed",
                        source="docs"))
    db.session.commit()
    try:
        out = C.run(llm_calls=0)
        left = {f.value: f for f in db.session.query(Facet).filter(Facet.value.ilike(PFX + "%"))}
        payment = [f for f in left.values() if "payment" in f.value.lower() and "gateway" not in f.value.lower()]
        assert len(payment) == 1, sorted(left)                   # five proposals: one
        one = payment[0]
        names = {one.value} | set(one.synonyms or [])
        assert {f"{PFX} Payment Service", f"{PFX}_payment_svc", f"{PFX}PaymentService",
                f"{PFX}-payment-service-prd"} - {one.value} <= names
        assert f"{PFX}-payment-gateway" in left and f"{PFX}-srv-01" in left and f"{PFX}-srv-02" in left
        assert db.session.query(Tag).filter(Tag.ref == "doc:1", Tag.facet_id == one.id).count() == 1   # its items
        assert db.session.query(Link).filter(Link.a_ref == f"facet:{one.id}",                            # its links
                                             Link.b_ref == f"facet:{other.id}").count() == 1
        assert out["merged"] == 4 and out["groups"] == 1
    finally:
        _clean(db)


def test_a_persons_value_is_kept_its_twins_wait_as_the_same(ctx):
    from superset.extensions import db

    from supagent.knowledge import consolidate as C
    from supagent.models import Facet

    _clean(db)
    mine = _add(db, "application", f"{PFX}-billing", status="approved", source="admin")
    p1 = _add(db, "application", f"{PFX} Billing")
    p2 = _add(db, "application", f"{PFX}-billing-stg", source="llm")
    twin = _add(db, "application", f"{PFX}_BILLING", status="approved", source="admin")   # people made both
    db.session.commit()
    try:
        out = C.run(llm_calls=0, mode="propose")
        db.session.expire_all()
        for p in (p1, p2):
            sug = db.session.get(Facet, p.id).suggested or {}
            assert sug.get("same_as") in (mine.id, twin.id) and sug.get("same_by") == "learning"
        assert db.session.get(Facet, mine.id).status == "approved" and db.session.get(Facet, twin.id) is not None
        assert out["same_as"] == 2 and out["merged"] == 0
        n = C.merge_suggested("admin", "application")             # To review's "Merge them"
        assert n == 2
        db.session.expire_all()
        assert db.session.get(Facet, p1.id) is None and db.session.get(Facet, p2.id) is None
        kept = [db.session.get(Facet, i) for i in (mine.id, twin.id)]
        names = set().union(*[{f.value} | set(f.synonyms or []) for f in kept])
        assert f"{PFX} Billing" in names and f"{PFX}-billing-stg" in names
        assert all(f.status == "approved" for f in kept)          # people's values: never merged together here
    finally:
        _clean(db)


def test_auto_merges_a_strong_twin_of_a_persons_value_at_once(ctx):
    from superset.extensions import db

    from supagent.knowledge import consolidate as C
    from supagent.models import Facet

    _clean(db)
    mine = _add(db, "component", f"{PFX}-redis-cache", status="approved", source="admin")
    p = _add(db, "component", f"{PFX} Redis Cache")
    q = _add(db, "component", f"{PFX}-redis-cache-v2")           # a version apart: a doubt, left as it is
    db.session.commit()
    try:
        out = C.run(llm_calls=0, mode="auto")
        db.session.expire_all()
        assert db.session.get(Facet, p.id) is None and f"{PFX} Redis Cache" in (db.session.get(Facet, mine.id).synonyms or [])
        assert db.session.get(Facet, q.id) is not None and not (db.session.get(Facet, q.id).suggested or {}).get("same_by")
        assert out["merged"] == 1 and out["doubts"] >= 1
    finally:
        _clean(db)


class _Judge:
    """A scripted LLM: groups the doubtful names it is shown (by their numbers)."""

    def __init__(self, answer):
        self.answer, self.seen = answer, []

    def chat(self, messages, tools=None, max_tokens=None):
        self.seen.append(messages[-1]["content"])
        return {"role": "assistant", "content": self.answer(messages[-1]["content"])}


def test_the_doubts_go_to_the_llm_and_its_answer_is_checked(ctx):
    from superset.extensions import db

    from supagent.knowledge import consolidate as C
    from supagent.models import Facet

    _clean(db)
    full = _add(db, "application", f"{PFX} order management system")
    short = _add(db, "application", f"{PFX} OMS")
    api = _add(db, "application", f"{PFX}-inventory")
    api2 = _add(db, "application", f"{PFX}-inventory-api")
    db.session.commit()

    def answer(text):
        lines = text.splitlines()
        oms = [ln.split(".")[0] for ln in lines if "order management" in ln or " OMS" in ln]
        return '{"groups": [[%s], [99, 0]]}' % ", ".join(oms)       # a number out of range: dropped

    judge = _Judge(answer)
    try:
        res = C.plan(llm=judge, llm_calls=5)
        assert judge.seen and res["asked"] >= 1
        groups = [{f.id for f in [g["keep"]] + g["others"]} for g in res["groups"]]
        assert {full.id, short.id} in groups
        assert not any({api.id, api2.id} <= g for g in groups)      # the LLM did not say so: apart
        C.apply(res)
        db.session.commit()
        db.session.expire_all()
        assert (db.session.get(Facet, full.id) is None) != (db.session.get(Facet, short.id) is None)
        assert C.plan(llm=None, llm_calls=0)["asked"] == 0           # no LLM: the doubts stay apart
    finally:
        _clean(db)


def test_to_review_merges_the_other_names_together(app):
    from superset.extensions import db

    from supagent.knowledge import consolidate as C
    from supagent.models import Facet

    with app.app_context():
        _clean(db)
        mine = _add(db, "application", f"{PFX}-ledger", status="approved", source="admin")
        p = _add(db, "application", f"{PFX} Ledger")
        db.session.commit()
        C.run(llm_calls=0, mode="propose")
        ids = (mine.id, p.id)
        db.session.remove()
    try:
        c = app.test_client()
        login(c, "admin")
        d = c.get("/supagent/admin/api/review").get_json()
        assert d["same"].get("application", 0) >= 1
        r = c.post("/supagent/admin/api/facets/merge-same", json={"facet": "application"})
        assert r.status_code == 200 and r.get_json()["merged"] >= 1
        c2 = app.test_client()
        login(c2, "alice")
        assert c2.post("/supagent/admin/api/facets/merge-same", json={}).status_code in (401, 403)
    finally:
        with app.app_context():
            assert db.session.get(Facet, ids[1]) is None
            _clean(db)
            db.session.remove()


class _Value:
    """A value as plan() reads it (no database row)."""

    def __init__(self, i, value, facet="application", status="proposed", source="docs"):
        self.id, self.value, self.facet, self.status, self.source = i, value, facet, status, source
        self.synonyms, self.reviewed_by, self.description, self.suggested = [], None, "", None


def test_the_name_kept_is_written_out_without_environment(ctx):
    from supagent.knowledge import consolidate as C

    group = [_Value(1, "payment-svc"), _Value(2, "payment-service-prd"), _Value(3, "Payment Service"),
             _Value(4, "payment_svc")]
    assert C._canonical(group, {1: 5, 4: 2}).value == "Payment Service"      # (used more, still a short form)
    assert C._canonical(group + [_Value(5, "PAYMENT_SVC", source="data")], {}).value == "PAYMENT_SVC"
    assert C._canonical(group + [_Value(6, "pay-svc", status="approved", source="admin")], {}).value == "pay-svc"


def test_the_llm_is_asked_by_small_groups_once(ctx):
    from superset.extensions import db

    from supagent.knowledge import consolidate as C
    from supagent.models import Meta

    db.session.query(Meta).filter(Meta.key == C.ASKED).delete()
    db.session.commit()
    values = [_Value(100, "settlement sync")] + [_Value(i, f"{w} settlement sync") for i, w in enumerate(
        ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india", "juliet", "kilo", "lima",
         "mike", "november", "oscar", "papa", "quebec", "romeo", "sierra", "tango", "uniform", "victor", "whiskey",
         "xray", "yankee", "zulu"], start=1)]           # (0.10.10: "x settlement sync" and "y settlement sync" are
    #                                                     two; each with "settlement sync" a doubt)
    judge = _Judge(lambda text: '{"groups": []}')
    try:
        res = C.plan(values=values, llm=judge, llm_calls=2)
        assert res["doubts"] >= 25 and res["asked"] == 2 and len(judge.seen) == 2
        assert all(len(t.splitlines()) <= C.GROUP_MAX for t in judge.seen)      # 26 names: 12 at most at once
        C.apply(res)
        db.session.commit()
        again = C.plan(values=values, llm=judge, llm_calls=5)
        assert again["asked"] == 1 and len(judge.seen) == 3                      # the third part only, then none
        C.apply(again)
        db.session.commit()
        assert C.plan(values=values, llm=judge, llm_calls=5)["asked"] == 0 and len(judge.seen) == 3
    finally:
        db.session.query(Meta).filter(Meta.key == C.ASKED).delete()
        db.session.commit()


def test_the_maps_structure_keeps_parts_apart():
    from supagent.knowledge.consolidate import _apart_by_structure

    wholes = {1: {10}, 2: {20}, 3: {10}, 10: set()}
    assert _apart_by_structure(1, 2, wholes)          # parts of two services
    assert not _apart_by_structure(1, 3, wholes)      # two parts of one service: their names decide
    assert _apart_by_structure(1, 10, wholes)         # a module and its own service
    assert not _apart_by_structure(1, 4, wholes)      # the other one is part of nothing known


def test_an_llm_group_never_joins_two_things_through_a_third(ctx):
    """(0.10.10) The LLM answers "ticket bridge, tb, teams bridge are one": tb is the initials of both, and the two
    names differ by a word of their own: nothing is joined to the other through tb."""
    from superset.extensions import db

    from supagent.knowledge import consolidate as C
    from supagent.models import Meta

    db.session.query(Meta).filter(Meta.key == C.ASKED).delete()
    db.session.commit()
    values = [_Value(1, "ticket bridge"), _Value(2, "tb"), _Value(3, "teams bridge"), _Value(4, "tvr sync"),
              _Value(5, "tvr gateway")]
    judge = _Judge(lambda text: '{"groups": [[1, 2, 3, 4, 5]]}')
    try:
        res = C.plan(values=values, llm=judge, llm_calls=3)
        assert judge.seen and res["asked"] >= 1                                  # (the LLM was asked)
        joined = [{f.value for f in [g["keep"]] + g["others"]} for g in res["groups"]]
        assert not any({"ticket bridge", "teams bridge"} <= g or "tb" in g or {"tvr sync", "tvr gateway"} <= g
                       for g in joined), joined
    finally:
        db.session.query(Meta).filter(Meta.key == C.ASKED).delete()
        db.session.commit()
