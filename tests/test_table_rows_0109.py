"""(0.10.9) A table of a page keeps one line per row, its cells apart, whatever is inside its cells: the Confluence
editor wraps a cell's text in a paragraph (<td><p>web-01</p></td>), pages written by hand or exported are often laid
out on several lines, a cell holds a list or line breaks. Every row was read one cell per line: no table of hosts,
of VIPs, of services or of owners was read on such a page (only a compact table, or a Markdown table of a file)."""

from __future__ import annotations


def _text(html):
    from supagent.knowledge.docs import storage_to_text

    return storage_to_text(html)


def test_a_row_is_one_line_whatever_its_cells_hold(ctx):
    rows = "A | B\nx | y"
    assert _text("<table><tbody><tr><th>A</th><th>B</th></tr><tr><td>x</td><td>y</td></tr></tbody></table>") == rows
    assert _text("<table><tbody><tr><th><p><strong>A</strong></p></th><th><p>B</p></th></tr>"
                 "<tr><td><p>x</p></td><td><p>y</p></td></tr></tbody></table>") == rows        # the editor's cells
    assert _text('<table data-layout="default"><colgroup><col style="width: 226.0px;" /><col /></colgroup><tbody>'
                 "<tr><th><p>A</p></th><th><p>B</p></th></tr><tr><td><p>x</p></td><td><p>y</p></td></tr></tbody>"
                 "</table>") == rows
    assert _text("<table>\n  <tr>\n    <th>A</th>\n    <th>B</th>\n  </tr>\n  <tr>\n    <td>x</td>\n"
                 "    <td>y</td>\n  </tr>\n</table>") == rows                                     # laid out on lines


def test_a_cells_values_stay_apart_and_the_text_around_unchanged(ctx):
    t = _text("<p>Before.</p><table><tbody><tr><th>Host</th><th>Services</th></tr><tr><td>app-vm-01</td>"
              "<td><ul><li>shop</li><li>cart</li></ul></td></tr><tr><td><p>app-vm-02</p></td>"
              "<td><p>shop</p><p>search</p></td></tr><tr><td>app-vm-03</td><td>shop<br/>cart</td></tr></tbody>"
              "</table><h2>After</h2><ul><li>one</li><li>two</li></ul>")
    assert t == ("Before.\nHost | Services\napp-vm-01 | shop, cart\napp-vm-02 | shop, search\napp-vm-03 | shop, cart\n"
                 "## After\n- one\n- two")


def test_a_table_of_hosts_in_the_editors_shape_is_read(ctx):
    from test_prose_010 import facts

    text = _text("<table><tbody><tr><th><p>Host</p></th><th><p>Services</p></th><th><p>PDUs</p></th></tr>"
                 "<tr><td><p>app-vm-01</p></td><td><p>reverse_proxy</p></td><td><p>pdu-a-1, pdu-b-1</p></td></tr>"
                 "</tbody></table>")
    t = facts(text, parts=("reverse_proxy",))
    assert {("reverse_proxy", "runs_on", "app-vm-01"), ("app-vm-01", "powered_by", "pdu-a-1"),
            ("app-vm-01", "powered_by", "pdu-b-1")} <= t


def test_a_placeholder_in_a_cell_is_no_value(ctx):
    from test_prose_010 import facts

    text = ("Service | Runs on | Calls | Owner\nzqshop | app-vm-11 | None | platform team\n"
            "zqcart | app-vm-12 | N/A, zqshop | TBD\nzqsearch | - | - | -\n")
    t = facts(text, parts=("zqshop", "zqcart", "zqsearch"))
    assert ("zqcart", "calls", "zqshop") in t and ("zqshop", "runs_on", "app-vm-11") in t
    assert not any(o.lower() in ("none", "n/a", "tbd", "-") for _s, _v, o in t)


def test_a_table_of_services_names_its_services(ctx):
    from test_prose_010 import facts

    text = ("Application | Purpose | Owning Team | Servers | Calls\n"
            "zqledger | the ledger | finance team | app-vm-21, app-vm-22 | zqrates, zqother\n"
            "Monitoring | the checks | ops team | mon-vm-01 | -\n"
            "zq-batch | nightly runs | data team | Kubernetes | -\n")
    t = facts(text, parts=("zqrates",))
    assert {("zqledger", "runs_on", "app-vm-21"), ("zqledger", "runs_on", "app-vm-22"),
            ("zqledger", "owned_by", "finance team"), ("zqledger", "calls", "zqrates")} <= t
    assert not any(s in ("Monitoring", "zq-batch") for s, _v, _o in t)      # a word; no server named
    assert ("zqledger", "calls", "zqother") not in t                          # a new part's calls: to known parts
    t = facts("Service | Port | Protocol\nzqssh | 22 | TCP\n")                # no column of servers: no part
    assert not t
