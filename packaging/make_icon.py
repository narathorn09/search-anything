"""App icon files (PNG, ICO, ICNS) from the CAHON icon artwork.

packaging/icon-1024.png is cahon/static/brand/icon.svg rendered at 1024 px
(the mascot "น้องคาหน" on a navy rounded square).
"""

import sys
from pathlib import Path

from PIL import Image

SRC = Path(__file__).resolve().parent / "icon-1024.png"

if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    img = Image.open(SRC).convert("RGBA")
    img.save(out / "icon.png")
    img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(out / "icon.icns")
    print("icons written to", out)
