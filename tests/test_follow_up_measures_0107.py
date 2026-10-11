"""(0.10.7, M1-0107m) A follow-up asking another figure of the same thing, and an average per day taken over each
day's records: "And its average over that day?" after the day's highest load was answered twice with no query (1.33;
the data: 2.26); "And the flash PnL?" after an answer whose first query listed every status's rows was answered with
the official figure (the word being in that answer); "the average daily unexplained PnL of a desk" was computed as an
average of each day's record averages (several traders a day: 448.64 for 2,691.84). An aggregate no previous query
computed asks for its own query; an answer's words hold no figure; a per-day step averaging an amount is sent back
once (a latency, a load or a price averaged per day is each day's figure: as before)."""
from __future__ import annotations


def test_a_new_aggregate_is_another_figure(ctx):
    from supagent.knowledge.carry import new_aggregates

    peak = "SELECT MAX(value) AS peak FROM metrics WHERE metric = 'load1' AND ts >= '2026-09-24' AND ts < '2026-09-25'"
    assert new_aggregates("And its average over that day?", [peak]) == ["average (AVG)"]
    assert new_aggregates("And its average over that day?", [peak.replace("MAX", "AVG")]) == []
    assert new_aggregates("What was the highest?", ["SELECT host, value FROM t ORDER BY value DESC LIMIT 1"]) == []
    assert new_aggregates("How many were there?", [peak]) == ["How many (COUNT)"]
    assert new_aggregates("Which host was it on?", [peak]) == []          # no aggregate asked
    assert new_aggregates("And its average?", []) == []                   # no query before: nothing to compare


def test_the_follow_up_asks_its_own_query(ctx, monkeypatch):
    import json

    from test_agent_loop import agent_with, call, say

    prev = ("SELECT MAX(\"value\") AS peak FROM \"metrics\" WHERE \"host\" = 'srv-a' AND \"ts\" >= '2026-09-24' "
            "AND \"ts\" < '2026-09-25'")
    when = ("SELECT \"ts\", \"value\" FROM \"metrics\" WHERE \"host\" = 'srv-a' AND \"ts\" >= '2026-09-24' AND "
            "\"ts\" < '2026-09-25' ORDER BY \"value\" DESC LIMIT 1")
    history = [{"role": "user", "content": "What was the highest 1-minute load of srv-a on 24 September?"},
               {"role": "assistant", "content": "The highest 1-minute load of srv-a on 24 September was 7.91.",
                "queries": [{"query": prev}]},
               {"role": "user", "content": "At what time was it?"},
               {"role": "assistant", "content": "It was at 14:03.", "queries": [{"query": when}]}]
    made_up = say("**1.33**.")
    sql = {"request": {"database_id": 1, "sql": prev.replace("MAX", "AVG")}}
    rows = json.dumps({"success": True, "columns": [{"name": "avg"}], "rows": [{"avg": 2.26}], "row_count": 1})
    a, ran = agent_with(monkeypatch, [made_up, call("execute_sql", sql), say("Its average that day was 2.26.")],
                        results=lambda n, args: rows)
    answer, _trace = a.ask("And its average over that day?", history)
    assert a.asks_new and not a.follow_up                                # ("that day": another figure already)
    assert answer == "Its average that day was 2.26." and len(ran) == 1
    assert a.llm.choices == [None, "required", None]                     # its own query, compulsory after the nudge
    # one turn before, "the average" alone: no other day nor value, an aggregate no query computed
    b, ran_b = agent_with(monkeypatch, [say("**1.33**."), call("execute_sql", sql), say("The average was 2.26.")],
                          results=lambda n, args: rows)
    answer, _trace = b.ask("And the average?", history[:2])
    assert b.new_values == ["average (AVG)"] and b.asks_new and not b.follow_up
    assert answer == "The average was 2.26." and len(ran_b) == 1 and b.llm.choices == [None, "required", None]


