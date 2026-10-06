"""The router (MOA): the LLM's route used when it is confident enough, the normal way otherwise; confirmed
examples override the LLM only when several close ones agree or an admin set one; only the routes the execution
kept to are examples; the classic agent gets the route's tools and instruction; the governed pipeline sends the
routes only the classic agent's tools answer to it and records the route on the answer's row."""

from __future__ import annotations

import json

import pytest

from test_agent_loop import ScriptedLLM


def route_call(route, confidence="high", second="", scores=None):
    args = {"route": route, "confidence": confidence, "second": second, "why": "test"}
    if scores is not None:
        args = {"route": route, "scores": scores, "why": "test"}
    return {"role": "assistant", "content": "", "tool_calls": [{"id": "r", "type": "function", "function": {
        "name": "route_question", "arguments": json.dumps(args)}}]}


def read_call(restated="", general=False):
    return {"role": "assistant", "content": "", "tool_calls": [{"id": "q", "type": "function", "function": {
        "name": "read_question", "arguments": json.dumps({"restated": restated, "general": general})}}]}


class Recording(ScriptedLLM):
    def chat(self, messages, tools=None, max_tokens=None, tool_choice=None):
        self.tools = [*getattr(self, "tools", []), [t["function"]["name"] for t in tools or []]]
        return super().chat(messages, tools, max_tokens, tool_choice)


@pytest.fixture()
def on(ctx, monkeypatch):
    from supagent import settings

    real = settings.get
    conf = {"agent.router": True, "router.min_confidence": "medium", "agent.read_question": False}
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    yield conf


def test_the_llm_route_when_sure_else_the_normal_way(on):
    from supagent import router

    d = router.decide("Why was the report late yesterday?", llm=ScriptedLLM([route_call("incident")]), shown=[],
                      found=[])
    assert (d.route, d.by, d.active) == ("incident", "llm", True)
    d = router.decide("Tell me about it", llm=ScriptedLLM([route_call("functional", "low")]), shown=[], found=[])
    assert (d.route, d.by, d.active) == ("other", "fallback", False)
    on["router.min_confidence"] = "low"
    d = router.decide("Tell me about it", llm=ScriptedLLM([route_call("functional", "low")]), shown=[], found=[])
    assert d.route == "functional"
    garbled = {"role": "assistant", "content": "I think this is about servers"}
    assert router.decide("Tell me", llm=ScriptedLLM([garbled]), shown=[], found=[]).route == "other"
    on["agent.router"] = False
    assert router.decide("Why was the report late?", llm=ScriptedLLM([route_call("incident")])).by == "off"


def test_confirmed_examples_override_only_when_several_agree_or_an_admin_set_one(on):
    from supagent import router

    one = [{"question": "why did the batch fail", "route": "incident", "similarity": 0.93}]
    d = router.decide("why did the batch fail last night", llm=ScriptedLLM([route_call("technical")]), shown=one,
                      found=[])
    assert (d.route, d.by) == ("technical", "llm")                       # one example never flips the LLM
    two = one + [{"question": "what made the batch fail", "route": "incident", "similarity": 0.9}]
    d = router.decide("why did the batch fail last night", llm=ScriptedLLM([route_call("technical")]), shown=two,
                      found=[])
    assert (d.route, d.by) == ("incident", "examples")
    split = two + [{"question": "how does the batch work", "route": "technical", "similarity": 0.85}]
    d = router.decide("why did the batch fail last night", llm=ScriptedLLM([route_call("technical")]), shown=split,
                      found=[])
    assert d.by == "llm"                                                  # the close examples disagree
    admin = [{"question": "batch failures", "route": "observability", "similarity": 0.95, "admin": True}]
    d = router.decide("batch failures?", llm=ScriptedLLM([route_call("incident")]), shown=admin, found=[])
    assert (d.route, d.by) == ("observability", "admin example")
    far = [{"question": "x", "route": "incident", "similarity": 0.5}] * 3
    assert router.decide("q", llm=ScriptedLLM([route_call("charts")]), shown=far, found=[]).route == "charts"
    messages = ScriptedLLM([route_call("incident")])
    similar = [{"question": "what made the payroll run late", "route": "incident", "similarity": 0.7}]
    router.decide("why did the batch fail", llm=messages, shown=two + similar,
                  found=[{"kind": "guide", "title": "Batch chain", "facets": "aspect: technical"}])
    prompt = messages.seen[0][-1]["content"]
    assert "incident: what made the payroll run late" in prompt and "guide: Batch chain [aspect: technical]" in prompt
    assert "why did the batch fail\n" not in prompt.split("Question:")[0]       # the same question only votes


