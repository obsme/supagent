"""(0.10.1) Three Ansible idioms read: a play's hosts written with Jinja (a variable, its default('x'), groups['x']), a
role kept to one group by its condition (when: inventory_hostname in groups[...] / 'x' in group_names), and a playbook,
an inventory or variables given as a sample to copy (site.yml.sample, hosts.example, all.yml.dist)."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_projects_010 import triples, units

STORE = {
    "hosts.example": "[mons]\nmon-1\nmon-2\n\n[osds]\nosd-1\n\n[mgrs]\nmon-1\n",
    "group_vars/all.yml.sample": "mon_group_name: mons\n",
    "site.yml.sample": "- hosts: \"{{ mon_group_name | default('mons') }}\"\n  roles:\n    - role: monitor\n\n"
                       "- hosts: \"{{ osd_group_name | default('osds') }}\"\n  roles:\n    - role: diskd\n\n"
                       "- hosts: all\n  roles:\n    - role: managerd\n      when: inventory_hostname in groups['mgrs']\n"
                       "    - role: lookoutd\n      when: \"'osds' in group_names\"\n",
    "roles/monitor/tasks/main.yml": "- service: name=monitord state=started\n",
    "roles/diskd/tasks/main.yml": "- service: name=diskd state=started\n",
    "roles/managerd/tasks/main.yml": "- service: name=managerd state=started\n",
    "roles/lookoutd/tasks/main.yml": "- service: name=lookoutd state=started\n",
}


def test_templated_hosts_conditions_and_samples(ctx):
    from supagent.knowledge.projects import facts

    found, _names = facts(units(STORE))
    t = triples(found)
    assert ("mon-1", "in_group", "mons") in t and ("osd-1", "in_group", "osds") in t        # hosts.example
    assert ("monitor", "runs_on", "mons") in t                       # {{ mon_group_name | default('mons') }}
    assert ("diskd", "runs_on", "osds") in t                         # a default('osds') with no variable set
    assert ("managerd", "runs_on", "mgrs") in t and ("managerd", "runs_on", "all") not in t   # kept to its group
    assert ("lookoutd", "runs_on", "osds") in t and ("lookoutd", "runs_on", "all") not in t


def test_the_samples_are_read_as_what_they_stand_for():
    from supagent.knowledge.docs import sample_base, wanted_file
    from supagent.knowledge.understand import lang_of

    assert sample_base("site.yml.sample") == "site.yml" and sample_base("group_vars/all.yml.dist") == "group_vars/all.yml"
    assert sample_base("hosts.example") == "hosts.example"         # no extension under it: the name itself
    assert lang_of("site.yml.sample") == lang_of("site.yml")
    assert wanted_file("group_vars/all.yml.sample", "code")
