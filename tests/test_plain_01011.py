"""(0.10.11) The closing summary of an investigation after its last call: a model that begins one more call when no
tool is declared (cut at its markup: an empty answer, the same each time) is asked with its tools declared and none
to call, the older results shortened; the user gets the text, not "the model wrote no text"."""
import pytest

from supagent.agent import Agent
from supagent.llm import EmptyAnswer


class FakeLLM:
    def __init__(self, reasons=False):
        self.asked = []
        self._reasons = reasons

    def reasons(self):
        return self._reasons

    def chat(self, messages, tools=None, max_tokens=None, tool_choice=None, stop=None):
        self.asked.append((bool(tools), tool_choice))
        if tools and tool_choice == "none":
            return {"role": "assistant", "content": "The cache evictions after the change caused it; it ended at 11:02."}
        raise EmptyAnswer("the LLM returned an empty answer")


def _agent(llm, specs):
    a = object.__new__(Agent)
    a.llm, a._specs = llm, specs
    return a


def test_empty_without_tools_asked_with_tools_and_none():
    llm = FakeLLM()
    messages = [{"role": "user", "content": "q"}, {"role": "tool", "content": "x" * 50000, "tool_call_id": "1"},
                {"role": "user", "content": "(No tool call is left for this answer. Write the answer now.)"}]
    msg = _agent(llm, [{"type": "function", "function": {"name": "execute_sql"}}])._plain(messages, 500)
    assert "11:02" in msg["content"]
    assert llm.asked == [(False, None), (True, "none")]


def test_no_tools_to_declare_stays_empty():
    with pytest.raises(EmptyAnswer):
        _agent(FakeLLM(), None)._plain([{"role": "user", "content": "q"}], 500)


def test_a_reasoning_model_is_not_asked_twice_the_same_way():
    llm = FakeLLM(reasons=True)
    msg = _agent(llm, [{"type": "function", "function": {"name": "execute_sql"}}])._plain(
        [{"role": "user", "content": "q"}], 500)
    assert "11:02" in msg["content"] and llm.asked == [(True, "none")]


def test_a_checks_note_says_the_question_again():
    a = object.__new__(Agent)
    a.raw_question = "Did the frontend deployment of that afternoon play a role?"
    work = [{"role": "assistant", "content": "", "tool_calls": [{"id": str(i)}]} if i % 2 == 0 else
            {"role": "tool", "content": "(rows)", "tool_call_id": str(i - 1)} for i in range(10)]
    messages = [{"role": "system", "content": "s"}, {"role": "user", "content": a.raw_question}] + work + [
                {"role": "assistant", "content": "No: the PostgreSQL logs held no error."},
                {"role": "user", "content": "(Check before answering: the part blamed, its own lines never read.)"}]
    short = [{"role": "user", "content": a.raw_question}, {"role": "user", "content": "(Check before answering: x)"}]
    a._remind(short, 1)                                        # short work: the question is close enough
    assert short[-1]["content"] == "(Check before answering: x)"
    a._remind(messages, 2)
    assert messages[-1]["content"].endswith('"Did the frontend deployment of that afternoon play a role?")')
    a._remind(messages, 2)                                     # said once
    assert messages[-1]["content"].count("Did the frontend") == 1
    first = [{"role": "user", "content": "(Check: x)"}]
    a._remind(first, 1)                                        # nothing after the question yet: left alone
    assert first[0]["content"] == "(Check: x)"
    tool = [{"role": "user", "content": "q"}, {"role": "tool", "content": "(rows)"}]
    a._remind(tool, 1)                                         # a tool's result: left alone
    assert tool[-1]["content"] == "(rows)"
