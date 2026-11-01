"""CI check: the desktop app's copy_to_clipboard really reaches the system
clipboard (Thai included). Reads it back with the OS's own API."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from search_anything.desktop import copy_to_clipboard  # noqa: E402

TEXT = "คัดลอก path: C:\\เอกสาร\\สัญญา.pdf ✓"


def read_back() -> str:
    if sys.platform.startswith("win"):
        import ctypes
        from ctypes import wintypes

        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        u32.GetClipboardData.restype = wintypes.HANDLE
        k32.GlobalLock.argtypes, k32.GlobalLock.restype = [wintypes.HGLOBAL], ctypes.c_void_p
        u32.OpenClipboard(None)
        try:
            ptr = k32.GlobalLock(u32.GetClipboardData(13))
            text = ctypes.wstring_at(ptr)
            k32.GlobalUnlock(ptr)
            return text
        finally:
            u32.CloseClipboard()
    out = subprocess.run(["pbpaste"], capture_output=True, env={**os.environ, "LANG": "en_US.UTF-8"}).stdout
    return out.decode("utf-8")


copy_to_clipboard(TEXT)
got = read_back()
ok = got == TEXT
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
print("clipboard:", "OK" if ok else f"MISMATCH {got!r}")
sys.exit(0 if ok else 1)
