"""(0.11.7) A wiki of 30 spaces and more in one link (the user's request of 21 October 2026: "the learning should
manage the spaces of their own, summarise, and the context and link between applications and components and
services"): every space of a big wiki has its page, a space with no page tree is summarized by its parts, each part
with its own space and the other spaces documenting it, the links page from the relations between the parts of two
spaces; the reader keeps the relations of a page's tables and sentences to what they state."""
from __future__ import annotations


def _unit(text, title="Notes"):
    from supagent.knowledge import understand as U

    unit = {"ukey": "1", "kind": "page", "title": title, "url": "", "path": "", "text": text, "meta": {}}
    unit["found"] = U.discover(unit)
    return unit


def _facts(text, parts, title="Notes"):
    from supagent.knowledge import understand as U

    names = U.Names()
    own = {}
    for p in parts:
        names.add_part(p)
        own[U.norm(p)] = p
    owner = U._page_owner(title, names, own)            # (as the reading does: the part a page's title names)
    return [(f["subject"], f["verb"], f["obj"]) for f in U.facts_of(_unit(text, title), owner, names, own)]


PARTS = ["Orderly", "orderly-api", "orderly-worker", "tarn-cp", "conveyor-ci", "crm-core", "helpdesk-desk",
         "kafka-bus", "Customer"]


def test_a_row_naming_the_page_part_relates_to_it_and_is_no_member_of_it(ctx):
    """(0.11.7) On a part's own page, a table of its components makes each row one of its parts; a row naming that
    part in another cell relates to it ("conveyor-ci | tarn-cp | uses" on tarn-cp's runbook): no member of it."""
    got = _facts("## Who uses it\n\nComponent | Talks to | How\nconveyor-ci | tarn-cp | uses\n", PARTS,
                 title="tarn-cp runbook 50")
    assert ("conveyor-ci", "part_of", "tarn-cp") not in got
    got = _facts("Orderly is an application owned by the Kite team.\n## Components\n\nComponent | Role\n"
                 "orderly-api | takes the requests\norderly-worker | does the background work\n", PARTS, title="Orderly")
    assert ("orderly-api", "part_of", "Orderly") in got and ("orderly-worker", "part_of", "Orderly") in got


def test_a_purpose_phrase_names_no_end_of_a_relation(ctx):
    """(0.11.7) "X calls Y for the customer data": what for, no second end (a dashboard named "Customer" read as a
    target before); the ends a list names are all kept."""
    assert _facts("helpdesk-desk calls crm-core for the customer data.", PARTS) == [
        ("helpdesk-desk", "calls", "crm-core")]
    got = _facts("orderly-api calls crm-core and kafka-bus.", PARTS)
    assert ("orderly-api", "calls", "crm-core") in got and ("orderly-api", "calls", "kafka-bus") in got


def test_a_part_runs_on_a_platform_the_pages_declare(ctx):
    """(0.11.7) "X runs on tarn-cp", tarn-cp a part the pages declare (no host): X runs on it (was dropped); a cloud or
    Kubernetes said so is no place of its own."""
    assert ("orderly-worker", "runs_on", "tarn-cp") in _facts("orderly-worker runs on tarn-cp.", PARTS)
    assert not [f for f in _facts("orderly-worker runs on Kubernetes.", PARTS) if f[1] == "runs_on"]


def test_what_a_part_is_and_its_owner_said_in_one_sentence(ctx):
    """(0.11.7) "x is a service owned by the y team", "x is a component of y owned by the z team": what it is, what it
    is part of and its owner (the owner's words made the whole sentence unread); never from a sentence about the page
    itself."""
    got = _facts("kafka-bus is a service owned by the Lark team.", PARTS)
    assert ("kafka-bus", "is_a", "service") in got and ("kafka-bus", "owned_by", "Lark team") in got
    got = _facts("orderly-api is a component of Orderly owned by the Kite team.", PARTS)
    assert {("orderly-api", "part_of", "Orderly"), ("orderly-api", "is_a", "component"),
            ("orderly-api", "owned_by", "Kite team")} <= set(got)
    assert _facts("This page is a service owned by the Kite team.", PARTS) == []


