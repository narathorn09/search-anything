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
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/>',
  close: '<path d="M6 6l12 12M18 6 6 18"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="m13.5 6.5 4 4"/>',
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
const state = { status: null, kind: "", results: [], selected: -1, detailId: null, seq: 0 };
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

async function copy(text, label = "คัดลอกแล้ว") {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = el("textarea", {}, text);
    document.body.append(ta); ta.select(); document.execCommand("copy"); ta.remove();
  }
  toast(label);
}

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
async function search() {
  const seq = ++state.seq;
  const q = $("#q").value.trim();
  if (searchAbort) searchAbort.abort(); // drop the request for older keystrokes
  if (!q && !prefs.recent && !state.kind) {
    // Settings → "รายการล่าสุด" is off: a blank start until the user types.
    state.results = [];
    state.selected = -1;
    renderResults();
    hideDetail();
    return;
  }
  searchAbort = new AbortController();
  const params = new URLSearchParams({ q, kind: state.kind, limit: prefs.resultLimit });
  try {
    const data = await api(`/api/search?${params}`, { signal: searchAbort.signal });
    if (seq !== state.seq) return; // a newer search already finished
    state.results = data.results;
    state.selected = data.results.length ? 0 : -1;
    renderResults();
    if (isSide() && state.selected >= 0) showDetail(state.results[0].id);
    else hideDetail();
  } catch (e) {
    if (e.name === "AbortError") return;
    if (e.status === 401) return showLogin();
    toast(e.message);
  }
}

function resultMeta(r) {
  if (r.kind === "file") return [ext(r.title), fmtSize(r.size), fmtShortDate(r.mtime)];
  if (r.kind === "password") return [r.username, r.url];
  if (r.kind === "bookmark") return [r.url, ...(r.tags || []).map((t) => `#${t}`)];
  return [fmtShortDate(r.updated_at), ...(r.tags || []).map((t) => `#${t}`)];
}

function renderResults() {
  const ul = $("#results");
  ul.replaceChildren();
  const t = terms();
  const label = state.kind ? KIND_LABEL[state.kind] : "";
  $("#result-title").textContent = !state.results.length ? "" : t.length ? "ผลการค้นหา" : label || "ล่าสุด";
  $("#result-count").textContent = state.results.length ? `${state.results.length} รายการ` : "";
  if (!state.results.length) {
    const fresh = !t.length;
    ul.append(el("li", { class: "empty reveal" },
      el("strong", {}, fresh ? "พิมพ์เพื่อค้นหา" : "ไม่พบผลลัพธ์"),
      fresh ? "หรือกด เพิ่ม เพื่ออัปโหลดไฟล์ จดโน้ต เก็บลิงก์ หรือรหัสผ่าน" : "ลองคำอื่น หรือคำที่ยาวขึ้น"));
    return;
  }
  state.results.forEach((r, i) => {
    const meta = resultMeta(r).filter(Boolean);
    const li = el("li", {
      class: `row reveal${i === state.selected ? " selected" : ""}`, style: `--i:${Math.min(i, 12)}`,
      onclick: () => { select(i); if (!isSide()) openDetail(); },
      ondblclick: () => primaryAction(r),
    },
      tile(r.kind),
      el("div", { class: "copy" },
        el("div", { class: "title" }, highlight(r.title, t)),
        meta.length ? el("div", { class: "meta" }, meta.map((m, j) => el("span", { class: j ? "dot" : "" }, highlight(m, t)))) : null,
        r.snippet && r.kind !== "password" && t.length ? el("div", { class: "snip" }, highlight(r.snippet, t)) : null));
    ul.append(li);
  });
}

function select(i) {
  if (i < 0 || i >= state.results.length) return;
  state.selected = i;
  [...$("#results").children].forEach((li, j) => li.classList.toggle("selected", i === j));
  $("#results").children[i].scrollIntoView({ block: "nearest" });
  // Side column follows the selection; a closed drawer stays closed.
  if (isSide() || $("#detail").classList.contains("open")) showDetail(state.results[i].id);
}

async function primaryAction(r) {
  if (r.kind === "file") return openFile(r.id);
  if (r.kind === "bookmark") { const u = safeUrl(r.url); if (u) window.open(u, "_blank", "noopener"); return; }
  if (r.kind === "password") { const p = await revealPassword(r.id); if (p != null) copy(p, "คัดลอกรหัสผ่านแล้ว"); return; }
  if (r.kind === "note") return editItem(r.id);
}

