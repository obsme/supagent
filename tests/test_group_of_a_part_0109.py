"""(0.10.9) A table's "Group" or "Runs on" cell names where a row runs: a server or a group of servers. A cell naming
a part the map knows as no server nor group of servers (a logical database "on pg-shared-1", its cluster) made that
part a host of the row, and the cluster was proposed as a server."""

from __future__ import annotations


def test_a_group_cell_naming_a_known_part_makes_no_host(ctx):
    from test_prose_010 import facts

    text = ("Database | Engine | Group | Owner\nzqpricing-db | PostgreSQL 16 | on pg-shared-1 | pricing team\n"
            "zqpromo-db | PostgreSQL 16 | on pg-shared-1 | marketing team\n")
    t = facts(text, parts=("zqpricing-db", "zqpromo-db", "pg-shared-1"))
    assert not any(v == "runs_on" and o == "pg-shared-1" for _s, v, o in t)


def test_a_group_cell_naming_a_server_or_a_group_still_runs_on_it(ctx):
    from test_prose_010 import facts

    text = ("Role | Target Group | Owner\nzqweb | web | web team\nzqworker | on app-vm-07 | web team\n")
    t = facts(text, hosts=("web", "app-vm-07"), parts=("zqweb", "zqworker"))
    assert ("zqweb", "runs_on", "web") in t and ("zqworker", "runs_on", "app-vm-07") in t


def test_a_new_host_named_in_a_group_cell_is_still_read(ctx):
    from test_prose_010 import facts

    t = facts("Service | Runs on\nzqshop | app-vm-31\n", parts=("zqshop",))
    assert ("zqshop", "runs_on", "app-vm-31") in t
