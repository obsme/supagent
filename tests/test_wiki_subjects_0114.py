"""(0.11.4) A wiki of thousands of pages on many subjects, summarized well (the user's request of 20 October 2026: the
summary of 6,000 wiki pages on many different subjects, every subject understood, and where pages disagree, the date
each was written compared and the most recent one followed). The readers keep the date a page's source says it was
last changed (Confluence: version.when; a web page: a dated meta, else its Last-Modified when older than the answer)
and a Confluence page's parents; a summary reads every branch of a wiki's tree (each subject its room, its own page
first, then its most linked and its latest pages), each page with its date; the writer follows the most recent
source and says what changed."""
from __future__ import annotations

from email.utils import formatdate

from test_docs_readers import HTML, SECRET, _doc, _html, env, servers  # noqa: F401  (the fixtures)


# --------------------------------------------------------------------------------------------- #
# the readers: a page's date, a Confluence page's parents
# --------------------------------------------------------------------------------------------- #
def test_a_day_is_what_the_source_says_or_none(app):
    from supagent.knowledge.docs import day_of

    assert day_of("2025-03-14T10:22:31.000+01:00") == "2025-03-14"          # Confluence's version.when
    assert day_of("2024-11-02") == "2024-11-02"
    assert day_of("Wed, 05 Feb 2025 10:00:00 GMT") == "2025-02-05"            # an HTTP date (Last-Modified)
    for wrong in (None, "", "yesterday", "2025-13-40", "1970-01-01T00:00:00Z", "2999-01-01", "20250314", "3.14"):
        assert day_of(wrong) is None, wrong                                    # not a date, or not a plausible one


def _space(when: dict, parents: dict):
    """A Confluence space OPS (Data Center, /confluence): 100 its home, 101 under it, 102 under 101; each page with the
    version.when of `when` (none: no date said) and the ancestors of `parents`."""
    titles = {"100": "Operations", "101": "Billing", "102": "Billing runbook"}

    def page(pid: str) -> dict:
        version = {"number": 4, **({"when": when[pid]} if when.get(pid) else {})}
        return {"id": pid, "type": "page", "title": titles[pid], "status": "current", "version": version,
                "space": {"key": "OPS"}, "ancestors": [{"id": a, "type": "page", "title": titles[a]} for a in parents[pid]],
                "body": {"storage": {"value": f"<p>The page {titles[pid]}.</p>", "representation": "storage"}},
                "_links": {"webui": f"/display/OPS/{titles[pid].replace(' ', '+')}"}}

    def route(path, q, h):
        if path == "/confluence/rest/api/content" and q.get("spaceKey") == "OPS":
            return 200, {}, {"results": [page(k) for k in titles], "start": 0, "limit": 25, "size": 3, "_links": {}}
        return 404, {}, {"statusCode": 404}

    return route


def test_a_confluence_page_keeps_when_it_was_changed_and_its_parents(env, servers, app):
    from test_dictionary_080 import _client

    from supagent.knowledge import docs as D

    s = servers(_space({"100": "2023-10-02T09:00:00.000Z", "101": "2026-03-12T17:45:00.000+01:00"},
                       {"100": [], "101": ["100"], "102": ["100", "101"]}))
    d = _doc(f"{s.base}/confluence/display/OPS", auth={"type": "bearer"}, secret=SECRET)
    assert D.refresh(d)["status"] == "ok"
    pages = {p["title"]: p for p in d.pages}
    assert pages["Operations"]["modified"] == "2023-10-02" and pages["Billing"]["modified"] == "2026-03-12"
    assert "modified" not in pages["Billing runbook"]                       # no date said: none kept, never guessed
    assert [pages[t]["ancestors"] for t in ("Operations", "Billing", "Billing runbook")] == [[], ["100"], ["100", "101"]]
    assert all("ancestors" in r["query"]["expand"].split(",") for r in s.got)           # asked with the pages
    with _client(app, "admin") as c:                                     # the document's pages list says the day
        got = c.get(f"/supagent/admin/api/docs/{d.id}/pages").get_json()["pages"]
    assert {p["title"]: p["modified"] for p in got} == {"Operations": "2023-10-02", "Billing": "2026-03-12",
                                                         "Billing runbook": None}


