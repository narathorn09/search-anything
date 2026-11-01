# CAHON promo film

A ~31-second promo film shown entirely through the real product: a continuous take of the CAHON window, with a camera that follows the hand and zooms in on each step. It never cuts and is not a slideshow.

Made with **[onetake](https://github.com/feitangyuan/onetake)** (Patrick, PolyForm Noncommercial 1.0.0: **free for noncommercial use only**). The library and the render scripts are not in this repo; `prepare-assets.sh` fetches them.

## Concept

**One search box, one take.** The search box is the spine of the film. It starts as a grey system search lost in a pile of files, and it finds nothing (the pain). It becomes CAHON's search box in the same spot. Every word typed opens straight into what it found: a file, a number inside a file, a scanned bill the mascot reads. The camera never cuts. At the end the camera pulls back, only the search box is left, and its caret writes **CAHON**.

| t | beat | camera | what carries into the next beat |
|---|---|---|---|
| 0.00–1.85 | System search types "สัญญาเช่า", spins; files scattered around; silent | close-up 1.5×, almost still | the box |
| 1.85 | "ไม่พบรายการ" (no results), the pile shakes | shake | — |
| 2.00–2.88 | Three hits: "ชื่อไฟล์?" "PDF สแกน?" "รหัสผ่าน?" (hard cuts) | shake on each hit | — |
| 3.10 | **ENTER**: the box becomes CAHON's, the files blow away, music starts | pull back 1.4× → 0.94× | the box |
| 3.6–7.2 | The hand clicks the box, types "สัญญาเช่า" → result → the file opens | snap to the box, follow down to the result, glide to the details | the box |
| 7.4–10.5 | "35,000" (remember only a number) → highlighted inside the file | whip back to the box, dive 2.15× onto the highlight; **dead still for 1 s, music stops** | the box |
| 11.0–16.8 | "ใบแจ้งหนี้" → open → **อ่านด้วย OCR**, the mascot reads it → text appears | close-up on the OCR row 2×, pull back to the text | the box |
| 17.3–20.3 | **Burst**: type chips → time range menu → results ("ประเภทไฟล์", "ช่วงเวลา", "เจอแล้ว") | whip × 3 | — |
| 20.3–21.3 | Rest | dead still | the folder panel |
| 22.0–26.6 | Add a folder → pick it → the mascot scans it | panel → folder window → close-up on the mascot | the mascot |
| 27.4–28.6 | Pull back: the app is a window on the desk; the box separates from it, the mascot hops onto the box | pull back to 0.66× | the box |
| 29.0–31.6 | The caret writes C·A·H·O·N, "ค้นหาทุกอย่าง ในช่องเดียว", Windows · Mac · GitHub | push to 1.0×, then dead still | — |

Captions name the pain first (red), then the answer (green). Sound uses onetake's palette (one room, few events). The music is generated in code: no samples, no licences.

## Making it again

Needs Node + Playwright, Python 3 with `playwright numpy scipy Pillow`, ffmpeg, Xvfb, and Tesseract (OCR).

1. Demo data and the app (see `../tools/README.md`): `python tools/make_demo_data.py files /tmp/cahon-demo`, start the app with OCR scanning turned off and `HOME=/tmp/cahon-demo/home`, then `python tools/make_demo_data.py items http://localhost:8765`.

2. Record the real app on a 2560×1440 virtual screen. This writes `public/product.mp4` and `src/timeline.json` (when and where each step happens):

   ```bash
   Xvfb :99 -screen 0 2560x1440x24 &
   ```

   ```bash
   DISPLAY=:99 BASE_URL=http://localhost:8765 node record-product.js
   ```

3. Fetch onetake and the fonts, and split the footage into frames:

   ```bash
   ./prepare-assets.sh
   ```

   ```bash
   mkdir -p public/frames && ffmpeg -i public/product.mp4 -vf fps=30 -q:v 3 public/frames/%04d.jpg
   ```

4. Sound, preview, render:

   ```bash
   cd film && python3 score.py
   ```

   ```bash
   python3 ~/onetake/scripts/stills.py comp.html --times 1.5,9.9,14,18.3,29.3 --out ../out/stills.png
   ```

   ```bash
   python3 ~/onetake/scripts/render.py comp.html --out ../out/cahon-promo.mp4 --sfx sfx.wav
   ```

If you record a new take, the times change: update `FOOT` (film time → recording time) and `KEYS` (the camera) in `film/comp.html` from the new `src/timeline.json`.