def _space(key, doc_id, n, at=0, flat=False, home=True, titles=None):
    """A space of `n` pages (read since 0.11.4: their parents), each ~800 characters: a home and its pages, under
    subjects of 5 pages (a tree) or all under the home (flat); with no home, every page at the top."""
    pages, content = [], ""
    hid = f"{key}-home"
    if home:
        block = f"# {key} home\nThe pages of {key}.\n"
        pages.append({"id": hid, "title": f"{key} home", "space": key, "at": at, "chars": len(block), "ancestors": []})
        content += block
    for i in range(n):
        title = (titles or {}).get(i) or f"{key} page {i}"
        block = f"# {title}\n" + f"Notes {i} of {key}. " * 45 + "\n"
        sub = f"{key}-s{i // 5}"
        anc = [] if not home else [hid] if flat else [hid, sub]
        if not flat and home and i % 5 == 0:
            sblock = f"# {key} subject {i // 5}\nA subject.\n"
            pages.append({"id": sub, "title": f"{key} subject {i // 5}", "space": key, "at": at + len(content),
                          "chars": len(sblock), "ancestors": [hid]})
            content += sblock
        pages.append({"id": f"{key}-p{i}", "title": title, "space": key, "at": at + len(content), "chars": len(block),
                      "ancestors": anc, "modified": "2026-01-01"})
        content += block
    return content, pages


def _doc(doc_id, url, *spaces):
    content, pages = "", []
    for key, n, kw in spaces:
        c, p = _space(key, doc_id, n, at=len(content), **kw)
        content += c
        pages += p
    return {"id": doc_id, "title": f"wiki {doc_id}", "url": url, "content": content, "pages": pages}


def _ev(*docs, parts=None):
    return {"databases": {}, "inventory": {}, "relations": [], "entries": [], "answers": [], "part_relations": [],
            "memory": [], "docs": list(docs), "parts": parts or {}}


def test_every_space_of_a_big_wiki_has_its_page_and_a_space_two_links_reach_has_one(app):
    """(0.11.7) A wiki longer than what the overviews read whole: every space of 20 pages or more has its page (the
    defaults: 20 pages, 40 spaces), named by its home; a space two links of one wiki reach has one page (the document
    holding the most of its pages; was one page each, of one slug, written in turn at every build); a small wiki
    (read whole by the overviews) has none."""
    from supagent.knowledge.context import _big_spaces

    a = _doc(1, "https://wiki.example.com/display/OPS", ("OPS", 60, {}), ("DEV", 25, {}), ("TINY", 8, {}))
    b = _doc(2, "https://wiki.example.com/display/DEV", ("DEV", 30, {}), ("OPS", 21, {}))
    got = {(s["space"], s["doc"]["id"], s["name"]) for s in _big_spaces(_ev(a, b))}
    assert got == {("OPS", 1, "OPS home"), ("DEV", 2, "DEV home")}
    small = _doc(3, "https://small.example.com/display/X", ("X", 25, {}))
    small["content"] = small["content"][:20000]
    assert _big_spaces(_ev(small)) == []


def test_two_sites_spaces_of_one_key_are_two_spaces(app):
    """(0.11.7) Two wikis (two sites) each with a space "OPS": two spaces, each its own page and slug, the site with
    the most pages of it keeping the bare key (a small wiki added later renames no page of the big one); a space with
    no home (pages imported at its top) is named by its key."""
    from supagent.knowledge.context import _big_spaces, _space_specs

    a = _doc(1, "https://wiki.example.com/display/OPS", ("OPS", 45, {}))
    b = _doc(2, "https://other.example.org/display/OPS", ("OPS", 40, {"home": False}))
    spaces = _big_spaces(_ev(a, b))
    assert sorted(s["space"] for s in spaces) == ["OPS", "OPS@other.example.org"]
    specs = {s["slug"]: s for s in _space_specs(_ev(a, b), spaces)}
    assert set(specs) == {"space-ops", "space-ops-other-example-org"}
    assert specs["space-ops-other-example-org"]["title"] == "Wiki space OPS"
    assert specs["space-ops"]["title"] == "Wiki space OPS home"


