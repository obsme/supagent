# Changes

## 0.11.0 — 2026-10-17

The final release of this series: the owner's nine requests of 17 October 2026, a review of the code (the agent and
its tools, the API, the pages, the integrations, the System map's learning and the readers of repositories), tests of
every route and of every page, and a user guide (docs/USER-GUIDE.md).

The agent's context, in tiers (`agent.context_tiers`, on)
* **What the team keeps comes first, each said once**: the catalog's rules (in the instructions), the memories, the
  team's words, where the data is and the learned answers are given whole, before anything else. A copy is left out: a
  memory that says what another memory or a rule of the team says (the same words in the same order, once case,
  punctuation, plurals and small words are set aside), a learned answer that runs the same query with the same tool on
  the same database as another. Two texts that differ in what they say are never one: another word, number, unit,
  negation ("don't" is "do not"), operator or sign ("> 500" and "< 500", "UTC -2" and "UTC +2"), modal verb ("must",
  "may"), condition, or a quoted value as written ('FAILED' and 'failed') keeps both, and To review lists the two when
  they are alike, for a person to decide.
* **Then the chat**: the last complete exchange always (the last question answered and all after it), then the older
  messages, the newest first, in the room the first tier and the tools leave (half of the model's window, about four
  characters a token; a server that states no window counts as 64k), never starting with an answer. A long chat no
  longer fills a small model's window.
* **Then the documentation, chosen**: the knowledge found for the question (the catalog's and the agent's entries take
  the room first, up to half of it, the documents and the Context after), and the LLM context's lines about the
  question, in the room that is left, never the whole page: a line is given when its head names a word of the
  question, or it names much of it, or a name the question writes, or it is the main data of a database the question
  is about; a line of an entry the search gave already is left out. A question the LLM context says nothing about gets
  none of it. On a lab's 24,000-character LLM context: 1,200 to 6,500 characters a question, nothing for a question
  about a runbook. The page's formulas still count as said when the queries' conditions are checked, as when it was
  given whole.
* Off (`agent.context_tiers` = false): as 0.10.12.

To review
* **Duplicates**: a memory (a person's own, a group's, or a person's copy of the team's), a catalog entry or a learned
  answer (the same query) said more than once: one warning per set, the oldest kept, the copies removed or disabled in
  one click; two alike that may repeat or contradict each other (70 % of their words in common or more): said with
  both, for a person to decide. Found in 0.01 s on a lab (a rule saved four times).

The learning's history
* **Kept 30 days** (`learn.history_days`): the runs (learning, classification, Context, backups, restores, documents)
  finished before are removed every hour with the changes they found; the last run of each kind is kept whatever its
  age, a run still going never. 0: kept for ever.

The Context's documents
* **Written for a new member of the team**: "In short" first, how things work and why, one name for one thing, a table
  where it compares, citations once per paragraph; nothing that does not help understanding (no counts of objects,
  documents or pages, no long lists of metric or field names: the evidence the writer reads carries no counts either).
* **A relations diagram** at the end of the overview, the technical overview (how the parts run on and connect to each
  other) and each application's page, built from what the documents and the code state (the most stated first, 30 at
  most; never written by the LLM), drawn by the page with no library; its lines ("A -> B : calls") stay readable in
  the PDF and Word exports and in the search. The pages are written again at the next Context build and wait in To
  review (`context.review`).

Backups
* **Cleaned by number and by age**: the last `backup.keep` (14) and none older than `backup.keep_days` (30; the newest
  always kept); what a stopped backup left is removed after a day; cleaned every hour, not only after a backup.
* **Restore… in Settings**: a backup of the server, or a file brought from elsewhere (one downloaded before, another
  Superset's), checked as a backup this version can restore (`backup.upload_max_mb`, 2048), then the parts to put
  back; the present state is saved first, as before.

The usage page
* Every figure checked against the database (calls, tokens sent and written, prompt cache share, errors, largest
  context, time per call, answers, LLM and tool calls per answer, sent back by the checks): equal. Corrected: the
  hours and days by the viewer's time zone name (a period over a change of summer time counted an hour off); the
  answers' figures over every answer of the period (they were over the 50,000 slowest); the context size of the calls
  that have one (a failed call's 0 no longer lowers it).
* **The Servers card shows the disk Superset is on** (its home and its installation: the disk of /data when Superset
  lives there), with what it holds and its free space; no longer every mount of the host.

The review of the code
* **The agent**: an answer's worker closes its database session before the answer runs (no transaction left open for
  the length of an answer); the LLM client blames a field the server refuses only when the server names it, and its
  retries stay within the call's time.
* **Rights**: a person's own memory changed only by them and an admin; a note's sharing checked as when it is made;
  replacing the catalog from a file takes the right to delete; an approved link removed only with the right to delete;
  a viewer gets the part links of the parts their map shows only; a learned answer's check run as the person; an
  answer's files checked by id.
* **Requests**: a number a request sends that is not one: its default taken or a 400, never a server error; one
  question at a time per chat (its row locked: two tabs no longer answer it twice); a value's name matched exactly (a
  "_" or "%" in it is no pattern); the group memories listed.
* **Speed and memory**: the Knowledge tab and the documents list never load a wiki's text or pages (the database
  counts them); the search's hourly sync reads only the pieces' hashes; a wiki space read batch by batch, its pages'
  text dropped once read.
* **Documents**: a document holding a NUL character read and saved; one that cannot be saved said, not retried every
  hour; a reading claimed (two workers never read one document at once); a worker's time limit is no document error; a
  repository file refused for now kept as it was.
* **Runs**: a run says it is alive with each progress it saves and is taken for dead from its last word, not from its
  start (a Context build of hours is no longer marked interrupted and started a second time); Stop says a backup or a
  restore cannot be stopped; the Servers card forgets a host gone for a week.
* **Backups**: zip64 (beyond 4 GB), no half-written file left by a failed backup, the daily one due by the server's
  date (a file brought from elsewhere counts for none); a documents restore keeps what was understood of them.
* **The Context**: an application's name counted once per text it is in.
* **The pages**: Approve or Reject all shown decides only the cards still shown (it approved again a value rejected
  alone, and never sent the last); a link line of the System map opens its panel, an edit on the map is drawn at once,
  and a description being typed survives the map's refresh; "Keep the LLM calls (days)" is saved; a refused Settings
  save says why, in red, and keeps the other cards' unsaved edits; a double click or Enter twice asks once, and Ask
  again never stops the answer being written; the docked chat takes the keyboard only when its page has it; the usage
  page keeps its figures and says the error when a request fails, and draws only the latest choice; confirmations and
  explanations show above the full-screen map; a document's pages drawn 500 at a time (50,000 pages: the panel opens
  in 0.1 s, a removal takes 0.01 s); Merge asks first and is an Admin's; the labels say who can act.
* **The learning**: an Ansible inventory whose host is written with its SSH port is read (the whole inventory was
  lost), so are a range with a step, a huge range, a play whose hosts are a range, vars_files given as one string and
  templated Kubernetes manifests; a long run of spaces in a heading no longer stalls the reading (minutes before);
  forget-learned keeps the indices a person gave a value on the System map; an index activated again brings back only
  the fields it took with it; a value's name is never matched as a pattern ("db_1" was taken for "db01"); a relations
  diagram says a part once ("x" and "x (prod)"); a link a person corrected in To review (turned round, another kind)
  is never withdrawn by the next learning.
* **Integrations and the command line**: a PDF export of a page whose table header is taller than a page ends (it
  added pages for ever); a yes/no setting refuses a word that is neither (a typo turned a TLS check off) and a JSON
  setting a value of another shape than its default; the secret of OpenSearch Dashboards is never said in an error (it
  reached the dashboards list, the Settings test and the LLM); a saved object whose aggregation reads itself no longer
  breaks the reading; a dashboards list item of a long ref no longer blocks every later listing; settings --unset of
  an unknown key and restore of a file that is no backup say so instead of a traceback; a drafted alert rule keeps the
  team grafana.rule_labels fixes.
* **After the gate** (security and crash fixes of the agent's tools, each with its unit test, not measured with the
  LLM): the SQL tools refuse SELECT … INTO (it ran as CREATE TABLE) and a query that reads a dataset with row-level
  security filters for the user (they apply to a chart or Explore of the dataset); a scheduled report goes only to the
  allowed e-mail domains, as an e-mail sent now; the agent makes a note the team's only for a user who may share, and
  deletes another person's note only for one who may delete; a catalog entry of the wrong shape is refused and no
  longer breaks the catalog for everyone; a day at the end of the calendar (9999-12-31 and the day after) no longer
  breaks its chat.

Tests
* Every route: each read answered for an admin without a server error, the four pages drawn, each write refused to a
  person without the AI role, each write given an empty or wrong body answered with an error, never a 500.
* Every page in a browser (tests/ui, Playwright, against a running Superset: SUPAGENT_UI_URL, SUPAGENT_UI_PASSWORD):
  the chat and its panels, every tab and sub-tab of the Data dictionary, the entry and import panels, a Context page
  and its diagram, the search, the System map, every section of the Settings, the Restore panel, the backups and runs
  lists, the usage page and its Servers card, the chat panel on Superset's pages, every "i" explanation; a write cycle
  with SUPAGENT_UI_WRITE=1, a question with SUPAGENT_UI_ASK=1; skipped without them (on a lab: 25 passed).

Measured before the release under a rule written before any result (gate G-0.11 and its amendments, the context in
tiers on), on the frozen build 5def04c with Qwen3.6-35B-A3B (llama.cpp, its server restarted first), one round of each
open set: the main open set on the small model's profile (the lab's server states a 64k window) 160 of 162 right (the
rule: at most 3 misses), 2 wrong without a mark (the rule: 2), both in one chain that left a sales channel out of a
revenue, a miss also seen before the tiers; the observability open set on the big model's profile forced (the LLM
context given as its lines about the question) 29 of 29, none wrong (the rule: 27 and 1). 0.11.0's prompt files (the
agent, its budget, the context's tiers, the search, the memories, the LLM context) are those measured; its tools
changed only by the security and crash fixes listed above. Every page in a browser (tests/ui against the lab, with the
write cycle and a question): 25 passed. A Context built with the new writer on the lab: three summary pages written
again in 125 s (3 LLM calls), each ending with its relations diagram, no counts. The unit tests: 2285 passed. Not
measured: gpt-oss-120b.

Known limits: the agent's tools that need access to a whole database (comparisons, the records about a part, a table's
profile) read it as SQL Lab does for a user with that access, without row-level security filters: give such access
only to people the filters do not separate. Not measured: gpt-oss-120b (the gate ran Qwen3.6-35B-A3B).

Upgrade from 0.10.12.1: pip install the wheel on every host, restart the web servers, the workers and beat; nothing to
run (tables unchanged, v20). New settings: `agent.context_tiers` (on), `learn.history_days` (30),
`backup.keep_days` (30), `backup.upload_max_mb` (2048). The learning's runs older than 30 days and the backups older
than 30 days (beyond the newest) are removed at the first hourly tick: set them first if you keep more. The Context's
pages are written again at the next build and wait in To review. INSTALL.txt, *From 0.10.12.1 to 0.11.0*.

## 0.10.12.1 — 2026-10-16

A correction of 0.10.12's summaries, found by reading its change again the same evening: each document's room in a
summary page was the same (the summary's 24,000 characters shared by six documents), so a wiki of 5,000 pages had the
room of a three-page one: about nine of its central pages. A document's room now follows its number of pages (a small
one keeps its text, 3,000 characters at most; the ones of many pages share the rest, 30,000 in all), and each central
page is given in fewer words (its first 160 characters): a wiki of 5,000 pages among five small documents gives some
hundred of its central pages. What a summary reads of a wiki is then: those central pages (the most linked to by its
other pages), and the relations its pages state (the 80 most stated, from every page the understanding read).

Not measured with an LLM: released by the owner's decision without a gate, as 0.10.12; checked before it, the unit
tests (2212 passed) and the deny-list. On the lab's 11 documents, the summary's evidence gives each document a room
following its pages (222 pages: 10,829 characters and 74 of its pages; the smallest, 3,000), a summary page's evidence
about 40,000 characters.

Upgrade from 0.10.12: pip install the wheel on every host, restart the web servers, the workers and beat; nothing to
run (tables unchanged, v20; no new setting). The summaries are written again at the next Context build (the Context
tab's Build now, or the nightly one); a summary page that exists waits in To review for a person's validation
(`context.review`, on): approve it there. INSTALL.txt, *From 0.10.12 to 0.10.12.1*.

## 0.10.12 — 2026-10-16

Released by the owner's decision without the measurement runs of a gate ("release the fixes on 0.10.12 without
validating it this time", 16 October): checked before it, the unit tests and the deny-list only. It brings the team's
requests of 16 October evening, the agent's fixes of the development rounds after 0.10.11, and 0.10.11.1 and
0.10.11.2.

Not measured: released by the owner's decision without the measurement runs of a gate (no LLM run); checked before it,
the unit tests (2211 passed) and the deny-list. The new summaries' evidence was built on the lab's 11 documents
without an LLM: 600 relations found across their pages, a summary page's evidence about 33,000 characters.

What the team asked
* **Saving what the agent learned is fast**: after every save (a learned answer edited, confirmed or rejected, a
  catalog entry, a memory, a page removed) the knowledge store behind the agent's search read every piece of the
  knowledge (its text, its vector, its categories, its words) and kept the saved kind's: 0.47 ms a piece, minutes with
  a wiki of thousands of pages, the page saying "updating the agent's search" all along. Now the kinds saved are read
  as such, and one document's change reads that document's pieces only.
* **The summary of a wiki of thousands of pages**: the Context's summary pages (How the system works, Technical
  overview, an application's page) were written from the first 3,000 characters of six documents: a wiki of 5,000
  pages gave its first page. They now read each document's digest (its central pages, the most linked to by its other
  pages, each with its first lines) and the relations the documents and the code state about the parts (A calls B,
  runs on C, depends on D..., with the number of pages stating each): the chains between applications come from every
  page. An application's page gets the relations that name it. The main applications are counted over every page.
* **A wiki of more than 5,000 pages**: one document reads up to 50,000 pages (was 5,000); a new one, 2,000 (was 200).
  The list of documents never loads a wiki's text and sends a document's pages only when they are few (its number
  otherwise).
* **Repositories of scripts, custom folders and libraries**: a repository's code is read by default (was its
  documentation and text files only); one asked for its documentation that has none has its code read (it was an
  error, "no text file", and nothing was read); a file without an extension is read anywhere when it is a script
  (its first line is #!: ops/backup, deploy/run), as before in bin/ and scripts/; a build folder's scripts are read
  (build/deploy.sh; what a build left there is not); more scripts and configuration are read (csh, fish, awk, sed, Tcl,
  VBScript, Puppet, Salt, RPM specs, PL/SQL, DDL, HQL, Nomad, Rego, Bicep, Jsonnet, CUE, Nix, Bazel, CMake...);
  20,000 files are listed (was 5,000). A role's copied files and certificates are never taken for scripts.

Answers
* **A last text that only says the work is done** ("The answer is complete. All tasks have been done.", after the work
  plan's last update) is never the answer: the answer written before it is given, or the model is asked once for the
  whole answer.
* **Rows linked to a period's rows, taken by their own date**: "the net revenue of the week", defined in the chat as
  the week's sold orders minus the refunds of those orders, answered with the refunds made in the week (their own
  return date): two different sets of orders. The answer is sent back once to use the reading the question means and
  to say which; the key reading is named when a definition in the chat ties the rows. Found only on the queries whose
  results give the answer's figures (a query tried and dropped is not the answer's reading).
* **A question of what depends on what, answered from a table**: "which applications depend on them?" answered from
  an inventory table, the System map never read, missed a link only the map has. Any data query no longer spares the
  System map: only a figure asked (a count, a ranking, a total) answered from the data does.
* **The query an answer wrote is run** when the answer ran no data query, also after a lookup of the table's
  description: "And on the 23rd?" was answered twice with the SQL written in the text and an invented figure.
* **The first rows ordered by a label are sent back before they run**: "the server with the least available memory"
  queried with ORDER BY 1 ASC LIMIT 1 over (server, its minimum) gave the first server by name. A query keeping five
  rows or fewer of its groups, ordered by a label it groups by (not a time bucket), is sent back once to order by the
  figure; sent again unchanged, it runs.

Also in 0.10.12: 0.10.11.1 and 0.10.11.2 (a chat that froze the browser, chats deleted from the command line, the
servers' CPU, memory and disks in the usage page, several pages of a document removed at once, the steps kept whole).

Upgrade from 0.10.11.2, 0.10.11.1 or 0.10.11: pip install the wheel on every host, restart the web servers, the workers
and beat; nothing to run (tables unchanged, v20; no new setting). A repository document keeps the choice it was saved
with: edit it and choose *All its code too* to have its scripts and libraries read (a new one reads them; one without
documentation has its code read anyway). A wiki: raise its *Pages or files at most* (Edit) above its number of pages;
the Context's summaries are written again at its next build (the Context tab's Build now, or the nightly build).
INSTALL.txt, *From 0.10.11.2 to 0.10.12*.

