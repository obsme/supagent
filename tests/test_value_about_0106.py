"""(0.10.6) The AI's description of a part is kept only when it says something of the part and keeps its links'
directions (measured on a lab map in 0.10.5: "PnL is a value of the category subject.", "It is read by Other.", and
"tix_api ... calls nginx_web" where the line was "nginx_web calls tix_api"); the subjects, topics the knowledge is
about, are no parts to describe."""

from __future__ import annotations


def test_a_description_that_says_nothing_is_not_kept():
    from supagent.knowledge.value_about import says_something

    assert not says_something("PnL is a value of the category subject.", "PnL", "subject")
    assert not says_something("It is read by Other.", "Other", "subject")
    assert not says_something("Metrics sends data to it.", "Metrics", "subject")
    assert says_something("zq-orders takes the customers' orders and hands them to the shop.", "zq-orders",
                          "application")
    assert says_something("zq-db-01 is a server that runs zq-ordersdb.", "zq-db-01", "server")


def test_a_description_that_turns_a_link_round_is_not_kept():
    from supagent.knowledge.value_about import links_kept

    lines = ["zq-web calls zq-api", "zq-api depends on zq-cache", "zq-api runs on zq-app (runs as the API)"]
    assert not links_kept("zq-api is an application that calls zq-web and depends on zq-cache.", "zq-api", lines)
    assert links_kept("zq-api is an application called by zq-web that depends on zq-cache.", "zq-api", lines)
    assert not links_kept("zq-api is an application that is depended on by zq-cache.", "zq-api", lines)
    assert links_kept("zq-api runs on zq-app.", "zq-api", lines)
    both = lines + ["zq-api calls zq-web"]                                  # said both ways: either is right
    assert links_kept("zq-api calls zq-web.", "zq-api", both)


def test_the_subjects_are_not_described(ctx):
    from superset.extensions import db

    from supagent.knowledge.value_about import wanted
    from supagent.models import Facet

    rows = [Facet(facet="subject", value="zqtopic", status="approved", source="seed"),
            Facet(facet="application", value="zqapp", status="approved", source="admin")]
    db.session.add_all(rows)
    db.session.commit()
    try:
        names = {f.value for f in wanted(1000)}
        assert "zqapp" in names and "zqtopic" not in names
    finally:
        for f in rows:
            db.session.delete(f)
        db.session.commit()
