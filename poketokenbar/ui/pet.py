"""The companion, living on the desktop.

A frameless always-on-top window rather than an actor on a compositor's stage,
which is what the GNOME front end gets to use. Windows has no equivalent of that
and no equivalent of Wayland's refusal to let a client place its own window
either, so the plain approach works: a borderless translucent widget positioned
wherever it was last left.

Hover shows today's usage, click opens the main window, drag moves it, and the
position is written back through the daemon's own config so it survives a
reboot.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtWidgets import QApplication, QLabel, QMenu, QVBoxLayout, QWidget

from .. import l10n

from .widgets import Sprite, label

# How far a press may travel and still count as a click rather than a drag.
# Without it every click ends as a one-pixel drag and the window never opens.
CLICK_SLOP = 4

DEFAULT_SIZE = 96

# Shown until a sprite has been fetched even once.
FALLBACK_GLYPH = "\N{EGG}"


class DesktopPet(QWidget):
    def __init__(self, on_activate=None, on_moved=None, on_hide=None) -> None:
        super().__init__()
        self._on_activate = on_activate or (lambda: None)
        self._on_moved = on_moved or (lambda x, y: None)
        self._on_hide = on_hide or self.hide
        self._state = {}
        self._last_alert_id = None
        self._bubble = QLabel(self, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self._bubble.setObjectName("pet_limit_bubble")
        self._bubble.setTextFormat(Qt.PlainText)
        self._bubble.setWordWrap(True)
        self._bubble.setFixedWidth(220)
        self._bubble.setContentsMargins(10, 8, 10, 8)
        self._bubble.setStyleSheet("background: #2c2c2c; color: white; border: 1px solid #666; border-radius: 8px;")
        self._bubble.setAttribute(Qt.WA_ShowWithoutActivating)
        self._bubble.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self._bubble.hide)
        self._press: QPoint | None = None
        self._dragging = False
        self._tooltip_text = ""
        # The last path that actually resolved to a file. A sprite the daemon
        # could not download comes through as "", and drawing that meant an
        # invisible window — so the pet vanished and came back as the network
        # flapped, which is the same thing as "it keeps disappearing".
        self._last_sprite = ""

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            # Keeps it off the taskbar and out of Alt-Tab: it is an ornament,
            # not a window someone switches to.
            | Qt.Tool
            # And it must never become the active window. Windows owns a tool
            # window to whichever window of the application was last active, so
            # a pet that takes activation on click becomes owned by the popup —
            # and vanishes with it the moment the popup is closed again. That
            # is the "it disappears when I click it" report.
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # Same reason, for the show() that follows: showing a window normally
        # activates it.
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.sprite = Sprite(DEFAULT_SIZE)
        layout.addWidget(self.sprite)
        self.set_size(DEFAULT_SIZE)

    # --- state -------------------------------------------------------------

    def set_size(self, size: int) -> None:
        """Resize the window and the sprite in it.

        Poking the sprite's private size did the first half only: the picture
        had already been scaled when it was loaded, and nothing rescaled it, so
        the slider moved the box and left the Pokemon the size it was.
        """
        self.sprite.set_size(size)
        self.setFixedSize(size, size)

    def update_state(self, state: dict | None) -> None:
        self._state = state or {}
        panel = self._state.get("panel") or {}
        # Follows the panel, so a pinned species shows here too — the daemon has
        # already resolved which one that is. An empty path is a fetch that has
        # not succeeded yet, never a decision to show nothing, so the last one
        # that worked stays up rather than the pet blanking.
        path = panel.get("sprite_path") or ""
        if path:
            self._last_sprite = path
        # Before the first sprite ever arrives — a fresh install with no
        # network — the glyph is what stands in. An empty translucent window
        # is indistinguishable from the pet being gone.
        self.sprite.set_fallback(FALLBACK_GLYPH)
        self.sprite.set_path(self._last_sprite or None)

        config = (state or {}).get("config") or {}
        size = int(config.get("floating_pet_size") or DEFAULT_SIZE)
        if size != self.width():
            self.set_size(size)
        # Both always-visible surfaces share one quality setting, as upstream's
        # do: a frame costs a redraw wherever it is drawn.
        from .widgets import quality_of
        from ..system_state import power_saver

        self.sprite.set_quality("saver" if power_saver() else quality_of(config))

        today = (state or {}).get("today") or {}
        tooltip = today.get("tokens_grouped", "")
        if tooltip != self._tooltip_text:
            self._tooltip_text = tooltip
            self.setToolTip(tooltip)

        alert = self._state.get("limit_alert") or {}
        if alert.get("id") and alert["id"] != self._last_alert_id:
            self._last_alert_id = alert["id"]
            age = time.time() - float(alert.get("created_at", 0))
            if config.get("limit_notifications", True) and 0 <= age < 15:
                self._bubble.setText(str(alert.get("title", "")) + "\n" + str(alert.get("body", "")))
                self._bubble.adjustSize()
                self._place_bubble()
                self._bubble.show()
                self._bubble_timer.start(12000)
        if not config.get("limit_notifications", True):
            self._bubble.hide()

    def context_menu(self):
        language = (self._state.get("config") or {}).get("language", "en")
        menu = QMenu(self)
        menu.addAction(l10n.t("open", language), self._on_activate)
        menu.addAction(l10n.t("floating_pet_hide", language), self._on_hide)
        return menu

    def contextMenuEvent(self, event) -> None:
        menu = self.context_menu()
        menu.exec(event.globalPos())
        menu.deleteLater()
        event.accept()

    def _place_bubble(self) -> None:
        screen = self._screen_for(self.x(), self.y())
        x = self.x() + (self.width() - self._bubble.width()) // 2
        y = self.y() - self._bubble.height() - 6
        if screen:
            area = screen.availableGeometry()
            x = max(area.left(), min(x, area.right() - self._bubble.width() + 1))
            if y < area.top():
                y = min(area.bottom() - self._bubble.height() + 1, self.y() + self.height() + 6)
        self._bubble.move(x, y)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        if hasattr(self, "_bubble"):
            self._place_bubble()

    def hideEvent(self, event) -> None:
        self._bubble.hide()
        super().hideEvent(event)

    def place(self, x: int, y: int) -> None:
        """Move the pet, keeping it reachable on some screen.

        Clamped to the screen the position lands on, not to the one the pet is
        currently on — that made the edge of the current monitor a wall, so a
        pet on the primary display could never be dragged onto the second.

        A position on a monitor that is no longer attached still has to end up
        somewhere visible, so a point that belongs to no screen is pulled into
        the nearest one rather than left where it was.
        """
        x, y = int(x), int(y)
        screen = self._screen_for(x, y)
        if screen is None:
            self.move(x, y)
            return
        area = screen.availableGeometry()
        self.move(
            max(area.left(), min(x, area.right() - self.width() + 1)),
            max(area.top(), min(y, area.bottom() - self.height() + 1)),
        )

    def _screen_for(self, x: int, y: int):
        """The screen a position belongs to, else the nearest one.

        Nearest by the distance to each screen's rectangle, so dragging past
        the edge of one monitor hands the pet to whichever is actually next to
        it — including one above or below, which comparing centres gets wrong
        on a stacked arrangement.
        """
        application = QApplication.instance()
        screens = list(application.screens()) if application else []
        if not screens:
            return None
        centre = QPoint(x + self.width() // 2, y + self.height() // 2)
        for screen in screens:
            if screen.geometry().contains(centre):
                return screen
        return min(screens, key=lambda s: _distance(s.geometry(), centre))


    # --- interaction --------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        if self._press is None:
            return
        target = event.globalPosition().toPoint() - self._press
        if not self._dragging:
            travelled = (target - self.pos()).manhattanLength()
            if travelled < CLICK_SLOP:
                return
            self._dragging = True
        self.place(target.x(), target.y())
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if self._press is None:
            return
        was_dragging = self._dragging
        self._press = None
        self._dragging = False
        if was_dragging:
            self._on_moved(self.x(), self.y())
        else:
            self._on_activate()
        event.accept()


def _distance(rect, point: QPoint) -> int:
    """Squared distance from a point to a rectangle, zero inside it."""
    dx = max(rect.left() - point.x(), 0, point.x() - rect.right())
    dy = max(rect.top() - point.y(), 0, point.y() - rect.bottom())
    return dx * dx + dy * dy
