# tools

## record-guide-videos.js

อัดวิดีโอสั้นของแต่ละเมนูที่แสดงในคู่มือของแอป (`search_anything/static/guide/*.mp4` และภาพหน้าปก `*.jpg`)

ต้องมี: Node.js, Playwright (`npm i playwright` แล้ว `npx playwright install chromium`) และ ffmpeg

1. เปิดแอปพร้อมข้อมูลตัวอย่าง เช่น โฟลเดอร์ที่มีไฟล์หลายชนิด โน้ต ลิงก์ และรหัสผ่าน
   - ตั้ง master password เป็น `masterpass1` แล้วล็อกตู้ไว้ วิดีโอ "ตู้รหัสผ่าน" จะสาธิตการปลดล็อก
   - วิดีโอ "ดูเนื้อหา" ใช้ไฟล์ชื่อ `billing_service.py` ที่มีคำว่า `rent`
2. อัดทั้งหมด:

   ```bash
   node tools/record-guide-videos.js
   ```

   หรืออัดเฉพาะบางเมนู:

   ```bash
   node tools/record-guide-videos.js search viewer
   ```

3. วิดีโอ "การสแกนไฟล์" ต้องอัดตอนที่กำลังสแกนอยู่จริง ให้เปิดเซิร์ฟเวอร์อีกตัวที่มีไฟล์เยอะ แล้วชี้ไปที่เซิร์ฟเวอร์นั้น:

   ```bash
   SCAN_URL=http://localhost:8766 node tools/record-guide-videos.js scan
   ```

สคริปต์จะวาดเคอร์เซอร์และคำอธิบายภาษาไทยลงในวิดีโอเอง แล้วแปลงเป็น MP4 (H.264, กว้าง 960 px) ซึ่งเล่นได้ทุก browser
