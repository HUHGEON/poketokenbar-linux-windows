"""The small pieces the panels are built from.

Qt plays a GIF natively through QMovie, so unlike the GNOME front end there is
no frame decoding here at all — the animated Gen-V sprites are handed to Qt as
files and it does the rest.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QMovie, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

# Utilisation bands, matching limits.level() in the daemon. Stated outright
# rather than taken from the palette: "close to your limit" has to read as a
# warning whatever theme is in use.
LEVEL_COLOURS = {
    "ok": "#3fb950",
    "warn": "#d29922",
    "crit": "#f85149",
}


def level_colour(level: str | None) -> str:
    return LEVEL_COLOURS.get(level or "ok", LEVEL_COLOURS["ok"])


# Frame-duration floors in seconds, so a larger number is fewer frames per
# second. Mirrors the GNOME front end's framecap.js and the macOS app's
# AnimationQuality — a frame costs a redraw wherever it is drawn, and these are
# the two always-visible surfaces.
#
# None of them is 0: an animation running at native rate keeps the machine
# awake, which is why "saver" is also the default.
FRAME_FLOORS = {"saver": 0.4, "balanced": 0.2, "smooth": 0.1}
DEFAULT_QUALITY = "saver"

# Animation switched off entirely. Deliberately not a fourth entry in the table
# above: those are frame rates, and this is the absence of one. An infinite
# floor says exactly that — `decimate` collapses a loop into its first frame,
# and a one-frame schedule starts no timer, so a still sprite costs no redraws.
# Mirrors ANIMATION_OFF in the GNOME front end's framecap.js.
ANIMATION_OFF = "off"


def frame_floor(quality: str | None) -> float:
    if quality == ANIMATION_OFF:
        return math.inf
    return FRAME_FLOORS.get(quality or "", FRAME_FLOORS[DEFAULT_QUALITY])


def quality_of(config: dict | None) -> str:
    return (config or {}).get("animation_quality") or DEFAULT_QUALITY


def decimate(delays: list[float], floor: float) -> list[tuple[int, float]]:
    """Thin frames so none is shown for less than `floor`, keeping the speed.

    Returns (frame index, hold in seconds). The rule is the one a plausible
    implementation gets wrong: **drop frames, never stretch them.** Raising each
    frame's own delay to the floor keeps all of them and lengthens the loop —
    upstream measured a 55-frame, 2.75s Gen-V sprite becoming a 22s loop at a
    0.4s floor, an eighth of the intended speed.
    """
    if floor <= 0 or len(delays) <= 1:
        return [(index, delay) for index, delay in enumerate(delays)]

    out: list[tuple[int, float]] = []
    held: int | None = None
    accumulated = 0.0
    for index, delay in enumerate(delays):
        if held is None:
            held = index
        accumulated += delay
        # The epsilon keeps floating-point accumulation from pushing an interval
        # one frame further than it should.
        if accumulated + 1e-9 >= floor:
            out.append((held, accumulated))
            held = None
            accumulated = 0.0
    # A short tail is merged into the previous frame rather than emitted on its
    # own, so one loop still lasts exactly as long as the source did.
    if held is not None and accumulated > 0:
        if out:
            out[-1] = (out[-1][0], out[-1][1] + accumulated)
        else:
            out.append((held, accumulated))
    return out


class Sprite(QLabel):
    """An animated sprite.

    A repeat of the same path is a no-op: rebuilding the QMovie on every poll
    would restart the animation from frame one every two seconds, so the
    companion would visibly stutter rather than loop.
    """

    def __init__(self, size: int = 64, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self._path: str | None = None
        self._movie: QMovie | None = None
        self._quality = DEFAULT_QUALITY
        self._schedule: list[tuple[int, float]] = []
        self._step = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedSize(size, size)

    def set_path(self, path: str | None) -> None:
        if path == self._path:
            return
        self._path = path
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        if not path:
            self.clear()
            return

        movie = QMovie(path)
        if movie.isValid():
            # Scaled here rather than by the label: QMovie renders at its own
            # size and a scaledContents label would resample every frame.
            movie.setScaledSize(QSize(self._size, self._size))
            self._movie = movie
            self.setMovie(movie)
            self._rebuild_schedule()
            return

        # A still PNG, or a GIF Qt could not read. Either way one frame beats
        # a blank square.
        pixmap = QPixmap(path)
        if pixmap.isNull():
            self.clear()
            return
        self.setPixmap(pixmap.scaled(
            self._size, self._size, Qt.KeepAspectRatio, Qt.FastTransformation))

    def set_quality(self, quality: str) -> None:
        """Change how smoothly this sprite animates.

        Re-times the frames already loaded rather than reopening the file: the
        pixels have not changed, only how many of them get drawn.
        """
        if quality == self._quality:
            return
        self._quality = quality
        self._rebuild_schedule()

    def set_paused(self, paused: bool) -> None:
        """Stop animating without discarding the movie.

        The window spends most of its life hidden in the tray, and a sprite
        nobody can see should not be costing frames.
        """
        if self._movie is None:
            return
        if paused:
            self._timer.stop()
            self._movie.setPaused(True)
        else:
            self._movie.setPaused(False)
            self._rebuild_schedule()

    def _rebuild_schedule(self) -> None:
        """Work out which frames to show, and for how long.

        QMovie plays a GIF at its own rate, which is correct but is also every
        frame. Driving it by hand is what allows the rate to come down without
        the loop getting longer — `setSpeed` would do the opposite.
        """
        self._timer.stop()
        movie = self._movie
        if movie is None:
            return
        count = movie.frameCount()
        if count <= 1:
            movie.jumpToFrame(0)
            return

        delays = []
        for index in range(count):
            movie.jumpToFrame(index)
            # Milliseconds on the wire, seconds here.
            delays.append(max(0.02, movie.nextFrameDelay() / 1000))
        self._schedule = decimate(delays, frame_floor(self._quality))
        self._step = 0
        self._show_step()

    def _show_step(self) -> None:
        if not self._schedule or self._movie is None:
            return
        index, hold = self._schedule[self._step]
        self._movie.jumpToFrame(index)
        # One frame is a still sprite — with animation off, or a single-frame
        # file. Timing it would wake the process once a loop to redraw the
        # picture it is already showing.
        if len(self._schedule) > 1:
            self._timer.start(max(20, round(hold * 1000)))

    def _advance(self) -> None:
        if not self._schedule:
            return
        self._step = (self._step + 1) % len(self._schedule)
        self._show_step()


def label(text: str = "", *, dim: bool = False, bold: bool = False,
          colour: str | None = None, size: int | None = None) -> QLabel:
    widget = QLabel(text)
    parts = []
    if bold:
        parts.append("font-weight: bold")
    if colour:
        parts.append(f"color: {colour}")
    if size:
        parts.append(f"font-size: {size}px")
    if dim:
        parts.append("color: palette(mid)")
    if parts:
        widget.setStyleSheet("; ".join(parts))
    widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return widget


def heading(text: str) -> QLabel:
    return label(text, bold=True)


def row(*widgets: QWidget) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def stat_line(name: str, value: str, colour: str | None = None) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(label(name, dim=True))
    layout.addStretch(1)
    layout.addWidget(label(value, colour=colour))
    return container


def meter(fraction: float, level: str | None = None) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 100)
    # Clamped so a limit past 100% still reads as full rather than wrapping.
    bar.setValue(max(0, min(100, round((fraction or 0) * 100))))
    bar.setTextVisible(False)
    bar.setFixedHeight(6)
    bar.setStyleSheet(
        "QProgressBar { border: none; background: palette(alternate-base); }"
        f"QProgressBar::chunk {{ background: {level_colour(level)}; }}"
    )
    return bar


def button(text: str, on_click, enabled: bool = True) -> QPushButton:
    widget = QPushButton(text)
    widget.clicked.connect(on_click)
    widget.setEnabled(enabled)
    return widget


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    return line


def card(*widgets: QWidget) -> QWidget:
    container = QWidget()
    container.setStyleSheet(
        "background: palette(alternate-base); border-radius: 6px;")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(8, 6, 8, 6)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def column(*widgets: QWidget) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    for widget in widgets:
        layout.addWidget(widget)
    return container


def clear_layout(layout) -> None:
    """Empty a layout, destroying what was in it.

    `deleteLater` rather than a plain drop: a widget removed from its layout is
    still parented and still painted until Qt collects it, so without this a
    rebuilt panel shows both versions at once.
    """
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