def test_an_average_per_day_of_an_amount_sums_each_day_first(ctx):
    from supagent.knowledge.sqllint import per_day_refusal

    q = "What was the average daily unexplained PnL of the desk in September, in official PnL?"
    inner_avg = ("SELECT AVG(d) FROM (SELECT COB_DATE, AVG(PNL_UNEXPLAINED) AS d FROM pnl WHERE DESK = 'D1' AND "
                 "COB_DATE >= '2026-09-01' AND COB_DATE <= '2026-09-30' GROUP BY COB_DATE) AS x")
    msg = per_day_refusal(q, "execute_sql", {"sql": inner_avg})
    assert msg and "average of averages" in msg and "PNL_UNEXPLAINED" in msg
    assert per_day_refusal(q, "execute_sql", {"sql": inner_avg.replace("AVG(PNL_UNEXPLAINED)", "SUM(PNL_UNEXPLAINED)")}) is None
    latency = ("SELECT AVG(d) FROM (SELECT day, AVG(latency_ms) AS d FROM requests_by_day GROUP BY day) AS x")
    assert per_day_refusal("What was the average daily latency in September?", "execute_sql", {"sql": latency}) is None
    rows = "SELECT AVG(PNL_UNEXPLAINED) FROM pnl WHERE DESK = 'D1'"          # the records averaged: as before
    assert "averages the records themselves" in per_day_refusal(q, "execute_sql", {"sql": rows})


def test_its_measure_is_the_subjects_not_the_previous_narrowing(ctx):
    """"And its average latency?" after "Which error code came up most often?": the error filter the previous
    question introduced is not carried ("its" is the pricer); a question with no possessive keeps it ("Which error
    category ...?" after "How many failed jobs ...?"), and the first question's conditions are always the subject's."""
    from supagent.knowledge.carry import dropped

    first = "How many pricing requests did svc-a receive on 22 September?"
    errors = "Which error code came up most often?"
    prev = ["SELECT ERROR_CODE, COUNT(*) FROM requests WHERE SERVICE = 'svc-a' AND STATUS IN ('ERROR', 'TIMEOUT') AND "
            "ts >= '2026-09-22' AND ts < '2026-09-23' GROUP BY ERROR_CODE"]
    now = ["SELECT AVG(LATENCY_MS) / 1000.0 FROM requests WHERE SERVICE = 'svc-a' AND ts >= '2026-09-22' AND "
           "ts < '2026-09-23'"]
    q = "And its average latency, in seconds?"
    assert dropped(q, prev, now, errors, [first, "What was its failure rate?"]) == []
    assert [c.column for c in dropped(q, prev, now)] == ["STATUS"]                     # (no history given: as before)
    failed_first = "How many jobs failed on 22 September?"
    jobs = ["SELECT COUNT(*) FROM jobs WHERE STATUS = 'FAILED' AND day = '2026-09-22'"]
    by_cat = ["SELECT CATEGORY, COUNT(*) FROM jobs WHERE day = '2026-09-22' GROUP BY CATEGORY"]
    assert [c.column for c in dropped("Which error category came up most often?", jobs, by_cat, failed_first, [])] \
        == ["STATUS"]                                                                   # no "its": kept
    only = ["SELECT AVG(LATENCY_MS) FROM requests WHERE ts >= '2026-09-22' AND ts < '2026-09-23'"]
    assert [c.column for c in dropped(q, prev, only, first, [])] == ["SERVICE", "STATUS"] or \
        [c.column for c in dropped(q, prev, only, first, [])] == ["STATUS", "SERVICE"]  # the first question's: kept


def test_a_step_announced_again_is_answered_from_the_results(ctx, monkeypatch):
    """M-0107R1: the dashboard found, the answer announced another search, was reminded once, then announced
    another again ("Let me also check for any dashboards that might be related to logistics or returns.") and that
    was the whole answer. After the reminder, a step announced again is answered from the results above, asked once
    without tools; an answer written so goes through the checks as any other."""
    import json

    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "title"}], "rows": [{"title": "Deliveries board"}],
                       "row_count": 1})
    sql = {"request": {"database_id": 1, "sql": "SELECT title FROM boards WHERE title ILIKE '%deliver%'"}}
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), say("Let me also check boards about shipping."),
                                      say("Let me also check for any boards that might be related to returns."),
                                      say("One board is about deliveries: Deliveries board.")],
                        results=lambda n, args: rows)
    answer, _trace = a.ask("Which boards do we have about deliveries?", [])
    assert answer.startswith("One board is about deliveries: Deliveries board.") and len(ran) == 1
    assert a.usage.get("nudges") == 2                                    # the reminder, then the answer asked


