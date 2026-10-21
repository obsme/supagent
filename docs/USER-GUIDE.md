# supagent user guide

For supagent 0.11.0 on Apache Superset 6.1.

This guide explains every page, button and setting of supagent, and how to use them. It is written for the
people who use the chat, the people who look after the agent's knowledge, and the administrators who run it.
Each section can be read on its own:

* people who only ask questions: sections 1 and 2;
* people who curate the knowledge (Editors): sections 3, 6 and 9;
* administrators: every section, especially 4, 5, 7, 8 and 9.

Installation and upgrades are not covered here: see `INSTALL.txt` and `README.md` in the delivery.

## Contents

1. [What supagent is, and the three roles](#1-what-supagent-is-and-the-three-roles)
2. [Quick start for a user: the chat](#2-quick-start-for-a-user-the-chat)
3. [The Data dictionary, tab by tab](#3-the-data-dictionary-tab-by-tab)
4. [The Settings page](#4-the-settings-page)
5. [The LLM usage page](#5-the-llm-usage-page)
6. [How the agent works (for admins)](#6-how-the-agent-works-for-admins)
7. [What is cleaned automatically, and when](#7-what-is-cleaned-automatically-and-when)
8. [Command line reference](#8-command-line-reference)
9. [Troubleshooting and FAQ](#9-troubleshooting-and-faq)

---

## 1. What supagent is, and the three roles

supagent is an AI agent that runs inside Superset. You ask it a question in plain words ("how many orders failed
yesterday, by payment method?"). It searches what the team knows about the data, runs the queries, and answers
with the key figures and with the query results shown as tables and charts. It acts with **your own Superset
permissions**: it sees only the databases, datasets and charts that you may see, and Superset's row-level
security applies to it.

It is installed as a Python package in Superset's virtualenv. Nothing else runs beside Superset: the pages are
served by Superset itself, the work runs in Superset's Celery workers (or in the web server when there is no
worker), and everything is stored in Superset's own database.

What it adds to Superset:

| Page | Where you find it | Who |
|---|---|---|
| **Chat** | The robot at the bottom right of Superset's pages (or the **Chat** tab of the top bar, with `agent.launcher` = tab). It opens as a panel beside the page you are on, or as a full page (`/supagent/`). | Everyone with a role of the agent |
| **Data dictionary** | Superset's *Settings* menu, section *Manage*, then **Data dictionary**; also the *Data dictionary* tab at the top of the chat page. | Everyone with a role of the agent (read); Editors and Admins (write) |
| **Chat settings** (the Settings page) | Superset's *Settings* menu, section *Manage*, then **Chat settings**; also the *Settings* tab of the chat page. | Admins |
| **LLM usage** | The *LLM usage* tab at the top of the chat page, next to *Settings*. | Admins |
| **Command line** | `superset supagent ...` on a Superset host. | Administrators of the servers |

The top bar of supagent's own pages shows the tabs you may open, the supagent version and the account the agent
acts as (yours).

What the agent works with:

* an **LLM**: any OpenAI-compatible chat API with tool calls (a company gateway, vLLM, llama.cpp...);
* optionally an **embedding model**, for a search by meaning as well as by words;
* the databases of Superset, first of all the **OpenSearch** databases (through the osagg connector) and the
  **Prometheus / Mimir** databases (through the promagg connector), which it learns every day;
* what the team gives it: a catalog of definitions and rules, a team memory, documents, wikis and repositories,
  notes, and optionally Grafana and OpenSearch Dashboards.

### The three roles

supagent has three roles. Their names depend on how your Superset was set up:

* **After `superset supagent init`** (the default): the roles **AI Viewer**, **AI Editor** and **AI Admin** exist
  next to Superset's own *Gamma*, *Alpha* and *Admin*. Each AI role carries both Superset's permissions (taken from
  Gamma, Alpha and Admin, as the table below says) and supagent's own: give a user one of them. The role **AI
  Agent** of older versions is kept as it was (chat, Data dictionary read, notes and memories for the team).
* **After `superset supagent roles --apply`**: there are only three roles, **Viewer**, **Editor** and **Admin**.
  The AI roles are merged into Superset's roles, and *Alpha* and *Gamma* are renamed *Editor* and *Viewer*.
  `superset supagent roles --undo` goes back. The setting `roles.simple` records which state you are in; never
  change it by hand.

In this guide, *Viewer*, *Editor* and *Admin* mean either name.

| What you can do | Viewer | Editor | Admin |
|---|:---:|:---:|:---:|
| Ask questions in the chat, read and download the answers, mark them Helpful or Not helpful, stop an answer, delete your own chats | yes | yes | yes |
| Write notes and memories for yourself | yes | yes | yes |
| Write notes and memories for the whole team or for a group (Superset group) | no | yes | yes |
| Read the Data dictionary: catalog, team memory, documents, notes, Context, what the agent learned, System map, data, search | yes | yes | yes |
| See the **To review** and **Categories** tabs, approve and correct what waits | no | yes | yes |
| Write the knowledge: catalog entries, team memory, documents and sites, descriptions of the data, categories and values, links of the System map, Context pages, learned answers, team notes | no | yes | yes |
| **Delete** knowledge: catalog entries, documents and pages of a document, values (reject an approved one, merge, retire), categories, links of the map, other people's notes and memories, learned answers | no | no | yes |
| The **Chat settings** page (LLM, learning, backups, all settings) and the **LLM usage** page | no | no | yes |
| Choose which Grafana and OpenSearch Dashboards dashboards the agent reads; create a drafted alert rule or dashboard in Grafana; read a category from a new field | no | no | yes |
| Superset itself | *Gamma* without anything that changes something; data: none unless given | *Alpha* and SQL Lab, without deletions | *Admin* |

Notes on the table:

* An Editor *proposes* the removal of a link of the System map (with a reason); an Admin decides. Everything else
  an Editor cannot delete, they can usually disable or reject instead (a memory, a learned answer).
* "Admin" for supagent means Superset's *Admin* role, or any role that has *can write on AIAgentAdmin* (the AI
  Admin role).
* The data a Viewer may query is given as Superset gives it (a role or a group per team). With
  `superset supagent init --viewer-data all` (setting `roles.viewer_data` = `all`) the Viewer role reads every
  database and dataset.
* Whatever the role, the agent never reads more than the user may read. Each user sees in the Data dictionary
  only what concerns the databases they may query, and a Context page only when they may query every database it
  is written from.

The Superset permissions behind the roles, for administrators who build their own roles:

| Permission | Viewer | Editor | Admin | What it opens |
|---|:---:|:---:|:---:|---|
| can read, can write on `AIAgent` | yes | yes | yes | the chat (asking, feedback, own memories and notes) |
| can share on `AIAgent` | no | yes | yes | notes and memories for the team or a group |
| can read on `AIAgentDictionary` | yes | yes | yes | reading the Data dictionary |
| can write on `AIAgentDictionary` | no | yes | yes | descriptions of the data, the map, Context pages, learned answers |
| can read, can edit on `AIAgentAdmin` | no | yes | yes | To review and Categories; writing the catalog, team memory, documents, categories |
| can delete on `AIAgentAdmin` | no | no | yes | every deletion of the knowledge |
| can write on `AIAgentAdmin` | no | no | yes | Settings, LLM usage, dashboard switches |

Giving a role from the command line: `superset supagent grant <user> [<user> ...] --role viewer|editor|admin`
(or Superset's own user list).

---

## 2. Quick start for a user: the chat

### 2.1 Open the chat

* **On any Superset page** (a dashboard, a chart, a dataset, SQL Lab): click the round robot at the bottom right of
  the page. The chat opens as a panel on the right; the page narrows beside it and its charts fit the width left.
  The **×** of the panel closes it, and the robot comes back. (With `agent.launcher` = tab in Settings, *Agent*, the
  robot is replaced by **Chat** in Superset's top bar, as before 0.11.3: click it to open and to close the panel.)
  * Drag the panel's left edge to make it wider or narrower (or focus the edge and use the arrow keys; Shift moves
    faster).
  * **⧉** floats the panel over the page: move it by its title bar, resize it from any edge or corner, double-click
    its title bar to make it as big as the window (and again to go back). **⇥** docks it again. In a window
    narrower than about 1,220 pixels the panel floats by itself (the page keeps at least 900 pixels); under 900
    pixels it takes the whole width.
  * **⤢** opens the chat as a full page. Ctrl-click, Cmd-click, Shift-click or a middle click on the robot (or on
    the *Chat* tab) does the same.
  * The panel stays open from page to page in the same browser tab. Links in an answer that lead to Superset open
    in the page beside the panel; links to other sites open in a new tab.
  * If the panel says "The chat cannot be shown here", open the full page with the link it gives (see section 9).
* **As a full page**: Ctrl-click the robot (or the *Chat* tab), or go to `/supagent/`. The full page has the tabs *Chat*,
  *Data dictionary* and, for admins, *Settings* and *LLM usage*.

The left column of the chat (behind the **Conversations** button in the panel) holds:

* **New conversation**: an empty chat with a few example questions to click;
* **Memory**: what the agent remembers for you and for the team (2.7);
* **Notes**: the team's notes and yours (2.9);
* **Search your chats**: type two letters or more to find your earlier chats by their words (and by meaning when
  the knowledge store is installed); a click opens the chat on the message found. Escape clears the box;
* your conversations, the latest first (your last 100). The agent names a chat after its first answer with a
  short generic title.

The chat that was open last time opens again when you come back.

### 2.2 Ask a question

Type in the box at the bottom and press **Enter** (or **Send**). **Shift+Enter** starts a new line. A question
may be up to 8,000 characters. Drag the top edge of the box to make it taller (or use the arrow keys on that
edge); double-click the edge to get the default height back.

Good questions name what you want, the period and the scope: "Top 10 checkout-api errors yesterday, by status
code", "Compare the orders of web-shop today with the same weekday last week". You do not need table or field
names: the agent finds them in what it learned.

One question at a time per conversation: while an answer is being written, **Send** becomes **Stop**. To ask
something else at the same time, open a **New conversation**.

Two short commands are saved at once without asking the LLM:

* `/note <text>`: a note for the team. A Viewer writes notes for themselves only: for them `/note` answers "your
  role (AI Viewer) writes notes for yourself only", and `/mynote` is the one to use;
* `/mynote <text>`: a note for yourself.

### 2.3 While the agent works

The answer's place shows what is happening: *Waiting for the agent…*, *Thinking…*, *Running <tool>…*, and the time
since you asked. Below it:

* **Work plan** (big requests: an investigation, a question of many parts, several charts or a dashboard, a long
  request): the tasks the agent keeps, each marked pending, in progress, done or dropped, with what it found;
* **N tool calls**: every step it took, with its name, its time and whether it failed. A knowledge search step
  says what was searched for, what was found, and a misspelled word it read otherwise ("'refunnd' read as
  'refund'").

An answer usually takes from a few seconds to a few minutes; an investigation ("why did the night batch run
late?") takes longer. After `agent.answer_seconds` (25 minutes by default) the agent is told to answer with what
it has found.

### 2.4 Read the answer

An answer has, from top to bottom:

* **Understood as** (when shown): the question as the agent read it, in the team's names. **Similar earlier
  requests (their way was reused)**: learned answers it started from. A general question (writing a script, what a
  technology means) says that it was answered without the platform's data;
* **the answer**: the key figures and what they mean. Tables in the text scroll sideways when they are wide (the
  first column stays in view); code blocks have a **Copy** link;
* **the query results**, one tab per result when there are several (its title and number of rows):
  * **Table** / **Chart**: bars for rankings, lines over time, figures for a single row. When several numeric
    columns could be drawn, a list chooses the one to draw. *Chart* is greyed when the rows cannot be drawn
    (hover it to see why);
  * **Copy** copies the rows (tab-separated: paste them into a spreadsheet); **CSV** and **Excel** download them;
    **PNG** downloads the chart as an image (shown when a chart is drawn);
  * the caption says the number of rows and the database; *first N rows here* when the page keeps only the first
    rows, *long values cut here* when long texts were shortened;
  * **SQL** or **PromQL** (folded): the query behind the result, with **Copy the SQL** (or *Copy the PromQL*);
* **files** the agent made: an Excel extract (**Download**, with its number of rows) or an image of a chart or a
  dashboard (**Download image**, **Open**);
* **Copy answer** (the whole text, also when the page shows only its first 60,000 characters), **Helpful**,
  **Not helpful**, and *Answered <time> · N s*;
* the **Work plan** and the **tool calls**, folded.

Your own question has **Copy** and **Ask again** under it. A failed or stopped answer has **Ask again**.

When you open an older chat, the query results of its last two answers are shown; an earlier answer shows **Show
the query results** to load its rows.

A thin line between questions marks the chat's **subjects**: *New subject* (the answer was given none of the
earlier messages) or *Back to: …* (the answer was given that earlier subject's messages).

#### The check notes

The agent checks every answer before you see it (section 6.4). Most problems are sent back to the model and fixed
without you seeing anything. When one remains, the answer ends with a short note in brackets that starts with
**(Check: …)**. Read it as a warning about the answer above, for example:

* "these numbers or names do not come from the results of this answer's queries: …": treat those figures as not
  verified;
* "no query ran in this answer: numbers or rows shown here do not come from the data": ask again to have them read
  from the data;
* "the team's rule "…" was not applied in this answer's queries";
* "the question names <value> (<field>); no query of this answer filters on it";
* "<n> is where the LIMIT of a query cut its rows, not a count: more rows match";
* "the question asks about the future; the figures above are past ones, not a forecast";
* "<part> named as a cause, but neither the system map nor this answer's results tie it to …";
* "the query shown here was not run in this answer";
* "<tool> could not run in this answer: what it covers was not checked";
* "no Superset chart was saved…", "no query was saved in SQL Lab…", "the e-mail was sent without an image…".

*(Cut: the model's text went round in circles from here.)* means the model repeated itself and its text was cut.
When a note matters, ask again or rephrase. Admins see how many answers kept such a note on the LLM usage page.

### 2.5 Download Excel

There are two ways, for two needs:

* **The Excel link of a result** gives the rows the page keeps of that result. The page keeps at most 3 MB of rows
  per answer (120 columns, 2,000 characters per value). That is enough for most answers; the caption says *first N
  rows here* when rows were left out.
* **Ask the agent for an Excel extract** ("an Excel extract of every failed order of last week, with the customer
  and the amount"). It runs the query again and writes a file of up to `tools.export_max_rows` rows (500,000 by
  default), shown in the answer with **Download**. Files are kept `tools.keep_days` days (7); a file larger than
  `tools.max_file_mb` (50 MB) is named but not kept.

The agent can also make an image of a saved chart or a dashboard, send an e-mail with an image or a file (to the
e-mail domains of `tools.email_allowed_domains`; any domain when it is empty), and save charts, datasets,
dashboards, SQL Lab queries and reports in Superset, when your Superset role allows it. Saving charts and dashboards
needs Superset's MCP service (see the status line of the Settings page).

### 2.6 Follow-up questions

The agent reads the earlier messages of the same subject with each question. You can say:

* "and yesterday?", "and on the 23rd?", "the same for checkout-api": the previous question again for that day or
  that value, with its conditions;
* "make a chart of that", "save that as a dashboard", "show me the SQL": about the last answers;
* "only production", "without the test orders": the previous answer narrowed;
* "continue": a big request takes up the tasks of its work plan that are left;
* "back to the orders question": an earlier subject.

When a question is ambiguous ("the late ones" at the start of a chat, a name several values match), the agent asks
back with the candidates instead of guessing. Answer in a few words.

A question about another subject starts a new subject: the agent no longer reads the earlier messages, which keeps
it fast and focused. To be sure to start fresh, use **New conversation**.

### 2.7 "Remember that …": memories

The agent keeps preferences, rules and facts that it gives itself with every question:

* **From the chat**: say "remember that …", "from now on …", "always …", "by default …" ("From now on, give
  durations in minutes"). Marking an answer **Helpful** and the reason given with **Not helpful** are read the same
  way.
* **In the Memory drawer** (the **Memory** button): write the text, choose for whom, click **Remember**:
  * **For me only**: used at once, in your answers only;
  * **For the team (after an admin's approval)** (a Viewer; **For the team** for an Editor or an Admin): for
    everyone. A Viewer's waits in *To review* until an Editor or an Admin approves it (`memory.team_approval`); a team
    memory written by an Editor or an Admin is approved at once;
  * **For the group <name>**: for the members of one of your Superset groups (same approval rule).

  The drawer lists **For you**, **For the team** and **Waiting for an admin's approval**. **Edit** changes a text
  or its kind (preference, rule, fact); **Forget** removes it after a confirmation. Your own memories are yours to
  edit and forget; the team's are edited by Editors and Admins and forgotten by Admins.

A Viewer keeps memories for themselves only. Editors and Admins manage the team's memories in *Data dictionary →
Knowledge → Team memory*.

### 2.8 Helpful and Not helpful

Under each finished answer:

* **Helpful**: the answer becomes a *learned answer*: its way to the result (its query and its path: the data it
  used and its steps) under a short generic question the agent writes. The next similar question, from anyone who
  may query that database, starts from it. It waits in *To review* for an Editor or an Admin to confirm it. A
  message "Kept as an example for similar questions" confirms it.
* **Not helpful**: a box asks *What was wrong?* (optional). Admins see the reasons, and what a reason says about the
  data ("killed jobs count as failed too") is proposed for the memory.
* Click the same button again to take it back. Taking *Helpful* back (or marking *Not helpful*) withdraws the
  learned answer, unless an admin confirmed it already.

### 2.9 Notes

Notes are for what a meeting decided or a fact the team must not lose. The agent finds them when they matter and
always says whose note it is and of which day. A note is never taken as a rule.

* **Notes** button: write the text, an optional title, tags and the day it is about, choose for whom (the team, a
  group, or yourself), then **Save the note** (or Ctrl+Enter). Below: a search box, the catalog's verified notes
  that match (*In the catalog (verified)*), the notes (pinned first, then the newest) and **More**.
* On a note: **Edit** and **Delete** (your own notes; Editors also edit the team's), **Pin for everyone** /
  **Unpin** and **Make a catalog entry** (Editors and Admins, team notes). A catalog entry made from a note is a
  verified guide.
* In the question box: `/note …` or `/mynote …`.
* Or ask the agent: "note that the release moved to Thursday", "add to my note about the carriers that …", "show my
  notes of last week", "undo the last change to that note", "delete my note about …" (it shows the note and asks
  first).

### 2.10 Stop an answer

Click **Stop** (the *Send* button while an answer runs). The answer stops at once and shows *(stopped)*; you can ask
the next question right away. A query or an LLM call already running ends on its own in the background and its
result is thrown away. **Ask again** under the stopped answer asks it again.

An answer that makes no progress for 35 minutes (a worker restarted, for instance) is marked as failed with a note,
so a conversation is never locked.

### 2.11 Delete chats

* **In the chat**: the **×** next to a conversation. A small card asks to confirm: its messages, results and files
  go for good; what the agent learned from it (learned answers, memories) stays. Deleting the chat whose answer is
  running stops that answer.
* **From the command line** (administrators): `superset supagent conversations` lists the chats, the latest first,
  with their user, number of messages and size; `--delete ID` (repeat it for several) or `--user NAME --all`
  says what would go, and with `--yes` deletes it. See section 8.
* **Automatically**: an admin can set `chats.keep_days` so that chats nobody used for that many days are deleted
  (off by default). See section 7.

If the page says *"The chat that was open last time did not finish opening"*, the chat is too heavy for the
browser to draw (very large rows or labels): **Open it** tries again, **Delete it** removes it.

---

## 3. The Data dictionary, tab by tab

The Data dictionary is everything the agent knows and uses in its answers: what the team wrote (the catalog, the
team memory, the documents and sites, the notes), the Context written from it, and what the agent learns every day
from the data and the chats.

Open it from Superset's *Settings* menu (*Manage* → **Data dictionary**) or from the *Data dictionary* tab of the
chat page. It has four tabs: **To review** (Editors and Admins), **Knowledge**, **Data** and **Search**.

Common to every tab:

* Each part has an **i** button: a short card says what it is. Escape or a click outside closes it.
* What cannot be undone (a deletion, a removal) is asked in a small card next to the button, with a red button
  that does it; *Cancel*, Escape or a click elsewhere keeps everything.
* Texts marked **AI-written** come from the LLM and are not checked by a person until an Editor approves or
  corrects them. **agent** marks a catalog entry the agent wrote from evidence; **curated** a text people wrote or
  approved.
* After a save, a line next to the tabs follows the agent's search: *Saved · updating the agent's search…*, then
  *Saved · the agent's search is up to date* (a few seconds). If it says the search was not updated, the hourly
  indexing catches up.
* The **Databases** line at the top (click to open it) lists the databases you may query: their kind (OpenSearch
  indices, Prometheus / Mimir metrics), when they were last learned, how many objects they hold and how many are
  described. The **N AI-written** link opens those descriptions in *Data → Browse* to check them.
* Every tab has its own address, to bookmark or share: `…/supagent/dictionary/#catalog`, `#review`, `#memory`,
  `#docs`, `#notes`, `#context`, `#learned`, `#categories`, `#map`, `#browse`, `#relations`, `#changes`, `#search`.
  An item found by the search opens at `#open/<kind>:<id>`, for anyone who may read it.
* The page opens on *To review* for Editors and Admins when something waits there, else on the *Catalog*.

Viewers see every tab read-only, except *To review* and *Categories*, which they do not see.

### 3.1 To review (Editors and Admins)

Nothing the learning or the chats propose is used by the agent before a person approves it. To review gathers all
of it, each item a card with its actions. The tab shows how many items wait; the Settings page shows it too.

At the top: a lead line ("N items wait for you"), a chip per group (a click scrolls to the group), and a **filter**
box: type a part, a repository, a document or a word and press Enter to see only what names it or was read in it.
*Approve all shown* and *Reject all shown* then act on the filtered items only. Each group shows its first 50
items (the count says how many wait in all). A decided card says what was done and leaves the list.

| Group | What waits | Actions |
|---|---|---|
| **Team memory proposed from the chats** | Team rules, facts and preferences read in the chats or written for the team | **Approve**; **Edit** (correct the text, then *Save and approve*); **Reject** (kept, not used) |
| **Answers marked Helpful** | Learned answers: a title, a description, the steps and the checks the agent kept, the question, the query or the investigation path, and its path (the data it used, its steps) | **Confirm**; **Edit** (title, description, steps, checks, question, query, path; **Check the query** runs it with your permissions; *Save and confirm*); **Reject** (never proposed) |
| **New values proposed for the categories** | Values proposed by the LLM or read in the data's fields, with the links proposed with them and where they come from | **Approve**; **Edit…** (category, name, what it covers, other names; *Save and approve*, or *Save* to decide later); **Merge into…** an approved value (Admins); **Reject**. When the value has the name of one you already have: **Merge into <value>** (Admins) |
| **Links proposed for removal** | Links of the System map whose removal an Editor or the learning proposed, with why | **Remove** or **Keep** (Admins; Editors see "an AI Admin decides") |
| **Parts that look retired** | Values not seen in the data for `categories.retire_days` days, or that a text says were retired or decommissioned | **Retire** (Admins: kept, marked retired, no longer used nor drawn); **Keep** (not proposed again for this reason) |
| **Categories given to items** | Categories the LLM was not sure enough to give alone | **Approve**; **Change…** (another value, *Save and approve*); **Reject** |
| **Relations and interactions** | Links between parts that documents, code, logs or data state, each with the sentence or line that says it | Correct the **short** explanation and the **in full** one; **Edit** (the kind of link, *turn it round*); **Approve**; **Save** (keep it waiting); **Reject** |
| **Where the categories are in the data** | Labels or fields that hold several values of a category and are not read for it yet | **Read <category> from <field>** (Admins: the next learning proposes its other values); **Set aside** |
| **What could confuse the agent or the search** | Warnings, each with why and what to do (below) | The one-click fix the warning offers (a merge or a removal: Admins); **Set aside** (not said again) |
| **Alert rules and dashboards drafted for Grafana** (Admins only) | Drafts the agent wrote from a team rule or a chat request, with a preview | **Create in Grafana** (with `grafana.writes` on: created, then read back); **Reject** |
| **Kinds of work learned from the chats** | How the router classified questions people confirmed (already used: listed under *When you have time*) | Choose the right kind and **Set**; **Not an example** |
| **Context pages written by the agent** | A change of a Context page, a new page, or the removal of a page whose subject is gone | See below |

Bulk buttons appear on some groups when several items wait: **Approve all shown**, **Reject all shown**, **Approve
the N <category> values found in the data** (the values read from a category's fields, all at once), **Merge the N
other names of <category> values you have** (Admins: proposals written like a value you have become its other
names), **Read: fine, all new pages shown** (new Context pages). Each asks for a confirmation first.

**Refused earlier (new in 0.11.4).** At the very bottom of the tab, folded and in small grey letters, **Refused
earlier** keeps what was refused before: the values of the categories (refused, removed or retired) and the links
of the System map refused, the latest first, 30 at a time (**Show more**). It is read only when opened and never
counted in what waits; the filter box above applies to it too. On each:

* **Propose again**: it goes back to its group above, to decide;
* **Use again**: in use at once.

A value refused lost its links and items at that time; the next learning proposes them again. A value with the name
of one in use cannot be added again (it says which), nor a link whose part is not in use (add the part again
first). Refused items stay refused until then: they are what keeps the learning from proposing them again.

**Context pages.** A change is shown as the page now against the page proposed, line by line, the changed words
marked (**Side by side** / **One column**; long unchanged stretches folded, click to open them), with *In short: the
statements added and dropped*. When it replaces an earlier proposal nobody reviewed, what the earlier one said and
this one no longer says is listed, so nothing is lost silently. Actions:

* a change: **Approve** or **Keep the page as it is**; **Edit** the proposed text (*Show the changes*, then *Save
  and approve*);
* a new page (already shown, marked *not reviewed*): **Read: fine**, **Reject** (shown to nobody, not searched,
  proposed again when its sources change) or **Edit**;
* a removal: **Remove** (Admins) or **Keep it**.

**The warnings** (also printed by `superset supagent lint`):

| Kind | What it means | Fix offered |
|---|---|---|
| same name | One name for two things: a value in two categories ("web" a server group and an application) | Rename one with what it is; or merge the proposal into the approved value, or reject it |
| two ways | One thing written two ways in a category ("web-shop" and "webshop") | **Merge "x" into "y"** (the other writing kept as another name) |
| loop | The System map in a circle (A part of B and B part of A; A runs on B and B runs on A) | **Keep "A runs on B"** (the other link rejected), or **Reject** the wrong link |
| shared pages | Documents holding the same pages (a wiki given as one document per space) | **Disable** the copy |
| two meanings | A glossary term defined twice, differently | Keep one definition (edit or disable the other entry) |
| duplicates (new in 0.11.0) | A memory (a person's, a group's or a copy of the team's), a catalog entry or a learned answer (the same query) said more than once; or two alike that may repeat or contradict each other | **Remove the copy**: a memory copy is disabled (kept, not used), a learned answer copy is deleted; **Disable the copy** for a catalog entry. The oldest is kept. For two alike: read both, keep one or make each say when it applies |

A **copy** has the same words in the same order once case, punctuation, plurals and small words are set aside
("Always give durations in minutes, please." and "Give durations in minutes"). Anything that changes what a text says
keeps the two apart: another word (a qualifier, a condition), a negation ("don't" is "do not"), an operator or a sign
("> 500" and "< 500"), a modal verb ("must", "may"), a quoted value as written ('FAILED' and 'failed'). Two texts
that share most of their words (70 % or more) without being copies are listed as **alike**. The agent is already given
a copy only once (section 6.2); the warning is there to clean the knowledge.

### 3.2 Knowledge → Catalog

What people know about the data, one entry each, with its history. The classifications:

| Classification | What it holds |
|---|---|
| glossary | Business terms, YAML `term: definition` |
| index | One or more indices: description, time field, fields, relationships |
| metrics | Metrics: description, unit, labels, SQL, saved metrics |
| relationships | How metric labels match index fields |
| checks | Health checks used by `check_health` (expression, operator, threshold) |
| rule | A rule the agent always follows ("Exclude UAT unless the user asks for it") |
| guide | Documentation, runbooks, how-tos, explanations (text or Markdown) |
| formula | A calculated field: `name = expression`, and the table it applies to |

* **Filters**: classification, category, *Written by anyone / the agent / people*, and a search box.
* **New entry**, **Import YAML**, **Export YAML** (Editors and Admins).
* Click an entry to open it. Editors get the editor: **Title**, **Classification** (its help is shown), **Category**,
  **Format** (YAML, Text, Markdown), **Enabled (used by the agent)**, the content, **Save**, **Delete** (Admins;
  restorable from the history), and **History**: every version with *view* and *restore this version*. YAML is
  checked before it is saved (with the line and column of an error). Two people editing the same entry cannot
  overwrite each other.
* An entry the agent wrote says its evidence (answers confirmed as helpful, a team rule approved, a definition
  quoted from a document). Save it to take it over: the agent no longer changes it. Delete it and the agent never
  writes it again.
* Warnings under the filters: an entry skipped because it is invalid, and a term or index defined twice (the most
  recent change is used; a person's entry wins over the agent's).
* **Import YAML**: paste a whole catalog; it is split into entries (same title: updated; others: added). *Also delete
  the structured entries this file does not have* replaces instead of merging (it deletes entries: Admins).

Viewers see the enabled entries, read-only.

### 3.3 Knowledge → Team memory

Preferences, rules and facts for everyone, learned from the chats or written here.

* **Add for the team** (Editors and Admins): the text, its kind (**rule**, **fact**, **preference**), an optional
  category. Used at once.
* **Filters**: the state (**Used**, **Proposed**, **Disabled**, **Moved to the catalog**) and a search box.
* **Actions** per memory: **Approve**, **Disable** (kept, not used), **Edit**, **Delete** (Admins). A rule or fact
  that became a catalog entry shows *in the catalog* and **Edit it in the catalog**.

A memory proposed from a chat is not used until it is approved. Viewers see the memories in use.

### 3.4 Knowledge → Documents and sites

Documents the agent searches: text, Markdown or HTML files, web pages and sites, Confluence wiki spaces and
Bitbucket repositories, read again every few days. Each page is cut into pieces for the search, so the agent
finds the passage a question needs and names its page. PDF files are not read.

**Adding one** (Editors and Admins):

| Field | Meaning |
|---|---|
| Address of a page, a site, a wiki space or a repository | The address to read. Intranet addresses are read only when their domain is in `docs.allowed_domains` (Settings) |
| Read as | *Detected from the address*, or *Web page or site*, *Confluence wiki*, *Bitbucket repository* |
| Category | Optional, e.g. Runbooks |
| Pages or files at most | 2,000 by default, up to 50,000 |
| Read again every (days) | 7 by default |
| Sign-in | *None (a public site)*, *Token (Bearer)*, *User and password or app token (Basic)*, *Token in a header of its own* (with its header name). The secret is kept encrypted and sent only to that site |
| The site's certificate | *As in Settings (checked)*, *Checked*, or *Not checked* (an internal site whose certificate this server does not trust) |
| CA file on the server (optional) | A PEM file present on every Superset host |
| A repository: read | *All its code too: scripts, libraries, configuration (passwords, tokens and keys in it masked)* (the default) or *Its documentation and text files only* |

Then **Add** (it is read at once), or **Upload a file** (text, Markdown, HTML, CSV, JSON, YAML, reStructuredText,
AsciiDoc; 20 MB at most). What a sign-in reads becomes searchable by everyone who can open the Data dictionary: use
a token that only reads what they may see.

**The list**: Document (its address and how it is read), Category, Pages, Size, *In the search* (its pieces),
State (*ok*, *reading* while it is being read, or *error* with the error; *limit of N pages reached*; *N pages not
read: see Pages*), Read (when).
Actions:

* **Read again** (sites): read it now;
* **Pages** / **Hide pages**: every page read, with its title and address, its space, its size, its links and
  images; the pages not read and why (not readable, no text, too large, a title matching `docs.skip_titles`, read
  by another document); and a warning when the number of pages was reached ("Raise Pages (Edit) to read more of
  the site");
  * **Remove** on a page (Admins): the page is not read again; its text, its search pieces and what was learned
    from it are deleted at once;
  * The list draws 500 pages at a time: **Show 500 more (N not shown)** draws the next ones ("No page matches."
    when the filter finds none);
  * **Removing several pages at once** (Admins): type in *Filter the pages (title, address, space)*, tick the pages
    or **all shown** (the rows drawn), then **Remove N picked pages** and confirm ("N removed");
  * **Removed (not read again)** lists them, each with **Read again** (read at the document's next reading);
* **Edit**: category, pages, days, how it is read, its sign-in (an empty secret keeps the saved one), certificate,
  CA file, and for a repository what to read. Saving reads it again;
* **Delete** (Admins): its pages leave the agent's search (and its saved sign-in is deleted).

A repository is read again only as far as it changed (the files changed since the last commit read). Files that
hold keys (`.env`, `*.pem`, `*.key`...) and vendored or built files are never read; passwords, tokens and keys
given a value in any file are masked before anything is kept.

**Dashboards and visualizations** (shown to Editors and Admins; only Admins switch them): the dashboards of the
team's Grafana and OpenSearch Dashboards that the agent reads. One tab per source, with how many are read.

* **List now**: read the list again from the source (no AI, no page written; the learning does it too).
* **Deactivate all** / **Activate all**: the agent stops reading every dashboard (their pages leave the Context and
  the search at once) or reads them all again. To read only a few: *Deactivate all*, then switch on those needed.
* **New ones: read** / **New ones: not read until activated** (`grafana.read_new`, `osd.read_new`).
* Filters: a search (title, folder, type), *Dashboards* or *Panels* (*Visualizations and saved searches* for
  OpenSearch Dashboards), *Read by the agent* / *Not read*, sort (*Last modified first*, *By title*, *By folder* or
  *By index pattern*). **Activate the N shown** / **Deactivate the N shown** act on the filtered list.
* Each row: its **Read** switch (saved at once), its title (a link to it), its folder or index patterns, its panels
  (click to list them, each with its own switch), when and by whom it was last modified.

An OpenSearch Dashboards dashboard switched on reads its visualizations too. Alert rules are always read. The
connections themselves are set in Settings (section 4.7 and 4.8).

### 3.5 Knowledge → Notes

Every note you may read, page by page (25 a page): the team's and yours. A search box and *The team's and mine* /
*Mine*. Columns: Note (click to read it; *pinned*, *in the catalog* and its tags), By, Day, For (*the team* or *its
author only*). Actions: **Pin for everyone** / **Unpin** and **Make a catalog entry** (Editors and Admins, team
notes), **Delete** (your own notes; others' notes: Admins; the chat's notes panel shows Delete only where you may).

### 3.6 Knowledge → Context

What the system is, functionally and technically, written every night from what the team shares: the documents,
the catalog, the team memory, the dictionary and the answers marked Helpful. Raw chats are never read. It reads like
a book: the contents on the left (*Functional* and *Technical* parts, numbered chapters), the page on the right.

* **Find in the Context**: shows the pages that hold your words (how many of each part).
* **Export all**: **Book (Word)** and **Book (PDF)**: the whole Context as a book (a summary, the contents with
  page numbers in the PDF, parts and numbered chapters, the related pages of each page). **This page: Word, PDF**
  exports the page on screen.
* A page shows its badges: **AI-written** (written by the LLM from the sources listed under it: check before relying
  on it), **edited** (a person's version), **a change waits** / **removal proposed** (it waits in To review; the page
  stays as it is until someone decides), **not reviewed** (nobody read it yet). Under it: **Written from N sources**,
  and **Related pages** to read next.
* **Relations diagrams** (new in 0.11.0): *How the system works*, the *Technical overview* (its infrastructure
  links) and each application's page end with a **Relations diagram**: the parts as boxes, left to right, each arrow
  saying what one part does to the other (calls, sends data to, runs on…), the most stated first. It is built from
  what the documents and the code state, never by the LLM. Hover an arrow to read it; **The relations as text**
  shows the same lines ("A -> B : calls"), which are also what the exports and the search contain. A diagram draws
  30 relations and 40 parts at most (the most connected).
* **Build now** (Editors and Admins): write the Context now (it is listed with the runs on the Settings page).
* **Correct this page** (Editors and Admins): edit the page's Markdown and **Save my version**: the page is yours,
  the agent never writes over it. **Give it back to the agent** (on a page you edited): the next build writes it
  again from its sources.

The pages: *How the system works*, *Technical overview*, (new in 0.11.5) one page per big wiki space, **Wiki space
<name>**, (new in 0.11.6) **How the wiki spaces connect**, and one page per main application (AI-written, at most
`context.max_llm_calls` LLM calls a build, written again only when their sources changed). A wiki space page is
written for each space of 200 pages or more of a Confluence wiki read with 0.11.5 or later (six at most, the biggest
first): its subjects in a table (what each is and what holds now, as the most recent pages say; where a page says
since when something holds, what that replaced and since when), and its main pages. Where two pages disagree, it
follows the one changed last (the reader keeps the day each wiki page was last changed and its place in the wiki's
tree); where the newest page does not settle it, the page says that the pages disagree and gives each statement with
its day, never a guess. Before it is saved, a space page is checked: when it leaves out a subject of its space, names
something its pages never give (a host name the LLM made up) or guesses from what is usual ("typically", "we
assume"), the LLM is asked once to write it again (one more LLM call); a made-up name or a guess still there after
that is taken out with its sentence. A wiki read before 0.11.5 gets its space pages after its next reading (**Read
again** on its row in Documents and sites brings them sooner).

With two big spaces or more, **How the wiki spaces connect** shows which subjects of one space the pages of another
name, and what for: the links are counted from the pages themselves, without the LLM (a subject's pages that name
another subject, two pages at least), each with the sentence of the latest page that says it; the page has a row for
each of the main links between the spaces (checked as a space page is) and draws them. The space pages and this page
are written first in a build, then the two overviews: from 0.11.6 they read a big wiki through its spaces' pages as
they are then (your corrected version of a space page counts), in the place of the wiki's own pages, so that *How the
system works* gives the spaces, how they connect and their current values. A wiki without such spaces is read as
before. Facts pages written
without the LLM: each data source, each inventory (servers, services, applications, environments...), the links
between databases, the glossary, the rules and facts, the dashboards and their charts, Grafana and OpenSearch
Dashboards pages, the parts, repositories, wiki spaces and server groups the documents describe, a page per system
of the System map, and the **LLM context** in two versions (*full* and *light*), which the agent is given with the
questions (section 6.2). You see the pages of the databases you may query.

### 3.7 Knowledge → Learned by the agent

What the agent learned by itself, on the databases you may query. At the top: how many relations it measured and
how many AI-written descriptions wait in each database (a link opens them).

**Learned answers**: answers marked Helpful, under a short generic question, the most useful first. The filter
chooses *All*, *Helpful, to review*, *Confirmed*, *Rejected*, *Saved automatically (0.2.1 and before)*. Columns:

* **Question** (its title and a line that says why it ranks where it does: what people said of the answers it was
  given to, whether its query worked when run again);
* **Way**: the tool and the database, the query (click to unfold) and **its path** (the data it uses, its steps);
* **Time**, **Helpful / not** (of the answers it was given to), **Status** (*helpful, to review*, *confirmed*,
  *rejected*).

Actions (Editors and Admins): **Confirm**, **Edit** (the generic question, the query, the path; **Check the query**
runs it with your permissions; **Save and confirm** runs a changed query first and confirms it only if it works;
**Save only**; **Cancel**; *Before the last change* shows the earlier text), **Reject** (kept, never proposed),
**Delete** (Admins). One that people keep saying is wrong is no longer proposed.

**Catalog entries the agent wrote**: each with its classification, where it comes from, and when it was updated.

**Where the data of the questions was**: the tables (indices, metrics) the answers read, with the words of the
questions that led there and how many answers used each. A word in **bold** led only there; a grey word also led to
other tables (hover it to see which). Search by word or table, filter by database. Editors and Admins:

* **×** on a word removes it from a table (new answers may teach it again);
* **Add**: write words, choose the database and the index or metric, **Add**: words put by hand never fade.

An answer marked Not helpful takes back what it taught.

**Query timings**: how long each kind of query took (values replaced by `?`), slowest first: the table or metric,
the query (unfold it, **Copy**), calls, average, slowest, failures (with the last error). Editors also see the last
query as it ran. The agent sees these timings when it queries the same table.

### 3.8 Knowledge → Categories (Editors and Admins)

Every piece of knowledge is classified in the platform's own words: **functional** or **technical** (the aspect),
its **subjects**, the **applications** and **components** it is about, and your own categories (server,
environment, team…). The router and the search use them; the System map draws them.

* **Filters**: the category, the state (*Approved and proposed*, *Approved*, *Proposed*) and a search box. Once the
  list is filtered, Admins get **Remove the N values shown** (never on the unfiltered list).
* **Add a value**: choose its category, write the value, *What it covers* and *Also called* (other names), **Add**.
  Used at once.
* **The values table**: Value (its description, other names, where it was read from), Category, Items (how many
  pieces of knowledge are about it), For example, State (*used* or *proposed*, and *from the start*, *from the
  data*, *by the LLM* or *by an admin*). Actions: **Approve** (a proposed one), **Edit** (its name, its category, what
  it covers, its other names; a value renamed onto one that exists is merged with it, which is an Admin's),
  **Links…** (its links to other parts: see below), **Merge…** into another value of the same category (Admins
  only, after the confirmation "Merge “X” into “Y”?"),
  **Remove** (an approved value: Admins) or **Reject** (a proposed one). A removed value is not proposed again;
  adding it by hand brings it back.
* **Categories: add, rename or remove one, and where their values come from** (fold): each category with its
  number of values, the field names its values are read from, the category it is drawn inside on the map, and what
  it is (a sentence people, the agent and the router read). **Edit**: its name (your own categories), the field-name
  pattern it reads (e.g. `^(host|node|server)$`), what it is, and *In a column of its own* or *Inside: <category>*.
  **Remove** (Admins, your own categories) takes it away with its values and everything that names them, after
  saying what goes. **New category** with its field-name pattern, **Add**.

**Links…** on a value lists its links from its end: **→** to the other part, **←** from it, **↔** both ways, each
with what it is and what it does, and *In the data (where the agent filters on it)*: the labels and fields that hold
the value, as the data writes it. **+ Add a link**: the other part (type to find it), what the link is (a few
words), what it does (what to check on the other part), its direction, **Add the link**. On a link: **Edit**,
**Remove** (Admins) or **Propose its removal** (Editors).

**Several values at once (new in 0.11.4).** Tick the box of each value (the box in the header ticks every value the
list shows; the fixed aspects have none). A bar above the list says how many are chosen and offers:

* **Put them in** a category or a subcategory (a subcategory is listed after the category it is inside, e.g.
  *Component › Exporters*), then **Put the N values there**. Each one moves as when dropped on the System map, with
  its links, items and other names; a value still proposed moves too. A value whose name (or other name) is already
  used in that category is not moved, and the bar says so: merge the two first if they are one.
* **Link each to** one other value (type to find it), with what the link is, what it does (optional) and its way
  (*from each to it*, *from it to each*, *both ways*), then **Link the N values** (asked first). Example: every
  server chosen gets "is scraped by" to the component *node_exporter*. A value that already has this link keeps it
  as written; a value still proposed is skipped until approved. Admins get **Undo** right after, which takes the
  links just added back.
* **Clear the choice**.

The choice follows the list: a value no longer shown (another filter) leaves it.

**Several links at once (new in 0.11.4).** In a value's **Links…**, tick links (or **Choose every link**): a box
appears to write **what they are** and **what they do** on all of them, then **Write on the N links**. An empty field
keeps each link's own text; the links' parts, way, kind and state do not change. Admins also get **Remove them**
(asked first). The same box is on the System map's panel of a value.

### 3.9 Knowledge → System map

The architecture of the system as the categories describe it: one column per category (subjects, applications,
components, servers…), each part in a box with what it does (its description, else a sentence of the documents that
name it) and how many items are about it, and the links between parts as arrows (an arrow at both ends when a link
goes both ways). Everyone who can open the dictionary sees it, limited to the parts of the databases they may query.

**Moving around**: drag the background to pan, the mouse wheel to zoom (or the keys **+**, **-** and the arrows when
the map has the focus); **Fit** fits the map to the window; **Full screen** puts the map, its tools and its panel on
the whole screen (Escape comes back). **Export: PNG, SVG, PDF** saves the map as drawn.

**Choosing what you see** (kept in your browser, not for the others):

* the **filter box** above the map: type to find categories and parts, choose several; a part comes with what it is
  in, what is inside it and what it is linked to; nothing chosen shows everything;
* the **legend**: each category is a switch (shown or hidden), with how many parts it has; *Show the hidden
  categories* brings them back; *Filtered on … ×* clears a part filter;
* on a category's name: a click **folds** its parts into one box (and opens them again; a big category starts
  folded); the **funnel** filters the map on that category (again: everything); the **×** hides it; the **ⓘ** opens
  its panel;
* the line at the bottom of a box opens or closes the parts drawn inside it (a server's disks inside the server, a
  sub-subject inside its subject).

**A category's panel** (its ⓘ): what it is, how many parts, the fields its values are read from, the category it is
drawn inside, **Open every part inside** / **Close them**, and for a big category *Its parts grouped by* (*automatic*,
*what they hold (what runs on them)*, *what they belong to*, *no groups*). **Show this category only**. Editors also
write **What it is** (**Save**) and **Change it**: **Add the value**, *Drawn* (*In a column of its own* or *Inside:
<category>*), **Add the subcategory**.

**A part's panel** (click its box): its category, name, other names, description (*Written by the AI…* when the AI
wrote it), how many items are about it, where it comes from, its **Links** (as in Categories → Links…, with *+ Add a
link*), **Filter the map on it** and **Its knowledge** (a search for it in the Search tab). Editors also get:

* **Inside**: what it is inside (**Take it out**), *Put it inside: type a part*, then **Move inside** (out of the part
  of that category it was in) or **Also inside (copy)** (inside both); a category and a name, then **Add inside** (a
  value inside it); **Remove this value…** (Admins: takes it off the map);
* **Edit**: what it is, what it does (**Save the description**; **Use the sentence found** fills in the documents'
  sentence), **Add a link from here** (then click the other part; Escape cancels), **Hide from the map**.

**A link's panel** (click an arrow): its two parts, what it is, *What it does*, who explained it and where it was
read (*Said in: …*), the other links drawn on the same line, and a proposed removal with **Remove it** / **Keep it**
(Admins). Editors **Edit** it (its short and long explanation, its direction, **Save**), and **Remove** it (Admins)
or **Propose its removal** with why (Editors).

**Editing the map** (Editors and Admins). Every change is saved at once, for everyone.

* The legend offers **+ Category** (a category of your own, in a column of its own or inside another) and **+ Link**
  (two parts found by typing; the kind of link: belongs to, runs on, connects to, relies on, reads from, sends data
  to, monitors, triggers, is related to, or your own words; what it does; one way or both ways), and **Show the N
  hidden** when parts were hidden from the map.
* **Edit** turns the edit mode on. Then you can drag a category's name to move its column (its boxes follow), drag
  a value up and down its column (its place is kept) or onto a subcategory's box to move it there, use the **+** on
  a category's name to make a subcategory, and use **Group categories…** in the legend (a frame drawn around the
  columns of several categories, display only: nothing changes for the agent). The panels open with their *Edit*
  part unfolded.

Chips in the legend lead to *To review* when proposed values or links wait, or when links are proposed for removal
(drawn dashed until an Admin decides). **N points to complete for investigations** (Editors and Admins) lists what an
investigation follows and does not find yet: parts not found in the data, parts with no link, joins, usual values
(`superset supagent check-system` prints the same).

The map follows the knowledge by itself: it is read again every 20 seconds while you look at it (once a minute for
Viewers), not while you edit it, and not after 15 minutes with nobody at the page. A new part or link is outlined
for a moment. It draws approved values only: a proposed one appears once approved.

### 3.10 Data → Browse, Relations, Changes

**Browse**: what the daily learning found in the databases. Filters: the database; the kind (*Metrics*, *Metric
labels*, *Metric families*, *Indices*, *Index fields*); *Show*: *Current*, *AI-written, not approved*, *Without
description*, *Gone*, *Deactivated*; a search box. Columns: Name, Kind, Type, Unit, Description (with its badge:
AI-written, curated, from the source; gone; deactivated), Size (series, documents or distinct values). 50 a page,
**Previous** / **Next**.

Click a row to open its panel: its type, unit, category, other names, the source's help text, first and last seen;
**Measured** (series, documents, data range, time field, rates, min, max, average, percentiles, distinct values,
fill rate, frequent values…); its **Labels** or **Fields** (click one to open it); the other metrics with the same
label; its **Relations** (*Open* the other end); its **History**. Editors also edit it:

* the description, category, unit and other names, then **Save as curated**;
* **Approve the AI text** (an AI-written description becomes approved as it is);
* **Deactivate** / **Activate**: a deactivated index or metric (with its fields or labels) is never seen nor used
  by the agent and the search.

A description written by a person that says a field, label, metric or index is not used ("Not used",
"Deprecated: take HOST") is honoured: a query or a chart that uses it is refused with the team's words, and the agent
takes another field. A description written by the LLM never counts for this.

**Relations**: how metrics and index fields relate, written in the catalog or measured on the data (the values two
columns have in common, measured every day), with the confidence. **Wrong** (Editors and Admins) on a measured
relation: never measured again, never given to the agent (**Restore** undoes it). The right relation is a catalog
entry of classification *relationships*.

**Changes**: what changed in the data over the last 1, 7 or 30 days: new, gone and back objects, changed types or
units, big changes in series counts, with the database and the detail.

### 3.11 Search

Search everything the agent knows, as the agent searches for each question: by words and, with an embedding model,
by meaning. Type, choose a kind if needed (*Metrics*, *Indices*, *Guides*, *Notes*, *Rules*, *Glossary*, *Formulas*,
*Learned answers*, *Memory*, *Documents and sites*, *Context*), **Search**. The results (500 at most, 20 a page) show
their kind, their name (a link: a chart or a dashboard opens in Superset in a new tab, everything else in the side
panel), how they were found, and their text. A misspelled word read as a known word is said ("'refunnd' read as
'refund'").

---

## 4. The Settings page

*Settings* menu → *Manage* → **Chat settings** (or the *Settings* tab of the chat page). Admins only.

**The status line** at the top says, in green when all is well:

* the supagent version and the version of its tables (*tables vN*);
* where answers run: *Celery workers answer (N)*, *no Celery worker: answers run in the web server*, *no Celery
  worker: questions wait for one (agent.executor = celery)*, or *answers run in the web server (agent.executor =
  thread)*;
* *Superset MCP tools (charts, dashboards)*, or *Superset MCP service not installed: no chart saving*;
* *daily learning in the beat schedule*, or *daily learning not scheduled*;
* *last daily run <when> (<status>)*, with *none in the last day, is Celery beat running?* when the last scheduled
  run is more than a day old.

**How a setting is shown**: its name, its key in small letters (the key used on the command line), an **i** with
what it does, and its box: a check box, a list, a number, a text, a JSON text, or a password box for a secret. A
secret is stored encrypted with Superset's `SECRET_KEY` and never shown back: the box says *set — leave empty to keep
it* or *not set*. A list is written comma-separated.

**Save**: each section has its own **Save**, which saves the settings of that section that you changed (*saved N
setting(s)*, or *nothing changed*; an error names the setting). Emptying a number box removes the saved value;
`superset supagent settings --unset KEY` does it for any setting. Without a saved value, the setting comes from
`superset_config.py` or the environment when they set it, else from its default (below).

**Where a value comes from**, in this order: the value saved on this page or with `superset supagent settings`;
else `SUPAGENT_<KEY>` in `superset_config.py` (the key in capitals, dots as underscores, e.g.
`SUPAGENT_LLM_BASE_URL`); else the environment variable of the same name; else the default. A saved setting is
stored in Superset's database: every web server and worker reads it when it next uses it, with no restart.

In the tables below, "on" and "off" are check boxes, an empty default is written "(empty)", and a secret is marked
*(secret)*.

### 4.1 LLM

An OpenAI-compatible chat API with tool calls. Authentication: none, a fixed token, or a token from the company
middleware (OAuth2 client credentials), renewed before it expires. The middleware fields appear when
*Authentication* is *middleware*, the token when it is *token*.

| Setting | Default | What it does |
|---|---|---|
| `llm.base_url` | (empty) | The API base: what comes before `/chat/completions`, e.g. `https://llm-gateway.example/v1` |
| `llm.model` | (empty) | The model's name; empty: the first model the server lists |
| `llm.auth` | none | `none`, `token` (a fixed access token) or `middleware` (a token from the company middleware) |
| `llm.token` | (secret) | The fixed access token (`llm.auth` = token) |
| `llm.middleware.token_url` | (empty) | The middleware's token endpoint (POST `grant_type=client_credentials`) |
| `llm.middleware.consumer_key` | (empty) | The consumer key, sent with the consumer secret as HTTP Basic |
| `llm.middleware.consumer_secret` | (secret) | The consumer secret |
| `llm.middleware.cert_path` | (empty) | A client certificate file (PEM) when the middleware asks for one (mutual TLS) |
| `llm.middleware.key_path` | (empty) | Its private key (PEM) |
| `llm.middleware.scope` | (empty) | The OAuth2 scope to ask for (empty: none) |
| `llm.middleware.renew_before` | 60 | Renew the token this many seconds before it expires |
| `llm.ca_bundle` | (empty) | A CA file to trust for the middleware and the LLM (empty: the system's) |
| `llm.verify_tls` | on | Check the TLS certificates of the middleware and the LLM |
| `llm.timeout` | 900 | Seconds to wait for one LLM answer |
| `llm.temperature` | 0.2 | Sampling temperature |
| `llm.thinking` | off | Let reasoning models think before each step (slower) |
| `llm.reasoning_effort` | (empty) | `low`, `medium` or `high` for models that always reason; empty: the server's default; never sent to a server that refuses it |
| `llm.keep_reasoning` | off | Send a reasoning model's reasoning back with its tool calls within one answer (to measure; off: not sent) |
| `llm.max_answer_tokens` | 8192 | Tokens of one LLM answer at most, so a model that repeats itself stops (0: the server's limit; four times this with `llm.thinking`) |
| `llm.extra_headers` | {} | More HTTP headers for the LLM calls (a JSON object) |

**Test the LLM** (save first): gets a token from the middleware when there is one, finds the model and asks for one
word: *OK: model …, middleware token …, answer "…" in N s*. It also reads again what the LLM server says about
itself (its context window, whether the model reasons, which fields and tool choices it accepts) and lists what
supagent adapts to it under *Adapted to this LLM*. The context window it reads chooses the context profile (4.5).
An error says what failed (address, certificate, token, model). The command line does the same: `superset supagent
test-llm` (`--profile` also measures thinking, tool calls and the prompt cache).

### 4.2 Daily learning

Every day at the chosen hour the learning reads the metrics (promagg) and the indices (osagg) as the learning user:
their types, units, values, series, time ranges, relations, and what changed since the day before. The Context is
built every night after it. Both are runs, listed below the buttons.

**Buttons**:

* **Save**: the settings of this section (learning and Context).
* **Learn now**: a learning run now. Refused while another run is running (*learning run N is still running*, or
  *is stopping: try again in a moment*).
* **Classify now**: the categories only, as a run of its own: the values read in the data's fields, the knowledge
  items that changed classified by the LLM, the interactions the documents state. The daily learning (or the
  classification after the nightly Context) does it too.
* **Stop** (shown while a run runs): marks the running run *stopped* at once; it keeps what it learned, and a new run
  can start right away. A learning, Context or classification run ends at its next check (every few seconds); the
  request or LLM call in progress finishes in the background. A backup or a restore is not interrupted: it finishes
  its work.

**The runs list** (15 a page, refreshed every 5 seconds while a run runs): **Run** (#number), **Why** (its kind and
reason: *schedule*, *manual*, *cli*; kinds: learning, *context*, *classify*, *backup*, *restore*), **Started**,
**Duration**, **Status** (*running*, *stopping…*, *done*, *partial*, *stopped*, *error*), **Changes** (what it
found different in the data) and **Summary**: per database the metrics, labels, indices and fields read, how many of
those due today were profiled, *stopped at its share of the time (learn.max_minutes): the next run continues*, the
databases left out and why, the AI descriptions written, the LLM calls and tokens; while it runs, *now: <database>
(<step>); next: …*. **steps (N)** unfolds every step with its time and counts. The runs are kept
`learn.history_days` days (section 7).

Schedule and scope:

| Setting | Default | What it does |
|---|---|---|
| `learn.enabled` | on | Learn once a day |
| `learn.hour` | 2 | The hour of the daily run (0-23, server time): one run a day |
| `learn.days` | every day | The days of the week with a run (`mon, tue, …, sun`) |
| `learn.user` | (empty) | The Superset user the learning reads the data as (empty: the first Admin) |
| `learn.history_days` | 30 | Days the learning's history is kept: the runs (learning, classification, Context, backups, restores, documents) and the changes they found; the last run of each kind is always kept; 0: kept for ever |
| `learn.databases` | (empty) | Database names or ids to learn (empty: every osagg and promagg database) |
| `learn.indices` | (empty) | Only these indices (patterns with `*`, e.g. `orders-*`); an index learned before that they leave out is marked gone |
| `learn.indices_exclude` | (empty) | Never these indices |
| `learn.metrics` | (empty) | Only these metrics (patterns with `*`, e.g. `http_*`); a metric learned before that they leave out is marked gone |
| `learn.metrics_exclude` | (empty) | Never these metrics (e.g. `go_*`) |
| `learn.one_table_each` | on | The names of the same documents are one table: an index family and its aliases, an alias and its index, a data stream |
| `learn.group_rollover` | on | Dated or rolled-over indices (`logs-2026.09.27`, `…-000123`) learned as one family, through the newest |

Load on the databases (the learning is gentle on purpose):

| Setting | Default | What it does |
|---|---|---|
| `learn.max_minutes` | 30 | Stop a run after this many minutes; the next run continues |
| `learn.max_objects` | 20000 | Metrics or indices listed per database at most |
| `learn.profile_every_days` | 7 | Refresh the statistics of each metric or index every N days (a share each day; new ones at once) |
| `learn.max_requests_per_minute` | 60 | Requests per minute to each database (one at a time) |
| `learn.request_timeout` | 30 | Seconds before one request is given up |
| `learn.stop_after_errors` | 5 | Leave a database for the day after this many failures in a row (429, 5xx, timeouts) |
| `learn.profile_hours` | 24 | The window of the value statistics, in hours (one hour above 50,000 series) |
| `learn.stats_max_series` | 200000 | No value statistics for metrics with more series |
| `learn.series_sample` | 1000 | Series read per metric to learn its labels and values |
| `learn.sample_docs` | 100000 | Documents sampled per index (per shard) for the field statistics |
| `learn.fields_per_request` | 40 | Field statistics per OpenSearch request |

What the learning writes:

| Setting | Default | What it does |
|---|---|---|
| `learn.llm_descriptions` | on | The LLM describes what has no description (marked AI-written) |
| `learn.associations` | on | Learn where the data is from the answers: the words of a question and the tables its queries read (Not helpful takes them back) |
| `learn.agent_catalog` | on | The agent writes catalog entries when the evidence is certain (formulas of confirmed answers, approved team rules and facts, definitions quoted from documents) |
| `learn.agent_catalog_docs` | on | … and reads the definitions of the documents (the LLM, once per new or changed document) |

Categories and the System map:

| Setting | Default | What it does |
|---|---|---|
| `learn.classify_per_run` | 400 | Knowledge items the daily learning classifies at most (the next run continues; 0: none) |
| `learn.merge_duplicates` | propose | One value per thing: proposals that name the same thing are put together. `propose`: To review merges them in one click; `auto`: a name written the same way is merged at once; `off` |
| `learn.merge_llm_calls` | 20 | LLM calls per learning to decide doubtful groups of names (0: only names written the same way) |
| `learn.new_part_min_units` | 2 | A part the documents name is proposed when code, configuration, a diagram or the data says it, or when this many pages or files say it |
| `learn.subject_links` | on | Propose a link between a part and a subject that several classified texts are about together |
| `learn.interactions` | on | Read the documents, guides, Context pages and notes for how the parts interact (proposed in To review with their sentence) |
| `learn.interactions_logs` | on | Read the recent lines of the log tables for the interactions they show (proposed in To review; no LLM) |
| `learn.interactions_logs_seconds` | 120 | The time that step may take |
| `learn.interactions_spans` | on | Span tables (Jaeger, OpenTelemetry): which service calls which, drawn as *calls* links with how many and how long |
| `learn.aliases` | on | A table that lists names with their other names (a CMDB) makes the names of one row one value |
| `learn.pod_names` | on | The names of one service in two sources, found by the pods or hosts they run on, made one value |
| `learn.behaviour` | on | The usual day of each service of the span tables kept and shown as a usual |
| `learn.usual_logs` | on | The log patterns of every day kept as usual, so that an investigation does not blame them |
| `learn.usual_latency` | on | The usual latency of each service of the latency histograms |
| `learn.same_events` | on | The same events shipped to two log tables said so, never added twice |
| `learn.describe_values` | off | The classification writes what a part is from what the documents say (off: measured with errors) |

The nightly Context:

| Setting | Default | What it does |
|---|---|---|
| `context.enabled` | on | Build the Context every night |
| `context.hour` | 4 | Its hour (after the day's learning run) |
| `context.review` | on | A change of a page the agent writes waits for a person in To review; a new page is shown at once, marked not reviewed; off: pages are written over |
| `context.classify_after` | on | After each Context build the classification runs on what it wrote (the nightly learning then leaves the categories to it) |
| `context.system_pages` | on | A page per system of the System map, written without the LLM |
| `context.max_llm_calls` | 12 | LLM calls of a build at most (the summary pages whose sources changed) |
| `context.fields_shown` | 30 | Fields listed on a data source's page for each of its first three main indices (0: none) |

### 4.3 Backups of the knowledge

One file a day holds the whole knowledge as it is. Restore puts back the parts you choose, after saving the present
state in a backup of its own, so that a restore can be undone.

| Part | What it holds |
|---|---|
| categories and System map | the values of the categories, what they are part of, the items they are given to, the links of the map and its arrangement, the categories themselves (their fields, their descriptions) |
| catalog | the catalog's entries and all their versions |
| memory | the team's and the users' memories |
| documents | the documents and sites with their texts, and which dashboards the agent reads |
| notes | the notes |
| Context | the Context pages |
| learned answers and paths | the learned answers, the investigation paths, the examples, the words that lead to a table, the kinds of work people confirmed |
| descriptions of the data | the descriptions of the data's objects, their units, other names and categories (put back on the objects of the same name) |
| settings | the settings |
| vectors | only with `backup.vectors`: the vectors of the search pieces |

A backup never holds a secret (the LLM's token, a site's sign-in: on the same Superset a restore keeps them;
elsewhere they are entered again), nor the chats, the usage figures or the runs.

| Setting | Default | What it does |
|---|---|---|
| `backup.enabled` | on | Make a backup every day |
| `backup.hour` | 1 | Its hour (the server's clock) |
| `backup.days` | (empty) | The days of the daily backup (`mon`, `tue`…); empty: every day |
| `backup.keep` | 14 | Backups kept: the oldest beyond this number are removed |
| `backup.keep_days` | 30 | Backups older than this many days are removed too (the newest is always kept); 0: by number only |
| `backup.upload_max_mb` | 2048 | The largest backup file that can be brought from elsewhere, in MB |
| `backup.dir` | (empty) | The directory of the backups (empty: `supagent-backups` in Superset's home). With several servers, a directory they share |
| `backup.vectors` | off | Save the vectors too: files several times bigger, and a full restore needs no new embedding |

**Buttons**:

* **Back up now**: a backup at once (a run listed with the others; refused while another run runs).
* **Restore…** opens the restore panel:
  1. *From*: a backup of this server, or *or a file*: choose a `.zip` and **Bring this file**. The file is checked
     (a backup this version can restore, no larger than `backup.upload_max_mb`) and kept in the backup directory
     as `…-uploaded.zip`. A file made by a later version is refused ("upgrade first").
  2. Tick the parts to put back (each with how many rows it holds).
  3. **Restore the parts chosen**, then confirm. The present rows of each part chosen are replaced by the backup's;
     the other parts stay as they are. The present state is first saved as `…-before-restore.zip` (the last 5 are
     kept). The restore is a run, listed with the others.
* **The list** (the latest first): *Backup* (its file name), *Made*, *Size*, *Why* (schedule, manual, cli, before a
  restore…, and by whom), *What it holds*; per row **Download** (keep a copy elsewhere) and **Restore…** (the same
  choice of parts for that backup). The line above the list says the directory.

After a restore the search follows at once; the vectors of what came back are computed by the hourly indexing (or
`superset supagent index`). A part restored alone may name items that no longer exist: they are simply not shown.
For the whole of Superset's database (the chats too), your database's own dump remains the tool.

### 4.4 Agent

How questions are answered. The keys are grouped here by purpose; the page lists them in one block.

Answers, tools and where they run:

| Setting | Default | What it does |
|---|---|---|
| `agent.max_steps` | 16 | Tool calls per question at most (a question of many parts gets half as many more, within the next limit); then the agent answers with what it found |
| `agent.max_steps_big` | 32 | Tool calls at most for an investigation, or a request that builds charts or a dashboard |
| `agent.answer_seconds` | 1500 | After this many seconds, an answer still calling tools is told to answer now (two calls left); 0: no limit |
| `agent.launcher` | robot | How the chat opens on Superset's pages: `robot` (a round button at the bottom right; the top bar's *Chat* tab hidden) or `tab` (*Chat* in the top bar) |
| `agent.executor` | auto | Where answers run: `celery` (the workers), `thread` (the web server), `auto` (the workers when one is alive, else the web server) |
| `agent.celery_queue` | (empty) | The Celery queue of the answers and the learning runs, when the workers read named queues only (empty: the default queue) |
| `agent.queue_keep_days` | 90 | With Celery's queue in Superset's database: delivered messages deleted after this many days (0: never) |
| `agent.databases` | (empty) | The databases the agent may use (names or ids; empty: the osagg and promagg ones). Superset's access still applies |
| `agent.preferred_databases` | (empty) | When the same index or metric is in several databases, the ones to use first |
| `agent.osagg_max_scan_rows` | 20000 | Raw documents an OpenSearch query that cannot be pushed down may read; above, it is refused at once with the reason (0: the connection's own cap) |
| `agent.now` | (empty) | A fixed "now" (`YYYY-MM-DD HH:MM`) for demos on old data |
| `agent.extra_instructions` | (empty) | More instructions added to the agent's prompt |
| `agent.disabled_tools` | (empty) | Tools the agent must not use (e.g. `send_email`) |
| `agent.pipeline` | classic | `classic` (the model writes the queries, checked after) or `governed` (a test: the model fills a plan, code checks it and writes the queries) |
| `agent.router` | on | Route each question (functional, technical, incident, charts, observability, infrastructure): the knowledge given first, the tools and a short instruction |
| `agent.subjects` | on | Each question goes with the messages of its subject only (off: the last messages of the chat) |
| `agent.read_question` | off | Read each question first, in a call of its own (off: measured to mislead follow-ups) |
| `agent.general_answers` | on | With `agent.read_question`: a general question is answered without the platform's data |
| `agent.ask_unclear` | on | A question that names one thing several values match is asked back with the candidates, not guessed |
| `agent.ledger` | on | Big requests get a work plan kept by the system ("continue" takes up its open tasks) |
| `agent.ledger_investigations` | on | Investigations get the work plan too |

Investigations:

| Setting | Default | What it does |
|---|---|---|
| `agent.compare_seconds` | 45 | `compare_groups`: after this many seconds it reads no further field and answers with what it has |
| `agent.compare_threads` | 3 | `compare_groups`: queries at a time on OpenSearch (1 on a busy cluster) |
| `agent.compare_follow` | on | `compare_groups` follows a lead once by itself (a stage where the rows wait on one value) |
| `agent.compare_against` | yesterday, 1 week ago, 4 weeks ago | The days the team compares with, besides the usual (`N days ago`, `N weeks ago`, `N months ago`, `1 year ago`; empty: none) |
| `agent.inputs_walk` | on | When the rows were late before they were ready, the inputs of the parts in scope (two steps up the System map) come with the comparison |
| `agent.inputs_logs` | on | … with what those inputs' logs say that they do not usually (three calls at most) |
| `agent.with_parts` | on | A part made of other parts (a pool and its servers) is looked at with them (16 at most) |
| `agent.calendar_facts` | on | The calendar facts of the days looked at (the third Friday, the last business day…) that the team's knowledge speaks of |
| `agent.cross_check` | off | A test: an answer with figures is computed a second time by the governed pipeline; differences are said (slower) |
| `agent.cross_check_seconds` | 180 | The time that second computation may take |

What the agent is given (see also 4.5):

| Setting | Default | What it does |
|---|---|---|
| `agent.context_profile` | auto | `short` (a model of 32k-64k tokens per request), `long` (128k or more), `auto` (long when the LLM's server states `budget.long_from_tokens` tokens or more, or `agent.context_tokens` does) |
| `agent.context_tokens` | 0 | The tokens the model reads per request, when its server does not say it (a gateway); 0: as the server says |
| `agent.compact_at` | 24000 | Prompt tokens from which the older tool results of an answer are cut to their first lines (both profiles; a profile's own `budget.*.compact_at` wins) |
| `agent.llm_context` | on | Give the LLM context the learning writes: its full version to a big model; a small model gets its light version only when a person set this on explicitly |
| `agent.context_tiers` | on | The agent's context in tiers (new in 0.11.0, section 6.2); off: as 0.10.12 (the LLM context whole in the instructions, the chat's last 40 messages) |

Checks of an answer (section 6.4):

| Setting | Default | What it does |
|---|---|---|
| `agent.check_numbers` | on | Every number must come from what the agent was given; it is asked once to take the others from a query, then they are marked |
| `agent.force_tool` | on | An answer that gives figures, names or times no tool returned, with no query run, is sent back once with a tool call made compulsory |
| `agent.shown_sql_check` | on | An answer that shows a query that did not run as the one behind its figures is sent back once |
| `agent.outer_join_check` | on | A WHERE condition on the optional table of a LEFT JOIN is sent back before the query runs, with the two ways to write it |
| `agent.value_elsewhere` | on | A query that found nothing for a value its field does not hold: the fields that hold it are named |
| `agent.share_join_check` | on | A share computed over an inner join of the part and the whole is sent back once |
| `agent.period_window_check` | on | A follow-up that names no period keeps the chat's period |
| `agent.join_check` | on | A SUM, AVG or COUNT over a join that repeats the rows it sums is sent back before it runs |
| `agent.definition_links` | on | A glossary term defined as a relation between rows ("the refunds of those orders"): tables read apart are linked on their key |
| `agent.definition_check` | off | A test: one LLM call compares a glossary definition with the answer's queries |
| `agent.bare_doubt_check` | off | Measured with more silent mistakes: a reply that only doubts ("are you sure?") gets a note of its own |
| `agent.claimed_query_check` | off | Measured with more silent mistakes: a follow-up that says a query ran when none did is sent back |
| `agent.correction_check` | off | Measured with more silent mistakes: a reply that disputes the previous answer is checked on another path |
| `agent.announce_ing` | off | Not measured yet: an answer that ends by announcing a step is sent back |
| `agent.link_limit_hint` | off | Not measured yet: the system picture says to check a link's limit on its metrics' peaks |

The LLM usage record:

| Setting | Default | What it does |
|---|---|---|
| `usage.keep_days` | 90 | Days the record of every LLM call is kept (the LLM usage page); 0: kept |

> In this version the *Save* button of the Agent section saves the `agent.*` settings only: change
> `usage.keep_days` with `superset supagent settings --set usage.keep_days=N`.

### 4.5 What the agent gives the LLM: small model / big model

Each question goes to the LLM with the instructions, the tools, the knowledge found for it, the team's rules, the
LLM context, the earlier messages of the chat and the results of the tools it calls. How much of each depends on
the model: a **small model** (32k to 64k tokens per request: the *short* profile) gets the small sizes, a **big
model** (128k, 256k: the *long* profile) the big sizes, grown with its window.

The line at the top says the profile in use and why: *In use: the big model's sizes (long); the model reads N tokens
per request; an answer starts with about N tokens, of which N for the instructions and the tools (an estimate)*,
followed by a **Warning** when the start of an answer may take more than half the window, one tool result more than
a quarter, or when older results are cut only after the window is full.

Two columns, **Small model (short)** and **Big model (long)** (*: in use* on the profile in use), hold the same sizes.
Leave a box empty for the profile's own size, shown in grey. A size typed here is used as typed. When a setting for
both profiles decides a size, the box says *in use: N (set in agent.compact_at)*.

| Size (`budget.short.<size>`, `budget.long.<size>`) | What it limits | Small model | Big model (at 128k) |
|---|---|---|---|
| `compact_at` | Prompt tokens from which the older tool results are cut (then again at half as much more) | 24,000 tokens | 60 % of the window |
| `search_chars` | Characters of knowledge found for the question | 2,500 | 10,000 |
| `piece_chars` | Characters of each piece of that knowledge | 450 | 1,800 |
| `context_chars` | Characters of each Context section given with the question | 450 | 4,800 |
| `llm_context_chars` | Characters of the LLM context's lines about the question, at most | 6,000 | 120,000 |
| `tool_chars` | Characters of a tool's result (a query's rows, a search's findings) | 8,000 | 32,000 |
| `describe_chars` | Characters of a description of the data (`describe_data`) | 16,000 | 48,000 |
| `compare_chars` | Characters of a comparison of groups (`compare_groups`) | 12,000 | 36,000 |
| `history_chars` | Characters of each earlier message of the chat | 3,000 | 12,000 |
| `rules_near_chars` | Characters of the team's rules given in full with the question | 1,500 | 6,000 |
| `rule_chars` | Characters of one of the team's rules | 1,500 | 6,000 |
| `group_chars` | Characters of a comparison of logs between groups | 6,500 | 19,500 |
| `shrunk_first` | Characters an older tool result keeps at the first cut | 1,500 | 6,000 |
| `shrunk_second` | Characters an older tool result keeps at the second cut | 500 | 2,000 |

The big model's own sizes are given for a window of 128k tokens and grow or shrink with the window: half of them at
64k, one and a half times at 256k and more, never below the small model's.

Which size is used, in this order: the profile's own setting (`budget.short.*` or `budget.long.*`); else the setting
for both profiles (`agent.compact_at` for `compact_at`, `search.prompt_chars` for `search_chars`); else the profile's
own size.

**When the big model's sizes apply**:

| Setting | Default | What it does |
|---|---|---|
| `budget.long_from_tokens` | 100000 | With `agent.context_profile` = auto: a model whose server states this many tokens per request or more gets the big model's sizes |
| `budget.long_cut_share` | 0.6 | Big model: the share of its window from which the older tool results are cut (unless `budget.long.compact_at` is set) |
| `budget.long_assumed_tokens` | 131072 | The big profile forced on a server that states no window: the window its sizes are made for |

### 4.6 Files, e-mails and other agents

| Setting | Default | What it does |
|---|---|---|
| `tools.export_dir` | `~/superset-exports` | Where images and Excel files are written on the host that makes them |
| `tools.export_max_rows` | 500000 | Rows of an Excel extract at most |
| `tools.email_allowed_domains` | (empty) | The e-mail domains the agent may send to (empty: any) |
| `tools.keep_days` | 7 | Days the files of the answers (images, Excel) are kept for the chat |
| `tools.max_file_mb` | 50 | Files bigger than this are named in the answer but not kept |
| `tools.brief_crossings` | off | Not measured yet: `check_health` also shows the thresholds crossed too briefly to be a breach |
| `mcp.servers` | [] | Other MCP servers whose tools the agent may use: a JSON list of `{name, transport, url or command/args, headers, description, tools, write, allow_write, roles}` (needs `pip install "supagent[graph]"`) |
| `mcp.user` | (empty) | The Superset user that `superset supagent mcp` (the agent's tools served to other agents) acts as; empty: `MCP_DEV_USERNAME` of `superset_config.py` |
| `chats.keep_days` | 0 | Delete the chats nobody used for this many days (0: keep every chat); what they taught stays |

### 4.7 Grafana

The team's Grafana, read through its MCP server (`mcp-grafana` run with `-t streamable-http`). Off until
`grafana.mcp_url` is set. The agent reads the dashboards and the alert rules, explains them in the learning and
watches them in investigations. It drafts alert rules and dashboards only when writes are on, and an Admin approves
each one in To review; it never changes or deletes what exists in Grafana. Which dashboards it reads: *Data
dictionary → Documents and sites → Dashboards and visualizations*.

**Test the connection** (save first) says whether the MCP server answers, or what is wrong.

| Setting | Default | What it does |
|---|---|---|
| `grafana.mcp_url` | (empty) | The MCP server, e.g. `http://grafana-mcp.example:8000/mcp`; empty: no Grafana |
| `grafana.mcp_token` | (secret) | The token the MCP server asks of its callers (its `--server-auth-token`) |
| `grafana.grafana_token` | (secret) | A Grafana service account token sent with each request (empty: the server's own credentials) |
| `grafana.url` | (empty) | Grafana's address as people open it, for the links the agent gives |
| `grafana.roles` | (empty) | The Superset roles whose users may read Grafana through the agent (empty: everyone) |
| `grafana.writes` | off | Alert rules and dashboards may be created, each after an Admin approved its draft (off: drafts only) |
| `grafana.alert_folder` | (empty) | The UID of the folder the approved alert rules go to (empty: none created) |
| `grafana.rule_group` | supagent | The rule group of the approved alert rules |
| `grafana.rule_labels` | `{"managed_by": "supagent"}` | Labels every created alert rule has (JSON) |
| `grafana.label_keys` | severity, team, service, environment | The label keys a draft may set besides those |
| `grafana.datasource` | (empty) | The UID of the Prometheus or Mimir datasource the alert rules query |
| `grafana.dashboard_folder` | (empty) | The folder of a drafted dashboard when no one names one |
| `grafana.dashboard_folders` | (empty) | The folders the agent's dashboards may go to (empty: any) |
| `grafana.cache_seconds` | 60 | Seconds a Grafana answer is kept |
| `grafana.timeout` | 20 | Seconds a call to the MCP server may take |
| `grafana.context` | on | With the nightly Context build: a page per dashboard and per folder of alert rules |
| `grafana.learn` | on | The learning reads Grafana too, each dashboard explained by the AI |
| `grafana.max_llm_calls` | 30 | Dashboards the AI explains at most per learning or Context build (an explanation is written again only when its dashboard changes) |
| `grafana.max_dashboards` | 300 | Dashboards read at most by the nightly Context build |
| `grafana.read_new` | on | A dashboard listed for the first time is read (off: it waits until someone activates it) |

### 4.8 OpenSearch Dashboards

Versions 2.19 and 3.8, read through the saved objects API (GET requests only). Off until `osd.url` is set. The
agent reads each dashboard's visualizations (what they compute, on which index pattern), explains them in the
learning and computes the same on the index with its SQL tools. **Test the connection** (save first) checks it.

| Setting | Default | What it does |
|---|---|---|
| `osd.url` | (empty) | Its address with its base path, e.g. `https://dashboards.example:5601` |
| `osd.auth` | (empty) | How supagent signs in: empty (none), `basic`, `bearer`, `header` |
| `osd.user` | (empty) | The user (`basic`): one that may only read the saved objects |
| `osd.secret` | (secret) | Its password or token |
| `osd.header` | (empty) | The header's name (`osd.auth` = header) |
| `osd.tenant` | (empty) | The tenant whose saved objects are read (`global`, `private` or a tenant's name; empty: the user's default) |
| `osd.verify_tls` | on | Check its certificate |
| `osd.ca_bundle` | (empty) | A CA file on the server to check it with |
| `osd.roles` | (empty) | The Superset roles whose users may read its dashboards through the agent (empty: everyone) |
| `osd.context` | on | With the nightly Context build: a page per dashboard |
| `osd.learn` | on | The learning reads it too, each dashboard explained by the AI |
| `osd.max_llm_calls` | 30 | Dashboards the AI explains at most per learning or Context build |
| `osd.max_objects` | 10000 | Saved objects read at most |
| `osd.timeout` | 30 | Seconds a call may take |
| `osd.read_new` | on | A dashboard or visualization listed for the first time is read (off: it waits until activated) |

### 4.9 Knowledge search and memory

With each question the agent gets the knowledge that looks relevant: the dictionary, the catalog's guides and rules,
the learned answers, the memory, the documents and sites. Words are searched with PostgreSQL's full-text search;
with an embedding model, meanings too; with the extensions pgvector, pg_textsearch or pg_trgm in the database,
everything is also kept in the knowledge store (schema `supagent_store`).

| Setting | Default | What it does |
|---|---|---|
| `search.enabled` | on | Give the agent the knowledge relevant to each question |
| `search.top_k` | 6 | Pieces of knowledge given with each question |
| `search.prompt_chars` | 2500 | Characters of knowledge per question at most (both profiles; `budget.*.search_chars` wins) |
| `search.values` | on | A question that names a value of the data (a server, a service, a status) first gets which labels and fields hold it |
| `search.terms_uncapped` | on | The terms of a glossary and the rules of an entry are each a piece of their own |
| `search.spelling` | on | A searched word no piece holds is read as the known word one typing slip away; the search says so |
| `search.rewrite` | weak | A weak search is written again once by the LLM and both are fused (`off`: never) |
| `search.rewrite_seconds` | 4.0 | Seconds the LLM may take for that |
| `search.judge_meaning_floor` | (empty) | Without a reranker: a closest piece by meaning under this cosine makes the search weak |
| `search.vector_store` | database | Where vectors are searched: `database` (Superset's database, in memory) or `qdrant` |
| `search.store` | auto | The PostgreSQL knowledge store: `auto` (used once built), `on`, `off` |
| `search.store_uri` | (secret) | The PostgreSQL that holds the store (empty: Superset's database) |
| `search.store_schema` | supagent_store | The store's schema (its own: wiped with DROP SCHEMA) |
| `search.bm25` | auto | Words ranked by BM25 of pg_textsearch when installed (`auto`), or PostgreSQL's full-text search (`builtin`) |
| `search.chats` | on | The store keeps the chats: each user may search their own |
| `search.chat_days` | 365 | Days of chats the store keeps |
| `search.chat_box_similarity` | 0.72 | The chat's search box: a chat found by meaning only must be at least this close |
| `embed.model` | (empty) | The embedding model (e.g. `bge-m3`, named as the server lists it); empty: search by words only |
| `embed.base_url` | (empty) | The embedding API base (empty: the LLM's, with the LLM's authentication) |
| `embed.batch` | 16 | Texts per embedding request |
| `embed.per_run` | 2000 | Pieces embedded per indexing run at most (the next run continues) |
| `embed.max_minutes` | 45 | Minutes one reading of the documents and the search's pieces may take (hourly, after a document is read, the learning's step): its embeddings stop there, the next reading continues |
| `embed.query_instruction` | (empty) | A text put before a question when it is embedded, for models trained with one |
| `qdrant.url` | (empty) | The Qdrant server (`search.vector_store` = qdrant) |
| `qdrant.api_key` | (secret) | Its API key |
| `qdrant.collection` | supagent | Its collection |
| `memory.enabled` | on | Learn preferences, rules and facts from the chats |
| `memory.team_approval` | on | Team and group memories wait for an approval before they are used (personal ones are used at once) |
| `memory.prompt_chars` | 2000 | No longer used: every memory is given whole |
| `docs.allowed_domains` | (empty) | Domains documents may be read from (e.g. `wiki.example.com`); empty: public sites only |
| `docs.verify_tls` | on | Check the certificates of the documents' sites (a document can say otherwise) |
| `docs.ca_bundle` | (empty) | A CA file (on every Superset host) to trust for the documents' sites |
| `docs.max_kb` | 2048 | The largest page or file read, in KB |
| `docs.skip_titles` | `\bdeprecated\b` | Pages whose title matches this regular expression are not read, nor the pages they lead to (empty: every page) |

### 4.10 Knowledge

Links to where the knowledge is edited, in the Data dictionary: **What waits for review (N)**, **Catalog**, **Team
memory**, **Documents and sites**.

### 4.11 Settings that are not on the page

These settings are set with `superset supagent settings --set key=value` (or in `superset_config.py`, or the
environment). Some are also written by the Categories tab and the System map, as noted.

| Setting | Default | What it does |
|---|---|---|
| `governed.use_datasets` | on | Governed pipeline: a query on a table that has a Superset dataset runs through the chart data API (its permissions and row-level security apply) |
| `router.min_confidence` | medium | The router's confidence needed to use a route (`low`, `medium`, `high`) |
| `categories.custom` | (empty) | Your own categories besides subject, application and component (written by *Categories → Add* and *+ Category*) |
| `categories.fields` | see below | Where each category's values are read in the data: category → a regular expression of field or label names (written by *Categories → Edit*) |
| `categories.about` | {} | What each category is, in a sentence (written by *Categories → Edit* and the map's *What it is*) |
| `categories.inside` | {} | Categories drawn inside another on the map, e.g. `{"disk": "server"}` (written by *Inside* / *Drawn*) |
| `categories.qualified` | {} | Categories whose values are named after the part they belong to, e.g. `{"disk": "server"}` |
| `categories.review_all` | on | Nothing the learning finds changes the categories before an approval in To review |
| `categories.retire_days` | 14 | A value the data has not shown for this many days is proposed for retirement (0: no such check) |
| `categories.max_values` | 1000 | A field with more values is not read as a list of category values (applications: 60) |
| `categories.relation_min_docs` | 5 | Documents two values must share in an index to be proposed as one part of the other |
| `categories.label_links` | on | Link at once the values a metric's series carry together (off: proposed in To review) |
| `categories.data_link_days` | 21 | A link read from the data that the data has not shown for this many days is proposed for removal |
| `categories.learned_max_chars` | 30 | A value the learning proposes has a name of this many characters at most |
| `categories.learned_max_words` | 3 | … and this many words at most |
| `roles.simple` | off | The roles are Admin, Editor and Viewer: set by `superset supagent roles --apply` / `--undo` only |
| `roles.viewer_data` | none | The data of the Viewer role: `none` (as Superset gives it) or `all` (every database) |
| `charts.scan` | on | With the nightly Context: look at the team's Superset charts (their last full day against the same weekday of the 4 weeks before) and write what each shows |
| `charts.max_charts` | 200 | Charts looked at per night at most (the ones on dashboards first) |
| `charts.minutes` | 20 | Minutes that look may take |
| `charts.max_requests_per_minute` | 12 | Chart queries a minute per database during that look |
| `charts.max_llm_calls` | 40 | LLM calls a night to write what the charts show |
| `knowledge.apply_background` | on | A save in the Data dictionary answers at once; the search follows in the background |
| `knowledge.understand` | on | Read what the documents and the code state, without an LLM (who calls whom, what runs where…) |
| `knowledge.understand_catalog` | on | The catalog's guides, notes, rules and glossaries read the same way |
| `knowledge.understand_llm` | off | The LLM reads the wiki pages and prose documents too (off: it added more wrong links than right ones) |
| `knowledge.llm_units` | 200 | Pages the LLM reads per learning run at most |
| `knowledge.llm_seconds` | 120 | Seconds the LLM may take to read one page |
| `knowledge.propose` | on | Propose what the documents and the code state for the categories and the System map (To review) |
| `rerank.url` | (empty) | A cross-encoder reranker's endpoint (empty: none) |
| `rerank.api` | jina | `jina` (Jina, Cohere, vLLM, llama.cpp, Infinity) or `tei` (text-embeddings-inference) |
| `rerank.model` | (empty) | The reranker model's name (empty: the server's) |
| `rerank.auth` | none | `none`, `token` or `llm` (the LLM's authentication) |
| `rerank.token` | (secret) | Its token (`rerank.auth` = token) |
| `rerank.timeout` | 2.0 | Seconds it may take (later: the search's own order, and no call for a minute) |
| `rerank.depth` | 40 | Pieces read again by the reranker |
| `rerank.weight` | 1.0 | How much its order counts against the search's |
| `rerank.max_chars` | 1500 | Characters of each piece it reads |
| `rerank.judge_floor` | (empty) | A best piece scored under this makes the search weak (`search.rewrite`) |

The default of `categories.fields`:

```json
{"application": "^(application|app|app_name|service|service_name|system|platform)$",
 "component": "^(component|components|module)$"}
```

---

## 5. The LLM usage page

The *LLM usage* tab of the chat page (Admins). It shows every call to the LLM: what it was for, for whom, how big its
context was, how much came from the LLM server's prompt cache, how long it took, and the answers of the chat.

**The period**: *Last 24 hours*, *Last 7 days*, *Last 30 days*, *Last 90 days* (shown at once when chosen), or
*Dates...* with **From** and **To**; **By** *auto* (by hour up to three days, else by day), *hour* or *day*; **Show**
reads it again. Hours and days are counted in **your browser's time zone**, by its name, so a period across a change
of summer time counts each call in its own hour. A period of more than 500,000 calls is cut (the page says so:
choose a shorter one). The calls are kept `usage.keep_days` days (90).

### 5.1 The tiles

| Tile | What it counts |
|---|---|
| **Tokens** | The tokens of every LLM call of the period: the context sent plus the answer written (*N sent, N written*) |
| **LLM calls** | The number of calls, and how many failed |
| **Context size** | The average context of the calls, in tokens (a failed call that has no size is left out), the size 95 % of them stay under, and the largest |
| **From the prompt cache** | The share of the context tokens the LLM server took from its prompt cache instead of reading them again (when the server reports it), and how many tokens that was |
| **Time per call** | The average time of a call, and the time 95 % of them stay under |
| **People** | The users the calls were made for (the background work is not counted) |
| **Answers** | Every answer of the chat in the period, with its average time and the time 95 % stay under |
| **Calls per answer** | The average LLM calls and tool calls of an answer, and how many tool calls failed in all |
| **Sent back by the checks** | How many times a check sent an answer back to the model before it was shown: a rule, a period or a database not applied, no tool called, a number not from the data (section 6.4) |
| **Answers marked** | The answers that still ended with a *(Check: …)* note |

**Tokens over time, by task**: a chart of the tokens (context plus answer) or of the calls (**Tokens** / **Calls**),
per hour or per day, one line or bar per task.

### 5.2 The tables

* **By person**: Person (*(nightly and background work)* for the calls made for no one), Answers (their answers in
  the chat), Tokens, Calls, Avg context, Largest, Cache %, Avg s, Failed.
* **By task**, the same figures per task: *Answers in the chat*, *Daily learning (descriptions)*, *Context
  (nightly)*, *Memory from the chats*, *Learned answers (Helpful)*, *Agent catalog*, *Tidying learned answers*, *Chat
  names*, *LLM tests*, *Categories of the knowledge*, *What the charts show*, *Other background work*, *Other* (a task
  with no name of its own is shown by its key).
* **By model**: the same figures per model.
* **The biggest contexts**: the 10 calls with the largest context: When, Task, For, Context, Cached, s.
* **The slowest answers**: the 10 slowest answers: the Question, For, s, LLM calls, Tool calls, Context.

The command `superset supagent stats --days N` gives where the time of the answers goes from the command line.

### 5.3 The Servers card

Every server a Superset component runs on (a web server, a Celery worker, Celery beat), one row per host. Each
process of a component writes its host's figures every minute (read from `/proc`: Linux, nothing to install); the
card is read again every minute.

| Column | What it shows |
|---|---|
| **Server** | The host name |
| **Components** | `web`, `worker`, `beat`; *(gone)* when that component has not written for 5 minutes (the host is down or the component no longer runs there) |
| **CPU** | The CPU used over the last minute, in % (red from 85 %) |
| **Load 1 · 5 · 15** | The load averages and the number of cores (red when the 1-minute load is above the cores) |
| **Memory** | Used of total (used = total minus available), and the % (red from 90 %) |
| **Swap** | Used of total (red above half); *none* when there is no swap |
| **Superset's disk** | The disk that holds Superset's home (`SUPERSET_HOME`, else `~/.superset`: its configuration, uploads and, by default, the backups) and the disk of its installation (the virtualenv): one line when both are on the same disk. Used of total, %, and the free space as the system lets Superset use it (red from 90 %). Hover a line to see what it holds |
| **Superset processes** | How many processes of this host run Superset or supagent, and the memory they hold |
| **CPU, 24 h** / **Memory, 24 h** | Small lines of the last 24 hours (a point every 5 minutes); hover for the peak |
| **Seen** | *now*, or how many minutes ago the host last wrote |

A host appears once its processes run supagent 0.10.11.1 or later; restart the web servers, workers and beat after
an upgrade.

---

## 6. How the agent works (for admins)

### 6.1 Where answers run

With `agent.executor` = `auto` (the default), a question goes to Superset's Celery workers while one of them is
alive (each worker writes a heartbeat in Superset's database every 30 seconds). With no worker alive, or none that
started the question within 15 seconds, the web server that received it answers in a thread. Whatever the number of
workers and web servers, a question is answered once. A worker holds at most as many questions as it has processes.

The background LLM work (the learning's descriptions, the learned answers and memories from a *Helpful*) waits while
answers are being computed, so that the LLM serves the people waiting first. An answer with no progress for 35
minutes is marked as failed.

### 6.2 What the agent is given: the context in tiers

New in 0.11.0 (`agent.context_tiers`, on). Each question goes to the LLM with a context built in three tiers, so
that what the team keeps always comes first and nothing is said twice:

1. **The instructions** with the tools and the team's rules (the catalog's first 30 rules), then **what the team
   keeps**, given whole, each said once:
   * the memories that apply to this user (theirs, their groups', the team's);
   * the team's rules again next to the question (in full when they are short, else a line pointing to them);
   * the terms of the glossary the question uses;
   * the parts of the system the question names, and for an investigation or a question about how the system works
     or how parts connect, the picture around them (the System map);
   * **where the data is**: the tables, metrics and fields the question's words lead to;
   * the learned answers of similar questions (up to three, one per tool, database and query).

   A text that says the same as another (the same words in the same order, case, punctuation, plurals and small
   words aside) is given once. Anything that changes what it says keeps both: another word (a qualifier, a
   condition), a negation, an operator or a sign, a modal verb, a quoted value as written ("durations in minutes"
   and "durations in seconds" both stay). Texts alike but not the same are both given, and listed in *To review*
   (duplicates) for a person to decide.

2. **The chat**: the messages of the question's subject (at most 40): always the last complete exchange (the last
   question that was answered, and what follows it), then the older messages, the newest first, as many as fit in
   the room left, never starting with an answer. The room is half of the model's window (about four characters a
   token; a window the server does not state counts as 64k tokens for a small model, `budget.long_assumed_tokens` for
   a big one) minus the instructions, the tools sent with this question and the first tier, keeping room for the
   documentation. Each message is cut at `history_chars`.

3. **The documentation chosen for the question**, in the room left:
   * the knowledge found by the search: the catalog's and the agent's entries, the glossary, memories and learned
     answers first (up to half of this room), then the documents and the Context; a piece that says the same as a
     text of the first tier is left out;
   * the **LLM context's lines about the question**: the LLM context is a page the learning writes (the catalog's
     rules, glossary, formulas and facts, the main data with its meaning and fields, the links between databases,
     the questions answered well before), in a full and a light version. The agent takes from it only the lines
     whose subject the question names, or that name the main data of a database the question is about, up to
     `llm_context_chars` and never the whole page; a line about an entry given already is left out. The full version
     is used for a big model; a small model gets the light version only when `agent.llm_context` was set on by a
     person; with `agent.llm_context` off, none.

With `agent.context_tiers` off, the agent works as 0.10.12 did: the LLM context whole in the instructions and the
chat's last 40 messages. `superset supagent prompt "<question>" --user <name>` prints exactly what the LLM would be
given for a question, without asking the LLM.

### 6.3 While it answers

The agent calls tools: it searches the knowledge, describes the data, runs SQL or PromQL with the user's permissions,
compares groups and periods with what is usual, reads logs and records, checks health, saves charts or dashboards,
makes Excel files and images, reads Grafana and OpenSearch Dashboards. A big request gets a work plan (`agent.ledger`).

Limits: `agent.max_steps` tool calls (16; `agent.max_steps_big`, 32, for an investigation or charts and
dashboards); after `agent.answer_seconds` (1,500 s) it must answer with what it found. When the conversation grows
past `compact_at` prompt tokens, the older tool results are cut to their first lines and the work plan is given
again.

### 6.4 The checks of an answer

Every answer is checked by code before it is shown; most checks need no LLM call:

* **before a query runs**: a SUM or COUNT over a join that repeats rows, a condition that turns a LEFT JOIN into an
  inner join, a sum of a counter's raw values, a field the team said not to use, an OpenSearch query that would read
  more than `agent.osagg_max_scan_rows` raw documents: refused or sent back with how to write it;
* **after the answer is written**: every number must come from a query result, the question or the knowledge; the
  team's rules must be applied in the queries; a value the question names must be filtered on; a follow-up keeps the
  chat's period and conditions; a query shown must have run; a cause must be tied to the question's parts; a count
  must not be a LIMIT; an answer with figures and no query is sent back with a tool call made compulsory
  (`agent.force_tool`).

An answer that fails a check is sent back to the model once, with what to fix (the *Sent back by the checks* tile).
If it still fails, the answer is shown with a *(Check: …)* note (2.4; the *Answers marked* tile). Each check has its
setting in the *Agent* section (4.4).

### 6.5 What the agent learns from the chats

* **Learned answers**: only from *Helpful*; they wait in To review; a confirmed one is proposed first for similar
  questions, by anyone who may query its database. One that people keep marking *Not helpful* is no longer
  proposed.
* **Where the data is** (`learn.associations`): the words of a question and the tables its successful queries read;
  *Not helpful* takes them back.
* **Memories**: from "remember…", "from now on…", "always…", from *Helpful*, from what a message states about the
  data, and from the reason given with *Not helpful*. Personal ones are used at once; team ones wait for approval.
* **Query timings**: how long each kind of query takes, shown to the agent next to the table.
* **Kinds of work**: the router's classification of questions people confirmed.

### 6.6 The daily learning

One run a day at `learn.hour` on `learn.days`, started by the hourly task (section 7): a day without a run yet gets
it at the next hour, after an outage too. The databases never learned come first, each with a fair share of
`learn.max_minutes`. Its steps, each listed under the run:

1. for each database: list the metrics or the indices with their types (every day), profile the ones due today
   (statistics refreshed every `learn.profile_every_days`), note what changed, and let the LLM describe what has no
   description while it reads (marked AI-written);
2. measure the **relations** between databases (a label and a field that hold the same values);
3. apply the **catalog**; describe what is still missing with the time left;
4. the **categories** (unless the Context build does them that night, `context.classify_after`): the values read in
   the data's fields, the items classified by the LLM (`learn.classify_per_run`), one value per thing, parts that
   look retired, the interactions documents and logs state, the links explained — all proposed in To review;
5. the **agent's catalog entries**, the generic questions of the learned answers, Grafana and OpenSearch Dashboards;
6. the **search index** and its embeddings, and a check of how well "where the data is" finds the data of the
   *Helpful* answers.

It is gentle with the databases: `learn.max_requests_per_minute` (one request at a time) and a database is left for
the day after `learn.stop_after_errors` overload errors in a row. `superset supagent learn --plan` says what today's
run would do without reading any data. **Stop** (Settings) or `superset supagent learn --stop` stops it; it keeps
what it learned. To learn a database again from scratch: `superset supagent forget-learned` (section 8).

### 6.7 The nightly Context

At `context.hour` (04:00), after the day's learning (never next to another run), the Context is built: the facts
pages without the LLM, the summary pages with it (at most `context.max_llm_calls` calls, only for the pages whose
evidence changed; `--force` writes them again anyway), the relations diagrams from what the documents and the code
state, the look at the team's charts (`charts.scan`), the Grafana and OpenSearch Dashboards pages, the system pages
and the LLM context. With `context.review` on, a change of an existing page waits in To review; a page a person
corrected is never written over. Then the classification runs on what it wrote (`context.classify_after`).

### 6.8 The search

Every piece of knowledge (a description, a catalog entry, a glossary term, a memory, a learned answer, a page of a
document, a Context page, a value of the System map with its links, a chart) is searchable by words, and by meaning
when `embed.model` is set. With the knowledge store in PostgreSQL, near spellings are found too. A misspelled word
is read as the known word one typing slip away; a weak search may be written again once by the LLM
(`search.rewrite`); a reranker can order the results again (`rerank.*`). A user finds only what they may see: the
pieces of the databases they may query, the team's pieces and their own memories.

A save in the Data dictionary updates the pieces it changed at once, in the background; the hourly indexing catches
up on anything left (vectors of more than 64 pieces, documents due to be read again).

---

## 7. What is cleaned automatically, and when

supagent's periodic work runs in one task, every hour at minute 7, sent by **Celery beat** and run by a **Celery
worker**. In order: the clean-ups below; the daily backup when it is due (else the backups are pruned); the daily
learning when it is due (else the documents due are read again and the search is indexed); the upkeep of the
knowledge store; the nightly Context when it is due, then the classification.

| What | When | Setting (default) |
|---|---|---|
| Chats nobody used, with their messages, files and answer timings (what they taught stays) | every hour | `chats.keep_days` (0: never) |
| Files of the answers kept in Superset's database (images, Excel) | every hour | `tools.keep_days` (7 days) |
| Files in the export directory of a host | each time a new file is written there | environment variable `EXPORT_KEEP_DAYS` (7 days) |
| Records of the LLM calls (the usage page) | every hour | `usage.keep_days` (90 days; 0: kept) |
| The learning's history: finished runs (learning, classification, Context, backups, restores, documents) and the changes they found | every hour | `learn.history_days` (30 days; 0: kept). The last run of each kind and a run still going are always kept |
| Backups beyond the newest `backup.keep`, and those older than `backup.keep_days` | after each backup and every hour | `backup.keep` (14), `backup.keep_days` (30; 0: by number only). The newest backup is always kept |
| Backups made before a restore | the same | the last 5 kept, none older than `backup.keep_days` |
| Files a stopped backup left behind (`.zip.part`) | the same | after a day |
| Delivered messages of a Celery queue kept in Superset's database | every hour | `agent.queue_keep_days` (90 days; 0: never) |
| Heartbeats of workers that stopped | every hour | — |
| The record of which learned items each answer used (their ranking) | every hour | older than a year and a month |
| Chats kept in the knowledge store (search your chats) | the store's hourly upkeep | `search.chat_days` (365) |
| An answer with no progress (a worker restarted) | when its chat is read | marked failed after 35 minutes |

The knowledge itself is never cleaned by age: catalog entries and their versions, memories, notes, documents,
Context pages, learned answers and the dictionary stay until a person removes them (or a newer learning finds an
object gone).

**Without beat and a worker, none of this runs**: no clean-up, no daily backup, no daily learning, no nightly
Context. The Settings page then says *none in the last day, is Celery beat running?*. Run them from cron instead
(`superset supagent learn`, `superset supagent backup`, `superset supagent context --build`); the clean-ups have no
command of their own.

---

## 8. Command line reference

Run the commands on a Superset host, with Superset's virtualenv and configuration (the same `SUPERSET_CONFIG_PATH`
and environment as the web server): `superset supagent <command> [options]`. A command that changes or deletes
something in bulk only says what it would do until you add `--yes`. Commands that read "as a user" see what that
user may see (default: the learning user, `learn.user`).

**Installation and access**

| Command and options | What it does |
|---|---|
| `init [--viewer-data none\|all]` | Creates or upgrades the tables, the permissions and the roles (AI Admin, AI Editor, AI Viewer; or Admin, Editor, Viewer with `roles.simple`), builds the knowledge store the first time it finds the PostgreSQL extensions. `--viewer-data all`: the Viewer role reads every database |
| `grant USER [USER ...] [--role viewer\|editor\|admin\|agent]` | Gives users a role (default `viewer`; `agent` is the role of earlier versions) |
| `roles [--apply] [--undo] [--force]` | Without an option: what would change to have only Admin, Editor and Viewer (and what stops it). `--apply` does it (a copy of every user's roles is kept); `--undo` goes back; `--force` even when row-level security filters or dashboards name a role that goes |
| `settings [--set KEY=VALUE ...] [--unset KEY ...]` | Shows every setting (secrets: only whether set), or changes some; `--unset` removes a saved value (the setting then comes from `superset_config.py`, the environment or its default) |
| `test-llm [--profile]` | Gets a token (middleware), finds the model, asks for one word, says what supagent adapts to the LLM; `--profile` also measures thinking, tool calls and the prompt cache (a minute) and prints both profiles' sizes |
| `mcp [--host HOST] [--port 5009]` | Serves the agent's tools over MCP (streamable HTTP) for other agents, as the user `mcp.user` (needs `fastmcp`). By default it listens on this host only; keep it there or behind your gateway |

**Learning and the Context**

| Command and options | What it does |
|---|---|
| `learn [--database NAME ...] [--no-llm] [--minutes N] [--plan] [--stop]` | A learning run now (what the daily run does). `--database` only those; `--no-llm` no AI descriptions this time; `--minutes` its time limit; `--plan` only estimates today's work (objects due, requests, minutes); `--stop` stops the running run |
| `classify [--minutes 15] [--limit 400]` | The classification now (categories, relations), a run listed in Settings |
| `interactions [--minutes 15] [--limit 200] [--again]` | Reads the documents, guides, Context pages and notes for the interactions they state, proposed in To review; `--again` reads every text again |
| `interactions --explain [--again] [--kinds K,...] [--minutes N] [--limit N]` | Writes the short and long explanations of the links that lack them (the approved first); `--again` writes again those the AI wrote alone (an admin's words stay); `--kinds` only those kinds (e.g. `runs_on,monitors`) |
| `understand [--show] [--propose]` | Reads what the documents and the code state (the units whose text changed); `--propose` proposes it for the categories and the map; `--show` prints every relation with its sources |
| `consolidate [--dry-run] [--llm-calls N] [--mode propose\|auto]` | One value per thing: proposals that name the same thing as another value put together (`--dry-run`: shown only) |
| `context [--build] [--no-llm] [--force] [--no-classify]` | Lists the Context pages; `--build` builds it now (`--no-llm`: facts pages only; `--force`: summary pages written again even when their sources did not change; `--no-classify`: no classification after it) |
| `charts [--scan] [--understand] [--chart N ...] [--minutes N]` | The look at the team's charts now: `--scan` their last full day against the 4 weeks before, `--understand` what they show (LLM), then what was found |
| `agent-catalog [--no-docs]` | Lets the agent write the catalog entries it is certain of now (`--no-docs`: not the documents, no LLM call) |
| `tidy-learned [--limit 200]` | Rewrites the questions of learned answers and the chat names that are not generic yet, merges the duplicates (LLM) |
| `index [--refresh-docs]` | Updates the searchable pieces that changed and their vectors; `--refresh-docs` also reads the sites that are due |
| `forget-learned [--database NAME ...] [--everything] [--yes]` | Forgets what the learning learned (dictionary, AI descriptions, measured relations, changes) to learn it again from scratch; `--everything` also what people did in the dictionary; without `--yes`, only shows what would go |
| `reset-knowledge [--context] [--categories] [--links] [--all] [--yes]` | Wipes what the learning made, to make it again: the Context pages, the categories' values, the map's links; what people made stays (`--all`: that too). A backup is made first; without `--yes`, only shows what would go |
| `remove-auto-learned` | Deletes the learned answers that versions 0.2.1 and before saved by themselves |

**The catalog**

| Command and options | What it does |
|---|---|
| `import-catalog PATH [--replace]` | Splits a catalog (YAML) into entries and applies it; `--replace` also deletes the structured entries the file does not have |
| `export-catalog` | Prints every enabled entry merged into one YAML (conflicts and invalid entries on stderr) |
| `push-descriptions [--labels]` | Writes the catalog's descriptions into the dataset columns' descriptions (`--labels`: their verbose names too, which relabel existing charts) |
| `push-metrics` | Writes the catalog's metrics into Superset datasets with their saved metrics |

**Checking the knowledge and the agent**

| Command and options | What it does |
|---|---|
| `check-knowledge [--json]` | Is everything the team put in given to the agent? (pieces out of step, vectors, catalog errors and unknown names, rules, what waits); exit code 1 on a problem |
| `check-system [--question "..."] [--user U] [--json]` | What the agent knows of the system for an investigation and what is missing; with `--question`, what it is given for it (no LLM) |
| `lint [--json]` | The warnings of To review (what could confuse the agent or the search), each with a fix |
| `knowledge [--changes N] [--user U]` | What is learned per database, the relations, the last runs; `--changes N`: the changes of the last N days |
| `describe [TOPIC] [--name INDEX_OR_METRIC] [--user U]` | What `describe_data` gives the agent for these words, or for one index or metric |
| `search QUERY [--user U] [--limit 8]` | Searches the knowledge as the agent does |
| `prompt QUESTION --user U [--full]` | What the agent gives the LLM for a question, without asking the LLM (`--full`: the whole instructions) |
| `ask QUESTION --user U [--steps/--no-steps] [--pipeline classic\|governed]` | Asks the agent a question in this process, as a user, and prints its tool calls and answer |
| `stats [--days 7]` | Where the time of the answers goes: LLM and tools, prompt sizes, prompt cache, the slowest |
| `evaluate [--limit 200] [--user U]` | Does "where the data is" find the data of the Helpful answers? (hit@1, hit@3, MRR) |
| `gaps [--days 30] [--user U]` | Questions not answered well (Not helpful, failed, no data found) and learned answers about data that no longer exists |

**The knowledge store** (PostgreSQL)

| Command and options | What it does |
|---|---|
| `store status` | Where it is, its extensions and versions, its size, the warnings to read |
| `store rebuild` | Builds it again beside the one in use, then switches |
| `store sync` | Brings it in step now (it is, hourly and after each change) |
| `store wipe [--yes]` | Drops it (the built-in search answers until the next rebuild); asks unless `--yes` |
| `store search QUERY [--user U] [--limit 8] [--chats]` | Searches it as a user would, each piece with how it was found; `--chats`: the user's own chats |

**Backups and chats**

| Command and options | What it does |
|---|---|
| `backup [--vectors/--no-vectors]` | A backup of the knowledge now, in `backup.dir` (default for vectors: `backup.vectors`) |
| `backups` | The backups of this server, the latest first, with what each holds |
| `restore NAME [--parts a,b,...] [--yes]` | Puts back a backup of `backup.dir`, whole or by part (`categories`, `catalog`, `memory`, `documents`, `notes`, `context`, `learned`, `dictionary`, `settings`, `vectors`); the present state is saved first; without `--yes`, lists what it holds |
| `conversations [--user NAME] [--limit 30]` | Lists the chats, the latest first, with their user, messages and size |
| `conversations --delete ID [--delete ID ...] [--yes]` | Deletes those chats with their messages, files and examples (without `--yes`: what would go) |
| `conversations --user NAME --all [--yes]` | Deletes every chat of that user |

**Examples**

```bash
# connect the LLM through a company middleware, then test it
superset supagent settings \
  --set llm.base_url=https://llm-gateway.example/v1 --set llm.model=<model> \
  --set llm.auth=middleware --set llm.middleware.token_url=https://auth.example/oauth2/token \
  --set llm.middleware.consumer_key=<key> --set llm.middleware.consumer_secret=<secret>
superset supagent test-llm --profile

# give roles
superset supagent grant analyst1 analyst2 --role viewer
superset supagent grant curator1 --role editor

# learn one database now, with more time the first time
superset supagent learn --plan
superset supagent learn --database "Orders logs" --minutes 240

# build the Context now and check what reaches the agent
superset supagent context --build
superset supagent check-knowledge
superset supagent prompt "failed orders of checkout-api yesterday" --user analyst1

# backups
superset supagent backup
superset supagent backups
superset supagent restore supagent-knowledge-20261017-010700.zip --parts catalog,memory          # shows only
superset supagent restore supagent-knowledge-20261017-010700.zip --parts catalog,memory --yes    # does it

# a heavy chat that freezes a browser
superset supagent conversations --user analyst1
superset supagent conversations --delete 1234 --yes
```

---

## 9. Troubleshooting and FAQ

**1. Test the LLM fails, or every answer ends in an error about the LLM.**
* `llm.base_url` is what comes before `/chat/completions` (often ending in `/v1`); `llm.model` is the name the
  server lists (empty: its first model).
* Authentication: with `llm.auth` = middleware, check the token URL, the consumer key and secret, the client
  certificate and key paths (they must exist **on every host**, the workers included: the workers answer), the
  scope. With `token`, the token.
* Certificates: `llm.ca_bundle` for a company CA; `llm.verify_tls` only as a last resort.
* Run `superset supagent test-llm` on a web server **and** on a worker host: the error says which step failed. The
  workers need the same environment as the web server (`SUPAGENT_*` variables, proxies, certificate paths).
* A slow server: raise `llm.timeout` (900 s by default).

**2. Answers are slow.**
* *LLM usage*: *Time per call* (the LLM server), *Context size* (a big context is slow to read), *Calls per answer*,
  *The slowest answers*; or `superset supagent stats --days 7`.
* The LLM server serves a limited number of requests at once (its parallel slots, a gateway's quota): many people at
  once wait for it. Background LLM work waits for the answers, but a long learning run still shares the server.
* A wrong context profile gives a big context to a small model (see 7 below).
* Investigations take longer by nature; `agent.max_steps_big`, `agent.compare_seconds` and `agent.answer_seconds`
  bound them.
* Without Celery workers, answers run in the web server's processes and compete with Superset's pages.

**3. An answer stays on "Waiting for the agent…".**
* The status line of Settings: *no Celery worker: questions wait for one (agent.executor = celery)* means no worker
  is alive; start one, or set `agent.executor` to `auto`.
* With `auto`, a question no worker starts within 15 seconds is answered by the web server: check the web server's
  log (logger `supagent`).
* An answer with no progress for 35 minutes is marked failed; **Stop** frees the conversation at once.
* "the previous question of this conversation is still being answered": stop it, or open a new conversation.

**4. The chat (or the panel on every Superset page) freezes or stays blank.**
* A chat whose answer holds very heavy rows or labels can be slow to draw. When a chat did not finish opening, the
  next load says so and does not open it again: use **Delete it**, or delete it from the command line
  (`superset supagent conversations --user NAME`, then `--delete ID --yes`).
* "The chat cannot be shown here" in the panel: the chat page could not be shown in a frame (Talisman's
  `frame_options` set to DENY, or the session expired and a login page came back). Open the full page from the
  link; with DENY, set `frame_options` to SAMEORIGIN in Superset's Talisman configuration.
* After an upgrade, nothing to clear: the page files carry their content's hash in their names.

**5. A page of the Data dictionary is slow.**
* The System map reads itself again every 20 seconds while it is shown; filter it (the box above it) or fold the big
  categories. Large maps are faster with the parts grouped (a category's ⓘ, *Its parts grouped by*).
* *To review* computes its warnings once per change of the knowledge; the first load after a change takes longer.
* A wiki of thousands of pages: its page list loads only when you click **Pages**.
* Check the web server on the Servers card (CPU, memory, load).

**6. The daily learning does not run.**
* Settings status line: *none in the last day, is Celery beat running?* means that no scheduled run started in the
  last day: Celery beat or the workers are not running. Run **one** beat for all hosts, and at least one worker,
  both started with Superset's configuration. *daily learning not scheduled* means supagent's hourly task is missing
  from the beat schedule of that configuration: check that `superset_config.py` registers supagent
  (`FLASK_APP_MUTATOR`) and that nothing replaces the beat schedule after it.
* `learn.enabled`, `learn.hour` (server time) and `learn.days`.
* A run that is still *running* or *stopping* blocks the next one: **Stop**, then **Learn now**.
* A database missing from a run: the run's summary says why (left out by `learn.databases`, or the learning user
  `learn.user` may not read it). `superset supagent learn --plan` says what today's run would do.
* A database marked *partial* (*stopped at its share of the time*): the next run continues. Give the first run more
  time: `superset supagent learn --database NAME --minutes 240`.
* *stopped after N failures in a row*: the database was overloaded (429, 5xx, timeouts) and left for the day; lower
  `learn.max_requests_per_minute`.
* A run long at *search index and embeddings*: the step says what it does (*running (embeddings: 400 of 2,000)*).
  Its embeddings stop at its time (what is left of the run's, ten minutes at least, `embed.max_minutes` at most) and
  the hourly readings embed the pieces left; until then they are found by their words. A big backlog (a new wiki or
  repository, a reader change): `superset supagent index --minutes 240` on a worker host. An embedding model on CPUs
  that times out: a smaller `embed.batch`.

**7. The Context is not rebuilt, or a page did not change.**
* `context.enabled` and `context.hour`; the build runs after the day's learning and never next to another run: look
  for a *context* run in the runs list, with its steps.
* A summary page is written again only when its sources changed (`superset supagent context --build --force` writes
  it anyway), and at most `context.max_llm_calls` pages a build (the next night goes on).
* With `context.review` on, the change of an existing page waits in **To review** until someone approves it.
* A page a person corrected is never written over: **Give it back to the agent** first.
* Editors can press **Build now** but cannot open Settings: the page says the build started, and the pages show in
  the Context when it is done (a changed page waits in To review); an Admin sees the run in Settings.

**8. To review is empty, or something expected is not proposed.**
* The tab is for Editors and Admins only. A filter typed in its box hides the rest: clear it.
* Values and links are proposed by the classification and the learning: check the last *classify* and learning runs
  (Settings) and their steps; **Classify now** runs it at once. `learn.classify_per_run` limits each run.
* Documents are read for parts and links when `knowledge.understand` and `knowledge.propose` are on; run
  `superset supagent understand --propose --show` to see what they state.
* `superset supagent check-knowledge` and `superset supagent lint` say what is out of step.

**9. A restore did not happen, or did not do what was expected.**
* "run N (…) is still running: restore after it": wait for the run, or **Stop** it.
* "not a backup of the knowledge", "made by a later version: upgrade first", or a file larger than
  `backup.upload_max_mb`: the file brought from elsewhere was refused.
* Several web servers: the list shows the backups of the server that answered the page. Give them a shared
  `backup.dir`.
* Only the parts ticked are replaced. The present state was saved first (`…-before-restore.zip`): restore that one
  to undo.
* The vectors of what came back are computed by the hourly indexing (`superset supagent index` does it now).
* Secrets are never in a backup: on another Superset, enter the LLM token and the sites' sign-ins again.

**10. The disk is full, or filling.**
* The Servers card shows the disk Superset is on in red from 90 %.
* Backups: lower `backup.keep` or `backup.keep_days`, keep `backup.vectors` off, or move `backup.dir` to a larger
  disk. Each restore adds a `…-before-restore.zip`.
* The export directory (`tools.export_dir`, on each host) holds Excel files and images; they are removed after
  `EXPORT_KEEP_DAYS` days (7) when new ones are written.
* In Superset's database: the chats (`chats.keep_days`), the answers' files (`tools.keep_days`), the LLM calls
  (`usage.keep_days`), the learning history (`learn.history_days`), a database queue (`agent.queue_keep_days`).
  None of these clean-ups run without beat and a worker (section 7).

**11. The wrong context profile is used.**
* *Settings → What the agent gives the LLM* says the profile in use and the window the model reads. With
  `agent.context_profile` = auto, the profile follows the window the LLM server states; a gateway often states none:
  set `agent.context_tokens` to the model's real window, or choose `short` or `long` yourself.
* Some servers state the window per parallel slot (the whole context divided by the slots): that is the real room
  of one request.
* **Test the LLM** reads the window again after the LLM server changed. Read the warnings of that section: a start of
  answer bigger than half the window leaves little room for the results.

**12. A user cannot see something, or gets "not allowed".**
* No *Chat* tab: the user has no role of the agent (`superset supagent grant USER --role viewer`).
* "your role (AI Viewer) keeps memories for yourself only" / "writes notes for yourself only": a Viewer cannot
  share; give the Editor role if needed.
* An Editor's delete is refused: deletions are an Admin's.
* The agent finds no data: it uses the user's own Superset permissions (database access, datasets, row-level
  security). A Viewer has no data unless Superset gives it (or `roles.viewer_data` = all).
* A Context page or a learned answer is missing for a user: it is shown only to users who may query every database
  it is about.

**13. The agent says there is no data, or queries the wrong table.**
* Is the database learned? (the *Databases* line of the Data dictionary). Is the object deactivated (*Data →
  Browse → Deactivated*) or left out by `learn.indices` / `learn.metrics`?
* *Learned by the agent → Where the data of the questions was*: remove a wrong word (×) or add the team's words to a
  table (**Add**).
* Describe the table or field in *Data → Browse*, or add a catalog entry. `superset supagent describe "words"`,
  `superset supagent search "words"` and `superset supagent check-system --question "..."` show what the agent finds.

**14. A document, a wiki or a repository is not read.**
* Its state and error in *Documents and sites*; **Pages** lists what was not read and why.
* An intranet address needs its domain in `docs.allowed_domains`. A certificate this server does not trust: a CA
  file (`docs.ca_bundle`, or the document's own) or, last resort, *Not checked*.
* "the site asked to sign in": set the sign-in (Edit). *limit of N pages reached*: raise *Pages or files at most*.
* Pages whose title matches `docs.skip_titles` are skipped.

**15. Grafana or OpenSearch Dashboards: Test the connection fails.**
* Save the settings first: the test uses the saved ones. "not set up: save grafana.mcp_url first".
* Grafana: the MCP server must run with `-t streamable-http` and be reachable from every Superset host;
  `grafana.mcp_token` must match its `--server-auth-token`. Only users of `grafana.roles` may use it.
* OpenSearch Dashboards: the address with its base path, the sign-in, the tenant, the certificate.

**16. Learn now (or Classify now, Back up now, Restore) says a run is already running.**
* One run at a time for all the hosts: learning, Context, classification, backup and restore. Wait for it (the runs
  list refreshes itself), or **Stop** it: the run is marked stopped at once and a new one can start right away
  (also when the process of the old run died, after a restart).

**17. A setting seems ignored.**
* The saved value wins over `superset_config.py`, which wins over the environment: `superset supagent settings`
  prints the value in use.
* Some settings are not on the Settings page (4.11): set them with the command line.
* `usage.keep_days` is shown in the Agent section but saved only from the command line in this version.

---

*supagent 0.11.0. Settings, buttons and commands are described as the code of this version has them.*
