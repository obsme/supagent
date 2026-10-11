"""(0.10.7, user: "I want to adapt itself automatically for different llm types") supagent finds what an LLM server
does (a few small calls of made-up text: does the model reason first, does a short answer come back empty, does the
server take reasoning_effort, chat_template_kwargs, tool_choice required and none, how it writes a name, its context),
keeps it for every process, and each process adapts from its first call; what the answers teach (a field refused, a
reasoning seen) is kept too. A server that takes everything (Qwen on llama.cpp) changes nothing."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from supagent import llm as L


def _server(answer):
    """A fake OpenAI-compatible server: answer(body) -> (status, message, finish, usage); /models lists one model."""
    state = {"bodies": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # noqa: D401
            pass

        def _send(self, status, payload):
            out = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def do_GET(self):  # noqa: N802
            if self.path.endswith("/models"):
                return self._send(200, {"data": [{"id": state["model"], "max_model_len": state.get("ctx")}]})
            return self._send(404, {"error": "no"})

        def do_POST(self):  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            state["bodies"].append(body)
            status, msg, finish, usage = answer(body)
            if status != 200:
                return self._send(status, {"error": {"message": msg}})
            self._send(200, {"choices": [{"message": {"role": "assistant", **msg}, "finish_reason": finish}],
                             "usage": usage})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    return srv, state


@pytest.fixture()
def clean(ctx):
    """No stored profile, and this process's tables empty, before and after."""
    from superset.extensions import db

    from supagent.models import Meta

    def wipe():
        for table in (L._CHOICE, L._NONE, L._EFFORT, L._TEMPLATE_KWARGS, L._REASONING):
            table.clear()
        L._PROFILE["read_at"].clear()
        L._PROFILE["value"] = None
        db.session.query(Meta).filter(Meta.key == L.PROFILE_KEY).delete()
        db.session.commit()

    wipe()
    yield
    wipe()


def qwen_like(body):
    """Takes everything, never reasons, calls the tool when it has one."""
    if body.get("tools") and body.get("tool_choice") != "none":
        return 200, {"content": "", "tool_calls": [{"id": "1", "type": "function", "function": {
            "name": "ticket_status", "arguments": "{\"number\": \"4711\"}"}}]}, "tool_calls", {}
    text = body["messages"][-1]["content"]
    return 200, {"content": "OK" if "OK" in text else text.split(": ", 1)[-1]}, "stop", {}


def gpt_oss_like(body):
    """Reasons before each answer (counted in max_tokens), only tool_choice auto, typographic hyphens."""
    if body.get("tool_choice") in ("required", "none"):
        return 400, "tool_choice: only 'auto' is supported for this model", None, None
    if (body.get("max_tokens") or 0) < 200:                       # its reasoning took the tokens
        return 200, {"content": "", "reasoning_content": "The user wants"}, "length", \
            {"completion_tokens_details": {"reasoning_tokens": body.get("max_tokens")}}
    if body.get("tools"):
        return 200, {"content": "", "reasoning_content": "call it", "tool_calls": [{"id": "1", "type": "function",
                     "function": {"name": "ticket_status", "arguments": "{\"number\": \"4711\"}"}}]}, "tool_calls", {}
    text = body["messages"][-1]["content"]
    said = "OK" if "OK" in text else text.split(": ", 1)[-1].replace("-", "‑")
    return 200, {"content": said, "reasoning_content": "easy"}, "stop", {}


def test_a_server_that_takes_everything_changes_nothing(clean):
    srv, st = _server(qwen_like)
    st["model"] = "qwen3.6-35b-a3b"
    try:
        prof = L.LLM(L.LLMConfig(base_url=st["url"], model="qwen3.6-35b-a3b")).probe()
        assert prof["family"] == "qwen" and not prof["reasons"] and prof["tool_calls"] is True
        assert prof["tool_choice_required"] and prof["tool_choice_none"] and prof["reasoning_effort"]
        assert not prof["typography"] and not prof["short_answer_empty"]
        assert prof["said"][1].startswith("nothing to adapt")
        assert L.stored_profile()["model"] == "qwen3.6-35b-a3b"
    finally:
        srv.shutdown()


