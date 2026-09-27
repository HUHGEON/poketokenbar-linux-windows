"""The egg sprite, and the PNG decoding it needs.

The egg was reported as "a different image". It was: PokeAPI's egg.png is a
96x96 canvas with a 28x30 egg in the middle of it, so drawn uncropped it is a
third the size of every other sprite beside it. The macOS app crops it, and
this could not — the decoder accepted only 8-bit RGBA and the file is 4-bit
palette, so it returned None and the original was saved unchanged.
"""

import struct
import zlib

import pytest

from poketokenbar import sprites


def _png(width, height, depth, colour, rows, palette=b"", transparency=b""):
    """Build a PNG by hand, so a colour type can be tested without a fixture."""
    def chunk(kind, body):
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    out = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, 0))
    if palette:
        out += chunk(b"PLTE", palette)
    if transparency:
        out += chunk(b"tRNS", transparency)
    return out + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def _pixels(png):
    decoded = sprites._png_chunks(png)
    assert decoded is not None, "the decoder refused this file"
    _header, data, width, height = decoded
    return data, width, height


# MARK: colour types


def test_a_four_bit_palette_with_transparency_decodes():
    """The shape PokeAPI's egg.png actually is — measured, not assumed: 96x96,
    bit depth 4, colour type 3, with a tRNS chunk."""
    # Two pixels per byte: index 1 then index 2.
    rows = bytes([0, 0x12])
    png = _png(2, 1, 4, 3, rows,
               palette=bytes([0, 0, 0, 255, 0, 0, 0, 255, 0]),
               transparency=bytes([0, 255, 128]))
    data, width, _height = _pixels(png)
    assert width == 2
    assert tuple(data[0:4]) == (255, 0, 0, 255)
    assert tuple(data[4:8]) == (0, 255, 0, 128)


def test_a_palette_index_uses_its_transparency_entry():
    """A tRNS shorter than the palette means the rest are opaque, which is what
    makes an egg's own pixels solid and its canvas empty."""
    rows = bytes([0, 0x01])
    png = _png(2, 1, 4, 3, rows,
               palette=bytes([1, 2, 3, 4, 5, 6]), transparency=bytes([0]))
    data, _width, _height = _pixels(png)
    assert data[3] == 0, "index 0 is transparent"
    assert data[7] == 255, "index 1 has no tRNS entry, so it is opaque"


def test_eight_bit_rgba_still_decodes():
    rows = bytes([0, 10, 20, 30, 40])
    data, _width, _height = _pixels(_png(1, 1, 8, 6, rows))
    assert tuple(data) == (10, 20, 30, 40)


def test_grayscale_is_scaled_to_eight_bits():
    # One 4-bit sample of 15, which is white at that depth.
    data, _width, _height = _pixels(_png(1, 1, 4, 0, bytes([0, 0xF0])))
    assert tuple(data) == (255, 255, 255, 255)


def test_rgb_without_alpha_is_opaque():
    data, _width, _height = _pixels(_png(1, 1, 8, 2, bytes([0, 7, 8, 9])))
    assert tuple(data) == (7, 8, 9, 255)


def test_an_interlaced_file_is_refused_rather_than_misread():
    """Adam7 is a different decoder; returning half-decoded pixels would crop to
    the wrong box."""
    png = bytearray(_png(1, 1, 8, 6, bytes([0, 1, 2, 3, 4])))
    png[8 + 8 + 12] = 1  # the interlace byte in IHDR
    assert sprites._png_chunks(bytes(png)) is None


def test_a_file_that_is_not_a_png_is_refused():
    assert sprites._png_chunks(b"not a png at all") is None


# MARK: the crop


def _canvas(side, box, offset):
    """A `side`x`side` transparent canvas with an opaque `box` square in it."""
    rows = bytearray()
    for y in range(side):
        rows.append(0)
        for x in range(side):
            inside = offset <= x < offset + box and offset <= y < offset + box
            rows += bytes((255, 0, 0, 255) if inside else (0, 0, 0, 0))
    return _png(side, side, 8, 6, bytes(rows))


def test_the_crop_removes_the_empty_canvas():
    cropped = sprites._crop_to_content(_canvas(96, 30, 33))
    assert cropped is not None
    _data, width, height = _pixels(cropped)
    assert (width, height) == (30, 30)


def test_the_cropped_result_is_square():
    """The sprite is drawn into a square box, so a non-square crop would be
    stretched by whichever front end scales it."""
    rows = bytearray()
    for y in range(20):
        rows.append(0)
        for x in range(20):
            solid = 2 <= x < 18 and 8 <= y < 12  # a wide, short bar
            rows += bytes((1, 2, 3, 255) if solid else (0, 0, 0, 0))
    cropped = sprites._crop_to_content(_png(20, 20, 8, 6, bytes(rows)))
    _data, width, height = _pixels(cropped)
    assert width == height


def test_a_fully_transparent_image_is_left_alone():
    """There is no content to crop to, and cropping to nothing would produce a
    zero-sized PNG."""
    assert sprites._crop_to_content(_canvas(8, 0, 0)) is None


def test_content_filling_the_canvas_is_not_enlarged():
    cropped = sprites._crop_to_content(_canvas(8, 8, 0))
    _data, width, height = _pixels(cropped)
    assert (width, height) == (8, 8)


# MARK: against the real file


@pytest.mark.network
def test_the_real_pokeapi_egg_crops_to_its_own_bounds():
    """The regression this exists for. Skipped without a network."""
    import urllib.error
    import urllib.request

    url = f"{sprites.SPRITE_BASE}/egg.png"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "poketokenbar"})
        raw = urllib.request.urlopen(request, timeout=10).read()
    except (urllib.error.URLError, OSError):
        pytest.skip("no network")

    _data, width, height = _pixels(raw)
    assert (width, height) == (96, 96)
    cropped = sprites._crop_to_content(raw)
    assert cropped is not None
    _cropped_data, cropped_width, cropped_height = _pixels(cropped)
    assert cropped_width <= 40 and cropped_height <= 40, (
        f"the egg is still on a {cropped_width}x{cropped_height} canvas")
