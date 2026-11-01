// Records the short usage videos shown in the in-app guide (คู่มือ).
//
//   1. Start the app with some sample data (see tools/README.md).
//   2. node tools/record-guide-videos.js
//   3. Videos + posters are written to cahon/static/guide/
//
// Needs Node, Playwright (npm i playwright) and ffmpeg (for MP4/H.264).
// Each scenario runs in its own browser context so it gets its own video.
// A fake cursor and a caption are drawn into the page, because headless
// recordings show neither the mouse nor any explanation.

const { chromium } = require("playwright");
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const BASE = process.env.BASE_URL || "http://localhost:8765";
const SCAN_BASE = process.env.SCAN_URL || BASE; // a server with many files, for the scan video
const OUT = process.env.OUT_DIR || path.join(__dirname, "..", "cahon", "static", "guide");
const ONLY = process.argv.slice(2);
const SIZE = { width: 1280, height: 800 };

// ----------------------------------------------------------- page helpers
async function decorate(page) {
  await page.evaluate(() => {
    const style = document.createElement("style");
    style.textContent = `
      #rec-cursor { position: fixed; z-index: 99999; left: 0; top: 0; width: 22px; height: 22px; pointer-events: none;
        transform: translate(640px, 420px); transition: transform .6s cubic-bezier(.22,1,.36,1); }
      #rec-cursor svg { width: 22px; height: 22px; filter: drop-shadow(0 2px 3px rgba(0,0,0,.35)); }
      #rec-cursor .ripple { position: absolute; left: -14px; top: -14px; width: 28px; height: 28px; border-radius: 50%;
        border: 3px solid #0074e2; opacity: 0; }
      #rec-cursor.click .ripple { animation: rec-ripple .5s ease-out; }
      @keyframes rec-ripple { from { opacity: .9; transform: scale(.3); } to { opacity: 0; transform: scale(1.6); } }
      #rec-caption { position: fixed; z-index: 99998; left: 50%; bottom: 22px; transform: translateX(-50%) translateY(20px);
        max-width: 80%; padding: 10px 18px; border-radius: 14px; background: rgba(23,23,23,.88); color: #fff;
        font: 500 17px "Google Sans", sans-serif; opacity: 0; transition: all .35s cubic-bezier(.34,1.56,.64,1); }
      #rec-caption.on { opacity: 1; transform: translateX(-50%); }`;
    document.head.append(style);
    const c = document.createElement("div");
    c.id = "rec-cursor";
    c.innerHTML = '<span class="ripple"></span><svg viewBox="0 0 24 24"><path d="M5 3l14 8-6.5 1.6L9.6 19z" fill="#fff" stroke="#171717" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.append(c);
    const cap = document.createElement("div");
    cap.id = "rec-caption";
    document.body.append(cap);
  });
}

async function caption(page, text, ms = 0) {
  await page.evaluate((t) => {
    const c = document.getElementById("rec-caption");
    c.classList.remove("on");
    void c.offsetWidth;
    c.textContent = t;
    if (t) c.classList.add("on");
  }, text);
  if (ms) await page.waitForTimeout(ms);
}

async function moveTo(page, selector, { dx = 0.5, dy = 0.5 } = {}) {
  const box = await page.locator(selector).first().boundingBox();
  if (!box) throw new Error(`not visible: ${selector}`);
  const x = box.x + box.width * dx, y = box.y + box.height * dy;
  await page.evaluate(([x, y]) => { document.getElementById("rec-cursor").style.transform = `translate(${x}px, ${y}px)`; }, [x, y]);
  await page.waitForTimeout(650);
  return { x, y };
}

async function click(page, selector, opts = {}) {
  await moveTo(page, selector, opts);
  await page.evaluate(() => {
    const c = document.getElementById("rec-cursor");
    c.classList.remove("click"); void c.offsetWidth; c.classList.add("click");
  });
  await page.locator(selector).first().click(opts.dbl ? { clickCount: 2 } : {});
  await page.waitForTimeout(opts.after ?? 600);
}

async function type(page, selector, text) {
  await click(page, selector, { after: 200 });
  await page.locator(selector).first().fill("");
  await page.locator(selector).first().type(text, { delay: 110 });
  await page.waitForTimeout(700);
}

