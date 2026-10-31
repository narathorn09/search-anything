"use strict";

const $ = (sel) => document.querySelector(sel);
const KIND_ICON = { file: "📄", note: "📝", bookmark: "🔗", password: "🔑" };
const KIND_LABEL = { file: "ไฟล์", note: "โน้ต", bookmark: "ลิงก์", password: "รหัสผ่าน" };

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
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) node.setAttribute(k, v);
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
const fmtDate = (ts) => (ts ? new Date(ts * 1000).toLocaleString("th-TH") : "");
const terms = () => $("#q").value.trim().split(/\s+/).filter(Boolean);
const safeUrl = (u) => (/^(https?|ftp):\/\//i.test(u) ? u : /^[\w.-]+\.[a-z]{2,}/i.test(u) ? `https://${u}` : null);

// ------------------------------------------------------------------- modal
/**
 * Show a form dialog. On submit, `action(values)` runs; if it throws, the error
 * is shown and the dialog stays open. Resolves with action's result, or null if cancelled.
 */
function modalLoop(title, fields, action, { submit = "บันทึก" } = {}) {
  return new Promise((resolve) => {
    const dlg = $("#modal");
    const form = $("#modal-form");
    form.replaceChildren(el("h2", {}, title));
    const inputs = {};
    for (const f of fields) {
      const input = f.type === "textarea"
        ? el("textarea", { name: f.name, placeholder: f.placeholder || "" }, f.value || "")
        : el("input", { name: f.name, type: f.type || "text", placeholder: f.placeholder || "", value: f.value || "", autocomplete: f.autocomplete || "off" });
      input.required = !!f.required;
      inputs[f.name] = input;
      const row = f.generate
        ? el("div", { class: "row" }, input, el("button", { type: "button", onclick: () => { input.value = genPassword(); input.type = "text"; } }, "สุ่ม"))
        : input;
      form.append(el("div", { class: "field" }, el("label", {}, f.label), row));
    }
    const error = el("p", { class: "error" });
    let done = false;
    const finish = (value) => { if (!done) { done = true; resolve(value); } };
    form.append(error, el("div", { class: "row" },
      el("button", { type: "submit", class: "primary" }, submit),
      el("button", { type: "button", onclick: () => dlg.close() }, "ยกเลิก")));
    form.onsubmit = async (e) => {
      e.preventDefault();
      const values = Object.fromEntries(Object.entries(inputs).map(([k, v]) => [k, v.value]));
      try {
        const out = await action(values);
        finish(out);
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
      { name: "p1", label: "Master password (อย่างน้อย 8 ตัว) — ถ้าลืมจะกู้รหัสผ่านที่เก็บไว้ไม่ได้", type: "password", required: true, autocomplete: "new-password" },
      { name: "p2", label: "ยืนยันอีกครั้ง", type: "password", required: true, autocomplete: "new-password" },
    ], async (v) => {
      if (v.p1 !== v.p2) throw new Error("รหัสผ่านไม่ตรงกัน");
      await api("/api/vault/setup", { method: "POST", body: { master_password: v.p1 } });
      return true;
    }, { submit: "ตั้งค่า" });
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
    if (state.selected >= 0) showDetail(state.results[0].id, false);
    else hideDetail();
  } catch (e) {
    if (e.status === 401) return showLogin();
    toast(e.message);
  }
}

function renderResults() {
  const ul = $("#results");
  ul.replaceChildren();
  const t = terms();
  if (!state.results.length) {
    ul.append(el("li", { class: "empty" }, t.length ? "ไม่พบผลลัพธ์" : "ยังไม่มีข้อมูล — เพิ่มโน้ต ลิงก์ รหัสผ่าน หรือเลือกโฟลเดอร์ใน ⚙️"));
    return;
  }
  state.results.forEach((r, i) => {
    const sub = r.kind === "file" ? r.path : r.kind === "password" ? [r.username, r.url].filter(Boolean).join(" · ") : r.kind === "bookmark" ? r.url : "";
    const li = el("li", { class: i === state.selected ? "selected" : "", onclick: () => select(i), ondblclick: () => primaryAction(r) },
      el("div", { class: "head" }, el("span", { title: KIND_LABEL[r.kind] }, KIND_ICON[r.kind]), el("span", { class: "title" }, highlight(r.title, t))),
      sub ? el("div", { class: "sub" }, highlight(sub, t)) : null,
      r.snippet && r.kind !== "password" ? el("div", { class: "snip" }, highlight(r.snippet, t)) : null);
    ul.append(li);
  });
}

function select(i) {
  if (i < 0 || i >= state.results.length) return;
  state.selected = i;
  [...$("#results").children].forEach((li, j) => li.classList.toggle("selected", i === j));
  $("#results").children[i].scrollIntoView({ block: "nearest" });
  showDetail(state.results[i].id, false);
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

async function showDetail(id) {
  const item = await api(`/api/items/${id}`);
  state.detail = item;
  const t = terms();
  const box = $("#detail");
  box.replaceChildren();
  box.classList.remove("hidden");
  box.append(el("h2", {}, KIND_ICON[item.kind], " ", highlight(item.title, t)));
  const actions = el("div", { class: "actions" });

  if (item.kind === "file") {
    box.append(el("div", { class: "meta" }, item.path), el("div", { class: "meta" }, `${fmtSize(item.size)} · แก้ไขล่าสุด ${fmtDate(item.mtime)}`));
    actions.append(
      el("button", { class: "primary", onclick: () => openFile(item.id) }, state.status.mode === "local" ? "เปิดไฟล์" : "ดาวน์โหลด"),
      el("button", { onclick: () => copy(item.path, "คัดลอก path แล้ว") }, "คัดลอก path"));
    box.append(actions);
    if (item.content) box.append(el("pre", {}, highlight(item.content.slice(0, 20000), t)));
    else box.append(el("p", { class: "muted" }, "ไม่มีเนื้อหาที่อ่านได้ (ค้นได้จากชื่อไฟล์)"));
    return;
  }

  if (item.kind === "bookmark" || item.kind === "password") {
    const u = safeUrl(item.url);
    if (item.url) box.append(el("div", { class: "field" }, el("label", {}, "URL"),
      u ? el("a", { href: u, target: "_blank", rel: "noopener noreferrer" }, item.url) : el("span", {}, item.url)));
  }
  if (item.kind === "password") {
    if (item.username) box.append(el("div", { class: "field" }, el("label", {}, "Username"),
      el("div", { class: "row" }, el("span", { class: "secret" }, item.username), el("button", { onclick: () => copy(item.username) }, "คัดลอก"))));
    const secret = el("span", { class: "secret" }, "••••••••••");
    const showBtn = el("button", { onclick: async () => {
      const p = await revealPassword(item.id);
      if (p == null) return;
      if (secret.textContent.startsWith("•")) { secret.textContent = p; showBtn.textContent = "ซ่อน"; }
      else { secret.textContent = "••••••••••"; showBtn.textContent = "แสดง"; }
    } }, "แสดง");
    box.append(el("div", { class: "field" }, el("label", {}, "Password"), el("div", { class: "row" }, secret, showBtn,
      el("button", { class: "primary", onclick: async () => { const p = await revealPassword(item.id); if (p != null) copy(p, "คัดลอกรหัสผ่านแล้ว"); } }, "คัดลอก"))));
  }
  if (item.tags && item.tags.length) box.append(el("div", { class: "tags" }, item.tags.map((tag) => el("span", { class: "tag" }, `#${tag}`))));
  if (item.content) box.append(el("pre", {}, highlight(item.content, t)));
  box.append(el("div", { class: "meta" }, `แก้ไขล่าสุด ${fmtDate(item.updated_at)}`));
  actions.append(
    el("button", { onclick: () => editItem(item.id) }, "แก้ไข"),
    el("button", { class: "danger", onclick: () => deleteItem(item) }, "ลบ"));
  box.append(actions);
}

// ------------------------------------------------------------------ edit
const FIELD_LABELS = { note: "โน้ต", bookmark: "ลิงก์", password: "รหัสผ่าน" };

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

  const saved = await modalLoop(`${id ? "แก้ไข" : "เพิ่ม"}${FIELD_LABELS[kind]}`, fields, (v) => {
    const body = { kind, title: v.title, content: v.content, url: v.url || "", username: v.username || "", tags: v.tags.split(/\s+/).filter(Boolean) };
    if (kind === "password") body.password = id && !v.password ? null : v.password;
    return api(id ? `/api/items/${id}` : "/api/items", { method: id ? "PUT" : "POST", body }).catch((e) => {
      // The form dialog is open, so we can't stack the unlock dialog on top of it.
      if (e.status === 423) throw new Error("ตู้รหัสผ่านล็อกอยู่ — ยกเลิกแล้วกด 🔒 เพื่อปลดล็อกก่อน");
      throw e;
    });
  });
  if (saved) {
    toast("บันทึกแล้ว");
    await refreshStatus();
    await search();
    const idx = state.results.findIndex((r) => r.id === saved.id);
    if (idx >= 0) select(idx); else showDetail(saved.id);
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
    el("p", { class: "muted" }, `โหมด: ${s.mode === "local" ? "Local (เครื่องนี้)" : "Server"}`),
    el("p", { class: "muted" }, s.indexing.running ? "กำลังสแกนไฟล์…" :
      idx ? `สแกนล่าสุด: ${idx.scanned} ไฟล์, อัปเดต ${idx.added_or_updated}, ลบ ${idx.removed} (${idx.seconds}s)` : "ยังไม่ได้สแกน"));

  if (s.can_edit_folders) {
    const ta = el("textarea", { placeholder: "/home/me/Documents\nD:\\Work" }, s.folders.join("\n"));
    ta.style.minHeight = "100px";
    const err = el("p", { class: "error" });
    form.append(el("div", { class: "field" }, el("label", {}, "โฟลเดอร์ที่ให้ค้นหา (บรรทัดละโฟลเดอร์)"), ta), err,
      el("button", { type: "button", class: "primary", onclick: async () => {
        try {
          await api("/api/folders", { method: "PUT", body: { folders: ta.value.split("\n") } });
          toast("บันทึกแล้ว กำลังสแกน…"); dlg.close(); pollIndexing();
        } catch (e) { err.textContent = e.message; }
      } }, "บันทึกโฟลเดอร์"));
  } else {
    form.append(el("div", { class: "field" }, el("label", {}, "โฟลเดอร์ที่ค้นหา (ตั้งค่าตอนรันเซิร์ฟเวอร์)"), el("pre", {}, s.folders.join("\n") || "-")));
  }
  if (s.can_upload) {
    const file = el("input", { type: "file", multiple: "" });
    form.append(el("div", { class: "field" }, el("label", {}, "อัปโหลดไฟล์ขึ้นเซิร์ฟเวอร์เพื่อให้ค้นหาได้"), file),
      el("button", { type: "button", onclick: async () => {
        if (!file.files.length) return;
        const fd = new FormData();
        for (const f of file.files) fd.append("files", f);
        try { await api("/api/upload", { method: "POST", body: fd }); toast("อัปโหลดแล้ว"); dlg.close(); pollIndexing(); }
        catch (e) { toast(e.message); }
      } }, "อัปโหลด"));
  }
  form.append(el("div", { class: "row" },
    el("button", { type: "button", onclick: async () => { await api("/api/reindex", { method: "POST" }); toast("กำลังสแกนใหม่…"); dlg.close(); pollIndexing(); } }, "สแกนไฟล์ใหม่"),
    s.mode === "server" ? el("button", { type: "button", onclick: async () => { await api("/api/logout", { method: "POST" }); dlg.close(); showLogin(); } }, "ออกจากระบบ") : null,
    el("button", { type: "button", onclick: () => dlg.close() }, "ปิด")));
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
  for (const chip of document.querySelectorAll("#filters .chip")) {
    const k = chip.dataset.kind;
    chip.querySelector("span").textContent = k ? s.counts[k] : total;
  }
  $("#vault-btn").textContent = s.vault.unlocked ? "🔓" : "🔒";
  $("#vault-btn").title = s.vault.unlocked ? "ล็อกตู้รหัสผ่าน" : "ปลดล็อกตู้รหัสผ่าน";
  $("#status-line").textContent = s.indexing.running ? "กำลังสแกนไฟล์…" : `${s.mode === "local" ? "Local" : "Server"} · ${total} รายการ`;
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
  const chip = e.target.closest(".chip");
  if (!chip) return;
  state.kind = chip.dataset.kind;
  document.querySelectorAll("#filters .chip").forEach((c) => c.classList.toggle("active", c === chip));
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
