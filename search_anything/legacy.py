"""Old binary Office formats: Word .doc, Excel .xls, PowerPoint .ppt (97-2003).

These are the Python readers. The Rust module (native/src/legacy.rs, xls via
calamine) produces exactly the same text, faster; tests/test_native.py checks
it. Both follow the same rules:

* .doc - the text of the whole document (body, footnotes, headers, comments,
  text boxes) from the piece table, with field codes removed (a hyperlink
  shows its text, not "HYPERLINK ..."), table cells joined by tabs.
* .ppt - every text atom outside the slide masters (the "Click to edit
  Master title style" boilerplate), in file order, one per line.
* .xls - like .xlsx: "# sheet name", then each row's non-empty cells joined
  by tabs, numbers and dates printed the way Python prints them.

Encrypted or very old (Word 6/95) files raise ValueError; the file stays
searchable by name.
"""

from __future__ import annotations

import re
import struct
from pathlib import Path

MAX_STREAM_BYTES = 256 * 1024 * 1024
_BLANKS = re.compile(r"\n{3,}")


def _open_ole(path: Path):
    import olefile

    if not olefile.isOleFile(str(path)):
        raise ValueError("not an OLE2 (97-2003) file")
    return olefile.OleFileIO(str(path))


def _read_stream(ole, name: str) -> bytes:
    if not ole.exists(name):
        raise ValueError(f"no {name} stream")
    if ole.get_size(name) > MAX_STREAM_BYTES:
        raise ValueError(f"{name} is too large")
    return ole.openstream(name).read()


