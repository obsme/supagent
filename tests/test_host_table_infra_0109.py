"""(0.10.9) A table of hosts says more than what runs on each host: its power supplies, its switch ports and its owner
("Server | Uplinks | Power feed | Maintainer"). Those columns were skipped: a wiki stating hundreds of a
datacenter's power and network links gave none of them to the System map. Each becomes a link of its own words
(powered by, connects to, owned by), the one a person draws with those words, proposed in the deployment's category
for its target (power, switch port, team) and not proposed when the deployment has no such category; the host is a
server; a port number or a person is no link; a table of parts' owner naming a team is its owner on the map (a
person stays a fact of the Context pages); the parts column says
where parts run as before."""
from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_prose_010 import facts
from test_second_pass_0105 import _approve_all, _clean, _repo, _state

TABLE = ("Host | Role | Services | Switch ports | PDUs | Owner | IP\n"
         "app-vm-01 | server | reverse_proxy | sw-a-1 ge-0/0/10, sw-a-2 ge-0/0/10 | pdu-a-left, pdu-a-right | web team | "
         "10.1.2.3\n"
         "db-vm-02 | server | db | sw-b-1 ge-0/0/11 | pdu-b-left | data team | 10.1.2.4\n")


def test_power_ports_and_owner_columns_are_links(ctx):
    t = facts(TABLE, parts=("reverse_proxy", "db"))
    assert {("reverse_proxy", "runs_on", "app-vm-01"), ("db", "runs_on", "db-vm-02")} <= t
    assert {("app-vm-01", "powered_by", "pdu-a-left"), ("app-vm-01", "powered_by", "pdu-a-right"),
            ("db-vm-02", "powered_by", "pdu-b-left")} <= t
    assert {("app-vm-01", "connects_to", "sw-a-1 ge-0/0/10"), ("app-vm-01", "connects_to", "sw-a-2 ge-0/0/10"),
            ("db-vm-02", "connects_to", "sw-b-1 ge-0/0/11")} <= t
    assert {("app-vm-01", "owned_by", "web team"), ("db-vm-02", "owned_by", "data team")} <= t
    assert not any(o.startswith("10.1.2") for _s, _v, o in t)           # the address column: no link


def test_a_port_number_or_a_person_is_no_link(ctx):
    text = ("Host | Services | Ports | Owner\napp-vm-03 | reverse_proxy | 80, 443, tcp/8443 | Jane Doe\n"
            "app-vm-04 | reverse_proxy | 8080 | platform team\n")
    t = facts(text, parts=("reverse_proxy",))
    assert not any(v == "connects_to" for _s, v, _o in t)               # port numbers: no switch port
    assert ("app-vm-03", "owned_by", "Jane Doe") not in t and ("app-vm-04", "owned_by", "platform team") in t


def test_one_column_per_supply_or_link_and_columns_of_something_else(ctx):
    text = ("Hostname | PSU1 | PSU_B | Uplink 1 | Port2 | PSU status | Uplink speed | Power BI\n"
            "app-vm-05 | pdu-r1-a | ups2 | sw-c-1 xe-1/0/3 | sw-c-2 et-0/0/7 | OK | 10G | yes\n")
    t = facts(text)
    assert {("app-vm-05", "powered_by", "pdu-r1-a"), ("app-vm-05", "powered_by", "ups2"),
            ("app-vm-05", "connects_to", "sw-c-1 xe-1/0/3"), ("app-vm-05", "connects_to", "sw-c-2 et-0/0/7")} <= t
    assert not any(o in ("OK", "10G", "yes") for _s, _v, o in t)         # a status, a speed, another tool: no link
    t = facts("Host | Power\napp-vm-06 | redundant\napp-vm-07 | left\n")
    assert not any(v == "powered_by" for _s, v, _o in t)                 # a word, no device's name


