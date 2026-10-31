import time

import pytest

from search_anything import textview
from search_anything.textview import LineIndex, LineIndexCache


def test_range_reads_match_python_lines(tmp_path):
    p = tmp_path / "big.log"
    lines = [f"line {i} ค่าเช่า {'x' * (i % 7)}" for i in range(1, 30001)]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    idx = LineIndex(p)
    assert idx.total_lines == 30000 and idx.encoding == "utf-8"
    assert idx.lines(0, 3) == lines[:3]
    assert idx.lines(29998, 10) == lines[29998:]
    assert idx.lines(12345, 2) == lines[12345:12347]
    assert idx.lines(40000, 5) == []
    assert len(idx.offsets) * idx.offsets.itemsize < 300_000  # ~8 bytes per line, not the file


def test_line_endings_and_edge_cases(tmp_path):
    crlf = tmp_path / "w.txt"
    crlf.write_bytes(b"a\r\nb\r\nc")  # Windows endings, no newline at the end
    idx = LineIndex(crlf)
    assert idx.total_lines == 3 and idx.lines(0, 5) == ["a", "b", "c"]
    empty = tmp_path / "e.txt"
    empty.write_bytes(b"")
    assert LineIndex(empty).total_lines == 1 and LineIndex(empty).lines(0, 5) == [""]
    blank_end = tmp_path / "n.txt"
    blank_end.write_bytes(b"x\n\n")
    assert LineIndex(blank_end).lines(0, 5) == ["x", ""]


def test_encodings(tmp_path):
    thai = tmp_path / "thai.txt"
    thai.write_bytes("บรรทัดแรก\nค่าเช่า 5000\n".encode("cp874"))
    idx = LineIndex(thai)
    assert idx.encoding == "cp874" and idx.lines(1, 1) == ["ค่าเช่า 5000"]
    u16 = tmp_path / "u16.txt"
    u16.write_text("หนึ่ง\nสอง\n", encoding="utf-16")
    idx = LineIndex(u16)
    assert idx.encoding == "utf-16" and idx.lines(0, 2) == ["หนึ่ง", "สอง"]
    bom = tmp_path / "bom.txt"
    bom.write_bytes("﻿แรก\nสอง".encode("utf-8"))
    assert LineIndex(bom).lines(0, 2) == ["แรก", "สอง"]


def test_very_long_lines_are_cut_for_display(tmp_path):
    p = tmp_path / "min.js"
    p.write_text("a" * 50_000 + "\nok\n")
    first, second = LineIndex(p).lines(0, 2)
    assert len(first) <= textview.MAX_LINE_CHARS + 2 and first.endswith("…") and second == "ok"


def test_find_streams_and_caps(tmp_path):
    p = tmp_path / "x.log"
    p.write_text("".join(f"row {i}{' needle' if i % 10 == 0 else ''}{' NEEDLE' if i % 20 == 0 else ''}\n" for i in range(1, 1001)))
    res = LineIndex(p).find(["needle"], max_hits=5)
    assert res["total_lines"] == 100 and res["total_matches"] == 150 and len(res["hits"]) == 5
    assert res["hits"][0] == {"line": 10, "count": 1, "col": 7, "preview": "row 10 needle"}
    assert LineIndex(p).find([], 5)["hits"] == []


def test_find_stops_at_deadline(tmp_path, monkeypatch):
    p = tmp_path / "x.log"
    p.write_text("needle\n" * 20000)
    monkeypatch.setattr(textview, "FIND_DEADLINE", -1)
    res = LineIndex(p).find(["needle"])
    assert res["partial"] is True


def test_cache_rebuilds_when_file_changes(tmp_path):
    p = tmp_path / "c.txt"
    p.write_text("one\n")
    cache = LineIndexCache(size=2)
    a = cache.for_file(p)
    assert cache.for_file(p) is a
    time.sleep(0.01)
    p.write_text("one\ntwo\nthree\n")
    b = cache.for_file(p)
    assert b is not a and b.total_lines == 3


def test_big_file_index_is_quick(tmp_path):
    p = tmp_path / "huge.log"
    with p.open("w") as f:
        for i in range(400_000):
            f.write(f"line {i} some words here\n")
    t = time.time()
    idx = LineIndex(p)
    assert idx.total_lines == 400_000
    assert time.time() - t < 5
    assert idx.lines(399_999, 1) == ["line 399999 some words here"]