def test_a_web_page_says_its_date_by_its_meta_or_an_old_last_modified(env, servers):
    from supagent.knowledge import docs as D

    links = "".join(f"<a href='/docs/{x}'>{x}</a> " for x in ("old", "now", "ld", "none"))

    def site(path, q, h):
        if path == "/docs/":
            return 200, HTML, _html("Docs", '<meta property="article:modified_time" content="2024-11-02T08:00:00Z">'
                                            f"<p>Start.</p>{links}")
        if path == "/docs/old":           # a file served as it is: changed long before it was asked for
            return 200, {**HTML, "Last-Modified": "Wed, 05 Feb 2025 10:00:00 GMT"}, _html("Old", "<p>Old text.</p>")
        if path == "/docs/now":           # a page made for each request: its Last-Modified is now, not a change
            return 200, {**HTML, "Last-Modified": formatdate(usegmt=True)}, _html("Now", "<p>Made now.</p>")
        if path == "/docs/ld":            # its structured data says when it was changed
            return 200, HTML, _html("Ld", '<script type="application/ld+json">{"@type": "Article", '
                                          '"dateModified": "2026-01-20T12:00:00+00:00"}</script><p>Dated.</p>')
        if path == "/docs/none":
            return 200, HTML, _html("None", "<p>No date said.</p>")
        return 404, {}, "no"

    d = _doc(servers(site).base + "/docs/")
    assert D.refresh(d)["status"] == "ok"
    said = {p["title"]: p.get("modified") for p in d.pages}
    assert said == {"Docs": "2024-11-02", "Old": "2025-02-05", "Now": None, "Ld": "2026-01-20", "None": None}
    assert D.html_to_text(_html("T", "<p>x</p>")) == ("T", "x", [])          # its callers: three things, as before


# --------------------------------------------------------------------------------------------- #
# the summaries: every subject of a big wiki, each page dated, the latest change, what is archived last
# --------------------------------------------------------------------------------------------- #
def _tree(subjects: dict, *, space: str = "OPS", home: bool = True) -> dict:
    """A wiki as the Confluence reader stores it: a home page (id "1"), under it a page per subject, under each its
    pages: subjects = {name: [(title, text, day, links), ...]} (the subject's own page first; a link "@i": to the
    subject's i-th page)."""
    texts, pages, at, n = [], [], 0, 100

    def add(pid, title, text, day, parents, links):
        nonlocal at
        block = f"# {title}\n{text}"
        at += 2 if texts else 0
        pages.append({"id": pid, "title": title, "space": space, "at": at, "chars": len(block), "links": links,
                      "ancestors": parents, **({"modified": day} if day else {})})
        texts.append(block)
        at += len(block)

    if home:
        add("1", "Home", "The space's home: its subjects below.", "2024-01-01", [], [])
    for name, rows in subjects.items():
        root = str(n)
        for i, (title, text, day, links) in enumerate(rows):
            add(str(n), title, text, day, (["1"] if home else []) + ([root] if i else []),
                [str(int(root) + int(x[1:])) if str(x).startswith("@") else x for x in links])
            n += 1
        n += 1000 - n % 1000
    return {"id": 1, "title": "Company wiki", "content": "\n\n".join(texts), "pages": pages}


def _subject(name: str, n: int, linked: bool, *, day: str = "2024-02-01") -> list:
    rows = [(name, f"{name} is a subject of the company. " + "More about it. " * 8, day, [])]
    for i in range(1, n):
        rows.append((f"{name} note {i}", f"Routine notes {i} of {name}. " * 6, f"2025-{1 + i % 12:02d}-10",
                     ["@0", f"@{i - 1}"] if linked else []))     # a busy subject's pages link to its first one, and
    return rows                                                   # to the one before them


