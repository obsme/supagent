"""(0.10.10) Parts filed in the person's own categories: the software installed on the hosts in their software
category, the system's applications in their one category of services (a leaf, never an external one)."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("name,expected", [
    ("apache", "host software"), ("tomcat7", "host software"), ("nginx", "host software"),
    ("miniconda", "host software"), ("telegraf", "host software"), ("valkey", "datastore"),
    ("rabbitmq", "message broker"), ("billing-api", "application")])
def test_software_goes_to_the_person_s_software_category(name, expected):
    from supagent.knowledge.naming import filed

    cats = ["application", "component", "datastore", "host software", "message broker", "platform service"]
    assert filed("application", name, None, cats)[0] == expected


def test_without_a_software_category_nothing_changes():
    from supagent.knowledge.naming import filed

    cats = ["application", "component", "datastore", "platform service"]
    assert filed("application", "nginx", None, cats)[0] == "platform service"   # its infrastructure category
    assert filed("application", "miniconda", None, cats)[0] == "application"   # a runtime: as before


def test_the_service_category_is_named_by_its_head_noun_and_is_the_system_s_own():
    from supagent.knowledge.proposals import NOT_OWN_SERVICE, SERVICE_CATEGORY

    assert SERVICE_CATEGORY.search("platform service") and SERVICE_CATEGORY.search("business system")
    assert not SERVICE_CATEGORY.search("service area") and not SERVICE_CATEGORY.search("microservice")
    assert NOT_OWN_SERVICE.search("external service") and NOT_OWN_SERVICE.search("third-party service")
    assert not NOT_OWN_SERVICE.search("platform service")
