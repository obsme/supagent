"""(0.10.9.2) What a category holds when its name says nothing the filing knows ("box", "fleet", "category c"): read
from the person's description of it (its head noun, the gloss in brackets after it, what follows a first colon),
else from where the person nested it; a name that says a kind keeps it; a description that defines nothing changes
nothing. The filing's name rules then file servers, groups, teams, services and the hosts' software in such
categories as they do in categories named "server", "server group", "team"..."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("text,role", [
    ("one physical or virtual computer, by the name it answers to", None),          # no noun for it: nothing
    ("the computers (virtual machines) we run things on", "host"),
    ("Machines physiques ou virtuelles, par leur nom", "host"),
    ("un serveur (physique ou virtuel) désigné par son nom", "host"),
    ("a set of servers that share one role", "group"),
    ("l'ensemble des serveurs d'un même rôle", "group"),
    ("an inventory group: the computers of one role", "group"),
    ("the people who answer for a product (a team)", "team"),
    ("une équipe qui exploite les produits", "team"),
    ("the stages a release goes through: test, acceptance, live", "environment"),
    ("databases and key-value stores the products write to", "store"),
    ("a relational database engine the services keep their tables in", "store"),
    ("database engine software the products use", "store"),
    ("tooling software deployed on each machine: agents, web servers", "software"),
    ("host software: what runs the machines", "software"),
    ("a service our own platform runs for the products", "own service"),
    ("services hosted by another company that we call", "external"),
    ("a service outside the company that the products use", "external"),
    ("what customers use: a web site, a mobile app, an API", "application"),
    ("message brokers carrying events between services", "broker"),
    ("queues of the broker, with who publishes and who reads", "messaging"),
    ("a nightly batch job and what it reads", "job"),
    ("a lane of the road map (no kind of thing)", None),
    ("a firewall or a web application firewall", None),                  # its head noun says no kind we file
    ("une base de données relationnelle de l'équipe", "store"),           # French: the head noun comes first
    ("a database instance per environment", "store"),
    ("a deployable unit of a product (an API, a worker, a consumer, a UI)", None),   # examples, no definition
    ("", None),
])
def test_what_a_description_defines_its_category_as(text, role):
    from supagent.knowledge.catkind import described

    assert described(text) == role


def _person(monkeypatch, about, inside=None):
    from supagent import settings

    conf = {"categories.about": about, "categories.inside": inside or {}}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))


def test_a_name_that_says_a_kind_keeps_it_and_one_that_says_nothing_reads_its_description(ctx, monkeypatch):
    from supagent.knowledge.catkind import kind_name, serverish

    _person(monkeypatch, {"server": "a team (wrongly described)", "box": "a server we run things on (physical or "
                          "virtual)", "zqx lane": "a lane of the road map", "crate": "Ansible groups: boxes that share "
                          "a role", "zqx kit": "the software we deploy to each box (agents, runtimes)"})
    assert kind_name("server") == "server" and kind_name("Platform Service") == "platform service"
    assert kind_name("box") == "server" and serverish("box")
    assert kind_name("crate") == "server group" and serverish("crate")
    assert kind_name("zqx kit") == "installed software" and not serverish("zqx kit")
    assert kind_name("zqx lane") == "zqx lane" and not serverish("zqx lane")      # defines nothing: as before
    assert kind_name("") == ""


def test_where_a_category_is_nested_says_what_it_holds_when_nothing_else_does(ctx, monkeypatch):
    from supagent.knowledge.catkind import kind_name

    _person(monkeypatch, {"fleet": "an inventory group of one role", "zqx item": "", "zqx lane": ""},
            {"zqx item": "fleet", "zqx lane": "message broker", "zqx stream": "fleet"})
    assert kind_name("zqx item") == "server"                  # inside a category of groups: their hosts
    assert kind_name("zqx lane") == "queue"                   # inside the brokers: their queues
    assert kind_name("zqx stream") == "zqx stream"            # its name says what it holds: kept


def test_the_filing_finds_the_persons_categories_by_their_descriptions(ctx, monkeypatch):
    from supagent import settings
    from supagent.knowledge import naming
    from supagent.knowledge.proposals import _category

    cats = ["zqx a", "zqx b", "zqx c", "zqx d", "zqx e", "zqx f"]
    about = {"zqx a": "a server (physical or virtual), known by its name",
             "zqx b": "an inventory group of the playbooks: servers sharing a role",
             "zqx c": "a squad of engineers who operate products",
             "zqx d": "a relational database engine where the products keep their rows",
             "zqx e": "software deployed on each server: agents, proxies, runtimes",
             "zqx f": "a stage of a release: production or acceptance"}
    conf = {"categories.custom": cats, "categories.about": about, "categories.inside": {"zqx a": "zqx b"}}
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda key: conf[key] if key in conf else real(key))
    naming._SOFT.clear()
    assert _category("host", "web-01") == "zqx a"
    assert _category("group", "web") == "zqx b"
    assert _category("team", "Ops crew") == "zqx c"
    assert _category("environment", "staging") == "zqx f"
    assert naming.software_category() == "zqx e"
    naming._SOFT.clear()


def test_the_map_readers_know_a_category_of_servers_by_its_description(ctx, monkeypatch):
    from supagent.knowledge.catkind import serverish
    from supagent.knowledge.datalinks import kind_of

    _person(monkeypatch, {"box": "a server they reach by name (physical or virtual)", "zqx kit": "a lane of a road"})
    assert kind_of("zqx kit", "box") == ("runs_on", "zqx kit", "box")      # what runs on the boxes
    assert kind_of("box", "zqx kit") == ("runs_on", "zqx kit", "box")
    assert serverish("host") and not serverish("zqx kit")
