"""(0.9.6.1) A Context page is complete: a description is cut only after a whole sentence (never "... and a"), a data
source's page gives its main indices' documents and time range and the fields (or labels) of its first main items;
an AI-written page cut by the LLM's length limit is asked to go on (a reasoning cut before its end is no page); one
page whose LLM call fails leaves the others written (the build ends "partial", saying which); a new page can be
rejected (shown to nobody, not searched, proposed again for review only when its sources change), and a version a
person refused is not proposed again."""

from __future__ import annotations

import pytest

from test_context import FakeLLM, _pages, shared  # noqa: F401  (the fixture)
from test_knowledge import world  # noqa: F401  (the fixture)

LONG = ("The index holds one document per run of a batch job. Each document says where the job ran, when it "
        "started and ended, and how it ended. The status is SUCCESS or FAILED; a job run again keeps its first "
        "document. The node is the server that ran it, as named in the inventory of the platform.")


def test_clip_keeps_whole_sentences_and_words(ctx):
    from supagent.knowledge.context import clip

    assert clip("Short text.", 50) == "Short text."
    assert clip("One sentence here. Another one that goes on and on.", 30) == "One sentence here. …"
    assert clip("A sentence that ends right at the limit. And more.", 41) == "A sentence that ends right at the limit. …"
    cut = clip("averyveryverylongword " * 6, 30)
    assert cut.endswith(" …") and "averyveryverylongword" in cut and not cut.rstrip(" …").endswith("averyvery")
    assert clip("word " * 40, 31).endswith("word …")                         # never inside a word


def test_a_data_source_page_is_complete(shared):
    from superset.extensions import db

    from supagent.knowledge.context import collect, fact_pages
    from supagent.models import KObject

    jobs = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == "jobs").one()
    status = db.session.query(KObject).filter(KObject.kind == "field", KObject.parent == "jobs",
                                              KObject.name == "STATUS").one()
    jobs.description, jobs.description_source = LONG, "llm"
    status.description, status.description_source = "How the run ended.", "llm"
    db.session.commit()
    pages = {p["slug"]: p["content"] for p in fact_pages(collect())}
    page = pages["data-sources-jobs"]
    assert LONG in page                                                      # the whole description, not 200 letters
    assert "(1,000 documents; from 2026-09-01 to 2026-09-24, time field `ts`)" in page
    assert "Learned objects: 3 fields, 1 index." in page               # (not "indexs")
    assert "## The fields of index `jobs`" in page
    fields = page.split("## The fields of index `jobs`", 1)[1]
    assert fields.index("`STATUS` (keyword): How the run ended.") < fields.index("`NODE`")   # described first
    assert "Values: FAILED, SUCCESS." in fields
    metrics = pages["data-sources-metrics"]
    assert "## The labels of metric `node_cpu_seconds_total`" in metrics and "`mode`" in metrics


def test_a_long_description_is_cut_after_a_whole_sentence(shared):
    from superset.extensions import db

    from supagent.knowledge.context import DESC_CHARS, collect, fact_pages
    from supagent.models import KObject

    jobs = db.session.query(KObject).filter(KObject.kind == "index", KObject.name == "jobs").one()
    jobs.description = " ".join([LONG] * 6)
    db.session.commit()
    page = next(p["content"] for p in fact_pages(collect()) if p["slug"] == "data-sources-jobs")
    line = next(ln for ln in page.splitlines() if ln.startswith("- index `jobs`"))
    said = line.split(": ", 1)[1].split(" (1,000 documents")[0]
    assert len(said) <= DESC_CHARS + 2 and said.endswith(". …")


class Scripted:
    """An LLM that answers from a script of (text, finish_reason)."""

    def __init__(self, answers):
        self.answers, self.calls, self.last_usage, self.last_finish = list(answers), [], None, None

    def chat(self, messages, tools=None, max_tokens=None):
        self.calls.append((messages, max_tokens))
        text, self.last_finish = self.answers.pop(0)
        self.last_usage = {"prompt_tokens": 10, "completion_tokens": 5}
        return {"content": text}


SPEC = {"section": "functional", "slug": "s", "title": "Overview", "brief": "Explain.",
        "evidence": [{"ref": "doc:1", "title": "Runbook", "text": "The batch runs at night."}]}


def test_a_page_cut_by_the_length_limit_goes_on(ctx):
    from supagent.knowledge.context import CONTINUE, write_summary

    llm = Scripted([("## Overview\n\nThe batch runs at night and its first part ", "length"),
                    ("ends before dawn [E1].", "stop")])
    out = write_summary(SPEC, llm)
    assert out["content"] == "## Overview\n\nThe batch runs at night and its first part ends before dawn [E1]."
    assert not out["cut"] and out["tokens"] == 30
    second = llm.calls[1][0]
    assert second[-2] == {"role": "assistant", "content": "## Overview\n\nThe batch runs at night and its first part "}
    assert second[-1]["content"] == CONTINUE


def test_a_reasoning_cut_before_its_end_is_no_page(ctx):
    from supagent.knowledge.context import SUMMARY_TOKENS, write_summary

    llm = Scripted([("<think>Let me think about the batch, which", "length"), ("## Overview\n\nAt night [E1].", "stop")])
    out = write_summary(SPEC, llm)
    assert out["content"] == "## Overview\n\nAt night [E1]." and "<think>" not in out["content"]
    assert llm.calls[1][1] == 2 * SUMMARY_TOKENS                             # asked again with twice the room


