"use strict";
const $ = (s, r = document) => r.querySelector(s);
/* Advanced mode (open the page with ?advanced=1) shows the strategy choice, search-step counts, demo data,
   the Experiments tab and the strategy comparison export. Normal teachers never see them. */
const ADVANCED = new URLSearchParams(location.search).get("advanced") === "1";
if (!ADVANCED) document.querySelectorAll(".adv-only").forEach(el => el.remove());
const state = { data: null, plan: null, current: 0, courses: [], labBusy: false, labDone: false };

/* ---------- small helpers (text is always set with textContent, so names can't inject HTML) */
function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") el.style.cssText = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid !== null && kid !== undefined && kid !== false)
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  return el;
}
/* Messages appear as toasts that slide in (motion.js). An empty message clears the current toast. */
function showAlert(msg, kind = "error") { Motion.toast(msg, kind); }

/* Small constant icons for empty states (static markup, never built from user text). */
const ICON = {
  upload: '<path d="M12 16V4m0 0L7 9m5-5 5 5M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
  seats: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
};
function emptyState(icon, title, text, btn) {
  const ico = h("div", { class: "empty-ico", "aria-hidden": "true" });
  ico.innerHTML = `<svg viewBox="0 0 24 24">${ICON[icon]}</svg>`;
  return h("div", { class: "empty-state" }, ico, h("h3", {}, title), h("p", {}, text), btn);
}
async function api(path, opts) {
  let res;
  try { res = await fetch(path, opts); }
  catch { throw new Error("Cannot reach the planner. Make sure it is still running, then reload this page."); }
  if (!res.ok) {
    let msg = res.statusText;
    try {
      const j = await res.json();
      msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* keep statusText */ }
    throw new Error(msg);
  }
  return res.json();
}
async function busy(btn, label, fn) {
  const old = btn.textContent; btn.disabled = true; btn.setAttribute("aria-busy", "true"); btn.textContent = label; showAlert("");   // aria-busy shows the spinner
  try { await fn(); } catch (e) { showAlert(e.message); } finally { btn.disabled = false; btn.removeAttribute("aria-busy"); btn.textContent = old; }
}

/* ---------- course colours: golden-angle hues, stable per course code; the code is also printed in each seat.
   Only the hue is set here; the .cc class in styles.css turns it into background, border and text colours. */
function courseColor(code) {
  const i = Math.max(0, state.courses.indexOf(code)), hue = (i * 137.5 + 205) % 360;
  return `--h:${hue.toFixed(1)}`;
}

/* ---------- dates: files and the server use 2026-11-23; people read "Mon, 23 Nov 2026" */
function fmtDate(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return iso;
  return new Date(+m[1], +m[2] - 1, +m[3]).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}
const provTag = () => h("span", { class: "tag-prov", title: "This layout is an estimate. Check it on the Rooms tab." }, "Provisional");

/* ---------- tabs */
const tabButtons = () => [...document.querySelectorAll(".tabs button")];
function openTab(name, focus = false) {
  const panel = $("#tab-" + name), was = document.querySelector(".panel:not([hidden])");
  tabButtons().forEach(b => {
    const on = b.dataset.tab === name;
    b.setAttribute("aria-selected", on); b.tabIndex = on ? 0 : -1; if (on && focus) b.focus();
  });
  document.querySelectorAll(".panel").forEach(p => p.hidden = p !== panel);
  Motion.moveTab();                                    // slide the amber pill under the new tab
  if (panel !== was) Motion.enterPanel(panel);         // fade + rise the panel's cards one by one
  if (name === "lab") loadLab();
}
tabButtons().forEach(b => b.addEventListener("click", () => openTab(b.dataset.tab)));
/* Keyboard: arrow keys, Home and End move between tabs (the usual tab-list pattern). */
$(".tabs").addEventListener("keydown", e => {
  const all = tabButtons(), i = all.findIndex(b => b.getAttribute("aria-selected") === "true");
  const next = { ArrowRight: (i + 1) % all.length, ArrowLeft: (i - 1 + all.length) % all.length, Home: 0, End: all.length - 1 }[e.key];
  if (next === undefined) return;
  e.preventDefault(); openTab(all[next].dataset.tab, true);
});
Motion.tabs($(".tabs")); Motion.dropzones(); Motion.highlight($("#plan-out"));
Motion.enter([$(".navbar"), $(".eyebrow")], { step: 70 }); Motion.enterPanel($("#tab-data"));   // page load

/* ---------- light / dark theme. The inline script in <head> already set data-theme before the first paint;
   this only wires the button. The choice is remembered in localStorage (wrapped in try/catch: storage can be blocked). */
