"""(0.10.7, obs7dev-l) "On which servers does db-a run, and which one is its primary?" took nine calls: the search
found the two pieces of the page of the data stores, and the knowledge given with the question keeps one line per
page: the first piece's (the primaries of other databases) was given, the second's, which says db-a's primary, left
out as the same page. Of two pieces of one page, the one that holds more of the names the question writes is the
page's line."""
from __future__ import annotations

SRC = "Source: https://wiki.example/ARCH/Data+stores\n"
FIRST = {"kind": "doc", "ref": "doc:1#ab12-2", "title": "Wiki ARCH › Data stores",
         "text": SRC + "db-c: the primary runs on srv-c1, it replicates to srv-c2.\n"
                       "stg-db-a is one of the databases of the staging cluster."}
SECOND = {"kind": "doc", "ref": "doc:1#ab12-1", "title": "Wiki ARCH › Data stores",
          "text": SRC + "db-a | PostgreSQL 16 | srv-a1, srv-a2\ndb-a: the primary runs on srv-a1, it replicates to srv-a2."}


def test_the_names_a_question_writes(ctx):
    from supagent.knowledge.search import holds_names, names_written

    assert names_written("On which servers does db-a run, and which one is its primary?") == {"db-a"}
    assert names_written("Errors of srv_x.y on 2026-09-28 at 09:30, 10.5 % of rack r-1b?") == {"srv_x.y", "r-1b"}
    assert holds_names(FIRST["text"], {"db-a"}) == 0            # stg-db-a is another name
    assert holds_names(SECOND["text"], {"db-a"}) == 1
    assert holds_names("DB-A is down.", {"db-a"}) == 1


def test_the_piece_of_a_page_that_holds_the_named_part_is_given(ctx, monkeypatch):
    from supagent.knowledge import judge, resolve, spelling
    from supagent.knowledge.search import knowledge_block

    monkeypatch.setattr(judge, "judged", lambda q, run, n: ([FIRST, SECOND], {}))
    monkeypatch.setattr(resolve, "gone_names", lambda: set())
    monkeypatch.setattr(spelling, "correct", lambda q: {"changes": []})
    text = knowledge_block("On which servers does db-a run, and which one is its primary?", set())
    assert "db-a: the primary runs on srv-a1" in text and "db-c" not in text
    assert text.count("Wiki ARCH › Data stores") == 1                        # one line for the page
    same = knowledge_block("Which database is the primary of the staging cluster?", set())   # no name written:
    assert "db-c: the primary runs on srv-c1" in same and "srv-a1" not in same              # the first, as before
    other = knowledge_block("Which database replicates to srv-c2?", set())   # the name in the first piece only
    assert "db-c: the primary runs on srv-c1" in other