def finish(text: str, cap: int) -> str:
    """Shared clean-up: trailing spaces/tabs off each line, at most one blank line."""
    text = "\n".join(line.rstrip(" \t") for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip(" \t\n")[:cap]


# --------------------------------------------------------------------- .doc
_CTRL_MAP = {
    0x0D: "\n", 0x0B: "\n", 0x0C: "\n", 0x0E: "\n",  # paragraph, line, page, column breaks
    0x09: "\t", 0x1E: "-", 0xA0: " ",  # tab, non-breaking hyphen, no-break space
}


def doc_text(path: Path, cap: int) -> str:
    ole = _open_ole(path)
    try:
        word = _read_stream(ole, "WordDocument")
        if len(word) < 0x200 or struct.unpack_from("<H", word, 0)[0] != 0xA5EC:
            raise ValueError("not a Word 97-2003 document")
        flags = struct.unpack_from("<H", word, 0x0A)[0]
        if flags & 0x0100:
            raise ValueError("encrypted document")
        csw = struct.unpack_from("<H", word, 32)[0]
        lw_at = 32 + 2 + csw * 2
        cslw = struct.unpack_from("<H", word, lw_at)[0]
        ccps = struct.unpack_from("<11I", word, lw_at + 2)[3:11]  # ccpText ... ccpHdrTxbx
        fclcb_at = lw_at + 2 + cslw * 4 + 2
        fc_clx, lcb_clx = struct.unpack_from("<II", word, fclcb_at + 33 * 8)
        table = _read_stream(ole, "1Table" if flags & 0x0200 else "0Table")
    finally:
        ole.close()
    pieces = _piece_table(table[fc_clx:fc_clx + lcb_clx])
    total = sum(ccps)
    chars: list[str] = []
    for cp_start, cp_end, fc, compressed in pieces:
        if cp_start >= total:
            break
        n = min(cp_end, total) - cp_start
        if compressed:
            raw = word[fc // 2: fc // 2 + n]
            chars.append(raw.decode("cp1252", errors="replace"))  # bytes Windows-1252 leaves undefined -> U+FFFD
        else:
            raw = word[fc: fc + 2 * n]
            chars.append(raw.decode("utf-16-le", errors="replace"))
    return finish(_doc_clean("".join(chars)), cap)


def _piece_table(clx: bytes) -> list[tuple[int, int, int, bool]]:
    i = 0
    while i < len(clx) and clx[i] == 0x01:  # Prc: property modifiers, skipped
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise ValueError("no piece table")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5: i + 5 + lcb]
    n = (len(plc) - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    pieces = []
    for k in range(n):
        fc_raw = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        compressed = bool(fc_raw & 0x40000000)
        pieces.append((cps[k], cps[k + 1], fc_raw & 0x3FFFFFFF, compressed))
    return pieces


def _doc_clean(text: str) -> str:
    """Remove field codes and control marks; cells -> tabs, rows -> lines."""
    out: list[str] = []
    fields: list[bool] = []  # per open field: still in its code part?
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        o = ord(c)
        if o == 0x13:  # field begins: its code follows
            fields.append(True)
        elif o == 0x14:  # separator: the result (shown text) follows
            if fields:
                fields[-1] = False
        elif o == 0x15:  # field ends
            if fields:
                fields.pop()
        elif fields and fields[-1]:
            pass  # field code text, e.g. HYPERLINK "http://..."
        elif o == 0x07:  # end of cell; two in a row = end of table row
            if i + 1 < n and ord(text[i + 1]) == 0x07:
                out.append("\n")
                i += 1
            else:
                out.append("\t")
        elif o in _CTRL_MAP:
            out.append(_CTRL_MAP[o])
        elif o < 0x20 or o == 0x1F:
            pass  # object anchors, footnote marks, soft hyphens
        else:
            out.append(c)
        i += 1
    return "".join(out)


# --------------------------------------------------------------------- .ppt
_PPT_CONTAINER_SKIP = {0x03F8}  # MainMaster (slide master layouts)
_SLIDE_LIST_WITH_TEXT = 0x0FF0
_TEXT_CHARS, _TEXT_BYTES = 0x0FA0, 0x0FA8


def ppt_text(path: Path, cap: int) -> str:
    ole = _open_ole(path)
    try:
        data = _read_stream(ole, "PowerPoint Document")
    finally:
        ole.close()
    parts: list[str] = []
    _ppt_walk(data, 0, len(data), parts, 0)
    return finish("\n".join(p.replace("\r", "\n").replace("\x0b", "\n") for p in parts), cap)


def _ppt_walk(data: bytes, start: int, end: int, parts: list[str], depth: int) -> None:
    pos = start
    while pos + 8 <= end:
        ver_inst, rtype, length = struct.unpack_from("<HHI", data, pos)
        body = pos + 8
        stop = min(body + length, end)
        if ver_inst & 0x000F == 0x000F:  # container
            instance = ver_inst >> 4
            skip = rtype in _PPT_CONTAINER_SKIP or (rtype == _SLIDE_LIST_WITH_TEXT and instance == 1)
            if not skip and depth < 64:
                _ppt_walk(data, body, stop, parts, depth + 1)
        elif rtype in (_TEXT_CHARS, _TEXT_BYTES):
            raw = data[body:stop]
            text = raw.decode("utf-16-le", errors="replace") if rtype == _TEXT_CHARS else raw.decode("latin-1")
            if text.strip(" \t\r\n") != "*":  # "*" = slide number/date placeholder
                parts.append(text)
        pos = body + length


# --------------------------------------------------------------------- .xls
def xls_text(path: Path, cap: int) -> str:
    import xlrd

    from .extractors import _Collector, py_excel_value

    book = xlrd.open_workbook(str(path), on_demand=True)
    out = _Collector()
    try:
        for sheet_index in range(book.nsheets):
            sheet = book.sheet_by_index(sheet_index)
            out.add(f"# {sheet.name}")
            for r in range(sheet.nrows):
                cells = []
                for cell in sheet.row(r):
                    text = _xls_cell(cell, book.datemode, py_excel_value)
                    if text:
                        cells.append(text)
                if cells:
                    out.add("\t".join(cells))
                if out.full:
                    break
            book.unload_sheet(sheet_index)
    finally:
        book.release_resources()
    return out.text()[:cap]


def _xls_cell(cell, datemode: int, py_excel_value) -> str:
    import xlrd

    t, v = cell.ctype, cell.value
    if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return ""
    if t == xlrd.XL_CELL_TEXT:
        return v
    if t == xlrd.XL_CELL_NUMBER:
        return py_excel_value(v)
    if t == xlrd.XL_CELL_DATE:
        return py_excel_value(v, date=True, epoch_1904=bool(datemode))
    if t == xlrd.XL_CELL_BOOLEAN:
        return "True" if v else "False"
    if t == xlrd.XL_CELL_ERROR:
        return xlrd.error_text_from_code.get(v, "#ERR")
    return str(v)