const themeBtn = $("#theme-toggle");
function applyTheme(theme, save) {
  document.documentElement.setAttribute("data-theme", theme);
  document.querySelector('meta[name="theme-color"]').setAttribute("content", theme === "light" ? "#f6efe2" : "#16130f");
  const next = theme === "light" ? "Switch to dark theme" : "Switch to light theme";
  themeBtn.setAttribute("aria-label", next); themeBtn.title = next;
  if (save) { try { localStorage.setItem("theme", theme); } catch { /* not saved, still works for this visit */ } }
}
applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark", false);
themeBtn.addEventListener("click", () => applyTheme(document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light", true));

/* ---------- DATA tab */
document.querySelectorAll(".file input").forEach(inp => inp.addEventListener("change", () => {
  const files = [...inp.files], label = inp.closest(".file");
  label.classList.remove("has"); void label.offsetWidth;          // remove, reflow, add again so the tick pops every time
  label.classList.toggle("has", files.length > 0);
  $(".file-name", label).textContent = !files.length ? "Choose file" : files.length === 1 ? files[0].name : `${files.length} files: ` + files.map(f => f.name).join(", ");
}));
const isPdf = f => /\.pdf$/i.test(f.name) || f.type === "application/pdf";
/* PDFs are routed to the preview screen; CSV/Excel go straight in (they are already tables). */
$("#upload-form").addEventListener("submit", e => {
  e.preventDefault();
  const form = e.target, pick = n => [...form.elements[n].files].filter(f => f.size > 0);
  const sFiles = pick("students"), rFiles = pick("rooms"), cFiles = pick("schedule");
  if (!sFiles.length && !rFiles.length && !cFiles.length) return showAlert("Choose at least one file first.");
  if (rFiles.length > 1 || cFiles.length > 1) return showAlert("Choose one rooms file and one schedule file at most.");
  const sPdf = sFiles.filter(isPdf), sOther = sFiles.filter(f => !isPdf(f));
  if (sPdf.length && sOther.length) return showAlert("Choose either PDF student lists or one CSV/Excel student file, not both together.");
  if (sOther.length > 1) return showAlert("Choose one CSV/Excel student file, or several PDF lists.");
  const rPdf = rFiles.filter(isPdf), cPdf = cFiles.filter(isPdf);
  const rOther = rFiles.filter(f => !isPdf(f)), cOther = cFiles.filter(f => !isPdf(f));
  busy($("#upload-form button[type=submit]"), "Loading…", async () => {
    hidePreview();
    if (sOther.length) {                               // students as CSV/Excel: one request, as before (rooms/schedule tables go along)
      const fd = new FormData(); fd.append("students", sOther[0]);
      if (rOther.length) fd.append("rooms", rOther[0]); if (cOther.length) fd.append("schedule", cOther[0]);
      onLoaded(await api("/api/data", { method: "POST", body: fd }));
    } else if (rOther.length || cOther.length) {       // only rooms / schedule tables (student lists are PDFs or already loaded)
      const fd = new FormData();
      if (rOther.length) fd.append("rooms", rOther[0]); if (cOther.length) fd.append("schedule", cOther[0]);
      await api("/api/tables", { method: "POST", body: fd }); await afterEdit();
      showAlert("Files loaded. Generate the seating again to use them.", "info");
    }
    await Promise.all([loadRoomsTab(), loadTimetable()]);
    // every PDF: read it, show what was found, and wait for the teacher to confirm
    const queue = [...rPdf.map(f => ["rooms", f]), ...cPdf.map(f => ["schedule", f]), ...sPdf.map(f => ["students", f])];
    if (queue.length) await runPreviews(queue);
  });
});
if (ADVANCED) $("#demo-btn").addEventListener("click", () => {
  const fd = new FormData(); fd.append("demo", "true");
  busy($("#demo-btn"), "Loading…", async () => { hidePreview(); onLoaded(await api("/api/data", { method: "POST", body: fd })); await Promise.all([loadRoomsTab(), loadTimetable()]); });
});

/* ---------- PDF preview / fix / confirm. One PDF at a time; the next one opens after the last is confirmed or skipped. */
const P = { queue: [], done: 0, total: 0 };
function hidePreview() { P.queue = []; $("#preview").replaceChildren(); }
async function runPreviews(queue) {
  P.queue = queue; P.done = 0; P.total = queue.length;
  await nextPreview();
}
async function nextPreview() {
  const box = $("#preview"); box.replaceChildren();
  if (!P.queue.length) return;                         // the last message (loaded / skipped / why a PDF failed) stays on screen
  const [kind, file] = P.queue[0];
  const fd = new FormData(); fd.append("kind", kind); fd.append("file", file);
  let res;
  try { res = await api("/api/pdf/preview", { method: "POST", body: fd }); }
  catch (e) { P.queue.shift(); P.done++; showAlert(`${file.name}: ${e.message}`); return nextPreview(); }   // e.g. scanned PDF: say why, go on with the next file
  const step = P.total > 1 ? ` (file ${P.done + 1} of ${P.total})` : "";
  const finish = async (msg) => { P.queue.shift(); P.done++; if (msg) showAlert(msg, "info"); await nextPreview(); };
  const skip = h("button", { class: "btn", type: "button", onclick: () => finish("Skipped " + file.name + ".") }, "Skip this file");
  if (kind === "students") box.append(studentPreview(res, step, skip, finish));
  else if (kind === "rooms") box.append(roomsPreview(res, step, skip, finish));
  else box.append(schedulePreview(res, step, skip, finish));
  box.scrollIntoView({ behavior: "smooth", block: "start" });
}
function studentPreview(res, step, skip, finish) {
  const rows = res.rows.map(r => ({ ...r }));
  const sel = h("select", { "aria-label": "Group this list belongs to" }, h("option", { value: "" }, "Choose group…"),
    res.groups.map(g => h("option", { value: g, selected: g === res.suggested_group }, g)));
  const count = h("b", {});
  const btn = h("button", { class: "btn primary", type: "button" });
  /* Feedback under the dropdown. It only labels which batch this PDF belongs to (the rows always come from the PDF), so it says
     plainly what loading will do: replace an existing list or add a new one. Counts come from the data already loaded. */
  const prefix = (rows[0] ? rows[0].roll_no : "").slice(0, 7);
  const loadedCount = g => ((state.data && state.data.cohorts) || []).find(c => c.group === g);
  const note = h("p", { class: "group-note", role: "status" });
  const loadedNote = res.already_loaded.length ? h("p", { class: "muted" }) : null;
  const update = () => { const n = rows.filter(r => r.include).length; count.textContent = n; btn.textContent = sel.value ? `Load these ${n} students into ${sel.value}` : `Load these ${n} students`; };
  const showGroup = () => {
    const g = sel.value, old = loadedCount(g);
    let text, kind;
    if (!g) { text = "Choose which group this list belongs to."; kind = "none"; }
    else if (res.already_loaded.includes(g)) { text = `Loading this will replace the existing ${g} list${old ? ` (${old.students} students)` : ""}.`; kind = "replace"; }
    else { text = `New list: no ${g} list is loaded yet.`; kind = "new"; }
    if (g && res.suggested_group && g !== res.suggested_group) text += ` These roll numbers (${prefix}…) normally mean ${res.suggested_group}.`;
    if (g && !res.suggested_group) text += " The group could not be guessed from the roll numbers, so check it yourself.";
    note.textContent = text; note.className = "group-note " + kind;
    if (loadedNote) loadedNote.textContent = "Already loaded: " + res.already_loaded.map(x => x === g ? x + " (this list will replace it)" : x).join(", ") + ".";
    update();
  };
  sel.addEventListener("change", () => { showGroup(); Motion.crossfade(note); });
  const body = h("tbody", {}, rows.map(r => h("tr", { class: r.include ? "" : "off-row" },
    h("td", {}, h("input", { type: "checkbox", checked: r.include, "aria-label": "Include " + r.roll_no, onchange: ev => { r.include = ev.target.checked; ev.target.closest("tr").classList.toggle("off-row", !r.include); update(); } })),
    h("td", { class: "c-code" }, h("input", { type: "text", value: r.roll_no, "aria-label": "Roll number", oninput: ev => { r.roll_no = ev.target.value; } })),
    h("td", { class: "c-name" }, h("input", { type: "text", value: r.name, "aria-label": "Name", oninput: ev => { r.name = ev.target.value; } })),
    h("td", { class: r.note ? "note-cell" : "" }, r.note))));
  btn.addEventListener("click", () => busy(btn, "Loading…", async () => {
    if (!sel.value) throw new Error("Choose which group this list belongs to first.");
    const d = await api("/api/students/confirm", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group: sel.value, rows: rows.map(({ roll_no, name, include }) => ({ roll_no, name, include })) }) });
    state.data = d; state.plan = null; state.current = 0; state.courses = Object.keys(d.course_names || {}).sort();
    renderSummary(); renderPlan(); setDownloads(); await Promise.all([loadRoomsTab(), loadTimetable()]);
    await finish(`Loaded ${rows.filter(r => r.include).length} students for ${sel.value}. ${d.students} students in total. Load the other lists, or go to Seating plan.`);
  }));
  showGroup();
  return h("div", { class: "card preview" },
    h("h2", {}, "Check the student list" + step),
    h("p", { class: "muted" }, h("b", {}, res.filename), ` · ${res.pages} page${res.pages === 1 ? "" : "s"}. Only the roll number and name were taken from the PDF. Fix anything that looks wrong, untick students who should not be loaded, then load the list.`),
    res.warnings.length ? h("ul", { class: "warns" }, res.warnings.map(w => h("li", {}, w))) : null,
    loadedNote,
    h("div", { class: "toolbar" }, h("label", {}, "This list is for ", sel), h("span", { class: "spacer" }), h("span", { class: "muted", style: "margin:0" }, count, " of " + rows.length + " ticked")),
    note,
    h("div", { class: "tbl-wrap prev-tbl" }, h("table", { class: "tt" }, h("thead", {}, h("tr", {}, ["Load", "Roll number", "Name", "Note"].map(x => h("th", {}, x)))), body)),
    res.ignored.length ? h("details", { class: "notes", open: true }, h("summary", {}, `Not loaded: ${res.ignored.length} line(s) with no roll number`), h("ul", {}, res.ignored.map(x => h("li", {}, x)))) : null,
    h("div", { class: "toolbar" }, btn, skip));
}
function roomsPreview(res, step, skip, finish) {
  const btn = h("button", { class: "btn primary", type: "button" }, "Use these rooms");
  btn.addEventListener("click", () => busy(btn, "Loading…", async () => {
    await api("/api/rooms", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rooms: res.rooms }) });
    await loadRoomsTab(); await afterEdit(); await finish("Rooms loaded from the PDF. Check each one on the Rooms tab.");
  }));
  return h("div", { class: "card preview" }, h("h2", {}, "Check the rooms" + step),
    h("p", { class: "muted" }, `${res.filename}. These rooms will replace the ones on the Rooms tab. You can correct any seat there afterwards.`),
    table(["Room", "Name", "Size", "Seats"], res.rooms.map(r => [r.room_id, r.name, `${r.rows} × ${r.cols}`, r.capacity])),
    h("div", { class: "toolbar" }, btn, skip));
}
function schedulePreview(res, step, skip, finish) {
  const btn = h("button", { class: "btn primary", type: "button" }, "Use this timetable");
  btn.addEventListener("click", () => busy(btn, "Loading…", async () => {
    await api("/api/timetable", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows: res.rows }) });
    await loadTimetable(); await afterEdit(); await finish("Timetable loaded from the PDF. Check it on the Timetable tab.");
  }));
  return h("div", { class: "card preview" }, h("h2", {}, "Check the timetable" + step),
    h("p", { class: "muted" }, `${res.filename}. This will replace the Timetable tab. Check the dates and paper codes.`),
    res.warnings.length ? h("ul", { class: "warns" }, res.warnings.map(w => h("li", {}, w))) : null,
    table(["Date", "Time", "Paper code", "Paper name", "Group"], res.rows.map(r => [fmtDate(r.date), r.slot, r.course, r.course_name, r.group])),
    h("div", { class: "toolbar" }, btn, skip));
}