// -------------------------------------------------------------- scenarios
const SCENARIOS = {
  async folders(p) {
    await caption(p, "หน้าแรกบอกว่าค้นหาในโฟลเดอร์ไหน และแต่ละโฟลเดอร์มีกี่ไฟล์");
    await moveTo(p, "#folder-panel .fp-folder >> nth=0");
    await p.waitForTimeout(1800);
    await caption(p, "กด เพิ่มโฟลเดอร์ (ในแอปจะเปิดหน้าต่างเลือกโฟลเดอร์ของเครื่อง)");
    await click(p, '#folder-panel button:has-text("เพิ่มโฟลเดอร์")', { after: 1200 });
    await caption(p, "เลือกโฟลเดอร์ที่อยากให้ค้นหา");
    await click(p, '.fb-dir:has-text("โปรเจกต์ลูกค้า")', { after: 1100 });
    await click(p, '#modal button[type=submit]', { after: 700 });
    await caption(p, "น้องเริ่มสแกนโฟลเดอร์ใหม่ให้ทันที", 2600);
    await caption(p, "กด × เพื่อเอาโฟลเดอร์ออกได้ (ไฟล์ในเครื่องไม่ถูกลบ)");
    await moveTo(p, "#folder-panel .fp-folder:has-text(\"โปรเจกต์ลูกค้า\") .fp-remove");
    await p.waitForTimeout(1800);
  },
  async refine(p) {
    await type(p, "#q", "ค่าเช่า");
    await caption(p, "ปุ่มประเภทไฟล์ บอกว่าเจอประเภทละกี่ไฟล์");
    await click(p, '#type-chips .type-chip[data-type="excel"]', { after: 1400 });
    await caption(p, "เลือกได้หลายประเภทพร้อมกัน");
    await click(p, '#type-chips .type-chip[data-type="word"]', { after: 1500 });
    await click(p, '#type-chips .type-chip[data-type=""]', { after: 900 });
    await caption(p, "ปุ่ม ช่วงเวลา: ดูเฉพาะที่แก้ไขช่วงที่ต้องการ");
    await click(p, "#date-btn", { after: 900 });
    await click(p, '#date-menu .menu-item:has-text("7 วันล่าสุด")', { after: 1600 });
    await caption(p, "หรือเลือกวันที่เอง");
    await click(p, "#date-btn", { after: 700 });
    await click(p, '#date-menu .menu-item:has-text("กำหนดเอง")', { after: 1300 });
    await click(p, '#modal button[type=submit]', { after: 1500 });
    await caption(p, "กด ทุกช่วงเวลา เพื่อล้างตัวกรอง");
    await click(p, "#date-btn", { after: 600 });
    await click(p, '#date-menu .menu-item:has-text("ทุกช่วงเวลา")', { after: 1500 });
  },
  async ocr(p) {
    await type(p, "#q", "ใบแจ้งหนี้");
    await click(p, "#results li.row >> nth=0", { dx: 0.3, after: 1200 });
    await caption(p, "ไฟล์สแกนบางไฟล์ อาจยังอ่านข้อความได้ไม่ครบ", 1800);
    await caption(p, "กด อ่านด้วย OCR น้องจะอ่านให้ทุกหน้า");
    await click(p, '.ocr-box button:has-text("อ่านด้วย OCR")', { after: 600 });
    await p.waitForSelector('.ocr-box:has-text("อ่านได้")', { timeout: 60000 });
    await caption(p, "อ่านเสร็จ ข้อความในภาพค้นหาได้แล้ว", 2400);
    await type(p, "#q", "INV-2024");
    await caption(p, "ค้นด้วยเลขที่ในใบแจ้งหนี้ก็เจอ", 2000);
  },
  async search(p) {
    await caption(p, "พิมพ์ในช่องค้นหาช่องเดียว");
    await type(p, "#q", "ค่าเช่า");
    await caption(p, "เจอทั้งไฟล์ Excel, เว็บเพจ และโค้ด — ภาษาไทยติดกันก็เจอ", 2200);
    await type(p, "#q", "rent");
    await caption(p, "คำที่เจอถูกไฮไลต์ พร้อมข้อความตัวอย่างจากในไฟล์", 2200);
    await caption(p, "กด ↓ ↑ เพื่อเลือก แล้ว Enter เพื่อเปิด");
    await p.keyboard.press("ArrowDown"); await p.waitForTimeout(500);
    await p.keyboard.press("ArrowDown"); await p.waitForTimeout(1300);
  },
  async add(p) {
    await caption(p, "กดปุ่ม เพิ่ม");
    await click(p, "#add-btn", { after: 900 });
    await caption(p, "เลือก โน้ต");
    await click(p, '#add-menu .menu-item:has-text("โน้ต")', { after: 800 });
    await caption(p, "ใส่ชื่อและเนื้อหา");
    await type(p, "#modal [name=title]", "Wi-Fi ออฟฟิศ");
    await type(p, "#modal [name=content]", "ชื่อเครือข่าย Office-5G รหัส sunflower99");
    await click(p, "#modal button[type=submit]", { after: 900 });
    await caption(p, "ค้นหาเจอทันทีที่บันทึก");
    await type(p, "#q", "sunflower");
    await p.waitForTimeout(1800);
  },
  async upload(p) {
    await caption(p, "ลากไฟล์จากเครื่องมาวางตรงไหนก็ได้");
    const dt = await p.evaluateHandle(() => {
      const d = new DataTransfer();
      d.items.add(new File(["ใบเสนอราคา งานออกแบบเว็บไซต์ ราคารวม 45,000 บาท"], "ใบเสนอราคา.txt", { type: "text/plain" }));
      return d;
    });
    await moveTo(p, "#results", { dx: 0.4, dy: 0.3 });
    await p.dispatchEvent("body", "dragenter", { dataTransfer: dt });
    await p.waitForTimeout(1600);
    await p.dispatchEvent("body", "drop", { dataTransfer: dt });
    await caption(p, "อัปโหลดเสร็จ ค้นเจอได้ทันที");
    await p.waitForTimeout(1600);
    await type(p, "#q", "ราคารวม");
    await caption(p, "ค้นเจอเนื้อหาในไฟล์ที่เพิ่งอัปโหลด", 2000);
  },
  async filters(p) {
    await caption(p, "เมนูซ้ายเลือกประเภทได้ ตัวเลขคือจำนวน");
    await click(p, '#filters [data-kind="file"]', { after: 1400 });
    await click(p, '#filters [data-kind="note"]', { after: 1400 });
    await click(p, '#filters [data-kind="bookmark"]', { after: 1400 });
    await caption(p, "ยังไม่พิมพ์ = รายการล่าสุดของประเภทนั้น");
    await click(p, '#filters [data-kind=""]', { after: 1800 });
  },
  async detail(p) {
    await type(p, "#q", "สัญญา");
    await caption(p, "คลิกผลลัพธ์เพื่อดูรายละเอียดด้านขวา");
    await click(p, "#results li.row >> nth=0", { dx: 0.3, after: 1500 });
    await caption(p, "มีปุ่มเปิดไฟล์ ดูเนื้อหา และคัดลอก path", 1500);
    await moveTo(p, '#detail button:has-text("เปิดไฟล์")');
    await caption(p, "ดับเบิลคลิกหรือ Enter = เปิดไฟล์ทันที", 2000);
  },
  async viewer(p) {
    await type(p, "#q", "rent");
    await caption(p, "กด ดูเนื้อหา");
    await click(p, '#results li.row:has-text("billing_service.py") .row-actions button', { after: 1200 });
    await caption(p, "บอกว่าเจอกี่ครั้งในกี่บรรทัด", 1800);
    await caption(p, "กดบรรทัดทางซ้าย เพื่อกระโดดไปบรรทัดนั้น");
    await click(p, "#viewer-hits .hit >> nth=4", { after: 1200 });
    await click(p, "#viewer-hits .hit >> nth=9", { after: 1200 });
    await caption(p, "หรือกด Enter / Shift+Enter เพื่อไปคำถัดไป");
    await p.focus("#viewer-q");
    for (let i = 0; i < 3; i++) { await p.keyboard.press("Enter"); await p.waitForTimeout(600); }
    await caption(p, "พิมพ์เลขบรรทัดเพื่อไปที่บรรทัดนั้นได้เลย");
    await type(p, "#viewer-line", "300");
    await p.keyboard.press("Enter");
    await p.waitForTimeout(1500);
  },
  async sort(p) {
    await type(p, "#q", "rent");
    await caption(p, "กดปุ่มเรียงลำดับ");
    await click(p, "#sort-btn", { after: 900 });
    await caption(p, "เลือก ชื่อ ก→ฮ");
    await click(p, '#sort-menu .menu-item:has-text("ชื่อ ก→ฮ")', { after: 1500 });
    await click(p, "#sort-btn", { after: 700 });
    await caption(p, "หรือ ขนาดใหญ่สุด — ระบบจำค่าที่เลือกไว้");
    await click(p, '#sort-menu .menu-item:has-text("ขนาดใหญ่สุด")', { after: 1800 });
  },
  async vault(p) {
    await caption(p, "เก็บรหัสผ่านไว้ในตู้ที่เข้ารหัส");
    await click(p, "#add-btn", { after: 700 });
    await click(p, '#add-menu .menu-item:has-text("รหัสผ่าน")', { after: 900 });
    if (await p.isVisible("#modal [name=p]")) {
      await caption(p, "ปลดล็อกด้วย master password");
      await type(p, "#modal [name=p]", "masterpass1");
      await click(p, "#modal button[type=submit]", { after: 1000 });
    }
    await type(p, "#modal [name=title]", "Netflix");
    await type(p, "#modal [name=username]", "me@mail.com");
    await caption(p, "กด สุ่ม เพื่อสร้างรหัสผ่านที่เดายาก");
    await click(p, '#modal button:has-text("สุ่ม")', { after: 900 });
    await click(p, "#modal button[type=submit]", { after: 1200 });
    await caption(p, "กดรูปตาเพื่อดู หรือปุ่มคัดลอก");
    await click(p, '#detail button[title="แสดง/ซ่อน"]', { after: 1500 });
    await click(p, '#detail button:has-text("คัดลอกรหัสผ่าน")', { after: 1200 });
    await caption(p, "ตู้ล็อกเองเมื่อไม่ได้ใช้ 15 นาที", 1600);
  },
  async scan(p) {
    await p.waitForSelector("#scan-pill:not(.hidden)", { timeout: 15000 });
    await caption(p, "หน้าแรกบอกว่ากำลังสแกนโฟลเดอร์ไหน ไปถึงไหนแล้ว");
    await moveTo(p, "#folder-panel .fp-head");
    await p.waitForTimeout(2400);
    await caption(p, "มุมซ้ายล่างก็บอกความคืบหน้า");
    await moveTo(p, "#scan-pill-open");
    await p.waitForTimeout(1200);
    await click(p, "#scan-pill-open", { after: 1400 });
    await caption(p, "ดูความเร็ว เวลาที่เหลือ และ CPU/RAM ที่ใช้", 2200);
    await caption(p, "หยุดได้ทุกเมื่อ — ไฟล์ที่สแกนแล้วยังค้นได้");
    await click(p, '#scan-card button:has-text("หยุดสแกน")', { after: 1800 });
    await caption(p, "เลือกโหมด ประหยัด เพื่อไม่ให้เครื่องหน่วง");
    await click(p, '.choice:has-text("ประหยัด")', { after: 1000 });
    await caption(p, "กดเริ่มสแกนต่อจากเดิม");
    await click(p, '#scan-card button:has-text("เริ่มสแกน")', { after: 2400 });
  },
  async settings(p) {
    await caption(p, "ปุ่มตั้งค่า");
    await click(p, "#settings-btn", { after: 1000 });
    await caption(p, "เปลี่ยนธีมและสีหลักได้ทันที");
    await click(p, '#settings .pref:has(strong:text-is("ธีม")) .seg button:text-is("มืด")', { after: 1000 });
    await click(p, '#settings .swatch[title="#7c3aed"]', { after: 1000 });
    await caption(p, "ซ่อนส่วนที่ไม่ใช้ ในหมวด การแสดงผล");
    await click(p, '.nav-item:has-text("การแสดงผล")', { after: 800 });
    await click(p, '#settings .pref:has(strong:text-is("ตัวกรองประเภท")) .seg button:text-is("แท็บ")', { after: 1000 });
    await caption(p, "อยากกลับค่าเดิม ไปที่ รีเซ็ต");
    await click(p, '.nav-item:has-text("รีเซ็ต")', { after: 800 });
    await click(p, 'button:has-text("คืนค่าเริ่มต้น")', { after: 1500 });
  },
};

