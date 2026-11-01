"use strict";
/* global loadPrefs, savePrefs, applyPrefs, DEFAULT_PREFS */

const $ = (sel) => document.querySelector(sel);
const KIND_LABEL = { file: "ไฟล์", note: "โน้ต", bookmark: "ลิงก์", password: "รหัสผ่าน" };

// Simple stroke icons (24×24), drawn for this app.
const ICONS = {
  file: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  note: '<path d="M5 4h14v11l-5 5H5z"/><path d="M14 20v-5h5M9 9h6M9 12.5h4"/>',
  bookmark: '<path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/>',
  password: '<circle cx="8" cy="15" r="4"/><path d="m11 12 8-8M16 7l2 2M14 9l2 2"/>',
  lock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  unlock: '<rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  open: '<path d="M14 4h6v6M20 4l-9 9M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4"/>',
  upload: '<path d="M12 15V4M7.5 8.5 12 4l4.5 4.5M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"/>',
  download: '<path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 15v3a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-3"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
  palette: '<path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.5-.8 1.5-1.6 0-1.2-1-1.6-1-2.6 0-.9.7-1.6 1.6-1.6H16a5 5 0 0 0 5-5c0-4-4-7.2-9-7.2z"/><circle cx="7.5" cy="11" r="1.2"/><circle cx="10.5" cy="7" r="1.2"/><circle cx="15" cy="7.5" r="1.2"/>',
  layout: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16M9 10h12"/>',
  keyboard: '<rect x="2.5" y="6" width="19" height="12" rx="2"/><path d="M6 10h.01M10 10h.01M14 10h.01M18 10h.01M7 14h10"/>',
  activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
  reset: '<path d="M4 12a8 8 0 1 0 2.4-5.7L4 8.5"/><path d="M4 4v4.5h4.5"/>',
  lines: '<path d="M8 6h12M8 12h12M8 18h8"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
  check: '<path d="m5 12 5 5 9-10"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  filter: '<path d="M4 5h16l-6 7.5V19l-4 1.5v-8z"/>',
  sort: '<path d="M7 4v16M3.5 16.5 7 20l3.5-3.5M14 6h7M14 11h5M14 16h3"/>',
  play: '<path d="M8 5.5v13l11-6.5z" fill="currentColor"/>',
  pointer: '<path d="M6 3l12 7-5.5 1.5L10 17z"/><path d="m12.5 11.5 5 5"/>',
};
const icon = (name) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("class", "icon");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICONS[name]; // static, trusted markup
  return s;
};

let prefs = loadPrefs();
const state = {
  status: null, kind: "", results: [], selected: -1, detailId: null, seq: 0,
  // paging: what the list was searched with, total (null = still counting), more pages?
  page: null, total: null, approx: false, hasMore: false, loadingMore: false, moreError: false,
};
const isSide = () => document.documentElement.dataset.detailMode === "side";

// ------------------------------------------------------------------ helpers
async function api(path, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts); // opts.signal lets callers cancel
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) {
    const err = new Error((data && data.detail) || res.statusText);
    err.status = res.status;
    throw err;
  }
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null && v !== false) node.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    node.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return node;
}

/** Render text with query terms wrapped in <mark>, without using innerHTML. */
function highlight(text, terms) {
  const frag = document.createDocumentFragment();
  if (!text) return frag;
  const words = terms.filter(Boolean).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!words.length) { frag.append(text); return frag; }
  const re = new RegExp(`(${words.join("|")})`, "gi");
  let last = 0;
  for (const m of text.matchAll(re)) {
    if (m.index > last) frag.append(text.slice(last, m.index));
    frag.append(el("mark", {}, m[0]));
    last = m.index + m[0].length;
  }
  frag.append(text.slice(last));
  return frag;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 2200);
}

const isDesktop = () => !!state.status?.desktop;

async function copyText(text) {
  // In the desktop app the window's own clipboard access may be refused
  // (WebView2/WebKit): the app puts it on the system clipboard instead.
  if (isDesktop()) {
    try { await api("/api/clipboard", { method: "POST", body: { text } }); return true; } catch { /* fall through */ }
  }
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const ta = el("textarea", { style: "position:fixed;opacity:0;user-select:text" }, text);
    document.body.append(ta); ta.focus(); ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return ok;
  }
}

async function copy(text, label = "คัดลอกแล้ว") {
  toast(await copyText(text) ? label : "คัดลอกไม่ได้ ลองเลือกข้อความแล้วกด Ctrl+C");
}

// The desktop window has no right-click menu of its own (pywebview turns it
// off): offer Copy / Select all where it makes sense.
function selectedText() {
  const a = document.activeElement;
  if (a && (a.tagName === "INPUT" || a.tagName === "TEXTAREA") && a.selectionStart !== a.selectionEnd) {
    return a.value.slice(a.selectionStart, a.selectionEnd);
  }
  return String(window.getSelection() || "");
}

function closeContextMenu() { document.querySelector(".ctx-menu")?.remove(); }

document.addEventListener("contextmenu", (e) => {
  if (!isDesktop()) return; // a normal browser has its own menu
  e.preventDefault();
  closeContextMenu();
  const text = selectedText();
  const field = e.target.closest("input, textarea, pre, .vbody, #detail, .results");
  const items = [];
  if (text) items.push(["คัดลอก", async () => { await copy(text); }]);
  if (field) items.push(["เลือกทั้งหมด", () => {
    if (field.select) { field.focus(); field.select(); return; }
    const r = document.createRange(); r.selectNodeContents(field);
    const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
  }]);
  if (!items.length) return;
  const menu = el("div", { class: "ctx-menu", role: "menu" }, items.map(([label, run]) =>
    el("button", { type: "button", class: "menu-item", role: "menuitem", onclick: () => { closeContextMenu(); run(); } }, label)));
  document.body.append(menu);
  const w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = `${Math.min(e.clientX, innerWidth - w - 8)}px`;
  menu.style.top = `${Math.min(e.clientY, innerHeight - h - 8)}px`;
});
document.addEventListener("mousedown", (e) => { if (!e.target.closest(".ctx-menu")) closeContextMenu(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeContextMenu(); }, true);
window.addEventListener("blur", closeContextMenu);

function fmtSize(n) {
  if (n == null) return "";
  const u = ["B", "KB", "MB", "GB"]; let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}
const fmtDate = (ts) => (ts ? new Date(ts * 1000).toLocaleString("th-TH", { dateStyle: "medium", timeStyle: "short" }) : "");
const fmtShortDate = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString("th-TH", { day: "numeric", month: "short", year: "2-digit" }) : "");
const terms = () => $("#q").value.trim().split(/\s+/).filter(Boolean);
const safeUrl = (u) => (/^(https?|ftp):\/\//i.test(u) ? u : /^[\w.-]+\.[a-z]{2,}/i.test(u) ? `https://${u}` : null);
const ext = (name) => { const m = /\.([^.\/]+)$/.exec(name || ""); return m ? m[1].toUpperCase() : "—"; };
const tile = (kind) => el("div", { class: `tile ${kind}` }, icon(kind === "upload" ? "upload" : kind));
const btn = (label, onclick, cls = "secondary", iconName = null, attrs = {}) =>
  el("button", { type: "button", class: `btn ${cls}`, onclick, ...attrs }, iconName ? icon(iconName) : null, label);

// ------------------------------------------------------------------- modal
/**
 * Show a form dialog. On submit, `action(values)` runs; if it throws, the error
 * is shown and the dialog stays open. Resolves with action's result, or null if cancelled.
 */
function modalLoop(title, fields, action, { submit = "บันทึก", note = null } = {}) {
  return new Promise((resolve) => {
    const dlg = $("#modal");
    const form = $("#modal-form");
    form.replaceChildren(el("h2", {}, title));
    if (note) form.append(el("p", { class: "note" }, note));
    const inputs = {};
    for (const f of fields) {
      const input = f.type === "textarea"
        ? el("textarea", { name: f.name, placeholder: f.placeholder || "" }, f.value || "")
        : el("input", { name: f.name, type: f.type || "text", placeholder: f.placeholder || "", value: f.value || "", autocomplete: f.autocomplete || "off" });
      input.required = !!f.required;
      inputs[f.name] = input;
      const box = el("div", { class: "input" }, input,
        f.generate ? btn("สุ่ม", () => { input.value = genPassword(); input.type = "text"; }, "ghost sm") : null);
      form.append(el("div", { class: "field" }, el("label", {}, f.label), box));
    }
    const error = el("p", { class: "error" });
    let done = false;
    const finish = (value) => { if (!done) { done = true; resolve(value); } };
    form.append(error, el("div", { class: "actions-row" },
      btn("ยกเลิก", () => dlg.close(), "ghost"),
      el("button", { type: "submit", class: "btn primary" }, submit)));
    form.onsubmit = async (e) => {
      e.preventDefault();
      const values = Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, v.value]));
      try {
        const out = await action(values);
        // Resolve only after this dialog's own async "close" event has fired,
        // so it can't leak into a dialog opened right after (e.g. unlock → form).
        dlg.onclose = null;
        dlg.addEventListener("close", () => finish(out), { once: true });
        dlg.close();
      } catch (err) {
        error.textContent = err.message;
      }
    };
    dlg.onclose = () => finish(null);
    dlg.showModal();
    const first = Object.values(inputs)[0];
    if (first) first.focus();
  });
}

function genPassword(len = 20) {
  const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*-_=+";
  const buf = new Uint32Array(len);
  crypto.getRandomValues(buf);
  return Array.from(buf, (x) => chars[x % chars.length]).join("");
}

// ------------------------------------------------------------------ vault
async function ensureUnlocked() {
  await refreshStatus();
  const v = state.status.vault;
  if (v.unlocked) return true;
  if (!v.set_up) {
    const ok = await modalLoop("ตั้ง Master Password", [
      { name: "p1", label: "Master password (อย่างน้อย 8 ตัว)", type: "password", required: true, autocomplete: "new-password" },
      { name: "p2", label: "ยืนยันอีกครั้ง", type: "password", required: true, autocomplete: "new-password" },
    ], async (v) => {
      if (v.p1 !== v.p2) throw new Error("รหัสผ่านไม่ตรงกัน");
      await api("/api/vault/setup", { method: "POST", body: { master_password: v.p1 } });
      return true;
    }, { submit: "ตั้งค่า", note: "ใช้ปลดล็อกตู้รหัสผ่าน ถ้าลืมจะกู้รหัสผ่านที่เก็บไว้ไม่ได้" });
    await refreshStatus();
    return !!ok;
  }
  const ok = await modalLoop("ปลดล็อกตู้รหัสผ่าน", [
    { name: "p", label: "Master password", type: "password", required: true, autocomplete: "current-password" },
  ], async (v) => {
    await api("/api/vault/unlock", { method: "POST", body: { master_password: v.p } });
    return true;
  }, { submit: "ปลดล็อก" });
  await refreshStatus();
  return !!ok;
}

async function withVault(fn) {
  try {
    return await fn();
  } catch (e) {
    if (e.status !== 423) throw e;
    if (!(await ensureUnlocked())) return null;
    return fn();
  }
}

async function revealPassword(id) {
  const data = await withVault(() => api(`/api/items/${id}/reveal`, { method: "POST" }));
  return data && data.password;
}

async function toggleVault() {
  if (state.status.vault.unlocked) {
    await api("/api/vault/lock", { method: "POST" });
    toast("ล็อกตู้รหัสผ่านแล้ว");
    await refreshStatus();
  } else if (await ensureUnlocked()) {
    toast("ปลดล็อกแล้ว");
  }
}

// ----------------------------------------------------------------- search
let debounce;
function scheduleSearch() {
  clearTimeout(debounce);
  debounce = setTimeout(search, 80);
}

let searchAbort = null;
let moreAbort = null;
let countAbort = null;
let countTimer = null;

/** First page of a new search. Later pages load while scrolling (loadMore). */
async function search() {
  const seq = ++state.seq;
  const q = $("#q").value.trim();
  for (const ctl of [searchAbort, moreAbort, countAbort]) ctl?.abort(); // drop older requests
  clearTimeout(countTimer);
  if (!q && !prefs.recent && !state.kind) {
    // Settings → "รายการล่าสุด" is off: a blank start until the user types.
    Object.assign(state, { results: [], selected: -1, total: 0, approx: false, hasMore: false });
    renderResults();
    hideDetail();
    return;
  }
  searchAbort = new AbortController();
  state.page = { q, kind: state.kind, sort: prefs.sortBy };
  const params = new URLSearchParams({ ...state.page, limit: prefs.resultLimit, offset: 0 });
  try {
    const data = await api(`/api/search?${params}`, { signal: searchAbort.signal });
    if (seq !== state.seq) return; // a newer search already finished
    Object.assign(state, {
      results: data.results, selected: data.results.length ? 0 : -1,
      total: data.total, approx: data.approx, hasMore: data.has_more, loadingMore: false, moreError: false,
    });
    renderResults();
    if (isSide() && state.selected >= 0) showDetail(state.results[0].id);
    else hideDetail();
    if (data.total == null) scheduleCount(seq);
  } catch (e) {
    if (e.name === "AbortError") return;
    if (e.status === 401) return showLogin();
    toast(e.message);
  }
}

