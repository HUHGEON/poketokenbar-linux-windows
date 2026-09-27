"""Starting at login.

The macOS app registers a login item; neither Linux nor Windows has one, and
they do not agree with each other. What both have is a folder, so the whole
feature is one file in one place — which also makes every part of it checkable
from any platform.
"""

from pathlib import Path

import pytest

from poketokenbar import autostart, config


def test_the_setting_exists_so_the_control_does_something():
    """config.load drops a key it has no default for, so the switch would flip
    and change nothing."""
    assert "launch_at_login" in config.DEFAULTS


# MARK: where the entry goes


def test_linux_uses_the_xdg_autostart_directory():
    """Read at login by GNOME, KDE and every other freedesktop session."""
    path = autostart.entry_path(
        Path("/home/u"), {"XDG_CONFIG_HOME": "/home/u/.config"}, "linux")
    assert path == Path("/home/u/.config/autostart/poketokenbar.desktop")


def test_windows_uses_the_startup_folder():
    path = autostart.entry_path(
        Path("C:/Users/u"), {"APPDATA": "C:/Users/u/AppData/Roaming"}, "win32")
    assert path.parent.name == "Startup"
    assert path.name.endswith(".cmd")


def test_no_step_needs_an_administrator():
    """Every path is inside the user's own profile, so switching this on never
    raises a prompt."""
    windows = autostart.entry_path(
        Path("C:/Users/u"), {"APPDATA": "C:/Users/u/AppData/Roaming"}, "win32")
    assert "Program Files" not in str(windows)


# MARK: what it starts


@pytest.mark.parametrize("system", ["linux", "win32"])
def test_it_starts_both_halves(system):
    """A daemon with no window and a window with no daemon are each a broken
    install."""
    text = autostart.contents(system, "py")
    assert "poketokenbar.daemon" in text
    assert "poketokenbar.ui.app" in text


def test_the_modules_it_names_exist():
    """A rename on the Python side is invisible to a string that hardcodes the
    old name: the entry still runs and simply does nothing."""
    root = Path(__file__).resolve().parent.parent
    for module in autostart.MODULES:
        target = root.joinpath(*module.split("."))
        assert target.with_suffix(".py").is_file() or (target / "__init__.py").is_file()


def test_the_linux_entry_does_not_wait_for_the_daemon_to_exit():
    """The daemon never exits, so chaining the two with && starts the daemon
    and then waits forever for a window that never appears."""
    text = autostart.contents("linux", "py")
    assert "&&" not in text
    assert "poketokenbar.daemon &" in text


def test_the_linux_entry_is_a_desktop_file_the_session_will_read():
    text = autostart.contents("linux", "py")
    assert text.startswith("[Desktop Entry]")
    assert "Type=Application" in text
    assert "X-GNOME-Autostart-enabled=true" in text


def test_the_windows_entry_does_not_block_on_the_first_command():
    """Without `start` the batch file runs the daemon and never reaches the
    second line."""
    text = autostart.contents("win32", "py")
    assert text.count("start ") == len(autostart.MODULES)
    assert text.startswith("@echo off")


# MARK: switching it on and off


def test_enabling_writes_the_entry_and_disabling_removes_it(tmp_path):
    target = tmp_path / "nested" / "entry.desktop"
    assert not autostart.is_enabled(target)

    autostart.enable(target, "linux", "py")
    assert autostart.is_enabled(target)
    assert "poketokenbar.daemon" in target.read_text(encoding="utf-8")

    autostart.disable(target)
    assert not autostart.is_enabled(target)


def test_disabling_something_already_off_is_not_an_error(tmp_path):
    """A checkbox has no way to report one."""
    autostart.disable(tmp_path / "never-existed")


def test_apply_makes_the_entry_match_the_setting(tmp_path):
    target = tmp_path / "entry.desktop"
    autostart.apply(True, target)
    assert target.is_file()
    autostart.apply(False, target)
    assert not target.exists()
