"""Read text out of scanned PDFs and images (OCR) with Tesseract.

Tesseract is an external program (``tesseract``), with the Thai language
data (``tha``). The Docker image ships both; on a computer without them OCR
simply stays off and everything else works as before.

* PDFs: only pages without a text layer (scans, photos of paper) are read;
  pages with real text are left to the normal extractor.
* Pages are rendered in grayscale at 300 dpi (smaller for huge pages) with
  pdfium, then passed to Tesseract one at a time, so memory stays small.
* Tesseract writes Thai "ำ" as two characters (nikhahit + sara aa); it is
  joined back so searches typed on a keyboard match.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .extractors import PDFIUM_LOCK, normalize_thai

log = logging.getLogger(__name__)

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
DPI = 300
MAX_SIDE_PX = 4200  # pages larger than ~A3 at 300 dpi are scaled down
MIN_IMAGE_SIDE = 200  # icons and thumbnails are skipped
MAX_IMAGE_PIXELS = 80_000_000
TEXT_PAGE_CHARS = 30  # a PDF page with fewer real characters is treated as a scan
PAGE_TIMEOUT = 120  # seconds Tesseract may take for one page
DEFAULT_MAX_PAGES = 100
MARK = "\n\n=== ข้อความจากภาพสแกน (OCR) ===\n"
WANTED_LANGS = ("tha", "eng")

_WINDOWS_PATHS = (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe")
_UNIX_PATHS = ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract", "/usr/bin/tesseract")


class Stopped(Exception):
    """The scan was stopped while a file was being read."""


@dataclass
class Engine:
    path: str | None
    version: str = ""
    langs: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return bool(self.path and self.lang)

    @property
    def thai(self) -> bool:
        return "tha" in self.langs

    @property
    def lang(self) -> str:
        return "+".join(l for l in WANTED_LANGS if l in self.langs)

    def info(self) -> dict:
        return {"available": self.available, "installed": bool(self.path), "thai": self.thai,
                "version": self.version, "langs": [l for l in WANTED_LANGS if l in self.langs]}


_engine: Engine | None = None
_engine_at = 0.0
_engine_lock = threading.Lock()


def _find_binary() -> str | None:
    env = os.environ.get("CAHON_TESSERACT")
    if env:
        return env if Path(env).is_file() else None
    found = shutil.which("tesseract")
    if found:
        return found
    for p in _WINDOWS_PATHS if sys.platform.startswith("win") else _UNIX_PATHS:
        if Path(p).is_file():
            return p
    return None


def engine(max_age: float = 60.0) -> Engine:
    """Tesseract on this computer (checked at most once a minute)."""
    global _engine, _engine_at
    with _engine_lock:
        if _engine is not None and time.monotonic() - _engine_at < max_age:
            return _engine
        path = _find_binary()
        eng = Engine(path)
        if path:
            try:
                out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10,
                                     **_quiet()).stdout
                eng.version = (out.splitlines() or [""])[0].replace("tesseract", "").strip()
                listing = subprocess.run([path, "--list-langs"], capture_output=True, text=True, timeout=10,
                                         **_quiet()).stdout
                eng.langs = tuple(l.strip() for l in listing.splitlines()[1:] if l.strip())
            except (OSError, subprocess.SubprocessError) as exc:
                log.warning("tesseract found at %s but did not run: %s", path, exc)
                eng = Engine(None)
        _engine, _engine_at = eng, time.monotonic()
        return eng


def _quiet() -> dict:
    """No console windows popping up on Windows."""
    if sys.platform.startswith("win"):
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    return {}


def _low_priority() -> dict:
    if sys.platform.startswith("win"):
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)
        return {"creationflags": flags}

    def nice():
        try:
            os.nice(10)
        except OSError:
            pass

    return {"preexec_fn": nice}


def is_candidate(path: str, images: bool) -> bool:
    suffix = os.path.splitext(path)[1].lower()
    return suffix in PDF_EXTENSIONS or (images and suffix in IMAGE_EXTENSIONS)


_BLANKS = re.compile(r"\n{3,}")


def clean(text: str) -> str:
    text = normalize_thai(text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return _BLANKS.sub("\n\n", text).strip()


class Reader:
    """OCR for one scan session. ``should_stop`` is polled while Tesseract runs."""

    def __init__(self, eng: Engine, threads: int = 1, should_stop=lambda: False):
        self.eng = eng
        self.threads = max(1, threads)
        self.should_stop = should_stop
        self.on_page = None  # callback(page_no, page_count)

    # -------------------------------------------------------------- tesseract
    def _tesseract(self, image, extra: tuple[str, ...] = ()) -> str:
        """Text of one image, without the lines Tesseract is unsure of (see keep_confident)."""
        fd, tmp = tempfile.mkstemp(prefix="cahon-ocr-", suffix=".png")
        os.close(fd)
        base = tmp[:-4] + "-out"
        try:
            image.save(tmp, "PNG", compress_level=1)
            # One pass writes both the text (.txt) and per-word confidence (.tsv).
            if not self._run([self.eng.path, tmp, base, "-l", self.eng.lang, "--psm", "3", *extra, "txt", "tsv"]):
                return ""
            try:
                text = Path(base + ".txt").read_text(encoding="utf-8", errors="replace")
            except OSError:  # no "txt"/"tsv" configs in this Tesseract: plain text
                return self._plain(tmp)
            try:
                tsv = Path(base + ".tsv").read_text(encoding="utf-8", errors="replace")
            except OSError:
                return text
            return keep_confident(text, tsv)
        finally:
            for f in (tmp, base + ".txt", base + ".tsv"):
                try:
                    os.unlink(f)
                except OSError:
                    pass

    def _plain(self, image_path: str) -> str:
        out = self._run([self.eng.path, image_path, "stdout", "-l", self.eng.lang, "--psm", "3"], capture=True)
        return out or ""

    def _run(self, cmd: list[str], capture: bool = False):
        env = {**os.environ, "OMP_THREAD_LIMIT": str(self.threads)}
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, env=env, **_low_priority())
        started = time.monotonic()
        while True:
            try:
                out, _ = proc.communicate(timeout=0.3)
                break
            except subprocess.TimeoutExpired:
                if self.should_stop():
                    proc.kill()
                    proc.communicate()
                    raise Stopped()
                if time.monotonic() - started > PAGE_TIMEOUT:
                    proc.kill()
                    proc.communicate()
                    log.warning("OCR page timed out")
                    return None
        if capture:
            return out.decode("utf-8", errors="replace")
        return proc.returncode == 0

    # -------------------------------------------------------------------- pdf
    def read_pdf(self, path: str, max_pages: int, force: bool = False) -> tuple[str, int]:
        """Text of the scanned pages, and how many pages were read with OCR.
        ``force`` reads every page, also those with a text layer (a broken or
        partial text layer, or text drawn as pictures), more carefully."""
        import pypdfium2 as pdfium

        with PDFIUM_LOCK:
            pdf = pdfium.PdfDocument(path)
        try:
            with PDFIUM_LOCK:
                total = len(pdf)
                scans = []
                for i in range(total):
                    page = pdf[i]
                    try:
                        textpage = page.get_textpage()
                        chars = len("".join(textpage.get_text_range().split()))
                        textpage.close()
                    finally:
                        page.close()
                    if force or chars < TEXT_PAGE_CHARS:
                        scans.append(i)
                    if len(scans) >= max_pages:
                        break
            parts = []
            for n, i in enumerate(scans):
                if self.should_stop():
                    raise Stopped()
                if self.on_page:
                    self.on_page(n + 1, len(scans))
                with PDFIUM_LOCK:
                    page = pdf[i]
                    try:
                        w, h = page.get_size()  # points
                        scale = min(DPI / 72, MAX_SIDE_PX / max(w, h, 1))
                        bitmap = page.render(scale=scale, grayscale=True)
                        image = bitmap.to_pil().copy()  # own the pixels: the bitmap is freed next
                        bitmap.close()
                    finally:
                        page.close()
                text = self._read_picture(image) if force else clean(self._tesseract(image))
                image.close()
                if text:
                    parts.append(f"--- หน้า {i + 1} ---\n{text}" if total > 1 else text)
            return "\n\n".join(parts), len(scans)
        finally:
            with PDFIUM_LOCK:
                pdf.close()

    # ----------------------------------------------------------------- images
    def read_image(self, path: str, max_pages: int) -> tuple[str, int]:
        from PIL import Image, ImageOps, ImageSequence

        Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
        parts, pages = [], 0
        with Image.open(path) as img:
            frames = getattr(img, "n_frames", 1)
            for n, frame in enumerate(ImageSequence.Iterator(img)):
                if n >= max_pages:
                    break
                if self.should_stop():
                    raise Stopped()
                if self.on_page and frames > 1:
                    self.on_page(n + 1, min(frames, max_pages))
                page = ImageOps.exif_transpose(frame.convert("L"))
                if min(page.size) < MIN_IMAGE_SIDE:
                    continue
                if max(page.size) > MAX_SIDE_PX:
                    page.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
                pages += 1
                text = self._read_picture(page)
                if text:
                    parts.append(f"--- หน้า {n + 1} ---\n{text}" if frames > 1 else text)
        return "\n\n".join(parts), pages

    def _read_picture(self, page) -> str:
        """Pictures (photos, screenshots, chat images) are often small, shrunk and
        recompressed, with pale text on mixed backgrounds. Measured on such
        images (tools/README, "OCR"): enlarging small ones and adding a second
        pass with adaptive thresholding found 82% of the words instead of 58%."""
        from PIL import Image

        f = min(UPSCALE_MAX, UPSCALE_TO_PX / max(page.size))
        if f > 1.05:
            page = page.resize((round(page.width * f), round(page.height * f)), Image.LANCZOS)
        text = clean(self._tesseract(page))
        if not text:
            return ""  # no text found: skip the second pass (most photos)
        second = clean(self._tesseract(page, ("-c", "thresholding_method=1")))
        return merge_passes(text, second)

    def read(self, path: str, max_pages: int = DEFAULT_MAX_PAGES, force: bool = False) -> tuple[str, int]:
        if os.path.splitext(path)[1].lower() in PDF_EXTENSIONS:
            return self.read_pdf(path, max_pages, force)
        return self.read_image(path, max_pages)


MIN_LINE_CONFIDENCE = 60  # mean Tesseract confidence (0-100) a line needs to be kept
UPSCALE_TO_PX = 2600  # pictures smaller than this (longest side) are enlarged …
UPSCALE_MAX = 3.0  # … by at most this factor
_SPACES = re.compile(r"\s+")


def merge_passes(first: str, second: str) -> str:
    """The first pass, plus lines only the second pass found (with at least
    three letters or digits, so stray marks from busy backgrounds stay out)."""
    seen = _SPACES.sub("", first)
    extra = []
    for line in second.splitlines():
        flat = _SPACES.sub("", line)
        if flat and flat not in seen and sum(ch.isalnum() for ch in flat) >= 3:
            extra.append(line.strip())
            seen += flat
    return first + ("\n" + "\n".join(extra) if extra else "")


def keep_confident(text: str, tsv: str) -> str:
    """Drop the lines Tesseract is unsure of.

    Photos without text (leaves, fabric, faces…) come out as junk like
    "Say | ri , 7 ด 8" with confidence 0-50, while real text scores 80-97.
    Tesseract writes the non-empty lines of ``text`` in the same order as the
    line records of ``tsv``; each line's mean word confidence (weighted by
    length) decides. If the two do not line up, the text is kept as it is.
    """
    lines: dict[tuple, list[tuple[float, int]]] = {}
    order: list[tuple] = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12:
            continue
        key = tuple(cols[1:5])  # page, block, paragraph, line
        if cols[0] == "4":
            order.append(key)
            lines[key] = []
        elif cols[0] == "5" and cols[11].strip() and key in lines:
            try:
                conf = float(cols[10])
            except ValueError:
                continue
            if conf >= 0:
                lines[key].append((conf, len(cols[11].strip())))
    scored = [lines[k] for k in order if lines[k]]
    out_lines = text.splitlines()
    non_empty = [i for i, line in enumerate(out_lines) if line.strip()]
    if len(non_empty) != len(scored):
        return text
    drop = set()
    for i, words in zip(non_empty, scored):
        total = sum(n for _, n in words)
        mean = sum(c * n for c, n in words) / total if total else 0
        if mean < MIN_LINE_CONFIDENCE or not any(ch.isalnum() for ch in out_lines[i]):
            drop.add(i)
    return "\n".join(line for i, line in enumerate(out_lines) if i not in drop)


def merge(body: str, ocr_text: str) -> str:
    """Body text with the OCR section (replacing an older one)."""
    base = body.split(MARK, 1)[0]
    return base + MARK + ocr_text if ocr_text else base