def test_no_health_check_defined_is_no_check_that_failed(ctx):
    """obs7dev: the catalog had no checks; every check_health call failed ("no checks in catalog.yaml"), and that
    failure marked the investigation's "no error was found in the dependencies" as not checked. With no check
    defined there is nothing it could have checked: not counted; any other failure of it still is."""
    from supagent import agent as A

    trace = [{"tool": "check_health", "status": "error", "result": '{"error": "no checks in catalog.yaml"}'}]
    assert A._unchecked(trace) == []
    trace = [{"tool": "check_health", "status": "error", "result": '{"error": "metrics database unreachable"}'}]
    assert A._unchecked(trace) == ["check_health"]



def test_which_metrics_asks_names_not_their_values(ctx, monkeypatch):
    """obs7dev: "Which metrics compare the pods' memory with their limit?" was answered with the two names right,
    after seven queries of their values (ten calls, over its budget of six). The first data query of a names-only
    question is sent back once; sent again unchanged, it runs; a question asking values is not concerned."""
    import json

    from test_agent_loop import agent_with, call, say

    sql = {"request": {"database_id": 2, "sql": "SELECT pod, AVG(value) FROM mem_usage GROUP BY pod"}}
    rows = json.dumps({"success": True, "columns": [{"name": "pod"}], "rows": [{"pod": "p1"}], "row_count": 1})
    named = say("mem_usage and mem_limit: the pods' usage and limit.")
    a, ran = agent_with(monkeypatch, [call("execute_sql", sql), named, named, named, named],
                        results=lambda n, args: rows)
    answer, trace = a.ask("Which metrics compare the pods' memory with their limit?", [])
    assert ran == [] and answer.startswith("mem_usage and mem_limit") and "names asked" in str(trace)
    b, ran_b = agent_with(monkeypatch, [call("execute_sql", sql), call("execute_sql", sql), say("Done: p1."),
                                        say("Done: p1."), say("Done: p1.")], results=lambda n, args: rows)
    b.ask("Which metrics compare the pods' memory with their limit?", [])
    assert len(ran_b) == 1                                                     # sent again unchanged: it runs
    c, ran_c = agent_with(monkeypatch, [call("execute_sql", sql), say("p1 uses 0.8 GiB."), say("p1 uses 0.8 GiB."),
                                        say("p1 uses 0.8 GiB.")], results=lambda n, args: rows)
    c.ask("What was the average memory of the pods on 2 October?", [])
    assert len(ran_c) == 1                                                     # values asked: as before


def test_what_a_failure_reaches_comes_first():
    """obs7dev: "If the cache's server goes down, what is affected?": what a failure reaches (if_it_fails) came after
    the parts and the chains, past the result's size: the second step (the application calling the one that uses
    the cache) never read. It comes first, the chains cut short."""
    from supagent.knowledge.brief import TO_CHAINS, _summaries_first

    res = {"parts": [{"name": "srv"}], "paths": {"led_from": [f"chain {i}" for i in range(40)]},
           "if_it_fails": {"srv": {"runs_on_it": ["cache"], "and_further": ["shop calls inventory"]}}}
    out = _summaries_first(res)
    assert list(out)[0] == "if_it_fails" and len(out["paths"]["led_from"]) == TO_CHAINS + 1
    plain = {"parts": [{"name": "srv"}], "paths": {"led_from": [f"chain {i}" for i in range(40)]}}
    assert _summaries_first(dict(plain)) == plain                              # no summary: as before


