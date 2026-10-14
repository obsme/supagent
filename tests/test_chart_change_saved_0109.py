"""(0.10.9) "Make it a pie chart instead.": the model asked update_chart for a preview (generate_preview true), so
Superset saved nothing and the chart stayed a bar chart; the answer opened "I've successfully updated the chart to a
pie chart" and then told the user to press Save, and the check of claimed changes did not see the claim (an adverb
between "I've" and "updated"). A change asked is saved whatever the model asks; a preview stays a preview when the
user asks for one or asks for no change; a claimed change with no saved change is marked, adverb or not."""

from __future__ import annotations

import json
import types


def _guard(question):
    from supagent.agent import Agent, ChartGuard

    a = object.__new__(Agent)
    a.names, a.question = {"update_chart"}, question
    a.superset = types.SimpleNamespace(available=False, call=lambda n, args: "{}")
    guard = ChartGuard(a)
    guard.parse = None
    guard._dataset = lambda ident: None
    return guard


def test_a_change_asked_is_saved_even_when_the_model_asks_a_preview(ctx):
    for question in ("Make it a pie chart instead.", "Change the colours of the bars.", "Sort it by amount, please.",
                     "Mets-le en camembert."):
        _n, sent, refused = _guard(question).before(
            "update_chart", {"request": {"identifier": 7, "config": {"chart_type": "pie"}, "generate_preview": True}})
        assert refused is None and sent["request"]["generate_preview"] is False, question
    for question in ("Show me a preview of it as a pie chart.", "What would it look like as a pie chart?",
                     "Is this chart up to date?"):
        _n, sent, _r = _guard(question).before(
            "update_chart", {"request": {"identifier": 7, "config": {"chart_type": "pie"}, "generate_preview": True}})
        assert sent["request"]["generate_preview"] is True, question


def test_a_claimed_change_with_no_saved_change_is_marked_adverb_or_not(ctx):
    from supagent.agent import claims_check

    preview = json.dumps({"chart": {"id": 7, "viz_type": "echarts_timeseries_bar", "is_unsaved_state": True}})
    trace = [{"tool": "update_chart", "status": "done", "args": {"request": {"identifier": 7}}, "result": preview}]
    for answer in ("Perfect! I've successfully updated the chart to a pie chart.",
                   "I have now changed the chart into a table.", "I've just converted it to a pie chart."):
        assert "the saved chart was not changed" in claims_check(answer, trace), answer
    saved = json.dumps({"chart": {"id": 7, "viz_type": "pie", "is_unsaved_state": False}})
    done = [{"tool": "update_chart", "status": "done", "args": {"request": {"identifier": 7}}, "result": saved}]
    assert claims_check("I've successfully updated the chart to a pie chart.", done) == ""