function onLoaded(d) {
  state.data = d; state.plan = null; state.current = 0;
  state.courses = Object.keys(d.course_names || {}).sort();
  renderSummary(); renderPlan(); setDownloads();
  showAlert(`Loaded ${d.students} students, ${d.rooms.length} rooms and ${d.sessions.length} exam sessions. Next: generate the seating.`, "info");
  openTab("plan");
}
const paperCount = d => new Set(d.sessions.flatMap(s => s.courses)).size;
function table(head, rows) {
  return h("div", { class: "tbl-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, head.map(x => h("th", {}, x)))),
    h("tbody", {}, rows.map(r => h("tr", {}, r.map(c => h("td", {}, c)))))));
}
function renderSummary() {
  const d = state.data, box = $("#summary"); box.replaceChildren();
  if (!d) return;
  box.append(h("div", { class: "card" },
    h("h2", {}, "What was loaded"),
    h("div", { class: "stats" },
      [["Students", d.students], ["Papers", paperCount(d)], ["Rooms", d.rooms.length], ["Exam sessions", d.sessions.length]]
        .map(([l, n]) => h("div", { class: "stat" }, h("b", { "data-count": n }, n), l))),
    d.cohorts && d.cohorts.length ? h("div", { class: "legend", style: "margin-top:12px" }, h("span", { class: "muted", style: "margin:0" }, "Student lists loaded:"),
      d.cohorts.map(c => h("span", { class: "chip" }, `${c.group} · ${c.students}`,
        h("button", { class: "x", title: "Remove this list", "aria-label": "Remove list " + c.group, onclick: () => removeList(c.group) }, "×")))) : null,
    d.warnings.length ? h("ul", { class: "warns" }, d.warnings.map(w => h("li", {}, w))) : null,
    h("div", { class: "two", style: "margin-top:16px" },
      h("div", {}, h("h3", { style: "margin-bottom:8px" }, "Rooms"),
        table(["Room", "Name", "Size", "Seats", "Available"], d.rooms.map(r => [r.room_id, h("span", {}, r.name, r.provisional ? provTag() : null), `${r.rows} × ${r.cols}`, r.capacity, r.available ? "yes" : "no"]))),
      h("div", {}, h("h3", { style: "margin-bottom:8px" }, "Exam schedule"),
        table(["Date", "Time", "Papers"], d.sessions.map(s => [fmtDate(s.date), s.slot, s.courses.join(", ")]))))));
  Motion.countAll(box); Motion.enter(box.children);    // numbers count up, the card rises in
}

