"""(0.10.11) The classes of the 0.10.10 gates' misses: a tool call written as text, sizes in decimal units no one
asked for, a time of day asked and not given, a question back whose question ends no line."""
import json

from supagent.agent import asks_back, decimal_unasked, question_last, time_unsaid
from supagent.llm import markup_read

TOOLS = [{"type": "function", "function": {"name": "describe_data", "parameters": {"type": "object", "properties": {
    "index": {"type": "string"}, "limit": {"type": "integer"}, "fields": {"type": "array"}}}}},
         {"type": "function", "function": {"name": "execute_sql", "parameters": {"type": "object", "properties": {
             "sql": {"type": "string"}, "database_id": {"type": "integer"}}}}}]


def _trace(*values):
    return [{"tool": "execute_sql", "status": "done", "result": json.dumps({"rows": [[v] for v in values]})}]


def test_markup_call_read_as_a_call():
    msg = {"role": "assistant", "content": "<tool_call>\n<function=describe_data>\n<parameter=index>\napp-jobs"
                                           "\n</parameter>\n<parameter=limit>\n20\n</parameter>\n</function>\n</tool_call>"}
    out = markup_read(msg, TOOLS)
    assert out["content"] == ""
    call = out["tool_calls"][0]["function"]
    assert call["name"] == "describe_data"
    assert json.loads(call["arguments"]) == {"index": "app-jobs", "limit": 20}   # typed by the schema


def test_markup_text_before_kept_and_json_form():
    msg = {"content": "Let me look.\n<tool_call>\n{\"name\": \"execute_sql\", \"arguments\": {\"sql\": \"SELECT 1\"}}\n"
                      "</tool_call>"}
    out = markup_read(msg, TOOLS)
    assert out["content"] == "Let me look."
    assert json.loads(out["tool_calls"][0]["function"]["arguments"]) == {"sql": "SELECT 1"}


def test_markup_left_as_it_was():
    cut = {"content": "<tool_call>\n<function=describe_data>\n<parameter=index>\nosagg-lab"}
    assert markup_read(cut, TOOLS) is cut                       # cut before its end
    other = {"content": "<tool_call>\n<function=drop_table>\n<parameter=x>\ny\n</parameter>\n</function>\n</tool_call>"}
    assert markup_read(other, TOOLS) is other                   # a tool not offered
    assert markup_read(other, None) is other                    # no tool offered at all
    plain = {"content": "The answer is 42."}
    assert markup_read(plain, TOOLS) is plain
    done = {"content": "", "tool_calls": [{"id": "x"}]}
    assert markup_read(done, TOOLS) is done


def test_decimal_size_no_one_asked_for():
    trace = _trace(11003281408)
    why = decimal_unasked("**srv-apac-009** dropped to approximately **11.00 GB** (11,003,281,408 bytes).", trace,
                          "Which server had the least available memory on 23 September, and how low did it go?")
    assert why and "10.25 GiB" in why
    # asked in GB: kept; given in GiB too: kept; no bytes behind it: kept
    assert decimal_unasked("It went down to 11.00 GB.", trace, "How low did it go, in GB?") is None
    assert decimal_unasked("10.25 GiB (11.00 GB).", trace, "How low did it go?") is None
    assert decimal_unasked("The disk holds 500 GB.", _trace(3.5), "How big is the disk?") is None
    # a binary value labelled GB is said too
    assert decimal_unasked("It went down to 10.25 GB.", trace, "How low did it go?")
    # a rate is no size
    assert decimal_unasked("It read 11.00 MB/s.", _trace(11000000), "How fast did it read?") is None


def test_time_of_day_asked_none_given():
    assert time_unsaid("At what time was it?", "The highest 1-minute load of srv-amer-003 on 24 September was **3.38**.")
    assert not time_unsaid("At what time was it?", "It was at **04:25** (3.38).")
    assert not time_unsaid("At what time was it?", "Around 4 am.")
    assert not time_unsaid("What was the highest load?", "It was 3.38.")
    assert time_unsaid("What was the cause, and when did it end?", "The cause was the cache eviction.")
    assert not time_unsaid("What was the cause, and when did it end?", "It ended at 11:02.")


def test_question_inside_a_line_goes_last():
    s41 = ("Could you please specify which application or server you are interested in (e.g., APP_A, APP_B, n1, n2) "
           "or if you want the total for all of them? Also, please specify the time period (e.g., today, yesterday, "
           "or the last days).")
    out = question_last(s41)
    assert asks_back(out)
    assert out.startswith("Please specify the time period")
    assert out.endswith("for all of them?")
    s09 = ("Could you clarify what you mean by \"late ones\"? Are you referring to:\n\n"
           "1. Late reports (from the `reports` index)\n2. Late shipments (from the `shipments` index)\n"
           "3. Late batch jobs (from the `batch` index)")
    out = question_last(s09)
    assert asks_back(out)
    assert out.startswith("Are you referring to:")
    assert out.endswith("\"late ones\"?")
    assert "1. Late reports" in out and "3. Late batch jobs" in out


def test_question_inside_left_alone():
    offer = "Revenue was 1,234 EUR in September. Would you like it by country? Also, let me know the period."
    assert question_last(offer) == offer                        # a result with an offer: not a question back
    statement = "Which one? I picked the shipments index for this answer."
    assert question_last(statement) == statement                # words after the question that ask nothing


def test_a_whole_configured_size_is_left_alone():
    trace = _trace(4294967296, 2147483648)                      # maxmemory 4 GiB then 2 GiB, in bytes
    assert decimal_unasked("A change reduced maxmemory from 4 GB to 2 GB at 10:12.", trace, "What changed?") is None
    assert decimal_unasked("Memory used was 1.82 GB.", _trace(1954210119), "How much memory?")   # not whole: said


def test_reach_asks_only_the_kinds_the_question_names():
    from supagent.knowledge.leads import reach_unsaid

    reach = {"par1-b": {"runs_on_it": ["zqx-cache (cache) on zqx-cache-01", "zqx-cart-cache (cache) on zqx-cache-04"],
                        "uses_it": ["zqx-inventory (application) waits for zqx-cache",
                                    "zqx-logship (component) reads from zqx-inventory",
                                    "Zqx overview (dashboard) shows zqx-inventory"]}}
    q = "If rack par1-b loses power, which data stores go down with it, and which applications depend on them?"
    out = reach_unsaid(q, "zqx-cache on zqx-cache-01 goes down; zqx-inventory depends on it.", reach)
    assert out == ["zqx-cart-cache (cache) on zqx-cache-04"]     # the collector and the dashboard are not asked for
    every = reach_unsaid("If rack par1-b loses power, what is affected?", "zqx-cache goes down.", reach)
    assert any("zqx-logship" in x for x in every) and any("Zqx overview" in x for x in every)


def test_a_question_back_with_a_closing_offer_ends_on_its_question():
    s40 = ("The term \"errors\" applies to several different parts of the system, including applications like ZQX_A, "
           "ZQX_B and many more, as well as servers like n1, n2, srv-amer-000, and 198 more.\n\nCould you please specify "
           "which application or server you are interested in, and for which period (today, yesterday, or the last few "
           "days)? If you would like a total across all of them, please let me know.")
    out = question_last(s40)
    assert asks_back(out)
    assert out.endswith("(today, yesterday, or the last few days)?")
    assert "If you would like a total across all of them, please let me know." in out
    result = "There were 1,234 errors yesterday. Would you like them by server? If you want, let me know."
    assert question_last(result) == result                      # a result with an offer: left as it was
