"""Measure where scanning time goes, stage by stage.

    python tools/bench_scan.py make  /tmp/corpus     # build a test corpus once
    python tools/bench_scan.py run   /tmp/corpus     # measure

The corpus mixes what an office folder holds: many small text/code files
plus Word, Excel, PowerPoint, PDF and HTML documents (Thai + English), in
nested folders. Stages measured separately:

  walk        listing every file (os.scandir) and stat
  extract     reading text out of each file type (one thread, per file)
  write       inserting text into the SQLite FTS index
  full scan   the real pipeline end to end (thread mode and worker process)
  rescan      a second scan when nothing changed
  search      query latency on the finished index

Run it before and after a change to compare.
"""

from __future__ import annotations

import cProfile
import io
import json
import os
import pstats
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

THAI = ("สัญญาเช่าพื้นที่สำนักงาน ค่าเช่าเดือนละ บาท ใบเสร็จรับเงิน ภาษีมูลค่าเพิ่ม ผู้ให้เช่า ผู้เช่า "
        "กรุงเทพมหานคร รายงานการประชุม งบประมาณ ประจำปี ฝ่ายบัญชี โครงการ").split()
ENG = ("invoice contract budget meeting report quarterly revenue customer project deadline "
       "lorem ipsum dolor sit amet consectetur adipiscing elit").split()

COUNTS = {"txt": 30000, "py": 10000, "md": 5000, "json": 3000, "csv": 1000, "html": 1000,
          "docx": 400, "xlsx": 300, "pptx": 200, "pdf": 300, "bin": 2000}


def words(rng: random.Random, n: int) -> str:
    return " ".join(rng.choice(THAI if rng.random() < 0.5 else ENG) for _ in range(n))


def make(root: Path) -> None:
    import docx
    import openpyxl
    from pptx import Presentation

    rng = random.Random(42)
    root.mkdir(parents=True, exist_ok=True)
    dirs = [root / f"dept{a}" / f"proj{b}" / f"y{2020 + c}" for a in range(8) for b in range(10) for c in range(4)]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    def where(i: int) -> Path:
        return dirs[i % len(dirs)]

    t = time.time()
    for i in range(COUNTS["txt"]):
        (where(i) / f"note{i}.txt").write_text("\n".join(words(rng, 12) for _ in range(rng.randint(5, 60))))
    for i in range(COUNTS["py"]):
        (where(i) / f"mod{i}.py").write_text("\n".join(f"def f{j}(x):\n    return x * {j}  # {words(rng, 5)}"
                                                       for j in range(rng.randint(5, 80))))
    for i in range(COUNTS["md"]):
        (where(i) / f"doc{i}.md").write_text("# " + words(rng, 4) + "\n\n" + "\n\n".join(words(rng, 30) for _ in range(10)))
    for i in range(COUNTS["json"]):
        (where(i) / f"data{i}.json").write_text(json.dumps([{"id": j, "text": words(rng, 6)} for j in range(40)], ensure_ascii=False))
    for i in range(COUNTS["csv"]):
        (where(i) / f"table{i}.csv").write_text("\n".join(",".join(words(rng, 1) for _ in range(6)) for _ in range(300)))
    for i in range(COUNTS["html"]):
        (where(i) / f"page{i}.html").write_text("<html><head><style>p{}</style></head><body>"
                                                + "".join(f"<p>{words(rng, 20)}</p>" for _ in range(40)) + "</body></html>")
    for i in range(COUNTS["bin"]):
        (where(i) / f"photo{i}.jpg").write_bytes(os.urandom(rng.randint(20_000, 200_000)))
    print(f"text files: {time.time() - t:.0f}s", flush=True)

    t = time.time()
    for i in range(COUNTS["docx"]):
        d = docx.Document()
        for _ in range(rng.randint(20, 120)):
            d.add_paragraph(words(rng, 25))
        table = d.add_table(rows=10, cols=4)
        for row in table.rows:
            for cell in row.cells:
                cell.text = words(rng, 2)
        d.save(where(i) / f"report{i}.docx")
    for i in range(COUNTS["xlsx"]):
        wb = openpyxl.Workbook()
        for s in range(3):
            ws = wb.active if s == 0 else wb.create_sheet(f"Sheet{s}")
            for r in range(rng.randint(200, 1500)):
                ws.append([r, words(rng, 3), rng.random() * 1000, words(rng, 2), "2024-01-01", r * 7])
        wb.save(where(i) / f"budget{i}.xlsx")
    for i in range(COUNTS["pptx"]):
        p = Presentation()
        for _ in range(rng.randint(10, 40)):
            slide = p.slides.add_slide(p.slide_layouts[1])
            slide.shapes.title.text = words(rng, 5)
            slide.placeholders[1].text = "\n".join(words(rng, 12) for _ in range(5))
        p.save(where(i) / f"deck{i}.pptx")
    print(f"office files: {time.time() - t:.0f}s", flush=True)

    t = time.time()
    pdfs = _make_pdfs(rng, root / "_pdf_src", 10)
    for i in range(COUNTS["pdf"]):
        shutil.copy(pdfs[i % len(pdfs)], where(i) / f"scanless{i}.pdf")
    shutil.rmtree(root / "_pdf_src")
    print(f"pdf files: {time.time() - t:.0f}s", flush=True)


