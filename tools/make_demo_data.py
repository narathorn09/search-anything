"""Demo data for the guide videos (tools/record-guide-videos.js) and screenshots.

    python tools/make_demo_data.py files /tmp/cahon-demo        # folders of sample files
    python tools/make_demo_data.py items http://localhost:8765  # notes, links, passwords

`files` writes (all made up):
    home/เอกสาร/…           Word, Excel, PDF, HTML, code (the folder the app searches)
    home/รูปภาพ/…           a scanned bill (image-only PDF) and a transfer slip
    home/โปรเจกต์ลูกค้า/…    a second folder, added in the "folders" video
    many/…                   thousands of small files, for the "scan" video
File dates are spread over two years, for the date filter.

`items` adds notes and links, sets the vault password to "masterpass1",
stores two passwords, then locks the vault (the vault video unlocks it).
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.request
from pathlib import Path

DAY = 86400
THAI_FONT = "/usr/share/fonts/truetype/tlwg/Garuda.ttf"


def age(path: Path, days: float) -> None:
    t = time.time() - days * DAY
    os.utime(path, (t, t))


def docx_file(path: Path, title: str, paragraphs: list[str], days: float) -> None:
    import docx

    d = docx.Document()
    d.add_heading(title, 1)
    for p in paragraphs:
        d.add_paragraph(p)
    d.save(path)
    age(path, days)


def xlsx_file(path: Path, sheet: str, rows: list[list], days: float) -> None:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for r in rows:
        ws.append(r)
    wb.save(path)
    age(path, days)


def picture(lines: list[str], size=(1240, 1754), font_size=34):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("L", size, 255)
    draw = ImageDraw.Draw(img)
    face = ImageFont.truetype(THAI_FONT, font_size) if Path(THAI_FONT).exists() else ImageFont.load_default(size=font_size)
    y = 120
    for line in lines:
        draw.text((110, y), line, font=face, fill=0)
        y += int(font_size * 2.1)
    return img


def text_file(path: Path, text: str, days: float) -> None:
    path.write_text(text, encoding="utf-8")
    age(path, days)


def make_files(root: Path) -> None:
    home = root / "home"
    docs, pics, client, many = home / "เอกสาร", home / "รูปภาพ", home / "โปรเจกต์ลูกค้า", root / "many"
    for d in (docs / "สัญญา", docs / "การเงิน", docs / "โค้ด", docs / "เว็บ", pics, client, many):
        d.mkdir(parents=True, exist_ok=True)

    docx_file(docs / "สัญญา" / "สัญญาเช่าสำนักงาน.docx", "สัญญาเช่าสำนักงาน", [
        "สัญญาฉบับนี้ทำขึ้นระหว่าง บริษัท ตัวอย่าง จำกัด (ผู้เช่า) และ นายสมชาย ใจดี (ผู้ให้เช่า)",
        "ค่าเช่ารายเดือน 35,000 บาท ชำระภายในวันที่ 5 ของทุกเดือน (monthly rent)",
        "ระยะเวลาเช่า 3 ปี เริ่มวันที่ 1 มกราคม 2567 เงินประกัน 105,000 บาท",
    ], 40)
    docx_file(docs / "สัญญา" / "สัญญาจ้างออกแบบเว็บไซต์.docx", "สัญญาจ้างออกแบบเว็บไซต์", [
        "ผู้ว่าจ้างตกลงจ้างผู้รับจ้างออกแบบเว็บไซต์ ราคารวม 45,000 บาท แบ่งจ่าย 3 งวด",
        "ส่งมอบงานภายใน 60 วัน หลังลงนามในสัญญา",
    ], 3)
    docx_file(docs / "สัญญา" / "บันทึกข้อตกลงความร่วมมือ.docx", "บันทึกข้อตกลง (MOU)", [
        "ความร่วมมือด้านการพัฒนาบุคลากร ระยะเวลา 2 ปี", "Memorandum of understanding",
    ], 420)
    xlsx_file(docs / "การเงิน" / "งบประมาณ-ค่าเช่า-2567.xlsx", "ค่าใช้จ่าย", [
        ["รายการ", "เดือน", "จำนวนเงิน", "หมายเหตุ"],
        *[["ค่าเช่าสำนักงาน", m, 35000, "office rent"] for m in ("ม.ค.", "ก.พ.", "มี.ค.", "เม.ย.")],
        ["ค่าไฟฟ้า", "ม.ค.", 8200, "electricity"],
        ["ค่าอินเทอร์เน็ต", "ม.ค.", 1590, "internet"],
    ], 12)
    xlsx_file(docs / "การเงิน" / "รายรับรายจ่าย-ไตรมาส3.xlsx", "Q3", [
        ["หมวด", "รายรับ", "รายจ่าย"], ["ขายสินค้า", 520000, 0], ["ค่าเช่าคลังสินค้า", 0, 48000], ["เงินเดือน", 0, 310000],
    ], 75)
    xlsx_file(docs / "การเงิน" / "ภาษี-2565.xlsx", "ภาษี", [["ปี", "ภาษีที่จ่าย"], [2565, 128000]], 700)
    text_file(docs / "การเงิน" / "รายการโอนเงิน.csv",
              "วันที่,รายการ,จำนวน\n2024-05-01,ค่าเช่า,35000\n2024-05-03,ค่าน้ำ,640\n", 1)
    text_file(docs / "เว็บ" / "ค่าเช่าคอนโดใกล้รถไฟฟ้า.html",
              "<html><head><title>ค่าเช่าคอนโด</title></head><body><h1>เปรียบเทียบค่าเช่าคอนโดใกล้ BTS</h1>"
              "<p>ห้องสตูดิโอ ค่าเช่าเริ่มต้น 12,000 บาท/เดือน rent from 12,000 THB</p></body></html>", 20)
    text_file(docs / "บันทึกการประชุม-ทีมการตลาด.md",
              "# ประชุมทีมการตลาด\n\n- แคมเปญปลายปี งบ 200,000 บาท\n- เปิดตัวสินค้าใหม่เดือนธันวาคม\n", 0.2)
    text_file(docs / "README.txt", "โฟลเดอร์เอกสารตัวอย่างสำหรับ CAHON\n", 200)

    # billing_service.py: 400 lines, "rent" on many of them (the viewer video).
    lines = ['"""Billing service: monthly rent, deposits and late fees."""', "", "import datetime as dt", ""]
    for i in range(1, 60):
        lines += [f"def step_{i}(account):",
                  f"    rent = account.rent * {1 + i / 100:.2f}  # adjusted rent, step {i}" if i % 3 == 0 else f"    total = account.balance + {i}",
                  f"    return {'rent' if i % 3 == 0 else 'total'}", "", ""]
    lines += [f"# line {n}: helper" for n in range(len(lines), 400)]
    text_file(docs / "โค้ด" / "billing_service.py", "\n".join(lines) + "\n", 6)

    # Scanned bill: a PDF that is only a picture (OCR video).
    picture(["ใบแจ้งหนี้ / INVOICE", "เลขที่ INV-2024-0042", "ค่าบริการดูแลระบบ 12,500 บาท",
             "ครบกำหนดชำระ 15 พฤศจิกายน", "ธนาคารกสิกรไทย 123-4-56789-0"]).convert("RGB").save(
        pics / "ใบแจ้งหนี้-สแกน.pdf", resolution=150)
    age(pics / "ใบแจ้งหนี้-สแกน.pdf", 2)
    picture(["โอนเงินสำเร็จ", "จำนวน 35,000.00 บาท", "ค่าเช่าสำนักงาน เดือนพฤษภาคม"], size=(900, 700), font_size=36).save(
        pics / "สลิปโอนเงิน.png")
    age(pics / "สลิปโอนเงิน.png", 5)

    docx_file(client / "ใบเสนอราคา-ระบบจองห้องประชุม.docx", "ใบเสนอราคา", [
        "ระบบจองห้องประชุมออนไลน์ ราคา 180,000 บาท", "รวมการดูแลระบบ 1 ปี"], 1)
    xlsx_file(client / "แผนงาน-ลูกค้า.xlsx", "Timeline", [["งาน", "สัปดาห์"], ["ออกแบบ", 2], ["พัฒนา", 6]], 1)
    for i in range(40):
        text_file(client / f"บันทึกงาน-{i + 1:02d}.txt", f"บันทึกงานลูกค้า ครั้งที่ {i + 1}\n", random.uniform(0, 30))

    # Many files for the scan video (the scan has to run long enough to film).
    random.seed(7)
    words = "รายงาน สัญญา ใบเสร็จ ค่าเช่า โครงการ ประชุม งบประมาณ invoice report project budget meeting".split()
    for d in range(60):
        sub = many / f"แผนก-{d:02d}"
        sub.mkdir(exist_ok=True)
        for i in range(400):
            body = " ".join(random.choice(words) for _ in range(200))
            (sub / f"เอกสาร-{i:03d}.txt").write_text(body, encoding="utf-8")
    print(f"files written to {root}")


def post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(base.rstrip("/") + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def make_items(base: str) -> None:
    for title, content, tags in [
        ("Wi-Fi บ้าน", "ชื่อเครือข่าย Home-5G รหัส coconut2024", ["บ้าน"]),
        ("เบอร์ช่างแอร์", "ช่างสมศักดิ์ 081-234-5678 ล้างแอร์ปีละ 2 ครั้ง", ["บ้าน"]),
        ("ไอเดียแคมเปญปลายปี", "ลด 20% ทุกสินค้า แจกของขวัญลูกค้าประจำ", ["งาน"]),
    ]:
        post(base, "/api/items", {"kind": "note", "title": title, "content": content, "tags": tags})
    for title, url, content in [
        ("ธนาคารแห่งประเทศไทย อัตราแลกเปลี่ยน", "https://www.bot.or.th", "ดูอัตราแลกเปลี่ยนรายวัน"),
        ("กรมสรรพากร ยื่นภาษีออนไลน์", "https://www.rd.go.th", "ยื่นภาษีเงินได้บุคคลธรรมดา"),
    ]:
        post(base, "/api/items", {"kind": "bookmark", "title": title, "url": url, "content": content})
    post(base, "/api/vault/setup", {"master_password": "masterpass1"})
    post(base, "/api/vault/unlock", {"master_password": "masterpass1"})
    for title, user, url in [("อีเมลบริษัท", "somchai@example.com", "https://mail.example.com"),
                             ("ระบบบัญชี", "acc-admin", "https://acc.example.com")]:
        post(base, "/api/items", {"kind": "password", "title": title, "username": user, "url": url,
                                  "password": "Demo-" + str(random.randint(1000, 9999)) + "-pass"})
    post(base, "/api/vault/lock", {})
    print("notes, links and passwords added; vault password: masterpass1 (locked)")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("files", "items"):
        sys.exit(__doc__)
    make_files(Path(sys.argv[2])) if sys.argv[1] == "files" else make_items(sys.argv[2])
