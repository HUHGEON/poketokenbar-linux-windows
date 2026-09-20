"""Build the Windows shortcut icon from the selected pixel Pokeball PNG.

The source and ICO are committed, so rebuilding needs no network or imaging
library. Preserve the transparent margin and scale with nearest-neighbour
to keep the pixel edges crisp.

Windows has read PNG-compressed entries in an .ico since Vista, so each size
goes in as a PNG rather than as a DIB.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from poketokenbar import sprites

SIZES = (16, 24, 32, 48, 64, 128, 256)
OUT = Path(__file__).resolve().parent.parent / "packaging" / "windows" / "poketokenbar.ico"
SOURCE = OUT.with_suffix(".png")


def scale(pixels: bytes, width: int, height: int, size: int) -> bytes:
    """Nearest-neighbour to a square, keeping the aspect and centring it."""
    side = max(width, height)
    out = bytearray(size * size * 4)
    for y in range(size):
        # Map back through the letterbox: source coordinates may fall outside
        # the image, and those pixels stay transparent.
        source_y = (y * side // size) - (side - height) // 2
        for x in range(size):
            source_x = (x * side // size) - (side - width) // 2
            if not (0 <= source_x < width and 0 <= source_y < height):
                continue
            source = (source_y * width + source_x) * 4
            target = (y * size + x) * 4
            out[target:target + 4] = pixels[source:source + 4]
    return bytes(out)


def png_of(pixels: bytes, size: int) -> bytes:
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filter: none
        rows += pixels[y * size * 4:(y + 1) * size * 4]
    return sprites._png_from_rgba(bytes(rows), size, size)


def main() -> int:
    decoded = sprites._png_chunks(SOURCE.read_bytes())
    if decoded is None:
        raise SystemExit("could not decode the icon PNG")
    _header, pixels, width, height = decoded

    images = [png_of(scale(pixels, width, height, size), size) for size in SIZES]

    # ICONDIR, then one ICONDIRENTRY per image, then the images themselves.
    offset = 6 + 16 * len(images)
    directory = struct.pack("<HHH", 0, 1, len(images))
    for size, image in zip(SIZES, images):
        directory += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # 0 means 256
            0 if size >= 256 else size,
            0, 0, 1, 32, len(image), offset)
        offset += len(image)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(directory + b"".join(images))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(images)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
