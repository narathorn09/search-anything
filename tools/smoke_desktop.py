"""Run a built desktop app and check it really works (used by CI on Windows/macOS).

    python tools/smoke_desktop.py "dist/CAHON/CAHON.exe"

Starts the app with a temporary home folder (Documents = tests/fixtures) in
browser mode, waits for the first scan and OCR, then searches Thai words from
a .doc, .xls, .ppt and a screenshot (OCR). Exits non-zero on failure.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECT = {"น้ำประปา": "report.doc", "ชาเขียว": "budget.xls", "ลดต้นทุน": "plan.ppt", "ยอดชำระ": "thai-invoice.png"}


def get(port: int, path: str):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10) as r:
        return json.loads(r.read())


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):  # Windows consoles default to cp1252: print Thai safely
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    exe = Path(sys.argv[1]).resolve()
    tmp = Path(tempfile.mkdtemp(prefix="cahon-smoke-"))
    home, data = tmp / "home", tmp / "data"
    shutil.copytree(ROOT / "tests" / "fixtures", home / "Documents")
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "CAHON_DATA_DIR": str(data), "CAHON_NO_WINDOW": "1"}
    proc = subprocess.Popen([str(exe)], env=env)
    ok = False
    try:
        port = None
        for _ in range(120):
            try:
                port = json.loads((data / "running.json").read_text())["port"]
                get(port, "/api/status")
                break
            except (OSError, ValueError, KeyError):
                time.sleep(1)
        assert port, "the app did not start"
        status = None
        for _ in range(300):
            status = get(port, "/api/status")
            ix = status["indexing"]
            if not ix["running"] and status["counts"]["file"] >= 4 and ix["ocr"]["done"] >= 1:
                break
            time.sleep(1)
        print("status:", json.dumps({"files": status["counts"]["file"], "ocr": status["indexing"]["ocr"]}, ensure_ascii=False))
        assert status["indexing"]["ocr"]["available"] and status["indexing"]["ocr"]["thai"], "bundled OCR not found"
        failures = []
        for word, file in EXPECT.items():
            titles = [r["title"] for r in get(port, "/api/search?q=" + urllib.parse.quote(word))["results"]]
            print(f"search {word!r}: {titles}")
            if file not in titles:
                failures.append(word)
        assert not failures, f"not found: {failures}"
        ok = True
    except AssertionError as exc:
        print("FAILED:", exc)
        log = data / "app.log"
        if log.exists():
            print(log.read_text(encoding="utf-8", errors="replace")[-4000:])
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("SMOKE TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