def test_a_device_with_its_outlet_or_port_in_any_notation(ctx):
    text = ("Server (Rack/U) | PSU 1 (PDU / Outlet) | PSU 2 | NIC 1 (Switch / Port) | NIC 2 | Uplink 3 | Uplink 4\n"
            "app-vm-08 (R2/U12) | pdu-r2-a / 4 | pdu-r2-b:4 | sw-r2-1 / Ethernet1/7 | sw-r2-2:Eth1/7 | Gi1/0/9 on "
            "sw-core-1 | eth0\n"
            "app-vm-09 | pdu-r2-a/5 | pdu-r2-b #5 | sw-r2-1/E1/8 | sw-r2-2 xe-0/0/8 | bond0 | sw-r2-3\n")
    t = facts(text)
    assert {("app-vm-08", "powered_by", "pdu-r2-a"), ("app-vm-08", "powered_by", "pdu-r2-b"),
            ("app-vm-09", "powered_by", "pdu-r2-a"), ("app-vm-09", "powered_by", "pdu-r2-b")} <= t
    assert {("app-vm-08", "connects_to", "sw-r2-1 Ethernet1/7"), ("app-vm-08", "connects_to", "sw-r2-2 Ethernet1/7"),
            ("app-vm-08", "connects_to", "sw-core-1 GigabitEthernet1/0/9"),
            ("app-vm-09", "connects_to", "sw-r2-1 Ethernet1/8"), ("app-vm-09", "connects_to", "sw-r2-2 xe-0/0/8"),
            ("app-vm-09", "connects_to", "sw-r2-3")} <= t                                  # one name per interface
    assert not any(o in ("eth0", "bond0") or o.startswith("pdu-r2-a ") for _s, _v, o in t)   # the host's own NIC; no
    assert not any(s.startswith("app-vm-08 ") for s, _v, _o in t)                       # outlet in a name; the host
    t = facts("Host | NIC 1 | NIC 2 | Interface 3\napp-vm-10 | X710 | sw-r3-1:Eth1/2 | eno1\n")   # a card's model, a
    assert {o for _s, v, o in t if v == "connects_to"} == {"sw-r3-1 Ethernet1/2"}                # host's own NIC: no


def test_their_targets_go_in_the_deployments_category_or_nowhere(ctx, monkeypatch):
    from supagent.knowledge import facets, proposals

    monkeypatch.setattr(facets, "editable", lambda: ["server", "application", "power", "switch port", "team"])
    assert proposals._category("power", "pdu-a-left") == "power"
    assert proposals._category("port", "sw-a-1 ge-0/0/10") == "switch port"
    assert proposals._category("team", "web team") == "team"
    monkeypatch.setattr(facets, "editable", lambda: ["server", "application"])
    assert proposals._category("power", "pdu-a-left") is None              # no such category: no link proposed
    monkeypatch.setattr(facets, "editable", lambda: ["server", "application", "groups", "backups", "lookups"])
    assert proposals._category("power", "pdu-a-left") is None              # "ups" as a word only


def test_a_link_in_words_is_the_one_a_person_draws_with_those_words(ctx):
    from supagent.knowledge.proposals import LINK_OF
    from supagent.knowledge.sysmap import generic, worded

    assert LINK_OF["powered_by"] == worded("powered by") == worded("  Powered   BY ") and generic(LINK_OF["powered_by"])
    assert LINK_OF["connects_to"] == worded("connects to") and LINK_OF["owned_by"] == worded("owned by")
    assert len({LINK_OF["powered_by"], LINK_OF["connects_to"], LINK_OF["owned_by"]}) == 3


PAGE = {
    "README.md": "# Servers\n\n| Server | Uplinks | Power feed | Maintainer | Services |\n|---|---|---|---|---|\n"
                 "| zqhost-01 | zqsw-1 Gi1/0/5 | zqpdu-left | zqnet squad | zqproxy |\n"
                 "| zqhost-02 | zqsw-2 Gi1/0/6 | zqpdu-right | Jane Doe | - |\n\n"
                 "# Services\n\n| Service | Owner | Notes |\n|---|---|---|\n| zqproxy | John Smith | the front |\n"
                 "| zqapi | zqweb team | the API |\n",
}


