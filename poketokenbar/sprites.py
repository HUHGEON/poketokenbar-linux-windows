"""Sprite fetching — ports SpriteLoader.swift.

Sprites are downloaded at runtime and cached on disk; none are bundled.

The macOS app decodes GIF frames with ImageIO. QML's AnimatedImage plays a GIF
directly, so here the job is only to put a file on disk and hand back its path.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

from . import platform_paths, unown

SPRITE_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"
ITEM_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items"
USER_AGENT = "poketokenbar/0.1"
# Animated Black/White sprites exist for Gen I-V only.
MAX_ANIMATED_ID = 649


def _asset_name(species_id: int, unown_form: str | None) -> str:
    form = unown.resolved(species_id, unown_form)
    return f"{species_id}-{form}" if form and form != "a" else str(species_id)


def cache_key(species_id: int, animated: bool, shiny: bool, unown_form: str | None = None) -> str:
    return f"{_asset_name(species_id, unown_form)}-{'sh' if shiny else ''}{'a' if animated else 's'}"


def sprite_url(species_id: int, animated: bool, shiny: bool, unown_form: str | None = None) -> str:
    name = _asset_name(species_id, unown_form)
    if animated:
        shiny_part = "shiny/" if shiny else ""
        return (
            f"{SPRITE_BASE}/versions/generation-v/black-white/animated/"
            f"{shiny_part}{name}.gif"
        )
    return f"{SPRITE_BASE}/{'shiny/' if shiny else ''}{name}.png"


def _crop_to_content(png: bytes) -> bytes | None:
    """Trim the transparent margin, squared around what is left.

    Written against the PNG bytes directly rather than with an imaging library:
    this project has no third-party runtime dependency, and adding Pillow for
    one 96x96 crop is not a trade worth making. Returns None when the file is
    not a shape this can handle, and the caller keeps the original.
    """
    try:
        import zlib
    except ImportError:  # pragma: no cover - zlib is always present
        return None

    chunks = _png_chunks(png)
    if chunks is None:
        return None
    header, pixels, width, height = chunks
    if width <= 0 or height <= 0:
        return None

    # Content bounds: any pixel with a non-zero alpha.
    left, top, right, bottom = width, height, -1, -1
    for y in range(height):
        row = pixels[y * width * 4:(y + 1) * width * 4]
        for x in range(width):
            if row[x * 4 + 3] > 2:
                left, right = min(left, x), max(right, x)
                top, bottom = min(top, y), max(bottom, y)
    if right < left or bottom < top:
        return None

    box_width, box_height = right - left + 1, bottom - top + 1
    side = min(max(box_width, box_height), width, height)
    start_x = max(0, min(left - (side - box_width) // 2, width - side))
    start_y = max(0, min(top - (side - box_height) // 2, height - side))

    rows = bytearray()
    for y in range(start_y, start_y + side):
        rows.append(0)  # PNG filter byte: none
        offset = (y * width + start_x) * 4
        rows += pixels[offset:offset + side * 4]
    return _png_from_rgba(bytes(rows), side, side)


def _png_chunks(png: bytes):
    """Decode a non-interlaced PNG to 8-bit RGBA.

    Every colour type has to be here, not just RGBA. The one file this exists
    for — PokeAPI's ``pokemon/egg.png`` — was measured to be **96x96, bit depth
    4, colour type 3 (palette) with a tRNS chunk**, so an RGBA-only decoder
    returned None for the very sprite it was written to crop, and the egg was
    saved uncropped: 96x96 of canvas around a ~28x30 egg. That is exactly the
    "different egg image" that got reported.

    Interlaced files are still refused; Adam7 is a different decoder and no
    sprite in this project uses it.
    """
    import struct
    import zlib

    if png[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    offset, header = 8, None
    data = bytearray()
    palette = b""
    transparency = b""
    while offset + 8 <= len(png):
        length, kind = struct.unpack(">I4s", png[offset:offset + 8])
        body = png[offset + 8:offset + 8 + length]
        offset += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            data += body
        elif kind == b"IEND":
            break
    if header is None:
        return None
    width, height, depth, colour, compression, filter_method, interlace = header
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(colour)
    if channels is None or interlace != 0 or width <= 0 or height <= 0:
        return None
    if depth not in (1, 2, 4, 8, 16):
        return None
    if colour == 3 and (depth == 16 or not palette):
        return None
    if colour != 3 and depth in (1, 2, 4) and colour != 0:
        return None  # sub-byte depths only exist for grayscale and palette

    # Filtering works on whole bytes; for sub-byte depths the unit is one byte.
    pixel = max(1, (depth * channels) // 8)
    stride = (width * channels * depth + 7) // 8

    raw = zlib.decompress(bytes(data))
    lines: list[bytearray] = []
    previous = bytearray(stride)
    position = 0
    for _ in range(height):
        if position >= len(raw):
            return None
        filter_type = raw[position]
        position += 1
        line = bytearray(raw[position:position + stride])
        if len(line) != stride:
            return None
        position += stride
        _unfilter(filter_type, line, previous, pixel)
        lines.append(line)
        previous = line

    out = bytearray(width * height * 4)
    for y, line in enumerate(lines):
        for x, (r, g, b, a) in enumerate(
                _rgba_scanline(line, width, depth, colour, palette, transparency)):
            base = (y * width + x) * 4
            out[base:base + 4] = bytes((r, g, b, a))
    return header, bytes(out), width, height


def _samples(line: bytearray, count: int, depth: int):
    """Unpack `count` samples of `depth` bits each, MSB first, as PNG stores them."""
    if depth == 8:
        return list(line[:count])
    if depth == 16:
        return [line[i * 2] for i in range(count)]  # high byte is enough for 8-bit output
    out = []
    per_byte = 8 // depth
    mask = (1 << depth) - 1
    for index in range(count):
        byte = line[index // per_byte]
        shift = 8 - depth * (index % per_byte + 1)
        out.append((byte >> shift) & mask)
    return out


def _rgba_scanline(line, width, depth, colour, palette, transparency):
    """One decoded scanline as (r, g, b, a) tuples."""
    if colour == 3:
        for index in _samples(line, width, depth):
            base = index * 3
            if base + 3 > len(palette):
                yield (0, 0, 0, 0)
                continue
            alpha = transparency[index] if index < len(transparency) else 255
            yield (palette[base], palette[base + 1], palette[base + 2], alpha)
        return

    if colour == 0:  # grayscale
        # _samples already narrowed 16-bit samples to their high byte.
        top = 255 if depth == 16 else (1 << depth) - 1
        for value in _samples(line, width, depth):
            level = value * 255 // top if top else 0
            yield (level, level, level, 255)
        return

    step = 2 if depth == 16 else 1
    for x in range(width):
        if colour == 2:  # RGB
            base = x * 3 * step
            yield (line[base], line[base + step], line[base + 2 * step], 255)
        elif colour == 4:  # grayscale + alpha
            base = x * 2 * step
            level = line[base]
            yield (level, level, level, line[base + step])
        else:  # RGBA
            base = x * 4 * step
            yield (line[base], line[base + step],
                   line[base + 2 * step], line[base + 3 * step])


def _unfilter(filter_type: int, line: bytearray, previous: bytearray, pixel: int) -> None:
    """Reverse one PNG scanline filter, in place. See RFC 2083 section 6."""
    if filter_type == 0:
        return
    for i in range(len(line)):
        a = line[i - pixel] if i >= pixel else 0
        b = previous[i]
        c = previous[i - pixel] if i >= pixel else 0
        if filter_type == 1:
            line[i] = (line[i] + a) & 0xFF
        elif filter_type == 2:
            line[i] = (line[i] + b) & 0xFF
        elif filter_type == 3:
            line[i] = (line[i] + (a + b) // 2) & 0xFF
        elif filter_type == 4:
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            nearest = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            line[i] = (line[i] + nearest) & 0xFF


def _png_from_rgba(rows: bytes, width: int, height: int) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


class SpriteStore:
    def __init__(self, cache_dir: Path | None = None) -> None:
        base = cache_dir or (platform_paths.cache_base() / "poketokenbar")
        self.dir = base / "sprites"
        self.dir.mkdir(parents=True, exist_ok=True)

    def item_path(self, item_name: str) -> Path | None:
        """Local path to an item sprite, or None when PokeAPI has none."""
        target = self.dir / f"item-{item_name}.png"
        if target.is_file() and target.stat().st_size > 0:
            return target
        request = urllib.request.Request(f"{ITEM_BASE}/{item_name}.png")
        request.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status != 200:
                    return None
                data = response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        if not data:
            return None
        tmp = target.with_suffix(".png.tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        return target

    def egg_path(self) -> Path | None:
        """The egg sprite, cropped to its content.

        PokeAPI's egg sits on a 96x96 canvas and occupies about 28x30 of it, so
        used as-is it renders tiny next to a Pokemon that fills its frame — the
        macOS app crops it once for exactly this reason, and without the crop
        the egg looks like a different image entirely.

        Cropped to a square around the content, not to the bounding box: the
        egg is taller than it is wide, and a rectangular crop stretches in a
        square frame.
        """
        target = self.dir / "egg.png"
        if target.is_file() and target.stat().st_size > 0:
            return target

        raw = self._download(f"{SPRITE_BASE}/egg.png")
        if raw is None:
            return None
        cropped = _crop_to_content(raw)
        tmp = target.with_suffix(".png.tmp")
        tmp.write_bytes(cropped if cropped is not None else raw)
        tmp.replace(target)
        return target

    def _download(self, url: str) -> bytes | None:
        request = urllib.request.Request(url)
        request.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status != 200:
                    return None
                data = response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        return data or None

    def path(self, species_id: int, animated: bool = True, shiny: bool = False,
             unown_form: str | None = None) -> Path | None:
        """Local path to the sprite, downloading it once if needed.

        Returns None when unavailable so the caller can fall back rather than
        render a broken image.
        """
        if animated and species_id > MAX_ANIMATED_ID:
            animated = False

        key = cache_key(species_id, animated, shiny, unown_form)
        target = self.dir / f"{key}.{'gif' if animated else 'png'}"
        if target.is_file() and target.stat().st_size > 0:
            return target

        request = urllib.request.Request(sprite_url(species_id, animated, shiny, unown_form))
        request.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status != 200:
                    return None
                data = response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        if not data:
            return None

        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)  # atomic — a crash must not leave a torn sprite
        return target
