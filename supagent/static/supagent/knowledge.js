/* supagent data dictionary: what the team gives the agent and what waits for an admin. The review (To review),
   the catalog, the team memory, the documents and sites, the categories; for admins with their actions, for the
   others read only. A save answers at once; the agent's search follows in the background: the line next to the
   tabs says when it is up to date. */
(function () {
  "use strict";
  var S = window.supagent, el = S.el, D = S.dictionary;
  var $ = function (id) { return document.getElementById(id); };
  var admin = S.canEdit, canDelete = S.canDelete;   // an editor writes; deleting is an admin's (0.9.6)
  // (0.10.6) the kinds of a link of the System map, as people say them (To review's corrections, the Categories page)
  var LINK_KINDS = [["part_of", "belongs to"], ["runs_on", "runs on"], ["calls", "calls, connects to"],
                    ["depends_on", "relies on, depends on"], ["reads_from", "reads from"], ["sends_to", "sends data to"],
                    ["monitors", "monitors"], ["triggers", "triggers, starts"], ["about", "is related to"]];
  if (!D) return;

  function result(node, r, good) {
    node.textContent = r && r.error ? r.error : good;
    node.className = "result " + (r && r.error ? "bad" : "good");
  }
  function badge(text, cls) { return el("span", { class: "badge" + (cls ? " " + cls : ""), text: text }); }
  /* what cannot be undone: confirmed in a small card next to the button (common.js) */
  function sureButton(label, fn, ask, detail, yes) {
    return S.sureButton(label, fn, { ask: ask || label + "?", detail: detail, yes: yes || label });
  }
  /* a card's panel (Part of…, Merge into…, Rename, Change…, Edit): its button opens it, the same button closes it;
     one panel open at a time on a card */
  function panelToggle(btn, cls, build) {
    var c = btn.closest(".rcard"), body = c.querySelector(".rbody");
    var open = body.querySelector(".rpanel." + cls);
    c.querySelectorAll(".rpanel").forEach(function (x) { if (x._close) x._close(); x.remove(); });
    c.querySelectorAll("button[aria-expanded]").forEach(function (b) { b.setAttribute("aria-expanded", "false"); b.classList.remove("on"); });
    if (open) return;                                       // it was open: closed now
    var panel = build(c);
    if (!panel) return;
    panel.classList.add("rpanel", cls);
    body.appendChild(panel);
    btn.setAttribute("aria-expanded", "true");
    btn.classList.add("on");
    var first = panel.querySelector("input, select, textarea");
    if (first) first.focus();
  }
  function toggleButton(label, cls, build) {
    return el("button", { type: "button", class: "btn small", text: label, "aria-expanded": "false",
      onclick: function (ev) { panelToggle(ev.currentTarget, cls, build); } });
  }

  // ------------------------------------------------------------------ the agent's search after a save
  var applyBox = $("apply-state"), applyTimer = null, applyUntil = 0;
  function applyShow(cls, text) {
    applyBox.hidden = false;
    applyBox.className = "apply-state " + cls;
    applyBox.textContent = text;
  }
  function pollApply() {
    S.admin("GET", "apply").then(function (st) {
      clearTimeout(applyTimer);
      if (st.error && st._status) { applyBox.hidden = true; return; }
      if (st.pending && !st.stale && Date.now() < applyUntil) {
        applyShow("busy", "Saved · updating the agent’s search…");
        applyTimer = setTimeout(pollApply, 1000);
        return;
      }
      if (st.pending) {
        applyShow("warn", "Still updating the agent’s search; if the server restarted, the hourly indexing catches up");
        return;
      }
      if (st.error) {
        applyShow("warn", "Saved, but the agent’s search was not updated (" + st.error + "); the hourly indexing catches up");
        return;
      }
      applyShow("ok", "Saved · the agent’s search is up to date");
      applyTimer = setTimeout(function () { applyBox.hidden = true; }, 6000);
    });
  }
  function saved() {
    if (!admin) return;
    applyUntil = Date.now() + 120000;
    applyShow("busy", "Saved · updating the agent’s search…");
    clearTimeout(applyTimer);
    applyTimer = setTimeout(pollApply, 600);
  }
  D.saved = saved;
  if (admin) {
    S.admin("GET", "apply").then(function (st) { if (st.pending && !st.error) { applyUntil = Date.now() + 120000; pollApply(); } });
  }

  // ------------------------------------------------------------------ To review (admins)
  var counts = {};
  var WAITING = ["memory", "recipes", "values", "relations", "tags", "links", "removals", "retire", "context", "warnings",
                 "fields", "grafana"];                  // (0.11.0) the groups in the server's "waiting" (views._review)
  function setWaiting(n) {
    var c = $("review-count");
    c.textContent = n > 999 ? "999+" : String(n);
    c.hidden = !n;
  }
  D.reviewWaiting = function () {
    return S.admin("GET", "review?limit=1").then(function (d) { setWaiting(d.waiting || 0); return d.waiting || 0; });
  };

  function card(main, meta, actions) {
    var acts = el("div", { class: "ractions" }, actions);
    var c = el("div", { class: "rcard" }, [el("div", { class: "rbody" }, main.concat([meta ? el("div", { class: "rmeta", text: meta }) : null])), acts]);
    c._acts = acts;
    return c;
  }
  /* an action on a card: the card shows what was done; the counts follow */
  function act(label, cls, group, fn) {
    return el("button", { type: "button", class: "btn small" + (cls ? " " + cls : ""), text: label, onclick: function () {
      var c = this.closest(".rcard"), buttons = c.querySelectorAll("button");
      buttons.forEach(function (b) { b.disabled = true; });
      Promise.resolve(fn(c)).then(function (r) {
        if (r && r.error) {
          buttons.forEach(function (b) { b.disabled = false; });
          var err = c.querySelector(".rerr") || c.querySelector(".rbody").appendChild(el("div", { class: "rerr result bad" }));
          err.textContent = r.error;
          return;
        }
        if (r && r.keep) { buttons.forEach(function (b) { b.disabled = false; }); return; }
        c.classList.add("done");
        c._acts.innerHTML = "";
        c._acts.appendChild(el("span", { class: "rdone", text: (r && r.done) || "done" }));
        done(group);
        leave(c, group, r && r.reload);
      });
    } });
  }
  /* a decided card leaves the list at once (what was done shows the time of a fade); a group emptied while more
     wait is filled again; after a merge everything is read again (the other values' counts changed) */
  function leave(c, group, reload) {
    c.classList.add("leaving");
    setTimeout(function () {
      var list = c.parentNode;
      c.remove();
      var left = list ? list.querySelectorAll(".rcard:not(.done)").length : 0;
      if (reload || (!left && (counts[group] || 0) > 0)) { reviewLoad(); return; }
      if (!left) { var sec = $("rg-" + group); if (sec) sec.remove(); }
    }, 450);
  }
  function done(group, n) {                    // n items of a group were decided: the counts follow
    counts[group] = Math.max(0, (counts[group] || 0) - (n === undefined ? 1 : n));
    var c = $("rg-count-" + group);
    if (c) c.textContent = S.num(counts[group]);
    // (0.11.0) every group the server counts as waiting (its "waiting"), not six of them: the badge never drops too low
    var waiting = WAITING.reduce(function (s, k) { return s + (counts[k] || 0); }, 0);
    setWaiting(waiting);
    summaryLine(waiting);
    saved();
  }

  /* a page's old and new versions, line by line (0.9.6, the user's request): side by side, the old on the left in red
     where it goes, the new on the right in green where it comes, the words that changed marked; in one column on a
     narrow screen or on demand; long unchanged stretches folded. rows: the server's diff (knowledge.context). */
  var DIFF_CONTEXT = 2, DIFF_FOLD = 6;
  function diffView(rows, labels) {
    var box = el("div", { class: "diff" });
    var wide = window.matchMedia ? !window.matchMedia("(max-width: 760px)").matches : true;
    var mode = wide ? "split" : "unified";
    var bar = el("div", { class: "diff-bar" });
    var counts = { add: 0, del: 0, mod: 0 };
    rows.forEach(function (r) { if (counts[r.op] !== undefined) counts[r.op]++; });
    bar.appendChild(el("span", { class: "diff-sum" }, [
      el("span", { class: "diff-n add", text: "+" + (counts.add + counts.mod) }), " ",
      el("span", { class: "diff-n del", text: "\u2212" + (counts.del + counts.mod) }),
      " lines" + (counts.mod ? " (" + counts.mod + " changed in place)" : "")]));
    var toggle = el("button", { type: "button", class: "btn small", text: "", onclick: function () {
      mode = mode === "split" ? "unified" : "split"; draw(); } });
    bar.appendChild(toggle);
    box.appendChild(bar);
    var holder = el("div", { class: "diff-scroll" });
    box.appendChild(holder);
    function parts(list, cls) {
      return (list || []).map(function (pt) {
        return pt[0] === "eq" ? document.createTextNode(pt[1]) : el("span", { class: cls, text: pt[1] });
      });
    }
    function cell(r, side) {                  // the text of one side of a row, its changed words marked
      if (r.op === "mod") return parts(side === "old" ? r.old_parts : r.new_parts, side === "old" ? "w-del" : "w-add");
      var t = side === "old" ? r.old : r.new;
      return t === null || t === undefined ? [] : [document.createTextNode(t === "" ? " " : t)];
    }
    function shown() {                         // the rows to draw: unchanged runs folded, but around each change
      var keep = rows.map(function () { return false; });
      rows.forEach(function (r, i) {
        if (r.op === "same") return;
        for (var k = Math.max(0, i - DIFF_CONTEXT); k <= Math.min(rows.length - 1, i + DIFF_CONTEXT); k++) keep[k] = true;
      });
      var out = [], i = 0;
      while (i < rows.length) {
        if (keep[i] || rows[i].op !== "same") { out.push(rows[i]); i++; continue; }
        var j = i;
        while (j < rows.length && !keep[j]) j++;
        if (j - i < DIFF_FOLD) { for (var k = i; k < j; k++) out.push(rows[k]); }
        else out.push({ fold: rows.slice(i, j) });
        i = j;
      }
      return out;
    }
    function draw() {
      toggle.textContent = mode === "split" ? "One column" : "Side by side";
      holder.innerHTML = "";
      var table = el("table", { class: "diff-table " + mode });
      if (mode === "split") table.appendChild(el("thead", {}, [el("tr", {}, [
        el("th", { class: "ln" }), el("th", { text: labels[0] }), el("th", { class: "ln" }), el("th", { text: labels[1] })])]));
      var body = el("tbody");
      shown().forEach(function (r) {
        if (r.fold) {
          var tr = el("tr", { class: "d-fold" }, [el("td", { colspan: mode === "split" ? "4" : "3" }, [
            el("button", { type: "button", class: "linkish", text: "\u22ef " + r.fold.length + " unchanged lines", onclick: function () {
              var frag = document.createDocumentFragment();
              r.fold.forEach(function (x) { frag.appendChild(line(x)[0]); });
              tr.replaceWith(frag);
            } })])]);
          body.appendChild(tr);
          return;
        }
        line(r).forEach(function (tr) { body.appendChild(tr); });
      });
      table.appendChild(body);
      holder.appendChild(table);
    }
    function line(r) {
      if (mode === "split") {
        return [el("tr", { class: "d-" + r.op }, [
          el("td", { class: "ln", text: r.o || "" }),
          el("td", { class: "code old" + (r.op === "del" || r.op === "mod" ? " gone" : "") }, cell(r, "old")),
          el("td", { class: "ln", text: r.n || "" }),
          el("td", { class: "code new" + (r.op === "add" || r.op === "mod" ? " come" : "") }, cell(r, "new"))])];
      }
      var out = [];                             // one column: the old line (−) then the new one (+)
      if (r.op === "same") out.push(el("tr", { class: "d-same" }, [el("td", { class: "ln", text: r.n || "" }),
        el("td", { class: "sign", text: " " }), el("td", { class: "code" }, cell(r, "new"))]));
      if (r.op === "del" || r.op === "mod") out.push(el("tr", { class: "d-del" }, [el("td", { class: "ln", text: r.o || "" }),
        el("td", { class: "sign", text: "\u2212" }), el("td", { class: "code gone" }, cell(r, "old"))]));
      if (r.op === "add" || r.op === "mod") out.push(el("tr", { class: "d-add" }, [el("td", { class: "ln", text: r.n || "" }),
        el("td", { class: "sign", text: "+" }), el("td", { class: "code come" }, cell(r, "new"))]));
      return out;
    }
    draw();
    box._update = function (newRows) { rows = newRows; draw(); };
    return box;
  }

  function recipeSummary(r) {              // what the agent (or a person) kept of a Helpful answer
    if (!(r.title || r.description || (r.how || []).length)) return null;
    var box = el("div", { class: "recipe-summary" });
    if (r.title) box.appendChild(el("div", { class: "rs-title", text: r.title }));
    if (r.description) box.appendChild(el("div", { class: "rs-desc", text: r.description }));
    if ((r.how || []).length) {
      box.appendChild(el("div", { class: "ctx-diff-h", text: "Steps" }));
      box.appendChild(el("ol", { class: "rs-steps" }, r.how.map(function (x) { return el("li", { text: x }); })));
    }
    if ((r.tasks || []).length) {
      box.appendChild(el("div", { class: "ctx-diff-h", text: "Checks each time" }));
      box.appendChild(el("ul", { class: "rs-tasks" }, r.tasks.map(function (x) { return el("li", { text: x }); })));
    }
    box.appendChild(el("div", { class: "muted small", text: r.summary_by && r.summary_by !== "agent" ?
      "written by " + r.summary_by : "written by the agent from the whole discussion: correct it with Edit" }));
    return box;
  }

  var GROUPS = [
    ["memory", "Team memory proposed from the chats", "Used for everyone once approved. Correct the wording if needed."],
    ["recipes", "Answers marked Helpful", "Confirmed ones are proposed first for similar questions; rejected ones never. Each keeps its path: the data it used (tables with their fields, metrics with their labels) and its steps; correct it in your words before confirming. An answer that ran no query (a check, a comparison with usual) is kept as its path; an investigation as the path the LLM wrote of it. Once confirmed, the next similar question starts from it."],
    ["values", "New values proposed for the categories", "Proposed by the LLM from the texts, or read by the learning in the data's category fields. A value is used once approved, with the links proposed with it; merge it into an existing one when it is the same thing. Nothing is added to the categories without you."],
    ["removals", "Links proposed for removal", "A link whose removal was proposed (by an editor, or by the learning: what it was read from is gone, the data no longer shows it) stays drawn and followed until you decide. Remove: it goes. Keep: the proposal goes."],
    ["retire", "Parts that look retired", "A value read in the data that its category's fields and labels have not shown for two weeks, or one a text says was retired or decommissioned. Nothing is retired by itself. Retire keeps the value, marked retired: it is no longer used nor drawn, and adding it again by hand brings it back. Keep: the same reason is not proposed again."],
    ["tags", "Categories given to items", "The LLM was not sure enough to give these alone."],
    ["links", "Relations and interactions", "What the LLM found related (explains, about, depends on), and the interactions between parts of the system that your documents state (each with its sentence): approved, they are drawn on the System map and followed by the agent's investigations."],
    ["fields", "Where the categories are in the data", "Labels and fields that hold several values of a category and are not read for it yet (0.10.2). Read it: the agent knows where the category is in the data, and the next learning proposes the label's other values as values of the category (here, to approve). Set aside: not proposed again."],
    ["warnings", "What could confuse the agent or the search", "Found in the knowledge each time this page is read (0.10.2): one name for two things (or a proposal naming a value of another category), one thing written two ways, the System map in a circle, documents holding the same pages, a term defined twice, (0.11.0) a memory, a catalog entry or a learned answer said twice or two alike ones. Each says why and what to do; Set aside: not said again."],
    ["grafana", "Alert rules and dashboards drafted for Grafana", "Drafted by the agent from a rule the team wrote (team memory, catalog) or asked in a chat (0.10.10). Grafana has nothing until you approve (with grafana.writes on): an alert rule is created in the folder of the settings (grafana.alert_folder), a dashboard in the folder of Browse its draft names (the folders whose dashboards are about the same things are shown), then read back. An existing rule or dashboard is never changed. Reject keeps it rejected."],
    ["context", "Context pages written by the agent", "The nightly Context build proposes each change of a page (and the removal of a page whose subject is gone): the page shown stays as it is until you approve. A newer change of the same page replaces the one you did not review yet; what that one said and this one no longer does is listed, so nothing is lost silently. A new page is shown at once and listed here until someone has read it."],
    // (0.11.0) last, as on the page: the only group the agent already uses
    ["routes", "Kinds of work learned from the chats", "Already used as examples by the router; set the right kind, or remove a wrong one."]
  ];
  var TITLES = {};
  GROUPS.forEach(function (g) { TITLES[g[0]] = g[1]; });

  function reviewFilter() {
    var input = el("input", { type: "search", class: "rfilter", value: reviewQ, "aria-label": "Filter what waits",
                              placeholder: "Filter: a part, a repository, a document, a word (Enter)" });
    var go = function () { var v = input.value.trim(); if (v !== reviewQ) { reviewQ = v; reviewLoad(); } };
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") go(); });
    input.addEventListener("search", go);           // (the field's clear button)
    return el("div", { class: "rfilter-row" }, [input, reviewQ ? el("span", { class: "muted", text: " only what names or was read in “" + reviewQ + "”; Approve or Reject all shown applies to these" }) : null]);
  }

  function summaryLine(waiting) {
    var box = $("review-summary");
    box.innerHTML = "";
    if (waiting || counts.routes || reviewQ) box.appendChild(reviewFilter());
    if (!waiting && !counts.routes && reviewQ) {
      box.appendChild(el("p", { class: "lead", text: "Nothing that waits names or was read in “" + reviewQ + "”." }));
      return;
    }
    if (!waiting && !counts.routes) {
      box.appendChild(el("p", { class: "lead", text: "Nothing waits for you. What the chats and the daily learning propose shows here, each with its actions." }));
      return;
    }
    box.appendChild(el("p", { class: "lead", text: waiting ? S.num(waiting) + " item" + (waiting > 1 ? "s wait" : " waits") + " for you. Nothing here is used by the agent until approved" +
      (counts.routes ? ", except the last group, which it already uses." : ".") :
      "Nothing waits for you. The agent already uses the items below; check them when you have time." }));
    var chips = el("div", { class: "rchips" });
    GROUPS.forEach(function (g) {
      if (!counts[g[0]]) return;
      chips.appendChild(el("button", { type: "button", class: "chip", text: g[1] + " · " + S.num(counts[g[0]]), onclick: function () {
        var s = $("rg-" + g[0]);
        if (s) s.scrollIntoView({ behavior: "smooth", block: "start" });
      } }));
    });
    box.appendChild(chips);
  }

  function group(key, items, render, extra) {
    var g = GROUPS.filter(function (x) { return x[0] === key; })[0];
    if (!counts[key]) return null;
    var head = el("div", { class: "rgroup-head" }, [el("h2", { text: g[1] }), S.info(g[2], g[1]),
      el("span", { class: "count", id: "rg-count-" + key, text: S.num(counts[key]) })]);
    if (extra && extra.bulk) head.appendChild(extra.bulk);
    var list = el("div", { class: "rlist" }, items.map(function (it) {   // (0.11.0) each card knows its item (bulk)
      var c = render(it);
      if (c) c._item = it;
      return c;
    }));
    var sec = el("section", { class: "rgroup", id: "rg-" + key }, [head, list]);
    if (extra && extra.fold && items.length > extra.fold) {          // a long optional group: the first ones
      var hidden = Array.prototype.slice.call(list.children, extra.fold);
      hidden.forEach(function (c) { c.hidden = true; });
      sec.appendChild(el("button", { type: "button", class: "btn small", text: "Show " + hidden.length + " more", onclick: function () {
        hidden.forEach(function (c) { c.hidden = false; });
        this.remove();
      } }));
    }
    if (counts[key] > items.length) {
      sec.appendChild(el("p", { class: "muted", text: "The first " + items.length + " of " + S.num(counts[key]) + (extra && extra.more ? "; " : ".") },
        extra && extra.more ? [extra.more] : []));
    }
    return sec;
  }

  /* the values the learning read in the data's category fields: a category's ones approved together (a field of
     servers gives hundreds), each button after a confirmation */
  function foundBulk(found) {
    var cats = Object.keys(found).filter(function (c) { return found[c] > 0; }).sort();
    if (!cats.length) return null;
    var box = el("span", { class: "rbulk" });
    cats.forEach(function (c) {
      var label = "Approve the " + S.num(found[c]) + " " + (FACET_NAMES[c] || c).toLowerCase() + " value" + (found[c] > 1 ? "s" : "") + " found in the data";
      var go = el("button", { type: "button", class: "btn small", text: label, onclick: function () {
        S.confirm(go, label + "?", { yes: "Approve " + S.num(found[c]), no: "Cancel",
          detail: "They are the values of the fields this category is read from. Each one is used by the agent at once; you can still change or retire them in Categories." }).then(function (ok) {
          if (!ok) return;
          go.disabled = true;
          S.admin("POST", "facets/approve-found", { facet: c }).then(function (r) {
            if (r.error) { go.disabled = false; go.title = r.error; return; }
            saved();
            reviewLoad();
          });
        });
      } });
      box.appendChild(go);
    });
    return box;
  }

  /* (0.10.9.2) the proposals the learning found to be other names of values you have: merged into them together,
     a category at a time, after a confirmation */
  function sameBulk(same) {
    var cats = Object.keys(same || {}).filter(function (c) { return same[c] > 0; }).sort();
    if (!cats.length || !S.canDelete) return null;
    var box = el("span", { class: "rbulk" });
    cats.forEach(function (c) {
      var label = "Merge the " + S.num(same[c]) + " other name" + (same[c] > 1 ? "s" : "") + " of " + (FACET_NAMES[c] || c).toLowerCase() + " values you have";
      var go = el("button", { type: "button", class: "btn small", text: label, onclick: function () {
        S.confirm(go, label + "?", { yes: "Merge " + S.num(same[c]), no: "Cancel",
          detail: "Each proposal is written like a value you have (case, spaces, a short form, an environment, a typo): it becomes one of that value's other names, its items and links go to it." }).then(function (ok) {
          if (!ok) return;
          go.disabled = true;
          S.admin("POST", "facets/merge-same", { facet: c }).then(function (r) {
            if (r.error) { go.disabled = false; go.title = r.error; return; }
            saved();
            reviewLoad();
          });
        });
      } });
      box.appendChild(go);
    });
    return box;
  }

  function newPage(pg) { return pg.what === "new" && !pg.rejected_before; }   // a Context page nobody read yet

  function grafanaDashboard(x, sp, pv) {   // (0.10.10) a dashboard drafted for Grafana, shown as it will be written
    var fits = pv["where it fits"] || [], d = sp.dashboard || {};
    var rows = [
      el("div", { class: "rtext" }, [el("strong", { text: d.title || sp.title || x.title }), document.createTextNode(" · a new dashboard")]),
      el("div", { class: "muted", text: "Folder in Browse: " + (pv.folder || sp.folder || sp.folder_uid || "?") +
        (fits.length ? (pv["fits best"] ? " (where its dashboards are about the same things)" :
          " · the folder whose dashboards are about the same things: " + fits[0].folder) : "") }),
      el("div", { class: "muted", text: "Time: from " + ((d.time || {}).from || "?") + " · tags: " + (d.tags || []).join(", ") })];
    if (d.description) rows.push(el("div", { class: "rtext small-note", text: "Description: " + d.description }));
    (d.panels || []).forEach(function (p) {
      var dfl = ((p.fieldConfig || {}).defaults) || {}, steps = ((dfl.thresholds || {}).steps || []).filter(function (t) { return t.value !== null && t.value !== undefined; });
      rows.push(el("div", { class: "rtext small-note", text: p.title + " (" + p.type + (dfl.unit ? ", " + dfl.unit : "") +
        (steps.length ? ", thresholds " + steps.map(function (t) { return t.color + " from " + t.value; }).join(", ") : "") + ")" +
        (p.description ? " · description: " + p.description : "") }));
      if (p.type === "text") rows.push(el("pre", { class: "query", text: (p.options || {}).content || "" }));
      if (p.targets) rows.push(el("pre", { class: "query", text: p.targets.map(function (t) {
        return t.expr + (t.legendFormat && t.legendFormat !== "__auto" ? "   [legend " + t.legendFormat + "]" : ""); }).join("\n") }));
    });
    if (fits.length) rows.push(el("div", { class: "muted", text: "Where it fits: " + fits.map(function (f) {
      return f.folder + " (" + (f.shares || []).join(", ") + ")"; }).join(" · ") }));
    if (x.source_text) rows.push(el("details", { class: "query" }, [el("summary", { text: "What the team wrote (" + x.source + ")" }), el("pre", { text: x.source_text })]));
    return card(rows, [x.source, x.requested_by ? "asked by " + x.requested_by : "", S.when(x.requested_at)].filter(Boolean).join(" · "), [
      act("Create in Grafana", "primary", "grafana", function () {
        return S.admin("POST", "grafana/" + x.id, { decision: "approve", spec_hash: x.spec_hash }).then(function (r) {
          return r.error ? r : { done: "created in " + (r.folder || "Grafana") + ((r.differences || []).length ?
            " (read back with differences: " + r.differences.join("; ") + ")" : " and read back") }; }); }),
      act("Reject", "", "grafana", function () {
        return S.admin("POST", "grafana/" + x.id, { decision: "reject" }).then(function (r) { return r.error ? r : { done: "rejected" }; }); })]);
  }


  function bulk(label, key, items, fn, reject, opts) {   // "Approve all shown" (or reject): a second click confirms;
    opts = opts || {};                                     // opts.pick: only those items (0.10.10), opts.detail: what it does
    /* (0.11.0) the cards still waiting, each with its own item: a card decided alone leaves the list, and the next
       cards were then paired with the items before theirs (a value rejected was approved again, the last one skipped) */
    var waiting = function () {
      var sec = $("rg-" + key);
      return sec ? Array.prototype.filter.call(sec.querySelectorAll(".rcard"), function (c) {
        return c._item && items.indexOf(c._item) >= 0 && !c.classList.contains("done") && (!opts.pick || opts.pick(c._item));
      }) : [];
    };
    var box = el("span", { class: "rbulk" });
    var go = el("button", { type: "button", class: "btn small", text: label, onclick: function () {
      var n = waiting().length;                            // (0.11.0) counted now: the ones decided alone are not in it
      if (!n) return;
      S.confirm(go, label + ": the " + n + " shown?", { yes: (reject ? "Reject " : "Approve ") + n, no: "Cancel",
        detail: opts.detail || (reject ? "Each one is set aside and never proposed again; you can still add it by hand." :
          "Each one is used by the agent at once; you can still change or retire them in Categories.") }).then(function (ok) {
        if (ok) all();
      });
    } });
    var all = function () {
      var sec = $("rg-" + key);                            // (0.11.0) one bulk at a time: Approve all and Reject all both wait
      if (sec) sec.querySelectorAll(".rbulk button").forEach(function (b) { b.disabled = true; });
      var chain = Promise.resolve(), n = 0;
      waiting().forEach(function (c) {
        var it = c._item;
        chain = chain.then(function () {
          return c.classList.contains("done") ? { skip: true } : fn(it);     // decided alone meanwhile: left as decided
        }).then(function (r) {
          if (!r || r.skip || r.error) return;
          c.classList.add("done", "leaving"); c._acts.innerHTML = ""; c._acts.appendChild(el("span", { class: "rdone", text: reject ? "rejected" : "approved" }));
          n++;
        });
      });
      chain.then(function () { go.remove(); done(key, n); setTimeout(reviewLoad, 450); });
    };
    box.appendChild(go);
    return box;
  }

  var reviewQ = "";                             // (0.10.1) the filter: a part, a repository, a document, a word
  function reviewLoad() {
    var box = $("review");
    box.innerHTML = "";
    box.appendChild(el("p", { class: "muted", text: "Loading…" }));
    return S.admin("GET", "review?limit=50" + (reviewQ ? "&q=" + encodeURIComponent(reviewQ) : "")).then(function (d) {
      box.innerHTML = "";
      if (d.error) { box.appendChild(el("p", { class: "result bad", text: d.error })); return; }
      counts = Object.assign({}, d.counts || {});
      setWaiting(d.waiting || 0);
      summaryLine(d.waiting || 0);
      var parts = [
        group("memory", d.memory || [], function (m) {
          var text = el("div", { class: "rtext", text: m.text });
          return card([text], [m.kind, m.category, m.source === "chat" ? "from a chat" : "written by a user", S.when(m.created_at)].filter(Boolean).join(" · "), [
            act("Approve", "primary", "memory", function () { return S.admin("POST", "memory/" + m.id, { status: "active" }).then(function (r) { return r.error ? r : { done: "approved" }; }); }),
            toggleButton("Edit", "p-edit", function () {
              var ta = el("textarea", { rows: "2", "aria-label": "Memory" });
              ta.value = m.text;
              text.hidden = true;
              var panel = el("div", { class: "actions" }, [ta, act("Save and approve", "primary", "memory", function () {
                return S.admin("POST", "memory/" + m.id, { text: ta.value, status: "active" }).then(function (r) { return r.error ? r : { done: "corrected and approved" }; });
              })]);
              panel._close = function () { text.hidden = false; };
              return panel;
            }),
            act("Reject", "", "memory", function () { return S.admin("POST", "memory/" + m.id, { status: "disabled" }).then(function (r) { return r.error ? r : { done: "rejected (kept, not used)" }; }); })
          ]);
        }),
        group("recipes", d.recipes || [], function (r) {
          var isPath = r.tool === "investigation" || r.tool === "path";   // the way an answer went: read, not run
          // what the agent kept of the discussion (0.9.6): a title, a description, the steps, the checks
          var kept = recipeSummary(r);
          var q = el("div", { class: kept ? "rtext muted small" : "rtext", text: (kept ? "Question: " : "") + r.question });
          var way = el("details", { class: "query" }, [el("summary", { text: (r.tool === "investigation" ? "Investigation path" : r.tool === "path" ?
            "Path (the checks that answered it)" : (r.tool || "")) + (r.target ? " · " + r.target : "") }), el("pre", { text: r.query || "" })]);
          if (isPath) way.open = true;
          // the path of an answer that keeps a query: the data it used and its steps
          var steps = !isPath && r.path ? el("details", { class: "query recipe-way" }, [el("summary", { text: "Its path: the data it uses, its steps" }), el("pre", { text: r.path })]) : null;
          if (kept) way.open = false;                // the summary first; the run itself folded below it
          return card([kept, q, way, steps].filter(Boolean),
            "used " + S.num(r.uses || 1) + " time" + ((r.uses || 1) > 1 ? "s" : "") + " · " + S.when(r.created_at), [
              act("Confirm", "primary", "recipes", function () { return S.dict("POST", "recipes/" + r.id, { status: "confirmed" }).then(function (x) { return x.error ? x : { done: "confirmed" }; }); }),
              toggleButton("Edit", "p-edit", function () {
                var qa = el("textarea", { rows: "2", class: "recipe-q", "aria-label": isPath ? "The kind of problem" : "The generic question", maxlength: "2000" });
                qa.value = r.question || "";
                var code = el("textarea", { rows: isPath ? "12" : "6", class: "recipe-query", spellcheck: "false", "aria-label": isPath ? "The path" : "The query" });
                code.value = r.query || "";
                var res = el("div", { class: "result", role: "status" });
                var pathBox = steps ? el("textarea", { rows: "5", class: "recipe-path", spellcheck: "false", "aria-label": "Its path: the data it uses, its steps" }) : null;
                if (pathBox) pathBox.value = r.path || "";
                var tt = el("input", { type: "text", maxlength: "120", class: "recipe-title", "aria-label": "Title", placeholder: "Title" });
                tt.value = r.title || "";
                var dd = el("textarea", { rows: "2", class: "recipe-desc", "aria-label": "Description", placeholder: "What it answers, when to reuse it" });
                dd.value = r.description || "";
                var hw = el("textarea", { rows: "5", class: "recipe-how", "aria-label": "Steps, one per line", placeholder: "The steps, one per line" });
                hw.value = (r.how || []).join("\n");
                var tk = el("textarea", { rows: "3", class: "recipe-tasks", "aria-label": "Checks, one per line", placeholder: "The checks to do each time, one per line" });
                tk.value = (r.tasks || []).join("\n");
                q.hidden = true; way.hidden = true;
                if (steps) steps.hidden = true;
                if (kept) kept.hidden = true;
                var panel = el("div", { class: "recipe-edit" }, [el("div", { class: "ctx-diff-h", text: "What to keep (title, description, steps, checks)" }),
                  tt, dd, hw, tk, el("div", { class: "ctx-diff-h", text: "The question and the way it was answered" }), qa, code, pathBox, el("div", { class: "actions" }, [
                  isPath ? null : el("button", { type: "button", class: "btn small", text: "Check the query", onclick: function () {
                    res.className = "result"; res.textContent = "running it with your permissions…";
                    S.dict("POST", "recipes/" + r.id + "/check", { query: code.value }).then(function (x) {
                      res.className = "result " + (x.error ? "bad" : "good");
                      res.textContent = x.error || ("The query runs: " + S.num(x.rows) + " row" + (x.rows === 1 ? "" : "s") +
                        (x.columns && x.columns.length ? " (" + x.columns.join(", ") + ")" : ""));
                    });
                  } }),
                  act("Save and confirm", "primary", "recipes", function () {
                    var body = { question: qa.value, query: code.value, status: "confirmed", title: tt.value,
                                 description: dd.value, how: hw.value, tasks: tk.value };
                    if (pathBox) body.path = pathBox.value;
                    return S.dict("POST", "recipes/" + r.id, body).then(function (x) {
                      return x.error ? x : { done: "corrected and confirmed" };
                    });
                  })]), res]);
                panel._close = function () { q.hidden = false; way.hidden = false; if (steps) steps.hidden = false; if (kept) kept.hidden = false; };
                return panel;
              }),
              act("Reject", "", "recipes", function () { return S.dict("POST", "recipes/" + r.id, { status: "rejected" }).then(function (x) { return x.error ? x : { done: "rejected" }; }); })
            ]);
        }),
        group("values", d.values || [], function (v) {
          var name = el("div", { class: "rtext" }, [el("span", { class: "facet-chip" })]);
          var desc = el("div", { class: "muted" }), parts = el("div", { class: "muted" });
          var paint = function () {                 // the card says the value as it is now (after an Edit saved)
            name.firstChild.textContent = v.facet + ": " + v.value;
            desc.textContent = v.description || "";
            desc.hidden = !v.description;
            parts.textContent = (v.parents || []).length ? "links proposed with it: " + (v.parents || []).map(function (x) {
              return "\u2192 " + x.value + " (" + (FACET_NAMES[x.facet] || x.facet).toLowerCase() + "): belongs to"; }).join("; ") : "";
            parts.hidden = !(v.parents || []).length;
          };
          paint();
          /* the same name under another category (a "component" that is a service of yours): one click files it there */
          var elsewhere = !!v.same_as && v.same_as.facet !== v.facet;
          var same = v.same_as ? el("div", { class: "rsame" }, [
            el("span", { class: "muted", text: elsewhere ? "You already have " + v.same_as.facet + " " + v.same_as.value + ": probably the same part. " :
              "The LLM thinks it is the same as " + v.same_as.facet + " " + v.same_as.value + ". " })]) : null;
          var acts = [
            act("Approve", "primary", "values", function () { return S.admin("POST", "facets/" + v.id, { status: "approved" }).then(function (r) { return r.error ? r : { done: "approved" }; }); }),
            /* Edit: everything about the value at once, as in Categories (its category, its name, what it covers,
               its other names), then approved with it, or saved to decide later; its links once it is approved */
            toggleButton("Edit…", "p-edit", function () {
              var cat = el("select", { "aria-label": "Category" }, Object.keys(FACET_NAMES).map(function (k) {
                return el("option", { value: k, text: FACET_NAMES[k], selected: k === v.facet ? "selected" : null }); }));
              var nm = el("input", { type: "text", class: "rename", "aria-label": "Name", maxlength: "128" });
              nm.value = v.value;
              var ds = el("input", { type: "text", "aria-label": "What it covers", placeholder: "what it covers" });
              ds.value = v.description || "";
              var sy = el("input", { type: "text", "aria-label": "Also called", placeholder: "also called (comma separated)" });
              sy.value = (v.synonyms || []).join(", ");
              var send = function (approve) {
                var body = { facet: cat.value, value: nm.value, description: ds.value, synonyms: sy.value };
                if (approve) body.status = "approved";
                return S.admin("POST", "facets/" + v.id, body);
              };
              var merged = function (r) {            // that name exists there already: one value, said
                return { done: "merged into " + r.facet + " " + r.value + " (it exists already)", reload: true };
              };
              var saveApprove = act("Save and approve", "primary", "values", function () {
                return send(true).then(function (r) {
                  if (r.error) return r;
                  return r.merged_into ? merged(r) : { done: "approved as " + r.facet + ": " + r.value };
                });
              });
              var saveOnly = act("Save", "", "values", function (c) {
                    return send(false).then(function (r) {
                      if (r.error) return r;
                      if (r.merged_into) return merged(r);
                      v.facet = r.facet; v.value = r.value; v.description = ds.value.trim();
                      v.synonyms = sy.value.split(",").map(function (x) { return x.trim(); }).filter(Boolean);
                      paint();
                      c.querySelectorAll(".rpanel").forEach(function (x) { x.remove(); });
                      c.querySelectorAll("button[aria-expanded]").forEach(function (b) { b.setAttribute("aria-expanded", "false"); b.classList.remove("on"); });
                      var note = c.querySelector(".rsaved") || c.querySelector(".rbody").appendChild(el("div", { class: "rsaved result good" }));
                      note.textContent = "saved: it still waits for your approval";
                      saved();
                      return { keep: true };
                    });
              });
              return el("div", { class: "facet-edit" }, [
                el("label", { class: "field" }, [el("span", { text: "Category" }), cat]),
                el("label", { class: "field" }, [el("span", { text: "Name" }), nm]),
                el("label", { class: "field" }, [el("span", { text: "What it covers" }), ds]),
                el("label", { class: "field" }, [el("span", { text: "Also called" }), sy]),
                el("div", { class: "actions" }, [saveApprove, saveOnly])]);
            }),
            !canDelete ? null : toggleButton("Merge into…", "p-merge", function () {   // (0.11.0) a merge: an AI Admin's
              var sel = el("select", { class: "merge", "aria-label": "Merge into" }, [el("option", { value: "", text: "Loading…" })]);
              var line = el("div", { class: "actions" }, [sel]);
              S.admin("GET", "facets?facet=" + encodeURIComponent(v.facet) + "&status=approved").then(function (f) {
                sel.innerHTML = "";
                sel.appendChild(el("option", { value: "", text: "Merge into…" }));
                (f.facets || []).forEach(function (x) { sel.appendChild(el("option", { value: x.id, text: x.value + " (" + x.items + ")" })); });
                if (canDelete) line.appendChild(act("Merge", "primary", "values", function () {
                  if (!sel.value) return { keep: true };
                  return S.admin("POST", "facets/" + v.id, { merge_into: +sel.value }).then(function (r) {
                    return r.error ? r : { done: "merged into " + sel.options[sel.selectedIndex].text.replace(/ \(\d[\d,]*\)$/, ""), reload: true };
                  });
                }));
              });
              return line;
            }),
            act("Reject", "", "values", function () { return S.admin("POST", "facets/" + v.id, { status: "rejected" }).then(function (r) { return r.error ? r : { done: "rejected" }; }); })
          ];
          if (v.same_as && canDelete) acts.unshift(act("Merge into " + (elsewhere ? v.same_as.facet + " " : "") + v.same_as.value, "primary", "values", function () {
            // another category: the value moves there, where its name exists (one value, its items together)
            var body = elsewhere ? { facet: v.same_as.facet, value: v.same_as.value } : { merge_into: v.same_as.id };
            return S.admin("POST", "facets/" + v.id, body).then(function (r) {
              return r.error ? r : { done: "merged into " + v.same_as.value, reload: true };
            });
          }));
          var from = v.source === "data" ? "found in the data" + ((v.origins || []).length ? ": " + v.origins[0] : "") : "proposed by the LLM";
          return card([name, desc, parts, same], S.num(v.items) + " item" + (v.items === 1 ? "" : "s") + " · " + from, acts);
        }, { bulk: el("span", { class: "rbulks" }, [sameBulk(d.same || {}), foundBulk(d.found || {}),
          (d.values || []).length > 1 ? bulk("Approve all shown", "values", d.values, function (v) { return S.admin("POST", "facets/" + v.id, { status: "approved" }); }) : null,
          (d.values || []).length > 1 ? bulk("Reject all shown", "values", d.values, function (v) { return S.admin("POST", "facets/" + v.id, { status: "rejected" }); }, true) : null]) }),
        group("removals", d.removals || [], function (x) {
          return card([el("div", { class: "rtext" }, [document.createTextNode(x.a_title + (x.both ? " \u2194 " : " \u2192 ") + x.b_title + ": "),
                         el("span", { class: "link-kind", text: x.label || String(x.kind || "").replace(/_/g, " ") })]),
                       x.note ? el("div", { class: "muted", text: "“" + x.note + "”" }) : null,
                       el("div", { class: "muted", text: "Why: " + (x.why || "?") })],
            "removal proposed " + S.when(x.at) + (x.source ? " · the link came from " + x.source : ""),
            S.canDelete ? [
              act("Remove", "primary", "removals", function () { return S.dict("POST", "map", { removal: { id: x.id, remove: true } }).then(function (r) { return r.error ? r : { done: "removed" }; }); }),
              act("Keep", "", "removals", function () { return S.dict("POST", "map", { removal: { id: x.id, remove: false } }).then(function (r) { return r.error ? r : { done: "kept" }; }); })
            ] : [el("span", { class: "muted", text: "an AI Admin decides" })]);
        }),
        group("retire", d.retire || [], function (x) {
          var why = x.kind === "said" ? "a text says it was retired" : x.kind === "absent" ? "no longer in the data" : "names nothing";
          return card([el("div", { class: "rtext" }, [el("span", { class: "facet-chip", text: x.facet + ": " + x.value })]),
                       el("div", { class: "muted", text: x.why }),
                       x.evidence ? el("div", { class: "muted", text: (x.kind === "said" ? "“" + x.evidence + "”" : "it was read from: " + x.evidence) }) : null],
            why + " · " + (x.source === "data" ? "read from the data" : "put by hand") + (x.at ? " · proposed " + x.at : ""), [
              canDelete && act("Retire", "primary", "retire", function () { return S.admin("POST", "facets/" + x.id, { retire: true }).then(function (r) { return r.error ? r : { done: "retired (kept, no longer used)" }; }); }),
              act("Keep", "", "retire", function () { return S.admin("POST", "facets/" + x.id, { retire: false }).then(function (r) { return r.error ? r : { done: "kept: not proposed again for this reason" }; }); })
            ]);
        }),
        group("tags", d.tags || [], function (t) {
          return card([el("div", { class: "rtext" }, [document.createTextNode(t.title + " "), el("span", { class: "facet-chip", text: t.facet + ": " + t.value })])],
            t.ref + (t.confidence !== null && t.confidence !== undefined ? " · confidence " + Math.round(t.confidence * 100) + "%" : ""), [
              act("Approve", "primary", "tags", function () { return S.admin("POST", "tags/" + t.id, { status: "approved" }).then(function (r) { return r.error ? r : { done: "approved" }; }); }),
              toggleButton("Change…", "p-retag", function () {
                var sel = el("select", { class: "retag", "aria-label": "Another value" }, [el("option", { value: "", text: "Loading…" })]);
                var panel = el("div", { class: "actions" }, [sel,
                  act("Save and approve", "primary", "tags", function () {
                    if (!sel.value) return { keep: true };
                    return S.admin("POST", "tags/" + t.id, { facet_id: +sel.value }).then(function (r) {
                      return r.error ? r : { done: "changed to " + sel.options[sel.selectedIndex].text + " and approved" };
                    });
                  })]);
                S.admin("GET", "facets?status=approved").then(function (d) {
                  sel.innerHTML = "";
                  sel.appendChild(el("option", { value: "", text: "Another value…" }));
                  var by = {};
                  (d.facets || []).forEach(function (v) { (by[v.facet] = by[v.facet] || []).push(v); });
                  Object.keys(by).sort(function (a, b) { return (a === t.facet ? -1 : 0) - (b === t.facet ? -1 : 0); }).forEach(function (k) {
                    sel.appendChild(el("optgroup", { label: k }, by[k].map(function (v) { return el("option", { value: v.id, text: v.value }); })));
                  });
                });
                return panel;
              }),
              act("Reject", "", "tags", function () { return S.admin("POST", "tags/" + t.id, { status: "rejected" }).then(function (r) { return r.error ? r : { done: "rejected" }; }); })
            ]);
        }, { bulk: (d.tags || []).length > 1 ? bulk("Approve all shown", "tags", d.tags, function (t) { return S.admin("POST", "tags/" + t.id, { status: "approved" }); }) : null }),
        group("links", d.links || [], function (x) {
          // an interaction between two parts of the system, read in a text: its short and long explanations (an
          // admin corrects them here before approving), and the sentence that says it
          var shortIn = el("input", { type: "text", maxlength: "500", value: x.note || "", "aria-label": "Short explanation",
                                      placeholder: x.kind === "runs_on" ? "In a few words: what it is or does on that place" :
                                        x.kind === "monitors" ? "In a few words: what it watches" :
                                        "In a few words: what it waits for, reads, sends, uses" });
          var longIn = el("textarea", { rows: "2", maxlength: "2000", "aria-label": "Long explanation",
                                        placeholder: "What an investigation checks on the other part, and what a problem there does here" });
          longIn.value = x.detail || "";
          // (0.10.6) corrected before approving: its kind (from the list) and its direction
          var kindSel = x.parts ? el("select", { "aria-label": "Kind of link" }, LINK_KINDS.map(function (k) {
            return el("option", { value: k[0], text: k[1], selected: k[0] === x.kind ? "selected" : null }); })) : null;
          if (kindSel && LINK_KINDS.every(function (k) { return k[0] !== x.kind; })) {
            kindSel.insertBefore(el("option", { value: x.kind, text: x.label || String(x.kind || "").replace(/_/g, " "), selected: "selected" }), kindSel.firstChild);
          }
          var turn = x.parts ? el("input", { type: "checkbox", "aria-label": "Turn the link round" }) : null;
          var editBox = x.parts ? el("div", { class: "link-edit", hidden: "hidden" }, [
            el("label", {}, [el("span", { class: "muted", text: "Kind: " }), kindSel]),
            el("label", {}, [turn, el("span", { text: " turn it round (" + x.b_title + " \u2192 " + x.a_title + ")" })])]) : null;
          function edits() {
            var body = {};
            if (kindSel && kindSel.value !== x.kind) body.kind = kindSel.value;
            if (turn && turn.checked) body.reverse = true;
            if (x.parts && (shortIn.value !== (x.note || "") || longIn.value !== (x.detail || ""))) { body.note = shortIn.value; body.detail = longIn.value; }
            return body;
          }
          return card([el("div", { class: "rtext" }, [document.createTextNode(x.a_title + (x.both ? " \u2194 " : " \u2192 ") + x.b_title + ": "),
                                                    el("span", { class: "link-kind", text: x.parts ? x.label : String(x.kind || "").replace(/_/g, " ") })]),
                       editBox,
                       x.parts ? el("label", { class: "link-explain" }, [el("span", { class: "muted", text: "Short: " }), shortIn]) :
                         (x.note ? el("div", { class: "muted", text: "“" + x.note + "”" }) : null),
                       x.parts ? el("details", { class: "link-explain" }, [el("summary", { text: "In full: what to do when following it" }), longIn]) : null,
                       x.evidence ? el("div", { class: "muted small-note", text: "Said in: " + x.evidence }) : null],
            (x.parts ? "a link of the System map" : x.a + " → " + x.b) + (x.confidence !== null && x.confidence !== undefined ? " · confidence " + Math.round(x.confidence * 100) + "%" : ""), [
              act("Approve", "primary", "links", function () {
                var body = edits();
                body.status = "approved";
                return S.admin("POST", "links/" + x.id, body).then(function (r) { return r.error ? r : { done: "approved" + (body.kind || body.reverse ? " as corrected" : "") }; }); }),
              x.parts ? el("button", { type: "button", class: "btn small", text: "Edit", onclick: function () { editBox.hidden = !editBox.hidden; } }) : null,
              x.parts ? act("Save", "", "links", function () {
                var body = edits();
                if (!Object.keys(body).length) return Promise.resolve({ error: "nothing changed" });
                return S.admin("POST", "links/" + x.id, body).then(function (r) { return r.error ? r : { done: "saved (still to approve)", reload: true }; }); }) : null,
              act("Reject", "", "links", function () { return S.admin("POST", "links/" + x.id, { status: "rejected" }).then(function (r) { return r.error ? r : { done: "rejected" }; }); })
            ]);
        }, { bulk: (d.links || []).length > 1 ? el("span", { class: "rbulks" }, [
          bulk("Approve all shown", "links", d.links, function (x) { return S.admin("POST", "links/" + x.id, { status: "approved" }); }),
          bulk("Reject all shown", "links", d.links, function (x) { return S.admin("POST", "links/" + x.id, { status: "rejected" }); }, true)]) : null }),
        group("fields", d.fields || [], function (x) {
          return card([el("div", { class: "rtext" }, [el("span", { class: "facet-chip", text: x.subject })]),
                       el("div", { class: "muted", text: "Why: " + x.why }),
                       el("div", { class: "rtext small-note", text: "What it does: " + x.fix })],
            x.held + " of " + x.of + " values of " + x.category + (x.others ? " · " + x.others + " other values" : ""),
            (S.isAdmin ? [act("Read " + x.category + " from " + x.name, "primary", "fields", function () {
              return S.admin("POST", "fields/decide", { category: x.category, name: x.name, read: true }).then(function (r) {
                return r.error ? r : { done: "read from " + x.name + " (the next learning proposes its values)" }; }); })] : []).concat([
              act("Set aside", "", "fields", function () {
                return S.admin("POST", "fields/decide", { category: x.category, name: x.name, read: false }).then(function (r) {
                  return r.error ? r : { done: "set aside: not proposed again" }; }); })]));
        }),
        group("grafana", d.grafana || [], function (x) {         // (0.10.10) an alert rule for Grafana: an admin's
          var sp = x.spec || {}, pv = x.preview || {};
          if (x.kind === "create_dashboard") return grafanaDashboard(x, sp, pv);   // or a dashboard
          var now = Array.isArray(pv["value now"]) ? pv["value now"].join(", ") : (pv["value now"] || "?");
          var fires = pv["would fire now"] === true ? " (it would fire now)" : pv["would fire now"] === false ? " (it would not fire now)" : "";
          var rows = [
            el("div", { class: "rtext" }, [el("strong", { text: sp.title || x.title })]),
            el("pre", { class: "query", text: (sp.query || "") + "\n" + (sp.operator === "lt" ? "< " : "> ") + sp.threshold + " for " + (sp.for || "") }),
            el("div", { class: "muted", text: "Labels: " + Object.keys(sp.labels || {}).map(function (k) { return k + "=" + sp.labels[k]; }).join(", ") +
              " · folder " + (sp.folder_uid || "") + ", group " + (sp.rule_group || "") }),
            el("div", { class: "muted", text: "Value now: " + now + fires + (pv.notified ? " · notified: " + pv.notified.join(", ") : "") })];
          var ann = sp.annotations || {};                    // every text written with the rule (0.10.10)
          if (ann.summary) rows.push(el("div", { class: "rtext small-note", text: "Summary: " + ann.summary }));
          if (ann.description) rows.push(el("div", { class: "rtext small-note", text: "Description: " + ann.description }));
          if (ann.runbook_url) rows.push(el("div", { class: "rtext small-note", text: "Runbook: " + ann.runbook_url }));
          if (x.source_text) rows.push(el("details", { class: "query" }, [el("summary", { text: "The rule as the team wrote it (" + x.source + ")" }), el("pre", { text: x.source_text })]));
          return card(rows, [x.source, x.requested_by ? "asked by " + x.requested_by : "", S.when(x.requested_at)].filter(Boolean).join(" · "), [
            act("Create in Grafana", "primary", "grafana", function () {
              return S.admin("POST", "grafana/" + x.id, { decision: "approve", spec_hash: x.spec_hash }).then(function (r) {
                return r.error ? r : { done: "created in Grafana" + ((r.differences || []).length ? " (read back with differences: " + r.differences.join("; ") + ")" : " and read back") }; }); }),
            act("Reject", "", "grafana", function () {
              return S.admin("POST", "grafana/" + x.id, { decision: "reject" }).then(function (r) { return r.error ? r : { done: "rejected" }; }); })]);
        }),
        group("warnings", d.warnings || [], function (w) {
          return card([el("div", { class: "rtext" }, [el("span", { class: "facet-chip", text: w.subject })]),
                       el("div", { class: "muted", text: "Why: " + w.why }),
                       el("div", { class: "rtext small-note", text: "What to do: " + w.fix })],
            String(w.kind || "").replace(/_/g, " ") + ((w.refs || []).length ? " · " + w.refs.join(", ") : ""),
            (canDelete ? (w.merge || []).map(function (m) {      // one thing written two ways: the fix in one click
              return act(m.label, "primary", "warnings", function () {
                return S.admin("POST", "facets/" + m.from, { merge_into: m.into }).then(function (r) { return r.error ? r : { done: "merged", reload: true }; }); });
            }) : []).concat((w.keep || []).map(function (k) {   // (0.10.6) a loop: one direction kept, the other rejected
              return act(k.label, "primary", "warnings", function () {
                return S.admin("POST", "links/" + k.reject, { status: "rejected" }).then(function (r) { return r.error ? r : { done: "done: the other one rejected", reload: true }; }); });
            })).concat((w.reject || []).map(function (k) {      // (0.10.6) a proposal named as an approved value: rejected
              return act(k.label, "", "warnings", function () {
                return S.admin("POST", "facets/" + k.facet, { status: "rejected" }).then(function (r) { return r.error ? r : { done: "rejected", reload: true }; }); });
            })).concat((w.disable || []).map(function (k) {     // (0.10.6) a document holding only pages read before
              return act(k.label, "", "warnings", function () {
                return S.admin("POST", "docs/" + k.doc, { enabled: false }).then(function (r) { return r.error ? r : { done: "disabled", reload: true }; }); });
            })).concat((canDelete ? (w.remove || []) : []).map(function (k) {   // (0.11.0) a copy: removed or disabled
              return act(k.label, "", "warnings", function () {
                // (0.11.0) a memory or an entry is disabled (kept, not used); a learned answer is deleted: removed
                var done = function (r) { return r.error ? r : { done: k.recipe ? "removed" : "disabled", reload: true }; };
                if (k.memory) return S.admin("POST", "memory/" + k.memory, { status: "disabled" }).then(done);
                if (k.recipe) return S.dict("DELETE", "recipes/" + k.recipe).then(done);
                return S.admin("PUT", "entries/" + k.entry, k.values || { enabled: false }).then(done);
              });
            })).concat([
              act("Set aside", "", "warnings", function () { return S.admin("POST", "lint/dismiss", { key: w.key }).then(function (r) { return r.error ? r : { done: "set aside: not said again" }; }); })
            ]));
        }),
        group("context", d.context || [], function (pg) {
          // a Context page: its change as statements added and dropped, what an earlier proposal said that this one does not
          var main = [el("div", { class: "rtext" }, [document.createTextNode(pg.title + " "),
            el("span", { class: "facet-chip", text: pg.section + " \u00b7 " + (pg.what === "remove" ? "removal proposed" :
              pg.what === "new" ? (pg.rejected_before ? "new version of a page you rejected" : "new page") : "change proposed") })])];
          function list(title, items, cls) {
            if (!items || !items.length) return;
            main.push(el("div", { class: "ctx-diff-h", text: title + " (" + items.length + ")" }));
            main.push(el("ul", { class: "ctx-diff " + cls }, items.slice(0, 12).map(function (x) { return el("li", { text: x }); })));
          }
          var dv = diffView(pg.diff || [], pg.what === "new" ? ["", "The new page"] :
            pg.what === "remove" ? ["The page shown (its removal is proposed)", ""] : ["The page shown now", "The page proposed"]);
          if (pg.what === "change") {
            main.push(dv);
            if (pg.replaced) list("Said by the earlier proposal it replaces, not by this one", pg.left_out, "left");
            var short = el("details", { class: "ctx-full" }, [el("summary", { text: "In short: the statements added and dropped" })]);
            var keep = main;
            main = [];
            list("Added", pg.added, "add");
            list("No longer said (obsolete in the page shown)", pg.obsolete, "drop");
            main.forEach(function (x) { short.appendChild(x); });
            main = keep;
            main.push(short);
          } else if (pg.what === "remove") {
            main.push(el("div", { class: "rtext muted", text: "Its subject is no longer found (a database or an application gone)." }));
            main.push(dv);
          } else {
            main.push(dv);
          }
          var acts = [];
          if (pg.what !== "remove" || canDelete) acts.push(act(pg.what === "remove" ? "Remove" :
            pg.what === "new" && !pg.rejected_before ? "Read: fine" : "Approve",
            "primary", "context", function () {
              return S.admin("POST", "context/" + pg.id + "/review", { action: "approve" }).then(function (r) {
                return r.error ? r : { done: pg.what === "remove" ? "removed" : "approved" }; });
            }));
          if (pg.what !== "new") acts.push(act(pg.what === "remove" ? "Keep it" : "Keep the page as it is", "", "context", function () {
            return S.admin("POST", "context/" + pg.id + "/review", { action: "reject" }).then(function (r) {
              return r.error ? r : { done: "kept as it is" }; });
          }));
          // a new page can be refused (0.9.6.1): shown to nobody, not searched; proposed again (here) when its sources change
          if (pg.what === "new") acts.push(act("Reject", "", "context", function () {
            return S.admin("POST", "context/" + pg.id + "/review", { action: "reject" }).then(function (r) {
              return r.error ? r : { done: "rejected: not shown nor searched; proposed again when its sources change" }; });
          }));
          // edit the proposed page (or a new one) before approving it, as the other cards: your text is shown (0.9.6)
          if (pg.what !== "remove") acts.push(toggleButton("Edit", "p-edit", function () {
            var ta = el("textarea", { class: "context-edit ctx-edit", rows: "16", "aria-label": "The page, as it will be shown" });
            ta.value = pg.what === "change" ? pg.proposed : pg.content;
            return el("div", { class: "ctx-editor" }, [
              el("div", { class: "ctx-diff-h", text: "Edit the page (Markdown); Save and approve shows your text. The agent proposes " +
                "again only when its sources change, and lists what of your text its proposal would drop." }),
              ta, el("div", { class: "actions" }, [el("button", { type: "button", class: "btn small", text: "Show the changes",
                onclick: function () {
                  S.admin("POST", "context/" + pg.id + "/diff", { content: ta.value }).then(function (r) {
                    if (!r.error && dv._update) { dv._update(r.diff || []); dv.scrollIntoView({ behavior: "smooth", block: "nearest" }); }
                  });
                } }), act("Save and approve", "primary", "context", function () {
                return S.admin("POST", "context/" + pg.id + "/review", { action: "approve", content: ta.value }).then(function (r) {
                  return r.error ? r : { done: r.edited ? "approved as you edited it" : "approved" }; });
              })])]);
          }));
          return card(main, "version " + pg.version + (pg.proposed_at ? " \u00b7 proposed " + S.when(pg.proposed_at) : "") +
            (pg.replaced ? " \u00b7 replaces " + pg.replaced + " earlier proposal" + (pg.replaced > 1 ? "s" : "") : ""), acts);
        }, (d.context || []).filter(newPage).length > 1 ? { bulk: bulk("Read: fine, all new pages shown", "context",   // (0.10.10)
          d.context || [], function (pg) { return S.admin("POST", "context/" + pg.id + "/review", { action: "approve" }); }, false,
          { pick: newPage, detail: "Each new page stays as it is (the agent reads it already); you can still edit or reject it later in the Context." }) } : null),
        // (0.11.0) the Context pages wait for a decision: drawn above; what the agent already uses comes last
        counts.routes ? el("h2", { class: "section-title later", text: "When you have time (already used by the agent)" }) : null,
        group("routes", d.routes || [], function (r) {
          var sel = el("select", { "aria-label": "Kind of work" }, ROUTES.map(function (k) { return el("option", { value: k, text: k, selected: k === r.route ? "selected" : null }); }));
          return card([el("div", { class: "rtext", text: r.question }), el("div", {}, [el("span", { class: "facet-chip", text: r.route })])],
            "routed by " + (r.by || "?") + " · marked " + (r.signal || "") + " · " + S.when(r.at), [
              sel,
              act("Set", "primary", "routes", function () { return S.admin("POST", "routes/" + r.id, { route: sel.value }).then(function (x) { return x.error ? x : { done: sel.value === r.route ? "kept: " + r.route : "set to " + sel.value }; }); }),
              act("Not an example", "", "routes", function () { return S.admin("POST", "routes/" + r.id, { remove: true }).then(function (x) { return x.error ? x : { done: "removed" }; }); })
            ]);
        }, { fold: 10 })
      ];
      parts.forEach(function (p) { if (p) box.appendChild(p); });
      box.appendChild(refusedFold());
    });
  }
  var ROUTES = ["functional", "technical", "incident", "charts", "observability", "infrastructure"];

  /* (0.11.4) what was refused before, out of the way (the user's request: "in a hidden menu, not clearly visible"):
     folded at the very bottom, read only when opened, never counted as waiting. A value or a link can be proposed
     again (it comes back above, to decide) or used again at once; one that cannot says why. */
  var refusedOpen = false;
  function refusedFold() {
    var fold = el("details", { class: "refused-fold" }, [el("summary", { text: "Refused earlier" })]);
    var body = el("div", { class: "refused-body" });
    fold.appendChild(body);
    var loaded = false;
    fold.addEventListener("toggle", function () {
      refusedOpen = fold.open;
      if (fold.open && !loaded) { loaded = true; refusedLoad(body); }
    });
    if (refusedOpen) { fold.open = true; }
    return fold;
  }
  function refusedLoad(body) {
    body.innerHTML = "";
    body.appendChild(el("p", { class: "muted", text: "Reading what was refused…" }));
    var q = reviewQ ? "&q=" + encodeURIComponent(reviewQ) : "";
    S.admin("GET", "review/refused?limit=30" + q).then(function (d) {
      body.innerHTML = "";
      if (d.error) { body.appendChild(el("p", { class: "result bad", text: d.error })); return; }
      body.appendChild(el("p", { class: "muted small-note", text: "Kept so that the learning does not propose them again. " +
        "Propose again: back in the lists above, to decide; Use again: in use at once. A value refused lost its links " +
        "and items then; the next learning proposes them again." + (reviewQ ? " Only what names \u201c" + reviewQ + "\u201d." : "") }));
      var c = d.counts || {};
      body.appendChild(refusedList("values", "Values", c.values || 0, d.values || [], q));
      body.appendChild(refusedList("links", "Links", c.links || 0, d.links || [], q));
    });
  }
  function refusedList(what, title, total, rows, q) {
    var sec = el("section", { class: "refused-list" }, [el("h3", { text: title + " \u00b7 " + S.num(total) })]);
    var list = el("div", { class: "rlist" });
    sec.appendChild(list);
    if (!total) { list.appendChild(el("p", { class: "muted", text: "None." })); return sec; }
    var shown = 0;
    var add = function (items) {
      items.forEach(function (x) { list.appendChild(what === "values" ? refusedValue(x) : refusedLink(x)); });
      shown += items.length;
      more.hidden = shown >= total;
      more.textContent = "Show more (" + S.num(total - shown) + ")";
    };
    var more = el("button", { type: "button", class: "btn small", onclick: function () {
      more.disabled = true;
      S.admin("GET", "review/refused?what=" + what + "&limit=30&offset=" + shown + q).then(function (d) {
        more.disabled = false;
        if (!d.error) add(d[what] || []);
      });
    } });
    sec.appendChild(more);
    add(rows);
    return sec;
  }
  function refusedCard(main, meta, actions) {
    var acts = el("div", { class: "ractions" }, actions);
    var c = el("div", { class: "rcard refused" }, [el("div", { class: "rbody" }, main.concat([meta ? el("div", { class: "rmeta", text: meta }) : null])), acts]);
    c._acts = acts;
    return c;
  }
  function refusedAct(label, cls, fn, doneText) {
    return el("button", { type: "button", class: "btn small" + (cls ? " " + cls : ""), text: label, onclick: function () {
      var c = this.closest(".rcard"), buttons = c.querySelectorAll("button");
      buttons.forEach(function (b) { b.disabled = true; });
      fn().then(function (r) {
        if (r && r.error) {
          buttons.forEach(function (b) { b.disabled = false; });
          var err = c.querySelector(".rerr") || c.querySelector(".rbody").appendChild(el("div", { class: "rerr result bad" }));
          err.textContent = r.error;
          return;
        }
        c.classList.add("done");
        c._acts.innerHTML = "";
        c._acts.appendChild(el("span", { class: "rdone", text: doneText }));
        saved();
        D.reviewWaiting();                                // a value proposed again waits again: the badge follows
      });
    } });
  }
  function refusedValue(f) {
    var by = [f.by ? "refused by " + f.by : "", S.when(f.at), f.source ? { seed: "from the start", data: "from the data", llm: "by the LLM", admin: "by an admin", docs: "from the documents" }[f.source] || f.source : ""].filter(Boolean).join(" \u00b7 ");
    var main = [el("div", { class: "rtext" }, [el("strong", { text: f.value }), el("span", { class: "muted", text: " (" + (FACET_NAMES[f.facet] || f.facet) + ")" })]),
      f.description ? el("div", { class: "muted", text: f.description }) : null,
      (f.origins || []).length ? el("div", { class: "muted small-note", text: "from: " + f.origins.join("; ") }) : null].filter(Boolean);
    if (f.in_use) {
      main.push(el("div", { class: "muted", text: "\u201c" + f.in_use.value + "\u201d is in use with this name: nothing to add again." }));
      return refusedCard(main, by, []);
    }
    return refusedCard(main, by, [
      refusedAct("Propose again", "", function () { return S.admin("POST", "facets/" + f.id, { status: "proposed" }); }, "proposed again (above)"),
      refusedAct("Use again", "primary", function () { return S.admin("POST", "facets/" + f.id, { status: "approved" }); }, "in use again")]);
  }
  function refusedLink(x) {
    var dir = x.both ? " \u2194 " : " \u2192 ";
    var main = [el("div", { class: "rtext" }, [el("strong", { text: x.a.value }), el("span", { text: dir }), el("strong", { text: x.b.value }),
                                              el("span", { class: "muted", text: ": " + x.label })]),
      x.detail ? el("div", { class: "muted small-note", text: x.detail }) : null,
      x.evidence ? el("div", { class: "muted small-note", text: "read in: " + x.evidence }) : null].filter(Boolean);
    var meta = [x.by ? "refused by " + x.by : "", x.source ? { llm: "by the LLM", data: "from the data", admin: "by an admin", docs: "from the documents" }[x.source] || x.source : ""].filter(Boolean).join(" \u00b7 ");
    if (x.why_not) {
      main.push(el("div", { class: "muted", text: "Not added again: " + x.why_not + "." }));
      return refusedCard(main, meta, []);
    }
    return refusedCard(main, meta, [
      refusedAct("Propose again", "", function () { return S.admin("POST", "links/" + x.id, { status: "proposed" }); }, "proposed again (above)"),
      refusedAct("Use again", "primary", function () { return S.admin("POST", "links/" + x.id, { status: "approved" }); }, "in use again")]);
  }

  // ------------------------------------------------------------------ Catalog
  var cat = { entries: [], classifications: {}, current: null, loaded: false };
  function catLoad(keep) {
    if (!admin) {
      return S.dict("GET", "knowledge").then(function (d) {
        cat.entries = (d.entries || []).map(function (e, i) {
          return { id: e.id || -1 - i, title: e.title, classification: e.classification, category: e.category, enabled: true,
                   updated_at: e.updated_at, updated_by: e.by, content: e.content, agent: e.by === "agent" };
        });
        catFilters(Object.keys(cat.entries.reduce(function (o, e) { o[e.classification] = 1; return o; }, {})),
                   Object.keys(cat.entries.reduce(function (o, e) { if (e.category) o[e.category] = 1; return o; }, {})));
        catRender();
      });
    }
    return S.admin("GET", "entries").then(function (d) {
      cat.entries = d.entries || [];
      cat.classifications = d.classifications || {};
      var ec = $("e-class"), dl = $("e-categories"), ve = ec.value;
      if (!ec.options.length) {          // built once: rebuilding it would reset an open editor's classification
        Object.keys(cat.classifications).forEach(function (k) { ec.appendChild(el("option", { value: k, text: k })); });
      } else if (ve) {
        ec.value = ve;
      }
      dl.innerHTML = "";
      (d.categories || []).forEach(function (c) { dl.appendChild(el("option", { value: c })); });
      catFilters(Object.keys(cat.classifications), d.categories || []);
      var w = $("cat-warnings");
      w.innerHTML = "";
      (d.errors || []).forEach(function (e) { w.appendChild(el("div", { class: "warn", text: "Skipped (invalid): “" + e.entry + "” — " + e.error })); });
      (d.conflicts || []).forEach(function (c) { w.appendChild(el("div", { class: "warn", text: "Defined twice: " + c.kind + " " + c.name + " in “" + c.entries.join("” and “") + "”; the most recent change is used (“" + c.kept + "”)" })); });
      catRender();
      if (keep && cat.current) { var e = cat.entries.filter(function (x) { return x.id === cat.current.id; })[0]; if (e) catOpen(e); }
    });
  }
  function catFilters(classes, categories) {
    var sc = $("cat-class"), sg = $("cat-category"), vc = sc.value, vg = sg.value;
    sc.innerHTML = '<option value="">All classifications</option>';
    classes.forEach(function (k) { sc.appendChild(el("option", { value: k, text: k })); });
    sg.innerHTML = '<option value="">All categories</option>';
    categories.forEach(function (c) { sg.appendChild(el("option", { value: c, text: c })); });
    sc.value = vc; sg.value = vg;
  }
  function catRender() {
    var tb = $("cat-list").querySelector("tbody"), c = $("cat-class").value, g = $("cat-category").value, q = $("cat-q").value.trim().toLowerCase();
    var a = $("cat-author").value;
    tb.innerHTML = "";
    var rows = cat.entries.filter(function (e) {
      return (!c || e.classification === c) && (!g || e.category === g) &&
        (!a || (a === "agent") === !!e.agent) &&
        (!q || (e.title + " " + (e.content || "")).toLowerCase().indexOf(q) >= 0);
    });
    rows.forEach(function (e) {
      var title = el("td", { text: e.title + " " });
      if (e.agent) title.appendChild(el("span", { class: "badge agent", text: "agent", title: "Written by the agent" }));
      else if (e.origin) title.appendChild(el("span", { class: "badge", text: "learned, taken over", title: "Learned by the agent, then changed by a person: the agent no longer changes it" }));
      var open = function () { catOpen(e); };
      tb.appendChild(el("tr", { class: "link", tabindex: "0", onclick: open, onkeydown: function (ev) { if (ev.key === "Enter") open(); } }, [
        title, el("td", {}, [badge(e.classification)]),
        el("td", { text: e.category || "" }),
        el("td", {}, [e.enabled ? badge("enabled", "ok") : badge("disabled", "off")]),
        el("td", { class: "muted when", text: S.when(e.updated_at) + (e.updated_by ? " · " + e.updated_by : "") + (e.version ? " · v" + e.version : "") })
      ]));
    });
    if (!rows.length) tb.appendChild(D.emptyRow(5, cat.entries.length ? "No entry matches." : admin ? "No entry yet: add one, or import a catalog (YAML)." : "No catalog entry yet."));
  }
  function catHelp() { $("e-help").textContent = cat.classifications[$("e-class").value] || ""; }
  function evidenceText(e) {
    var v = e.evidence || {}, why;
    if (v.source === "answers") {
      why = "the same calculation in " + v.confirmed + " answer" + (v.confirmed > 1 ? "s" : "") + " confirmed as helpful (used " +
        v.uses + " time" + (v.uses > 1 ? "s" : "") + ")" + (v.database ? ", on database " + v.database : "") +
        (v.messages && v.messages.length ? "; answers #" + v.messages.slice(-5).join(", #") : "");
    } else if (v.source === "team memory") {
      why = "a team " + (e.classification === "rule" ? "rule" : "fact") + " approved by " + (v.approved_by || "an admin");
    } else if (v.source === "document") {
      why = v.terms + " definition" + (v.terms > 1 ? "s" : "") + " quoted word for word from “" + (v.title || v.url || "a document") + "”";
    } else {
      why = "its evidence";
    }
    return (e.agent ? "Written by the agent from " + why + ". Edit and save it to take it over (the agent will not change it any more); delete it and the agent will not write it again."
                    : "Learned by the agent from " + why + ", then changed by " + (e.updated_by || "a person") + ": the agent no longer changes it.");
  }
  function catOpen(e) {
    if (!admin) {
      D.textDrawer(e.title, e.classification + (e.category ? " · " + e.category : "") + " · by " + (e.updated_by || "?"), e.content);
      return;
    }
    cat.current = e;
    $("entry-title-h").textContent = e ? e.title : "New entry";
    $("e-title").value = e ? e.title : "";
    $("e-class").value = e ? e.classification : "rule";
    $("e-category").value = e ? (e.category || "") : "";
    $("e-fmt").value = e ? (e.fmt || "yaml") : "text";
    $("e-enabled").checked = e ? e.enabled : true;
    $("e-content").value = e ? (e.content || "") : "";
    $("e-result").textContent = ""; $("e-result").className = "result";
    $("e-delete").hidden = !e || !canDelete;
    $("e-history-box").hidden = !e; $("e-history").innerHTML = ""; $("e-history-box").open = false;
    $("e-evidence").hidden = !(e && e.origin);
    $("e-evidence").textContent = e && e.origin ? evidenceText(e) : "";
    catHelp();
    $("entry-drawer").hidden = false;
    $("e-title").focus();
  }
  function catHistory() {
    if (!cat.current) return;
    S.admin("GET", "entries/" + cat.current.id + "/history").then(function (d) {
      var box = $("e-history"); box.innerHTML = "";
      (d.versions || []).forEach(function (v) {
        var pre = el("pre", { text: v.content, hidden: true });
        box.appendChild(el("div", { class: "version" }, [
          el("div", {}, [el("strong", { text: "v" + v.version }), document.createTextNode(" · " + S.when(v.changed_at) + " · " + (v.changed_by || "") + (v.deleted ? " · deleted" : "") + (v.enabled === false ? " · disabled" : "") + " "),
            el("button", { type: "button", class: "linkish", text: "view", onclick: function () { pre.hidden = !pre.hidden; } }),
            v.deleted || v.version === cat.current.version ? null : el("button", { type: "button", class: "linkish", text: "restore this version", onclick: function () {
              S.admin("POST", "entries/" + cat.current.id + "/restore", { version: v.version }).then(function (r) {
                if (r.error) { $("e-result").textContent = r.error; $("e-result").className = "result bad"; return; }
                cat.current = r.entry; saved(); catLoad(true);
              });
            } })]), pre]));
      });
    });
  }
  D.openEntry = function (id) {
    var find = function () { return cat.entries.filter(function (x) { return x.id === id; })[0]; };
    var e = find();
    if (e) { catOpen(e); return; }
    catLoad(false).then(function () { var x = find(); if (x) catOpen(x); });
  };

  if (admin) {
    $("cat-export").href = document.body.dataset.adminApi + "catalog/export";
    $("e-history-box").addEventListener("toggle", function () { if ($("e-history-box").open) catHistory(); });
    $("e-class").addEventListener("change", function () {
      catHelp();
      if (!cat.current) $("e-fmt").value = ["rule", "guide", "formula"].indexOf($("e-class").value) >= 0 ? "text" : "yaml";
    });
    $("e-save").addEventListener("click", function () {
      var body = { title: $("e-title").value, classification: $("e-class").value, category: $("e-category").value,
                   fmt: $("e-fmt").value, enabled: $("e-enabled").checked, content: $("e-content").value };
      if (cat.current) body.version = cat.current.version;
      var res = $("e-result"), btn = $("e-save");
      btn.disabled = true;
      res.textContent = "saving…"; res.className = "result";
      S.admin(cat.current ? "PUT" : "POST", cat.current ? "entries/" + cat.current.id : "entries", body).then(function (r) {
        btn.disabled = false;
        if (r.error) { res.textContent = r.error; res.className = "result bad"; return; }
        cat.current = r.entry;
        res.textContent = "saved (v" + r.entry.version + ")" + (r.applied && r.applied.curated ? ", applied to " + r.applied.curated + " objects" : "");
        res.className = "result good";
        $("entry-title-h").textContent = r.entry.title; $("e-delete").hidden = !canDelete; $("e-history-box").hidden = false;
        saved();
        catLoad(false);
      });
    });
    $("e-delete").addEventListener("click", function () {
      if (!cat.current) return;
      S.confirm($("e-delete"), "Delete \u201c" + cat.current.title + "\u201d?", { detail: "The agent no longer uses it. " +
          "It can be restored from its history (Export YAML keeps a copy too)." }).then(function (ok) {
        if (!ok) return;
        S.admin("DELETE", "entries/" + cat.current.id + "?version=" + cat.current.version).then(function (r) {
          if (r.error) { $("e-result").textContent = r.error; $("e-result").className = "result bad"; return; }
          $("entry-drawer").hidden = true; cat.current = null; saved(); catLoad(false);
        });
      });
    });
    $("entry-close").addEventListener("click", function () { $("entry-drawer").hidden = true; });
    $("cat-new").addEventListener("click", function () { catOpen(null); });
    $("cat-import").addEventListener("click", function () { $("import-result").textContent = ""; $("import-drawer").hidden = false; });
    $("import-close").addEventListener("click", function () { $("import-drawer").hidden = true; });
    $("import-go").addEventListener("click", function () {
      var res = $("import-result"), btn = $("import-go");
      btn.disabled = true;
      res.textContent = "importing…"; res.className = "result";
      S.admin("POST", "catalog", { content: $("import-text").value, mode: $("import-replace").checked ? "replace" : "merge" }).then(function (r) {
        btn.disabled = false;
        if (r.error) { res.textContent = r.error; res.className = "result bad"; return; }
        var i = r.imported || {};
        res.textContent = "added " + (i.added || 0) + ", updated " + (i.updated || 0) + ", unchanged " + (i.unchanged || 0) +
                          (i.deleted ? ", deleted " + i.deleted : "") + " entries";
        res.className = "result good";
        saved();
        catLoad(false);
      });
    });
  }
  ["cat-class", "cat-category", "cat-author"].forEach(function (id) { $(id).addEventListener("change", catRender); });
  $("cat-q").addEventListener("input", catRender);

  // ------------------------------------------------------------------ Team memory
  var memRows = [];
  function memRender() {
    var tb = $("team-memory").querySelector("tbody"), st = $("mem-status").value, q = $("mem-q").value.trim().toLowerCase();
    tb.innerHTML = "";
    var rows = memRows.filter(function (m) { return (!st || m.status === st) && (!q || (m.text + " " + (m.category || "")).toLowerCase().indexOf(q) >= 0); });
    rows.forEach(function (m) {
      var text = el("td", { text: m.text });
      var acts = el("td", { class: "row-actions" });
      if (admin) {
        var post = function (body) { return S.admin("POST", "memory/" + m.id, body).then(function (r) { if (!r.error) saved(); memLoad(); }); };
        if (m.status === "catalog" && m.entry_id) {          // a catalog entry replaced it: edited there
          acts.appendChild(el("button", { type: "button", class: "linkish", text: "Edit it in the catalog",
            title: "Open its catalog entry", onclick: function () { D.openEntry(m.entry_id); } }));
        } else {
          if (m.status !== "active") acts.appendChild(el("button", { type: "button", class: "linkish", text: "Approve", onclick: function () { post({ status: "active" }); } }));
          if (m.status !== "disabled") acts.appendChild(el("button", { type: "button", class: "linkish", text: "Disable", onclick: function () { post({ status: "disabled" }); } }));
          acts.appendChild(el("button", { type: "button", class: "linkish", text: "Edit", onclick: function () {
            if (text.querySelector("textarea")) return;
            var ta = el("textarea", { rows: "2", "aria-label": "Memory" }); ta.value = m.text;
            text.innerHTML = ""; text.appendChild(ta);
            text.appendChild(el("div", { class: "actions" }, [el("button", { type: "button", class: "btn small primary", text: "Save", onclick: function () { post({ text: ta.value }); } }),
              el("button", { type: "button", class: "btn small", text: "Cancel", onclick: memRender })]));
            ta.focus();
          } }));
          if (canDelete) acts.appendChild(sureButton("Delete", function () { S.chat("DELETE", "memory/" + m.id).then(function (r) { if (!r.error) saved(); memLoad(); }); },
            "Delete this team memory?", "It is gone for good and the agent no longer uses it. Disable keeps it without using it."));
        }
      }
      tb.appendChild(el("tr", {}, [text, el("td", { text: m.kind + (m.category ? ", " + m.category : "") }),
        el("td", { text: (m.by || "") + (m.source === "chat" ? " (from a chat)" : "") }),
        el("td", {}, [badge(m.status === "catalog" ? "in the catalog" : m.status === "active" ? "used" : m.status,
                            m.status === "active" ? "ok" : m.status === "disabled" ? "off" : m.status === "catalog" ? "agent" : "warn")]),
        acts]));
    });
    if (!rows.length) tb.appendChild(D.emptyRow(5, memRows.length ? "No memory matches." : "No team memory yet."));
  }
  function memLoad() {
    if (!admin) {
      return S.dict("GET", "knowledge").then(function (d) {
        memRows = (d.team_memory || []).map(function (m) { return { text: m.text, kind: m.kind, category: m.category, status: "active", created_at: m.created_at }; });
        memRender();
      });
    }
    return S.admin("GET", "memory").then(function (d) { memRows = d.memory || []; memRender(); });
  }
  $("mem-status").addEventListener("change", memRender);
  $("mem-q").addEventListener("input", memRender);
  if (admin) {
    $("mem-add").addEventListener("click", function () {
      var res = $("mem-result"), btn = $("mem-add");
      if (!$("mem-text").value.trim()) { res.textContent = "write the memory first"; res.className = "result bad"; return; }
      btn.disabled = true;
      S.chat("POST", "memory", { text: $("mem-text").value, scope: "team", kind: $("mem-kind").value, category: $("mem-category").value }).then(function (r) {
        btn.disabled = false;
        result(res, r, "added for the team");
        if (!r.error) { $("mem-text").value = ""; saved(); memLoad(); }
      });
    });
  }

  // ------------------------------------------------------------------ Documents and sites
  /* (0.10.12) a document's number of pages: a wiki of thousands is sent with its number, not its list */
  function pageCount(x) { return x.page_count !== undefined && x.page_count !== null ? x.page_count : (x.pages || []).length; }
  var READS = { web: "web page or site", confluence: "Confluence wiki", bitbucket: "Bitbucket repository", upload: "uploaded file" };
  var SIGNIN = { bearer: "token (Bearer)", basic: "user and password or token", header: "token in a header" };
  function inSearch(x) {
    if (x.pieces) return S.num(x.pieces) + " piece" + (x.pieces === 1 ? "" : "s");
    return x.status === "ok" ? "not yet" : "";
  }
  /* the sign-in fields: shown for the kind chosen (a user for basic, a header's name for header) */
  function signInFields(box, auth) {
    auth = auth || {};
    var type = el("select", { "aria-label": "Sign-in" }, [["", "None (a public site)"], ["bearer", "Token (Bearer)"],
      ["basic", "User and password or app token (Basic)"], ["header", "Token in a header of its own"]].map(function (o) {
        return el("option", { value: o[0], text: o[1], selected: (auth.type || "") === o[0] ? "selected" : null }); }));
    var user = el("input", { type: "text", "aria-label": "User", placeholder: "user", autocomplete: "off" });
    user.value = auth.user || "";
    var header = el("input", { type: "text", "aria-label": "Header name", placeholder: "header, e.g. Private-Token", autocomplete: "off" });
    header.value = auth.header || "";
    var secret = el("input", { type: "password", "aria-label": "Token or password", autocomplete: "new-password",
      placeholder: auth.secret_set ? "set: leave empty to keep it" : "token or password" });
    var sync = function () {
      user.hidden = type.value !== "basic";
      header.hidden = type.value !== "header";
      secret.hidden = !type.value;
    };
    type.addEventListener("change", sync);
    sync();
    [type, user, header, secret].forEach(function (x) { box.appendChild(x); });
    return function () {
      var out = { auth: { type: type.value, user: user.value, header: header.value } };
      if (secret.value) out.secret = secret.value;
      return out;
    };
  }
  function docEditor(x, row) {
    var cell = el("td", { colspan: "8" }), rowEd = el("tr", { class: "editing" }, [cell]);
    var cat = el("input", { type: "text", "aria-label": "Category", placeholder: "category" }); cat.value = x.category || "";
    var pages = el("input", { type: "number", min: "1", max: "50000", "aria-label": "Pages or files at most" }); pages.value = x.max_pages || 1;
    var days = el("input", { type: "number", min: "1", "aria-label": "Read again every (days)" }); days.value = x.refresh_days || 7;
    var reader = el("select", { "aria-label": "Read as" }, [["", "detected (" + (READS[x.reads_as] || x.reads_as) + ")"],
      ["web", READS.web], ["confluence", READS.confluence], ["bitbucket", READS.bitbucket]].map(function (o) {
        return el("option", { value: o[0], text: o[1], selected: (x.reader || "") === o[0] ? "selected" : null }); }));
    var auth = el("span", { class: "signin" });
    var signIn = x.kind === "url" ? signInFields(auth, x.auth) : null;
    var a0 = x.auth || {};
    var tls = el("select", { "aria-label": "The site's certificate" }, [["", "certificate: as in Settings"], ["yes", "certificate checked"],
      ["no", "certificate not checked"]].map(function (o) {
        var cur = a0.verify_tls === true ? "yes" : a0.verify_tls === false ? "no" : "";
        return el("option", { value: o[0], text: o[1], selected: cur === o[0] ? "selected" : null }); }));
    var ca = el("input", { type: "text", "aria-label": "CA file on the server", placeholder: "CA file on the server (optional)", autocomplete: "off" });
    ca.value = a0.ca_bundle || "";
    var files = el("select", { "aria-label": "A repository: read" }, [["docs", "repository: documentation and text files"],
      ["code", "repository: all the code too (secrets masked)"]].map(function (o) {
        return el("option", { value: o[0], text: o[1], selected: (a0.files || "code") === o[0] ? "selected" : null }); }));
    files.hidden = !(x.reads_as === "bitbucket" || x.reader === "bitbucket");
    reader.addEventListener("change", function () { files.hidden = !(reader.value === "bitbucket" || (!reader.value && x.reads_as === "bitbucket")); });
    var res = el("span", { class: "result" });
    var save = el("button", { type: "button", class: "btn small primary", text: "Save", onclick: function () {
      var body = { category: cat.value };
      if (x.kind === "url") {
        body.max_pages = +pages.value; body.refresh_days = +days.value; body.reader = reader.value;
        Object.assign(body, signIn());
        body.verify_tls = tls.value === "" ? null : tls.value === "yes";
        body.ca_bundle = ca.value; body.files = files.value;
      }
      save.disabled = true;
      S.admin("POST", "docs/" + x.id, body).then(function (r) {
        save.disabled = false;
        result(res, r, x.kind === "url" ? "saved: reading it again" : "saved");
        if (!r.error) { saved(); setTimeout(docsLoad, x.kind === "url" ? 2500 : 300); }
      });
    } });
    cell.appendChild(el("div", { class: "doc-edit" }, [
      el("div", { class: "nm muted", text: x.url || x.title || "" }),
      el("div", { class: "filters" }, x.kind === "url" ? [cat, el("label", { class: "inline" }, ["Pages ", pages]),
        el("label", { class: "inline" }, ["Every ", days, " days"]), reader] : [cat]),
      x.kind === "url" ? el("div", { class: "filters" }, [el("span", { class: "muted", text: "Sign-in:" }), auth]) : null,
      x.kind === "url" ? el("div", { class: "filters" }, [tls, ca, files]) : null,
      x.kind === "url" ? el("p", { class: "muted small-note", text: "The token is kept encrypted and sent only to this site; " +
        "what it reads becomes searchable by everyone who can open the Data dictionary." }) : null,
      el("div", { class: "actions" }, [save, el("button", { type: "button", class: "btn small", text: "Cancel",
        onclick: function () { rowEd.replaceWith(row); } }), res])]));
    row.replaceWith(rowEd);
  }
  /* (0.10.7) the pages of a document, under its row: each page read (its title, address, size, links), the pages
     not read and why, and the limit reached with pages left unread */
  var PAGE_ROWS = 500;                              /* (0.11.0) rows drawn at a time: 50,000 at once froze the page */
  function docPages(x, row, btn) {
    var open = row.nextSibling && row.nextSibling.className === "doc-pages" ? row.nextSibling : null;
    if (open) { open.remove(); btn.textContent = "Pages"; return; }
    var cell = el("td", { colspan: "8" }, [el("div", { class: "muted", text: "Reading the list of pages…" })]);
    var box = el("tr", { class: "doc-pages" }, [cell]);
    row.after(box); btn.textContent = "Hide pages";
    var shown = null;                               /* (0.10.9.2) the list as last shown */
    var view = null;                                /* (0.11.0) the rows drawn: a removal takes only its rows away */
    var read = function () { return S.admin("GET", "docs/" + x.id + "/pages").then(render); };
    /* (0.10.9.1) a page removed by an admin: not read again, its text, its search pieces and what was learned from
       it deleted at once; given back from the list of the removed pages */
    var removeBtn = function (p, tr) {
      var b = el("button", { type: "button", class: "linkish", text: "Remove", title: "Not read again; its text, its search pieces and what was learned from it deleted" });
      b.addEventListener("click", function () {
        var td = b.parentNode, res = el("span", { class: "result", role: "status" });
        var yes = el("button", { type: "button", class: "btn small danger", text: "Remove it" });
        var no = el("button", { type: "button", class: "btn small", text: "Cancel" });
        td.innerHTML = "";
        td.appendChild(el("div", { class: "doc-page-confirm" }, [el("span", { text: "Remove this page from the document? " }), yes, no, res]));
        no.addEventListener("click", function () { td.innerHTML = ""; td.appendChild(removeBtn(p, tr)); });
        yes.addEventListener("click", function () {
          yes.disabled = no.disabled = true;
          S.admin("POST", "docs/" + x.id + "/pages/remove", { page_id: p.page_id || "", path: p.path || "", url: p.url || "" }).then(function (r) {
            if (!r || r.error) { res.textContent = (r && r.error) || "not removed"; res.className = "result bad"; yes.disabled = no.disabled = false; return; }
            /* (0.10.9.2) the list changed in place (never read again from the server, the place kept); (0.11.0) its row
               only: the list is not drawn again (50,000 pages took seconds at each removal) */
            if (view) view.drop([p], [{ key: r.removed, title: r.title || p.title || "", url: p.url || "" }]);
            else read();
          });
        });
      });
      return b;
    };
    /* (0.10.11.1) several pages removed at once: a filter (title, address, space), "all shown", Remove picked;
       (0.11.0) "all shown" picks the rows drawn: the first ones that match (Show more draws the next ones) */
    var bulkBar = function (v) {
      var filter = el("input", { type: "search", placeholder: "Filter the pages (title, address, space)", "aria-label": "Filter the pages" });
      var all = el("input", { type: "checkbox", "aria-label": "Pick every page shown" });
      var go = el("button", { type: "button", class: "btn small danger", text: "Remove picked pages" });
      var res = el("span", { class: "result", role: "status" });
      var bar = el("div", { class: "doc-pages-bulk" }, [el("label", {}, [all, document.createTextNode(" all shown ")]), filter, go, res]);
      var picked = function () { return v.rows.filter(function (r) { return r.box && r.box.checked; }); };
      var count = function () {
        var n = picked().length;
        go.disabled = !n;
        go.textContent = n ? "Remove " + S.num(n) + " picked page" + (n === 1 ? "" : "s") : "Remove picked pages";
      };
      v.count = count;                              // a row's box, made when the row is first drawn, calls it
      filter.addEventListener("input", function () {
        v.filter = filter.value.trim().toLowerCase();
        v.limit = PAGE_ROWS;
        all.checked = false;
        v.paint();
      });
      all.addEventListener("change", function () {
        v.drawn().forEach(function (r) { r.box.checked = all.checked; });
        count();
      });
      go.addEventListener("click", function () {
        var chosen = picked();
        if (!chosen.length) return;
        var yes = el("button", { type: "button", class: "btn small danger", text: "Remove " + S.num(chosen.length) });
        var no = el("button", { type: "button", class: "btn small", text: "Cancel" });
        var ask = el("span", { class: "doc-page-confirm" }, [el("span", { text: "Remove " + S.num(chosen.length) + " page" +
          (chosen.length === 1 ? "" : "s") + " from the document (not read again; their text, search pieces and what was learned from them deleted)? " }), yes, no]);
        go.replaceWith(ask);
        no.addEventListener("click", function () { ask.replaceWith(go); });
        yes.addEventListener("click", function () {
          yes.disabled = no.disabled = true;
          res.textContent = "Removing…"; res.className = "result";
          S.admin("POST", "docs/" + x.id + "/pages/remove", { pages: chosen.map(function (r) {
            return { page_id: r.p.page_id || "", path: r.p.path || "", url: r.p.url || "" }; }) }).then(function (r) {
            ask.replaceWith(go);
            if (!r || r.error || !(r.removed || []).length) {
              res.textContent = (r && r.error) || "not removed"; res.className = "result bad"; return;
            }
            res.textContent = S.num(r.removed.length) + " removed"; res.className = "result good";
            all.checked = false;
            if (view) view.drop(chosen.map(function (c) { return c.p; }), r.removed.map(function (k) {
              return { key: k.key, title: k.title || "", url: k.url || "" }; }));
            else read();
          });
        });
      });
      count();
      return bar;
    };
    function render(d) {
      cell.innerHTML = "";
      view = null;
      if (d.error) { cell.appendChild(el("div", { class: "result bad", text: d.error })); return; }
      shown = d;
      shown.pages = d.pages || [];
      shown.excluded = d.excluded || [];
      var last = d.last_reading || {}, can = !!d.can_remove;
      var head = el("div", { class: "doc-pages-head" });
      var sayHead = function () {
        var pages = shown.pages, gone = shown.excluded;
        var said = S.num(pages.length) + " page" + (pages.length === 1 ? "" : "s") + " read";
        if (last.not_read) said += " · " + S.num(last.not_read) + " not read (listed below)";
        if (gone.length) said += " · " + S.num(gone.length) + " removed";
        if (last.at) said += " · last read " + S.when(last.at);
        head.textContent = said;
      };
      sayHead();
      cell.appendChild(head);
      if (last.limit_reached) {
        cell.appendChild(el("div", { class: "result warn", text: "The limit of " + S.num(d.max_pages) + " pages was reached" +
          (last.left ? ": at least " + S.num(last.left) + " more linked page" + (last.left === 1 ? " was" : "s were") + " not read" : "") +
          ". Raise “Pages” (Edit) to read more of the site." }));
      }
      var heads = (can ? [""] : []).concat(["Page", "Space", "Size", "Links", "Images"]).concat(can ? [""] : []);
      var table = el("table", { class: "grid compact" }, [el("thead", {}, [el("tr", {}, heads.map(function (h) {
        return el("th", { text: h }); }))])]);
      var tb = el("tbody", {});
      /* (0.11.0) every page has its line in `rows` (what it is searched by); its row in the table is made when it is
         first drawn: the first PAGE_ROWS that match the filter, Show more for the next ones */
      var v = view = { filter: "", limit: PAGE_ROWS, count: function () {}, rows: shown.pages.map(function (p) {
        return { p: p, text: [p.title, p.path, p.url, p.space].filter(Boolean).join(" ").toLowerCase() };   // (0.10.11.1)
      }) };
      var make = function (r) {
        if (r.tr) return r.tr;
        var p = r.p;
        var name = p.url ? el("a", { href: p.url, target: "_blank", rel: "noopener", text: p.title || p.path || p.url }) :
          el("span", { text: p.title || p.path || "" });
        var tr = el("tr", {}, [el("td", {}, [name, p.url ? el("div", { class: "muted nm", text: p.url }) : null]),
          el("td", { text: p.space || "" }), el("td", { class: "num", text: S.bytes(p.chars || 0) }),
          el("td", { class: "num", text: p.links ? S.num(p.links) : "" }), el("td", { class: "num", text: p.images ? S.num(p.images) : "" })]);
        if (can) {
          var pick = el("input", { type: "checkbox", "aria-label": "Pick this page" });
          pick.addEventListener("change", function () { v.count(); });
          tr.insertBefore(el("td", {}, [pick]), tr.firstChild);
          tr.appendChild(el("td", { class: "row-actions" }, [removeBtn(p, tr)]));
          r.box = pick;
        }
        r.tr = tr;
        return tr;
      };
      var matching = function () {
        return v.filter ? v.rows.filter(function (r) { return r.text.indexOf(v.filter) >= 0; }) : v.rows;
      };
      var more = el("button", { type: "button", class: "btn small", hidden: "hidden",
        onclick: function () { v.limit += PAGE_ROWS; v.fill(); } });
      var none = null;
      /* the rows drawn are always the first ones that match, in order: a removal takes rows away, fill() adds the next */
      v.fill = function () {
        var list = matching(), want = Math.min(list.length, v.limit), k = 0;
        if (none) { none.remove(); none = null; }
        while (k < list.length && list[k].tr && list[k].tr.parentNode === tb) k++;
        for (var i = k; i < want; i++) tb.appendChild(make(list[i]));
        if (!list.length) tb.appendChild(none = D.emptyRow(heads.length, v.rows.length ? "No page matches." : "No page read yet."));
        more.hidden = list.length <= v.limit;
        more.textContent = "Show " + S.num(Math.min(PAGE_ROWS, list.length - v.limit)) + " more (" + S.num(Math.max(0, list.length - v.limit)) + " not shown)";
      };
      v.paint = function () { tb.innerHTML = ""; none = null; v.fill(); };     // the filter changed: drawn again
      v.drawn = function () { return v.rows.filter(function (r) { return r.tr && r.tr.parentNode === tb; }); };
      /* pages removed (one, or picked ones): their rows go, the next pages take their places, the counts follow */
      v.drop = function (ps, entries) {
        ps.forEach(function (p) { p._gone = true; });
        shown.pages = shown.pages.filter(function (q) { return !q._gone; });
        v.rows = v.rows.filter(function (r) {
          if (!r.p._gone) return true;
          if (r.tr) r.tr.remove();
          return false;
        });
        var at = new Date().toISOString();
        entries.forEach(function (k) { shown.excluded.push({ key: k.key, title: k.title, url: k.url, by: "you", at: at }); });
        v.fill();
        sayHead();
        sayGone();
        v.count();
      };
      if (can && v.rows.length) cell.appendChild(bulkBar(v));
      table.appendChild(tb);
      cell.appendChild(el("div", { class: "table-wrap" }, [table]));
      cell.appendChild(more);
      v.fill();
      var goneBox = el("div", { class: "doc-pages-gone" });
      var sayGone = function () {
        var gone = shown.excluded;
        goneBox.innerHTML = "";
        if (!gone.length) return;
        goneBox.appendChild(el("div", { class: "doc-pages-head", text: "Removed (not read again)" }));
        goneBox.appendChild(el("p", { class: "muted small-note", text: "Their text, their search pieces and what was learned from them " +
          "were deleted; what the System map was proposed from them is withdrawn at the next learning (a link already approved " +
          "is only proposed for removal)." }));
        var rt = el("tbody", {});
        gone.slice().reverse().forEach(function (k) {
          var back = el("button", { type: "button", class: "linkish", text: "Read again", title: "Read at the document's next reading (Read again on its row: now)" });
          back.addEventListener("click", function () {
            back.disabled = true;
            S.admin("POST", "docs/" + x.id + "/pages/restore", { key: k.key }).then(function (r) {
              if (!r || r.error) { back.disabled = false; back.textContent = (r && r.error) || "not given back"; return; }
              read();
            });
          });
          rt.appendChild(el("tr", {}, [el("td", {}, [el("div", { text: k.title || k.url || k.key }),
            k.url ? el("div", { class: "muted nm", text: k.url }) : null]),
            el("td", { class: "muted", text: [k.by, k.at ? S.when(k.at) : ""].filter(Boolean).join(" · ") }),
            el("td", { class: "row-actions" }, [back])]));
        });
        goneBox.appendChild(el("div", { class: "table-wrap" }, [el("table", { class: "grid compact" }, [el("thead", {}, [el("tr", {}, [
          el("th", { text: "Page" }), el("th", { text: "Removed" }), el("th", { text: "" })])]), rt])]));
      };
      sayGone();
      cell.appendChild(goneBox);
      if ((last.skipped || []).length) {
        cell.appendChild(el("div", { class: "doc-pages-head", text: "Not read" }));
        var nt = el("tbody", {});
        last.skipped.forEach(function (k) {
          nt.appendChild(el("tr", {}, [el("td", {}, [el("div", { text: k.title || k.url || "" }),
            k.title && k.url ? el("div", { class: "muted nm", text: k.url }) : null]), el("td", { class: "muted", text: k.why || "" })]));
        });
        cell.appendChild(el("div", { class: "table-wrap" }, [el("table", { class: "grid compact" }, [el("thead", {}, [el("tr", {}, [
          el("th", { text: "Page" }), el("th", { text: "Why" })])]), nt])]));
      }
    }
    read();
  }
  function docsLoad() {
    var tb = $("docs").querySelector("tbody");
    if (!admin) {
      return S.dict("GET", "knowledge").then(function (d) {
        tb.innerHTML = "";
        (d.docs || []).forEach(function (x) {
          tb.appendChild(D.row(function () {
            D.textDrawer(x.title, (x.url || "uploaded file") + (x.category ? " · " + x.category : ""),
              x.excerpt + (x.chars > (x.excerpt || "").length ? "\n… (" + S.num(x.chars) + " characters in all)" : ""));
          }, [el("td", {}, [el("div", { text: x.title || x.url || "document" }), x.url ? el("div", { class: "muted nm", text: x.url }) : null]),
              el("td", { text: x.category || "" }), el("td", { class: "num", text: S.num(x.pages || (x.kind === "url" ? 0 : 1)) }),
              el("td", { class: "num", text: S.bytes(x.chars) }), el("td", { class: "num", text: inSearch(x) }),
              el("td", {}, [badge(x.status || "", x.status === "ok" ? "ok" : x.status === "error" ? "bad" : "")]),
              el("td", { class: "muted", text: S.when(x.fetched_at) }), el("td", {})]));
        });
        if (!(d.docs || []).length) tb.appendChild(D.emptyRow(8, "No document or site yet."));
      });
    }
    return S.admin("GET", "docs").then(function (d) {
      tb.innerHTML = "";
      (d.docs || []).forEach(function (x) {
        var acts = el("td", { class: "row-actions" });
        var row = el("tr", {});
        if (x.kind === "url") acts.appendChild(el("button", { type: "button", class: "linkish", text: "Read again", onclick: function () {
          this.disabled = true;
          S.admin("POST", "docs/" + x.id + "/refresh", {}).then(function () { setTimeout(docsLoad, 3000); });
        } }));
        if (x.kind === "url") acts.appendChild(el("button", { type: "button", class: "linkish doc-pages-btn", text: "Pages",
          title: "Every page read, with its details, and the pages not read and why", "aria-label": "Pages read: details",
          onclick: function () { docPages(x, row, this); } }));
        acts.appendChild(el("button", { type: "button", class: "linkish", text: "Edit", title: "Category, pages, how it is read, its sign-in",
          onclick: function () { docEditor(x, row); } }));
        if (canDelete) {
          var gone = el("span", { class: "result", role: "status" });   // (0.11.8.3) said while it runs, and why it did not
          acts.appendChild(sureButton("Delete", function (b) {
            b.disabled = true; gone.textContent = "Deleting…"; gone.className = "result";
            S.admin("DELETE", "docs/" + x.id).then(function (r) {
              if (r.error) { b.disabled = false; gone.textContent = "Not deleted: " + r.error; gone.className = "result bad"; return; }
              saved(); docsLoad(); }); },
            "Delete “" + (x.title || x.url || "this document") + "”?",
            (pageCount(x) > 1 ? "Its " + S.num(pageCount(x)) + " pages leave" : "It leaves") + " the agent's search" +
            (x.kind === "url" ? (x.auth && x.auth.type ? ", and its saved sign-in is deleted" : "") + "; the site can be added again." :
              "; upload it again to get it back.")));
          acts.appendChild(gone);
        }
        var how = x.kind === "url" ? (READS[x.reads_as] || x.reads_as) + (x.auth && x.auth.type ? " · signed in with a " +
          (SIGNIN[x.auth.type] || x.auth.type) + (x.auth.user ? " (" + x.auth.user + ")" : "") : "") +
          (x.auth && x.auth.verify_tls === false ? " · certificate not checked" : x.auth && x.auth.ca_bundle ? " · CA file " + x.auth.ca_bundle : "") +
          (x.reads_as === "bitbucket" && x.auth && x.auth.files === "code" ? " · all the code" : "") : READS.upload;
        [el("td", {}, [el("div", { text: x.title || x.url || "document" }),
            x.url ? el("div", { class: "muted nm", text: x.url }) : null, el("div", { class: "muted small-note", text: how })]),
          el("td", { text: x.category || "" }), el("td", { class: "num", text: S.num(pageCount(x) || (x.kind === "upload" ? 1 : 0)) }),
          el("td", { class: "num", text: S.bytes(x.chars) }), el("td", { class: "num", text: inSearch(x) }),
          el("td", {}, [badge(x.status || "", x.status === "ok" ? "ok" : x.status === "error" ? "bad" : ""), x.error ? el("div", { class: "muted", text: x.error }) : null,
            x.read && x.read.limit_reached ? el("div", { class: "muted", text: "limit of " + S.num(x.max_pages) + " pages reached" +
              (x.read.left ? " (" + S.num(x.read.left) + "+ not read)" : "") }) : null,
            x.read && x.read.not_read ? el("div", { class: "muted", text: S.num(x.read.not_read) + " page" + (x.read.not_read === 1 ? "" : "s") + " not read: see Pages" }) : null]),
          el("td", { class: "muted", text: x.fetched_at ? S.when(x.fetched_at) : "" }), acts].forEach(function (c) { row.appendChild(c); });
        tb.appendChild(row);
      });
      if (!(d.docs || []).length) tb.appendChild(D.emptyRow(8, "No document yet."));
    });
  }
  // ------------------------------------------------------------------ (0.10.10) Dashboards and visualizations
  /* The dashboards of Grafana and OpenSearch Dashboards with their panels or visualizations, and which of them the
     agent reads: each one switched on or off (an admin's), all off then the needed ones on, the last modified date to
     choose from. A switch saves at once; the pages of a dashboard switched off leave the Context and the search. */
  var DASH = { source: null, q: "", kind: "dashboard", state: "", sort: "updated", rows: [], total: 0, sources: [],
               can: false, poll: null, qTimer: null, seq: 0 };
  var DASH_PAGE = 200;
  var KID_NAMES = { grafana: ["panel", "panels"], osd: ["visualization", "visualizations"] };
  function dashSource() { return DASH.sources.filter(function (x) { return x.source === DASH.source; })[0]; }
  function dashKid(n) { var k = KID_NAMES[DASH.source] || ["item", "items"]; return n === 1 ? k[0] : k[1]; }
  function dashLoad() {
    var box = $("dash");
    if (!box) return null;
    return S.admin("GET", "dashlist").then(function (d) {
      if (!d || d.error) { box.innerHTML = ""; box.appendChild(el("div", { class: "result bad", text: (d && d.error) || "not read" })); return; }
      DASH.can = !!d.can_change;
      DASH.sources = d.sources || [];
      var known = DASH.sources.filter(function (x) { return x.source === DASH.source; }).length;
      if (!known) {
        var set = DASH.sources.filter(function (x) { return x.configured || x.dashboards; });
        DASH.source = (set[0] || DASH.sources[0] || {}).source || null;
      }
      dashRender();
    });
  }
  function dashPollJob() {
    clearTimeout(DASH.poll);
    DASH.poll = setTimeout(function () {
      S.admin("GET", "dashlist").then(function (d) {
        if (!d || d.error) return;
        DASH.sources = d.sources || DASH.sources;
        var s = dashSource();
        if (s && s.job && s.job.running) { dashHead(); dashPollJob(); } else { dashRender(); }
      });
    }, 3000);
  }
  function dashRender() {
    var box = $("dash");
    box.innerHTML = "";
    if (!DASH.sources.length) return;
    box.appendChild(el("div", { class: "dash-tabs", role: "tablist", "aria-label": "Source" }, DASH.sources.map(function (x) {
      var on = x.source === DASH.source;
      return el("button", { type: "button", role: "tab", class: "btn small" + (on ? " on" : ""), "aria-selected": on ? "true" : "false",
        text: x.name + (x.dashboards ? " · " + S.num(x.dashboards_read) + " of " + S.num(x.dashboards) + " read" : ""),
        onclick: function () { if (on) return; DASH.source = x.source; DASH.q = ""; DASH.kind = "dashboard"; DASH.state = ""; dashRender(); } });
    })));
    box.appendChild(el("div", { id: "dash-head", class: "dash-head" }));
    box.appendChild(el("div", { id: "dash-body" }));
    dashHead();
    dashBody();
  }
  function dashHead() {
    var head = $("dash-head"), s = dashSource();
    if (!head || !s) return;
    head.innerHTML = "";
    var job = s.job || {};
    var said = [];
    if (s.url) said.push(s.url);
    said.push(s.listed_at ? "listed " + S.when(s.listed_at) : "not listed yet");
    if (s.dashboards) said.push(S.num(s.dashboards_read) + " of " + S.num(s.dashboards) + " dashboards read · " + S.num(s.kids_read) + " of " + S.num(s.kids) + " " + s.kid + " read");
    if (s.gone) said.push(S.num(s.gone) + " gone from " + s.name);
    head.appendChild(el("div", { class: "muted", text: said.join(" · ") }));
    if (!s.configured) {
      head.appendChild(el("div", { class: "result warn", text: s.name + " is not set up: " + (s.source === "grafana" ?
        "grafana.mcp_url (its MCP server)" : "osd.url and its sign-in (osd.auth, osd.user, osd.secret)") + " in Settings." }));
    }
    if (job.running) {
      head.appendChild(el("div", { class: "result", role: "status", text: (job.what === "list" ? "Listing" : "Writing the pages") + " since " + S.when(job.started) + "…" }));
    } else if (job.error) {
      head.appendChild(el("div", { class: "result bad", text: "Last " + (job.what === "list" ? "listing" : "writing") + ": " + job.error }));
    }
    if (!DASH.can) return;
    var res = el("span", { class: "result", role: "status" });
    var listNow = el("button", { type: "button", class: "btn small", text: "List now", disabled: !s.configured || job.running ? "disabled" : null,
      title: "Read the list again from " + s.name + " (no AI, no page written)",
      onclick: function () {
        listNow.disabled = true;
        S.admin("POST", "dashlist/" + s.source + "/list", {}).then(function (r) {
          result(res, r, "listing…");
          if (!r.error) { s.job = { running: true, what: "list", started: new Date().toISOString() }; dashHead(); dashPollJob(); }
          else listNow.disabled = false;
        });
      } });
    var all = function (on) {
      return function () {
        S.admin("POST", "dashlist/" + s.source + "/all", { active: on }).then(function (r) {
          result(res, r, on ? "all read: their pages are written now" : "none read: " + S.num(r.pages_removed || 0) + " page" + (r.pages_removed === 1 ? "" : "s") + " left the Context");
          if (!r.error) { saved(); dashLoad(); }
        });
      };
    };
    var offAll = sureButton("Deactivate all", all(false), "Deactivate every dashboard of " + s.name + "?",
      "The agent stops reading them: their pages leave the Context and the search now, and new dashboards wait until someone activates them. Activate the ones needed after.", "Deactivate all");
    var onAll = sureButton("Activate all", all(true), "Activate every dashboard of " + s.name + "?",
      "The agent reads them all again (their pages are written in the background), and new dashboards too.", "Activate all");
    var nw = el("select", { "aria-label": "New dashboards" }, [["1", "New ones: read"], ["0", "New ones: not read until activated"]].map(function (o) {
      return el("option", { value: o[0], text: o[1], selected: (s.read_new ? "1" : "0") === o[0] ? "selected" : null }); }));
    nw.addEventListener("change", function () {
      S.admin("POST", "dashlist/" + s.source + "/default", { active: nw.value === "1" }).then(function (r) {
        result(res, r, nw.value === "1" ? "new ones are read" : "new ones wait until activated");
        if (!r.error) s.read_new = nw.value === "1";
      });
    });
    head.appendChild(el("div", { class: "actions" }, [listNow, offAll, onAll, nw, res]));
  }
  function dashBody() {
    var body = $("dash-body"), s = dashSource();
    if (!body || !s) return;
    body.innerHTML = "";
    var q = el("input", { type: "search", "aria-label": "Search the dashboards", placeholder: "Search a title, a folder, a type" });
    q.value = DASH.q;
    var kind = el("select", { "aria-label": "Show" }, [["dashboard", "Dashboards"], ["kids", s.source === "grafana" ? "Panels" : "Visualizations and saved searches"]].map(function (o) {
      return el("option", { value: o[0], text: o[1], selected: DASH.kind === o[0] ? "selected" : null }); }));
    var state = el("select", { "aria-label": "Read or not" }, [["", "Read or not"], ["read", "Read by the agent"], ["unread", "Not read"]].map(function (o) {
      return el("option", { value: o[0], text: o[1], selected: DASH.state === o[0] ? "selected" : null }); }));
    var sort = el("select", { "aria-label": "Sort" }, [["updated", "Last modified first"], ["title", "By title"], ["folder", s.source === "grafana" ? "By folder" : "By index pattern"]].map(function (o) {
      return el("option", { value: o[0], text: o[1], selected: DASH.sort === o[0] ? "selected" : null }); }));
    var reload = function () { DASH.q = q.value; DASH.kind = kind.value; DASH.state = state.value; DASH.sort = sort.value; dashRows(false); };
    q.addEventListener("input", function () { clearTimeout(DASH.qTimer); DASH.qTimer = setTimeout(reload, 300); });
    [kind, state, sort].forEach(function (x) { x.addEventListener("change", reload); });
    body.appendChild(el("div", { class: "filters" }, [q, kind, state, sort]));
    body.appendChild(el("div", { id: "dash-bulk", class: "actions" }));
    var table = el("table", { class: "grid compact", id: "dash-table" }, [el("thead", {}, [el("tr", {})]), el("tbody", {})]);
    body.appendChild(el("div", { class: "table-wrap" }, [table]));
    body.appendChild(el("div", { id: "dash-more" }));
    dashRows(false);
  }
  function dashRows(more) {
    var s = dashSource(), tb = document.querySelector("#dash-table tbody"), th = document.querySelector("#dash-table thead tr");
    if (!s || !tb) return;
    var offset = more ? DASH.rows.length : 0, seq = ++DASH.seq;
    var path = "dashlist/" + s.source + "?kind=" + encodeURIComponent(DASH.kind) + "&q=" + encodeURIComponent(DASH.q) +
      "&state=" + encodeURIComponent(DASH.state) + "&sort=" + encodeURIComponent(DASH.sort) + "&offset=" + offset + "&limit=" + DASH_PAGE;
    S.admin("GET", path).then(function (d) {
      if (seq !== DASH.seq) return;                 // (0.11.0) a later search or Show more answers: an older one never draws
      if (!d || d.error) {
        var again = more ? document.querySelector("#dash-more button") : null;
        if (again) {                                // (0.11.0) the rows shown stay; Show more can be clicked again
          again.disabled = false; again.textContent = again.dataset.label || again.textContent; again.title = (d && d.error) || "not read";
          return;
        }
        tb.innerHTML = ""; tb.appendChild(D.emptyRow(6, (d && d.error) || "not read")); return;
      }
      var boards = DASH.kind === "dashboard";
      th.innerHTML = "";
      (boards ? ["Read", "Dashboard", s.source === "grafana" ? "Folder" : "Index patterns", s.kid.charAt(0).toUpperCase() + s.kid.slice(1), "Last modified"]
              : ["Read", s.source === "grafana" ? "Panel" : "Visualization", "Type", s.source === "grafana" ? "Dashboard" : "On dashboards", "Last modified"]).forEach(function (h) {
        th.appendChild(el("th", { text: h })); });
      if (!more) { tb.innerHTML = ""; DASH.rows = []; }
      DASH.total = d.total || 0;
      (d.rows || []).forEach(function (x) { DASH.rows.push(x); tb.appendChild(dashRow(x, boards)); });
      if (!DASH.rows.length) tb.appendChild(D.emptyRow(5, s.listed_at ? "Nothing matches." : "Not listed yet: List now (or the next learning) reads the list."));
      var left = DASH.total - DASH.rows.length;
      var moreBox = $("dash-more");
      moreBox.innerHTML = "";
      if (left > 0) moreBox.appendChild(el("button", { type: "button", class: "btn small", text: "Show " + S.num(Math.min(left, DASH_PAGE)) + " more (" + S.num(left) + " left)",
        onclick: function (ev) {                    // (0.11.0) one click reads one page: a double click appended it twice
          var b = ev.currentTarget;
          b.disabled = true; b.dataset.label = b.textContent; b.textContent = "Reading…";
          dashRows(true);
        } }));
      dashBulk();
    });
  }
  function dashBulk() {
    var box = $("dash-bulk"), s = dashSource();
    if (!box || !s) return;
    box.innerHTML = "";
    if (!DASH.can || !DASH.total) return;
    var what = DASH.kind === "dashboard" ? "dashboard" + (DASH.total === 1 ? "" : "s") : dashKid(DASH.total);
    var res = el("span", { class: "result", role: "status" });
    var go = function (on) {
      return function () {
        S.admin("POST", "dashlist/" + s.source + "/matching", { active: on, q: DASH.q, kind: DASH.kind, state: DASH.state }).then(function (r) {
          result(res, r, (on ? "read: " : "not read: ") + S.num(r.items || 0) + " " + what + (r.cascaded ? " (and " + S.num(r.cascaded) + " of their " + dashKid(2) + ")" : ""));
          if (!r.error) { saved(); dashLoad(); }
        });
      };
    };
    box.appendChild(el("span", { class: "muted", text: S.num(DASH.total) + " " + what + " shown:" }));
    box.appendChild(el("button", { type: "button", class: "btn small", text: "Activate the " + S.num(DASH.total) + " shown", onclick: go(true) }));
    box.appendChild(el("button", { type: "button", class: "btn small", text: "Deactivate the " + S.num(DASH.total) + " shown", onclick: go(false) }));
    box.appendChild(res);
  }
  /* one row: its switch (an admin's), its title and link, where it is, its panels (a dashboard: shown under it on a
     click), when it was last modified and by whom */
  function dashRow(x, boards) {
    var s = dashSource();
    var tr = el("tr", { class: x.read ? "" : "dash-off" });
    var box = el("input", { type: "checkbox", "aria-label": "Read by the agent: " + (x.title || x.ref) });
    box.checked = !!x.active;
    box.disabled = !DASH.can;
    var note = el("div", { class: "muted small-note" });
    if (x.active && !x.read && x.kind === "panel") note.textContent = "its dashboard is not read";
    box.addEventListener("change", function () {
      var on = box.checked;
      box.disabled = true;
      S.admin("POST", "dashlist/" + s.source + "/set", { ids: [x.id], active: on }).then(function (r) {
        box.disabled = !DASH.can;
        if (!r || r.error) { box.checked = !on; note.textContent = (r && r.error) || "not saved"; note.className = "result bad"; return; }
        x.active = on;
        x.read = on && !(x.kind === "panel" && note.textContent);
        tr.className = x.read ? "" : "dash-off";
        note.className = "muted small-note";
        note.textContent = on ? "read: its page is written now" + (r.cascaded ? " (and " + S.num(r.cascaded) + " " + dashKid(r.cascaded) + ")" : "")
                              : "not read" + (r.pages_removed ? ": its page left the Context" : "") + (r.cascaded ? " (and " + S.num(r.cascaded) + " " + dashKid(r.cascaded) + ")" : "");
        saved();
        S.admin("GET", "dashlist").then(function (d) { if (d && !d.error) { DASH.sources = d.sources || DASH.sources; dashTabsCount(); } });
        var open = tr.nextSibling && tr.nextSibling.className === "dash-kids" ? tr.nextSibling : null;
        if (open && x.kind === "dashboard") { open.remove(); dashKids(x, tr, null); }
      });
    });
    var name = x.link ? el("a", { href: x.link, target: "_blank", rel: "noopener", text: x.title || x.ref }) : el("span", { text: x.title || x.ref });
    var who = x.updated_by ? " by " + x.updated_by : "";
    var cells = [el("td", {}, [box]), el("td", {}, [name, note])];
    if (boards) {
      cells.push(el("td", { class: "muted", text: x.folder || "" }));
      var kids = x.children || 0;
      cells.push(el("td", {}, [kids ? el("button", { type: "button", class: "linkish", text: S.num(kids) + " " + dashKid(kids), "aria-expanded": "false",
        onclick: function () { dashKids(x, tr, this); } }) : el("span", { class: "muted", text: x.children === 0 ? "none" : "" })]));
    } else {
      cells.push(el("td", { class: "muted", text: x.type || "" }));
      var on = (x.dashboards || []).map(function (b) { return b.title; });
      if (!on.length && x.dashboard) on = [x.dashboard];
      cells.push(el("td", { class: "muted", text: on.length ? on.slice(0, 3).join(", ") + (on.length > 3 ? " +" + (on.length - 3) : "") : (s.source === "osd" ? "on no dashboard" : "") }));
    }
    cells.push(el("td", { class: "muted", text: x.updated_at ? S.when(x.updated_at) + who : "" }));
    cells.forEach(function (c) { tr.appendChild(c); });
    return tr;
  }
  function dashTabsCount() {
    var tabs = document.querySelectorAll("#dash .dash-tabs button");
    DASH.sources.forEach(function (x, i) {
      if (tabs[i]) tabs[i].textContent = x.name + (x.dashboards ? " · " + S.num(x.dashboards_read) + " of " + S.num(x.dashboards) + " read" : "");
    });
    dashHead();
  }
  function dashKids(x, tr, btn) {
    var open = tr.nextSibling && tr.nextSibling.className === "dash-kids" ? tr.nextSibling : null;
    if (open) { open.remove(); if (btn) btn.setAttribute("aria-expanded", "false"); return; }
    var s = dashSource();
    var cell = el("td", { colspan: "5" }, [el("div", { class: "muted", text: "Reading its " + dashKid(2) + "…" })]);
    var row = el("tr", { class: "dash-kids" }, [cell]);
    tr.after(row);
    if (btn) btn.setAttribute("aria-expanded", "true");
    S.admin("GET", "dashlist/" + s.source + "/children?ref=" + encodeURIComponent(x.ref)).then(function (d) {
      cell.innerHTML = "";
      if (!d || d.error) { cell.appendChild(el("div", { class: "result bad", text: (d && d.error) || "not read" })); return; }
      var t = el("tbody", {});
      (d.rows || []).forEach(function (k) { t.appendChild(dashRow(k, false)); });
      if (!(d.rows || []).length) t.appendChild(D.emptyRow(5, "None listed."));
      cell.appendChild(el("div", { class: "table-wrap" }, [el("table", { class: "grid compact" }, [el("thead", {}, [el("tr", {}, ["Read",
        s.source === "grafana" ? "Panel" : "Visualization", "Type", s.source === "grafana" ? "Dashboard" : "On dashboards", "Last modified"].map(function (h) {
          return el("th", { text: h }); }))]), t])]));
    });
  }
  if (admin) {
    var docAuth = function () {
      var t = $("doc-auth").value;
      $("doc-user-box").hidden = t !== "basic";
      $("doc-header-box").hidden = t !== "header";
      $("doc-secret-box").hidden = !t;
      $("doc-auth-note").hidden = !t;
    };
    $("doc-auth").addEventListener("change", docAuth);
    docAuth();
    var docFiles = function () {             // a repository's choice: shown for a Bitbucket address
      var r = $("doc-reader").value, u = $("doc-url").value;
      $("doc-files-box").hidden = !(r === "bitbucket" || (!r && /bitbucket|\brepos\b/i.test(u)));
    };
    $("doc-reader").addEventListener("change", docFiles);
    $("doc-url").addEventListener("input", docFiles);
    docFiles();
    $("doc-add").addEventListener("click", function () {
      var res = $("doc-result"), btn = $("doc-add");
      if (!$("doc-url").value.trim()) { res.textContent = "write the address first (or upload a file)"; res.className = "result bad"; return; }
      btn.disabled = true;
      var body = { url: $("doc-url").value, category: $("doc-category").value, reader: $("doc-reader").value,
                   max_pages: +$("doc-pages").value, refresh_days: +$("doc-days").value,
                   auth: { type: $("doc-auth").value, user: $("doc-user").value, header: $("doc-header").value },
                   verify_tls: $("doc-tls").value === "" ? null : $("doc-tls").value === "yes",
                   ca_bundle: $("doc-ca").value, files: $("doc-files").value };
      if ($("doc-secret").value) body.secret = $("doc-secret").value;
      S.admin("POST", "docs", body).then(function (r) {
        btn.disabled = false;
        result(res, r, "added: reading it now");
        if (!r.error) {
          ["doc-url", "doc-secret", "doc-user", "doc-header", "doc-ca"].forEach(function (id) { $(id).value = ""; });
          $("doc-tls").value = ""; $("doc-files").value = "code";
          $("doc-auth").value = ""; docAuth();
          saved(); setTimeout(docsLoad, 3000);
        }
        docsLoad();
      });
    });
    $("doc-file").addEventListener("change", function () {
      var f = this.files && this.files[0], res = $("doc-result");
      if (!f) return;
      if (f.size > 20 * 1024 * 1024) { res.textContent = "file too large (20 MB at most)"; res.className = "result bad"; return; }
      var reader = new FileReader();
      reader.onload = function () {
        S.admin("POST", "docs", { name: f.name, title: f.name, category: $("doc-category").value, content: String(reader.result) }).then(function (r) {
          result(res, r, "uploaded: " + f.name);
          if (!r.error) saved();
          docsLoad();
        });
      };
      reader.readAsText(f);
      this.value = "";
    });
  }

  // ------------------------------------------------------------------ Categories (admins)
  function facetsLoad() {
    var p = [];
    if ($("fac-facet").value) p.push("facet=" + encodeURIComponent($("fac-facet").value));
    if ($("fac-status").value) p.push("status=" + encodeURIComponent($("fac-status").value));
    if ($("fac-q").value.trim()) p.push("q=" + encodeURIComponent($("fac-q").value.trim()));
    return S.admin("GET", "facets" + (p.length ? "?" + p.join("&") : "")).then(function (d) {
      var tb = $("facets").querySelector("tbody");
      tb.innerHTML = "";
      var all = d.facets || [];
      all.forEach(function (f) {
        var post = function (body) { return S.admin("POST", "facets/" + f.id, body).then(function (r) { if (!r.error) { saved(); loadCategories(); } facetsLoad(); return r; }); };
        var valueCell = el("td", {}, [el("div", { class: "facet-value", text: f.value }),
          f.description ? el("div", { class: "muted", text: f.description }) : null,
          (f.synonyms || []).length ? el("div", { class: "muted", text: "also: " + f.synonyms.join(", ") }) : null,

          (f.origins || []).length ? el("div", { class: "muted facet-origins", text: "from: " + f.origins.slice(-3).join("; ") +
            (f.origins.length > 3 ? " (+" + (f.origins.length - 3) + ")" : "") }) : null]);
        var acts = el("td", { class: "row-actions" });
        if (f.status !== "approved") acts.appendChild(el("button", { type: "button", class: "linkish", text: "Approve", onclick: function () { post({ status: "approved" }); } }));
        acts.appendChild(el("button", { type: "button", class: "linkish", text: "Edit", onclick: function () {
          if (valueCell.querySelector("input")) return;
          var v = el("input", { type: "text", "aria-label": "Value" }); v.value = f.value;
          var ds = el("input", { type: "text", "aria-label": "Description", placeholder: "what it covers" }); ds.value = f.description || "";
          var sy = el("input", { type: "text", "aria-label": "Also called", placeholder: "also called (comma separated)" }); sy.value = (f.synonyms || []).join(", ");
          // the category itself: a value moves between subjects, applications and components (the aspect is fixed)
          var cat = FACET_NAMES[f.facet] ? el("select", { "aria-label": "Category" }, Object.keys(FACET_NAMES).map(function (k) {
            return el("option", { value: k, text: FACET_NAMES[k], selected: k === f.facet ? "selected" : null });
          })) : null;
          var msg = el("span", { class: "result", role: "status" });
          var save = el("button", { type: "button", class: "btn small primary", text: "Save", onclick: function () {
            var body = { value: v.value, description: ds.value, synonyms: sy.value };
            if (cat) body.facet = cat.value;
            S.admin("POST", "facets/" + f.id, body).then(function (r) {
              if (r.error) { result(msg, r, ""); return; }
              saved();
              loadCategories();                               // the categories' counts follow
              facetsLoad();
            });
          } });
          valueCell.innerHTML = "";
          valueCell.appendChild(el("div", { class: "facet-edit" }, [v, cat, ds, sy,
            el("div", { class: "actions" }, [save,
              el("button", { type: "button", class: "btn small", text: "Cancel", onclick: facetsLoad }), msg])]));
          v.focus();
        } }));
        if (f.status === "approved") acts.appendChild(el("button", { type: "button", class: "linkish", text: "Links…",   // (0.9.6)
          "aria-expanded": "false", onclick: function (ev) {
            var open = valueCell.querySelector(".links-box");
            if (open) { open.remove(); ev.target.setAttribute("aria-expanded", "false"); return; }
            ev.target.setAttribute("aria-expanded", "true");
            valueCell.appendChild(S.linksBox({ id: f.id, value: f.value }, { onchange: function () { saved(); } }));
          } }));
        // (0.11.0) a merge is an AI Admin's (as the server): the button only for one, and asked first (it is not undone)
        var same = canDelete ? all.filter(function (x) { return x.facet === f.facet && x.id !== f.id && x.status === "approved"; }) : [];
        if (same.length) {
          acts.appendChild(el("button", { type: "button", class: "linkish", text: "Merge…", onclick: function () {
            if (acts.querySelector("select")) return;
            var sel = el("select", { "aria-label": "Merge into" }, [el("option", { value: "", text: "into…" })].concat(
              same.map(function (x) { return el("option", { value: x.id, text: x.value }); })));
            acts.appendChild(sel);
            sel.addEventListener("change", function () {
              var into = sel.value, name = into ? sel.options[sel.selectedIndex].text : "";
              if (!into) return;
              S.confirm(sel, "Merge “" + f.value + "” into “" + name + "”?", { yes: "Merge", no: "Cancel",
                detail: "Its items and links go to “" + name + "”, its name becomes one of its other names, and “" +
                  f.value + "” goes. It cannot be undone." }).then(function (ok) {
                if (ok) post({ merge_into: +into });
                else if (sel.value === into) sel.value = "";      // (another value chosen meanwhile: kept)
              });
            });
          } }));
        }
        // (0.10.6.1) every value but the fixed aspects, the ones seeded at the start too (they had no way out): a value
        // removed stays removed (the learning never seeds a rejected one again)
        if ((canDelete || f.status !== "approved") && f.facet !== "aspect") acts.appendChild(sureButton(f.status === "approved" ? "Remove" : "Reject", function () { post({ status: "rejected" }); },
          (f.status === "approved" ? "Remove " : "Reject ") + "\u201c" + f.value + "\u201d?",
          (f.items ? "Its " + S.num(f.items) + " item" + (f.items === 1 ? "" : "s") + " lose this " + f.facet + ". " : "") +
          "It is not proposed again; adding it by hand brings it back."));
        // (0.11.4) a box to choose it: the values chosen are changed together (the bar above the list)
        var pick = f.facet === "aspect" ? null : el("input", { type: "checkbox", class: "fac-pick", "aria-label": "Choose " + f.value,
          checked: facPicked[f.id] ? "checked" : null, onchange: function (ev) {
            if (ev.target.checked) facPicked[f.id] = { id: f.id, value: f.value, facet: f.facet, status: f.status };
            else delete facPicked[f.id];
            facAll();
            facBar();
          } });
        tb.appendChild(el("tr", { class: facPicked[f.id] ? "picked" : "" }, [el("td", { class: "pick-col" }, [pick]),
          valueCell, el("td", { text: f.facet }), el("td", { class: "num", text: S.num(f.items) }),
          el("td", { class: "muted", text: (f.examples || []).join(" · ") }),
          el("td", {}, [badge(f.status === "approved" ? "used" : "proposed", f.status === "approved" ? "ok" : "warn"),
                        el("div", { class: "muted", text: { seed: "from the start", data: "from the data", llm: "by the LLM", admin: "by an admin", docs: "from the documents" }[f.source] || f.source || "" })]),
          acts]));
      });
      if (!all.length) tb.appendChild(D.emptyRow(7, "No category yet: the daily learning classifies the knowledge (or: superset supagent classify)."));
      // (0.11.4) the choice is what the list shows: a value no longer shown (another filter, moved away) leaves it
      var shown = {};
      all.forEach(function (f) { shown[f.id] = f; });
      Object.keys(facPicked).forEach(function (k) {
        if (!shown[k] || shown[k].facet === "aspect") delete facPicked[k];
        else facPicked[k] = { id: shown[k].id, value: shown[k].value, facet: shown[k].facet, status: shown[k].status };
      });
      facShown = all;
      facAll();
      facBar();
      // (0.10.6.1) the values shown removed at once (an admin; the fixed aspects stay): filter by category, state or
      // words first, then remove what is left in the list, asked once with how many
      var bulkBox = $("fac-bulk"), gone = all.filter(function (f) { return f.facet !== "aspect"; });
      if (bulkBox) {
        bulkBox.innerHTML = "";
        var filtered = $("fac-facet").value || $("fac-status").value || $("fac-q").value.trim();
        if (canDelete && gone.length && filtered) {                   // (never the whole list unfiltered)
          var go = el("button", { type: "button", class: "btn small", text: "Remove the " + S.num(gone.length) + " value" + (gone.length === 1 ? "" : "s") + " shown" });
          go.addEventListener("click", function () {
            S.confirm(go, "Remove the " + S.num(gone.length) + " value" + (gone.length === 1 ? "" : "s") + " shown?", { yes: "Remove " + S.num(gone.length), no: "Cancel",
              detail: "Their items lose them; they are not proposed again (adding one by hand brings it back). The list's filters choose which ones." }).then(function (ok) {
              if (!ok) return;
              go.disabled = true;
              var n = 0, chain = Promise.resolve();
              gone.forEach(function (f) {
                chain = chain.then(function () { return S.admin("POST", "facets/" + f.id, { status: "rejected" }); }).then(function (r) {
                  if (!(r && r.error)) n++;
                  go.textContent = "Removed " + S.num(n) + " of " + S.num(gone.length) + "…";
                });
              });
              chain.then(function () { saved(); loadCategories(); facetsLoad(); });
            });
          });
          bulkBox.appendChild(go);
        }
      }
    });
  }
  /* (0.11.4) the values chosen in the list (their boxes ticked), changed together, the user's request: put in one
     category (a subcategory, or another category), or each given the same link to one other value (a component, an
     application…), with what it is and what it does. What cannot be done is said, value by value; the rest is done. */
  var facPicked = {}, facShown = [], CATS = [];
  function pickedIds() { return Object.keys(facPicked).map(Number); }
  function facAll() {                          // the header's box: every value shown, some, none
    var box = $("fac-all");
    if (!box) return;
    var can = facShown.filter(function (f) { return f.facet !== "aspect"; }), n = pickedIds().length;
    box.checked = !!can.length && n === can.length;
    box.indeterminate = n > 0 && n < can.length;
    box.disabled = !can.length;
    box.onchange = function () {
      if (box.checked) can.forEach(function (f) { facPicked[f.id] = { id: f.id, value: f.value, facet: f.facet, status: f.status }; });
      else facPicked = {};
      $("facets").querySelectorAll("tbody tr").forEach(function (tr) {
        var c = tr.querySelector(".fac-pick");
        if (c) { c.checked = box.checked; tr.classList.toggle("picked", box.checked); }
      });
      facBar();
    };
    $("facets").querySelectorAll("tbody tr").forEach(function (tr) {
      var c = tr.querySelector(".fac-pick");
      if (c) tr.classList.toggle("picked", c.checked);
    });
  }
  function catChoices() {                      // the categories as a tree: a subcategory after the one it is inside
    var within = {}, kids = {}, seen = {}, out = [];
    CATS.forEach(function (c) { within[c.name] = c.inside || ""; });
    CATS.forEach(function (c) {
      var p = within[c.name] && within.hasOwnProperty(within[c.name]) && within[c.name] !== c.name ? within[c.name] : "";
      (kids[p] = kids[p] || []).push(c.name);
    });
    (function walk(p, path) {
      (kids[p] || []).forEach(function (n) {
        if (seen[n]) return;
        seen[n] = 1;
        var here = path.concat([FACET_NAMES[n] || n]);
        out.push({ name: n, label: here.join(" › ") });
        walk(n, here);
      });
    })("", []);
    CATS.forEach(function (c) { if (!seen[c.name]) out.push({ name: c.name, label: FACET_NAMES[c.name] || c.name }); });
    return out;
  }
  function facBar() {
    var bar = $("fac-sel");
    if (!bar) return;
    var ids = pickedIds(), n = ids.length;
    if (!n || !admin) { bar.hidden = true; bar.innerHTML = ""; bar._built = false; bar._fill = null; return; }
    bar.hidden = false;
    var many = function (k) { return S.num(k) + " value" + (k === 1 ? "" : "s"); };
    if (bar._built) { bar._count(n); return; }        // the bar kept (what is typed in it too); its counts follow
    bar.innerHTML = "";
    bar._built = true;
    var res = el("div", { class: "result", role: "status", "aria-live": "polite" });
    var say = function (text, bad) { res.textContent = text; res.className = "result" + (bad ? " warn" : " good"); };
    var skippedText = function (sk) {
      if (!sk || !sk.length) return "";
      return " Not done for " + sk.slice(0, 5).map(function (x) { return "“" + (x.value || "#" + x.id) + "” (" + x.why + ")"; }).join(", ") +
        (sk.length > 5 ? " and " + (sk.length - 5) + " more" : "") + ".";
    };
    var count = el("strong", { class: "fac-sel-count" });
    var clear = el("button", { type: "button", class: "linkish", text: "Clear the choice", onclick: function () {
      facPicked = {};
      $("facets").querySelectorAll(".fac-pick").forEach(function (c) { c.checked = false; });
      facAll();
      facBar();
    } });
    // put them in a category: a subcategory (a category drawn inside another), or another category
    var to = el("select", { "aria-label": "The category to put them in" });
    bar._fill = function () {
      var was = to.value;
      to.innerHTML = "";
      to.appendChild(el("option", { value: "", text: "a category or a subcategory…" }));
      catChoices().forEach(function (c) { to.appendChild(el("option", { value: c.name, text: c.label })); });
      to.value = was;
    };
    bar._fill();
    loadCategories();                                     // read again: one made meanwhile (on the map) is a choice

    var move = el("button", { type: "button", class: "btn small primary", onclick: function () {
      var ids = pickedIds();
      if (!to.value) { say("Choose the category to put them in.", true); to.focus(); return; }
      move.disabled = true;
      S.dict("POST", "map", { move_values: { ids: ids, facet: to.value } }).then(function (r) {
        move.disabled = false;
        if (r.error) { say(r.error, true); return; }
        var name = to.options[to.selectedIndex] ? to.options[to.selectedIndex].text : r.facet;
        say((r.moved ? "Put " + many(r.moved) + " in " + name + "." : "Nothing moved.") +
            (r.there ? " " + many(r.there) + " " + (r.there === 1 ? "was" : "were") + " there already." : "") +
            skippedText(r.skipped), (r.skipped || []).length > 0);
        if (r.moved) { saved(); loadCategories(); }
        facetsLoad();
      });
    } });
    // the same link from each one to one other value (or from it to each, or both ways)
    var other = S.picker({ single: true, placeholder: "The other value: type to search", label: "The value to link them to",
      load: function (words) {
        return S.admin("GET", "facets?status=approved&brief=1&limit=60" + (words ? "&q=" + encodeURIComponent(words) : "")).then(function (d) {
          var rows = d.facets || [];
          return { items: rows.map(function (f) { return { id: f.id, label: f.value, group: f.facet, data: f }; }),
                   more: Math.max(0, (d.total || 0) - rows.length) };
        });
      } });
    var desc = el("input", { type: "text", maxlength: "500", class: "fac-sel-desc", "aria-label": "What the link is",
                             placeholder: "What the link is (is scraped by, runs on, sends data to…)" });
    var work = el("textarea", { rows: "2", maxlength: "2000", "aria-label": "What the link does",
                                placeholder: "What it does, what to check on the other value when following it (optional)" });
    var way = el("select", { "aria-label": "Direction" }, [
      el("option", { value: "out", text: "from each to it →" }),
      el("option", { value: "in", text: "from it to each ←" }),
      el("option", { value: "both", text: "both ways ↔" })]);
    var add = el("button", { type: "button", class: "btn small primary", onclick: function () {
      var target = other.chosen()[0], ids = pickedIds();
      if (!target) { say("Choose the value to link them to.", true); return; }
      if (!desc.value.trim()) { say("Say what the link is.", true); desc.focus(); return; }
      S.confirm(add, "Link " + many(ids.length) + " to “" + target.label + "”?", { yes: "Add the links", no: "Cancel",
        detail: "Each chosen value gets the link “" + desc.value.trim() + "” (" + way.options[way.selectedIndex].text +
          "), used at once. A value linked so already keeps its own link as written." }).then(function (ok) {
        if (!ok) return;
        add.disabled = true;
        S.dict("POST", "map", { link_many: { ids: ids, to: +target.id, note: desc.value, detail: work.value, way: way.value } }).then(function (r) {
          add.disabled = false;
          if (r.error) { say(r.error, true); return; }
          say((r.made ? "Added " + S.num(r.made) + " link" + (r.made === 1 ? "" : "s") + " to “" + r.other.value + "”." : "No link added.") +
              (r.had ? " " + many(r.had) + " had it already (kept as written)." : "") + skippedText(r.skipped),
              (r.skipped || []).length > 0);
          if (r.made && canDelete && (r.ids || []).length) {        // a wrong target: the links just added taken back
            var undo = el("button", { type: "button", class: "linkish", text: "Undo", onclick: function () {
              undo.disabled = true;
              S.dict("POST", "map", { remove_links: { ids: r.ids } }).then(function (x) {
                if (x.error) { say(x.error, true); return; }
                say("Taken back: the " + S.num(x.removed) + " link" + (x.removed === 1 ? "" : "s") + " just added.", false);
                saved();
              });
            } });
            res.appendChild(document.createTextNode(" "));
            res.appendChild(undo);
          }
          if (r.made) saved();
          facetsLoad();
        });
      });
    } });
    bar._count = function (k) {
      count.textContent = many(k) + " chosen";
      move.textContent = "Put the " + many(k) + " there";
      add.textContent = "Link the " + many(k);
    };
    bar._count(n);
    bar.appendChild(el("div", { class: "fac-sel-head" }, [count, clear]));
    bar.appendChild(el("div", { class: "fac-sel-row", role: "group", "aria-label": "Put them in a category" }, [
      el("span", { class: "fac-sel-label", text: "Put them in" }), to, move]));
    bar.appendChild(el("div", { class: "fac-sel-row", role: "group", "aria-label": "Link each one to one value" }, [
      el("span", { class: "fac-sel-label", text: "Link each to" }), other.el, desc, way, add]));
    bar.appendChild(el("div", { class: "fac-sel-row fac-sel-work" }, [el("span", { class: "fac-sel-label" }), work]));
    bar.appendChild(res);
  }
  var FACET_NAMES = { subject: "Subject", application: "Application", component: "Component" };
  function plural(k) {                         // Subjects, Applications, Components; one's own: as named
    return FACET_NAMES[k] + (["subject", "application", "component"].indexOf(k) >= 0 ? "s" : "");
  }
  /* the categories as the settings say (the deployment's own after the three): names, the selects, the panel */
  function loadCategories() {
    return S.admin("GET", "facets/categories").then(function (d) {
      var cats = d.categories || [];
      if (!cats.length) return;
      CATS = cats;
      Object.keys(FACET_NAMES).forEach(function (k) { delete FACET_NAMES[k]; });
      cats.forEach(function (c) { FACET_NAMES[c.name] = c.name.charAt(0).toUpperCase() + c.name.slice(1); });
      var add = $("fac-new-facet"), keep = add.value;
      add.innerHTML = "";
      cats.forEach(function (c) { add.appendChild(el("option", { value: c.name, text: FACET_NAMES[c.name] })); });
      if (keep && FACET_NAMES[keep]) add.value = keep;
      var filt = $("fac-facet"), was = filt.value;
      filt.innerHTML = "";
      filt.appendChild(el("option", { value: "", text: "All categories" }));
      cats.concat([{ name: "aspect" }]).forEach(function (c) {
        filt.appendChild(el("option", { value: c.name, text: c.name === "aspect" ? "Aspect" : plural(c.name) }));
      });
      filt.value = was;
      var list = $("cat-own-list");
      list.innerHTML = "";
      cats.forEach(function (c) { list.appendChild(categoryRow(c, cats)); });
      var bar = $("fac-sel");
      if (bar && bar._fill) bar._fill();                  // (0.11.4) the bar's categories follow
    });
  }
  /* a category in the list: what it holds, where its values are read, the category it is drawn inside on the
     System map (0.9.6.5); an admin changes its name (their own ones), its field names and the category it is
     inside, or removes it (their own ones) with everything that names its values, asked first */
  function categoryRow(c, cats) {
    var li = el("li", {});
    var n = c.values || 0;
    var show = function () {
      li.innerHTML = "";
      li.appendChild(el("strong", { text: FACET_NAMES[c.name] }));
      li.appendChild(el("span", { class: "muted", text: (c.builtin ? " (built in: it stays; its values are removed one by one in the list below)" : " (yours)") + " · " + S.num(n) + " value" + (n === 1 ? "" : "s") +
        (c.fields ? " · values read from the fields " + c.fields : " · no field read") +
        (c.inside ? " · drawn inside its " + (FACET_NAMES[c.inside] || c.inside).toLowerCase() + " on the System map" : "") }));
      // what the category is: for people, and given to the agent and the router with the parts a question names
      li.appendChild(c.about ? el("div", { class: "cat-about", text: c.about }) :
        admin ? el("div", { class: "cat-about muted", text: "No description yet: Edit to say what it is (the agent and the router read it)." }) : null);
      if (!admin) return;
      var acts = el("span", { class: "row-actions cat-own-acts" });
      acts.appendChild(el("button", { type: "button", class: "linkish", text: "Edit", onclick: edit }));
      if (!c.builtin) {
        var goes = [];
        if (n) goes.push(S.num(n) + " value" + (n === 1 ? "" : "s"));
        if (c.tags) goes.push(S.num(c.tags) + " link" + (c.tags === 1 ? "" : "s") + " to items");
        var nl = (c.parts || 0) + (c.interactions || 0);           // (0.9.6: one kind of relation, the link)
        if (nl) goes.push(S.num(nl) + " link" + (nl === 1 ? "" : "s") + " of the map");
        if (canDelete) acts.appendChild(sureButton("Remove", function () {
          return S.admin("POST", "facets/categories", { name: c.name, remove: true }).then(function (r) {
            result($("cat-own-result"), r, "removed: " + FACET_NAMES[c.name] + (r.removed && r.removed.values ? " with its " + S.num(r.removed.values) + " value" + (r.removed.values === 1 ? "" : "s") : ""));
            if (!r.error) { saved(); loadCategories(); facetsLoad(); }
          });
        }, "Remove the category “" + FACET_NAMES[c.name] + "”?",
           (goes.length ? "These go with it: " + goes.join(", ") + ". " : "It has no value: only the category goes. ") + "This cannot be undone.",
           "Remove"));
      }
      li.appendChild(acts);
    };
    var edit = function () {
      li.innerHTML = "";
      var name = el("input", { type: "text", maxlength: "24", "aria-label": "Name of the category", class: "cat-own-name" });
      name.value = c.name;
      name.disabled = !!c.builtin;
      if (c.builtin) name.title = "Built in: its name stays";
      var rx = el("input", { type: "text", "aria-label": "Field names it reads (a pattern)", class: "cat-own-rx",
                             placeholder: "Field names it reads, e.g. ^(host|node|server)$" });
      rx.value = c.fields || "";
      var what = el("input", { type: "text", maxlength: "300", "aria-label": "What this category is", class: "cat-own-about",
                               placeholder: "What it is, in a sentence (the agent and the router read it)" });
      what.value = c.about || "";
      // the System map draws its values inside the value of that category they are part of or run on
      var within = el("select", { "aria-label": "Drawn inside (System map)", class: "cat-own-inside",
                                  title: "On the System map, its values drawn inside the value of that category they are part of or run on (a server's disks inside it)" },
        [el("option", { value: "", text: "In a column of its own" })].concat((cats || []).filter(function (x) { return x.name !== c.name; })
          .map(function (x) { return el("option", { value: x.name, text: "Inside: " + FACET_NAMES[x.name] }); })));
      within.value = c.inside || "";
      var msg = el("span", { class: "result", role: "status" });
      li.appendChild(el("span", { class: "filters cat-own-edit" }, [name, rx, what, within,
        el("button", { type: "button", class: "btn small primary", text: "Save", onclick: function () {
          var body = { name: c.name, fields: rx.value, about: what.value };
          if (within.value !== (c.inside || "")) body.inside = within.value;
          if (!c.builtin && name.value.trim().toLowerCase() !== c.name) body.rename = name.value;
          S.admin("POST", "facets/categories", body).then(function (r) {
            if (r.error) { result(msg, r, ""); return; }
            result($("cat-own-result"), r, "saved" + (body.rename ? ": its values follow" : rx.value !== (c.fields || "") ? ": the next learning reads its values" :
              "inside" in body ? (body.inside ? ": the System map draws its values inside their " + (FACET_NAMES[body.inside] || body.inside).toLowerCase() :
              ": the System map gives it a column of its own") : ""));
            saved(); loadCategories(); facetsLoad();
          });
        } }),
        el("button", { type: "button", class: "btn small", text: "Cancel", onclick: show }), msg]));
      (c.builtin ? rx : name).focus();
    };
    show();
    return li;
  }
  if (admin) {
    $("cat-own-add").addEventListener("click", function () {
      var res = $("cat-own-result");
      S.admin("POST", "facets/categories", { name: $("cat-own-name").value, fields: $("cat-own-fields").value }).then(function (r) {
        result(res, r, "added: the next learning reads its values (or add them above); it has its column on the System map");
        if (!r.error) { $("cat-own-name").value = ""; $("cat-own-fields").value = ""; loadCategories(); facetsLoad(); }
      });
    });
  }
  // (0.9.6) a value's links are added once it exists: Links… on its line
  if (admin) {
    $("fac-add").addEventListener("click", function () {
      var res = $("fac-result"), btn = $("fac-add");
      if (!$("fac-new-value").value.trim()) { res.textContent = "write the value first"; res.className = "result bad"; return; }
      btn.disabled = true;
      S.admin("POST", "facets", { facet: $("fac-new-facet").value, value: $("fac-new-value").value,
                                  description: $("fac-new-desc").value, synonyms: $("fac-new-syn").value }).then(function (r) {
        btn.disabled = false;
        result(res, r, "added: used at once");
        if (!r.error) {
          ["fac-new-value", "fac-new-desc", "fac-new-syn"].forEach(function (id) { $(id).value = ""; });
          saved();
          loadCategories();                                   // the categories' counts follow
          facetsLoad();
        }
      });
    });
  }
  var facTimer = null;
  ["fac-facet", "fac-status"].forEach(function (id) { $(id).addEventListener("change", facetsLoad); });
  $("fac-q").addEventListener("input", function () { clearTimeout(facTimer); facTimer = setTimeout(facetsLoad, 250); });

  // ------------------------------------------------------------------ Notes (0.7): every user's, read here too
  var notePage = { page: 0, size: 25, total: 0 };
  function notesLoad() {
    var p = ["limit=" + notePage.size, "offset=" + notePage.page * notePage.size];
    if ($("note-q").value.trim()) p.push("q=" + encodeURIComponent($("note-q").value.trim()));
    if ($("note-who").value === "mine") p.push("mine=1");
    return S.chat("GET", "notes?" + p.join("&")).then(function (d) {
      var tb = $("notes").querySelector("tbody");
      tb.innerHTML = "";
      notePage.total = d.total || 0;
      (d.notes || []).forEach(function (n) {
        var post = function (path, body) {
          return S.chat("POST", "notes/" + n.id + path, body).then(function (r) { if (!r.error) saved(); notesLoad(); return r; });
        };
        var acts = el("td", { class: "row-actions" });
        if (admin && n.scope === "team") {
          acts.appendChild(el("button", { type: "button", class: "linkish", text: n.pinned ? "Unpin" : "Pin for everyone",   // (0.11.0) as in the chat
            onclick: function () { post("", { pinned: !n.pinned }); } }));
          if (!n.entry_id) acts.appendChild(el("button", { type: "button", class: "linkish", text: "Make a catalog entry",
            onclick: function () { post("/promote", {}); } }));
        }
        if (n.can_change && (n.mine || canDelete)) acts.appendChild(sureButton("Delete", function () {
          S.chat("DELETE", "notes/" + n.id).then(function () { saved(); notesLoad(); });
        }, "Delete the note \u201c" + (n.title || "Note") + "\u201d?", "It cannot be restored" +
           (n.entry_id ? " (its catalog guide stays)." : ".")));
        var tags = (n.tags || []).length ? "#" + n.tags.join(" #") : "";
        tb.appendChild(el("tr", {}, [
          el("td", {}, [el("button", { type: "button", class: "linkish nm", text: n.title || "Note", onclick: function () {
              D.textDrawer(n.title || "Note", [n.author, n.day, tags].filter(Boolean).join(" · "), n.text);
            } }),
            n.pinned ? badge("pinned", "ok") : null, n.entry_id ? badge("in the catalog", "ok") : null,
            tags ? el("div", { class: "muted", text: tags }) : null]),
          el("td", { text: n.author }), el("td", { text: n.day }),
          el("td", { text: n.scope === "team" ? "the team" : "its author only" }), acts]));
      });
      if (!(d.notes || []).length) tb.appendChild(D.emptyRow(5, "No note yet: in the chat, Notes (or /note … in the question box)."));
      S.pager($("note-pager"), notePage, notesLoad);
    });
  }
  var noteTimer = null;
  $("note-q").addEventListener("input", function () {
    clearTimeout(noteTimer);
    noteTimer = setTimeout(function () { notePage.page = 0; notesLoad(); }, 250);
  });
  $("note-who").addEventListener("change", function () { notePage.page = 0; notesLoad(); });

  // ------------------------------------------------------------------ the tabs of this file
  /* To review needs the categories as the settings say them (one's own too): the Category of Edit…, the values a
     proposed one can be part of. The page may open on this tab, before Categories was ever shown. */
  var categoriesRead = null;                   // once per page: Categories keeps them current after that
  D.register("review", function () {
    var box = $("review");
    box.innerHTML = "";
    box.appendChild(el("p", { class: "muted", text: "Loading…" }));
    categoriesRead = categoriesRead || loadCategories();
    return categoriesRead.then(reviewLoad, reviewLoad);
  });
  D.register("catalog", function () { catLoad(false); });
  D.register("memory", memLoad);
  D.register("docs", function () { docsLoad(); if (admin) dashLoad(); });
  D.register("notes", notesLoad);
  D.register("categories", function () {
    return loadCategories().then(function () { return facetsLoad(); });
  });
})();
