"""Settings: what the admin page and `superset supagent settings` change.

A value comes from, in order: the supagent_setting table (admin page, CLI), superset_config.py
(SUPAGENT_<KEY> with dots as underscores, e.g. SUPAGENT_LLM_BASE_URL), the environment (the
same name), the default below. Secrets are stored encrypted with Superset's SECRET_KEY and
never shown back (the admin page only says whether one is set).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Spec:
    key: str
    default: Any
    kind: str            # str | int | float | bool | list | json | choice
    help: str
    secret: bool = False
    choices: tuple[str, ...] = ()


SPECS: list[Spec] = [
    # ---- the LLM (OpenAI-compatible chat completions with tool calls)
    Spec("llm.base_url", "", "str", "OpenAI-compatible API base: what comes before /chat/completions, "
         "e.g. https://llm-gateway.example/v1/openai or http://llm-host:8080/v1"),
    Spec("llm.model", "", "str", "Model name; empty: the first model the server lists"),
    Spec("llm.auth", "none", "choice", "How the agent authenticates to the LLM: none, token (a fixed "
         "access token), middleware (a token obtained from the company middleware, renewed before "
         "it expires)", choices=("none", "token", "middleware")),
    Spec("llm.token", "", "str", "The fixed access token (llm.auth = token)", secret=True),
    Spec("llm.middleware.token_url", "", "str", "Middleware token endpoint (OAuth2 client "
         "credentials: POST grant_type=client_credentials)"),
    Spec("llm.middleware.consumer_key", "", "str", "Consumer key (sent with the consumer secret as HTTP Basic)"),
    Spec("llm.middleware.consumer_secret", "", "str", "Consumer secret", secret=True),
    Spec("llm.middleware.cert_path", "", "str", "Client certificate file (PEM) for the middleware, if it "
         "requires one (mutual TLS)"),
    Spec("llm.middleware.key_path", "", "str", "Private key file (PEM) of the client certificate"),
    Spec("llm.middleware.scope", "", "str", "OAuth2 scope to ask for (empty: none)"),
    Spec("llm.middleware.renew_before", 60, "int", "Renew the token this many seconds before it expires"),
    Spec("llm.ca_bundle", "", "str", "CA file to trust for the middleware and the LLM (empty: the "
         "system's CAs)"),
    Spec("llm.verify_tls", True, "bool", "Check the TLS certificates of the middleware and the LLM"),
    Spec("llm.timeout", 900, "int", "Seconds to wait for one LLM answer"),
    Spec("llm.temperature", 0.2, "float", "Sampling temperature"),
    Spec("llm.thinking", False, "bool", "Let reasoning models think before each step (slower)"),
    Spec("llm.max_answer_tokens", 8192, "int", "Tokens of one LLM answer at most: a model that repeats itself "
         "stops there (0: the LLM server's own limit; with llm.thinking, four times this)"),
    Spec("llm.extra_headers", {}, "json", "More HTTP headers for the LLM calls (JSON object)"),
    # ---- the agent
    Spec("agent.max_steps", 16, "int", "Tool calls per question at most: a hard limit on the tools the agent runs for "
         "one answer (the updates of its work plan are not counted); a question of many parts gets half as many more, "
         "within the limit below. When they are used, the agent answers with what it found"),
    Spec("agent.read_question", False, "bool", "Read each question before answering it (a call of its own, at the "
         "same time as its route): the question as one precise request in the team's names (shown as \"Understood "
         "as\" and given to the agent), and whether it needs anything of this platform (agent.general_answers). Off "
         "by default: measured in 0.9.6, the reading misled follow-ups (\"that\" read as the last figure, \"the same "
         "weekday a week earlier\" read with the names of unrelated charts)"),
    Spec("agent.general_answers", True, "bool", "With agent.read_question: a general question (writing or fixing a "
         "script, what a technology means in general) is answered without this platform's data and knowledge: "
         "quicker. Only when the router "
         "says so, the question names no part, table or chart of the platform, and the model, asked to say if it "
         "needs the platform, does not"),
    Spec("agent.max_steps_big", 32, "int", "Tool calls at most for an investigation (why did it fail, what changed, "
         "the cause) or a request that builds charts or a dashboard: a hard limit as well"),
    Spec("agent.compare_seconds", 45, "int", "compare_groups (investigations): one call reads about ten small "
         "aggregations per field of the table (the window and the 8 earlier days); after this many seconds it reads "
         "no further field and answers with what it has"),
    Spec("agent.compare_threads", 3, "int", "compare_groups: how many of its queries run at a time on OpenSearch "
         "(1: one after the other, on a busy cluster)"),
    Spec("agent.compare_follow", True, "bool", "compare_groups follows a lead once by itself: when the rows wait at "
         "a stage on one value of a field (a pool, a queue), it makes the same comparison over every row that has "
         "this value, whatever the question's other conditions (what holds it). About as many queries again; off: "
         "the agent asks for it when it wants it"),
    Spec("agent.compare_against", "yesterday, 1 week ago, 4 weeks ago", "str", "The days your team compares with, "
         "besides the usual (the median of the previous days): compare_groups and compare_to_usual give each figure "
         "on them too, and say when a figure is as usual but far from an older one (a change older than the last "
         "days). Any of: yesterday, N days ago, N weeks ago, N months ago, 1 year ago (weeks and months: the same "
         "weekday), separated by commas; empty: none. A question may name others (\"compared with three months "
         "ago\")"),
    Spec("governed.use_datasets", True, "bool", "Governed pipeline: a query on a table that has a Superset dataset "
         "runs through the chart data API (the dataset's permissions and row-level security apply); else as "
         "execute_sql"),
    Spec("mcp.servers", [], "json", "Other MCP servers whose tools the agent may use (JSON list of {name, transport: "
         "streamable_http | sse | stdio | websocket, url or command/args, headers, description, tools, write, "
         "allow_write, roles}); needs pip install \"supagent[graph]\""),
    Spec("agent.subjects", True, "bool", "Each question of a chat goes with the messages of its subject only: a "
         "follow-up gets its subject from its start, a question about other data starts a new subject without the "
         "earlier ones, a question about an earlier subject's data goes back to it (the LLM decides when the words "
         "cannot tell). Off: the last exchanges of the chat, as before 0.8"),
    Spec("agent.router", True, "bool", "Route each question (the MOA router: functional, technical, incident, "
         "charts, observability, infrastructure) by its meaning, the knowledge it touches and the routes people "
         "confirmed: the route chooses the knowledge given first, the tools and a short instruction; not sure: "
         "the normal way"),
    Spec("agent.cross_check", False, "bool", "Test: an answer of the classic agent with figures is computed a second "
         "time, independently (the governed pipeline's checked plan, its queries built by code); when the figures "
         "differ, the answer says so with the other ones (the answer comes later: the time of a second computation)"),
    Spec("agent.cross_check_seconds", 180, "int", "Seconds the second computation of agent.cross_check may take; later: "
         "no second opinion"),
    Spec("router.min_confidence", "medium", "choice", "The router's confidence needed to use a route (below it: "
         "the normal way)", choices=("low", "medium", "high")),
    Spec("agent.pipeline", "classic", "choice", "How questions are answered: classic (the model writes the queries, "
         "checked after) or governed (test: the knowledge is chosen first, the model fills a plan, code checks it "
         "and builds the queries; charts and status questions stay classic)", choices=("classic", "governed")),
    Spec("agent.databases", [], "list", "Databases the agent may use (names or ids); empty: the OpenSearch "
         "(osagg) and Prometheus / Mimir (promagg) ones. Superset's database access still applies"),
    Spec("agent.preferred_databases", [], "list", "When the same index or metric is in several databases: the ones "
         "to use first (names or ids, in order), unless the question names another database or is about a chart "
         "or a dashboard of another one. Empty: the catalog's metrics database, then the database the team's "
         "charts use for it"),
    Spec("agent.osagg_max_scan_rows", 20000, "int", "OpenSearch (osagg): raw documents one query of the agent may "
         "read when it cannot be pushed down (the connection's own cap applies if lower); above, the query is "
         "refused at once with the reason instead of running for minutes. 0: the connection's cap"),
    Spec("agent.now", "", "str", "A fixed 'now' (YYYY-MM-DD HH:MM) for demos on old data; empty: the clock"),
    Spec("agent.extra_instructions", "", "str", "More instructions added to the agent's prompt"),
    Spec("agent.disabled_tools", [], "list", "Tools the agent must not use (e.g. send_email)"),
    Spec("usage.keep_days", 90, "int", "Days the record of every LLM call is kept (the LLM usage page); 0: kept"),
    Spec("agent.check_numbers", True, "bool", "Every number of an answer must come from what the agent was given "
         "(query results, their totals and rates, the question, the knowledge): the agent is asked once to take "
         "the others from a query, then they are marked in the answer"),
    Spec("agent.ledger", True, "bool", "Big requests (an investigation, a question of many parts, several charts, a "
         "long request) get a work plan kept by the system: the tasks the agent writes (work_plan) or the steps of an "
         "investigation and each finding of compare_groups, the results of its tools attached to them, the plan given "
         "back when the conversation is shortened, the tasks left and the findings not explained sent back once "
         "before the answer, the plan shown in the answer's steps; \"continue\" takes up its open tasks"),
    Spec("agent.ledger_investigations", True, "bool", "With agent.ledger: investigations get the work plan too (their "
         "steps and each finding of the first comparison as tasks). Off: an investigation runs on its own steps and "
         "checks, with no plan to keep (the plan's calls and its check before the answer cost an investigation time "
         "and calls)"),
    Spec("agent.ask_unclear", True, "bool", "A question that names one thing several values match (\"the options "
         "book\" when five books are options books; \"the pricer\" on a day's data) or that starts a conversation "
         "with something never said (\"show me the late ones\") is asked back with the candidates, not guessed"),
    Spec("agent.compact_at", 24000, "int", "Prompt tokens of an answer's conversation from which the older tool "
         "results are cut to their first lines (then again at half as much more), the work plan given again: models "
         "read long contexts worse well before their limit (0: only when the context is full)"),
    Spec("agent.answer_seconds", 1500, "int", "After this long, an answer still calling tools is told to answer "
         "now (two calls left, then its answer from what it found and its work plan's notes): on a slow or busy LLM "
         "server an investigation ends with an answer, not a time-out. 0: no limit (the calls only)"),
    Spec("agent.inputs_walk", True, "bool", "Investigations: when compare_groups finds the rows late before they "
         "were ready, the inputs of the parts in its scope (two steps up the system map: what they depend on, read "
         "from, receive data from) are given with its result"),
    Spec("agent.shown_sql_check", True, "bool", "An answer that shows a query as the one behind its figures, when no "
         "call ran it (its figures came from other queries), is sent back once to run it or show the ones run"),
    Spec("agent.outer_join_check", True, "bool", "A query whose WHERE puts a condition on the table a LEFT JOIN keeps "
         "optional (the rows without a match dropped, as by an inner join) is sent back before it runs, with the two "
         "ways to write it; sent again unchanged, it runs"),
    Spec("agent.value_elsewhere", True, "bool", "A query that found nothing for a value its field does not hold: "
         "the other fields of its tables that hold it are named (\"filter on that field\"), and the answer is asked "
         "for the query again, not for a count of 0"),
    Spec("agent.share_join_check", True, "bool", "A share computed over an inner join of the part's table and the "
         "whole's (the whole kept only its rows that have a part) is sent back once"),
    Spec("agent.period_window_check", True, "bool", "A follow-up that names no period goes on with the chat's: when "
         "its queries read from more than a day before the chat's days and none starts inside them, the answer is "
         "sent back once to keep them (not when the question asks for a comparison or what is usual)"),
    Spec("agent.with_parts", True, "bool", "Investigations: a part named to check_health or records_about that "
         "the system map says is made of other parts (a pool and its servers, a cluster and its nodes; 16 at most) is "
         "looked at with them: their health breaches (said as found through it) and their records (changes, "
         "alerts) come with its own"),
    Spec("agent.inputs_logs", True, "bool", "With agent.inputs_walk: the logs of those inputs (compare_logs "
         "called by the system on the first log table that has a field of their category, over the comparison's "
         "window, first where the change is concentrated, then everywhere; at most three calls) are given too: a "
         "late input often says what it waits for"),
    Spec("agent.join_check", True, "bool", "A SUM, AVG or COUNT over a JOIN whose other table has several rows "
         "for the key (the rows summed repeat: double counting) is sent back before it runs (one probe query per "
         "table and key, kept 10 minutes)"),
    Spec("agent.calendar_facts", True, "bool", "Investigations: the calendar facts of the days looked at (the "
         "third Friday, the last business day of the month...) that the team's knowledge speaks of are given with "
         "the question"),
    Spec("agent.definition_links", True, "bool", "When a question uses a term the glossary defines as a relation "
         "between rows (\"the refunds of those orders\") and the answer read the tables apart (no JOIN, no key IN "
         "(SELECT ...)), the answer is sent back once to link them on their key (by code, no LLM call)"),
    Spec("agent.definition_check", False, "bool", "Test: when a question uses a term the glossary defines with how to "
         "compute it, one short LLM call compares the definition with the answer's queries; what differs (a "
         "condition, \"of those orders\") sends the answer back once"),
    Spec("agent.force_tool", True, "bool", "An answer that gives figures, names or times no tool returned, with no "
         "query run, is sent back once with a tool call made compulsory (the LLM server must accept tool_choice "
         "\"required\"; one that refuses it is asked with \"auto\")"),
    # ---- learning
    Spec("learn.enabled", True, "bool", "Learn once a day (at the hour below, on the days below)"),
    Spec("learn.hour", 2, "int", "Daily at this hour (0-23, server time): ONE run per day, not every N hours"),
    Spec("learn.days", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"], "list",
         "Days of the week with a learning run (mon, tue, wed, thu, fri, sat, sun)"),
    Spec("learn.user", "", "str", "Superset user the learner reads the data as (empty: the first Admin)"),
    Spec("learn.databases", [], "list", "Database names or ids to learn (empty: every osagg and promagg database)"),
    Spec("learn.indices", [], "list", "Only these indices (patterns with *, e.g. batch-jobs*); empty: every index "
         "the OpenSearch database lists. An index learned before that the patterns leave out is marked gone"),
    Spec("learn.indices_exclude", [], "list", "Never these indices (patterns with *)"),
    Spec("learn.one_table_each", True, "bool", "Names of the same documents are one table: a family of indices and an "
         "alias on all of them, an alias and its index, learned once (under a dataset's name, else the name already "
         "learned, else the data stream's, the alias's, the pattern's); an alias on only some indices of a family (a "
         "write alias on the newest) is kept with the family's table as a part, never told as a table of its own; a "
         "data stream is said to be one (its backing indices, its generations deleted by retention)"),
    Spec("learn.metrics", [], "list", "Only these metrics (patterns with *, e.g. node_*, batch_*); empty: every "
         "metric. A metric learned before that the patterns leave out is marked gone"),
    Spec("learn.metrics_exclude", [], "list", "Never these metrics (patterns with *, e.g. go_*)"),
    Spec("learn.max_minutes", 30, "int", "Stop a learning run after this many minutes (the next run continues)"),
    Spec("learn.max_objects", 20000, "int", "Metrics or indices listed per database at most"),
    Spec("learn.profile_every_days", 7, "int", "Refresh the statistics of each metric or index every N days (a "
         "rolling cycle: each day only its share; new ones at once). The list of metrics, indices and types is "
         "read every run"),
    Spec("learn.max_requests_per_minute", 60, "int", "Requests per minute to each database while learning (one at "
         "a time)"),
    Spec("learn.request_timeout", 30, "int", "Seconds before one learning request is given up"),
    Spec("learn.stop_after_errors", 5, "int", "Stop learning a database after this many failures in a row "
         "(429, 5xx, timeouts): the backend is busy"),
    Spec("learn.profile_hours", 24, "int", "Window of the value statistics (hours; one hour above 50,000 series)"),
    Spec("learn.stats_max_series", 200000, "int", "No value statistics for metrics with more series than this"),
    Spec("learn.series_sample", 1000, "int", "Series read per metric to learn its labels and their values"),
    Spec("learn.sample_docs", 100000, "int", "Documents sampled per index (per shard) for the field statistics"),
    Spec("learn.fields_per_request", 40, "int", "Field statistics per OpenSearch request (big indices: several "
         "requests)"),
    Spec("learn.group_rollover", True, "bool", "Learn dated or rolled-over indices (logs-2026.09.27, "
         "...-000123) as one family, through its latest member"),
    Spec("learn.associations", True, "bool", "Learn where the data is from the answers: the words of a question and "
         "the metrics or indices its successful queries read (used to find them for the next questions; Not helpful "
         "takes them back). Not listed with the learned answers"),
    Spec("learn.llm_descriptions", True, "bool", "Ask the LLM to describe what has no description (marked unverified)"),
    Spec("context.review", True, "bool", "A change of a Context page the agent writes waits for a person's validation "
         "(Knowledge, To review: the change, what it adds, what it leaves out, what it makes obsolete); the next change "
         "of the same page replaces the one not validated yet. A new page is shown at once, marked not reviewed; a "
         "page whose subject is gone is proposed for removal. Off: the agent's pages are written over, as before"),
    Spec("context.enabled", True, "bool", "Build the Context every night: the system's functional and technical "
         "documentation, from the documents, the catalog, the team memory, the data dictionary and the Helpful answers"),
    Spec("context.hour", 4, "int", "Hour of the nightly Context build (after the day's learning run)"),
    Spec("context.classify_after", True, "bool", "After each Context build (the nightly one, one asked in the page or "
         "the command line), the classification runs on what it wrote: the categories of the items, the part-of of "
         "the values, the interactions the documents and the Context state, each explained. The nightly learning "
         "then leaves the categories to it"),
    Spec("charts.scan", True, "bool", "With the nightly Context build: look at the team's Superset charts (their last "
         "full day against the same weekday of the 4 weeks before, per series: high, low, data stopped) and write "
         "what each shows; the agent answers \"anything unusual on the dashboard\" from it (chart_anomalies)"),
    Spec("charts.max_charts", 200, "int", "Charts looked at per night at most (the ones on dashboards first)"),
    Spec("charts.minutes", 20, "int", "Minutes the nightly look at the charts may take at most"),
    Spec("charts.max_requests_per_minute", 12, "int", "Chart queries a minute at most per database during the nightly "
         "look (a database that answers it is overloaded learn.stop_after_errors times in a row is left for the "
         "next night)"),
    Spec("charts.max_llm_calls", 40, "int", "LLM calls a night at most to write what the charts show (written again "
         "only for a chart that changed)"),
    Spec("context.max_llm_calls", 12, "int", "LLM calls of a Context build at most (its summary pages: only the ones "
         "whose sources changed are written again; the facts pages need no LLM)"),
    Spec("context.fields_shown", 30, "int", "The fields (or labels) listed on a data source's Context page for each of "
         "its first three main indices (or metrics), the described ones first, then the most filled (0: none; the "
         "Data dictionary has them all)"),
    Spec("knowledge.apply_background", True, "bool", "A save in the Data dictionary answers at once; the catalog "
         "applied to the dictionary, the searchable pieces and their vectors follow in the background (seconds)"),
    Spec("categories.custom", [], "list", "Categories of your own besides subject, application and component (e.g. "
         "server, environment, team): their values are added by hand, read from the data's fields "
         "(categories.fields) and proposed by the LLM, like the others"),
    Spec("categories.fields", {"application": r"^(application|app|app_name|service|service_name|system|platform)$",
                               "component": r"^(component|components|module)$"}, "json",
         "Where the values of a category are read in the data: category -> a regular expression of field (or "
         "label) names, e.g. {\"server\": \"^(server|host|hostname|node)$\"}; the values found are proposed "
         "as values of that category, to approve in To review (where they come from is kept; used at once with "
         "categories.review_all off), and two such fields of one index tell which values go together (proposed "
         "as 'part of', to approve)"),
    Spec("categories.about", {}, "json", "What each category is, in a sentence: category -> description, e.g. "
         "{\"pool\": \"a group of servers that share the same queue of slots\"}. Written in Categories or on the "
         "System map; shown to people with the category's name and given to the agent and to the router with the "
         "parts a question names"),
    Spec("categories.review_all", True, "bool", "Nothing the learning finds changes the categories before an admin "
         "approves it (To review): the categories the LLM gives an item and the relations it finds, even the ones "
         "it is sure of, and (0.9) the new values it reads in the data's category fields or infers for the data's "
         "objects; off: what the LLM is sure of (medium, high) is used at once on approved values and the values "
         "of the data are approved at once, as in 0.6. The values the LLM proposes, the 'part of' relations and "
         "the removals always wait"),
    Spec("categories.retire_days", 14, "int", "A value the learning read in the data that none of its category's "
         "fields and labels has shown for this many days is proposed for retirement in To review (never retired by "
         "itself; a value put by hand is only proposed when a text says it was retired or decommissioned); 0: no "
         "such check"),
    Spec("categories.max_values", 1000, "int", "A field with more values than this is not read as a list of "
         "category values (applications: 60 at most)"),
    Spec("categories.relation_min_docs", 5, "int", "Documents two values must share in an index to be proposed "
         "as one part of the other"),
    Spec("categories.qualified", {}, "json", "Categories whose values are named after the part they belong to: "
         "category -> the category of that part, e.g. {\"disk\": \"server\"}: a disk /dev/sda1 seen with server srv-1 "
         "is the value \"srv-1 /dev/sda1\", part of srv-1 (every server has its own sda1)"),
    Spec("categories.inside", {}, "json", "Categories drawn inside another on the System map (0.9.6.5): category -> "
         "the category its values are inside, e.g. {\"disk\": \"server\", \"partition\": \"disk\"}: a server's "
         "disks are drawn inside the server they are part of (or run on), opened and closed with a click, as many "
         "levels down as the categories go. A category of categories.qualified is inside the category it is named "
         "after unless this says otherwise (\"\": not inside). Display only: the agent reads what each value is part "
         "of, not this"),
    Spec("roles.simple", False, "bool", "The roles are Admin, Editor and Viewer (0.9.6.6): supagent's AI roles merged "
         "into Superset's Admin, Alpha and Gamma, these two renamed Editor and Viewer; Superset's role sync makes "
         "Editor and Viewer where it made Alpha and Gamma. Set by superset supagent roles --apply (and --undo), not "
         "by hand"),
    Spec("roles.viewer_data", "none", "choice", "The data the Viewer role (AI Viewer) reads: none (give its users "
         "their databases' access as Superset does: a role or a group per team) or all (every database and dataset)",
         choices=("none", "all")),
    Spec("categories.label_links", True, "bool", "Link at once the values a metric's series carry together (a "
         "server with its component, a tenant with its servers: 0.9.6); off: proposed in To review like an index's"),
    Spec("categories.data_link_days", 21, "int", "A link read from the data that the data has not shown for this many "
         "days is proposed for removal (never removed alone)"),
    Spec("learn.classify_per_run", 400, "int", "Knowledge items the daily learning classifies at most (their "
         "categories: aspect, subjects, applications, components, and the relations their texts state); the next "
         "run continues; 0: none (no item is given to the LLM)"),
    Spec("learn.interactions_logs_seconds", 120, "int", "learn.interactions_logs: the time the step may take (checked "
         "before each query: on a big or shared cluster the queries left are not sent, the next night goes on); "
         "about 900 small queries a log table read whole, some of them a piece of text searched in the messages"),
    Spec("learn.interactions_logs", True, "bool", "With the classification, the recent lines of the log tables (a time "
         "field, a text field, a field of a category's values) are read for the interactions they show (\"still "
         "waiting for its inputs: A, B\", \"request to X\"): each pair seen on enough lines and days waits in To review "
         "with its evidence, never drawn nor used before an admin approves it (no LLM)"),
    Spec("learn.aliases", True, "bool", "A table of the data that lists names with their other names (a CMDB, an asset "
         "or service catalog: a name field and an aliases, alias, aka or other_names field) makes the names of one row "
         "one value of the categories: merged at once (its other names its synonyms, what was filed under them and "
         "the interactions drawn on them moved to it), or suggested in To review when an admin reviews what the "
         "learning finds (no LLM)"),
    Spec("learn.interactions_spans", True, "bool", "The span tables of the data (Jaeger, OpenTelemetry: a span id, a "
         "parent span id and a service field) show which service calls which: a span under a span of another service, "
         "a client span naming its peer (peer.service). Each call seen on the last day of the data is drawn on the System "
         "map as an interaction 'calls' with how many and how long (approved like the values read in the data, else "
         "in To review) (no LLM)"),
    Spec("learn.behaviour", True, "bool", "The usual day of each service of the span tables (spans a day, average and 95th "
         "percentile duration, share of errors, busiest hours: the median of the days before the data's last day) is kept "
         "with the table and shown with it, labelled as a usual, so that a slowness or a burst of errors is told from "
         "what the service always does (no LLM)"),
    Spec("learn.usual_logs", True, "bool", "For the log tables whose kind says where the service is, the services with the "
         "most lines are read over the data's last full day against the days before (compare_logs): their patterns of "
         "every day (a warning written every night) are kept with the table and shown with it, labelled as usual, so "
         "that an investigation does not blame what the logs always say (no LLM)"),
    Spec("learn.pod_names", True, "bool", "Names of one service in two sources (orders for Kubernetes, shop-orders "
         "for OpenTelemetry) found by the pods or hosts they run on over the last full day (most of their pods shared): "
         "made one value of the map, as an inventory's names are (or suggested when categories.review_all); a sidecar "
         "in every pod is never merged (no LLM)"),
    Spec("learn.usual_latency", True, "bool", "For every latency histogram whose series name a service (service_name, "
         "service, application, app, job), the usual day of each service (median and 95th percentile, requests a day: "
         "the median of the days before the data's last day) is kept with it and shown, labelled as a usual (no LLM)"),
    Spec("learn.same_events", True, "bool", "For each log table, a few lines of its busiest services on its last full "
         "day are looked for in the other log tables (the same pod or host, within two seconds, the same text): most "
         "of them found there are the same events shipped twice (the OpenTelemetry SDK and the container's stdout), "
         "said with both tables so that they are never added (no LLM)"),
    Spec("learn.interactions", True, "bool", "The daily learning reads the documents, guides, Context pages and team "
         "notes for how the parts of the system interact (depends on, runs on, reads from, calls...) and proposes "
         "what they state for the System map, each with its sentence, word for word; nothing is drawn or used "
         "before an admin approves it (To review)"),
    Spec("learn.describe_values", False, "bool", "(0.10.5, off: measured on a lab map, 2 descriptions of 154 gave "
         "a part a role no line states, 1 said a link the other way round, 7 said nothing) The classification "
         "writes what a part is for the parts with no description (one added by hand too), from what the "
         "documents say of it, its links and where the data has it, and from that only; a part with none of these "
         "gets nothing; shown as written by the AI until a person saves a description; a person's description is "
         "never written over"),
    Spec("backup.enabled", True, "bool", "Every day, the whole knowledge is saved in one file (the categories and "
         "the System map, the catalog, the memory, the documents, the notes, the Context, the learned answers and "
         "paths, the descriptions of the data, the settings; no secret): the history to go back to. Restored whole "
         "or by part (Settings, Backups; superset supagent restore)"),
    Spec("backup.hour", 1, "int", "The hour of the daily backup (the server's clock, 0-23)"),
    Spec("backup.days", [], "list", "The days of the daily backup (mon, tue...); empty: every day"),
    Spec("backup.keep", 14, "int", "Backups kept (the oldest are removed)"),
    Spec("backup.dir", "", "str", "The directory of the server where the backups are written (empty: "
         "supagent-backups in Superset's home). With several servers: a directory they share, or the backups are "
         "on the server that made them"),
    Spec("backup.vectors", False, "bool", "The vectors of the search pieces are saved too: several times bigger "
         "files, and a full restore needs no embedding (off: they are computed again from the texts)"),
    Spec("learn.agent_catalog", True, "bool", "The agent adds catalog entries when the evidence is certain: "
         "formulas used in answers confirmed as helpful, team rules and facts approved by an admin, definitions "
         "quoted word for word from the documents. Written as (agent): edit one to take it over; delete it and the "
         "agent never writes it again"),
    Spec("learn.agent_catalog_docs", True, "bool", "... and reads the definitions of the documents (the LLM, once "
         "per new or changed document)"),
    # ---- knowledge search (retrieval): words (PostgreSQL full-text) and vectors (embedding model)
    Spec("agent.bare_doubt_check", False, "bool", "(0.10.4, off: measured with more silent "
         "mistakes on a held set) A reply that only doubts the answer (\"are you "
         "sure?\", \"check again\") gets its own note: check it again with a new query, change an assumption "
         "only on evidence, keep an undefined word's reading and ask"),
    Spec("agent.claimed_query_check", False, "bool", "(0.10.4, off: measured with more silent "
         "mistakes on a held set) A follow-up answered without any query while its "
         "text says a query was run (\"I ran a query\", \"the query executed\") is sent back with a query made "
         "compulsory: the chat's own figures no longer let it through"),
    Spec("agent.correction_check", False, "bool", "(0.10.3, off in 0.10.4: measured with more "
         "silent mistakes on a held set) A reply that disputes or corrects the previous answer (\"that's "
         "wrong\", \"check again\", \"I meant the sold ones\") gets the previous answer's queries and is checked "
         "again on another path: the assumption it changes named, the knowledge searched again, a new query (an answer "
         "with no query, or with the same query again, sent back once) (0.10.3)"),
    Spec("agent.announce_ing", False, "bool", "(0.10.4, off until measured) An answer ending by announcing a step "
         "written in -ing (\"let me try searching for ...\") is sent back like the other announcements"),
    Spec("agent.link_limit_hint", False, "bool", "(0.10.4, off until measured) The system picture's head says to "
         "check a link's limit on the peaks of its metrics over the period"),
    Spec("tools.brief_crossings", False, "bool", "(0.10.4, off until measured) check_health also shows the "
         "thresholds crossed too briefly to be a breach, on the servers or applications it is asked about"),
    Spec("search.enabled", True, "bool", "Give the agent the knowledge relevant to each question (dictionary, "
         "notes, rules, learned answers, memories, documents)"),
    Spec("search.top_k", 6, "int", "Pieces of knowledge given with each question"),
    Spec("search.values", True, "bool", "A question that names a value of the data (a server, a service, a status: "
         "3 characters at least, held by the labels or fields the learning read) gets first which metrics' labels "
         "and indices' fields hold it, and the category values named so (0.10.2)"),
    Spec("search.terms_uncapped", True, "bool", "The terms of a glossary and the rules of an entry are each a piece of "
         "their own in a search's results (the cap of two pieces per page applies to pages and notes only)"),
    Spec("search.spelling", True, "bool", "Read a searched word that no piece of the knowledge holds (a letter missing, "
         "one too many, two swapped, a space inside a word, two words run together) as the known word one edit away; "
         "the search says what it read otherwise"),
    Spec("search.prompt_chars", 2500, "int", "Characters of knowledge given with each question at most"),
    Spec("embed.model", "", "str", "Embedding model (e.g. bge-m3); empty: search by words only"),
    Spec("embed.base_url", "", "str", "Embedding API base (what comes before /embeddings); empty: the LLM's "
         "(llm.base_url), with the LLM's authentication (token or middleware)"),
    Spec("embed.batch", 16, "int", "Texts per embedding request"),
    Spec("embed.per_run", 2000, "int", "Pieces embedded per indexing run at most (the next run continues)"),
    Spec("search.vector_store", "database", "choice", "Where the vectors are searched: database (Superset's "
         "database, compared in memory: no extension, no service) or qdrant (a Qdrant server)",
         choices=("database", "qdrant")),
    Spec("qdrant.url", "", "str", "Qdrant server (search.vector_store = qdrant), e.g. http://qdrant-host:6333"),
    Spec("qdrant.api_key", "", "str", "Qdrant API key", secret=True),
    Spec("qdrant.collection", "supagent", "str", "Qdrant collection"),
    Spec("search.store", "auto", "choice", "The knowledge store in PostgreSQL (words by BM25 with pg_textsearch, near "
         "spellings with pg_trgm, meaning with pgvector, the chats): auto = used once built (superset supagent store "
         "rebuild; init builds it when the extensions are there), on, off (the search of 0.5)",
         choices=("auto", "on", "off")),
    Spec("search.store_uri", "", "str", "PostgreSQL that holds the store (e.g. postgresql://user:pw@host/db); empty: "
         "Superset's database", secret=True),
    Spec("search.store_schema", "supagent_store", "str", "Schema of the store (its own: wiped with DROP SCHEMA, left "
         "out of a backup with pg_dump --exclude-schema)"),
    Spec("search.bm25", "auto", "choice", "Words ranked by: auto = BM25 of pg_textsearch when installed, else "
         "PostgreSQL's full-text search; builtin = PostgreSQL's full-text search", choices=("auto", "builtin")),
    Spec("search.chats", True, "bool", "The store keeps the chats: each user may search their own (search_my_chats), "
         "and the tables of confirmed answers vote for the questions like them (the decider)"),
    Spec("search.chat_days", 365, "int", "Days of chats the store keeps"),
    Spec("search.chat_box_similarity", 0.72, "float", "The chat's search box: a chat found by meaning only (none of "
         "the words typed) when at least this close (cosine; 0.72 suits Qwen3-Embedding-0.6B: lower it for models "
         "whose scores are lower); chats with the words are always found"),
    Spec("rerank.url", "", "str", "A cross-encoder reranker's endpoint (e.g. http://gateway:8092/v1/rerank): the "
         "first pieces the search found are read with the question and ordered again; empty: no reranker"),
    Spec("rerank.api", "jina", "choice", "The reranker's API: jina ({query, documents} -> results with "
         "relevance_score: Jina, Cohere, vLLM, llama.cpp --reranking, Infinity) or tei ({query, texts}: "
         "text-embeddings-inference)", choices=("jina", "tei")),
    Spec("rerank.model", "", "str", "The reranker model's name, sent with each request (jina API; e.g. "
         "Qwen3-Reranker-0.6B, bge-reranker-v2-m3); empty: the server's"),
    Spec("rerank.auth", "none", "choice", "The reranker's authentication: none, token (rerank.token) or llm (the "
         "LLM's: its token or the middleware, when the reranker is on the same gateway)",
         choices=("none", "token", "llm")),
    Spec("rerank.token", "", "str", "The reranker's access token (rerank.auth = token)", secret=True),
    Spec("rerank.timeout", 2.0, "float", "Seconds the reranker may take; later: the search's own order (and no "
         "call for a minute)"),
    Spec("rerank.depth", 40, "int", "Pieces of the search read again by the reranker"),
    Spec("rerank.weight", 1.0, "float", "How much the reranker's order counts against the search's (1: as much; "
         "2: twice as much)"),
    Spec("rerank.max_chars", 1500, "int", "Characters of each piece the reranker reads (about 512 tokens)"),
    Spec("rerank.judge_floor", "", "str", "The reranker as the search's judge: a best piece scored under this (the "
         "reranker's own scale, e.g. 0.2) makes the search weak (search.rewrite); empty: the reranker does not judge"),
    Spec("search.rewrite", "weak", "choice", "The agent's help for a weak search (a word near the knowledge's words "
         "that nothing reads, or the judge's low score): weak = the LLM writes the question again once (spelling fixed, "
         "names kept, a few other words) and both searches are fused (about 5% of questions; on 2,300 documentation "
         "pages, questions with two words two slips away found 80% -> 82%, none lost); off = never",
         choices=("off", "weak")),
    Spec("search.rewrite_seconds", 4.0, "float", "Seconds the LLM may take to write a weak search again (later: the "
         "first search alone)"),
    Spec("search.judge_meaning_floor", "", "str", "Without a reranker: the closest of the first pieces by meaning under "
         "this cosine (the embedding model's scale, e.g. 0.45 for bge-m3) makes the search weak (search.rewrite); "
         "empty: not used"),
    Spec("embed.query_instruction", "", "str", "Text put before a question when it is embedded, for models trained "
         "with one (Qwen3-Embedding: 'Instruct: Given a question about the data, retrieve the metrics, tables and "
         "knowledge that answer it\\nQuery:'); empty: the question alone"),
    # ---- documents and sites
    Spec("docs.allowed_domains", [], "list", "Domains the agent may fetch pages from (e.g. wiki.company.com); "
         "empty: public sites only (no private addresses)"),
    Spec("docs.verify_tls", True, "bool", "Check the TLS certificate of the sites documents are read from (a document can "
         "say otherwise: Documents and sites, Edit); off: the connection is encrypted but the site is not checked"),
    Spec("docs.ca_bundle", "", "str", "CA file (PEM, a path on every Superset host) to trust for the documents' sites, "
         "e.g. the company's root CA (empty: the system's CAs; a document can give its own)"),
    Spec("knowledge.understand", True, "bool", "Read what the documents and the code state (0.10), without an LLM: "
         "the services a repository calls, the databases it writes and reads, the metrics it registers, the indices "
         "a shipper writes, a diagram's arrows, a page's sentences and tables; each fact with the line that says it, "
         "for the System map, the Context and the agent (only the units whose text changed are read again)"),
    Spec("knowledge.understand_catalog", True, "bool", "The catalog's guides, notes, rules, definitions and glossaries "
         "read with the documents (0.10): the links between parts they state"),
    Spec("knowledge.understand_llm", False, "bool", "The LLM reads the wiki's pages and the prose documents too (0.10): "
         "the links between parts they state in words the rules do not read, each kept only with the page's own words "
         "that state it (ranked below code, configuration and diagrams); off: the rules alone"),
    Spec("knowledge.llm_units", 200, "int", "Pages and documents the LLM reads per learning run at most (the others at "
         "the next run; a page is read again only when its text changes)"),
    Spec("knowledge.llm_seconds", 120, "int", "Seconds the LLM may take to read one page"),
    Spec("knowledge.propose", True, "bool", "Propose what the documents and the code state (0.10) for the "
         "categories and the System map, each waiting in To review with where it was read: the parts they name (a "
         "service an application, a database, a cache or a tool a component, a host a server), the links between "
         "them, a part's indices and metrics; compared with what exists (stated again: confirmed; the other way round "
         "or no longer stated: removal proposed); nothing a person made or refused is changed"),
    Spec("docs.max_kb", 2048, "int", "Largest page or file read (KB)"),
    # ---- memory learned from the chats
    Spec("memory.enabled", True, "bool", "Learn preferences, rules and facts from the chats"),
    Spec("memory.team_approval", True, "bool", "Team memories need an admin's approval before they are used "
         "(personal ones are used at once)"),
    Spec("memory.prompt_chars", 2000, "int", "Characters of memories given with every question at most (rules, "
         "then preferences, then facts; the facts left out are still found by the knowledge search)"),
    # ---- other agents (MCP server mode)
    Spec("mcp.user", "", "str", "Superset user the MCP server mode (`superset supagent mcp`, for other agents) "
         "acts as; empty: MCP_DEV_USERNAME of superset_config.py"),
    # ---- files, e-mails
    Spec("tools.export_dir", "~/superset-exports", "str", "Where images and Excel files are written"),
    Spec("tools.export_max_rows", 500000, "int", "Rows of an Excel extract at most"),
    Spec("tools.email_allowed_domains", [], "list", "E-mail domains the agent may send to (empty: any)"),
    Spec("tools.keep_days", 7, "int", "Days the files of the answers (images, Excel) are kept"),
    Spec("chats.keep_days", 0, "int", "Delete the chats nobody used for this many days (0: keep every chat); "
         "what they taught (learned answers, memory, associations) stays"),
    Spec("tools.max_file_mb", 50, "int", "Files bigger than this (MB) are not kept for the chat page"),
    # ---- where answers are computed
    Spec("agent.executor", "auto", "choice", "Where questions are answered: celery (Superset's workers), "
         "thread (the web server), auto (celery when a worker answers, else thread)",
         choices=("auto", "celery", "thread")),
    Spec("agent.celery_queue", "", "str", "Celery queue of the answers and the learning runs (empty: the default "
         "queue); set it when the workers only read named queues (celery worker -Q ...)"),
    Spec("agent.queue_keep_days", 90, "int", "With Celery's queue in Superset's database (broker_url \"sqla+...\"): "
         "delivered messages are deleted after this many days (0: never; Celery itself never deletes them)"),
]
BY_KEY = {s.key: s for s in SPECS}


def _env_name(key: str) -> str:
    return "SUPAGENT_" + key.upper().replace(".", "_")


def _coerce(spec: Spec, value: Any) -> Any:
    if value is None:
        return spec.default
    if spec.kind in ("str", "choice"):
        v = str(value)
        if spec.kind == "choice" and v not in spec.choices:
            raise ValueError(f"{spec.key}: one of {', '.join(spec.choices)}")
        return v
    if spec.kind == "int":
        return int(value)
    if spec.kind == "float":
        return float(value)
    if spec.kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if spec.kind == "list":
        if isinstance(value, (list, tuple)):
            return [str(v) for v in value]
        text = str(value).strip()
        if text.startswith("["):
            return [str(v) for v in json.loads(text)]
        return [v.strip() for v in text.split(",") if v.strip()]
    if spec.kind == "json":
        return value if isinstance(value, (dict, list)) else json.loads(str(value) or "null")
    return value


def get(key: str) -> Any:
    spec = BY_KEY[key]
    from supagent.models import Setting
    from superset import db

    try:
        row = db.session.get(Setting, key)
    except Exception:  # pylint: disable=broad-except  (tables not created yet)
        db.session.rollback()
        row = None
    if row is not None:
        if spec.secret and row.secret:
            return row.secret
        if not spec.secret and row.value is not None:
            return _coerce(spec, row.value)
    from flask import current_app

    conf = current_app.config.get(_env_name(key)) if current_app else None
    if conf is not None:
        return _coerce(spec, conf)
    env = os.environ.get(_env_name(key))
    if env is not None:
        return _coerce(spec, env)
    return spec.default


def set_value(key: str, value: Any, by: str = "") -> None:
    """Store a setting (value None: back to the default)."""
    spec = BY_KEY.get(key)
    if spec is None:
        raise KeyError(f"unknown setting {key!r}")
    from supagent.models import Setting
    from superset import db

    row = db.session.get(Setting, key) or Setting(key=key)
    if spec.secret:
        row.secret = None if value in (None, "") else str(value)
        row.value = None
    else:
        row.value = None if value is None else _coerce(spec, value)
    row.updated_by = by
    db.session.merge(row)
    db.session.commit()


def describe() -> list[dict]:
    """Every setting with its current value (secrets: only whether they are set)."""
    out = []
    for spec in SPECS:
        value = get(spec.key)
        out.append({"key": spec.key, "kind": spec.kind, "help": spec.help, "choices": list(spec.choices),
                    "secret": spec.secret, "default": None if spec.secret else spec.default,
                    "value": (bool(value) if spec.secret else value)})
    return out