/** Ask for the total a moment after the user stops typing (counting can take a while). */
function scheduleCount(seq) {
  countTimer = setTimeout(async () => {
    countAbort = new AbortController();
    try {
      const c = await api(`/api/search/count?${new URLSearchParams(state.page)}`, { signal: countAbort.signal });
      if (seq !== state.seq) return;
      state.total = c.total;
      state.approx = c.approx;
      if (!c.approx && state.results.length >= c.total) state.hasMore = false;
      updateCount();
      updateSentinel();
    } catch (e) { /* aborted or failed: the list still works without a total */ }
  }, 350);
}

/** Next page, appended to the list. Safe to call often: one request at a time. */
async function loadMore() {
  if (!state.hasMore || state.loadingMore || !state.page) return;
  const seq = state.seq;
  state.loadingMore = true;
  state.moreError = false;
  updateSentinel();
  moreAbort = new AbortController();
  const params = new URLSearchParams({ ...state.page, limit: prefs.resultLimit, offset: state.results.length });
  try {
    const data = await api(`/api/search?${params}`, { signal: moreAbort.signal });
    if (seq !== state.seq) return;
    const have = new Set(state.results.map((r) => r.id));
    const rows = data.results.filter((r) => !have.has(r.id));
    const start = state.results.length;
    state.results.push(...rows);
    state.hasMore = data.has_more && rows.length > 0;
    if (data.total != null) { state.total = data.total; state.approx = data.approx; }
    appendRows(rows, start);
  } catch (e) {
    if (e.name === "AbortError") return;
    state.moreError = true;
  } finally {
    if (seq === state.seq) {
      state.loadingMore = false;
      updateCount();
      updateSentinel();
      // Still near the bottom (short pages)? Keep filling.
      if (!state.moreError) requestAnimationFrame(() => { observer.unobserve($("#load-more")); observer.observe($("#load-more")); });
    }
  }
}

const observer = new IntersectionObserver((entries) => {
  if (entries.some((e) => e.isIntersecting)) loadMore();
}, { rootMargin: "900px 0px" }); // start loading well before the end is visible

function resultMeta(r) {
  if (r.kind === "file") return [ext(r.title), fmtSize(r.size), fmtShortDate(r.mtime)];
  if (r.kind === "password") return [r.username, r.url];
  if (r.kind === "bookmark") return [r.url, ...(r.tags || []).map((t) => `#${t}`)];
  return [fmtShortDate(r.updated_at), ...(r.tags || []).map((t) => `#${t}`)];
}

function rowEl(r, i, t, animate) {
  const meta = resultMeta(r).filter(Boolean);
  return el("li", {
    class: `row${animate ? " reveal" : ""}${i === state.selected ? " selected" : ""}`, style: animate ? `--i:${Math.min(i, 12)}` : null,
    onclick: () => { select(i); if (!isSide()) openDetail(); },
    ondblclick: () => primaryAction(r),
  },
    tile(r.kind),
    el("div", { class: "copy" },
      el("div", { class: "title" }, highlight(r.title, t)),
      meta.length ? el("div", { class: "meta" }, meta.map((m, j) => el("span", { class: j ? "dot" : "" }, highlight(m, t)))) : null,
      r.snippet && r.kind !== "password" && t.length ? el("div", { class: "snip" }, highlight(r.snippet, t)) : null),
    canView(r) ? el("div", { class: "row-actions" },
      btn("ดูเนื้อหา", (e) => { e.stopPropagation(); openViewer(r); }, "secondary sm", "lines", { title: "ดูเนื้อหาพร้อมเลขบรรทัด" })) : null);
}

function updateCount() {
  const n = state.results.length;
  const t = terms();
  const label = state.kind ? KIND_LABEL[state.kind] : "";
  const fmt = (x) => Number(x).toLocaleString();
  let title = "";
  if (n) {
    if (!t.length) title = label || "ล่าสุด";
    else if (state.total == null) title = "ผลการค้นหา";
    else title = state.approx ? `พบมากกว่า ${fmt(state.total)} รายการ` : `พบ ${fmt(state.total)} รายการ`;
  }
  $("#result-title").textContent = title;
  let sub = "";
  if (n) {
    if (state.total == null) sub = `${fmt(n)}${state.hasMore ? "+" : ""} รายการ · กำลังนับ…`;
    else if (state.total > n) sub = `แสดง ${fmt(n)} จาก ${state.approx ? "มากกว่า " : ""}${fmt(state.total)}`;
    else if (!t.length) sub = `${fmt(state.total)} รายการ`; // searching: the title already says it
  }
  $("#result-count").textContent = sub;
}

function updateSentinel() {
  const s = $("#load-more");
  if (!s) return;
  const n = state.results.length;
  s.className = "load-more";
  if (state.loadingMore) {
    s.replaceChildren(el("span", { class: "spinner", "aria-hidden": "true" }), "กำลังโหลดเพิ่ม…");
  } else if (state.moreError) {
    s.replaceChildren("โหลดไม่สำเร็จ ", btn("ลองอีกครั้ง", () => loadMore(), "secondary sm"));
  } else if (state.hasMore) {
    s.replaceChildren(btn("โหลดเพิ่ม", () => loadMore(), "ghost sm")); // fallback if scrolling doesn't trigger
  } else if (n > prefs.resultLimit) {
    s.classList.add("end");
    s.replaceChildren(`แสดงครบ ${n.toLocaleString()} รายการแล้ว`);
  } else {
    s.replaceChildren();
  }
}

function renderResults() {
  const ul = $("#results");
  observer.disconnect();
  ul.replaceChildren();
  window.scrollTo({ top: 0 });
  const t = terms();
  updateCount();
  if (!state.results.length) {
    const fresh = !t.length;
    ul.append(el("li", { class: "empty reveal" },
      el("strong", {}, fresh ? "พิมพ์เพื่อค้นหา" : "ไม่พบผลลัพธ์"),
      fresh ? "หรือกด เพิ่ม เพื่ออัปโหลดไฟล์ จดโน้ต เก็บลิงก์ หรือรหัสผ่าน" : "ลองคำอื่น หรือคำที่ยาวขึ้น"));
    return;
  }
  const frag = document.createDocumentFragment();
  state.results.forEach((r, i) => frag.append(rowEl(r, i, t, true)));
  const sentinel = el("li", { id: "load-more", class: "load-more" });
  frag.append(sentinel);
  ul.append(frag);
  updateSentinel();
  observer.observe(sentinel);
}

/** Add rows before the "load more" marker without touching existing rows. */
function appendRows(rows, start) {
  if (!rows.length) return;
  const t = terms();
  const frag = document.createDocumentFragment();
  rows.forEach((r, k) => frag.append(rowEl(r, start + k, t, false)));
  $("#results").insertBefore(frag, $("#load-more"));
}

function select(i) {
  if (i < 0 || i >= state.results.length) return;
  const rows = $("#results").querySelectorAll("li.row");
  rows[state.selected]?.classList.remove("selected");
  state.selected = i;
  rows[i].classList.add("selected");
  rows[i].scrollIntoView({ block: "nearest" });
  if (i >= state.results.length - 15) loadMore(); // keyboard users reach the end too: fetch early
  // Side column follows the selection; a closed drawer stays closed.
  if (isSide() || $("#detail").classList.contains("open")) showDetail(state.results[i].id);
}

async function primaryAction(r) {
  if (r.kind === "file") return openFile(r.id);
  if (r.kind === "bookmark") { const u = safeUrl(r.url); if (u) window.open(u, "_blank", "noopener,noreferrer"); return; }
  if (r.kind === "password") { const p = await revealPassword(r.id); if (p != null) copy(p, "คัดลอกรหัสผ่านแล้ว"); return; }
  if (r.kind === "note") return editItem(r.id);
}

async function openFile(id) {
  if (state.status.can_open_files) {
    try { await api(`/api/files/${id}/open`, { method: "POST" }); toast("กำลังเปิดไฟล์…"); }
    catch (e) { toast(e.message); }
  } else {
    window.open(`/api/files/${id}/download`, "_blank");
  }
}

// ----------------------------------------------------------------- detail
function hideDetail() {
  $("#detail").replaceChildren();
  state.detailId = null;
  closeDetail();
}

function openDetail() {
  const r = state.results[state.selected];
  if (!r) return;
  if (!isSide()) {
    $("#detail").classList.add("open");
    $("#scrim").classList.remove("hidden");
  }
  showDetail(r.id);
}

function closeDetail() {
  $("#detail").classList.remove("open");
  if (!settingsOpen()) $("#scrim").classList.add("hidden");
}

const valueBox = (content, ...buttons) => el("div", { class: "valuebox" }, content, ...buttons);

async function showDetail(id) {
  const item = await api(`/api/items/${id}`);
  if (state.results[state.selected]?.id !== id) return; // selection moved on
  state.detailId = id;
  const t = terms();
  const box = $("#detail");
  box.replaceChildren();

  const parts = [];
  const sub = item.kind === "file" ? item.path : KIND_LABEL[item.kind];
  parts.push(el("div", { class: "head" }, tile(item.kind),
    el("div", { style: "min-width:0" }, el("h2", {}, highlight(item.title, t)), el("div", { class: "sub" }, sub)),
    btn("", closeDetail, "ghost icon-only sm close", "close", { title: "ปิด", "aria-label": "ปิด" })));

  if (item.kind === "file") {
    parts.push(el("div", { class: "stats" },
      el("div", {}, el("strong", {}, ext(item.title)), el("span", {}, "ชนิด")),
      el("div", {}, el("strong", {}, fmtSize(item.size)), el("span", {}, "ขนาด")),
      el("div", {}, el("strong", {}, fmtShortDate(item.mtime)), el("span", {}, "แก้ไขล่าสุด"))));
    parts.push(el("div", { class: "actions" },
      btn(state.status.can_open_files ? "เปิดไฟล์" : "ดาวน์โหลด", () => openFile(item.id), "primary", "open"),
      btn("ดูเนื้อหา", () => openViewer(item), "secondary", "lines"),
      btn("คัดลอก path", () => copy(item.path, "คัดลอก path แล้ว"), "secondary", "copy"),
      item.uploaded ? btn("ลบไฟล์", () => deleteItem(item), "danger", "trash") : null));
    const isImage = /\.(png|jpe?g|gif|webp|bmp)$/i.test(item.title);
    if (isImage) parts.push(el("img", { class: "preview", src: `/api/files/${item.id}/preview`, alt: item.title, loading: "lazy" }));
    parts.push(item.content
      ? el("pre", {}, highlight(item.content.slice(0, 20000).trimStart(), t))
      : el("p", { class: "secondary" }, isImage || /\.(tiff?)$/i.test(item.title)
        ? "ไม่พบข้อความในรูปนี้ (หรือยังอ่านไม่ถึง: การอ่านข้อความในรูปทำเบื้องหลังหลังสแกนเสร็จ)"
        : "ไม่มีเนื้อหาที่อ่านได้ (ค้นได้จากชื่อไฟล์)"));
    box.append(...parts.map((p, i) => withReveal(p, i)));
    return;
  }

  if ((item.kind === "bookmark" || item.kind === "password") && item.url) {
    const u = safeUrl(item.url);
    parts.push(el("div", { class: "field" }, el("label", {}, "URL"),
      valueBox(u ? el("a", { href: u, target: "_blank", rel: "noopener noreferrer", class: "value" }, item.url) : el("span", { class: "value" }, item.url),
        u ? btn("", () => window.open(u, "_blank", "noopener,noreferrer"), "ghost icon-only sm", "open", { title: "เปิดลิงก์" }) : null)));
  }
  if (item.kind === "password") {
    if (item.username) parts.push(el("div", { class: "field" }, el("label", {}, "Username"),
      valueBox(el("span", { class: "value" }, item.username), btn("", () => copy(item.username), "ghost icon-only sm", "copy", { title: "คัดลอก" }))));
    const secret = el("span", { class: "secret" }, "••••••••••••");
    let shown = false;
    const toggle = btn("", async () => {
      if (shown) { secret.textContent = "••••••••••••"; shown = false; return; }
      const p = await revealPassword(item.id);
      if (p == null) return;
      secret.textContent = p; shown = true;
    }, "ghost icon-only sm", "eye", { title: "แสดง/ซ่อน" });
    parts.push(el("div", { class: "field" }, el("label", {}, "Password"),
      valueBox(secret, toggle, btn("", async () => { const p = await revealPassword(item.id); if (p != null) copy(p, "คัดลอกรหัสผ่านแล้ว"); }, "ghost icon-only sm", "copy", { title: "คัดลอก" }))));
    parts.push(el("div", { class: "actions" },
      btn("คัดลอกรหัสผ่าน", async () => { const p = await revealPassword(item.id); if (p != null) copy(p, "คัดลอกรหัสผ่านแล้ว"); }, "primary", "copy")));
  }
  if (item.tags && item.tags.length) parts.push(el("ul", { class: "chips" }, item.tags.map((tag) => el("li", { class: "chip" }, `#${tag}`))));
  if (item.content) parts.push(el("pre", {}, highlight(item.content, t)));
  parts.push(el("div", { class: "sub" }, `แก้ไขล่าสุด ${fmtDate(item.updated_at)}`));
  parts.push(el("div", { class: "actions" },
    item.kind === "note" ? btn("ดูเนื้อหา", () => openViewer(item), "secondary", "lines") : null,
    btn("แก้ไข", () => editItem(item.id), "secondary", "edit"),
    btn("ลบ", () => deleteItem(item), "danger", "trash")));
  box.append(...parts.map((p, i) => withReveal(p, i)));
}