def _parts_ix(doc_id, key, groups):
    """A parts index (parts_index.index's shape) for the pages of one space: {part: [page numbers]}."""
    from collections import Counter

    parts, page_parts = {}, {}
    for name, nums in groups.items():
        k = name.lower()
        parts[k] = {"name": name, "kind": "service", "of": None, "home": key, "spaces": Counter({key: len(nums)}),
                    "pages": {(doc_id, f"{key}-p{i}") for i in nums}}
        for i in nums:
            page_parts[(doc_id, f"{key}-p{i}")] = [k]
    return {"parts": parts, "page_parts": page_parts, "relations": [], "space_names": {key: f"{key} home"},
            "page_space": {pg: key for p in parts.values() for pg in p["pages"]}}


def test_a_space_with_no_page_tree_is_summarized_by_its_parts(app):
    """(0.11.7) A flat space (every page under its home: no subject from its tree; was one list, no subject asked):
    its subjects are its parts (the pages about each: titled with it, or stating most of it), each with its pages in
    turns, its other pages last; its page asked a row for each; the parts given with their own space."""
    from supagent.knowledge.context import _big_spaces, _space_specs

    titles = {i: f"lantern-metrics runbook {i}" for i in range(0, 12)}
    titles.update({i: f"How to check pg-main ({i})" for i in range(12, 18)})
    d = _doc(1, "https://wiki.example.com/display/OBS", ("OBS", 45, {"flat": True, "titles": titles}))
    ev = _ev(d, parts=_parts_ix(1, "OBS", {"lantern-metrics": range(0, 12), "pg-main": range(12, 18)}))
    spec = _space_specs(ev, _big_spaces(ev))[0]
    assert spec["guard"]["subjects"] == ["lantern-metrics", "pg-main"]
    text = spec["evidence"][0]["text"]
    assert text.index("lantern-metrics:\n") < text.index("pg-main:\n") < text.index("Other pages:\n")
    assert "Its applications, components and services" in text
    parts = spec["evidence"][1]
    assert parts["parts"][0].startswith("lantern-metrics (a service): its own pages are in this space")


def test_the_links_page_is_written_from_the_relations_between_the_parts_of_two_spaces(app):
    """(0.11.7) The links page: the relations the pages state between parts whose own spaces differ (a relation of
    each pair of spaces in turn: a pair stated on many pages leaves room to the others), each with the sentence of
    the latest page saying it; a row asked for each of the first 20 across spaces; drawn with their verbs."""
    from collections import Counter

    from supagent.knowledge.context import LINKS_PARTS_BRIEF, _links_spec, part_links

    def part(name, home):
        return {"name": name, "kind": None, "of": None, "home": home, "spaces": Counter({home: 3}), "pages": set()}

    parts = {"a1": part("a1", "A"), "a2": part("a2", "A"), "b1": part("b1", "B"), "c1": part("c1", "C")}
    rel = lambda a, v, b, n: {"a": a, "verb": v, "b": b, "a_key": a, "b_key": b,  # noqa: E731
                              "pages": [(1, str(i)) for i in range(n)], "quote": f"{a} {v} {b}.", "where": "p"}
    ev = _ev(parts={"parts": parts, "relations": [rel("a1", "calls", "b1", 9), rel("a2", "calls", "b1", 8),
                                                  rel("a1", "sends_to", "c1", 1), rel("a1", "uses", "a2", 5)],
                    "space_names": {"A": "Space A", "B": "Space B", "C": "Space C"}, "page_space": {}})
    links = part_links(ev)
    assert [(x["a"], x["b"]) for x in links] == [("a1", "b1"), ("a1", "c1"), ("a2", "b1"), ("a1", "a2")]
    spaces = [{"space": k, "name": f"Space {k}", "doc": {"id": 1}, "pages": []} for k in "ABC"]
    spec = _links_spec(spaces, [], links)
    assert spec["brief"] == LINKS_PARTS_BRIEF
    assert spec["guard"]["pairs"] == [("a1", "b1"), ("a1", "c1"), ("a2", "b1")]
    assert {"a": "a1", "b": "c1", "verb": "sends_to"} in spec["diagram"]
    lines = spec["evidence"][1]["links"]
    assert lines[0] == 'a1 (Space A) calls b1 (Space B): "a1 calls b1." (page "p")'