def _groups(digest: str) -> dict:
    out, name = {}, None
    for ln in digest.splitlines()[1:]:
        if ln.startswith("- "):
            out[name].append(ln)
        else:
            name = ln.rstrip(":")
            out[name] = []
    return out


def test_every_subject_of_a_big_wiki_has_its_room_not_only_the_most_linked(app):
    from supagent.knowledge import context as C

    subjects = {"Orders": _subject("Orders", 3000, True)}               # a busy subject everything links to
    subjects.update({f"Quiet {k}": _subject(f"Quiet {k}", 40, False) for k in "ABCDEFGH"})   # nobody links to these
    wiki = _tree(subjects)
    out = C._digest(wiki, 12000, by_branch=True)                        # (0.11.5: a space's own page)
    assert len(out) <= 12000 and out.startswith("Spaces: OPS. Its subjects (the branches of its tree)")
    groups = _groups(out)
    assert list(groups)[:3] == ["Top pages", "Orders", "Quiet A"] and all(f"Quiet {k}" in groups for k in "ABCDEFGH")
    assert groups["Top pages"] == ["- Home [last changed 2024-01-01]: The space's home: its subjects below."]
    sizes = [len(v) for k, v in groups.items() if k != "Top pages"]
    assert max(sizes) - min(sizes) <= 1                                  # in turns: as many lines each
    assert all(v[0].startswith(f"- {k} [last changed 2024-02-01]: {k} is a subject") for k, v in groups.items()
               if k != "Top pages")
    old = dict(wiki, pages=[{k: v for k, v in p.items() if k != "ancestors"} for p in wiki["pages"]])
    before = C._digest(old, 12000)                                       # a wiki read before 0.11.4: as before
    assert before.startswith("Spaces: OPS. Its central pages first") and "Quiet" not in before
    assert before.splitlines()[0].endswith("each with its first lines:")   # (0.11.5: the overviews as in 0.11.4)


def test_a_subject_shows_its_latest_change_with_its_date_and_what_is_archived_last(app):
    from supagent.knowledge import context as C

    rows = [("Billing", "Billing is the invoicing application. Its database is on bil-db-01.", "2023-11-02", []),
            ("Billing (archived) setup", "Archived: this page is no longer maintained.", "2023-12-01", [])]
    rows += [(f"Billing how-to {i}", f"How to do task {i} in Billing. " * 5, "2024-01-15", ["@0", "@1"])
             for i in range(30)]                                         # the archived page: linked by every how-to
    rows += [(f"2026-0{m}-0{d} Billing weekly sync", "Notes of the week. " * 5, f"2026-0{m}-0{d}", [])
             for m in range(4, 10) for d in range(1, 5)]                 # newer than the change: meeting notes
    rows.insert(5, ("Billing database move", "Since 12 March 2026 the Billing database runs on bil-db-07; bil-db-01 "
                    "was switched off.", "2026-03-12", []))
    wiki = _tree({"Billing": rows, **{f"Other {k}": _subject(f"Other {k}", 20, False) for k in "ABC"}})
    groups = _groups(C._digest(wiki, 6000, by_branch=True))            # (0.11.5: a space's own page)
    billing = groups["Billing"]
    assert billing[0].startswith("- Billing [last changed 2023-11-02]: ") and "bil-db-01" in billing[0]
    assert any(ln.startswith("- Billing database move [last changed 2026-03-12]: Since 12 March 2026")
               for ln in billing[:3])
    assert not any("archived" in ln for ln in billing[:-1])              # what says it describes the past: last
    assert C.CHANGE_LEAD.search("As of 2026-03 the jobs run hourly.") and C.CHANGE_LEAD.search("from now on")
    assert not C.CHANGE_LEAD.search("Fixed: the export no longer retries forever.")   # a release note: not a change
    for said in ("Forward the traffic from 8443 to 8080.", "Starting 2048 workers per node.",
                 "From decision 12 of the board."):                       # a port, a number, a word: not a date
        assert not C.CHANGE_LEAD.search(said), said
    assert C.STALE_TITLE.search("Billing setup (archived)") and not C.STALE_TITLE.search("Log archive policy")


