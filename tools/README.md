# tools

## record-guide-videos.js

อัดวิดีโอของแต่ละเมนูที่แสดงในคู่มือของแอป (`cahon/static/guide/*.mp4` ขนาด 1280×800 สำหรับดูแบบจอใหญ่ และภาพหน้าปก `*.jpg`)

ต้องมี: Node.js, Playwright (`npm i playwright` แล้ว `npx playwright install chromium`), ffmpeg และ Tesseract (วิดีโอ OCR)

1. สร้างข้อมูลตัวอย่าง (ไฟล์ทั้งหมดเป็นของสมมติ):

   ```bash
   python tools/make_demo_data.py files /tmp/cahon-demo
   ```

2. ปิด OCR อัตโนมัติไว้ก่อนเปิดแอป (วิดีโอ OCR จะกดอ่านเอง) แล้วเปิดแอปโดยให้ "Home" ของหน้าต่างเลือกโฟลเดอร์อยู่ที่ข้อมูลตัวอย่าง:

   ```bash
   mkdir -p /tmp/cahon-demo/data
   python -c "from dataclasses import asdict; from cahon.db import Database; from cahon.indexer import ScanSettings; db = Database('/tmp/cahon-demo/data/search.db'); s = asdict(ScanSettings()); s['ocr'] = False; db.set_meta('scan_settings', s)"
   HOME=/tmp/cahon-demo/home python -m cahon --data-dir /tmp/cahon-demo/data --folder /tmp/cahon-demo/home/เอกสาร --folder /tmp/cahon-demo/home/รูปภาพ
   ```

3. เพิ่มโน้ต ลิงก์ และรหัสผ่านตัวอย่าง (ตั้ง master password เป็น `masterpass1` แล้วล็อกตู้ไว้ วิดีโอ "ตู้รหัสผ่าน" จะสาธิตการปลดล็อก):

   ```bash
   python tools/make_demo_data.py items http://localhost:8765
   ```

4. อัดทั้งหมด หรือเฉพาะบางเมนู:

   ```bash
   node tools/record-guide-videos.js
   ```

   ```bash
   node tools/record-guide-videos.js search ocr
   ```

   วิดีโอ "folders" เพิ่มโฟลเดอร์ `โปรเจกต์ลูกค้า` และวิดีโอ "ocr" อ่านใบแจ้งหนี้สแกน ถ้าจะอัดซ้ำให้เริ่มจากข้อมูลใหม่

5. วิดีโอ "การสแกนไฟล์" ต้องอัดตอนที่กำลังสแกนอยู่จริง ให้เปิดเซิร์ฟเวอร์อีกตัว (โหมดประหยัด) ที่ชี้ไปที่โฟลเดอร์ `many` แล้วเริ่มอัดทันที (ถ้าสแกนเสร็จเร็วเกินไป ให้เพิ่มไฟล์ใน `many/`):

   ```bash
   SCAN_URL=http://localhost:8766 node tools/record-guide-videos.js scan
   ```

สคริปต์จะวาดเคอร์เซอร์และคำอธิบายภาษาไทยลงในวิดีโอเอง แล้วแปลงเป็น MP4 (H.264, 1280×800) ซึ่งเล่นได้ทุก browser
