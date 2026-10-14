"""(0.10.9) The reading's rules change in a release; a deployment upgraded must read its documents again once, or the
new rules never apply to the pages it read before (0.10.7's and 0.10.8's rules did not, under the reader's version
"0.10.6", until the names it knew changed). The reader's version is the package's: an upgrade reads every unit again
once; a run with nothing changed reads none."""

from __future__ import annotations

from test_docs_readers import env  # noqa: F401  (the fixture)
from test_second_pass_0105 import _clean, _repo, _state

PAGE = {"README.md": "| Host | Services |\n|---|---|\n| zqhost-31 | zqsvc |\n",
        "docs/notes.md": "# Notes\n\nzqsvc calls zqother.\n"}


def test_the_readers_version_is_the_packages():
    import supagent
    from supagent.knowledge import understand as U

    assert U.READER == supagent.__version__


def test_an_upgrade_reads_every_unit_again_once(env, monkeypatch):  # noqa: F811
    from supagent.knowledge import understand as U

    before, d = _state(), _repo(PAGE, name="zqver")
    try:
        U.run(reason="test")
        again = U.run(reason="test")
        assert not again.get("analysed") and again.get("unchanged")            # nothing changed: nothing read
        monkeypatch.setattr(U, "READER", U.READER + ".next")                   # the next release's rules
        upgraded = U.run(reason="test")
        assert upgraded.get("analysed") == again.get("unchanged") and not upgraded.get("unchanged")
        assert not U.run(reason="test").get("analysed")                        # once
    finally:
        _clean(before, [d])