function withReveal(node, i) {
  node.classList.add("reveal");
  node.style.setProperty("--i", i);
  return node;
}

// ------------------------------------------------------------------ edit
async function editItem(id, kind) {
  const item = id ? await api(`/api/items/${id}`) : { kind, title: "", content: "", url: "", username: "", tags: [] };
  kind = item.kind;
  if (kind === "password" && !(await ensureUnlocked())) return;
  const fields = [{ name: "title", label: "ชื่อ", required: true, value: item.title }];
  if (kind !== "note") fields.push({ name: "url", label: "URL", value: item.url, placeholder: "https://…" });
  if (kind === "password") {
    fields.push({ name: "username", label: "Username / Email", value: item.username });
    fields.push({ name: "password", label: id ? "Password (เว้นว่างไว้ถ้าไม่เปลี่ยน)" : "Password", type: "password", generate: true, autocomplete: "new-password" });
  }
  fields.push({ name: "content", label: kind === "note" ? "เนื้อหา" : "หมายเหตุ", type: "textarea", value: item.content });
  fields.push({ name: "tags", label: "แท็ก (คั่นด้วยเว้นวรรค)", value: (item.tags || []).join(" "), placeholder: "งาน ส่วนตัว" });

  const saved = await modalLoop(`${id ? "แก้ไข" : "เพิ่ม"}${KIND_LABEL[kind]}`, fields, (v) => {
    const body = { kind, title: v.title, content: v.content, url: v.url || "", username: v.username || "", tags: v.tags.split(/\s+/).filter(Boolean) };
    if (kind === "password") body.password = id && !v.password ? null : v.password;
    return api(id ? `/api/items/${id}` : "/api/items", { method: id ? "PUT" : "POST", body }).catch((e) => {
      // The form dialog is open, so we can't stack the unlock dialog on top of it.
      if (e.status === 423) throw new Error("ตู้รหัสผ่านล็อกอยู่ — ยกเลิกแล้วปลดล็อกในหน้าตั้งค่าก่อน");
      throw e;
    });
  });
  if (saved) {
    toast("บันทึกแล้ว");
    await refreshStatus();
    await search();
    const idx = state.results.findIndex((r) => r.id === saved.id);
    if (idx >= 0) select(idx);
  }
}

async function deleteItem(item) {
  const what = item.kind === "file" ? `ลบไฟล์ "${item.title}" ออกจากเครื่อง/เซิร์ฟเวอร์?` : `ลบ "${item.title}" ?`;
  if (!confirm(what)) return;
  await api(`/api/items/${item.id}`, { method: "DELETE" });
  toast("ลบแล้ว");
  hideDetail();
  await refreshStatus();
  search();
}

// --------------------------------------------------------------- add menu
const ADD_ITEMS = [
  { key: "upload", label: "อัปโหลดไฟล์", hint: "ลากมาวางก็ได้", run: () => $("#upload-input").click() },
  { key: "note", label: "โน้ต", run: () => editItem(null, "note") },
  { key: "bookmark", label: "ลิงก์", run: () => editItem(null, "bookmark") },
  { key: "password", label: "รหัสผ่าน", run: () => editItem(null, "password") },
];

function toggleAddMenu(open = $("#add-menu").classList.contains("hidden")) {
  const menu = $("#add-menu");
  if (open) {
    menu.replaceChildren(...ADD_ITEMS.map((it) => el("button", {
      type: "button", class: "menu-item", role: "menuitem",
      onclick: () => { toggleAddMenu(false); it.run(); },
    }, tile(it.key), it.label, it.hint ? el("span", { class: "hint" }, it.hint) : null)));
    menu.classList.remove("hidden");
    menu.querySelector("button").focus();
  } else {
    menu.classList.add("hidden");
  }
  $("#add-btn").setAttribute("aria-expanded", String(open));
}

// ------------------------------------------------------------------- sort
const SORT_OPTIONS = [
  ["relevance", "เกี่ยวข้องที่สุด"], ["newest", "แก้ไขล่าสุด"], ["oldest", "เก่าที่สุด"],
  ["name", "ชื่อ ก→ฮ / A→Z"], ["name_desc", "ชื่อ ฮ→ก / Z→A"], ["largest", "ขนาดใหญ่สุด"], ["type", "ประเภท"],
];

function updateSortLabel() {
  const found = SORT_OPTIONS.find(([v]) => v === prefs.sortBy) || SORT_OPTIONS[0];
  $("#sort-label").textContent = found[1];
}

function toggleSortMenu(open = $("#sort-menu").classList.contains("hidden")) {
  const menu = $("#sort-menu");
  if (open) {
    menu.replaceChildren(...SORT_OPTIONS.map(([value, label]) => el("button", {
      type: "button", class: "menu-item", role: "menuitemradio", "aria-checked": String(value === prefs.sortBy),
      onclick: () => { toggleSortMenu(false); setPref("sortBy", value); },
    }, label, (() => { const c = icon("check"); c.classList.add("check"); return c; })())));
    menu.classList.remove("hidden");
    (menu.querySelector('[aria-checked="true"]') || menu.querySelector("button")).focus();
  } else {
    menu.classList.add("hidden");
  }
  $("#sort-btn").setAttribute("aria-expanded", String(open));
}

// ----------------------------------------------------------------- viewer
/*
 * Virtualised viewer: only the lines on screen exist in the page, and they
 * are fetched in chunks while scrolling. A 400,000-line log opens as fast
 * as a 40-line note, and memory stays flat.
 */
const canView = (r) => r && (r.kind === "file" || r.kind === "note");
const viewerOpen = () => !$("#viewer").classList.contains("hidden");
const LINE_H = 22;      // px per line (fixed, so position = line × LINE_H)
const VCHUNK = 400;     // lines per request
const OVERSCAN = 40;    // extra lines rendered above/below the screen
const MAX_CHUNKS = 60;  // chunks kept in memory (24,000 lines)
const MAX_SCROLL_PX = 15e6; // browsers cap element heights (~17-33M px): squeeze the scrollbar beyond this
const viewer = {
  info: null, gen: 0, chunks: new Map(), pending: new Set(), raf: 0, lastKey: "",
  scale: 1, // scroll px per line = LINE_H * scale (< 1 only for files with millions of lines)
  words: [], test: null, hits: [], hitLines: new Map(), current: -1, currentLine: -1,
  flashLine: -1, revealLine: -1, findAbort: null,
};

async function openViewer(item) {
  let info;
  try { info = await api(`/api/items/${item.id}/text`); }
  catch (e) { return toast(e.message); }
  viewer.gen++;
  Object.assign(viewer, { info, chunks: new Map(), pending: new Set(), lastKey: "", hits: [], hitLines: new Map(),
    current: -1, currentLine: -1, flashLine: -1, revealLine: -1 });
  $("#viewer .viewer-tile").replaceChildren(tile(info.kind));
  $("#viewer-title").textContent = info.title;
  const badge = info.kind === "note" ? "โน้ต" : info.source === "disk" ? "จากไฟล์จริง — เลขบรรทัดตรงกับไฟล์" : "ข้อความที่ดึงจากเอกสาร";
  $("#viewer-sub").replaceChildren(el("span", { class: "badge" }, badge),
    `${info.total_lines.toLocaleString()} บรรทัด`, info.size != null ? ` · ${fmtSize(info.size)}` : "", info.path ? ` · ${info.path}` : "");
  const code = $("#viewer-code");
  code.classList.toggle("mono", info.source === "disk");
  code.style.setProperty("--gutter", `${String(info.total_lines).length + 1}ch`);
  viewer.scale = Math.min(1, MAX_SCROLL_PX / (info.total_lines * LINE_H));
  code.replaceChildren(
    el("div", { class: "vspacer", style: `height:${Math.ceil(info.total_lines * LINE_H * viewer.scale) + 24}px` }),
    el("div", { class: "vwindow" }));
  code.scrollTop = 0;
  code.scrollLeft = 0;
  $("#viewer-line").max = info.total_lines;
  $("#viewer-line").value = "";
  $("#viewer-q").value = $("#q").value.trim();
  $("#viewer").classList.remove("hidden");
  renderWindow();
  runFind(true);
  $("#viewer-q").focus();
}

function closeViewer() {
  viewer.gen++;
  viewer.findAbort?.abort();
  $("#viewer").classList.add("hidden");
  $("#viewer-code").replaceChildren();
  $("#viewer-hits").replaceChildren();
  viewer.info = null;
  viewer.chunks = new Map();
  $("#q").focus();
}

/** [first, last) lines to draw, and where the drawn block goes (px). */
function visibleRange() {
  const c = $("#viewer-code");
  const total = viewer.info.total_lines;
  const exact = c.scrollTop / (LINE_H * viewer.scale); // line at the top edge
  const first = Math.max(0, Math.floor(exact) - OVERSCAN);
  const last = Math.min(total, Math.ceil(exact + c.clientHeight / LINE_H) + OVERSCAN);
  const top = c.scrollTop - (exact - first) * LINE_H; // equals first × LINE_H when not squeezed
  return [first, last, top];
}

async function ensureChunk(k) {
  if (viewer.chunks.has(k)) {
    const lines = viewer.chunks.get(k);
    viewer.chunks.delete(k); viewer.chunks.set(k, lines); // most recently used
    return;
  }
  if (viewer.pending.has(k)) return;
  viewer.pending.add(k);
  const gen = viewer.gen;
  try {
    const d = await api(`/api/items/${viewer.info.id}/text/lines?start=${k * VCHUNK}&count=${VCHUNK}`);
    if (gen !== viewer.gen) return;
    viewer.chunks.set(k, d.lines);
    while (viewer.chunks.size > MAX_CHUNKS) viewer.chunks.delete(viewer.chunks.keys().next().value);
    viewer.lastKey = "";
    scheduleRender();
  } catch (e) { /* closed or failed: placeholders stay */ }
  finally { if (gen === viewer.gen) viewer.pending.delete(k); }
}

function scheduleRender() {
  if (viewer.raf) return;
  viewer.raf = requestAnimationFrame(() => { viewer.raf = 0; renderWindow(); });
}

/** Draw only the lines in (and just around) the visible area. */
function renderWindow() {
  if (!viewer.info) return;
  const [first, last, top] = visibleRange();
  for (let k = Math.floor(first / VCHUNK); k <= Math.floor(Math.max(first, last - 1) / VCHUNK); k++) ensureChunk(k);
  const key = `${first}:${last}:${Math.round(top)}:${viewer.currentLine}:${viewer.flashLine}:${viewer.hits.length}:${viewer.words.join(" ")}`;
  if (key === viewer.lastKey) return; // nothing changed
  viewer.lastKey = key;
  const frag = document.createDocumentFragment();
  for (let n = first; n < last; n++) {
    const chunk = viewer.chunks.get(Math.floor(n / VCHUNK));
    const text = chunk ? chunk[n % VCHUNK] : null;
    const hit = viewer.hitLines.has(n) || (text != null && viewer.test && viewer.test.test(text));
    frag.append(el("div", {
      class: `vline${hit ? " has-hit" : ""}${n === viewer.currentLine ? " current" : ""}${n === viewer.flashLine ? " flash" : ""}${text == null ? " loading" : ""}`,
      "data-line": n + 1,
    }, el("span", { class: "ln" }, n + 1), el("span", { class: "lt" }, text == null ? "" : hit ? highlight(text, viewer.words) : text)));
  }
  const win = $("#viewer-code .vwindow");
  win.style.transform = `translateY(${top}px)`;
  win.replaceChildren(frag);
  if (viewer.revealLine >= 0) revealMatch();
}

/** After jumping to a hit, also scroll sideways so the word itself is visible. */
function revealMatch() {
  const mark = document.querySelector(`#viewer-code .vline[data-line="${viewer.revealLine + 1}"] mark`);
  if (!mark) return;
  viewer.revealLine = -1;
  const code = $("#viewer-code");
  const x = mark.offsetLeft;
  if (x < code.scrollLeft + 40 || x > code.scrollLeft + code.clientWidth - 80) code.scrollLeft = Math.max(0, x - 120);
}

