"""
Generate a synthetic inspection photo (PNG) for the SIH demo — stdlib only.

Produces an industrial-looking grayscale "housing face" with a radial heat/
discoloration hotspot and scoring streaks so a local vision model has real
visual evidence to describe. Nothing in the app depends on this file.

Usage: python scripts/generate_inspection_image.py [out_path]
"""
import struct
import sys
import zlib
from pathlib import Path

W, H = 512, 384


def _chunk(typ: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + typ + data
            + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF))


def generate() -> bytes:
    cx, cy = W * 0.62, H * 0.45          # hotspot centre (right-of-centre)
    rows = []
    for y in range(H):
        row = bytearray(b"\x00")         # filter type 0 per scanline
        for x in range(W):
            # brushed-metal base with horizontal machining lines
            base = 150 + (18 if (y // 4) % 2 else 0)
            # vignette
            dx, dy = x - W / 2, y - H / 2
            base -= int((dx * dx + dy * dy) / (W * H / 3))
            # radial heat hotspot: darker/bluer ring region
            d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
            if d < 70:
                t = 1 - d / 70
                base = int(base * (1 - 0.55 * t))       # darkened burn zone
                if 28 < d < 40:                          # bright rim (blueing edge)
                    base = min(235, base + 60)
            # diagonal scoring streaks inside hotspot
            if d < 80 and ((x - y) // 6) % 7 == 0:
                base = max(0, base - 35)
            row += bytes((max(0, min(255, base)),) * 3)
        rows.append(bytes(row))

    ihdr = struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)   # 8-bit RGB
    return (b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
            + _chunk(b"IEND", b""))


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).parent / "sample_data" / "bearing_inspection.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    data = generate()
    out.write_bytes(data)
    print(f"Wrote {len(data):,} bytes -> {out}")
