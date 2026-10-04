"""The agent: the LLM chooses the tools, the tools run in-process as the user who asks.

Tools: supagent's own (SQL, the learned data dictionary, files, e-mails, reports, metrics,
see supagent.tools and supagent.tools_superset) and Superset's MCP tools for charts and
dashboards (supagent.superset_mcp). The chart guard checks chart configs before Superset's MCP
service sees them (it answers only "An error occurred" for an invalid one and saves one more
chart at every accepted retry): Superset's own schema, the dataset's columns and saved
metrics, a preview without saving (a failing or empty chart is not saved), a second save of
the same name becomes an update, and date filters on the time column become the chart's time
range (dashboards ignore plain filters on it).
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import logging
import re
import time
from typing import Any, Callable

from supagent import settings
from supagent.dates import MONTH
from supagent.llm import LLM, EmptyAnswer, LLMError, add_usage

log = logging.getLogger(__name__)
MAX_TOOL_CHARS = 8000
TOOL_CHARS = {"describe_data": 16000, "compare_groups": 12000}   # (a comparison is an investigation's evidence:
#                                   its findings, its stages, the rows outside the scope, with the system's notes)
HISTORY_MESSAGES = 40      # of the chat given with a question at most (the runner gives its subject's: knowledge.topics)
HISTORY_CHARS = 3000      # of one earlier message given with the question
REPLY_WORDS = 25          # a reply to the agent's question back is at most this long
MANY_PARTS = 4            # a question of this many parts (commas, "and") gets half as many calls more
LEDGER_WORDS = 60         # a request this long gets a work plan (agent.ledger)
INVESTIGATION_STEPS = 2   # an investigation gets this many times the calls of an answer
FREE_PLAN_TURNS = 6       # turns whose only call is work_plan that do not count against those calls
UPSTREAM_LOG_CALLS = 3    # compare_logs calls by code on the logs of the inputs of late rows (agent.inputs_logs)
# compare_groups: 'on "POOL", concentrated on GRID_A (82 against 0 usually)': where the change is
CONCENTRATED = re.compile(r'on \\?"([@\w.]+)\\?", concentrated on ([\w.\-]+(?:, [\w.\-]+)*)')
RETRY_TOKENS = 2048       # tokens of the step after an unreadable tool call, at least
FRAGMENT_WORDS = 8        # "The failed jobs.", "Only PROD.": completes the previous question
FRAGMENT = re.compile(r"^\s*(?:and|et|or|ou|only|just|but|mais|the|le|la|les|for|pour|in|on|with|without|avec|"
                      r"sans|per|par|by|excluding|including|except|hors|what about|how about|same|m[êe]me|seulement|"
                      r"uniquement|plut[ôo]t|rather|instead)\b", re.I)
RESULT_TOOLS = ("execute_sql", "promql_query")      # their full result is kept for the page's views


class Cancelled(Exception):
    pass


CORE = """You are the data assistant of this Superset. You act with the permissions of the user who asks: the
tools only show and do what this user may see and do in Superset.

Rules:
1. Facts come from the tools: never invent a number, an id or a name, and never add numbers up yourself:
   quote the column_sums of a result, or run a query. Never write a list as a range ("srv-000 to srv-200"):
   give its count and the names the result showed. Count exactly what is asked: every condition of a
   query comes from the question, the chat, the team's rules and words or the documents given (a status,
   an environment, a threshold nobody gave is not added). Answer in the language of the question, even when
   the data, the dictionary or earlier answers use another language.
2. When "Where the data is" is given below, start from it: it names the metrics, indices and fields that
   match the question, with their database id and a SQL to adapt. Use them as they are. Call
   describe_data (topic = the words of the question) only for what it lacks, and search_knowledge at most
   once.
3. One query per answer when you can: execute_sql with the database id given. Metrics (Prometheus /
   Mimir, promagg): SQL on the metric's own table, or on all_metrics with metric_name = '...'. Jobs, logs
   and other documents (OpenSearch, osagg): SQL on the index. Other databases only when the user names
   them; a chart or a dashboard: the database of its dataset (the same index or metric in another
   database can hold other data).
4. A tool error says what to fix: fix it and try once more; never repeat a call that failed; after two
   failures on the same step, answer with what you have and say what did not work.
5. Say exactly what the tools did, never claim what a tool result does not show. If the data ends before
   "now", say so and use its last days. Timestamps are local time (never call them UTC); now is given
   with the question. The data tell what happened, not what will: to a question about the future (a
   forecast, tomorrow, next month), say first that the data cannot tell it, then give the past figures
   that help (the same weekday of the last weeks) as past figures, never one figure as what will happen.
   Groups that add up to more than the total hold rows counted in several groups (a field with several
   values in a row); less than the total, rows without a value: say which only when a query shows it.
6. Know what the question means before you query: the team's words, the memory, the learned answers and
   the chat decide first. If a word can still mean two things in the data that give different numbers
   (two fields or metrics that fit, a term nobody defined, a period that is not said and has no usual
   default), do not guess: answer only with ONE short question naming the readings you see (the field or
   metric of each) and the one you would take, and stop there. Otherwise answer, and when you chose a
   reading say it in one line at the start, naming the other one the data has. Never ask what the
   question, the team's words or the chat already say."""

RICH = """
7. The chat page shows the rows of every query you run (execute_sql, promql_query) under your answer as a
   table and a chart that the user can switch, copy and download: to show a chart or a time series, run
   the query; never draw charts in text and never make an image unless asked. Give the key figures in one
   or two sentences, at most a 10-row Markdown table, and the SQL you ran. Files and images you make
   appear under your answer by themselves: never write their paths, links or Markdown images."""

PLAIN = """
7. Report requests: run the SQL, then answer with one or two sentences and a Markdown table (at most 30
   rows); for a ranking or a time series also call show_chart and put its output in the answer. Give the
   SQL you ran."""

OSAGG_RULES = """

SQL on OpenSearch (osagg), not a full SQL engine: OpenSearch runs the filters and the GROUP BY /
aggregates, and only their small result is post-processed. Table = index name; field names are case
sensitive and double-quoted ("APPLICATION", "@timestamp_date"). Write only queries it can push down:
  * one index, WHERE filters (=, IN, <, >, BETWEEN, LIKE, IS NULL) on single fields, joined with AND / OR,
    with a time range; pairs of values: ("A" = 'x' AND "B" = 'y') OR (...), never ("A", "B") IN (...) nor
    an expression over several fields;
  * aggregates (COUNT, SUM, AVG, MIN, MAX, COUNT(DISTINCT), percentiles) with GROUP BY on fields or on
    DATE_TRUNC of the timestamp; the latest of each key = GROUP BY the key with MAX of the timestamp (not
    ROW_NUMBER() and not a self-join);
  * a row list: filtered, with ORDER BY and a LIMIT (at most 1000);
  * a JOIN only in an aggregating query, on equal fields, each index filtered to at most 100,000
    documents; ORDER BY, HAVING, window functions, WITH and UNION only on top of aggregated rows. A definition
    that relates two indices ("the payments of those invoices") is such a JOIN on their key, the period on the
    first one: not each index filtered on its own dates.
Never put a row list of an index in a subquery, a WITH or a join: work in steps (one query for the few
keys you need, then WHERE key IN (those values)). Two periods (a week and the week before): one query
per period, or GROUP BY DATE_TRUNC('day' or 'week', the time field); never CASE on the time field. An error saying the query "could not be fully pushed
down" means: rewrite it that way, do not run it again. A date or a period in the question ("on 23
September", "last week") filters the index's time field (the one the dictionary names); business dates
only when the question says so (position date, business date, D-1, W-1). Business dates: "POSITION_DATE" (yyyymmdd),
"POSITION_LABEL" (D, D-1, W-1, Y-1...) and "POSITION_TIME" (execution time moved onto the D-1 position
date) are columns when the index has them; filter labels with "POSITION_LABEL" IN ('D-1', 'W-1')."""

PROMAGG_RULES = """

SQL on metrics (promagg), turned into PromQL, not a full SQL engine: one table per metric; columns ts, one
column per label, value, and for counters rate / increase. One metric table per query, no JOIN of metric
tables row by row, no WITH, window function or subquery over raw samples, no quantile of raw samples
(QUANTILE_OVER_TIME or a histogram), no GROUP BY or WHERE on the sample value (HAVING). Always filter ts on
a time range and GROUP BY a time bucket (DATE_TRUNC('hour', ts)). Counters: SUM(rate) = per second,
SUM(increase) = count, never SUM or AVG of value; gauges: AVG(value), MIN(value), MAX(value); histograms
(*_bucket tables): HISTOGRAM_QUANTILE(0.95, SUM(RATE(value))); a condition on one label:
SUM(rate) FILTER (WHERE mode <> 'idle'); CPU usage = busy %: 100 * SUM(rate) FILTER (WHERE mode <> 'idle') /
SUM(rate) (SUM(rate) of every mode is the number of cores). Which servers had samples: GROUP BY node, COUNT(*).
Tenants (Mimir): a database over several tenants has a column __tenant_id__, and each tenant is usually a
different application or subject: a question about one filters on its tenant (WHERE __tenant_id__ = '...'),
a comparison groups by it, values of different tenants are never added up unless asked, and the answer
names the tenants it covers. Two metrics together: aggregate each one in its own query, or promql_query
(arithmetic between metrics, offsets, label_replace)."""

SECTIONS = {
    "charts": """

Saving Superset charts and dashboards (asked here): check the fields with get_chart_type_schema, then call
generate_chart once with save_chart=true and the requested chart_name; a tool error tells you exactly what
to fix. Use only the dataset's column names. COUNT(*) is the dataset's saved metric "count":
{"name": "count", "saved_metric": true}. Ratios, percentiles and conditional counts cannot be written in a
chart's fields: use the dataset's saved metrics (get_dataset_info lists them), or save the query that
computed the value as a dataset with create_virtual_dataset (a PromQL finding, on its promagg database:
SELECT ts, <its labels>, value FROM promql('<the PromQL>') WHERE ts >= TIMESTAMP '<start>' AND ts <
TIMESTAMP '<end>') and chart that dataset: x = its time column, y = AVG of its value column, group_by its
labels. The dates are in the dataset's SQL: a chart config has no time_range field. A chart of an earlier
finding uses the queries listed for that answer, with their time window. To change a saved chart call update_chart with its id instead of
creating another one. Chart filters are fixed values (no rolling time range): turn "last 7 days" into dates
from "now"; a POSITION_LABEL filter and a date filter must not contradict each other. Charts cannot compare
with an earlier period: to compare position dates use X = POSITION_TIME grouped by POSITION_LABEL. The chart
under your answer in the chat is not saved in Superset: save with generate_chart / generate_dashboard.
A dashboard of several charts: make each chart at once (a query first only when a field or a value is not
known), then generate_dashboard with their ids; do not spend calls re-checking the data. Name every saved chart
with what it shows and its period ("<what it shows> - <its period>"), never twice the same name.""",
    "status": """

What is happening now ("in production", "with <an application>", "on <a metric, a chart or a dashboard>", "is
everything normal"): 1) find the dashboards and charts about the subject (the knowledge found names them, with
their ids; else list_dashboards / list_charts), 2) chart_anomalies on that dashboard or chart: what the nightly
look found on each chart (its last full day against the same weekday of the 4 weeks before; data that stopped);
look_now=true to look again now, 3) read their latest data (get_chart_data), the team's checks with their limits
(check_health) and the alerts firing (list_alerts), and compare with the usual (compare_to_usual: the same window
of the previous weeks), 4) answer subject by subject: normal or not, with the value, the usual, the limit and
since when, and a screenshot of a chart that shows a problem (chart_image) when one is found. Say what could not
be checked and the day the look compared; "nothing unusual" only when it was checked.""",
    "sqllab": """

SQL Lab and Explore (asked here): save_sql_query saves a query in SQL Lab's Saved Queries (database_id, sql, a
label); open_sql_lab_with_context gives a link that opens SQL Lab with a query ready (database_connection_id,
sql, title); generate_explore_link gives a link to explore a dataset with a chart config, nothing saved
(dataset_id, config as for generate_chart). Save or open the query that gave the finding the user means (the
queries of the chat's earlier answers are listed with the question), and give the link or the saved query's
name.""",
    "investigation": """

Investigations ("why is ... late, slow, failing", "what happened", "find the cause"): work in this order.
1) The facts, in one call: compare_groups on the question's table with its scope (the parts it names: "The system
   around this question" lists them; the environment; the business date when there is one) and no measure. It
   compares every measure with the same time of the earlier days (the usual) and gives it on the team's reference
   days (yesterday, a week ago, weeks ago; against = [...] for the days the question names: "than last month"),
   and says which is off and on which values: each duration against its usual, the volumes, and the stages of
   the rows in their order (the table's time fields: how many rows had reached each by now, how long after the
   one before, how many wait). start: when what is looked at began (today's rows: midnight today), end: now.
   Never compare days with queries of your own, nor count again what it gave. If it answers with an error, fix
   the call as the error says and make it again: it is the base of everything after. If nothing stands out,
   against the usual and against the older reference days, say so with its figures and stop.
2) Read it in the order of the stages: the first that is clearly off says what kind of problem it is (its
   description says what a row waits for there); fewer rows at the stages after it are its wake, but a stage it
   says is off on its own (the rows take longer once there) is a second finding: explain each. Late before
   it could start: it waited for what it depends on (look at those: what feeds it, what runs before it). Ready
   but waiting: it waits for a capacity (a slot, a token, a queue): who holds it is in the same result,
   outside_the_scope (the rows outside the question's scope there: more than usual, and whose) and
   the_rows_there (the same comparison over every row there: what lasts longer, and where). Started but longer:
   where (the same call on the table of its steps; the servers; the version; the volume processed). The field
   named first is where the change is concentrated. A figure as usual against the last days and far from an
   older reference day is a change older than those days: look at what changed between the two.
3) Why, from what stands out: the records compare_groups gives under "related" (the changes made to that
   application, the alerts of those servers); what it depends on, runs on, reads or calls in the system picture
   (system_links for any part) and the health of those servers or services in that window (check_health with
   entities = their names) and their logs (compare_logs: what they say that they do not usually); the changes
   recorded before it started (records_about with the parts you blame, not only the applications asked); what
   the team wrote of such a day (memory, documents, notes: a month end). A level is a finding only against its usual:
   promql_query says whether each series is "as on the previous days" (a pool that is full every night, a queue
   as long as every night are not what changed), check_health marks the breaches that happen on most days.
4) Check a cause before naming it: it must concern the same rows (those servers, that step, that application)
   and the same time, and what is not affected must be free of it. What else happened and does not match (an
   alert on a server those rows did not use, a release of an application whose other rows are on time, an input
   they do not read, a level or a breach that is usual, a known effect of another size) is not the cause: say in
   one line that it was ruled out, and why. A day the team documented, with the effect it documented, is the
   explanation: say it is expected.
5) Answer: what is wrong with its figures against usual (and against the reference days when they say more),
   where, since when, the cause with the record or the figure that shows it, what it delays, what was ruled out,
   and what you could not check.""",
    "usual": """

Unusual or not (asked here): compare_to_usual(promql, start, end) compares the window with the same window
of the previous weeks and gives a verdict per series; use it rather than judging a number alone.""",
    "notes": """

Notes (asked here): the users' notes (what a meeting decided, a fact to keep). search_notes finds them (words,
days; mine=true: the user's own), read_note gives one in full. A note is its author's, not verified: say whose
and of which day; never a team rule, never a query's condition. Write or change one only when the user asks:
add_note (for the team, unless they say it is for them: "my note", "for me", "personal", "private"; its day when
they say it; their words, nothing added), change_note (add_text adds to it, text replaces it, undo=true puts back
the version before the last change; the user's own notes, an admin's for the team's ones). Say what was saved or
changed: its title and for whom. To delete one: find it, show it (title, author, day), ask whether to delete it
and stop; call delete_note with confirmed=true only in the answer to their yes.""",
    "files": """

Files, e-mails and reports (asked here): a file or Excel extract -> export_excel (every matching row: no
LIMIT unless the user asks for the first N; only there a row list may join the big index with small ones,
e.g. jobs with their application's TEAM); an e-mail now -> send_email
(body_markdown, sql for a table, chart_sqls or image_paths for images, excel_sql or attach_paths for the
Excel file); a recurring e-mail -> create_report. JSON asked -> answer with the rows as a ```json block
only.""",
    "images": """

Images (asked here): an image of data -> chart_from_sql (a SELECT: label column then value columns; bar =
ranking, line = time series); an image of a saved Superset chart or dashboard -> chart_image(chart_id or
dashboard_id).""",
}

INTENTS = {
    "charts": re.compile(r"\bdashboards?\b|tableau de bord|\bsuperset\b[^.?!\n]{0,40}\b(chart|graph|graphique)|"
                         r"\b(saved?|create|creer|cr[ée]e|build|update|modif\w*|enregistr\w*|edit)\b[^.?!\n]{0,50}"
                         r"\b(chart|graph|graphique)|\bchart (id|#)\s*\d+|\bexisting (chart|dashboard)", re.I),
    "investigation": re.compile(r"\b(why|cause|reason|root cause|saturat\w*|incident|slow\w*|degrad\w*|outage|"
                                r"investigat\w*|diagnos\w*|troubleshoot\w*|what (has |have )?happened|"
                                r"what explains?|pourquoi|raison|lent\w*|panne|que s'est-il pass[ée])\b", re.I),
    "files": re.compile(r"\b(excel|xlsx|csv|extract\w*|export\w*|file|fichier|download|t[ée]l[ée]charg\w*|mail\w*|"
                        r"e-mail|envoi\w*|send|report\w*|rapport|schedul\w*|every (day|week|morning|monday)|"
                        r"chaque|tous les|quotidien|hebdo\w*|json)\b", re.I),
    "images": re.compile(r"\b(image|images|png|picture|photo|screenshot|capture|mail\w*|e-mail)\b", re.I),
    "usual": re.compile(r"\b(usual|unusual|abnormal\w*|anomal\w*|normal|baseline|habitu\w*|inhabituel\w*|"
                        r"anormal\w*)\b|\bcompared? (to|with) (last|previous|the same)|\bthan (usual|normal|last week)",
                        re.I),
    "status": re.compile(r"\bwhat('?s| is| are) (happening|going on|wrong)\b|\b(status|state|health) of\b|"
                         r"\bwhat('?s| is) the (status|state|health)\b|\bhealthy\b|"
                         r"\bany (issues?|problems?|incidents?|anomal\w*|alerts?)\b|\bis (everything|all|it|that) (ok|"
                         r"fine|normal|good|healthy)\b|\b(right now|happening now|currently|at the moment)\b|"
                         r"\bque se passe|\ben ce moment\b|\bactuellement\b|\best-ce (normal|grave)\b|"
                         r"\bdes (probl[èe]mes?|incidents?|alertes?)\b", re.I),
    "read_charts": re.compile(r"\b(chart|graph|dashboard)\s*(id\s*)?#?\s*\d+\b|\b(saved|existing|superset) "
                              r"(charts?|dashboards?)\b|\bwhat (does|do|is in) (the|this|that|my) (chart|dashboard)\b|"
                              r"\b(numbers|data|values) (of|in|behind) (the|this|that|its) (charts?|dashboards?)\b|"
                              r"\b(what|which|list|show)\b[^.?!\n]{0,20}\b(charts|graphs|graphiques)\b|"
                              r"\bcharts? (are|is) (in|on)\b|\b(its|their) charts\b|\bthe charts (of|in|on)\b|"
                              r"\bquels graphiques\b|\bles graphiques (du|de|des)\b", re.I),
    "history": re.compile(r"\b(last time|as before|like before|the other day|you (told|gave|said|showed|sent) me|"
                          r"(i|we) (already )?(asked|requested|looked at|checked)\b[^.?!\n]{0,40}\b(before|earlier|last|"
                          r"yesterday|previously|already)|(previous|earlier|past|old) (chats?|conversations?|questions?|"
                          r"answers?))\b|\b(la derni[èe]re fois|comme (avant|la derni[èe]re fois)|d[ée]j[àa] demand[ée]|"
                          r"tu m'as (dit|donn[ée]|montr[ée]|envoy[ée])|(anciennes?|pr[ée]c[ée]dentes?) "
                          r"(conversations?|questions?|r[ée]ponses?))\b", re.I),
    "notes": re.compile(r"\b(notes?|meetings?|minutes of|stand-?ups?|decided|decisions?|agreed|we (said|noted)|"
                       r"(write|jot|put) (it |this |that )?down|r[ée]unions?|compte[- ]rendu|d[ée]cid[ée]e?s?|"
                       r"on a (dit|not[ée])|not(er|ez)|prends? note)\b", re.I),
    "sqllab": re.compile(r"\bsql ?lab\b|\bsaved? (it|this|that|the|my|as)?\s*(sql|query|queries|requ[êe]te)\b|"
                         r"\bexplore\b|\bexplorer\b|\b(link|lien|url)\b|\bopen (it|this|that|the (query|sql))\b|"
                         r"\bouvr\w+ (la|cette) requ[êe]te\b", re.I),
}
TOOLS_OF = {
    "charts": {"get_chart_type_schema", "generate_chart", "update_chart", "update_chart_preview", "list_charts",
               "get_chart_info", "generate_dashboard", "add_chart_to_existing_dashboard", "list_dashboards",
               "get_dashboard_info", "fix_chart_time_range", "chart_image", "create_virtual_dataset", "get_chart_data"},
    "files": {"export_excel", "send_email", "create_report", "list_reports"},
    "images": {"chart_from_sql", "chart_image"},
    "usual": {"compare_to_usual", "chart_anomalies", "compare_groups", "compare_logs"},
    "sqllab": {"save_sql_query", "open_sql_lab_with_context", "generate_explore_link"},
    "read_charts": {"get_chart_data", "get_chart_info", "list_charts", "list_dashboards", "get_dashboard_info",
                    "chart_image", "chart_anomalies"},
    "status": {"get_chart_data", "get_chart_info", "list_charts", "list_dashboards", "get_dashboard_info",
               "chart_image", "compare_to_usual", "chart_anomalies", "compare_groups", "compare_logs", "system_links"},
    "investigation": {"compare_to_usual", "chart_anomalies", "search_notes", "compare_groups", "compare_logs",
                      "system_links", "records_about"},
    "system": {"system_links", "records_about"},
    "history": {"search_my_chats"},
    "notes": {"search_notes", "read_note", "add_note", "change_note", "delete_note"},
}
INTENT_TOOLS = set().union(*TOOLS_OF.values())


