"""(0.10.4) A role the plays apply to most of a project's groups, starting no service of its own, is configuration,
not a part; a group a play makes as it runs (add_host, group_by) is no place."""
from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_projects_010 import triples, units

from supagent.knowledge import projects as P


def test_a_service_is_known_by_its_names_without_instance_and_unit():
    assert P._service_bases("ceph-mds@{{ ansible_facts['hostname'] }}") == {"ceph-mds"}
    assert P._service_bases("{{ 'x-crash@' + h if c else 'x-crash.service' }}") == {"x-crash"}
    assert P._service_bases("node_exporter") == {"node-exporter"}
    assert P._service_bases("{{ container_service_name }}") == set()
    assert P._service_bases("ceph.target") == {"ceph"}


def _role(name: str, services: list[str]) -> P.Role:
    r = P.Role(name, f"roles/{name}")
    r.services, r.tasks = list(services), True
    return r


def test_a_role_owns_a_service_named_after_it_not_the_systems_or_another_roles():
    roles = {n: _role(n, []) for n in ("app-mon", "app-osd", "app-handler", "app-node-exporter", "app-infra")}
    pre = P._role_prefix(roles)
    assert pre == "app-"
    assert P._own_service(_role("app-mon", ["app-mon@{{ h }}", "app-mon.target"]), pre)
    assert P._own_service(_role("app-node-exporter", ["node_exporter"]), pre)
    assert not P._own_service(_role("app-handler", ["app-osd@{{ h }}", "app-crash@{{ h }}"]), pre)
    assert not P._own_service(_role("app-infra", ["{{ ntp_service_name }}", "firewalld"]), pre)
    assert not P._own_service(_role("app-container-common", ["app.target"]), pre)


def _service_task(name: str) -> str:
    return f'- name: start\n  service:\n    name: "{name}"\n    state: started\n'


SITE = """
- hosts: mons
  roles: [app-common, app-mon, app-exporter]
- hosts: osds
  roles: [app-common, app-osd, app-exporter]
- hosts: mdss
  roles: [app-common, app-mds, app-exporter]
- hosts: rgws
  roles: [app-common, app-rgw, app-exporter]
"""
SERVICES = (("app-common", "{{ container_service_name }}"), ("app-mon", "app-mon@{{ h }}"),
            ("app-osd", "app-osd@{{ h }}"), ("app-mds", "app-mds@{{ h }}"), ("app-rgw", "app-rgw@{{ h }}"),
            ("app-exporter", "app-exporter"))
HOSTS = "[mons]\nm1\n[osds]\no1\n[mdss]\nd1\n[rgws]\nr1\n"


def _files(site: str) -> dict[str, str]:
    files = {"site.yml": site, "hosts": HOSTS}
    for r, svc in SERVICES:
        files[f"roles/{r}/tasks/main.yml"] = _service_task(svc)
    return files


def test_a_role_on_every_group_without_its_own_service_is_not_proposed_as_running_on_each(ctx):
    t = triples(P.facts(units(_files(SITE)))[0])
    assert ("app-mon", "runs_on", "mons") in t and ("app-osd", "runs_on", "osds") in t
    assert ("app-exporter", "runs_on", "mons") in t          # its own service, on every group: a part everywhere
    assert not any(s == "app-common" and v == "runs_on" for s, v, _o in t)   # no service of its own: configuration


def test_a_role_on_few_groups_stays_a_part_whatever_its_service(ctx):
    t = triples(P.facts(units(_files(SITE.replace("app-common, ", "", 3))))[0])
    assert ("app-common", "runs_on", "rgws") in t           # one group of four: kept as it was


def test_a_group_made_while_the_play_runs_is_no_place(ctx):
    site = """
- hosts: mdss
  tasks:
    - add_host:
        name: "{{ item }}"
        groups: active_mdss
      loop: "{{ groups['mdss'] }}"
- hosts: active_mdss
  roles: [app-mds]
- hosts: mdss
  roles: [app-mds]
"""
    files = {"site.yml": site, "hosts": "[mdss]\nd1\n", "roles/app-mds/tasks/main.yml": _service_task("app-mds")}
    t = triples(P.facts(units(files))[0])
    assert ("app-mds", "runs_on", "mdss") in t and ("app-mds", "runs_on", "active_mdss") not in t