async function removeList(group) {
  if (!confirm(`Remove the loaded list for ${group}?`)) return;
  try {
    const d = await api("/api/students/" + encodeURIComponent(group), { method: "DELETE" });
    state.plan = null; state.data = d.rooms ? d : null; if (!state.data) state.courses = [];
    renderSummary(); renderPlan(); setDownloads(); showAlert(`Removed the list for ${group}.`, "info");
  } catch (e) { showAlert(e.message); }
}

/* ---------- PLAN tab */
const RULE_LABEL = { horizontal: "Left and right", fourway: "Left, right, front and back" };
const STRAT_LABEL = { greedy: "Greedy (max-heap)", backtracking: "Backtracking (pruned)", hybrid: "Hybrid (greedy, then backtracking)" };
async function loadOptions() {
  try {
    const o = await api("/api/options");
    const fill = (sel, names, labels, def) => names.forEach(n => {
      const op = h("option", { value: n }, labels[n] || n); if (n === def) op.selected = true; sel.append(op);
    });
    fill($("#rule"), o.rules, RULE_LABEL, "fourway"); if (ADVANCED) fill($("#strategy"), o.strategies, STRAT_LABEL, "hybrid");
  } catch (e) { showAlert(e.message); }
}
function setDownloads() {
  document.querySelectorAll(".dl a[data-fmt]").forEach(a => {
    a.classList.toggle("off", !state.plan);
    if (state.plan) a.setAttribute("href", "/api/download/" + a.dataset.fmt); else a.removeAttribute("href");
  });
  const cmp = $("#compare-btn");           // advanced only; needs loaded data, not a plan
  if (cmp) {
    cmp.classList.toggle("off", !state.data);
    if (state.data) cmp.setAttribute("href", "/api/compare?rule=" + encodeURIComponent($("#rule").value)); else cmp.removeAttribute("href");
  }
}
$("#rule").addEventListener("change", () => setDownloads());
$("#plan-btn").addEventListener("click", () => {
  if (!state.data) return showAlert("Load your data on the Data tab first.");
  busy($("#plan-btn"), "Generating…", async () => {
    Motion.skeleton($("#plan-out"));                   // loading state while the API works
    try {
      const [plan] = await Promise.all([api("/api/plan", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rule: $("#rule").value, strategy: ADVANCED ? $("#strategy").value : "hybrid" }) }), Motion.minDelay(300)]);
      state.plan = plan; state.current = 0; renderPlan("fresh"); setDownloads();
    } catch (e) { renderPlan(); throw e; }             // on failure bring the previous view back, then show the error
  });
});

