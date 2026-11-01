"""Old Office formats: Word .doc, Excel .xls, PowerPoint .ppt (97-2003).

The fixtures were made with LibreOffice from documents written by
python-docx/openpyxl/python-pptx (Thai + English, a table, a header, notes,
dates, a formula).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from cahon import legacy
from cahon.db import Database
from cahon.extractors import MAX_TEXT_CHARS, extract_text
from cahon.indexer import Indexer, ScanSettings

FIX = Path(__file__).parent / "fixtures"


def test_doc():
    text = legacy.doc_text(FIX / "report.doc", MAX_TEXT_CHARS)
    assert "รายงานการประชุม ประจำปี 2567" in text
    assert "งบประมาณรวม 1,250,000 บาท Invoice INV-2024-0042 สำนักงานใหญ่ น้ำประปา" in text
    assert "ช่อง 0-0\tช่อง 0-1\tช่อง 0-2\nช่อง 1-0" in text  # table: cells -> tabs, rows -> lines
    assert "บรรทัดแรก\nบรรทัดที่สอง" in text  # line break inside a paragraph
    assert "café naïve" in text
    assert "หัวกระดาษ บริษัท ตัวอย่าง จำกัด" in text  # header text is searchable too
    assert "\x07" not in text and "\x13" not in text


def test_xls():
    text = legacy.xls_text(FIX / "budget.xls", MAX_TEXT_CHARS)
    lines = text.split("\n")
    assert lines[0] == "# ยอดขาย"
    assert "กาแฟ\t3\t45.5\t2024-01-31 08:30:00\tTrue\t136.5" in lines  # 136.5 = cached formula result
    assert "ชาเขียว\t10\t0.3\t2023-12-25 00:00:00\tFalse" in lines
    assert "Total\t13\t1234567.125" in lines
    assert "# Sheet2" in lines


def test_ppt_skips_master_boilerplate():
    text = legacy.ppt_text(FIX / "plan.ppt", MAX_TEXT_CHARS)
    assert text.split("\n") == ["แผนงานไตรมาส 3", "เพิ่มยอดขาย 20 เปอร์เซ็นต์", "ลดต้นทุน", "ตารางสรุป",
                                "เซลล์ 00", "เซลล์ 01", "เซลล์ 10", "เซลล์ 11", "โน้ตผู้บรรยาย พูดเรื่องงบ"]
    assert "Click to edit" not in text


def test_cap():
    assert legacy.doc_text(FIX / "report.doc", 20) == legacy.doc_text(FIX / "report.doc", MAX_TEXT_CHARS)[:20]


def test_not_a_legacy_file(tmp_path):
    fake = tmp_path / "fake.doc"
    fake.write_bytes(b"this is not an OLE file")
    with pytest.raises(ValueError):
        legacy.doc_text(fake, MAX_TEXT_CHARS)
    assert extract_text(fake) == ""  # no content, no crash: found by name only


@pytest.mark.parametrize("name", ["report.doc", "budget.xls", "plan.ppt"])
def test_rust_reader_gives_the_same_text(name):
    native = pytest.importorskip("cahon_native")
    if not hasattr(native, "doc_text"):
        pytest.skip("cahon_native built before .doc/.xls/.ppt support")
    fn = {"doc": (legacy.doc_text, native.doc_text), "xls": (legacy.xls_text, native.xls_text),
          "ppt": (legacy.ppt_text, native.ppt_text)}[name.rsplit(".", 1)[1]]
    for cap in (MAX_TEXT_CHARS, 50):
        assert fn[1](str(FIX / name), cap) == fn[0](FIX / name, cap)


def test_scan_finds_words_inside_old_office_files(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    for f in ("report.doc", "budget.xls", "plan.ppt"):
        shutil.copy(FIX / f, docs / f)
    db = Database(tmp_path / "s.db")
    Indexer(db, [str(docs)], ScanSettings(ocr=False)).run()
    assert [r["title"] for r in db.search("น้ำประปา")] == ["report.doc"]
    assert [r["title"] for r in db.search("ชาเขียว")] == ["budget.xls"]
    assert [r["title"] for r in db.search("ลดต้นทุน")] == ["plan.ppt"]
