"""The desktop pet: what it draws, how big, and where it may go.

Four bugs reported from Windows, all in the same corner of the Qt front end.
None was visible in a test because none of these tests existed: the suite
checked that a sprite could be pointed at a file, not what came out of it.

The GIF is built here rather than downloaded. A sprite that is not square is
the whole point of two of these, and a fixture that happened to be square
would pass every one of them while the bug stood.
"""

import struct

import pytest

pytest.importorskip("PySide6", reason="the Qt front end is optional")

from PySide6.QtCore import QPoint, QRect  # noqa: E402
from PySide6.QtGui import QImageReader, QMovie  # noqa: E402

from poketokenbar.ui import pet as pet_module  # noqa: E402
from poketokenbar.ui.pet import DesktopPet  # noqa: E402
from poketokenbar.ui.widgets import Sprite  # noqa: E402

# Deliberately not square, and taller than wide, so a fit that ignores the
# aspect is a visible distortion rather than a rounding difference.
# Long enough that the slowest preset still has frames to drop: a real Gen-V
# sprite runs 2.75s to 10.7s, and a fixture shorter than the 0.4s floor
# decimates to a single frame and would "prove" the animation is broken.
GIF_WIDTH, GIF_HEIGHT, GIF_FRAMES = 4, 6, 40


def tiny_gif(width=GIF_WIDTH, height=GIF_HEIGHT, frames=GIF_FRAMES, delay_cs=6):
    """A GIF89a of solid-colour frames: two colours, so the LZW minimum code
    size is 2 and each frame is one code per pixel."""
    out = bytearray(b"GIF89a")
    out += struct.pack("<HHBBB", width, height, 0xF0, 0, 0)
    out += bytes((0, 0, 0, 255, 255, 255))
    out += b"\x21\xFF\x0BNETSCAPE2.0\x03\x01\x00\x00\x00"
    for index in range(frames):
        out += b"\x21\xF9\x04\x00" + struct.pack("<H", delay_cs) + b"\x00\x00"
        out += b"\x2C" + struct.pack("<HHHHB", 0, 0, width, height, 0)
        codes = [4] + [index % 2] * (width * height) + [5]
        bits, acc, nbits = bytearray(), 0, 0
        for code in codes:
            acc |= code << nbits
            nbits += 3
            while nbits >= 8:
                bits.append(acc & 0xFF)
                acc >>= 8
                nbits -= 8
        if nbits:
            bits.append(acc & 0xFF)
        out += b"\x02" + bytes((len(bits),)) + bytes(bits) + b"\x00"
    return bytes(out + b"\x3B")


@pytest.fixture
def animated(tmp_path, qt_app):
    path = tmp_path / "sprite.gif"
    path.write_bytes(tiny_gif())
    assert QImageReader(str(path)).imageCount() == GIF_FRAMES, "fixture is not animated"
    return str(path)


# MARK: it has to move


def test_the_movie_is_cached_so_it_can_be_rewound(animated, qt_app):
    """A GIF decodes forwards. Seeking backwards — which is what the end of a
    loop is — fails silently without the frames kept, and the sprite then holds
    one pose forever at every quality."""
    sprite = Sprite(48)
    sprite.set_path(animated)
    assert sprite.movie().cacheMode() == QMovie.CacheAll


def test_a_rewind_actually_lands(animated, qt_app):
    """The failure was silent: jumpToFrame returned false and the movie stayed
    where it was, so nothing raised and nothing moved."""
    movie = QMovie(animated)
    movie.setCacheMode(QMovie.CacheAll)
    for index in range(movie.frameCount()):
        movie.jumpToFrame(index)
    assert movie.jumpToFrame(0)
    assert movie.currentFrameNumber() == 0


@pytest.mark.parametrize("quality", ["saver", "balanced", "smooth"])
def test_every_quality_animates(animated, qt_app, quality):
    """Only the power saver is meant to be slow; none of them is meant to be
    still. The report was that Balanced did not move at all."""
    sprite = Sprite(48)
    sprite.set_quality(quality)
    sprite.set_path(animated)
    assert len(sprite._schedule) > 1, f"{quality} has nothing to advance through"
    assert sprite._timer.isActive(), f"{quality} is not running"


def test_smoother_settings_draw_more_frames(animated, qt_app):
    def frames(quality):
        sprite = Sprite(48)
        sprite.set_quality(quality)
        sprite.set_path(animated)
        return len(sprite._schedule)

    assert frames("saver") <= frames("balanced") <= frames("smooth")


# MARK: it has to keep its shape


