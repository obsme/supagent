"""(0.11.6) How the spaces of a big wiki connect, and How the system works from the spaces' own pages (the user's
request of 21 October 2026: "per space pages, and then another summary to see the links between [them], and update
How the system works according to that"). The links between the spaces' subjects are counted without the LLM (the
pages of a subject that name another); their page is written from them; the overviews read a big wiki through its
spaces' pages once they are written, in the place and the room of its digest."""
from __future__ import annotations


def _space(key, home, subjects, per, start):
    """A big space `key` of a wiki read since 0.11.5: its home, then for each subject (title, its pages' texts) its
    own page and `per` pages under it, each dated."""
    pages, n = [], 0
    out = {"pages": pages, "content": ""}

    def add(pid, title, text, ancestors, day):
        block = f"# {title}\n{text}\n"
        pages.append({"id": pid, "title": title, "space": key, "at": start + len(out["content"]),
                      "chars": len(block), "ancestors": ancestors, "links": [], "modified": day})
        out["content"] += block

    add(f"{key}-home", home, f"The pages of the {home}.", [], "2024-01-01")
    for title, texts in subjects:
        sid = f"{key}-{title}"
        add(sid, title, f"{title} is a part of the {home}.", [f"{key}-home"], "2024-02-01")
        for j in range(per):
            n += 1
            text, day = texts[j] if j < len(texts) else (f"Notes {j} about {title}.", "2024-03-01")
            add(f"{key}-p{n}", f"{title} page {j}", text, [f"{key}-home", sid], day)
    return out


def _wiki():
    """Two big spaces: PRD (Orders, Billing) and PLT (Gateway, Queue). Orders' pages name Gateway on 3 pages (the
    latest says since when) and Queue on 2 (the latest of them says it is archived); Gateway's name Queue on 3;
    Billing's name Orders once (fewer than LINKS_MIN_PAGES: no link)."""
    from supagent.knowledge.context import SPACE_MIN_PAGES

    per = SPACE_MIN_PAGES // 2
    prd = _space("PRD", "Product home", [
        ("Orders", [("Orders calls Gateway for every payment.", "2025-01-10"),
                    ("Orders retries through Gateway.", "2025-02-10"),
                    ("Since May 2026 Orders reaches Gateway over mTLS. Other notes.", "2026-05-01"),
                    ("Orders puts its events on Queue.", "2025-03-01"),
                    ("Archived: Orders once wrote to Queue directly.", "2026-06-01")]),
        ("Billing", [("Billing reads the totals of Orders.", "2025-04-01")])], per, 0)
    plt = _space("PLT", "Platform home", [
        ("Gateway", [("Gateway forwards to Queue.", "2025-01-01"), ("Gateway buffers in Queue.", "2025-01-02"),
                     ("Gateway drains Queue at night.", "2025-01-03")]),
        ("Queue", [])], per, len(prd["content"]))
    return {"id": 11, "title": "Company wiki", "content": prd["content"] + plt["content"],
            "pages": prd["pages"] + plt["pages"]}


def _ev(*docs):
    return {"databases": {}, "inventory": {}, "relations": [], "entries": [], "answers": [], "part_relations": [],
            "memory": [], "docs": list(docs)}


def test_the_subjects_of_two_spaces_are_linked_by_the_pages_that_name_them(app):
    """(0.11.6) A link from subject A to subject B: the pages of A's tree that name B (LINKS_MIN_PAGES at least), with
    the sentence of the latest that names B (one that says it is archived only when no other does); the links across
    spaces first, the most named first."""
    from supagent.knowledge.context import _big_spaces, subject_links

    links = subject_links(_big_spaces(_ev(_wiki())))
    got = [(x["a"], x["b"], x["pages"]) for x in links]
    assert got == [("Orders", "Gateway", 3), ("Orders", "Queue", 2), ("Gateway", "Queue", 3)]
    assert links[0]["a_space"] == "Product home" and links[0]["b_space"] == "Platform home"
    assert links[0]["example"] == "Since May 2026 Orders reaches Gateway over mTLS."    # the latest page's sentence
    assert links[1]["example"] == "Orders puts its events on Queue."                     # not the archived one
    assert links[2]["a_space"] == links[2]["b_space"] == "Platform home"                 # inside a space: after