def g_user() -> Any:
    """The current user (flask.g), or None outside a request."""
    try:
        from flask import g

        return getattr(g, "user", None)
    except Exception:  # pylint: disable=broad-except
        return None


def intents(question: str) -> set[str]:
    return {k for k, rx in INTENTS.items() if rx.search(question or "")}


# "that finding", "the same", "ce résultat": the question is about an earlier answer
REFERS_BACK = re.compile(
    r"\b(that|these|those|it|them|same|above|previous|earlier|findings?|results?)\b|"
    r"\bthis\b(?!\s+(week|month|year|morning|afternoon|evening|night|quarter)\b)|"
    r"\b(cela|ça|celui|celle|ceux|m[êe]mes?|pr[ée]c[ée]dente?s?|ci-dessus|r[ée]sultats?|trouvailles?)\b|"
    r"\b(cet|cette|ces)\b(?!\s+(semaine|ann[ée]e|matin|nuit|apr[èe]s-midi)\b)|"
    r"\bce\s+(graphique|chiffre|r[ée]sultat|tableau|calcul|constat)|"
    # "the ratio of the first to the second", "the former", "both of them": earlier answers by their place (a probe
    # question was routed to a new subject and computed a temperature over a latency)
    r"\bthe (?:first|second)(?: one)? (?:to|and|vs\.?|versus|over|divided by|compared (?:to|with)|minus) the "
    r"(?:first|second|other)\b|\bthe (?:former|latter)\b|\b(?:both|the two) (?:of them|figures|values|numbers|"
    r"results|answers)\b|\b(?:le|du|au) premier\b[^?.]{0,20}\b(?:au|et|sur|par rapport au|du) (?:le )?second\b|"
    r"\bles deux (?:chiffres|valeurs|r[ée]sultats|nombres)\b|\b(?:ce dernier|cette derni[èe]re)\b", re.I)


# "What was its failure rate?", "And their notional?", "Quel est son taux ?": a possessive with nothing before it that
# it could stand for refers to the answer before; "Which servers exceeded their limit?" has its own antecedent
POSSESSIVE = re.compile(r"\b(its|their|son|sa|ses|leur|leurs)\b", re.I)
LEAD_WORDS = frozenset(
    "what was were is are and also then so how about much many did does do which where when why who the of for in on at "
    "to with by a an has had have et aussi alors quel quelle quels quelles est était sont étaient combien de du des le la "
    "les a-t-il ont avait".split())


def refers_back(question: str) -> bool:
    text = question or ""
    if REFERS_BACK.search(text):
        return True
    m = POSSESSIVE.search(text)
    return bool(m) and all(w in LEAD_WORDS for w in re.findall(r"[a-zà-ÿ'-]+", text[:m.start()].lower()))


def queries_note(history: list[dict] | None) -> str:
    """What the last answers of the chat were computed from: the queries that ran and gave their
    rows, with their database and time window (runner.queries_of), each under the question it
    answered. Given with the new question (never inside the earlier answers: the LLM would copy
    it into its own). A query only written in an answer's text did not run."""
    lines = []
    asked = ""
    for h in history or []:
        if h.get("role") == "user":
            asked = " ".join(str(h.get("content") or "").split())[:160]
        elif h.get("queries"):
            lines.append(f'- the answer to "{asked}":')
            lines += ["  " + line for line in _query_lines(h["queries"])]
    if not lines:
        return ""
    return ("What the last answers of this chat were computed from (for a question about them; a query only "
            "written in an answer's text did not run; do not repeat this list):\n" + "\n".join(lines))


def _query_lines(queries: list[dict]) -> list[str]:
    lines = []
    for q in queries or []:
        where = f" on database {q['database']!r}" if q.get("database") else ""
        if q.get("database_id"):
            where += f" (id {q['database_id']})"
        window = f", from {q['start']} to {q['end']}" if q.get("start") and q.get("end") else ""
        if window and q.get("step"):
            window += f", step {q['step']}"
        cols = f" -> columns {', '.join(map(str, q.get('columns') or []))}" if q.get("columns") else ""
        lines.append(f"{q.get('tool')}{where}{window}: {q.get('query')}{cols}")
    return lines


CHART_TOOLS = ("generate_chart", "update_chart", "update_chart_preview")
REF_FIELDS = {"name", "column_name", "label", "dtype", "aggregate", "saved_metric"}
RUNNABLE_AGGREGATES = {"SUM", "COUNT", "AVG", "MIN", "MAX", "COUNT_DISTINCT"}


LANGS = {
    "English": set("the and of to in is are what which how many much per by give show me for with from today "
                   "yesterday last this that were was did does do there any all top most least between".split()),
    "French": set("le la les des du de et est sont quel quelle quels quelles combien par pour avec aujourd hui "
                  "hier dernier derniers dernière cette ces qui que quoi donne donnez moi montre montrez entre "
                  "au aux sur dans une un plus moins".split()),
}
ANSWER_IN = {"English": "Answer in English.", "French": "Réponds en français."}


def question_language(text: str) -> str | None:
    """English or French from the common words of the question (None when unclear)."""
    ws = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", (text or "").lower())
    scores = {lang: sum(1 for w in ws if w in vocab) for lang, vocab in LANGS.items()}
    best = max(scores, key=scores.get)
    others = [v for k, v in scores.items() if k != best]
    return best if scores[best] >= 2 and scores[best] > max(others, default=0) else None


def now() -> dt.datetime:
    fixed = (settings.get("agent.now") or "").strip()
    return dt.datetime.fromisoformat(fixed) if fixed else dt.datetime.now()


def _short_error(ex: Exception) -> str:
    lines = [ln.strip() for ln in str(ex).splitlines()[1:]]
    return "\n".join(ln for ln in lines if ln and not ln.startswith("For further information"))[:1500]


def _sort_entries(values: list) -> list:
    """Table sort_by "col DESC" / "-col" / "col" -> Superset's ["col", ascending] entries."""
    out = []
    for v in values:
        if isinstance(v, (list, tuple)) and len(v) == 2 and isinstance(v[0], str):
            out.append(json.dumps([v[0], bool(v[1])]))
            continue
        if not isinstance(v, str) or v.lstrip().startswith("["):
            out.append(v)
            continue
        text = v.strip()
        desc = text.startswith("-") or text.upper().endswith(" DESC")
        col = text.lstrip("-").strip()
        for suffix in (" DESC", " ASC", " desc", " asc"):
            if col.endswith(suffix):
                col = col[: -len(suffix)].strip()
        out.append(json.dumps([col, not desc]))
    return out


def _refs(node: Any, path: str = "") -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    if isinstance(node, dict):
        if isinstance(node.get("name"), str) or isinstance(node.get("column"), str):
            out.append((path or "config", node))
        for k, v in node.items():
            if k not in ("x_axis", "y_axis", "legend"):
                out.extend(_refs(v, f"{path}.{k}" if path else k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.extend(_refs(v, f"{path}[{i}]"))
    return out


CONFIG_NAME = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_\s\-.]*$")     # a column name Superset's chart config accepts
PERIOD = re.compile(rf"\b(\d{{1,2}}(?:st|nd|rd|th|er)?\s+(?:of\s+)?{MONTH}|{MONTH}\s+\d{{1,2}}|\d{{4}}-\d{{2}}-\d{{2}}|"
                    r"yesterday|today|tonight|this (?:week|month|morning|night)|"
                    r"last \d+ (?:hours?|days?|weeks?|months?)|hier|aujourd'hui|cette (?:nuit|semaine)|"
                    r"\d+ derni[eè]res? (?:heures|jours|semaines))\b", re.I)


class ChartGuard:
    def __init__(self, agent: "Agent") -> None:
        self.agent = agent
        self.datasets: dict[str, tuple[set[str], set[str]]] = {}
        self.saved: dict[str, int] = {}
        self.dataset_of: dict[int, Any] = {}
        try:
            from superset.mcp_service.chart.schemas import parse_chart_config

            self.parse: Callable[[dict], Any] | None = parse_chart_config
        except Exception:  # pylint: disable=broad-except
            self.parse = None

    def _dataset(self, ident: Any) -> tuple[set[str], set[str]] | None:
        from supagent.tools_superset import DatasetInfoRequest, get_dataset_info

        key = str(ident)
        if key not in self.datasets:
            try:
                info = get_dataset_info(DatasetInfoRequest(identifier=int(ident)))
            except Exception:  # pylint: disable=broad-except
                return None
            if info.get("error"):
                return None
            self.datasets[key] = ({c["column_name"] for c in info.get("columns") or []},
                                  {m["metric_name"] for m in info.get("metrics") or []})
        return self.datasets[key]

    def _check(self, config: dict, cols: set[str] | None, metrics: set[str] | None) -> list[str]:
        errors = []
        for where, ref in _refs(config):
            if isinstance(ref.get("column"), str) and "name" not in ref:
                if cols is not None and ref["column"] not in cols:
                    errors.append(f"{where}: unknown column '{ref['column']}'")
                continue
            name = ref["name"]
            extra = sorted(set(ref) - REF_FIELDS)
            if extra:
                errors.append(f"{where}: {', '.join(extra)} is not a chart field (a column takes only "
                              "name, label, aggregate or saved_metric; SQL expressions are not possible)")
            agg = str(ref.get("aggregate") or "").upper()
            if agg and agg not in RUNNABLE_AGGREGATES:
                errors.append(f"{where}: Superset cannot run {agg} in these charts (only "
                              f"{', '.join(sorted(RUNNABLE_AGGREGATES))}); use a saved metric of the "
                              f"dataset if one fits ({', '.join(sorted(metrics or [])) or 'none'}), "
                              "otherwise say it is not possible")
            if cols is None:
                continue
            if ref.get("saved_metric"):
                if name not in (metrics or set()):
                    errors.append(f"{where}: '{name}' is not a saved metric (saved metrics: "
                                  f"{', '.join(sorted(metrics or []))})")
            elif name in cols:
                continue
            elif name in (metrics or set()):
                errors.append(f'{where}: "{name}" is a saved metric: use {{"name": "{name}", "saved_metric": true}}')
            elif name.lower() in ("count", "*", "count(*)", "rows", "jobs"):
                errors.append(f"{where}: there is no column '{name}'; COUNT(*) is "
                              + ('{"name": "count", "saved_metric": true}' if "count" in (metrics or set())
                                 else "COUNT of a column that is never empty"))
            else:
                errors.append(f"{where}: unknown column '{name}' (columns: {', '.join(sorted(cols))[:800]})")
        return errors

    def _not_used(self, dataset_id: Any, config: dict) -> list[str]:
        """Chart fields the team said not to use (their description), on this dataset's table."""
        from superset.connectors.sqla.models import SqlaTable
        from superset.extensions import db

        from supagent.knowledge.excluded import of_table, violations

        try:
            ds = db.session.get(SqlaTable, int(dataset_id))
        except (TypeError, ValueError):
            return []
        if ds is None:
            return []
        if ds.sql:                                       # a virtual dataset: its query
            return [f"this dataset uses {p}" for p in violations([ds.sql])]
        banned = {x["name"]: x["why"] for x in of_table(ds.database_id, ds.table_name)}
        return [f"{where}: the team marked \"{ref['name']}\" as not to be used (\"{banned[ref['name']]}\"): "
                "use another field" for where, ref in _refs(config)
                if isinstance(ref.get("name"), str) and ref["name"] in banned]

    def _period_missing(self, dataset_id: Any, config: dict) -> list[str]:
        """The question is about a period and the chart, on a table (not a query with its dates), has no
        filter on the table's time column: it would show every date while the answer speaks of one."""
        from superset.connectors.sqla.models import SqlaTable
        from superset.extensions import db

        question = getattr(self.agent, "question", "") or ""
        if not PERIOD.search(question):
            return []
        try:
            ds = db.session.get(SqlaTable, int(dataset_id))
        except (TypeError, ValueError):
            return []
        if ds is None or (ds.sql or "").strip():           # a virtual dataset: the dates are in its SQL
            return []
        times = {c.column_name for c in ds.columns if c.is_dttm} | ({ds.main_dttm_col} if ds.main_dttm_col else set())
        if not times:
            return []
        used = {f.get("column") for f in config.get("filters") or [] if isinstance(f, dict)}
        if used & times:
            return []
        col = ds.main_dttm_col or sorted(times)[0]
        if not CONFIG_NAME.match(col):                  # "@timestamp_date": a chart filter cannot name it
            return [f'the question is about a period, and this chart would show every date: its time column "{col}" '
                    "cannot be used in a chart filter. Save the query of the finding, with its dates in the WHERE, as a "
                    "dataset (create_virtual_dataset) and chart that dataset"]
        return [f'the question is about a period, and this chart has no filter on the time column "{col}": it '
                f'would show every date. Add the period of the question as two filters: {{"column": "{col}", "op": '
                f'">=", "value": "<start of the period, YYYY-MM-DD HH:MM>"}} and {{"column": "{col}", "op": "<", '
                '"value": "<end of the period>"}} (dates from the question and from now)']

    def shows(self, chart_id: Any) -> str:
        """What a saved chart returns now (rows, first ones): the answer describes that chart, not the
        intent (a row limit a chart type ignores, a filter that did not apply). A question for the top
        N of something and a chart that shows more of them: said, with what to do."""
        if not getattr(getattr(self.agent, "superset", None), "available", False):
            return ""
        try:
            text = self.agent.superset.call("get_chart_data", {"request": {"identifier": int(chart_id), "limit": 1000}})
            data = json.loads(text)
        except Exception:  # pylint: disable=broad-except
            return ""
        rows = data.get("data") or data.get("rows") or []
        total = data.get("row_count") or data.get("total_rows") or len(rows)
        if not isinstance(rows, list):
            return ""
        first = "; ".join(", ".join(f"{k}={v}" for k, v in list(r.items())[:4]) if isinstance(r, dict) else str(r)
                          for r in rows[:5])
        out = f"\n(the saved chart {chart_id} returns {total} row(s) now; first: {first[:600]})"
        column, count = categories(rows)
        wanted = wanted_top(column or "", top_n(getattr(self.agent, "question", "") or ""))
        if wanted and column and count > wanted:
            out += (f"\n(NOT DONE: the question asks for {wanted} and this chart shows {count} {column} values: a row "
                    f"limit does not cut the categories of this chart type. Save the query that keeps the top {wanted} "
                    f"(ORDER BY the measure DESC LIMIT {wanted}) as a dataset with create_virtual_dataset and chart "
                    "that dataset, or say that it could not be done: never say it shows the top "
                    f"{wanted}.)")
        return out

    def _dry_run(self, dataset_id: Any, config: dict) -> str | None:
        text = self.agent.superset.call("generate_chart", {"request": {
            "dataset_id": dataset_id, "config": config, "save_chart": False, "preview_formats": ["table"]}})
        try:
            data = json.loads(text)
        except ValueError:
            return None
        if data.get("success") is False or data.get("error"):
            return json.dumps({"success": False, "error": "the chart query fails, nothing was saved",
                               "details": data.get("error")}, ensure_ascii=False, default=str)[:3000]
        if ((data.get("previews") or {}).get("table") or {}).get("row_count") == 0:
            return json.dumps({"success": False, "error": "the chart returns NO ROWS with these filters, "
                               "nothing was saved: use dates that exist in the data, and labels "
                               "that agree with the dates, then call again"})
        return None

    def before(self, name: str, args: dict) -> tuple[str, dict, str | None]:
        req = args.get("request", args)
        if name not in CHART_TOOLS or not isinstance(req, dict):
            return name, args, None
        if name == "update_chart" and "generate_preview" not in req and \
                not PREVIEW_ASK.search(getattr(self.agent, "question", "") or ""):
            req["generate_preview"] = False            # "make it a pie chart": the saved chart changes (Superset's
            #                                            default is an unsaved preview the answer then calls "updated")
        if name == "update_chart" and req.get("dataset_id") is not None:
            return name, args, json.dumps({"success": False, "error": "update_chart cannot change the dataset of a chart "
                                           "(it would keep the old one and its dates). Make a new chart on the new "
                                           "dataset (generate_chart with a chart_name), put it on the dashboard "
                                           "(add_chart_to_existing_dashboard), and say that it is a new chart"})
        config = req.get("config")
        if isinstance(config, dict) and config.get("chart_type") == "table":
            for key in ("sort_by", "order_by_cols", "order_by"):
                if isinstance(config.get(key), list):
                    config[key] = _sort_entries(config[key])
        if isinstance(config, dict):
            errors = []
            if self.parse is not None:
                try:
                    self.parse(copy.deepcopy(config))
                except Exception as ex:  # pylint: disable=broad-except
                    errors.append(_short_error(ex))
            ds = req.get("dataset_id") if name == "generate_chart" else self.dataset_of.get(req.get("identifier"))
            known = self._dataset(ds) if ds is not None and not errors else None
            x = config.get("x") if isinstance(config.get("x"), dict) else {}
            if known and x.get("name") == "ts" and {"ts", "value"} <= known[0] and not config.get("time_grain"):
                config["time_grain"] = "PT1H"      # metrics (promagg): time buckets, never raw samples
            if not errors:
                errors += self._check(config, *(known or (None, None)))
            if not errors and ds is not None:
                errors += self._not_used(ds, config)
            saving_now = (name == "generate_chart" and req.get("save_chart")) or name == "update_chart"
            if not errors and ds is not None and saving_now:
                errors += self._period_missing(ds, config)
            if not errors and name == "generate_chart" and req.get("save_chart") and \
                    not str(req.get("chart_name") or "").strip():
                named = name_asked(getattr(self.agent, "question", "") or "")
                if named:                              # "save it as 'X'": the name the user gave (a model that left
                    req["chart_name"] = named          # it out sent the same call again and again)
                else:
                    errors.append("a saved chart needs a chart_name that says what it shows and its period (Superset's "
                                  "automatic names repeat: \"Sum(x) by y\" for two different charts)")
            if errors and "create_virtual_dataset" in self.agent.names and any(
                    k in e for e in errors for k in ("unknown column", "is not a saved metric", "cannot run")):
                errors.append("a calculation (a percentage, a ratio, PromQL) is not a field of this dataset: save "
                              "the query of the finding with create_virtual_dataset, then chart the new dataset")
            if errors:
                return name, args, json.dumps({"success": False, "error": "invalid chart config: fix these points "
                                               "and call the tool again", "details": errors}, ensure_ascii=False)
            saving = (name == "generate_chart" and req.get("save_chart")) or (
                name == "update_chart" and req.get("generate_preview") is False)
            if saving and ds is not None:
                problem = self._dry_run(ds, config)
                if problem:
                    return name, args, problem
        chart_name = req.get("chart_name")
        if name == "generate_chart" and req.get("save_chart") and chart_name in self.saved:
            return "update_chart", {"request": {"identifier": self.saved[chart_name], "config": config,
                                                "chart_name": chart_name, "generate_preview": False}}, None
        return name, args, None

    def after(self, name: str, args: dict, content: str) -> str:
        from supagent.tools import fix_chart_time_range

        if name not in CHART_TOOLS:
            return content
        try:
            data = json.loads(content)
        except ValueError:
            return content
        chart = data.get("chart") or {}
        if chart.get("is_unsaved_state"):
            content += ("\n(NOT SAVED: this is an unsaved preview of the change, the saved chart is unchanged. To change "
                        "the saved chart, call update_chart again with generate_preview false; otherwise tell the user "
                        "it is a preview to open, not a change.)")
        if chart.get("id") and chart.get("slice_name"):
            self.saved[chart["slice_name"]] = chart["id"]
            ds = args.get("request", args).get("dataset_id")
            if ds is not None:
                self.dataset_of[chart["id"]] = ds
            try:
                fixed = fix_chart_time_range(int(chart["id"]))
            except Exception:  # pylint: disable=broad-except
                fixed = {}
            if fixed.get("time_range"):
                content += f"\n(the date filters were saved as the chart's time range: {fixed['time_range']})"
        chart_id = chart.get("id") or (args.get("request", args).get("identifier") if name == "update_chart" else None)
        if chart_id and data.get("success") is not False and not data.get("error"):
            try:                                        # its data API, CSV and text reports work
                from supagent.tools import refresh_query_context

                # a chart made in Explore keeps its own (pivots...), unless this answer saved it
                refresh_query_context(int(chart_id), keep_existing=name == "update_chart"
                                      and int(chart_id) not in self.saved.values())
            except Exception:  # pylint: disable=broad-except
                log.warning("supagent: query context of chart %s not written", chart_id, exc_info=True)
            content += self.shows(chart_id)
        return content


TOP_N = re.compile(r"\b(?:top|only(?:\s+the)?|just(?:\s+the)?|the|les)\s+(\d{1,3})\s+(?:(?:most|least|biggest|"
                   r"largest|highest|lowest|busiest|slowest|fastest|worst|best|plus)\s+)?([A-Za-z\u00C0-\u00FF_]+)", re.I)
TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}|^\d{10,13}$")


def top_n(question: str) -> list[tuple[int, set[str]]]:
    """(N, the words of what is counted) of "the 5 applications with the most failures", "the 5 busiest
    servers" (a server is also a node, a host)."""
    from supagent.knowledge.describe import stem
    from supagent.knowledge.resolve import SYNONYMS

    out = []
    for m in TOP_N.finditer(question or ""):
        word = stem(m.group(2).lower())
        out.append((int(m.group(1)), {word} | SYNONYMS.get(word, set())))
    return out


def categories(rows: list) -> tuple[str | None, int]:
    """The column of a chart's rows that holds categories (text, not a time) and how many it shows."""
    best: tuple[str | None, int] = (None, 0)
    if not rows or not isinstance(rows[0], dict):
        return best
    for col in rows[0]:
        vals = {str(r.get(col)) for r in rows if isinstance(r, dict) and isinstance(r.get(col), str)}
        if vals and not any(TIMESTAMP.match(v) for v in vals) and len(vals) > best[1]:
            best = (col, len(vals))
    return best


