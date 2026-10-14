"""(0.10.9.1) What a part named after known software is: the software a host runs (an application server, a runner
of workers, a file or mail daemon, an antivirus) in the person's category for their hosts' software; a key-value
store with their datastores; a coordination or load balancing service with their platform services; a version
number or "cloud" after a database's name; the roles that only install a client, mount a share or set a path."""
from __future__ import annotations

import pytest

CATS = ["application", "datastore", "message broker", "platform service", "external service", "host software",
        "environment", "server group", "server"]


@pytest.mark.parametrize("name,expected", [
    ("passenger", "host software"), ("sidekiq_worker", "host software"), ("sneakers_worker", "host software"),
    ("samba", "host software"), ("clamav", "host software"), ("mailcatcher", "host software"),
    ("subversion", "host software"), ("gunicorn", "host software"), ("tomcat9", "host software"),
    ("redis", "datastore"), ("app_redis", "datastore"), ("solr9cloud", "datastore"), ("postgresql18", "datastore"),
    ("search-solr9-prod", "datastore"), ("zookeeper", "platform service"), ("nginxplus", "platform service"),
    ("rabbitmq", "message broker"), ("passenger-info-service", "application"), ("apache-kafka", "message broker")])
def test_known_software_goes_to_the_person_s_category_for_it(name, expected):
    from supagent.knowledge.naming import filed

    assert filed("application", name, None, CATS)[0] == expected


def test_a_key_value_store_prefers_a_category_of_caches():
    from supagent.knowledge.naming import filed

    assert filed("application", "redis", None, ["application", "database", "cache"])[0] == "cache"
    assert filed("application", "redis", None, ["application", "component"])[0] == "component"   # as before


def test_the_hosts_software_without_a_category_of_its_own():
    from supagent.knowledge.naming import filed

    assert filed("application", "passenger", None, ["application", "platform service"])[0] == "platform service"
    assert filed("application", "passenger", None, ["application", "component"])[0] == "component"


def test_a_name_that_only_starts_with_a_software_s_name_is_no_software():
    from supagent.knowledge.naming import kind_of

    assert kind_of("passenger-portal") is None and kind_of("samba-gateway-api") is None
    assert kind_of("sidekiq") == "hosted" and kind_of("puma_server") == "hosted"


@pytest.mark.parametrize("role", ["psql-client", "mysql_client", "hr_share", "extra_path", "rust", "cargo"])
def test_roles_that_install_a_client_mount_a_share_or_set_a_path_are_no_part(role):
    from supagent.knowledge.projects import Role

    assert Role(role, None).part is None


@pytest.mark.parametrize("role", ["orders_api", "billing-worker", "ledger"])
def test_other_roles_still_name_their_part(role):
    from supagent.knowledge.projects import Role

    assert Role(role, None).part is not None


def test_a_play_for_each_environment_runs_on_every_environment_s_group():
    from supagent.knowledge.projects import Inventory, env_places

    inv = Inventory("inventory/all/hosts")
    for g in ("shop_production", "shop_staging", "shop_qa", "shop_cache_cluster", "billing_production"):
        inv.group(g, 1)
    got = env_places("shop_{{ runtime_env | default('staging') }}", [{}], inv, [("group", "shop_staging")])
    assert set(got) == {("group", "shop_production"), ("group", "shop_qa")}       # never shop_cache_cluster
    assert env_places("shop_{{ runtime_env | default('staging') }}", [{"runtime_env": "qa"}], inv, []) == []
    assert env_places("shop_production", [{}], inv, []) == []
