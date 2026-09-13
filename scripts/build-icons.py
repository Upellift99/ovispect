#!/usr/bin/env python3
"""Generate the app icons under src/ovispect/static from a single drawing.

The icon is the "live" status dot of the dashboard (#4ade80) inside a thin
ring, on the page background (#0a0a0a). It is drawn with Pillow at 4x and
downscaled so edges stay smooth. Run from the repository root:

    python3 scripts/build-icons.py

Requires Pillow (`pip install pillow`); it is a build-time dependency only.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

STATIC = Path(__file__).resolve().parent.parent / "src" / "ovispect" / "static"
BG = (10, 10, 10, 255)
GREEN = (74, 222, 128, 255)
RING = (64, 64, 64, 255)

# (file name, pixel size)
TARGETS = [
    ("apple-touch-icon.png", 180),
    ("icon-192.png", 192),
    ("icon-512.png", 512),
    ("favicon-32.png", 32),
]


def draw(size: int) -> Image.Image:
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), BG)
    c = s / 2

    # Soft glow behind the dot, like the pulse animation's box-shadow.
    glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    r_glow = s * 0.26
    g.ellipse((c - r_glow, c - r_glow, c + r_glow, c + r_glow), fill=(74, 222, 128, 110))
    glow = glow.filter(ImageFilter.GaussianBlur(s * 0.06))
    img.alpha_composite(glow)

    d = ImageDraw.Draw(img)
    # Thin outer ring: the "O" of ovispect.
    r_ring = s * 0.36
    d.ellipse(
        (c - r_ring, c - r_ring, c + r_ring, c + r_ring), outline=RING, width=max(1, int(s * 0.022))
    )
    # The live dot.
    r_dot = s * 0.17
    d.ellipse((c - r_dot, c - r_dot, c + r_dot, c + r_dot), fill=GREEN)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    for name, size in TARGETS:
        out = STATIC / name
        draw(size).convert("RGB" if name.startswith("apple") else "RGBA").save(out, optimize=True)
        print(f"wrote {out.relative_to(STATIC.parent.parent.parent)} ({size}x{size})")


if __name__ == "__main__":
    main()
