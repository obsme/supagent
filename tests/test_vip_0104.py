"""(0.10.4, the user's request of 8 October: "we can have in many cases a VIP url pointing to services in servers")
A VIP in the System map: an address whose name says vip (orders-vip.example.com, vip-orders, x.vip.example.com),
a VIP variable (orders_vip, keepalived's virtual_ipaddress, vip_fqdn), a VIP column of a table or a sentence that
names a VIP: the VIP routes to the services it fronts, the servers behind it are grouped under it, and a caller's
address on a VIP is a call to the service."""
from __future__ import annotations

from test_prose_010 import facts


def _code(path, text, owner, parts=(), hosts=()):
    from supagent.knowledge.understand import Names, discover, facts_of, norm

    n = Names()
    for p in parts:
        n.add_part(p)
    for h in hosts:
        n.hosts[norm(h)] = h
    u = {"ukey": path, "path": path, "kind": "file", "title": path, "text": text, "meta": {}}
    u["found"] = discover(u)
    return {(f["subject"], f["verb"], f["obj"]) for f in facts_of(u, owner, n, {})}


def test_an_address_on_a_vip_is_a_call_to_its_service_and_the_vip_routes_to_it(ctx):
    conf = "orders_url: https://orders-vip.example.com:8443/api\nbilling_url: http://vip-billing.corp.example.com/\n" \
           "stock_url: http://stock.vip.example.com/v1\nother_url: http://legacy-vip.example.com/\n"
    t = _code("conf/app.yml", conf, "shop", parts=("shop", "orders", "billing", "stock"))
    assert {("orders-vip.example.com", "routes_to", "orders"), ("shop", "calls", "orders"),
            ("vip-billing.corp.example.com", "routes_to", "billing"), ("stock.vip.example.com", "routes_to", "stock"),
            ("shop", "calls", "legacy-vip.example.com")} <= t
    assert not any(o in ("orders-vip", "vip-billing") for _s, _v, o in t)


def test_a_vip_variable_and_keepalived(ctx):
    t = _code("group_vars/lb.yml", "orders_vip: 10.0.0.10\nhaproxy_vip_fqdn: shop.example.com\n", None,
              parts=("orders", "haproxy"))
    assert {("10.0.0.10", "routes_to", "orders"), ("shop.example.com", "routes_to", "haproxy")} <= t
    ka = "vrrp_instance VI_1 {\n  state MASTER\n  virtual_ipaddress {\n    192.168.10.50\n  }\n}\n"
    # (0.10.5) keepalived holds the VIP: it is never behind it (no "routes_to keepalived")
    assert not any(v == "routes_to" and o == "keepalived" for _s, v, o in
                   _code("roles/lb/templates/keepalived.conf.j2", ka, "keepalived", parts=("keepalived",)))


def test_a_vip_table_and_a_vip_sentence(ctx):
    table = "VIP | Service | Servers\norders-vip.example.com | orders | app-01, app-02\n10.0.0.20 | billing | app-03\n"
    t = facts(table, parts=("orders", "billing"))
    assert {("orders-vip.example.com", "routes_to", "orders"), ("app-01", "in_group", "orders-vip.example.com"),
            ("app-02", "in_group", "orders-vip.example.com"), ("10.0.0.20", "routes_to", "billing"),
            ("app-03", "in_group", "10.0.0.20")} <= t
    t = facts("The VIP stock-vip.example.com points to the stock service on app-05 and app-06.", parts=("stock",))
    assert {("stock-vip.example.com", "routes_to", "stock"), ("app-05", "in_group", "stock-vip.example.com"),
            ("app-06", "in_group", "stock-vip.example.com")} <= t
    assert not facts("We do not have a VIP for the stock service any more.", parts=("stock",))


def test_a_vip_is_proposed_as_an_address_with_its_servers(ctx):
    from supagent.knowledge.proposals import _category, LINK_OF

    assert LINK_OF["routes_to"] == "calls"
    assert _category("vip", "orders-vip.example.com") == _category("host", "app-01")