@pytest.mark.parametrize("size", [24, 48, 96, 192])
def test_an_animated_sprite_keeps_its_proportions(animated, qt_app, size):
    """Gen-V sprites are not square and differ per species. Scaling to
    `size x size` stretches every one into a rectangle it was never drawn as —
    squashed hardest at small sizes, which is where it reads as "it turned into
    a square"."""
    sprite = Sprite(size)
    sprite.set_path(animated)
    drawn = sprite.movie().currentPixmap().size()
    assert drawn.width() != drawn.height(), "the sprite was squashed square"
    assert abs(drawn.width() / drawn.height() - GIF_WIDTH / GIF_HEIGHT) < 0.05
    assert max(drawn.width(), drawn.height()) <= size


def test_a_still_image_keeps_its_proportions(tmp_path, qt_app):
    from PySide6.QtGui import QImage

    path = tmp_path / "still.png"
    QImage(10, 20, QImage.Format_ARGB32).save(str(path))
    sprite = Sprite(40)
    sprite.set_path(str(path))
    drawn = sprite.pixmap().size()
    assert (drawn.width(), drawn.height()) == (20, 40)


# MARK: resizing has to resize the picture


def test_resizing_resizes_the_sprite_not_just_the_box(animated, qt_app):
    """setScaledSize is honoured only until the first frame is decoded, so a
    loaded movie cannot be rescaled and has to be reopened. Changing the box
    alone left the slider moving the frame and not the Pokemon in it."""
    sprite = Sprite(96)
    sprite.set_path(animated)
    before = sprite.movie().currentPixmap().size()

    sprite.set_size(48)
    after = sprite.movie().currentPixmap().size()
    assert after != before, "the box shrank and the picture did not"
    assert max(after.width(), after.height()) == 48


def test_the_pet_resizes_through_the_setting(animated, qt_app):
    pet = DesktopPet()
    state = {"panel": {"sprite_path": animated}, "config": {"floating_pet_size": 96}}
    pet.update_state(state)
    before = pet.sprite.movie().currentPixmap().size()

    state["config"]["floating_pet_size"] = 48
    pet.update_state(state)
    after = pet.sprite.movie().currentPixmap().size()
    assert (pet.width(), pet.height()) == (48, 48)
    assert after != before


def test_resizing_to_the_same_size_does_not_restart_the_animation(animated, qt_app):
    """Reloading is how a resize works now, and a poll that changes nothing
    must not reload — the sprite would jump back to frame one every two
    seconds."""
    sprite = Sprite(96)
    sprite.set_path(animated)
    movie = sprite.movie()
    sprite.set_size(96)
    assert sprite.movie() is movie


# MARK: it has to be able to reach the other monitor


class _Screen:
    def __init__(self, rect):
        self._rect = rect

    def geometry(self):
        return self._rect

    def availableGeometry(self):
        return self._rect


def place_with(monkeypatch, pet, screens, x, y):
    monkeypatch.setattr(
        pet_module.QApplication, "instance",
        staticmethod(lambda: type("App", (), {"screens": lambda self: screens})()),
    )
    pet.place(x, y)
    return pet.x(), pet.y()


@pytest.fixture
def pet96(qt_app):
    pet = DesktopPet()
    pet.setFixedSize(96, 96)
    return pet


def test_the_pet_can_be_dragged_onto_a_second_monitor(monkeypatch, pet96):
    """It was clamped to the screen it was already on, which made the edge of
    the primary display a wall."""
    screens = [_Screen(QRect(0, 0, 1920, 1080)), _Screen(QRect(1920, 0, 1280, 1024))]
    assert place_with(monkeypatch, pet96, screens, 2400, 400)[0] == 2400


def test_a_monitor_below_counts_too(monkeypatch, pet96):
    """Choosing by horizontal distance alone hands the pet to the wrong screen
    on a stacked arrangement."""
    screens = [_Screen(QRect(0, 0, 1920, 1080)), _Screen(QRect(0, 1080, 1920, 1080))]
    assert place_with(monkeypatch, pet96, screens, 400, 2000)[1] == 2000


def test_it_still_cannot_be_pushed_off_the_far_edge(monkeypatch, pet96):
    screens = [_Screen(QRect(0, 0, 1920, 1080)), _Screen(QRect(1920, 0, 1280, 1024))]
    x, _y = place_with(monkeypatch, pet96, screens, 9999, 400)
    assert x == 1920 + 1280 - 96


def test_a_position_on_no_screen_is_pulled_back_onto_one(monkeypatch, pet96):
    """A position saved on a monitor that is no longer attached would otherwise
    leave the pet invisible with no way to get it back."""
    screens = [_Screen(QRect(0, 0, 1920, 1080))]
    x, y = place_with(monkeypatch, pet96, screens, -5000, -5000)
    assert screens[0].geometry().contains(QPoint(x, y))


def test_with_no_screens_at_all_it_just_moves(monkeypatch, pet96):
    """Qt can report none while a session is starting, and refusing to move is
    worse than moving somewhere."""
    assert place_with(monkeypatch, pet96, [], 300, 200) == (300, 200)