def test_the_subjects_of_a_space_under_one_page_and_of_a_repository(app):
    from supagent.knowledge import context as C

    under_docs = [{"id": "d", "title": "Docs", "space": "S", "ancestors": ["1"]}]
    for s in ("a", "b"):
        under_docs += [{"id": f"{s}{i}", "title": f"{s} {i}", "space": "S", "ancestors": ["1", "d"] + ([f"{s}0"] if i
                                                                                                        else [])}
                       for i in range(4)]
    names = [(key, sorted(p["id"] for p in pages)) for key, pages in C._branches(under_docs)]
    assert names == [((), ["d"]), (("S", "1", "d", "a0"), ["a0", "a1", "a2", "a3"]),   # down the one page everything
                     (("S", "1", "d", "b0"), ["b0", "b1", "b2", "b3"])]                  # is under
    repo = [{"path": p} for p in ("README.md", "roles/web/tasks/main.yml", "roles/web/vars/main.yml",
                                  "roles/db/tasks/main.yml", "docs/a.md", "docs/b.md", "docs/c.md", "x/y.md")]
    got = [(key, len(pages)) for key, pages in C._branches(repo)]
    assert got == [((), 1), (("", "roles"), 3), (("", "docs"), 3), (None, 1)]   # its folders; README first, x/ last
    digest = C._digest({"content": "x" * 99, "pages": []}, 10)          # (a small document: its beginning)
    assert digest == "x" * 10


def test_the_writer_follows_the_most_recent_source(app):
    """(0.11.5) Told only to a page whose evidence says its pages' days; any other page's prompt is 0.11.4's own (its
    hash unchanged: not written again for this)."""
    from supagent.knowledge.context import DATED_HEAD, PROMPT, _prompt

    dated = {"title": "T", "brief": "B", "evidence": [{"ref": "doc:1", "text": f"Its pages{DATED_HEAD}:\n- a (2026-03-12): b"}]}
    said = " ".join(_prompt(dated).format(title="T", brief="B").split())
    assert "the evidence gives the day each was last changed, follow the most recent one" in said
    assert "never give the older statement as the current one" in said and said.endswith("The page: T. B")
    plain = {"title": "T", "brief": "B", "evidence": [{"ref": "doc:1", "text": "Its central pages first:\n- a: b"}, "x"]}
    assert _prompt(plain) is PROMPT and "most recent" not in PROMPT


def _wiki(n_subjects=3, per=70, dated=True):
    """A wiki read since 0.11.4: a space's home, subjects under it, their pages (one per subject a dated change)."""
    pages, content, i = [], "", 0

    def add(pid, title, text, ancestors, day=None):
        nonlocal content
        block = f"# {title}\n{text}\n"
        page = {"id": pid, "title": title, "space": "OPS", "at": len(content), "chars": len(block),
                "ancestors": ancestors, "links": []}
        if dated and day:
            page["modified"] = day
        pages.append(page)
        content += block

    add("home", "Operations home", "Where the operations teams keep their pages.", [], "2024-01-01")
    for k in range(n_subjects):
        sid = f"s{k}"
        add(sid, f"Subject {k}", f"Subject {k} is a service of the platform.", ["home"], "2024-02-01")
        for j in range(per):
            i += 1
            add(f"p{i}", f"Subject {k} page {j}", f"Notes {j} about subject {k}. " * 8, ["home", sid], "2024-03-01")
        add(f"c{k}", f"Subject {k} moved", f"Since 12 March 2026 subject {k} runs on host-{k}-new.", ["home", sid],
            f"2026-03-1{k}")
    return {"id": 7, "title": "Company wiki", "content": content, "pages": pages}


