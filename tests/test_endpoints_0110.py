"""(0.11.0) Every page and API route of supagent answered: each GET of the three views (the chat, the Data
dictionary, the settings) for an admin without a server error, the pages as HTML; each route that writes refused to a
person without the AI role; each write route given an empty or wrong body answered with an error, never a server
error (500). Routes that start long work (a learning run, a backup, an answer by the LLM) are left to their own tests."""
from __future__ import annotations

import json
import re

import pytest

from conftest import login

# routes that start work in the background or call an LLM / a remote service: their own tests cover them
STARTS_WORK = re.compile(r"/(learn|classify|backups|restore|test_llm|test-llm|test_source|test-source|refresh|ask|"
                         r"messages?|answer|retry|context/build|build|stop|helpful|remember|grafana|osd|dash|mcp|"
                         r"upload|export|chart|excel|email|run|reread|read_now|crawl|import|index|reindex|sync)\b")


def _routes(app):
    out = []
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/supagent/"):
            continue
        for method in sorted((rule.methods or set()) - {"HEAD", "OPTIONS"}):
            out.append((method, rule.rule, sorted(rule.arguments)))
    return out


def _path(rule: str) -> str:
    """A route with its arguments filled: an id that exists nowhere, a name that is no file."""
    path = re.sub(r"<int:[^>]+>", "999999", rule)
    path = re.sub(r"<(?:string:|path:)?([^>]+)>", lambda m: "nothing-here" if "fmt" not in m.group(1) else "pdf", path)
    return path


def test_the_routes_are_this_version_s(app):
    rules = {rule for _m, rule, _a in _routes(app)}
    assert len(rules) >= 95                                    # every view's routes (an older copy had 88)
    for rule in ("/supagent/admin/api/hosts", "/supagent/admin/api/backups/upload", "/supagent/admin/api/lint/dismiss",
                 "/supagent/dictionary/api/recipes/<int:rid>", "/supagent/api/conversations"):
        assert rule in rules, rule


def test_every_get_route_answers_an_admin(app):
    bad = []
    with app.app_context(), app.test_client() as c:
        login(c, "admin")
        for method, rule, args in _routes(app):
            if method != "GET" or STARTS_WORK.search(rule):
                continue
            r = c.get(_path(rule))
            if r.status_code >= 500:
                bad.append((rule, r.status_code, r.get_data(as_text=True)[:200]))
            elif "/api/" in rule and r.status_code == 200 and r.mimetype == "application/json":
                json.loads(r.get_data(as_text=True))
    assert not bad, bad


@pytest.mark.parametrize("page", ["/supagent/", "/supagent/dictionary/", "/supagent/admin/", "/supagent/admin/usage"])
def test_the_pages_are_drawn(app, page):
    with app.app_context(), app.test_client() as c:
        login(c, "admin")
        r = c.get(page, follow_redirects=True)
        assert r.status_code == 200 and "text/html" in r.content_type
        html = r.get_data(as_text=True)
        assert "<script" in html and "supagent" in html


def test_write_routes_are_refused_without_the_role(app):
    let_in = []
    with app.app_context(), app.test_client() as c:
        login(c, "nobody")                                     # a Superset user without the AI role
        for method, rule, _args in _routes(app):
            if method == "GET":
                continue
            r = c.open(_path(rule), method=method, json={})
            if r.status_code < 300 or r.status_code >= 500:
                let_in.append((method, rule, r.status_code))
    assert not let_in, let_in


def test_write_routes_refuse_a_wrong_body_without_a_server_error(app):
    bad = []
    with app.app_context(), app.test_client() as c:
        login(c, "admin")
        for method, rule, _args in _routes(app):
            if method == "GET" or STARTS_WORK.search(rule):
                continue
            for body in ({}, {"id": "x", "text": None, "parts": "x", "status": 3}):
                r = c.open(_path(rule), method=method, json=body)
                if r.status_code >= 500:
                    bad.append((method, rule, json.dumps(body), r.status_code, r.get_data(as_text=True)[:160]))
    assert not bad, bad
