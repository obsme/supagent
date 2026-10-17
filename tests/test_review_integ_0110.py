"""(0.11.0) The review of the integrations and the tools off the question path: exports, the command line,
Grafana, OpenSearch Dashboards, the dashboards list, the host statistics, the models and the settings."""

from __future__ import annotations

import signal
from contextlib import contextmanager

import pytest


@contextmanager
def _within(seconds: int):
    """Fails the test instead of hanging it when the code under test loops for ever."""
    def stop(*_a):
        raise TimeoutError(f"still running after {seconds} s")

    old = signal.signal(signal.SIGALRM, stop)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# --------------------------------------------------------------------------------------------- #
# export: a table whose header is taller than a page
# --------------------------------------------------------------------------------------------- #
def test_pdf_table_header_taller_than_a_page_ends():
    from supagent import export as X

    md = "| " + "word " * 1500 + "|\n|---|\n| a |\n| b |\n"
    doc = X.Document("Context", [X.Section("Technical", [X.Page("Wide", md)])])
    with _within(20):
        pdf = X.to_pdf(doc)
    assert pdf.startswith(b"%PDF") and pdf.rstrip().endswith(b"%%EOF")
    assert pdf.count(b"/Type /Page ") < 20                # the header once, the rows under it: a few pages


# --------------------------------------------------------------------------------------------- #
# settings: what is stored is what was meant
# --------------------------------------------------------------------------------------------- #
def test_a_yes_no_setting_refuses_a_word_that_says_neither(ctx):
    from supagent import settings

    with pytest.raises(ValueError):
        settings.set_value("llm.verify_tls", "ture")          # a typo was stored as false: the TLS check off
    assert settings.get("llm.verify_tls") is True
    try:
        for word, want in (("false", False), ("off", False), ("YES", True), (" on ", True), (False, False),
                           (1, True), ("0", False)):
            settings.set_value("llm.verify_tls", word)
            assert settings.get("llm.verify_tls") is want, word
    finally:
        settings.set_value("llm.verify_tls", None)


def test_a_json_setting_keeps_the_shape_of_its_default(ctx):
    from supagent import settings

    for key, bad in (("llm.extra_headers", "[1]"), ("grafana.rule_labels", '"x"'), ("mcp.servers", "{}")):
        with pytest.raises(ValueError):
            settings.set_value(key, bad)
        assert settings.get(key) == settings.BY_KEY[key].default
    try:
        settings.set_value("llm.extra_headers", '{"X-Team": "a"}')
        assert settings.get("llm.extra_headers") == {"X-Team": "a"}
    finally:
        settings.set_value("llm.extra_headers", None)


# --------------------------------------------------------------------------------------------- #
# the command line: a wrong word is said, never a traceback
# --------------------------------------------------------------------------------------------- #
def test_settings_unset_of_an_unknown_key_is_said(app):
    from click.testing import CliRunner

    from supagent import cli

    with app.app_context():
        res = CliRunner().invoke(cli.settings_cmd, ["--unset", "no.such.key"], obj=None)
    assert isinstance(res.exception, SystemExit) and "unknown setting" in res.output, (res.exception, res.output)


def test_restore_of_a_file_that_is_no_backup_is_said(app, tmp_path, monkeypatch):
    import zipfile

    from click.testing import CliRunner

    from supagent import cli
    from supagent.knowledge import backup as B

    monkeypatch.setattr(B, "directory", lambda: str(tmp_path))
    (tmp_path / "supagent-knowledge-20261017-120000.zip").write_bytes(b"half copied")
    with zipfile.ZipFile(tmp_path / "supagent-knowledge-20261017-120001.zip", "w") as z:
        z.writestr("other.json", "{}")
    for name in ("supagent-knowledge-20261017-120000.zip", "supagent-knowledge-20261017-120001.zip"):
        with app.app_context():
            res = CliRunner().invoke(cli.restore, [name], obj=None)
        assert isinstance(res.exception, SystemExit) and "is not a backup of the knowledge" in res.output, \
            (res.exception, res.output)
    with app.app_context():                                   # a name of none: said as before
        res = CliRunner().invoke(cli.restore, ["supagent-knowledge-20261017-120002.zip"], obj=None)
    assert isinstance(res.exception, SystemExit) and "no backup" in res.output, res.output


# --------------------------------------------------------------------------------------------- #
# OpenSearch Dashboards: the sign-in's secret is never said; a saved object never loops
# --------------------------------------------------------------------------------------------- #
def _osd(monkeypatch, **conf):
    from supagent import osd

    given = {"osd.url": "https://osd.invalid", "osd.timeout": 5, **conf}
    monkeypatch.setattr(osd, "_setting", lambda k, d=None: given.get(k, d))
    return osd


def test_an_osd_token_ending_with_a_line_break_is_sent_without_it(monkeypatch):
    import requests

    osd = _osd(monkeypatch, **{"osd.auth": "bearer", "osd.secret": "tok-SECRET\n"})   # a token read from a file
    sent: list[dict] = []

    def no_network(self, request, **kw):
        sent.append(dict(request.headers))
        raise requests.ConnectionError("no network in the tests")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", no_network)
    with pytest.raises(osd.OSDError):
        osd._get("/api/saved_objects/_find", [("type", "dashboard")])
    assert sent and sent[0]["Authorization"] == "Bearer tok-SECRET"


def test_an_osd_header_refused_is_said_without_its_value(monkeypatch):
    import requests

    osd = _osd(monkeypatch, **{"osd.auth": "header", "osd.header": "X-Token", "osd.secret": "tok\nSECRET"})
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", lambda *a, **k: pytest.fail("sent"))
    with pytest.raises(osd.OSDError) as got:                 # requests refuses it: its text has the value
        osd._get("/api/saved_objects/_find", [])
    assert "SECRET" not in str(got.value)

    def refused(*a, **k):                                     # http.client's own check, a plain ValueError
        raise ValueError("Invalid header value b'Bearer tok-SECRET\\n'")

    monkeypatch.setattr(requests, "get", refused)
    with pytest.raises(osd.OSDError) as got:
        osd._get("/api/saved_objects/_find", [])
    assert "SECRET" not in str(got.value)


def test_an_osd_aggregation_of_itself_is_described_without_a_loop():
    from supagent import osd

    itself = [{"id": "1", "type": "derivative", "schema": "metric", "params": {"metricAgg": "1"}}]
    each_other = [{"id": "1", "type": "derivative", "schema": "metric", "params": {"metricAgg": "2"}},
                  {"id": "2", "type": "cumulative_sum", "schema": "metric", "params": {"metricAgg": "1"}}]
    for aggs in (itself, each_other):
        said, _fields = osd._aggs(aggs)
        assert said and said[0].startswith(("the change of", "the running sum of")), said


# --------------------------------------------------------------------------------------------- #
# the list of Documents and sites: an item of a long ref is found again
# --------------------------------------------------------------------------------------------- #
def test_a_listed_item_of_a_long_ref_is_found_again(ctx):
    from superset.extensions import db

    from supagent import dashlist
    from supagent.models import DashItem

    item = {"kind": "visualization", "ref": "zqx-" + "v" * 300, "title": "Long one", "parents": []}
    try:
        assert dashlist.record("osd", [item], listed=False)["new"] == 1
        again = dashlist.record("osd", [dict(item)], listed=False)      # was: a second row, the unique key broken
        assert again["new"] == 0 and again["updated"] == 1
    finally:
        db.session.rollback()
        db.session.query(DashItem).filter(DashItem.source == "osd", DashItem.ref.like("zqx-%")).delete(
            synchronize_session=False)
        db.session.commit()
