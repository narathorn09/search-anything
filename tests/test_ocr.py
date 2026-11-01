"""OCR of scanned PDFs / images, and Thai text repair."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from search_anything import ocr
from search_anything.db import Database
from search_anything.extractors import extract_text, normalize_thai
from search_anything.indexer import Indexer, ScanSettings

THAI_FONT = "/usr/share/fonts/opentype/tlwg/Loma.otf"
needs_tesseract = pytest.mark.skipif(not ocr.engine().available, reason="tesseract not installed")
needs_thai = pytest.mark.skipif(not (ocr.engine().thai and Path(THAI_FONT).exists()),
                                reason="Thai OCR data or font missing")


def scanned_pdf(path: Path, lines: list[str], pages: int = 1, font: str | None = None) -> Path:
    """An image-only PDF (no text layer), like a scanner makes."""
    from PIL import Image, ImageDraw, ImageFont

    face = ImageFont.truetype(font, 34) if font else ImageFont.load_default(size=40)
    images = []
    for p in range(pages):
        img = Image.new("L", (1654, 2339), 255)  # A4 at 200 dpi
        draw = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            draw.text((120, 150 + 80 * i), f"{line} {p + 1}" if i == 0 else line, font=face, fill=0)
        images.append(img.convert("RGB"))
    images[0].save(path, save_all=True, append_images=images[1:], resolution=200)
    return path


def test_normalize_thai():
    # Private-use tone marks (from PDF fonts) and the two-character "ำ".
    assert normalize_thai("เชา สํานักงาน น้ํา") == "เช่า สำนักงาน น้ำ"
    assert normalize_thai("นํ้า") == "น้ำ"
    assert normalize_thai("สำ นักงาน", pdf=True) == "สำนักงาน"
    assert normalize_thai("สำ นักงาน") == "สำ นักงาน"  # only PDFs have layout gaps
    assert normalize_thai("plain english") == "plain english"


def test_merge_replaces_old_ocr_section():
    body = ocr.merge("base text", "first")
    assert body.endswith("first") and body.startswith("base text")
    assert ocr.merge(body, "second") == ocr.merge("base text", "second")
    assert ocr.merge(body, "") == "base text"


def test_candidates():
    assert ocr.is_candidate("/a/scan.PDF", images=False)
    assert not ocr.is_candidate("/a/photo.jpg", images=False)
    assert ocr.is_candidate("/a/photo.jpg", images=True)
    assert not ocr.is_candidate("/a/notes.txt", images=True)


def test_missing_tesseract_keeps_scanning(tmp_path, monkeypatch):
    monkeypatch.setenv("SA_TESSERACT", str(tmp_path / "nope"))
    try:
        assert not ocr.engine(max_age=0).available
        docs = tmp_path / "docs"
        docs.mkdir()
        scanned_pdf(docs / "scan.pdf", ["HELLO"])
        db = Database(tmp_path / "s.db")
        stats = Indexer(db, [str(docs)]).run()
        assert stats.ocr_files == 0 and db.counts()["file"] == 1
        assert db.search("scan")  # still found by name
    finally:
        monkeypatch.delenv("SA_TESSERACT")
        ocr.engine(max_age=0)


@needs_tesseract
def test_scanned_pdf_becomes_searchable(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    scanned_pdf(docs / "contract.pdf", ["RENTAL AGREEMENT", "Invoice ZEBRA-4471", "Total 12500 THB"], pages=2)
    (docs / "note.txt").write_text("just text")
    assert extract_text(docs / "contract.pdf") == ""  # no text layer
    db = Database(tmp_path / "s.db")
    ix = Indexer(db, [str(docs)])
    stats = ix.run()
    assert stats.ocr_files == 1 and stats.ocr_pages == 2
    hits = db.search("ZEBRA-4471")
    assert [h["title"] for h in hits] == ["contract.pdf"]
    body = db.get_item(hits[0]["id"], 100000)["body"]
    assert "หน้า 1" in body and "หน้า 2" in body and "OCR" in body
    assert db.ocr_summary()["done"] == 1

    # Unchanged: not read again. A newer extractor re-reads the file but keeps the OCR text.
    assert ix.run().ocr_files == 0
    db.set_meta("extractor_version", 1)
    assert ix.run().ocr_files == 0
    assert db.search("ZEBRA-4471")

    # Changed file: read again; deleted file: forgotten.
    scanned_pdf(docs / "contract.pdf", ["RENTAL AGREEMENT", "Invoice KOALA-9001"])
    os.utime(docs / "contract.pdf", (1, 1))
    assert ix.run().ocr_files == 1
    assert db.search("KOALA-9001") and not db.search("ZEBRA-4471")
    (docs / "contract.pdf").unlink()
    ix.run()
    assert db.ocr_states() == {}


@needs_tesseract
def test_ocr_can_be_turned_off_and_images_are_optional(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    docs = tmp_path / "docs"
    docs.mkdir()
    scanned_pdf(docs / "scan.pdf", ["WALRUS-123"])
    img = Image.new("L", (1200, 400), 255)
    ImageDraw.Draw(img).text((40, 150), "PELICAN-777", font=ImageFont.load_default(size=60), fill=0)
    img.save(docs / "photo.png")
    db = Database(tmp_path / "s.db")
    ix = Indexer(db, [str(docs)], ScanSettings(ocr=False))
    assert ix.run().ocr_files == 0 and not db.search("WALRUS-123")
    ix.update_settings(ScanSettings(ocr=True, ocr_images=False))
    assert ix.run().ocr_files == 1 and db.search("WALRUS-123") and not db.search("PELICAN-777")
    ix.update_settings(ScanSettings(ocr=True, ocr_images=True))
    assert ix.run().ocr_files == 1 and db.search("PELICAN-777")


@needs_tesseract
def test_blank_pdf_is_remembered(tmp_path):
    import pypdfium2 as pdfium

    docs = tmp_path / "docs"
    docs.mkdir()
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(595, 842).close()
    pdf.save(str(docs / "empty.pdf"))
    pdf.close()
    db = Database(tmp_path / "s.db")
    stats = Indexer(db, [str(docs)]).run()
    # A blank page has no text layer: it is read, finds nothing, and is remembered.
    assert stats.ocr_files == 1
    assert db.ocr_summary()["none"] == 1


@needs_thai
def test_thai_scan(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    scanned_pdf(docs / "สัญญา.pdf", ["สัญญาเช่าพื้นที่สำนักงาน เลขที่ 2567/0142",
                                     "ค่าเช่าเดือนละ 45,000 บาท ชำระภายในวันที่ 5",
                                     "ใบเสร็จรับเงิน ภาษีมูลค่าเพิ่ม"], font=THAI_FONT)
    db = Database(tmp_path / "s.db")
    Indexer(db, [str(docs)]).run()
    for word in ("สำนักงาน", "ชำระ", "ใบเสร็จรับเงิน", "2567/0142"):
        assert db.search(word), word


@needs_tesseract
def test_ocr_in_worker_process(tmp_path):
    from search_anything.worker import ProcessIndexer

    docs = tmp_path / "docs"
    docs.mkdir()
    scanned_pdf(docs / "scan.pdf", ["OTTER-5150"])
    db = Database(tmp_path / "s.db")
    stats = ProcessIndexer(db, [str(docs)]).run()
    assert stats.ocr_files == 1
    assert db.search("OTTER-5150")


def test_keep_confident_drops_unsure_lines():
    tsv = "\n".join([
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext",
        "4\t1\t1\t1\t1\t0\t0\t0\t0\t0\t-1\t",
        "5\t1\t1\t1\t1\t1\t0\t0\t0\t0\t96\tใบเสร็จ",
        "5\t1\t1\t1\t1\t2\t0\t0\t0\t0\t93\t12,500",
        "4\t1\t1\t1\t2\t0\t0\t0\t0\t0\t-1\t",
        "5\t1\t1\t1\t2\t1\t0\t0\t0\t0\t21\tSay",
        "5\t1\t1\t1\t2\t2\t0\t0\t0\t0\t3\t|ri,",
        "4\t1\t2\t1\t1\t0\t0\t0\t0\t0\t-1\t",
        "5\t1\t2\t1\t1\t1\t0\t0\t0\t0\t91\t|",
    ])
    text = "ใบเสร็จ 12,500\nSay |ri,\n\n|\n"
    assert ocr.keep_confident(text, tsv) == "ใบเสร็จ 12,500\n"
    # Lines that do not match the TSV: keep everything rather than guess.
    assert ocr.keep_confident("one\ntwo", tsv) == "one\ntwo"


@needs_tesseract
def test_images_are_read_by_default_and_photos_without_text_add_nothing(tmp_path):
    import random

    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    docs = tmp_path / "docs"
    docs.mkdir()
    shot = Image.new("RGB", (1300, 300), "white")
    ImageDraw.Draw(shot).text((40, 100), "SLIP TRANSFER 4,250 THB", font=ImageFont.load_default(size=56), fill="black")
    shot.save(docs / "slip.jpg")
    rng = random.Random(7)  # a busy picture with no writing (fabric/leaves)
    pic = Image.new("L", (1600, 1200), 128)
    draw = ImageDraw.Draw(pic)
    for _ in range(4000):
        x, y = rng.randrange(1600), rng.randrange(1200)
        draw.rectangle((x, y, x + rng.randint(2, 14), y + rng.randint(2, 30)), fill=rng.choice([0, 255, 60, 200]))
    pic.filter(ImageFilter.GaussianBlur(0.6)).save(docs / "texture.jpg")
    db = Database(tmp_path / "s.db")
    stats = Indexer(db, [str(docs)]).run()  # default settings
    assert stats.ocr_files == 2
    assert [r["title"] for r in db.search("TRANSFER")] == ["slip.jpg"]
    texture = db.search("texture")[0]
    body = db.get_item(texture["id"], 100000)["body"]
    assert ocr.MARK not in body  # nothing confident enough: no OCR text at all
    assert db.ocr_summary()["none"] == 1


def test_merge_passes_adds_only_new_lines():
    first = "ใบแจ้งหนี้ เลขที่ 42\nยอดรวม 1,250 บาท"
    second = "ใบแจ้งหนี้ เลขที่ 42\nกรุณาชำระภายในวันที่ 15\n| a \\\nยอดรวม 1,250 บาท"
    assert ocr.merge_passes(first, second) == first + "\nกรุณาชำระภายในวันที่ 15"
    assert ocr.merge_passes(first, "") == first
