"""(0.10.7) Production runs gpt-oss-120b; the lab, Qwen3.6 with its thinking turned off. A model that always reasons
before it answers (gpt-oss: the harmony analysis channel) counts its reasoning in max_tokens: the router's 400 tokens,
the topics' 12, the test button's 16 came back empty or cut. Its calls get room to reason (known by its name, or once
its answers show reasoning), a cut empty answer is asked again with more room, no stop string cuts its reasoning, and
an answer whose server did not read the harmony format is read (its final channel; a tool call written in the
commentary channel)."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from supagent import llm as L


@pytest.fixture()
def server():
    """A fake OpenAI-compatible server answering from a list of (message, finish_reason, usage) and keeping the
    bodies it was sent."""
    state = {"answers": [], "bodies": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            state["bodies"].append(body)
            msg, finish, usage = state["answers"].pop(0)
            out = json.dumps({"choices": [{"message": {"role": "assistant", **msg}, "finish_reason": finish}],
                              "usage": usage}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    L._REASONING.clear()
    yield state
    srv.shutdown()
    L._REASONING.clear()


def test_a_model_known_to_reason_gets_room_and_no_stop(server):
    server["answers"] += [({"content": "OK", "reasoning_content": "The user wants OK."}, "stop", {})]
    client = L.LLM(L.LLMConfig(base_url=server["url"], model="gpt-oss-120b"))
    assert client.chat([{"role": "user", "content": "Reply OK"}], max_tokens=16, stop=["<tool_call>"])["content"] == "OK"
    sent = server["bodies"][-1]
    assert sent["max_tokens"] == 16 + L.REASONING_TOKENS and "stop" not in sent


def test_a_model_seen_reasoning_gets_room_from_then_on(server):
    server["answers"] += [({"content": "OK", "reasoning_content": "thinking"}, "stop", {}),
                          ({"content": "OK"}, "stop", {})]
    client = L.LLM(L.LLMConfig(base_url=server["url"], model="some-model"))
    client.chat([{"role": "user", "content": "a"}], max_tokens=16)
    assert server["bodies"][-1]["max_tokens"] == 16                     # not known yet
    client.chat([{"role": "user", "content": "b"}], max_tokens=16)
    assert server["bodies"][-1]["max_tokens"] == 16 + L.REASONING_TOKENS


def test_an_answer_cut_empty_is_asked_again_with_more_room(server):
    server["answers"] += [({"content": ""}, "length", {"completion_tokens_details": {"reasoning_tokens": 400}}),
                          ({"content": "The answer."}, "stop", {})]
    client = L.LLM(L.LLMConfig(base_url=server["url"], model="m"))
    assert client.chat([{"role": "user", "content": "q"}], max_tokens=400)["content"] == "The answer."
    assert server["bodies"][1]["max_tokens"] > server["bodies"][0]["max_tokens"] + L.REASONING_TOKENS


def test_reasoning_effort_is_sent_when_set_and_dropped_when_refused(server, monkeypatch):
    client = L.LLM(L.LLMConfig(base_url=server["url"], model="gpt-oss-120b", reasoning_effort="low"))
    server["answers"] += [({"content": "OK"}, "stop", {})]
    client.chat([{"role": "user", "content": "q"}])
    assert server["bodies"][-1]["reasoning_effort"] == "low"
    calls = []

    def refuse(self, method, path, **kw):
        body = json.loads(kw["data"])
        calls.append(body)
        if "reasoning_effort" in body:
            raise L.LLMError('LLM x/chat/completions: HTTP 400: {"error": "unknown field reasoning_effort"}')
        return type("R", (), {"json": lambda self: {"choices": [{"message": {"content": "OK"}}]}})()

    L._EFFORT.clear()
    monkeypatch.setattr(L.LLM, "_request", refuse)
    assert client.chat([{"role": "user", "content": "q"}])["content"] == "OK"
    assert "reasoning_effort" in calls[0] and "reasoning_effort" not in calls[1]
    L._EFFORT.clear()


@pytest.mark.parametrize("content, expected", [
    ("<|channel|>analysis<|message|>The user asks for 4.<|end|><|start|>assistant<|channel|>final<|message|>"
     "The answer is 4.<|return|>", "The answer is 4."),
    ("analysisThe user asks for 4. Compute.assistantfinalThe answer is 4.", "The answer is 4."),
    ("The analysis of the logs shows 4 errors.", "The analysis of the logs shows 4 errors."),   # no marker: as it was
])
def test_a_harmony_answer_the_server_did_not_read(content, expected):
    assert L.harmony_read({"content": content})["content"] == expected


def test_a_tool_call_written_in_the_commentary_channel_is_read():
    leaked = ('<|channel|>analysis<|message|>Need the data.<|end|><|start|>assistant<|channel|>commentary '
              'to=functions.execute_sql <|constrain|>json<|message|>{"request": {"database_id": 1, "sql": "SELECT 1"}}'
              '<|call|>')
    msg = L.harmony_read({"content": leaked})
    assert msg["content"] == "" and msg["tool_calls"][0]["function"]["name"] == "execute_sql"
    assert json.loads(msg["tool_calls"][0]["function"]["arguments"]) == {"request": {"database_id": 1, "sql": "SELECT 1"}}
    plain = L.harmony_read({"content": "Use execute_sql with SELECT 1."})
    assert "tool_calls" not in plain


def test_the_typography_of_gpt_oss_is_made_plain():
    """(the gpt-oss-20b probe) "orders‑db" with a non-breaking hyphen matches nothing: not the data's name in a query,
    not the tools' text in the checks; a quote curled in a query's value breaks the SQL."""
    msg = L.plain_typography({"content": "orders‑db runs on db‑pg‑01 — “primary”, 1 234 rows",
                              "tool_calls": [{"id": "1", "type": "function", "function": {
                                  "name": "execute_sql", "arguments": json.dumps(
                                      {"request": {"sql": "SELECT * FROM t WHERE name = ‘orders‑db’"}})}}]})
    assert msg["content"] == "orders-db runs on db-pg-01 — “primary”, 1 234 rows"   # dashes, quotes kept
    sql = json.loads(msg["tool_calls"][0]["function"]["arguments"])["request"]["sql"]
    assert sql == "SELECT * FROM t WHERE name = \u2018orders-db\u2019"            # hyphen plain, quotes as written
    fr = L.plain_typography({"content": "", "tool_calls": [{"id": "2", "type": "function", "function": {
        "name": "execute_sql", "arguments": json.dumps({"request": {"sql": "SELECT * FROM t WHERE team = 'l\u2019\u00e9quipe'"}})}}]})
    assert "l\u2019\u00e9quipe" in json.loads(fr["tool_calls"][0]["function"]["arguments"])["request"]["sql"]
    same = {"content": "plain text", "tool_calls": None}
    assert L.plain_typography(same) is same


def test_out_of_calls_a_reasoning_model_keeps_its_tools_with_none_to_call():
    """(the gpt-oss-20b probe, W02.1) after 16 calls the final answer was asked with no tool declared: three empty
    answers, the user got "the model wrote no text" and a raw result."""
    from supagent.agent import Agent
    from supagent.llm import EmptyAnswer

    class Fake:
        def __init__(self, reasoning):
            self.calls, self.reasoning = [], reasoning

        def reasons(self):
            return self.reasoning

        def chat(self, messages, tools=None, max_tokens=None, tool_choice=None, stop=None):
            self.calls.append((bool(tools), tool_choice))
            if tools and tool_choice == "none":
                return {"content": "The final answer."}
            if self.reasoning:
                raise EmptyAnswer("empty")
            return {"content": "The final answer, without tools."}

    a = object.__new__(Agent)
    a._specs = [{"type": "function", "function": {"name": "execute_sql"}}]
    a.llm = Fake(True)
    assert a._plain([{"role": "user", "content": "q"}], 100)["content"] == "The final answer."
    assert a.llm.calls == [(True, "none")]
    a.llm = Fake(False)                                                 # a model that does not reason: as before
    assert a._plain([{"role": "user", "content": "q"}], 100)["content"] == "The final answer, without tools."
    assert a.llm.calls == [(False, None)]


def test_tool_choice_none_is_sent_and_a_server_without_it_gets_no_tools(server, monkeypatch):
    client = L.LLM(L.LLMConfig(base_url=server["url"], model="m"))
    server["answers"] += [({"content": "OK"}, "stop", {})]
    tools = [{"type": "function", "function": {"name": "t", "parameters": {"type": "object", "properties": {}}}}]
    client.chat([{"role": "user", "content": "q"}], tools=tools, tool_choice="none")
    assert server["bodies"][-1]["tool_choice"] == "none" and server["bodies"][-1]["tools"]
    calls = []

    def refuse(self, method, path, **kw):
        body = json.loads(kw["data"])
        calls.append(body)
        if body.get("tool_choice") == "none":
            raise L.LLMError('LLM x/chat/completions: HTTP 400: {"error": "tool_choice none is not supported"}')
        return type("R", (), {"json": lambda self: {"choices": [{"message": {"content": "OK"}}]}})()

    L._NONE.clear()
    monkeypatch.setattr(L.LLM, "_request", refuse)
    assert client.chat([{"role": "user", "content": "q"}], tools=tools, tool_choice="none")["content"] == "OK"
    assert "tools" not in calls[1] and "tool_choice" not in calls[1]
    L._NONE.clear()


def test_an_output_the_server_could_not_read_is_said_at_once(monkeypatch):
    """(the gpt-oss-20b probe b) llama.cpp answered HTTP 500 "The model produced output that does not match the expected
    peg-native format": retried seven times as an outage (about three minutes), then the answer failed. It is said at
    once, and the agent reads it as an unreadable call (asked again once with a note)."""
    from supagent.agent import BAD_TOOL_CALL

    calls = {"n": 0}

    class Answer:
        status_code = 500
        text = '{"error":{"code":500,"message":"The model produced output that does not match the expected peg-native format"}}'

    client = L.LLM(L.LLMConfig(base_url="http://127.0.0.1:9/v1", model="gpt-oss-20b"))

    def request(*a, **k):
        calls["n"] += 1
        return Answer()

    monkeypatch.setattr(client.session, "request", request)
    monkeypatch.setattr(L, "RETRY_DELAYS", (0.01, 0.01, 0.01))
    with pytest.raises(L.LLMError) as err:
        client.chat([{"role": "user", "content": "q"}])
    assert calls["n"] == 1 and BAD_TOOL_CALL.search(str(err.value))
