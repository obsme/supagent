"""(0.10.11) A draft from a team rule has the labels the rule says: its team as the rules already in Grafana write it,
no label the rule never says (an invented label can send the alert elsewhere). Invented names only."""
from __future__ import annotations

import pytest

from supagent import grafana as G
from supagent import grafana_rules as R


@pytest.fixture()
def conf(monkeypatch):
    from supagent import settings

    values = {"grafana.label_keys": ["severity", "team", "service", "environment"],
              "grafana.rule_labels": {"managed_by": "supagent"}}
    monkeypatch.setattr(settings, "get", lambda k: values.get(k))
    rules = [{"uid": "a", "labels": {"team": "zqxdata", "severity": "warning"}},
             {"uid": "b", "labels": {"team": "zqxshop"}}, {"uid": "c", "labels": {}}]
    monkeypatch.setattr(G, "alert_rules", lambda **kw: rules)
    return values


def test_team_as_the_rule_names_it(conf):
    text = "Alert the zqxdata team (severity critical) when the zqx orders database deadlocks exceed 3 per minute."
    labels = {"severity": "critical", "team": "zqxdata-platform", "service": "zqx-orders-db", "environment": "prod",
              "managed_by": "supagent"}
    out, changed = R._grounded_labels(labels, text)
    assert out == {"severity": "critical", "team": "zqxdata", "managed_by": "supagent"}
    assert any("team=zqxdata" in c for c in changed)
    assert any("service=zqx-orders-db left out" in c for c in changed)
    assert any("environment=prod left out" in c for c in changed)


def test_labels_the_rule_says_stay(conf):
    text = "Page the zqxshop team when the zqx checkout queue in prod holds more than 500 messages for 10 minutes."
    labels = {"team": "zqxshop", "environment": "prod", "managed_by": "supagent"}
    out, changed = R._grounded_labels(labels, text)
    assert out == labels and changed == []


def test_a_new_team_written_as_said(conf):
    text = "Alert the zqx billing team when the invoices queue is stuck."
    out, changed = R._grounded_labels({"team": "finance"}, text)
    assert out["team"] == "billing"                         # the word before "team", as written
    assert changed


def test_no_team_named_keeps_the_team(conf):
    out, changed = R._grounded_labels({"team": "zqxshop", "severity": "warning"},
                                      "Alert when the zqx checkout errors exceed 5 per minute.")
    assert out == {"team": "zqxshop", "severity": "warning"} and changed == []


def test_a_team_fixed_by_the_settings_stays(conf):
    """(0.11.0) grafana.rule_labels fixing the team: a team named in the rule's text does not replace it (the alerts
    went to the wrong team)."""
    conf["grafana.rule_labels"] = {"managed_by": "supagent", "team": "zqxoncall"}
    text = "Alert the zqxdata team when the zqx orders database deadlocks exceed 3 per minute."
    out, _changed = R._grounded_labels({"team": "zqxoncall", "managed_by": "supagent"}, text)
    assert out["team"] == "zqxoncall"