Known gaps
* Not measured: no gate run (the owner's decision). The agent's fixes were measured in development rounds only (main
  open set 158 to 159 of 162, observability 26 to 28 of 29; an A/B run of the observability set the same day gave 0.10.12
  27 and 29, 0.10.11 29 and 28: a round's variance). The new summaries were checked on the lab's 11 documents (600
  relations found, a summary page's evidence about 33,000 characters) without an LLM run, not on a wiki of thousands of
  pages.
* The relations come from what the understanding reads (calls, runs on, uses, depends on, connects to... written in
  the forms it knows: configuration, code, tables, sentences of those forms); a relation said otherwise in free prose is
  not stated, and the summary says "not known yet" where nothing states it.

## 0.10.11.2 — 2026-10-16

A correction of 0.10.11.1, found by reading its change again the same day: it also cut the steps an answer keeps
(each step's arguments over 4,000 characters), and those steps are read by more than the page: *Helpful* keeps an
answer's query as an example for similar questions, and the learning reads the tables its queries name. A query of
8,851 characters would have been kept as its first 1,002. The steps are kept whole again; only the copy sent to the
chat page is cut. What 0.10.11.1 brought is unchanged, and an answer saved by 0.10.11.1 with a query that long (the
rare case) keeps the cut query: ask it again for a whole example.

Measured in the lab on the frozen build e14434c, as 0.10.11.1 was: a test now proves the point (a query of 5,000
characters and more, in a step saved by the agent's own code, is kept whole by Helpful while the page's copy is cut).
The two chats built like the one reported open as with 0.10.11.1: 0.2 s and 0.7 s, no long task in the page; the rows
of the heavy one, asked, in 4.9 s once. Two paths checked for the first time: a chat that did not finish drawing is
not opened again by itself (the page says so, nothing drawn) and Open it draws it with no long task; the chat panel
opened on a Superset page with each heavy chat answers in 3.2 s, its longest task 274 ms (Superset's own page). Tables
unchanged (v20); the unit tests: 2187 passed.

Upgrade from 0.10.11.1 or 0.10.11: pip install the wheel on every host, restart the web servers, the workers and
beat; nothing to run (tables unchanged, v20; no new setting). INSTALL.txt, *From 0.10.11.1 to 0.10.11.2*.

## 0.10.11.1 — 2026-10-16

The team's report of 16 October on 0.10.11: after a question about the anomalies of an OpenSearch Dashboards
dashboard, the chat, the chat panel and Superset's pages stopped answering in that browser, after a reload and after a
restart of Superset too. And three requests: the chats deleted from the command line, the CPU, memory and disks of
every server a Superset component runs on in the usage page, and several pages of a wiki removed at once.

In the lab, a chat built like the one reported froze the same way, in the browser: an answer's chart. Its bars were
labelled with the rows' values (log messages with their stack traces: thousands of characters each), and the page
fitted each label to its place by taking one character off at a time and measuring the whole text again: minutes of
work for one chart, in the page's only thread. The chat panel is the chat page in a frame of the same site, which
shares that thread with the Superset page around it, and the chat opens again, at every load, the chat that was open:
every Superset page of that browser froze. Superset's server was not loaded by it (its health answered in under
0.01 s while the page was frozen). An answer that kept tens of megabytes of rows (raw log lines) did not freeze the
page but made its chat slow to open (4.7 s to load, 5.1 s to draw): both are fixed here.

Measured in the lab on the frozen build 8bbe720 against 0.10.11, with two chats built like the one reported: a 30-row
"top error messages" answer (labels of 2,000 to 40,000 characters) and a 42 MB answer (six results of 5,000 raw log
rows). With 0.10.11 the first chat's page never answered again (stopped after 3 min 26 s); the second took 4.7 s to
load and 5.1 s to draw, the web process 150 MB bigger. With 0.10.11.1 the first opens in 0.2 s (0.1 MB sent instead of
0.9 MB) and the second in 0.7 s, with no long task in the page; the second's rows, asked with Show the query results,
come in 4.9 s once (then bounded and saved so). Superset's health answered in under 0.01 s throughout. In a browser:
two pages of a document removed at once, the Servers table showing the lab's host; on the command line: a chat listed,
deleted, then said gone. Tables unchanged (v20); the unit tests: 2186 passed.

The chat page
* **Labels and values fitted at once**: a label is cut by halves to its place (from its first 400 characters); a
  column's distinct values are counted as they come (they were listed again at every row: half a second for 5,000
  rows of 12 columns); a value axis never loops on huge numbers close together; a table cell shows its first 300
  characters (more of it in its tooltip); a number is looked for in short cells only.
* **A chat that did not finish drawing is not opened again by itself**: the next load of the page says so, with
  *Open it* and *Delete it*.
* **A chat opens with the rows of its last two answers**; an earlier answer's come with *Show the query results*.

What an answer keeps for the page
* **Bounded**: 120 columns, 2,000 characters per value, 3 MB of rows for all the results of one answer (the first rows
  kept; the page says "first N rows here" or "long values cut here", and an Excel extract asked of the agent has every
  row). The steps' arguments and lists are cut the same way; an answer's text is drawn up to its first 60,000
  characters (*Copy answer* gives all of it).
* **Answers kept before 0.10.11.1** are bounded when they are next read, and saved so; rows over 4 MB are never read
  to open a chat, only when asked (*Show the query results*).

Command line
* **superset supagent conversations**: the chats, the latest first, with their user, their messages and their size
  (counted by the database: a chat too big to open is listed without being read); `--user NAME`, `--limit N`.
  `--delete ID` (repeated for several) or `--user NAME --all` say what would go; with `--yes` they are deleted, with
  their messages, files and the examples taken from them, as the chat's own Delete.

Usage page
* **Servers**: every host a Superset component runs on (a web server, a Celery worker, beat) with its CPU over the last
  minute, load, memory, swap, disks (each over 90 % shown in red), what the Superset processes there take, the last 24
  hours of CPU and memory as small lines, and when it was last heard from (a component silent for 5 minutes is shown
  as gone). Each process of a component writes its host's figures every minute, read from /proc (Linux): nothing to
  install on the hosts.

Documents and sites
* **Several pages removed at once**: in a document's *Pages*, tick the pages (or *all shown* after a filter by title,
  address or space), then *Remove N picked pages*: the document's text rebuilt once, their search pieces and what was
  learned from them deleted, never read again (as one page's *Remove*).

Upgrade from 0.10.11: pip install the wheel on every host, restart the web servers, the workers and beat; nothing to
run (tables unchanged, v20; no new setting). Browsers take the new page files at once (their names carry their
content's hash). INSTALL.txt, *From 0.10.11 to 0.10.11.1*.

Known gaps
* The agent's work runs in the web server when no Celery worker is alive (`agent.executor` auto, or thread): a long
  investigation then shares the web server's processes with Superset's pages. Celery workers keep it apart (README,
  *Celery workers and beat*).
* Measured on the lab, with chats built like the one reported (raw log rows; long labels); the team's own chat was not
  available.

## 0.10.11 — 2026-10-16

Stabilization after 0.10.10: the misses of its gates read as classes and fixed where they come from, and Grafana and
OpenSearch Dashboards set up in the Chat settings page. Tables unchanged (v20): pip install and restart.

Measured before the release under a rule written before any result, on the frozen build 505c2b7 with Qwen3.6-35B-A3B
(llama.cpp, its server restarted first), two rounds of each open set on the small model's profile: the main open set
160 and 160 of 162 right (320 of 324; the rule: 318), 2 wrong without a mark in all (the rule: 3); the observability
open set 28 and 29 of 29 (57 of 58; the rule: 54), 1 wrong without a mark. Grafana questions (13 and an approval): 13
right, every request to change what exists refused, the one rule created being the one approved, nothing else changed.
OpenSearch Dashboards questions: 8 of 9 right; two requests to change it refused, nothing changed. The Chat settings
page checked in a browser (both sections, the secrets as password fields, Test the connection's messages) and Test the
connection run against the lab's Grafana and OpenSearch Dashboards. The unit tests: 2176 passed. The upgrade from
0.10.10 on a copy of a lab: tables v20 unchanged, every setting kept, the System map's 289 values and 2,224 links
kept, health 200, the knowledge search answering. 0.10.11 is that build with one test's sample data renamed (b12534d,
found by the rule's deny-list check and registered as an amendment to the rule before the remaining results were read;
the package's files are the same) and its version. Not measured: gpt-oss-120b.

Answers
* **A tool call written as text** (the model's own markup, which the LLM server did not read) is run as the call it is,
  when it names a tool offered; markup that cannot be read is never shown to the user (asked once more, else the
  answer is written without it).
* **Sizes in the units asked**: a result's bytes given in decimal units no one asked for ("11.00 GB" for
  11,003,281,408 bytes) are sent back once for binary units (10.25 GiB); a whole configured size ("maxmemory 4 GB")
  is left as people write it.
* **A time of day asked is given**: "At what time was it?" answered with the value again and no time is sent back
  once, the next step running the query of the moment.
* **The chat's own words before the memory**: a unit or a format asked earlier in the same chat ("In hours, please.")
  wins over a stored preference; a preference about one kind of figure (how long something took) is about that kind
  only and is not mentioned where it does not apply.
* **A question back ends on its question**, also when it was written "...? Also, please specify the period.",
  "...? Are you referring to:" followed by the choices, or closed by an offer ("If you want, I can also break it down
  by day.").
* **The user's question said again in long work**: when a check sends an answer back after ten steps or more since the
  question, its note ends with the user's question, so the answer is for that question, not for one step of the work
  or the question before (seen in the observability set after long investigations and several checks).
* **The closing summary of an investigation that used up its calls** is written even when the model began one more
  call (it was cut to nothing, and the user got "the model wrote no text").
* **What a failure reaches**: a question that names the kinds of parts it asks for ("which data stores go down, and
  which applications depend on them?") is not asked the parts that only watch, show, own or deploy another
  (dashboards, alert rules, log collectors, teams); the answer lists each part once, the parts asked about first.

Grafana and OpenSearch Dashboards
* **Set up in Chat settings** (Settings -> Chat settings): a Grafana section and an OpenSearch Dashboards section with
  every setting, Save and **Test the connection** (Grafana: the MCP server reaches Grafana and the datasource set is
  one of its datasources; OpenSearch Dashboards: the saved objects API answers with the sign-in set). In 0.10.10 these
  settings could only be set with superset supagent settings --set.
* **A drafted alert rule has the labels its team rule says**: the team as the rules already in Grafana write it ("the
  data team": team=data, not data-platform), and no label the rule never says (service, environment); what changed is
  said with the draft.

Known gaps
* **The observability set with Grafana and OpenSearch Dashboards set up** was not run again for this release (0.10.10:
  28 of 29, the miss an investigation that used up its calls and wrote no text). The closing summary written after the
  last call is checked by unit tests and by the observability set without them.
* **An answer can be only a closing line**: in one OpenSearch Dashboards question of the release run the agent
  answered "The answer is complete. All tasks have been done." after updating its work plan, instead of the answer
  (which index, field, aggregation and filter measure the checkout response time). Ask again; a coming version
  gives the answer written before such a line.
* The rest of 0.10.10's known gaps stand (see 0.10.10): lab instances only (Grafana 13.2.4 with mcp-grafana 2.0.2,
  OpenSearch Dashboards 2.19.5 and 3.8.0 without the security plugin), the numbers behind an OpenSearch Dashboards
  visualization computed by the agent with its SQL tools, Grafana's alert history as its API gives it.

## 0.10.10 — 2026-10-15

The team's requests of 14 October: the team's central Grafana, read through its MCP server (dashboards, alert rules,
alerts and who they reach), in the Context and in the learning, explained, used in health questions and
investigations; alert rules and dashboards drafted by the agent and created only when an admin approves; OpenSearch
Dashboards (2.19 and 3.8, no MCP server) read the same way; in Documents and sites, the list of the dashboards and
visualizations of both, each one read by the agent or not; the agent's context organized so that the three kinds of
dashboards are never confused. Tables v20 (`superset supagent init`); the Grafana and OpenSearch Dashboards settings
are new, and both stay off until set.

Measured before the release under a rule written before any result, on the frozen build beb5b36 (0.10.10 is that build
with its version) with Qwen3.6-35B-A3B (llama.cpp, its server restarted first), one round of each set on the small
model's profile: the main open set 156 of 162 right, 4 wrong without a mark, under the rule's bar (158, at most 2):
released by the owner's decision. The observability open set 28 of 29 right (the rule: 28), 0 wrong without a mark;
the same set with Grafana and OpenSearch Dashboards set up and read by the learning first (9 and 6 dashboards
explained), 28 of 29, 0 wrong without a mark. Grafana questions written for this release and never seen before (13 and
an approval): 12 right, every request to change what exists refused, the one rule created being the one approved,
nothing else changed. OpenSearch Dashboards questions written for this release (9, on dashboards over real indices,
figures checked against the data): 9 right; two requests to change OpenSearch Dashboards refused, nothing changed. The
unit tests: 2156 passed. The upgrade from 0.10.9.2 on a copy of a lab: tables v18 to v20, every setting kept, the
System map's 289 values and 2,224 links kept, health 200, the knowledge search answering. Not measured: gpt-oss-120b.

Grafana (the team's central Grafana, through its MCP server)
* **Reads, fast and condensed**: the agent finds dashboards, reads one whole (the panels of collapsed rows too, each
  panel's query, unit and thresholds), lists alert rules and which fire, reads one rule with its condition and the
  contact points its alerts reach by the notification policies, and tells which panels and rules read a metric
  (grafana_metric_uses). Answers are cached (`grafana.cache_seconds`); the nightly read of every dashboard and rule
  runs on one MCP session, four calls at a time. Texts written in Grafana are given as data, never as instructions.
* **Context and learning**: a facts page per dashboard (what each panel reads and computes, in words; the metrics
  with the data dictionary's descriptions; the System map's values its queries select) and per folder of alert rules
  (query, condition, hold, labels, who is notified), explained by the AI in the learning (what the dashboard watches,
  what would look unusual, which panels to look at first when that part misbehaves; written again only when the
  dashboard changes; `grafana.max_llm_calls` a run).
* **In health questions and investigations**: grafana_watch tells what Grafana shows about a part (a service, a host,
  a database, a team) now or at the time asked: each panel about it against its thresholds, worst first, with the
  alerts firing or pending about it. An investigation or a question of health whose answer never looked at Grafana
  (set up for that user) is sent back once to look.
* **Alert rules from the team's rules**: the agent drafts a rule from a team memory, a catalog entry or the chat
  (metrics checked in the datasource, never guessed; the query run once and refused with Prometheus' own reason when
  it is not valid PromQL; the folder, group and fixed labels of the settings; a preview of the value now and of who
  would be notified). A rule asked in the chat takes a team rule as its source only on clear evidence (what is
  measured, its threshold, its hold, its direction and its team agree), and is found again, never drafted twice.
  An admin approves it in To review; it is then created and read back.
* **Dashboards**: the agent drafts a new dashboard in the right folder of Browse (the folders holding dashboards about
  the same things are always said; panels checked: metrics, PromQL, Grafana's panel types and units); a corrected
  draft replaces the waiting one; an admin approves; it is created as a new dashboard only and read back.
* **Never more**: nothing is written without an admin's approval (`grafana.writes`, off by default); an existing rule
  or dashboard is never changed or deleted, no folder is created; a Grafana MCP server registered in `mcp.servers` is
  never offered whole. Asked to change, pause, silence, rename, move, share or delete what exists in Grafana or
  OpenSearch Dashboards, the agent says plainly it cannot, then what it can do instead.

OpenSearch Dashboards (2.19 and 3.8; no MCP server)
* **Read through its saved objects API** (GET only; basic, bearer or header sign-in, tenant, certificate as set): each
  visualization said in words from its definition (aggregations, TSVB, Timeline, Vega, Markdown, controls, saved
  searches, VisBuilder), with its index pattern, time field, query, filters and color ranges.
* **Context and learning**: a page per dashboard and per index pattern of the visualizations on no dashboard,
  explained by the AI in the learning; the agent's tools osd_dashboards and osd_dashboard.
* **In health questions and investigations**: the agent is told that the team's visualizations say how the team
  measures a part (index, field, aggregation, filters, ranges) and computes the same on that index with its SQL tools.

Documents and sites: which dashboards the agent reads
* **The list** of the dashboards and visualizations of Grafana and OpenSearch Dashboards, with their folder or index
  patterns, type, and when and by whom they were last modified (newest first); a switch per item, Deactivate all then
  switch on the few needed (new ones then wait), a whole search at once (admins).
* **Switched off**: its page leaves the Context and the search at once (never waiting in To review), the AI does not
  explain it, its panels are not watched; the agent's list tools say how many are switched off and, when a question
  names one, that it exists and is switched off (never that it does not exist, never what it shows). A Grafana
  draft's safety checks still see every dashboard.

The agent's context
* **One system named, its tools only**: a question (or its chat) that names one dashboard system set up here
  (Superset, Grafana, OpenSearch Dashboards) is offered only that system's chart and dashboard tools and
  instructions; "OpenSearch Dashboards" no longer reads as Superset dashboards asked; a question that names none
  keeps every system's reading tools; a system named but not set up filters nothing.

Known gaps
* **Checked against lab instances only**: Grafana 13.2.4 with mcp-grafana 2.0.2, OpenSearch Dashboards 2.19.5 and
  3.8.0 without the security plugin. Signing in to OpenSearch Dashboards with the security plugin (basic, tenants,
  a redirect to SAML or OpenID), its workspaces (2.18+) and its multiple data sources are checked by unit tests
  only; tell us what your central Grafana and your OpenSearch Dashboards use.
* **The numbers behind an OpenSearch Dashboards visualization** are computed by the agent with its SQL tools on the
  same index (it is told the visualization's definition); there is no tool that runs a visualization as OpenSearch
  Dashboards does. Grafana's panels are run by grafana_watch through the MCP server.
* **Grafana's alert history** is what Grafana's API and the MCP server give: firing and pending alerts now, the rules'
  states; an alert that fired and resolved earlier is found in the data when Alertmanager's alerts are indexed.
* **An investigation that uses up its tool calls** can end without an answer: with Grafana and OpenSearch Dashboards
  set up, one investigation of the observability set spent its calls (Grafana's panels among them) and the model
  wrote no text, even when asked again; the same question without them was answered right. An answer that runs out of
  calls will say what it found in a coming version; until then, ask a narrower question.
* **A drafted rule's labels** can be off: a rule drafted from a team memory about "the data team" got the label
  team=data-platform. Nothing is created before an admin approves: check a draft's labels in To review.
* The rest of 0.10.9.2's known gaps stand (see 0.10.9.2).

## 0.10.9.2 — 2026-10-14

The team's requests of 14 October: the known gap of 0.10.9.1 (an answer that writes out its query waited for a second
LLM request), the learning's weak spot (a deployment's own categories, when their names are not the usual ones), and
the System map's subcategories; the learning again, on real repositories and wikis it never saw. No table change
(v18); no new setting.

Measured before the release under a rule written before any result, on the frozen build 17a4e01 (0.10.9.2 is that
build with its version) with Qwen3.6-35B-A3B (llama.cpp, its server restarted first), one round of each open set on
the small model's profile (the lab's model reads 64k tokens per request): the main open set 159 of 162 right (the
rule: 158), 2 wrong without a mark; the observability open set 29 of 29 right (the rule: 26), 0 wrong without a mark.
The unit tests: 2033 passed. The upgrade from 0.10.9.1 on a copy of a lab: tables unchanged (v18), every setting kept,
the System map's 289 values and 2,224 links kept, health 200, the knowledge search answering. The learning, no LLM: on
ten development corpora no figure lower than 0.10.9.1's (seven higher); on a corpus built from a real infrastructure
repository and its wiki after 0.10.9.1 was released and frozen before this build was, read once: 63.4 % of the
proposed values in the right category (0.10.9.1: 48.5 %), 59 of its parts found (33), 87.4 % of the links between
known parts right (71.2 %), 3 of 28 map-wide questions answered (none); on four development corpora with the team's
categories renamed (other words, or none at all) and the same descriptions, the same figures as with their own names
(0.10.9.1 filed 33 % to 100 % of them). Not measured: gpt-oss-120b, the big model's profile (unchanged since
0.10.9.1).

The learning
* **The team's categories read by what they say they hold**: the learning filed what it reads into the team's
  categories by their names ("server", "host group", "team", "host software"...). A category named otherwise ("box",
  "fleet", "landscape", or any word of the team's own) is now read by its description in Categories: the head noun
  of its first phrase ("a machine (a virtual machine or a server) by its hostname" holds servers; "an Ansible
  inventory group: ..." groups; "a crew (a team of people)" a team; "software installed on the machines" the hosts'
  software; "a service run by someone else" outside services), else by where the category is nested (inside a
  category of groups: their hosts). A name that already says what it holds is read as before; a description that
  defines nothing changes nothing; the category's own name is the one stored and shown. Describe your categories
  (Categories, each category's description) for the learning to use them whatever their names.
* **Real infrastructure repositories and their wikis read better**: nested roles (roles/<software>/<piece>), the
  servers of a load balancer's backend, a table read by what its columns hold (where each row runs, keeps its data,
  who looks after it), a page defining its title, the groups the plays run on even when no inventory lists them, an
  organisation's deployment roles named after their software (fix and dependency roles propose nothing), an
  application's address whose host is a template (the engine its scheme names), a team named in two languages on two
  pages as one team, the team's own words for a part ("the event bus is a Kafka cluster"), a system named in prose
  by a name of its own shape when a known part's sentence relates to it.
* **Faster**: the learning reads each category's name and description once (a learning run's proposals about a third
  faster on the lab's corpora).

The System map
* **A subcategory moves like a value**: a subcategory's box (made with "+" on a category's name) takes its place
  among its column's values: drag it up or down its column, it stays where it is dropped, for everyone. Before, it
  was always drawn at the bottom of its column.
* **An empty subcategory takes a value dropped on it.**
* **The values inside a subcategory are set in a little**, with a line down their side, so they are easy to tell from
  the category's own values.

Map-wide questions and the knowledge search
* **What breaks when a store or a stream is down** includes what writes to it (an application storing its records, a
  service publishing on a bus), not only what reads it or runs on it.
* **Questions as people write them**: an outage in other words ("unavailable", "goes away", "cannot be reached",
  "which products feel it"), "installed on", the environments a group is in, "the x group" for the groups of that
  name, a team asked in another language than the map names it, where a service of no parts of its own is deployed.
* **A category of servers known by its description** in what the agent reads of the map (the servers a name or an
  address names, what runs where, "if db-01 is down").

The agent
* **A query written out in an answer is run at once** (0.10.9.1's known gap): an answer that writes the query its
  figures claim without calling the tool had that query asked for in a second LLM request first, which could wait
  about two minutes on the lab's model; the query is now run at once and the answer written from its rows.
* **A follow-up's knowledge searched with the question it goes on from**, so another subject's entries of the same
  word do not come first.
* **A follow-up asking a value its chat grouped by but never named** gets its own query instead of being answered as
  if the value had been read.

Known gaps
* **Applications and services of a repository the learning never saw** are found better but not yet well: on a
  real infrastructure repository and wiki read only once, after this build was frozen, 63 % of what the learning
  proposes goes to the right category of the team (0.10.9.1: 49 %), 87 % of the links it proposes between known
  parts are right (0.10.9.1: 71 %), and 3 of 28 map-wide questions are answered (0.10.9.1: none).
* **A category's description changed in Categories** reaches the filing of the hosts' software within a minute (that
  one choice is read again every minute); every other use of it at once.
* **The big model's profile** was measured on the lab's 64k-per-request model forced to a 128k window (0.10.9.1) and
  not on gpt-oss-120b; agent.context_profile = short keeps the small model's sizes.
* The rest of 0.10.9.1's known gaps stand (see 0.10.9.1), but the second request of an answer written without its
  tool, fixed here.

## 0.10.9.1 — 2026-10-14

The team's requests of 14 October: what the agent gives the LLM settable in Settings, for the small model and for the
big one; the System map followed better by the map-wide questions and the knowledge search; the learning again, on
real repositories it never saw. No table change (v18); 31 new settings, all empty (each size is the profile's own,
0.10.9's).

Measured before the release under a rule written before any result, on the frozen build e4e6339 (0.10.9.1 is that
build with the fix of the saves alone, checked by the unit tests, the upgrade and a first conversation) with
Qwen3.6-35B-A3B (llama.cpp, its server restarted first), one round of each open set on the small model's profile (the
lab's model reads 64k tokens per request): the main open set 159 of 162 right (the rule: 158), 3 wrong without a mark;
the observability open set 28 of 29 right (the rule: 26), 1 wrong without a mark. The big model's profile, on the same
model given one 128k slot (auto chose the big profile): the observability open set 28 of 29 (the rule: 26; 0.10.9 got
28 there the same way), the first five chats and ten single questions of the main open set 36 of 36 (the rule: at most
2 not right, none wrong without a mark). The unit tests: 1948 passed. The upgrade from 0.10.9 on a copy of a lab:
tables unchanged (v18), every setting kept, the System map's 289 values and 2,224 links kept, health 200, the
knowledge search answering. The learning: on ten development corpora no figure lower than 0.10.9's; on two corpora
built from real Ansible repositories after the release of 0.10.9 and frozen before the build was (a government
open-data program's 2020 deployment, a Linux distribution's infrastructure, each with a wiki in English and French),
one reading each, no LLM: 86.2 % and 75.6 % of the proposed values in the right category (0.10.9: 85.3 % and 75.2 %),
0.992 and 0.997 of the links right; the map-wide questions on their maps 1 and 2 of 28, as 0.10.9 (see the known
gaps). Not measured: gpt-oss-120b.

What the AI is given
* **What the agent gives the LLM, settable for each context profile**: every size of the small model's profile (a
  model of 32k-64k tokens per request) and of the big model's (128k or more) is a setting of its own, budget.short.* and
  budget.long.*: the prompt tokens from which an answer's older tool results are cut, the knowledge given with a
  question and each of its pieces, each Context section, the LLM context, a tool's result, a description of the data,
  a comparison of groups, of logs, each earlier message, the team's rules, an older result after each cut. Empty: the
  profile's own size (the big model's grows with its window). Three more say when the big model's sizes apply
  (budget.long_from_tokens, 100,000), the share of its window from which older results are cut
  (budget.long_cut_share, 0.6) and the window assumed for a big profile forced on a server that states none
  (budget.long_assumed_tokens, 131,072). A size you type for the big model is used as typed. agent.compact_at and
  search.prompt_chars still apply to both profiles when set; a profile's own setting wins over them.
* **Settings, "What the agent gives the LLM: small model (32k-64k) / big model (128k+)"**: both profiles side by side,
  the profile in use and the model's window, each profile's own size in grey, an estimate of the tokens an answer
  starts with, and a warning when the sizes may not fit the window. `superset supagent test-llm --profile` prints the
  same.

The System map and the knowledge search
* **A group of one environment, asked by its plain name**: a map value named "pool-a (production)" or "web (ops prod)"
  (an inventory group of one environment) is found when a question names pool-a or web: every environment's group of
  that name, or the one of the environment the question names ("what runs on pool-a in production?"). A name of the
  map's own is never taken. The map-wide questions and the agent's knowledge search both find them.
* **A team asked for is an owner question** whatever its verb: "which team looks after X", "who runs X", "what does the
  data team run" are answered from who owns what.

The learning
* **Known software filed where the team keeps it**: application servers, job runners, file and mail daemons,
  antivirus (passenger, sidekiq, samba, clamav...) go to the team's category for the hosts' software; a key-value store
  to its stores; coordination and load balancing services to its shared services; a version number or "cloud" after a
  database's name is the database; roles that only install a client, mount a share or set a path propose nothing.
* **The team's category for what its users use** may be named or described a website, a web application, a portal or
  a product; the category for shared services may say internal or backend services ("product line" stays a line of
  business).
* **Ansible**: a play for each environment ("app_{{ env | default('staging') }}") runs on every environment's group,
  not only the default's; an upstream of a load balancer whose servers are inventory hosts is the application the
  playbooks deploy on their groups; an application's own worker units and roles (app-workers, app_sqs_poller) are its
  names, not parts of their own.
* **French pages and configuration**: possessives ("de son X"), DNS resolver lines and git repository URLs read.

Saves that answer at once (the team's report of 14 October)
* **Deactivating or activating a field, a label, a metric or an index** in the Data dictionary answers at once: the
  LLM context is written again in the background (it reads the whole dictionary: the request waited for it, seconds
  on a big dictionary); the drawer and the rows of the list change in place, an index's fields or a metric's labels
  with it. A query naming what was deactivated is still sent back at once.
* **Removing a page of a document** answers at once and keeps the list where it was: only that document's search
  pieces are written again (before: every document's, in the web server's background, slowing every page); a
  document saved or deleted writes its own pieces only too.

The agent
* **A real zero is no "no data"**: an answer that calls a query's 0 "no data" (and asks back) is sent back once.
* **The chat's period kept on a table whose date is text**: a follow-up whose query reads such a table with no bound
  on time is sent back to keep the period the chat's earlier queries bounded it by.
* **A size converted by hand**: an answer that turns one number of bytes into a binary size that is neither
  conversion is sent back with the right value.

Known gaps
* **Applications and services of a repository the learning never saw** are still found far less often than its hosts
  and groups: on two real Ansible repositories read after the build was frozen (a government open-data program's, a
  Linux distribution's infrastructure), the hosts and groups were nearly all right, but only a few of the products,
  internal services, databases and outside providers were proposed, and almost none of the links between them; the
  map-wide questions ("what breaks if the database is down", "which team runs X") on those maps were answered for 1-2
  of 28. What an application's configuration says of its stores (a postgresql://, redis:// or amqp:// URL whose host is
  a variable) is not yet a link. This is the next release's first work.
* **The big model's profile** was measured on the lab's 64k-per-request model forced to a 128k window (obs7dev 28/29 for
  0.10.9; see "Measured") and not on gpt-oss-120b; agent.context_profile = short keeps the small model's sizes.
* **An answer the model writes without calling its tool** (the query written in the answer) is sent back once; on the
  lab's model that second request can wait about two minutes before the query it wrote is run (0.10.9 and 0.10.9.1
  alike, a few times a day on the lab's suites; the answer is right). The next release's first agent work.
* The rest of 0.10.9's known gaps stand (see 0.10.9).

## 0.10.9 — 2026-10-14

The team's requests of 12 and 13 October: the AI given as much as the model can read (a 32k-64k model and a 128k-256k
one each get their own sizes), an LLM context the learning writes for the model in a full and a light version, the
memories given whole and first, edited in place, fields and metrics deactivated; the System map's values ordered by
hand; a document's page removed for good; the learning made mature on the kinds of sources the team keeps (Ansible
repositories with their inventories' groups and child groups, Confluence pages and their tables, Python services with
their configuration, scripts, Bitbucket): its proposals are names, one value per thing, filed in the team's own
categories. No table change (v18); three new settings.

Measured before the release under a rule written before any result (the held-out sets never read: totals only), on the
frozen build 4073711 with Qwen3.6-35B-A3B (llama.cpp, its server restarted first; the lab's model reads 64k tokens per
request: the short profile), each open set twice (two rounds): the main open set (162 steps) 161 and 160 of 162 right
(the rule: 158 in each round), 1 and 2 wrong without a mark; the observability open set (29 steps) 27 and 28 of 29
right (the rule: 26 in each round), 0 and 1 wrong without a mark; the held-out sets of 0.10.9 (101 steps on a main lab
and an observability lab) 94 of 101 right (the rule: 91). The unit tests: 1,843 passed. The upgrade from 0.10.8.1 on a
copy of a lab: tables unchanged (v18), every setting kept, the System map's 289 values and 2,224 links kept, health
200, the knowledge search answering. The learning: on ten development corpora (six messy multi-subject ones, four from
real repositories and wikis), no figure lower than 0.10.8.1's (values in the right category, right links, relations
found). The learning on a corpus written after the build was frozen (a university library's real Ansible repository:
inventories with their groups and child groups per environment, the applications' variables, playbooks and load
balancer configurations; and a wiki in English and French), one reading, no LLM: 173 of the 199 values proposed in the
right category (86.9 %), 263 of 269 proposed links right. Not measured: the long profile (a 128k-256k model; the lab's
models read 64k tokens) and gpt-oss-120b.

How it was released: the first frozen build (fc2af03) failed the release gate's first round on the main suite (7 of
the first 112 steps wrong: a net revenue's formula, a business date's field, a unit asked): the memories, now given
whole and first, took what they needed beyond their room out of the knowledge found for the question. The released
build gives them their room on top of it (and re-reads a stored LLM profile that has no context window, 0.10.8's);
it was then measured from the start.

What the AI is given
* **Two context profiles** (agent.context_profile: auto, short, long). Short is a model of 32k-64k tokens per request:
  the sizes of 0.10.8, unchanged. Long is a model of 100k tokens or more (128k, 256k): the knowledge given with a
  question, each Context section, each tool result, the chat's history and the memories grow with the window (128k:
  four times the short sizes; 256k: six times; never less than short), and the older tool results of an answer are cut
  from 60 % of the window (24k tokens before, whatever the model). Auto reads the window from the LLM's server (vLLM's
  max_model_len, llama.cpp's context per slot) and keeps it in the LLM's profile; agent.context_tokens says it when a
  gateway does not. A size you set yourself (agent.compact_at, search.prompt_chars, memory.prompt_chars) wins over the
  profile's. Settings -> Chat settings and `superset supagent test-llm --profile` show the profile in use and why.
* **The LLM context**: after each learning, two pages of the Context (technical), "LLM context (full)" and "LLM context
  (light)", written from the catalog (the team's rules, glossary, formulas, notes), the data dictionary's main indices
  and metrics with their meaning (the full one with their fields and values), the links between the databases and the
  questions the team marked Helpful; no LLM. A model of the long profile is given the full version with every
  question (agent.llm_context, on); a model of the short profile is given the light one only when you set
  agent.llm_context on yourself: on the lab's 64k model the light version made the agent answer some follow-ups from it
  without a query. Each user is given only what their databases hold; the rules are given apart, once. Both pages
  are yours to edit (the learning then keeps your version) or to refuse. The instructions say it holds no answer: a
  figure, a list, or what a given record is or has always comes from a query.
* **Memories**: every memory is given whole (its lines kept), before the other knowledge, and never left out (they were
  cut to 400 characters and could give way to the search); "remember that X" is kept as written, at once, before the
  answer (the AI no longer rewords it after); a memory of a field that no longer exists is said so, not dropped. They
  come on top of the knowledge found for the question: the team's formulas and what a field means never give way to
  them (a first build took their room from the knowledge and lost answers that need a formula: found by the gate,
  fixed before the release). memory.prompt_chars is no longer used.

Memories and the Data dictionary
* **Edit a memory** in place (Memories: Edit; its text, kind and scope), as its author or an admin.
* **Deactivate a field, a label, a metric or an index** (Data dictionary: Deactivate): the agent and the search no
  longer see or use it; a query that names it is refused before it runs; deactivating an index or a metric
  deactivates its fields or labels with it, and Activate brings them back; the learning keeps it deactivated. Shown
  "deactivated" in the dictionary; the LLM context is written again.

The System map and the documents
* **Values in order**: in Edit, a value moves up and down its column only and keeps the place you drop it at, for
  everyone; "+" on a category's name makes a subcategory and values are dropped into it. Values placed anywhere before
  are back in their lists.
* **To review and the System map open faster** on a big deployment (measured: To review 3.1 s -> 1.2-2.2 s, the map
  2.1-2.5 s -> 1.0 s on 1 288 values and 4 297 links).
* **A page removed from a document** (Documents and sites: Pages: Remove) is never read again, and what came from it
  (its text, its search pieces, its facts) is deleted at once.
* **An upgrade reads the documents again once** with the new reading rules (the reader's version is the package's).

The learning
* **A value is a name**: no bare number or code, no version, no quantity, no date, no address outside an address's
  category, no placeholder, no ticket, no path, no word for a kind of thing alone (a team or an area may be named with
  common words in its own category: "Platform team", "data"); no part proposed from one sentence of one page.
* **One value per thing**: names of one thing written differently (case, separators, a plural, short forms, an
  environment's or a version's word) are put together (`superset supagent consolidate`, --dry-run to see it);
  servers' and groups' names are compared as written; a doubt goes to the LLM or to To review.
* **Filed in your categories**: what a part is comes from the noun next to its name in the pages, what the reading
  knows of it (an inventory's group, a host, a VIP) and its name's shape; it goes to the category of yours that says
  it (your groups, VIPs, namespaces, topics, jobs, buckets, providers, software, brokers, areas, teams), then to your
  one category of services, never to a team it is for.
* **Ansible as written**: inventories' groups and child groups (ini and YAML, per environment); a role installed from
  Galaxy is read from its own folder (roles/namespace.name: its tasks decide whether it runs a service); roles that set
  the hosts up, the system's daemons (autofs, atop, sysstat, yum-cron...), a role applied as another part's user, its
  systemd units, modules or plugins, and jobs (x-importer, x-lint, x-cleanup) make no part; a host agent (telegraf,
  node exporter) is kept; scripts and templates are read; firewall lists and a collection's steps are no parts.
* **Pages and tables**: a services table says where each service runs, its owning team ("Owner", "Team", "Run by",
  "Operated by") and its area or domain ("Area", "Domain"); a table of hosts gives each host's power supplies, switch
  ports and owner; systems and their parts ("X is a module of Y", "Y is made of A, B and C"); teams from ownership
  sentences in English and French; initials ("Identity Hub (IH)"); a server's short name in the pages is that server.
* **Repositories**: a Compose file whose services all carry one product's name (tick-web, tick-postgresql,
  tick-nginx) is that product; a repository's one service built from its own root is the repository's application,
  by its name; a database name computed by the code is no name.
* **The full picture**: the map's communities, a Context page per community, map-wide questions answered by
  environment and category.

The agent
* An open question asked back names the System map's parts; a long list of choices keeps its question last; a bound
  on a table's time field in epoch milliseconds is the question's period; a crash said with a guessed cause reads the
  pods' events first; a chart change asked is saved even when the model asks for a preview; a table's "Depends on"
  column is a dependency; a field's values learned from a sample are said to be a sample.

Settings (new): agent.context_profile (auto), agent.context_tokens (0: as the server says), agent.llm_context (on:
the full version to a long-profile model; the light one to a short-profile model only when you set it).

Known gaps (0.10.9)
* **The full LLM context on a 128k-256k model is not measured**: the lab's models read 64k tokens per request. If the
  agent answers questions about the data without running queries, set agent.llm_context=false.
* **External services**: a provider, a SaaS or a public site a configuration or a page names by its address
  (api_url: https://..., "calls carrier-x-api (api.carrier-x.example)") is filed as an application of yours when no
  page calls it external, partner, provider or vendor; its host may also give a second value (carrier-x beside
  carrier-x-api). With a category of yours for external services, move them there once (To review); without one,
  reject them or make one.
* **A product's processes sharing one image** in a Compose file without one name (a self-hosted vendor stack: web,
  worker, cron, many consumers) are each proposed, each with the links its shared settings give: approve the product
  and its main parts, reject the rest.
* **A sample inventory** (inventory/sample/) is read as a sample: no groups proposed from it, by design.
* Dokku-style application lists in a group's variables are proposed as applications on that group.
* **Software named by a role** (passenger, sidekiq_worker, samba, clamav), a key-value store or a coordination service
  (redis, zookeeper, solr9cloud) can be proposed as an application, or as host software beside your category for
  datastores or platform services: move it once in To review (measured on a fresh corpus: 13 of 199 values in
  another category than the person's).
* **A load balancer's upstream names** (nginx "upstream shop-prod", "media-downloads") are proposed as applications
  of their own: reject them; the application they serve is already on the map by its own name.
* **A memory of a preference for one kind of figure** ("give durations in minutes") can be applied to other figures,
  now that memories are given whole and first: an answer about a memory size may add a note "in minutes" beside
  the right size. Write such a memory with the figures it is for ("durations of jobs in minutes").

## 0.10.8.1 — 2026-10-12

The position labels in D labels only, with osagg 0.2.15. osagg 0.2.15 labels a position date D (today's), D-1, D-2...
(working days before today, Monday to Friday) or D+1, D+2... (after today): the week and year labels W-x and Y-x are
gone, and a filter on them (or on M-x) selects nothing. **Install the two together**: 0.10.8 with osagg 0.2.15 filters
on W-1, which compares D-1 with nothing and says nothing about it; 0.10.8.1 with osagg 0.2.14 asks for D-6 where osagg
0.2.14 still says W-1. Nothing else changes: no table change (v18), no new setting, no new reading of the documents.

* **The agent's rules**: POSITION_LABEL is D, D-1, D-2... (working days back; the same weekday a week earlier is 5
  more: D-1 and D-6), filtered as POSITION_LABEL IN ('D-1', 'D-6'); they said D-1, W-1, Y-1 and IN ('D-1', 'W-1').
* **A label column learned from the connector** is described "(D, D-1, D-2...: working days back)". A column learned
  by an earlier version, "(D, D-1, W-1, Y-1...)", is said so at the next learning of its database (its stored text,
  its help and its description), not only when its index is profiled again; no request to the database. A
  description an admin verified is kept as written.
* A comparison on a value that is no label is sent back naming D, D-1, D-2... (it named W-1 among the labels).
* The example catalog's glossary line for POSITION_LABEL is osagg 0.2.15's (it said W-1, W-2... and Y-1).

Your own charts, dashboards, alerts and saved queries that filter POSITION_LABEL on W-x, Y-x or M-x select nothing with
osagg 0.2.15: write them with D labels. W-1 was the same weekday a week before the session date: D-5 after the 14:00
cut-off, D-6 before it and at weekends; W-2: D-10 or D-11; Y-1 is the D-x of the same date a year earlier.

**Your catalog's glossary**: a POSITION_LABEL line that names W-1 (a glossary imported from osagg's catalog.yaml before
0.2.15 says "W-1, W-2... Y-1" and filters IN ('D-1', 'W-1')) still sends the agent to a label that selects nothing:
edit it in Settings -> Data dictionary -> Catalog to osagg 0.2.15's line (INSTALL.txt, *From 0.10.8 to 0.10.8.1*).
supagent never changes an entry a person wrote or imported.

Checked: the unit tests (the expected texts and one new test: a column learned with the old text, one verified, a
second learning that changes nothing); the dates of D-1, D-5, D-6 and W-1 under osagg 0.2.14 and 0.2.15 at four
moments (a weekday before and after the cut-off, a Monday morning, a Saturday): D-6 under 0.2.15 is the date W-1 had
under 0.2.14 before the cut-off, and the dates of D-1 are the same. Not measured: no question set was asked again (the
change is the wording of the labels and the description of their column).

## 0.10.8 — 2026-10-11

The team's requests of 11 October and the known gaps of 0.10.7. A short first question that names nothing ("what is the
number of errors?", "how is the CPU?") is asked back at once with the main parts of the System map suggested, instead of
many calls over everything; a name written in another case or with other separators, and a server named by its short
name, its full name or its address with a port, are searched as the data writes them; all but one of the gaps listed
with 0.10.7 are fixed as classes (each with tests on other data, no question's text or value in the code). Developed and
measured on the open question sets only: the held-out sets were used in 0.10.7's last fix loop, so 0.10.8 has no
held-out figure; new sealed sets come with 0.10.9. Published at the owner's request once the full open run below ended.

Measured on the release's code (build 089239c) with Qwen3.6-35B-A3B (llama.cpp), each open set once (development
figures: these sets were used to find the fixes):
* Main open set (156 questions + 6 written for the team's requests: 162): **159 right (98.1%), 3 wrong without a
  mark**; of the 156, 155 (0.10.7's final run: 154 and 154).
* Observability open set (25 steps + 4 written for the team's requests: 29): **24 right (82.8%), 5 wrong without a
  mark**; of the 25, 21 (0.10.7's final run: 23 and 24; an earlier build of 0.10.8 the same evening: 25). Read by
  hand: no name was rewritten and no question was asked back in them (an investigation that missed one of its causes,
  and its follow-up's count; a route asked to "the payment gateway" looked for to another part; a question whose
  queries two checks refused in turn: known gaps, below). Asked again three times each after the release, these four
  were answered right 11 times of 12 on the release's code and 10 of 12 on the earlier build of the same evening: a
  run's variance, not a regression of this release.
* The team's requests (10 questions): 7 right. A short question that names nothing was asked back with no call each
  time; two were asked back with kinds of errors as suggestions instead of the System map's parts, one with its
  list of choices after the question. A server given by its full name where the metrics write name:port is answered
  (it was asked back before).
* A simple question answered over its budget of calls and seconds counts as a miss in these figures.
* 1563 unit tests passed; no lab name or benchmark figure in the code; the upgrade 0.10.7 -> 0.10.8 on a copy of a lab's
  data: tables v18 unchanged, its 29 settings kept (same digest), health 200, a smoke 5/5; the knowledge search on a lab
  map: 80/80 names found twice (as 0.10.7).

Questions that name nothing
* **A short first message that asks a measure and names nothing is asked back before any call**: "What is the number
  of errors?", "what is the nulber of errors" (misspelled words too), "Combien d'erreurs hier ?", "How many requests
  failed?", and the same for what a team monitors per part (CPU, memory, heap, disk, space, load, latency, throughput,
  traffic, network, connections, queues, lag, uptime, availability, pods, health, status...). One short question back
  asks which part, and which period when none is said, and suggests the System map's main applications, components,
  services and servers (the most linked first, eight per category, with how many more), and "all of them" when a total
  is wanted. Only when the map has two parts at least; a question that names a part, a value or a table, a follow-up or
  a longer request is answered as before (checked on the four question sets of the labs: only the open questions
  written for it are asked back).

Names as the data writes them
* **A name written another way than the data writes it is searched as the data writes it**: a query comparing a field
  or a metric's label (=, IN, <>, NOT IN; PromQL label matchers) with 'HOST-A-07', 'host_a_7' or 'web 01' for the data's
  host-a-07 and Web-01 found nothing. Before the query runs, the value is rewritten as the data writes it when exactly
  one learned value of that field or label is written so (case, separators - _ . / : and spaces, leading zeros); an
  exact value is never touched, two candidates leave it as written. The result says it: "'HOST-A-07' is written
  'host-a-07' in the data: the query used it so."
* **A server is found by its full name, its short name or its address with a port, whichever is asked**: the data
  writes web01.corp.example (or web01.corp.example:9100, a metric's instance) and the question says web01, or the
  other way. On a field or a label that holds hosts (host, hostname, instance, node, server, fqdn, device, target...),
  queries (SQL, PromQL, and the conditions of compare_groups, compare_logs and what_they_share) are rewritten as above
  when exactly one learned value is that host (an address of the asked port first); the System map finds a server by
  its short name, and a full name or an address finds the server of that name; check_health matches the named
  servers to the series by any of their names; records_about looks for the names as each target field writes them;
  the knowledge search says where every spelling of a host is in the data. Never another host of the same short name
  (web01.corp.example is not web01.dmz.example: two of them are left as written, and an empty result lists both),
  never an IP prefix, never a word that every question uses (a server named graph... is not found by "graph").

Investigations
* **The part an investigation blames has its own log lines read**: the change behind a failure was found and the error
  the part logged was never read; such an answer is sent back once to read the part's error lines of the window and say
  the error.
* **"Who held it?" is not answered with a user the lines only show waiting for the lock**: an answer naming a user or
  an application that the results only show waiting is sent back once to read the server's lines of the window without
  a word filter, the longest durations first.
* **An observation the question states at a time of day is read by minutes before it is denied**: "orders dropped to
  almost nothing around 08:00" was denied from hourly totals that hid a drop of some minutes.
* A question of how parts are linked (what consumes, depends on, runs on...) answered without the map's tool is sent
  back once with system_links made compulsory (consumers reached through a mirror were missed); a count question, or an
  answer the data gave, is never sent back by it.

Figures and follow-ups
* **A code the data writes for a name the people said is said**: a country, a currency, a language (the ISO codes of
  the CLDR data that Superset's Babel carries, named in seven languages); a count of one country's orders written with
  the country's code was refused as a condition nobody asked for, and the answer counted every country.
* **A message that goes back to an earlier question ("Back to ...: ...")** is told which question its words name and
  that its conditions (the subject, the day, the filters) are that question's, not the later questions'; what it asks,
  and in which unit, is its own.
* COUNT(*) on a metric named as samples (sample_count, points, scrapes) runs (it was refused again for each new query);
  a rate summed inside a CASE is sent back as a rate, like SUM(rate).
* **A windowed PromQL function whose window is the whole period asked is read once, at its end**: increase(x[45m]) over
  08:00..08:45 was read as a range of points, each looking 45 minutes back, and the answer gave a busier window's
  figure.
* Sent back for a value at a moment, the answer reads it in one query with all it needs (a share read in three queries
  took a simple question over its budget).
* **A zero from a word searched in a text, when the word is a value of another field of the table, is sent back** with
  that field to count with ("none of its failures were timeouts" when TIMEOUT is an error category).
* An answer cut a second time gets the older tool results shortened and is asked once more (its context was near the
  model's limit).

Honesty
* **A reply to a check that argues instead of answering keeps the answer it replaced** (when it gives none of its
  figures and names, or only some of them in a shorter text): a right list sent back came back as "the question asks
  ... so I used the field X", the list never written again.
* An opening that announces the answer ("Based on my investigation, I can now provide you with the answer:") is removed;
  an answer that points at a result instead of giving its value ("(value from earlier result)", "[value]") is sent back
  once to write each value or leave the row out.

Known gaps, seen in the measured run (for 0.10.9): a chart change asked ("make it a pie chart") can be left as an
unsaved preview when the model asks for one, and the answer says the chart changed (the check of claimed changes missed
"I've successfully updated"); a time filter written in epoch milliseconds on a numeric time field can be refused as a
condition nobody asked for while the period check asks for one, until the calls run out; a short question that names
nothing can be asked back with kinds of data as suggestions instead of the System map's parts, or with its list of
choices after the question; a part asked about in a yes or no can be confirmed as a cause because its alert fired at the
same time (listed with 0.10.7: not fixed in 0.10.8).

## 0.10.7 — 2026-10-11

The agent's answers made steady (the team's request of 9 October): questions on the System map's paths (from a part to
the metrics, the documents and the parts to check), root causes with their decoys, the fastest way for simple
questions, and an honest "no data". Developed on open question sets; at the end, at the owner's request, the
held-out sets were used too: the release candidate's held-out failures were fixed (each as a class of failure, with
tests on other data, no question's text or value in the code) and the sets run again. The held-out figures below
therefore measure questions the last fixes were made against, not unseen ones. One held-out grader was corrected
before the final run: it read "0 minutes late" and "failed 0 times" as a late report and a failure.

Measured on the frozen build 7eb7412 with Qwen3.6-35B-A3B (llama.cpp, its server restarted first), every set twice,
under the rule written before any run (absolute targets):
* Held-out sets (75 + 25 questions, twice: 200 answers): **185 right (92.5%), 11 wrong without a mark**; the rule asked
  190 and at most 4: NOT met. Round 1: 74/75 and 21/25; round 2: 69/75 and 21/25.
* Open sets (156 + 25 questions, twice: 362 answers): **355 right (98.1%), 7 wrong without a mark**; the rule asked 95%
  and at most 7: met. Round 1: 154/156 and 23/25; round 2: 154/156 and 24/25.
* A simple question answered over its budget of calls and seconds counts as a miss in these figures.
* 1517 unit tests passed; no lab name or benchmark figure in the code; the upgrade 0.10.6 -> 0.10.7 on a copy of a lab's
  data: tables v18 unchanged, its 29 settings kept (same digest), health 200; the knowledge search on a lab map: 80/80
  names found (78 asked).
Published although the held-out clause of the rule were not met: the owner asked for this release by the afternoon of 11
October, after a last loop of fixes (above).

Known gaps, seen in the final run (for 0.10.8): a name the question says that the data writes as a code (a country
and its ISO code) can be refused as a condition nobody asked for, and the count then covers more than was asked; an
answer sent back by a check can be replaced by a reply to the check; a follow-up going back to an earlier subject
("back to ...") can keep the subject of the turns in between; an investigation can find the change behind a failure
and miss the error its part logged; "which database user held it" can be answered with the user that the lines show
waiting for the lock; a part asked about in a yes or no can be confirmed as a cause because its alert fired at the
same time; an observation the question states at a time of day can be denied from hourly totals that hide a drop of
some minutes; the consumers reached through a mirror (two links on the map) can be missed; a metric counted by its
samples (COUNT(*)) is refused again for each new query, which spends the calls of a simple question. Read by hand,
two of the held-out answers counted wrong say the right thing (a "no data" written in other words; a right count
followed by another day's figure); the figures above stay as graded.

Questions on the System map
* **The routes from a part to another** (`system_links` with `to`): each route a list of links, the shortest first,
  distinct routes only, from each named part apart; given first in the tool's result, like **what a failure reaches**
  (a server, a rack, a room or a cluster: the parts on it, then the ones that call them), the long chains cut short.
* **An answer on what a failure affects names every part it reaches** (system_links' `if_it_fails`: on it, then
  through it, then further), or says why one is not affected.
* A question of dependencies goes to the map's tool first; the servers a part runs on are said with where they are in
  the data (their metrics' and logs' labels); a scrape target of a host is said; a file named after a part speaks for
  it; a data source's address comes before its type.

Investigations
* **An investigation about to run out of calls with its records never looked up spends one on what changed behind
  the cause first** (a deployment): its calls had gone to queries that failed.
* **Records with a start and an end (alerts, incidents, maintenance) are read by their overlap with the window** in an
  investigation, once per answer: an alert raised the day before and still firing was never read.
* Facts asked by their name ("the export of the 28th") are a lookup with the whole picture of their parts and their
  records; a cause said with a verb stays an investigation; a recurring thing asked as a cause is compared with its
  other days; the records that began just after the time given are read too; `records_about` reads a record table that
  is an index pattern.
* **A cause blamed whose records were never looked up** is sent back once (its changes, jobs and alerts read first).
* **A yes or no asked about a suspect is said first**, then why (out of calls too); a suspect named with a hedge is
  checked, not repeated. "What was the cause?" is no yes or no: it is not asked for one.
* A subject, an aspect or a value that only watches others (a monitoring job) is never taken for a blamed part.
* **Where the rows it blames ran** (a server, a host, a node read in their table) is part of an investigation's answer:
  read once when no query did.
* The work plan's step "what changed behind the cause" counts as done once the records were looked up (nothing found
  included); a task of the plan that is the answer itself ("compile the final answer") is written by answering.
* **Who did something on a part** (which database user, account or session held, ran, deleted...) is read in the
  log lines of that part's servers, not taken from a change's author: an answer whose queries read none of them is
  sent back once; the service user is read where its error says.

Metrics
* "Which metrics...?" asks for their names: the first query of their values is sent back once (one more is allowed).
* **The data dictionary of one metric gives the values of its labels in all its data**: the learning reads an hour of
  series, which an incident's rare value (result = error) is not in; describe_data of that metric adds them ("ok,
  declined (also in its data: error)") instead of letting the agent conclude the metric cannot count errors.
* "Which metrics show it?" after an incident reads the data to tell which moved; a follow-up that names a category ("on
  the database side") and no value of its own means the values of that category the chat named: they are searched with
  it. A family's metrics are offered together.

Figures and follow-ups
* A follow-up asking a new aggregate ("and its average?") or a new value (named in the plural too: "timeouts" for the
  value TIMEOUT) needs its own query; an average per day of an
  amount sums each day first; "its" refers to the chat's subject, not to the previous question's own narrowing; a
  follow-up counts the rows of the answer it goes on from; its time is checked against the hours of the answer before;
  a figure asked after an investigation is answered as one figure.
* A follow-up's answer that gives names, times or figures no result holds is sent back with a query made compulsory
  ("at what time was it?" after the day's maximum is read, not guessed).
* **A follow-up answered with the previous answer written again** (a root cause's whole report for "how many times
  were they killed?") is sent back once with the question it has to answer, said in the first sentence.
* **A field the question names is read**: "how many jobs were relaunched?" counts the flag RELAUNCHED, not another
  field's value that looks like it (said once when no query read it).
* A total minus its part (the sales minus the refunds of those orders) is not computed over one INNER JOIN, which keeps
  only the rows that have a part: the total over all its rows, the part through the join. A join of a raw index that
  the connector refuses (written WITH) is answered with the join that runs (the tables themselves, aggregated).
* Sizes in binary units are computed with binary factors; the statistics of single runs come from the runs' records;
  days written in full ("the day after 26 September") are said as dates.

Honesty
* **No zero for data that is not collected**; an absence of data is said first, then where it was looked for; a zero
  counted by a text search for a name no field holds is sent back (where its records are is looked for first).
* A health check with no check defined is said so, not counted as a check that failed.
* A query written in the answer with a result made up is run; an answer that stopped in the middle, or that only
  promises the answer or announces one more check ("let me verify ...") when out of calls, is asked again once; an
  unreadable tool call is retried once; the very same call sent a third time ends the calls (the answer is written
  from the results); an answer that ends inside a table row or a code block left open is asked again, whatever its
  length.
* A word of a data name is not a value (a value's word written as part of a queried table's name, "network receive
  errors" for a ..._network_receive_errs_total counter, is not taken for a team named network); a filter value that is
  another field's name is said; a question back ends with its question.
* When the calls run out after a check sent an answer back, the answer written last is given (with its marks), not
  "the model wrote no text" and a raw result; an answer written again after any check says nothing of the check; a
  check that corrects one detail (sizes in binary units, a count, a zero) asks for the whole answer again, not the
  detail alone.
* An answer built from a tool's result (the map, the dictionary, a dashboard's or a dataset's description) is not
  sent back for names no tool gave: its headings and the keys of its lists ("**Routing layer**", "- **Purpose**:")
  were taken for names, a tool made compulsory, and the model wrote in circles; an answer with no tool result behind
  it is checked as before. What an answer says was done to a note is checked in a chat about notes only.
* A step that had to call a tool and went round in circles, with no result yet, is asked for the call again (not
  for a final answer "from the results above", which were none).
* "Compare with X." after several measures compares every measure the chat asked, not the last one only.
* **A term the team defined with some values of a field is computed with those values**: "the orders delivered"
  computed with the orders paid too (a wider rule of the team, for sales, put in place of the definition) is sent
  back once (by code, `agent.definition_links`); a value another term of the question or the question itself names
  is allowed. The glossary given with a question says so.
* **"Which part has the most ...?" answered from single rows that repeat a part** (one trader's row for a book) is
  said with the result: the rows are summed, counted or averaged per part before the comparison.
* A day said in several words ("the day before yesterday", "3 days ago", "last week", "this morning") is one date:
  the words before it name the period's event ("closed the day before yesterday": the closing time).
* **A follow-up that names its subject and asks another measure** ("What was <name>'s average latency that day?"
  after "Which model had the most failures?") is about that subject, not the failures the previous question kept to
  (told by the earlier answers' queries, whatever words were used); the same name with no other measure ("And
  <other>'s?") keeps them. When a follow-up's conditions are sent back, the agent decides (a message with no scope of
  its own goes on from the chat's) instead of asking the user back; a question back asked again word for word for a
  new question is sent back.
* **"(a) OR (b) AND <filters>" is never run as written**: refused with the WHERE it means, "((a) OR (b)) AND
  <filters>" (a comparison of two days counted the first day's rows unfiltered when the refused call was sent again).
* **A level asked at a time of day is read at that moment** ("the memory use at 09:30"), not as the average of the
  hour that starts then: sent back once to read the samples at the moment.
* Sent back for the chat's period, an answer that says the period with no query run since is sent back with a query
  made compulsory (a follow-up's count over every day was said to be the week's).
* A failed call refused when sent again is no failure of the source, and a call without the expression an error
  names runs (SUM(CAST(n AS BIGINT)) refused by a metrics source, then SUM(n) refused too).
* An answer's opening "I have all the information needed ... No additional tool calls are needed." is removed.
* **A memory that applies only when the user says X** ("When the user says 'X', filter by APPLICATION='X'") is not
  given with a question whose chat never says X (told "applies only then", a model still filtered by X), and another
  memory that only names X ("the critical applications are X and Y") does not make that filter asked for a question
  it has nothing to do with.
* "It happens every night: was that related to the problem?" is answered after comparing with the other nights:
  what happens at the same hours every night is the usual, not the cause of a problem that happened once.
* A dashboard (a value that shows other parts) is never blamed as a cause.
* The metrics found by search_knowledge say the values of their small labels in all their data, beyond the hour
  the learning sampled ("result: error" only in an incident's hours), as describe_data of one metric does.

The fastest way
* A simple question searches the knowledge once and reads the dictionary at most twice before its query, and lists
  no databases once the dictionary said where the data is; after its fifth call it is told once to answer when the
  results hold the answer.
* "Which metrics ...?" asks for names: each new query of their values is sent back (two at most), not only the first;
  the same query sent again runs (when the values are needed to tell which ones).
* A search of the knowledge of one kind that finds nothing searches every kind (a runbook kept as a wiki page is
  found when the guides were searched); a search that found nothing is not the question's one search.
* **The knowledge given with a question holds the sentence that answers it**: of two pieces of one page found, the one
  that writes the names of the question is given ("which one is its primary?" gets "the primary runs on ...").
* "Which data stores ...?" lets a query keep the kinds of store (database, cache, broker, storage) without a send-back.

The knowledge search
* **The System map's explanations that the AI wrote are said so** wherever the agent reads them (the map's pieces of
  search_knowledge and of the knowledge given with a question, the brief's "What to do when following them",
  system_links): "- a monitors b (explained by the AI): ..." (a person's own words as they are). An answer gave the
  AI's advice on following an alert's link as "what the runbook says", the runbook itself in the same result.
* "guide", "doc", "runbook", "wiki", "documentation"... search the catalog's guides and the documents and sites
  together; a kind that finds nothing searches the documentation and the users' notes, then every kind.
* An excerpt of a piece is chosen by the words of the question it keeps whole: a runbook's line of steps was cut
  from the knowledge given with the question while its title was kept.
* `records_about` reads the servers (and groups of servers) the System map says the named parts run on: an alert of
  a cache is kept under the server it runs on.

Documents and sites
* **A wiki's pages are read through every way a page links to another**: through the site's own URL as its API gives
  it (a wiki read through another name or address), over http or https, with or without the default port, by a short
  link (…/x/AbCd), by title in viewpage.action?spaceKey=…&title=…, and in the storage format by address (ri:url) or by
  the page's id (ri:content-entity). A site read as web pages follows its links written another way (http or https,
  capitals, a default port), each page read once.
* A link's full address is said after its words when they do not say it ("the dashboard (https://...)").
* **"Pages" on each document**: every page read (title, address, space, size, links, images), the pages not read and
  why (not readable, no text, too large, docs.skip_titles, read by another document), and the limit of pages reached
  with how many linked pages were left. New addresses read 200 pages at most by default (was 20).

The LLM
* **supagent adapts itself to the LLM it is given**: what the server and the model do is found by a few small calls of
  made-up text (does the model reason first, does a short answer come back empty, does the server take
  reasoning_effort, chat_template_kwargs, tool_choice required and none, how the model writes a name, its context),
  kept for every process (web workers, Celery workers) and applied from their first call; what the answers teach (a
  field refused, a reasoning seen) is kept too. Made by the Test the LLM button (which says what supagent adapts), by
  `superset supagent test-llm`, and by the nightly learning when none is known or it is a week old.
* **Models that always reason (gpt-oss)**: room to reason added to every call, no stop strings, a cut empty answer
  asked again with more room, the harmony format read when a server leaves it in the text, names written with
  non-breaking hyphens or narrow spaces made plain, a closing answer asked with the tools declared and tool_choice
  "none", an output the server could not read retried as a call, not as an outage. New setting
  `llm.reasoning_effort` (empty: the server's default; low, medium, high). New setting `llm.keep_reasoning` (off; not
  measured): a reasoning model's reasoning sent back with its tool calls within one answer, as OpenAI advises for
  gpt-oss.

Learning
* One reading of the documents at a time; a diagram's source is read by the diagram reader only.

0.10.6.1 and 0.10.6.2 are in this release (their sections below).

Upgrade from 0.10.6.2: install the wheel and restart; tables v18 unchanged; two new settings (llm.reasoning_effort,
empty by default; llm.keep_reasoning, off).

## 0.10.6.2 — 2026-10-09

The team's reports of 9 October on 0.10.6.1: a value rejected in To review left the links and the items proposed with
it; the learning proposed values named with long phrases, proposed monitoring tools, infrastructure services and Java
libraries as applications, and linked the subjects to nothing; an Ansible repository that keeps its inventories per
environment (inventory/PRD/hosts, inventory/STG/hosts) had its environments' groups mixed in one.

Not measured again: the agent's answering code is 0.10.6's (a subject's links are said to it, never followed).
Checked before this release: the unit tests (42 new); the Ansible reader on the lab's 12 Ansible repositories, the old
reader against the new (the repositories with one inventory and no environment folder unchanged; the others in
levels such as "infra prod" and "infra staging"); a dry run on a lab map without the LLM: 13 subject links proposed for
4 approved subjects (100 with the first rule, two shared texts: too many, not kept), and the one connector proposed as an
application filed as a component.

To review
* **A rejected value takes its proposals with it**: the links drawn with it, proposed or approved, and the items given
  to it go when a value is rejected, retired or removed; what a person refused about it stays, so that it is not
  proposed again.

The learning's names
* **A learned value is a name**: 30 characters at most (`categories.learned_max_chars`) and 3 words at most
  (`categories.learned_max_words`; a name joined by - _ or . is one word), no sentence (its punctuation, an article
  first, a verb): else it is not proposed. A host's full name over the limit (svc.namespace.svc.cluster.local): its
  first label, the full name kept as another name. Never checked: a value that exists (a person's, the catalog's, one
  approved), the servers' and the groups' names, the values read in the data's fields.
* **What a part is**: a library or a framework the code is built with (log4j, jackson-databind,
  spring-boot-starter-web, lodash, a name ending -lib, -sdk, -common, -utils...) is not proposed; a monitoring tool
  (Prometheus, Grafana, Zabbix, an exporter...), an infrastructure service (DNS, LDAP, a proxy or a load balancer, a
  message broker, a CI server, an application server) or a database server is a component, or goes to a category of
  yours named for them (monitoring, observability, infrastructure, middleware, databases, libraries...). The AI's
  instructions say the same; the code applies it whatever the AI answers.
* **What waits from an older reading is put right** at the next learning: a proposal named with a phrase, or a library,
  withdrawn; a tool proposed as an application moved. A value a person approved, edited or refused is never changed.

Subjects
* **A subject's parts**: an approved part and an approved subject that 3 texts or more are about together (a fifth of
  the texts of one of them at least) are proposed linked, the part "relates to" the subject, with the texts as
  evidence, 10 parts per subject at most (`learn.subject_links`, on). Drawn on the System map once approved; the agent
  is told a part's subjects, and its paths (impact, chains, leads) never go through a subject.

Ansible
* **Inventories per environment**: a repository that keeps its inventories per environment (inventory/<ENV>/hosts,
  inventories/<env>/hosts.yml, <application>/inventory/<env>/hosts, inventory/<env>.ini...) gives each environment a
  level of its own: "orders PRD" holds that environment's groups, "web (orders PRD)", each holding its servers; a
  play's role runs on its group in every environment. A group named like the environment or the application
  (production, orders) is the environment itself. The application's name is the folder above the inventory, else the
  repository's name without its Ansible words (orders-ansible: orders). A repository with one inventory and no
  environment folder keeps its names. An environment named test (inventory/test/hosts) is read like the others, no
  longer as the repository's tests.
* A map that has the old groups: the levels and the groups per environment are proposed in To review, and the old
  group's links may be proposed for removal. Approve the new ones, then remove the old group (approved, the
  environments mixed) from the Categories page: its links go with it, and the servers are drawn under their
  environment (the map draws a server under the first group it was put in).

Upgrade from 0.10.6.1 or 0.10.6: the wheel on every host, restart; nothing to run (tables v18). New settings:
`categories.learned_max_chars` (30), `categories.learned_max_words` (3), `learn.subject_links` (on). INSTALL.txt,
*From 0.10.6.1 to 0.10.6.2*.

## 0.10.6.1 — 2026-10-09

The team's reports of 9 October on 0.10.6: a wiki document failed whole ("…/rest/api/content: HTTP 404: not found, or
not visible to this document's sign-in", 0 pages) when one page it leads to could not be read; the values seeded at the
start (the categories people wrote in the catalog, the ones the learning gave to the data's objects) could not be
removed from the Categories page.

Not measured again: the agent's answering code is 0.10.6's. Checked before this release: the unit tests; the readers
against local servers (a wiki whose child page answers 404, a page in a space the sign-in may not see, a page titled
"deprecated" with a page under it, an empty page with a page under it; a site with a missing page, a deprecated one and
an empty one); the Categories page in a browser (a value removed alone and with the new bulk removal, no page error).

Documents and sites
* **A page that cannot be read is skipped, the others are read**: a page under the document's page, or one its links
  name, that this document's sign-in may not see (404, 403, a login page) or that is not text is skipped and counted
  (the document's "skipped"); the crawl goes on through every other page and its links, down to the document's
  "Pages or files at most". The document's first page must be readable (else its error, as before). A diagram whose
  attachment cannot be read no longer fails the page.
* **Deprecated pages are not read**: a page whose title matches `docs.skip_titles` (default: "deprecated", any case)
  is not read, nor the pages under it and its links (the document's first page always is); empty: every page is read.
* **A page with no text** is not kept, and the pages under it and its links are still followed.

Categories
* **Every value can be removed**: the values seeded at the start had no remove action; every value now has one (Remove
  for a value in use, Reject for a proposed one), except the two aspects (functional, technical). A removed value is
  never seeded or proposed again; adding it by hand brings it back.
* **Remove the values shown**: once the list is filtered (a category, a state or words), an admin removes every value
  it shows at once, asked first with how many.
* The categories themselves (add, rename, remove one of yours) are in "Categories: add, rename or remove one, and
  where their values come from", above the values; a built-in one (subject, application, component) stays, its values
  removed one by one or with the bulk removal.

Upgrade from 0.10.6: the wheel on every host, restart; nothing to run (tables v18). INSTALL.txt, *From 0.10.6 to
0.10.6.1*.

## 0.10.6 — 2026-10-09

The learning proposes what the texts say, To review corrects what it proposes, and the agent's knowledge search follows
the System map. A team collecting and preparing its data with this release reviews fewer proposals that no text
supports, corrects the others in place instead of rejecting them, adds links of any kind from the Categories page, and
asks the agent questions that follow the map's paths. It is the release after 0.10.0: 0.10.4 and 0.10.5, measured and
not released, come with it (below). The agent's checks written after 0.10.0 are still off; what it reads is richer
(the map's paths, what a failure reaches, a metric's usage kept whole) and a reply about its no-tool check keeps the
answer.

Measured before release under a rule written before any result (totals; the held-out sets are never read). The first candidate (4d88f33) failed the learning clause on a fresh held-out corpus: link precision 0.687 against the 0.10.5 candidate's 0.750, beyond the 0.03 allowed. The cause, found on a development corpus written the same way (Promtail's configuration read as Prometheus'), was fixed, and the fixed candidate (ec7447b) was measured again from the start under the same clauses, on another fresh corpus (a port's container-terminal platform: an Ansible repository of 33 files with tests/, molecule/ and examples/ folders, and a wiki of 10 pages; 49 relations): 39 of 49 relations found (0.10.5 candidate: 37, 0.10.0: 30), 106 of 148 links right (0.716; 0.627, 0.509), no value from tests, molecule or examples on the map (5, 5), no more denied statements than the 0.10.5 candidate (2), and a second learning over the approved map removed nothing. Upgrade from 0.10.0 on a copy of a lab: tables unchanged (v18), every setting kept, health 200. The agent (the same model as 0.10.0's measurement): held-out set 69 and 65 answers right of 75, with 4 and 9 wrong answers not marked; main set 150 and 146 of 156, with 5 and 9 (0.10.0: held 73 and 71 with 1 and 3, main 149 and 147 with 5 and 5). The agent's clauses were NOT met (held: 13 wrong answers not marked over its two runs where 9 were allowed; 430 answers right over the four runs where 432 were required; 27 not marked where 20 were allowed): 0.10.6 is released by the owner's decision, for its learning and its knowledge search; on questions it was not developed on, the agent's answers are less reliable than 0.10.0's.

Known gaps: the agent's answers on questions it was not developed on are less reliable than 0.10.0's (above); a question asking what to check about parts whose data the agent cannot see ("search results are stale: what should be checked?") runs a whole investigation (more than 15 minutes on a slow model) before answering from the runbook; the main set's known misses remain (an average taken over the wrong rows, a follow-up keeping the filter of the turn before, "one week earlier" taken as the day before); the LLM's classification and its reading of the interactions were not measured again for this release (0.10.4's figures, below).

What the learning proposes: what the texts say
* **"Part of" from the AI only with its sentence**: the classification's LLM proposed "X belongs to Y" with no text
  saying it (on a lab map 33 parts "belonging to" a web application); now a proposal comes only with a sentence of the
  texts it read that names both and says it ("is part of", "one of", "inside", "consists of"...), quoted with it.
* **Interactions read by the AI**: the quote must name both parts; a subject (a topic) is no end of a link; "the
  server runs postgresql" is turned round (postgresql runs on the server); no flow (calls, reads, sends) to a server.
* **One name, one value**: a value waiting in To review under one category is the value of its name for the next
  batches (no twin proposed in another category); a subject the AI proposed with the name of a part the code or a
  configuration names becomes that part (its items with it); a group named like a subject is "name (group)"; a
  subject a person approved keeps its name.
* **Tests, fixtures and examples are no fact of the map**: a repository's `tests/`, `test/`, `testing/`, `testdata/`,
  `fixtures/`, `molecule/`, `examples/`, `e2e/`, `spec/` stay in the search but give no server, no group and no link
  (`tests/functional/all_daemons/hosts` gave "mon0 part of ceph-monitoring"); a group a real play names that only a
  test inventory holds stays the play's place, none of its test hosts read.
* **Where a part runs ends with its clause**: "the job running on the app group is responsible for reading from the
  DB" runs on the app group, not on the DB's; "reading from", "pushing to" and the other -ing verbs are read.
* **A scrape target that is a service** (a Compose service of another file of the repository) is no host the job's
  part runs on ("prometheus runs on otel").
* **Promtail ships logs**: a configuration with `scrape_configs` was read as Prometheus'; Promtail's (told by its
  positions file or its Loki push URL) is a log shipper's, its jobs (named after the services whose logs it reads)
  no "monitors" link.
* The reading's rules are version 0.10.6: the first reading after the upgrade reads every unit again once (a proposal
  the new rules no longer make is withdrawn).

To review corrects; the Categories page links
* **A proposed link is edited before it is approved**: its kind (belongs to, runs on, connects to, relies on, reads
  from, sends data to, monitors, triggers, is related to), its direction, its short and full explanations;
  *Approve* takes it as corrected.
* **Each warning with its own actions**: a value proposed twice (merge it, or reject the proposed one), a loop (keep
  one direction: the other is rejected), pages shared by two documents (disable one), besides *Set aside*.
* **"+ Link" at the top of the Categories page**, beside "+ Category": two parts found by typing, the kind from a list
  or in one's own words (the words people used before offered too, to edit), what to do when following it, one way or
  both.

The knowledge the agent searches
* **Paths in one call**: `system_links(names, depth=2|3)` gives "leads_to" (what the parts depend on, call, read,
  send to, and further, each step a link, the server at its end) and "led_from" (what leads to them: a failure's
  impact); never a circle.
* **What a server's failure reaches, in an answer's words**: a server or a group named comes with "if_it_fails", at
  any depth: what runs on it, on each of its servers (a group), on its group (it may go on on the group's other
  servers), then what depends on, calls, reads from or sends to those, and further, each with its step. "If db-01 is
  down, which applications stop working?" was answered with what runs on db-01 although the applications depending
  on those were in the paths; with it, the three applications are named. A part that runs on other servers too says
  so ("postgresql (component; also runs on db-02)": it may go on there), the server's own group and its own servers
  left out (they fail with it).
* **A metric's usage kept whole**: the knowledge given with a question shows a window of each piece around the
  question's words; a metric whose labels have long descriptions lost its last lines there ("SQL: a counter: use the
  column rate or increase, never SUM", the catalog's formulas), and "how many requests ended with a 503" was summed
  from the per-second rate. When the window leaves them out, they are given whole and the room is taken from the
  labels' descriptions (the labels and their values kept): on the lab's main suite, 23 metric lines gain the hint.
* **From a category**: `system_links(["applications"])` lists a category's values (80, with the count); the search has
  a piece per category (its count and 30 of its values).
* **A question about the system's build** (its parts, a chain, what depends on what, what a failure reaches, with no
  data word in it) gets the System map's, the documents' and the Context's pieces first, the data's objects after
  them, and no "where the value is" first: on the lab's demonstration map, of 40 such questions' expected names
  78 of 80 are in what the tools give (70 before these changes).
* The reading of the texts for interactions keeps to its time and reads long texts to their end (a long text went on
  at its next window in the next run; it was marked read after its first windows).

The agent
* **A reply to the no-tool check that speaks of the check keeps the answer**: an answer written without a tool is sent
  back once ("if the question really needs no data, give the same answer again"); a reply that spoke of the check
  ("No data query was needed ... provided based on the glossary") replaced the definition the user never saw. The
  answer it was sent on is kept, only when it holds no figure: a made-up number is never brought back.

0.10.5 (measured, not released; its content comes with 0.10.6): its knowledge clauses were met (on its fresh held-out corpus, kn15: 31 of 43 relations found, 99 of 109 links right; a second learning over an approved map removed nothing), and its agent was held: on the held set 68 of 75 twice, with 6 and 4 answers wrong and not marked, above the bar of 5 its rule had set (the agent's code was 0.10.0's; what it reads had changed).

What a team makes, kept
* **No removal for lack of evidence**: values, links, what is inside what and items added by hand are never removed
  nor proposed for removal because the documents, the LLM or the data say nothing of them; only evidence proposes a
  change, with approval: a link a person drew whose other direction the code or a configuration states (quoting the
  file and its line), a sentence that denies a link or puts it in the past (quoted), a text saying a value was retired.
* **Keep is remembered** with its reason, for every proposed removal: the same reason is not proposed again for that
  link; another reason (another sentence, another file) is.
* **A learning again changes nothing by itself**: a learned link a person approved is proposed for removal only once a
  document's text changed after the documents last stated it (`supagent_meta` understand_texts_at, the link's
  seen_at) and its words are gone from every enabled document. New proposals can still come (a name approved since is
  recognised in more sentences), never against what was approved: no link the other way round of an approved one from
  a page's words, no call from what holds data or messages to its clients, no link to a VIP (the service behind it
  gets it), no flow from a server or a group.
* **What is understood of a part added by hand**: its links get the AI's short and long explanations when they have
  none (a person's words kept); the sentences that say what a part is are found whatever its separators. A
  description written by the AI for a part with none (from the sentences that name it, its links and where the data
  has it, shown as *written by the AI* until a person saves one) is OFF (`learn.describe_values`): judged by hand
  against the lines each was given on the lab's demonstration map, 2 of 154 gave a part a role no line states, 1
  said a link the other way round, 7 said nothing of the part; the next release fixes that and measures again.

The documents and the code, read better (the reading's rules versioned: the first reading after the upgrade reads
every unit once)
* **YAML**: a file written as several documents ("---", comments, "---" again) is read; a playbook so written was
  ignored.
* **Ansible**: a play deploying with its own tasks places the services they start; a role carrying a Compose file of
  several services is no part (its files speak for their own tool); a table's "Target Group" column says where a role
  runs (its "all": every server).
* **Addresses**: an environment file is a configuration; an address naming a server or a VIP is the service there its
  line says (scheme, port, key's name); a templated password keeps an address whole; a fully qualified name is the
  inventory's host; an upstream `orders_backend` is orders; what holds a VIP is never behind it.
* **Prometheus**: a job's targets are its targets' list only (no label's value, no template's expression, no commented
  target, no localhost); a scraped part is no host its job runs on; each target quoted on its own line.
* **Pages and diagrams**: a PlantUML box is named by its label's first line, a box holding other boxes stands for the
  one it holds; an arrow with no word from a scraper monitors, from a dashboard reads, from a log shipper sends; a
  table with a holder's column ("Keepalived on") is a VIP table; a server or a group is where parts run, never what a
  page, a row or a flow is about; a server named after its service hides no part's name; "(... on host)" reads the
  hosts in its brackets only; a verb inside a part's name ("photo-store") is no verb; a denial stays in its clause; a
  diagram's box for many ("Services") is no part.

0.10.4 (measured, not released; its content comes with 0.10.6): The learning, on a fresh corpus written for this release by an LLM from a specification the reader's author did not phrase (an Ansible repository of 20 files and a wiki of 10 pages): 29 of its 45 relations found (0.10.0: 23), 83 of 91 links right (0.912; 0.10.0: 58 of 63), no denied or past statement read as a link, every server inside its own group (17 of 17), 2 of its 3 VIPs on the map with the service they front (0.10.0: none). Three earlier held-out sets: right links up on each (4 to 5, 3 to 4, 22 to 24), precision up on each. A question's part names: written with other separators 93 of 93 found (0.10.0: 14), with a one-letter slip 65 of 69 (0.10.0: 0), no part named wrongly (0.10.0: 28), ordinary questions naming a part by accident 4 of 121 (as 0.10.0). A value of the data named in another case or with other separators: 98.3%, 98.3%, 96.7% found (fresh sample). No planted secret stored on nine corpora; the two literal passwords of the fresh corpus stored nowhere. Upgrade from 0.10.0 on a copy of a lab: tables unchanged (v18), every setting kept, the first reading after it reads every unit once. With the LLM on the same fresh corpus (reported, not gated: the categories, what is inside what and the links' explanations are gated only through the map's structure, by rules): every link of the map explained short and long (91 of 91; the 75 "inside" relations are shown as nesting), 6 of the 91 explanations name a third part of the map, each a relation the corpus states (one adds a detail it does not: "point-in-time recovery"); 9 applications, 12 components, in the servers' category the 17 servers, 14 groups, the 3 VIPs and their 3 addresses, 27 values inside another; the LLM's reading of the texts proposes links of which about 4 in 10 are right (12 of 29 here, 8 of 18 on an earlier held-out corpus), in To review only; relations found after the whole chain 30 of 45 (stated in the repository 29 of 39, in the wiki 28 of 41). The agent (its checks written after 0.10.0 off): held-out set 69 and 68 answers right of 75 with 3 and 4 wrong answers not marked; main set 151 and 151 of 156 with 4 and 3; corrections (the held half: 8 cases of a first answer, then a user's correction, true or false): right then right 4, wrong then right 1, wrong twice 1, and right then wrong once, giving in to a false correction where the rule allowed none (the three builds before it: none); so 0.10.4 was not released, by its rule. The learning's figures here are 0.10.4's reader's; 0.10.5's was measured against it on the earlier held-out sets (above).

0.10.4: the documents and the code, read better (the reading's rules versioned: the first reading after the upgrade
reads every unit once)
* **Pages**: a denied or past statement is no link ("never calls", "used to read", "n'utilise plus"); the subject of a
  verb is the part before it, a clause after a colon or a "which" has its own; arrows between parts; a table of hosts
  ("Host | Role | Services"); a route ("through the proxy to the app server"); where a part runs and what it calls,
  writes or reads in French, Spanish, German, Portuguese and Italian; a misspelled part (a letter missing, one too many,
  two swapped); a list item stays one sentence (a page with lists gets new search pieces once, at its next reading).
* **Configuration**: Prometheus' scrape jobs and alertmanagers, Grafana's data sources, the Beats' modules and
  monitors, Monit's checks, Caddy's upstreams, in their own files or in a deployment's variables; a public address is
  its organisation's; `http://${CATALOGUE_HOST}:8080` is the catalogue; an address variable's default in code is a call.
* **Compose and Kubernetes**: a service's build folder and the folders it mounts speak for it; network aliases are its
  other names; extension files and Swarm stacks are read; a workload versioned after its application is that
  application; a templated manifest is read.
* **Ansible**: a role's services are other names of its part; a role making accounts or databases uses that database;
  a role publishing a web site is an application; the files a role copies named after their path are read, never one
  whose name speaks of a secret.
* **VIPs**: an address whose name says vip, a VIP variable, keepalived's `virtual_ipaddress`, a table's VIP column, a
  sentence naming a VIP: on the System map a VIP is an address (the servers' category) linked to the service it fronts,
  with the servers behind it in it; a caller's address on a VIP is a call to its service.
* **A question's part names**: written with other separators ("node exporter", `node_exporter`) or with a one-letter
  slip (6 letters or more, one part only, never a plural), the system around the question starts from that part.
* **What a person made**: never removed nor proposed for removal because the documents, the LLM or the data say
  nothing of it (a text saying a value was retired proposes its retirement, with the sentence); `reset-knowledge
  --categories` keeps the learned values a person's work rests on (a link drawn to one, a value put inside one, an item
  given to one); in 0.10.0 such a link went with its learned end.
* **The agent's checks written after 0.10.0, off** (to turn on after measuring them on your data): an answer that says
  a query ran when none did (`agent.claimed_query_check`), a doubt with nothing new (`agent.bare_doubt_check`), an
  announced step in -ing (`agent.announce_ing`), the limit a System map link names (`agent.link_limit_hint`),
  `check_health`'s brief crossings (`tools.brief_crossings`); 0.10.3's correction checked again on another path
  (`agent.correction_check`). README, *Checks of an answer before it is shown*.

0.10.2: the data and the categories
* **A value of the data found by the search, however it is written**: a question naming a server, a service, a status
  or any value the learning read (up to 1,000 per label or field) gets first which metrics' labels and indices' fields
  hold it, written as the data writes it (its case: a filter needs it), and the category values named so; written in
  another case or with other separators ("web shop", "WEB_SHOP" for "Web-Shop"; up to five words read together, the
  longest match first: a word inside a value is not a value alone); a category value named by one of its other names
  says where it is in the data. These pieces come on top of the documents' pieces, never in their place, and only for
  the databases the user may query (`search.values`, on).
* **Where each part is in the data**: the links panel of a part (Categories page, System map) says, per label or
  field, the value as written there and its metrics or indices, for the databases the user may query.
* **The category a label holds, proposed**: a label or a field holding several values of a category (3 at least and
  a fifth of them, a good part of its own values being the category's), not read for it yet, waits in To review
  (*Where the categories are in the data*); an admin reads the category from it (`categories.fields`: the agent knows
  where the category is in the data, and the next learning proposes the label's other values as values of the
  category) or sets it aside.
* **What could confuse the agent or the search, in To review** (`superset supagent lint`): a value proposed again in
  another category ("X is an application already and is proposed as a subject": merge it in one click, or reject or
  rename it), one name for two things, one thing written two ways in a category ("web-shop" and "Web Shop", "invoice"
  and "invoices": merged in one click, the other writing kept as another name; a value inside or running on another
  is not proposed), the System map in a circle (parts of each other, two parts each running on the other), documents
  holding the same pages (a document whose every page another holds: disable it), a term defined twice differently.
  Each says why and what to do; *Set aside*: not said again.
* **The values' index built in a fraction of a second** on a large dictionary (a label kept once per metric is read
  once: 3,000 metrics with 10 labels, two at the 1,000-value cap, and 300 indices: 0.21 s instead of 7.9 s).

0.10.1: what measuring 0.10.0 showed
* **Three Ansible idioms read**: a play's hosts written with Jinja (a variable from the play, the inventory or a role's
  defaults, its `default('x')`, `groups['x']`), a role kept to one group by its condition (`when: inventory_hostname
  in groups[...]`, `'x' in group_names`), a playbook, an inventory or variables given as a sample to copy
  (`site.yml.sample`, `hosts.example`). Measured against 0.10.0's reader by a rule written first: on held-out classic
  Ansible projects where each role runs 19 of 25 found at 86% right -> 100% right, the repositories' links 18 -> 20 of
  22, nothing lower on two other sets; on a large community project (sample plays, templated hosts) 4 -> 31 of 32.
* **An approval reaches every process's search**: a value or a link of the System map approved, edited or removed
  is in the search before the next question of every server process (a stamp in supagent_meta written after the
  change's commit, read at most every 2 s); in 0.10.0 the chat's answers, which run in the Celery workers, saw it at
  the hourly indexing only (or after `superset supagent index`).
* **Each wiki page read once**: a wiki read to the last page its links lead to, given as one document per space whose
  pages link to each other, had every page read, cut, embedded and understood once per document; a page is now the
  document's with the lowest id that reaches it (a document removed or disabled gives its pages to the next one at
  its next reading). On a development wiki of three spaces: 66 pages read, pieces and units -> 24. The Context's
  wiki pages are made per space whatever document read its pages (they were per document, each listing every page).
* **To review filtered by a word**: a part, a repository, a document (what a proposal names or where it was read);
  the counts are the filter's and *Approve all shown* / *Reject all shown* (values and links) act on what it shows,
  so that what one repository proposed is reviewed at once. The short explanation's hint follows the link's kind.
* **A classification run keeps time for the links**: the items given to the LLM take half the run at most when the
  links are read and explained after them, a quarter of the run is kept for the explanations, the reading has the
  rest (on a big platform the items used the whole run and the explanations were left a minute).

Upgrade from 0.10.0: the wheel on every host, `superset supagent init` once (no table changes: v18), restart; the first
reading after it reads every unit once. From 0.9.6.x: the same, the tables go from v17 to v18. INSTALL.txt,
*From 0.10.0 to 0.10.5* and *From 0.9.6.x to 0.10.5*.

## 0.10.0 — 8 October 2026

The knowledge release: the search finds what the documents, the code, the catalog, the data dictionary and the System
map say, misspelled or not; the documents and the repositories are read for what they state (who calls whom, what
runs where, which database, where the logs go) and proposed for the categories and the System map with their evidence;
the System map, with its links' explanations, is searched like the rest. 0.9.7's checks of the agent's work (never
released) are in it too.

Measured before release on 7 and 8 October 2026 (the same LLM as before, the lab's questions; the held-out sets never looked at while building, totals only): the agent on the held-out questions 73 of 75 and 71 of 75 right in two runs, 1 and 3 wrong without a warning (0.9.6's first held-out run: 70 of 75, 3); on the main suite 149 of 156 and 147 of 156 in two runs, 5 and 5 wrong without a warning (0.9.6: 6 and 6); on a fourth set of harder general questions (development material), one run: 13 of 16 (3 wrong without a warning); the investigation scenarios were not run on this build. The knowledge search on 2,311 public documentation pages, 3,169 held-out queries, with production's embedding model (bge-m3), the right page first / among the ten first: clean questions .667 / .917 (before 0.10: .523 / .843), a word with two typing slips .514 / .820 (.182 / .483), a name with a typo .637 / .868 (.302 / .577), a name with other separators .687 / .918 (.374 / .725), three misspelled words .617 / .928 (.400 / .844). No planted secret kept or searched on eight test corpora (every secret line masked). The upgrade rehearsed on a copy of a lab's database: 0.9.6 to 0.10.0 (tables v17 to v18 in 8 s, every setting kept), back to 0.9.6.9 with and without its init, forward again, the backup restored identical.

Changed after that measurement, in the learning and in the search, not in the agent's code (the agent reads what they
give: the links' explanations through the System map's pieces and its brief, the search's pieces): the explanations of the links (supagent/knowledge/interactions.py: each kind explained as what it is; supagent/cli.py: interactions --explain [--again]), checked on two development corpora, the same links explained by the old and the new prompt and judged by a rule written before reading them: the parts that run on a place right 31 of 31 against about 12 of 31, and 28 of 28 (five short explanations weak) against 21 of 28; the flows no worse, fewer other parts named; --again run with the LLM on a copy, an admin's words kept. The same page read by several documents (supagent/knowledge/search.py, the cap of a search's pieces): no piece shared in the measured environment, so the figures above are unchanged; on a development wiki of three spaces, five searches' distinct pages among the first six 2, 2, 2, 6, 4 -> 6, 6, 6, 6, 6, the page each one is about kept. Unit tests: 1113 passed.

Known gaps, measured on a fresh set read once (six public repositories and a wiki of three spaces never seen before,
totals): the links between parts that the repositories' configuration states are read well (67 of 78 found; 71% of the
links read are right); the relations the pages and the code state, scored one by one, much less (29% found, 42% of
those read right; 13% and 26% with the right kind of link); where each part runs 2 of 12 (8 of them Compose services
deployed by an Ansible play, not read yet); an inventory's hosts in their groups 10 of 11. On classic Ansible projects
never seen before (held-out set, totals): where each role runs 19 of 25 found, 86% of what is read right; the hosts in
their groups 18 of 24, all right. Every proposal waits in To review for a person: review before approving. Not read
yet: a name qualified by its application ("the storage Prometheus") told from a same-named part of another one;
Compose services deployed by an Ansible play; a host named by its IP address in a sentence. To review can be long on a
very large Ansible project. Several documents of one wiki whose pages link to each other each read, cut and embed
every page their links reach (the search gives it once): one document per wiki reads each page once.

Known gaps of the agent, seen while measuring the builds after this one (the same code is in this one): a follow-up answered from the chat's own figures, without a new query, can say that a query was run (once in 156 questions); a reply that disputes an answer ("that's wrong", "are you sure?") has no check of its own: the agent may defend its figure, or change its reading, without a new query; the team's health checks report a breach only when it lasts the check's duration, so a short peak above a limit that a System map link names is not shown (ask for the metric itself over the period).

The knowledge search
* **Misspelled and hard questions**: the three ways of the search (words, near spellings, meaning) fused by their
  scores, and a question written as a sentence fused by ranks, a list of keywords or a name by scores; a word read
  with two typing slips from the documents' own words; the names the documents write found as typed, exactly or
  nearly; a judge before any LLM help: a weak search (a word near the knowledge's words that nothing reads; a
  reranker's low score with `rerank.judge_floor`) written again once by the LLM and both searches fused
  (`search.rewrite` = weak, on; `search.rewrite_seconds`); the questions found well never wait for it.
* **The System map in the search**: each approved value of a category is a piece of its own: its description, its
  other names, the category it is drawn inside, what it is part of and its parts, and every approved link it has,
  both ways, with the link's short and long explanations; written again at the next indexing when a value or a
  link is added, approved, edited or removed (hourly, or at once with `superset supagent index` after a batch of
  approvals). A proposed or rejected one is not searched.
* **A glossary's terms are not capped** (0.9.7, `search.terms_uncapped`): each term and each rule a piece of its own.
* **A page several documents read comes once**: a wiki's spaces whose pages link to each other, each read to the last
  page its links lead to, held every page once per space (a search's first six were two pages three times): its
  sections come once, two pieces of it at most, whatever document read it.
* The knowledge block given with each question keeps its room for the pieces (the words no piece holds are named by
  the search tool only).
* **Secrets masked before anything is kept or searched**, three more formats: a connection string's password with
  any character up to the next `;` (ADO.NET, Npgsql, ODBC), a secret given as the default of an environment lookup
  (`os.environ.get("API_TOKEN", "...")`, getenv, ENV.fetch), and a secret written in a sentence in the usual
  languages ("Mot de passe ... :", "Passwort für ...:", "the API key is ..."); a plain word, a reference or a
  placeholder after the label is not.

The documents and the code
* **A wiki read to the last page its links lead to**, each page with its links, its images' text and its diagrams
  (draw.io, Gliffy, Mermaid, PlantUML read from their source).
* **What the documents and the code state, read without an LLM** (`knowledge.understand`, on): who calls whom (the
  addresses code and configuration reach), the databases written and read, the caches, where the logs go, the
  metrics registered, the indices a shipper writes; code cut at its declarations for the search, each piece saying
  what it is part of (its file, language, repository, service). `superset supagent understand [--propose] [--show]`.
* **Repositories read across their files**: an Ansible project (its inventories, read even without an extension:
  every host in its groups and the groups in theirs; its plays: what runs where; its roles judged a part when they run
  a service or deploy an application, else a base role; its templates naming another group: who reaches whom), a
  Kubernetes repository (a workload's environment and the ConfigMaps it takes), a Docker Compose file (depends_on,
  links, the addresses in a service's environment). What a repository is is said on its Context page ("An Ansible
  project: 2 inventories (12 hosts in 5 groups), 4 playbooks, 9 roles; what it deploys: ...").
* **Proposed with their evidence** for the categories and the System map (`knowledge.propose`, To review), compared
  with what exists: parts as values, servers and their groups (the server category), the links between them; a
  proposal is not withdrawn when a reading suddenly finds less (a document not fetched a moment).
* **Context pages from what the documents and the code state**: a page per part (its other names, its code, what it
  uses and what uses it, its data, the pages about it, the repositories it was read in), per server group, per
  repository and per wiki space.
* **The catalog's guides, notes, rules, definitions and glossaries** read with the documents.
* **Each kind of link explained as what it is**: the short and long explanations the AI writes for a link were asked
  as flows for every kind (0.9.6 too): a part that runs on a server "waited for the health of" the other servers or
  "read its configuration from" the place it runs on. Now a flow says what the first part waits for, reads, sends or
  uses; a part that runs on a place what it is or does there and what to check on that place (health, resources,
  restarts); a monitor what it watches; each link from its own two parts only. `superset supagent interactions
  --explain` writes the missing explanations at once; `--again --kinds runs_on,monitors` writes again those the AI
  wrote alone for those kinds (an admin's words stay, the flows keep theirs), continuing where the last run stopped,
  until it says done.
* The LLM's reading of the pages (`knowledge.understand_llm`) is off by default: measured, it added more wrong links
  than right ones.

The agent
* **The whole picture for a question of how parts are connected** (where something runs, what it calls or uses,
  where its data or logs go, what a failure reaches; also in French): the System map's interactions one step out and
  one further, as an investigation has; a server says what runs on the groups it is part of.
* **An answer the model wrote beside a tool call is not lost**: a last message that only points back to it gets it
  back.
* From 0.9.7: **a value held by another field** (`agent.value_elsewhere`), **a share over an inner join**
  (`agent.share_join_check`), **a follow-up keeps the chat's period** (`agent.period_window_check`), **a LEFT JOIN
  made inner** (`agent.outer_join_check`), **a query shown that was not run** (`agent.shown_sql_check`); the period
  check reads `BETWEEN '<first day>' AND '<last day>'` on a field of days as ending with that day; the examples the LLM
  reads are neutral.

The changes of 0.9.6.1 to 0.9.6.9 are in 0.10.0.

Upgrade from 0.9.6.x: the wheel on every host, `superset supagent init` once (tables v17 to v18), restart. INSTALL.txt,
*From 0.9.6.x to 0.10.0*.

## 0.9.6.9 — 6 October 2026

The System map edited where it is drawn: each change saved at once.

Not measured again: the agent's answering code is 0.9.6's (see 0.9.6). Checked before this release: the unit tests (1012 passed, among them every change of the map through its API, who may and may not make it) and the page in a browser (below).

* **A funnel** on each category's name and each part's box filters the map on it; a second click, no longer.
* **A part's panel** (editors): what it is inside, each with "Take it out"; "Put it inside" another part (found by
  typing), moved (out of the part of that category it was in) or copied (inside both); "Add inside" a new value;
  "Remove this value…" (who may delete). Never inside itself nor inside what is inside it.
* **A category's ⓘ**: add a value, add a subcategory (drawn inside it), choose the category it is drawn inside;
  **+ Category** in the legend makes a category.
* Links were already added, changed and removed in a part's panel ("+ Add a link").

Checked in a browser on a synthetic map (200 servers with their disks, partitions and cpus, applications,
components): the funnels, a server copied inside a second application, a disk added inside a server, a value and a
subcategory added, a category made, a value removed; no page error.

Upgrade from 0.9.6.8: the wheel on every host, restart; nothing to run (tables v17).

## 0.9.6.8 — 6 October 2026

Two corrections of 0.9.6.6 and 0.9.6.7.

Not measured again: the agent's answering code is 0.9.6's (see 0.9.6). Checked before this release: the unit tests (1010 passed) and both commands on a PostgreSQL copy of a lab's database (below).

* `reset-knowledge` takes the Context pages it wipes out of the knowledge store and the vectors too (0.9.6.7 left them
  there until the store's next sync: the search could still give them).
* The three-roles setting is read without touching what Superset's role sync is doing: a first `superset init`, before
  supagent's tables exist, could lose the sync's work with 0.9.6.6 and 0.9.6.7 (`superset supagent init` after it
  repaired it).

Both commands were run on a PostgreSQL copy of a lab's Superset database: `roles --apply` (Admin, Editor and Viewer;
`superset init` made no Alpha nor Gamma again; Editor deletes nothing), `--undo` (every user's roles as before);
`reset-knowledge --yes` (a backup, the learning's values, links and Context pages wiped, a person's values kept),
`restore` (every count as before).

Upgrade from 0.9.6.7: the wheel on every host, restart; nothing to run (tables v17).

## 0.9.6.7 — 6 October 2026

A way to wipe what the learning made and make it again: the Context, the categories' values with their descriptions,
the System map's links with theirs (e.g. once a version reads the documents better).

Not measured again: the agent's answering code is 0.9.6's (see 0.9.6). Checked before this release: the unit tests (1010 passed, among them a wipe that keeps what people made and a restore of its backup that puts every row back).

* `superset supagent reset-knowledge --context --categories --links` says what would go and what stays; nothing is
  changed. Goes: the Context pages the agent wrote, the values read in the data or proposed by the LLM with the items
  they were given, the links neither drawn nor described by a person; every item is classified again. Stays: the
  values a person added (with their descriptions), the links a person drew or described, the Context pages a person
  wrote, the items a person gave a value (`--all`: those go too, and the categories' descriptions). The categories
  themselves (their names, fields, what is inside what) always stay.
* With `--yes`: a backup of the knowledge first (nothing is wiped when it cannot be made, e.g. while a learning
  runs), then the wipe; the command says the next steps (learn, classify, interactions --again, context --build
  --force, then To review) and the way back (`superset supagent restore <backup> --parts categories,context --yes`).

Upgrade from 0.9.6.6: the wheel on every host, restart; nothing to run (tables v17). INSTALL.txt, *From 0.9.6.6 to
0.9.6.7*.

## 0.9.6.6 — 6 October 2026

Three roles only, Admin, Editor and Viewer, when you want it: supagent's AI roles merged into Superset's own.

Not measured again: the agent's answering code is 0.9.6's (see 0.9.6). Checked before this release: the unit tests (1008 passed, among them the roles applied and undone: only Admin, Editor and Viewer, Superset's role sync not making Alpha and Gamma again, a Viewer chatting, every user's roles back), the dry run on a PostgreSQL lab.

* `superset supagent roles` says what would change and what stops it: the roles renamed and removed, the users and
  groups moved; superset_config.py naming Alpha, Gamma or an AI role (`AUTH_USER_REGISTRATION_ROLE`,
  `AUTH_ROLES_MAPPING`, `PUBLIC_ROLE_LIKE`…: it stops until they name Editor, Viewer or Admin); row level security
  filters or dashboards given an AI role.
* `--apply`: Alpha becomes **Editor** and Gamma **Viewer** (the same roles: their users, row level security filters
  and dashboards keep them); AI Admin's users get **Admin**, AI Editor's Editor, AI Viewer's and AI Agent's Viewer;
  the AI roles are removed; a copy of every user's and group's roles is kept.
* From then on `superset init` makes Editor and Viewer where it made Alpha and Gamma: Editor = Alpha and SQL Lab
  without deleting, with the knowledge written (no settings); Viewer = Gamma without anything that changes
  something, with the chat; Admin = everything. `superset supagent grant <user> --role viewer|editor|admin` gives
  them.
* `--undo`: Alpha, Gamma and the AI roles again, every user's and group's roles as they were.
* Nothing changes until `--apply`.

Upgrade from 0.9.6.5: the wheel on every host, restart; nothing to run (tables v17). The steps for the three roles:
INSTALL.txt, *From 0.9.6.5 to 0.9.6.6*.

## 0.9.6.5 — 6 October 2026

The System map in levels: categories drawn inside others, opened and closed with a click; the map filtered on a
part; big categories grouped by what their parts hold.

Not measured again: the agent's answering code is 0.9.6's (see 0.9.6). Checked before this release: the unit tests (1006 passed, among them: with categories inside others, the values, their links and the agent's picture of the system are the same), the page in a browser (below).

* **A category inside another** (Categories → Edit → Inside): a server's disks drawn inside the server, a disk's
  partitions inside the disk, its cpu inside it, as many levels as the categories go. Each value is drawn inside the
  value it is part of (else runs on); the line at the bottom of a box opens or closes what is inside it (this browser
  remembers; a category's ⓘ opens or closes them all). A category named after another (`categories.qualified`) is
  inside it unless you choose otherwise. Never inside itself nor in a loop.
* **A value inside another of its category**: a sub-subject inside the subject it is part of.
* **The map filtered on a part** (the box above the map, or "Filter the map on it" in its panel): the part, what it
  is in, what is inside it every level down, the parts it is linked to; a chip says what the map is filtered on.
* **Big categories grouped by what their parts hold**: servers by the components that run on them ("holding grafana
  + redis · 26 servers"), as the links say (read in the metrics' labels, or drawn by people: "runs on", "hosted on",
  "deployed on"); or by what they belong to (their application), as before. Each viewer chooses in the category's ⓘ.
* Display only: what the agent reads (the values, their links, the system around a question) does not change.
* 0.9.6.4's sentences of the parts: among sentences of the same score, the first shown can differ from 0.9.6.3's
  (the texts are read in the order they were made); the sentences found are the same.

Checked in a browser on a synthetic map of 5,522 parts and 6,812 links (servers, disks, partitions, cpus,
sub-subjects): drawn in about 1 s; three levels opened; the filter on a server; the groups switched; the PNG export.

Upgrade from 0.9.6.4: the wheel on every host, restart; nothing to run (tables v17).

## 0.9.6.4 — 6 October 2026

The System map answers in under a second on a big platform (it could take about 20 seconds).

Not measured again: the agent's answering code is 0.9.6's (see 0.9.6). Checked before this release: the unit tests (1004 passed), the map's data and the page timed on a synthetic map before and after the change (below), the sentences found compared with 0.9.6.3's on random texts.

* **The sentences that explain the parts are read in the background.** For each part with no description, the map
  shows the sentence of a document, a guide or a Context page that says what it is. Its request read every text to
  find them: up to 8 s each time, again in each Superset process, again whenever a text changed, and the parts after
  the first 2,000 waited for a later reading. A job now reads them once for every process (kept in Superset's
  database), when the texts change or when parts are new; the map shows them at its next reading (the first time, a
  few seconds later).
* **What exists now is read once per document**: the map counted each part's items by reading the name of every
  piece of the search (hundreds of thousands with a repository's code); now one row per document, kept 30 s.
* **The page asks again less often when the server is slow**, never while a reading runs.
* An error while reading the admins' list of what investigations still lack no longer breaks the map.

Measured on a synthetic map (4,240 parts, 4,800 links, 50,000 pieces of documents): the map's data in 0.65 s the
first time and 0.26 s after (9.9 s before), the page drawn in 1 s (9.5 s before); with 300,000 pieces, 0.27 s, and
21 s for the reading in the background. The sentences found are the ones 0.9.6.3 found (tested on random texts).

Upgrade from 0.9.6.3: the wheel on every host, restart; nothing to run (tables v17).

## 0.9.6.3 — 6 October 2026

Two more kinds of secret masked in what the documents give, before anything is kept.

Not measured again: the agent's answering code is 0.9.6's (see 0.9.6). Checked before this release: the unit tests (995 passed), the two test corpora of the documents' reading (no planted secret in the stored text nor in the search's pieces).

* **A DSN without a URL scheme**: `user:password@tcp(host:port)/db` (Go's MySQL driver), `user:password@host:port/db`.
* **A key held by a name that says so** (`SIGNING_KEY`, `apiKey`, `RATES_KEY`...) given a literal value.
* An e-mail address, an ssh address, a call (`make_key(x)`) are not taken for secrets.
* A document read before keeps its text until it is read again: read the repositories again (Documents and sites →
  Read again).

Found by a corpus written to test the reading of repositories (a lab's, kept out of the code): two of its four planted
secrets stayed in the stored text with 0.9.6.2; none with 0.9.6.3.

Upgrade from 0.9.6.2: the wheel on every host, restart; nothing to run (tables v17).

## 0.9.6.2 — 6 October 2026

The team's request of 6 October: a Bitbucket repository must connect easily.

Not measured again: the agent's answering code is 0.9.6's (see 0.9.6). Checked before this release: the unit tests (994 passed), the addresses of the five forms (Data Center, a personal repository with a context path and a user, without .git, Cloud with and without a user) read as their repository and signed in to the same site.

* **A repository's clone address** is read as the repository, its default branch: Data Center
  `https://host/scm/KEY/repo.git` (a personal one `~user`), Cloud `https://bitbucket.org/ws/repo.git`, with or
  without a `user@` in it.
* **A big repository's folders are all listed**: the listing grows with the files asked (Cloud lists one folder a
  request).
* Corrections of 0.9.6.1's notes: the secrets written in a file are masked in every file a repository gives (its
  documentation and text files too, not only with "all its code"); and its check at a new commit asked for the three
  files that had changed: two were read and the third, deleted, was removed (not "three changed files read").

Upgrade from 0.9.6.1 (or 0.9.6): the wheel on every host, restart; nothing to run (tables v17). INSTALL.txt, *From
0.9.6.1 to 0.9.6.2*.

## 0.9.6.1 — 6 October 2026

The team's reports of 6 October on 0.9.6: Context pages that stopped in the middle of a sentence and did not go on,
no way to reject a new Context page, a wiki not read because of its certificate, a Bitbucket repository's code not
read.

Not measured again: the agent's answering code is 0.9.6's, measured before its release (see 0.9.6). Checked before this release: the unit tests (989 passed); the Context pages built read-only from a lab database; the documents' readers against local servers (a site whose certificate no system CA trusts: refused with how to read it, then read with its CA file, then read without the check; a Bitbucket repository read in full, then at the same commit with nothing read, then at a new commit with only its three changed files read and a deleted one removed).

The Context
* **Pages complete**: a description was cut at 200 characters, in the middle of a sentence ("... and a"): whole
  sentences now. A data source's page gives its main indices' documents and time range, and the fields (or labels)
  of its first three main indices or metrics, the described ones first (`context.fields_shown`, 30).
* **AI-written pages**: 3,000 tokens a page; an answer cut by that limit is asked to go on (twice at most); a
  reasoning cut before its end is never kept as the page; still cut, the page says where it stops and is written
  again at the next build.
* **The build goes on**: one page whose LLM call fails (an empty answer, a timeout, a prompt too long) no longer
  stops the build: the other pages are written, the search is updated, the run says "partial" with the pages not
  written.
* **Reject a new page** (To review): shown to nobody and not searched, proposed again only when its sources change;
  a change kept as it is is no longer proposed again with the same sources.

Documents and sites
* **The site's certificate**: checked (as before), checked with a CA file (the document's, or `docs.ca_bundle`:
  the company's root CA), or not checked (the document's choice, or `docs.verify_tls`); a site whose certificate
  is not trusted says so, with these ways to read it.
* **A Bitbucket repository's code** (*A repository: read*: all its code too): the source code of every common
  language, build and deployment files, 5,000 files at most a document; never the files that hold keys (`.env`,
  `*.pem`, `*.key`...) nor the vendored and built ones (`node_modules`, `dist`, `*.min.js`, lock files); the
  secrets written in the code (a password, token or key given a value, a URL's password, a private key) masked.
* **Read again only as far as it changed**: the branch's last commit is kept with each file; the same commit,
  nothing is read; another commit, only the files changed between the two.
* **The search**: a document's pieces are named after their page: a changed page makes again its pieces only (at
  the first index after the upgrade, the pieces of the documents read from an address are made again once).

Upgrade from 0.9.6: the wheel on every host, restart; nothing to run (tables v17). INSTALL.txt, *From 0.9.6 to
0.9.6.1*.

## 0.9.6 — 6 October 2026

The team's requests of 5 October: roles and teams, the System map's links and inventory, a search that reads
misspelled words and large documentation, the Context validated by people, and an agent that does not repeat a
failing call and keeps to a hard limit of calls.

Measured before release on 6 October 2026 (the same LLM as before, the lab's held-out questions, never looked at while building): this version's first held-out run, 70 of 75 right, 3 wrong without a warning, no error (0.9.4: 69 and 69 right, 5 and 3 wrong without a warning); the smoke test 5 of 5. A first build of 0.9.6 with the question's reading on scored 63 of 75 (8 wrong without a warning) on the same held-out questions; on the main suite its answers showed that the reading misled follow-ups, so the reading is off by default and that build was not released. This version was chosen after that held-out result was seen. The full measurement (two runs of each suite, two investigation runs of each version, against 0.9.4) is still running: its result comes with the next release.

Roles and teams
* **Three roles** made by `superset supagent init`: AI Admin (everything), AI Editor (charts, dashboards, datasets
  explored, SQL Lab, the knowledge written; no settings, no deletion), AI Viewer (reads and chats; their data: none
  given by init, `--viewer-data all` or per team). The role AI Agent of earlier versions is kept as it was.
  `superset supagent grant <user> --role viewer|editor|admin`.
* **Teams are Superset's groups**: a note or a memory can be for a group (its members only); the search finds a
  group's notes for its members only.

The System map
* **One kind of relation, the link**: what it is (its description), what it does (what to do when following it), its
  way or both ways, several between two parts; "part of" became links ("belongs to") at the upgrade (tables v17). A
  part's links on the map and in Categories → Links…; an AI Editor proposes a removal, an AI Admin removes or keeps
  it; the learning proposes removing a link whose sentence or text is gone, or that the data no longer shows.
* **Links read from the data**: the values two category labels of a metric's series carry together (a component
  and its server, a server and its tenant) are linked at once; an index's are proposed. A category can be named
  after the part it belongs to (`categories.qualified`: "srv-1 /dev/sda1").
* **Hundreds of parts**: a big category shows its parts by what they belong to (servers under their application),
  each group opened with a click; long lists paged (a 718-part lab map: 7,969 drawing elements to 2,827).

The knowledge search
* **A misspelled word is read as the knowledge spells it** (a letter missing, doubled, swapped, a key next to it, a
  space inside, two words run together), said in the chat's step, the search box and the agent's background.
* **Documents cut at their sections** (Markdown, web and Confluence headings), titled with their headings; two pieces
  of a page at most; the agent reads the part of a piece its words are in.
* Measured on 2,311 public documentation pages: the right page among the ten first 81 → 90 out of 100 (words), 87 →
  93 (with a small embedding model); with one word misspelled 39-47 → 80-86.

The Context
* **A change is validated by a person**: the page shown stays until approved; a newer change replaces the one not
  reviewed yet, with what it no longer says listed; the old and the new version side by side in red and green; Edit
  before approving.
* **The Context as a book**: parts, numbered chapters, a summary, the related pages of each page; PDF and Word.

The agent
* **The request read first, off by default** (`agent.read_question`): the question written again as one precise
  request in the team's names (shown as "Understood as"; an LLM call of its own, at the same time as the routing
  call), used to find the earlier requests like it; with it, a general question (a script, a definition) is answered
  without the platform's data. Measured before the release, the reading misled follow-ups ("that" taken for the
  last figure, "the same weekday a week earlier" read with the names of unrelated charts): it stays a setting until
  it does not.
* **No repeated failing call**: the same call failing the same way is not run a third time; a column name not found
  gets the closest ones.
* **A hard cap of tool calls** per question (`agent.max_steps`, `agent.max_steps_big` for big work), said to the
  agent as the last calls come.
* **A Helpful answer is kept as a summary** the agent writes of the whole discussion (a title, a description, the
  steps, the checks), corrected by a person.
* One figure of a period is computed by the database, not added up from its hours.
* **A part made of other parts is checked with them** in an investigation (`agent.with_parts`): a pool's health checks
  and records include its servers', each breach found that way saying through which part.

The chat
* Wide tables fit (no word broken letter by letter; they scroll in their own box); the question box is resized from
  its top edge; the dark mode follows Superset's (black background).

## 0.9.5 — not released on its own (its changes are in 0.9.6)

Observability: logs of several shippers, traces, data streams and the metrics of many exporters, learned and read
without being told where things are; and the general fixes the observability probes and a third general probe found.

Measured on 6 October 2026 against 0.9.4 (two runs of each suite, the same LLM): held-out questions right in both runs 69 of 75 (0.9.4: 65), wrong without a warning 3 (0.9.4: 8); the main suite 144 of 156 right in both runs (142); the held-out investigation days 475 points (400); the investigations of the dev and test days 1,695 points against 0.9.4's 1,805, in one run of each. Its rule asked for no loss on any of the five, so 0.9.5 was not released on its own. Two more runs of the three investigations that lost most then gave both versions the same totals (205 and 245 points each): the drop was within the run-to-run spread of single runs, and 0.9.6's rule compares two runs of each version. 0.9.6 carries 0.9.5's changes and was measured with them.

What the learning finds in the data (no LLM; each step can be turned off in the settings)
* **The kind of each index**, from its fields alone: logs and their shipper (Fluent Bit's Kubernetes filter,
  Logstash / Elastic Common Schema, the OpenTelemetry Collector, other logs with a line and a level), spans of traces
  (Jaeger, OpenTelemetry: durations and their units, the parent span, the service a call goes to, errors), Kubernetes
  events, alerts, an inventory, metrics stored as documents (OpenTelemetry data points, Metricbeat). describe_data says
  where each thing is (the line, its level, the service, the pod, the node), how a trace is counted, and that a level
  may only be in the line's text; a table of business data gets nothing.
* **Data streams and rollover aliases** (`learn.one_table_each`): a family of rolled-over indices and an alias on all
  of them, an alias and its index, are one table, learned once; an alias on only part of a family (a write alias on the
  newest index) is told as a part of that table, never as a table of its own; a data stream is said to be one, with its
  hidden backing indices and the generations retention deleted. The exact documents and time range of every table
  (the profile's sample stopped at the first documents of each shard).
* **What is usual**: each service's usual day from the spans (spans a day, average and 95th percentile duration,
  errors, busiest hours) and from its latency histograms (median, 95th percentile, requests a day); the patterns its
  logs write every day. All labelled as a usual, never as a figure of a day asked.
* **The same events shipped twice** (the OpenTelemetry SDK and the container's stdout) found by sampling lines, said
  with both tables: never add the two.
* **One thing, several names**: the names an inventory gives as one thing, and the names of one service in two
  sources found by the pods or hosts they own (a sidecar in every pod, or two services on one host, never merged).
* **The system map from the data**: the calls the span tables show.
* **Metric types from the samples** when no metadata gives them: a count without "_total" that only increases, a
  "_count" that is a level; a Prometheus `instance` label written host:port related to the host fields of the logs.

What the agent does with it
* **compare_logs** reads a log table by its kind (its line, its level, or the level written in the line), accepts a
  family of daily indices as a table, and compares with the one earlier day left when retention kept no more.
* **system_links and records_about** also read what an inventory says the parts stand on (their nodes, a rack, a
  switch port): the change or the alert behind a failure below the services; the record tables' fields that name a
  part are searched.
* **list_alerts** also tells the alerts recorded in the data (an Alertmanager archive) that are still firing.
* Checks sent back once: a suspected cause confirmed on its timing alone ("was it the deployment?"); "what changed?"
  answered without the change records found; "the team" answered for all teams together; a question asked back before
  looking at a part the map knows; a follow-up reading every day while the chat asked about a period; SUM or AVG of a
  metric that only increases. "Failed" supports a status-code threshold and an error flag. "Last weekend" is a period.
  A summary asked at the end of a chat is not a new investigation. The work said aloud before a question asked back is
  not shown.
* describe_data matches a topic with the kind of each table; values shared with another database are told as values
  to match, not a join; `learn.classify_per_run = 0` gives no item to the LLM.

## 0.9.4 — 2026-10-04

Two candidates in one release: 0.9.3 (investigations that follow the inputs of late rows, long work that keeps its
results, answers given again or claimed and not done sent back) was measured and NOT released (its held-out
questions below 0.9.2's: right in both runs 60 of 75 against 65); 0.9.4 adds to it the general fixes of 21 failure
classes, found by tracing the misses of two probes written for the purpose (dev4, dev5: general failure
scenarios) and of the earlier measurements to their causes, each replayed on every stored query before it was kept.

Measured on 2026-10-04 with the frozen question sets and the model of 0.9.2's measurement:

* **Held-out questions** (75, sealed: never used to shape a change, opened only after the code was frozen): 0.9.4's
  first run **69 right**, 1 wrong but marked as unsure, **5 wrong without a mark**; 0.9.2's two runs: 69 and 65
  right, 5 and 9 wrong without a mark. The bar of this release was written before that run: at least 67 right and
  at most 7 wrong without a mark (0.9.2's mean per run). The rest of the measurement (the second held-out run, the
  main set of 156 questions twice, the 25 investigation scenarios) is still running; its results come with the next
  release notes.
* **0.9.3 was measured on all of them and not released**: held-out questions right in both runs 60 of 75 (0.9.2: 65),
  wrong without a mark in either run 12 (0.9.2: 9), main set right in both runs 141 of 156 (0.9.2: 142), although
  its investigations scored higher (1,875 points against 1,755 on the dev and test scenarios, 415 against 390 on the
  held-out ones).
* **Two probes of general failure scenarios** written for this release (62 and 27 questions; in-sample: their misses
  were traced to find the fixes below): 0.9.4 59/62 (twice) and 25/27, 0.9.3 56/62 and 22/27. They ran 0.9.4 before
  its last change (a count said in words supports its condition), which was replayed instead on the 4,765 stored
  queries: 9 conditions no longer flagged, none newly flagged.

Investigations
* **Rows late before they were ready get their inputs** (`agent.inputs_walk`, on): when `compare_groups` finds the
  rows late at a stage before they could run (waiting for their inputs, not for a slot), the inputs of the parts in
  its scope, two steps up the System map (what they depend on, read from, receive data from), come with its result.
* **And what those inputs' logs say** (`agent.inputs_logs`, on): the system calls `compare_logs` itself on the inputs'
  log table over the comparison's window, first where the change is concentrated (the pool the rows waited on), then
  everywhere, at most three calls: a new pattern ("<name> still waiting for its inputs after # min: <feed>",
  "commit to <database> took # s", "slow I/O on <share>") comes with the inputs; nothing new, one short line. On the
  stored scenarios of the simulated platform it brings the cause's own lines in three of the six where it fires and
  stays quiet in the others.
* **A pool's capacity blamed for rows that were not ready** is sent back once to follow their inputs (a pool cannot
  hold rows that are not ready).
* **`records_about`**: the changes, releases, restarts, alerts and incidents recorded on the parts an answer blames,
  over the days before the effect (every record table of the data dictionary, by its keyword fields and its text):
  the record behind the cause, not only the applications asked about.
* **The calendar of the days looked at** (`agent.calendar_facts`, on): the third Friday, the last business day of the
  month or quarter... when the team's knowledge literally speaks of such a day, comes with an investigation, with the
  effect the team documented.
* **Logs read everywhere while the change is in one place** (one pool) are read again there, once.
* **A comparison's result keeps 12,000 characters** (its findings, its stages, the rows outside its scope), and the
  system's notes after it reach the model whole (the result cut to make room, not the notes).
* **The calls of an investigation go to the work**: a turn that only keeps the work plan does not count against the
  calls (six at most); when the calls run out before the answer, the answer is what the plan's notes say was found,
  and what was not checked, rather than nothing; "the last calls" is said once.
* **Past its time** (`agent.answer_seconds`, 1,500 s), an answer answers with what it found: two more calls at most,
  the checks that would send it back mark it instead, and the work plan's notes make the answer if the model writes
  nothing.
* **Long work shortened early** (`agent.compact_at`, 24,000 prompt tokens, then half as many again): the older tool
  results are cut to their first lines with the work plan given again, long before the context is full (models read
  long contexts worse well before their limit).
* `agent.ledger_investigations` (on): with it off, investigations run without the work plan (a comparison of the two
  on the 20 incidents decides the default of the next version).

Answers (0.9.3)
* **An answer given again for a new question** (the previous figure repeated word for word, no tool) is sent back
  with a query made compulsory; so is a follow-up that asks for a new value and is answered with figures and no
  query.
* **"And its average latency, in seconds?"** after "which error code came up most often?" is a new question about
  that subject (its, their, son, sa, leur...), not the previous question again; when both readings are possible the
  answer gives the figure for both.
* **"And the longest one?"** keeps the unit the question before asked (minutes, not hours).
* **An action said done with no tool doing it** ("the chart is saved", "added to the dashboard", "the query is
  saved") is sent back to be done, not only marked.
* **osagg's refusal of a LEFT JOIN condition that keeps the empty rows** comes with a hint that writes the join (an
  inner join on the key, the right table's condition in WHERE, one aggregating query; never a hand-made list of keys).
* **"What share of those sales was refunded?"** with the part and the whole read from two tables apart is sent back
  once to count the part within those rows.
* **A SUM, AVG or COUNT over a join that repeats the rows** (the other table has several rows for the key) is sent
  back before it runs (`agent.join_check`, on; one probe query per table and key, kept 10 minutes).

Dates and periods
* **A field that holds days is shown and compared as dates.** Its learned range was shown at 02:00 (midnight UTC in
  Paris time) while osagg (0.2.10+) compares such a field as dates: answers copied the 02:00 onto their bounds and
  moved the period by a day (the 1st of the month left out; the 23rd read for the 22nd). Shown as dates now, a bound
  with a time of day on such a field is sent back once, and a right equality with a date is no longer refused.
* **BETWEEN or <= at the next midnight** on a field of days (which takes in that whole day) is sent back.
* **"last Monday", "on Monday", "lundi dernier"** name the most recent such day; the period check holds the query to
  it (a model counted a Tuesday).
* **A question about the future** answered with past figures says so first (sent back once, then marked).
* **A sum of nothing for a period before (or after) the data** says that the data does not cover it, rather than 0,
  also on a second date field of the index.
* **An open question** (why, is it usual) may compare its day with the days around it; for a count of that day a
  window of several days is refused and said so.

Queries
* **a OR b AND c** in a WHERE (AND binds first: the team's conditions on one branch only) is sent back before it runs.
* **A value the field never holds** (express as a value of the channel field) is sent back before it runs, with the
  field's values and the field that holds it (small vocabularies only; not in investigations, where looking a host
  up and finding nothing is an answer).
* **An average per day computed over the records** is sent back with both readings.
* **A column named for one extreme computed with the other** (MAX(...) AS min_...) is sent back.
* **A count said in words** ("more than one order", "at least twice") supports its condition: the check of
  conditions nobody asked for no longer sends back HAVING COUNT(*) > 1 for "more than one".

Follow-ups and grounding
* **A follow-up that keeps the previous period keeps the previous question's other conditions.**
* **A follow-up about a field the previous queries never read** gets a compulsory query.
* **"The ratio of the first to the second", "the former", "both of them"** refer to the answers before.
* **A value the question leaves out** ("cancelled trades left out") is met by any condition on its field.
* **The check of conditions nobody asked for** reads durations in words (an hour = 3,600 s), the ranks an inner
  query computes, and French words for a flag; a memory that applies "when the user says X" is no support without X.
* **A question back about which data to use**, when the value named is in one of them only, is sent back.

Actions
* **A chart is saved with the name the request gave**; "the chart has been renamed" or "the chart is now a pie
  chart" with no call is a claimed change (sent back to be done).

Pages
* **The top bar shows the supagent version.**

From 0.9.2: `pip install` on every host and restart (no schema change).

## 0.9.2 — 4 Oct 2026

Reliability: the answers were measured three times over (the 156 questions of the end-to-end suite, a held-out set
of 75 new questions written before any change, the investigation suite with 5 held-out scenarios), every miss
sorted by its cause, and each cause answered by a general mechanism, tested on the stored runs before an LLM run.

Measured against 0.9.1, two runs each on the same LLM server, by a rule fixed before the runs:
* the 75 held-out questions (written before any change, never studied one by one): right in both runs 65 (86.7%)
  against 56 (74.7%); wrong without a mark in at least one run 9 against 18;
* the 156 questions of the end-to-end suite: right in both runs 142 (91.0%) against 133 (85.3%); in-sample (the
  fixes come from that suite's misses), so the held-out figures are the ones that say whether they generalise;
* investigations (20 simulated incidents): the same points (1,755 each), one more solved (15 against 14); the 5
  held-out incidents 78 points against 65; about twice as long (the work plan's calls: see 0.9.3).

* **The work plan of a big request** (`agent.ledger`, on): an investigation, a question of many parts, several
  charts or a long request gets a plan the system keeps: the agent writes its tasks (`work_plan`), the system
  attaches what each tool returned to the task in progress, gives the plan back when the conversation is shortened
  and with the last calls, seeds an investigation's steps and one task per finding of `compare_groups`, and sends
  back once the tasks left, the findings the answer does not explain and the open step "what changed behind the
  cause". The chat shows it as a checklist; "continue" takes up the tasks left.
* **No invented names, times or figures**: a follow-up restating the chat without a query may not present names or
  times the previous answer does not hold; an answer that still gives figures, names or times no tool returned, or a
  query written and not run, is sent back once with a tool call made compulsory (`agent.force_tool`, on; the server
  must accept `tool_choice` "required"); a query written and not run is never an answer, even without figures.
* **Asked back, not guessed** (`agent.ask_unclear`, on): one thing named that several values match ("the options
  book"), or something never said at the start of a conversation ("the late ones"): one short question naming the
  candidates. Never for a name before a noun ("the <APP> jobs"), a noun before a noun ("the most job failures"), a
  value already said of any field the noun names, words that together name one value, or a day said elsewhere in the
  message (a first version asked back on three questions it should answer; on every stored message it now asks only
  where it should).
* **A follow-up's subject**: "how many trades of that desk were cancelled" keeps only the desk's conditions (the
  check of 0.8 added back the narrower ones of the previous answer and turned right counts into wrong ones), also
  when the previous answer only selected the desk ("which desk does the first one work on?").
* **A follow-up that names a value no query used runs its own query**: "And the flash PnL?" after the official one
  was answered from the chat, the official figure given as the flash one; a word of the follow-up that is a value of
  a field of the tables just read, used by none of the previous queries, question or answer, takes the restating
  exemption away (a tool call compulsory after the answer is sent back).
* **The period check sends fewer right queries back** (it dates from 0.7): a JOIN with the period on one of its
  tables passes without it on the others (the join keeps their rows of those orders); for a table whose time the
  words do not name, another date of the same event (ORDER_DATE for ORDER_TIME), or the date the answer it follows
  put the period on, counts; "that day" names its event's time; a time field that only says when the record was
  indexed (@timestamp) takes any of the table's own dates. On 7,091 stored queries, 113 refusals fewer, each of them
  on the main suite a false one; 16 of the 38 refusals of the stored investigations go.
* **A term defined as a relation between rows** ("the refunds of those orders"), said in the question and computed
  from the tables apart (no JOIN, no key IN (SELECT ...)): sent back once to link them on their key, by code
  (`agent.definition_links`, on).
* **Metrics**: "were there any restarts that day?" is a count of events, not of samples (the samples check knew
  only "how many"); a metrics query with no time condition that finds nothing says that it read only the backend's
  default window (the last 24 h) and gives the data's range, so that no "no data" comes from it.
* **The work plan keeps one task per step**: a step of the investigation plan rewritten in the model's words (its
  own details, no number) is that step (on a slow server the duplicates had a third of the calls go to the plan).
* **What a query shows by its own text**: two columns computing the same aggregate under different names are sent
  back before the query runs; a time of day read from hour buckets is sent back.
* **Saved charts**: "make it a pie chart" saves the change (Superset's `update_chart` writes an unsaved preview by
  default); a preview is never called a change.
* Dates and times given with a question are no figures (a made-up 43 passed at 10:43); what the model says about a
  check before its corrected answer is cut; a context too long no longer turns the request's template field off.
* `agent.definition_check` (a test, off): a term the glossary defines, computed another way, sent back once. On 202
  stored answers it flags 16 of 33 wrong ones but also 55 of 169 right ones: off.

From 0.9.1: `pip install` on every host and restart (no schema change).

## 0.9.1 — 3 Oct 2026

* **The interactions the logs show keep to their time, query by query** (`learn.interactions_logs_seconds`, 120): the
  step sends up to about 900 small queries per log table (an hourly sample of 14 days, then the patterns that
  state an interaction searched by a piece of their text); the time was only checked between two tables, so one
  table of a big or shared cluster could run every one of its queries. It is now checked before each query: the
  queries left are not sent, what was read is used, and the step's result says so with the number of queries sent
  (the simulated platform's log table: 729 queries for 14 days, the 18 dependencies between its applications found,
  none wrong; not timed on a large index). On a big or shared cluster, lower the time or switch the step off
  (`learn.interactions_logs`).
* **`compare_logs` counts line by line within its time, query by query** (40 s): the budget was checked between two
  patterns, each of a dozen queries.

Neither path is exercised by the end-to-end suite nor by the investigation suite: unit tests only (a budget that
runs out before the first query, and in the middle of a table).
From 0.9.0: `pip install` on every host and restart (no schema change).

## 0.9.0 — 3 Oct 2026

Investigations: a question that asks what is wrong and why ("today the night batch of the billing applications is
far behind, the runs take longer than usual: why?") is answered by finding what is really off, where, what that
depends on and what changed, and by checking the cause before naming it: the tables compared with their usual in
one call (`compare_groups`), the logs too (`compare_logs`: what they say that they do not usually), the System map
followed with each interaction explained (what to do when following it), the cause checked against the same rows
and the same time. See *Investigations* in the README.

* **The system around the question** is given with it, built without the LLM from the team's categories, the
  interactions of the System map and the catalog: the parts the question names, what each consists of, what they
  depend on, run on, read from, send data to and call (one step further for what they wait for), where each kind
  of part is in the data (the fields and metric labels of its category), how the tables join, which field holds
  the usual value of a measure, the health checks. A plain question that names a family gets what the family
  consists of (its applications), so that it is counted on the right values.
* **`compare_groups`** (new tool): what is unusual in a table, and where. One call compares **every measure** of
  the table over the question's scope with the same time of the 8 previous days that have data, in total and value
  by value for each field of few values (the ones asked, then the table's others): the rows, each duration against
  the field that holds its usual, each numeric field; for a business date, **the stages of its rows** (the table's
  time fields in their order: how many had reached each by that time of day, how long after the one before, how
  many were waiting and since when), the first stage clearly off said first; for each measure that is off, the
  field whose values hold most of the change on the fewest rows; and **the latest records of the related tables**
  (the catalog's joins: the changes of that application, the alerts of those servers; else the records that
  mention the value). Noise is kept out (small counts, averages over two rows, a status, a field the runs not
  started do not have yet); a new version is read against the history of the one it replaces. A business-date
  label of the scope (or the date itself) is read for each earlier day as that day's own business date, a weekend
  once. One measure can still be asked alone.
* **The days your team compares with** (`agent.compare_against`: yesterday, 1 week ago, 4 weeks ago; change them
  in the settings: N days, weeks or months ago, 1 year ago): `compare_groups` gives each figure that stands out
  on those days, says when a figure is as usual against the last days but far from an older reference day (a
  change older than a week: where, and since which day to look), and compares in full with the days a question
  names (`against`: "compared with three months ago"); `compare_to_usual` gives each series on them. Weeks and
  months are the same weekday; on a Monday, yesterday is the Friday. A figure far from the last days and the
  same as on the same weekday of the earlier weeks is said to be what that weekday is; and what stands out says
  since when it has been off (the days before that were already so, or new on this day).
* **`compare_groups` follows a lead once by itself**: when the rows wait at a stage on one value of a field (the
  runs of one pool waiting for a slot, the orders of one country not shipped), the same call says **who else is
  there** (`outside_the_scope`: the rows outside the question's scope that share that value during the window,
  against the earlier days and by the scope's own fields: more than usual, and whose) and makes **the same
  comparison over every row that has this value** (`the_rows_there`: what holds it, since when, the related
  records). `agent.compare_follow` (on). A stage that is off on its own after the first late one (the rows take
  longer once started) is said separately: a late start does not explain a longer run.
* **`compare_groups` on any table**: nothing in it is about one kind of system (a table, its time fields, its
  numeric fields, its fields of few values, the catalog's joins): orders or tickets are compared like runs.
  One call costs about a hundred small aggregations (about sixty more when it follows a lead), three at a time
  (`agent.compare_threads`), and stops reading fields after `agent.compare_seconds` (45). A scope written with a
  time (the rows since 01:00 today) moves with each earlier day; `a OR b AND c` is read with the alternatives of
  one field together; a condition that holds only while a row is in progress (a status) is left out and said; a
  reference day the data does not reach is said as such, with no figure of that day; when nothing stands out the
  result says to answer that.
* **What the waiting rows wait on is looked for outside the question's own fields**: rows that wait before their
  last stage (for a slot, a token) and stand out both on the application the question asked about and on a pool
  are followed on the pool (who else holds it), not on the application (outside the scope on it are only its other
  rows: a test campaign holding the production pool was never looked at).
* **The calls of an answer are kept for what is not yet known**: the same query once per day is sent back at the
  third (one query grouped by day, or `compare_groups`), and eight tool calls at most are run from one message.
* **A business date is the one of the day asked about**: `compare_groups` on a past day's batch (a window that
  ended days ago, the scope's label D-1) reads the label as of that day, and each earlier day's own from there.
  A time field given with the call that the connector computes from the business date is not taken for the time
  of the rows (the table's own is used, and said).
* **A column the connector computes is described by the connector**, never by the LLM: a business-date label
  that the LLM, shown a column with no value of its own, had described as "the status of a run" made the agent
  filter the label on states. The descriptions the LLM wrote of such columns are replaced at the next learning
  run (the ones an admin verified stay).
* **Every interaction of the System map explained, twice**: a short explanation (a few words, shown when the line is
  clicked: the map draws no text on its lines any more) and a long one, what to do when an investigation follows
  it (what to check on the other part, what a problem there does here). The LLM writes both with the interactions
  it reads in the texts (the sentence becomes their evidence) and, in the classification's new step *interactions
  explained*, for the others (an admin's, the older ones) from the two parts, the sentence and the Context: only
  what is empty, never over an admin. A click on a line (or its name in a part's panel) opens its panel; admins
  correct both there, in the new-interaction form and in To review. The agent gets the short ones with the system
  around a question, the long ones of the question's parts too, both from `system_links`. Schema 15 (`superset
  supagent init`): the links' long explanation, evidence and author; a sentence kept as an older link's note
  becomes its evidence.
* **Interactions the logs show** (`learn.interactions_logs`, on; no LLM): with the classification, the recent lines
  of each log table are read for the interactions they state ("still waiting for its inputs: A, B", "request to
  X", "commit to Y"): the part a line comes from (its application) tied to the parts it names, the kind read in its
  words; a pair seen on 5 lines and 2 days waits in To review with its evidence (lines, days, an example). A kind
  the map already has ties only the categories it ties there. On a simulated platform, from 14 days of its logs:
  the 18 real dependencies between its applications found, none wrong.
* **The classification right after the Context** (`context.classify_after`, on): each Context build (nightly, from
  the page or `superset supagent context --build`; `--no-classify` to skip) is followed by the classification,
  which reads what the Context wrote with the documents, the metrics and the data; the nightly learning leaves the
  categories to it unless a Context was already built that day.
* **`compare_logs`** (new tool): **what do the logs say that they do not usually?** The lines of a log table
  (application logs, batch logs, events: any table with a time field and a text field) grouped into patterns (the
  numbers, times, ids, names and quoted values left out; a list of names is one name), each counted against the
  same window of the 8 earlier days that have data: the **new** ones (2 lines for an error, 5 for a warning), the
  ones **far above usual**, the **rare** ones (there on fewer than half the earlier days, with the days they were
  there), the ones as frequent as usual **whose numbers are far from their usual** (each number by its place,
  named by the words around it: the same slow write, 40 s tonight against 8 s), what is **gone**, and what comes
  **every day** (no finding). Where the lines come from (the fields of few values; the names they hold, written
  back in the pattern when nearly all hold one), when, an example; the errors first, then the most lines. The
  patterns said are counted line by line in the database, with their first and last line and their places
  counted by field, so that a burst at the end of the window leans nothing; a big table stops counting after 40 s
  and says so. Scope and reference days as for `compare_groups`. The picture of a question names the log tables of
  its parts (*Their logs*), and the investigation steps read the logs of the parts that look wrong.
* **`system_links`** (new tool): what the System map says of any part: what it is part of and consists of, its
  interactions both ways, where its kind is in the data.
* **Five steps** for an investigation (the facts in one call; the reading of the stages: released late, waiting
  for a slot or running longer; why; the check of the cause; the answer with what was ruled out and what could
  not be checked) and **twice the calls** of an answer.
* **What an answer blames is checked**: a part of the system given as the cause must be tied to the question's
  parts by the System map (two steps) or by a result of the answer's own queries on them; else it is sent back
  once, then marked under the answer. A bare word of the map (a category of the catalog kept as a subject, with
  no description, part of nothing and linked to nothing: "memory", "cache") is no part: it is neither checked nor
  counted among the question's parts.
* **An answer thought aloud** ("Let me re-examine... Here's the corrected answer:") keeps what follows the last
  announcement of the answer, when a full answer follows it.
* **Investigation paths**: an investigation marked Helpful keeps its path (the kind of problem and of cause, the
  checks in order, what confirms the cause, what was ruled out), written generic by the LLM. It waits in To review
  with the answers marked Helpful; once an admin confirms it, the next investigations of that kind of problem get
  it, with the other causes found before for the same problem (one symptom, several known causes: the closest and
  the most often found with their steps, the others in a line). The last query of an investigation is no longer
  kept as an example or a learned answer.
* **Every answer marked Helpful keeps its path**, small request or big one (a count, an extract, a check, a
  confirmation): the data it used (the tables with the fields its queries name, the metrics with their labels) and
  its steps in their order, read from the answer itself (no LLM, no value of that one case: the dates, names and
  numbers of its queries are left out, the failed steps too). It is kept with the learned answer, shown in *To
  review* and in *Learned by the agent*, and given to the agent with the query for the next similar question. An
  answer that ran no query to keep (a health check, a comparison with usual, a comparison of groups) used to
  teach nothing: it is now learned as its path. An admin corrects a path in their own words before confirming it
  (*Edit*; emptied, it goes back to what the answer did), and what an admin wrote stays when the same question is
  answered another way. Like every learned answer, a path is given only to who may query its database.
* **The interactions your documents state are proposed for the System map** (`learn.interactions`, on;
  `superset supagent interactions`): the LLM reads documents, guides, Context pages and team notes next to the
  known parts they name and proposes how those interact, each with the sentence that says so, word for word. They
  wait in To review with their sentence; the map draws, and investigations follow, the approved ones only (the map
  says how many wait).
* **What is missing for investigations** (`superset supagent check-system [--question "..."]`, and for admins the
  System map page): what the agent knows of the system (the parts per category and where each is in the data, the
  interactions, the joins, the usual values, the health checks, the paths) and, in words, what it does not find;
  for a question, what the agent is given and the names nothing knows. No LLM, nothing changed.
* **The System map's display**: a click on a category's name folds its parts into one box and opens them again
  (the Open / Fold buttons are gone; any category folds); each viewer chooses the categories shown (a switch per
  category in the legend, a cross in each category's name: only the lines between what is shown are drawn; kept in
  the browser, for that viewer only); **full screen**. In *Edit*, an admin drags a category's name to move it
  with its boxes, and puts categories in **groups** drawn as frames (servers, resources and network under one
  name): display only.
* **Nothing the learning finds changes the categories before an admin approves it** (`categories.review_all`,
  on): the values read in the data's category fields and the categories the learning gave to the data's objects
  now wait in *To review* like the LLM's proposals (each says where it comes from; a category's values found in
  the data are approved together in one click); the values of what people wrote (a category on a catalog entry or
  a document) are used at once, as before. No value in use is merged, retired or changed by the learning: a
  proposed value that has the name of an approved value of another category says so (one click merges it), and a
  name the team already has under another category is not proposed again as a component. A subject may still
  share its name with a part. With `categories.review_all` off, the values of the data are approved at once, as
  before.
* **What you see on the map is chosen in a box where you type**: several categories and parts (a part with what
  it is part of, its parts and what it interacts with), in place of the *Everything* list of one part.
* **What each category is**: a description an admin writes in Categories or on the map, shown with the category
  and given to the agent (the system picture, `system_links`) and to the router with the parts a question names
  (`categories.about`).
* **Parts that look retired are proposed** (*To review*), never retired by the learning: a value read in the data
  that its category's fields and labels have not shown for `categories.retire_days` (14) days, seen so by two
  checks; any value, the ones put by hand too, that a text says was retired or decommissioned. *Retire* keeps the
  value, marked retired; *Keep* declines that reason.
* **"Part of" is chosen in a box where you type** (several values, the matches listed by the server): no list of
  thousands is loaded any more.
* **The classification at the size of a platform**: the values of a category read from the data are read once
  each, with where each comes from (which field of which indices, which label of which metrics), instead of once
  per metric that carries the label with a query per value (more than half an hour with thousands of metrics: now
  a second); such a category is no longer a list the LLM chooses in or adds to. The classification is a run of
  its own (*Classify now*, `superset supagent classify`) listed in the settings with its steps and its LLM use.
* **Backups of the knowledge, restored whole or by part**: one zip a day (`backup.enabled`, `backup.hour`, the
  last `backup.keep` kept, in `backup.dir`) with the categories and the System map, the catalog, the memory, the
  documents, the notes, the Context, the learned answers and paths, the descriptions of the data, the settings
  (never a secret; the vectors with `backup.vectors`). *Settings → Backups*: Back up now, Download, Restore… (the
  parts chosen are put back as they were, after the present state is saved in a backup of its own);
  `superset supagent backup | backups | restore`. Backups and restores are runs listed with the others.
* **The catalog**: a field that holds the usual value of another says `usual_of: <that field>` (index entries).
* **The router**: the *incident* route covers what is wrong now as well as a past period; the *technical* route
  offers `system_links` and gets the whole system picture. Any other question that names parts of the system gets
  what it names only (*What the question names*): a follow-up on a server's load needs no map of the platform
  (given the whole picture, the model answered such follow-ups from it without querying, in the end-to-end suite).
* **A memory that says when it applies applies only then**: the memories given with a question say that one
  written as "when the user says X" (or "for the desk Y") is no filter for a question that does not say X (a saved
  "when the user says BILLING, show only BILLING data" scoped "How many jobs failed yesterday?" to BILLING).
* **A query written in an answer and not run** is sent back to be run when the answer says what it returned ("the
  query returned no rows"), not only when it shows figures.
* **`check_health`: new, or every night?** Each breach says on how many of the seven previous days the same
  series breached the same check in the same window, is marked usual when it does on most of them, and the new
  ones come first: an alert that fires every night is not what changed today.
* **`promql_query`: a level with its usual.** A query of a few series gives each one what it was over the same
  window of the 7 previous days (`usual_avg`, `usual_max`, `against_usual`) and says in words whether these
  levels are their usual: a pool that is full every night is not what changed.
* **System map: the panel of a part with nothing under it** (most applications and servers) stopped halfway since
  0.8.0 (a page error after "Part of"): its interactions, *What touches it* and the admin's edits are shown again.
* **A tool call the server could not read** (a call that ran on to the token limit) is followed by a step of a
  quarter of `llm.max_answer_tokens` (2,048 at least): a second one does not cost as many minutes again.
* **Metrics**: `compare_to_usual` refuses a counter read as it is (it says to compare its rate or its increase)
  and says when a value far from its median is within what the earlier weeks differ by; "now" in the metric tools'
  times follows `agent.now` when an admin pinned it.

From 0.8.x: `pip install` on every host, `superset supagent init` once (schema 14 -> 15: three nullable columns of
`supagent_link`), restart (INSTALL.txt, *From 0.8 to 0.9.0*: what starts by itself, and the three statements to
go back to 0.8.2).

## 0.8.2 — 2 Oct 2026

The Data dictionary, from a first day of review on a real platform:
* **To review: a proposed value is edited whole before it is approved.** *Edit…* on its card (in place of Rename)
  has what the Categories page's Edit has: its category (subject, application, component, your own), its name,
  what it covers, its other names and what it is part of, then *Save and approve*, or *Save* to keep it waiting
  with what was changed. A name that exists already in the category it moves to makes one value of the two, with
  the parts chosen, approved when asked.
* **Saving an edit never takes away a "part of" the admin could not see.** The list of what a value can be part of
  fills after a request and held the first 1,000 values in the order of the categories' names: with a big category
  read from the data (servers), the subjects were not in it, and saving an edit of a value (Categories → Edit, To
  review → Part of…) then removed its subjects without a word. The list now has every category, the wider ones
  first (5,000 names at most); the save buttons wait for it; a part the list does not show stays as it is.
* **The AI-written descriptions of the data are no longer listed in To review** (tens of thousands on a platform:
  nobody approves them one by one). *Data → Browse → AI-written, not approved* shows them, to correct the ones that
  matter; the page's first line counts them without calling them to check.
* **Categories of your own are edited and removed** (Knowledge → Categories → *Categories and where their values
  come from*): *Edit* changes the name of one of yours (its values follow) and the field names of any; *Remove*
  takes one of yours away with its values and everything that names them (the items they were given to, the "part
  of", the interactions of the map, their places), after asking and saying what goes. Each category says how many
  values it has. A name of your own is shown as you wrote it (no "s" added: Infra, Monitoring).
* **The System map follows the categories by itself**: read again when it is shown, when the window comes back and
  every 20 seconds while it is looked at (once a minute for who is not an admin; never while an admin edits it; not
  after 15 minutes with nobody at the page, so that an open map does not keep a session alive); it says what a
  reading brought ("Updated:
  new part ..., 1 new “part of”", *Show* brings it in view) and outlines it for a moment. An admin sees every
  category, the ones with no value yet too (a category just added has its column, with "No value yet: add one in
  Categories"), and how many proposed values wait in To review (the map draws the approved ones). While it reads,
  the page says "Updating…".
* **The map answers fast on a big platform**: it read every metric with its statistics (seconds with tens of
  thousands of metrics) and looked all the documents up again for every value after each change; it now reads the
  two columns it needs, and keeps each value's explanation while the documents do not change.
* **Team memory: "Edit it in the catalog" opens the entry** that replaced the memory (it was a text, not a link).

No schema change: from 0.8.0 or 0.8.1, `pip install` on every host and restart.

## 0.8.1 — 2 Oct 2026

Two refinements of 0.8.0's checks, found by replaying them on the recorded answers of the end-to-end suite:
* **The number check accepts the time units said as written** (60 minutes in an hour, 24 hours in a day, 1,440 minutes
  in a day), as it does 3,600 seconds and the bytes of a GiB: 0.8.0 marked "more than one hour (60 minutes)" or "a
  24-hour target" with a check note when no result held 60 or 24. A number close to them (59, 61, 23) is still a
  figure to find in the results.
* **"its", "their", "son", "leur" refer to the answer before only with nothing before them they could stand for**:
  "What was its failure rate?", "And their notional?" do; "Which servers exceeded their memory limit yesterday?"
  is a question of its own (0.8.0 read it as a follow-up: the previous question's conditions could be pushed onto it).

## 0.8.0 — 2 Oct 2026

The pages:
* **Explanations behind an "i"**: the paragraphs that explained each part of the Data dictionary, the chat's drawers,
  the settings (each setting's text too) and the LLM usage page are behind an **i** next to the title: a click shows
  the text in a small card (a second click, Escape or a click elsewhere closes it). The tabs are bigger.
* **Learned by the agent** is a section of **Knowledge** (the old address `#learned` still opens it).
* **The catalog's "note" is "guide"** (documentation, runbooks, how-tos), so that it is not taken for the users'
  quick notes. The upgrade renames the entries, their history and their search pieces (the knowledge store too); a
  YAML or a call with "note" still works. Search → Kind: Guides or Notes.
* **Learned answers corrected before they are confirmed**: Edit (Learned by the agent, and To review) changes the
  generic question and the query; *Check the query* runs it with the admin's permissions (a few rows); a changed
  query is confirmed only if it runs. The former question and query are kept (Before the last change).
* **Where the data of the questions was: words added by hand** (an index or a metric of a database): stemmed like
  the questions' words, they never fade and a miss or a Not helpful never removes them (dashed chips).
* **To review**: the groups' titles stand out from the text; *Part of…*, *Merge into…*, *Rename*, *Change…* and
  *Edit* open a panel that their button closes again (one panel at a time on a card).
* **The Context as documentation**: the contents (functional, technical) on the left, the page on the right, a box
  that finds the pages by their words, the sources under each page; **Word (.docx) and PDF** of a page or of the
  whole Context (pure Python: nothing to install).
* **The System map** (Knowledge → System map, for every user of the dictionary, each seeing the parts that concern
  the databases they may query): the architecture as the categories describe it, one column per category, each part
  with what it does (its description, else the sentence of a document, a guide or a Context page that names it), a
  grey line to what it is part of, and the **interactions** an admin draws (depends on, sends data to, calls,
  reads from, runs on, triggers, monitors) as arrows; a big category folded into one box; focus on a part (what
  touches it). Admins: Edit to move the boxes (kept), draw an interaction, write what a part is, hide a part.
  Exports: PNG, SVG, PDF.
* **Documents and sites behind a sign-in**: a token (Bearer), a user and a password or app token (Basic), or a
  token in a header of its own, kept encrypted (Superset's SECRET_KEY), sent only to the document's own site (never
  after a redirect elsewhere), never shown nor logged. **Confluence** (a page and the pages under it, or a space;
  Data Center and Cloud) and **Bitbucket** (a repository's text files, documentation first; Data Center and Cloud)
  are read through their APIs; other sites as web pages. Each page is cut in its own pieces for the agent's search
  (words and meanings, in the knowledge store when PostgreSQL has pgvector, pg_textsearch, pg_trgm), with its
  address: the agent names the page. The table says how many pieces each document has in the search.
* **The chat panel on Superset's pages floats**: a button switches between docked (the page narrows beside it; the
  left edge, or the arrow keys on it, set its width) and floating (moved by its title bar, resized from any edge or
  corner, over the page: the charts do not move). Place and size are kept in the browser. Docked, it leaves the page
  900 pixels at least (a dashboard's header needs about 850: below, its charts would go under the panel); dragged
  further, it says to float it; in a window too small for both (under 1,220 pixels) it floats.
* **What cannot be undone is confirmed**: every delete (a chat, a memory, a note, a document, a catalog entry, a
  learned answer, a word of a table, a category, an interaction) asks in a small card next to the button what goes
  with it; Cancel, Escape or a click elsewhere keeps everything.

The agent:
* **The subjects of a chat**: a follow-up ("and on the 23rd?", "which one had the most?", "in hours please", a reply
  to the agent's question) is given its subject's messages from the start (the first exchange, the ones in between
  shortened, the last ones in full); a question about other data starts a new subject without the earlier messages;
  a question about an earlier subject's data goes back to it. Decided from the words, the named values, the tables
  each subject read and the question needs; the LLM is asked in a short call only when that cannot tell; not sure:
  the same subject. The chat shows a thin line where a subject starts or comes back. `agent.subjects=false`: the
  last exchanges, as before.
* **A follow-up for another day is answered for that day**: "And on the 23rd?", "Et le 23 ?", "And the day
  before?", "la veille" are read from the day the questions before named. Such a follow-up gets its own query, with
  the previous question's conditions, and the period check reads the earlier question with the new day in its place
  (its "shipped", its "during the night" kept): the 23rd's query was refused as "not 22 September", and the 22nd's
  figure came back. With no day before ("And the 2nd?" after a ranking), it is no day.
* **A month is a month's name**: "the top 5 markets", "3 decisions", "10 junior" named a day (5 March, 3 December,
  10 June) for the period checks of queries and charts and for the answer checks.
* **A follow-up answered without a query restates the previous answer only**: its numbers must be in that answer;
  one found only in an older answer of the subject ("10,000", a limit) no longer passes for a new figure ("What was
  that book's VaR?" was answered with it): the answer is sent back for a query.
* **The number check no longer takes 59 to 61, 24 or 1 for "found"**: the unit constants (3,600 seconds in an
  hour, 86,400 in a day, 1,024 bytes) ground only themselves, as written; converted, they made such numbers of any
  answer pass ("61 trades booked by voice", made up, was not sent back).
* **A query written in the answer instead of run** (with figures no query gave) is sent back with that reason: "call
  execute_sql with it"; still not run, the answer says no query ran.
* **"No such field" is looked up first**: an answer that says the data has no such field or value while no tool was
  called is sent back once to look it up (describe_data: the fields and their values; a value may be in a field with
  another name), follow-up or not. A wrong "there is no such field" in a chat's earlier answer was repeated by the
  next ones.
* **Metrics: "how many" is a number of events**: a query that adds up `rate` (per-second rates) for a "how many"
  question, or counts the samples of a gauge (a counter exported as a gauge, such as the kernel's OOM kills), is sent
  back once with the right form (`SUM(increase)`, `SUM(INCREASE(value))`, `COUNT(DISTINCT label)`); sent again
  unchanged, it runs.
* **Follow-ups keep their context**: "What was *its* failure rate?", "their", "son", "leur" refer to the answer
  before: a short question with such a word and no value of its own stays in the subject, whatever tables its other
  words make the resolver guess (it was taken for a new subject and lost what "it" was); a question the subjects find
  goes on from the last exchange with nothing of its own ("Which error code came up most often?") is read with the
  previous question and keeps its conditions; "that day", "ce jour-là" are the day named before; a short question with such a day ("Compare with the day
  before.") stays in its subject ("the ones delivered
  that day": the period on the delivery time); "in total", "overall", "au total" take the whole, not the previous
  answer's part.
* **"Back to …" has the scope of the question it goes back to**: the last answer's conditions are no longer pushed
  onto it ("Back to the September returns: how many were refunded?" after a question about one return reason was
  counted for that reason only).
* **The words of a subject**: words that start like a time word ("events", "declined", "market", "main",
  "maintenance") are no longer left out when the subject of a question is decided.
* A value the question names is kept when the query writes its table as a pattern (0.7.1).

Upgrade: `pip install` and `superset supagent init` (schema 13 → 14: new nullable columns, the guides renamed);
see INSTALL.txt. A fresh Superset 6.1.0 installed from PyPI today needs three pins (INSTALL.txt).

## 0.7.1 — 2 Oct 2026

* **A value the question names is kept when the query writes its table as a pattern.** A production answer to
  "the application X's KO errors of D-1, by category" queried `"<index>*"` while the dictionary knows the index as
  `"<index>"` (an alias, a family of dated indices): the checks looked the table's fields up by the exact name,
  found none, and the query that left the application out was not sent back. A query's table written with `*` now
  reads the dictionary's indices it matches (and a dated index the dictionary's pattern that covers it), for every
  check that looks fields up: the values the question names, the team's rules, the periods.
* No table change: `pip install --upgrade` and a restart.

## 0.7.0 — 1 Oct 2026

* **Notes**: any user writes one in seconds (what a meeting decided), for the team or for themselves: the chat's
  Notes button (search, pages, edit), `/note ...` or `/mynote ...` in the question box (saved without the LLM),
  Data dictionary → Knowledge → Notes. The agent finds them (the knowledge search; `search_notes` with words and
  days), always with their author and day, as not verified: never a team rule, never the source of a query's
  condition. An admin pins a team note or makes a catalog entry of it. Table supagent_note.
* **The agent as a notes assistant**: asked in the chat, it reads (`read_note`), writes (`add_note`: the team's,
  or personal when the user says so), adds to or changes (`change_note`, `undo` back to the version before) and
  deletes (`delete_note`, only in its answer to the user's yes: a call in the turn the deletion is asked is never
  run) the notes the user may change, as that user. Each note keeps its earlier versions (`versions`, 20). A
  request about notes gets the notes tools only; an answer that says a note was saved, changed or deleted with no
  such call is sent back, then replaced by what is true (the lab's LLM wrote "has been deleted" without calling
  anything). "Note for the team: ...", "Make a personal note for me: ...", "Add a note: ..." are saved at once,
  without the LLM, like `/note`; the call in the answer to the user's yes is the confirmed deletion.
* **The charts and dashboards looked at every night** (`charts.scan`, with the Context build): each chart's last
  full day against the same weekday of the four weeks before, per series, through Superset's chart data API as
  the learning user (high, low; data that stopped is said as such; a few events are not unusual; charts left out
  say why); what each chart shows in words (LLM, cached); a Context page per dashboard. The agent's
  `chart_anomalies` answers "anything unusual on the X dashboard?" for the charts the user may see (with
  row-level security, a look now as them). Gentle on the databases: `charts.max_requests_per_minute`, a database
  answering it is overloaded is left for the next night. `superset supagent charts`. Table supagent_chart_scan.
* **Where the data of the questions was** (Data dictionary → Learned by the agent): one row per table, the words
  that led there (one that also led to other tables and databases says so), the answers and the Helpful among
  them; a search box, a database filter, pages; Wrong (admins) takes a word away from a table.
* **Data dictionary → Search lists everything found**, not the 12 best: every piece the search finds (at most 500,
  the first ones in the order the agent sees them), 20 per page, with the count. Each name is a link to where the
  item is read or edited: a chart or a dashboard opens in Superset (new tab); an index, a metric, a catalog entry,
  a note, a team memory, a document, a Context page or a learned answer opens in the dictionary's side panel, at
  an address that can be copied or bookmarked (`#open/<item>`, opened only for a user who may search it).
* **Categories by hand** (Data dictionary → Knowledge → Categories, admins): a value is added to a category
  (subject, application, component) with its description and other names, used at once; one that exists is said
  so, a retired one comes back. **Edit changes the category itself**, not only the value's text: a value moves
  between subjects, applications and components with its items (where the other category has that value
  already, the two become one, as a merge; a rename onto an existing value merges too, where it failed before).
  The aspect (functional, technical) stays fixed.
* **A value can be part of several others** (the user's example: a jvm of two applications and four components):
  when it is added or with Edit → Part of (Ctrl or Cmd + click for several). The list says what each value is
  part of; the items of a value count as about each value it is part of (a note on the jvm is found for both
  applications); a merge keeps what each value is part of.
* **The learning says it too**: a new value the LLM proposes (from the metrics, the data, the notes, the
  catalog, the memories) comes with the known values it is part of, approved with it, and, when it names a
  known value, a one-click "Merge into" that value; what the texts say about known values ("the posting engine
  is part of LEDGER") waits in To review → Categories part of others (Approve, Reject).
* **Categories of your own, read from the data** (Categories → Categories and where their values come from):
  besides subject, application and component, an admin adds categories (server, environment, team...) and,
  for any of them, the field names its values are read from (`categories.fields`, e.g. `server:
  ^(host|node|server)$`). The learning makes their values approved values with where they come from ("field
  NODE of jobs-*"); the LLM classifies into them too. Two such fields of one index show which values go
  together (the profile's sample): proposed as "part of" (an application above its servers) in To review, never
  applied without an admin (a rejected one is not proposed again). Settings `categories.custom`,
  `categories.fields`, `categories.max_values`, `categories.relation_min_docs`.
* **System map** (Categories → System map): the system as the categories describe it, each value under what it
  is part of (a value of several under each), with the items about it that exist now by kind; a metric removed
  or a note deleted is no longer counted, and a value whose items are all gone says so.
* **To review**: a decided item leaves the list at once (it stayed, green, until the page was read again); a
  value merged into an approved one counts its items at once (they waited as proposed). Besides Approve and
  Reject, **Change…**: a "part of" suggestion approved with only the values chosen (or others; the rest is not
  proposed again), an item's category moved to another value, a new value approved with what it is part of.
* **Nothing the LLM finds is used before an admin approves it** (`categories.review_all`, on by default, a change
  from 0.6): every category it gives an item and every relation it finds between items waits in To review, even
  the ones it is sure of; until approved, the router and the search do not use them. Values and their "part of"
  relations always wait. `categories.review_all=false` gives the 0.6 behaviour (what it is sure of, on approved
  values, used at once).
* Fields named `component` or `module` now feed the component category (`categories.fields`); before, a field
  named `component` fed the application values.

* **Reliability on a second subject.** A retail lab (orders and payments, deliveries, returns, customer care) and its
  benchmark (25 cases, two wordings, split before any run). What its held-out half found, fixed:
  * **The time the question names is the time of its period**: "parcels shipped on 17 and 18 September" counted on
    the delivery time, "tickets opened" on the first response time. The classic check sends back a query whose
    period is on another date field than the one the question names; the governed plan's period takes that field
    (`Period.field`). Two named days ("17 and 18 September") are a span, not the second day.
  * **An index's time field is its dataset's main time column** when the team chose one in Superset (the learner
    took the first date field by name); indices learned before take it at the next learning run.
  * **A rule's condition is read its way and on the data it names**: "Orders of the channel TEST (CHANNEL =
    'TEST') ... never count them (CHANNEL <> 'TEST')" was applied as CHANNEL = 'TEST' (the governed pipeline counted
    the test orders only); now the operator a rule writes decides, else the words of its sentence before or after
    the value. "Exclude cancelled trades (STATUS = 'CANCELLED')" no longer goes to other tables with a CANCELLED
    status. A condition code added from a rule never stands for one the question asks for ("failed at payment"
    planned without the failed condition is sent back).
  * **A follow-up keeps the previous question's conditions** (classic): "... show me only <app>" after an
    answer counted with a business-date label added the application and dropped the label. The previous
    answer's conditions on a table queried again, that this answer's queries lose and the message neither
    changes nor removes, are sent back once, then said under the answer. "Make it in your memory", "when I say
    X ... you should know" are learned like "remember".
  * **A value the question names is in the query** (classic, as the governed plan already checked): "How many web
    orders did we sell" counted every channel (no 'WEB' in its query): such an answer is sent back once, then
    marked; a value said before the table's subject ("test orders") is named in both pipelines; "UAT included"
    is not a filter.
  * **Governed answers**: the top N asked is the whole answer (it said "the results only show the first rows"); a
    count has no unit ("count of rows, in seconds"), nor a sum one the dictionary does not give ("in percent").
  * **A day said as `DATE '2026-09-22'`** (or a midnight `TIMESTAMP`) on a date field stored with a time finds
    nothing: sent back as `= '2026-09-22'` already was ("LYON orders of 22 September": 0 instead of 136).
  * **No figure for the future**: "Forecast tomorrow's orders" got "~411 orders" (the mean of four Fridays); the
    data tell what happened: past figures as past figures.
  * **Status questions read the nightly look first** (`chart_anomalies`, then the live checks).
  * **Investigations, generic**: the question's own data first, then what people said about that time (the
    team's notes, the documents), the systems' health only for systems' data (the instructions named the jobs
    index and the servers: "why were deliveries late" went there); two calls before the end, the agent answers.
* **A second, independent computation** (test, off: `agent.cross_check`): when the classic agent answers with
  figures from its own queries, the governed pipeline computes the same question its own way (its plan, queries
  built by code); when its figures differ from the answer's headline figures, the answer says so with the other
  figures. Costs the second computation's time (`agent.cross_check_seconds`, 180 at most). Measured on the lab's
  112 labelled answers: it caught 4 of 21 wrong answers and questioned 12 of 91 right ones; it stays off.

Upgrade: `superset supagent init` (schema 13: supagent_note, supagent_chart_scan; columns supagent_facet.parents,
supagent_facet.suggested, supagent_facet.origins).

## 0.6.0 (2026-10-01)

The release of the 0.6.0 test versions: the code of 0.6.0b7 with one fix, found by rehearsing the upgrade from
0.5.4 on a copy of the lab's database owned by an ordinary role (not a superuser, as Superset's database user is
as a rule):

* **The knowledge store with a database user that is not a superuser**: it read `shared_preload_libraries`, which
  PostgreSQL shows only to superusers and `pg_read_all_settings`; the store was then never built (`init` said "not
  used (no pgvector, pg_textsearch or pg_trgm...)" with the three there) and the search of 0.5.4 kept answering.
  Now read where PostgreSQL leaves it out instead of failing; when it is not shown, `store status` says to check
  it as a superuser. `init` prints the store's real error, if any.

What 0.6.0 brings, by test version below:

* **The router (MOA)** (on; `agent.router`): the kind of work each question needs, from its meaning, the knowledge
  it touches and the routes people confirmed; nothing in it is about one business.
* **The Data dictionary redesigned**: To review, Knowledge (the catalog, team memory, Context, documents and sites,
  categories: moved from the Settings page), Data, Learned by the agent, Search; saves answer at once.
* **Categories of the knowledge** (`superset supagent classify`, daily) and **the learned items ranked by the
  discussions**.
* **The knowledge store in PostgreSQL** (optional: pgvector, pg_trgm, pg_textsearch; `superset supagent store`),
  with each user's chats and **a search box for them**.
* **A cross-encoder reranker** (optional, off: `rerank.url`).
* **The governed pipeline** (optional, off: `agent.pipeline = governed`) and other MCP servers as sources
  (`supagent[graph]`).
* The fixes the domain benchmark (PnL, risk, pricing, trades, reports) found: team rules only where their value
  can be, dates said as days on timed fields, NaN results saved, a stuck LLM call not waited for twice, qualified
  counts.

Upgrade from 0.5.4: INSTALL.txt, "Upgrade from 0.5.4 to 0.6.0" (6 new tables, schema 9; checks of PostgreSQL
before; a rollback to 0.5.4 needs no restore).

## 0.6.0b7 (test version, 2026-10-01)

* **An LLM that does not answer in time is not asked again**: a read timeout was retried, so one stuck call of the
  governed plan held the answer 2 x llm.timeout (half an hour on the lab). Quick steps have their own bound: the
  router 60 s, the decider's choice 120 s, the plan 180 s; then the normal way (the classic agent) answers.
* **A count the question qualifies needs that condition**: "How many jobs failed" planned without a condition on
  the field that says FAILED counted every job (the lab, once its glossary term was missing: all 73,769 jobs said
  "failed"); such a plan is sent back with the field and its values.

## 0.6.0b6 (test version, 2026-10-01)

* **An answer whose results hold NaN is saved** (a sum over no row): PostgreSQL's JSON refused the whole row and the
  answer was lost ("The agent could not answer"); NaN and infinities are stored as null. SQLite (the tests) took it.
* A condition the planning model copies from a team rule follows the rule's limits, like the ones code adds: not on
  a step grouped by its field (per BOOK), not where its value cannot be.

## 0.6.0b5 (test version, 2026-10-01)

Found on the domain benchmark's dev half with 0.6.0b4:

* A rule's condition does not concern a table where its value cannot be (BOOK = 'ALL' on an index whose books are
  all known and none is ALL); the words every rule has ("not", "unless"...) no longer pick its tables.
* Governed plans: a day said as an equality on a date field (COB_DATE = 2026-09-23) becomes the step's period or
  that day's range; a code is not said by a part of another code ("FX_OPT_G10" does not say the desk FX_SPOT; both
  pipelines); a question back ends with its question, its options first, so that the reply is read as its answer.

## 0.6.0b4 (test version, 2026-10-01)

Found by the domain benchmark (PnL, risk, pricing, trades, reports) on 0.6.0b3:

* **A team rule applies to the data it is about**: a rule on a field (BOOK = 'ALL', "the VaR of a desk") was
  added to every table with that field (PnL, trades), which then found nothing. A rule now concerns the tables
  carrying its distinguishing subject (VaR: the risk index), and a query or step per that field (per BOOK) never
  gets its filter. Both pipelines.
* **A date alone on a date field with times** (`"TRADE_DATE" = '2026-09-23'` on dates stored at 00:00 UTC, or
  with real times) matches nothing: the classic agent's query is sent back once with the day's range.
* A unit the model puts on a measure that nobody asked for (a PnL "in percent") is removed by code.
* A governed step that fails (a learned count ">=200" read as a number crashed the plan's check) hands the question
  to the classic agent instead of ending the answer in an error; such counts are read as "at least".

* The knowledge given with a question names each piece's application and subject; the categories list the most
  used first; a one-letter code is not an application; no near-spelling search in a store built without pg_trgm.

## 0.6.0b3 (test version, 2026-10-01)

**The router (MOA)**: before each answer one short LLM call chooses the kind of work a question needs
(functional, technical, incident, charts, observability, infrastructure), from its meaning, the knowledge it
touches (with its categories) and the routes people confirmed; the route gives the knowledge of its kind first,
its tools and a short instruction; not sure: the normal way. Nothing in it is about one business. It learns only
from confirmed answers whose execution followed the route; the same question's examples never decide alone
(two agreeing, or an admin's route decision). Lab, held-out half: 82% routed right cold (57% with the first
definitions), 88% with examples, 83% with a wrong example (31%).

**The Data dictionary redesigned**: To review (what waits for an admin, each item with its actions), Knowledge
(catalog, team memory, Context, documents and sites, categories: moved from the Settings page), Data, Learned by
the agent, Search; deep links. **Saves answer at once**: the agent's search follows in the background, the page
says when it is up to date (lab: 0.03-0.5 s instead of 0.8-1.6 s).

**Categories of the knowledge** (`superset supagent classify`, daily): functional or technical, subjects,
applications, components, and the relations between items, by the LLM; an admin reviews only the new values, the
unsure tags and the same-as relations.

**What the agent learned is ranked by the discussions**: the items each answer was given, the tables it read, the
learned queries it ran again (worked or not), and what people said of those answers; the learned answers proposed
follow it; the Learned tab is sorted by it with its reasons.

**A search box for the user's own chats**; **a cross-encoder reranker** for the knowledge search (optional,
`rerank.url`, fails open).

Upgrade: `superset supagent init` (tables of schema 9: categories, tags, relations, uses).

## 0.6.0b2 (test version, 2026-09-30)

**The knowledge store in PostgreSQL** (pgvector, pg_trgm, pg_textsearch; `superset supagent store ...`): the search
runs in PostgreSQL, by words (BM25), near spellings (a name or a value typed with a typo) and meaning (an HNSW index:
no vectors in the processes' memory), the ranks fused, with the user's permissions applied inside the queries. It
also keeps each user's chats (the tool `search_my_chats`, their own only) and the routes people confirmed (the
governed decider's `neighbors` votes; near spellings as `spelling`). Derived and rebuildable: a schema of its own,
built by `init` when the extensions are there, `store rebuild|sync|wipe|status|search`, `search.store = off` to go
back at once; its connections are autocommit and closed after use. pg_textsearch before 0.6.1: see the README (a
ROLLBACK after an error can fail in sessions that loaded it; do not preload 0.5.x).

**The governed plan counts what the question names**: a value of the data it names (BILLING, UAT, a server) is a
condition or a group of the plan, a glossary term it uses is counted as the glossary defines it, a unit it asks
for (in GiB, in minutes) is on a measure and converted by code, and a time bucket only when it asks for one (per
hour, daily, when...); no total of rows a query cut; an explanation that does not say the knowledge gives the
knowledge's own text; explore links, SQL Lab and questions about earlier chats go to the classic agent.

## 0.6.0b1 (test version, 2026-09-30)

**A second way to answer: the governed pipeline** (setting `agent.pipeline = governed`; `classic` stays the
default, so installing this version changes nothing until an admin switches it). In the classic pipeline the
model writes SQL and checks read it afterwards. In the governed one the model never writes a query:

* **the decider** chooses the knowledge a question needs before anything else: candidate tables (an index or a
  metric in one database) from the dictionary itself (names, descriptions, synonyms, associations, the values the
  question names, the database, chart or dashboard it names, the learned answers, the team's charts), ranked by a
  small learned gate (readable weights, learned only from answers a person confirmed: Helpful, an admin's
  confirmation, the reply to a question back; bounded around the defaults); one LLM call then chooses among the
  best ones and says what is ambiguous or missing; the chosen tables are given in full (fields, labels, values,
  units, verified or AI-written descriptions) with the team's rules on their fields, the glossary terms, the notes
  and learned answers;
* **the plan**: one LLM call fills a typed plan (tables, measures, groups, conditions, period, top N). Every
  condition carries its source (the question's own words, the chat, a knowledge item, an earlier step); code checks
  it: a condition nobody gave, a period that is not the question's, a limit nobody asked for, a value the data does
  not have, a counter averaged, a unit it cannot convert, are sent back once; the team's rules are added by code
  (not when the question asks for their value);
* **the queries are built by code** from the plan (OpenSearch and Prometheus), run with the user's permissions
  (execute_sql);
* **the answer** is written from a figures sheet made by code; its numbers are checked against the results; code
  adds how it was counted ("failed jobs in jobs (database 1) · STATUS = FAILED (you said "failed") · ENV ≠ UAT
  (the team's rule ...) · 23 Sep 2026"), a value that is not in the data, a period outside the data;
* questions back, answers from the knowledge alone, and "the data cannot answer" are kinds of plans;
* chart, dashboard, e-mail and export requests, status questions ("is everything normal"), questions for another
  MCP source, and a question no valid plan could be written for go to the classic agent (the steps say which way).

The pipeline runs as a LangGraph graph when `supagent[graph]` is installed, else the same steps in order.

**Other MCP servers as sources** (setting `mcp.servers`, needs `supagent[graph]`): their tools are offered to the
agent (named `<server>_<tool>`), indexed as knowledge (the decider routes questions to them), run with the
server's own headers (`{username}` replaced); a tool that changes something runs only when an admin allowed it
(`allow_write`); `roles` limits a server to some users.

Also: a metrics database whose live list of metrics failed is not asked again for a minute (a Mimir outage no
longer costs every question a timeout); `superset supagent ask --pipeline governed|classic`.

Install and roll back: see INSTALL.txt. The new table (supagent_route: what the decider showed, chose and read for
each answer) is ignored by 0.5.x.

## 0.5.4 (2026-09-30)

* The same code as 0.5.3, published under a new version number. Everything below 0.5.3 applies.

## 0.5.3 (2026-09-30)

**No condition of the model's own.** Every condition of a query (WHERE, FILTER, CASE, HAVING, PromQL
matchers, a saved chart's filters) must come from what was said: the question and the chat, the team's
rules and words (glossary), the memory, the documents, notes and learned answers found for the question,
the formulas of the instructions (`mode <> 'idle'`), or the rows an earlier query of the same answer gave
(the 3 servers with the most failures, then their CPU). In the lab the model counted "late" jobs among
the successful ones only (288 instead of 337) and "jobs over 45 minutes" from the 60-minute bucket; both
passed every check. Now such a query is sent back before it runs, once per condition: sent again, or in
another query of the same answer, it runs and the answer says so ("this answer counts only STATUS =
'SUCCESS', a condition the question did not ask for"); a histogram bucket (`le`) sent back comes with the
reminder that it counts up to its bound only (no estimate between buckets). Words say values in other
words ("failed" FAILED, "errors" FAILED, "production" PROD, "5xx" '5%', "45 minutes" 2700), the
dictionary's lists of values are not a source (every status is in them). Not checked: open questions
(what is happening, why, is it normal), queries that only list values, dates and times (the period
check), IS NULL, comparisons with 0. Replayed over node3's latest 800 stored answers (1,077 queries with
conditions, the lab's rule and SLA note in place), it sends back queries in 5 answers: the two invented
conditions above, position labels used for a calendar date, and 2 answers whose values came from a result
the replay only had cut to 4,000 characters (the live agent reads it whole). Values an earlier query of
the answer found count when that query gave figures or was filtered (the applications that failed today),
not a bare list of values (every status).

**Every way an answer ends gets its checks.** Out of calls, the model's last summary had no check of its
numbers, rules or conditions, and an empty answer's fallback (the last result) none of the rules and
conditions: they now get the same notes as any answer.

**An answer going round in circles.** In the lab a long report ended with the model writing its working
notes again and again ("I will now write the response. One final check: ...") until the server's limit:
174,000 characters shown to the user after 17 minutes. Such an answer (the same block of lines a third
time) is now sent back once with the loop cut out of the chat, then cut where it repeats and said; one
LLM answer has at most `llm.max_answer_tokens` tokens (8192; with `llm.thinking`, four times this; 0: the
server's own limit). A short first paragraph where the model says it will now write the answer ("Now I
have all the numbers. Let me write the summary:"), with no figure in it, is left out.

**A LIMIT read as a count.** A query grouped by four columns with LIMIT 100 gave 100 rows, and the answer
said "100 failed job runs" (358 in fact), unmarked: 100 was "from the query". Such a number (the rows a
query's own LIMIT let through, written as a count, not asked for, not a value of the result) is now sent
back once, then marked. And a small result cut by its own LIMIT kept the column totals but lost the note
saying it was cut (the totals were then read as those of every row): the note stays, and says the totals
are those of the rows shown only.

**A plan instead of the work.** Asked to change a chart, add it to a dashboard and e-mail it, the model
answered "I'll do this in three steps: 1. ... 2. ... 3. ..." and called no tool; the check of announced
steps read only the last sentence. An answer that is only a list of steps it will take is now sent back
once, like an announced step.

Also: the total of the rows a sentence names ("BILLING and PAYROLL account for 871") is read as from the
results when it is the sum of those rows in one column of a result (it was marked as made up when the rows
were not the first ones of the result).

## 0.5.2 (2026-09-30)

* A short follow-up that asks for something new ("And on 22 September?", "The CPU of srv-amer-002
  yesterday.") is no longer read as completing the previous question, nor answered from the chat's
  results without a query: 0.5.1 could answer "And on 22 September?" with the number of the 23rd,
  unmarked. Such an answer, still without a query after the reminder, is marked.
* "database 4" names a database; a bare "base 4" no longer does.

## 0.5.1 (2026-09-30)

Checks that run **before** a query or a saved chart, instead of after the answer (a model told
afterwards often keeps its answer; a call sent back before it runs is written again). Each sends the
call back with what to change, every reason at once. Sent again unchanged, a call left out of a rule,
a period or a counter runs (the question may mean it; a rule left out is then marked in the answer);
a call on another database never does (it is read only when the question names it: its name, or
"database 4").

* **The team's rules**: a query or a saved chart on data that has the field or label of a filtering
  rule ("Exclude the UAT environment (ENVIRONMENT_TYPE = 'UAT')") and does not use it, with the
  condition to add (`"ENVIRONMENT_TYPE" <> 'UAT'`, a chart filter, a PromQL matcher). Also the SQL of
  e-mails, SQL Lab saved queries and `compare_to_usual`.
* **The right database** when the same index or metric is in several (two OpenSearch clusters, a DR
  replica, one Mimir reached directly, federated and through a gateway): the database the question
  names (its own words next to a word for a database, its whole name, a tenant only it has), and the
  database of the charts and dashboards the question or the chat is about (an id, a link, a title,
  or read by a tool of the answer). In the lab, questions about the dashboard of the gateway's
  tenants were answered from the federated database (same metric, other data).
* **The question's period**: a question with a date or a period needs a filter on the time of the
  data (the index's time field, `ts` of metrics), not on business dates unless it speaks of them;
  one whole day needs the whole day, a span of days ("the week of 14 to 20 September") exactly those
  days (in the lab: `POSITION_LABEL = 'D-1'` for "on 23 September", a chart of "23 September" built
  on 00:00-06:00, a week ending at 06:00 the next day).
* **Counters counted as samples**: `COUNT(*)` on a counter, histogram or summary of a metrics
  database counts samples, not requests or errors (in the lab: "66.67 % availability, 2,880 errors"
  that were sample counts, and "201,600 jobs over 45 minutes" from a histogram bucket); the call is
  sent back with `SUM(increase)`.

Also:
* When the same index or metric is in several databases, "Where the data is" names the one to use and
  why: `agent.preferred_databases` (new setting, names or ids in order), then the catalog's metrics
  database, then the database the team's charts use for it (before: the lowest score, then the
  catalog, then the lowest id). Chart and dashboard pieces of the knowledge name their database.
* A value the question names that is in several kinds of data (an application of the jobs index and a
  label of HTTP metrics) is shown with where it is when the question does not say which; the answer
  says which one it took, and when it read only one of them and does not name the other, a line under
  it does ("Not read for this answer: BILLING_API is also a value of the label application of 10
  metrics ... Ask if you meant that data."). The lookup reads one label per name, not every metric's.
* A reply to the agent's question back ("The failed jobs.") comes with the question it answers, and so
  does a short reply that completes the previous question after an answer ("The failed jobs.", "Only
  PROD."): in the lab the model then answered for every application.
* A list continued past the results ("... up to `srv-amer-199`") that stays after the check is taken
  out of the answer (the lines before it stay) instead of marking the whole answer.
* A follow-up answered from the chat's own results (every number in them) is not sent back for a new
  query.
* A saved chart asked for the top N that shows more categories is told NOT DONE, with how to do it (in
  the lab the model listed the first 5 rows of the chart, sorted by name, as "the top 5").
* Names in `code` are checked like the others (`srv-amer-200`, a series continued, was missed in
  backticks); `n1-n5` of two given names is not flagged. A big result says how many rows have an empty
  value (201 "servers" were 200 and one row without a server).
* The numbers check no longer reads the date of "now" as a period (30 September was 43,200 minutes:
  a made-up 43 passed on the 30th of the month); the rest of a share the answer shows (99.00 %
  available next to 1.00 % of errors), a converted value rounded twice (19.1949 GiB written 19.20)
  and the unit constants (1,073,741,824 bytes per GiB) are not marked as made up, nor a number said
  as rounded ("roughly 12,300", to the hundred). The numbers check
  asks to delete the sentences it cannot support, rather than to keep them.
* "How many" answered with shares or rates only is sent back once for the count; a result cut by the
  SQL's own LIMIT says that more rows may match (in the lab "61 of the 100 failures" were 100 rows of
  358).
* A question of many parts (a manager's summary of five figures) gets half as many tool calls more;
  a tool call the model writes as text when its calls are used up is not shown as the answer (the
  results it had are); the instructions tell to compare periods one query per period.
* Charts the agent saves or changes get the query context Superset's front end would save (Superset's
  MCP service saves none, so their data API, CSV and text reports failed with "Chart has no query context
  saved"), mixed charts with their two queries; a chart made in Explore keeps its own; a chart type it
  cannot be written for keeps none.

## 0.5.0 (2026-09-29)

* **Context**: every night (after the day's learning) the agent writes the system's documentation,
  *Functional* and *Technical* (Data dictionary -> Context), from what the team shares (documents and
  sites, catalog, team memory, data dictionary, Helpful answers; not the raw chats). Facts pages are
  written without the LLM (each data source, each inventory of servers, services, applications,
  environments, regions, clusters and teams, the glossary, the rules and facts); summary pages (how
  the system works, the technical overview, one page per main application) by the LLM from the
  evidence only, citing it, marked AI-written, and only when their evidence changed (at most
  `context.max_llm_calls` calls per build). A page is shown only to the users who may query every
  database it draws from; admins correct pages (never written over); the agent finds them in its
  knowledge search, below the catalog and the documents. `superset supagent context --build`.
  Tables: `superset supagent init` adds `supagent_context` (schema 5).
* **Data dictionary**: a *Knowledge* tab (the catalog, the documents and sites, the team memory, read
  only) and, in the *Learned* tab, what the agent learned by itself (its catalog entries with their
  evidence, where the data of the questions was found, the relations measured, the AI descriptions
  to verify), each filtered by the databases the user may query. The long lists (query timings,
  changes, relations, and the runs of the settings page) come in pages, like Browse.
* `superset supagent prompt "question" --user U`: what the LLM is given for a question (the team's
  rules, the user's and the team's memory, where the data is with its descriptions, the knowledge
  found: documents, catalog, Context, learned answers), without asking the LLM. A test checks, end
  to end, that each of them reaches the LLM, and nothing the user may not see.
* **Nothing the team puts in is missed, nothing given twice**:
  * a description written in the Data dictionary, a catalog entry saved, deleted, restored or
    imported is used by the next answer on every server (a knowledge stamp in Superset's database
    makes each web server and worker read the dictionary, the catalog and what not to use again,
    instead of after 1 to 5 minutes), and the agent's search finds it at once (its pieces written
    and embedded straight away; before: at the next learning run). A description the catalog no
    longer gives is taken back (unless a person wrote another one since);
  * the team's words: the glossary terms of a question (their words, a code such as D-1 or W-4 that
    their definition uses, the terms they name) are given in full with the question, before where
    the data is; each term is also its own piece of the search (the whole glossary was one piece,
    rarely found);
  * the knowledge found with a question no longer repeats what the other parts give (a metric of
    the same name in two databases, the metrics of "Where the data is", the learned answers, the
    memories, the team's rules): its room goes to the catalog, the documents and the Context (a
    Context page counted as found much lower than it was; now at most two, the page about a subject
    of the question first);
  * the columns the OpenSearch connector computes (the business-day label and time of osagg) are in
    the dictionary with what they are, and the catalog's descriptions reach them;
  * saving a memory or a document no longer reads the whole dictionary again.
* `superset supagent check-knowledge`: is everything the team put in given to the agent? Pieces out
  of step, pieces without a vector, catalog entries ignored (invalid) or in conflict, names the
  catalog describes that the dictionary does not have (misspelled, or not learned: their text reaches
  nothing), rules not given in full, what waits for an admin. Exit code 1 when there is a problem.
* **Numbers checked**: every number of an answer must come from what the agent was given (a value
  of a query result, as shown or rounded, a share as a percentage, seconds in minutes, bytes in GB, a
  column's total or average, the total of its first rows, a row count, a rate within a row, a
  duration between two times; the question's, the chat's and the knowledge's numbers). Otherwise the
  agent is asked once to take it from a query (totals, rates, differences computed in the query),
  and a number still made up is marked in the answer. Replayed on the lab's 271 stored answers, it
  caught totals added up wrongly (7,014 or 6,461 failed jobs for 7,011). Setting
  `agent.check_numbers` (on).
* **The team's rules are applied**: in the lab the model ignored a catalog rule ("exclude UAT unless
  asked") in 4 answers out of 4, although it was in its instructions. The rules now also come next
  to the question (in full when short) and win over the learned answers; and a rule that filters on a
  field or label and asks for it (exclude, only, unless, never...: `ENVIRONMENT_TYPE = 'UAT'`) is
  checked on the queries: a query on data that has that field and does not use it sends the answer
  back once, then the answer is marked (unless the question asks for the rule's value); a rule that
  only says what a value means ("KO = failed") is never checked that way.
* **Names too**: a server, host or other name with digits that the answer writes must come from what
  the agent was given (in the lab it answered "srv-amer-000 through srv-amer-199" after seeing 25 of
  the servers: the series was continued, and wrong).
* **A value that does not exist** ("the jobs of ZEPHYR"): a count of 0 now comes with the
  dictionary's note that the value is not one of the field's values, so the answer says so instead of
  "0 jobs failed".
* **LLM usage page** (admins: the *LLM usage* tab next to *Settings*): every call to the LLM is recorded
  with what it was for (the answers in the chat, the daily learning, the Context, the memory, learned
  answers, the agent catalog, tidying, tests), for whom, its model, its context size (tokens sent), the
  tokens written, how much came from the LLM server's prompt cache, its time, and whether it failed. The
  page shows them for a period (the last 24 hours, 7, 30 or 90 days, or dates; by hour or by day, in
  the viewer's time zone): totals, tokens or calls over time by task, per person, per task, per model,
  the answers (time, LLM and tool calls per answer, answers sent back by the checks, answers marked),
  the biggest contexts and the slowest answers. Calls are kept `usage.keep_days` (90). Table
  `supagent_llm_call` (schema 7: `superset supagent init`).
* **Fixed**: a data source's Context page listed its links with the other data sources, naming their
  metrics to users who may not query them; the links are now pages of their own, seen only by the users
  who may query both databases.
* **What is happening now**: "what is happening in production / with an application / on this metric,
  chart or dashboard", "is everything normal" get a procedure and the tools for it: the dashboards and
  charts about the subject (Superset's charts and dashboards are now part of the knowledge: what each
  shows, its dataset, metrics, filters, the dashboards it is on; seen only by the users Superset lets
  open the chart, or the dashboard and all its charts), their latest data (`get_chart_data`), the team's
  checks and limits, the alerts
  firing, the comparison with the usual (the same window of the previous weeks), and a screenshot of
  a chart that shows a problem.
* **Follow-ups get the tools they need**: "what charts are in it?" after a question about a dashboard
  had no Superset tool (it named no chart nor dashboard); a question that refers back now gets the
  tools and instructions of the one it refers to. A saved chart must have a name saying what it shows
  and its period (Superset's automatic names repeated "Sum(x) by y" for two different charts).
* **More of Superset's MCP tools**: save a query in SQL Lab (`save_sql_query`), a link that opens SQL
  Lab with a query (`open_sql_lab_with_context`), a link to explore a dataset (`generate_explore_link`),
  the data of an existing chart (`get_chart_data`), offered when a question asks for them; an answer
  saying a query was saved in SQL Lab is checked like a chart or a dashboard. After a chart is saved or
  changed, the agent is told what the saved chart returns (rows, first values), so that its answer
  describes the chart, not the intent; a chart of a period on a table must filter that period.
* **Mimir tenants**: `__tenant_id__` usually separates applications or subjects: the agent filters on
  the tenant a question is about, groups by it to compare, never adds tenants up unless asked, and
  names them; "Where the data is" lists a metric's tenants, and the Context inventory has a Tenants
  section.
* **The Context stays short with a big dictionary** (10,000 metrics, 80,000 labels): a data source's
  page lists the 25 metrics and indices that matter (a person's description, the catalog, the ones the
  answers used and the learned answers), the rest counted by domain, not every description.
* **Results named, tries not shown**: an answer's results were shown as "Result 1", "Result 2"... with
  nothing to tell them apart. A query run again in the same shape (the same table, columns and time
  window: fixed after an error, a check or a rule) now replaces its earlier try (still listed in the
  answer's tool calls) when it only adds conditions; other conditions (PROD, then UAT) are a comparison
  and both stay. Each result is named by what it shows ("FAILED by APPLICATION · 23 Sep", "CPU busy %
  over time · 23 Sep 00:00-08:00"); two results of the same name say what differs (their filters).
* **A reply the LLM server cannot read** (a tool call of 53,000 characters, cut): the model is asked
  once again with short arguments instead of the answer failing with an HTTP 500; after that, it says
  what it did. An aggregate inside an aggregate on the metrics (`AVG(SUM(...))`) now comes with the way
  to write it (the ratio of the two sums is already the share over the window; the 5 busiest with
  ORDER BY ... LIMIT 5).
* **Dashboards of several charts**: the agent has twice the tool calls when it builds charts and
  dashboards, is told not to spend them re-checking the data, and when the calls run out it writes
  what it saved (with the links) and what remains, instead of "stopped after too many tool calls".
  A dataset on OpenSearch whose SQL has an ORDER BY could not be created (osagg turned the LIMIT 0
  Superset adds into a top-0 request that OpenSearch refuses): the dataset's SQL is wrapped.
* **AI descriptions**: a unit is written only when the name spells it or the values prove it (in the
  lab a duration in seconds, named `..._d`, was described "in days"); in "Where the data is" an
  unverified AI description is marked as such.
* **The agent asks when a question can mean two things** that give different numbers (two fields or
  metrics that fit, a term nobody defined): one short question naming the readings and the one it
  would take, instead of guessing; otherwise it says in one line which reading it took. The user's
  answer is learned (a team definition, for an admin to approve).
* **No copies in the team's knowledge, and a real Delete**: writing again a memory that exists gave a
  second one (removing a memory only disabled it, and the next one was a new copy); a catalog entry
  could be created twice. Now a memory written again is the same one (brought back if a person writes
  it after it was disabled; one learned again from a chat stays refused), Delete removes a memory for
  good (the user's own, or any for an admin, with *Delete* in the settings' Team memory list; *Disable*
  keeps one unused), `superset supagent init` merges the copies already there, and the catalog refuses
  a second entry of the same title, or of the same classification and content ("edit that one").
* **Not helpful, and why**: after Not helpful, the chat asks what was wrong (optional). The reason is
  shown to the admins (`superset supagent gaps`) and what it says about the data is proposed to the
  memory. Column `feedback_reason` (schema 6).
* **The chat panel on Superset's pages**: with a long conversation open, the buttons Conversations,
  New conversation and Memory scrolled out of sight (the panel's page grew with the conversation);
  now only the messages scroll.
* **Fixed (0.4.8)**: "not used" was also read inside an explanation ("mode idle = unused" in the
  description of a CPU metric made the agent refuse that metric). It now counts only when the
  description, or one of its sentences, starts by saying so.

## 0.4.8 (2026-09-29)

* **Learning much faster on metric names with dots**: the batched Mimir requests (series counts,
  depth of the history) escaped a dot in a way PromQL refuses ("unknown escape sequence"), and every
  batch with such a name fell back to one request per metric (the history: about 7 per metric).
* **No more paying twice for label descriptions**: labels found on newly profiled metrics take the
  description of the same name in the same database (a person's first) without an LLM call; the
  descriptions show the LLM calls and tokens apart from the copies.
* **Steps of a run**: every run lists what it did, step by step (per database: listed, new, due,
  profiled, requests, errors, batches read one at a time with their first error, history, changes
  by type; then descriptions, relations, catalog, categories, agent catalog, generic questions,
  search index, check), with times and durations, also for a run in progress and for the step a
  stopped run was doing; each step is also in the server log. "Objects learned or updated" (which
  counted every object seen again) is replaced by the new objects found.
* **The search index no longer embeds every metric again after each run**: its text had the series
  count and sampled label values, which change every run.
* **"Not used" is honoured**: a person's description saying a field, label, metric or index is not
  used keeps the agent from proposing it and from querying it (a query or chart that uses it is
  refused with the team's words).

## 0.4.7 (2026-09-29)

* **Questions about an earlier answer**: "create the chart in Superset of that finding" was
  answered from the question's own few words (the agent looked for other data, and saved a chart
  of something else). Now the agent is given, with the new question, what the last two answers
  were computed from: the queries that gave their rows (tool, database, SQL or PromQL, time window,
  columns; a query only written in an answer's text is marked as not run), and a question that
  refers back looks for the data of the question it refers to.
* **CPU usage** hints give the busy % (`100 * SUM(rate) FILTER (WHERE mode <> 'idle') / SUM(rate)`)
  for CPU-seconds metrics with a `mode` label: the sum of every mode is the number of cores, which
  an answer about "CPU usage" could show as a flat 4.00.
* **Charts of a calculated finding**: a percentage, a ratio or PromQL is saved as a Superset
  virtual dataset (`create_virtual_dataset`, only offered when a chart is asked; PromQL through
  promagg's `promql()`), then charted with the finding's time range. The tool checks the Dataset
  write permission (and database access for `promql()`), lets Superset check the SQL's tables, and
  gives back the same dataset when asked again. A chart field that does not exist now points to it.
* **Stop learning is immediate**: the run is marked stopped at once (also one whose process
  died), and *Learn now* starts a new one right away (before: "stopping" until its next step, which
  could be the end of a long LLM call, and a new run waited). The run also stops while it waits for
  the last descriptions or for the people's answers.

## 0.4.6 (2026-09-29)

* The same code as 0.4.5, published under a new version number (a package mirror that
  had kept 0.4.5 as not found fetches 0.4.6 as new). Everything below 0.4.5 applies.

## 0.4.5 (2026-09-29)

* **Celery workers without Redis, several web servers and workers**: the workers can use
  Superset's own database as their queue (`broker_url = "sqla+" + SQLALCHEMY_DATABASE_URI`, five
  lines in `superset_config.py`, see *Celery workers and beat*). Every worker writes a heartbeat
  in Superset's database (every 30 seconds, removed when it stops), so `agent.executor` = `auto`
  sees the workers with any broker (a queue in a database cannot carry Celery's ping), and the
  settings page counts them.
* **One question, one answer**: a question is answered by the first process that starts it (worker
  or web server), the others leave it; a busy worker leaves the next questions to the other
  workers. In `auto`, a question no worker started within 15 seconds is answered by the web server
  that received it; with no worker alive, the web server answers at once.
* `agent.queue_keep_days` (default 90): the delivered messages of a queue in Superset's database
  are deleted after that many days (Celery never deletes them), with the heartbeats of workers
  gone for a day, by the hourly tick.
* **Learning**: the databases never learned come first, each database gets a fair share of the
  time left (a database of thousands of metrics no longer keeps the others waiting for days), and
  the runs list shows, while the run goes, the database being learned, the ones still to come and
  the ones left out with the reason (before, only at the end of the run). One run at a time for
  all the hosts (a row lock while a run starts).
* A file made by an earlier answer (Excel, chart image) is found by the next answer on any worker
  or web server (it is kept in Superset's database), for the same user only.

## 0.4.4 (2026-09-29)

* **AI descriptions during the learning**: the LLM describes what has no description while the
  databases are read (the learner waits for the databases most of the time: the LLM works
  meanwhile), as the metrics and indices are learned, instead of after a database (0.4.3) or after
  the whole run (0.4.2). A Mimir of thousands of metrics that takes two hours to learn gets its
  descriptions during those two hours. Once every database is read: the relations between them
  all, the catalog, then the descriptions still missing with the time left.
* A run in progress shows in the runs list how many objects it learned or updated, and how many
  AI descriptions it wrote so far.

## 0.4.3 (2026-09-29)

* **Every database is learned, and a run says which ones it left out and why**: each run lists
  the osagg and promagg databases it did not learn, with the reason (not in `learn.databases`,
  or the learning user `learn.user` may not read it), and the names of `learn.databases` that
  match no database; so does `superset supagent learn --plan`. (A run learns every osagg and
  promagg database the learning user may read, unless `learn.databases` lists some.)
* **Descriptions during the learning, database by database**: each database is learned then
  described by the LLM (after the catalog), with a fair share of the time left, before the next
  database; the relations between them all are measured at the end, and the time left goes to
  the descriptions a database's share did not reach. The runs list shows each database's
  descriptions.
* **Stop learning**: a button on the settings page (and `superset supagent learn --stop`) stops the
  running run at its next step; it keeps what it learned and ends as "stopped", and *Learn now*
  starts a new one as soon as it stopped (a run whose process died does not block the next one
  for more than a minute and a half).

## 0.4.2 (2026-09-29)

* The chat panel's ⤢ button opens the full chat page again (in 0.4.1 it closed the panel: it was
  taken for a click on the Chat tab).

## 0.4.1 (2026-09-29)

* **The chat beside Superset's pages**: the Chat tab of the top bar no longer leaves the page: it
  opens the chat as a panel on the right, and the dashboard, chart, dataset or SQL Lab page stays
  usable beside it (it narrows to make room). A link to Superset in an answer (a chart, a
  dashboard) opens in the page while the chat stays open; other sites open in a new tab. The
  panel stays open from page to page in the browser tab, can be resized by dragging its left
  edge, and follows Superset's light or dark theme. Ctrl+click on the tab, or the panel's ⤢
  button, still opens the full chat page. Only for the users who may chat; never on embedded or
  standalone dashboards. Added through Superset's own place for custom page scripts
  (`tail_js_custom_extra.html`, kept as the deployment has it): nothing to configure.

## 0.4.0 (2026-09-29)

Faster answers, fewer wasted calls, learning runs that never block, and commands to measure it.
Nothing added to the pages or the chat; the same install (pip, `superset supagent init`, restart).

* **The instructions stay in the LLM server's prompt cache**: what is found for a question (where
  the data is, the knowledge, the learned answers, the user's memories) now comes with the
  question instead of inside the instructions, which (with the tools) are the same from one
  question and one user to the next. Measured on the lab LLM (llama.cpp): the first step of an
  answer processed 4,500-4,700 prompt tokens in 25-27 s; now 1,300-1,550 in 9-11 s (3,188 from
  the cache).
* **An empty result says why**, from the data dictionary (no extra query): a value in the wrong
  case ("'failed' is written 'FAILED'"), not a value of the field or label (the closest ones), a
  time window before the data starts or after it stopped.
* **No call twice**: an identical call that succeeded is not run again in the same answer
  (reading again after a save is allowed).
* **An empty LLM answer** is asked again twice; still empty after a query succeeded, the answer
  shows that result instead of failing.
* **An answer that announces a step without taking it** ("Let me run the query.") is sent back
  once; offers ("if you want, I can...") are not.
* **All-clear claims are checked**: an answer that says all is well while a check or a query it
  relies on could not run gets a one-line correction.
* **compare_to_usual**: is a metric unusual for this time? The same window on the previous weeks
  (median and median absolute deviation per series: normal, high, low; unknown with fewer than
  three weeks). Offered when a question asks ("unusual", "higher than usual", "anormal"...) and in
  investigations.
* **Where the data is, learned better**: associations no answer used for 60 days, or to a metric
  or index that is gone, are not used; one that sent the agent to data that was not there (an
  error, no rows, while the answer came from elsewhere) loses a use. Learned answers and memories
  naming a metric or index that no longer exists are not given to the agent.
* **Better matching**: failed / failure / failing, alerting / alerts, throttled / throttling meet
  (stems of at least four letters; `init` stems the stored words again); a match on a rare word
  (elasticsearch) counts more than one on a word hundreds of names have (node).
* **Knowledge search**: a piece found by meaning only must be close enough (cosine 0.35, within
  0.2 of the closest); each result of `search_knowledge` says which search found it.
* **Learning runs never block at the end**: `learn.llm_per_run` is gone. The LLM describes what
  has no description 100 objects at a time (10 per request, each request saved at once), metrics
  and indices first, until the run's time limit; the next run goes on. A label is described once
  per database for every metric that has it (not once per metric). The relations are measured
  reading the objects in steps (never tens of thousands of labels at once) and written 100 at a
  time; a relation marked Wrong holds for the label name of every metric (the first run of 0.4.0
  may measure some relations again: the label that stands for a name is now always the same);
  the rewriting of older learned answers stops at the time limit too.
* **People first**: the background LLM work (the daily learning, learned answers and memory from a
  Helpful) waits while answers are being computed (2 minutes at most per call).
* **Measure it**: `superset supagent stats` (where the time of the answers goes, prompt sizes,
  prompt cache share, slowest answers), `superset supagent evaluate` (does "Where the data is"
  find the data of the Helpful answers: hit@1, hit@3, MRR; also after each learning run),
  `superset supagent gaps` (questions not answered well, learned answers about data that is
  gone), `superset supagent test-llm --profile` (thinking, tool calls, prompt cache).
* `chats.keep_days` (0, the default: keep): chats nobody used for that long go; what they taught
  stays.
* Run `superset supagent init` (one new table; the stored words are stemmed again).

## 0.3.0 (2026-09-28)

Faster, surer answers: the agent is told where the data is, gets short strict instructions and
only the tools the question needs, and learns where the data was from its own answers.

* **Where the data is, before the LLM starts**: the metrics, indices and fields whose names
  (split on `_ : . -`), HELP texts, descriptions and synonyms match the words of the question,
  with built-in synonyms (cpu / processor, mem / memory, es / elasticsearch, disk / fs, French
  words...), are given to the agent with their database id, type, unit, labels and a SQL to
  adapt. It uses the live list of metric names, so it works while the dictionary is empty or
  still learning (10,000 names: well under a second), and only the databases the agent may use
  and the user may query.
* **Learning where the data is from the answers** (`learn.associations`, on by default): the
  words of a question and the metrics or indices its successful queries read; the next
  questions with those words find them first. *Not helpful* takes them back. These are not
  learned answers (that list still only holds what users marked *Helpful*); switch it off with
  `learn.associations = false`.
* **Short, strict instructions**: the rules every answer needs (about 40% shorter), then only
  the sections the question asks for (saving charts, investigations, files / e-mails / reports,
  images); in the chat, the tools that save charts, make files, e-mails, reports or images are
  offered only when the question asks for them. One query when possible; a failing call is
  fixed once, never repeated, and after two failures the agent answers with what it has.
* **The chat draws the charts**: to "see a chart", the agent runs the query (the page shows it
  as a table and a chart); `chart_from_sql` (images) is not offered without Chromium on the
  host, nor `chart_image` without a webdriver.
* **Databases**: every tool takes a database id or name (in any case, or with a letter wrong);
  a SQL on a metric or on `all_metrics` goes to the metrics database; the agent uses only the
  OpenSearch (osagg) and Prometheus / Mimir (promagg) databases unless `agent.databases`
  lists others.
* **Statements are knowledge**: a message that tells something ("STATUS_INFO = KO means the job
  failed", "this metric is the CPU of the cluster nodes") is read for durable facts and rules
  (team ones wait for an admin's approval, `memory.team_approval`).
* **Memories within a budget** (`memory.prompt_chars`, 2,000 characters): the memories given with
  every question are the rules, then the preferences, then the facts; the facts left out are
  still found by the knowledge search when a question is about them. Statements are learned
  now, so the block no longer grows with them.
* **Extracts hold every row**: an Excel extract gets no LIMIT unless the user asks for the first
  N, and when the SQL's own LIMIT is reached the tool says so (the agent runs it again without
  it). Before, an extract could stop at the LIMIT of the tool's example while the answer said
  "all the rows".
* A table name that is no index or metric (in a JOIN too) is named in the error, with the
  closest names, instead of "JOIN not supported" or "Did you mean pg_prepared_statements".
* The knowledge search is updated during a learning run (every 500 metrics, and after each
  database), not only at its end. `describe_data` no longer shows unknown time ranges.
* Run `superset supagent init` (one new table).

## 0.2.5 (2026-09-28)

* **Learning again from scratch**: `superset supagent forget-learned` shows, per database, what
  the learning learned (nothing changes without `--yes`); `--yes` forgets it (dictionary
  objects with their statistics and AI-written descriptions, measured relations, history of
  changes) for every database or those given with `--database`, and the next run learns them
  again as new. The catalog entries, learned answers, query timings, memory, documents, chats
  and settings are kept, and so is what admins did in the Data dictionary page (descriptions
  written or approved there, synonyms, relations marked Wrong); `--everything` forgets that too.

## 0.2.4 (2026-09-28)

* **The pages load their new files after an upgrade**: Superset lets browsers keep static files
  for a year, and supagent's URLs did not change with its files, so a browser could keep the
  former CSS with the new theme script: a half-dark page (dark bubbles with dark text on a light
  page), and former JavaScript fixes missing. Every CSS and JavaScript URL now has its content
  hash. (One Ctrl+F5 is enough for browsers that already hold the former files.)
* **Thousands of metrics are learned in a few runs**: the series counts of 50 metrics come from
  one query, the labels of metrics with a few series from one shared request, and each metric
  has one statistics query of its own: about one request per metric instead of about ten for a
  new one. The start of the data (the depth of the history) is looked up afterwards with the time
  left, about 8 label-index requests per 50 metrics instead of about 7 per metric. Checked on the
  lab Mimir: the same series counts and label values as before for all 28 metrics; 3,000
  metrics in the tests: 60 count queries, 3,000 statistics queries, 60 label requests, 60
  history requests. `learn --plan` gives the new estimate and the history lookups apart.
* **The settings page says why a run is partial**: "N of M due today profiled; stopped at the
  time limit (learn.max_minutes): the next run continues"; history lookups left for later do not
  make a run partial.
* **Wrong relations**: an admin marks a measured relation **Wrong** in *Data dictionary →
  Relations*: it is never measured again nor given to the agent (**Restore** undoes it). A
  catalog entry of classification *relationships* states the right one. Run
  `superset supagent init` (two new columns).

## 0.2.3 (2026-09-28)

* A chat whose first message is not a data question (a greeting) is now named too; before, it
  stopped `superset supagent tidy-learned` (and the daily renaming) from naming the other chats.

## 0.2.2 (2026-09-28)

* **Stop works at once, and no chat is blocked**: Stop marks the answer stopped immediately and
  the chat takes the next question right away (it answered "the previous question is still
  being answered" until the step in progress ended). The run that was in the middle of an LLM
  call or a query never writes over the stopped answer and learns nothing from it. The chat
  page kept checking a stopped answer after another chat was opened, which turned *Send* into
  *Stop* in every chat: fixed.
* **Many users at once**: a running answer held one connection of Superset's database pool for
  its whole duration (idle in a transaction while it waited for the LLM); with many answers at
  once the pool ran out and every page hung. It now holds none while it waits. There is no
  one-at-a-time limit in supagent: see *Operations* in the README for what sets the number of
  answers in parallel (the LLM server, Celery's concurrency, the web server's workers).
* **Learned answers come only from Helpful**: an answer is no longer learned by itself. *Helpful*
  learns it (in the background: the LLM writes its generic question) as *helpful, to review*;
  an admin confirms or rejects it; *Not helpful* or taking *Helpful* back withdraws it unless
  an admin confirmed it. Upgrade (`superset supagent init`): the 0.2.x learned answers users
  had marked Helpful wait for review, the ones an admin had confirmed stay confirmed (told apart
  by their Helpful clicks: an admin-confirmed one that users had also marked Helpful goes to
  review too); the ones saved by themselves are kept but no longer listed nor used, and
  `superset supagent remove-auto-learned` deletes them.
* **Learned answers and chats are named by a short generic question** that the agent writes:
  standalone even when the message only continued or corrected an earlier one, without the
  ids, dates or names of one case ("Number of failed jobs for a given application on a given
  day"), in the user's language. Ids, numbers and dates never stay (checked, sent back once,
  then replaced); names are sent back once. The agent also says whether a question already
  learned asks the same thing: the answer then joins it instead of making a duplicate. The
  first answer of a chat gives it a 2-6 word generic name. `superset supagent tidy-learned`
  rewrites older learned answers and chat names and merges duplicates (the daily learning
  does it too).
* **The agent knows the limits of osagg and promagg** (they are not full SQL engines): what each
  can run is in its instructions and next to each database it lists; refusals come with how to
  rewrite the query (in steps, or pairs of values as `(A = x AND B = y) OR ...`). A query osagg
  cannot push down may read at most `agent.osagg_max_scan_rows` raw documents (20,000; the
  connection's own cap if lower): osagg counts first and refuses at once instead of reading
  hundreds of thousands of documents for minutes. On the lab, a question that took two refused
  queries now takes none.
* **Query timings show the whole query** (values replaced by `?`) with its last error; admins
  also see the last one as it ran.
* **The pages follow Superset's theme**: the mode chosen in Superset (light, dark or system),
  always light when Superset has no dark theme (`THEME_DARK = None`), and Superset's primary
  color. They followed the operating system only.

## 0.2.1 (2026-09-28)

* Metadata databases that are not UTF-8 (PostgreSQL created with LATIN1, MySQL without
  `?charset=utf8mb4`): answers and learning runs failed with "'latin-1' codec can't encode
  character '\u2013'" as soon as a text held a character the database cannot store (LLMs
  write – — ‑ ’ “ ” … all the time). supagent now finds the encoding of the connection once
  and folds what it writes: – → -, ’ → ', … → ..., blocks → #, letters outside the encoding
  lose their accent, the rest becomes ?; accents the encoding has (é, à, ç) are kept. Nothing
  changes on a UTF-8 database. Names the agent saves in Superset (charts, dashboards, reports)
  are folded the same way, and downloads keep any file name.

## 0.2.0 (2026-09-28)

Built for millions of index rows and billions of metric samples, and for learning from the team.

* **Gentle daily learning**: one run per day (`learn.hour`, `learn.days`), a cheap daily pass
  (metadata and mappings), statistics refreshed on a rolling basis (`learn.profile_every_days`),
  about 3 requests per metric, dated and rolled-over indices learned as one family, batched
  field statistics, a rate limit per database, timeouts, and a stop after repeated overload
  errors. `superset supagent learn --plan` estimates a run without reading data.
* **Catalog in separate entries**: title, classification, category and content, each with its
  history (restore, soft delete), checked before saving (YAML errors with line and column),
  protected against concurrent edits; import (merge or replace) and export. A person's entry
  always wins over one the agent wrote. The 0.1 catalog is split once, kept as a backup.
* **The agent writes catalog entries when the evidence is certain** (`learn.agent_catalog`):
  formulas of answers confirmed as helpful, team rules and facts approved by an admin,
  definitions quoted word for word from the documents. Marked *agent* with their evidence;
  taken back when the evidence breaks; never changed again once a person edits them, never
  written again once a person deletes them. `superset supagent agent-catalog`.
* **Learning from the answers**: the final query of each answer kept as a recipe (confirmed by
  *Helpful*, rejected by *Not helpful*) for similar questions of the team; query timings per
  kind of query; big results summarised for the LLM (the user still gets every row); raw reads
  of metrics with more than 50,000 series refused with advice.
* **Answers from the tools only**: an answer with no tool call, or showing results no query
  returned, goes back to the model once (and is marked if it still does); `SUM` / `AVG` of a
  counter's raw value is refused with the right way (`rate`, `increase`, the catalog's
  formulas); query results reach the model with their column sums, and it must quote them
  rather than add numbers up; `check_health` says when its entities match nothing instead of
  "no breach"; `send_email` does not attach the same extract twice.
* A learning run stopped by a restart is marked *interrupted* and the day's run is tried again
  (3 times a day at most); a metric whose data stopped costs 2 lookups instead of a bisection.
* **Memory**: preferences of a user and rules and facts of the team, learned from explicit
  signals ("always", "from now on", "remember", "toujours", "désormais"...) and *Helpful*
  answers; team memories wait for an admin's approval (`memory.team_approval`). *Memory* drawer
  in the chat, team memory on the settings page.
* **Knowledge search**: words (PostgreSQL full-text search) and meaning (an OpenAI-compatible
  embedding model such as BGE-M3; vectors as float16 in Superset's database, or Qdrant), fused;
  only what the user may see is searched. No database extension (no pgvector).
* **Documents and sites**: uploaded text, Markdown and HTML, web pages and sites fetched again
  every N days, with allowed domains and size limits.
* Data dictionary: a search tab and the learned answers with their timings.
* New dependency: none (numpy and requests come with Superset).

## 0.1.0 (2026-09-27)

First version: the agent inside Superset.

* Chat page: the **Chat** tab of Superset's top bar (the dictionary and the settings are in
  Superset's Settings menu). Answers come from Superset's Celery workers, or from a thread
  of the web server when no worker runs, with the permissions of the user who asks. Tools
  run in-process: SQL, the learned dictionary, Excel extracts, screenshots of charts and
  dashboards, e-mails, scheduled reports, PromQL, health checks, alerts, and Superset's MCP
  tools for charts and dashboards, behind a check that the MCP service acts as the user who
  asks.
* Result views: the rows of every query as a table (sortable) and a chart (lines over time,
  horizontal bars for rankings, figures for one row), with copy, CSV, Excel and PNG. Files
  are kept in Superset's database. Copy buttons on questions, answers, SQL and code blocks.
  Stop button. *Helpful* keeps the SQL as an example for similar questions.
* The data dictionary learned every day. For indices and fields (osagg): type, fill rate,
  values, ranges, time range. For metrics and labels (promagg): type, unit, HELP text,
  series, data range, rates, percentiles, label values. It also keeps the measured relations
  with their evidence, metric families, the catalog (curated, verified), LLM descriptions
  (marked unverified) and the changes from run to run.
* Admin settings: LLM authentication `none`, `token` or `middleware` (OAuth2 client
  credentials with consumer key and secret, a client certificate, and a token renewed before
  it expires). Learning schedule and scope, catalog import, learning runs, test button.
* `superset supagent` commands, and the MCP server mode for other agents.
* Chat details: every question and answer shows its date and time (and a running answer the
  time spent); a tool list opened during an answer stays open.
