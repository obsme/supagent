"""(0.10.4) A team's pages: the hosts a placement names though no inventory does ("run on meet-01"), every subject of
a list ("the web, prosody and jicofo containers run on ..."), a name in brackets ("the recorder (jibri) runs on ..."),
a table's "scrapes" column; a language, a system, a version or a port is no host."""
from __future__ import annotations

from test_prose_010 import facts


def test_hosts_no_inventory_names_and_every_subject_of_a_list(ctx):
    t = facts("The web, prosody and jicofo containers run on meet-01. The video bridges (jvb) run on meet-jvb-01 and "
              "meet-jvb-02. The recorder (jibri) runs on meet-rec-01.", parts=("web", "prosody", "jicofo", "jvb", "jibri"))
    assert {("web", "runs_on", "meet-01"), ("prosody", "runs_on", "meet-01"), ("jicofo", "runs_on", "meet-01"),
            ("jvb", "runs_on", "meet-jvb-01"), ("jvb", "runs_on", "meet-jvb-02"), ("jibri", "runs_on", "meet-rec-01")} <= t


def test_a_language_a_system_or_a_port_is_no_host(ctx):
    t = facts("The importer runs on Python 3.11 and java17. The gateway runs on port 8080. The api runs on ubuntu22.",
              parts=("importer", "gateway", "api"))
    assert not any(v == "runs_on" for _s, v, _o in t)


def test_a_tables_scrapes_column_says_what_its_part_monitors(ctx):
    text = "Prometheus | Runs on | Scrapes\nvideo watcher | obs-01 | prosody, jvb (port 8080), unknown thing\n"
    t = facts(text, hosts=("obs-01",), parts=("video watcher", "prosody", "jvb"))
    assert {("video watcher", "monitors", "prosody"), ("video watcher", "monitors", "jvb"),
            ("video watcher", "runs_on", "obs-01")} <= t
    assert not any(o == "unknown thing" for _s, _v, o in t)


def test_a_qualified_name_is_the_part_of_the_same_repository_as_its_row(ctx):
    from supagent.knowledge.understand import Names, _qualified, norm

    n = Names()
    for p in ("prometheus", "store-prometheus", "prometheus-server", "store-mgr", "api-gateway"):
        n.add_part(p)
    n.homes = {norm("store-prometheus"): {1}, norm("store-mgr"): {1}, norm("prometheus-server"): {2},
               norm("api-gateway"): {2}, norm("prometheus"): {3}}
    assert _qualified("storage Prometheus", "prometheus", n, ["store-mgr"]) == "store-prometheus"
    assert _qualified("clinic Prometheus", "prometheus", n, ["api-gateway"]) == "prometheus-server"
    assert _qualified("video Prometheus", "prometheus", n, []) == "prometheus"        # nothing to tell: as resolved
    assert _qualified("Grafana", "grafana", n, ["store-mgr"]) == "grafana"            # one candidate: itself
