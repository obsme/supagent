"""(0.11.0) Browser tests of every page, tab and button of supagent, against a running Superset with supagent:

    SUPAGENT_UI_URL=https://superset.example.com SUPAGENT_UI_PASSWORD=... [SUPAGENT_UI_USER=admin] \
        python -m pytest tests/ui -q

Skipped without those settings or without Playwright (pip install playwright; playwright install chromium). They
open every page, every tab and sub-tab, every panel and every "i" explanation, check what each shows, and fail on any
error of the page's scripts. They change nothing, except with SUPAGENT_UI_WRITE=1: then a team memory, a catalog
entry and a note are made through the pages and removed again (use a test instance). No question is asked to the
LLM unless SUPAGENT_UI_ASK=1 (one short question, its answer drawn)."""
from __future__ import annotations

import os
import re
import time

import pytest

URL = os.environ.get("SUPAGENT_UI_URL", "").rstrip("/")
USER = os.environ.get("SUPAGENT_UI_USER", "admin")
PASSWORD = os.environ.get("SUPAGENT_UI_PASSWORD", "")
WRITE = os.environ.get("SUPAGENT_UI_WRITE") == "1"
ASK = os.environ.get("SUPAGENT_UI_ASK") == "1"
WAIT = 60_000

pytestmark = pytest.mark.skipif(not (URL and PASSWORD), reason="SUPAGENT_UI_URL and SUPAGENT_UI_PASSWORD not set")


def _session():
    import requests

    s = requests.Session()
    s.headers["Referer"] = URL
    r = s.get(f"{URL}/login/", timeout=60)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r.text) or re.search(
        r'id="csrf_token"[^>]*value="([^"]+)"', r.text)
    s.post(f"{URL}/login/", data={"username": USER, "password": PASSWORD, "csrf_token": m.group(1) if m else ""},
           allow_redirects=True, timeout=60)
    page = s.get(f"{URL}/supagent/", timeout=60)
    assert page.status_code == 200, f"sign-in as {USER}: HTTP {page.status_code}"
    return s


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("playwright.sync_api")
    s = _session()
    with pw.sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1500, "height": 1000})
        ctx.add_cookies([{"name": c.name, "value": c.value, "url": URL} for c in s.cookies])
        yield ctx
        b.close()


@pytest.fixture()
def page(browser):
    pg = browser.new_page()
    pg.errors = []                                          # the page's script errors: a test fails on any
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: pg.errors.append(m.text) if m.type == "error" and "favicon" not in m.text
          and "Failed to load resource" not in m.text else None)
    yield pg
    pg.close()


def _open(pg, path: str) -> None:
    pg.goto(f"{URL}{path}", wait_until="domcontentloaded", timeout=WAIT)
    pg.wait_for_load_state("networkidle", timeout=WAIT)


def _no_errors(pg) -> None:
    assert not pg.errors, pg.errors[:5]


def _explanations(pg) -> int:
    """Every "i" button of the page shows its explanation (a card with the text of its hidden source) and Escape
    closes it."""
    n = 0
    for b in pg.locator("button.info[aria-controls]:visible").all():
        b.click()
        card = pg.locator(".pop-info").last
        card.wait_for(state="visible", timeout=10_000)
        assert card.inner_text().strip(), b.get_attribute("aria-controls")
        pg.keyboard.press("Escape")
        card.wait_for(state="detached", timeout=10_000)
        n += 1
    return n


# ------------------------------------------------------------------------------------------------ the chat
def test_the_chat_page_and_its_panels(page):
    _open(page, "/supagent/")
    for sel in ("#question", "#send", "#new-chat", "#toggle-convs", "#open-memory", "#open-notes", "#messages"):
        assert page.locator(sel).count() == 1, sel
    page.click("#open-memory")
    page.wait_for_selector("#memory-drawer:not([hidden])", timeout=WAIT)
    assert page.locator("#memory-text").is_visible() and page.locator("#memory-save").is_visible()
    page.click("#memory-close")
    assert page.locator("#memory-drawer").is_hidden()
    page.click("#open-notes")
    page.wait_for_selector("#notes-drawer:not([hidden])", timeout=WAIT)
    page.click("#notes-close")
    assert page.locator("#notes-drawer").is_hidden()
    if page.locator("#toggle-convs").is_visible():          # (a narrow window: the conversations folded)
        page.click("#toggle-convs")
        page.click("#toggle-convs")
    page.fill("#conv-search", "zzz-nothing-matches")
    page.wait_for_timeout(800)
    page.fill("#conv-search", "")
    page.click("#new-chat")
    assert page.locator("#question").is_editable()
    _explanations(page)
    _no_errors(page)