def test_an_admin_decides_alone_only_by_setting_the_route_itself(on):
    """An admin confirming an answer judged the answer, not its route: that example votes like the others; a
    route an admin kept or corrected (To review) decides alone for the same question."""
    from superset.extensions import db

    from supagent import router
    from supagent.models import Route

    from supagent.knowledge.resolve import terms

    db.session.query(Route).delete()
    q = "why did the payroll batch fail last night"
    r = Route(question=q, terms=" ".join(terms(q)), shown=[], chosen=[], used=[], moa="charts", moa_by="llm",
              moa_followed=True, signal="confirmed")               # an admin confirmed the answer
    db.session.add(r)
    db.session.commit()
    try:
        shown = router._examples_by_words(q, 6)
        assert shown and not shown[0]["admin"]
        d = router.decide(q, llm=ScriptedLLM([route_call("incident")]), shown=shown, found=[])
        assert (d.route, d.by) == ("incident", "llm")
        r.moa_by = "admin"                                         # an admin set the route itself
        db.session.commit()
        shown = router._examples_by_words(q, 6)
        assert shown[0]["admin"]
        d = router.decide(q, llm=ScriptedLLM([route_call("incident")]), shown=shown, found=[])
        assert (d.route, d.by) == ("charts", "admin example")
    finally:
        db.session.query(Route).delete()
        db.session.commit()


def test_one_wrong_example_of_the_same_question_never_decides(on):
    """The LLM never sees a close example (it would follow it); alone, it does not vote either."""
    from supagent import router

    wrong = [{"question": "why was the report late yesterday", "route": "charts", "similarity": 0.97}]
    llm = ScriptedLLM([route_call("incident")])
    d = router.decide("why was the report late yesterday", llm=llm, shown=wrong, found=[])
    assert (d.route, d.by) == ("incident", "llm")
    assert "charts: why was the report late" not in llm.seen[0][-1]["content"]


def test_the_confidence_is_how_far_the_best_score_is_ahead(on):
    from supagent import router

    def decide(route, scores):
        return router.decide("q", llm=ScriptedLLM([route_call(route, scores=scores)]), shown=[], found=[])

    d = decide("incident", {"incident": 90, "observability": 40, "functional": 10})
    assert (d.route, d.confidence, d.second, d.by) == ("incident", "high", "", "llm")
    assert d.scores["incident"] == 90
    d = decide("incident", {"incident": 80, "infrastructure": 60})
    assert (d.route, d.confidence, d.second) == ("incident", "medium", "infrastructure")
    assert decide("incident", {"incident": 70, "infrastructure": 65}).route == "other"      # too close: normal way
    assert decide("charts", {"charts": 40}).route == "other"                                 # nothing fits well
    assert decide("charts", {"functional": 90, "charts": 50}).route == "other"               # it hesitates
    assert decide("functional", {"functional": "95", "technical": "x"}).route == "functional"   # tolerant


def test_only_confirmed_routes_the_execution_kept_to_teach(on):
    from superset.extensions import db

    from supagent import router
    from supagent.governed.gate import confirm
    from supagent.models import Route

    db.session.query(Route).delete()
    db.session.commit()
    kept = router.record(None, "why did the payroll batch fail on monday",
                         router.Decision(route="incident", llm="incident", confidence="high", by="llm"))
    dropped = router.record(None, "why did the payroll batch fail on tuesday",
                            router.Decision(route="incident", llm="incident", confidence="high", by="llm"))
    router.left(dropped)                                                   # the execution left the route
    for rid, mid in ((kept, 9001), (dropped, 9002)):
        r = db.session.get(Route, rid)
        r.message_id = mid
    db.session.commit()
    confirm(9001, "helpful")
    confirm(9002, "helpful")
    found = router._examples_by_words("why did the payroll batch fail", 6)
    assert [e["route"] for e in found] == ["incident"] and "monday" in found[0]["question"]
    confirm(9001, "not_helpful")
    assert router._examples_by_words("why did the payroll batch fail", 6) == []
    db.session.query(Route).delete()
    db.session.commit()


