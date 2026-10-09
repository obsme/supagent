"""(0.10.5) A value with no description, one a person added included, gets one written by the AI from what is known of
it (the sentences that name it, its links, where the data has it) and from that only; a value nothing describes gets
nothing; a person's description is never written over; the AI's says so on the System map until a person saves one."""

from __future__ import annotations

import json

from test_dictionary_080 import _client

NAMES = ("zz-orders", "zz-shop", "zz-mine", "zz-unknown")


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def chat(self, messages, tools=None, max_tokens=None):
        text = messages[-1]["content"]
        self.prompts.append(text)
        out = []
        for line in text.splitlines():
            if ". zz-orders (" in line:
                out.append({"n": int(line.split(".", 1)[0]), "description": "The service that takes the customers' orders "
                            "and hands them to the shop."})
            elif ". " in line and line.split(".", 1)[0].isdigit():
                out.append({"n": int(line.split(".", 1)[0]), "description": "NONE"})
        return {"tool_calls": [{"function": {"name": "descriptions", "arguments": json.dumps({"descriptions": out})}}]}


def test_a_value_with_no_description_gets_the_ais_from_what_is_known_only(ctx):
    from superset.extensions import db

    from supagent.knowledge.sysmap import map_data
    from supagent.knowledge.value_about import describe_values
    from supagent.models import Facet, Link

    try:
        orders = Facet(facet="application", value=NAMES[0], status="approved", source="admin")
        shop = Facet(facet="application", value=NAMES[1], status="approved", source="admin",
                     description="The web shop where customers buy.")
        mine = Facet(facet="application", value=NAMES[2], status="approved", source="admin", description="A person's words.")
        unknown = Facet(facet="application", value=NAMES[3], status="approved", source="admin")
        db.session.add_all([orders, shop, mine, unknown])
        db.session.flush()
        db.session.add(Link(a_ref=f"facet:{shop.id}", b_ref=f"facet:{orders.id}", kind="calls", status="approved",
                            source="admin", note="places the orders"))
        db.session.commit()
        llm = FakeLLM()
        out = describe_values(llm, seconds=60)
        assert out["described"] == 1 and out["nothing_known"] >= 1
        sent = "\n".join(llm.prompts)
        assert "zz-shop calls zz-orders (places the orders)" in sent and "zz-unknown" not in sent
        db.session.expire_all()
        got = {f.value: f for f in db.session.query(Facet).filter(Facet.value.in_(NAMES))}
        assert got[NAMES[0]].description.startswith("The service that takes the customers' orders")
        assert (got[NAMES[0]].suggested or {}).get("description_by") == "llm"
        assert got[NAMES[2]].description == "A person's words." and not (got[NAMES[2]].suggested or {}).get("description_by")
        assert got[NAMES[3]].description is None
        shown = {v["value"]: v for v in map_data(True)["values"] if v["value"] in NAMES}
        assert shown[NAMES[0]]["description_by"] == "llm" and shown[NAMES[2]]["description_by"] is None
        assert describe_values(FakeLLM(), seconds=60)["described"] == 0          # done once: nothing left to write
        with _client(ctx, "admin") as c:                                             # a person saves one: theirs
            r = c.post("/supagent/dictionary/api/map", json={"describe": {"id": got[NAMES[0]].id,
                                                                      "description": "Takes the orders (edited)."}})
            assert r.status_code == 200
        db.session.expire_all()
        f = db.session.get(Facet, got[NAMES[0]].id)
        assert f.description == "Takes the orders (edited)." and not (f.suggested or {}).get("description_by")
    finally:
        db.session.rollback()
        ids = [i for (i,) in db.session.query(Facet.id).filter(Facet.value.in_(NAMES))]
        refs = [f"facet:{i}" for i in ids]
        db.session.query(Link).filter(Link.a_ref.in_(refs) | Link.b_ref.in_(refs)).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids or [-1])).delete(synchronize_session=False)
        db.session.commit()


def test_a_part_written_with_other_separators_gets_its_documents_sentences(ctx):
    from superset.extensions import db

    from supagent.knowledge.sysmap import hints, name_forms
    from supagent.models import Doc, Facet

    assert name_forms("Tix_API") == {"tix_api", "tix-api", "tix api"} and name_forms("shop") == {"shop"}
    try:
        f = Facet(facet="application", value="zz_order_desk", status="approved", source="admin")
        db.session.add(f)
        db.session.add(Doc(kind="upload", title="Desk notes", enabled=True, status="ok",
                           content="The zz-order-desk is the Python service that takes the customers' orders."))
        db.session.commit()
        from supagent.knowledge.index import index_knowledge

        index_knowledge()
        got = hints({f.id: f})
        assert got.get(f.id) and "takes the customers' orders" in got[f.id][0][2]
    finally:
        db.session.rollback()
        db.session.query(Doc).filter(Doc.title == "Desk notes").delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.value == "zz_order_desk").delete(synchronize_session=False)
        db.session.commit()
