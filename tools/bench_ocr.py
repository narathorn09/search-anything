"""Measure OCR on busy pictures: screenshots, infographics, receipts, phone
photos of documents, text over pictures - clean, and shrunk + recompressed the
way chat apps do (where OCR struggles most).

    python tools/bench_ocr.py [seed] [folder]

Prints word recall (share of the words in each picture that OCR found) for
the app's reader (cahon.ocr). Needs Tesseract with Thai, and the
internet once to fetch the Thai fonts. 1 Nov 2026, Tesseract 5.3, 4 cores:
before 58.4% (shrunk) / 98.9% (clean); now 82.0% / 99.2%.
"""
import json, os, random, sys, re, time, urllib.request
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/ocrbench"); OUT.mkdir(parents=True, exist_ok=True)
FONT_URLS = {"sarabun": "sarabun/Sarabun-Regular.ttf", "sarabunb": "sarabun/Sarabun-Bold.ttf",
             "noto": "notosansthai/NotoSansThai%5Bwdth,wght%5D.ttf", "kanit": "kanit/Kanit-Regular.ttf",
             "prompt": "prompt/Prompt-Regular.ttf"}
F = {}
for key, rel in FONT_URLS.items():  # Thai fonts used in real documents (OFL, from google/fonts)
    path = OUT / "fonts" / f"{key}.ttf"
    if not path.exists():
        path.parent.mkdir(exist_ok=True)
        urllib.request.urlretrieve("https://raw.githubusercontent.com/google/fonts/main/ofl/" + rel, path)
    F[key] = str(path)
TH = ("ใบแจ้งหนี้ สำนักงาน ค่าบริการ ประจำเดือน กรุณาชำระ ภายในวันที่ ยอดรวม ภาษีมูลค่าเพิ่ม ส่วนลด สมาชิก โปรโมชั่น พิเศษ "
      "ลงทะเบียน ฟรี ติดต่อ สอบถาม รายละเอียด เพิ่มเติม สินค้า จัดส่ง ด่วน รับประกัน คุณภาพ บริษัท จำกัด สาขา ถนน "
      "แขวง เขต กรุงเทพมหานคร โทรศัพท์ อีเมล เว็บไซต์ นัดหมาย ประชุม ผู้จัดการ ฝ่ายขาย การตลาด งบประมาณ รายงาน "
      "ไตรมาส เป้าหมาย ยอดขาย เพิ่มขึ้น ลดลง เปอร์เซ็นต์ ลูกค้า ใหม่ เก่า บัญชี ธนาคาร โอนเงิน สำเร็จ หมายเลข อ้างอิง").split()
EN = "Invoice Total Amount Discount Member Promotion Register Contact Report Quarter Sales Customer Account Transfer Reference Order Delivery Warranty".split()
rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 3)
truth = {}

def phrase(n):
    out = []
    for _ in range(n):
        r = rng.random()
        out.append(rng.choice(TH) if r < 0.7 else rng.choice(EN) if r < 0.85 else str(rng.randint(10, 99999)))
    return " ".join(out)

def font(name, size): return ImageFont.truetype(F[name], size)

def screenshot(i):  # app UI at 1x scale, small fonts
    W, H = 1366, 768; img = Image.new("RGB", (W, H), (245, 246, 248)); d = ImageDraw.Draw(img); lines = []
    d.rectangle((0, 0, W, 56), fill=(33, 37, 41)); t = phrase(4); d.text((20, 16), t, font=font("noto", 18), fill="white"); lines.append(t)
    d.rectangle((0, 56, 230, H), fill=(255, 255, 255))
    for k in range(10):
        t = phrase(2); d.text((20, 80 + k * 34), t, font=font("noto", 14), fill=(60, 60, 60)); lines.append(t)
    for r in range(4):
        for c in range(3):
            x, y = 260 + c * 360, 80 + r * 170
            d.rounded_rectangle((x, y, x + 340, y + 150), 10, fill="white", outline=(225, 225, 225))
            t = phrase(3); d.text((x + 16, y + 14), t, font=font("sarabunb", 16), fill=(20, 20, 20)); lines.append(t)
            for j in range(3):
                t = phrase(4); d.text((x + 16, y + 44 + j * 22), t, font=font("sarabun", 13), fill=(110, 110, 110)); lines.append(t)
            d.rounded_rectangle((x + 220, y + 112, x + 326, y + 140), 6, fill=(0, 116, 226))
            t = phrase(1); d.text((x + 232, y + 116), t, font=font("noto", 14), fill="white"); lines.append(t)
    return img, lines

def infographic(i):  # poster: colored boxes, white-on-dark, mixed sizes
    W, H = 1080, 1350; img = Image.new("RGB", (W, H), (255, 236, 210)); d = ImageDraw.Draw(img); lines = []
    t = phrase(3); d.text((60, 50), t, font=font("kanit", 64), fill=(180, 30, 60)); lines.append(t)
    colors = [(30, 60, 120), (0, 140, 120), (230, 120, 20), (90, 40, 140)]
    for k in range(4):
        y = 200 + k * 270; d.rounded_rectangle((50, y, W - 50, y + 240), 24, fill=colors[k])
        d.ellipse((80, y + 60, 200, y + 180), fill=(255, 255, 255, 80))
        t = phrase(3); d.text((230, y + 30), t, font=font("prompt", 38), fill="white"); lines.append(t)
        for j in range(3):
            t = phrase(5); d.text((230, y + 95 + j * 44), t, font=font("sarabun", 26), fill=(235, 235, 235)); lines.append(t)
    for j in range(2):
        t = phrase(6); d.text((60, 1290 - 40 * (1 - j)), t, font=font("noto", 20), fill=(90, 70, 60)); lines.append(t)
    return img, lines

