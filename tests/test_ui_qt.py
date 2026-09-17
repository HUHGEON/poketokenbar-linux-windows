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

import math
import os
import sys

import pytest

pytest.importorskip("PySide6", reason="the Qt front end is optional")

# Must be set before QApplication exists, and QApplication is process-wide.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

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


def keep(widget):
    """Hold a Qt object for the life of the process. See above."""
    sys._poketokenbar_qt[1].append(widget)
    return widget

from poketokenbar.ui import panels  # noqa: E402
from poketokenbar.ui.app import TrayApp, Window  # noqa: E402
from poketokenbar.ui.reader import StateReader  # noqa: E402
from poketokenbar.ui.widgets import Sprite, level_colour, meter  # noqa: E402

from test_extension_contract import full_payload  # noqa: E402


@pytest.fixture(scope="session")
def qt_app():
    """The one QApplication; Qt allows exactly one per process."""
    return _APPLICATION


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


@pytest.mark.parametrize("name", PANEL_NAMES)
def test_every_panel_renders_a_full_payload(qt_app, reader, payload, name):
    window = keep(Window(reader))
    panel = window.panels[name]
    panel.update(payload)
    assert panel.layout_.count() > 0, f"{name} produced no widgets"


@pytest.mark.parametrize("name", PANEL_NAMES)
def test_every_panel_survives_an_empty_state(qt_app, name):
    """The state before the daemon has ever run, which is what a fresh install
    sees. A front end that raises here never shows anything at all."""
    empty = StateReader()
    window = keep(Window(empty))
    window.panels[name].update(None)
    window.panels[name].update({})


@pytest.mark.parametrize("name", PANEL_NAMES)
def test_updating_twice_does_not_double_the_contents(qt_app, reader, payload, name):
    """A widget removed from a layout is still parented and still painted until
    Qt collects it, so a rebuild without an explicit delete shows both."""
    window = keep(Window(reader))
    panel = window.panels[name]
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
    window.tabs.setCurrentIndex(0)
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


def test_the_tray_menu_offers_open_refresh_and_quit(qt_app):
    tray = keep(TrayApp(qt_app, StateReader()))
    labels = [action.text() for action in tray.tray.contextMenu().actions()]
    assert labels[0] == "Open"
    assert "Refresh" in labels
    assert "Quit" in labels


def test_polling_an_absent_state_file_does_not_raise(qt_app, tmp_path):
    """The normal state right after install."""
    subject = StateReader(path=tmp_path / "absent.json")
    tray = keep(TrayApp(qt_app, subject))
    tray.poll()
    assert subject.error


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

    soon = (datetime.now(timezone.utc) + timedelta(hours=2, minutes=15)).isoformat()
    assert panels.resets_in(soon, lambda k: k) in ("2h 15m", "2h 14m")

    later = (datetime.now(timezone.utc) + timedelta(days=3, hours=4)).isoformat()
    assert panels.resets_in(later, lambda k: k).startswith("3d ")


def test_a_past_reset_says_so():
    assert panels.resets_in("2020-01-01T00:00:00Z", lambda k: k) == "resetting_now"


def test_an_unparseable_reset_is_blank_not_an_error():
    for value in (None, "", "not a date", 12345):
        assert panels.resets_in(value, lambda k: k) == ""


def test_ago_reads_as_english():
    assert panels.ago(5) == "just now"
    assert panels.ago(600) == "10 min ago"
    assert panels.ago(None) == ""


# MARK: settings coverage


def test_the_settings_panel_offers_every_daemon_setting():
    """A setting nobody can change may as well not exist."""
    from poketokenbar import config

    offered = {key for key, *_ in panels.SettingsPanel.TOGGLES}
    offered |= {key for key, *_ in panels.SettingsPanel.SPINS}
    offered |= {key for key, *_ in panels.SettingsPanel.CHOICES}
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
    assert not offered - set(config.DEFAULTS)


def test_the_language_choice_matches_the_daemon_catalogue():
    from poketokenbar import l10n

    choices = dict((key, options) for key, _label, options in panels.SettingsPanel.CHOICES)
    assert list(choices["language"]) == list(l10n.LANGUAGES)


