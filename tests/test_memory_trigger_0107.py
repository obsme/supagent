"""(0.10.7) A memory that applies only when the user says X ("When the user says 'NOVA', filter by
APPLICATION='NOVA'") is not given with a question whose chat never says X (told "applies only then", a model still
added the filter); and another memory line that only happens to name X ("The critical applications are NOVA and
VEGA") does not make that filter said for a question it has nothing to do with."""

from __future__ import annotations

from test_search import clean_knowledge  # noqa: F401  (the fixture)
from test_knowledge import world  # noqa: F401  (the fixture it uses)

BLOCK = ("What this user and the team asked to remember (...):\n"
         "- (this user, rule) When the user says 'NOVA', filter by APPLICATION='NOVA'.\n"
         "- (team, fact) The critical applications are NOVA and VEGA (field APPLICATION).\n"
         "- (this user, preference) Give durations in minutes.")


def test_a_conditional_memory_is_given_when_its_word_is_said(clean_knowledge):
    from superset.extensions import security_manager as sm

    from supagent.knowledge.memory import add, prompt_block, triggered

    assert triggered("Give durations in minutes.", "How many tasks failed?")             # always
    assert not triggered("When the user says 'NOVA', filter by APPLICATION='NOVA'.", "How many tasks failed?")
    assert triggered("When the user says 'NOVA', filter by APPLICATION='NOVA'.", "How many nova tasks failed?")
    assert not triggered("Quand je dis « NOVA », filtrer APPLICATION='NOVA'.", "Combien de tâches ont échoué ?")
    alice = sm.find_user(username="alice").id
    assert add(alice, "When the user says 'NOVA', filter by APPLICATION='NOVA'") is not None
    assert add(alice, "Give durations in minutes") is not None
    assert "NOVA" in prompt_block(alice)                                                # no question given: as before
    block = prompt_block(alice, asked="How many tasks failed on 3 March?")
    assert "NOVA" not in block and "durations in minutes" in block
    assert "NOVA" in prompt_block(alice, asked="How many NOVA tasks failed on 3 March?")


def test_an_unrelated_memory_line_does_not_say_the_gated_value(ctx):
    from supagent.knowledge.conditions import build, sql_conditions, unsaid, untriggered

    q = "How many tasks failed on 3 March, against the Monday before?"
    kept = untriggered(BLOCK, q)
    assert "When the user says" not in kept and "NOVA" not in kept and "VEGA" in kept     # the fact's other words stay
    about = "How many tasks of the critical applications failed on 3 March?"
    assert "NOVA and VEGA" in untriggered(BLOCK, about)                                 # the line is about it
    sql = ("SELECT COUNT(*) FROM \"tasks\" WHERE \"STATUS\" = 'FAILED' AND \"APPLICATION\" = 'NOVA' AND "
           "\"DAY\" = '2031-03-03'")
    s = build([{"role": "user", "content": BLOCK + "\n" + q}], [q, BLOCK])
    assert "APPLICATION = 'NOVA'" in [c.said() for c in unsaid(sql_conditions(sql), s)]
    s2 = build([{"role": "user", "content": BLOCK + "\n" + about}], [about, BLOCK])
    assert "APPLICATION = 'NOVA'" not in [c.said() for c in unsaid(sql_conditions(sql), s2)]