def test_a_yes_or_no_about_a_suspect_comes_first():
    """obs7dev: "Did the frontend deployment of that afternoon play a role?" answered with the incident's whole
    investigation again, its "no" at the end. A yes-or-no question about a suspect whose answer starts with neither is
    sent back once; a short answer or one that says it first is not."""
    from supagent.agent import verdict_missing

    q = "Did the frontend deployment of that afternoon play a role?"
    long_ = ("## Root cause\\nAn export job read four million rows from the database ... " + "x" * 300 +
             "\\n## What was ruled out\\n- Frontend deployment: it did not cause the slowdown.")
    assert verdict_missing(q, long_)
    assert not verdict_missing(q, "No: the frontend deployment ended twelve minutes before the slowdown. " + "x" * 300)
    assert not verdict_missing(q, "It did not: the slowdown started with the export job. " + "x" * 300)
    assert not verdict_missing("How many orders were placed?", long_)
    assert not verdict_missing(q, "Short answer, no verdict word here.")
    # (0.10.7, obs7dev-n) a cause asked for is no yes or no: it was sent back as one, and the answer written again
    # began with "Yes:" and lost the mechanism it had found
    for open_q in ("Checkout was slow on 28 September in the afternoon. What was the cause?",
                   "Inventory was slow late in the morning. What was the cause, and when did it end?",
                   "Why did the export fail, and who was responsible?"):
        assert not verdict_missing(open_q, long_), open_q
    for yes_no in ("Inventory warns every night. Was that related to the problem of the morning?",
                   "The export ran at 14:00 - could it be the cause of the slowdown?",
                   "Est-ce que le déploiement est la cause du problème ?"):
        assert verdict_missing(yes_no, long_), yes_no


def test_which_metrics_show_it_reads_the_data():
    """obs7dev-h: "Which metrics show it on the database side?" (it: the incident of the chat) needs the data to tell
    which metrics moved; sent back as names only, it named metrics from memory. A follow-up that refers back is not
    a names-only question."""
    from supagent.agent import refers_back

    assert refers_back("Which metrics show it on the database side?")
    assert not refers_back("Which metrics compare the checkout pods' memory with their limit?")


