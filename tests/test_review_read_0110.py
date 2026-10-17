"""The review of the reading of documents and repositories (0.11.0): odd input read in time and right."""

from __future__ import annotations

import re
import time


def test_a_heading_with_a_long_run_of_spaces_is_read_at_once(ctx):
    """A comment line of a configuration file ("# key" + thousands of spaces + "value") is taken for a heading by the
    sections' reader: its pattern tried every split of the spaces (cubic: 2,000 spaces took about ten seconds)."""
    from supagent.knowledge.index import sections

    line = "# key" + " " * 3000 + "value x"
    t = time.time()
    got = sections(f"{line}\nbody\n")
    assert time.time() - t < 2
    assert got[0][0] == ["key" + " " * 3000 + "value x"]
    t = time.time()                                    # a run as long as a file can be: its attributes' pattern too
    got = sections("# key" + " " * 200_000 + "value {#an-id}\nbody\n")
    assert time.time() - t < 2
    assert got[0][0] == ["key" + " " * 200_000 + "value"]


def test_a_heading_text_as_the_pattern_took_it(ctx):
    from supagent.knowledge.index import sections

    before = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")     # the patterns before 0.11.0 (short lines only)
    attrs = re.compile(r"\s*\{[:#][^}]*\}\s*$")
    for line in ("## Title ##", "# C#", "### ###", "#   ", "# Title  #  ", "## a # b ##\t", "# t {#id}", "#\tTab",
                 "## Title ##\r", "# x#y #", "# #", "###### six ######", "# t {: .note}  ", "# a {#x} {#y}",
                 "# {#only}", "# t\t{:x} ##"):
        old = before.match(line)
        got = sections(line + "\ntext")
        if old is None:
            assert got[0][0] == [], line
        else:
            assert got[0][0] == [attrs.sub("", old.group(2)).strip()], line
