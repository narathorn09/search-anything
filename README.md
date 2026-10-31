# Search Anything

ช่องค้นหาช่องเดียว ค้นได้ทุกอย่าง: **ชื่อไฟล์ เนื้อหาในไฟล์ โน้ต ลิงก์ (bookmark) และรหัสผ่าน**
พิมพ์แล้วเห็นผลลัพธ์ทันที ไม่ต้องไล่เปิดหลายที่

- ค้นภาษาไทยได้ แม้คำจะติดกันไม่เว้นวรรค (ใช้ SQLite FTS5 แบบ trigram จับคำย่อยตั้งแต่ 3 ตัวอักษร ถ้าพิมพ์สั้นกว่านั้นจะค้นแบบ LIKE แทน)
- อ่านเนื้อหาไฟล์ข้อความ/โค้ด, `.pdf`, `.docx` ส่วนไฟล์ชนิดอื่น (รูป วิดีโอ ฯลฯ) ค้นได้จากชื่อไฟล์และชื่อโฟลเดอร์
- รหัสผ่านเข้ารหัสด้วย master password (scrypt + Fernet) ค้นได้จากชื่อ / username / URL แต่ตัวรหัสผ่านไม่ถูกเก็บเป็นข้อความธรรมดาและไม่ถูกนำไปค้นหา
- ตู้รหัสผ่านล็อกตัวเองอัตโนมัติเมื่อไม่ได้ใช้ 15 นาที

## ติดตั้ง

ต้องใช้ Python 3.10 ขึ้นไป

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

```bash
pip install -r requirements.txt
```

## โหมด Local (ใช้บนเครื่องตัวเอง)

```bash
python -m search_anything --folder ~/Documents --folder ~/Desktop
```

แล้วเปิด http://localhost:8765

- รันอยู่บน `127.0.0.1` เท่านั้น เครื่องอื่นเข้าไม่ได้ จึงไม่ต้องล็อกอิน
- เพิ่ม/ลบโฟลเดอร์ที่ให้ค้นได้จาก ⚙️ ในหน้าเว็บ (ระบบจำไว้ให้)
- กด Enter ที่ผลลัพธ์ที่เป็นไฟล์ จะเปิดไฟล์ด้วยโปรแกรมปกติของเครื่อง

## โหมด Server (เข้าจากที่ไหนก็ได้)

```bash
SA_PASSWORD='รหัสผ่านสำหรับล็อกอิน' python -m search_anything --mode server --folder /srv/files
```

- ต้องล็อกอินด้วย `SA_PASSWORD` ก่อนใช้งาน (ระบบนี้ออกแบบให้ใช้คนเดียว)
- อัปโหลดไฟล์ขึ้นเซิร์ฟเวอร์ผ่าน ⚙️ ได้ ไฟล์จะถูกเก็บใน `data/uploads/` และค้นหาได้ทันที
- ไฟล์ที่ค้นเจอจะ **ดาวน์โหลด** แทนการเปิดในเครื่อง
- ถ้าเปิดให้เข้าจากอินเทอร์เน็ต ควรวางไว้หลัง HTTPS (เช่น Caddy, nginx, Cloudflare Tunnel) และใส่ `--https-cookie`
- จำกัดชื่อโดเมนที่รับได้ด้วย `--allowed-host search.example.com` ได้

## ตัวเลือกทั้งหมด

| ตัวเลือก | ตัวแปร environment | ค่าเริ่มต้น | ความหมาย |
|---|---|---|---|
| `--mode` | `SA_MODE` | `local` | `local` หรือ `server` |
| `--host` | `SA_HOST` | `127.0.0.1` (local) / `0.0.0.0` (server) | address ที่รับการเชื่อมต่อ |
| `--port` | `SA_PORT` | `8765` | พอร์ต |
| `--data-dir` | `SA_DATA_DIR` | `data` | ที่เก็บฐานข้อมูลและไฟล์อัปโหลด |
| `--folder` (ใส่ซ้ำได้) | `SA_FOLDERS` (คั่นด้วย `:` หรือ `;` บน Windows) | – | โฟลเดอร์ที่จะสแกน |
| `--reindex-interval` | `SA_REINDEX_INTERVAL` | `300` | สแกนไฟล์ใหม่ทุกกี่วินาที (สแกนเฉพาะไฟล์ที่เปลี่ยน) |
| `--auto-lock` | `SA_AUTO_LOCK` | `900` | ล็อกตู้รหัสผ่านหลังไม่ได้ใช้กี่วินาที |
| `--allowed-host` | `SA_ALLOWED_HOSTS` (คั่นด้วย `,`) | `*` (server) | ชื่อโดเมนที่อนุญาต |
| `--https-cookie` | `SA_HTTPS_COOKIE=1` | ปิด | ส่ง cookie ผ่าน HTTPS เท่านั้น |
| – | `SA_PASSWORD` | – | รหัสผ่านล็อกอิน (จำเป็นในโหมด server) |

## คีย์ลัด

| ปุ่ม | ทำอะไร |
|---|---|
| `/` หรือ `Ctrl/⌘ + K` | ไปที่ช่องค้นหา |
| `↑` `↓` | เลือกผลลัพธ์ |
| `Enter` | ไฟล์ → เปิด/ดาวน์โหลด · ลิงก์ → เปิดเว็บ · รหัสผ่าน → คัดลอก · โน้ต → แก้ไข |
| `Esc` | ล้างช่องค้นหา |

## ความปลอดภัย

- **ถ้าลืม master password จะกู้รหัสผ่านที่เก็บไว้ไม่ได้**
- ข้อมูลทั้งหมดอยู่ใน `data/search.db` ควรสำรองไฟล์นี้ (รหัสผ่านในไฟล์ถูกเข้ารหัส แต่โน้ต ลิงก์ และเนื้อหาไฟล์ที่ index ไว้ไม่ได้เข้ารหัส)
- โหมด local ตรวจ `Host` header เพื่อกันเว็บอื่นแอบเรียก API ผ่าน DNS rebinding

## โครงสร้าง

```
search_anything/
  __main__.py   # CLI: python -m search_anything
  app.py        # FastAPI routes, โหมด local/server, ล็อกอิน
  db.py         # SQLite + FTS5 trigram index และการค้นหา
  indexer.py    # สแกนโฟลเดอร์ ดึงข้อความจากไฟล์ (txt/code/pdf/docx)
  vault.py      # เข้ารหัส/ถอดรหัสรหัสผ่าน
  static/       # หน้าเว็บ (HTML/CSS/JS ล้วน ไม่ต้อง build)
tests/
```

รันเทสต์:

```bash
pip install pytest httpx && python -m pytest
```