def test_a_blamed_part_whose_records_were_never_looked_up(ctx):
    """obs7dev-h: the cache's evictions blamed, the changes looked up on the database only (its maxmemory change
    never read, an older change of the database named a contributing factor). The parts an answer blames that no
    records_about (nor a query) named, nor what they run on or what runs on them, are said."""
    from superset.extensions import db

    from supagent.knowledge import brief
    from supagent.knowledge.leads import unlooked
    from supagent.models import Facet, Link

    made = [Facet(facet="component", value="zqkcache", status="approved", source="admin"),
            Facet(facet="component", value="zqkdb", status="approved", source="admin"),
            Facet(facet="application", value="zqkapp", status="approved", source="admin"),
            Facet(facet="component", value="zqksrv", status="approved", source="admin")]
    db.session.add_all(made)
    db.session.flush()
    r = {f.value: f"facet:{f.id}" for f in made}
    db.session.add_all([Link(a_ref=r["zqkcache"], b_ref=r["zqksrv"], kind="runs_on", status="approved", source="admin"),
                        Link(a_ref=r["zqkapp"], b_ref=r["zqkcache"], kind="depends_on", status="approved",
                             source="admin")])
    db.session.commit()
    brief._CACHE["stamp"] = None
    try:
        answer = "## Root cause\nThe zqkcache evictions caused the slowdown of zqkapp."
        q = "zqkapp was slow this morning: what was the cause?"
        on_db = [{"tool": "records_about", "status": "done", "args": {"names": ["zqkdb"]}}]
        assert unlooked(answer, on_db, q) == ["zqkcache"]               # zqkapp: what the question names
        on_srv = on_db + [{"tool": "records_about", "status": "done", "args": {"names": ["zqksrv"]}}]
        assert unlooked(answer, on_srv, q) == []                     # what it runs on: looked up
        assert unlooked(answer, [], q) == []                         # nothing looked up at all: another check's
        assert unlooked("No cause found.", on_db, q) == []
        # (0.10.7, obs lab) a subject or a value that only watches others is no part to blame
        extra = [Facet(facet="subject", value="zqkstock", status="approved", source="admin"),
                 Facet(facet="component", value="zqkwatch", status="approved", source="admin")]
        db.session.add_all(extra)
        db.session.flush()
        made += extra
        db.session.add_all([Link(a_ref=f"facet:{extra[1].id}", b_ref=r["zqkcache"], kind="monitors",
                                 status="approved", source="admin")])
        db.session.commit()
        brief._CACHE["stamp"] = None
        blames = "## Root cause\nThe zqkstock levels and the zqkwatch job caused the slowdown of zqkapp, with zqkcache."
        assert unlooked(blames, on_db, q) == ["zqkcache"]
        watched = Facet(facet="component", value="zqkqueue", status="approved", source="admin")   # only watched by
        db.session.add(watched)                                                                   # others: it can fail
        db.session.flush()
        made.append(watched)
        db.session.add(Link(a_ref=f"facet:{extra[1].id}", b_ref=f"facet:{watched.id}", kind="monitors",
                            status="approved", source="admin"))
        db.session.commit()
        brief._CACHE["stamp"] = None
        assert unlooked("## Root cause\nThe zqkqueue backlog slowed zqkapp down.", on_db, q) == ["zqkqueue"]
        system = Facet(facet="component", value="zqkmonitoring", status="approved", source="admin")   # a watcher
        db.session.add(system)                                                     # part of a monitoring system
        db.session.flush()
        made.append(system)
        db.session.add(Link(a_ref=f"facet:{extra[1].id}", b_ref=f"facet:{system.id}", kind="part_of",
                            status="approved", source="admin"))
        db.session.commit()
        brief._CACHE["stamp"] = None
        assert unlooked(blames, on_db, q) == ["zqkcache"]                           # still no part to blame
    finally:
        ids = [f.id for f in made]
        db.session.query(Link).filter(Link.a_ref.in_([f"facet:{i}" for i in ids])).delete(synchronize_session=False)
        db.session.query(Facet).filter(Facet.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        brief._CACHE["stamp"] = None


def test_the_absence_of_data_is_said_first():
    """obs7dev-h: "How many errors did the service log on ...?" answered with the search first and "its logs are not
    collected" at the end only. An answer narrating its search whose conclusion, last, is the absence is sent back
    once to say it first; an answer saying it first, or a figure found, is not."""
    from supagent.agent import no_data_buried

    buried = ("I looked in all the log indices available in the database:\n- logs-a: holds svc-a and svc-b only\n"
              "- logs-b: holds svc-c only\n- logs-c: holds svc-d only\n- alerts: 0 alerts for svc-x that day\n" + "x" * 220 +
              "\nNone of the available log indices contain logs from svc-x: its logs are not collected.")
    assert no_data_buried(buried)
    first = "No logs of svc-x are collected: none of the indices hold it.\n" + buried
    assert not no_data_buried(first)
    found = "I looked in the logs of svc-x: it logged 42 errors that day, most of them timeouts. " + "y" * 400
    assert not no_data_buried(found)
    # (0.10.7, obs7dev-n) "Based on my investigation, I can see that: 1. ... 4. ..." then "the available log indices
    # do not contain logs for svc-x": its absence too, said last
    based = ("Based on my investigation, I can see that:\n\n1. logs-a contains logs for svc-a only\n2. logs-b contains "
             "logs for svc-b and svc-c\n3. logs-c contains logs for svc-d\n4. the alerts show no alert for svc-x that "
             "day\n" + "z" * 220 + "\n\n**I cannot determine how many errors svc-x logged: the available log indices "
             "do not contain logs for svc-x.**")
    assert no_data_buried(based)
    assert not no_data_buried("No logs of svc-x are collected.\n\n" + based)


def test_a_category_of_the_chat_means_its_values(ctx):
    """obs7dev-j: "Which metrics show it on the database side?" after answers about the export that held a database:
    the knowledge searched with the questions alone found nothing of that database; the agent took three metrics of
    another family (deadlocks, commits, rollbacks) and found none moved. A follow-up naming a category and no value of
    its own means the values of that category the chat named: they are searched with it."""
    from superset.extensions import db

    from supagent import settings
    from supagent.knowledge import brief
    from supagent.models import Facet

    before = settings.get("categories.custom")
    settings.set_value("categories.custom", ["database"])
    made = [Facet(facet="database", value="zqcdb-main", status="approved", source="admin",
                  description="a PostgreSQL database"),
            Facet(facet="database", value="zqcdb-old", status="approved", source="admin", description="the old one"),
            Facet(facet="application", value="zqcshop", status="approved", source="admin", description="the shop")]
    db.session.add_all(made)
    db.session.commit()
    brief._CACHE["stamp"] = None
    try:
        history = [{"role": "user", "content": "Why was zqcshop slow yesterday afternoon?"},
                   {"role": "assistant", "content": "An export held a long transaction on zqcdb-main: zqcshop waited."},
                   {"role": "user", "content": "Did the deployment play a role?"},
                   {"role": "assistant", "content": "No: it ended before the slowdown began."}]
        q = "Which metrics show it on the database side?"
        assert brief.chat_values(q, history) == ["zqcdb-main"]
        assert brief.chat_values("And which databases did it hold?", history) == ["zqcdb-main"]    # a plural
        assert brief.chat_values("Which metrics show it on zqcdb-old?", history) == []   # it names its own value
        assert brief.chat_values("Which metrics show it?", history) == []                # no category named
        assert brief.chat_values(q, []) == []                                            # nothing named before
    finally:
        db.session.query(Facet).filter(Facet.id.in_([f.id for f in made])).delete(synchronize_session=False)
        db.session.commit()
        settings.set_value("categories.custom", before)
        brief._CACHE["stamp"] = None


def test_the_chats_values_are_searched_with_the_follow_up(ctx, monkeypatch):
    """The values a follow-up's category stands for go with it to the knowledge search (nothing else changes)."""
    from supagent import agent as A
    from supagent.knowledge import search

    seen: list[str] = []
    monkeypatch.setattr(search, "knowledge_block", lambda q, shown=None, **k: seen.append(q) or "")
    monkeypatch.setattr(A.Agent, "_investigating", lambda self, q: False)
    monkeypatch.setattr(A.Agent, "_route_intents", lambda self: set())
    a = object.__new__(A.Agent)
    a.understood, a.moa, a.username = {"as": ""}, None, "alice"
    a.intent_text = "Why was zqcshop slow?\nWhich metrics show it on the database side?"
    a.chat_values = ["zqcdb-main"]
    A.Agent._question_blocks(a, a.intent_text, set())
    assert seen == [a.intent_text + "\nzqcdb-main"]
    a.chat_values = []
    A.Agent._question_blocks(a, a.intent_text, set())
    assert seen[-1] == a.intent_text                                              # none: as before


def test_a_follow_up_answered_with_a_time_no_result_holds_must_query(ctx, monkeypatch):
    """(main suite M1-0107n) "At what time was it?" after "the highest load was 3.38" (one query: its MAX only) was
    answered with no tool, "at 14:00" (the data: 04:26); sent back once, the model wrote the same text and it was kept.
    A follow-up's answer from no tool that gives names, times or figures the chat's results do not hold is sent back
    with its next step made to call a tool."""
    import json

    from test_agent_loop import agent_with, call, say

    prev = ("SELECT MAX(\"value\") AS peak FROM \"load1\" WHERE \"node\" = 'srv-a' AND \"ts\" >= '2026-09-24' "
            "AND \"ts\" < '2026-09-25'")
    history = [{"role": "user", "content": "What was the highest 1-minute load of srv-a on 24 September?"},
               {"role": "assistant", "content": "The highest 1-minute load of srv-a on 24 September was **3.38**.",
                "queries": [{"query": prev}]}]
    made_up = say("The highest load of srv-a was **3.38**, at **14:00**.")
    when = {"request": {"database_id": 1, "sql": "SELECT ts, value FROM load1 WHERE node = 'srv-a' ORDER BY value DESC LIMIT 1"}}
    rows = json.dumps({"success": True, "columns": [{"name": "ts"}, {"name": "value"}],
                       "rows": [{"ts": "2026-09-24 04:26:00", "value": 3.38}], "row_count": 1})
    a, ran = agent_with(monkeypatch, [made_up, call("execute_sql", when), say("It was at 04:26."), say("It was at 04:26.")],
                        results=lambda n, args: rows)
    answer, _trace = a.ask("At what time was it?", history)
    assert answer.startswith("It was at 04:26") and len(ran) == 1
    assert a.llm.choices[1] == "required"                       # the step after the send-back must call a tool


def test_a_simple_question_is_told_once_after_its_fifth_call(ctx, monkeypatch):
    """(obs7dev-k) "On which servers does the database run, and which one is its primary?" was answered in 2 to 4 calls
    on most builds, then in 7 (over the budget of a simple question): the map's answer checked again in three sources
    before the documents. After the fifth call of a question that is no investigation nor a big request, its result
    says once to answer if the results hold the answer."""
    import json

    from supagent import agent as A
    from test_agent_loop import agent_with, call, say

    rows = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 1}], "row_count": 1})
    sql = lambda i: {"request": {"database_id": 1, "sql": f"SELECT {i} AS n FROM t"}}  # noqa: E731
    replies = [call("execute_sql", sql(i)) for i in range(1, 7)] + [say("It is 1.")] * 3
    a, ran = agent_with(monkeypatch, replies, results=lambda n, args: rows)
    a.ask("What is the value of n?", [])
    tools = [m["content"] for m in a.llm.seen[-1] if m["role"] == "tool"]
    assert len(ran) == 6 and A.SIMPLE_NOTE in tools[4] and sum(A.SIMPLE_NOTE in t for t in tools) == 1
    monkeypatch.setattr(A.Agent, "_investigating", lambda self, q: True)
    b, _ran = agent_with(monkeypatch, [call("execute_sql", sql(i)) for i in range(1, 7)] + [say("It is 1.")] * 3,
                         results=lambda n, args: rows)
    b.ledger = None
    b.ask("Why is n 1?", [])
    assert not any(A.SIMPLE_NOTE in m["content"] for sent in b.llm.seen for m in sent if m["role"] == "tool")