def test_the_classic_agent_gets_the_routes_tools_and_instruction(on, monkeypatch):
    from supagent.agent import TOOLS_OF, Agent
    from supagent.router import ROUTE_NOTES

    a = object.__new__(Agent)
    a.username, a.rich = "admin", True
    a.llm = ScriptedLLM([route_call("charts")])
    names = sorted(TOOLS_OF["charts"] | {"execute_sql"})
    a.specs = [{"type": "function", "function": {"name": n}} for n in names]
    monkeypatch.setattr(Agent, "_system", lambda self, q, shown=None: "SYSTEM")
    monkeypatch.setattr(Agent, "_question_blocks", lambda self, q, shown=None: "")
    messages = a.prompt("Show me what the jobs look like", [])
    assert a.moa.route == "charts" and ROUTE_NOTES["charts"] in messages[-1]["content"]
    offered = {s["function"]["name"] for s in a._specs_for("Show me what the jobs look like")}
    assert "generate_chart" in offered                  # a chart tool, though the words name no chart
    assert a.prompt("Show me what the jobs look like", []) and len(a.llm.seen) == 1     # routed once
    from superset.extensions import db

    from supagent.models import Route

    a.after_saved(4242)
    r = db.session.get(Route, a.route_id)
    assert (r.moa, r.moa_followed, r.message_id) == ("charts", True, 4242)
    db.session.delete(r)
    db.session.commit()


def test_the_governed_pipeline_sends_chart_and_incident_questions_to_the_classic_agent(on, no_ledger, monkeypatch):
    from test_governed_pipeline import governed

    from supagent.agent import Agent

    said = {"role": "assistant", "content": "The batch failed on srv-a-1 at 03:05."}
    a, _ran = governed(monkeypatch, [route_call("incident"), said, said, said])       # the classic checks may ask again
    monkeypatch.setattr(Agent, "route", Agent.route)
    answer, trace = a.ask("Why was the report late on 23 September?", [])
    assert [s["tool"] for s in trace][:1] == ["route"] and "srv-a-1" in answer
    assert a.way.startswith("classic: the router: incident")


def test_the_reading_is_a_call_of_its_own_and_the_route_is_asked_as_before(on):
    """(0.9.6) Asked in the routing call, the reading made the routes worse (0.734 against 0.761 on the router's
    suite): the route is asked with its instruction and tool alone, the reading with its own, at the same time;
    both calls are counted in the answer's usage."""
    from supagent import router

    on["agent.read_question"] = True
    llm = Recording([route_call("incident"), read_call("Why was the daily report late on 5 October", False)])
    d = router.decide("Why was the report late yesterday?", llm=llm, shown=[], found=[])
    assert (d.route, d.restated, d.general) == ("incident", "Why was the daily report late on 5 October", False)
    assert llm.tools == [["route_question"], ["read_question"]]
    route_msgs, read_msgs = llm.seen
    assert route_msgs[0]["content"] == router.ROUTER_SYSTEM and read_msgs[0]["content"] == router.READ_SYSTEM
    assert route_msgs[1:] == read_msgs[1:]                                  # what both are shown
    assert "restated" not in json.dumps(router.ROUTE_TOOL) and d.usage["calls"] == 2
    # a general question: said by the reading
    d = router.decide("How do I loop over the lines of a file in bash?", shown=[], found=[],
                      llm=ScriptedLLM([route_call("other"), read_call("A bash loop over the lines of a file", True)]))
    assert d.general is True
    # a word of the team's glossary in the question: never general
    glossary = [{"kind": "glossary", "title": "pool saturation (glossary)"}]
    d = router.decide("What does pool saturation mean?", shown=[], found=glossary,
                      llm=ScriptedLLM([route_call("functional"), read_call("What pool saturation means", True)]))
    assert d.general is False and d.restated == "What pool saturation means"
    # the reading fails: the route stands, the question as it was asked
    d = router.decide("Why was the report late yesterday?", shown=[], found=[],
                      llm=ScriptedLLM([route_call("incident"), RuntimeError("the model is down")]))
    assert (d.route, d.restated, d.general) == ("incident", "", False)
    # off: one call
    on["agent.read_question"] = False
    llm = Recording([route_call("incident")])
    d = router.decide("Why was the report late yesterday?", llm=llm, shown=[], found=[])
    assert llm.tools == [["route_question"]] and d.restated == "" and d.usage["calls"] == 1


