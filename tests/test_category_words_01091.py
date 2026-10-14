"""(0.10.9.1) A deployment's category for what its users use may be named or described otherwise than "application"
(a website, a web application, a portal, a product); its category for the shared services may say "internal" or
"backend" services. A category for physical sites, a business line or the platform's shared services keeps its
own meaning."""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("cats,about,expected", [
    (["team", "portal", "database", "host group"], {}, "portal"),
    (["team", "web application", "database"], {}, "web application"),
    (["team", "products", "database"], {}, "products"),
    (["team", "site", "database"], {"site": "a website or public API the program runs for the public"}, "site"),
    (["team", "application", "platform service"], {"platform service": "a shared service the applications rely on"},
     "application"),
])
def test_the_category_for_what_users_use(cats, about, expected):
    from supagent.knowledge.placing import best_category

    assert best_category("application", cats, about) == expected


def test_a_site_that_is_a_place_or_a_line_of_products_attracts_no_application():
    from supagent.knowledge.placing import best_category

    assert best_category("application", ["team", "site", "database"], {"site": "a data center of the company"}) \
        is None
    assert best_category("application", ["team", "product line", "database"], {}) is None


@pytest.mark.parametrize("name", ["internal service", "backend services", "back-end service", "shared services",
                                  "platform service", "core services"])
def test_the_category_for_the_shared_services(name):
    from supagent.knowledge.naming import OWN

    assert OWN["infrastructure"].match(name)