async function openFile(id) {
  if (state.status.mode === "local") {
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
  if (!$("#settings").classList.contains("open")) $("#scrim").classList.add("hidden");
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
      btn(state.status.mode === "local" ? "เปิดไฟล์" : "ดาวน์โหลด", () => openFile(item.id), "primary", "open"),
      btn("คัดลอก path", () => copy(item.path, "คัดลอก path แล้ว"), "secondary", "copy"),
      item.uploaded ? btn("ลบไฟล์", () => deleteItem(item), "danger", "trash") : null));
    parts.push(item.content
      ? el("pre", {}, highlight(item.content.slice(0, 20000), t))
      : el("p", { class: "secondary" }, "ไม่มีเนื้อหาที่อ่านได้ (ค้นได้จากชื่อไฟล์)"));
    box.append(...parts.map((p, i) => withReveal(p, i)));
    return;
  }

  if ((item.kind === "bookmark" || item.kind === "password") && item.url) {
    const u = safeUrl(item.url);
    parts.push(el("div", { class: "field" }, el("label", {}, "URL"),
      valueBox(u ? el("a", { href: u, target: "_blank", rel: "noopener noreferrer", class: "value" }, item.url) : el("span", { class: "value" }, item.url),
        u ? btn("", () => window.open(u, "_blank", "noopener"), "ghost icon-only sm", "open", { title: "เปิดลิงก์" }) : null)));
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

// --------------------------------------------------------------- settings
function setPref(key, value) {
  const before = { ...prefs };
  prefs = { ...prefs, [key]: value };
  savePrefs(prefs);
  applyPrefs(prefs);
  onPrefsChanged(before);
}

function onPrefsChanged(before) {
  if (!before || before.recent !== prefs.recent || before.resultLimit !== prefs.resultLimit) search();
  if (!before || before.filters !== prefs.filters) {
    if (prefs.filters === "hidden" && state.kind) setKind(""); // hidden filter must not keep filtering
  }
  if (!before || before.detail !== prefs.detail) {
    closeDetail();
    if (isSide() && state.selected >= 0) showDetail(state.results[state.selected].id);
    else $("#detail").replaceChildren();
  }
  if (!before || before.snippets !== prefs.snippets) renderResults();
  if ($("#settings").classList.contains("open")) renderSettings();
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

const section = (title, ...rows) => el("section", { class: "sheet-section" }, el("h3", {}, title), el("div", { class: "card" }, rows));

const ACCENTS = ["auto", "#0074e2", "#1a7f37", "#0f766e", "#7c3aed", "#d6336c", "#e8590c"];

function renderSettings() {
  const s = state.status;
  const p = prefs;
  const seg = (key, options) => segmented(options, p[key], (v) => setPref(key, v));
  const sw = (key, label) => toggle(p[key], (v) => setPref(key, v), label);

  const swatches = el("div", { class: "swatches" },
    ACCENTS.map((c) => el("button", {
      type: "button", class: `swatch${c === "auto" ? " auto" : ""}`, title: c === "auto" ? "อัตโนมัติ (ดำ/ขาวตามธีม)" : c,
      style: c === "auto" ? "" : `background:${c}`, "aria-pressed": String(p.accent === c), onclick: () => setPref("accent", c),
    })),
    el("input", { type: "color", class: "swatch-custom", title: "เลือกสีเอง", value: p.accent === "auto" ? "#262626" : p.accent,
      oninput: (e) => setPref("accent", e.target.value) }));

  const idx = s.indexing.last;
  const filesCard = [
    el("div", { class: "stats", style: "margin:10px 0" },
      el("div", {}, el("strong", {}, s.counts.file.toLocaleString()), el("span", {}, "ไฟล์ในดัชนี")),
      el("div", {}, el("strong", {}, s.indexing.running ? "กำลังสแกน" : idx ? `${idx.seconds}s` : "—"), el("span", {}, "สแกนล่าสุด")),
      el("div", {}, el("strong", {}, s.mode === "local" ? "Local" : "Server"), el("span", {}, "โหมด"))),
  ];
  if (s.can_edit_folders) {
    const ta = el("textarea", { placeholder: "/home/me/Documents\nD:\\Work", style: "min-height:96px" }, s.folders.join("\n"));
    const err = el("p", { class: "error" });
    filesCard.push(pref("โฟลเดอร์ที่ให้ค้นหา", "บรรทัดละโฟลเดอร์ (ไฟล์ที่อัปโหลดค้นได้เสมอ)", el("div", { style: "display:grid;gap:8px" },
      el("div", { class: "input" }, ta), err,
      el("div", { class: "sheet-foot" },
        btn("บันทึกโฟลเดอร์", async () => {
          try {
            await api("/api/folders", { method: "PUT", body: { folders: ta.value.split("\n") } });
            toast("บันทึกแล้ว กำลังสแกน…"); pollIndexing();
          } catch (e) { err.textContent = e.message; }
        }, "primary sm"),
        btn("สแกนไฟล์ใหม่", async () => { await api("/api/reindex", { method: "POST" }); toast("กำลังสแกนใหม่…"); pollIndexing(); }, "secondary sm"))), true));
  } else {
    filesCard.push(pref("โฟลเดอร์ที่ค้นหา", "ตั้งค่าตอนรันเซิร์ฟเวอร์ (--folder)",
      el("ul", { class: "chips" }, s.folders.length ? s.folders.map((f) => el("li", { class: "chip" }, f)) : el("li", { class: "chip" }, "—")), true));
    filesCard.push(pref("สแกนไฟล์ใหม่", "ปกติระบบสแกนเองทุก 5 นาที",
      btn("สแกนเลย", async () => { await api("/api/reindex", { method: "POST" }); toast("กำลังสแกนใหม่…"); pollIndexing(); }, "secondary sm")));
  }

  const vault = s.vault;
  const sheet = $("#settings");
  sheet.replaceChildren(
    el("div", { class: "sheet-head" }, el("h2", {}, "ตั้งค่า"),
      btn("", closeSettings, "ghost icon-only sm", "close", { title: "ปิด", "aria-label": "ปิด" })),
    el("div", { class: "sheet-body" },
      section("หน้าตา",
        pref("ธีม", null, seg("theme", [["system", "ตามระบบ"], ["light", "สว่าง"], ["dark", "มืด"]])),
        pref("สีหลัก", "ปุ่มหลัก จุดที่เลือก และไฮไลต์", swatches, true),
        pref("ขนาดตัวอักษร", null, seg("fontSize", [["sm", "เล็ก"], ["md", "ปกติ"], ["lg", "ใหญ่"]])),
        pref("มุม", null, seg("radius", [["square", "เหลี่ยม"], ["rounded", "ปกติ"], ["round", "มน"]])),
        pref("ความหนาแน่น", "กระชับ = เห็นผลลัพธ์ได้มากขึ้นต่อหน้าจอ", seg("density", [["comfortable", "สบายตา"], ["compact", "กระชับ"]])),
        pref("ฟอนต์", null, seg("font", [["google", "Google Sans"], ["system", "ฟอนต์ระบบ"]])),
        pref("ภาพเคลื่อนไหว", null, sw("motion", "ภาพเคลื่อนไหว"))),
      section("สิ่งที่แสดงบนหน้าจอ",
        pref("รูปแบบหน้า", "มีกรอบ = สไตล์การ์ดแบบ fastwork", seg("layout", [["clean", "เรียบ"], ["framed", "มีกรอบ"]])),
        pref("ตัวกรองประเภท", "ทั้งหมด / ไฟล์ / โน้ต / ลิงก์ / รหัสผ่าน", seg("filters", [["hidden", "ซ่อน"], ["tabs", "แท็บ"], ["rail", "เมนูซ้าย"]])),
        pref("รายละเอียด", "ด้านข้าง = แสดงตลอดบนจอกว้าง", seg("detail", [["drawer", "เปิดเมื่อคลิก"], ["side", "ด้านข้าง"]])),
        pref("ไอคอนประเภท", null, seg("icons", [["none", "ซ่อน"], ["small", "เล็ก"], ["large", "ใหญ่"]])),
        pref("ข้อความตัวอย่าง", "ส่วนของเนื้อหาที่ตรงกับคำค้น", sw("snippets", "ข้อความตัวอย่าง")),
        pref("รายการล่าสุด", "แสดงรายการล่าสุดก่อนเริ่มพิมพ์", sw("recent", "รายการล่าสุด")),
        pref("แถบคีย์ลัดและสถานะ", "ด้านล่างของหน้า", sw("footer", "แถบคีย์ลัดและสถานะ")),
        pref("ปุ่มตู้รหัสผ่าน", "ปุ่มล็อก/ปลดล็อกข้างช่องค้นหา", sw("vaultButton", "ปุ่มตู้รหัสผ่าน"))),
      section("การใช้งาน",
        pref("กด Enter", "Shift+Enter ทำอีกแบบ", seg("enterAction", [["open", "เปิดทันที"], ["details", "ดูรายละเอียด"]])),
        pref("จำนวนผลลัพธ์", null, seg("resultLimit", [[20, "20"], [50, "50"], [100, "100"]]))),
      section("ไฟล์และโฟลเดอร์", ...filesCard),
      section("ตู้รหัสผ่าน",
        pref(vault.unlocked ? "ปลดล็อกอยู่" : vault.set_up ? "ล็อกอยู่" : "ยังไม่ได้ตั้ง Master Password",
          vault.unlocked ? "ล็อกเองอัตโนมัติเมื่อไม่ได้ใช้ 15 นาที" : "ปลดล็อกเพื่อดูหรือคัดลอกรหัสผ่าน",
          btn(vault.unlocked ? "ล็อก" : vault.set_up ? "ปลดล็อก" : "ตั้งค่า", async () => { await toggleVault(); renderSettings(); },
            vault.unlocked ? "secondary sm" : "primary sm", vault.unlocked ? "lock" : "unlock"))),
      s.mode === "server" ? section("บัญชี",
        pref("ออกจากระบบ", null, btn("ออกจากระบบ", async () => { await api("/api/logout", { method: "POST" }); closeSettings(); showLogin(); }, "danger sm"))) : null,
      el("div", { class: "sheet-foot" },
        btn("คืนค่าหน้าตาเริ่มต้น", () => {
          const before = { ...prefs };
          prefs = { ...DEFAULT_PREFS };
          savePrefs(prefs); applyPrefs(prefs); onPrefsChanged(before); toast("คืนค่าเริ่มต้นแล้ว");
        }, "ghost sm"),
        el("span", { class: "secondary", style: "font-size:12px;align-self:center" }, "การตั้งค่าหน้าตาบันทึกไว้ใน browser นี้"))));
}

async function openSettings() {
  await refreshStatus();
  closeDetail();
  renderSettings();
  const sheet = $("#settings");
  sheet.classList.remove("hidden");
  requestAnimationFrame(() => sheet.classList.add("open"));
  $("#scrim").classList.remove("hidden");
}

function closeSettings() {
  const sheet = $("#settings");
  sheet.classList.remove("open");
  setTimeout(() => { if (!sheet.classList.contains("open")) sheet.classList.add("hidden"); }, 450);
  if (!$("#detail").classList.contains("open")) $("#scrim").classList.add("hidden");
  $("#q").focus();
}

async function pollIndexing() {
  for (let i = 0; i < 600; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    await refreshStatus();
    if ($("#settings").classList.contains("open")) renderSettings();
    if (!state.status.indexing.running) break;
  }
  search();
}

// ----------------------------------------------------------------- status
async function refreshStatus() {
  state.status = await api("/api/status");
  const s = state.status;
  if (!s.authenticated) return;
  const total = Object.values(s.counts).reduce((a, b) => a + b, 0);
  for (const item of document.querySelectorAll("#filters [data-kind]")) {
    const k = item.dataset.kind;
    item.querySelector(".count").textContent = (k ? s.counts[k] : total).toLocaleString();
  }
  const vb = $("#vault-btn");
  vb.replaceChildren(icon(s.vault.unlocked ? "unlock" : "lock"));
  vb.title = s.vault.unlocked ? "ล็อกตู้รหัสผ่าน" : "ปลดล็อกตู้รหัสผ่าน";
  const pr = s.indexing.progress || {};
  $("#status-line").textContent = !s.indexing.running ? `${s.mode === "local" ? "Local" : "Server"} · ${total.toLocaleString()} รายการ`
    : pr.phase === "indexing" ? `กำลังสแกนไฟล์ ${pr.done.toLocaleString()} / ${pr.total.toLocaleString()}` : "กำลังสำรวจโฟลเดอร์…";
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
    const details = (prefs.enterAction === "details") !== e.shiftKey;
    if (details) openDetail(); else primaryAction(state.results[state.selected]);
  }
});
document.addEventListener("keydown", (e) => {
  if ($("#modal").open) return;
  if (e.key === "Escape") {
    if (!$("#add-menu").classList.contains("hidden")) { toggleAddMenu(false); $("#add-btn").focus(); return; }
    if ($("#settings").classList.contains("open")) { closeSettings(); return; }
    if ($("#detail").classList.contains("open")) { closeDetail(); $("#q").focus(); return; }
    if (document.activeElement === $("#q") && $("#q").value) { $("#q").value = ""; search(); }
    return;
  }
  const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
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
});
$("#scrim").addEventListener("click", () => { closeSettings(); closeDetail(); });
$("#settings-btn").addEventListener("click", openSettings);
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