def test_read_and_proposed_end_to_end(env):  # noqa: F811
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.knowledge.sysmap import worded
    from supagent.models import Facet, Link

    before_cats = settings.get("categories.custom")
    settings.set_value("categories.custom", ["server", "power supply", "switch port", "team"])
    proxy = Facet(facet="application", value="zqproxy", status="approved", source="admin")
    api = Facet(facet="application", value="zqapi", status="approved", source="admin")
    db.session.add_all([proxy, api])
    db.session.commit()
    before, d = _state(), _repo(PAGE, name="zqdc")
    try:
        U.run(reason="test")
        rels = {(r["from"], r["kind"], r["to"], r["obj_kind"]) for r in U.export()["relations"]}
        assert ("zqhost-02", "powered_by", "zqpdu-right", "power") in rels
        assert ("zqhost-01", "connects_to", "zqsw-1 GigabitEthernet1/0/5", "port") in rels
        assert ("zqproxy", "owned_by", "John Smith", "attribute") in rels      # a person: a fact, as before
        assert ("zqapi", "owned_by", "zqweb team", "owner") in rels             # a team: the part's owner
        out = propose()
        vals = {f.value: f for f in db.session.query(Facet).filter(Facet.value.like("zq%") | Facet.value.like("%Doe")
                                                                     | Facet.value.like("%Smith"))}
        assert vals["zqhost-01"].facet == vals["zqhost-02"].facet == "server"   # a host with no part on it too
        assert vals["zqpdu-left"].facet == "power supply" and vals["zqsw-2 GigabitEthernet1/0/6"].facet == "switch port"
        assert vals["zqnet squad"].facet == "team"
        assert "Jane Doe" not in vals and "John Smith" not in vals              # a person: no value, no link
        ref = lambda n: f"facet:{vals[n].id}"                                   # noqa: E731
        x = db.session.query(Link).filter(Link.a_ref == ref("zqhost-01"), Link.b_ref == ref("zqpdu-left")).one()
        assert (x.kind, x.note, x.status) == (worded("powered by"), "powered by", "proposed") and x.evidence
        assert db.session.query(Link).filter(Link.a_ref == ref("zqhost-01"), Link.b_ref == ref("zqnet squad"),
                                             Link.kind == worded("owned by")).count() == 1
        assert db.session.query(Link).filter(Link.a_ref == ref("zqproxy"), Link.b_ref == ref("zqhost-01"),
                                             Link.kind == "runs_on").count() == 1
        assert out["links"] == 7, out              # 2 x (power, port), its owner, where the proxy runs, the API's team
        assert db.session.query(Link).filter(Link.a_ref == f"facet:{api.id}", Link.b_ref == ref("zqweb team"),
                                             Link.kind == worded("owned by")).count() == 1
        assert vals["zqweb team"].facet == "team" and db.session.get(Facet, api.id).facet == "application"
        # a person drew one of them in their own words already: confirmed, never proposed twice
        db.session.delete(x)
        db.session.commit()
        db.session.add(Link(a_ref=ref("zqhost-01"), b_ref=ref("zqpdu-left"), kind=worded("Powered  by"),
                            note="Powered  by", status="approved", source="admin"))
        db.session.commit()
        propose()
        assert db.session.query(Link).filter(Link.a_ref == ref("zqhost-01"), Link.b_ref == ref("zqpdu-left")).count() == 1
        _approve_all()
        U.run(reason="test")
        again = propose()
        assert (again["values"], again["links"], again["removals"]) == (0, 0, 0), again
    finally:
        _clean(before, [d])
        db.session.query(Facet).filter(Facet.id.in_([proxy.id, api.id])).delete(synchronize_session=False)
        db.session.commit()
        settings.set_value("categories.custom", before_cats)


def test_with_no_category_for_them_nothing_is_proposed(env):  # noqa: F811
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet

    before_cats = settings.get("categories.custom")
    settings.set_value("categories.custom", ["server"])
    page = {"README.md": "| Server | Uplinks | Power feed |\n|---|---|---|\n| zqhost-07 | zqsw-7 Gi1/0/7 | zqpdu-7 |\n"}
    before, d = _state(), _repo(page, name="zqdc7")
    try:
        U.run(reason="test")
        out = propose()
        assert not db.session.query(Facet).filter(Facet.value.like("zq%7%")).count(), out   # not the host either
    finally:
        _clean(before, [d])
        settings.set_value("categories.custom", before_cats)


def test_what_powers_a_power_device_said_in_a_sentence(ctx):
    t = facts("UPS-R9 feeds pdu-r9-a and pdu-r9-b. The PDU pdu-r8-a (fed from ups-r8) sits at the back.\n"
              "pdu-r7-a, pdu-r7-b are powered by UPS-R7.\n"
              "The UPS feeds the room. The billing job feeds the ledger-db with invoices.\n")
    assert {("pdu-r9-a", "powered_by", "UPS-R9"), ("pdu-r9-b", "powered_by", "UPS-R9"),
            ("pdu-r8-a", "powered_by", "ups-r8"), ("pdu-r7-a", "powered_by", "UPS-R7"),
            ("pdu-r7-b", "powered_by", "UPS-R7")} <= t
    assert not any(o in ("the room", "ledger-db") or s in ("room", "ledger-db") for s, _v, o in t)