def test_a_page_still_cut_says_where_it_stops(ctx):
    from supagent.knowledge.context import CONTINUATIONS, CUT_NOTE, write_summary

    llm = Scripted([("## Overview\n\nOne whole line.\nA line cut in the mid", "length")] * (CONTINUATIONS + 1))
    out = write_summary(SPEC, llm)
    assert out["cut"] and out["content"].endswith(CUT_NOTE) and len(llm.calls) == CONTINUATIONS + 1
    assert "\n\n" + CUT_NOTE in out["content"]


def test_one_page_failing_leaves_the_others_written(shared, monkeypatch):
    from supagent import llm as L
    from supagent.knowledge.context import build_context

    class Failing(FakeLLM):
        def chat(self, messages, tools=None, max_tokens=None):
            if "The page: Technical overview." in messages[0]["content"]:
                raise L.LLMError("HTTP 500 from the LLM server")
            return super().chat(messages, tools, max_tokens)

    monkeypatch.setattr(L, "LLM", Failing)
    out = build_context(reason="test")
    pages = _pages()
    assert out["status"] == "partial" and "Technical overview" in out["error"]
    assert ("functional", "overview") in pages and ("functional", "application-billing") in pages
    assert ("technical", "architecture") not in pages
    steps = {s["step"]: s for s in out["steps"]}
    assert steps["summary pages (LLM)"]["failed"] == 1 and "search index" in steps        # the build went on


@pytest.fixture()
def fresh(ctx):
    from superset import db

    from supagent import settings
    from supagent.models import ContextPage

    settings.set_value("context.review", True)
    db.session.query(ContextPage).filter(ContextPage.slug == "reject-test").delete()
    db.session.commit()
    yield {"section": "technical", "slug": "reject-test", "title": "Reject test", "sources": [], "database_ids": []}
    db.session.query(ContextPage).filter(ContextPage.slug == "reject-test").delete()
    db.session.commit()


V1, V2, V3 = "## Jobs\n- Runs at night.", "## Jobs\n- Runs at night and at noon.", "## Jobs\n- Runs every hour."


def test_a_new_page_can_be_rejected(fresh):
    from superset import db

    from supagent.knowledge.context import REJECTED, proposals, review, save_page
    from supagent.knowledge.index import _context_pieces
    from supagent.models import ContextPage

    assert save_page({**fresh, "content": V1}, "facts", "r1") == "written"
    p = db.session.query(ContextPage).filter_by(slug="reject-test").one()
    assert [x["what"] for x in proposals() if x["id"] == p.id] == ["new"]
    assert any(x["ref"].startswith(f"context:{p.id}#") for x in _context_pieces())
    review(p.id, "reject", "editor1")
    p = db.session.get(ContextPage, p.id)
    assert p.kind == REJECTED and not [x for x in proposals() if x["id"] == p.id]
    assert not any(x["ref"].startswith(f"context:{p.id}#") for x in _context_pieces())    # not searched
    assert save_page({**fresh, "content": V1}, "facts", "r1") == "rejected"    # the same page: not again
    assert save_page({**fresh, "content": V2}, "facts", "r2") == "proposed"    # its sources changed: to review
    listed = [x for x in proposals() if x["id"] == p.id][0]
    assert listed["what"] == "new" and listed["rejected_before"] and listed["content"] == V2
    review(p.id, "reject", "editor1")                                          # refused again
    assert save_page({**fresh, "content": V2}, "facts", "r2") == "rejected"
    assert save_page({**fresh, "content": V3}, "facts", "r3") == "proposed"
    review(p.id, "approve", "editor1")
    p = db.session.get(ContextPage, p.id)
    assert p.kind == "facts" and p.content == V3                               # shown again
    assert any(x["ref"].startswith(f"context:{p.id}#") for x in _context_pieces())


def test_a_change_kept_as_it_is_is_not_proposed_again(fresh):
    from superset import db

    from supagent.knowledge.context import review, save_page
    from supagent.models import ContextPage

    save_page({**fresh, "content": V1}, "summary", "k1")
    p = db.session.query(ContextPage).filter_by(slug="reject-test").one()
    review(p.id, "approve", "editor1")
    assert save_page({**fresh, "content": V2}, "summary", "k2") == "proposed"
    review(p.id, "reject", "editor1")                                          # kept as it is
    assert save_page({**fresh, "content": V2}, "summary", "k2") == "rejected"  # not every night again
    assert save_page({**fresh, "content": V3}, "summary", "k3") == "proposed"  # a new version: to review
    assert db.session.get(ContextPage, p.id).compared.get("rejected_hash") == "k2"


def test_a_rejected_page_whose_subject_is_gone_is_removed_quietly(fresh):
    from superset import db

    from supagent.knowledge.context import drop_pages, review, save_page
    from supagent.models import ContextPage

    save_page({**fresh, "content": V1}, "facts", "g1")
    p = db.session.query(ContextPage).filter_by(slug="reject-test").one()
    review(p.id, "reject", "editor1")
    others = {(x.section, x.slug) for x in db.session.query(ContextPage) if x.slug != "reject-test"}
    drop_pages(others)
    assert db.session.get(ContextPage, p.id) is None
