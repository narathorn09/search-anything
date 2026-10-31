"use strict";

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
};
const icon = (name) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  s.setAttribute("class", "icon");
  s.setAttribute("aria-hidden", "true");
  s.innerHTML = ICONS[name]; // static, trusted markup
  return s;
};

const state = { status: null, kind: "", results: [], selected: -1, detail: null, seq: 0 };

// ------------------------------------------------------------------ helpers
async function api(path, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const res = await fetch(path, opts);
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
const tile = (kind) => el("div", { class: `tile ${kind}` }, icon(kind));
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

// ----------------------------------------------------------------- search
let debounce;
function scheduleSearch() {
  clearTimeout(debounce);
  debounce = setTimeout(search, 120);
}

async function search() {
  const seq = ++state.seq;
  const q = $("#q").value.trim();
  const params = new URLSearchParams({ q, kind: state.kind, limit: 80 });
  try {
    const data = await api(`/api/search?${params}`);
    if (seq !== state.seq) return; // a newer search already finished
    state.results = data.results;
    state.selected = data.results.length ? 0 : -1;
    renderResults();
    if (state.selected >= 0) showDetail(state.results[0].id);
    else hideDetail();
  } catch (e) {
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
  const label = state.kind ? KIND_LABEL[state.kind] : "ทั้งหมด";
  $("#result-title").textContent = t.length ? "ผลการค้นหา" : state.kind ? label : "ล่าสุด";
  $("#result-count").textContent = state.results.length ? `${state.results.length} รายการ` : "";
  if (!state.results.length) {
    ul.append(el("li", { class: "empty reveal" },
      el("strong", {}, t.length ? "ไม่พบผลลัพธ์" : "ยังไม่มีข้อมูล"),
      t.length ? "ลองคำอื่น หรือเปลี่ยนประเภททางซ้าย" : "เพิ่มโน้ต ลิงก์ รหัสผ่าน หรือเลือกโฟลเดอร์ที่ปุ่มตั้งค่า"));
    return;
  }
  state.results.forEach((r, i) => {
    const meta = resultMeta(r).filter(Boolean);
    const li = el("li", {
      class: `row reveal${i === state.selected ? " selected" : ""}`, style: `--i:${Math.min(i, 12)}`,
      onclick: () => select(i), ondblclick: () => primaryAction(r),
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
  showDetail(state.results[i].id);
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
function hideDetail() { $("#detail").classList.add("hidden"); state.detail = null; }

const valueBox = (content, ...buttons) => el("div", { class: "valuebox" }, content, ...buttons);

async function showDetail(id) {
  const item = await api(`/api/items/${id}`);
  if (state.results[state.selected]?.id !== id) return; // selection moved on
  state.detail = item;
  const t = terms();
  const box = $("#detail");
  box.replaceChildren();
  box.classList.remove("hidden");

  const parts = [];
  const sub = item.kind === "file" ? item.path : KIND_LABEL[item.kind];
  parts.push(el("div", { class: "head" }, tile(item.kind),
    el("div", { style: "min-width:0" }, el("h2", {}, highlight(item.title, t)), el("div", { class: "sub" }, sub))));

  if (item.kind === "file") {
    parts.push(el("div", { class: "stats" },
      el("div", {}, el("strong", {}, ext(item.title)), el("span", {}, "ชนิด")),
      el("div", {}, el("strong", {}, fmtSize(item.size)), el("span", {}, "ขนาด")),
      el("div", {}, el("strong", {}, fmtShortDate(item.mtime)), el("span", {}, "แก้ไขล่าสุด"))));
    parts.push(el("div", { class: "actions" },
      btn(state.status.mode === "local" ? "เปิดไฟล์" : "ดาวน์โหลด", () => openFile(item.id), "primary", "open"),
      btn("คัดลอก path", () => copy(item.path, "คัดลอก path แล้ว"), "secondary", "copy")));
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
  if (item.tags && item.tags.length) parts.push(el("ul", { class: "chips", style: "list-style:none;margin:0;padding:0" }, item.tags.map((tag) => el("li", { class: "chip" }, `#${tag}`))));
  if (item.content) parts.push(el("pre", {}, highlight(item.content, t)));
  parts.push(el("div", { class: "sub" }, `แก้ไขล่าสุด ${fmtDate(item.updated_at)}`));
  parts.push(el("div", { class: "actions" },
    btn("แก้ไข", () => editItem(item.id), "secondary"),
    btn("ลบ", () => deleteItem(item), "danger")));
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
      if (e.status === 423) throw new Error("ตู้รหัสผ่านล็อกอยู่ — ยกเลิกแล้วกดปุ่มกุญแจเพื่อปลดล็อกก่อน");
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
  if (!confirm(`ลบ "${item.title}" ?`)) return;
  await api(`/api/items/${item.id}`, { method: "DELETE" });
  toast("ลบแล้ว");
  await refreshStatus();
  search();
}

// --------------------------------------------------------------- settings
async function openSettings() {
  await refreshStatus();
  const s = state.status;
  const form = $("#modal-form");
  const dlg = $("#modal");
  form.replaceChildren();
  form.onsubmit = (e) => e.preventDefault();
  const idx = s.indexing.last;
  form.append(el("h2", {}, "ตั้งค่า"),
    el("div", { class: "stats" },
      el("div", {}, el("strong", {}, s.mode === "local" ? "Local" : "Server"), el("span", {}, "โหมด")),
      el("div", {}, el("strong", {}, idx ? idx.scanned.toLocaleString() : "—"), el("span", {}, "ไฟล์ที่สแกน")),
      el("div", {}, el("strong", {}, s.indexing.running ? "กำลังสแกน" : idx ? `${idx.seconds}s` : "—"), el("span", {}, "สแกนล่าสุด"))));

  if (s.can_edit_folders) {
    const ta = el("textarea", { placeholder: "/home/me/Documents\nD:\\Work" }, s.folders.join("\n"));
    ta.style.minHeight = "110px";
    const err = el("p", { class: "error" });
    form.append(el("div", { class: "field" }, el("label", {}, "โฟลเดอร์ที่ให้ค้นหา (บรรทัดละโฟลเดอร์)"), el("div", { class: "input" }, ta)), err,
      el("div", { class: "actions-row", style: "justify-content:flex-start;margin:0" }, btn("บันทึกโฟลเดอร์", async () => {
        try {
          await api("/api/folders", { method: "PUT", body: { folders: ta.value.split("\n") } });
          toast("บันทึกแล้ว กำลังสแกน…"); dlg.close(); pollIndexing();
        } catch (e) { err.textContent = e.message; }
      }, "primary")));
  } else {
    form.append(el("div", { class: "field" }, el("label", {}, "โฟลเดอร์ที่ค้นหา (ตั้งค่าตอนรันเซิร์ฟเวอร์)"),
      el("ul", { class: "chips", style: "list-style:none;margin:0;padding:0" }, s.folders.map((f) => el("li", { class: "chip" }, f)))));
  }
  if (s.can_upload) {
    const file = el("input", { type: "file", multiple: "" });
    form.append(el("div", { class: "field" }, el("label", {}, "อัปโหลดไฟล์ขึ้นเซิร์ฟเวอร์เพื่อให้ค้นหาได้"), el("div", { class: "input" }, file)),
      el("div", { class: "actions-row", style: "justify-content:flex-start;margin:0" }, btn("อัปโหลด", async () => {
        if (!file.files.length) return;
        const fd = new FormData();
        for (const f of file.files) fd.append("files", f);
        try { await api("/api/upload", { method: "POST", body: fd }); toast("อัปโหลดแล้ว"); dlg.close(); pollIndexing(); }
        catch (e) { toast(e.message); }
      }, "secondary")));
  }
  form.append(el("div", { class: "actions-row" },
    s.mode === "server" ? btn("ออกจากระบบ", async () => { await api("/api/logout", { method: "POST" }); dlg.close(); showLogin(); }, "danger") : null,
    btn("สแกนไฟล์ใหม่", async () => { await api("/api/reindex", { method: "POST" }); toast("กำลังสแกนใหม่…"); dlg.close(); pollIndexing(); }, "secondary"),
    btn("ปิด", () => dlg.close(), "ghost")));
  dlg.onclose = null;
  dlg.showModal();
}

async function pollIndexing() {
  for (let i = 0; i < 600; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    await refreshStatus();
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
  $("#status-line").textContent = s.indexing.running ? "กำลังสแกนไฟล์…" : `${s.mode === "local" ? "Local" : "Server"} · ${total.toLocaleString()} รายการ`;
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
  else if (e.key === "Enter" && state.selected >= 0) { e.preventDefault(); primaryAction(state.results[state.selected]); }
  else if (e.key === "Escape") { $("#q").value = ""; search(); }
});
document.addEventListener("keydown", (e) => {
  if ($("#modal").open) return;
  const typing = ["INPUT", "TEXTAREA"].includes(document.activeElement.tagName);
  if ((e.key === "/" && !typing) || (e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey))) {
    e.preventDefault(); $("#q").focus(); $("#q").select();
  }
});
$("#filters").addEventListener("click", (e) => {
  const item = e.target.closest("[data-kind]");
  if (!item) return;
  state.kind = item.dataset.kind;
  document.querySelectorAll("#filters [data-kind]").forEach((c) => c.classList.toggle("active", c === item));
  search();
  $("#q").focus();
});
document.querySelectorAll("[data-new]").forEach((b) => b.addEventListener("click", () => editItem(null, b.dataset.new)));
$("#settings-btn").addEventListener("click", openSettings);
$("#vault-btn").addEventListener("click", async () => {
  if (state.status.vault.unlocked) { await api("/api/vault/lock", { method: "POST" }); toast("ล็อกตู้รหัสผ่านแล้ว"); await refreshStatus(); }
  else if (await ensureUnlocked()) toast("ปลดล็อกแล้ว");
});

(async () => {
  try {
    const s = await api("/api/status");
    if (s.authenticated) showMain(); else showLogin();
  } catch (e) { document.body.textContent = `เชื่อมต่อเซิร์ฟเวอร์ไม่ได้: ${e.message}`; }
})();