def test_a_host_column_after_an_asset_tag_two_devices_in_a_cell_and_other_languages(ctx):
    t = facts("Asset Tag | Hostname | Model | PDUs | Owner\nAT-0091 | app-vm-31 | R650 | pdu-q1-a, pdu-q1-b | platform team\n")
    assert {("app-vm-31", "powered_by", "pdu-q1-a"), ("app-vm-31", "powered_by", "pdu-q1-b"),
            ("app-vm-31", "owned_by", "platform team")} <= t
    assert not any(s == "AT-0091" for s, _v, _o in t)                       # the asset tag is no host
    t = facts("Node | Power (PSU1 / PSU2) | Uplinks\napp-vm-32 | pdu-q2-a / pdu-q2-b | sw-q2-1 / sw-q2-2\n")
    assert {("app-vm-32", "powered_by", "pdu-q2-a"), ("app-vm-32", "powered_by", "pdu-q2-b"),
            ("app-vm-32", "connects_to", "sw-q2-1"), ("app-vm-32", "connects_to", "sw-q2-2")} <= t
    assert ("app-vm-32", "connects_to", "sw-q2-1 sw-q2-2") not in t          # two switches, no port named "sw-q2-2"
    t = facts("Serveur | Alimentation A | Équipe\napp-vm-33 | pdu-q3-a | équipe plateforme\n")
    assert {("app-vm-33", "powered_by", "pdu-q3-a"), ("app-vm-33", "owned_by", "équipe plateforme")} <= t


def test_a_port_alone_names_no_device(ctx):
    t = facts("Serveur | Port Data 1 (acc-x-1) | Uplink\napp-vm-41 | GigabitEthernet1/0/11 | Eth1/4\n")
    assert not any(v == "connects_to" for _s, v, _o in t)          # the switch is in the header: no "GigabitEthernet1"


ASSETS = {
    "README.md": "| Hostname | PDUs | Uplink | Owner |\n|---|---|---|---|\n"
                 "| zqnode-1 | zqpdu-9-a | zqtor-9 Ethernet1/1 | zqcompute team |\n\n"
                 "| Asset Tag | Hostname | Owner |\n|---|---|---|\n| AT-1 | zqnode-1 | zqcompute team |\n"
                 "| AT-2 | zqpdu-9-a | zqcompute team |\n| AT-3 | zqtor-9 | zqcompute team |\n\n"
                 "The PDU zqpdu-9-a (fed by zqups-9) sits at the back.\n",
}


def test_an_asset_registers_switch_and_pdu_are_no_servers(env):  # noqa: F811
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import understand as U
    from supagent.knowledge.proposals import propose
    from supagent.models import Facet

    before_cats = settings.get("categories.custom")
    settings.set_value("categories.custom", ["server", "power", "switch port", "team"])
    before, d = _state(), _repo(ASSETS, name="zqassets")
    try:
        U.run(reason="test")
        propose()
        vals = {f.value: f.facet for f in db.session.query(Facet).filter(Facet.value.like("zq%"))}
        assert vals.get("zqnode-1") == "server" and vals.get("zqpdu-9-a") == "power"
        assert vals.get("zqtor-9") is None or vals.get("zqtor-9") != "server"       # a switch: never a server
        assert vals.get("zqtor-9 Ethernet1/1") == "switch port" and vals.get("zqups-9") == "power"
        from supagent.models import Link
        ids = {f.value: f.id for f in db.session.query(Facet).filter(Facet.value.like("zq%"))}
        assert db.session.query(Link).filter(Link.a_ref == f"facet:{ids['zqpdu-9-a']}",           # a PDU keeps its
                                             Link.b_ref == f"facet:{ids['zqups-9']}").count() == 1   # own supply
        assert not db.session.query(Link).filter(Link.a_ref == f"facet:{ids['zqpdu-9-a']}",
                                                 Link.b_ref == f"facet:{ids['zqcompute team']}").count()  # no owner
    finally:
        _clean(before, [d])
        settings.set_value("categories.custom", before_cats)