def test_who_did_it_on_a_part_is_read_in_its_servers_own_logs(ctx, monkeypatch):
    """(obs7dev-k) "Which database user and which application held the long transaction on the database ...?" was
    looked for in the traces and the applications' logs, never in the database's own lines on its server (right on the
    builds that read them): "not visible". A question of who did something on a part whose servers' log tables no query
    read is sent back once, its next step made to read them."""
    import json

    from supagent import agent as A
    from supagent.knowledge import brief
    from test_agent_loop import agent_with, call, say

    for q in ("Which database user held the long transaction on the database?", "Who ran the export on the db?",
              "Which account deleted the rows?", "Quel utilisateur a lancé la requête ?"):
        assert A.WHO_ASKED.search(q), q
    for q in ("How many users are there?", "Which application is slow?", "Who owns the database?"):
        assert not A.WHO_ASKED.search(q), q                               # (a part's servers are needed besides)
    monkeypatch.setattr(brief, "server_places", lambda q, logs_only=False: [("zqo-db-1", "host.name", ["zqo-logs-*"])])
    rows = json.dumps({"success": True, "columns": [{"name": "n"}], "rows": [{"n": 1}], "row_count": 1})
    traces = {"request": {"database_id": 1, "sql": "SELECT \"service\" FROM \"zqo-traces\" WHERE \"peer\" = 'zqo-db'"}}
    own = {"request": {"database_id": 1, "sql": "SELECT \"message\" FROM \"zqo-logs-*\" WHERE \"host.name\" = 'zqo-db-1'"}}
    q = "Which database user held the long transaction on zqo-db?"
    a, ran = agent_with(monkeypatch, [call("execute_sql", traces), say("The user is not visible in the traces."),
                                      call("execute_sql", own), say("The user reporting held it.")] +
                        [say("The user reporting held it.")] * 3, results=lambda n, args: rows)
    answer, _trace = a.ask(q, [])
    assert answer.startswith("The user reporting held it") and len(ran) == 2
    sent = [m["content"] for m in a.llm.seen[-1] if m["role"] == "user"]
    assert any("its servers' own records are in field \"host.name\" of zqo-logs-*" in c for c in sent)
    b, _ran = agent_with(monkeypatch, [call("execute_sql", own)] + [say("The user reporting held it.")] * 3,
                         results=lambda n, args: rows)
    b.ask(q, [])
    assert not any("its servers' own records" in m["content"] for sent in b.llm.seen for m in sent if m["role"] == "user")


