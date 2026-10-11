"""(0.10.7, the open obs runs) "What does our runbook say to check when <an alert> fires?": one search of the kind
"guide" found nothing (the runbook is a wiki page, a "doc"), every kind was searched, and the answer gave as the
runbook's steps the System map's explanation of the alert's link to the part it watches, which the AI wrote; the
runbook's own steps, in the same result, were left out. In the prompt, the runbook's excerpt had lost its line of
steps (cut at its end) while the AI's explanation was whole. What the AI explained is said so wherever the agent
reads it, "guide" and "doc" are the documentation, and an excerpt keeps the words it was chosen for."""
from __future__ import annotations

import json

from test_brief import system  # noqa: F401  (the fixture: Billing = Invoicing + Payments, grid-a, ledger db)
from test_judge_010 import conf, piece  # noqa: F401
from test_knowledge import world  # noqa: F401

STEPS = "Check the zq parts it names, their metrics over the same minutes, then what depends on them."


def test_who_wrote_an_explanation():
    from supagent.knowledge.brief import ai_explained

    assert ai_explained("llm") == "explained by the AI"
    assert ai_explained("carol and the AI") == "explained by the team and the AI"
    assert ai_explained("admin") == "" and ai_explained(None) == ""


def _by_the_ai(ids):
    from superset.extensions import db

    from supagent.knowledge.freshness import touch
    from supagent.models import Link

    x = db.session.query(Link).filter(Link.kind == "calls", Link.a_ref == f"facet:{ids['Payments']}").one()
    x.detail, x.explained_by = "Check the ledger db's open connections in the same window.", "llm"
    touch()
    db.session.commit()


def test_the_map_says_which_explanations_the_ai_wrote(system, app):  # noqa: F811
    from supagent.knowledge.brief import build, links_of
    from supagent.knowledge.index import _map_pieces
    from supagent.knowledge.search import as_shown

    ids = system
    _by_the_ai(ids)
    pieces = [p for p in _map_pieces() if p["ref"] == f"map:{ids['Payments']}"]
    shown = as_shown(pieces)[f"map:{ids['Payments']}"]
    assert ("- Payments calls ledger db (explained by the AI): one connection per run Check the ledger db's open "
            "connections in the same window.") in shown
    assert "- Invoicing depends on Payments: waits for the payments of the day" in shown      # a person's words
    assert "(explained by" not in pieces[0]["text"]                     # the stored piece (searched, embedded) as it was
    said = links_of(["Payments"])["parts"][0]["what_to_do_when_following"]
    assert said == ["Payments calls ledger db (explained by the AI): Check the ledger db's open connections in the "
                    "same window."]
    lines = "\n".join(build("Why is Payments late today?")["lines"])
    assert "Payments calls ledger db (explained by the AI): Check the ledger db's open connections" in lines


def test_a_link_of_a_kind_a_person_named_reads_as_words(system, app):  # noqa: F811
    from supagent.knowledge.search import as_shown

    ids = system
    text = f"service ledger db\n- Payments link:3f2a9c1d ledger db: keeps its ledger there"
    got = as_shown([{"ref": f"map:{ids['ledger db']}", "kind": "map", "text": text}])
    assert got[f"map:{ids['ledger db']}"].endswith("- Payments is linked to ledger db: keeps its ledger there")


def test_a_map_piece_is_cut_at_line_starts_only():
    from supagent.knowledge.search import excerpt

    text = "\n".join(f"- zq-{i} calls zq-{i + 1} (explained by the AI): it sends its batch. Check zq-{i + 1}'s "
                     f"queue then." for i in range(30))
    got = excerpt(text, "zq-17 queue", 300, lines=True)
    assert "- zq-17 calls zq-18 (explained by the AI)" in got or "- zq-16 calls zq-17 (explained by the AI)" in got
    assert all(ln.startswith(("- ", "…- ")) for ln in got.rstrip("…").split("\n"))


def test_an_excerpt_keeps_the_words_it_was_chosen_for():
    from supagent.knowledge.search import excerpt

    page = ("Source: https://wiki.example/OPS/Runbook+ZqAlert\n# Runbook ZqAlert\nZqAlert fires when its condition "
            "holds for 5 minutes on zq-a, zq-b, zq-c. ZqAlert fires to the pager, which pages the on-call for the "
            "critical alerts and posts the others to the chat.\n" + STEPS)
    got = excerpt(page, "What does our runbook say to check when ZqAlert fires?", 330)
    assert got.startswith("Source: https://wiki.example/OPS/Runbook+ZqAlert\n") and STEPS in got


def test_guide_and_doc_are_the_documentation(conf, monkeypatch):  # noqa: F811
    from supagent import tools
    from supagent.knowledge import search as S

    values, _unknown = conf
    values["search.rewrite"] = "off"
    seen: list = []

    def search(q, k=None, kinds=None, **kw):
        seen.append(kinds)
        return [piece("doc:7")] if kinds and "doc" in kinds else []

    monkeypatch.setattr(S, "search", search)
    monkeypatch.setattr(tools, "_as_user", lambda: __import__("contextlib").nullcontext())
    for kind in ("guide", "doc", "runbook", "Wiki", "documentation"):
        seen.clear()
        out = tools.search_knowledge("zqalert runbook what to check", kind=kind)
        assert [f["ref"] for f in out["results"]] == ["doc:7"] and seen == [("guide", "doc")] and "note" not in out
    seen.clear()
    out = tools.search_knowledge("zqalert notes", kind="note")         # the notes: then the documentation with them
    assert seen == [("guide", "teamnote"), ("guide", "doc", "teamnote")] and [f["ref"] for f in out["results"]] == \
        ["doc:7"] and out["note"] == "nothing of the kind 'note': the documentation and the users' notes searched"


def test_records_about_reads_the_servers_a_part_runs_on(system, app):  # noqa: F811
    from supagent import tools
    from supagent.knowledge import sysmap
    from supagent.knowledge.freshness import touch

    ids = system
    sysmap.save_interaction(ids["ledger db"], ids["srv-1"], "runs_on", "", "admin")
    touch()
    assert tools._servers_of_named(["ledger db"]) == ["srv-1"]          # an alert of it is kept under its server
    assert tools._servers_of_named(["Invoicing"]) == []                 # a pool is no server (its servers: made_of)
    assert tools._servers_of_named(["srv-1", "ledger db"]) == []        # named already