def test_a_real_client_reads_the_question_on_its_own_client_at_the_same_time(on, monkeypatch):
    """A real client: the reading runs in a thread on a client of its own (the routing call's time bound is set on
    the router's client, never on the reader's), and both are waited for."""
    import threading
    import types

    from supagent import llm as L, router

    on["agent.read_question"] = True
    both = threading.Barrier(2, timeout=5)              # each call waits for the other: they run at the same time
    made = []

    class Client(ScriptedLLM):
        def __init__(self, cfg=None, replies=()):
            super().__init__(list(replies) or [read_call("Why was the daily report late on 5 October")])
            self.cfg = cfg if cfg is not None else types.SimpleNamespace(timeout=300)
            made.append(self)

        def chat(self, messages, tools=None, max_tokens=None, tool_choice=None):
            import flask

            both.wait()
            self.context = (flask.has_app_context(), L._TASK.get())     # pylint: disable=protected-access
            return super().chat(messages, tools, max_tokens, tool_choice)

    monkeypatch.setattr(L, "LLM", Client)
    routing = Client(replies=[route_call("incident")])
    with L.llm_task("answer", message_id=4711):
        d = router.decide("Why was the report late yesterday?", llm=routing, shown=[], found=[])
    assert (d.route, d.restated) == ("incident", "Why was the daily report late on 5 October")
    reader = made[1]
    assert reader is not routing and reader.cfg is not routing.cfg and routing.cfg.timeout == 300
    assert d.usage["calls"] == 2
    # the reader's thread has the app (its call is recorded) and the answer's context (recorded as the answer's)
    assert reader.context[0] is True and (reader.context[1] or {}).get("message_id") == 4711


def test_the_real_client_reads_the_question_and_both_calls_are_recorded(on, ctx):
    """The real HTTP client against a local server: the route and the reading are asked, each with its own tool,
    and both calls are recorded as the answer's (supagent_llm_call), the reading's from its own thread."""
    import http.server
    import threading

    from superset.extensions import db

    from supagent import llm as L, router
    from supagent.models import LLMCall

    asked = []

    class Stub(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            tool = body["tools"][0]["function"]["name"]
            asked.append(tool)
            msg = route_call("incident") if tool == "route_question" else read_call("Why was the report late on 5 October")
            out = json.dumps({"choices": [{"message": msg}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out.encode())

        def log_message(self, *a):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        on["agent.read_question"] = True
        before = db.session.query(LLMCall).filter(LLMCall.message_id == 4712).count()
        client = L.LLM(L.LLMConfig(base_url=f"http://127.0.0.1:{server.server_port}/v1", model="stub"))
        with L.llm_task("answer", message_id=4712):
            d = router.decide("Why was the report late yesterday?", llm=client, shown=[], found=[])
        assert (d.route, d.restated, d.usage["calls"]) == ("incident", "Why was the report late on 5 October", 2)
        assert sorted(asked) == ["read_question", "route_question"]
        db.session.commit()
        assert db.session.query(LLMCall).filter(LLMCall.message_id == 4712).count() == before + 2
    finally:
        server.shutdown()


def test_by_default_the_question_is_not_read_and_nothing_of_a_reading_reaches_the_answer(ctx, monkeypatch):
    """(0.9.6, measured) The reading misled follow-ups; it is off by default: the router makes its one call with its
    own prompt, nothing is restated, no question is taken for a general one."""
    from supagent import router, settings
    from supagent.agent import Agent

    assert settings.get("agent.read_question") is False                  # the default
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: True if key == "agent.router" else real(key))
    llm = Recording([route_call("functional")])
    d = router.decide("What share of all the orders of that day is that?", llm=llm, shown=[], found=[])
    assert llm.tools == [["route_question"]] and llm.seen[0][0]["content"] == router.ROUTER_SYSTEM
    assert (d.restated, d.general) == ("", False) and d.usage["calls"] == 1
    a = object.__new__(Agent)
    a.moa = d
    assert a._general("How do I loop over the files of a folder in bash?", "") is False   # no general path