let findDebounce;
async function runFind(jump = false) {
  if (!viewer.info) return;
  const words = $("#viewer-q").value.trim().split(/\s+/).filter(Boolean);
  viewer.words = words;
  viewer.test = words.length ? new RegExp(words.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|"), "i") : null;
  viewer.findAbort?.abort();
  viewer.hits = [];
  viewer.hitLines = new Map();
  viewer.current = -1;
  viewer.currentLine = -1;
  viewer.lastKey = "";
  if (!words.length) {
    $("#viewer-count").textContent = "พิมพ์คำเพื่อค้นในไฟล์";
    renderHits(null);
    renderWindow();
    return;
  }
  $("#viewer-count").replaceChildren(el("span", { class: "spinner", "aria-hidden": "true" }), " กำลังค้นในไฟล์…");
  const gen = viewer.gen;
  viewer.findAbort = new AbortController();
  try {
    const r = await api(`/api/items/${viewer.info.id}/text/find?${new URLSearchParams({ q: words.join(" "), max: 2000 })}`, { signal: viewer.findAbort.signal });
    if (gen !== viewer.gen) return;
    viewer.hits = r.hits;
    viewer.hitLines = new Map(r.hits.map((h) => [h.line - 1, h.count]));
    const fmt = (x) => Number(x).toLocaleString();
    $("#viewer-count").replaceChildren(!r.total_matches ? (r.partial ? "ไม่พบ (ค้นได้บางส่วน)" : "ไม่พบในไฟล์นี้")
      : el("span", {}, "พบ ", el("strong", {}, fmt(r.total_matches)), " ครั้ง ใน ", el("strong", {}, fmt(r.total_lines)), " บรรทัด",
        r.partial ? " (ไฟล์ใหญ่มาก ค้นได้บางส่วน)" : ""));
    renderHits(r);
    viewer.lastKey = "";
    renderWindow();
    if (jump && viewer.hits.length) gotoHit(0);
  } catch (e) {
    if (e.name !== "AbortError") $("#viewer-count").textContent = e.message;
  }
}

function renderHits(r) {
  const list = $("#viewer-hits");
  if (!r || !r.hits.length) {
    list.replaceChildren(el("div", { class: "empty" }, viewer.words.length ? "ไม่มีบรรทัดที่ตรง" : "บรรทัดที่เจอคำค้นจะแสดงที่นี่ กดเพื่อกระโดดไปบรรทัดนั้น"));
    return;
  }
  const items = r.hits.map((h, k) => el("button", { type: "button", class: "hit", "data-k": k, onclick: () => gotoHit(k) },
    el("span", { class: "ln" }, h.line.toLocaleString()),
    el("span", { class: "txt" }, highlight(h.preview.trim(), viewer.words)),
    el("span", { class: "n", title: `${h.count} ครั้งในบรรทัดนี้` }, h.count)));
  if (r.total_lines > r.hits.length) items.push(el("div", { class: "empty" }, `แสดง ${r.hits.length.toLocaleString()} บรรทัดแรกจาก ${r.total_lines.toLocaleString()} บรรทัด`));
  list.replaceChildren(...items);
}

function gotoLine(lineNo, flash = true) {
  if (!viewer.info) return;
  const n = Math.min(Math.max(1, Number(lineNo) || 1), viewer.info.total_lines) - 1;
  const code = $("#viewer-code");
  code.scrollTop = Math.max(0, n * LINE_H * viewer.scale - code.clientHeight / 3);
  if (flash) {
    viewer.flashLine = n;
    setTimeout(() => { if (viewer.flashLine === n) { viewer.flashLine = -1; viewer.lastKey = ""; scheduleRender(); } }, 1200);
  }
  viewer.lastKey = "";
  renderWindow();
}

function gotoHit(k) {
  if (!viewer.hits.length) return;
  k = (k + viewer.hits.length) % viewer.hits.length; // wrap around
  document.querySelector(".hit.current")?.classList.remove("current");
  viewer.current = k;
  const hit = viewer.hits[k];
  viewer.currentLine = hit.line - 1;
  viewer.revealLine = hit.line - 1;
  gotoLine(hit.line);
  const item = document.querySelector(`.hit[data-k="${k}"]`);
  if (item) { item.classList.add("current"); item.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  $("#viewer-line").value = hit.line;
}

$("#viewer-code").addEventListener("scroll", scheduleRender, { passive: true });
$("#viewer-q").addEventListener("input", () => { clearTimeout(findDebounce); findDebounce = setTimeout(() => runFind(true), 250); });
$("#viewer-q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") { e.preventDefault(); gotoHit(viewer.current + (e.shiftKey ? -1 : 1)); }
});
$("#viewer").addEventListener("keydown", (e) => {
  if (e.key === "F3" || (e.key.toLowerCase() === "g" && (e.ctrlKey || e.metaKey))) { e.preventDefault(); gotoHit(viewer.current + (e.shiftKey ? -1 : 1)); }
  if (e.key.toLowerCase() === "f" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); $("#viewer-q").focus(); $("#viewer-q").select(); }
});
$("#viewer-next").addEventListener("click", () => gotoHit(viewer.current + 1));
$("#viewer-prev").addEventListener("click", () => gotoHit(viewer.current - 1));
$("#viewer-close").addEventListener("click", closeViewer);
$("#viewer").addEventListener("click", (e) => { if (e.target === $("#viewer")) closeViewer(); });
$("#viewer-line").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); gotoLine(Number(e.target.value)); } });
$("#viewer-code").addEventListener("click", (e) => {
  const ln = e.target.closest(".ln");
  if (ln && viewer.info) {
    const n = ln.textContent;
    $("#viewer-line").value = n;
    copy(`${viewer.info.path || viewer.info.title}:${n}`, `คัดลอก ${viewer.info.title}:${n}`);
  }
});
window.addEventListener("resize", () => { if (viewerOpen()) { viewer.lastKey = ""; scheduleRender(); } });

// ------------------------------------------------------------------ guide
/** "น้องค้น" — a magnifying glass with a face (SVG drawn for this app). */
function mascotSvg() {
  return '<svg viewBox="0 0 80 80"><line class="handle" x1="55" y1="55" x2="72" y2="72"/>' +
    '<circle class="lens" cx="36" cy="36" r="27"/><path class="glint" d="M20 26a18 18 0 0 1 9-9"/>' +
    '<ellipse class="eye" cx="28" cy="35" rx="3.4" ry="4.4"/><ellipse class="eye" cx="44" cy="35" rx="3.4" ry="4.4"/>' +
    '<circle class="shine" cx="29.2" cy="33.4" r="1.2"/><circle class="shine" cx="45.2" cy="33.4" r="1.2"/>' +
    '<ellipse class="cheek" cx="21.5" cy="43" rx="4" ry="2.6"/><ellipse class="cheek" cx="50.5" cy="43" rx="4" ry="2.6"/>' +
    '<path class="mouth" d="M31 44q5 5 10 0"/></svg>';
}
document.querySelectorAll(".mascot").forEach((m) => { m.innerHTML = mascotSvg(); }); // static, trusted markup

const GUIDE = [
  { key: "search", icon: "search", color: "file", title: "ค้นหาทุกอย่าง", target: ".input.search",
    text: "พิมพ์คำเดียว เจอทั้งชื่อไฟล์ เนื้อหาในไฟล์ โน้ต ลิงก์ และรหัสผ่าน ภาษาไทยที่เขียนติดกันก็เจอ กด / เพื่อเริ่มพิมพ์ได้ทันที" },
  { key: "add", icon: "plus", color: "note", title: "เพิ่มข้อมูล", target: "#add-btn",
    text: "ปุ่ม เพิ่ม: อัปโหลดไฟล์ จดโน้ต เก็บลิงก์ หรือเก็บรหัสผ่าน ทุกอย่างค้นเจอทันทีที่บันทึก" },
  { key: "upload", icon: "upload", color: "bookmark", title: "อัปโหลด & ลากวาง", target: "#main",
    text: "ลากไฟล์จากเครื่องมาวางตรงไหนก็ได้ในหน้า มีแถบความคืบหน้า และค้นเนื้อหาในไฟล์ได้ทันที" },
  { key: "filters", icon: "filter", color: "password", title: "เลือกประเภท", target: "#filters",
    text: "ทั้งหมด / ไฟล์ / โน้ต / ลิงก์ / รหัสผ่าน ถ้ายังไม่พิมพ์จะเห็นรายการล่าสุดของประเภทนั้น" },
  { key: "detail", icon: "open", color: "file", title: "รายละเอียด & เปิดไฟล์", target: "#results",
    text: "คลิกผลลัพธ์เพื่อดูรายละเอียด ดับเบิลคลิกหรือกด Enter เพื่อเปิดไฟล์ เปิดลิงก์ หรือคัดลอกรหัสผ่าน" },
  { key: "viewer", icon: "lines", color: "note", title: "ดูเนื้อหา & ไปบรรทัดที่เจอ", target: "#results",
    text: "ปุ่ม ดูเนื้อหา แสดงไฟล์พร้อมเลขบรรทัด บอกว่าเจอกี่ครั้งในกี่บรรทัด กดรายการเพื่อกระโดดไปบรรทัดนั้น" },
  { key: "sort", icon: "sort", color: "bookmark", title: "เรียงลำดับ", target: "#sort-btn",
    text: "เกี่ยวข้องที่สุด แก้ไขล่าสุด เก่าสุด ชื่อ ขนาด หรือประเภท ระบบจำค่าที่เลือกไว้ให้" },
  { key: "vault", icon: "lock", color: "password", title: "ตู้รหัสผ่าน", target: "#vault-btn",
    text: "รหัสผ่านถูกเข้ารหัสด้วย master password ปลดล็อกแล้วคัดลอกได้ในคลิกเดียว ล็อกเองเมื่อไม่ได้ใช้" },
  { key: "scan", icon: "activity", color: "file", title: "การสแกนไฟล์", target: "#settings-btn",
    text: "ดูสถานะสด หยุด/เริ่มสแกน และเลือกโหมด ประหยัด/สมดุล/เร็วสุด เพื่อไม่ให้เครื่องหน่วง" },
  { key: "settings", icon: "palette", color: "note", title: "ปรับหน้าตา", target: "#settings-btn",
    text: "ธีม สี ขนาดตัวอักษร ซ่อนส่วนที่ไม่ใช้ หรือเลือกแบบเรียบ กดคืนค่าเริ่มต้นได้ทุกเมื่อ" },
];

const guideOpen = () => !$("#guide").classList.contains("hidden");

function guideTile(g) {
  return el("div", { class: `tile ${g.color}` }, icon(g.icon));
}

function renderGuide() {
  const cards = GUIDE.map((g, i) => {
    const video = el("video", { muted: "", loop: "", playsinline: "", preload: "none",
      poster: `/static/guide/${g.key}.jpg`, src: `/static/guide/${g.key}.mp4` });
    video.muted = true;
    const media = el("div", { class: "gmedia", title: "ดูวิดีโอ",
      onclick: () => { if (video.paused) { video.play(); media.classList.add("playing"); } else { video.pause(); media.classList.remove("playing"); } } },
      video, el("div", { class: "play" }, el("span", {}, icon("play"))));
    video.addEventListener("error", () => media.remove()); // video not available
    return el("article", { class: "gcard", style: `--i:${i}` },
      el("div", { class: "gtop" }, guideTile(g), el("h3", {}, g.title)),
      media,
      el("p", {}, g.text),
      el("div", { class: "gfoot" }, btn("ชี้ให้ดู", () => { closeGuide(); startTour([tourStepFor(g)]); }, "secondary sm", "pointer")));
  });
  cards.push(el("article", { class: "gcard", style: `--i:${GUIDE.length}` },
    el("div", { class: "gtop" }, guideTile({ color: "upload", icon: "keyboard" }), el("h3", {}, "คีย์ลัด")),
    el("div", { class: "keys" },
      ...[["ไปที่ช่องค้นหา", "/ หรือ Ctrl+K"], ["เลือกผลลัพธ์", "↑ ↓"], ["เปิด / คัดลอก", "Enter"], ["ดูรายละเอียด", "Shift+Enter"],
        ["คำถัดไปในหน้าดูเนื้อหา", "Enter / F3"], ["ปิดหน้าต่าง / ล้างคำค้น", "Esc"]]
        .map(([a, k]) => el("div", {}, el("span", {}, a), el("kbd", {}, k)))),
    el("p", {}, "ทุกอย่างทำได้ด้วยคีย์บอร์ด ไม่ต้องจับเมาส์เลย")));
  $("#guide-grid").replaceChildren(...cards);
}

function openGuide() {
  closeSettings();
  closeDetail();
  $("#welcome").classList.add("hidden");
  renderGuide();
  $("#guide").classList.remove("hidden");
  $("#scrim").classList.remove("hidden");
  $("#guide-tour").focus();
}

function closeGuide() {
  if (!guideOpen()) return;
  $("#guide").classList.add("hidden");
  $("#guide-grid").replaceChildren(); // stops videos
  if (!settingsOpen() && !$("#detail").classList.contains("open")) $("#scrim").classList.add("hidden");
}

// ------------------------------------------------------------------- tour
const TOUR = [
  { sel: ".input.search", title: "ช่องค้นหาช่องเดียว", text: "พิมพ์อะไรก็ได้ ชื่อไฟล์ เนื้อหา โน้ต ลิงก์ รหัสผ่าน ผลลัพธ์ขึ้นทันทีระหว่างพิมพ์ (กด / เพื่อมาที่นี่)" },
  { sel: "#add-btn", title: "ปุ่มเพิ่ม", text: "อัปโหลดไฟล์ จดโน้ต เก็บลิงก์ หรือรหัสผ่าน หรือจะลากไฟล์มาวางที่ไหนก็ได้" },
  { sel: "#filters", title: "เลือกประเภท", text: "ดูเฉพาะไฟล์ โน้ต ลิงก์ หรือรหัสผ่าน ตัวเลขบอกจำนวนในแต่ละประเภท" },
  { sel: "#results", title: "ผลลัพธ์", text: "คลิกเพื่อดูรายละเอียด ดับเบิลคลิกเพื่อเปิด ปุ่ม ดูเนื้อหา จะแสดงเลขบรรทัดที่เจอคำค้น" },
  { sel: "#sort-btn", title: "เรียงลำดับ", text: "เกี่ยวข้องที่สุด ล่าสุด ชื่อ ขนาด หรือประเภท" },
  { sel: "#detail", title: "รายละเอียด", text: "ข้อมูลของรายการที่เลือก พร้อมปุ่มเปิดไฟล์ ดูเนื้อหา และคัดลอก" },
  { sel: "#vault-btn", title: "ตู้รหัสผ่าน", text: "ล็อก/ปลดล็อกได้ตรงนี้ ระบบล็อกเองเมื่อไม่ได้ใช้ 15 นาที" },
  { sel: "#settings-btn", title: "ตั้งค่า", text: "ปรับหน้าตา ซ่อนส่วนที่ไม่ใช้ ดูสถานะและหยุดการสแกนไฟล์" },
  { sel: "#help-btn", title: "กลับมาดูได้เสมอ", text: "คู่มือและวิดีโอสั้นของทุกเมนูอยู่ที่ปุ่มนี้ เท่านี้ก็พร้อมใช้งานแล้ว!" },
];
const tourStepFor = (g) => ({ sel: g.target, title: g.title, text: g.text });
const tour = { steps: [], i: 0 };
const tourOpen = () => !$("#tour").classList.contains("hidden");

