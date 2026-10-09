"""(0.10.6) The reading of the texts for interactions keeps to its time and reads long texts to their end: the time is
checked before each window of a text (a slow LLM took minutes a window and the explanations that follow lost their
time), and a text longer than WINDOWS windows goes on at its next window in the next run (it was marked read after its
first WINDOWS windows, the rest never read); a long text marked the old way goes on after its first WINDOWS."""

from __future__ import annotations

import json

import pytest
from test_brief import system  # noqa: F401  (the fixture: Billing = Invoicing + Payments, grid-a, ledger db)
from test_knowledge import world  # noqa: F401


def _long_text(n: int) -> str:
    """n windows, each naming two known parts (so each costs a call)."""
    from supagent.knowledge import interactions as I

    block = "Payments writes its results to the ledger db. " + "filler " * (I.WINDOW // 7)
    return "\n\n".join(f"Part {i}. {block}" for i in range(n))


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def time(self) -> float:
        return self.now


class Slow:
    """An LLM that takes `cost` seconds of the clock a call and finds nothing."""

    def __init__(self, clock: Clock, cost: float) -> None:
        self.clock, self.cost, self.calls = clock, cost, 0

    def chat(self, messages, tools=None, max_tokens=None):
        self.clock.now += self.cost
        self.calls += 1
        return {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "interactions", "arguments": json.dumps({"interactions": []})}}]}


@pytest.fixture()
def long_doc(system):  # noqa: F811
    from superset.extensions import db

    from supagent.models import Classified, Doc

    d = Doc(kind="upload", title="A long runbook", content=_long_text(6), enabled=True, status="ok")
    db.session.add(d)
    db.session.commit()
    yield d
    db.session.query(Doc).delete()
    db.session.query(Classified).delete()
    db.session.commit()


def test_the_time_is_checked_before_each_window(long_doc, monkeypatch):
    from supagent.knowledge import interactions as I

    clock = Clock()
    monkeypatch.setattr(I.time, "time", clock.time)
    llm = Slow(clock, cost=100.0)
    out = I.run(llm, seconds=150.0)
    assert llm.calls == 2 and out["left"] and out["texts"] == 0        # was: the text's 4 windows, 400 s for 150
    assert out.get("texts_in_part") == 1


def test_a_long_text_goes_on_at_its_next_window_until_its_end(long_doc, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import interactions as I
    from supagent.models import Classified

    clock = Clock()
    monkeypatch.setattr(I.time, "time", clock.time)
    assert len(I.windows(long_doc.content)) == 6
    first = Slow(clock, cost=1.0)
    out = I.run(first, seconds=600.0)
    assert first.calls == I.WINDOWS and out["texts"] == 0 and out["left"]
    mark = db.session.get(Classified, f"doc:{long_doc.id}#links").content_hash
    assert mark.endswith(f"@{I.WINDOWS}")
    second = Slow(clock, cost=1.0)
    out = I.run(second, seconds=600.0)
    assert second.calls == 2 and out["texts"] == 1                     # windows 5 and 6, then the text is read
    assert I.run(Slow(clock, cost=1.0), seconds=600.0)["texts"] == 0   # nothing left: no call
    long_doc.content += "\n\nPart 7. Invoicing waits for Payments."    # changed: read again from its start
    db.session.commit()
    again = Slow(clock, cost=1.0)
    I.run(again, seconds=600.0)
    assert again.calls == I.WINDOWS


def test_a_long_text_marked_the_old_way_goes_on_after_its_first_windows(long_doc, monkeypatch):
    from superset.extensions import db

    from supagent.knowledge import interactions as I
    from supagent.knowledge.facets import _hash
    from supagent.models import Classified

    clock = Clock()
    monkeypatch.setattr(I.time, "time", clock.time)
    db.session.add(Classified(ref=f"doc:{long_doc.id}#links", content_hash=_hash(long_doc.title, long_doc.content)))
    db.session.commit()
    llm = Slow(clock, cost=1.0)
    out = I.run(llm, seconds=600.0)
    assert llm.calls == 2 and out["texts"] == 1                         # the two windows never read before


def test_a_short_text_keeps_its_mark():
    from supagent.knowledge import interactions as I

    assert I.read_mark("h", 3, 3) == "h"                                 # as before 0.10.6: read whole
    assert I.read_mark("h", 2, 3) == "h@2"
    assert I.read_mark("h", 6, 6) == "h@6"                               # a long text read whole says so