def test_a_value_named_in_the_plural_is_a_new_value():
    """(main suite M2-0107n) "How many of its failures were timeouts?" after the failures counted and the application
    with the most found: answered "0 timeouts" with no query (211 in the data): "timeouts" was not found as the value
    TIMEOUT of a field the previous queries read, so the follow-up passed as one the chat holds. A plural names its
    value."""
    from supagent.knowledge.carry import new_values

    values = {"timeout": "ERROR_CATEGORY", "zqpapp": "APPLICATION", "failed": "STATUS"}
    prev = ['SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'FAILED\' AND "APPLICATION" = \'ZQPAPP\'']
    q = "How many of its failures were timeouts?"
    assert new_values(q, ["What was that application's failure rate?"], prev, values_of=lambda t: values) == \
        ["timeouts (ERROR_CATEGORY)"]
    timed = ['SELECT COUNT(*) FROM "jobs" WHERE "STATUS" = \'FAILED\' AND "ERROR_CATEGORY" = \'TIMEOUT\'']
    assert new_values(q, ["How many timed out?"], timed, values_of=lambda t: values) == []    # its queries used it
    assert new_values("And the classes?", ["?"], prev, values_of=lambda t: {"clas": "X"}) == []  # too short a stem


def test_out_of_calls_a_yes_or_no_is_asked_first(ctx, monkeypatch):
    """(0.10.7, obs7dev-n) "Was that related to the problem of the morning?" ran out of calls: the summary written then
    is not checked, and it said its "no" at the end only. The last message asks for the yes or no first when the
    question asks one; an open question is not told so."""
    from test_agent_loop import agent_with, call, say

    def ran_out(question: str) -> str:
        calls = [call("execute_sql", {"request": {"database_id": 1, "sql": f'SELECT {n} FROM "zq-logs"'}})
                 for n in range(1, 13)]
        a, _ran = agent_with(monkeypatch, calls + [say("No: the warnings come every night. " + "x" * 50)] * 3)
        a.ask(question, [])
        return " ".join(str(m["content"]) for m in a.llm.seen[-1] if m["role"] == "user")

    assert "The question asks yes or no" in ran_out("zqinv warns every night. Was that related to the morning's problem?")
    assert "The question asks yes or no" not in ran_out("zqinv was slow this morning. What was the cause?")