def receipt(i):  # dense small table
    W, H = 760, 1300; img = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(img); lines = []
    t = phrase(3); d.text((40, 30), t, font=font("sarabunb", 28), fill="black"); lines.append(t)
    for r in range(45):
        y = 90 + r * 26
        if r % 2: d.rectangle((30, y - 2, W - 30, y + 22), fill=(242, 242, 242))
        a, b = phrase(3), f"{rng.randint(1, 99)} {rng.randint(10, 9999)}.{rng.randint(0, 99):02d}"
        d.text((40, y), a, font=font("sarabun", 17), fill="black"); d.text((520, y), b, font=font("sarabun", 17), fill="black")
        lines += [a, b]
    return img, lines

def photo(i):  # phone photo of a two-column page: rotation, light falloff, blur, noise, jpeg
    page = Image.new("RGB", (1240, 1754), (250, 248, 240)); d = ImageDraw.Draw(page); lines = []
    t = phrase(4); d.text((80, 70), t, font=font("sarabunb", 40), fill=(20, 20, 20)); lines.append(t)
    for col in range(2):
        for r in range(34):
            t = phrase(4); d.text((80 + col * 560, 160 + r * 44), t, font=font("sarabun", 24), fill=(30, 30, 30)); lines.append(t)
    page = page.rotate(rng.uniform(-3, 3), expand=True, fillcolor=(70, 60, 50)).resize((1300, 1820))
    bg = Image.new("RGB", (1500, 2000), (70, 60, 50)); bg.paste(page, (100, 90))
    shade = Image.radial_gradient("L").resize(bg.size).point(lambda v: 255 - v // 3)
    bg = Image.composite(bg, Image.new("RGB", bg.size, (0, 0, 0)), shade).filter(ImageFilter.GaussianBlur(1.0))
    return bg, lines

def busy_bg(i):  # social post: text over a busy picture
    W, H = 1080, 1080; img = Image.linear_gradient("L").resize((W, H)).convert("RGB"); d = ImageDraw.Draw(img); lines = []
    for _ in range(150):
        x, y, r = rng.randrange(W), rng.randrange(H), rng.randint(10, 120)
        d.ellipse((x, y, x + r, y + r), fill=tuple(rng.randrange(256) for _ in range(3)))
    img = img.filter(ImageFilter.GaussianBlur(3)); d = ImageDraw.Draw(img)
    d.rectangle((40, 60, W - 40, 330), fill=(255, 255, 255))
    t = phrase(3); d.text((70, 90), t, font=font("kanit", 56), fill=(200, 0, 60)); lines.append(t)
    t = phrase(5); d.text((70, 200), t, font=font("prompt", 34), fill=(30, 30, 30)); lines.append(t)
    d.rectangle((40, 760, W - 40, 1020), fill=(0, 0, 0))
    for j in range(4):
        t = phrase(5); d.text((70, 780 + j * 58), t, font=font("noto", 34), fill=(255, 220, 0)); lines.append(t)
    return img, lines

makers = {"screenshot": screenshot, "infographic": infographic, "receipt": receipt, "photo": photo, "busybg": busy_bg}
for name, fn in makers.items():
    for v in range(2):
        img, lines = fn(v)
        fname = f"{name}{v}.jpg" if name == "photo" else f"{name}{v}.png"
        img.save(OUT / fname, quality=82) if fname.endswith(".jpg") else img.save(OUT / fname)
        truth[fname] = lines
(OUT / "truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=0))
print({k: sum(len(l.split()) for l in v) for k, v in truth.items()})


# ------------------------------------------------------------------ shrink
B = OUT
new = {}
for f, lines in truth.items():
    im = Image.open(B / f).convert("RGB")
    for scale, q in ((0.6, 55), (0.45, 70)):  # chat apps shrink and recompress
        small = im.resize((int(im.width * scale), int(im.height * scale)), Image.BILINEAR)
        name = f"{Path(f).stem}_s{int(scale*100)}.jpg"; small.save(B / name, quality=q); new[name] = lines
(B / "truth_hard.json").write_text(json.dumps(new, ensure_ascii=False))
print(len(new), "hard images")


# ----------------------------------------------------------------- measure
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from cahon import ocr  # noqa: E402
from cahon.extractors import normalize_thai  # noqa: E402

reader = ocr.Reader(ocr.engine())
for label, tf in (("shrunk + JPEG", "truth_hard.json"), ("clean", "truth.json")):
    data = json.loads((OUT / tf).read_text()); found = total = 0; t0 = time.time()
    for f, lines in data.items():
        out = re.sub(r"\s+", "", normalize_thai(reader.read(str(OUT / f))[0]))
        toks = [t for line in lines for t in line.split()]
        found += sum(normalize_thai(t) in out for t in toks); total += len(toks)
    print(f"{label:14s} recall {100 * found / total:5.1f}%  ({len(data)} pictures, {time.time() - t0:.0f}s)")
