"""The small pieces the panels are built from.

Qt plays a GIF natively through QMovie, so unlike the GNOME front end there is
no frame decoding here at all — the animated Gen-V sprites are handed to Qt as
files and it does the rest.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QImageReader, QMovie, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLayout, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from . import theme

# Utilisation bands, matching limits.level() in the daemon. Stated outright
# rather than taken from the palette: "close to your limit" has to read as a
# warning whatever theme is in use.
LEVEL_COLOURS = {
    "ok": theme.GREEN,
    "warn": theme.ORANGE,
    "crit": theme.RED,
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


def frame_floor(quality: str | None) -> float:
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
        self._fallback = ""
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

    def set_fallback(self, text: str) -> None:
        """What to draw when there is no image.

        Mint is a Gen-VIII item and PokeAPI has no sprite for it, so the daemon
        ships an emoji beside every item for exactly this. Ignoring it left a
        blank square in the shop where upstream shows a leaf.
        """
        if text == self._fallback:
            return
        self._fallback = text
        if not self._path:
            self._show_fallback()

    def _show_fallback(self) -> None:
        self.clear()
        if not self._fallback:
            return
        self.setText(self._fallback)
        self.setStyleSheet(f"font-size: {max(12, int(self._size * 0.7))}px;"
                           " background: transparent;")

    def set_path(self, path: str | None) -> None:
        if path == self._path:
            return
        self._path = path
        self._load()

    def set_size(self, size: int) -> None:
        """Resize the box and what is in it.

        The sprite is reloaded rather than rescaled, because a QMovie cannot be
        rescaled: `setScaledSize` is honoured only until the first frame has
        been decoded and is silently ignored after that — measured, with and
        without caching. Changing the box alone was what left the slider moving
        the frame and not the Pokemon inside it.
        """
        if size == self._size:
            return
        self._size = size
        self.setFixedSize(size, size)
        self._load()

    def _load(self) -> None:
        """Open whatever `_path` names, fitted to the current box."""
        if self._movie is not None:
            self._movie.stop()
            self._movie = None
        self._timer.stop()
        self._schedule = []
        self._step = 0
        if not self._path:
            self._show_fallback()
            return

        # The size on disk, without decoding anything: a QMovie reports its
        # *scaled* size once it has produced a frame, so asking it would fit an
        # already-fitted size on the second pass.
        reader = QImageReader(self._path)
        native = reader.size()
        frames = reader.imageCount()
        fitted = (native.scaled(QSize(self._size, self._size), Qt.KeepAspectRatio)
                  if not native.isEmpty() else QSize(self._size, self._size))

        if frames > 1:
            movie = QMovie(self._path)
            # Without this every jumpToFrame that is not the next one fails
            # silently and the movie stays where it was. A GIF decodes
            # sequentially, so seeking backwards — which is what the end of a
            # loop does — needs the frames kept. Measured on a 178-frame
            # sprite: uncached, jumps to 10, 40 and 3 all returned false and
            # left it on frame 0, so the pet held one pose at every quality.
            movie.setCacheMode(QMovie.CacheAll)
            if movie.isValid():
                # Before the first frame, or it is ignored for the movie's life.
                movie.setScaledSize(fitted)
                self._movie = movie
                self.setMovie(movie)
                self._rebuild_schedule()
                return

        # A still image, or a GIF Qt could not read. Either way one frame beats
        # a blank square.
        pixmap = QPixmap(self._path)
        if pixmap.isNull():
            self._show_fallback()
            return
        self.setText("")
        self.setPixmap(pixmap.scaled(
            fitted.width() or self._size, fitted.height() or self._size,
            Qt.KeepAspectRatio, Qt.FastTransformation))

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
        self._timer.start(max(20, round(hold * 1000)))

    def _advance(self) -> None:
        if not self._schedule:
            return
        self._step = (self._step + 1) % len(self._schedule)
        self._show_step()


def _no_squeeze(container: QWidget) -> QWidget:
    """Let a container grow but never shrink below what it asked for.

    Qt's default vertical policy is Preferred, which permits a layout short of
    room to compress a child *below its own minimum*. Inside a scroll area that
    is silently wrong: instead of a scrollbar appearing, the tallest card is
    crushed — which is what flattened the companion's name, meter and status
    message into a 44px strip while the rows beneath it rendered fine. Minimum
    means "sizeHint is the floor", so the body grows and the scroll area does
    its job.
    """
    container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return container


def label(text: str = "", *, dim: bool = False, bold: bool = False,
          colour: str | None = None, size: int | None = None,
          faint: bool = False, wrap: bool = False) -> QLabel:
    """One line of text, in one of the popover's three text weights.

    `dim` and `faint` are the secondary and tertiary greys rather than a
    palette role: the window paints its own dark surface, so palette(mid) would
    be resolved against the system theme and come out unreadable on it.
    """
    widget = QLabel(text)
    parts = [f"color: {colour or (theme.TERTIARY if faint else theme.SECONDARY if dim else theme.TEXT)}"]
    if bold:
        parts.append("font-weight: 600")
    if size:
        parts.append(f"font-size: {size}px")
    parts.append("background: transparent")
    widget.setStyleSheet("; ".join(parts))
    if wrap:
        widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return widget


def heading(text: str) -> QLabel:
    """A section title — the small grey caption above a group of rows."""
    return label(text, dim=True, size=12)


def big(text: str, size: int = 34) -> QLabel:
    return label(text, bold=True, size=size)


def badge(text: str, background: str, foreground: str, size: int = 10) -> QLabel:
    """A rounded pill: rarity, "raising", a Pokedex number."""
    widget = QLabel(text)
    widget.setStyleSheet(
        f"background: {background}; color: {foreground}; font-size: {size}px;"
        f" font-weight: 600; border-radius: 5px; padding: 1px 6px;"
    )
    widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Maximum)
    return widget


def rarity_badge(rarity: str | None, text: str) -> QLabel:
    background, foreground = theme.rarity_colours(rarity)
    return badge(text, background, foreground)


def row(*widgets: QWidget, spacing: int = 6, stretch: bool = False) -> QWidget:
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    if stretch:
        layout.addStretch(1)
    return _no_squeeze(container)


class _FlowLayout(QLayout):
    """A horizontal layout that wraps instead of forcing the window wider.

    The rarity filter is four chips whose text is translated, and a QHBoxLayout
    reports the sum of them as a minimum. Korean fits in 252px; French needs
    397 in a 368px column, and Qt honoured that by widening the scroll content
    until the fourth Pokedex column fell off the right edge of the popup. So
    the row wraps: one line in Korean and Japanese, two in French and German,
    and nothing is clipped in a language nobody has added yet.
    """

    def __init__(self, spacing: int = 2) -> None:
        super().__init__()
        self._items: list = []
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(spacing)

    def addItem(self, item) -> None:  # noqa: N802 - Qt override
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802 - Qt override
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802 - Qt override
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802 - Qt override
        return Qt.Orientations(Qt.Orientation(0))

    def hasHeightForWidth(self) -> bool:  # noqa: N802 - Qt override
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802 - Qt override
        return self._lay(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect) -> None:  # noqa: N802 - Qt override
        super().setGeometry(rect)
        self._lay(rect, apply=True)

    def sizeHint(self) -> QSize:  # noqa: N802 - Qt override
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802 - Qt override
        # The widest single chip, not the sum: that is what makes the wrap a
        # real answer rather than a delayed version of the same overflow.
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _lay(self, rect, *, apply: bool) -> int:
        x, y, line_height = rect.x(), rect.y(), 0
        for item in self._items:
            hint = item.sizeHint()
            if line_height and x + hint.width() > rect.right() + 1:
                x, y = rect.x(), y + line_height + self.spacing()
                line_height = 0
            if apply:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self.spacing()
            line_height = max(line_height, hint.height())
        return y + line_height - rect.y()


def wrap_row(*widgets: QWidget, spacing: int = 2) -> QWidget:
    """A row of widgets that wraps onto a second line when it does not fit."""
    container = QWidget()
    layout = _FlowLayout(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    container.setLayout(layout)
    container.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
    return container


def spread(left: QWidget, right: QWidget) -> QWidget:
    """Two widgets pushed to opposite edges — the shape of every stat line."""
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(6)
    layout.addWidget(left)
    layout.addStretch(1)
    layout.addWidget(right)
    return _no_squeeze(container)


def stat_line(name: str, value: str, colour: str | None = None) -> QWidget:
    return spread(label(name, dim=True), label(value, colour=colour))


def meter(fraction: float, level: str | None = None) -> QProgressBar:
    bar = QProgressBar()
    bar.setRange(0, 100)
    # Clamped so a limit past 100% still reads as full rather than wrapping.
    bar.setValue(max(0, min(100, round((fraction or 0) * 100))))
    bar.setTextVisible(False)
    bar.setFixedHeight(6)
    bar.setStyleSheet(
        f"QProgressBar {{ border: none; background: {theme.RAISED};"
        f" border-radius: 3px; }}"
        f"QProgressBar::chunk {{ background: {level_colour(level)};"
        f" border-radius: 3px; }}"
    )
    return bar


def button(text: str, on_click, enabled: bool = True) -> QPushButton:
    """A filled pill button — the shop's Buy, the bag's Use."""
    widget = QPushButton(text)
    widget.clicked.connect(on_click)
    widget.setEnabled(enabled)
    widget.setCursor(Qt.PointingHandCursor)
    widget.setStyleSheet(
        f"QPushButton {{ background: {theme.RAISED}; color: {theme.TEXT};"
        f" border: none; border-radius: 7px; padding: 5px 14px;"
        f" font-size: 12px; font-weight: 600; }}"
        f"QPushButton:hover {{ background: #4a4a4c; }}"
        f"QPushButton:disabled {{ color: {theme.TERTIARY}; }}"
    )
    return widget


def icon_button(glyph: str, on_click, tooltip: str = "", size: int = 15) -> QPushButton:
    """A bare glyph — the footer's gear, power and refresh."""
    widget = QPushButton(glyph)
    widget.clicked.connect(on_click)
    widget.setCursor(Qt.PointingHandCursor)
    widget.setToolTip(tooltip)
    widget.setFlat(True)
    widget.setStyleSheet(
        f"QPushButton {{ background: transparent; color: {theme.SECONDARY};"
        f" border: none; font-size: {size}px; padding: 3px 6px; }}"
        f"QPushButton:hover {{ color: {theme.TEXT}; }}"
    )
    return widget


def separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.DIVIDER}; border: none;")
    return line


def card(*widgets: QWidget, horizontal: bool = True, padding: int = 10,
         spacing: int = 8, background: str | None = None) -> QWidget:
    """The rounded surface every group of rows sits on."""
    container = QWidget()
    container.setStyleSheet(
        f"background: {background or theme.CARD}; border-radius: 10px;")
    layout = (QHBoxLayout if horizontal else QVBoxLayout)(container)
    layout.setContentsMargins(padding, padding, padding, padding)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    return _no_squeeze(container)


def column(*widgets: QWidget, spacing: int = 2, align_top: bool = False) -> QWidget:
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(spacing)
    for widget in widgets:
        layout.addWidget(widget)
    if align_top:
        layout.addStretch(1)
    return _no_squeeze(container)


class Segmented(QWidget):
    """The tab strip, and the used/remaining switch in settings.

    One button per option with the active one filled in the accent colour —
    the shape the popover uses in three places, so it is one widget rather
    than three near-copies.
    """

    def __init__(self, options, on_select, active=None, compact: bool = False) -> None:
        super().__init__()
        self._buttons = {}
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.setStyleSheet(f"background: {theme.CARD}; border-radius: 9px;")
        for value, text in options:
            item = QPushButton(text)
            item.setCursor(Qt.PointingHandCursor)
            item.setFlat(True)
            item.clicked.connect(lambda _=False, v=value: on_select(v))
            self._buttons[value] = item
            layout.addWidget(item)
        self._compact = compact
        self.set_active(active if active is not None else next(iter(self._buttons), None))

    def set_active(self, active) -> None:
        padding = "3px 10px" if self._compact else "6px 16px"
        for value, item in self._buttons.items():
            on = value == active
            item.setStyleSheet(
                f"QPushButton {{ border: none; border-radius: 7px;"
                f" padding: {padding}; font-size: 12px; font-weight: 600;"
                f" background: {theme.ACCENT if on else 'transparent'};"
                f" color: {theme.TEXT if on else theme.SECONDARY}; }}"
                + ("" if on else
                   f"QPushButton:hover {{ color: {theme.TEXT}; }}")
            )


def chip(text: str, dot: str, active: bool, on_click=None) -> QWidget:
    """A rarity filter: a coloured dot, a name and a count.

    The dot keeps its hue whether or not the chip is selected — it is the
    legend for the colour used on every badge in the grid, so greying it out
    along with the text takes the legend away exactly when it is being read.
    """
    container = QWidget()
    container.setCursor(Qt.PointingHandCursor)
    container.setStyleSheet(
        f"background: {theme.CARD if active else 'transparent'};"
        f" border-radius: 9px;")
    layout = QHBoxLayout(container)
    layout.setContentsMargins(9, 3, 9, 3)
    layout.setSpacing(5)
    marker = QLabel("\u25cf")
    marker.setStyleSheet(f"color: {dot}; font-size: 9px; background: transparent;")
    caption = QLabel(text)
    caption.setStyleSheet(
        f"color: {theme.TEXT if active else theme.TERTIARY}; font-size: 11px;"
        f" font-weight: 600; background: transparent;")
    layout.addWidget(marker)
    layout.addWidget(caption)
    if on_click is not None:
        container.mousePressEvent = lambda _event: on_click()
    return _no_squeeze(container)


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