function findClashes(room, rule) {          // same rule as the backend, drawn on screen as a second opinion
  const at = {}; room.seats.forEach(s => { if (s.roll_no) at[s.row + "," + s.col] = s; });
  const steps = rule === "horizontal" ? [[0, 1]] : [[0, 1], [1, 0]], bad = new Set();
  for (const s of Object.values(at)) for (const [dr, dc] of steps) {
    const n = at[(s.row + dr) + "," + (s.col + dc)];
    if (n && n.course === s.course) { bad.add(s.row + "," + s.col); bad.add(n.row + "," + n.col); }
  }
  return bad;
}
/* mode: "fresh" = a plan was just generated (seats pop in, numbers count up); "switch" = another session was chosen (crossfade). */
function renderPlan(mode) {
  const out = $("#plan-out"); out.replaceChildren(); out.removeAttribute("aria-busy");
  const p = state.plan;
  if (!p) {
    out.append(state.data
      ? emptyState("seats", "Ready to seat your students", "Choose how students may sit next to each other, then select Generate seating.",
          h("button", { class: "btn primary", type: "button", onclick: () => $("#plan-btn").click() }, "Generate seating"))
      : emptyState("upload", "No data yet", "Load your files on the Data tab, then come back here to build the plan.",
          h("button", { class: "btn primary", type: "button", onclick: () => openTab("data") }, "Go to Data tab")));
    return;
  }
  const s = p.sessions[state.current], fresh = mode === "fresh";
  out.append(h("div", { class: "stats" },
    [["Exam sessions", p.sessions.length], ["Could not seat", p.failed_sessions], ["Seating conflicts", p.total_conflicts]]
      .map(([l, n]) => h("div", { class: "stat" }, h("b", { class: n && l !== "Exam sessions" ? "bad" : "", "data-count": fresh ? n : null }, n), l))));
  const anyProv = p.sessions.some(x => x.rooms.some(r => r.provisional));
  const list = h("div", { class: "sessions" }, p.sessions.map((x, i) =>
    h("button", { class: "sess" + (x.ok ? "" : " bad"), "aria-current": i === state.current, onclick: () => { state.current = i; renderPlan("switch"); } },
      fmtDate(x.date), h("small", {}, x.slot + (x.ok ? "" : " · could not seat")))));
  const counts = {}; s.rooms.forEach(r => r.seats.forEach(t => { if (t.course) counts[t.course] = (counts[t.course] || 0) + 1; }));
  const main = h("div", {},
    h("div", { class: "sess-head" },
      h("h2", {}, `${fmtDate(s.date)}, ${s.slot}`),
      h("span", {}, h("span", { class: "badge " + (s.ok && !s.conflicts ? "ok" : "bad") },
        !s.ok ? "Failed" : s.conflicts ? `${s.conflicts} conflicts` : "No conflicts"), ` ${s.student_count} students`)),
    s.error ? h("div", { class: "alert error" }, s.error) : null,
    s.warnings.length ? h("ul", { class: "warns" }, s.warnings.map(w => h("li", {}, w))) : null,
    h("div", { class: "legend" },
      s.courses.map(c => h("span", { class: "chip", "data-course": c }, h("i", { class: "sw cc", style: courseColor(c) }), `${c}${p.course_names[c] ? " " + p.course_names[c] : ""} (${counts[c] || 0})`)),
      h("span", { class: "chip" }, h("i", { class: "sw blocked" }), "No seat"),
      h("span", { class: "chip" }, h("i", { class: "sw empty" }), "Empty seat")),
    s.rooms.map(r => roomCard(r, p.rule)),
    !s.rooms.length && s.ok ? h("div", { class: "empty-msg" }, "No rooms used for this session.") : null);
  if (anyProv) out.append(h("div", { class: "alert warn" }, "Rooms marked “Provisional layout” are estimates. Check them on the Rooms tab before printing or sharing this plan."));
  out.append(h("div", { class: "layout" }, list, main));
  if (fresh) {                                         // plan just generated: stagger the blocks, pop the seats, count the numbers
    Motion.enter(out.querySelectorAll(".stats, .sessions, .sess-head, .room"));
    Motion.pop(out.querySelectorAll(".seat:not(.blocked):not(.empty)")); Motion.countAll(out);
  } else if (mode === "switch") {
    Motion.crossfade(main);
    const cur = list.children[state.current]; if (cur) cur.focus({ preventScroll: true });   // keep keyboard focus on the chosen session
  }
}
function roomCard(r, rule) {
  const bad = findClashes(r, rule), free = r.seats.filter(t => t.empty).length;
  const grid = h("div", { class: "grid", style: `grid-template-columns:28px repeat(${r.cols},74px)` }, h("span"));
  for (let c = 1; c <= r.cols; c++) grid.append(h("span", { class: "cn" }, c));
  r.seats.forEach(t => {
    if (t.col === 1) grid.append(h("span", { class: "rn" }, t.row));
    const k = t.row + "," + t.col, pos = `Row ${t.row}, seat ${t.col}`;
    if (t.blocked) grid.append(h("div", { class: "seat blocked", title: pos + ": no seat" }));
    else if (t.empty) grid.append(h("div", { class: "seat empty", title: pos + ": empty" }));
    else grid.append(h("div", { class: "seat cc" + (bad.has(k) ? " clash" : ""), tabindex: 0, style: courseColor(t.course), "data-course": t.course,
      title: `${pos}: ${t.name} (${t.roll_no}), ${t.course}` }, h("b", {}, t.roll_no), h("span", {}, t.course)));
  });
  return h("div", { class: "card room" },
    h("div", { class: "room-head" }, h("h3", {}, `${r.room_id} · ${r.name}`, r.provisional ? provTag() : null),
      h("small", {}, `${r.students} students · ${r.rows}×${r.cols} · ${free} empty` + (ADVANCED ? ` · solved by ${r.strategy} (${r.search_nodes} search steps)` : ""))),
    h("div", { class: "board" }, "FRONT OF ROOM (row 1)"), h("div", { class: "gridscroll" }, grid),
    bad.size ? h("p", { class: "note bad" }, "Red outlines mark seats that break the rule.") : null);
}