function targetOf(step) {
  const t = step.sel && document.querySelector(step.sel);
  if (!t) return null;
  const r = t.getBoundingClientRect();
  return r.width > 4 && r.height > 4 ? t : null;
}

function startTour(steps = TOUR) {
  closeGuide();
  closeSettings();
  $("#welcome").classList.add("hidden");
  // Skip steps whose element is hidden by the user's display settings.
  tour.steps = steps.length > 1 ? steps.filter((s) => targetOf(s)) : steps;
  tour.i = 0;
  if (!tour.steps.length) return;
  $("#tour").classList.remove("hidden");
  renderTourStep();
}

function renderTourStep() {
  const step = tour.steps[tour.i];
  const many = tour.steps.length > 1;
  const target = targetOf(step);
  const spot = $("#tour-spot");
  const bubble = $("#tour-bubble");
  $("#tour-step").textContent = many ? `${tour.i + 1} / ${tour.steps.length}` : "";
  $("#tour-title").textContent = step.title;
  $("#tour-text").textContent = step.text;
  $("#tour-dots").replaceChildren(...(many ? tour.steps.map((_, k) => el("i", { class: k === tour.i ? "on" : "" })) : []));
  $("#tour-back").classList.toggle("hidden", !many);
  $("#tour-back").disabled = tour.i === 0;
  $("#tour-skip").classList.toggle("hidden", !many || tour.i === tour.steps.length - 1);
  $("#tour-next").textContent = tour.i === tour.steps.length - 1 ? (many ? "เสร็จแล้ว!" : "เข้าใจแล้ว") : "ถัดไป";

  bubble.classList.remove("pop", "center");
  void bubble.offsetWidth; // restart the pop animation
  if (target) {
    target.scrollIntoView({ block: "nearest", inline: "nearest" });
    const r = target.getBoundingClientRect();
    const pad = 6;
    const box = {
      left: Math.max(4, r.left - pad), top: Math.max(4, r.top - pad),
      width: Math.min(r.width + pad * 2, innerWidth - 8), height: Math.min(r.height + pad * 2, innerHeight - 8),
    };
    Object.assign(spot.style, { left: `${box.left}px`, top: `${box.top}px`, width: `${box.width}px`, height: `${box.height}px`, opacity: 1 });
    const bw = Math.min(380, innerWidth - 24);
    const bh = bubble.offsetHeight || 170;
    const below = box.top + box.height + 14;
    const above = box.top - bh - 14;
    let top = below + bh < innerHeight - 8 ? below : above > 8 ? above : Math.max(8, innerHeight - bh - 8);
    let left = Math.min(Math.max(12, box.left + box.width / 2 - bw / 2), innerWidth - bw - 12);
    // Big targets (e.g. the result list): beside the spotlight if there is room, else inside it.
    if (box.height > innerHeight * 0.55) {
      top = Math.min(Math.max(8, box.top + 20), innerHeight - bh - 8);
      if (box.left + box.width + 16 + bw < innerWidth) left = box.left + box.width + 16;
      else if (box.left - 16 - bw > 0) left = box.left - 16 - bw;
      else left = Math.min(box.left + 20, innerWidth - bw - 12);
    }
    Object.assign(bubble.style, { left: `${left}px`, top: `${top}px` });
  } else {
    Object.assign(spot.style, { left: `${innerWidth / 2}px`, top: `${innerHeight / 2}px`, width: "0px", height: "0px" });
    bubble.classList.add("center");
  }
  bubble.classList.add("pop");
  const m = bubble.querySelector(".mascot");
  m.classList.remove("wave"); void m.offsetWidth; m.classList.add("wave");
  $("#tour-next").focus();
}

function endTour(finished) {
  $("#tour").classList.add("hidden");
  try { localStorage.setItem("sa-tour-done", "1"); } catch { /* ignore */ }
  if (finished && tour.steps.length > 1) {
    confetti();
    toast("เก่งมาก! พร้อมใช้งานแล้ว");
  }
  $("#q").focus();
}