def wanted_top(column: str, asked: list[tuple[int, set[str]]]) -> int | None:
    """The N the question asks for the things of this column (APPLICATION: "the 5 applications")."""
    c = re.sub(r"[^a-z]", "", (column or "").lower())
    for n, words in asked:
        if c and any(len(w) >= 3 and (w in c or c in w) for w in words):
            return n
    return None


def show_chart(title: str, labels: list[str], values: list[float], unit: str = "") -> str:
    """Bar chart as text, for the chat."""
    pairs = [(str(lb), float(v)) for lb, v in zip(labels, values) if v is not None][:40]
    if not pairs:
        return "(no data)"
    top = max(abs(v) for _, v in pairs) or 1.0
    width = max(len(lb) for lb, _ in pairs)
    lines = [title]
    for lb, v in pairs:
        bar = "█" * max(1, round(abs(v) / top * 40)) if v else ""
        lines.append(f"{lb.ljust(width)} {bar} {v:,.6g}{(' ' + unit) if unit else ''}")
    return "\n".join(lines)


SHOW_CHART_SPEC = {"type": "function", "function": {
    "name": "show_chart",
    "description": "Draw a bar chart as text for the chat answer (labels and values of a ranking or a time "
                   "series). Put the returned text in the answer inside a ``` block.",
    "parameters": {"type": "object", "required": ["title", "labels", "values"], "properties": {
        "title": {"type": "string"}, "labels": {"type": "array", "items": {"type": "string"}},
        "values": {"type": "array", "items": {"type": "number"}}, "unit": {"type": "string"}}}}}


def _cell(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}" if abs(v) < 1e15 else str(v)
    if isinstance(v, int):
        return f"{v:,}"
    return "" if v is None else str(v).replace("|", "/")


def _sql_rows(t: dict) -> list | None:
    try:
        rows = json.loads(t["result"]).get("rows") or []
    except (ValueError, TypeError, AttributeError):
        return None
    return rows if rows and isinstance(rows[0], dict) else None


def table_if_missing(answer: str, trace: list[dict]) -> str:
    if re.search(r"^\s*\|.+\|\s*$", answer, re.M):
        return ""
    if not any(t.get("called", t["tool"]) == "show_chart" for t in trace):
        return ""
    for t in reversed(trace):
        if t.get("called", t["tool"]) != "execute_sql":
            continue
        rows = _sql_rows(t)
        if not rows or len(rows) > 30:
            continue
        cols = list(rows[0])
        out = ["", "| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
        out += ["| " + " | ".join(_cell(r.get(c)) for c in cols) + " |" for r in rows]
        return "\n".join(out)
    return ""


def chart_if_missing(answer: str, trace: list[dict]) -> str:
    if "█" in answer or not re.search(r"^\s*\|.+\|\s*$", answer, re.M) or "```json" in answer.lower():
        return ""
    for t in reversed(trace):
        if t.get("called", t["tool"]) != "execute_sql":
            continue
        rows = _sql_rows(t)
        if not rows or len(rows) > 30 or len(rows[0]) != 2:
            return ""
        label_col, value_col = list(rows[0])
        if not all(isinstance(r.get(value_col), (int, float)) and r.get(value_col) is not None for r in rows):
            return ""
        chart = show_chart(value_col, [str(r.get(label_col)) for r in rows], [r[value_col] for r in rows])
        return "\n\n```\n" + chart + "\n```"
    return ""


def local_links(answer: str) -> str:
    """Markdown images and links to files of the server (the chat page shows the files)."""
    answer = re.sub(r"!\[[^\]]*\]\((?!https?://)[^)]*\)\s*", "", answer)
    return re.sub(r"\[([^\]]+)\]\((?:/|file:|~)[^)]*\)", r"\1", answer)


def trim_tables(answer: str, keep: int = 10) -> str:
    """Markdown tables longer than `keep` rows cut to their first rows (the chat page shows
    every row of the query results under the answer)."""
    lines, out, i = answer.split("\n"), [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?[\s:|-]+\|?\s*$", lines[i + 1]) \
                and "-" in lines[i + 1]:
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            rows = j - i - 2
            out += lines[i:i + 2 + min(rows, keep)]
            if rows > keep + 2:
                out.append("")
                out.append(f"*First {keep} of {rows} rows: every row is in the result below.*")
            else:
                out += lines[i + 2 + keep:j]
            i = j
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out)


NAME_ASKED = re.compile(r"\b(?:save[ds]? (?:it|this|the chart)? ?as|name[ds]? (?:it)?|call(?:ed)?(?: it)?|"
                        r"titled?|entitled|sous le nom|nomm[ée]e?|appel[ée]e?|intitul[ée]e?)\s*[\"'«“‘]\s*([^\"'»”’\n]{3,120}?)"
                        r"\s*[\"'»”’]", re.I)


def name_asked(question: str) -> str | None:
    """The name a request gives what it saves ("... and save it as 'Late parcels per carrier'")."""
    m = NAME_ASKED.search(question or "")
    return m.group(1).strip() if m else None


SAVED_CHART_ASK = re.compile(
    r"\bsuperset\b[^.?!\n]{0,40}\b(chart|graph|dashboard)|\b(create|save|make|build|add)\b[^.?!\n]{0,60}"
    r"\b(chart|dashboard)\b[^.?!\n]{0,40}\b(named|called|titled|in superset|(on|to|in) (a|the|my) dashboard)|"
    r"\bgraphique superset|\b(cr[ée]e[rz]?|enregistre[rz]?)\b[^.?!\n]{0,60}\b(graphique|tableau de bord)", re.I)
CHART_CLAIM = re.compile(r"\b(chart|graph)\b[^.\n]{0,40}\b(has been|was|is)\s+(created|saved)|"
                         r"\bgraphique\b[^.\n]{0,40}\b(a [ée]t[ée]|est)\s+(cr[ée][ée]|enregistr[ée])", re.I)
# "The chart has been updated to a pie chart", "I changed the chart to a table", "le graphique a été modifié"
CHART_CHANGE_CLAIM = re.compile(r"\b(chart|graph)\b[^.\n]{0,60}\b(has been|was|is now|now)\s+(updated|changed|converted|"
                                r"switched|turned|modified|made|renamed|retitled)\b|\bI(?:'ve| have)?\s+(updated|changed|"
                                r"converted|switched|turned|modified|made|renamed|retitled)\s+(the|your|it|this)\b[^.\n]{0,40}"
                                r"\b(chart|graph|into|to)\b|"
                                r"\bgraphique\b[^.\n]{0,60}\b(a [ée]t[ée]|est)\s+(modifi[ée]|transform[ée]|chang[ée]|renomm[ée])|"
                                r"\b(chart|graph)\b[^.\n]{0,40}\bis now (?:shown as |displayed as )?an?\b|"   # "is now a pie chart"
                                r"\bgraphique\b[^.\n]{0,40}\best (?:maintenant|d[ée]sormais) une?\b",
                                re.I)
PREVIEW_ASK = re.compile(r"\b(preview|aper[çc]u|without saving|sans (?:l')?enregistrer|do not save|don't save|not save it|"
                         r"just show|show me how it would look|ne l'enregistre pas)\b", re.I)


DASHBOARD_CLAIM = re.compile(r"\b(dashboard)\b[^.\n]{0,60}\b(has been|was|is)\s+(created|saved|updated|changed)|"
                             r"\b(added|ajout[ée]e?s?)\b[^.\n]{0,60}\b(to|au|dans le)\s+(the\s+)?(dashboard|tableau de bord)|"
                             r"\btableau de bord\b[^.\n]{0,60}\b(a [ée]t[ée]|est)\s+(cr[ée][ée]|enregistr[ée]|modifi[ée])",
                             re.I)
DASHBOARD_TOOLS = ("generate_dashboard", "add_chart_to_existing_dashboard", "update_dashboard")
SQLLAB_CLAIM = re.compile(r"\b(saved|enregistr[ée]e?)\b[^.\n]{0,60}\b(sql ?lab|saved quer(y|ies)|requ[êe]tes? "
                          r"enregistr[ée]es?)\b", re.I)


def saved_chart(trace: list[dict]) -> bool:
    return any((t.get("called") or t["tool"]) in ("generate_chart", "update_chart", "generate_dashboard")
               and t.get("status") == "done" for t in trace)


def changed_chart(trace: list[dict]) -> bool:
    """A chart was saved or changed for good in this answer (an unsaved preview of update_chart is no change)."""
    for t in trace:
        name = t.get("called") or t["tool"]
        if t.get("status") != "done" or name not in ("generate_chart", "update_chart"):
            continue
        if name == "generate_chart" and not ((t.get("args") or {}).get("request") or t.get("args") or {}).get("save_chart"):
            continue
        if '"is_unsaved_state": true' in (t.get("result") or "") or '"is_unsaved_state":true' in (t.get("result") or ""):
            continue
        return True
    return False


def saved_dashboard(trace: list[dict]) -> bool:
    return any((t.get("called") or t["tool"]) in DASHBOARD_TOOLS and t.get("status") == "done" for t in trace)


# a request about the notes themselves (not a question that notes may answer): only the notes tools are offered
NOTES_ASK = re.compile(
    r"^\W*(?:please\s+|can you\s+|could you\s+)?(?:"
    r"(?:make|write|take|add|create|save|put|jot|keep)\b[^.?!\n]{0,30}\bnotes?\b"
    r"|notes?\s+(?:for|to)\s+(?:the\s+team|me|myself|us|everyone)\b|notes?\s*:"
    r"|(?:add|append)\s+(?:this\s+|it\s+|that\s+)?to\s+(?:my|the|that|this|our|your)\s+(?:personal\s+|team\s+)?notes?\b"
    r"|(?:change|edit|update|modify|correct|fix|rename|retitle)\s+(?:my|the|that|this|our)\s+(?:personal\s+|team\s+)?notes?\b"
    r"|(?:undo|revert|restore)\b[^.?!\n]{0,40}\bnotes?\b"
    r"|(?:delete|remove|erase)\s+(?:my|the|that|this|our|a)\s+(?:personal\s+|team\s+)?notes?\b"
    r"|(?:show|list|find|read|open)\s+(?:me\s+)?(?:my|the|our|all)\s+(?:personal\s+|team\s+)?notes?\b"
    r"|(?:ajoute|[ée]cris|prends|cr[ée]e|enregistre)\b[^.?!\n]{0,30}\bnotes?\b"
    r"|(?:modifie|change|supprime|efface|annule)\b[^.?!\n]{0,20}\b(?:ma|la|cette|notre)\s+note\b)", re.I)
NOTE_DONE = re.compile(          # an answer saying a note was saved, changed or deleted in this turn
    r"\bnotes?\b[^.\n]{0,160}?\b(?:has been|have been|is now)\s+(created|saved|added|written|recorded|updated|"
    r"changed|appended|edited|modified|undone|restored|reverted|deleted|removed)\b(?!\s+by\b)"
    r"|\bI(?:'ve| have)?\s+(created|saved|added|wrote|recorded|updated|changed|appended|edited|modified|undid|"
    r"restored|reverted|deleted|removed)\b[^.\n]{0,60}\bnotes?\b"
    r"|\bnotes?\b[^.\n]{0,160}?\ba [ée]t[ée]\s+(cr[ée]{2}e?|enregistr[ée]e?|ajout[ée]e?|modifi[ée]e?|supprim[ée]e?|"
    r"annul[ée]e?|restaur[ée]e?)", re.I)
NOTE_ACTIONS = (               # what an answer says was done, the calls that do it (with their result's key)
    (re.compile(r"^(delet|remov|supprim)", re.I), (("delete_note", "deleted"),)),
    (re.compile(r"^(updat|chang|append|edit|modif|undo|undid|restor|revert|annul)", re.I), (("change_note", "after"),)),
    (re.compile(r"^(creat|cr[ée]|sav|add|ajout|writ|wrote|record|enregistr)", re.I),      # "added to the note": a
     (("add_note", "saved"), ("change_note", "after"))))                                   # change saves it too
CARRY_NUDGE = ("(Check before answering: this message goes on from the previous question, whose answer counted "
               "with {conds}; the queries of this answer drop {them}. Keep the previous question's conditions unless "
               "the user removes them: run the queries again with them. If the user asks a new question, answer it "
               "and say in one line that {them} no longer {apply}. Write the whole answer for the user as if for the "
               "first time: they see neither the one above nor this check.)")
CARRY_HALF_NUDGE = ("(Check before answering: the queries of this answer keep the previous question's period, which "
                    "this message does not say, so they take it as going on from the previous question; that answer "
                    "counted with {conds} too, and these queries drop {them}. If the message goes on from it, run the "
                    "queries again with {them}; if it is a question of its own, say in one line which period and "
                    "scope you used. Write the whole answer for the user as if for the first time: they see neither "
                    "the one above nor this check.)")
CARRY_NOTE = "\n\n(Check: the previous question counted with {conds}; this answer does not.)"
NAMED_NUDGE = ("(Check before answering: the question names {value} ({field} of {table}), and no query of this "
               "answer has a condition with it nor is per {field}: the figures above count every {field}. Run the "
               "query again with {field} = '{value}', or, if the question means something else, say so in one line. "
               "Write the whole answer for the user as if for the first time: they see neither the one above nor "
               "this check.)")
NAMED_OUT_NUDGE = ("(Check before answering: the question leaves out {value} ({field} of {table}), and no query of "
                   "this answer has a condition on {field}: the figures above count {value} too. Run the query again "
                   "with {field} <> '{value}', or, if the question means something else, say so in one line. Write "
                   "the whole answer for the user as if for the first time: they see neither the one above nor this "
                   "check.)")
NAMED_NOTE = "\n\n(Check: the question names {value} ({field}); no query of this answer filters on it.)"
FUTURE_NUDGE = ("(Check before answering: the question asks about a period that has not happened yet (from {start}), "
                "and the figures of this answer are past ones. The data cannot tell the future: say so first, in one "
                "line; then, if useful, give the past figures as a reference and say which period they are. Write the "
                "whole answer for the user as if for the first time: they see neither the one above nor this check.)")
FUTURE_NOTE = "\n\n(Check: the question asks about the future; the figures above are past ones, not a forecast.)"
NEEDLESS_ASK_NUDGE = ("(Check before answering: the question names {value}, a value of {field} in {table}; of the data "
                      "you offer, only that one holds it, so there is nothing to choose. Answer the question from "
                      "{table}, with its queries; ask back only about what the question leaves open. Write the whole "
                      "answer for the user as if for the first time: they see neither the one above nor this check.)")
NOTE_CLAIM_NUDGE = ("(Check before answering: your answer says a note was {what}, and no {tool} call did it in this "
                    "answer. Call {tool} now ({how}), or tell the user it was not done. Write the whole answer for "
                    "the user as if for the first time: they see neither the one above nor this check.)")
NOTE_HOW = {"delete_note": "with the note's note_id from search_notes: it shows the note, then ask the user to confirm",
            "change_note": "with the note's note_id from search_notes", "add_note": "with the user's text"}
NOTE_NOT_DONE = {
    "delete_note": "I have not deleted any note: the deletion did not run. Ask again (\"delete my note about ...\"): I "
                   "will show you the note and ask you to confirm.",
    "change_note": "The note was not changed: the change did not run. Ask again with what to change in which note.",
    "add_note": "No note was saved: the save did not run. Ask again with the note's text, or use the Notes button."}


def notes_request(text: str) -> bool:
    return bool(NOTES_ASK.search(text or ""))


def _note_done(trace: list[dict], tool: str, key: str) -> bool:
    for t in trace:
        if (t.get("called") or t["tool"]) == tool and t.get("status") == "done":
            try:
                if key in json.loads(t.get("result") or "{}"):
                    return True
            except (ValueError, TypeError):
                pass
    return False


def note_claim(answer: str, trace: list[dict]) -> tuple[str, str] | None:
    """(what the answer says was done to a note, the tool that does it) when no such call succeeded here."""
    for m in NOTE_DONE.finditer(answer or ""):
        word = next(g for g in m.groups() if g)
        for rx, calls in NOTE_ACTIONS:
            if rx.match(word):
                if not any(_note_done(trace, tool, key) for tool, key in calls):
                    return word.lower(), calls[0][0]
                break
    return None


ACTION_NUDGE = ("(Check before answering: your answer says that {what}, but no tool did it in this answer. Do it "
                "now ({tool}), then answer from what the tool returns. Write the whole answer for the user as if for "
                "the first time: they see neither the one above nor this check.)")


def action_claim(answer: str, trace: list[dict]) -> tuple[str, str] | None:
    """An action the answer says was done (a chart saved or changed, a dashboard made or changed, a query saved)
    that no tool of this answer did: (what, the tool that does it)."""
    if CHART_CLAIM.search(answer or "") and not saved_chart(trace):
        return "a chart was saved", "generate_chart with save_chart true and its chart_name"
    if CHART_CHANGE_CLAIM.search(answer or "") and not changed_chart(trace):
        return "the chart was changed", "update_chart with generate_preview false"
    if DASHBOARD_CLAIM.search(answer or "") and not saved_dashboard(trace):
        return "a dashboard was made or changed", "generate_dashboard, or add_chart_to_existing_dashboard"
    if SQLLAB_CLAIM.search(answer or "") and not any((t.get("called") or t["tool"]) == "save_sql_query" and
                                                     t.get("status") == "done" for t in trace):
        return "the query was saved in SQL Lab", "save_sql_query"
    return None


def claims_check(answer: str, trace: list[dict]) -> str:
    notes = []
    claimed = note_claim(answer, trace)
    if claimed:
        notes.append(f"no note was {claimed[0]} in this answer ({claimed[1]} did not run): the notes are as they were")
    sent = []
    for t in trace:
        if t.get("called", t["tool"]) != "send_email":
            continue
        try:
            res = json.loads(t["result"])
        except (ValueError, TypeError):
            continue
        if res.get("sent_to"):
            sent.append(res)
    for res in sent[-1:]:
        low = answer.lower()
        if not res.get("images") and re.search(r"\b(image|chart|graph)", low):
            notes.append("the e-mail was sent without an image (send_email: images 0)")
        if not res.get("attached") and re.search(r"attach|excel|xlsx", low):
            notes.append("the e-mail was sent without an attachment")
    if CHART_CLAIM.search(answer) and not saved_chart(trace):
        notes.append("no Superset chart was saved (only an image or the result shown here); ask again to save one")
    elif CHART_CHANGE_CLAIM.search(answer) and not changed_chart(trace):
        notes.append("the saved chart was not changed in this answer (at most an unsaved preview); ask again to save "
                     "the change")
    if DASHBOARD_CLAIM.search(answer) and not saved_dashboard(trace):
        notes.append("no Superset dashboard was created or changed in this answer; ask again to do it")
    if SQLLAB_CLAIM.search(answer) and not any((t.get("called") or t["tool"]) == "save_sql_query" and
                                               t.get("status") == "done" for t in trace):
        notes.append("no query was saved in SQL Lab in this answer; ask again to save it")
    return ("\n\n(Check: " + "; ".join(dict.fromkeys(notes)) + ".)") if notes else ""


QUERY_TOOLS = ("execute_sql", "promql_query", "export_excel", "check_health", "chart_from_sql", "get_chart_data",
               "compare_groups", "compare_logs", "compare_to_usual")
LOOKUP_TOOLS = QUERY_TOOLS + ("describe_data", "data_changes", "search_knowledge", "get_dataset_info",
                              "list_datasets", "list_charts", "get_chart_info", "list_dashboards", "get_dashboard_info")
RESULT_CLAIM = re.compile(r"```json|\b(sql|query|requ[êe]te|promql)\s+(run|ran|executed|ex[ée]cut[ée]e?)\b|"
                          r"\bI (ran|executed|queried)\b", re.I)
TABLE_WITH_NUMBERS = re.compile(r"^\s*\|[^\n]*\d[^\n]*\|\s*$", re.M)
NO_TOOL_NUDGE = ("(Check before answering: you called no tool. The knowledge given with the question is only a "
                 "summary, not an answer. Call describe_data for what the data contains and its fields, and run "
                 "the query (execute_sql, promql_query...) for any number or list. If the question really needs "
                 "no data, give the same answer again. Either way "
                 "write the whole answer for the user as if for the first time: they see neither the one above nor this check, so never mention it, apologise or say what changed.)")
LOOKUP_NUDGE = ("(Check before answering: your answer says the data has no such field or value, but you called no "
                "tool in this answer and the chat's earlier answers may be wrong. Look it up first: describe_data "
                "gives an index's fields with their values, and a value the question names may be in a field with "
                "another name (a channel, a direction, a source). Then answer, or ask back if it really is not there. "
                "Either way write the whole answer for the user as if for the first time: they see neither the one "
                "above nor this check, so never mention it, apologise or say what changed.)")
WRITTEN_SQL_NUDGE = ("(Check before answering: your answer shows a query that was not run, with results that no query "
                     "returned. Call execute_sql with that query now: the tool runs it on the data and gives you its "
                     "rows; then answer from its result. Never write a query in the answer instead of running it. Then "
                     "write the whole answer for the user as if for the first time: they see neither the one above nor "
                     "this check, so never mention it, apologise or say what changed.)")
WRITTEN_SQL = re.compile(r"```[a-z]*\s*\n\s*(?:WITH|SELECT)\b", re.I)       # a query written out, not run
# the user asks for the query itself ("give me the SQL", "the query to count ..."): writing it is the answer
WANTS_QUERY = re.compile(r"\b(sql|query|queries|requ[êe]tes?|promql|statement)\b", re.I)
# ... and what it returned said in words ("The query returned no rows", "this query gives the traders..."): a result
# no query gave
CLAIMED_RESULT = re.compile(r"\b(?:the|this|that) (?:query|request|sql) (?:returned|returns|gave|gives|shows|showed|"
                            r"found|finds|lists)\b|\breturned (?:no|\d)|\bno (?:rows?|records?|results?) "
                            r"(?:were |was |are |is )?(?:returned|found)\b|\bla requ[êe]te (?:a )?(?:renvoy|retourn|donn)", re.I)
# "The data does not contain a 'voice' field", "there is no such column", "n'existe pas": a claim of absence
ABSENCE = re.compile(
    r"\b(?:does not|doesn't|do not|don't) (?:contain|have|include|hold|record)\b|\bno (?:such )?(?:field|column|"
    r"value|data)\b|\b(?:is|are) not (?:available|present|recorded|stored|tracked) in\b|\bthere (?:is|are) no\b[^.\n]{0,40}"
    r"\b(?:field|column|value|direction|flag|attribute)s?\b|\bn'(?:existe|y a) pas\b|\bne contient (?:pas|aucun)|"
    r"\baucun(?:e)? (?:champ|colonne|valeur)\b", re.I)
NUMBERS_NUDGE = ("(Check before answering: these numbers or names of your answer are in none of the results "
                 "above: {numbers}. Either run a query that returns them (totals, rates, averages and differences "
                 "are computed in the query itself: execute_sql, promql_query), or delete the sentences that hold "
                 "them. List only the names and rows a result gave (never continue a series; the page shows every "
                 "row of a result, so a table of at most 10 rows is enough). Then "
                 "write the whole answer for the user as if for the first time: they see neither the one above nor this check, so never mention it, apologise or say what changed.)")
DEFINITION_NUDGE = ("(Check before answering: the team defines {term} as \"{definition}\", and a check of your queries "
                    "found: {why}. Compute {term} exactly as defined (each condition and each relation it states; a "
                    "relation between two tables is a JOIN on their key or a condition on the key), then answer from "
                    "that result; if your query does follow the definition, keep it. Write the whole answer for the user "
                    "as if for the first time: they see neither the one above nor this check.)")
GRAIN_NUDGE = ("(Check before answering: your answer gives {time} as the moment, but the query grouped the times by "
               "{grain}: {time} is the start of that {grain}, not the moment. Read the moment itself (the rows or samples "
               "ordered by the value, without DATE_TRUNC), or give the {grain} as a range (\"between 04:00 and 05:00\"). "
               "Write the whole answer for the user as if for the first time: they see neither the one above nor this "
               "check.)")
ASK_FIRST_NUDGE = ("(Check before answering: the question is not clear enough to answer (see the note given with it). "
                   "Answer only with one short question to the user that names the candidates, and stop. Write it for "
                   "the user as if for the first time: they see neither the one above nor this check.)")
# an investigation's answer that finds nothing wrong, or a documented effect: no change to look for behind it
NOTHING_WRONG = re.compile(r"\bnothing (?:is )?(?:unusual|abnormal|wrong)\b|\bno (?:real |significant |abnormal |unusual )?"
                           r"(?:delay|slowdown|problem|incident)\b|\bas (?:usual|expected|every (?:month|week))\b|"
                           r"\b(?:is|are|looks?) normal\b|\bon time\b|\bdocumented\b|\bexpected (?:effect|monthly|every)\b|"
                           r"\brien d'anormal\b|\bcomme d'habitude\b|\battendu\b", re.I)
STAGE_NUDGE = ("(Check before answering: compare_groups says {stage} is the first stage that is off: the rows were late "
               "before they could run, so they waited for their inputs (what feeds them, what runs before them), not for a "
               "slot or a queue: a pool cannot hold rows that are not ready, and a wait for capacity shows as rows ready "
               "but not started. Follow their inputs: which feed or upstream job was late, by how much, and the record "
               "behind it (system_links of those jobs, the feeds' and upstream jobs' own times and alerts). If those "
               "inputs did wait for this pool themselves, say so with the figure that shows it. Then write the whole "
               "answer for the user as if for the first time: they see neither the one above nor this check.)")
# capacity named as the cause: in a sentence that says cause, not one that says it was as usual
CAPACITY_WORDS = re.compile(r"\b(slots?|congest\w*|queue backlog|file d'attente|"     # a pool's, not a cache's
                            r"(?:pool|grid|queue|file)\b[^.\n]{0,40}\b(?:satur\w*|full|plein\w*|capacit\w*)|"
                            r"(?:satur\w*|capacit\w*)\b[^.\n]{0,40}\b(?:pool|grid|queue|slots?))\b", re.I)
CAUSE_WORDS = re.compile(r"\b(caus\w*|because|due to|explains?|expliqu\w*|origin\w*|à cause|dû|car|raison|"
                         r"responsable|driv\w+|led to|leads? to|resulting|result\w* from|stems? from|comes? from|"
                         r"provoqu\w*|entra[iî]n(?:e|ent|é|ée|és|ées|ait|aient)|vient de|li[ée]e?s? à|parce)\b", re.I)
# the capacity said as an effect, or said not to be the cause: no blame
CAPACITY_EFFECT = re.compile(r"\b(not the (?:main |primary |root |real )?cause|pas (?:la|une) cause|consequences?|"
                             r"conséquences?|symptoms?|symptômes?|a result of|the result of|le résultat|effects? of|effets?)\b",
                             re.I)
# said as usual, or denied, near the capacity words (not a negation of another clause: "the jobs do not start
# because the pool is full" blames the pool)
AS_USUAL_WORDS = re.compile(r"\b(fine|normal\w*|usual\w*|as usual|ok|free|available|libres?|disponibles?|"
                            r"habituel\w*|comme d'habitude|comme chaque)\b", re.I)
CAPACITY_DENIED = re.compile(r"\b(no|not|never|nor|n'|pas|aucun\w*|ni|sans|without|rather than|plutôt que)\b"
                             r"(?:(?!\b(?:car|because|since|parce|puisque|due|dû|as)\b)[^.\n,;:]){0,30}$", re.I)


LOGS_LEAD = re.compile(r'say that they do not usually[^:]*\):[^"]*?\(1\) "([^"]{5,200})"')


def logs_lead(note: str) -> tuple[str, list[str]] | None:
    """The first new pattern of the inputs' logs note ("(1) \"<name> still waiting for its inputs after # min:
    <name>\" ..."), as (a short title, the words an answer that explains or rules it out would say), or None."""
    m = LOGS_LEAD.search(note or "")
    if not m:
        return None
    pattern = m.group(1)
    words = [w for w in re.findall(r"[A-Za-z][\w.]{4,}", pattern) if w.lower() not in ("<name>", "name")]
    return f'"{pattern[:120]}" (new)', list(dict.fromkeys(words))[:6]


def capacity_blamed(answer: str) -> bool:
    """A sentence of the answer that names capacity (a full pool, slots, a queue) as a cause: not said as usual near
    it, not denied right before it."""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", answer or ""):
        m = CAPACITY_WORDS.search(sentence)
        if not m or not CAUSE_WORDS.search(sentence) or CAPACITY_EFFECT.search(sentence):
            continue
        before, around = sentence[max(0, m.start() - 40):m.start()], sentence[max(0, m.start() - 50):m.end() + 50]
        if CAPACITY_DENIED.search(before) or AS_USUAL_WORDS.search(around) or \
                re.search(r"\b(?:not|no|never|n'|pas|jamais|aucun\w*)\b", m.group(0), re.I):   # "the pool was not full"
            continue
        return True
    return False


LEDGER_NUDGE = ("(Check before answering: your work plan is not finished: {gaps}. Do what is left now (a call each), "
                "or mark it dropped with work_plan and say why in the answer; the answer covers every task and explains "
                "or rules out each finding. Write the whole answer for the user as if for the first time: they see neither "
                "the one above nor this check.)")
INVENTED_NUDGE = ("(Check before answering: your answer gives {names}, which no tool returned in this answer and "
                  "nothing above holds. Call the tool that reads them from the data now (execute_sql, promql_query, "
                  "describe_data...), then answer from its result only; if the data does not have them, say so. Write the "
                  "whole answer for the user as if for the first time: they see neither the one above nor this check.)")
NUMBERS_NOTE = ("\n\n(Check: these numbers or names do not come from the results of this answer's queries: "
                "{numbers}.)")
BAD_TOOL_CALL = re.compile(r"parse tool call|tool call arguments|invalid tool call|failed to parse", re.I)
# the conversation is longer than the model's context (llama.cpp, vLLM, OpenAI say it their way)
CONTEXT_FULL = re.compile(r"exceeds? the available context|exceed_context_size|context (?:size|length|window) "
                          r"(?:exceeded|is exceeded)|maximum context length|too many tokens|prompt is too long", re.I)
SHRUNK = (1500, 500)       # chars kept of the older tool results when the context is full, then again
KEPT_WHOLE = 3             # the latest tool results kept whole the first time
COMPACT_KEPT = 4           # the latest tool results kept whole when a long conversation is shortened early
CONTEXT_FULL_NUDGE = ("(The conversation became longer than the model can read: the older results above were "
                      "shortened. Make no more calls unless one is essential; write the answer for the user now from "
                      "the results above, and say what could not be checked.)")
UNREADABLE_CALL = ("(Your last reply could not be read: the arguments of its tool call were not valid JSON (too long, "
                   "or cut). Call the tool again with short arguments: a chart config names columns and aggregates, "
                   "never the data rows. Or write the answer with what you have.)")
TIME_UP = "(The time for this answer is up.) "
LAST_CALLS = ("(Two tool calls are left for this answer: write the answer for the user now from the results above "
              "(what they show, what is known and what is not); call a tool only if the answer cannot be written "
              "without it.)")
OUT_OF_STEPS = ("(No tool call is left for this answer. Write the answer for the user now, from the results "
                "above: what was done (the charts, datasets and dashboards saved, with their links), what the "
                "results show, and what remains to do. Do not claim anything the tools did not do.)")
RULES_NUDGE = ("(Check before answering: the team's rule \"{rule}\" applies to the data you queried, and your query "
               "does not apply it. Run the query again applying it, or, if the question asks otherwise, say so in "
               "one line. Then "
               "write the whole answer for the user as if for the first time: they see neither the one above nor this check, so never mention it, apologise or say what changed.)")
RULES_NOTE = "\n\n(Check: the team's rule \"{rule}\" was not applied in this answer's queries.)"
LOOP_NUDGE = ("(Your answer repeated the same lines again and again: it is cut above. Write the final answer for the "
              "user now, once: what the results above give, without working notes.)")
LOOP_NOTE = "\n\n(Cut: the model's text went round in circles from here.)"
COUNT_NUDGE = ("(Check before answering: the question asks how many or how much, and your answer gives no number "
               "for it (only shares or rates). Give that number from a query (COUNT, SUM, SUM(increase) of a counter), "
               "or say why it cannot be counted.)")
LIMIT_NUDGE = ("(Check before answering: {n} is the number of rows the LIMIT {n} of your query let through, not a "
               "count of what the question asks: more rows match. For a total, run a query without that LIMIT "
               "(COUNT(*), or the sum of the counts). Then write the whole answer for the user as if for the first "
               "time: they see neither the one above nor this check, so never mention it, apologise or say what "
               "changed.)")
LIMIT_NOTE = "\n\n(Check: {n} is where the LIMIT of a query cut its rows, not a count: more rows match.)"
TIE_NUDGE = ("(Check before answering: your answer gives {names} as a cause, but nothing ties {it} to {scope}: the "
             "team's system map shows no link between them, and no result of this answer shows the affected rows on "
             "{it}. Either check it (group the affected rows by the field that holds {it}; system_links says what "
             "{scope} runs on and depends on), or take {it} out of the causes and say what is established. Then write "
             "the whole answer for the user as if for the first time: they see neither the one above nor this check, "
             "so never mention it, apologise or say what changed.)")
TIE_NOTE = ("\n\n(Check: {names} named as a cause, but neither the system map nor this answer's results tie {it} to "
            "{scope}.)")
HOW_MANY = re.compile(r"\b(how many|how much|combien|quel(?:le)? (?:nombre|quantit[ée]))\b", re.I)
NONE_SAID = re.compile(r"\b(no|none|zero|nothing|aucun\w*|z[ée]ro|pas de|rien)\b", re.I)


def adds_to(question: str, before: str, earlier: list[str] | None = None) -> bool:
    """The question names a day, a period or a value the previous one did not ("And on 22 September?", "And on
    the 23rd?", "And the day before?", "The CPU of srv-amer-002 yesterday."): its answer needs its own query. The
    earlier questions (oldest first, the previous one last) give the day "the 23rd" is relative to."""
    if not before:
        return False
    from supagent.knowledge.period import PERIOD_WORDS, anchor_of, days_named
    from supagent.knowledge.resolve import VALUE_TOKEN

    today = now().date()
    asked = [str(q) for q in earlier or [] if q] or [before]
    if asked[-1] != before:
        asked.append(before)
    said = set(days_named(before, today, anchor_of(asked[:-1], today)))
    if set(days_named(question, today, anchor_of(asked, today))) - said:
        return True
    said_before = {w.lower() for w in PERIOD_WORDS.findall(before)}
    if {w.lower() for w in PERIOD_WORDS.findall(question)} - said_before:
        return True
    return bool(set(VALUE_TOKEN.findall(question or "")) - set(VALUE_TOKEN.findall(before or "")))


def without_extrapolation(answer: str, unknown: list[str]) -> tuple[str, list[str]]:
    """After the check was given: the lines that continue a list up to a name no result gave are taken out
    (unless most of the answer would go); the other made-up numbers and names stay marked."""
    from supagent.grounding import NAME, drop_extrapolated

    names = [u for u in unknown if NAME.fullmatch(u)]
    if not names:
        return answer, unknown
    trimmed, left = drop_extrapolated(answer, names)
    if not trimmed.strip() or len(trimmed.splitlines()) < len(answer.splitlines()) / 2:
        return answer, unknown
    return trimmed, [u for u in unknown if u not in names or u in left]


def missing_count(question: str, answer: str) -> bool:
    """The question asks how many / how much and the answer has no number but shares (and no "none")."""
    if not HOW_MANY.search(question or "") or asks_back(answer) or NONE_SAID.search(answer or ""):
        return False
    from supagent.grounding import SKIP

    text = SKIP[0].sub(" ", answer or "")
    for rx in SKIP[5:14]:                              # dates, times, years, names with digits
        text = rx.sub(" ", text)
    for m in re.finditer(r"(?<![\w.])\d[\d,\u202f\u00a0]*(?:\.\d+)?(\s*%)?", text):
        if not m.group(1):
            return False                                # a number that is not a share
    return True


NO_QUERY_NUDGE = ("(Check before answering: your answer shows results or says that a query ran, but no query ran "
                  "in this answer. Run it now (execute_sql, promql_query...) and answer from its result: never "
                  "show numbers or rows that no tool returned. Then "
                  "write the whole answer for the user as if for the first time: they see neither the one above nor this check, so never mention it, apologise or say what changed.)")


def _has_data(answer: str) -> bool:
    """Numbers or names with digits in the answer's text: results, not only a question."""
    from supagent.grounding import answer_names, answer_numbers

    return bool(answer_numbers(answer) or answer_names(answer))


def asks_back(answer: str) -> bool:
    """The answer is a question to the user (what they meant): short, ends with a question, no
    result in it (rule 6)."""
    text = (answer or "").strip()
    last = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip()), "")
    return bool(text) and len(text) <= 1200 and last.rstrip("*_ )").endswith("?") and \
        not TABLE_WITH_NUMBERS.search(text) and "```" not in text