/* After rooms or the timetable change, the old plan is stale: drop it and refresh the counts on the Data tab. */
async function afterEdit() {
  state.plan = null; state.current = 0;
  try {
    const r = await fetch("/api/data");
    if (r.ok) { state.data = await r.json(); state.courses = Object.keys(state.data.course_names || {}).sort(); renderSummary(); }
  } catch { /* data tab refreshes on next load */ }
  renderPlan(); setDownloads();
}
const unsaved = () => (R.draft.length && JSON.stringify(R.draft) !== R.saved) || (T.rows.length && JSON.stringify(T.rows) !== T.saved);
window.addEventListener("beforeunload", e => { if (unsaved()) { e.preventDefault(); e.returnValue = ""; } });
const cleanRoom = r => ({ room_id: r.room_id, name: r.name, layout: [...r.layout], available: r.available, provisional: r.provisional, note: r.note });

/* ---------- ROOMS tab: pick a room, click seats on/off, save */
const R = { draft: [], saved: "", sel: 0 };
const roomSeats = room => room.layout.reduce((n, line) => n + [...line].filter(ch => ch === "1").length, 0);
async function loadRoomsTab() {
  try { setRooms((await api("/api/rooms")).rooms); } catch (e) { showAlert(e.message); }
}
function setRooms(list) {
  R.draft = list.map(cleanRoom); R.saved = JSON.stringify(R.draft); R.sel = Math.min(R.sel, R.draft.length - 1);
  renderRooms();
}
function renderRooms() {
  const out = $("#rooms-out"); out.replaceChildren();
  if (!R.draft.length) return;
  const anyProv = R.draft.some(r => r.provisional);
  out.append(h("div", { class: "card" },
    h("h2", {}, "Rooms"),
    h("p", { class: "muted" }, "Pick a room, then click a seat to switch it on or off (you can also drag across several). Click a row or column number to switch the whole line. Row 1 is the front of the room. Two students on the same bench count as sitting next to each other."),
    anyProv ? h("div", { class: "alert warn", style: "margin:0" }, "Provisional layouts: the rooms marked Provisional are estimates until you confirm them. Correct each one here, then tick “Layout checked against the real room”.") : null));
  out.append(h("div", { class: "layout" }, h("div", { id: "room-list", class: "sessions" }), h("div", { id: "room-editor" })));
  renderRoomList(); renderRoomEditor();
}
function renderRoomList() {
  const box = $("#room-list"); if (!box) return; box.replaceChildren();
  R.draft.forEach((r, i) => box.append(h("button", { class: "sess", "aria-current": i === R.sel, onclick: () => { R.sel = i; renderRoomList(); renderRoomEditor(); Motion.crossfade($("#room-editor")); } },
    h("span", {}, `${r.room_id || "(no ID)"}`, r.provisional ? provTag() : null),
    h("small", {}, `${roomSeats(r)} seats` + (r.available ? "" : " · not in use")))));
  box.append(h("button", { class: "btn small", onclick: addRoom }, "+ Add room"));
}
function addRoom() {
  let n = R.draft.length + 1, id = "Room " + n;
  while (R.draft.some(r => r.room_id.toLowerCase() === id.toLowerCase())) id = "Room " + (++n);
  R.draft.push({ room_id: id, name: id, layout: Array(5).fill("11111111"), available: true, provisional: true, note: "New room: set the real layout." });
  R.sel = R.draft.length - 1; renderRoomList(); renderRoomEditor();
}
function renderRoomEditor() {
  const box = $("#room-editor"); if (!box) return; box.replaceChildren();
  const room = R.draft[R.sel]; if (!room) return;
  const rows = room.layout.length, cols = room.layout[0].length;
  const count = h("b", {}, roomSeats(room));
  const setCell = (r, c, on) => { const line = [...room.layout[r]]; line[c] = on ? "1" : "0"; room.layout[r] = line.join(""); };
  const cells = [];
  const paintCell = (el, on) => { el.classList.toggle("off", !on); el.setAttribute("aria-pressed", on); };
  let paint = null;                                    // while dragging: true = switching seats on, false = off
  const apply = (r, c) => { if (paint === null) return; setCell(r, c, paint); paintCell(cells[r][c], paint); count.textContent = roomSeats(room); renderRoomList(); };
  const stop = () => { paint = null; document.removeEventListener("pointerup", stop); };
  const grid = h("div", { class: "edit-grid", style: `grid-template-columns:28px repeat(${cols},36px)` }, h("span"));
  const flipLine = (cellsOfLine, setters) => { const any = cellsOfLine.some(([r, c]) => room.layout[r][c] === "1"); cellsOfLine.forEach(([r, c]) => setCell(r, c, !any)); renderRoomEditor(); renderRoomList(); };
  for (let c = 0; c < cols; c++) grid.append(h("button", { class: "edge", title: `Switch column ${c + 1} on or off`, onclick: () => flipLine(Array.from({ length: rows }, (_, r) => [r, c])) }, c + 1));
  for (let r = 0; r < rows; r++) {
    cells[r] = [];
    grid.append(h("button", { class: "edge", title: `Switch row ${r + 1} on or off`, onclick: () => flipLine(Array.from({ length: cols }, (_, c) => [r, c])) }, r + 1));
    for (let c = 0; c < cols; c++) {
      const on = room.layout[r][c] === "1";
      const el = h("button", { type: "button", class: "cell" + (on ? "" : " off"), "aria-pressed": String(on), "aria-label": `Row ${r + 1}, seat ${c + 1}`,
        title: `Row ${r + 1}, seat ${c + 1}`,
        onpointerdown: ev => { ev.preventDefault(); paint = room.layout[r][c] !== "1"; document.addEventListener("pointerup", stop); apply(r, c); },
        onpointerenter: () => apply(r, c),
        onkeydown: ev => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); paint = room.layout[r][c] !== "1"; apply(r, c); paint = null; } } });
      cells[r].push(el); grid.append(el);
    }
  }
  const resize = (dr, dc) => {
    const nr = rows + dr, nc = cols + dc;
    if (nr < 1 || nc < 1 || nr > 40 || nc > 40) return;
    room.layout = Array.from({ length: nr }, (_, r) => Array.from({ length: nc }, (_, c) => (r < rows && c < cols ? room.layout[r][c] : "1")).join(""));
    renderRoomEditor(); renderRoomList();
  };
  const field = (label, key, extra = {}) => h("label", {}, label, h("input", { type: "text", value: room[key], ...extra, oninput: ev => { room[key] = ev.target.value; renderRoomList(); } }));
  box.append(h("div", { class: "card" },
    h("div", { class: "room-head" }, h("h3", {}, room.name || room.room_id), h("small", {}, h("span", {}, count, ` seats · ${rows} rows × ${cols} columns`))),
    h("div", { class: "fields" }, field("Room ID", "room_id", { maxlength: 20 }), field("Name", "name", { maxlength: 40 }),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: room.available, onchange: ev => { room.available = ev.target.checked; renderRoomList(); } }), "Use this room"),
      h("label", { class: "check" }, h("input", { type: "checkbox", checked: !room.provisional, onchange: ev => { room.provisional = !ev.target.checked; renderRoomList(); } }), "Layout checked against the real room")),
    h("div", { class: "board" }, "FRONT OF ROOM (row 1)"),
    h("div", { class: "gridscroll" }, grid),
    h("div", { class: "toolbar" },
      h("button", { class: "btn small", onclick: () => resize(1, 0) }, "+ Row"), h("button", { class: "btn small", onclick: () => resize(-1, 0) }, "− Row"),
      h("button", { class: "btn small", onclick: () => resize(0, 1) }, "+ Column"), h("button", { class: "btn small", onclick: () => resize(0, -1) }, "− Column"),
      h("span", { class: "spacer" }),
      h("button", { class: "btn small", onclick: () => { if (R.draft.length < 2) return showAlert("At least one room is needed."); if (!confirm(`Delete ${room.room_id}?`)) return; R.draft.splice(R.sel, 1); R.sel = Math.max(0, R.sel - 1); renderRoomList(); renderRoomEditor(); } }, "Delete this room")),
    h("label", { class: "fields", style: "display:block;margin:6px 0 0" }, h("span", { style: "font-size:.8rem;color:var(--muted);font-weight:500" }, "Notes"),
      h("textarea", { oninput: ev => { room.note = ev.target.value; } }, room.note))));
  box.append(h("div", { class: "card toolbar", style: "margin-top:0" },
    h("button", { class: "btn primary", id: "rooms-save", onclick: ev => busy(ev.target, "Saving…", async () => {
      setRooms((await api("/api/rooms", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rooms: R.draft }) })).rooms);
      await afterEdit(); showAlert("Rooms saved. Generate the seating again to use them.", "info"); }) }, "Save rooms"),
    h("button", { class: "btn", onclick: () => busy($("#rooms-save"), "Reloading…", loadRoomsTab) }, "Discard changes"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn", onclick: ev => { if (!confirm("Go back to the starting rooms (B-002 to B-005, provisional)? Your changes to the rooms will be lost.")) return;
      busy(ev.target, "Resetting…", async () => { setRooms((await api("/api/rooms/reset", { method: "POST" })).rooms); await afterEdit(); showAlert("Rooms reset to the starting layouts.", "info"); }); } }, "Reset to starting rooms")));
}

