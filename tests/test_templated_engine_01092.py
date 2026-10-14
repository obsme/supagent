"""(0.10.9.2) An application's configuration that names its store or broker by an address whose host is a template
("postgresql://app@{{ db_host }}/app", "redis://:pw@%(REDIS_HOST)s/1", "http://%(solr)s:{{ port }}/solr/core") uses
the part of that engine the documents know; a name is never made from a scheme alone."""
from __future__ import annotations


def _facts(path, text, names):
    from supagent.knowledge.understand import discover, facts_of

    unit = {"ukey": path, "path": path, "kind": "file", "title": path.rsplit("/", 1)[-1], "text": text, "meta": {}}
    unit["found"] = discover(unit)
    return {(f["subject"], f["verb"], f["obj"]) for f in facts_of(unit, "ledger", names, {"ledger": "ledger"})}


def _names(*parts):
    from supagent.knowledge.understand import Names

    n = Names()
    for p in parts:
        n.add_part(p)
    return n


INI = ("[app:main]\n"
       "sqlalchemy.url = postgresql://%(db_user)s:%(db_pass)s@%(db_server)s/%(db_name)s\n"
       "BROKER_HOST = redis://:{{ ledger_redis_password }}@%(REDIS_HOST)s/1\n"
       "solr_url = http://%(solr_server)s:{{ ledger_solr_port }}/solr/{{ core }}\n"
       "events = amqp://ledger:{{ pw }}@{{ mq_host }}:5672/\n")


def test_a_templated_address_links_the_application_to_the_engine_the_documents_know(ctx):
    got = _facts("roles/ledger/templates/production.ini.j2", INI, _names("PostgreSQL", "Redis", "Solr", "RabbitMQ"))
    objs = {o for s, v, o in got if s == "ledger"}
    assert {"PostgreSQL", "Redis", "Solr", "RabbitMQ"} <= objs


def test_no_engine_part_known_no_link_and_no_new_name(ctx):
    got = _facts("roles/ledger/templates/production.ini.j2", INI, _names("Billing"))
    assert not any(o.lower() in ("postgresql", "postgres", "redis", "solr", "rabbitmq") for _s, _v, o in got)


def test_a_commented_or_documented_templated_address_is_no_link(ctx):
    text = "# sqlalchemy.url = postgresql://user:pass@{{ db_host }}/app\n"
    got = _facts("roles/ledger/templates/production.ini.j2", text, _names("PostgreSQL"))
    assert not any(o == "PostgreSQL" for _s, _v, o in got)