@pytest.mark.skipif(not ASK, reason="SUPAGENT_UI_ASK not set: no question asked to the LLM")
def test_a_question_is_answered_on_the_page(page):
    _open(page, "/supagent/")
    page.click("#new-chat")
    before = page.locator(".msg.assistant").count()
    page.fill("#question", "Which databases can you query? One line.")
    page.click("#send")
    page.wait_for_function("document.querySelector('#send').classList.contains('stop')", timeout=WAIT)   # answering
    page.wait_for_function("!document.querySelector('#send').classList.contains('stop')", timeout=600_000)  # written
    answers = page.locator(".msg.assistant")
    assert answers.count() > before and len(answers.last.inner_text().strip()) > 10, answers.last.inner_text()
    assert page.locator(".msg.assistant.error").count() == 0
    _no_errors(page)


# ------------------------------------------------------------------------------------------------ the dictionary
TABS = ("review", "knowledge", "data", "search")
SUBTABS = ("catalog", "memory", "docs", "notes", "context", "learned", "categories", "map", "browse", "relations",
           "changes")


def test_every_tab_of_the_data_dictionary(page):
    _open(page, "/supagent/dictionary/")
    for tab in TABS:
        btn = page.locator(f'[role="tab"][data-tab="{tab}"]')
        if not btn.count() or not btn.first.is_visible():
            continue                                         # (To review: admins only)
        btn.first.click()
        page.wait_for_selector(f"#tab-{tab}:not([hidden])", timeout=WAIT)
    _no_errors(page)


@pytest.mark.parametrize("sub", SUBTABS)
def test_every_sub_tab_draws(page, sub):
    _open(page, f"/supagent/dictionary/#{sub}")
    page.wait_for_selector(f"#sub-{sub}:not([hidden])", timeout=WAIT)
    page.wait_for_timeout(1500)                              # its lists read
    _explanations(page)
    _no_errors(page)


def test_the_catalog_entry_panel_and_the_import_panel(page):
    _open(page, "/supagent/dictionary/#catalog")
    page.wait_for_selector("#sub-catalog:not([hidden])", timeout=WAIT)
    page.click("#cat-new")
    page.wait_for_selector("#entry-drawer:not([hidden])", timeout=WAIT)
    for sel in ("#e-title", "#e-class", "#e-content", "#e-save"):
        assert page.locator(sel).is_visible(), sel
    page.click("#entry-close")
    assert page.locator("#entry-drawer").is_hidden()
    page.click("#cat-import")
    page.wait_for_selector("#import-go", state="visible", timeout=WAIT)
    page.click("#import-close")
    _no_errors(page)


def test_a_context_page_opens_and_draws_its_relations(page):
    _open(page, "/supagent/dictionary/#context")
    page.wait_for_selector("#sub-context:not([hidden])", timeout=WAIT)
    links = page.locator("#ctx-toc a, #ctx-toc button")
    if not links.count():
        pytest.skip("no Context page on this instance")
    links.first.click()
    page.wait_for_selector("#ctx-article .context-page", timeout=WAIT)
    blocks = [c for c in page.locator("#ctx-article pre code").all() if c.text_content().startswith("diagram: relations")]
    assert all(c.evaluate("c => !!c.closest('details')") for c in blocks)       # drawn, its text under a fold
    if blocks:
        assert page.locator("#ctx-article .relations-box svg").count() >= len(blocks)
    _no_errors(page)


def test_the_search_tab_answers(page):
    _open(page, "/supagent/dictionary/#search")
    page.wait_for_selector("#tab-search:not([hidden])", timeout=WAIT)
    page.fill("#k-q", "error")
    page.locator("#k-form").evaluate("f => f.requestSubmit ? f.requestSubmit() : f.submit()")
    page.wait_for_function("document.querySelector('#k-results') && document.querySelector('#k-results').textContent.length > 0",
                           timeout=WAIT)
    _no_errors(page)


def test_the_system_map_draws_and_fits(page):
    _open(page, "/supagent/dictionary/#map")
    page.wait_for_selector("#sub-map:not([hidden])", timeout=WAIT)
    page.wait_for_timeout(2000)
    if page.locator("#map-fit").is_visible():
        page.click("#map-fit")
    _no_errors(page)