/* ---------- TIMETABLE tab: one row per paper; edit any cell, add or delete rows, save */
const T = { rows: [], saved: "", days: 0, warnings: [] };
async function loadTimetable() {
  try { setTimetable(await api("/api/timetable")); } catch (e) { showAlert(e.message); }
}
function setTimetable(d) {
  T.rows = d.rows.map(r => ({ date: r.date, slot: r.slot, course: r.course, course_name: r.course_name, group: r.group || "" }));
  T.saved = JSON.stringify(T.rows); T.days = d.days; T.warnings = d.warnings || [];
  renderTimetable();
}
const ISO = /^\d{4}-\d{2}-\d{2}$/;
function renderTimetable() {
  const out = $("#timetable-out"); out.replaceChildren();
  const cell = (row, key, cls, type = "text") => h("td", { class: cls }, h("input", { type, value: row[key], "aria-label": key.replace("_", " "),
    oninput: ev => { row[key] = ev.target.value; updateCount(); } }));
  const count = h("span", { class: "muted", style: "margin:0" });
  function updateCount() { count.textContent = `${T.rows.filter(r => r.date && r.course).length} papers on ${new Set(T.rows.filter(r => r.date && r.course).map(r => r.date)).size} exam days`; }
  const body = h("tbody", {}, T.rows.map((row, i) => h("tr", {},
    cell(row, "date", "c-date", ISO.test(row.date) || !row.date ? "date" : "text"), cell(row, "slot", "c-slot"), cell(row, "course", "c-code"),
    cell(row, "course_name", "c-name"), cell(row, "group", "c-grp"),
    h("td", {}, h("button", { class: "x", title: "Delete this row", "aria-label": `Delete row ${i + 1}`, onclick: () => { T.rows.splice(i, 1); renderTimetable(); } }, "×")))));
  updateCount();
  out.append(h("div", { class: "card" },
    h("h2", {}, "Exam timetable"),
    h("p", { class: "muted" }, "One row per paper. Check every row against the printed timetable: the dates were matched to the papers by row order, so a slip is possible. Change any cell to correct it. The seating plan uses this table."),
    T.warnings.length ? h("ul", { class: "warns" }, T.warnings.map(w => h("li", {}, w))) : null,
    h("div", { class: "tbl-wrap" }, h("table", { class: "tt" }, h("thead", {}, h("tr", {}, ["Date", "Time", "Paper code", "Paper name", "Group", ""].map(x => h("th", {}, x)))), body)),
    h("div", { class: "toolbar" },
      h("button", { class: "btn small", onclick: () => { const last = T.rows[T.rows.length - 1] || {}; T.rows.push({ date: "", slot: last.slot || "", course: "", course_name: "", group: last.group || "" }); renderTimetable(); const inputs = $$all("#timetable-out tbody tr:last-child input"); if (inputs[0]) inputs[0].focus(); } }, "+ Add row"),
      h("button", { class: "btn small", onclick: () => { T.rows.sort((a, b) => (a.date || "￿").localeCompare(b.date || "￿")); renderTimetable(); } }, "Sort by date"),
      h("span", { class: "spacer" }), count),
    h("details", { class: "notes" }, h("summary", {}, "Notes about this timetable"), h("ul", {},
      h("li", {}, "Papers are told apart by their code. Papers with the same name but different codes (for example Forecasting Methods DS5A-601, DS5B-603 and DS6A-404) are treated as different papers. Two groups that share one code (DS6A-603 on 30 Nov) are one paper."),
      h("li", {}, "DS5A-623 (Marketing Analytics, printed on 23 Nov) is not listed because the MBA group does not write it. M.Tech sem 3 writes only Numerical Methods for DS6A-204, not Engineering Economics."),
      h("li", {}, "The Group column is only a label for checking the table. Students for each paper come from the student list.")))));
  out.append(h("div", { class: "card toolbar", style: "margin-top:0" },
    h("button", { class: "btn primary", id: "tt-save", onclick: ev => busy(ev.target, "Saving…", async () => {
      setTimetable(await api("/api/timetable", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rows: T.rows }) }));
      await afterEdit(); showAlert("Timetable saved. Generate the seating again to use it.", "info"); }) }, "Save timetable"),
    h("button", { class: "btn", onclick: () => busy($("#tt-save"), "Reloading…", loadTimetable) }, "Discard changes"),
    h("span", { class: "spacer" }),
    h("button", { class: "btn", onclick: ev => { if (!confirm("Go back to the timetable as first typed in? Your changes to the timetable will be lost.")) return;
      busy(ev.target, "Resetting…", async () => { setTimetable(await api("/api/timetable/reset", { method: "POST" })); await afterEdit(); showAlert("Timetable reset.", "info"); }); } }, "Reset to printed timetable")));
}
const $$all = (s, r = document) => [...r.querySelectorAll(s)];

