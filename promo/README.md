# CAHON promo film

A ~55-second promo film shown entirely through the real product: a continuous take of the CAHON window, with a camera that follows the hand and zooms in on each step. It never cuts and is not a slideshow.

Made with **[onetake](https://github.com/feitangyuan/onetake)** (Patrick, PolyForm Noncommercial 1.0.0: **free for noncommercial use only**). The library and the render scripts are not in this repo; `prepare-assets.sh` fetches them.

## Concept (v2: told in pictures, ~55 s)

**One search box, one take, told in pictures.** No captions: every pain and every answer is shown as an animation.

| t | beat | picture | camera |
|---|---|---|---|
| 0–2.4 | Can't find the file | The mascot hops from file to file in a messy pile; each file it checks gets a red ✕, and a "?" floats over its head | almost still |
| 2.4–4.4 | Scans can't be searched | A scanned page slides in; the mascot holds its magnifier over it, still can't read it, and gets sad | push in 1.25× |
| 4.4–5.9 | Things scattered everywhere | A note, a link and a key pop up and slip away in different directions | pull back |
| 5.5–6.6 | Searching takes forever | The mascot sits dozing next to a grey system search bar whose spinner keeps turning | close-up on the bar |
| 6.6 | **The turn** | The mascot jumps onto the bar → it becomes CAHON's search box, the pile blows away, the music starts | pull back to show the app |
| 7.9–14.7 | Type one word | Typing "สัญญาเช่า" → **a glowing line draws from the word to the file**, with a ring around it; the host ✓ | follow the hand |
| 15.7–21 | Remember only a number | Typing "35,000" → **a magnifier lands on the number inside the file** | dive 2×, dead still |
| 21.5–31.5 | Read a scan | Open the bill → press **อ่านด้วย OCR** → **a paper rises with a scan beam reading it** → it flies into the text, which gets a ring | close-up on the OCR row, then the text |
| 31.9–39.9 | Narrow it down | **PDF / W / X icons pop up** and **X jumps into the Excel chip**; **a calendar flips 1→7→14→21→30** | chase the badges, the calendar |
| 39.9–49.6 | Add a folder | Click add folder → pick it → **a folder flies into the panel** → the mascot in the panel scans it → a ring around the new folder | push in on the panel |
| 49.6–55.2 | The end | Pull back; the app becomes a window on the desk; only the box is left; the mascot hops onto it; the caret writes CAHON + "ค้นหาทุกอย่าง ในช่องเดียว" | pull back, then push in to 1×, dead still |

A small **host** mascot in the bottom-left corner reacts to every beat: working while searching, happy with a ✓ when something is found, celebrating when a job is done.

The footage plays at about 1–1.3× (a fast part at 2.4×), with holds after each answer. Sound: hops are "bubble", ✕ is "wood", a found result is a two-note chime. The music (made in code) drops out in the holds and while the OCR is reading.

Times come from `src/timeline.json` (recorded by `record-product.js`) through `SEGS` in `film/comp.html`, so a new take moves every animation with it. `score.py` reads its times from `film/events.json`, which is dumped from the comp's `__events()`. `film/comp-v1.html` is the first cut (captions, fast) kept for comparison.

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