def test_tab_labels_arrive_with_the_catalogue(qt_app, payload):
    """The tabs are created before the first successful read, when `text()` still
    returns the key — so without a re-label they read "home", "shop", "bag" in
    lower case forever, and a language change never reaches them.
    """
    subject = StateReader()
    window = keep(Window(subject))
    assert window.tabs.tabText(0) == "home", "no catalogue yet, so the key stands in"

    subject.state = payload
    window.refresh(payload)
    assert window.tabs.tabText(0) == payload["strings"]["home"]
    assert window.tabs.tabText(0) != "home"


def test_tab_labels_follow_a_language_change(qt_app, payload):
    """The daemon resolves every string, so switching language must land on the
    next poll without anything being rebuilt."""
    from poketokenbar import l10n

    subject = StateReader()
    subject.state = payload
    window = keep(Window(subject))
    window.refresh(payload)
    english = window.tabs.tabText(0)

    subject.state = dict(payload, strings=l10n.catalogue("ko"))
    window.refresh(subject.state)
    assert window.tabs.tabText(0) != english
    assert window.tabs.tabText(0) == l10n.catalogue("ko")["home"]


def test_the_settings_tab_keeps_its_own_name(qt_app, payload):
    """It is the extension's own word, not one the daemon ships."""
    subject = StateReader()
    subject.state = payload
    window = keep(Window(subject))
    window.refresh(payload)
    assert window.tabs.tabText(window.tabs.count() - 1) == "Settings"


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


def test_the_two_front_ends_agree_on_the_name_for_off():
    """Both read the same `animation_quality` out of the same config file, so a
    front end spelling it differently would silently animate anyway."""
    import re
    from pathlib import Path

    from poketokenbar.ui.widgets import ANIMATION_OFF

    source = (
        Path(__file__).resolve().parent.parent
        / "gnome-extension" / "poketokenbar@huhgeon.github.io" / "lib" / "framecap.js"
    ).read_text(encoding="utf-8")
    js = re.search(r"ANIMATION_OFF = '([^']+)'", source).group(1)
    assert js == ANIMATION_OFF


def test_switching_animation_off_collapses_a_loop_into_one_frame():
    """One frame is what makes it free: `_show_step` only arms the timer when
    the schedule has more than one, so a still sprite costs no redraws."""
    from poketokenbar.ui.widgets import ANIMATION_OFF, decimate, frame_floor

    schedule = decimate([0.05] * 4, frame_floor(ANIMATION_OFF))
    assert len(schedule) == 1
    index, hold = schedule[0]
    assert index == 0, "the still is the frame the sprite opens on"
    assert abs(hold - 0.2) < 1e-9, "one loop still lasts as long as the source"


def test_off_is_not_one_of_the_presets():
    """It is the absence of a frame rate, not a slower one. Folding it into the
    table would quietly break "the default is the cheapest preset"."""
    from poketokenbar.ui.widgets import ANIMATION_OFF, FRAME_FLOORS, frame_floor

    assert ANIMATION_OFF not in FRAME_FLOORS
    assert frame_floor(ANIMATION_OFF) == math.inf


def test_a_still_sprite_arms_no_timer(qt_app):
    """The whole point of the setting: not the movement it hides but the
    redraws it stops."""
    from poketokenbar.ui.widgets import ANIMATION_OFF, Sprite

    sprite = Sprite(size=48)
    sprite._schedule = [(0, 2.5)]
    sprite._step = 0
    sprite._quality = ANIMATION_OFF
    sprite._movie = _StubMovie()

    sprite._show_step()

    assert not sprite._timer.isActive()


class _StubMovie:
    """Just enough QMovie for `_show_step`; the real one needs a decoded file."""

    def __init__(self):
        self.jumped = []

    def jumpToFrame(self, index):
        self.jumped.append(index)


# MARK: save transfer


def test_the_tray_menu_offers_save_transfer(qt_app):
    """Handled by the daemon all along, and reachable only from poketokenctl —
    which is not where anyone looks to move their Pokedex."""
    tray = keep(TrayApp(qt_app, StateReader()))
    labels = [action.text() for action in tray.tray.contextMenu().actions()]
    assert "Export save" in labels
    assert "Import save" in labels


def test_the_save_path_is_predictable(qt_app):
    tray = keep(TrayApp(qt_app, StateReader()))
    assert tray.save_path().name == "poketokenbar-save.json"
