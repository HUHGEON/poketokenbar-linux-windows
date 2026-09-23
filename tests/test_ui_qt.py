"""The Qt front end, actually constructed and fed a real payload.

Qt runs offscreen, so unlike the GNOME extension this one can be built and
exercised here: every panel is instantiated, handed the output of a real
`state.build`, and asked to lay itself out. That does not prove it looks right,
but it does prove every widget constructs, every field it reads exists, and no
code path raises on the shapes the daemon actually emits.

The empty-state cases matter as much as the full ones. Most people install this
before the daemon has ever written a file, and a front end that raises on
`None` is one that never gets as far as showing anything.
"""

import os
import sys

import pytest

pytest.importorskip("PySide6", reason="the Qt front end is optional")

# Must be set before QApplication exists, and QApplication is process-wide.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect, QSize, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QGridLayout, QWidget  # noqa: E402

# Parked on `sys`, not in a module global or a fixture.
#
# Qt segfaults if the QApplication is destroyed while widgets and their timers
# are still alive, and at interpreter shutdown module globals are cleared in an
# order nothing here controls. `sys` outlives them, so the application is the
# last thing to go. The crash this avoids happens after every test has passed,
# which makes it invisible in the report and fatal to the exit code.
#
# The widgets are parked with it for the same reason: a TrayApp created in a
# test is not destroyed by the test, and Qt has to see them go first.
_APPLICATION = QApplication.instance() or QApplication([])
sys._poketokenbar_qt = (_APPLICATION, [])


def _page(window, name):
    """The panel behind a page name — settings is not one of the tabs."""
    return window.settings if name == "settings" else window.panels[name]


def _tab_text(window, key: str) -> str:
    return window.tabs._buttons[key].text()


def keep(widget):
    """Hold a Qt object for the life of the process. See above."""
    sys._poketokenbar_qt[1].append(widget)
    return widget

from poketokenbar.ui import panels  # noqa: E402
from poketokenbar.ui.app import TrayApp, Window, popover_position  # noqa: E402
from poketokenbar.ui.reader import StateReader  # noqa: E402
from poketokenbar.ui.widgets import Sprite, level_colour, meter  # noqa: E402

from test_extension_contract import full_payload  # noqa: E402


@pytest.fixture(scope="module")
def payload():
    return full_payload()


@pytest.fixture
def reader(payload):
    subject = StateReader()
    subject.state = payload
    return subject


# MARK: panels


PANEL_NAMES = ("home", "shop", "bag", "collection", "settings")


def test_pokedex_cards_fit_the_fixed_width_popover(qt_app, reader, payload):
    """The card header has three controls, so a fourth column is clipped by
    the 400px Windows popover instead of becoming narrower."""
    data = dict(payload, dex=payload["dex"] * 3)
    panel = keep(panels.CollectionPanel(reader))
    panel.update(data)
    grids = [
        child.layout() for child in panel.body.findChildren(QWidget)
        if isinstance(child.layout(), QGridLayout)
    ]
    assert len(grids) == 1
    grid = grids[0]
    positions = [grid.getItemPosition(index)[:2] for index in range(grid.count())]
    assert all(column < 3 for _row, column in positions)
    assert positions[3] == (1, 0)
    assert [grid.columnStretch(column) for column in range(3)] == [1, 1, 1]


@pytest.mark.parametrize("plan,status,multiplier", [
    ("plus", "detected", 1), ("go", "detected", 1),
    ("pro", "detected", 5), (None, "unavailable", 5),
    (None, "checking", 1),
])
def test_plan_display_is_read_only(qt_app, reader, payload, plan, status, multiplier, monkeypatch):
    from copy import deepcopy
    from PySide6.QtWidgets import QComboBox
    from poketokenbar.ui import panels

    data = deepcopy(payload)
    data.setdefault("settings", {})["plan"] = {
        "detected": plan, "status": status, "multiplier": multiplier,
    }
    written = []
    monkeypatch.setattr(panels.commands, "enqueue", lambda *args, **kwargs: written.append(args))
    window = keep(Window(reader))
    window.settings.update(data)
    control = window.settings.findChild(QComboBox, "detected_plan")
    assert control is not None and not control.isEnabled()
    assert control.currentData() == (plan or "")
    # Even programmatic selection has no connected write handler.
    control.setCurrentIndex((control.currentIndex() + 1) % control.count())
    assert written == []