def test_the_links_page_gives_the_subjects_the_links_and_a_row_for_each_of_the_first(app):
    """(0.11.6) The page of how the spaces connect: each space's subjects with their own page's first lines, the
    links with their sentences; the first links across spaces a row each (asked again once when one is left out, as a
    space page is for a subject); the links drawn, the diagram saying how to read them; none for a single space."""
    from supagent.knowledge.context import (LINKS_NOTE, LINKS_SLUG, _big_spaces, _faults, _links_spec, subject_links,
                                            write_summary)

    spaces = _big_spaces(_ev(_wiki()))
    spec = _links_spec(spaces, subject_links(spaces))
    assert spec["slug"] == LINKS_SLUG and spec["guard"]["pairs"] == [("Orders", "Gateway"), ("Orders", "Queue")]
    assert not any(c.isdigit() for c in spec["brief"]) and spec["diagram_note"] == LINKS_NOTE   # (no number: it was
    assert spec["guard"]["ask"] == "a row for each of the first 2 links given"                  # written on the page)
    assert [(d["a"], d["b"]) for d in spec["diagram"]] == [("Orders", "Gateway"), ("Orders", "Queue"),
                                                           ("Gateway", "Queue")]
    subjects = [e for e in spec["evidence"] if "subjects" in e]
    assert [e["title"] for e in subjects] == ["the subjects of the wiki space Platform home",     # (as big: by key)
                                              "the subjects of the wiki space Product home"]
    assert subjects[1]["subjects"][0] == "Orders: Orders is a part of the Product home."
    links = next(e for e in spec["evidence"] if "links" in e)["links"]
    assert links[0] == ('Orders (Product home) -> Gateway (Platform home): "Since May 2026 Orders reaches Gateway '
                        'over mTLS." (page "Orders page 2")')
    assert _links_spec(spaces[:1], subject_links(spaces[:1])) is None             # one space: no such page

    page = ("In short, the product's orders go through the platform [E3].\n\n## Main links\n\n| Subject | Names |\n"
            "|---|---|\n| Orders | Gateway [E3] |\n")
    assert _faults(page, spec["evidence"], spec)[0] == ["Orders -> Queue"]

    class LLM:
        last_usage, last_finish = {"prompt_tokens": 10, "completion_tokens": 5}, "stop"

        def __init__(self, pages):
            self.pages, self.asked = list(pages), []

        def chat(self, messages, max_tokens=0):
            self.asked.append(messages)
            return {"content": self.pages.pop(0)}

    fixed = page + "| Orders | Queue [E3] |\n"
    llm = LLM([page, fixed])
    out = write_summary(spec, llm)
    ask = llm.asked[1][-1]["content"]
    assert out["calls"] == 2 and "leaves out these links: Orders -> Queue" in ask
    assert "a row for each of the first 2 links given" in ask
    assert "| Orders | Queue [E3] |" in out["content"] and LINKS_NOTE in out["content"]
    assert "Orders -> Gateway : names" in out["content"]