def test_the_overviews_read_every_document_as_in_0114(app):
    """(0.11.5) The overviews read every document exactly as up to 0.11.4, a big wiki read since 0.11.4 too: each
    change of what they read (by subject, dated, its latest changes) made a big wiki's subjects or changes take the
    overview (measured); its subjects and changes are on its spaces' own pages. The page hash of an overview is then
    0.11.4's: not written again."""
    from collections import Counter

    from supagent.knowledge.context import DIGEST_LEAD, _digest

    def digest_0114(d, chars):                       # 0.11.4's _digest, as released
        content = d.get("content") or ""
        pages = [p for p in d.get("pages") or [] if isinstance(p.get("at"), int) and isinstance(p.get("chars"), int)]
        if len(content) <= chars or len(pages) < 3:
            return content[:chars]
        key = lambda p: str(p.get("id") or p.get("path") or p.get("title") or p.get("url") or "")  # noqa: E731
        ids = {str(p.get("id")): key(p) for p in pages if p.get("id")}
        titles = {str(p.get("title") or "").lower(): key(p) for p in pages if p.get("title")}
        inbound = Counter()
        for p in pages:
            for x in p.get("links") or []:
                target = ids.get(str(x)) or titles.get(str(x).split(":", 1)[-1].lower())
                if target and target != key(p):
                    inbound[target] += 1
        spaces = sorted({str(p["space"]) for p in pages if p.get("space")})
        head = ((f"Spaces: {', '.join(spaces[:10])}. " if spaces else "") +
                "Its central pages first (the ones its other pages link to most), each with its first lines:\n")
        out, used = [head], len(head)
        for p in sorted(pages, key=lambda p: (-inbound[key(p)], str(p.get("path") or "").count("/"),
                                              len(str(p.get("title") or "")))):
            block = content[p["at"]:p["at"] + p["chars"]]
            first, _, body = block.partition("\n")
            title = str(p.get("title") or first.lstrip("# ").strip())
            lead = " ".join((body if first.startswith("# ") else block).split())[:DIGEST_LEAD]
            line = f"- {title}: {lead}\n"
            if used + len(line) > chars:
                break
            out.append(line)
            used += len(line)
        return "".join(out)

    wiki = _wiki(per=200)
    for chars in (2_000, 6_000, 30_000):
        assert _digest(wiki, chars) == digest_0114(wiki, chars)
    old = _wiki(per=200, dated=False)
    for p in old["pages"]:
        p.pop("ancestors")
    assert _digest(old, 6_000) == digest_0114(old, 6_000)


