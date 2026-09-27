"""The tray icon and the window it opens.

Windows has no panel to extend, so the companion lives in the notification
area: the tray icon is the sprite, its tooltip carries today's numbers, and
clicking it opens the tabs.

The window is hidden rather than closed. Recreating it on every open would
throw away the Pokedex page someone was on and restart every sprite, and on
Windows a closed tray app that is still running is the normal shape.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QIcon, QMovie, QPixmap
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QMenu, QStackedWidget, QSystemTrayIcon,
    QVBoxLayout, QWidget,
)

from .. import commands, config
from .pet import DesktopPet
from .panels import (
    BagPanel, CollectionPanel, HomePanel, SettingsPanel, ShopPanel, ago,
)
from .reader import StateReader
from . import theme
from .widgets import (
    DEFAULT_QUALITY, Segmented, decimate, frame_floor, icon_button, label,
    quality_of, separator,
)

# The window is a fixed width so the Pokedex grid never reflows mid-browse.
WINDOW_SIZE = (400, 640)
# Matches the daemon's own default refresh, which is what actually changes the
# file — polling faster only re-reads the same bytes.
POLL_MILLISECONDS = 2000
# Tray icons are small; the sprite is scaled to this.
TRAY_ICON_SIZE = 22
# Frames past this are dropped, matching the GNOME front end: Gen-V sprites run
# to a few hundred at most, and anything far beyond that is not one of ours.
MAX_TRAY_FRAMES = 240


class Window(QWidget):
    """The tab strip, the page underneath it, and a footer.

    Settings is a page rather than a fifth tab, matching the popover: it is
    reached from the gear in the footer and leaves by its own back button, so
    the four tabs stay the four things someone switches between.
    """

    def __init__(self, reader: StateReader) -> None:
        super().__init__()
        self.reader = reader
        self.setWindowTitle("PokeTokenBar")
        self.resize(*WINDOW_SIZE)
        self.setStyleSheet(theme.STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.panels = {
            "home": HomePanel(reader),
            "shop": ShopPanel(reader),
            "bag": BagPanel(reader),
            "collection": CollectionPanel(reader),
        }
        self.settings = SettingsPanel(reader)
        self._current = "home"

        self.tabs = Segmented(
            tuple((key, reader.text(key)) for key in self.panels),
            self.show_tab, active="home")
        self.tab_bar = QWidget()
        bar_layout = QHBoxLayout(self.tab_bar)
        bar_layout.setContentsMargins(12, 10, 12, 6)
        bar_layout.addWidget(self.tabs)
        bar_layout.addStretch(1)
        layout.addWidget(self.tab_bar)

        # The settings header, shown only on that page.
        self.settings_bar = QWidget()
        header = QHBoxLayout(self.settings_bar)
        header.setContentsMargins(8, 10, 8, 6)
        back = icon_button("‹", lambda: self.show_tab(self._current), size=17)
        self.back_label = label(reader.text("back"), colour=theme.ACCENT)
        back_row = QWidget()
        back_row_layout = QHBoxLayout(back_row)
        back_row_layout.setContentsMargins(0, 0, 0, 0)
        back_row_layout.setSpacing(0)
        back_row_layout.addWidget(back)
        back_row_layout.addWidget(self.back_label)
        self.settings_title = label(reader.text("settings"), bold=True)
        header.addWidget(back_row)
        header.addStretch(1)
        header.addWidget(self.settings_title)
        header.addStretch(1)
        # Balances the title so it sits centred rather than pushed right.
        spacer = QWidget()
        spacer.setFixedWidth(back_row.sizeHint().width())
        header.addWidget(spacer)
        self.settings_bar.hide()
        layout.addWidget(self.settings_bar)

        self.stack = QStackedWidget()
        for panel in self.panels.values():
            self.stack.addWidget(panel)
        self.stack.addWidget(self.settings)
        layout.addWidget(self.stack, 1)

        layout.addWidget(separator())
        self.footer = label("", dim=True, size=12)
        footer_bar = QWidget()
        footer_layout = QHBoxLayout(footer_bar)
        footer_layout.setContentsMargins(12, 6, 10, 8)
        footer_layout.setSpacing(6)
        footer_layout.addWidget(icon_button(
            "\u21bb", lambda: commands.enqueue("refresh", {}),
            reader.text("refresh")))
        footer_layout.addWidget(self.footer)
        footer_layout.addStretch(1)
        self.gear = icon_button("\u2699", self.show_settings, reader.text("settings"))
        footer_layout.addWidget(self.gear)
        # Quits this window only. The daemon is a separate process and keeps
        # counting — closing the view must not lose someone's progress.
        footer_layout.addWidget(icon_button(
            "\u23fb", lambda: QApplication.instance().quit(), reader.text("quit")))
        layout.addWidget(footer_bar)

    # --- navigation --------------------------------------------------------

    def show_tab(self, key: str) -> None:
        self._current = key
        self.tabs.set_active(key)
        self.tab_bar.show()
        self.settings_bar.hide()
        self.stack.setCurrentWidget(self.panels[key])
        self.refresh(self.reader.state)

    def show_settings(self) -> None:
        self.tab_bar.hide()
        self.settings_bar.show()
        self.stack.setCurrentWidget(self.settings)
        self.refresh(self.reader.state)

    def _relabel(self) -> None:
        """Re-label the chrome from the current catalogue.

        It is built before the first successful read, when `text()` still
        returns the key itself — so without this the tabs read "home", "shop",
        "bag" in lower case forever, and a language change never reaches them.
        """
        for key, item in self.tabs._buttons.items():
            title = self.reader.text(key)
            if item.text() != title:
                item.setText(title)
        self.tabs.set_active(self._current)
        self.settings_title.setText(self.reader.text("settings"))
        self.back_label.setText(self.reader.text("back"))

    def refresh(self, state: dict | None) -> None:
        self._relabel()
        # Only the visible page is rebuilt: the others would throw their
        # children away again before anyone saw them.
        current = self.stack.currentWidget()
        for panel in list(self.panels.values()) + [self.settings]:
            if panel is current:
                # refresh(), not update(): it skips the rebuild when nothing
                # visible changed and puts the scroll position back when it
                # does not.
                panel.refresh(state)
        self.footer.setText(self._footer_text(state))

    def _footer_text(self, state: dict | None) -> str:
        if self.reader.error:
            return self.reader.error
        if self.reader.is_stale():
            return self.reader.text("stale_warning")
        errors = (state or {}).get("errors") or []
        if errors:
            return ", ".join(errors)
        if (state or {}).get("scanning"):
            return self.reader.text("scanning")
        age = self.reader.age_seconds()
        return "" if age is None else ago(age, self.reader.text)


class TrayApp:
    """Wires the reader, the tray icon and the window together."""

    def __init__(self, app: QApplication, reader: StateReader | None = None) -> None:
        self.app = app
        self.reader = reader or StateReader()
        self.window = Window(self.reader)
        self._sprite_path: str | None = None
        self._quality = DEFAULT_QUALITY
        # Pre-rendered (icon, hold) pairs and the timer that cycles them.
        self._icon_frames: list = []
        self._icon_step = 0
        self._icon_timer = QTimer()
        self._icon_timer.setSingleShot(True)
        self._icon_timer.timeout.connect(self._advance_icon)

        # Created only when the setting is on, and destroyed when it goes off.
        self.pet: DesktopPet | None = None

        self.tray = QSystemTrayIcon()
        self.tray.setIcon(self._fallback_icon())
        self.tray.setContextMenu(self._menu())
        self.tray.activated.connect(self._on_activated)

        self.timer = QTimer()
        self.timer.setInterval(POLL_MILLISECONDS)
        self.timer.timeout.connect(self.poll)

    def _menu(self) -> QMenu:
        # Keyed by catalogue key so _relabel_menu can put the translated text
        # back. Built before the first read, when text() still returns the key
        # itself — the same trap the tab strip fell into, and here it survived
        # every poll because a menu is only built once.
        self._menu_actions = {}
        menu = QMenu()
        show = QAction(self.reader.text("open"), menu)
        show.triggered.connect(self.toggle_window)
        self._menu_actions["open"] = show
        menu.addAction(show)

        refresh = QAction(self.reader.text("refresh"), menu)
        refresh.triggered.connect(lambda: commands.enqueue("refresh", {}))
        self._menu_actions["refresh"] = refresh
        menu.addAction(refresh)

        menu.addSeparator()
        # The daemon has handled these all along; without a control they were
        # reachable only from poketokenctl, which is not where anyone would look
        # for "move my Pokedex to another machine".
        export = QAction(self.reader.text("export_save"), menu)
        export.triggered.connect(
            lambda: commands.enqueue("export", {"path": str(self.save_path())}))
        self._menu_actions["export_save"] = export
        menu.addAction(export)

        import_action = QAction(self.reader.text("import_save"), menu)
        import_action.triggered.connect(
            lambda: commands.enqueue("import", {"path": str(self.save_path())}))
        self._menu_actions["import_save"] = import_action
        menu.addAction(import_action)

        menu.addSeparator()
        quit_action = QAction(self.reader.text("quit"), menu)
        # Quits this window only. The daemon is a separate process and keeps
        # counting — closing the view must not lose someone's progress.
        quit_action.triggered.connect(self.app.quit)
        self._menu_actions["quit"] = quit_action
        menu.addAction(quit_action)
        return menu

    def save_path(self):
        """Where a save is written to and read from.

        A fixed, predictable path rather than a file dialog: the export is
        triggered from a tray menu, and a modal file chooser from there is more
        ceremony than moving a Pokedex is worth.
        """
        from pathlib import Path

        return Path.home() / "poketokenbar-save.json"

    def _fallback_icon(self) -> QIcon:
        """A blank icon, so the tray entry exists before the first sprite.

        Without one the tray shows nothing at all and there is no way to open
        the window — which looks exactly like a crash.
        """
        pixmap = QPixmap(TRAY_ICON_SIZE, TRAY_ICON_SIZE)
        pixmap.fill(Qt.transparent)
        return QIcon(pixmap)

    def start(self) -> None:
        self.tray.show()
        self.poll()
        self.timer.start()

    def _relabel_menu(self) -> None:
        """Put the catalogue's words on the tray menu.

        Without this the menu keeps whatever text() returned at construction —
        which, before the first state file has been read, is the key itself.
        """
        for key, action in getattr(self, "_menu_actions", {}).items():
            text = self.reader.text(key)
            if action.text() != text:
                action.setText(text)

    def poll(self) -> None:
        state = self.reader.read()
        self._relabel_menu()
        self._update_tray(state)
        self._sync_pet(state)
        if self.window.isVisible():
            self.window.refresh(state)

    def _sync_pet(self, state: dict | None) -> None:
        """Create, update or remove the pet to match the daemon's settings.

        Removed rather than hidden when it is switched off: a hidden always-on-
        top window still exists, and the setting is meant to mean "not there".
        """
        wanted = bool(((state or {}).get("config") or {}).get("floating_pet_enabled"))
        if not wanted:
            if self.pet is not None:
                self.pet.close()
                self.pet = None
            return

        if self.pet is None:
            self.pet = DesktopPet(
                on_activate=self.toggle_window,
                on_moved=self._remember_pet_position,
            )
            config_values = (state or {}).get("config") or {}
            self.pet.update_state(state)
            self.pet.place(
                int(config_values.get("floating_pet_x") or 80),
                int(config_values.get("floating_pet_y") or 80),
            )
            self.pet.show()
            return

        self.pet.update_state(state)
        # Anything that hid it — a compositor, a session change, a window
        # manager reacting to the popup — used to be permanent: the pet still
        # existed, so nothing here ever showed it again and it was gone until
        # the app restarted. Unconditional, because a window the platform hid
        # still reports itself visible.
        self._reassert_pet()

    def _remember_pet_position(self, x: int, y: int) -> None:
        # Through the daemon's own config, so the pet comes back where it was
        # left — including after a reboot.
        config.set_value(config.default_path(), "floating_pet_x", str(x))
        config.set_value(config.default_path(), "floating_pet_y", str(y))
        commands.enqueue("reload_config", {})

    def _update_tray(self, state: dict | None) -> None:
        panel = (state or {}).get("panel") or {}
        # The pinned species when there is one, else the companion: the daemon
        # has already resolved that, so this only has to draw it.
        path = panel.get("sprite_path") or None
        if path != self._sprite_path:
            self._sprite_path = path
            self._set_icon(path)
        self._apply_quality(state)
        self.tray.setToolTip(self._tooltip(state))

    def _apply_quality(self, state: dict | None) -> None:
        """Re-time every animated surface from one setting.

        The tray is rebuilt rather than re-timed: its frames are pre-rendered
        icons, so a new floor means a different set of them.
        """
        quality = quality_of((state or {}).get("config"))
        if self.pet is not None:
            self.pet.sprite.set_quality(quality)
        if quality != self._quality:
            self._quality = quality
            path, self._sprite_path = self._sprite_path, None
            self._set_icon(path)
            self._sprite_path = path

    def _set_icon(self, path: str | None) -> None:
        """Load the tray sprite and start it moving.

        The macOS menu bar animates: it composites the GIF's frames at icon
        size once and cycles them on a single timer. Qt has no animated QIcon,
        so this does the same thing by hand rather than settling for a still
        frame — which is what made the companion look like a static PNG
        everywhere except on the Mac.

        The frames are rendered once, at load, not per tick: a scale and an
        icon construction on every frame is the cost that makes an animated
        tray icon a bad idea in the first place.
        """
        self._icon_timer.stop()
        self._icon_frames = []
        self._icon_step = 0
        if not path:
            self.tray.setIcon(self._fallback_icon())
            return

        movie = QMovie(path)
        if not movie.isValid():
            pixmap = QPixmap(path)
            self.tray.setIcon(self._fallback_icon() if pixmap.isNull()
                              else QIcon(self._scaled(pixmap)))
            return

        count = min(movie.frameCount(), MAX_TRAY_FRAMES)
        if count <= 1:
            movie.jumpToFrame(0)
            self.tray.setIcon(QIcon(self._scaled(movie.currentPixmap())))
            return

        delays = []
        for index in range(count):
            movie.jumpToFrame(index)
            # Milliseconds on the wire, seconds here. Floored, because GIFs are
            # commonly authored with a 0ms delay meaning "as fast as possible".
            delays.append(max(0.02, movie.nextFrameDelay() / 1000))

        # The same rate cap the popup and the pet use: a frame costs a redraw
        # wherever it is drawn, and this one is drawn in the notification area.
        for index, hold in decimate(delays, frame_floor(self._quality)):
            movie.jumpToFrame(index)
            self._icon_frames.append((QIcon(self._scaled(movie.currentPixmap())), hold))
        if not self._icon_frames:
            return
        self._show_icon_frame()

    def _scaled(self, pixmap: QPixmap) -> QPixmap:
        return pixmap.scaled(TRAY_ICON_SIZE, TRAY_ICON_SIZE,
                             Qt.KeepAspectRatio, Qt.FastTransformation)

    def _show_icon_frame(self) -> None:
        icon, hold = self._icon_frames[self._icon_step]
        self.tray.setIcon(icon)
        self._icon_timer.start(max(20, round(hold * 1000)))

    def _advance_icon(self) -> None:
        if not self._icon_frames:
            return
        self._icon_step = (self._icon_step + 1) % len(self._icon_frames)
        self._show_icon_frame()

    def _tooltip(self, state: dict | None) -> str:
        panel = (state or {}).get("panel") or {}
        parts = [panel.get("tokens_text"), panel.get("cost_text")]
        parts += [window["text"] for window in panel.get("limit_windows") or []]
        text = " · ".join(part for part in parts if part)
        return text or "PokeTokenBar"

    def _on_activated(self, reason) -> None:
        # Middle-click and hover are not "open": on Windows a hover fires this
        # too, and a window that appears under the cursor is startling.
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.toggle_window()

    def toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.hide()
        else:
            self.window.refresh(self.reader.state)
            self.window.show()
            self.window.raise_()
            self.window.activateWindow()
        self._reassert_pet()

    def _reassert_pet(self) -> None:
        """Put the pet back on top after the popup has come or gone.

        Qt cannot see a window the platform hid on its own — isVisible() still
        reports true — so this does not check first. Showing a window that is
        already showing costs nothing.
        """
        if self.pet is None:
            return
        self.pet.show()
        self.pet.raise_()


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    # Closing the window leaves the tray icon behind rather than ending the
    # process, which is what a tray application is for.
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("PokeTokenBar")

    tray = TrayApp(app)
    tray.start()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
