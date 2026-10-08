"""(0.9.8) A LEFT JOIN undone by its WHERE: a condition on the optional side drops the rows without a match, as an
inner join would ("gross revenue" read over the refunded orders only). Sent back before it runs; IS NULL, a COALESCE,
a condition inside an OR, or a condition in the ON are not judged."""

from supagent.knowledge.sqllint import outer_join_refusal, outer_join_undone

BASE = 'SELECT SUM(s."PRICE") FROM "subscriptions" s LEFT JOIN "cancellations" c ON c."SUB_ID" = s."SUB_ID" '


def test_a_condition_on_the_optional_side_in_where_is_found():
    found = outer_join_undone(BASE + 'WHERE s."START" >= \'2030-01-01\' AND c."STATE" = \'DONE\'')
    assert found == ('c."STATE" = \'DONE\'', "cancellations")
    said = outer_join_refusal("execute_sql", {"request": {"sql": BASE + 'WHERE c."STATE" = \'DONE\''}})
    assert said.startswith("tool error (not run: a LEFT JOIN made inner)") and "send this same call again unchanged" in said


def test_what_is_not_judged():
    assert outer_join_undone(BASE + 'WHERE s."START" >= \'2030-01-01\'') is None                 # the kept side
    assert outer_join_undone(BASE + 'WHERE c."SUB_ID" IS NULL') is None                           # an anti-join
    assert outer_join_undone(BASE + 'WHERE COALESCE(c."STATE", \'NONE\') <> \'DONE\'') is None
    assert outer_join_undone(BASE + 'WHERE (c."STATE" = \'DONE\' OR s."PLAN" = \'X\')') is None
    on = ('SELECT SUM(s."PRICE") FROM "subscriptions" s LEFT JOIN "cancellations" c ON c."SUB_ID" = s."SUB_ID" '
          'AND c."STATE" = \'DONE\'')
    assert outer_join_undone(on) is None                                                          # in the ON: right
    inner = 'SELECT SUM(s."PRICE") FROM "subscriptions" s JOIN "cancellations" c ON c."SUB_ID" = s."SUB_ID" WHERE c."STATE" = \'DONE\''
    assert outer_join_undone(inner) is None                                                       # an inner join
    assert outer_join_refusal("describe_data", {"index": "x"}) is None


def test_the_check_has_its_setting(monkeypatch):
    from supagent import settings

    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k: False if k == "agent.outer_join_check" else real(k))
    assert outer_join_refusal("execute_sql", {"request": {"sql": BASE + 'WHERE c."STATE" = \'DONE\''}}) is None
