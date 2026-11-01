"""File type groups for the type filter (PDF, Word, Excel …), by file extension."""

from __future__ import annotations

import os

from .extractors import TEXT_EXTENSIONS, TEXT_FILENAMES

# (key, label, extensions) — the order is the order of the chips in the UI.
GROUPS: list[tuple[str, str, frozenset[str]]] = [
    ("pdf", "PDF", frozenset({"pdf"})),
    ("word", "Word", frozenset({"doc", "docx", "dot", "dotx", "docm", "odt", "rtf", "pages"})),
    ("excel", "Excel", frozenset({"xls", "xlsx", "xlsm", "xlt", "xltx", "ods", "csv", "tsv", "numbers"})),
    ("slides", "PowerPoint", frozenset({"ppt", "pptx", "pps", "ppsx", "pot", "potx", "odp", "key"})),
    ("image", "รูปภาพ", frozenset({"jpg", "jpeg", "png", "gif", "bmp", "webp", "tif", "tiff", "heic", "heif",
                                   "svg", "ico", "raw", "cr2", "nef", "arw", "dng", "psd", "ai"})),
    ("text", "ข้อความ & โค้ด", (frozenset(e.lstrip(".") for e in TEXT_EXTENSIONS)
                               | {"html", "htm", "xhtml", "ipynb", "epub"}) - {"csv", "tsv", "svg"}),
    ("email", "อีเมล", frozenset({"eml", "msg", "mbox"})),
    ("archive", "ไฟล์บีบอัด", frozenset({"zip", "rar", "7z", "tar", "gz", "tgz", "bz2", "xz", "zst"})),
    ("media", "วิดีโอ & เสียง", frozenset({"mp4", "mov", "avi", "mkv", "wmv", "webm", "m4v", "mp3", "wav", "m4a",
                                          "aac", "flac", "ogg", "wma"})),
]
OTHER = "other"
LABELS = {key: label for key, label, _ in GROUPS} | {OTHER: "อื่นๆ"}
KEYS = [key for key, _, _ in GROUPS] + [OTHER]
_BY_EXT = {ext: key for key, _, exts in GROUPS for ext in exts}
assert len(_BY_EXT) == sum(len(exts) for _, _, exts in GROUPS), "an extension is in two groups"


def type_of(name: str) -> str:
    """The group of a file name, e.g. "report.PDF" -> "pdf"."""
    ext = os.path.splitext(name)[1][1:].lower()
    if ext:
        return _BY_EXT.get(ext, OTHER)
    return "text" if name.lower() in TEXT_FILENAMES else OTHER


def parse(value: str | None) -> frozenset[str]:
    """"pdf,word" -> {"pdf", "word"}; unknown keys are ignored."""
    return frozenset(k for k in (value or "").split(",") if k in LABELS)


def sql_filter(types: frozenset[str], column: str = "f.title") -> tuple[str, list[str]]:
    """SQL condition (and parameters) matching file names of these groups."""
    parts, params = [], []
    for key, _, exts in GROUPS:
        if key in types:
            parts += [f"lower({column}) LIKE ?"] * len(exts)
            params += [f"%.{e}" for e in sorted(exts)]
    if "text" in types:
        parts += [f"lower({column}) = ?"] * len(TEXT_FILENAMES)
        params += sorted(TEXT_FILENAMES)
    sql = " OR ".join(parts)
    if OTHER in types:
        known = [f"%.{e}" for e in sorted(_BY_EXT)]
        not_known = " AND ".join([f"lower({column}) NOT LIKE ?"] * len(known) +
                                 [f"lower({column}) <> ?"] * len(TEXT_FILENAMES))
        sql = f"{sql} OR ({not_known})" if sql else f"({not_known})"
        params += known + sorted(TEXT_FILENAMES)
    return f"({sql})" if sql else "0", params