function confetti() {
  if (document.documentElement.dataset.motion === "off" || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const box = el("div", { class: "confetti" });
  const colors = ["#f7a8b8", "#f8da9d", "#c4ddfb", "#c5e5c0", "#eccef3", getComputedStyle(document.documentElement).getPropertyValue("--color-accent").trim() || "#262626"];
  for (let k = 0; k < 90; k++) {
    box.append(el("i", { style: `left:${Math.random() * 100}%;background:${colors[k % colors.length]};` +
      `--x:${(Math.random() - 0.5) * 240}px;--r:${(Math.random() - 0.5) * 1440}deg;--d:${1.4 + Math.random() * 1.2}s;--delay:${Math.random() * 0.35}s;` +
      `border-radius:${k % 3 === 0 ? "50%" : "2px"}` }));
  }
  document.body.append(box);
  setTimeout(() => box.remove(), 3200);
}

$("#tour-next").addEventListener("click", () => { if (tour.i < tour.steps.length - 1) { tour.i++; renderTourStep(); } else endTour(true); });
$("#tour-back").addEventListener("click", () => { if (tour.i > 0) { tour.i--; renderTourStep(); } });
$("#tour-skip").addEventListener("click", () => endTour(false));
window.addEventListener("resize", () => { if (tourOpen()) renderTourStep(); });
$("#help-btn").addEventListener("click", openGuide);
$("#guide-close").addEventListener("click", closeGuide);
$("#guide-close-2").addEventListener("click", closeGuide);
$("#guide-tour").addEventListener("click", () => startTour());
$("#guide").addEventListener("click", (e) => { if (e.target === $("#guide")) closeGuide(); });
$("#welcome-yes").addEventListener("click", () => startTour());
$("#welcome-no").addEventListener("click", () => {
  $("#welcome").classList.add("hidden");
  try { localStorage.setItem("sa-tour-done", "1"); } catch { /* ignore */ }
});

function maybeWelcome() {
  let done = false;
  try { done = localStorage.getItem("sa-tour-done") === "1"; } catch { /* ignore */ }
  if (!done) setTimeout(() => { if (!tourOpen() && !guideOpen()) $("#welcome").classList.remove("hidden"); }, 1200);
}

// --------------------------------------------------------------- settings
const settingsOpen = () => !$("#settings").classList.contains("hidden");

function setPref(key, value) {
  const before = { ...prefs };
  prefs = { ...prefs, [key]: value };
  savePrefs(prefs);
  applyPrefs(prefs);
  onPrefsChanged(before);
}

function applyPreset(next, message) {
  const before = { ...prefs };
  prefs = { ...next };
  savePrefs(prefs);
  applyPrefs(prefs);
  onPrefsChanged(before);
  toast(message);
}

function onPrefsChanged(before) {
  if (!before || before.recent !== prefs.recent || before.resultLimit !== prefs.resultLimit || before.sortBy !== prefs.sortBy) search();
  updateSortLabel();
  if (!before || before.filters !== prefs.filters) {
    if (prefs.filters === "hidden" && state.kind) setKind(""); // hidden filter must not keep filtering
  }
  if (!before || before.detail !== prefs.detail) {
    closeDetail();
    if (isSide() && state.selected >= 0) showDetail(state.results[state.selected].id);
    else $("#detail").replaceChildren();
  }
  if (!before || before.snippets !== prefs.snippets) renderResults();
  renderStatusUI();
  if (settingsOpen()) renderSettingsPage();
}

function segmented(options, current, onChange) {
  return el("div", { class: "seg", role: "group" }, options.map(([value, label]) =>
    el("button", { type: "button", "aria-pressed": String(value === current), onclick: () => onChange(value) }, label)));
}

function toggle(current, onChange, label) {
  return el("button", { type: "button", class: "switch", role: "switch", "aria-checked": String(current), "aria-label": label,
    onclick: () => onChange(!current) });
}

function pref(title, desc, control, stack = false) {
  return el("div", { class: `pref${stack ? " stack" : ""}` },
    el("div", { class: "text" }, el("strong", {}, title), desc ? el("span", {}, desc) : null), control);
}

const group = (title, rows, hint = null) => el("section", { class: "group" },
  el("h3", {}, title), el("div", { class: "card" }, rows), hint ? el("p", { class: "hint" }, hint) : null);

const ACCENTS = ["auto", "#0074e2", "#1a7f37", "#0f766e", "#7c3aed", "#d6336c", "#e8590c"];

function fmtDuration(sec) {
  if (sec == null) return "—";
  sec = Math.round(sec);
  if (sec < 60) return `${sec} วิ`;
  const m = Math.floor(sec / 60), h = Math.floor(m / 60);
  return h ? `${h} ชม. ${m % 60} นาที` : `${m} นาที ${sec % 60} วิ`;
}
function fmtAgo(ts) {
  const sec = Math.max(0, Date.now() / 1000 - ts);
  if (sec < 60) return "เมื่อสักครู่";
  if (sec < 3600) return `${Math.floor(sec / 60)} นาทีที่แล้ว`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} ชั่วโมงที่แล้ว`;
  return fmtDate(ts);
}

// ---- pages
function pageAppearance() {
  const p = prefs;
  const seg = (key, options) => segmented(options, p[key], (v) => setPref(key, v));
  const swatches = el("div", { class: "swatches" },
    ACCENTS.map((c) => el("button", {
      type: "button", class: `swatch${c === "auto" ? " auto" : ""}`, title: c === "auto" ? "อัตโนมัติ (ดำ/ขาวตามธีม)" : c,
      style: c === "auto" ? "" : `background:${c}`, "aria-pressed": String(p.accent === c), onclick: () => setPref("accent", c),
    })),
    el("input", { type: "color", class: "swatch-custom", title: "เลือกสีเอง", value: p.accent === "auto" ? "#262626" : p.accent,
      oninput: (e) => setPref("accent", e.target.value) }));
  return [
    group("สีและธีม", [
      pref("ธีม", "ตามระบบ = เปลี่ยนสว่าง/มืดตามเครื่อง", seg("theme", [["system", "ตามระบบ"], ["light", "สว่าง"], ["dark", "มืด"]])),
      pref("สีหลัก", "ใช้กับปุ่มหลัก รายการที่เลือก และแถบความคืบหน้า", swatches, true),
    ]),
    group("ตัวอักษรและรูปทรง", [
      pref("ขนาดตัวอักษร", null, seg("fontSize", [["sm", "เล็ก"], ["md", "ปกติ"], ["lg", "ใหญ่"]])),
      pref("ฟอนต์", null, seg("font", [["google", "Google Sans"], ["system", "ฟอนต์ระบบ"]])),
      pref("มุม", null, seg("radius", [["square", "เหลี่ยม"], ["rounded", "ปกติ"], ["round", "มน"]])),
      pref("ความหนาแน่น", "กระชับ = เห็นผลลัพธ์ได้มากขึ้นต่อหน้าจอ", seg("density", [["comfortable", "สบายตา"], ["compact", "กระชับ"]])),
      pref("ภาพเคลื่อนไหว", "ปิดถ้าต้องการให้หน้าจอนิ่งหรือเครื่องช้า", toggle(p.motion, (v) => setPref("motion", v), "ภาพเคลื่อนไหว")),
    ]),
  ];
}

function pageDisplay() {
  const p = prefs;
  const seg = (key, options) => segmented(options, p[key], (v) => setPref(key, v));
  const sw = (key, label) => toggle(p[key], (v) => setPref(key, v), label);
  return [
    group("โครงหน้า", [
      pref("รูปแบบหน้า", "มีกรอบ = การ์ดแบบ fastwork · เรียบ = คอลัมน์เดียว", seg("layout", [["framed", "มีกรอบ"], ["clean", "เรียบ"]])),
      pref("ตัวกรองประเภท", "ทั้งหมด / ไฟล์ / โน้ต / ลิงก์ / รหัสผ่าน", seg("filters", [["rail", "เมนูซ้าย"], ["tabs", "แท็บ"], ["hidden", "ซ่อน"]])),
      pref("รายละเอียด", "ด้านข้าง = แสดงตลอดบนจอกว้าง · จอแคบจะเปิดเมื่อคลิกเสมอ", seg("detail", [["side", "ด้านข้าง"], ["drawer", "เปิดเมื่อคลิก"]])),
    ]),
    group("ผลลัพธ์", [
      pref("ไอคอนประเภท", null, seg("icons", [["large", "ใหญ่"], ["small", "เล็ก"], ["none", "ซ่อน"]])),
      pref("ข้อความตัวอย่าง", "ส่วนของเนื้อหาที่ตรงกับคำค้น", sw("snippets", "ข้อความตัวอย่าง")),
      pref("รายการล่าสุด", "แสดงรายการล่าสุดก่อนเริ่มพิมพ์", sw("recent", "รายการล่าสุด")),
    ]),
    group("แถบและปุ่มเสริม", [
      pref("แถบสถานะการสแกน", "มุมซ้ายล่างระหว่างสแกน พร้อมปุ่มหยุด", sw("scanIndicator", "แถบสถานะการสแกน")),
      pref("แถบคีย์ลัดและสถานะ", "ด้านล่างของหน้า", sw("footer", "แถบคีย์ลัดและสถานะ")),
      pref("ปุ่มตู้รหัสผ่าน", "ปุ่มล็อก/ปลดล็อกข้างช่องค้นหา", sw("vaultButton", "ปุ่มตู้รหัสผ่าน")),
    ]),
  ];
}

function pageBehavior() {
  const p = prefs;
  return [
    group("การค้นหา", [
      pref("กด Enter", "Shift+Enter = ดูรายละเอียด/เปิดทันที", segmented([["open", "เปิดทันที"], ["details", "ดูรายละเอียด"], ["view", "ดูเนื้อหา"]], p.enterAction, (v) => setPref("enterAction", v))),
      pref("เรียงผลลัพธ์", "เปลี่ยนได้จากปุ่มเรียงลำดับเหนือผลลัพธ์ด้วย", el("select", { class: "select", onchange: (e) => setPref("sortBy", e.target.value) },
        SORT_OPTIONS.map(([v, label]) => el("option", { value: v, selected: v === p.sortBy ? "" : null }, label)))),
      pref("โหลดผลลัพธ์ครั้งละ", "เลื่อนลงเพื่อโหลดเพิ่มเอง", segmented([[20, "20"], [50, "50"], [100, "100"]], p.resultLimit, (v) => setPref("resultLimit", v))),
    ]),
    group("คู่มือ", [
      pref("คู่มือการใช้งาน", "การ์ดอธิบายทุกเมนูพร้อมวิดีโอสั้น (กด ? ได้ทุกเมื่อ)", btn("เปิดคู่มือ", () => openGuide(), "secondary sm", "lines")),
      pref("ทัวร์ 1 นาที", "ชี้ทีละจุดบนหน้าจอจริง", btn("เริ่มทัวร์", () => startTour(), "primary sm", "pointer")),
    ]),
    group("คีย์ลัด", [
      pref("ไปที่ช่องค้นหา", null, el("span", {}, el("kbd", {}, "/"), " หรือ ", el("kbd", {}, "Ctrl"), "+", el("kbd", {}, "K"))),
      pref("เลือกผลลัพธ์", null, el("span", {}, el("kbd", {}, "↑"), " ", el("kbd", {}, "↓"))),
      pref("ปิดหน้าต่าง / ล้างคำค้น", null, el("kbd", {}, "Esc")),
      pref("เปิดคู่มือ", null, el("kbd", {}, "?")),
      pref("ในหน้าดูเนื้อหา: คำที่เจอถัดไป / ก่อนหน้า", null, el("span", {}, el("kbd", {}, "Enter"), " / ", el("kbd", {}, "Shift"), "+", el("kbd", {}, "Enter"))),
    ]),
  ];
}

const PROFILE_NOTES = {
  eco: "เหมาะกับโน้ตบุ๊กหรือเครื่องสเปกต่ำ ทำงานอื่นได้ลื่น แต่สแกนช้าที่สุด",
  balanced: "ค่าเริ่มต้น สแกนเร็วพอสมควรโดยไม่แย่งเครื่องมาก",
  fast: "สแกนเร็วที่สุด เครื่องอาจหน่วงระหว่างสแกน",
};

async function saveScanSettings(patch) {
  const current = state.status.indexing.settings;
  try {
    await api("/api/scan/settings", { method: "PUT", body: { ...current, ...patch } });
    await refreshStatus();
    renderSettingsPage();
  } catch (e) { toast(e.message); }
}

async function startScan() {
  await api("/api/scan/start", { method: "POST" });
  toast("เริ่มสแกนแล้ว");
  setTimeout(refreshStatus, 300);
}

async function stopScan() {
  const r = await api("/api/scan/stop", { method: "POST" });
  toast(r.stopped ? "กำลังหยุดสแกน…" : "ไม่มีการสแกนที่กำลังทำงาน");
  refreshStatus();
}

/** The live status card; refreshed in place while Settings is open. */
function fillScanCard(card) {
  const ix = state.status.indexing;
  const pr = ix.progress || {};
  const last = ix.last;
  const parts = [];
  if (ix.running) {
    const total = pr.total || 0;
    const pct = total ? Math.floor((pr.done / total) * 100) : null;
    const isOcr = pr.phase === "ocr";
    const title = pr.phase === "stopping" ? "กำลังหยุด…" : pr.phase === "walking" ? "กำลังสำรวจโฟลเดอร์…"
      : isOcr ? "กำลังอ่านภาพสแกน (OCR)" : "กำลังสแกนไฟล์";
    const sub = pr.phase === "walking" ? `พบแล้ว ${Number(pr.scanned || 0).toLocaleString()} ไฟล์`
      : total ? `${pr.done.toLocaleString()} / ${total.toLocaleString()} ไฟล์ที่ต้อง${isOcr ? "อ่านด้วย OCR" : "อ่าน"} · ${pct}%` : "";
    parts.push(el("div", { class: "scan-top" },
      el("div", { class: "state" }, el("strong", {}, el("span", { class: `dot-live ${pr.throttled ? "warn" : "on"}` }), title), el("span", {}, sub)),
      btn("หยุดสแกน", stopScan, "danger", null, pr.phase === "stopping" ? { disabled: "" } : {})));
    parts.push(el("div", { class: `progress${pct == null ? " indeterminate" : ""}` }, el("span", { style: pct == null ? "" : `width:${pct}%` })));
    parts.push(el("div", { class: "stats" },
      el("div", {}, el("strong", {}, !pr.rate ? "—" : isOcr ? `${Math.round(pr.rate * 600) / 10} ไฟล์/นาที` : `${pr.rate} ไฟล์/วิ`), el("span", {}, "ความเร็ว")),
      el("div", {}, el("strong", {}, fmtDuration(pr.eta_seconds)), el("span", {}, "เหลืออีกประมาณ")),
      el("div", {}, el("strong", {}, pr.cpu != null ? `${pr.cpu}%` : "—"), el("span", {}, "CPU ตัวสแกน")),
      el("div", {}, el("strong", {}, pr.worker_ram_mb != null ? `${pr.worker_ram_mb} MB` : pr.ram_mb != null ? `${pr.ram_mb} MB` : "—"),
        el("span", {}, pr.ram_limit_mb ? `RAM ตัวสแกน (เพดาน ${pr.ram_limit_mb} MB)` : "RAM ตัวสแกน"))));
    if (pr.worker_pid) parts.push(el("div", { class: "current" },
      `ทำงานใน process แยก (PID ${pr.worker_pid}) แบบ priority ต่ำ${pr.careful ? " · โหมดระวัง: อ่านทีละไฟล์หลังตัวสแกนล่ม" : ""}${pr.restarts ? ` · เริ่มใหม่ ${pr.restarts} ครั้ง` : ""}`));
    if (pr.current) parts.push(el("div", { class: "current" }, `กำลังอ่าน: ${pr.current}${isOcr && pr.pages ? ` · หน้า ${pr.page} / ${pr.pages}` : ""}`));
    if (pr.throttled) parts.push(el("div", { class: "notice" }, `พักชั่วคราวเพื่อไม่ให้เครื่องหน่วง — ${pr.throttled}`));
  } else {
    const sub = last ? `สแกนล่าสุด ${fmtAgo(last.finished_at)} · ${last.scanned.toLocaleString()} ไฟล์ · อ่านใหม่ ${last.added_or_updated.toLocaleString()}${
        last.ocr_files ? ` · OCR ${last.ocr_files.toLocaleString()} ไฟล์ (${(last.ocr_pages || 0).toLocaleString()} หน้า)` : ""} · ใช้เวลา ${fmtDuration(last.seconds)}`
      : "ยังไม่เคยสแกน";
    const auto = ix.settings.auto ? `สแกนอัตโนมัติทุก ${ix.settings.interval_minutes} นาที` : "ปิดการสแกนอัตโนมัติอยู่";
    parts.push(el("div", { class: "scan-top" },
      el("div", { class: "state" }, el("strong", {}, el("span", { class: "dot-live" }), "ไม่ได้สแกนอยู่"), el("span", {}, sub), el("span", {}, auto)),
      btn("เริ่มสแกน", startScan, "primary")));
    if (last && last.stopped) parts.push(el("div", { class: "notice info" }, "การสแกนครั้งล่าสุดถูกหยุดก่อนเสร็จ กด \"เริ่มสแกน\" เพื่อทำต่อ (ไฟล์ที่สแกนแล้วจะไม่อ่านซ้ำ)"));
    if (last && last.restarts) parts.push(el("div", { class: "notice" }, `ครั้งล่าสุดตัวสแกนล่มและเริ่มใหม่ ${last.restarts} ครั้ง${last.errors.length ? " — " + last.errors.slice(-2).join(" · ") : ""}`));
    if (last && last.paused_seconds >= 1) parts.push(el("div", { class: "notice info" }, `ครั้งล่าสุดพักไปรวม ${fmtDuration(last.paused_seconds)} เพื่อไม่ให้ใช้ CPU/RAM เกินขีดจำกัด`));
  }
  card.replaceChildren(...parts);
}

function pageScanning() {
  const s = state.status;
  const ix = s.indexing;
  const card = el("div", { class: "scan-card", id: "scan-card" });
  fillScanCard(card);

  const profiles = el("div", { class: "choice-grid" }, Object.entries(s.profiles).map(([key, p]) =>
    el("button", { type: "button", class: "choice", "aria-pressed": String(ix.settings.profile === key), onclick: () => saveScanSettings({ profile: key }) },
      el("strong", {}, p.label), el("span", {}, PROFILE_NOTES[key]),
      el("span", {}, `CPU ไม่เกิน ${p.max_cpu}% · RAM ไม่เกิน ${p.max_ram_mb} MB · ${p.threads} เธรดอ่านไฟล์`))));

  const folderRows = [];
  if (s.can_edit_folders) {
    const ta = el("textarea", { placeholder: "/home/me/Documents\nD:\\Work", style: "min-height:96px" }, s.folders.join("\n"));
    const err = el("p", { class: "error" });
    folderRows.push(pref("โฟลเดอร์ที่ให้ค้นหา", "บรรทัดละโฟลเดอร์ · ไฟล์ที่อัปโหลดค้นได้เสมอ", el("div", { style: "display:grid;gap:8px" },
      el("div", { class: "input" }, ta), err,
      el("div", { class: "btn-row" }, btn("บันทึกและสแกน", async () => {
        try {
          await api("/api/folders", { method: "PUT", body: { folders: ta.value.split("\n") } });
          toast("บันทึกแล้ว กำลังสแกน…"); refreshStatus();
        } catch (e) { err.textContent = e.message; }
      }, "primary sm"))), true));
  } else {
    folderRows.push(pref("โฟลเดอร์ที่ค้นหา", s.in_container
        ? "รันใน Docker: เลือกโฟลเดอร์ตอนเปิดแอป เช่น ./start.command --folder ~/Work (แสดงเป็น path จริงของเครื่อง)"
        : "ตั้งค่าตอนรันเซิร์ฟเวอร์ (--folder) · ไฟล์ที่อัปโหลดค้นได้เสมอ",
      el("ul", { class: "chips" }, s.folders.length ? s.folders.map((f) => el("li", { class: "chip" }, f)) : el("li", { class: "chip" }, "—")), true));
  }

  return [
    el("section", { class: "group" }, el("h3", {}, "สถานะ"), card),
    el("section", { class: "group" }, el("h3", {}, "การใช้ทรัพยากร (กันเครื่องค้าง)"), profiles,
      el("p", { class: "hint" }, `ระหว่างสแกน ระบบจะวัด CPU และ RAM ทุกครึ่งวินาที ถ้าเกินขีดจำกัด หรือ RAM ว่างเหลือน้อย จะพักชั่วคราวเอง · ${
        s.container && (s.container.cpus || s.container.memory_mb)
          ? `รันในคอนเทนเนอร์: CPU ${s.container.cpus ? s.container.cpus.toFixed(1) + " คอร์" : "ไม่จำกัด"} · RAM ${s.container.memory_mb ? s.container.memory_mb + " MB" : "ไม่จำกัด"} (ขีดจำกัดปรับตามคอนเทนเนอร์แล้ว)`
          : `เครื่องนี้มี ${s.cpu_count} คอร์`}`)),
    group("สแกนอัตโนมัติ", [
      pref("สแกนอัตโนมัติ", "ตรวจหาไฟล์ใหม่/ที่แก้ไขเป็นระยะ (อ่านเฉพาะไฟล์ที่เปลี่ยน)",
        toggle(ix.settings.auto, (v) => saveScanSettings({ auto: v }), "สแกนอัตโนมัติ")),
      pref("ทุกๆ", null, segmented([[5, "5 นาที"], [15, "15 นาที"], [30, "30 นาที"], [60, "1 ชม."]], ix.settings.interval_minutes,
        (v) => saveScanSettings({ interval_minutes: v }))),
    ]),
    group("อ่านข้อความจากภาพสแกน (OCR)", ocrRows(s, ix),
      "OCR ทำหลังสแกนไฟล์ปกติเสร็จ ทีละไฟล์ด้วย priority ต่ำ ไฟล์ใหม่ล่าสุดก่อน · อ่านครั้งเดียวต่อไฟล์ (อ่านใหม่เมื่อไฟล์เปลี่ยน)"),
    group("โฟลเดอร์", folderRows, "การตั้งค่าในหมวดนี้เก็บไว้ที่เครื่องที่รันแอป ใช้ร่วมกันทุก browser"),
    group("ชนิดไฟล์ที่อ่านเนื้อหาได้", Object.entries(s.supported_formats || {}).map(([k, v]) => pref(k, v, el("span"))),
      "ไฟล์ชนิดอื่น (รูป วิดีโอ ฯลฯ) ค้นได้จากชื่อไฟล์และโฟลเดอร์"),
    ...(ix.skipped && ix.skipped.length ? [group("ไฟล์ที่ข้ามเนื้อหา", [
      pref(`${ix.skipped.length} ไฟล์ทำให้ตัวสแกนล่ม`, "ยังค้นจากชื่อได้ กด \"ลองใหม่\" ให้สแกนครั้งถัดไปอ่านเนื้อหาอีกครั้ง",
        btn("ลองใหม่", async () => { await api("/api/scan/skipped", { method: "DELETE" }); toast("จะลองอ่านไฟล์เหล่านี้ในการสแกนครั้งถัดไป"); await refreshStatus(); renderSettingsPage(); }, "secondary sm")),
      el("ul", { class: "skipped" }, ix.skipped.slice(0, 20).map((f) => el("li", {}, el("code", {}, f.path), el("span", { class: "secondary" }, f.reason)))),
    ])] : []),
  ];
}

function ocrRows(s, ix) {
  const o = ix.ocr || {};
  const set = ix.settings;
  const langs = (o.langs || []).map((l) => ({ tha: "ไทย", eng: "อังกฤษ" }[l] || l)).join(" + ");
  let state;
  if (o.available && o.thai) {
    state = pref("พร้อมใช้งาน", `Tesseract ${o.version} · ภาษา ${langs} · อ่านแล้ว ${Number(o.done || 0).toLocaleString()} ไฟล์ (${Number(o.pages || 0).toLocaleString()} หน้า)${
      o.none ? ` · ไม่มีข้อความ ${o.none.toLocaleString()}` : ""}${o.failed ? ` · อ่านไม่ได้ ${o.failed.toLocaleString()}` : ""}`, el("span", { class: "dot-live on" }));
  } else {
    const how = s.in_container ? "อิมเมจ Docker นี้ไม่มี Tesseract — build ใหม่จาก Dockerfile ล่าสุด"
      : "Mac: brew install tesseract tesseract-lang · Windows: ติดตั้ง Tesseract (UB Mannheim) และติ๊ก Thai ตอนติดตั้ง · Linux: apt install tesseract-ocr tesseract-ocr-tha · หรือรันผ่าน Docker (มีให้ครบ)";
    state = pref(o.installed ? (o.available ? "ยังไม่มีภาษาไทย" : "Tesseract ใช้งานไม่ได้") : "ยังไม่ได้ติดตั้ง Tesseract",
      o.installed && o.available ? `อ่านได้เฉพาะ ${langs} · ${how}` : how, el("span", { class: "dot-live warn" }), true);
  }
  return [
    state,
    pref("อ่าน PDF ที่เป็นภาพสแกน", "หน้าที่ไม่มีข้อความ (สแกน/ถ่ายรูปเอกสาร) จะถูกอ่านด้วย OCR แล้วค้นหาได้เหมือนข้อความปกติ",
      toggle(set.ocr, (v) => saveScanSettings({ ocr: v }), "อ่าน PDF ที่เป็นภาพสแกน")),
    pref("อ่านข้อความในรูปภาพ", "jpg, png, gif, tiff, bmp, webp เช่น รูปถ่ายเอกสาร ภาพหน้าจอ สลิป · รูปที่ไม่มีตัวหนังสือ (คน วิว) จะถูกข้ามเอง เพราะเก็บเฉพาะบรรทัดที่อ่านได้ชัด",
      toggle(set.ocr_images, (v) => saveScanSettings({ ocr_images: v }), "อ่านรูปภาพด้วย")),
    pref("จำนวนหน้าสูงสุดต่อไฟล์", "ประมาณ 1–2 วินาทีต่อหน้า",
      segmented([[20, "20 หน้า"], [100, "100 หน้า"], [500, "500 หน้า"]], set.ocr_max_pages, (v) => saveScanSettings({ ocr_max_pages: v }))),
  ];
}

function pageSecurity() {
  const s = state.status;
  const vault = s.vault;
  const rows = [
    pref(vault.unlocked ? "ตู้รหัสผ่าน: ปลดล็อกอยู่" : vault.set_up ? "ตู้รหัสผ่าน: ล็อกอยู่" : "ยังไม่ได้ตั้ง Master Password",
      vault.unlocked ? "ล็อกเองอัตโนมัติเมื่อไม่ได้ใช้ 15 นาที" : "ปลดล็อกเพื่อดูหรือคัดลอกรหัสผ่าน",
      btn(vault.unlocked ? "ล็อก" : vault.set_up ? "ปลดล็อก" : "ตั้งค่า", async () => { await toggleVault(); renderSettingsPage(); },
        vault.unlocked ? "secondary sm" : "primary sm", vault.unlocked ? "lock" : "unlock")),
  ];
  const out = [group("ตู้รหัสผ่าน", rows, "ถ้าลืม master password จะกู้รหัสผ่านที่เก็บไว้ไม่ได้")];
  if (s.mode === "server") {
    out.push(group("บัญชี", [pref("ออกจากระบบ", "ออกจากระบบใน browser นี้",
      btn("ออกจากระบบ", async () => { await api("/api/logout", { method: "POST" }); closeSettings(); showLogin(); }, "danger sm"))]));
  }
  return out;
}

function pageReset() {
  const same = (preset) => Object.keys(DEFAULT_PREFS).every((k) => prefs[k] === preset[k]);
  return [
    el("section", { class: "group" }, el("h3", {}, "ชุดการตั้งค่าสำเร็จรูป"),
      el("div", { class: "choice-grid" },
        el("button", { type: "button", class: "choice", "aria-pressed": String(same(PREF_PRESETS.full)),
          onclick: () => applyPreset(PREF_PRESETS.full, "ใช้ค่าเริ่มต้นแล้ว") },
          el("strong", {}, "แสดงครบ (ค่าเริ่มต้น)"), el("span", {}, "เมนูประเภทด้านซ้าย รายละเอียดด้านข้าง แถบสถานะ และปุ่มทั้งหมด")),
        el("button", { type: "button", class: "choice", "aria-pressed": String(same(PREF_PRESETS.minimal)),
          onclick: () => applyPreset(PREF_PRESETS.minimal, "ใช้แบบเรียบแล้ว") },
          el("strong", {}, "เรียบ"), el("span", {}, "มีแค่ช่องค้นหา ปุ่มเพิ่ม และผลลัพธ์ รายละเอียดเปิดเมื่อคลิก")))),
    group("คืนค่า", [
      pref("คืนค่าหน้าตาเริ่มต้น", "ล้างทุกอย่างในหมวด หน้าตา / การแสดงผล / การใช้งาน กลับเป็นค่าเริ่มต้น",
        btn("คืนค่าเริ่มต้น", () => applyPreset(DEFAULT_PREFS, "คืนค่าเริ่มต้นแล้ว"), "danger sm")),
      pref("ชวนดูทัวร์อีกครั้ง", "แสดงคำชวนทัวร์ครั้งถัดไปที่เปิดแอป", btn("รีเซ็ตทัวร์", () => {
        try { localStorage.removeItem("sa-tour-done"); } catch { /* ignore */ }
        toast("จะชวนดูทัวร์อีกครั้งเมื่อเปิดแอปครั้งถัดไป");
      }, "secondary sm")),
    ], "การตั้งค่าหน้าตาบันทึกไว้ใน browser นี้ ไม่กระทบโฟลเดอร์ ไฟล์ โน้ต หรือรหัสผ่าน"),
  ];
}

// ------------------------------------------------------------ about / updates
let updatePoll = null;

function fmtBytes(n) { return n ? `${(n / 1048576).toFixed(1)} MB` : ""; }

async function updateAction(path, body) {
  try {
    const st = await api(path, { method: path.endsWith("settings") ? "PUT" : "POST", body });
    state.status.update = st;
    renderSettingsPage();
    if (st.state === "downloading" || st.state === "installing") pollUpdate();
  } catch (e) { toast(e.message); }
}

function pollUpdate() {
  clearTimeout(updatePoll);
  updatePoll = setTimeout(async () => {
    try {
      const st = await api("/api/update");
      state.status.update = st;
      if (settingsOpen() && settingsPage === "about") renderSettingsPage();
      if (st.state === "downloading" || st.state === "installing") pollUpdate();
    } catch { pollUpdate(); } // the app closes itself to install: keep trying quietly
  }, 700);
}

function pageAbout() {
  const s = state.status;
  const u = s.update;
  const rows = [pref("เวอร์ชันที่ใช้อยู่", "Search Anything", el("strong", {}, s.version || "—"))];
  if (!u) {
    rows.push(pref("อัปเดต", s.in_container
      ? "รันใน Docker: ดึงโค้ดใหม่ (git pull) แล้วรันสคริปต์ start อีกครั้ง"
      : "แอปที่ติดตั้งจากตัวติดตั้ง Windows/Mac อัปเดตในแอปได้ · แบบรันจากโค้ด: git pull แล้วเปิดใหม่", el("span")));
    return [group("เกี่ยวกับ", rows)];
  }
  rows.push(pref("ตรวจหาเวอร์ชันใหม่อัตโนมัติ", "วันละครั้ง ถาม GitHub ว่าเวอร์ชันล่าสุดคืออะไร ไม่ส่งข้อมูลไฟล์ คำค้น หรือข้อมูลใดๆ ของคุณ",
    toggle(u.auto, (v) => updateAction("/api/update/settings", { auto: v }), "ตรวจหาเวอร์ชันใหม่อัตโนมัติ")));
  const checked = u.last_check ? `ตรวจล่าสุด ${fmtAgo(u.last_check)}` : "ยังไม่ได้ตรวจ";
  let box;
  if (u.state === "downloading" || u.state === "installing") {
    const pct = Math.round((u.progress || 0) * 100);
    box = el("div", { class: "scan-card" },
      el("div", { class: "scan-top" }, el("div", { class: "state" },
        el("strong", {}, el("span", { class: "dot-live on" }), u.state === "installing" ? `กำลังติดตั้ง ${u.latest}…` : `กำลังดาวน์โหลด ${u.latest}…`),
        el("span", {}, u.state === "installing" ? "แอปจะปิดแล้วเปิดเวอร์ชันใหม่ให้เอง" : `${pct}% · ${fmtBytes(u.size)}`))),
      el("div", { class: "progress" }, el("span", { style: `width:${u.state === "installing" ? 100 : pct}%` })));
  } else if (u.newer) {
    box = el("div", { class: "scan-card" },
      el("div", { class: "scan-top" },
        el("div", { class: "state" }, el("strong", {}, el("span", { class: "dot-live on" }), `มีเวอร์ชันใหม่ ${u.latest}`),
          el("span", {}, `${fmtBytes(u.size)}${u.published ? " · ออกเมื่อ " + fmtShortDate(Date.parse(u.published) / 1000) : ""}`)),
        u.can_install ? btn("อัปเดตเลย", () => updateAction("/api/update/install"), "primary", "download")
          : (u.page ? btn("เปิดหน้าดาวน์โหลด", () => window.open(u.page, "_blank", "noopener,noreferrer"), "primary", "open") : null)),
      u.notes ? el("pre", { class: "notes" }, u.notes) : null);
  } else {
    box = el("p", { class: "secondary" }, u.latest ? `ใช้เวอร์ชันล่าสุดอยู่แล้ว (${u.latest})` : "");
  }
  rows.push(pref("สถานะ", `${checked}${u.error ? " · " + u.error : ""}`,
    btn("ตรวจเดี๋ยวนี้", () => updateAction("/api/update/check"), "secondary sm", null,
      u.state === "checking" || u.state === "downloading" ? { disabled: "" } : {})));
  return [group("เกี่ยวกับและอัปเดต", rows,
    "ดาวน์โหลดจาก GitHub Releases ของโปรเจกต์ และตรวจ SHA-256 ก่อนติดตั้ง ข้อมูลของคุณ (โน้ต รหัสผ่าน ดัชนี) อยู่ที่เดิม ไม่หายตอนอัปเดต"),
    el("section", { class: "group" }, box)];
}

const SETTINGS_PAGES = [
  { key: "appearance", label: "หน้าตา", icon: "palette", desc: "ธีม สี ตัวอักษร และรูปทรงของหน้าจอ", render: pageAppearance },
  { key: "display", label: "การแสดงผล", icon: "layout", desc: "เลือกว่าจะแสดงอะไรบนหน้าจอ ปิดส่วนที่ไม่ใช้ได้", render: pageDisplay },
  { key: "behavior", label: "การใช้งาน", icon: "keyboard", desc: "ปุ่ม Enter คีย์ลัด และจำนวนผลลัพธ์", render: pageBehavior },
  { key: "scanning", label: "การสแกนไฟล์", icon: "activity", desc: "สถานะ หยุด/เริ่มสแกน จำกัด CPU/RAM และโฟลเดอร์", render: pageScanning },
  { key: "security", label: "ความปลอดภัย", icon: "lock", desc: "ตู้รหัสผ่านและบัญชี", render: pageSecurity },
  { key: "reset", label: "รีเซ็ต", icon: "reset", desc: "คืนค่าหน้าตาเริ่มต้น หรือเลือกชุดการตั้งค่าสำเร็จรูป", render: pageReset },
  { key: "about", label: "เกี่ยวกับและอัปเดต", icon: "download", desc: "เวอร์ชัน และอัปเดตแอป", render: pageAbout },
];
let settingsPage = "appearance";

function renderSettingsNav() {
  const nav = document.querySelector(".settings-nav");
  nav.replaceChildren(el("div", { class: "nav-title" }, "ตั้งค่า"),
    ...SETTINGS_PAGES.map((pg) => el("button", {
      type: "button", class: "nav-item", "data-page": pg.key, "aria-current": pg.key === settingsPage ? "page" : null,
      onclick: () => { settingsPage = pg.key; renderSettingsNav(); renderSettingsPage(); $("#settings-body").scrollTop = 0; },
    }, icon(pg.icon), pg.label,
      pg.key === "scanning" && state.status?.indexing?.running ? el("span", { class: "badge", title: "กำลังสแกน" }) : null)));
}

function renderSettingsPage() {
  const pg = SETTINGS_PAGES.find((p) => p.key === settingsPage);
  $("#settings-title").textContent = pg.label;
  $("#settings-desc").textContent = pg.desc;
  const body = $("#settings-body");
  const scroll = body.scrollTop;
  body.replaceChildren(...pg.render());
  body.scrollTop = scroll;
}

async function openSettings(page) {
  if (typeof page === "string") settingsPage = page;
  closeGuide();
  await refreshStatus();
  closeDetail();
  renderSettingsNav();
  renderSettingsPage();
  $("#settings").classList.remove("hidden");
  $("#scrim").classList.remove("hidden");
  document.querySelector(`.nav-item[data-page="${settingsPage}"]`)?.focus();
}

function closeSettings() {
  $("#settings").classList.add("hidden");
  if (!$("#detail").classList.contains("open")) $("#scrim").classList.add("hidden");
  $("#q").focus();
}

// ----------------------------------------------------------------- status
let statusTimer = null;
let wasRunning = false;

let updateNoticeShown = false;

async function refreshStatus() {
  state.status = await api("/api/status");
  renderStatusUI();
  scheduleStatus();
  const u = state.status.update;
  if (u && u.newer && !updateNoticeShown && !(settingsOpen() && settingsPage === "about")) {
    updateNoticeShown = true;
    toast(`มีเวอร์ชันใหม่ ${u.latest} · ไปที่ ตั้งค่า → เกี่ยวกับและอัปเดต`);
  }
}

/** Poll quickly while a scan runs (live progress), slowly otherwise. */
function scheduleStatus() {
  clearTimeout(statusTimer);
  if (!state.status?.authenticated) return;
  statusTimer = setTimeout(() => refreshStatus().catch(() => scheduleStatus()), state.status.indexing.running ? 1000 : 8000);
}

function renderStatusUI() {
  const s = state.status;
  if (!s || !s.authenticated) return;
  const total = Object.values(s.counts).reduce((a, b) => a + b, 0);
  for (const item of document.querySelectorAll("#filters [data-kind]")) {
    const k = item.dataset.kind;
    item.querySelector(".count").textContent = (k ? s.counts[k] : total).toLocaleString();
  }
  const vb = $("#vault-btn");
  vb.replaceChildren(icon(s.vault.unlocked ? "unlock" : "lock"));
  vb.title = s.vault.unlocked ? "ล็อกตู้รหัสผ่าน" : "ปลดล็อกตู้รหัสผ่าน";

  const ix = s.indexing;
  const pr = ix.progress || {};
  const pct = pr.total ? Math.floor((pr.done / pr.total) * 100) : null;
  const scanText = pr.phase === "stopping" ? "กำลังหยุดสแกน…"
    : pr.phase === "walking" ? `กำลังสำรวจโฟลเดอร์… ${Number(pr.scanned || 0).toLocaleString()} ไฟล์`
    : pr.phase === "ocr" ? `กำลังอ่านภาพสแกน (OCR) ${pr.done.toLocaleString()} / ${pr.total.toLocaleString()} (${pct}%)`
    : pr.total ? `กำลังสแกน ${pr.done.toLocaleString()} / ${pr.total.toLocaleString()} (${pct}%)` : "กำลังสแกน…";
  $("#status-line").textContent = ix.running ? `${scanText}${pr.throttled ? " · พักชั่วคราว" : ""}`
    : `${s.mode === "local" ? (s.in_container ? "Local (Docker)" : "Local") : "Server"} · ${total.toLocaleString()} รายการ`;

  const pill = $("#scan-pill");
  pill.classList.toggle("hidden", !ix.running);
  pill.classList.toggle("throttled", !!pr.throttled);
  if (ix.running) {
    pill.querySelector(".pill-text").textContent = pr.throttled ? `${scanText} · พักชั่วคราว` : scanText;
    pill.querySelector(".bar > span").style.width = pct == null ? "8%" : `${pct}%`;
  }

  if (settingsOpen()) {
    const card = $("#scan-card");
    if (card) fillScanCard(card);
    const badge = document.querySelector('.nav-item[data-page="scanning"] .badge');
    if (!!badge !== ix.running) renderSettingsNav();
  }
  if (wasRunning && !ix.running) {
    const last = ix.last;
    toast(last && last.stopped ? "หยุดสแกนแล้ว" : "สแกนเสร็จแล้ว");
    search();
  }
  wasRunning = ix.running;
}

function showLogin() {
  $("#main").classList.add("hidden");
  $("#login").classList.remove("hidden");
  $("#login-password").focus();
}

async function showMain() {
  $("#login").classList.add("hidden");
  $("#main").classList.remove("hidden");
  await refreshStatus();
  $("#q").focus();
  search();
  maybeWelcome();
}

function setKind(kind) {
  state.kind = kind;
  document.querySelectorAll("#filters [data-kind]").forEach((c) => c.classList.toggle("active", c.dataset.kind === kind));
  search();
}

// ----------------------------------------------------------------- upload
function uploadFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const limit = (state.status.max_upload_mb || 200) * 1024 * 1024;
  const tooBig = files.filter((f) => f.size > limit);
  if (tooBig.length) return toast(`ไฟล์ใหญ่เกิน ${state.status.max_upload_mb} MB: ${tooBig.map((f) => f.name).join(", ")}`);

  const panel = $("#upload-panel");
  const bar = panel.querySelector(".bar > span");
  const label = panel.querySelector(".label");
  const total = files.reduce((a, f) => a + f.size, 0);
  label.textContent = files.length === 1 ? `กำลังอัปโหลด ${files[0].name}` : `กำลังอัปโหลด ${files.length} ไฟล์ (${fmtSize(total)})`;
  bar.style.width = "0%";
  panel.classList.remove("hidden");

  const fd = new FormData();
  for (const f of files) fd.append("files", f, f.name);
  const xhr = new XMLHttpRequest(); // fetch() has no upload progress events
  xhr.open("POST", "/api/upload");
  xhr.upload.onprogress = (e) => {
    if (!e.lengthComputable) return;
    const pct = Math.round((e.loaded / e.total) * 100);
    bar.style.width = `${pct}%`;
    if (pct >= 100) label.textContent = "กำลังอ่านเนื้อหาไฟล์…";
  };
  xhr.onload = async () => {
    panel.classList.add("hidden");
    let data = null;
    try { data = JSON.parse(xhr.responseText); } catch { /* not json */ }
    if (xhr.status !== 200) return toast((data && data.detail) || `อัปโหลดไม่สำเร็จ (${xhr.status})`);
    toast(`อัปโหลดแล้ว ${data.saved.length} ไฟล์`);
    await refreshStatus();
    // Show what was just uploaded: search for its name.
    $("#q").value = data.saved.length === 1 ? data.saved[0] : "";
    await search();
    const first = data.items[0] && state.results.findIndex((r) => r.id === data.items[0].id);
    if (first >= 0) select(first);
  };
  xhr.onerror = () => { panel.classList.add("hidden"); toast("อัปโหลดไม่สำเร็จ (เชื่อมต่อไม่ได้)"); };
  xhr.send(fd);
}

$("#upload-input").addEventListener("change", (e) => { uploadFiles(e.target.files); e.target.value = ""; });

// Drag files anywhere onto the window.
let dragDepth = 0;
const hasFiles = (e) => [...(e.dataTransfer?.types || [])].includes("Files");
window.addEventListener("dragenter", (e) => {
  if (!hasFiles(e) || $("#main").classList.contains("hidden")) return;
  e.preventDefault();
  if (++dragDepth === 1) $("#drop-zone").classList.remove("hidden");
});
window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
window.addEventListener("dragleave", (e) => {
  if (!hasFiles(e)) return;
  if (--dragDepth <= 0) { dragDepth = 0; $("#drop-zone").classList.add("hidden"); }
});
window.addEventListener("drop", (e) => {
  if (!hasFiles(e)) return;
  e.preventDefault();
  dragDepth = 0;
  $("#drop-zone").classList.add("hidden");
  if (!$("#main").classList.contains("hidden")) uploadFiles(e.dataTransfer.files);
});

// ----------------------------------------------------------------- events
$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/login", { method: "POST", body: { password: $("#login-password").value } });
    $("#login-password").value = "";
    $("#login-error").textContent = "";
    showMain();
  } catch (err) { $("#login-error").textContent = err.status === 401 ? "รหัสผ่านไม่ถูกต้อง" : err.message; }
});

$("#q").addEventListener("input", scheduleSearch);
$("#q").addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { e.preventDefault(); select(state.selected + 1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); select(state.selected - 1); }
  else if (e.key === "Enter" && state.selected >= 0) {
    e.preventDefault();
    const r = state.results[state.selected];
    if (prefs.enterAction === "view" && !e.shiftKey && canView(r)) return openViewer(r);
    const details = (prefs.enterAction === "details") !== e.shiftKey;
    if (details) openDetail(); else primaryAction(r);
  }
});
document.addEventListener("keydown", (e) => {
  if ($("#modal").open) return;
  if (tourOpen()) {
    if (e.key === "Escape") endTour(false);
    else if (e.key === "ArrowRight") $("#tour-next").click();
    else if (e.key === "ArrowLeft") $("#tour-back").click();
    return;
  }
  if (guideOpen()) {
    if (e.key === "Escape") closeGuide();
    return;
  }
  if (viewerOpen()) {
    if (e.key === "Escape") { e.preventDefault(); closeViewer(); }
    return; // the viewer handles its own keys
  }
  if (e.key === "Escape") {
    if (!$("#sort-menu").classList.contains("hidden")) { toggleSortMenu(false); $("#sort-btn").focus(); return; }
    if (!$("#add-menu").classList.contains("hidden")) { toggleAddMenu(false); $("#add-btn").focus(); return; }
    if (settingsOpen()) { closeSettings(); return; }
    if ($("#detail").classList.contains("open")) { closeDetail(); $("#q").focus(); return; }
    if (document.activeElement === $("#q") && $("#q").value) { $("#q").value = ""; search(); }
    return;
  }
  const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
  if (e.key === "?" && !typing) { e.preventDefault(); openGuide(); return; }
  if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey))) {
    e.preventDefault(); $("#q").focus(); $("#q").select();
  }
});
$("#filters").addEventListener("click", (e) => {
  const item = e.target.closest("[data-kind]");
  if (!item) return;
  setKind(item.dataset.kind);
  $("#q").focus();
});
$("#add-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleAddMenu(); });
document.addEventListener("click", (e) => {
  if (!e.target.closest(".add-wrap") && !$("#add-menu").classList.contains("hidden")) toggleAddMenu(false);
  if (!e.target.closest(".sort-wrap") && !$("#sort-menu").classList.contains("hidden")) toggleSortMenu(false);
});
$("#sort-btn").addEventListener("click", (e) => { e.stopPropagation(); toggleSortMenu(); });
updateSortLabel();
$("#scrim").addEventListener("click", () => { closeGuide(); closeSettings(); closeDetail(); });
$("#settings-btn").addEventListener("click", () => openSettings());
$("#settings-close").addEventListener("click", closeSettings);
// Click outside the settings window closes it.
$("#settings").addEventListener("click", (e) => { if (e.target === $("#settings")) closeSettings(); });
$("#scan-pill-open").addEventListener("click", () => openSettings("scanning"));
$("#scan-pill-stop").addEventListener("click", stopScan);
$("#vault-btn").addEventListener("click", toggleVault);

// Side ↔ drawer depends on window width.
let lastMode = document.documentElement.dataset.detailMode;
window.addEventListener("resize", () => {
  applyPrefs(prefs);
  const mode = document.documentElement.dataset.detailMode;
  if (mode !== lastMode) { lastMode = mode; onPrefsChanged({ ...prefs, detail: null }); }
});
// Follow the OS theme live when theme = "system" (CSS handles it; nothing to do).

(async () => {
  try {
    const s = await api("/api/status");
    if (s.authenticated) showMain(); else showLogin();
  } catch (e) { document.body.textContent = `เชื่อมต่อเซิร์ฟเวอร์ไม่ได้: ${e.message}`; }
})();