def repeating(text: str) -> int | None:
    """Where a text starts going round in circles: the same block of three lines (120 characters or more)
    a third time, as a model writes until its token limit ("I will now write the response. One final
    check: ..."). The text is kept up to the block's second copy; None when nothing repeats so."""
    lines = (text or "").splitlines(keepends=True)
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln)
    full = [i for i, ln in enumerate(lines) if ln.strip()]
    seen: dict[tuple, list[int]] = {}
    for j in range(len(full) - 2):
        block = tuple(" ".join(lines[full[j + m]].split()) for m in range(3))
        if sum(map(len, block)) < 120:
            continue
        at = seen.setdefault(block, [])
        if at and j - at[-1] < 3:                      # overlapping copies of one block: the same lines
            continue
        at.append(j)
        if len(at) >= 3:
            return starts[full[at[1]]]
    return None


def shortened(messages: list[dict], chars: int, keep: int) -> int:
    """The conversation made shorter when the model's context is full: the tool results but the latest `keep`
    cut to their first `chars` characters (the conclusion of a tool comes first). How many were cut."""
    tools = [m for m in messages if m.get("role") == "tool"]
    n = 0
    for m in tools[:-keep] if keep else tools:
        text = str(m.get("content") or "")
        if len(text) > chars + 80:
            m["content"] = text[:chars] + " ...[shortened: the conversation was too long for the model]"
            n += 1
    return n


def unsupported_answer(answer: str, trace: list[dict], question: str = "") -> str | None:
    """A reminder when an answer was written without the tools: no tool called at all, or
    results shown (a JSON block, "SQL run", a table of numbers) with no query run, or a query written
    and not run (unless the question asks for the query itself). A question back to the user (what
    they meant) is an answer."""
    if not trace and ABSENCE.search(answer or ""):
        return LOOKUP_NUDGE                            # "the data has no such field": said without looking
    if asks_back(answer) and not _has_data(answer):   # a question back, not results with an offer at the end
        return None
    done = {t.get("called") or t["tool"] for t in trace if t.get("status") == "done"}
    if WRITTEN_SQL.search(answer or "") and not done & set(QUERY_TOOLS) and \
            (_has_data(answer) or CLAIMED_RESULT.search(answer or "") or (question and not WANTS_QUERY.search(question))):
        return WRITTEN_SQL_NUDGE                       # the query in the text, its figures made up, or no figure at all
    if not trace:
        return NO_TOOL_NUDGE
    if RESULT_CLAIM.search(answer or "") and not done & set(QUERY_TOOLS):
        return NO_QUERY_NUDGE
    if len(TABLE_WITH_NUMBERS.findall(answer or "")) >= 2 and not done & set(LOOKUP_TOOLS):
        return NO_QUERY_NUDGE
    return None


EMPTY_RICH = "(The model wrote no text for this answer, even when asked again: the result of its last query is below.)"
EMPTY_PLAIN = "(The model wrote no text for this answer, even when asked again: here is the result of its last query.)"
ECHO_NUDGE = ("(Check before answering: your answer gives the previous answer again, word for word, but the "
              "question is a new one: \"{question}\". Answer this question, from the tools (a query for any number "
              "or name it asks for). Write the answer for the user as if for the first time: they see neither the one "
              "above nor this check.)")
AGAIN = re.compile(r"\b(again|repeat|once more|same answer|summar\w*|recap\w*|encore|répète|redis|rappelle|"
                   r"résum\w*)\b", re.I)


UNIT_ASKED = re.compile(r"\b(?:in|en)\s+(minutes?|seconds?|secondes?|hours?|heures?|days?|jours?|milliseconds?|"
                        r"millisecondes?|ms|GiB|GB|Go|MiB|MB|Mo|TB|percent|pourcentage|%|EUR|euros?|USD|dollars?)(?!\w)",
                        re.I)


POSSESSIVE_FOLLOW_UP = re.compile(r"^\s*(?:and\s+|et\s+)?(?:its|their|son|sa|ses|leur|leurs)\b", re.I)
NOT_SAME_KIND = re.compile(r"\b(how many|combien|which|who|quel(?:le)?s?|qui|unrelated|back to|something else|"
                           r"another question|different|revenons|autre question|retour)\b", re.I)


def unit_carried(question: str, history: list[dict] | None) -> str | None:
    """The unit the previous question asked its figure in ("..., in minutes?"), when this one is a short follow-up
    that says none ("And the longest one?"): the answer keeps it."""
    if UNIT_ASKED.search(question or "") or len((question or "").split()) > 12 or NOT_SAME_KIND.search(question or ""):
        return None                                    # a unit said, a new question, a count, another subject
    before = next((str(h.get("content") or "") for h in reversed(history or []) if h.get("role") == "user"), "")
    m = UNIT_ASKED.search(before)
    return m.group(1) if m else None


def echoes(answer: str, previous: str) -> bool:
    """The answer is the previous answer given again (its first 300 characters, the check marks left out)."""
    def norm(text: str) -> str:
        text = re.sub(r"\(Check:[^)]*\)", " ", text or "")
        return " ".join(text.lower().split())

    a, b = norm(answer), norm(previous)
    if len(b) < 120 or len(a) < 120:
        return False
    head = b[:300]
    return a.startswith(head) or (head in a and len(a) <= len(b) * 1.3)


UNSUPPORTED_NOTE = ("\n\n(Check: no query ran in this answer: numbers or rows shown here do not come from the "
                    "data. Ask again to have them read from the data.)")


def unsupported_note(answer: str, trace: list[dict], question: str = "") -> str:
    """After the reminder: an answer that still shows results no query returned is marked."""
    nudge = unsupported_answer(answer, trace, question)
    if nudge in (NO_QUERY_NUDGE, WRITTEN_SQL_NUDGE) or (nudge == NO_TOOL_NUDGE and (RESULT_CLAIM.search(answer or "") or len(
            TABLE_WITH_NUMBERS.findall(answer or "")) >= 2)):
        return UNSUPPORTED_NOTE
    return ""


SAVING_TOOLS = {"generate_chart", "update_chart", "generate_dashboard", "add_chart_to_existing_dashboard",
                "save_sql_query", "create_virtual_dataset", "create_report", "update_chart_preview"}
CALLS_AT_ONCE = 8          # tool calls run from one message of the model (the others are sent back)
PER_DAY = 3                # the third query of an answer that differs from earlier ones only by its dates is sent back
DAY_LITERAL = re.compile(r"'(?:\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?|\d{8}|[DWMY]-\d{1,3})'", re.I)
REPEAT_NOTE = ("You already made exactly this call in this answer and its result is above: the same call gives the "
               "same result. Use it: answer the user, or make a different call.")
# an answer that ends by announcing a step instead of taking it ("Let me run the query.")
ANNOUNCE = re.compile(
    r"(?:\b(?:I(?:'ll| will| am going to| shall)|let me|let's|now,? I(?:'ll| will)|next,? I(?:'ll| will))\b"
    r"[^.!?\n]{0,60}\b(?:run|query|check|call|create|fetch|look up|search|execute|generate|export|send|build|"
    r"compute|calculate|retrieve|pull|save|draw|plot)\b"
    r"|\b(?:je vais|laissez-moi|je lance|lan[çc]ons)\b[^.!?\n]{0,60}\b(?:lancer|ex[ée]cuter|v[ée]rifier|chercher|"
    r"cr[ée]er|interroger|calculer|r[ée]cup[ée]rer|envoyer|exporter|enregistrer|tracer)\b)[^.!?\n]*[.:!…]?\s*$", re.I)