def test_the_overviews_are_given_the_wiki_parts_with_their_spaces(app):
    """(0.11.7) The overviews' evidence: each whole with its parts, then the others, with what each is, its own space
    and the other spaces with pages about it."""
    from collections import Counter

    from supagent.knowledge.context import _parts_item

    parts = {"orderly": {"name": "Orderly", "kind": "application", "of": None, "home": "PRD",
                         "spaces": Counter({"PRD": 9, "SRE": 4}), "pages": set(range(13))},
             "orderly-api": {"name": "orderly-api", "kind": "component", "of": "Orderly", "home": "PRD",
                             "spaces": Counter({"PRD": 5}), "pages": set(range(5))},
             "kafka-bus": {"name": "kafka-bus", "kind": "service", "of": None, "home": "PLT",
                           "spaces": Counter({"PLT": 6, "DATA": 1}), "pages": set(range(7))}}
    item = _parts_item({"parts": {"parts": parts, "space_names": {"PRD": "Product", "SRE": "Reliability",
                                                                  "PLT": "Platform"}}})
    assert item[0]["parts"] == [
        "Orderly (an application): made of orderly-api; its own space Product; pages about it in Reliability too",
        "kafka-bus (a service); its own space Platform"]


def test_the_parts_index_reads_the_pages_facts_and_titles(ctx):
    """(0.11.7) The parts index from the understanding's facts and the pages' titles: a part's own space is the one of
    its own page (titled with its name), the other spaces are those with 2 pages or more about it; a kind a sentence
    says is kept, a column's head alone is not; what it is part of."""
    from superset.extensions import db

    from supagent.knowledge import parts_index as P
    from supagent.models import Doc, KFact, KUnit

    pages = [{"id": "1", "title": "kafka-bus", "space": "PLT", "ancestors": []},
             {"id": "2", "title": "kafka-bus runbook", "space": "SRE", "ancestors": []},
             {"id": "3", "title": "How to restart kafka-bus", "space": "SRE", "ancestors": []},
             {"id": "4", "title": "kafka-bus notes", "space": "DATA", "ancestors": []},
             {"id": "5", "title": "orderly-api", "space": "PRD", "ancestors": []}]
    d = Doc(kind="url", url="https://wiki.example.com/display/PLT", title="wiki", content="x", pages=pages,
            enabled=True, status="ok")
    db.session.add(d)
    db.session.flush()
    us = {p["id"]: KUnit(doc_id=d.id, ukey=p["id"], kind="page", title=p["title"]) for p in pages}
    db.session.add_all(us.values())
    db.session.flush()
    db.session.add_all([
        KFact(unit_id=us["1"].id, subject="kafka-bus", verb="is_a", obj="service", obj_kind="kind", confidence=0.7),
        KFact(unit_id=us["5"].id, subject="orderly-api", verb="is_a", obj="component", obj_kind="kind",
              confidence=0.65),
        KFact(unit_id=us["5"].id, subject="orderly-api", verb="part_of", obj="Orderly", obj_kind="part",
              confidence=0.7),
        KFact(unit_id=us["5"].id, subject="orderly-api", verb="sends_to", obj="kafka-bus", obj_kind="part",
              confidence=0.6, quote="orderly-api sends its events to kafka-bus.")])
    db.session.commit()
    try:
        ix = P.index([{"id": d.id, "url": d.url, "pages": pages}])
        kb, oa = ix["parts"]["kafka-bus"], ix["parts"]["orderly-api"]
        assert kb["home"] == "PLT" and P.others(kb) == ["SRE"] and kb["kind"] == "service"
        assert oa["kind"] is None and oa["of"] == "Orderly" and P.kind_phrase(oa) == "a part of Orderly"
        assert [(r["a"], r["verb"], r["b"]) for r in ix["relations"]] == [("orderly-api", "sends_to", "kafka-bus")]
    finally:
        db.session.query(Doc).filter(Doc.id == d.id).delete()
        db.session.commit()