def test_difficulty_sliders_are_saved_together(qt_app, reader, payload, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QPushButton, QSlider
    from poketokenbar import config

    path = tmp_path / "config.json"
    monkeypatch.setattr(config, "default_path", lambda: path)
    queued = []
    monkeypatch.setattr(panels.commands, "enqueue", lambda *args: queued.append(args))
    window = keep(Window(reader))
    window.settings.update(payload)
    growth = window.settings.findChild(QSlider, "growth_difficulty")
    save = window.settings.findChild(QPushButton, "save_difficulty")
    assert growth is not None and save is not None and save.isHidden()

    growth.setValue(0)
    assert not save.isHidden()
    save.click()

    values = config.load(path)
    assert values["growth_difficulty"] == 0.1
    assert values["shop_difficulty"] == 1.0
    assert queued == [("reload_config", {})]


@pytest.mark.parametrize("name", PANEL_NAMES)
def test_every_panel_renders_a_full_payload(qt_app, reader, payload, name):
    window = keep(Window(reader))
    panel = _page(window, name)
    panel.update(payload)
    assert panel.layout_.count() > 0, f"{name} produced no widgets"


@pytest.mark.parametrize("name", PANEL_NAMES)
def test_every_panel_survives_an_empty_state(qt_app, name):
    """The state before the daemon has ever run, which is what a fresh install
    sees. A front end that raises here never shows anything at all."""
    empty = StateReader()
    window = keep(Window(empty))
    _page(window, name).update(None)
    _page(window, name).update({})


@pytest.mark.parametrize("name", PANEL_NAMES)
def test_updating_twice_does_not_double_the_contents(qt_app, reader, payload, name):
    """A widget removed from a layout is still parented and still painted until
    Qt collects it, so a rebuild without an explicit delete shows both."""
    window = keep(Window(reader))
    panel = _page(window, name)
    panel.update(payload)
    first = panel.layout_.count()
    panel.update(payload)
    assert panel.layout_.count() == first


def test_home_shows_the_companion_not_the_pinned_species(qt_app, payload):
    """Pinning changes the tray icon; hiding the companion in Home would make
    its progress unreachable.

    The two paths are set apart explicitly: the shared fixture has no sprite
    store, so both come back empty and the assertion would hold either way.
    """
    pinned = dict(
        payload,
        companion=dict(
            payload["companion"],
            sprite_path="/cache/5-a.gif",
            panel_sprite_path="/cache/3-sha.gif",
        ),
    )
    subject = StateReader()
    subject.state = pinned
    window = keep(Window(subject))
    window.panels["home"].update(pinned)
    assert window.panels["home"].sprite._path == "/cache/5-a.gif"


# MARK: the window


def test_the_footer_reports_freshness(qt_app, reader, payload):
    window = keep(Window(reader))
    window.refresh(payload)
    assert "Updated" in window.footer.text()


def test_the_footer_reports_daemon_errors_before_freshness(qt_app, payload):
    subject = StateReader()
    subject.state = dict(payload, errors=["claude_code: boom"])
    window = keep(Window(subject))
    window.refresh(subject.state)
    assert "boom" in window.footer.text()


def test_the_footer_reports_a_stale_daemon(qt_app, payload):
    subject = StateReader()
    subject.state = dict(payload, updated_at=1.0)  # 1970
    window = keep(Window(subject))
    window.refresh(subject.state)
    assert window.footer.text() == subject.text("stale_warning")


def test_only_the_visible_tab_is_rebuilt(qt_app, reader, payload):
    """The others would throw their children away again before anyone saw them."""
    window = keep(Window(reader))
    window.show_tab("home")
    window.refresh(payload)
    assert window.panels["home"].layout_.count() > 0
    assert window.panels["shop"].layout_.count() == 0


# MARK: the tray


def test_the_tray_has_an_icon_before_the_first_sprite(qt_app):
    """Without one the tray entry is invisible and there is no way to open the
    window, which looks exactly like a crash."""
    tray = keep(TrayApp(qt_app, StateReader()))
    assert not tray.tray.icon().isNull()


def test_the_tooltip_carries_the_panel_numbers(qt_app, reader, payload):
    tray = keep(TrayApp(qt_app, reader))
    tray._update_tray(payload)
    tooltip = tray.tray.toolTip()
    assert payload["panel"]["tokens_text"] in tooltip
    for window in payload["panel"]["limit_windows"]:
        assert window["text"] in tooltip


def test_the_tooltip_falls_back_to_the_app_name(qt_app):
    tray = keep(TrayApp(qt_app, StateReader()))
    tray._update_tray(None)
    assert tray.tray.toolTip() == "PokeTokenBar"


def test_import_requires_confirmation_and_undo_is_in_the_tray(qt_app, reader, payload,
                                                               monkeypatch):
    transfer = {
        "exists": True, "error": "", "path": "/tmp/save.json",
        "exported_text": "2026-09-23", "dex_count": 2, "used_text": "10M",
        "current_dex_count": 4, "current_used_text": "20M",
        "goes_backwards": True, "can_undo": True,
    }
    reader.state = dict(payload, transfer=transfer)
    tray = keep(TrayApp(qt_app, reader))
    accepted = []
    queued = []
    monkeypatch.setattr(tray, "_ask_transfer",
                        lambda title, detail, key: accepted.append((title, detail, key)) or True)
    monkeypatch.setattr("poketokenbar.ui.app.commands.enqueue",
                        lambda name, args: queued.append((name, args)))

    tray._confirm_import()

    assert accepted and "20M" in accepted[0][1]
    assert queued == [("import", {"path": "/tmp/save.json"})]
    assert "undo_import" in tray._menu_actions


def test_the_tray_menu_offers_open_refresh_and_quit(qt_app, payload):
    subject = StateReader()
    subject.state = payload
    tray = keep(TrayApp(qt_app, subject))
    tray._relabel_menu()
    labels = [action.text() for action in tray.tray.contextMenu().actions()]
    assert labels[0] == payload["strings"]["open"]
    assert payload["strings"]["refresh"] in labels
    assert payload["strings"]["restart"] in labels
    assert payload["strings"]["quit"] in labels


def test_the_tray_menu_is_relabelled_once_the_catalogue_arrives(qt_app, payload):
    """A menu is built once and never rebuilt, so a menu labelled before the
    first read keeps the raw keys for the life of the process."""
    from poketokenbar import l10n

    subject = StateReader()
    tray = keep(TrayApp(qt_app, subject))
    assert tray._menu_actions["open"].text() == "open", "no catalogue yet"

    subject.state = dict(payload, strings=l10n.catalogue("ko"))
    tray._relabel_menu()
    assert tray._menu_actions["open"].text() == l10n.catalogue("ko")["open"]


def test_polling_an_absent_state_file_does_not_raise(qt_app, tmp_path):
    """The normal state right after install."""
    subject = StateReader(path=tmp_path / "absent.json")
    tray = keep(TrayApp(qt_app, subject))
    tray.poll()
    assert subject.error


def test_an_unchanged_state_skips_expensive_ui_updates(qt_app, payload, monkeypatch):
    """The UI ticks every two seconds; the daemon normally writes every two minutes."""
    subject = StateReader()
    subject.state = payload
    monkeypatch.setattr(subject, "read", lambda: subject.state)
    tray = keep(TrayApp(qt_app, subject))
    calls = {"menu": 0, "tray": 0, "pet": 0, "recover": 0}

    for name, key in (("_relabel_menu", "menu"), ("_update_tray", "tray"),
                      ("_sync_pet", "pet"), ("_reassert_pet", "recover")):
        monkeypatch.setattr(
            tray, name, lambda *args, key=key: calls.__setitem__(key, calls[key] + 1))

    tray.poll()
    tray.poll()

    assert calls == {"menu": 1, "tray": 1, "pet": 1, "recover": 1}


def test_reader_error_change_still_refreshes_the_ui(qt_app, payload, monkeypatch):
    subject = StateReader()
    subject.state = payload
    monkeypatch.setattr(subject, "read", lambda: subject.state)
    tray = keep(TrayApp(qt_app, subject))
    updates = []
    monkeypatch.setattr(tray, "_update_tray", lambda state: updates.append(state))

    tray.poll()
    subject.error = "state broke"
    tray.poll()

    assert len(updates) == 2


# MARK: widgets


def test_a_sprite_does_not_rebuild_for_the_same_path(qt_app, tmp_path):
    """Rebuilding the QMovie every poll restarts the animation from frame one,
    so the companion would stutter rather than loop."""
    sprite = keep(Sprite(32))
    sprite.set_path(None)
    assert sprite._path is None
    sprite.set_path(str(tmp_path / "missing.gif"))
    first = sprite._movie
    sprite.set_path(str(tmp_path / "missing.gif"))
    assert sprite._movie is first


def test_a_missing_sprite_file_leaves_the_label_blank(qt_app, tmp_path):
    sprite = keep(Sprite(32))
    sprite.set_path(str(tmp_path / "nope.gif"))
    assert sprite.pixmap().isNull()


def test_a_meter_clamps_past_full(qt_app):
    """A limit over 100% must read as full rather than wrapping."""
    assert meter(1.5).value() == 100
    assert meter(-1).value() == 0
    assert meter(0.42).value() == 42


def test_level_colours_are_stated_not_themed():
    """"Close to your limit" has to read as a warning in any theme."""
    assert level_colour("crit") != level_colour("ok")
    assert level_colour(None) == level_colour("ok")
    assert level_colour("nonsense") == level_colour("ok")


# MARK: formatting shared with the other front ends


def test_resets_in_counts_down_rather_than_printing_a_timestamp():
    """The minute is floored, as it is in the other front ends, so a moment
    short of 2h15m reads as 2h 14m. Asserting the exact minute would make this
    fail on the microseconds between building the input and reading it."""
    from datetime import datetime, timedelta, timezone

    from poketokenbar import l10n

    english = lambda key: l10n.t(key, "en")  # noqa: E731
    soon = (datetime.now(timezone.utc) + timedelta(hours=2, minutes=15)).isoformat()
    assert panels.resets_in(soon, english) in ("2h 15m", "2h 14m")

    later = (datetime.now(timezone.utc) + timedelta(days=3, hours=4)).isoformat()
    assert panels.resets_in(later, english).startswith("3d ")


def test_a_countdown_never_shows_more_than_two_units():
    """"6일 2시간", not "6일 2시간 13분 4초" — a full breakdown of a week-long
    window is noise, and it is what the popover shows."""
    from poketokenbar import l10n

    english = lambda key: l10n.t(key, "en")  # noqa: E731
    assert panels.duration(6 * 86400 + 2 * 3600 + 13 * 60 + 4, english) == "6d 2h"
    assert panels.duration(2 * 3600 + 36 * 60, english) == "2h 36m"
    assert panels.duration(26, english) == "26s"
    assert panels.duration(0, english) == "0s"


def test_a_past_reset_says_so():
    assert panels.resets_in("2020-01-01T00:00:00Z", lambda k: k) == "resetting_now"


def test_an_unparseable_reset_is_blank_not_an_error():
    for value in (None, "", "not a date", 12345):
        assert panels.resets_in(value, lambda k: k) == ""


def test_ago_is_resolved_through_the_catalogue():
    """Hardcoding it here is what left a Korean install reading English."""
    from poketokenbar import l10n

    korean = lambda key: l10n.t(key, "ko")  # noqa: E731
    assert panels.ago(5, korean) == l10n.t("updated_just_now", "ko")
    assert "10" in panels.ago(600, korean)
    assert panels.ago(None, korean) == ""


# MARK: settings coverage


def test_the_settings_panel_offers_every_daemon_setting():
    """A setting nobody can change may as well not exist."""
    from poketokenbar import config

    offered = {key for key, *_ in panels.SettingsPanel.TOGGLES}
    offered |= {key for key, *_ in panels.SettingsPanel.SPINS}
    offered |= {key for key, *_ in panels.SettingsPanel.CHOICES}
    offered |= {key for key, *_ in panels.SettingsPanel.DIFFICULTIES}
    not_for_a_form = {
        "floating_pet_x",       # set by dragging the pet
        "floating_pet_y",
        "custom_scan_roots",    # its own per-provider fields
    }
    missing = set(config.DEFAULTS) - offered - not_for_a_form
    assert not missing, f"settings with no control: {sorted(missing)}"


def test_every_settings_key_has_a_daemon_default():
    """config.load drops a key it has no default for, so a wrong name here is a
    control that changes nothing."""
    from poketokenbar import config

    offered = {key for key, *_ in panels.SettingsPanel.TOGGLES}
    offered |= {key for key, *_ in panels.SettingsPanel.SPINS}
    offered |= {key for key, *_ in panels.SettingsPanel.CHOICES}
    offered |= {key for key, *_ in panels.SettingsPanel.DIFFICULTIES}
    assert not offered - set(config.DEFAULTS)


def test_the_language_choice_matches_the_daemon_catalogue():
    from poketokenbar import l10n

    choices = {key: options for key, _label, options, _shown in panels.SettingsPanel.CHOICES}
    assert list(choices["language"]) == list(l10n.LANGUAGES)


def test_every_settings_label_is_a_catalogue_key():
    """A literal here is a label that never translates, which is exactly how the
    settings page ended up entirely in English."""
    from poketokenbar import l10n

    keys = {label for _key, label in panels.SettingsPanel.TOGGLES}
    keys |= {label for _key, label, *_ in panels.SettingsPanel.SPINS}
    keys |= {label for _key, label in panels.SettingsPanel.DIFFICULTIES}
    keys |= {label for _key, label, *_ in panels.SettingsPanel.CHOICES}
    for _key, _label, _options, shown in panels.SettingsPanel.CHOICES:
        if shown:
            keys |= set(shown)
    unknown = keys - set(l10n.STRINGS)
    assert not unknown, f"labels that are not catalogue keys: {sorted(unknown)}"


def test_tab_labels_arrive_with_the_catalogue(qt_app, payload):
    """The tabs are created before the first successful read, when `text()` still
    returns the key — so without a re-label they read "home", "shop", "bag" in
    lower case forever, and a language change never reaches them.
    """
    subject = StateReader()
    window = keep(Window(subject))
    assert _tab_text(window, "home") == "home", "no catalogue yet, so the key stands in"

    subject.state = payload
    window.refresh(payload)
    assert _tab_text(window, "home") == payload["strings"]["home"]
    assert _tab_text(window, "home") != "home"


def test_tab_labels_follow_a_language_change(qt_app, payload):
    """The daemon resolves every string, so switching language must land on the
    next poll without anything being rebuilt."""
    from poketokenbar import l10n

    subject = StateReader()
    subject.state = payload
    window = keep(Window(subject))
    window.refresh(payload)
    english = _tab_text(window, "home")

    subject.state = dict(payload, strings=l10n.catalogue("ko"))
    window.refresh(subject.state)
    assert _tab_text(window, "home") != english
    assert _tab_text(window, "home") == l10n.catalogue("ko")["home"]


def test_new_labels_fall_back_to_the_local_korean_catalogue(payload):
    """A newly installed UI may briefly read state from the old daemon."""
    from copy import deepcopy

    data = deepcopy(payload)
    data["config"]["language"] = "ko"
    data["strings"].pop("difficulty", None)
    data["strings"].pop("difficulty_growth", None)
    data["strings"].pop("difficulty_shop", None)
    subject = StateReader()
    subject.state = data

    assert subject.text("difficulty") == "난이도"
    assert subject.text("difficulty_growth") == "성장 난이도"
    assert subject.text("difficulty_shop") == "상점 가격 난이도"


def test_settings_is_a_page_not_a_fifth_tab(qt_app, payload):
    """The popover reaches it from the footer gear and leaves by a back button,
    so the four tabs stay the four things someone switches between."""
    subject = StateReader()
    subject.state = payload
    window = keep(Window(subject))
    window.refresh(payload)
    assert list(window.panels) == ["home", "shop", "bag", "collection"]

    window.show_settings()
    assert window.stack.currentWidget() is window.settings
    assert window.settings_bar.isVisibleTo(window)
    assert not window.tab_bar.isVisibleTo(window)

    window.show_tab("home")
    assert window.stack.currentWidget() is window.panels["home"]
    assert window.tab_bar.isVisibleTo(window)


def test_the_settings_header_is_translated_too(qt_app, payload):
    """It used to be the one label spelled out in English on purpose, which is
    what someone reading a Korean install saw first."""
    from poketokenbar import l10n

    subject = StateReader()
    subject.state = dict(payload, strings=l10n.catalogue("ko"))
    window = keep(Window(subject))
    window.refresh(subject.state)
    assert window.settings_title.text() == l10n.catalogue("ko")["settings"]
    assert window.back_label.text() == l10n.catalogue("ko")["back"]


# MARK: the desktop pet


def pet_state(payload, **config):
    return dict(payload, config={**payload.get("config", {}), **config})


def test_no_pet_until_the_setting_is_on(qt_app, payload):
    """Three settings for a pet that did not exist was worse than missing it:
    the switch flipped and nothing happened."""
    subject = StateReader()
    tray = keep(TrayApp(qt_app, subject))
    tray._sync_pet(pet_state(payload, floating_pet_enabled=False))
    assert tray.pet is None


def test_the_pet_appears_and_follows_the_panel(qt_app, payload):
    subject = StateReader()
    tray = keep(TrayApp(qt_app, subject))
    state = pet_state(
        payload, floating_pet_enabled=True, floating_pet_size=120,
        floating_pet_x=200, floating_pet_y=150,
    )
    state["panel"] = dict(state["panel"], sprite_path="/cache/3-sha.gif")
    tray._sync_pet(state)
    keep(tray.pet)

    assert tray.pet is not None
    assert tray.pet.width() == 120
    # It shows whatever the panel shows, so a pinned species appears here too.
    assert tray.pet.sprite._path == "/cache/3-sha.gif"


def test_turning_the_pet_off_removes_it(qt_app, payload):
    """Removed rather than hidden: a hidden always-on-top window still exists,
    and the setting is meant to mean "not there"."""
    subject = StateReader()
    tray = keep(TrayApp(qt_app, subject))
    tray._sync_pet(pet_state(payload, floating_pet_enabled=True))
    assert tray.pet is not None
    tray._sync_pet(pet_state(payload, floating_pet_enabled=False))
    assert tray.pet is None


def test_the_pet_is_frameless_and_stays_on_top(qt_app):
    from poketokenbar.ui.pet import DesktopPet

    pet = keep(DesktopPet())
    flags = pet.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    # An ornament, not a window to switch to.
    assert flags & Qt.Tool


def test_the_pet_clamps_to_the_screen(qt_app):
    """A position saved on a monitor that is gone would leave it invisible with
    no way to get it back."""
    from poketokenbar.ui.pet import DesktopPet

    pet = keep(DesktopPet())
    pet.place(-10_000, -10_000)
    assert pet.x() >= -1 and pet.y() >= -1
    pet.place(10_000_000, 10_000_000)
    assert pet.x() < 10_000_000


# MARK: animation quality


def test_the_frame_cap_keeps_the_loop_length(qt_app):
    """The rule a plausible implementation gets wrong: drop frames, never
    stretch them. Raising each to the floor keeps all 55 and turns a 2.75s loop
    into 22s."""
    from poketokenbar.ui.widgets import decimate

    delays = [0.05] * 55
    capped = decimate(delays, 0.4)
    assert abs(sum(hold for _index, hold in capped) - sum(delays)) < 1e-9
    assert len(capped) < len(delays)
    assert capped[0][0] == 0 and capped[1][0] == 8


def test_the_frame_cap_merges_a_short_tail(qt_app):
    from poketokenbar.ui.widgets import decimate

    capped = decimate([0.05, 0.05, 0.05], 0.1)
    assert len(capped) == 1
    assert abs(capped[0][1] - 0.15) < 1e-9


def test_no_quality_preset_disables_the_cap(qt_app):
    """Native frame rate keeps the machine awake, which is why "saver" is also
    the default."""
    from poketokenbar.ui.widgets import DEFAULT_QUALITY, FRAME_FLOORS, frame_floor

    assert all(floor > 0 for floor in FRAME_FLOORS.values())
    assert frame_floor(DEFAULT_QUALITY) == max(FRAME_FLOORS.values())
    assert frame_floor("nonsense") == FRAME_FLOORS[DEFAULT_QUALITY]


def test_the_two_front_ends_agree_on_the_presets():
    """A frame costs a redraw wherever it is drawn, and both front ends offer
    the same three names — they must mean the same rates."""
    import json
    import re
    from pathlib import Path

    from poketokenbar.ui.widgets import FRAME_FLOORS

    source = (
        Path(__file__).resolve().parent.parent
        / "gnome-extension" / "poketokenbar@huhgeon.github.io" / "lib" / "framecap.js"
    ).read_text(encoding="utf-8")
    block = re.search(r"FRAME_FLOORS = \{(.*?)\}", source, re.S).group(1)
    js = dict(
        (name, float(value))
        for name, value in re.findall(r"(\w+):\s*([\d.]+)", block)
    )
    assert js == FRAME_FLOORS


# MARK: save transfer


def test_the_tray_menu_offers_save_transfer(qt_app, payload):
    """Handled by the daemon all along, and reachable only from poketokenctl —
    which is not where anyone looks to move their Pokedex."""
    subject = StateReader()
    subject.state = payload
    tray = keep(TrayApp(qt_app, subject))
    tray._relabel_menu()
    labels = [action.text() for action in tray.tray.contextMenu().actions()]
    assert payload["strings"]["export_save"] in labels
    assert payload["strings"]["import_save"] in labels


def test_the_save_path_is_predictable(qt_app):
    tray = keep(TrayApp(qt_app, StateReader()))
    assert tray.save_path().name == "poketokenbar-save.json"


# MARK: the pet coming back
#
# It vanished when clicked on Windows: a tool window is owned by whichever
# window of the application was last active, so a pet that took activation
# became owned by the popup and went with it. The flags that stop that cannot
# be tested off Windows — macOS does not reproduce it, the unfixed version
# survives there too — but the recovery can be, and it does not depend on
# knowing what hid the window or why.


def test_the_pet_refuses_activation(qt_app):
    """The mechanism, stated as a property rather than as a behaviour: a pet
    that never becomes the active window is never owned by the popup."""
    from PySide6.QtCore import Qt

    from poketokenbar.ui.pet import DesktopPet

    pet = keep(DesktopPet())
    assert pet.windowFlags() & Qt.WindowDoesNotAcceptFocus
    assert pet.testAttribute(Qt.WA_ShowWithoutActivating)
    assert pet.focusPolicy() == Qt.NoFocus


def test_a_hidden_pet_is_back_on_the_next_poll(qt_app, payload):
    """Whatever hid it — a compositor, a session change, the platform
    reacting to the popup — it used to be permanent: the pet still existed, so
    nothing showed it again and it was gone until the app restarted."""
    subject = StateReader()
    subject.state = payload
    tray = keep(TrayApp(qt_app, subject))
    state = dict(payload, config=dict(payload["config"], floating_pet_enabled=True))
    tray._sync_pet(state)
    assert tray.pet is not None

    tray.pet.hide()
    assert not tray.pet.isVisible()

    tray._sync_pet(state)
    assert tray.pet.isVisible(), "the pet was left hidden"


def test_toggling_the_popup_puts_the_pet_back(qt_app, payload):
    """The moment it went missing, so recovery cannot wait for the next poll:
    two seconds of no pet after every click is the bug in slower form."""
    subject = StateReader()
    subject.state = payload
    tray = keep(TrayApp(qt_app, subject))
    tray._sync_pet(dict(payload, config=dict(payload["config"],
                                             floating_pet_enabled=True)))
    for _ in range(4):
        tray.pet.hide()
        tray.toggle_window()
        assert tray.pet.isVisible(), "closing or opening the popup lost the pet"


def test_bottom_right_tray_icon_anchors_popup_above_it():
    available = QRect(0, 0, 1920, 1040)
    tray_icon = QRect(1830, 1048, 24, 24)
    point = popover_position(tray_icon, available, QSize(400, 640))
    assert point.x() == 1454
    assert point.y() == 384


@pytest.mark.skipif(sys.platform != "win32", reason="Windows popover behavior")
def test_windows_popover_size_does_not_follow_page_content(payload):
    subject = StateReader()
    subject.state = payload
    window = keep(Window(subject))

    assert window.minimumSize() == QSize(400, 640)
    assert window.maximumSize() == QSize(400, 640)
    assert "border-radius: 18px" in window.styleSheet()


def test_footer_has_a_restart_button(reader):
    window = keep(Window(reader))
    restart = window.findChild(type(window.gear), "restart_app")

    assert restart is not None
    assert restart.toolTip() == reader.text("restart")


def test_popover_position_stays_inside_small_screen():
    available = QRect(100, 50, 800, 600)
    point = popover_position(QRect(), available, QSize(400, 640))
    assert point.x() >= available.left()
    assert point.y() == available.top()


def test_the_reassert_does_not_ask_whether_it_is_needed(qt_app, payload):
    """Qt cannot see a window the platform hid on its own — isVisible() still
    reports true — so a reassert guarded by that check would do nothing in the
    one case it exists for."""
    import inspect

    from poketokenbar.ui import app as app_module

    # The docstring says why it does not check, so only the code is scanned.
    source = inspect.getsource(app_module.TrayApp._reassert_pet)
    body = source[source.index('"""', source.index('"""') + 3) + 3:]
    assert "isVisible" not in body, "the reassert is guarded by a check that lies"
    assert "show()" in body
