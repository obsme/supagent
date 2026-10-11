"""(0.10.8) A count of one country's orders, the country named in the question and written as its ISO code in the
query, was refused as "a condition nobody asked for": the model removed it and counted every country. A code the
data writes for a name the people said (a country, a currency, a language) is said."""

from __future__ import annotations

from supagent.knowledge.conditions import build, code_names, refusal

SYSTEM = "Rules... Answer from the data."


def _support(question):
    return build([{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}], [question])


def _sql(where):
    return {"request": {"database_id": 1, "sql": f'SELECT COUNT(*) FROM "shipments" WHERE {where}'}}


def test_the_codes_and_their_names_come_from_the_cldr_data():
    names = code_names()
    assert "portugal" in names["pt"] and "portugais" in names["pt"]            # a country, a language (fr)
    assert any("franc" in n for n in names["chf"])                             # a currency


def test_a_code_of_a_name_the_question_says_is_said(ctx):
    assert refusal(_support("How many parcels went to Portugal on 2 March?"), "execute_sql",
                   _sql("\"DEST\" = 'PT'")) is None
    assert refusal(_support("How many payments were made in Swiss francs?"), "execute_sql",
                   _sql("\"CCY\" = 'CHF'")) is None
    assert refusal(_support("How many tickets were written in Dutch?"), "execute_sql",
                   _sql("\"LANG\" = 'nl'")) is None


def test_a_code_of_another_name_is_still_sent_back(ctx):
    said = refusal(_support("How many parcels went to Spain on 2 March?"), "execute_sql", _sql("\"DEST\" = 'PT'"))
    assert said and "(not run: a condition nobody asked for)" in said and "DEST = 'PT'" in said
    assert refusal(_support("How many parcels were sent on 2 March?"), "execute_sql", _sql("\"DEST\" = 'PT'"))