def test_a_part_latest_dated_change_holds_in_every_space(ctx):
    """(0.11.7) A part's latest dated change: the newest page about it whose first lines say since when something of
    it holds and name it (a link's title in a list is no sentence of it): given to every space page and the overviews,
    so that another space's older pages do not say the old value as current."""
    from superset.extensions import db

    from supagent.knowledge import parts_index as P
    from supagent.models import Doc, KFact, KUnit

    texts = [("1", "orderly-worker", "PRD", "2025-01-02", "orderly-worker is a component of Orderly."),
             ("2", "orderly-worker decision", "PRD", "2026-03-12",
              "The team decided. Since 12 March 2026, orderly-worker runs on ord-app-31; before, ord-app-11."),
             ("3", "orderly-worker runbook", "SRE", "2025-06-01", "orderly-worker runs on ord-app-11."),
             ("4", "orderly-worker notes", "SRE", "2026-07-01",
              "Notes.\n## Related pages\n- orderly-worker decision from 2026-03-12")]
    content, pages = "", []
    for pid, title, space, day, body in texts:
        block = f"# {title}\n{body}\n"
        pages.append({"id": pid, "title": title, "space": space, "ancestors": [], "modified": day,
                      "at": len(content), "chars": len(block)})
        content += block
    pages.append({"id": "5", "title": "orderly-worker decision from 2026-03-12", "space": "PRD", "ancestors": []})
    d = Doc(kind="url", url="https://wiki.example.com/display/PRD", title="wiki", content=content, pages=pages,
            enabled=True, status="ok")
    db.session.add(d)
    db.session.flush()
    us = {p["id"]: KUnit(doc_id=d.id, ukey=p["id"], kind="page", title=p["title"]) for p in pages}
    db.session.add_all(us.values())
    db.session.flush()
    db.session.add(KFact(unit_id=us["1"].id, subject="orderly-worker", verb="part_of", obj="Orderly", obj_kind="part",
                         confidence=0.75))
    db.session.commit()
    try:
        ix = P.index([{"id": d.id, "url": d.url, "pages": pages, "content": content}])
        part = ix["parts"]["orderly-worker"]
        assert part["change"] == {"day": "2026-03-12", "space": "PRD", "sentence": (
            "Since 12 March 2026, orderly-worker runs on ord-app-31; before, ord-app-11.")}
        assert P.change_phrase(part, {"PRD": "Product"}).startswith("its latest dated change (2026-03-12, in Product)")
    finally:
        db.session.query(Doc).filter(Doc.id == d.id).delete()
        db.session.commit()


def test_a_value_a_part_latest_change_replaced_no_longer_holds():
    """(0.11.7) A part's latest dated change names what it replaced after "before", "was", "replacing"...: that host or
    owner is no longer stated as holding (the overviews' relations and their diagram); the new one stays."""
    from supagent.knowledge.parts_index import superseded

    part = {"change": {"day": "2026-03-12", "space": "PRD", "sentence":
                       "Since 12 March 2026, orderly-worker runs on ord-app-31; before, orderly-worker runs on ord-app-11."}}
    assert superseded(part, "ord-app-11") and not superseded(part, "ord-app-31")
    part = {"change": {"day": "2026-04-20", "space": "BKG", "sentence":
                       "From 20 April 2026 the booking service is installed on bkg-14 (it was bkg-04)."}}
    assert superseded(part, "bkg-04") and not superseded(part, "bkg-14")
    assert not superseded({"change": None}, "x") and not superseded(None, "x")


