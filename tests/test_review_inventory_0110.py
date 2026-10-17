"""(0.11.0) The review of the inventory reader: a host written with its SSH port, a range with a step, a play's hosts
with a range, a play's vars_files as one string."""
from __future__ import annotations


def test_a_host_with_its_port_keeps_the_inventory():
    from supagent.knowledge.projects import _ini_inventory

    inv = _ini_inventory("inventory/hosts", "[web]\nweb1\nweb2:2222\n\n[db]\ndb1 ansible_host=10.0.0.5\n")
    assert inv is not None                                    # (a port lost the whole inventory)
    assert sorted(inv.hosts_of("web")) == ["web1", "web2"] and list(inv.hosts_of("db")) == ["db1"]


def test_a_range_with_a_step_and_a_huge_range():
    from supagent.knowledge.projects import _expand

    assert _expand("www[01:07:2].example") == ["www01.example", "www03.example", "www05.example", "www07.example"]
    assert len(_expand("web[1:99999999999]")) == 256          # (built whole before: the memory of the range)
    assert _expand("db-[a:c]") == ["db-a", "db-b", "db-c"]


def test_a_plays_hosts_with_a_range_and_vars_files_as_one_string():
    from supagent.knowledge.projects import _ini_inventory, _places, _plays

    inv = _ini_inventory("inventory/hosts", "[web]\nweb[0:3]\n")
    assert inv is not None and _places("web[0:1]", inv)        # (split at ":" before: placed nowhere)
    plays = _plays({"path": "site.yml", "text": "- hosts: web\n  vars_files: vars/main.yml\n  roles: [nginx]\n",
                    "kind": "ansible"})
    assert not plays or plays[0]["vars_files"] in ([], ["vars/main.yml"])   # never one letter a file


def test_a_repository_pages_first_heading_at_once(ctx):
    import time

    from supagent.knowledge.docs import FIRST_HEADING

    line = "# key" + " " * 5000 + "value x"
    t0 = time.monotonic()
    m = FIRST_HEADING.search(line)                              # (cubic before: 2,000 spaces 5 s)
    assert time.monotonic() - t0 < 0.5 and m is not None
    assert FIRST_HEADING.search("# Title ##\n").group(1).rstrip(" \t").rstrip("#").strip() == "Title"