ANNOUNCE_NUDGE = ("(Check before answering: your text ends by announcing a step (\"{step}\") but you called no "
                  "tool. Take that step now with the tool, or, if it is not needed, write the final answer without "
                  "announcing anything. The user sees neither the text above nor this check: never mention it.)")
APOLOGY = re.compile(r"^\s*(you'?re right|you are right|i apologi[sz]e|(my )?apologies|sorry|good catch|thanks? for "
                     r"(pointing|the)|i (included|made up|invented|fabricated)|vous avez raison|d[ée]sol[ée]|je m'excuse)\b"
                     r"[^\n]{0,240}?(?:[.!:](?:\s|$)|\n)", re.I)


def without_apology(answer: str) -> str:
    """An answer written again after a check: its first words for the check ("You're right, I included
    fabricated numbers...") are not for the user, who never saw it."""
    text = answer or ""
    for _ in range(2):                                   # "You're right. Let me provide the correct answer."
        m = APOLOGY.match(text)
        if not m:
            break
        text = text[m.end():].lstrip()
        text = re.sub(r"^(let me|here is|here's|voici)\b[^\n]{0,160}?[.:]\s*", "", text, flags=re.I)
    return text if text.strip() else answer


PREAMBLE = re.compile(r"\b(let me|i will|i'll|now i will|now i'll)\s+(now\s+)?(write|present|put together|compose|draft|"
                      r"format|give|provide|summari[sz]e)\b", re.I)


ANNOUNCED = re.compile(
    r"(?:^|(?<=[.!?:\n]))[^\n.!?]{0,160}\b(?:let me|i will|i'll|now i will|now i'll|je vais|laissez-moi)\s+"
    r"(?:now\s+|maintenant\s+)?(?:write|present|put together|compose|compile|prepare|formulate|draft|give|provide|"
    r"summari[sz]e|r[ée]diger|pr[ée]senter|donner|r[ée]sumer)\b[^\n.!?]{0,120}\b(?:answer|summary|response|findings?|conclusions?|report|"
    r"r[ée]ponse|synth[èe]se|r[ée]sum[ée]|what i(?:'ve| have) found)\b[^\n.!?]{0,60}[.:!]?[ \t]*\n"
    r"|(?:^|(?<=[.!?:\n]))[ \t]*(?:here(?:'s| is)|voici)\s+(?:the|my|la|ma)\s+(?:(?:corrected|final|revised|updated|"
    r"complete|full)\s+)?(?:answer|response|r[ée]ponse)(?:\s+(?:corrig[ée]e|finale|compl[èe]te))?\s*[.:][ \t]*\n", re.I)
ALOUD = re.compile(r"\b(?:let me (?:now |first |also |just )?(?:check|verify|look|see|query|run|confirm|compare|examine|"
                   r"re-?examine|re-?check|reconsider|double-check|review)|"
                   r"now i have|i (?:now )?have (?:all|the complete|enough|the full)|perfect[.!]|good[.!]|great[.!]|i see\b|"
                   r"i need to|je vais (?:maintenant )?(?:v[ée]rifier|regarder|comparer)|j'ai maintenant|parfait[.!])", re.I)
ANSWER_LABEL = re.compile(r"^\s*(?:#{1,4}\s*)?\*{0,2}(?:final\s+)?(?:answer|r[ée]ponse(?:\s+finale)?)\s*:?\*{0,2}\s*:?\s*\n", re.I)


# "Le nombre 14 est bien celui de ... Je vais supprimer cette mention. Voici la réponse corrigée : ---": what the model
# says about a check before the answer itself (the user never saw the check)
_FIXED = (r"(?:corrected|revised|updated|final|complete|new|fixed|corrig[ée]e|r[ée]vis[ée]e|mise [àa] jour|finale|"
          r"compl[èe]te|nouvelle)")
_REPLY = r"(?:answer|response|version|r[ée]ponse)"
CORRECTED = re.compile(rf"^(?P<lead>.{{0,900}}?)\b(?:here is|here's|below is|voici|ci-dessous)\s+(?:the|my|la|ma|une?|l')?\s*"
                       rf"(?:{_FIXED}\s+{_REPLY}|{_REPLY}\s+{_FIXED})\b[^\n]*\n+(?:\s*-{{3,}}\s*\n+)?", re.I | re.S)


def without_correction_lead(answer: str) -> str:
    """The answer without the model's words about a check that came before it ("Voici la réponse corrigée :"),
    when what follows is the answer (the longer part)."""
    m = CORRECTED.match(answer or "")
    if not m:
        return answer
    rest = answer[m.end():].strip()
    return rest if len(rest) > len(m.group("lead")) else answer


