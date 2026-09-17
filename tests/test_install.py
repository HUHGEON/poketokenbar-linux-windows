"""install.sh — the paths it copies, and the names it copies them under.

The script itself was run end to end in a container and does what it says. What
survives here are the parts that rot: a directory renamed in the repo, or a
uuid that stops matching, neither of which shows up until someone installs and
finds nothing enabled. Re-running pip and venv on every test run would buy
nothing those two checks do not already cover.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INSTALL = ROOT / "install.sh"
BASH = shutil.which("bash")


def script() -> str:
    return INSTALL.read_text(encoding="utf-8")


@pytest.mark.skipif(BASH is None, reason="bash is not installed")
def test_the_script_parses():
    result = subprocess.run([BASH, "-n", str(INSTALL)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(os.name == "nt", reason="NTFS carries no execute bit")
def test_it_is_executable():
    """Cloned and run as ./install.sh, a missing bit is the first thing anyone hits."""
    assert INSTALL.stat().st_mode & 0o111, "install.sh is not executable"


def test_the_extension_uuid_agrees_everywhere():
    """Shell will not load an extension whose directory and uuid differ, and
    install.sh copies by that name."""
    extension_dir = next((ROOT / "gnome-extension").iterdir())
    metadata = json.loads((extension_dir / "metadata.json").read_text(encoding="utf-8"))
    match = re.search(r'extension_uuid="([^"]+)"', script())
    assert match, "install.sh no longer names an extension uuid"
    assert match.group(1) == metadata["uuid"] == extension_dir.name


def test_every_source_path_it_copies_exists():
    """A directory renamed in the repo leaves the script copying nothing, and
    `cp -R` of a missing tree is the kind of failure people read past."""
    for relative in re.findall(r'"\$here/([^"]+)"', script()):
        # Skip the interpolated ones; those are covered by the uuid check.
        if "$" in relative:
            continue
        assert (ROOT / relative).exists(), f"install.sh copies missing path: {relative}"


def test_the_extension_tree_is_copied_by_its_uuid():
    assert '"$here/gnome-extension/$extension_uuid"' in script()


def test_every_desktop_is_handled():
    """The repo carries three front ends, so the script picks rather than
    assuming GNOME."""
    text = script()
    for name in ("install_gnome", "install_plasma", "install_qt"):
        assert name in text, f"{name} is not offered"
    assert "XDG_CURRENT_DESKTOP" in text


def test_an_unknown_desktop_gets_something_that_works():
    """XFCE, Cinnamon and the tiling compositors have no panel to extend and no
    plasmoid to load. Installing the Shell extension there leaves someone with
    nothing at all, which is what this used to do."""
    text = script()
    fallback = text.split("*KDE*")[1].split("esac")[0]
    assert "install_qt" in fallback
    assert "install_gnome" not in fallback


def test_the_tray_launcher_and_autostart_are_written():
    text = script()
    assert "poketokenbar.ui.app" in text, "the tray application is never started"
    assert "autostart" in text, "it would not come back after a reboot"


def test_a_missing_pyside_does_not_fail_the_install():
    """The daemon is the part that counts tokens; a front end that cannot be
    installed must not take it down with it."""
    text = script()
    qt = text.split("install_qt() {")[1].split("\n}")[0]
    assert "return 0" in qt
    assert "The daemon still works" in qt


def test_nothing_is_written_outside_home():
    """No step here needs root; a path outside $HOME would mean one does."""
    for path in re.findall(r'^\s*(?:mkdir -p|install -m\d+ [^\s]+)\s+"([^"]+)"', script(), re.M):
        assert path.startswith("$HOME") or path.startswith("$"), path


def test_the_service_step_can_be_skipped():
    """systemctl is unavailable in a container, and the install has to be
    testable without it."""
    assert "POKETOKENBAR_NO_SERVICE" in script()


def test_the_systemd_unit_matches_where_the_script_installs_the_app():
    """The unit hardcodes the venv and app paths; if the script moves either,
    the daemon starts and immediately fails to import itself.
    """
    unit = (ROOT / "systemd" / "poketokend.service").read_text(encoding="utf-8")
    text = script()
    assert 'app="$HOME/.local/share/poketokenbar/app"' in text
    assert 'venv="$HOME/.local/share/poketokenbar/venv"' in text
    assert "%h/.local/share/poketokenbar/venv/bin/python" in unit
    assert "%h/.local/share/poketokenbar/app" in unit


def test_each_install_puts_the_ui_in_a_new_directory_and_names_it():
    """extension.js loads main.js from the directory named in `current`. A new
    directory per install is what makes the running session load new code."""
    text = script()
    assert 'mv "$dest/lib" "$dest/$ui_dir"' in text
    assert '> "$dest/current"' in text
    assert re.search(r'ui_dir="lib-\$\(date [^)]*\)"', text)


def test_a_running_extension_is_reloaded_and_the_daemon_restarted():
    text = script()
    assert 'gnome-extensions disable "$extension_uuid" && gnome-extensions enable "$extension_uuid"' in text
    assert "systemctl --user restart poketokend.service" in text


def test_the_loader_accepts_the_directory_names_the_installer_writes():
    import subprocess

    loader = (ROOT / "gnome-extension" / "poketokenbar@huhgeon.github.io" / "extension.js").read_text()
    pattern = re.search(r"const UI_DIRECTORY = /(.*)/;", loader).group(1)
    stamp = subprocess.run(["date", "+%Y%m%d%H%M%S"], capture_output=True, text=True).stdout.strip()
    assert re.fullmatch(pattern.strip("^$"), f"lib-{stamp}")
    assert re.fullmatch(pattern.strip("^$"), "lib")
    assert not re.fullmatch(pattern.strip("^$"), "../elsewhere")