def _make_pdfs(rng: random.Random, out: Path, n: int) -> list[Path]:
    """Text PDFs printed by Chromium (real fonts, Thai shaping), via Node Playwright."""
    import subprocess

    out.mkdir(parents=True, exist_ok=True)
    jobs = []
    for i in range(n):
        body = "".join(f"<p>{words(rng, 30)}</p>" for _ in range(rng.randint(40, 300)))
        html = out / f"src{i}.html"
        html.write_text(f"<html><body style='font-family:sans-serif'>{body}</body></html>")
        jobs.append((str(html), str(out / f"src{i}.pdf")))
    script = ("const {chromium}=require('playwright');(async()=>{const b=await chromium.launch();"
              "const p=await b.newPage();for(const [h,o] of JSON.parse(process.argv[1])){"
              "await p.goto('file://'+h);await p.pdf({path:o});}await b.close();})();")
    subprocess.run(["node", "-e", script, json.dumps(jobs)], check=True)
    return [Path(o) for _, o in jobs]


# ------------------------------------------------------------------ measure
def fmt(seconds: float) -> str:
    return f"{seconds * 1000:.1f} ms" if seconds < 1 else f"{seconds:.2f} s"


def run(root: Path, profile_types: bool = True) -> dict:
    from search_anything.db import Database
    from search_anything.extractors import extract_text
    from search_anything.indexer import Indexer, ScanSettings
    from search_anything.worker import ProcessIndexer

    report: dict = {}
    files = [(p, n, st) for p, n, st in Indexer._walk(str(root))]
    total_bytes = sum(st.st_size for *_, st in files)
    print(f"corpus: {len(files):,} files, {total_bytes / 1e6:.0f} MB")

    # walk (warm cache, best of 3)
    times = []
    for _ in range(3):
        t = time.perf_counter()
        n = sum(1 for _ in Indexer._walk(str(root)))
        times.append(time.perf_counter() - t)
    report["walk"] = min(times)
    print(f"walk + stat:            {fmt(min(times))}  ({n / min(times):,.0f} files/s)")

    # extraction per type, one thread
    by_type: dict[str, list[Path]] = {}
    for p, n, st in files:
        by_type.setdefault(Path(p).suffix.lower(), []).append(Path(p))
    report["extract"] = {}
    print("\nextract (1 thread)      files    total     per file   MB/s    share")
    rows = []
    for suffix, paths in sorted(by_type.items()):
        sample = paths if len(paths) <= 3000 else random.Random(1).sample(paths, 3000)
        t = time.perf_counter()
        chars = 0
        for p in sample:
            chars += len(extract_text(p))
        took = time.perf_counter() - t
        scale = len(paths) / len(sample)
        mb = sum(p.stat().st_size for p in sample) / 1e6
        rows.append((suffix, len(paths), took * scale, took / len(sample), mb / took if took else 0))
    grand = sum(r[2] for r in rows)
    for suffix, count, total, per, mbs in sorted(rows, key=lambda r: -r[2]):
        report["extract"][suffix] = {"files": count, "seconds": round(total, 2), "per_file_ms": round(per * 1000, 2)}
        print(f"  {suffix:8s} {count:12,} {fmt(total):>9s} {fmt(per):>11s} {mbs:6.1f}  {total / grand * 100:5.1f}%")
    print(f"  {'all':8s} {len(files):12,} {fmt(grand):>9s}")
    report["extract_total"] = grand

    # write: extracted text into the FTS index, no extraction cost
    tmp = Path(tempfile.mkdtemp())
    db = Database(tmp / "w.db")
    sample = random.Random(2).sample(files, min(20000, len(files)))
    rows_in = [(p, n, extract_text(Path(p), st.st_size), st.st_mtime, st.st_size) for p, n, st in sample]
    t = time.perf_counter()
    for shard in db.shards:
        mine = [r for r in rows_in if db.shard_for(r[0]) is shard]
        for i in range(0, len(mine), 200):
            shard.upsert_many(mine[i:i + 200])
    took = time.perf_counter() - t
    chars = sum(len(r[2]) for r in rows_in)
    report["write_per_file_ms"] = took / len(rows_in) * 1000
    print(f"\nwrite (FTS, 1 thread):  {fmt(took)} for {len(rows_in):,} files, {chars / 1e6:.0f} M chars "
          f"-> {fmt(took / len(rows_in))}/file, est. all files {fmt(took / len(rows_in) * len(files))}")
    del rows_in  # free it before the scans below
    db.close()
    shutil.rmtree(tmp, ignore_errors=True)

    full_scans(root, report)

    if profile_types:
        for suffix in (".xlsx", ".docx", ".pptx", ".pdf", ".html"):
            paths = by_type.get(suffix, [])[:40]
            if not paths:
                continue
            prof = cProfile.Profile()
            prof.enable()
            for p in paths:
                extract_text(p)
            prof.disable()
            out = io.StringIO()
            pstats.Stats(prof, stream=out).sort_stats("tottime").print_stats(6)
            lines = [l for l in out.getvalue().splitlines() if l.strip() and ("{" in l or ".py" in l)][:6]
            print(f"\nhotspots {suffix}:")
            for l in lines:
                print("   ", l.strip()[:150])
    return report