def without_preamble(answer: str) -> str:
    """The model's words about writing the answer before it ("Now I have all the numbers. Let me write the
    summary:" and a rule): not for the user. A short first paragraph with no figure in it; or everything before
    the last announcement of the answer ("Let me now write the complete answer."), when what comes before it
    is the work said aloud ("Let me check...", "Now I have...") and a full answer follows it. An answer that
    announces one of its own parts ("I'll give the breakdown by region:") keeps everything."""
    text = (answer or "").lstrip()
    said = [m for m in ANNOUNCED.finditer(text)]
    if said and ALOUD.search(text[:said[-1].end()]):
        rest = text[said[-1].end():].lstrip("\n")
        rest = re.sub(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*\n", "", rest).lstrip()
        rest = ANSWER_LABEL.sub("", rest, count=1).lstrip()
        if len(rest) >= 400 and len(rest) >= 0.25 * len(text):        # a full answer follows
            return rest
    m = re.match(r"(.{1,300}?)(\n\s*\n|\n(?=\s*(?:-{3,}|\*{3,}|_{3,})\s*\n))", text, flags=re.S)
    if not m or re.search(r"\d", m.group(1)) or not PREAMBLE.search(m.group(1)):
        return answer
    rest = re.sub(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*\n", "", text[m.end():].lstrip("\n")).lstrip()
    return rest if len(rest) >= 80 else answer


def limit_as_count(answer: str, trace: list[dict], question: str = "") -> int | None:
    """The LIMIT of a query that cut its rows (the result has as many rows as the LIMIT), written in the
    answer as a number of something ("100 failed job runs"): not when the question asked for that many,
    when a value of the result is that number, or when the answer says rows, the first or at least N."""
    text = re.sub(r"```.*?```|`[^`\n]*`", " ", answer or "", flags=re.S)
    asked = {int(float(v)) for v in re.findall(r"\d+", question or "")}
    for t in trace:
        if t.get("status") != "done" or (t.get("called") or t["tool"]) != "execute_sql":
            continue
        req = (t.get("args") or {}).get("request") or t.get("args") or {}
        m = re.search(r"\blimit\s+(\d+)\s*;?\s*$", str(req.get("sql") if isinstance(req, dict) else ""), re.I)
        n = int(m.group(1)) if m else 0
        result = str(t.get("result") or "")
        got = re.search(r'"row_count":\s*(\d+)', result)
        if n < 2 or n in asked or not got or int(got.group(1)) != n:
            continue
        rest = re.sub(r'"row_count":\s*\d+|"note":\s*"(?:[^"\\]|\\.)*"', " ", result)
        if re.search(rf"(?<![\d.]){n}(?![\d.])", rest):
            continue                                   # a value of the result too
        for hit in re.finditer(rf"(?<![\w.,]){re.escape(f'{n:,}')}(?!\w|[.,]\d)", text):
            before = text[max(0, hit.start() - 30):hit.start()].lower()
            after = text[hit.end():hit.end() + 14].lower()
            if re.search(r"(first|top|up to|at most|at least|more than|over|limit(ed)?( to| of| at)?|showing|shown|"
                         r"only|>=?|≥)\W*$", before) or re.search(r"^\W*(rows?|lines?|results?|entries|records?)\b",
                                                                   after):
                continue
            return n
    return None


def announces_action(answer: str) -> str | None:
    """The announced step at the end of an answer that called no tool for it, or None. Offers
    ("if you want, I can...", "let me know...") and questions are not announcements."""
    tail = (answer or "").strip()[-300:]
    last = re.split(r"(?<=[.!?])\s+|\n+", tail)[-1] if tail else ""
    if not last or last.rstrip().endswith("?") or re.search(r"\b(if you|let me know|would you|do you want|shall I|"
                                                            r"si vous|souhaitez|voulez|dites-moi)\b", last, re.I):
        return None
    m = ANNOUNCE.search(last)
    if m:
        return last.strip()[:160]
    return announced_plan(answer)


PLAN_LEAD = re.compile(r"\b(I(?:'ll| will| am going to|'m going to)|let me|let's|je vais|nous allons)\b[^\n]{0,120}:\s*$", re.I)
LIST_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+\S")


def announced_plan(answer: str) -> str | None:
    """An answer that is only a plan: "I'll do this in three steps:" then the list of steps, and nothing
    done (the model wrote what it would do instead of calling the tools). Its first line, or None."""
    lines = [ln for ln in (answer or "").strip().splitlines()]
    while lines and not lines[-1].strip():
        lines.pop()
    items = 0
    while lines and LIST_ITEM.match(lines[-1]):
        items += 1
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    lead = lines[-1].strip() if lines else ""
    return lead[:160] if items >= 2 and PLAN_LEAD.search(lead) else None


# the answer says all is well while a check or a query of this answer could not run
ALL_CLEAR = re.compile(
    r"\bno (?:breach|problem|issue|error|anomal\w*|incident|saturation|alert|failure)s?\b"
    r"|\b(?:everything|all) (?:is |looks |was |seems )?(?:fine|ok|okay|normal|healthy|good)\b"
    r"|\b(?:is|are|was|were|looks?|seems?|remained|stayed) (?:healthy|normal|fine|stable)\b"
    r"|\baucun(?:e)? (?:probl[èe]me|anomalie|incident|erreur|d[ée]passement|saturation|alerte|[ée]chec)\b"
    r"|\btout (?:est|va|semble|était) (?:bien|normal|ok|correct)\b", re.I)
NEGATION = re.compile(r"\b(?:cannot|can't|could not|couldn't|unable|not possible|impossible|does not mean|doesn't "
                      r"mean|not necessarily|whether|if|without|unknown|unclear|n'a pas pu|ne peut|impossible de|"
                      r"sans|si)\b", re.I)
CHECK_TOOLS = ("execute_sql", "promql_query", "check_health", "list_alerts", "compare_to_usual")


def _unchecked(trace: list[dict]) -> list[str]:
    """What could not be checked in this answer: checks of check_health that failed, and data
    tools whose last call failed (a failure fixed by a later successful call does not count)."""
    out: list[str] = []
    last: dict[str, str] = {}
    for t in trace:
        tool = t.get("called") or t["tool"]
        if tool not in CHECK_TOOLS:
            continue
        last[tool] = t.get("status") or ""
        if tool == "check_health" and t.get("status") == "done":
            try:
                errors = (json.loads(t.get("result") or "{}") or {}).get("errors") or {}
            except (ValueError, TypeError, AttributeError):
                errors = {}
            out += [f"check {name}" for name in errors if f"check {name}" not in out]
    out += [tool for tool, status in last.items() if status == "error"]
    return out


def claims_all_clear(answer: str) -> bool:
    for m in ALL_CLEAR.finditer(answer or ""):
        start = max((answer or "").rfind(".", 0, m.start()), (answer or "").rfind("\n", 0, m.start()), m.start() - 80)
        if not NEGATION.search(answer[max(0, start):m.start()]):
            return True
    return False


def honesty_note(answer: str, trace: list[dict]) -> str:
    """A short correction when the answer says all is well while something it relies on could
    not run (the model sometimes reads "could not reach" as "found nothing")."""
    missing = _unchecked(trace)
    if not missing or not claims_all_clear(answer):
        return ""
    return f"\n\n(Check: {', '.join(missing[:6])} could not run in this answer: what it covers was not checked.)"


RULES_GIVEN = 30         # the team's rules in the instructions (the next ones are found by the search)
RULES_NEAR_CHARS = 1500  # the rules given again next to the question, in full, up to this size
RULE_CHARS = 1500        # of each (a longer rule: its parts are also found by the search)


def rule_line(rule: dict[str, str]) -> str:
    """A catalog rule for the prompt; its title is not repeated when the text begins with it."""
    body = rule["text"][:RULE_CHARS]
    return body if body.startswith(rule["title"].rstrip("\u2026")) else f"{rule['title']}: {body}"


class Agent:
    """Answers one question at a time for one user (inside supagent.security.acting_as)."""

    def __init__(self, username: str, on_step: Callable[[list[dict]], None] | None = None,
                 llm: LLM | None = None, rich_results: bool = False,
                 should_stop: Callable[[], bool] | None = None) -> None:
        from supagent import tools, tools_superset  # noqa: F401  (registers the tools)
        from supagent.superset_mcp import SupersetMCP

        self.username = username
        self.on_step = on_step
        self.should_stop = should_stop
        self.rich = rich_results
        self.llm = llm or LLM()
        disabled = set(settings.get("agent.disabled_tools") or [])
        if rich_results:
            disabled.add("show_chart")           # the page draws real charts
        from supagent.tools import chromium_binary, screenshots_possible

        if chromium_binary() is None:            # tools that cannot work on this host are not offered
            disabled.add("chart_from_sql")
        if not screenshots_possible():
            disabled.add("chart_image")
        self.registry = tools.mcp
        self.local = {n: t for n, t in self.registry.tools.items() if n not in disabled}
        self.superset = SupersetMCP(username)
        self.specs = [t.spec() for t in self.local.values()]
        if "show_chart" not in disabled:
            self.specs.append(SHOW_CHART_SPEC)
        self.specs += [s for n, s in self.superset.specs.items() if n not in disabled]
        self.mcp_tools: set[str] = set()
        try:                                     # other MCP servers (mcp.servers): their tools too
            from supagent import mcp_sources

            extra = [x for x in mcp_sources.specs(username) if x["function"]["name"] not in disabled]
            self.specs += extra
            self.mcp_tools = {x["function"]["name"] for x in extra}
        except Exception:  # pylint: disable=broad-except   (the agent works without them)
            log.warning("supagent: the MCP servers' tools are not offered", exc_info=True)
        self.names = {s["function"]["name"] for s in self.specs}
        self.guard = ChartGuard(self)
        self.scope: Any = None                   # the databases, charts and dashboards of the question
        self.places: dict = {}                   # values of the question in several kinds of data
        self.follow_up = False                   # the question refers to the chat (its results may answer it)
        self.support: Any = None                 # what was said (the conditions of the queries come from it)
        self.open_question = False               # "what is happening", "why": the agent chooses what to look at
        self.people_words = ""
        self.asks_new = False                    # a follow-up with another day, value or period
        self.period_text: str | None = None      # what the period checks read (a follow-up's own day in place)
        self.max_steps = int(settings.get("agent.max_steps"))

    def close(self) -> None:
        self.superset.close()

    def _specs_for(self, question: str) -> list[dict]:
        """The tools offered for this question. In the chat page, the tools that save charts, make
        files, e-mails, reports or images are offered only when the question asks for them (every
        query result is already shown as a table and a chart): fewer tools, fewer wrong calls."""
        if not self.rich:
            return self.specs
        question = getattr(self, "intent_text", None) or question
        asked = intents(question) | self._route_intents()
        wanted = set().union(*(TOOLS_OF.get(k, set()) for k in asked)) if asked else set()
        if self.wants_saved_chart:
            wanted |= TOOLS_OF["charts"]
        if notes_request(question):                     # "add to my note ...": the notes tools only
            return [s for s in self.specs if s["function"]["name"] in TOOLS_OF["notes"]]
        return [s for s in self.specs if s["function"]["name"] not in INTENT_TOOLS or s["function"]["name"] in wanted]

    def route(self, question: str, previous: str = "") -> Any:
        """The router's decision for this question (once per question: the governed pipeline and its classic
        fallback share it), recorded on the answer's route row."""
        from supagent import router

        key = question                                  # once per question, whatever chat context comes with it
        if getattr(self, "_moa_key", None) == key and getattr(self, "moa", None) is not None:
            return self.moa
        uid = getattr(g_user(), "id", None)
        d = router.decide(question, previous, uid, llm=self.llm if router.enabled() else None)
        if router.enabled():
            self._router_usage = dict(getattr(self.llm, "last_usage", None) or {})
            self.route_id = router.record(getattr(self, "route_id", None), question, d, uid)
        self._moa_key, self.moa = key, d
        return d

    def _route_intents(self) -> set[str]:
        from supagent.router import ROUTE_INTENTS

        moa = getattr(self, "moa", None)
        return set(ROUTE_INTENTS.get(moa.route, set())) if moa is not None and moa.active else set()

    def _investigating(self, question: str) -> bool:
        """The question asks what is wrong and why (its words, or the router's route): the investigation's
        instructions, tools, system picture and calls."""
        return "investigation" in (intents(getattr(self, "intent_text", None) or question) | self._route_intents())

    def after_saved(self, message_id: int) -> None:
        """The runner saved the answer: its route row knows its message (Helpful then teaches the router)."""
        route_id = getattr(self, "route_id", None)
        if not route_id:
            return
        try:
            from superset import db

            from supagent.models import Route

            r = db.session.get(Route, route_id)
            if r is not None:
                r.message_id = message_id
                db.session.commit()
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: route not linked to its answer", exc_info=True)

    def _system(self, question: str, shown: set[str] | None = None) -> str:
        """The instructions: the same for every user and every question of a kind, so that the LLM
        server keeps them and the tools (which follow them) in its prompt cache from one question
        to the next; what is found for this question and user goes with the question
        (_question_blocks). `shown` gets the team's rules given in full here."""
        text = CORE + (RICH if self.rich else PLAIN) + OSAGG_RULES + PROMAGG_RULES
        found = intents(getattr(self, "intent_text", None) or question) | (
            {"charts"} if self.wants_saved_chart else set())
        if not self.rich:
            found |= {"files", "images"}
        found |= self._route_intents() & {"investigation"}      # the router read it as one
        for k in ("charts", "status", "sqllab", "investigation", "files", "images", "usual"):
            if k in found and not (k == "usual" and ("investigation" in found or "status" in found)):
                text += SECTIONS[k]
        text += "\n\nReminder: answer in the language of the question below."
        if not self.superset.available:
            text += ("\n- Saving charts and dashboards is not available here (" + (self.superset.error or "") +
                     "): answer with the query results instead.")
        extra = (settings.get("agent.extra_instructions") or "").strip()
        if extra:
            text += "\n" + extra
        try:
            from supagent.knowledge.catalog import rules

            team_rules = rules()[:RULES_GIVEN]
        except Exception:  # pylint: disable=broad-except
            team_rules = []
        if team_rules:
            text += "\n\nRules of the team (from the catalog: always follow them):"
            for r in team_rules:
                text += "\n- " + rule_line(r)
                if shown is not None and len(r["text"]) <= RULE_CHARS:
                    shown.add(f"entry:{r['id']}")
        return text

    def _rules_reminder(self) -> str:
        """The team's rules again next to the question (the instructions have them all; a model follows
        what is near the question better): in full when they are short, else a line naming them."""
        try:
            from supagent.knowledge.catalog import rules

            team_rules = rules()[:RULES_GIVEN]
        except Exception:  # pylint: disable=broad-except
            return ""
        if not team_rules:
            return ""
        lines = [rule_line(r) for r in team_rules]
        if sum(len(x) for x in lines) <= RULES_NEAR_CHARS:
            return ("\n\nThe team's rules, for every query of this answer (they win over the learned answers "
                    "below; apply one unless the question asks otherwise):\n" + "\n".join(f"- {x}" for x in lines))
        return ("\n\nApply the team's rules of the instructions to every query of this answer (they win over the "
                "learned answers below).")

    def _question_blocks(self, question: str, shown: set[str] | None = None) -> str:
        """What is found for this question and this user, given with the question: their memories,
        the team's words (glossary), where the data is, the knowledge that matches, the learned
        answers. Nothing twice: the knowledge found leaves out what the instructions (`shown`) and
        the other blocks give."""
        shown = set() if shown is None else shown
        text = ""
        try:
            from flask import g

            from supagent.knowledge.memory import prompt_block

            text += prompt_block(getattr(getattr(g, "user", None), "id", None), shown)
        except Exception:  # pylint: disable=broad-except
            pass
        text += self._rules_reminder()
        try:
            from supagent.knowledge.glossary import glossary_block

            text += glossary_block(question, shown)   # the team's words, before where the data is
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: the team's words: not given", exc_info=True)
        self.people_words = text                        # the memory, the rules, the glossary: what people said
        try:                                            # the parts the question names, and for an investigation
            from supagent.knowledge.brief import brief_block   # what they depend on and where they are in the data

            # (the whole picture for an investigation and a question of how the system works; for any other
            # question only what it names: a follow-up on a server's load needs no map of the platform)
            text += brief_block(question, full=self._investigating(question) or bool(self._route_intents() & {"system"}))
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: the system around the question: not given", exc_info=True)
        try:
            from supagent.knowledge.resolve import where_block

            text += where_block(question, shown)     # where the data is, found without the LLM
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: where the data is: not found", exc_info=True)
        try:
            from supagent.knowledge.experience import recipes_for

            recipes = recipes_for(question)
        except Exception:  # pylint: disable=broad-except
            recipes = []
        shown |= {f"recipe:{r['id']}" for r in recipes}
        if settings.get("search.enabled"):
            try:
                from supagent.knowledge.search import knowledge_block

                about = intents(getattr(self, "intent_text", None) or question) | self._route_intents()
                from supagent.router import ROUTE_KINDS

                moa = getattr(self, "moa", None)
                text += knowledge_block(question, shown, with_charts=bool(about & {"status", "read_charts", "charts"}),
                                        prefer=ROUTE_KINDS.get(moa.route) if moa is not None and moa.active else None)
            except Exception:  # pylint: disable=broad-except
                log.warning("supagent: knowledge found: not given", exc_info=True)
        if self._investigating(question):                # the paths the team validated for such problems
            try:
                from supagent.knowledge.paths import paths_block

                text += paths_block(question, shown)
            except Exception:  # pylint: disable=broad-except
                log.warning("supagent: the investigation paths: not given", exc_info=True)
        if recipes:
            text += ("\n\nWays that answered similar questions before (helpful = marked Helpful by a user, "
                     "confirmed = also approved by an admin). Start "
                     "from them, adapting dates, filters and names to this question and to the team's rules (a "
                     "rule wins over a learned query), and run the query again: "
                     "their results are not kept and are not the answer:")
            for r in recipes:
                where = f" on database id {r['database_id']}" if r.get("database_id") else ""
                speed = f", {r['seconds']:.1f} s" if r.get("seconds") is not None else ""
                if r["tool"] == "path":                  # no query to run again: the checks that answered it
                    text += (f"\n- Q: {r['question'][:240]}\n  the way it was answered ({r['status']}, used "
                             f"{r['uses']} time(s)): " + " ".join(r["query"].split())[:900])
                    continue
                text += (f"\n- Q: {r['question'][:240]}\n  {r['tool']}{where} ({r['status']}, used {r['uses']} "
                         f"time(s){speed}): {r['query'][:900]}")
                if r.get("path"):                        # the data it used and its steps (0.9)
                    text += f"\n  its path: {r['path']}"
        return text.strip()

    def _call(self, name: str, args: dict) -> tuple[str, str]:
        """(tool really called, its result text)."""
        from supagent.knowledge.excluded import query_texts, refusal, violations

        problems = violations(query_texts(args))        # what the team said not to use
        if problems:
            return name, refusal(problems)
        if name in SAVING_TOOLS:                  # names and texts saved in Superset's own tables
            from supagent.textsafe import db_codec, fold_all

            args = fold_all(args, db_codec())
        if name == "chart_from_sql" and self.wants_saved_chart and not self.redirected_chart \
                and "generate_chart" in self.names:
            self.redirected_chart = True
            return name, ("tool error: the user asked for a chart saved in Superset: chart_from_sql only makes an "
                          "image. Find the dataset (list_datasets / get_dataset_info), check the fields with "
                          "get_chart_type_schema, then call generate_chart with save_chart=true and the requested "
                          "chart_name.")
        if name == "show_chart":
            try:
                return name, show_chart(**args)
            except Exception as ex:  # pylint: disable=broad-except
                return name, f"tool error: {ex}"
        if name in getattr(self, "mcp_tools", ()):
            from supagent import mcp_sources

            return name, mcp_sources.call(self.username, name, args)
        if name in self.local:
            try:
                return name, self.registry.call_text(name, args)
            except Exception as ex:  # pylint: disable=broad-except
                return name, f"tool error: {type(ex).__name__}: {str(ex)[:1500]}"
        called, call_args, content = self.guard.before(name, args)
        if content is not None:
            return called, content
        content = self.superset.call(called, call_args)
        content = self.guard.after(called, call_args, content)
        if called != name:
            content = f"(a chart with this name was already saved: {called} was used)\n" + content
        return called, content

    def prompt(self, question: str, history: list[dict] | None = None) -> list[dict]:
        """What the LLM is given for this question, before any tool call: the instructions (with the
        team's rules), the chat so far, then with the question what is known for it (memory, where
        the data is, the knowledge found: dictionary, catalog, documents, Context, learned answers).
        `superset supagent prompt` shows it."""
        before = next((str(h["content"]) for h in reversed(history or [])
                       if h.get("role") == "user" and h.get("content")), "")
        said = next((str(h["content"]) for h in reversed(history or [])
                     if h.get("role") == "assistant" and h.get("content")), "")
        # "The failed jobs.": the user answers the question the agent asked back (a short reply, not a
        # question), or completes the previous question after an answer ("The failed jobs.", "Only PROD.")
        answered = bool(before) and bool(said) and asks_back(said) and not question.strip().endswith("?") and \
            len(question.split()) <= REPLY_WORDS
        earlier = [str(h["content"]) for h in history or [] if h.get("role") == "user" and h.get("content")]
        adds = adds_to(question, before, earlier)      # "And on 22 September?": another day, value or period
        last = next((h for h in reversed(history or []) if h.get("role") == "assistant"), None)
        self.prev_queries = [str(q.get("query") or "") for q in (last or {}).get("queries") or [] if q.get("query")]
        self.new_values: list[str] = []
        if before and not adds and self.prev_queries:   # "And the flash PnL?": a value of the data the previous
            try:                                        # answer's queries never used
                from supagent.knowledge.carry import new_values

                self.new_values = new_values(question, [before, said], self.prev_queries)
            except Exception:  # pylint: disable=broad-except   (no dictionary: as before)
                log.debug("supagent: new values of a follow-up not read", exc_info=True)
            adds = bool(self.new_values)
        self.new_fields: list[str] = []
        if before and self.prev_queries:                # "Which error code came up most often?": a field the
            try:                                        # previous queries never read: the chat cannot hold it
                from supagent.knowledge.carry import new_fields

                self.new_fields = new_fields(question, self.prev_queries)
            except Exception:  # pylint: disable=broad-except   (no dictionary: as before)
                log.debug("supagent: new fields of a follow-up not read", exc_info=True)
        completes = bool(before) and bool(said) and not answered and not adds and \
            len(question.split()) <= FRAGMENT_WORDS and bool(FRAGMENT.match(question or "")) and \
            not POSSESSIVE_FOLLOW_UP.search(question or "")   # "And its average latency?" asks a new measure
        # "And on the 23rd?", "And yesterday?": the previous question again, for another day (its own query)
        another_day = bool(before) and adds and len(question.split()) <= FRAGMENT_WORDS and \
            bool(FRAGMENT.match(question or ""))
        replied = answered or completes
        # the subjects (knowledge.topics) found it goes on from the last exchange with no data of its own
        from supagent.knowledge.topics import CONTINUES_LAST

        sub = getattr(self, "subject", None)
        goes_on_last = sub is not None and not getattr(sub, "back", False) and getattr(sub, "how", "") in CONTINUES_LAST
        follow = bool(before) and (refers_back(question) or replied or another_day or goes_on_last)
        # the chat's results may answer it only when it asks nothing new (no other day, value or period)
        self.follow_up = answered or (follow and not adds)
        self.asks_new = bool(before) and adds
        self.wants_saved_chart = bool(SAVED_CHART_ASK.search(f"{before}\n{question}" if follow else question or ""))
        # "what charts are in it?": the tools, instructions and checks of the question it refers to, too
        self.intent_text = f"{before}\n{question}" if follow else question
        self.question = self.intent_text                  # the checks of periods and rules read it
        # the period checks: a follow-up's own day in place of the earlier question's ("shipped on ... at night")
        from supagent.knowledge.period import follow_up_text

        self.period_text = (follow_up_text(question, earlier) if follow else None) or self.intent_text
        self.raw_question, self.chat_history = question, list(history or [])     # a yes, as the user wrote it
        from supagent.knowledge.carry import continues

        self.goes_on = bool(before) and continues(question, follow)
        self.moa = self.route(question, before if follow else "")
        try:
            from supagent.knowledge.scope import scope_for

            # the databases the question names, the charts and dashboards it (or the chat) is about
            self.scope = scope_for(question, before if follow else "", said if follow else "")
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: the databases of the question: not found", exc_info=True)
            self.scope = None
        try:
            from supagent.knowledge.resolve import value_places

            self.places = value_places(self.intent_text)   # a value in two kinds of data: the other reading
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: the values of the question: not found", exc_info=True)
            self.places = {}
        shown: set[str] = set()                          # given once: not again in the knowledge found
        messages: list[dict] = [{"role": "system", "content": self._system(question, shown)}]
        recent = (history or [])[-HISTORY_MESSAGES:]
        for h in recent:
            if h.get("content"):
                messages.append({"role": h["role"], "content": str(h["content"])[:HISTORY_CHARS]})
        lang = question_language(question)
        hint = f" {ANSWER_IN[lang]}" if lang else ""
        # "create a chart of that finding": where the data is, from the question it refers to
        blocks = self._question_blocks(self.intent_text, shown)
        self.given_refs = set(shown)                    # what the prompt was given (the learned items' ranking)
        behind = queries_note(recent)                   # what "that finding" was computed from
        if behind:
            blocks = f"{blocks}\n\n{behind}" if blocks else behind
        where = self.scope.block().strip() if self.scope is not None else ""
        if where:
            blocks = f"{blocks}\n\n{where}" if blocks else where
        if self.moa.active:                             # the router's instruction for this kind of question
            from supagent.router import ROUTE_NOTES

            note = ROUTE_NOTES.get(self.moa.route, "")
            blocks = f"{blocks}\n\n{note}" if blocks and note else (note or blocks)
        if settings.get("agent.calendar_facts") and self._investigating(question):
            try:                                        # the third Friday, the month end: what the team wrote of it
                from supagent.knowledge.calendar_facts import documented, note as calendar_note

                cal = documented(self.intent_text, now().date())
                if cal:
                    blocks = f"{blocks}\n\n{calendar_note(cal)}" if blocks else calendar_note(cal)
            except Exception:  # pylint: disable=broad-except   (a note, never a lost question)
                log.debug("supagent: the calendar facts not read", exc_info=True)
        asked = question
        if answered:                                    # the question, then the reply that settles it
            back = next((ln.strip() for ln in reversed(said.strip().splitlines()) if ln.strip()), "")[:400]
            asked = f"{before}\n(You asked: \"{back}\" My reply: {question}) Answer my question with this reading."
        elif completes:                                 # the question, then what the user adds to it
            asked = f"{before}\n(About your answer above: {question}) Answer my question again with this."
        if history and not (answered or completes) and POSSESSIVE_FOLLOW_UP.search(question or "") and \
                len((question or "").split()) <= 10:      # "And its average latency?" after the top error code
            asked += ("\n(\"its\"/\"their\" here may stand for the subject of this conversation or for what the "
                      "answer before named last: when both readings are possible, give the figure for both, each "
                      "said as such.)")
        unit = unit_carried(question, history)
        if unit and not (answered or completes):        # "in minutes?" then "And the longest one?": in minutes
            asked += (f"\n(The question before asked for its figure in {unit}: give this one in {unit} too, if it is "
                      "of the same kind.)")
        self.unclear = self._ask_first(question, history) if not (answered or completes) else None
        if self.unclear:                                # one thing named, several match; nothing to refer to
            from supagent.knowledge.ambiguity import note as ask_note

            blocks = f"{blocks}\n\n{ask_note(self.unclear)}" if blocks else ask_note(self.unclear)
        messages.append({"role": "user", "content": (blocks + "\n\n" if blocks else "") +
                         f"(Now: {now():%A %Y-%m-%d %H:%M}.{hint})\n{asked}"})
        try:                                            # what was said: the conditions of the queries come from it
            from supagent.knowledge.conditions import build

            people = [question, self.intent_text, getattr(self, "people_words", "")] + [
                str(h.get("content") or "") for h in recent if h.get("role") == "user"]
            self.support = build(messages, people)
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: what was said: not read", exc_info=True)
            self.support = None
        self.open_question = bool(intents(self.intent_text) & {"status", "investigation", "usual"})
        return messages

    def _quick_note(self, question: str) -> tuple[str, list[dict]] | None:
        """"Note for the team: ...", "Make a personal note for me: ...": saved at once, as "/note" is, without the
        LLM (which took such a message for a question in the lab); the answer names the note for what follows."""
        from supagent.knowledge.notes import asked_to_write

        asked = asked_to_write(question)
        if asked is None or not asked["text"]:
            return None
        from supagent.tools import add_note

        personal = asked["scope"] == "user"
        out = add_note(asked["text"], personal=personal)
        step = {"tool": "add_note", "called": "add_note", "status": "error" if "error" in out else "done",
                "args": {"text": asked["text"], "personal": personal}, "seconds": 0,
                "result": json.dumps(out, default=str)[:4000]}
        if "error" in out:
            return f"The note was not saved: {out['error']}", [step]
        saved = out["saved"]
        return (f"Saved {'for you' if personal else 'for the team'}: \u201c{saved['title']}\u201d (note {saved['id']}; "
                f"Notes, on the left). To add to it or change it, say so here."), [step]

    def ask(self, question: str, history: list[dict] | None = None) -> tuple[str, list[dict]]:
        quick = self._quick_note(question)
        if quick is not None:
            return quick
        self.guard.saved = {}
        self.redirected_chart = False
        self.refused: set[str] = set()                 # calls sent back before running: they run if sent again
        self._shapes: dict[str, set[str]] = {}         # the queries of this answer, their dates left out
        failed: dict[str, str] = {}
        charts: list[str] = []
        emailed: list[str] = []
        messages = self.prompt(question, history)
        asked_at = self._asked_at = len(messages)      # what the LLM was given, before its own words
        trace: list[dict] = []
        nudged = announced = numbers_asked = rules_asked = count_asked = looped = limit_asked = notes_asked = False
        named_asked = carry_asked = tie_asked = echoed = action_asked = future_asked = source_asked = False
        about_notes = notes_request(getattr(self, "intent_text", None) or question)
        done: set[str] = set()                         # identical successful calls: not run twice
        saved_calls: set[str] = set()                   # identical saving calls: not run again either
        self.usage = {}
        add_usage(self.usage, getattr(self, "_router_usage", None) or {})     # the router's call, if any
        self._router_usage = {}
        specs = self._specs_for(question)
        building = "charts" in intents(question) or self.wants_saved_chart
        steps = self.max_steps * (2 if building else 1)   # several charts and a dashboard: more calls
        if not building and self._investigating(question):
            steps = self.max_steps * INVESTIGATION_STEPS   # the facts, where, why, the check: more calls
        elif not building and len(re.findall(r",|;|\band\b|\bet\b", question or "")) >= MANY_PARTS:
            steps = int(steps * 1.5)                   # a report of many figures: more calls
        unreadable = full = 0
        forced = force_tool = ledger_asked = unclear_asked = grain_asked = definition_asked = stage_asked = False
        self.waiting_stage = None                      # the first stage off before the rows run (compare_groups)
        self.concentrated, self.scope_hinted = [], False   # where its change is; the logs scope said once
        self.ledger = self._new_ledger(question, history, building)
        if self.ledger is not None:                   # a big request: its tasks, notes and results kept by the system
            from supagent.ledger import RULES, SPEC

            specs = list(specs or []) + [SPEC]
            plan = f"{RULES}\nYour work plan so far (kept by the system):\n{self.ledger.render()}" if \
                self.ledger.tasks else RULES
            text = messages[-1]["content"]
            at = text.rfind("(Now: ")
            messages[-1]["content"] = (text[:at] + plan + "\n\n" + text[at:]) if at >= 0 else f"{plan}\n\n{text}"
        i, plan_turns, compacted, last_said, timed_out = -1, 0, 0, False, False
        budget, began = int(settings.get("agent.answer_seconds") or 0), time.time()
        while i + 1 < steps:                           # (a while: a turn that only kept the plan adds one)
            i += 1
            self._check_stop()
            if budget and trace and not timed_out and time.time() - began > budget:
                timed_out = True                       # the answer's time is up: this turn and one more, then it
                steps = min(steps, i + 2)              # answers (a slow LLM server: an answer, not a time-out)
                log.info("supagent: the answer's time is up (%d s): it answers now", budget)
                # and no check sends it back any more (each would cost a turn): what one would send back is marked
                # on the answer instead (the checks' second pass), and no tool call is made compulsory
                looped = notes_asked = unclear_asked = nudged = announced = rules_asked = carry_asked = echoed = True
                named_asked = tie_asked = numbers_asked = limit_asked = ledger_asked = stage_asked = future_asked = True
                source_asked = True
                grain_asked = definition_asked = count_asked = forced = action_asked = True
            if i >= steps - 2 and steps >= 4 and trace and not last_said:   # the answer before the calls run out
                last_said = True                       # (once: a plan-only turn there moves the end by one)
                messages.append({"role": "user", "content": (TIME_UP if timed_out else "") + LAST_CALLS
                                 + self._plan_note()})
            choice, force_tool = ("required" if force_tool else None), False
            try:
                msg = self.llm.chat(messages, tools=specs, max_tokens=self._answer_tokens(short=bool(unreadable)),
                                    **({"tool_choice": choice} if choice else {}))
            except EmptyAnswer:
                add_usage(self.usage, self.llm.last_usage)
                fallback = self._empty_fallback(trace)
                if fallback is None:
                    raise
                return fallback + self._marks(fallback, trace), trace
            except LLMError as ex:
                if CONTEXT_FULL.search(str(ex)) and full < len(SHRUNK) and trace:
                    n = shortened(messages, SHRUNK[full], KEPT_WHOLE if full == 0 else 1)
                    full += 1
                    log.info("supagent: the context was full: %d older tool results shortened", n)
                    if full == len(SHRUNK) or not n:
                        messages.append({"role": "user", "content": CONTEXT_FULL_NUDGE + self._plan_note()})
                    elif self.ledger is not None and self.ledger.tasks:     # the plan, whole, after the cut
                        messages.append({"role": "user", "content": "(The conversation was shortened: older results "
                                         "were cut." + self._plan_note() + ")"})
                    continue
                if not BAD_TOOL_CALL.search(str(ex)) or unreadable >= 2:
                    if unreadable and trace:           # it did things before: say what, not an error
                        return self._out_of_steps(messages, trace), trace
                    raise
                unreadable += 1                        # the server could not read the model's tool call
                log.info("supagent: unreadable tool call sent back (%s)", str(ex)[:200])
                messages.append({"role": "user", "content": UNREADABLE_CALL})
                continue
            add_usage(self.usage, self.llm.last_usage)
            messages.append({k: v for k, v in msg.items() if k in ("role", "content", "tool_calls")})
            calls = msg.get("tool_calls") or []
            if not calls:
                answer = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
                cut = repeating(answer)
                if cut is not None and not looped:     # once: an answer going round in circles
                    looped = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (repeats itself, %d characters)", len(answer))
                    messages[-1]["content"] = answer[:cut]
                    messages.append({"role": "user", "content": LOOP_NUDGE})
                    continue
                if cut is not None:                    # again: cut there, and said
                    answer = answer[:cut].rstrip()
                claimed = None if notes_asked else note_claim(answer, trace)
                if claimed:                            # once: "the note has been deleted" with no such call
                    notes_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (a note %s without %s)", *claimed)
                    messages.append({"role": "user", "content": NOTE_CLAIM_NUDGE.format(
                        what=claimed[0], tool=claimed[1], how=NOTE_HOW[claimed[1]])})
                    continue
                if notes_asked and claimed is None and (again := note_claim(answer, trace)):
                    log.info("supagent: a note %s without %s again: the answer says it was not done", *again)
                    return NOTE_NOT_DONE[again[1]], trace     # said twice, not done: not shown as done
                if getattr(self, "unclear", None) and not unclear_asked and not asks_back(answer):
                    unclear_asked = True               # once: "the options book" answered for one of five
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (ask back first: %s)", self.unclear.get("said"))
                    messages.append({"role": "user", "content": ASK_FIRST_NUDGE})
                    continue
                nudge = None if nudged or about_notes or getattr(self, "unclear", None) else unsupported_answer(answer, trace, question)
                # a follow-up restating the previous answer: all its numbers in that answer (not anywhere in a long
                # subject: "10,000" from an older answer is no VaR of the book asked about)
                previous = next(([m] for m in reversed(messages[:asked_at]) if m.get("role") == "assistant"
                                 and m.get("content")), [])
                earlier = [m["content"] for m in messages[:asked_at] if m.get("role") == "assistant"
                           and isinstance(m.get("content"), str)][-3:]
                one = None if source_asked or trace or not asks_back(answer) else self._needless_ask(question, answer)
                if one:                                # once: "which of these sources?" when the value is in one
                    source_asked = True
                    if not forced and settings.get("agent.force_tool"):
                        forced = force_tool = True     # the next step runs a query
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (a question back about sources; %s is in %s only)", one[0], one[2])
                    messages.append({"role": "user", "content": NEEDLESS_ASK_NUDGE.format(value=one[0], field=one[1],
                                                                                          table=one[2])})
                    continue
                if earlier and not echoed and not trace and any(echoes(answer, e) for e in earlier) and \
                        not AGAIN.search(question or ""):   # once: an earlier answer given again for a new question
                    echoed = nudged = True
                    if not forced and settings.get("agent.force_tool"):
                        forced = force_tool = True     # the next step runs a query
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (the previous answer given again)")
                    messages.append({"role": "user", "content": ECHO_NUDGE.format(question=(question or "")[:300])})
                    continue
                if nudge in (NO_TOOL_NUDGE, NO_QUERY_NUDGE) and self.follow_up and \
                        not getattr(self, "new_fields", None) and \
                        settings.get("agent.check_numbers") and previous and not self._ungrounded(answer, previous) \
                        and not self._invented(answer, previous + [{"role": "user", "content": question}]):
                    nudge = None                       # (never a "no such field" or a query written, not run, nor
                    #                                    names or times the previous answer does not hold)
                if nudge:                              # once: an answer from the tools, not from the summary
                    nudged = True
                    if (nudge == WRITTEN_SQL_NUDGE or (nudge in (NO_TOOL_NUDGE, NO_QUERY_NUDGE) and
                                                         (self.asks_new or getattr(self, "new_fields", None)))) \
                            and not forced and settings.get("agent.force_tool"):
                        forced = force_tool = True     # a query written, not run, or a follow-up that asks for
                        #                                another day, value or period: the next step runs one
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (no tool / no query): %r", answer[-200:])
                    messages.append({"role": "user", "content": nudge})
                    continue
                step = None if announced else announces_action(answer)
                if step:                               # once: "Let me run the query." with no tool call
                    announced = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (announced step): %r", step)
                    messages.append({"role": "user", "content": ANNOUNCE_NUDGE.format(step=step)})
                    continue
                missed = self._unapplied(question, trace)      # every answer (a question back has no query)
                if missed and not rules_asked:         # once: a rule of the team not applied
                    rules_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (rule not applied): %r", missed[0][:200])
                    messages.append({"role": "user", "content": RULES_NUDGE.format(rule=missed[0][:300])})
                    continue
                lost = None if carry_asked else self._dropped(question, trace)
                if lost:                               # once: a follow-up lost the previous conditions
                    carry_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    said = ", ".join(c.said() for c in lost[:4])
                    half = getattr(self, "half_carried", False)
                    log.info("supagent: answer sent back (previous conditions dropped%s: %s)",
                             ", the period kept" if half else "", said)
                    messages.append({"role": "user", "content": (CARRY_HALF_NUDGE if half else CARRY_NUDGE).format(
                        conds=said, them="them" if len(lost) > 1 else "it",
                        apply="apply" if len(lost) > 1 else "applies")})
                    continue
                gap = None if named_asked else self._unnamed(question, trace)
                if gap:                                # once: "web orders" counted over every channel
                    named_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (a named value not in the queries: %s)", gap)
                    from supagent.knowledge.named import left_out

                    nudge = NAMED_OUT_NUDGE if left_out(question, gap[0]) else NAMED_NUDGE
                    messages.append({"role": "user", "content": nudge.format(value=gap[0], field=gap[1], table=gap[2])})
                    continue
                ahead = None if future_asked else self._future(question, answer, trace)
                if ahead:                              # once: next week answered with last week, silently
                    future_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (the future answered with past figures, not said)")
                    messages.append({"role": "user", "content": FUTURE_NUDGE.format(start=ahead)})
                    continue
                loose = None if tie_asked else self._untied(question, answer, trace)
                if loose:                              # once: a cause that nothing ties to the question's parts
                    tie_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (a cause not tied to the question's parts: %s)", loose[0])
                    messages.append({"role": "user", "content": TIE_NUDGE.format(
                        names=loose[0], scope=loose[1], it="them" if "," in loose[0] else "it")})
                    continue
                unknown = self._ungrounded(answer, messages[:asked_at] + [
                    m if m["role"] == "tool" else {"role": "assistant", "tool_calls": m["tool_calls"]}
                    for m in messages[asked_at:-1] if m["role"] == "tool" or m.get("tool_calls")])
                if unknown and not numbers_asked:      # once: numbers the model wrote itself
                    numbers_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (numbers not in the results): %s", unknown)
                    messages.append({"role": "user", "content": NUMBERS_NUDGE.format(numbers=", ".join(unknown[:12]))})
                    if not forced and not self._queried(trace) and settings.get("agent.force_tool"):
                        forced = force_tool = True     # no query ran: they can only come from one
                    continue
                invented = None if forced or self._queried(trace) or asks_back(answer) else \
                    self._invented(answer, messages[:asked_at] + [
                    m if m["role"] == "tool" else {"role": "assistant", "tool_calls": m["tool_calls"]}
                    for m in messages[asked_at:-1] if m["role"] == "tool" or m.get("tool_calls")])   # not its own words
                if invented and settings.get("agent.force_tool"):    # once: names or times no tool gave
                    forced = force_tool = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (names or times no tool gave): %s", invented)
                    messages.append({"role": "user", "content": INVENTED_NUDGE.format(names=", ".join(invented[:8]))})
                    continue
                claimed_action = None if action_asked or asks_back(answer) else action_claim(answer, trace)
                if claimed_action:                     # once: "added to the dashboard" with no such call: do it
                    action_asked = True
                    if not forced and settings.get("agent.force_tool"):
                        forced = force_tool = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (an action claimed, not done: %s)", claimed_action[0])
                    messages.append({"role": "user", "content": ACTION_NUDGE.format(what=claimed_action[0],
                                                                                    tool=claimed_action[1])})
                    continue
                read_as_count = limit_as_count(answer, trace, question)
                if read_as_count and not limit_asked:  # once: the rows a LIMIT let through read as a count
                    limit_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (LIMIT %s read as a count)", read_as_count)
                    messages.append({"role": "user", "content": LIMIT_NUDGE.format(n=read_as_count)})
                    continue
                gaps = None if ledger_asked or self.ledger is None or asks_back(answer) else self._ledger_gaps(answer)
                if gaps:                               # once: tasks of the plan not done, findings not explained
                    ledger_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (work plan: %s)", gaps[:200])
                    messages.append({"role": "user", "content": LEDGER_NUDGE.format(gaps=gaps)})
                    continue
                stage = getattr(self, "waiting_stage", None)
                if stage and not stage_asked and not asks_back(answer) and capacity_blamed(answer):
                    stage_asked = True                 # once: a full pool blamed for rows that were not ready
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (capacity blamed, the first stage off is %s)", stage)
                    messages.append({"role": "user", "content": STAGE_NUDGE.format(stage=stage)})
                    continue
                bucket = None if grain_asked else self._time_from_bucket(question, answer, trace)
                if bucket:                             # once: "at 04:00" read from hourly buckets
                    grain_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (a time read from %s buckets: %s)", bucket[1], bucket[0])
                    messages.append({"role": "user", "content": GRAIN_NUDGE.format(time=bucket[0], grain=bucket[1])})
                    continue
                differs = None if definition_asked else (self._definition_unlinked(question, trace) or
                                                         self._definition_differs(question, trace))
                if differs:                            # once: a defined term computed another way
                    definition_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (the definition of %s: %s)", differs[0], differs[2][:200])
                    messages.append({"role": "user", "content": DEFINITION_NUDGE.format(
                        term=differs[0], definition=differs[1][:700], why=differs[2])})
                    continue
                if not count_asked and missing_count(question, answer):     # once: "how many" answered with shares
                    count_asked = True
                    self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                    log.info("supagent: answer sent back (no count for how many)")
                    messages.append({"role": "user", "content": COUNT_NUDGE})
                    continue
                if nudged or announced or numbers_asked or rules_asked or count_asked or looped or limit_asked or \
                        notes_asked or named_asked or carry_asked or tie_asked:
                    answer = without_correction_lead(without_apology(answer))   # written again after a check the
                    #                                                                user never saw
                answer = without_preamble(answer)
                missing = [c for c in charts if c.splitlines()[-1].strip() not in answer]
                if missing:
                    answer += "".join(f"\n\n```\n{c}\n```" for c in missing)
                if not self.rich:
                    answer += table_if_missing(answer, trace)
                    answer += chart_if_missing(answer, trace)
                else:
                    answer = local_links(answer)       # the page shows the files itself
                    if any(t.get("full") for t in trace):
                        answer = trim_tables(answer)   # every row is in the page's result view
                note = unsupported_note(answer, trace, question) if nudged else ""
                if nudged and not note and self.asks_new and _has_data(answer) and \
                        not {t.get("called") or t["tool"] for t in trace if t.get("status") == "done"} & set(QUERY_TOOLS):
                    note = UNSUPPORTED_NOTE            # "And on 22 September?" answered with the chat's numbers
                if unknown:                            # a list continued past the results: that line goes
                    answer, unknown = without_extrapolation(answer, unknown)
                if unknown:                            # still there after asking: marked
                    note += NUMBERS_NOTE.format(numbers=", ".join(unknown[:12]))
                if missed:
                    note += RULES_NOTE.format(rule=missed[0][:300])
                if read_as_count:                      # still there after asking: marked
                    note += LIMIT_NOTE.format(n=read_as_count)
                kept = self._dropped(question, trace) if carry_asked else None
                if kept:                               # still dropped after asking: said
                    note += CARRY_NOTE.format(conds=", ".join(c.said() for c in kept[:4]))
                still = self._unnamed(question, trace) if named_asked else None
                if still:                              # still not in the queries after asking: marked
                    note += NAMED_NOTE.format(value=still[0], field=still[1])
                if future_asked and self._future(question, answer, trace):
                    note += FUTURE_NOTE                # still past figures for the future, not said: marked
                loose = self._untied(question, answer, trace) if tie_asked else None
                if loose:                              # still blamed after asking: marked
                    note += TIE_NOTE.format(names=loose[0], scope=loose[1], it="them" if "," in loose[0] else "it")
                note += self._marks(answer, trace, conditions_only=True)
                if cut is not None:
                    note += LOOP_NOTE
                self._keep_ledger(trace)
                return (answer + claims_check(answer, trace) + honesty_note(answer, trace) + note +
                        self._other_reading(answer, trace)), trace
            for at, tc in enumerate(calls):
                self._check_stop()
                name = tc["function"]["name"]
                if at >= CALLS_AT_ONCE:                # a flood of calls in one message: the first ones only
                    messages.append({"role": "tool", "tool_call_id": tc.get("id", name), "content": (
                        f"tool error (not run): {CALLS_AT_ONCE} calls at most in one message. Read the results above "
                        "first; then make the calls that are still needed, one question each.")})
                    continue
                try:
                    args = json.loads(tc["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                props = (self.superset.schema(name) or {}).get("properties", {})
                if list(props) == ["request"] and "request" not in args:
                    args = {"request": args}
                if name == "delete_note":
                    args = self._confirm_delete(args)
                step = {"tool": name, "args": args, "status": "running", "started": time.time()}
                trace.append(step)
                self._report(trace)
                t0 = time.time()
                call_key = name + json.dumps(args, sort_keys=True, default=str)
                called = name
                refused = None
                if name == "work_plan" and self.ledger is not None:
                    content = self.ledger.plan(args.get("tasks") if "tasks" in args else args.get("request"))
                elif name not in self.names:
                    content = f"unknown tool {name}"
                elif name == "send_email" and emailed:
                    content = (f"An e-mail was already sent for this request ({emailed[0]}): do not send another "
                               "one; tell the user what it contained.")
                elif call_key in failed:
                    content = (f"You already made exactly this call and it failed: {failed[call_key][:600]}. "
                               "Change the arguments as the error says, or answer the user.")
                elif call_key in done or call_key in saved_calls:
                    content = REPEAT_NOTE
                else:
                    refused = self._refusal(name, args)
                    again = call_key in self.refused
                    if refused and again and "(not run: another database)" not in refused \
                            and "(not run: confirmation)" not in refused and "(not run: one query per day)" not in refused:
                        refused = None                 # sent again unchanged: the period, a rule, a count may be meant
                    if refused:                        # another database: never (the question did not name it)
                        if again:                      # a third time: "you already made this call and it failed"
                            failed[call_key] = refused
                        self.refused.add(call_key)
                        self.usage["nudges"] = self.usage.get("nudges", 0) + 1
                        log.info("supagent: call sent back before running: %s", refused[:200])
                        content = refused
                    else:
                        called, content = self._call(name, args)
                    if name == "show_chart" and not content.startswith("tool error"):
                        charts.append(content)
                if re.search(r'"(error|success)":\s*("|false)|^(error|tool error|unknown tool)', content[:300]):
                    if not refused:
                        failed[call_key] = content
                    step["status"] = "error"
                else:
                    step["status"] = "done"
                    if self.scope is not None:
                        from supagent.knowledge.scope import learn_from_call

                        learn_from_call(self.scope, called, args)
                    if called == "send_email" and '"sent_to"' in content:
                        emailed.append(content[:300])
                    if content is not REPEAT_NOTE:
                        if called in SAVING_TOOLS:     # something changed: reading it again is not a repeat,
                            done.clear()               # saving the very same thing again is
                            saved_calls.add(call_key)
                        else:
                            done.add(call_key)
                if called in RESULT_TOOLS and step["status"] == "done" and content is not REPEAT_NOTE:
                    step["full"] = content               # for the page, never sent to the model whole
                    if getattr(self, "support", None) is not None:   # the 3 servers found: the next queries
                        req = args.get("request") if isinstance(args.get("request"), dict) else args
                        self.support.add_result(content, str(req.get("sql") or ""))   # may use them
                    if called == "execute_sql":
                        from supagent.knowledge.experience import compact_for_llm

                        content = compact_for_llm(content, question)
                        empty = self._window_note(called, args, content)
                        if empty:                      # no sample in the default window: no absence from it
                            content += "\n" + empty
                notes: list[str] = []                  # the system's own notes: after the result, never cut with it
                inputs_logs = None
                if called == "compare_groups" and step["status"] == "done" and getattr(self, "waiting_stage", None) \
                        is None and self._investigating(question):   # (the question's own comparison: the first)
                    from supagent.knowledge.groups import before_start

                    self.waiting_stage = before_start(content)
                    self.concentrated = CONCENTRATED.findall(content)[:3]   # where the change is: logs read there
                    if self.waiting_stage:             # late before ready: what they wait for, from the map
                        note = self._inputs_note(args, content)
                        if note:
                            notes.append(note)
                            inputs_logs = logs_lead(note)
                if called == "compare_logs" and step["status"] == "done" and getattr(self, "concentrated", None) \
                        and not getattr(self, "scope_hinted", False):
                    hint = self._logs_scope_hint(args)
                    if hint:                           # once: the logs read everywhere, the change is in one place
                        self.scope_hinted = True
                        notes.append(hint)
                if self.ledger is not None and name != "work_plan":
                    self.ledger.attach(called, content)
                    if called == "compare_groups" and step["status"] == "done" and self._investigating(question):
                        made = self.ledger.seed_findings(content)
                        if inputs_logs:                # what the inputs' logs say that they do not usually: a lead
                            t = self.ledger.add(f"Explain or rule out: the logs of the inputs say {inputs_logs[0]}",
                                                by="system", keys=inputs_logs[1])
                            made += [t] if t is not None else []
                        if made:
                            notes.append("\n(Added to your work plan: " + "; ".join(f"{t.id}. {t.title[:90]}" for t in made)
                                         + ": explain each, or rule it out, in the answer.)")
                    from supagent.ledger import REMIND_EVERY

                    if self.ledger.tasks and self.ledger.calls_since_update >= REMIND_EVERY:
                        self.ledger.calls_since_update = 0
                        notes.append("\n" + self.ledger.reminder())
                limit = TOOL_CHARS.get(name, MAX_TOOL_CHARS)
                room = max(limit // 2, limit - sum(len(n) for n in notes))
                if len(content) > room:
                    content = content[:room] + "\n...[truncated]"
                content += "".join(notes)
                step.update(called=called, seconds=round(time.time() - t0, 1), result=content[:4000])
                self._report(trace)
                messages.append({"role": "tool", "tool_call_id": tc.get("id", name), "content": content})
            if self.ledger is not None and plan_turns < FREE_PLAN_TURNS and not timed_out and \
                    all(tc["function"]["name"] == "work_plan" for tc in calls[:CALLS_AT_ONCE]):
                plan_turns += 1                        # a turn that only kept the plan: not one of the calls
                steps += 1
            compacted = self._compact(messages, compacted)    # long before full: the older results cut, the plan kept
        out = self._out_of_steps(messages, trace)
        self._keep_ledger(trace)
        return out, trace

    def _out_of_steps(self, messages: list[dict], trace: list[dict]) -> str:
        """No calls left: the LLM says, without tools, what was done (what is saved, with its links) and
        what remains, instead of an answer that only says it stopped."""
        given = self._given(messages)
        messages.append({"role": "user", "content": OUT_OF_STEPS + self._plan_note()})
        try:
            msg = self.llm.chat(messages, tools=None, max_tokens=self._answer_tokens())
            add_usage(self.usage, self.llm.last_usage)
            text = re.sub(r"<think>.*?</think>", "", msg.get("content") or "", flags=re.S).strip()
            # a call written as text instead of a summary ("<tool_call><function=execute_sql>..."): not shown
            text = re.sub(r"<tool_call>.*?(</tool_call>|$)|<function=.*?(</function>|$)", "", text, flags=re.S).strip()
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: the summary after the last call failed", exc_info=True)
            text = ""
        cut = repeating(text)
        if cut is not None:
            text = text[:cut].rstrip()
        text = without_preamble(text)
        found = self._ledger_findings() if not text or (announces_action(text) and len(text) < 800) else ""
        if found:                                      # nothing written, or only "let me check ...": what the
            text = found                               # work found, from its plan's notes, rather than nothing
        if not text:
            got = self._empty_fallback(trace)          # what the queries gave, rather than nothing
            if got:
                return got + self._marks(got, trace) + ("\n\n(Stopped: the tool calls of one answer were used up; "
                                                         "ask a narrower question.)")
            return "(stopped after too many tool calls: ask a narrower question)"
        if self.rich:
            text = local_links(text)
        return (text + claims_check(text, trace) + self._marks(text, trace, given=given) +
                (LOOP_NOTE if cut is not None else "") + "\n\n(Stopped: the tool calls of one answer were used up.)")

    def _answer_tokens(self, short: bool = False) -> int | None:
        """The most tokens one LLM answer may have (llm.max_answer_tokens; with thinking, four times as
        many: the reasoning counts too): a model repeating itself stops there. `short`: the step after a tool
        call the server could not read (a call that ran on to the limit): a quarter of it, so that a second one
        does not take as many minutes again."""
        try:
            cap = int(settings.get("llm.max_answer_tokens") or 0)
        except Exception:  # pylint: disable=broad-except
            return None
        if short:
            cap = min(cap or RETRY_TOKENS, max(RETRY_TOKENS, (cap or 0) // 4))
        if cap and getattr(getattr(self.llm, "cfg", None), "thinking", False):
            cap *= 4
        return cap or None

    def _given(self, messages: list[dict]) -> list[dict]:
        """What the LLM was given for this answer: the prompt, the tool results and calls (not its own words)."""
        at = getattr(self, "_asked_at", len(messages))
        return messages[:at] + [m if m["role"] == "tool" else {"role": "assistant", "tool_calls": m["tool_calls"]}
                                for m in messages[at:] if m["role"] == "tool" or m.get("tool_calls")]

    def _marks(self, answer: str, trace: list[dict], given: list[dict] | None = None,
               conditions_only: bool = False) -> str:
        """The notes an answer gets whatever way it ends (an answer, the calls used up, no text): numbers
        nothing supports (when `given`), a team rule not applied, a condition nobody asked for."""
        note = ""
        if not conditions_only:
            unknown = self._ungrounded(answer, given) if given is not None else []
            if unknown:
                note += NUMBERS_NOTE.format(numbers=", ".join(unknown[:12]))
            missed = self._unapplied(getattr(self, "question", ""), trace)
            if missed:
                note += RULES_NOTE.format(rule=missed[0][:300])
            read_as_count = limit_as_count(answer, trace, getattr(self, "question", ""))
            if read_as_count:
                note += LIMIT_NOTE.format(n=read_as_count)
        if not getattr(self, "open_question", False):
            from supagent.knowledge.conditions import note as condition_note

            note += condition_note(getattr(self, "support", None), trace)
        return note

    def _confirm_delete(self, args: dict) -> dict:
        """delete_note in the answer to the user's yes (to the answer before, which asked to delete that note): the
        deletion they confirmed, not shown to them once more (the lab: asked, "yes", then asked again)."""
        if args.get("confirmed"):
            return args
        try:
            from supagent.knowledge.notes import delete_refusal

            if delete_refusal(getattr(self, "raw_question", ""), getattr(self, "chat_history", []),
                              {**args, "confirmed": True}) is None:
                return {**args, "confirmed": True}
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: the confirmation of a deletion was not read", exc_info=True)
        return args

    def _dropped(self, question: str, trace: list[dict]) -> list:
        """The previous answer's conditions this follow-up's queries lost (knowledge.carry). A message the subjects
        found on the same data with no word that refers back ("Top two products by number of trades?" after two
        questions on one desk and day) is checked too when this answer's queries carry the previous answer's period
        that the message does not say: they took it as going on from it, and then lost its other conditions."""
        if not getattr(self, "prev_queries", None):
            return []
        try:
            from supagent.knowledge.carry import carries_period, dropped
            from supagent.knowledge.rulecheck import _queries

            current = _queries(trace)
            self.half_carried = False
            if not getattr(self, "goes_on", False):
                from supagent.knowledge.period import has_period

                if has_period(question, now().date()) or not carries_period(self.prev_queries, current):
                    return []
                self.half_carried = True
            return dropped(question, self.prev_queries, current)
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            from superset.extensions import db

            db.session.rollback()
            log.warning("supagent: the check of a follow-up's conditions failed", exc_info=True)
            return []

    def _needless_ask(self, question: str, answer: str):
        """A question back about which data to use when the value the question names is in one of them only
        (knowledge.resolve.needless_ask): (value, field, table) or None."""
        try:
            from supagent.knowledge.resolve import needless_ask

            return needless_ask(getattr(self, "raw_question", None) or question, answer)
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            from superset.extensions import db

            db.session.rollback()
            log.warning("supagent: the check of a question back failed", exc_info=True)
            return None

    def _future(self, question: str, answer: str, trace: list[dict]):
        """A question about the future answered with past figures and nothing said about it (knowledge.period)."""
        try:
            from supagent.knowledge.period import future_unsaid
            from supagent.knowledge.rulecheck import _queries

            return future_unsaid(getattr(self, "raw_question", None) or question, answer, _queries(trace), now().date())
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            log.warning("supagent: the check of a question about the future failed", exc_info=True)
            return None

    def _unnamed(self, question: str, trace: list[dict]) -> tuple[str, str, str] | None:
        """The first value the question names that this answer's queries never use (knowledge.named)."""
        try:
            from supagent.knowledge.named import unused
            from supagent.knowledge.rulecheck import _queries

            found = unused(question, _queries(trace))
            return found[0] if found else None
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            from superset.extensions import db

            db.session.rollback()
            log.warning("supagent: the check of named values failed", exc_info=True)
            return None

    def _untied(self, question: str, answer: str, trace: list[dict]) -> tuple[str, str] | None:
        """An investigation's answer blames parts of the system that nothing ties to the question's parts (the
        system map, the results of its own queries): (their names, the question's parts), else None."""
        if not self._investigating(question):
            return None
        try:
            from supagent.knowledge.leads import untied

            names, scope = untied(getattr(self, "intent_text", None) or question, answer, trace)
        except Exception:  # pylint: disable=broad-except   (a check never breaks an answer)
            log.warning("supagent: the check of the cause: not done", exc_info=True)
            return None
        return (", ".join(names[:6]), scope) if names else None

    def _refusal(self, name: str, args: dict) -> str | None:
        """Why this call is sent back before it runs (once), every reason at once: it reads a table in
        another database than the one the question or its charts name, it misses the question's period,
        or its data needs a team rule it does not apply."""
        try:
            from supagent.knowledge import rulecheck
            from supagent.knowledge.period import refusal as period_refusal
            from supagent.knowledge.scope import refusal

            from supagent.knowledge.conditions import refusal as condition_refusal

            question = getattr(self, "intent_text", None) or getattr(self, "question", "")
            if name == "delete_note":                  # the user's yes first, in their own message
                from supagent.knowledge.notes import delete_refusal

                return delete_refusal(getattr(self, "raw_question", ""), getattr(self, "chat_history", []), args)
            reasons = [refusal(self.scope, name, args) if self.scope is not None else None,
                       period_refusal(getattr(self, "period_text", None) or question, name, args,
                                      prior=getattr(self, "prev_queries", None),
                                      comparing=getattr(self, "open_question", False)),
                       self._day_by_day(name, args),
                       self._counted_samples(name, args, question),
                       None if getattr(self, "open_question", False) else
                       condition_refusal(getattr(self, "support", None), name, args)]
            from supagent.knowledge.sqllint import duplicate_refusal, extreme_refusal, or_and_refusal, per_day_refusal
            from supagent.knowledge.values import refusal as value_refusal

            reasons.append(duplicate_refusal(name, args))      # two columns, one aggregate: a condition lost
            reasons.append(or_and_refusal(name, args))         # a OR b AND c: c on b only
            reasons.append(per_day_refusal(question, name, args))   # an average per day as AVG over the records
            reasons.append(extreme_refusal(name, args))        # MAX(...) AS min_...: the other extreme
            if not getattr(self, "open_question", False):    # an investigation looks values up: none is news
                reasons.append(value_refusal(name, args))      # a field compared with a value it does not have
            reasons.append(self._fanout(name, args))           # a join that repeats the rows it sums
            if name in ("generate_chart", "update_chart"):
                req = args.get("request", args)
                config = req.get("config") if isinstance(req, dict) else None
                saving = isinstance(req, dict) and ((name == "generate_chart" and req.get("save_chart"))
                                                    or name == "update_chart")
                if saving and isinstance(config, dict):
                    reasons.append(rulecheck.chart_refusal(question, self._chart_dataset(name, req), config))
            else:
                reasons.append(rulecheck.call_refusal(question, name, args))
            reasons = [r for r in reasons if r]
            if not reasons:
                return None
            more = [re.sub(r"^tool error \(not run: [^)]*\): ", "", r) for r in reasons[1:]]
            return reasons[0] + ("".join(f" Also: {x}" for x in more))
        except Exception:  # pylint: disable=broad-except   (never a call lost for a check)
            log.warning("supagent: the checks before a call failed", exc_info=True)
            try:
                from superset.extensions import db

                db.session.rollback()
            except Exception:  # pylint: disable=broad-except
                pass
            return None

    def _day_by_day(self, name: str, args: dict) -> str | None:
        """The same query once per day: it differs from two earlier ones of this answer only by its dates (a
        date, a time, a business-date label). Fifteen calls for fifteen days is one query grouped by day, or one
        compare_groups; the calls of an answer are for what is not yet known."""
        if name != "execute_sql":
            return None
        req = args.get("request") if isinstance(args.get("request"), dict) else args
        sql = " ".join(str(req.get("sql") or "").split())
        if not sql or not DAY_LITERAL.search(sql):
            return None
        seen = getattr(self, "_shapes", None)
        if seen is None:
            seen = self._shapes = {}
        same = seen.setdefault(DAY_LITERAL.sub("'?'", sql), set())
        same.add(sql)
        if len(same) < PER_DAY:
            return None
        return ("tool error (not run: one query per day): this query differs from " + str(len(same) - 1) + " earlier "
                "ones only by its dates. Do not ask day by day. One query over the whole range grouped by day (GROUP BY "
                "DATE_TRUNC('day', the time field), or by the business date) gives every day at once; compare_groups "
                "compares a day with the earlier ones in one call (measure = the figure, e.g. \"avg(FIELD)\").")

    def _other_reading(self, answer: str, trace: list[dict]) -> str:
        """A value the question named that is also in data the answer did not read nor mention (BILLING_API's
        HTTP metrics when the answer counted its failed jobs): one line, so the user can ask for it."""
        places = getattr(self, "places", None)
        if not places or asks_back(answer):
            return ""
        try:
            from supagent.knowledge.resolve import other_reading
            from supagent.knowledge.rulecheck import _queries, _tables

            tables = set().union(*[_tables(q) for q in _queries(trace)] or [set()])
            return other_reading(answer, tables, places)
        except Exception:  # pylint: disable=broad-except
            log.warning("supagent: the other reading: not given", exc_info=True)
            return ""

    @staticmethod
    def _counted_samples(name: str, args: dict, question: str = "") -> str | None:
        """COUNT over a counter of a metrics database (samples, not events), or a "how many" answered with
        per-second rates added up."""
        from superset.extensions import db
        from superset.models.core import Database

        from supagent.knowledge.excluded import query_texts
        from supagent.knowledge.experience import count_of_counter, rate_as_count
        from supagent.knowledge.scope import call_target

        database_id, _tables = call_target(name, args)
        database = db.session.get(Database, database_id) if database_id is not None else None
        if database is None:
            return None
        sqls = [q for q in query_texts(args) if q]
        if not sqls or name == "promql_query":
            return None
        return count_of_counter(database, sqls[-1], question) or rate_as_count(database, sqls[-1], question)

    def _compact(self, messages: list[dict], done: int) -> int:
        """Long before the context is full (agent.compact_at prompt tokens, then half as much again): the tool
        results but the latest COMPACT_KEPT cut to their first characters (their conclusion comes first), once per
        level, with the work plan given again; models read long contexts worse well before their limit. How many
        levels are done."""
        try:
            at = int(settings.get("agent.compact_at") or 0)
        except Exception:  # pylint: disable=broad-except
            return done
        used = int((getattr(self.llm, "last_usage", None) or {}).get("prompt_tokens") or 0)
        if not at or done >= len(SHRUNK) or used < at * (1 + 0.5 * done):
            return done
        n = shortened(messages, SHRUNK[done], COMPACT_KEPT)
        if not n:
            return done                                # (nothing old enough to cut yet: the next turn)
        log.info("supagent: %d older tool results shortened at %d prompt tokens", n, used)
        messages.append({"role": "user", "content": "(The conversation was getting long: older results were cut to "
                         "their first lines." + self._plan_note() + " Go on from there.)"})
        return done + 1

    def _inputs_note(self, args: dict, content: str = "") -> str:
        """The inputs of the parts a comparison was scoped to (the values its scope names), two steps up the system
        map, when its rows were late before they were ready (agent.inputs_walk)."""
        if not settings.get("agent.inputs_walk"):
            return ""
        try:
            from supagent.knowledge.brief import inputs_of

            req = args.get("request") if isinstance(args.get("request"), dict) else args
            names = re.findall(r"'([^']{2,80})'", str((req or {}).get("where") or ""))
            found = inputs_of(names) if names else []
            if not found:
                return ""
            said = "; ".join(f"{name} ({cat}), which {fed} takes in" for name, cat, fed in found)
            return ("\n(The rows were late before they were ready: they waited for their inputs. What the system map "
                    f"says they take in: {said}. Check whether those were late themselves (their own times against "
                    "usual, their records) before naming a capacity or a slowness.)") + self._upstream_logs(
                found, req, CONCENTRATED.findall(content or "")[:2])
        except Exception:  # pylint: disable=broad-except   (a note, never a lost result)
            log.debug("supagent: the inputs of the scope not read", exc_info=True)
            return ""

    def _logs_scope_hint(self, args: dict) -> str:
        """compare_logs read every value of a field the first comparison found the change concentrated on (the pool
        the rows waited on): the same lines of the other values can hide what is new there (a live answer said the
        logs show nothing new; the same call on that pool shows a new pattern)."""
        try:
            from supagent.knowledge.linkfinder import log_tables

            req = args.get("request") if isinstance(args.get("request"), dict) else args
            table, where = str((req or {}).get("table") or ""), str((req or {}).get("where") or "")
            owners = next((t.get("owners") or {} for t in log_tables() if t.get("table") == table), {})
            for f, values in getattr(self, "concentrated", None) or []:
                vals = [v.strip() for v in values.split(",") if v.strip()][:3]
                if f in owners and vals and not re.search(rf'\b{re.escape(f)}\b', where):
                    listed = ", ".join("'" + v.replace("'", "''") + "'" for v in vals)
                    return (f"\n(The first comparison found the change concentrated on {f} = {', '.join(vals)}: this call "
                            f"read every {f}, and the same lines of the other values can hide what is new there. Read "
                            f"the logs again with \"{f}\" IN ({listed}) before saying what they show.)")
        except Exception:  # pylint: disable=broad-except   (a note, never a lost result)
            log.debug("supagent: the scope of the logs not checked", exc_info=True)
        return ""

    @staticmethod
    def _upstream_logs(found: list[tuple[str, str, str]], req: dict, where: list[tuple[str, str]] | None = None) -> str:
        """What the logs of those inputs say that they do not usually (compare_logs called by code on the first log
        table with a field of their category, over the comparison's window: first where the change is concentrated,
        `where` (the pool the rows waited on), then everywhere; agent.inputs_logs): a late input often says so
        itself ("still waiting for its inputs: <feed>")."""
        if not settings.get("agent.inputs_logs") or not req.get("start") or not req.get("end"):
            return ""
        from supagent.knowledge.linkfinder import log_tables
        from supagent.tools import compare_logs

        by_cat: dict[str, list[str]] = {}
        for name, cat, _fed in found:
            by_cat.setdefault(cat, []).append(name)
        def listed(values: list[str]) -> str:
            return ", ".join("'" + v.replace("'", "''") + "'" for v in values)

        tables = sorted(log_tables(), key=lambda t: "log" not in str(t.get("table") or "").lower())  # logs first
        quiet, calls = "", 0
        for t in tables:
            owners = t.get("owners") or {}
            field, names = next(((f, by_cat[c]) for f, c in owners.items() if by_cat.get(c)), (None, None))
            if not field:
                continue
            base, scoped, at = f'"{field}" IN ({listed(names[:8])})', "", []
            on: dict[str, list[str]] = {}   # where the rows waited (their pool): the inputs' lines there first
            for f, values in where or []:
                if f in owners and f != field:
                    on.setdefault(f, [])
                    on[f] += [v.strip() for v in values.split(",") if v.strip() and v.strip() not in on[f]]
            for f, vals in on.items():
                scoped += f' AND "{f}" IN ({listed(vals[:3])})'
                at += vals[:3]
            for cond, there in ((base + scoped, at), (base, [])) if scoped else ((base, []),):
                if calls >= UPSTREAM_LOG_CALLS:
                    return quiet
                calls += 1
                res = compare_logs(table=t["table"], start=str(req["start"]), end=str(req["end"]), where=cond)
                said = str(res.get("conclusion") or "") if isinstance(res, dict) and not res.get("error") else ""
                # what is there every day is no lead (the "no free slot" lines of every pool would read as one)
                said = said.split(" As every day:")[0].strip()
                whose = f"{', '.join(names[:8])}{' on ' + ', '.join(there) if there else ''}"
                if said and not said.startswith("Nothing new"):
                    return (f"\n(What the logs of {whose} say that they do not usually ({t['table']}, read by the "
                            f"system): {said[:700]})")
                if said and not quiet:
                    quiet = (f"\n(The logs of {whose} ({t['table']}, read by the system): nothing new over the "
                             "window, every pattern as on the earlier days.)")
        return quiet

    @staticmethod
    def _fanout(name: str, args: dict) -> str | None:
        """A SUM, AVG or COUNT over a join whose other table has several rows for the key (agent.join_check)."""
        if name != "execute_sql" or not settings.get("agent.join_check"):
            return None
        try:
            from superset.extensions import db
            from superset.models.core import Database

            from supagent.knowledge.excluded import query_texts
            from supagent.knowledge.scope import call_target
            from supagent.knowledge.sqllint import fanout_refusal
            from supagent.tools import repeated_keys

            sqls = [q for q in query_texts(args) if q]
            database_id, _tables = call_target(name, args)
            database = db.session.get(Database, database_id) if database_id is not None else None
            if not sqls or database is None or not re.search(r"\bJOIN\b", sqls[-1], re.I):
                return None
            return fanout_refusal(sqls[-1], lambda table, key: repeated_keys(database, table, key))
        except Exception:  # pylint: disable=broad-except   (a check, never a lost call)
            log.debug("supagent: the join of the query not checked", exc_info=True)
            return None

    @staticmethod
    def _window_note(name: str, args: dict, content: str) -> str | None:
        """A metrics query with no period that found no sample: said with the data's range (no absence from the
        backend's default window)."""
        try:
            from superset.extensions import db
            from superset.models.core import Database

            from supagent.knowledge.excluded import query_texts
            from supagent.knowledge.experience import window_note
            from supagent.knowledge.scope import call_target

            database_id, _tables = call_target(name, args)
            database = db.session.get(Database, database_id) if database_id is not None else None
            sqls = [q for q in query_texts(args) if q]
            return window_note(database, sqls[-1], content) if database is not None and sqls else None
        except Exception:  # pylint: disable=broad-except   (a note, never a lost result)
            log.debug("supagent: window note not made", exc_info=True)
            return None

    @staticmethod
    def _chart_dataset(name: str, req: dict) -> Any:
        """The dataset a chart call charts (generate_chart: its dataset_id; update_chart: the chart's)."""
        from superset.connectors.sqla.models import SqlaTable
        from superset.extensions import db
        from superset.models.slice import Slice

        try:
            if name == "generate_chart":
                return db.session.get(SqlaTable, int(req.get("dataset_id")))
            chart = db.session.get(Slice, int(req.get("identifier")))
            return db.session.get(SqlaTable, chart.datasource_id) if chart is not None else None
        except (TypeError, ValueError):
            return None

    def _unapplied(self, question: str, trace: list[dict]) -> list[str]:
        """The team's rules a query of this answer should have applied (a filter on a field it has)."""
        try:
            from supagent.knowledge.rulecheck import unapplied

            return unapplied(getattr(self, "intent_text", None) or question, trace)
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            log.warning("supagent: the team's rules not checked", exc_info=True)
            return []

    def _ungrounded(self, answer: str, given: list[dict]) -> list[str]:
        """The numbers of the answer that nothing the LLM was given supports (agent.check_numbers)."""
        if not settings.get("agent.check_numbers"):
            return []
        try:
            from supagent.grounding import ungrounded

            return ungrounded(answer, given)
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            log.warning("supagent: numbers of the answer not checked", exc_info=True)
            return []

    def _definition_unlinked(self, question: str, trace: list[dict]) -> tuple[str, str, str] | None:
        """(term, definition, what differs) when a term defined as a relation between rows ("the refunds of those
        orders") was computed from the tables apart (agent.definition_links, by code: knowledge.definitions)."""
        if not settings.get("agent.definition_links"):
            return None
        try:
            from supagent.knowledge.definitions import unlinked
            from supagent.knowledge.rulecheck import _queries

            # the term of this message itself ("And the gross revenue?" after the net revenue: not that term)
            asked = getattr(self, "raw_question", None) or question
            found = unlinked(asked, _queries(trace))
            if found:
                return found[0]["term"], found[0]["definition"], found[1]
            from supagent.knowledge.definitions import unlinked_share

            share = unlinked_share(asked, _queries(trace))     # "what share of those sales was refunded?"
            return ("the share asked", "a part of a set of rows, counted within those rows", share) if share else None
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            log.warning("supagent: the relations of the definitions not checked", exc_info=True)
            return None

    def _definition_differs(self, question: str, trace: list[dict]) -> tuple[str, str, str] | None:
        """(term, definition, what differs) when a term the glossary defines was computed another way
        (agent.definition_check: one short LLM call per term, knowledge.definitions)."""
        if not settings.get("agent.definition_check"):
            return None
        try:
            from supagent.knowledge.definitions import computed_terms, judge
            from supagent.knowledge.rulecheck import _queries

            queries = [q for q in _queries(trace) if re.search(r"\bSELECT\b", q, re.I)]
            if not queries:
                return None
            for term in computed_terms(getattr(self, "intent_text", None) or question):
                why = judge(self.llm, term, question, queries)
                add_usage(self.usage, getattr(self.llm, "last_usage", None) or {})
                if why:
                    return term["term"], term["definition"], why
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            log.warning("supagent: the definitions of the answer not checked", exc_info=True)
        return None

    def _time_from_bucket(self, question: str, answer: str, trace: list[dict]) -> tuple[str, str] | None:
        """A time of day asked and given from time buckets (knowledge.sqllint)."""
        try:
            from supagent.knowledge.rulecheck import _queries
            from supagent.knowledge.sqllint import time_from_bucket

            return time_from_bucket(question, answer, _queries(trace))
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            log.warning("supagent: the time of the answer not checked", exc_info=True)
            return None

    def _ask_first(self, question: str, history: list[dict] | None) -> dict | None:
        """The question names one thing several match, or refers to nothing said (agent.ask_unclear)."""
        if not settings.get("agent.ask_unclear"):
            return None
        try:
            from supagent.knowledge.ambiguity import ask_first

            return ask_first(question, history)
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            from superset.extensions import db

            db.session.rollback()
            log.warning("supagent: the check of an unclear question failed", exc_info=True)
            return None

    def _new_ledger(self, question: str, history: list[dict] | None, building: bool) -> Any:
        """The work ledger of a big request (agent.ledger): "continue" takes up the open tasks of the previous answer's
        ledger; an investigation gets its steps as tasks; a question of many parts, several charts or a long request
        gets an empty plan the model writes. None for any other question."""
        if not settings.get("agent.ledger"):
            return None
        from supagent.ledger import CONTINUE, Ledger

        led = Ledger(question)
        before = next((h for h in reversed(history or []) if h.get("role") == "assistant"), None)
        if CONTINUE.match(question or "") and led.take_up((before or {}).get("ledger")):
            return led
        if self._investigating(question):
            if not settings.get("agent.ledger_investigations"):
                return None                            # (an investigation's own steps and checks guide it)
            led.seed_investigation()
            return led
        q = question or ""
        parts = len(re.findall(r",|;|\band\b|\bet\b|\?", q))
        charts = len(re.findall(r"\b(?:charts?|graphs?|dashboards?|graphiques?)\b", q, re.I))
        if parts >= MANY_PARTS or (building and charts >= 2) or len(q.split()) >= LEDGER_WORDS:
            return led
        return None

    def _ledger_findings(self) -> str:
        """The answer when the calls ran out before the model wrote one: the notes of the plan's done tasks (its own
        lines, written while it worked, next to each task) and the tasks left, said as such."""
        led = getattr(self, "ledger", None)
        done = [t for t in (led.tasks if led is not None else []) if t.status == "done" and t.note]
        if not done:
            return ""
        left = [t for t in led.tasks if t.status not in ("done", "dropped")]

        def name(t: Any) -> str:
            if t.by == "system" and not t.title.startswith("Explain or rule out"):
                return t.title.split(":")[0]           # "The facts", "Where", "Why", "Deeper"
            return t.title.split(": ", 1)[-1][:100]

        lines = ["What the work found before its calls ran out (the notes of its work plan, not checked again):"]
        lines += [f"- {name(t)}: {t.note}" for t in done]
        if left:
            lines.append("Not checked: " + "; ".join(name(t) for t in left[:6]) + ".")
        return "\n".join(lines)

    def _plan_note(self) -> str:
        if getattr(self, "ledger", None) is None or not self.ledger.tasks:
            return ""
        return "\nYour work plan (kept by the system):\n" + self.ledger.render(results=True, max_chars=2000)

    def _ledger_gaps(self, answer: str) -> str:
        """What the plan still lacks: the model's own tasks open with no result, the findings the answer does not
        name (by the values they are concentrated on) and has not ruled out."""
        led = self.ledger
        gaps = [f"task {t.id} ({t.title[:100]}) has no result" for t in led.unworked() if t.by == "model"]
        deeper = next((t for t in led.open() if t.by == "system" and t.title.startswith("Deeper")), None)
        if deeper is not None and not NOTHING_WRONG.search((answer or "")[:800]):
            gaps.append(f"task {deeper.id} (what changed behind the cause: a change, release, restart or maintenance "
                        "recorded before the effect began on the part you blame, or what it waits for upstream: "
                        "records_about with the names of the parts you blame and when it began) is open")
        gaps += [f"finding {t.id} (on {', '.join(t.keys)}: {t.title.split(': ', 1)[-1][:90]}) is neither explained "
                 "nor ruled out" for t in led.uncovered(answer)]
        return "; ".join(gaps[:6])

    def _keep_ledger(self, trace: list[dict]) -> None:
        """The ledger as the answer's last step: the page shows it, the next "continue" takes up its open tasks."""
        led = getattr(self, "ledger", None)
        if led is None or not led.tasks:
            return
        trace.append({"tool": "work_plan", "called": "work_plan", "status": "done", "args": {}, "seconds": 0,
                      "result": led.render(), "ledger": led.state(), "started": time.time()})
        self._report(trace)

    def _invented(self, answer: str, given: list[dict]) -> list[str]:
        """The names (bold, list items, table cells, identifiers) and times of day the answer gives that none of the
        `given` messages holds (their text, their tool calls), when agent.check_numbers is on."""
        if not settings.get("agent.check_numbers"):
            return []
        try:
            from supagent.grounding import new_names, new_times

            texts = [str(m.get("content") or "") + json.dumps(m.get("tool_calls") or "") for m in given]
            return new_names(answer, texts) + new_times(answer, texts)
        except Exception:  # pylint: disable=broad-except   (never an answer lost for a check)
            log.warning("supagent: names of the answer not checked", exc_info=True)
            return []

    @staticmethod
    def _queried(trace: list[dict]) -> bool:
        return any(t.get("status") == "done" and (t.get("called") or t["tool"]) in QUERY_TOOLS for t in trace)

    def _empty_fallback(self, trace: list[dict]) -> str | None:
        """The LLM wrote nothing, even when asked again: the last query result, said plainly (None
        when no query succeeded: the answer fails as before)."""
        last = next((t for t in reversed(trace) if t.get("status") == "done"
                     and (t.get("called") or t["tool"]) in RESULT_TOOLS), None)
        if last is None:
            return None
        if self.rich:
            return EMPTY_RICH
        rows = _sql_rows(last)
        if rows and len(rows) <= 30:
            cols = list(rows[0])
            table = "\n".join(["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
                              + ["| " + " | ".join(_cell(r.get(c)) for c in cols) + " |" for r in rows])
        else:
            table = "```\n" + (last.get("result") or "")[:3000] + "\n```"
        return EMPTY_PLAIN + "\n\n" + table

    def _check_stop(self) -> None:
        if self.should_stop is not None and self.should_stop():
            raise Cancelled("stopped by the user")

    def _report(self, trace: list[dict]) -> None:
        if self.on_step is not None:
            try:
                self.on_step(trace)
            except Cancelled:
                raise
            except Exception:  # pylint: disable=broad-except
                log.exception("supagent: step report failed")
