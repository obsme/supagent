"""What a Helpful answer keeps (0.9.6, the user's request): the agent reads the whole discussion and the steps that
worked and writes a title, a description, the steps (each once) and the checks; no value of that one case stays; a
step naming data the answer never used is left out; a person's own summary is never written over."""

import json
import types

DISCUSSION = ["Which applications failed most yesterday?", "And on the server srv-emea-041?"]
SQL_OK = """SELECT "APPLICATION", COUNT(*) FROM "jobs" WHERE "STATUS_INFO" = 'KO' AND "SERVER" = 'srv-emea-041' GROUP BY 1"""
TRACE = [
    {"tool": "execute_sql", "status": "error", "args": {"request": {"sql": 'SELECT "STATUS" FROM "jobs"'}}},
    {"tool": "execute_sql", "status": "done", "args": {"request": {"sql": SQL_OK}}},
    {"tool": "execute_sql", "status": "done", "args": {"request": {"sql": SQL_OK}}},
    {"tool": "work_plan", "status": "done", "args": {}},
]


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def chat(self, messages, max_tokens=None, **kw):
        self.seen.append(messages)
        return {"content": self.replies.pop(0)}


def test_the_steps_that_worked_each_once(ctx):
    from supagent.knowledge.helpful import steps_that_worked

    got = steps_that_worked(TRACE)
    assert len(got) == 1 and got[0].startswith('execute_sql: SELECT "APPLICATION"')      # no error, no repeat, no plan


def test_a_summary_without_the_cases_values_nor_invented_data(ctx):
    from supagent.knowledge.helpful import summarize

    first = json.dumps({"title": "Failed jobs per application", "description": "Counts the failed jobs of a day per "
                        "application, for one server (srv-emea-041).",
                        "steps": ["Count the jobs with STATUS_INFO = 'KO' in jobs, grouped by APPLICATION, for the server "
                                  "srv-emea-041.", "Join with `cmdb-assets` for the owners."],
                        "tasks": ["State the day asked."]})
    second = json.dumps({"title": "Failed jobs per application", "description": "Counts the failed jobs of a day per "
                         "application, for a given server.",
                         "steps": ["Count the jobs with STATUS_INFO = 'KO' in jobs, grouped by APPLICATION, for a given "
                                   "server.", "Join with `cmdb-assets` for the owners."],
                         "tasks": ["State the day asked."]})
    llm = FakeLLM([first, second])
    out = summarize(DISCUSSION[-1], DISCUSSION[:-1], "srv-emea-041: PRICING 4, BOOKING 2.", TRACE, llm=llm)
    assert len(llm.seen) == 2 and "srv-emea-041" in llm.seen[1][-1]["content"]          # sent back once
    assert "srv-emea-041" not in json.dumps(out)
    assert out["how"] == ["Count the jobs with STATUS_INFO = 'KO' in jobs, grouped by APPLICATION, for a given server."]
    assert out["tasks"] == ["State the day asked."] and out["title"] == "Failed jobs per application"


def test_a_persons_summary_stays_and_the_agent_is_given_it(ctx):
    from supagent.knowledge.helpful import brief, keep

    r = types.SimpleNamespace(title=None, description=None, how=None, tasks=None, summary_by=None, summary_at=None)
    assert keep(r, {"title": "T", "description": "D", "how": ["one", "two"], "tasks": ["c"]}, by="alice")
    assert not keep(r, {"title": "Agent's", "description": "", "how": [], "tasks": []})       # alice's stays
    assert r.title == "T" and r.summary_by == "alice"
    assert brief(r) == "T: D Steps: 1) one 2) two Checks: c"