# ------------------------------------------------------------------------------------------------ the settings
def test_the_settings_page_every_section(page):
    _open(page, "/supagent/admin/")
    for sec in ("#sec-llm", "#sec-learn", "#sec-backup", "#sec-agent", "#sec-budget", "#sec-search"):
        assert page.locator(sec).count() == 1, sec
    page.wait_for_selector(".fields[data-group] .field, .fields[data-group] label, .fields[data-group] input",
                           timeout=WAIT)
    assert page.locator(".fields[data-group] input, .fields[data-group] select").count() > 20
    _explanations(page)
    _no_errors(page)


def test_the_restore_panel_opens_and_says_what_is_missing(page):
    _open(page, "/supagent/admin/")
    page.click("#restore-open")
    page.wait_for_selector("#restore-panel:not([hidden])", timeout=WAIT)
    assert page.locator("#restore-name option").count() >= 1
    page.click("#restore-upload")                            # no file chosen: said, nothing sent
    page.wait_for_function("document.querySelector('#restore-result').textContent.indexOf('choose') >= 0", timeout=WAIT)
    page.click("#restore-open")
    assert page.locator("#restore-panel").is_hidden()
    _no_errors(page)


def test_the_backups_and_runs_lists(page):
    _open(page, "/supagent/admin/")
    page.wait_for_selector("#backups tbody tr", timeout=WAIT)
    page.wait_for_selector("#runs tbody tr, #runs tr", timeout=WAIT)
    assert page.locator("#backup-dir").text_content().strip()
    _no_errors(page)


# ------------------------------------------------------------------------------------------------ the usage page
def test_the_usage_page(page):
    _open(page, "/supagent/admin/usage")
    page.wait_for_function("document.querySelectorAll('#tiles .tile').length >= 6", timeout=WAIT)
    assert page.locator("#answer-tiles .tile").count() >= 4
    page.wait_for_selector("table#hosts thead th", timeout=WAIT)
    heads = " ".join(page.locator("table#hosts thead th").all_text_contents())
    assert "Superset's disk" in heads
    page.select_option("#preset", index=1)
    page.wait_for_timeout(1500)
    for b in page.locator("[data-measure]").all():
        b.click()
    _explanations(page)
    _no_errors(page)


# ------------------------------------------------------------------------------------------------ the chat panel
def test_the_chat_panel_on_superset_pages(page):
    _open(page, "/superset/welcome/")
    page.wait_for_function("!!window.supagentDock", timeout=WAIT)
    page.evaluate("window.supagentDock.show()")
    page.wait_for_selector("iframe[src*='/supagent/']", timeout=WAIT)
    _no_errors(page)


# ------------------------------------------------------------------------------------------------ writing
@pytest.mark.skipif(not WRITE, reason="SUPAGENT_UI_WRITE not set: nothing written")
def test_a_team_memory_made_and_removed(page):
    text = f"UI test memory {int(time.time())}: durations in minutes"
    _open(page, "/supagent/dictionary/#memory")
    page.wait_for_selector("#sub-memory:not([hidden])", timeout=WAIT)
    page.fill("#mem-text", text)
    page.click("#mem-add")
    row = page.locator("#team-memory tr, #team-memory li", has_text=text).first
    row.wait_for(timeout=WAIT)
    row.locator("button", has_text=re.compile("Delete|Remove|Disable")).first.click()
    sure = page.locator(".sure button, .pop button", has_text=re.compile("Delete|Remove|Yes|Disable"))
    if sure.count():
        sure.first.click()
    page.wait_for_timeout(1500)
    _no_errors(page)


@pytest.mark.skipif(not WRITE, reason="SUPAGENT_UI_WRITE not set: nothing written")
def test_a_catalog_entry_made_and_deleted(page):
    title = f"UI test entry {int(time.time())}"
    _open(page, "/supagent/dictionary/#catalog")
    page.wait_for_selector("#sub-catalog:not([hidden])", timeout=WAIT)
    page.click("#cat-new")
    page.fill("#e-title", title)
    page.select_option("#e-class", "glossary")
    page.fill("#e-content", "UI test word: a word used by the UI test only.")   # (a glossary: term: meaning)
    page.click("#e-save")
    page.wait_for_function("/good|bad/.test((document.querySelector('#e-result') || {}).className || '')",
                           timeout=WAIT)
    assert page.locator("#e-result.good").count() == 1, page.locator("#e-result").text_content()
    page.click("#e-delete")                                  # deleted again, after its confirmation
    page.locator(".pop button", has_text=re.compile("^(Delete|Yes)$")).first.click()
    page.wait_for_selector("#entry-drawer", state="hidden", timeout=WAIT)
    _no_errors(page)