def full_scans(root: Path, report: dict) -> None:
    from search_anything.db import Database
    from search_anything.indexer import ScanSettings
    from search_anything.worker import ProcessIndexer

    # full scans
    # The default: a separate worker process (its own RAM is what the brake watches).
    for label, cls, profile in (("worker process, balanced", ProcessIndexer, "balanced"),
                                ("worker process, fast", ProcessIndexer, "fast")):
        d = Path(tempfile.mkdtemp())
        db = Database(d / "s.db")
        ix = cls(db, [str(root)], ScanSettings(profile=profile, ocr=False))
        t = time.perf_counter()
        stats = ix.run()
        took = time.perf_counter() - t
        report[f"full:{label}"] = took
        print(f"\nfull scan ({label}): {fmt(took)}  ({stats.added_or_updated / took:,.0f} files/s, "
              f"paused {stats.paused_seconds}s)")
        if label == "worker process, fast":
            t = time.perf_counter()
            stats = ix.run()
            report["rescan"] = time.perf_counter() - t
            print(f"rescan, nothing changed: {fmt(report['rescan'])}")
            for q in ("สำนักงาน", "invoice", "ภาษีมูลค่าเพิ่ม budget", "zzzz-not-there"):
                lat = []
                for _ in range(5):
                    db.invalidate()
                    t = time.perf_counter()
                    db.page(q, None, "relevance", 0, 50)
                    lat.append(time.perf_counter() - t)
                print(f"search {q!r}: median {fmt(statistics.median(lat))}")
                report[f"search:{q}"] = statistics.median(lat)
        db.close()
        shutil.rmtree(d, ignore_errors=True)



if __name__ == "__main__":
    cmd, where = sys.argv[1], Path(sys.argv[2])
    if cmd == "make":
        make(where)
    elif cmd == "scan":  # end-to-end scans only
        from search_anything.extractors import NATIVE
        print("native (Rust) readers:", NATIVE)
        full_scans(where, {})
    else:
        result = run(where)
        if len(sys.argv) > 3:
            Path(sys.argv[3]).write_text(json.dumps(result, ensure_ascii=False, indent=1))