def test_a_page_two_links_of_one_wiki_read_counts_once(ctx):
    """(0.11.7) Two documents of one site reading the same page (two links of one wiki): the page counts once in a
    part's pages and spaces (it was counted twice: a space with one page about a part documented it)."""
    from superset.extensions import db

    from supagent.knowledge import parts_index as P
    from supagent.models import Doc, KFact, KUnit

    pages = [{"id": "1", "title": "kafka-bus", "space": "PLT", "ancestors": []},
             {"id": "2", "title": "kafka-bus runbook", "space": "SRE", "ancestors": []}]
    docs = []
    for n in (1, 2):
        d = Doc(kind="url", url=f"https://wiki.example.com/display/X{n}", title=f"wiki {n}", content="x",
                pages=pages, enabled=True, status="ok")
        db.session.add(d)
        db.session.flush()
        for p in pages:
            u = KUnit(doc_id=d.id, ukey=p["id"], kind="page", title=p["title"])
            db.session.add(u)
            db.session.flush()
            db.session.add(KFact(unit_id=u.id, subject="kafka-bus", verb="is_a", obj="service", obj_kind="kind",
                                 confidence=0.7))
        docs.append(d)
    db.session.commit()
    try:
        ix = P.index([{"id": d.id, "url": d.url, "pages": pages} for d in docs])
        kb = ix["parts"]["kafka-bus"]
        assert kb["spaces"] == {"PLT": 1, "SRE": 1} and P.others(kb) == []
    finally:
        db.session.query(Doc).filter(Doc.id.in_([d.id for d in docs])).delete(synchronize_session=False)
        db.session.commit()


def test_a_links_page_row_joining_two_unrelated_parts_is_asked_again_then_left_out(app):
    """(0.11.7) The links page from the relations between parts: a table row naming two of its parts that no relation
    given joins (a relation made up: "beacon-mailer sends data to pg-main") gets the page asked again once; still there,
    the row is left out. A row naming three parts or more (a pair of spaces and its parts) is never counted."""
    from collections import Counter

    from supagent.knowledge.context import _links_spec, part_links, unjoined, write_summary

    def part(name, home):
        return {"name": name, "kind": None, "of": None, "home": home, "spaces": Counter({home: 3}), "pages": set()}

    parts = {"a1": part("a1", "A"), "b1": part("b1", "B"), "c1": part("c1", "C")}
    rel = lambda a, v, b: {"a": a, "verb": v, "b": b, "a_key": a, "b_key": b,  # noqa: E731
                           "pages": [(1, "p")], "quote": f"{a} {v} {b}.", "where": "p"}
    ev = _ev(parts={"parts": parts, "relations": [rel("a1", "calls", "b1"), rel("b1", "sends_to", "c1")],
                    "space_names": {"A": "Space A", "B": "Space B", "C": "Space C"}, "page_space": {}})
    spaces = [{"space": k, "name": f"Space {k}", "doc": {"id": 1}, "pages": []} for k in "ABC"]
    spec = _links_spec(spaces, [], part_links(ev))
    good = "In short, A calls B.\n\n| Part | Does | Other |\n|---|---|---|\n| a1 | calls | b1 |\n| b1 | sends | c1 |\n"
    bad = good + "| a1 | sends data to | c1 |\n| Space A, Space C | a1, b1, c1 | several |\n"
    assert unjoined(bad, spec) == ["| a1 | sends data to | c1 |"]

    class LLM:
        last_usage, last_finish = {"prompt_tokens": 10, "completion_tokens": 5}, "stop"

        def __init__(self, pages):
            self.pages, self.asked = list(pages), []

        def chat(self, messages, max_tokens=0):
            self.asked.append(messages)
            return {"content": self.pages.pop(0)}

    llm = LLM([bad, bad])
    out = write_summary(spec, llm)
    assert out["calls"] == 2 and "joins in one row two parts that no relation given joins" in llm.asked[1][-1]["content"]
    assert "| a1 | sends data to | c1 |" not in out["content"] and "| a1 | calls | b1 |" in out["content"]
    assert "| Space A, Space C | a1, b1, c1 | several |" in out["content"]