def test_who_did_it_says_where_the_part_writes_it_first(ctx, monkeypatch):
    """(0.10.7, obs7dev-m/n) "Which database user ... held the long transaction on the database?" used its calls up
    on alerts, traces and metrics and never read the database's own lines: the check after the answer came too late.
    Where the part's servers write their own log lines is said with the question."""
    from supagent import agent as A
    from supagent.knowledge import brief, search

    monkeypatch.setattr(search, "knowledge_block", lambda q, shown=None, **k: "")
    monkeypatch.setattr(A.Agent, "_investigating", lambda self, q: False)
    monkeypatch.setattr(A.Agent, "_route_intents", lambda self: set())
    monkeypatch.setattr(brief, "server_places", lambda q, logs_only=False: [("zqo-db-1", "host.name", ["zqo-logs-*"])])
    a = object.__new__(A.Agent)
    a.understood, a.moa, a.username, a.chat_values = {"as": ""}, None, "alice", []
    who = A.Agent._question_blocks(a, "Which database user held the long transaction on zqo-db?", set())
    assert "its servers (zqo-db-1) have their own log lines in field \"host.name\" of zqo-logs-*" in who
    other = A.Agent._question_blocks(a, "How many long transactions did zqo-db have?", set())
    assert "own log lines" not in other