def test_a_model_that_thinks_unless_told_not_to_is_profiled_as_the_agent_calls_it(clean):
    """Qwen3 thinks by default; the agent sends enable_thinking false: called so, it does not reason first (a probe
    without the switch had taken it for a reasoning model: room and no stop strings for every call)."""
    def qwen_thinking(body):
        if (body.get("chat_template_kwargs") or {}).get("enable_thinking") is False:
            return qwen_like(body)
        return 200, {"content": "", "reasoning_content": "Let me think"}, "length", {}

    srv, st = _server(qwen_thinking)
    st["model"] = "Qwen3.6-35B-A3B-UD-Q4_K_XL.gguf"
    try:
        prof = L.LLM(L.LLMConfig(base_url=st["url"], model=st["model"])).probe()
        assert not prof["reasons"] and not prof["short_answer_empty"] and prof["template_kwargs"] is True
        assert not L._REASONING
    finally:
        srv.shutdown()


def test_a_reasoning_model_on_a_server_with_auto_only_is_found_and_every_process_adapts(clean):
    srv, st = _server(gpt_oss_like)
    st.update(model="corp-chat-large", ctx=131072)                  # a gateway's alias: no "gpt-oss" in the name
    try:
        prof = L.LLM(L.LLMConfig(base_url=st["url"], model="corp-chat-large")).probe()
        assert prof["reasons"] and prof["short_answer_empty"] and prof["reasoning_field"] == "reasoning_content"
        assert prof["tool_choice_required"] is False and prof["tool_choice_none"] is False
        assert prof["typography"] and prof["context"] == 131072 and prof["tool_calls"] is True
        said = " | ".join(prof["said"])
        assert "reasons before it answers" in said and "refuses tool_choice \"required\"" in said
        # another process: its tables empty, the stored profile applied by its first client
        for table in (L._CHOICE, L._NONE, L._EFFORT, L._TEMPLATE_KWARGS, L._REASONING):
            table.clear()
        L._PROFILE["read_at"].clear()
        st["bodies"].clear()
        client = L.LLM(L.LLMConfig(base_url=st["url"], model="corp-chat-large"))
        tool = {"type": "function", "function": {"name": "ticket_status", "parameters": {"type": "object"}}}
        msg = client.chat([{"role": "user", "content": "status of 4711?"}], tools=[tool], tool_choice="required",
                          max_tokens=100)
        assert msg["tool_calls"] and len(st["bodies"]) == 1         # no refused call first: adapted at once
        assert st["bodies"][0]["tool_choice"] == "auto" and st["bodies"][0]["max_tokens"] == 100 + L.REASONING_TOKENS
    finally:
        srv.shutdown()


def test_what_the_answers_teach_is_kept_for_the_other_processes(clean):
    def no_effort(body):
        if "reasoning_effort" in body:
            return 400, "unknown field reasoning_effort", None, None
        return 200, {"content": "OK"}, "stop", {}

    srv, st = _server(no_effort)
    st["model"] = "m1"
    try:
        client = L.LLM(L.LLMConfig(base_url=st["url"], model="m1", reasoning_effort="high"))
        assert client.chat([{"role": "user", "content": "Reply OK"}])["content"] == "OK"
        assert L.stored_profile()["reasoning_effort"] is False and L.stored_profile()["source"] == "answers"
        L._EFFORT.clear()
        L._PROFILE["read_at"].clear()
        st["bodies"].clear()
        L.LLM(L.LLMConfig(base_url=st["url"], model="m1", reasoning_effort="high")).chat(
            [{"role": "user", "content": "Reply OK"}])
        assert "reasoning_effort" not in st["bodies"][0]            # the next process: not sent at all
    finally:
        srv.shutdown()


def test_the_family_of_a_model_by_its_name():
    assert [L.family_of(m) for m in ("openai/gpt-oss-120b", "Qwen3.6-35B-A3B", "meta-llama/Llama-3.3-70B",
                                     "mistral-large", "deepseek-r1", "corp-chat")] == \
        ["gpt-oss", "qwen", "llama", "mistral", "deepseek", "other"]
