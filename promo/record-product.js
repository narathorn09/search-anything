// Records CAHON itself for the promo (onetake §4, footage from the real thing):
// one continuous take of the real app on a virtual 2560x1440 screen (Xvfb +
// ffmpeg x11grab, sharp enough for a 1.6x close-up in a 1080p film), plus a
// timeline of what happens when and where (src/timeline.json) for the camera.
//
//   Xvfb :99 -screen 0 2560x1440x24 &
//   DISPLAY=:99 BASE_URL=http://localhost:8765 node record-product.js
//
// Needs the demo data from tools/make_demo_data.py (files + items), the app
// started with OCR turned off (the film reads the scanned bill on request) and
// HOME pointing at the demo "home" (the folder window starts there).

const { chromium } = require("playwright");
const { spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const BASE = process.env.BASE_URL || "http://localhost:8765";
const DISPLAY = process.env.DISPLAY || ":99";
const W = 2560, H = 1440, SCALE = 5 / 3; // the app laid out at 1536x864, drawn at 2560x1440
const OUT = path.join(__dirname, "public", "product.mp4");
const TIMELINE = path.join(__dirname, "src", "timeline.json");

const marks = [];
let t0 = 0;
const now = () => (Date.now() - t0) / 1000;

async function rectOf(page, selector) {
  const box = await page.locator(selector).first().boundingBox().catch(() => null);
  if (!box) return null;
  const r = (v) => Math.round(v * SCALE);
  return { x: r(box.x), y: r(box.y), w: r(box.width), h: r(box.height) };
}

/** Remember that `name` happens now, and where `zoom` (a selector) is on the recording. */
async function mark(page, name, zoom = null) {
  marks.push({ name, t: Number(now().toFixed(2)), rect: zoom ? await rectOf(page, zoom) : null });
}

// ------------------------------------------------------------ the hand
// Drawn into the page so it is in the footage: the cause of every reaction.
async function decorate(page) {
  await page.evaluate(() => {
    const style = document.createElement("style");
    style.textContent = `
      #rec-cursor { position: fixed; z-index: 99999; left: 0; top: 0; width: 24px; height: 24px; pointer-events: none;
        transform: translate(760px, 560px); transition: transform .62s cubic-bezier(.22,1,.36,1); }
      #rec-cursor svg { width: 24px; height: 24px; filter: drop-shadow(0 2px 3px rgba(0,0,0,.3)); transition: transform .08s; }
      #rec-cursor.down svg { transform: scale(.84); }
      #rec-cursor .ripple { position: absolute; left: -15px; top: -15px; width: 30px; height: 30px; border-radius: 50%;
        border: 2.5px solid #3a8f6c; opacity: 0; }
      #rec-cursor.click .ripple { animation: rec-ripple .45s ease-out; }
      @keyframes rec-ripple { from { opacity: .85; transform: scale(.3); } to { opacity: 0; transform: scale(1.6); } }`;
    document.head.append(style);
    const c = document.createElement("div");
    c.id = "rec-cursor";
    c.innerHTML = '<span class="ripple"></span><svg viewBox="0 0 24 24"><path d="M5 3l14 8-6.5 1.6L9.6 19z" fill="#fff" stroke="#171717" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.append(c);
  });
}

async function moveTo(page, selector, { dx = 0.5, dy = 0.5, wait = 650 } = {}) {
  const box = await page.locator(selector).first().boundingBox();
  if (!box) throw new Error(`not visible: ${selector}`);
  const x = box.x + box.width * dx, y = box.y + box.height * dy;
  await page.evaluate(([x, y]) => { document.getElementById("rec-cursor").style.transform = `translate(${x}px, ${y}px)`; }, [x, y]);
  await page.waitForTimeout(wait);
}

async function click(page, selector, opts = {}) {
  await moveTo(page, selector, opts);
  await page.evaluate(() => {
    const c = document.getElementById("rec-cursor");
    c.classList.remove("click"); void c.offsetWidth; c.classList.add("click", "down");
    setTimeout(() => c.classList.remove("down"), 90);
  });
  await page.locator(selector).first().click();
  await page.waitForTimeout(opts.after ?? 600);
}

async function typeIn(page, selector, text) {
  await click(page, selector, { after: 200 });
  await page.locator(selector).first().fill("");
  await page.waitForTimeout(200);
  await page.locator(selector).first().type(text, { delay: 105 });
}

// ------------------------------------------------------------ the take
async function story(p) {
  await mark(p, "home", "#main");
  await p.waitForTimeout(1500);

  // 1 · a word you remember → the file
  await mark(p, "type1", ".input.search");
  await typeIn(p, "#q", "สัญญาเช่า");
  await p.waitForTimeout(350);
  await mark(p, "found1", "#results li.row >> nth=0");
  await click(p, "#results li.row >> nth=0", { dx: 0.3, after: 500 });
  await mark(p, "detail1", "#detail");
  await p.waitForTimeout(1600);

  // 2 · something written inside → found inside
  await mark(p, "type2", ".input.search");
  await typeIn(p, "#q", "35,000");
  await p.waitForTimeout(400);
  await mark(p, "found2", "#results li.row >> nth=0");
  await p.waitForTimeout(1800);

  // 3 · a scanned bill → OCR on request
  await mark(p, "type3", ".input.search");
  await typeIn(p, "#q", "ใบแจ้งหนี้");
  await click(p, "#results li.row >> nth=0", { dx: 0.3, after: 600 });
  await mark(p, "ocr", ".ocr-box");
  await click(p, '.ocr-box button:has-text("อ่านด้วย OCR")', { after: 200 });
  await p.waitForSelector('.ocr-box:has-text("อ่านได้")', { timeout: 60000 });
  await mark(p, "ocrDone", ".ocr-box");
  await p.waitForTimeout(1300);
  await mark(p, "ocrText", "#detail pre");
  await p.waitForTimeout(1800);

  // 4 · narrow it down: type + date (the burst)
  await mark(p, "type4", ".input.search");
  await typeIn(p, "#q", "ค่าเช่า");
  await p.waitForTimeout(400);
  await mark(p, "chips", "#type-chips");
  await click(p, '#type-chips .type-chip[data-type="excel"]', { after: 500, wait: 450 });
  await mark(p, "date", "#date-btn");
  await click(p, "#date-btn", { after: 450, wait: 450 });
  await click(p, '#date-menu .menu-item:has-text("30 วันล่าสุด")', { after: 900, wait: 400 });
  await mark(p, "narrowed", "#results");
  await p.waitForTimeout(900);

  // 5 · add a folder, the mascot scans it
  await mark(p, "clear");
  await click(p, "#date-btn", { after: 300, wait: 350 });
  await click(p, '#date-menu .menu-item:has-text("ทุกช่วงเวลา")', { after: 300, wait: 350 });
  await p.locator("#q").fill("");
  await p.locator("#q").dispatchEvent("input");
  await p.waitForTimeout(900);
  await mark(p, "panel", "#folder-panel");
  await click(p, '#folder-panel button:has-text("เพิ่มโฟลเดอร์")', { after: 900 });
  await mark(p, "picker", "#modal");
  await click(p, '.fb-dir:has-text("โปรเจกต์ลูกค้า")', { after: 700 });
  await click(p, "#modal button[type=submit]", { after: 200 });
  await mark(p, "scanning", "#folder-panel");
  await p.waitForTimeout(3200);
  await mark(p, "scanned", "#folder-panel");
  await p.waitForTimeout(2500);
  await mark(p, "end");
}

(async () => {
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "cahon-rec-"));
  // App mode: no tabs, no address bar. The window is sized in layout pixels
  // (1536x864), which the 5/3 scale turns into the whole 2560x1440 screen.
  const ctx = await chromium.launchPersistentContext(profile, {
    headless: false, viewport: null, ignoreDefaultArgs: ["--enable-automation"],
    args: [`--app=${BASE}`, "--window-position=0,0", `--window-size=${W / SCALE},${H / SCALE}`,
      `--force-device-scale-factor=${SCALE}`, "--disable-features=Translate,TranslateUI", "--lang=th-TH",
      "--no-first-run", "--disable-infobars", "--hide-scrollbars"],
    env: { ...process.env, DISPLAY },
  });
  await ctx.addInitScript(() => { localStorage.setItem("cahon-tour-done", "1"); });
  const page = ctx.pages()[0];
  await page.reload();
  await page.waitForTimeout(2500);
  await decorate(page);
  await page.waitForTimeout(500);

  const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "x11grab", "-draw_mouse", "0", "-framerate", "30",
    "-video_size", `${W}x${H}`, "-i", `${DISPLAY}.0+0,0`, "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12",
    "-pix_fmt", "yuv420p", OUT], { stdio: ["pipe", "inherit", "inherit"] });
  await new Promise((r) => setTimeout(r, 1000));
  t0 = Date.now() - 1000; // the clip starts about when ffmpeg started
  try {
    await story(page);
  } catch (e) {
    console.error("story stopped:", e.message);
  }
  ff.stdin.write("q");
  await new Promise((r) => ff.on("close", r));
  await ctx.close();
  fs.rmSync(profile, { recursive: true, force: true });
  fs.writeFileSync(TIMELINE, JSON.stringify({ width: W, height: H, marks }, null, 2));
  console.log(`recorded ${OUT}\n${marks.map((m) => `${m.t.toFixed(1)}s ${m.name}`).join("\n")}`);
})();
