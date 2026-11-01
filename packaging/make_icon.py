"""Draw the app icon (a magnifier on a rounded square) as PNG, ICO and ICNS."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def draw(size: int = 1024) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = size * 0.06
    d.rounded_rectangle((pad, pad, size - pad, size - pad), radius=size * 0.22, fill=(0, 116, 226, 255))
    cx, cy, r = size * 0.44, size * 0.44, size * 0.2
    w = size * 0.075
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 255, 255, 255), width=int(w))
    a = 0.7071
    d.line((cx + r * a, cy + r * a, size * 0.74, size * 0.74), fill=(255, 255, 255, 255), width=int(w * 1.25))
    d.ellipse((size * 0.74 - w * 0.62, size * 0.74 - w * 0.62, size * 0.74 + w * 0.62, size * 0.74 + w * 0.62),
              fill=(255, 255, 255, 255))
    return img


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    img = draw()
    img.save(out / "icon.png")
    img.save(out / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(out / "icon.icns")
    print("icons written to", out)