def test_the_space_pages_come_first_then_the_links_then_the_overviews_which_read_them(app):
    """(0.11.6) With big spaces the summary pages are written in this order: the spaces' pages, their links' page,
    the two overviews (which read a big wiki through those pages), the applications; without one, as in 0.11.5 (the
    same specs: no page written again)."""
    from supagent.knowledge.context import LINKS_SLUG, summary_specs

    small = {"id": 12, "title": "Runbook", "content": "# Runbook\nRestart the ERP.\n", "pages": []}
    slugs = [s["slug"] for s in summary_specs(_ev(_wiki(), small))]
    assert slugs[:5] == ["space-plt", "space-prd", LINKS_SLUG, "overview", "architecture"]
    specs = {s["slug"]: s for s in summary_specs(_ev(_wiki(), small))}
    late = specs["overview"]["late"]
    assert late["docs"] == {"11": {"slugs": ["space-plt", "space-prd"], "chars": late["docs"]["11"]["chars"]}}
    assert late["links"] == LINKS_SLUG and specs["architecture"]["late"]["docs"] == late["docs"]
    plain = summary_specs(_ev(small))
    assert [s["slug"] for s in plain][:2] == ["overview", "architecture"] and not any("late" in s for s in plain)


def test_an_overview_reads_a_big_wiki_through_its_spaces_pages_once_they_are_written(ctx):
    """(0.11.6) Every space of the wiki has its page: the overview's item of the wiki (its place, its reference, its
    room) holds the links' page then the spaces' pages as they are now (without their diagram, code and citations,
    a person's version as it is), its brief told so; a space without its page, or a refused one: the digest as in
    0.11.5. The hash changes with what the pages say."""
    from superset.extensions import db

    from supagent.knowledge.context import LINKS_SLUG, WIKI_OVERVIEW, _hash, _late, summary_specs
    from supagent.models import ContextPage

    small = {"id": 12, "title": "Runbook", "content": "# Runbook\nRestart the ERP.\n", "pages": []}
    spec = {s["slug"]: s for s in summary_specs(_ev(_wiki(), small))}["overview"]
    before = [dict(x) for x in spec["evidence"]]
    assert _late(spec) is spec                                            # no page yet: as in 0.11.5
    rows = {"space-prd": ("Wiki space Product home", "In short, the product [E1].\n\n| Subject | Now |\n|---|---|\n"
                          "| Orders | through Gateway over mTLS [E1] |\n\n## Relations diagram\n\n```text\nx\n```"),
            "space-plt": ("Wiki space Platform home", "In short, the platform [E2].\n\n| Gateway | forwards to Queue |"),
            LINKS_SLUG: ("How the wiki spaces connect", "In short, the product relies on the platform [E1, E2].")}
    try:
        for slug, (title, text) in rows.items():
            db.session.add(ContextPage(section="functional", slug=slug, title=title, kind="summary", content=text,
                                       author="agent" if slug != "space-plt" else "alice"))
        db.session.commit()
        late = _late(spec)
        k = next(i for i, x in enumerate(before) if x["ref"] == "doc:11")
        item = late["evidence"][k]
        assert item["ref"] == "doc:11" and item["title"] == "Company wiki: its spaces, as their own pages say"
        text = item["text"]
        assert text.startswith("# How the wiki spaces connect\nIn short, the product relies on the platform.")
        assert "# Wiki space Product home" in text and "| Orders | through Gateway over mTLS |" in text
        assert "# Wiki space Platform home" in text and "Relations diagram" not in text and "[E" not in text
        assert len(text) <= spec["late"]["docs"]["11"]["chars"]
        assert [x for i, x in enumerate(late["evidence"]) if i != k] == [x for i, x in enumerate(before) if i != k]
        assert WIKI_OVERVIEW + "; ## Processes and chains" in late["brief"]       # a section in its list of sections
        assert late["brief"].replace(WIKI_OVERVIEW, "", 1) == spec["brief"]
        assert _hash([late["brief"], late["evidence"]]) != _hash([spec["brief"], spec["evidence"]])
        db.session.query(ContextPage).filter_by(slug="space-plt").update({"kind": "rejected"})
        db.session.commit()
        assert _late(spec) is spec                                        # a space's page refused: the digest
    finally:
        db.session.query(ContextPage).filter(ContextPage.slug.in_(list(rows))).delete(synchronize_session=False)
        db.session.commit()
