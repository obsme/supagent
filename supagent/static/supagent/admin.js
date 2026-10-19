/* supagent admin page: settings, LLM test, learning runs (the knowledge is edited in the Data dictionary) */
(function () {
  "use strict";
  var S = window.supagent, el = S.el;
  var $ = function (id) { return document.getElementById(id); };
  var specs = {};
  var LABELS = {
    /* (0.10.11) Grafana (its MCP server) and OpenSearch Dashboards */
    "grafana.mcp_url": "MCP server address", "grafana.mcp_token": "MCP server token",
    "grafana.grafana_token": "Grafana service account token", "grafana.url": "Grafana address (for the links)",
    "grafana.roles": "Roles that may use it", "grafana.writes": "Drafts may be created (each one approved)",
    "grafana.alert_folder": "Folder of the alert rules", "grafana.rule_group": "Rule group",
    "grafana.rule_labels": "Labels of every rule (JSON)", "grafana.label_keys": "Label keys a draft may set",
    "grafana.datasource": "Datasource UID (Prometheus or Mimir)", "grafana.dashboard_folder": "Folder of new dashboards",
    "grafana.dashboard_folders": "Folders new dashboards may go to", "grafana.cache_seconds": "Cache (s)",
    "grafana.timeout": "Timeout (s)", "grafana.context": "Context pages", "grafana.learn": "Explained in the learning",
    "grafana.max_llm_calls": "LLM calls per learning", "grafana.max_dashboards": "Dashboards read at most",
    "grafana.read_new": "New dashboards read",
    "osd.url": "Address (with its base path)", "osd.auth": "Sign-in", "osd.user": "User",
    "osd.secret": "Password or token", "osd.header": "Header name (sign-in by header)", "osd.tenant": "Tenant",
    "osd.verify_tls": "Check TLS certificates", "osd.ca_bundle": "CA bundle (PEM file)",
    "osd.roles": "Roles that may use it", "osd.context": "Context pages", "osd.learn": "Explained in the learning",
    "osd.max_llm_calls": "LLM calls per learning", "osd.max_objects": "Saved objects read at most",
    "osd.timeout": "Timeout (s)", "osd.read_new": "New dashboards read",
    "llm.base_url": "API base URL", "llm.model": "Model", "llm.auth": "Authentication", "llm.token": "Access token",
    "llm.middleware.token_url": "Middleware token URL", "llm.middleware.consumer_key": "Consumer key",
    "llm.middleware.consumer_secret": "Consumer secret", "llm.middleware.cert_path": "Client certificate (PEM file)",
    "llm.middleware.key_path": "Client key (PEM file)", "llm.middleware.scope": "Scope",
    "llm.middleware.renew_before": "Renew the token before expiry (s)", "llm.ca_bundle": "CA bundle (PEM file)",
    "llm.verify_tls": "Check TLS certificates", "llm.timeout": "Timeout (s)", "llm.temperature": "Temperature",
    "llm.thinking": "Reasoning (thinking) mode", "llm.extra_headers": "Extra HTTP headers (JSON)",
    "agent.max_steps": "Tool calls per question", "agent.max_steps_big": "Tool calls of an investigation or a dashboard", "agent.general_answers": "General questions without the data", "agent.subjects": "Follow the subjects of a chat", "agent.now": "Fixed “now”", "agent.extra_instructions": "Extra instructions",
    "agent.disabled_tools": "Disabled tools", "agent.check_numbers": "Check the numbers of the answers",
    "usage.keep_days": "Keep the LLM calls (days)", "agent.launcher": "Open the chat with", "agent.executor": "Where answers run", "agent.celery_queue": "Celery queue",
    "learn.enabled": "Learn once a day", "learn.hour": "Daily at (hour)", "learn.days": "On these days",
    "learn.user": "Learn as user", "learn.profile_every_days": "Statistics refreshed every (days)",
    "learn.max_requests_per_minute": "Requests per minute (each database)", "learn.request_timeout": "Request timeout (s)",
    "learn.stop_after_errors": "Stop after failures in a row", "learn.stats_max_series": "Statistics up to (series)",
    "learn.series_sample": "Series sampled per metric", "learn.sample_docs": "Documents sampled per index",
    "learn.fields_per_request": "Field statistics per request", "learn.group_rollover": "Group dated / rolled-over indices",
    "learn.databases": "Databases", "learn.indices": "Only these indices", "learn.indices_exclude": "Never these indices",
    "learn.metrics": "Only these metrics", "learn.metrics_exclude": "Never these metrics",
    "learn.max_minutes": "Time limit (minutes)", "learn.max_objects": "Metrics or indices per database at most",
    "learn.profile_hours": "Statistics window (hours)", "learn.llm_descriptions": "LLM descriptions",
    "learn.history_days": "Keep the learning's history (days)",
    "backup.keep_days": "Remove backups older than (days)", "backup.upload_max_mb": "Largest backup file brought (MB)",
    "mcp.user": "User of the MCP server mode",
    "tools.export_dir": "Export directory", "tools.export_max_rows": "Excel rows at most",
    "tools.email_allowed_domains": "Allowed e-mail domains", "tools.keep_days": "Keep answer files (days)",
    "tools.max_file_mb": "Largest file kept (MB)", "agent.celery_queue": "Celery queue",
    "search.enabled": "Give the relevant knowledge with each question", "search.top_k": "Pieces of knowledge per question",
    "search.prompt_chars": "Characters of knowledge per question", "embed.model": "Embedding model",
    "embed.base_url": "Embedding API base", "embed.batch": "Texts per embedding request",
    "embed.per_run": "Pieces embedded per run", "embed.max_minutes": "Minutes per reading of the documents",
    "search.vector_store": "Vectors kept in",
    "qdrant.url": "Qdrant server", "qdrant.api_key": "Qdrant API key", "qdrant.collection": "Qdrant collection",
    "docs.allowed_domains": "Allowed domains for documents", "docs.max_kb": "Largest page or file (KB)",
    "memory.enabled": "Learn from the chats", "memory.team_approval": "Team memories need approval",
    "memory.prompt_chars": "Characters of memories per question", "chats.keep_days": "Keep chats (days, 0: always)",
    "agent.queue_keep_days": "Keep delivered queue messages (days, 0: always)",
    "context.enabled": "Context every night", "context.hour": "Context hour",
    "context.max_llm_calls": "LLM calls per Context build"
  };

  function status() {
    S.admin("GET", "status").then(function (s) {
      var box = $("status");
      box.innerHTML = "";
      [["supagent " + (s.version || "?") + " (tables v" + (s.schema_version || "?") + ")", !!s.schema_version],
       [s.executor === "thread" ? "answers run in the web server (agent.executor = thread)" :
        s.celery_workers ? "Celery workers answer" + (s.workers ? " (" + s.workers + ")" : "") :
        s.executor === "celery" ? "no Celery worker: questions wait for one (agent.executor = celery)" :
        "no Celery worker: answers run in the web server", !!s.celery_workers || s.executor === "thread"],
       [s.superset_mcp ? "Superset MCP tools (charts, dashboards)" : "Superset MCP service not installed: no chart saving", !!s.superset_mcp],
       [s.daily_tick_scheduled ? "daily learning in the beat schedule" : "daily learning not scheduled", !!s.daily_tick_scheduled]
      ].forEach(function (x) { box.appendChild(el("span", { class: x[1] ? "ok" : "no", text: x[0] })); });
      var last = s.last_scheduled_run ? new Date(String(s.last_scheduled_run).replace(" ", "T") + "Z") : null;
      var fresh = last && (Date.now() - last.getTime()) < 26 * 3600 * 1000;
      box.appendChild(el("span", { class: fresh ? "ok" : "no",
        text: last ? "last daily run " + S.when(s.last_scheduled_run) + " (" + s.last_scheduled_status + ")" +
                     (fresh ? "" : ": none in the last day, is Celery beat running?")
                   : "no daily run yet (Celery beat starts it at the chosen hour)" }));
    });
  }

  function input(spec) {
    var id = "s-" + spec.key.replace(/\./g, "-");
    var v = spec.value;
    var node;
    if (spec.kind === "bool") {
      node = el("input", { type: "checkbox", id: id });
      node.checked = !!v;
    } else if (spec.kind === "choice") {
      node = el("select", { id: id }, spec.choices.map(function (c) { return el("option", { value: c, text: c }); }));
      node.value = v;
    } else if (spec.secret) {
      node = el("input", { type: "password", id: id, autocomplete: "new-password",
                           placeholder: v ? "set — leave empty to keep it" : "not set" });
    } else if (spec.kind === "json" || spec.key === "agent.extra_instructions") {
      node = el("textarea", { id: id, rows: "3", spellcheck: "false" });
      node.value = spec.kind === "json" ? JSON.stringify(v || {}, null, 0) : (v || "");
    } else if (spec.kind === "int" || spec.kind === "float") {
      node = el("input", { type: "number", id: id, step: spec.kind === "float" ? "0.05" : "1" });
      node.value = v;
    } else {
      node = el("input", { type: "text", id: id });
      node.value = spec.kind === "list" ? (v || []).join(", ") : (v === null || v === undefined ? "" : v);
    }
    node.dataset.key = spec.key;
    return node;
  }

  /* (0.10.9.1) what the agent gives the LLM, per context profile: budget.short.<size>, budget.long.<size> */
  var SIZE_LABELS = {
    compact_at: "Cut older results from (prompt tokens)", search_chars: "Knowledge per question",
    piece_chars: "Each piece of knowledge", context_chars: "Each Context section", llm_context_chars: "LLM context",
    tool_chars: "A tool's result", describe_chars: "A description of the data", compare_chars: "A comparison of groups",
    history_chars: "Each earlier message", rules_near_chars: "The team's rules in full", rule_chars: "One rule",
    group_chars: "A comparison of logs", shrunk_first: "An older result after the first cut",
    shrunk_second: "An older result after the second cut"
  };
  LABELS["budget.long_from_tokens"] = "Big model's sizes from (tokens per request)";
  LABELS["budget.long_cut_share"] = "Big model: cut older results from (share of the window)";
  LABELS["budget.long_assumed_tokens"] = "Big model forced on an unknown window: window assumed (tokens)";

  function labelOf(key) {
    var m = /^budget\.(short|long)\.(.+)$/.exec(key);
    return LABELS[key] || (m && SIZE_LABELS[m[2]]) || key;
  }

  /* a setting: its name, an "i" with what it does (shown on demand), its box */
  function fieldRow(spec) {
    var inp = input(spec);
    var name = labelOf(spec.key);
    var label = el("label", { for: inp.id }, [document.createTextNode(name), el("span", { class: "key", text: spec.key })]);
    var head = el("span", { class: "field-head" }, [label, spec.help ? S.info(spec.help, name) : null]);
    if (spec.kind === "bool") {
      return el("div", { class: "field check", "data-key": spec.key }, [inp, head]);
    }
    return el("div", { class: "field", "data-key": spec.key }, [head, inp]);
  }

  /* only: the groups of the card just saved (0.11.0): the other cards keep what is typed in them and not saved yet */
  function renderSettings(list, budget, only) {
    specs = {};
    list.forEach(function (s) { specs[s.key] = s; });
    document.querySelectorAll(".fields[data-group]").forEach(function (box) {
      var groups = box.dataset.group.split(" "), pre = box.dataset.prefix || "";
      if (only && !groups.some(function (g) { return only.indexOf(g) >= 0; })) return;
      box.innerHTML = "";
      list.forEach(function (s) {
        if (groups.indexOf(s.key.split(".")[0]) >= 0 && s.key.indexOf(pre) === 0) box.appendChild(fieldRow(s));
      });
    });
    authVisibility();
    renderBudget(budget);
  }

  /* (0.10.9.1) the profile in use, the model's window, the estimate and its warnings; each size box shows its
     profile's own size in grey, and what is in use when a setting for both profiles decides it */
  function renderBudget(b) {
    var now = $("budget-now");
    if (!now || !b) return;
    now.innerHTML = "";
    var est = b.estimate || {};
    now.appendChild(document.createTextNode("In use: the " + (b.profile === "long" ? "big" : "small") + " model's sizes (" +
      b.profile + "); the model reads " + (b.window ? S.num(b.window) + " tokens per request" : "a number of tokens its server does not state") +
      "; an answer starts with about " + S.num(est.start_tokens || 0) + " tokens, of which " + S.num(est.instructions_tokens || 0) +
      " for the instructions and the tools (an estimate)."));
    (est.warnings || []).forEach(function (t) { now.appendChild(el("span", { class: "warn", text: " Warning: " + t + "." })); });
    ["short", "long"].forEach(function (p) {
      var head = $("budget-h-" + p);
      if (head) head.textContent = (p === "short" ? "Small model (short)" : "Big model (long)") + (p === b.profile ? ": in use" : "");
      (b.names || []).forEach(function (n) {
        var key = "budget." + p + "." + n;
        var node = document.querySelector('[data-key="' + key + '"]:not(.field)');
        var row = document.querySelector('.field[data-key="' + key + '"]');
        if (!node || !row) return;
        node.placeholder = S.num(b.defaults[p][n]);
        var from = b.set[p][n], said = row.querySelector(".in-use");
        if (said) said.remove();                         // (0.11.0) a card not drawn again: said once
        if (from && from !== key) row.appendChild(el("span", { class: "in-use", text: "in use: " + S.num(b.sizes[p][n]) + " (set in " + from + ")" }));
      });
    });
  }

  function authVisibility() {
    var mode = ($("s-llm-auth") || {}).value;
    document.querySelectorAll('.field[data-key^="llm.middleware."]').forEach(function (f) { f.hidden = mode !== "middleware"; });
    var tok = document.querySelector('.field[data-key="llm.token"]');
    if (tok) tok.hidden = mode !== "token";
  }

  function values(groups) {
    var out = {};
    Object.keys(specs).forEach(function (k) {
      if (groups.indexOf(k.split(".")[0]) < 0) return;
      var node = document.querySelector('[data-key="' + k + '"]:not(.field)');
      if (!node) return;
      var spec = specs[k];
      var v;
      if (spec.kind === "bool") v = node.checked;
      else if (spec.kind === "list") v = node.value.split(",").map(function (x) { return x.trim(); }).filter(Boolean);
      else if (spec.kind === "json") { try { v = JSON.parse(node.value || "{}"); } catch (e) { v = node.value; } }
      else v = node.value;
      if (spec.secret && !v) return;
      if (!spec.secret && (spec.value === null || spec.value === undefined) && v === "") return;   // empty left empty
      if (!spec.secret && JSON.stringify(v) === JSON.stringify(spec.kind === "int" || spec.kind === "float" ? String(spec.value) : spec.value)) return;
      out[k] = v;
    });
    return out;
  }

  function loadSettings() { return S.admin("GET", "settings").then(function (d) { renderSettings(d.settings || [], d.budget); }); }

  var STEP_WORDS = { listed: "listed", "new": "new", due: "due", profiled: "profiled", not_due: "not due", metrics: "metrics",
    indices: "indices", labels: "labels", fields: "fields", families: "families", requests: "requests", errors: "errors",
    history: "history done", history_pending: "history left", gone: "gone", written: "written by the LLM",
    copied: "copied from the same name", tokens: "LLM tokens", left: "left", same_values: "relations",
    categories: "categories", added: "added", changed: "changed", removed: "removed", unchanged: "unchanged",
    "sync.added": "search pieces added", "sync.changed": "search pieces changed", "sync.removed": "search pieces removed",
    "sync.unchanged": "search pieces unchanged", "embed.embedded": "embedded", "embed.left": "left to embed",
    answers: "Helpful answers checked", hit_at_1: "share found first", hit_at_3: "share found in the first 3",
    mrr: "mean reciprocal rank", curated: "catalog descriptions", relations: "catalog relations",
    "documents.documents_read": "documents read", "documents.refused": "definitions refused",
    values_read: "values read", fields_read: "fields and labels read", proposed: "proposed (To review)",
    to_classify: "to classify", calls: "LLM calls", items: "items", tags: "categories given", links: "relations",
    values: "values", texts: "texts read", subject: "subjects", application: "applications", component: "components" };
  var STEP_SKIP = ["step", "at", "database", "seconds", "phase", "fallbacks", "changes", "interrupted", "last_error",
    "complete", "error", "stopped"];
  function stepText(x) {
    var bits = [];
    Object.keys(x).forEach(function (k) {
      var v = x[k];
      if (STEP_SKIP.indexOf(k) >= 0 || v === null || v === undefined || typeof v === "object" || v === 0) return;
      bits.push((typeof v === "number" ? S.num(v) : String(v)) + " " + (STEP_WORDS[k] || k.replace(/_/g, " ")));
    });
    Object.keys(x.fallbacks || {}).forEach(function (k) {
      var f = x.fallbacks[k];
      bits.push(k + ": " + S.num(f.batches) + " batches read one metric at a time (" + f.first_error + ")");
    });
    if (x.changes && Object.keys(x.changes).length) bits.push("changes: " + Object.keys(x.changes).map(function (k) {
      return S.num(x.changes[k]) + " " + k; }).join(", "));
    ["error", "stopped", "last_error", "interrupted"].forEach(function (k) { if (x[k]) bits.push(k.replace("_", " ") + ": " + x[k]); });
    return bits.join(", ");
  }
  var openSteps = {};                                  // runs whose steps are shown (kept across refreshes)
  function stepsBox(r) {
    var steps = (r.stats || {}).steps || [];
    if (!steps.length) return null;
    var box = el("details", { class: "steps", open: openSteps[r.id] ? "open" : null,
      ontoggle: function () { openSteps[r.id] = box.open; } }, [el("summary", { text: "steps (" + steps.length + ")" })]);
    var list = el("ol", {});
    steps.forEach(function (x) {
      var when = x.at ? new Date(x.at + "Z").toLocaleTimeString() : "";
      var took = x.seconds !== undefined ? S.num(Math.round(x.seconds)) + " s" : "running" + (x.phase ? " (" + x.phase + ")" : "");
      list.appendChild(el("li", { text: [when, x.step + (x.database ? ": " + x.database : ""), took, stepText(x)]
        .filter(Boolean).join(" · ") }));
    });
    box.appendChild(list);
    return box;
  }

  var runsPage = { page: 0, size: 15, total: 0 };
  function runs() {
    return S.admin("GET", "runs?page=" + runsPage.page + "&size=" + runsPage.size).then(function (d) {
      runsPage.total = d.total || 0;
      S.pager($("runs-pager"), runsPage, runs);
      var tb = $("runs").querySelector("tbody");
      tb.innerHTML = "";
      var running = false;
      (d.runs || []).forEach(function (r) {
        var st = r.stats || {};
        var secs = st.seconds !== undefined ? Math.round(st.seconds) + " s" : "";
        var parts = [];
        Object.keys(st.databases || {}).forEach(function (name) {
          var x = st.databases[name];
          var bits = [];
          ["metrics", "labels", "indices", "fields"].forEach(function (k) { if (x[k]) bits.push(S.num(x[k]) + " " + k); });
          if (x.due) bits.push(S.num(x.profiled || 0) + " of " + S.num(x.due) + " due today profiled");
          if (x.complete === false) bits.push("stopped at its share of the time (learn.max_minutes): the next run continues");
          if (x.history_pending) bits.push(S.num(x.history_pending) + " history lookups left for the next runs");
          if (x.skipped_unchanged) bits.push(S.num(x.skipped_unchanged) + " unchanged today");
          if (x.error) bits.push("error: " + x.error);
          if (x.llm && (x.llm.written || x.llm.left)) bits.push(S.num(x.llm.written || 0) + " AI descriptions" + (x.llm.left ? " (" + S.num(x.llm.left) + " left)" : ""));
          parts.push(name + ": " + (bits.join(", ") || "nothing"));
        });
        if (st.now && (r.status === "running" || r.status === "stopping")) {       // the run in progress
          var next = (st.plan || []).filter(function (n) { return n !== st.now && !(st.databases || {})[n]; });
          var cur = (st.steps || []).filter(function (x) { return x.seconds === undefined; })[0];
          var doing = cur ? " (" + (cur.phase || cur.step) + (stepText(cur) ? ": " + stepText(cur) : "") + ")" : "";
          parts.unshift("now: " + st.now + doing + (next.length ? "; next: " + next.join(", ") : ""));
        }
        if (r.progress) parts.push("so far: " + S.num(r.progress.new_objects) + " new objects");
        if (st.during) parts.push("AI descriptions while reading: " + S.num(st.during.written) + " written by the LLM in " +
          S.num(st.during.requests) + " calls (" + S.num(st.during.tokens) + " tokens), " + S.num(st.during.copied) +
          " copied from the same name");
        Object.keys(st.skipped || {}).forEach(function (name) { parts.push(name + ": not learned: " + st.skipped[name]); });
        if (r.kind === "classify") {                         // a classification run: what it read, what it proposed
          var cl = st.classified || {}, seed = cl.seeded || {};
          if (seed.values_read) parts.push(S.num(seed.values_read) + " values read in the data (" + S.num(seed.fields_read || 0) + " fields and labels)");
          if (seed.proposed) parts.push(S.num(seed.proposed) + " new value" + (seed.proposed > 1 ? "s wait" : " waits") + " in To review");
          if (cl.items) parts.push(S.num(cl.items) + " items classified in " + S.num(cl.calls || 0) + " LLM calls: " + S.num(cl.tags || 0) +
            " categories given, " + S.num(cl.proposed || 0) + " values proposed, " + S.num(cl.links || 0) + " relations");
          else if (!cl.error) parts.push("no item changed");
          if (cl.left) parts.push(S.num(cl.left) + " items left (the next run goes on)");
          if (cl.error) parts.push("error: " + cl.error);
          var inter = st.interactions;
          if (inter && (inter.texts || inter.proposed || inter.error)) parts.push("interactions: " + S.num(inter.texts || 0) + " texts read, " +
            S.num(inter.proposed || 0) + " proposed" + (inter.error ? " (" + inter.error + ")" : ""));
        }
        if (r.kind === "backup" && st.name) parts.push("file " + st.name + (st.bytes ? " (" + (S.bytes ? S.bytes(st.bytes) : S.num(st.bytes)) + ")" : "") +
          ((st.removed || []).length ? " · " + st.removed.length + " older removed" : ""));
        if (r.kind === "restore" && st.name) parts.push("of " + st.name + (st.saved_first ? " · the present state saved first in " + st.saved_first : "") +
          (st.error ? " · " + st.error : ""));
        if (st.llm_use) parts.push("LLM: " + S.num(st.llm_use.calls) + " calls, " + S.num((st.llm_use.prompt_tokens || 0) + (st.llm_use.completion_tokens || 0)) +
          " tokens, " + S.num(Math.round(st.llm_use.seconds || 0)) + " s" + (st.llm_use.failed ? ", " + S.num(st.llm_use.failed) + " failed" : ""));
        if (st.relations) parts.push("relations: " + (st.relations.same_values || 0) + " measured");
        if (st.llm) parts.push("AI descriptions: " + (st.llm.written || 0) + (st.llm.left ? ", " + st.llm.left +
          " left (the next run goes on)" : "") + (st.llm.error ? " (" + st.llm.error + ")" : ""));
        if (r.error && !/^stop asked at /.test(r.error)) parts.push(r.error);
        if (r.status === "running" || r.status === "stopping") running = true;
        tb.appendChild(el("tr", {}, [el("td", { text: "#" + r.id }), el("td", { text: (r.kind && r.kind !== "learn" ? r.kind + " · " : "") + r.reason }), el("td", { text: S.when(r.started_at) }),
          el("td", { text: secs }), el("td", { html: '<span class="badge ' + (r.status === "done" ? "ok" : r.status === "error" ? "bad" : "") + '">' + S.esc(r.status === "stopping" ? "stopping…" : r.status) + "</span>" }),
          el("td", { class: "num", text: S.num(r.changes) }), el("td", {}, [el("span", { text: parts.join(" · ") }), stepsBox(r)])]));
      });
      if (!(d.runs || []).length) tb.appendChild(el("tr", {}, [el("td", { colspan: "7", class: "muted", text: "No learning run yet." })]));
      running = running || !!d.running;                    // on another page too
      $("learn-stop").hidden = !running;                   // Stop while a run is running
      clearTimeout(runsTimer);                             // (0.11.0) one reading every 5 s, however many clicks asked
      runsTimer = running ? setTimeout(runs, 5000) : null;
    });
  }
  var runsTimer = null;

  document.addEventListener("change", function (ev) { if (ev.target && ev.target.id === "s-llm-auth") authVisibility(); });
  document.querySelectorAll("[data-save]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var groups = btn.dataset.save.split(" ");
      var payload = values(groups);
      var res = btn.parentNode.querySelector(".result") || btn.parentNode.appendChild(el("span", { class: "result" }));
      if (!Object.keys(payload).length) { res.textContent = "nothing changed"; res.className = "result"; return; }
      btn.disabled = true;
      S.admin("POST", "settings", { settings: payload }).then(function (r) {
        btn.disabled = false;
        // (0.11.0) refused or not answered (signed out, the CSRF token, the server, the network): nothing was saved
        if (r.error && !r.errors) { res.textContent = "not saved: " + r.error; res.className = "result bad"; return; }
        var errs = Object.keys(r.errors || {}).map(function (k) { return k + ": " + r.errors[k]; });
        res.textContent = errs.length ? errs.join("; ") : "saved " + (r.saved || []).length + " setting(s)";
        res.className = "result " + (errs.length ? "bad" : "good");
        if (r.settings) renderSettings(r.settings, r.budget, groups);   // (0.11.0) this card only
      });
    });
  });
  /* (0.10.11) Grafana's MCP server and OpenSearch Dashboards, tested with the settings saved */
  document.querySelectorAll("[data-test-source]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var source = btn.dataset.testSource, res = $(source + "-result");
      res.textContent = "testing…";
      res.className = "result";
      S.admin("POST", "test-source/" + source, {}).then(function (r) {
        res.textContent = (r.ok ? "OK: " : "") + (r.said || r.error || "failed");
        res.className = "result " + (r.ok ? "good" : "bad");
      });
    });
  });
  $("test-llm").addEventListener("click", function () {
    var res = $("llm-result");
    res.textContent = "asking the LLM…";
    res.className = "result";
    S.admin("POST", "test-llm", {}).then(function (r) {
      if (r.ok) {
        res.textContent = "OK: model " + r.model + (r.token ? ", middleware token " + r.token : "") + ", answer “" + r.answer + "” in " + r.seconds + " s";
        res.className = "result good";
        var said = (r.profile && r.profile.said) || [];       // (0.10.7) what supagent adapts to this LLM
        if (said.length) {
          res.appendChild(el("div", { class: "muted", text: "Adapted to this LLM:" }));
          res.appendChild(el("ul", { class: "llm-profile" }, said.map(function (t) { return el("li", { text: t }); })));
        }
      } else {
        res.textContent = r.error || "failed";
        res.className = "result bad";
      }
    });
  });
  $("learn-now").addEventListener("click", function () {
    var res = $("learn-result");
    S.admin("POST", "learn", {}).then(function (r) {
      res.textContent = r.error || "started (" + r.started + ")";
      res.className = "result " + (r.error ? "bad" : "good");
      setTimeout(runs, 1500);
    });
  });
  $("classify-now").addEventListener("click", function () {
    var res = $("learn-result");
    S.admin("POST", "classify", {}).then(function (r) {
      res.textContent = r.error || "classification started (" + r.started + "): it is listed below with its steps";
      res.className = "result " + (r.error ? "bad" : "good");
      setTimeout(runs, 1500);
    });
  });
  $("learn-stop").addEventListener("click", function () {
    var res = $("learn-result"), btn = $("learn-stop");
    btn.disabled = true;
    S.admin("POST", "learn/stop", {}).then(function (r) {
      btn.disabled = false;
      res.textContent = r.error || "run #" + r.stopped + " stopped: it keeps what it learned; Learn now starts a new one";
      res.className = "result " + (r.error ? "bad" : "good");
      setTimeout(runs, 1000);
    });
  });
  // ---------------------------------------------------------------- the backups of the knowledge
  var PART_WORDS = { categories: "categories and System map", catalog: "catalog", memory: "memory", documents: "documents",
    notes: "notes", context: "Context", learned: "learned answers and paths", dictionary: "descriptions of the data",
    settings: "settings", vectors: "vectors" };
  var listed = [];        /* (0.11.0) the backups listed: the Restore panel's choices */
  function backups() {
    return S.admin("GET", "backups").then(function (d) {
      var tb = $("backups").querySelector("tbody");
      tb.innerHTML = "";
      listed = (d.backups || []).filter(function (b) { return !b.error; });
      fillRestore();
      $("backup-dir").textContent = d.error ? "The directory " + d.directory + " cannot be read: " + d.error :
        "Written on this server in " + d.directory;
      (d.backups || []).forEach(function (b) {
        var parts = Object.keys(b.parts || {});
        var holds = parts.map(function (p) { return (PART_WORDS[p] || p) + " " + S.num(b.parts[p]); }).join(" · ");
        var acts = el("td", { class: "row-actions" });
        var panel = el("tr", { class: "backup-restore", hidden: "hidden" });
        if (!b.error) {
          acts.appendChild(el("a", { class: "linkish", href: document.body.dataset.adminApi + "backups/" + encodeURIComponent(b.name),
                                     download: b.name, text: "Download" }));
          acts.appendChild(el("button", { type: "button", class: "linkish", text: "Restore…", "aria-expanded": "false", onclick: function (ev) {
            panel.hidden = !panel.hidden;
            ev.currentTarget.setAttribute("aria-expanded", String(!panel.hidden));
          } }));
          var boxes = parts.map(function (p) {
            var cb = el("input", { type: "checkbox", value: p });
            return el("label", { class: "backup-part" }, [cb, document.createTextNode(" " + (PART_WORDS[p] || p) + " (" + S.num(b.parts[p]) + ")")]);
          });
          var res = el("span", { class: "result", role: "status" });
          var go = el("button", { type: "button", class: "btn small primary", text: "Restore the parts chosen", onclick: function () {
            var chosen = boxes.map(function (l) { return l.firstChild; }).filter(function (c) { return c.checked; }).map(function (c) { return c.value; });
            if (!chosen.length) { res.textContent = "choose the parts to put back"; res.className = "result bad"; return; }
            S.confirm(go, "Put back " + chosen.map(function (p) { return PART_WORDS[p] || p; }).join(", ") + " as of " + S.when(b.created_at) + "?",
              { yes: "Restore", no: "Cancel", detail: "The present " + (chosen.length > 1 ? "parts are" : "part is") +
                " replaced by the backup's. The present state is saved first in a backup of its own: a restore can be undone." }).then(function (ok) {
              if (!ok) return;
              go.disabled = true;
              S.admin("POST", "backups/" + encodeURIComponent(b.name) + "/restore", { parts: chosen }).then(function (r) {
                go.disabled = false;
                res.textContent = r.error || "restore started: it is listed with the runs (Daily learning)";
                res.className = "result " + (r.error ? "bad" : "good");
                setTimeout(function () { runs(); backups(); }, 2500);
              });
            });
          } });
          panel.appendChild(el("td", { colspan: "6" }, [el("div", { class: "backup-parts" }, boxes), el("div", { class: "actions" }, [go, res])]));
        }
        tb.appendChild(el("tr", {}, [el("td", { text: b.name }), el("td", { text: S.when(b.created_at) }),
          el("td", { class: "num", text: S.bytes ? S.bytes(b.bytes) : S.num(b.bytes) }),
          el("td", { class: "muted", text: (b.reason || "") + (b.by ? " · " + b.by : "") }),
          el("td", { class: "muted", text: b.error || holds }), acts]));
        tb.appendChild(panel);
      });
      if (!(d.backups || []).length) tb.appendChild(el("tr", {}, [el("td", { colspan: "6", class: "muted",
        text: "No backup on this server yet: the daily one is made at the hour above (by the workers' beat), or Back up now." })]));
    });
  }
  /* (0.11.0) Restore…: a backup of this server, or a file brought from elsewhere, then the parts to put back */
  function fillRestore(chosen) {
    var sel = $("restore-name");
    if (!sel) return;
    var keep = chosen || sel.value;
    sel.innerHTML = "";
    listed.forEach(function (b) {
      sel.appendChild(el("option", { value: b.name, text: S.when(b.created_at) + " · " + b.name + (b.reason ? " (" + b.reason + ")" : "") }));
    });
    if (!listed.length) sel.appendChild(el("option", { value: "", text: "no backup on this server yet" }));
    if (keep && listed.some(function (b) { return b.name === keep; })) sel.value = keep;
    restoreParts();
  }
  function restoreParts() {
    var box = $("restore-parts"), b = listed.filter(function (x) { return x.name === $("restore-name").value; })[0];
    box.innerHTML = "";
    if (!b) return;
    Object.keys(b.parts || {}).forEach(function (p) {
      box.appendChild(el("label", { class: "backup-part" }, [el("input", { type: "checkbox", value: p }),
        document.createTextNode(" " + (PART_WORDS[p] || p) + " (" + S.num(b.parts[p]) + ")")]));
    });
  }
  $("restore-open").addEventListener("click", function () {
    var panel = $("restore-panel");
    panel.hidden = !panel.hidden;
    this.setAttribute("aria-expanded", String(!panel.hidden));
    if (!panel.hidden) fillRestore();
  });
  $("restore-name").addEventListener("change", restoreParts);
  $("restore-upload").addEventListener("click", function () {
    var input = $("restore-file"), res = $("restore-result"), btn = this;
    if (!input.files || !input.files.length) { res.textContent = "choose a backup file first"; res.className = "result bad"; return; }
    var form = new FormData();
    form.append("file", input.files[0]);
    btn.disabled = true;
    res.textContent = "sending " + input.files[0].name + "…"; res.className = "result";
    fetch(document.body.dataset.adminApi + "backups/upload", { method: "POST", credentials: "same-origin", body: form,
      headers: { "Accept": "application/json", "X-CSRFToken": (document.querySelector('meta[name="csrf-token"]') || {}).content || "" } })
      .then(function (r) { return r.json().catch(function () { return { error: "HTTP " + r.status }; }); },
            function (e) { return { error: "network error: " + e }; })
      .then(function (r) {
        btn.disabled = false;
        if (r.error) { res.textContent = r.error; res.className = "result bad"; return; }
        input.value = "";
        res.textContent = "kept as " + r.saved.name + ": choose the parts to put back"; res.className = "result good";
        backups().then(function () { fillRestore(r.saved.name); });
      });
  });
  $("restore-go").addEventListener("click", function () {
    var go = this, res = $("restore-result"), name = $("restore-name").value;
    var b = listed.filter(function (x) { return x.name === name; })[0];
    var chosen = Array.prototype.slice.call(document.querySelectorAll("#restore-parts input:checked")).map(function (c) { return c.value; });
    if (!b) { res.textContent = "choose a backup"; res.className = "result bad"; return; }
    if (!chosen.length) { res.textContent = "choose the parts to put back"; res.className = "result bad"; return; }
    S.confirm(go, "Put back " + chosen.map(function (p) { return PART_WORDS[p] || p; }).join(", ") + " as of " + S.when(b.created_at) + "?",
      { yes: "Restore", no: "Cancel", detail: "The present " + (chosen.length > 1 ? "parts are" : "part is") +
        " replaced by the backup's. The present state is saved first in a backup of its own: a restore can be undone." }).then(function (ok) {
      if (!ok) return;
      go.disabled = true;
      S.admin("POST", "backups/" + encodeURIComponent(name) + "/restore", { parts: chosen }).then(function (r) {
        go.disabled = false;
        res.textContent = r.error || "restore started: it is listed with the runs (Daily learning)";
        res.className = "result " + (r.error ? "bad" : "good");
        setTimeout(function () { runs(); backups(); }, 2500);
      });
    });
  });
  $("backup-now").addEventListener("click", function () {
    var res = $("backup-result");
    S.admin("POST", "backups", {}).then(function (r) {
      res.textContent = r.error || "backup started: it is listed below in a moment, and with the runs";
      res.className = "result " + (r.error ? "bad" : "good");
      setTimeout(function () { runs(); backups(); }, 2500);
    });
  });
  backups();
  // ---------------------------------------------------------------- the knowledge: in the Data dictionary
  var dictUrl = document.body.dataset.dictionaryUrl || "";
  [["go-review", "review"], ["go-catalog", "catalog"], ["go-memory", "memory"], ["go-docs", "docs"]].forEach(function (x) {
    $(x[0]).href = dictUrl + "#" + x[1];
  });
  S.admin("GET", "review?limit=1").then(function (d) {
    if (d.waiting) $("go-review").textContent = "What waits for review (" + S.num(d.waiting) + ")";
  });
  status();
  loadSettings();
  runs();
})();