// Same order as the guide in the app (GUIDE in cahon/static/app.js).
const ORDER = ["search", "folders", "add", "upload", "filters", "refine", "detail", "viewer", "ocr", "sort", "vault", "scan", "settings"];

// ------------------------------------------------------------------ main
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const tmp = fs.mkdtempSync(path.join(require("os").tmpdir(), "guide-rec-"));
  const browser = await chromium.launch();
  for (const key of ORDER) {
    const run = SCENARIOS[key];
    if (ONLY.length && !ONLY.includes(key)) continue;
    const ctx = await browser.newContext({ viewport: SIZE, recordVideo: { dir: tmp, size: SIZE }, deviceScaleFactor: 1 });
    await ctx.addInitScript(() => { localStorage.setItem("cahon-tour-done", "1"); });
    const page = await ctx.newPage();
    await page.goto(key === "scan" ? SCAN_BASE : BASE);
    await page.waitForTimeout(1200);
    await decorate(page);
    try {
      await run(page);
      await caption(page, "", 600);
    } catch (e) {
      console.error(`✗ ${key}: ${e.message}`);
    }
    const video = page.video();
    await ctx.close();
    const webm = await video.path();
    const mp4 = path.join(OUT, `${key}.mp4`);
    // H.264 for every browser, full 1280×800 (the guide plays it large); trim the blank first second.
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-ss", "1", "-i", webm, "-vf", "fps=30",
      "-c:v", "libx264", "-preset", "slow", "-crf", "26", "-tune", "animation", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", mp4]);
    execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-sseof", "-1.2", "-i", mp4, "-frames:v", "1", "-q:v", "4",
      path.join(OUT, `${key}.jpg`)]);
    console.log(`✓ ${key}: ${(fs.statSync(mp4).size / 1024).toFixed(0)} KB`);
  }
  await browser.close();
  fs.rmSync(tmp, { recursive: true, force: true });
})();