def test_the_overview_is_asked_a_row_for_each_application_of_the_wiki(app):
    """(0.11.7) The overview's Applications table: a row for each application the wiki pages describe (the parts
    index, the most written first, 20 at most), asked again once when one is left out; its other checks as before
    (no name nor guess check on the overview)."""
    from collections import Counter

    from supagent.knowledge.context import _faults, summary_specs

    parts = {"orderly": {"name": "Orderly", "kind": "application", "of": None, "home": "PRD",
                         "spaces": Counter({"PRD": 5}), "pages": set(range(5))},
             "kafka-bus": {"name": "kafka-bus", "kind": "service", "of": None, "home": "PLT",
                           "spaces": Counter({"PLT": 3}), "pages": set(range(3))}}
    ev = _ev(parts={"parts": parts, "relations": [], "space_names": {"PRD": "Product", "PLT": "Platform"},
                    "page_space": {}})
    spec = {s["slug"]: s for s in summary_specs(ev)}["overview"]
    assert spec["guard"]["subjects"] == ["Orderly"] and spec["guard"]["only_subjects"]
    assert _faults("In short, it runs `made-up-host-01`.", [], spec) == (["Orderly"], [], [], [])
    assert "guard" not in {s["slug"]: s for s in summary_specs(_ev())}["overview"]


def test_a_space_digest_line_ends_on_a_word_never_on_a_bare_number(app):
    """(0.11.7) A space page's digest line: its page's first characters cut at a word's end, never on a bare number
    ("... after 5" was written "after 5 minutes"), "..." when cut; a short one as it is."""
    from supagent.knowledge.context import _cut

    text = "Owner: the Purchasing team. Escalate to the Purchasing team after 5 minutes without progress."
    assert _cut(text, 70) == "Owner: the Purchasing team. Escalate to the Purchasing team after ..."
    assert _cut(text, 62) == "Owner: the Purchasing team. Escalate to the Purchasing team ..."   # inside "after"
    assert _cut("Short one.", 70) == "Short one."


def test_the_overview_names_the_wiki_applications_its_table_leaves_out(app):
    """(0.11.7) The overview's applications check reads its Applications section (an application named elsewhere on the
    page is no row of the table); one still left out after the second turn is named at the section's end."""
    from collections import Counter

    from supagent.knowledge.context import APPS_MORE, _faults, summary_specs, write_summary

    parts = {k: {"name": n, "kind": "application", "of": None, "home": "PRD", "spaces": Counter({"PRD": 3}),
                 "pages": set(range(i))} for i, (k, n) in enumerate([("orderly", "Orderly"), ("beacon", "Beacon")], 3)}
    ev = _ev(parts={"parts": parts, "relations": [], "space_names": {"PRD": "Product"}, "page_space": {}})
    spec = {s["slug"]: s for s in summary_specs(ev)}["overview"]
    page = ("In short, two applications.\n\n## Applications\n\n| Application | What it does |\n|---|---|\n"
            "| Beacon | sends the mails |\n\n## Processes and chains\n\nOrderly calls Beacon.\n")
    assert _faults(page, [], spec)[0] == ["Orderly"]

    class LLM:
        last_usage, last_finish = {"prompt_tokens": 10, "completion_tokens": 5}, "stop"

        def __init__(self, pages):
            self.pages, self.asked = list(pages), []

        def chat(self, messages, max_tokens=0):
            self.asked.append(messages)
            return {"content": self.pages.pop(0)}

    out = write_summary(spec, LLM([page, page]))
    text = out["content"]
    assert APPS_MORE + "Orderly." in text and text.index(APPS_MORE) < text.index("## Processes and chains")