/* ---------- EXPERIMENTS tab */
const LAB = ADVANCED ? [
  ["solver", "Design & Analysis of Algorithms", "Solver scaling", "Greedy, backtracking and hybrid solvers on an empty n×n room (about 80% full, 3 courses). Search steps show how much work each one does."],
  ["feasibility", "Design & Analysis of Algorithms", "Feasibility check", "Counting how many same-course students a room can hold: simple runs of seats (left/right) vs bipartite matching (four-way)."],
  ["bitmask", "Computer Architecture", "Bitmask conflict check", "Checking a row with mask & (mask << 1) instead of comparing every seat."],
  ["memory", "Computer Architecture", "Memory layout", "Flat array vs list of lists, walked row by row and column by column."]] : [];
const ms = t => { const n = parseFloat(t); return isNaN(n) ? 0 : n; };
async function loadLab() {
  if (state.labDone || state.labBusy) return;
  state.labBusy = true; const out = $("#lab-out");
  out.replaceChildren(h("div", { class: "empty-msg" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Running the timing experiments. This takes a few seconds…"));
  try {
    const d = await api("/api/benchmarks"); out.replaceChildren();
    LAB.forEach(([key, subject, title, blurb]) => {
      const rows = d.rows.filter(r => r.experiment === key), max = {};
      rows.forEach(r => max[r.size] = Math.max(max[r.size] || 0, ms(r.time)));
      out.append(h("div", { class: "card" }, h("h2", {}, title), h("p", { class: "muted" }, subject + ". " + blurb),
        h("div", { class: "tbl-wrap bars" }, h("table", {}, h("thead", {}, h("tr", {}, ["Size", "Items", "Variant", "Time", "Note"].map(x => h("th", {}, x)))),
          h("tbody", {}, rows.map(r => h("tr", {}, h("td", {}, r.size), h("td", {}, r.n), h("td", {}, r.variant),
            h("td", { class: "t", style: "min-width:130px" }, r.time, h("i", { class: "bar-t", style: `width:${max[r.size] ? Math.max(2, ms(r.time) / max[r.size] * 100) : 0}%` })),
            h("td", {}, String(r.note)))))))));
    });
    out.append(h("div", { class: "alert info" }, d.note));
    state.labDone = true;
  } catch (e) { out.replaceChildren(); showAlert(e.message); }
  state.labBusy = false;
}

/* ---------- start: dropdowns, and restore the loaded data if the server still has it */
(async function init() {
  await loadOptions(); renderPlan(); setDownloads();
  await Promise.all([loadRoomsTab(), loadTimetable()]);
  try { const d = await fetch("/api/data"); if (d.ok) { const j = await d.json(); state.data = j; state.courses = Object.keys(j.course_names || {}).sort(); renderSummary(); renderPlan(); setDownloads(); } } catch { /* nothing loaded yet */ }
})();