def test_a_big_wiki_space_has_its_own_summary_page(app):
    """(0.11.5) A space of SPACE_MIN_PAGES pages or more of a wiki read since 0.11.4 has a summary page of its own,
    after the overviews: its subjects in turns, dated; a smaller space, or a wiki read before, has none."""
    from supagent.knowledge.context import SPACE_MIN_PAGES, _space_specs

    big = _wiki(n_subjects=3, per=max(SPACE_MIN_PAGES, 200) // 3 + 1)
    specs = _space_specs({"docs": [big]})
    assert [s["slug"] for s in specs] == ["space-ops"] and specs[0]["title"] == "Wiki space Operations home"
    text = specs[0]["evidence"][0]["text"]
    assert "Its subjects" in text and all(f"Subject {k}" in text for k in range(3))
    assert _space_specs({"docs": [_wiki(n_subjects=1, per=10)]}) == []
    old = _wiki(n_subjects=3, per=max(SPACE_MIN_PAGES, 200) // 3 + 1)
    for p in old["pages"]:
        p.pop("ancestors")
    assert _space_specs({"docs": [old]}) == []


def test_the_parents_are_read_from_the_top_whatever_their_order(app):
    """(0.11.5) Confluence's ancestors are taken from the top; a list from the page up (another server, another API)
    is turned round from the depth of the parents that are pages of the wiki."""
    from supagent.knowledge.context import _place, _top_first

    pages = [{"id": "1", "ancestors": []}, {"id": "2", "ancestors": ["1"]}, {"id": "3", "ancestors": ["1", "2"]},
             {"id": "4", "ancestors": ["3", "2", "1"]}]                           # (this one from the page up)
    fixed = {p["id"]: p for p in _top_first(pages)}
    assert _place(fixed["4"]) == ("1", "2", "3", "4") and _place(fixed["3"]) == ("1", "2", "3")
    assert pages[3]["ancestors"] == ["3", "2", "1"]                              # (the document's own pages unchanged)


def test_a_space_page_names_its_subjects_and_is_asked_again_once(app):
    """(0.11.5) A wiki space's page is given its subjects (the titles of its branches' own pages) and, written, is
    asked again once when it leaves one out or names what its evidence never gives (a host it completed itself:
    fs-online-02 from fs-online-01): what comes back is kept, the second call counted; a page that needs nothing is
    not asked again."""
    from supagent.knowledge.context import SPACE_MIN_PAGES, _space_specs, _subject_names, write_summary

    big = _wiki(n_subjects=3, per=max(SPACE_MIN_PAGES, 200) // 3 + 1)
    assert _subject_names([p for p in big["pages"]]) == ["Subject 0", "Subject 1", "Subject 2"]
    spec = _space_specs({"docs": [big]})[0]
    assert spec["guard"] == {"subjects": ["Subject 0", "Subject 1", "Subject 2"]}
    assert spec["brief"].endswith("Its subjects (a row each): Subject 0, Subject 1, Subject 2.")

    class LLM:
        last_usage, last_finish = {"prompt_tokens": 10, "completion_tokens": 5}, "stop"

        def __init__(self, pages):
            self.pages, self.asked = list(pages), []

        def chat(self, messages, max_tokens=0):
            self.asked.append(messages)
            return {"content": self.pages.pop(0)}

    first = ("In short, the space documents its subjects [E1].\n\n## Subjects\n\n| Subject | Now |\n|---|---|\n"
             "| Subject 0 | runs on host-0-new and fs-online-02 [E1] |\n| Subject 1 | on `host-1-new` [E1] |\n")
    fixed = ("In short, the space documents its subjects [E1].\n\n## Subjects\n\n| Subject | Now |\n|---|---|\n"
             "| Subject 0 | runs on host-0-new [E1] |\n| Subject 1 | runs on host-1-new [E1] |\n"
             "| Subject 2 | runs on host-2-new [E1] |\n")
    llm = LLM([first, fixed])
    out = write_summary(spec, llm)
    assert out["calls"] == 2 and out["content"].startswith(fixed.split("\n")[0])
    ask = llm.asked[1][-1]["content"]
    assert "Subject 2" in ask and "fs-online-02" in ask and "host-0-new" not in ask   # (host-0-new: in the evidence)
    assert llm.asked[1][-2] == {"role": "assistant", "content": first.strip()}
    assert out["checks"][0].startswith("written again once: it leaves out these subjects of the space: Subject 2")
    clean = LLM([fixed])
    out = write_summary(spec, clean)
    assert out["calls"] == 1 and len(clean.asked) == 1                    # nothing to correct: no second call
    plain = LLM([first])
    out = write_summary({**spec, "guard": None}, plain)                    # an overview: never asked again
    assert out["calls"] == 1 and len(plain.asked) == 1


def test_what_a_space_page_still_invents_after_it_was_asked_again_is_left_out(app):
    """(0.11.5) Asked again, a wiki space's page that still names a host its evidence never gives (atl-sso-11 on a
    real page) loses the sentence that says it (in a table, the sentence of its cell; the other sentences stay); an
    answer worse than the first (more subjects left out, more names invented) is not kept."""
    from supagent.knowledge.context import SPACE_MIN_PAGES, _space_specs, _without_names, write_summary

    spec = _space_specs({"docs": [_wiki(n_subjects=3, per=max(SPACE_MIN_PAGES, 200) // 3 + 1)]})[0]

    class LLM:
        last_usage, last_finish = {"prompt_tokens": 10, "completion_tokens": 5}, "stop"

        def __init__(self, pages):
            self.pages = list(pages)

        def chat(self, messages, max_tokens=0):
            return {"content": self.pages.pop(0)}

    head = "In short, the space documents its subjects [E1].\n\n## Subjects\n\n| Subject | Now |\n|---|---|\n"
    first = head + ("| Subject 0 | runs on led-app-22 [E1] |\n| Subject 1 | runs on pf-srch-32 [E1] |\n"
                    "| Subject 2 | runs on host-2-new [E1] |\n")
    again = head + ("| Subject 0 | Runs on host-0-new. Its sync job runs on `atl-sso-11`, not known yet. |\n"
                    "| Subject 1 | runs on host-1-new [E1] |\n| Subject 2 | runs on host-2-new [E1] |\n\n"
                    "The sign-in goes through atl-sso-11 [E1].\n")
    out = write_summary(spec, LLM([first, again]))
    assert out["calls"] == 2
    assert "atl-sso-11" not in out["content"] and "led-app-22" not in out["content"]
    assert "| Subject 0 | Runs on host-0-new. |" in out["content"] and "sign-in" not in out["content"]
    assert out["checks"][1].startswith("still there after that, left out: Its sync job runs on `atl-sso-11`")
    worse = head + "| Subject 0 | runs on led-app-22 and mx-9 [E1] |\n"         # two subjects left out: not kept
    out = write_summary(spec, LLM([first, worse]))
    assert "Subject 2" in out["content"] and "led-app-22" not in out["content"] and "pf-srch-32" not in out["content"]
    assert "| Subject 0 | not known yet |" in out["content"]
    page, gone = _without_names("- A on x-1. B stays.\n```\nx-1\n```\n# x-1", ["x-1"])
    assert page == "- B stays.\n```\nx-1\n```\n# x-1" and gone == ["A on x-1."]


def test_a_space_page_that_guesses_between_its_pages_is_asked_again_and_the_guess_left_out(app):
    """(0.11.5) A wiki space's page that reasons from what is usual where its pages do not say ("given typical feature
    store patterns, we assume ...": a real page, where two pages disagreed) is asked again once, told to write what
    the pages say or that they disagree; a guess still there is left out with its sentence (a table cell's parts
    apart: "<br>"). A word its evidence uses itself ("usually" in a page's text) is no guess. The writer's rule says
    it too (RECENCY: never guess; the pages disagree, each statement with its day)."""
    from supagent.knowledge.context import RECENCY, SPACE_MIN_PAGES, _space_specs, guesses, write_summary

    assert "Never guess from what is usual or likely" in " ".join(RECENCY.split())
    spec = _space_specs({"docs": [_wiki(n_subjects=3, per=max(SPACE_MIN_PAGES, 200) // 3 + 1)]})[0]
    assert guesses("Subject 0 typically runs on host-0-new; we assume so.", ["Subject 0 runs on host-0-new."]) == \
        ["typically", "assume"]
    assert guesses("It usually runs at night.", ["The job usually runs at night."]) == []

    class LLM:
        last_usage, last_finish = {"prompt_tokens": 10, "completion_tokens": 5}, "stop"

        def __init__(self, pages):
            self.pages, self.asked = list(pages), []

        def chat(self, messages, max_tokens=0):
            self.asked.append(messages)
            return {"content": self.pages.pop(0)}

    head = "In short, the space documents its subjects [E1].\n\n## Subjects\n\n| Subject | Now |\n|---|---|\n"
    rows = "| Subject 1 | runs on host-1-new [E1] |\n| Subject 2 | runs on host-2-new [E1] |\n"
    first = head + ("| Subject 0 | Runs on host-0-new.<br>The pages disagree. Given typical patterns, we assume it "
                    "moved. [E1] |\n") + rows
    llm = LLM([first, first])
    out = write_summary(spec, llm)
    ask = llm.asked[1][-1]["content"]
    assert out["calls"] == 2 and "guesses from what is usual where the pages do not say (typical, assume)" in ask
    assert "| Subject 0 | Runs on host-0-new.<br>The pages disagree. [E1] |" in out["content"]
    assert "typical" not in out["content"] and out["checks"][1].startswith("still there after that, left out: Given")
