"""The Windows installer scripts.

They cannot be run from here, but they can be parsed — PowerShell's own parser
runs on Linux — and the paths and module names they name can be checked against
the code they are supposed to start. Those are the two ways a script like this
fails: a syntax error, or a rename on the Python side that nothing tells it
about.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from poketokenbar import config, platform_paths, state

WINDOWS_DIR = Path(__file__).resolve().parent.parent / "packaging" / "windows"
INSTALL = WINDOWS_DIR / "install.ps1"
UNINSTALL = WINDOWS_DIR / "uninstall.ps1"

PWSH = shutil.which("pwsh") or shutil.which("powershell")

PARSE = (
    "$errs = $null;"
    "[System.Management.Automation.Language.Parser]::ParseFile("
    "'{path}', [ref]$null, [ref]$errs) | Out-Null;"
    "if ($errs.Count) {{ $errs | ForEach-Object {{ Write-Output $_ }}; exit 1 }}"
)


def both_scripts():
    return [INSTALL, UNINSTALL]


@pytest.mark.parametrize("path", both_scripts(), ids=lambda p: p.name)
def test_the_scripts_exist(path):
    assert path.is_file(), f"missing {path}"
    assert path.read_text(encoding="utf-8").strip()


@pytest.mark.skipif(PWSH is None, reason="PowerShell is not installed")
@pytest.mark.parametrize("path", both_scripts(), ids=lambda p: p.name)
def test_each_script_parses(path):
    result = subprocess.run(
        [PWSH, "-NoProfile", "-Command", PARSE.format(path=path)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"{path.name} does not parse:\n{result.stdout}"


# MARK: what it starts


def test_it_launches_the_modules_that_actually_exist():
    """A rename on the Python side is invisible to a script that hardcodes the
    old module name — the shortcut still exists and simply does nothing."""
    script = INSTALL.read_text(encoding="utf-8")
    for module in re.findall(r"-m (poketokenbar[\w.]*)", script):
        parts = module.split(".")
        target = Path(__file__).resolve().parent.parent.joinpath(*parts)
        assert target.with_suffix(".py").is_file() or (target / "__init__.py").is_file(), (
            f"install.ps1 starts {module}, which does not exist"
        )


def test_it_starts_both_halves():
    """The daemon produces the numbers and the tray shows them; one without the
    other is an install that looks broken."""
    script = INSTALL.read_text(encoding="utf-8")
    assert "poketokenbar.daemon" in script
    assert "poketokenbar.ui.app" in script


def test_it_uses_pythonw_so_no_console_window_appears():
    """python.exe brings a console host with it, so a tray app started at login
    would flash a black window on every boot."""
    script = INSTALL.read_text(encoding="utf-8")
    assert "pythonw.exe" in script
    assert "Scripts\\python.exe" in script, "the plain interpreter is still needed for pip"


def test_it_installs_the_qt_front_end():
    """Without PySide6 the tray app cannot start at all, and the failure is
    silent because nothing has a console."""
    assert "PySide6" in INSTALL.read_text(encoding="utf-8")


# MARK: where it puts things


def test_the_install_root_is_under_the_user_profile():
    """No step here needs an administrator; a path outside the profile would
    mean one does."""
    script = INSTALL.read_text(encoding="utf-8")
    assert "$env:LOCALAPPDATA" in script
    assert "C:\\Program Files" not in script


def test_it_names_the_state_file_where_the_daemon_writes_it():
    """The closing message tells someone where to look; if it names the wrong
    directory the first thing they check will be empty."""
    script = INSTALL.read_text(encoding="utf-8")
    windows_state = platform_paths.state_base(
        home=Path("C:/Users/u"), env={"APPDATA": "C:/Users/u/AppData/Roaming"},
        system="win32")
    assert windows_state.name == "Roaming"
    assert "APPDATA" in script and "poketokenbar" in script


def test_the_uninstaller_leaves_the_save_alone():
    """A Pokedex should not vanish because someone removed the viewer."""
    script = UNINSTALL.read_text(encoding="utf-8")
    assert "LOCALAPPDATA" in script, "it removes the install root"
    # The save lives in APPDATA, and the script must say so rather than delete it.
    assert "delete it by hand" in script.lower() or "by hand" in script.lower()
    assert "Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $env:APPDATA" not in script


def test_the_daemon_and_the_tray_agree_on_the_state_path():
    """Both are started by the same script and must read and write one file."""
    from poketokenbar.ui.reader import StateReader

    assert StateReader().path == state.default_path()


def test_config_and_state_share_a_root_on_windows():
    """Windows has no equivalent of the XDG split, so both sit in Roaming; a
    mismatch would leave the tray editing settings the daemon never reads."""
    home, env = Path("C:/Users/u"), {"APPDATA": "C:/Users/u/AppData/Roaming"}
    assert (
        platform_paths.config_base(home, env, "win32")
        == platform_paths.state_base(home, env, "win32")
    )
    assert config.DEFAULTS  # the module the tray writes through


# MARK: the generated VBScript


def test_the_launcher_is_built_by_substitution_not_interpolation():
    """The first release shipped a .vbs one quote short.

    VBScript escapes a quote inside a string by doubling it, so the Run line
    needs three quotes then two. Interpolating a path into that is how one got
    lost, and the result parses fine as PowerShell while every launch dies with
    "Expected end of statement" — which no amount of parsing the installer
    would have caught.
    """
    script = INSTALL.read_text(encoding="utf-8")
    assert "@'" in script, "the template must be a single-quoted here-string"
    assert '"""__PYW__"" -m __MODULE__"' in script, (
        "the Run line no longer has the doubled quotes VBScript needs"
    )
    # The call is split across lines for readability, so the dot is not adjacent.
    assert "Replace('__PYW__'" in script


def test_the_template_has_balanced_vbscript_quoting():
    """Counted rather than eyeballed: every line of the template must have an
    even number of quotes, or the string never closes."""
    script = INSTALL.read_text(encoding="utf-8")
    template = script.split("$vbsTemplate = @'")[1].split("'@")[0]
    for line in template.strip().splitlines():
        assert line.count('"') % 2 == 0, f"unbalanced quotes: {line}"


def test_the_launcher_starts_both_halves():
    script = INSTALL.read_text(encoding="utf-8")
    assert "'poketokenbar.daemon'" in script
    assert "'poketokenbar.ui.app'" in script


def test_ci_actually_runs_the_installer():
    """Parsing it is not running it, and the quoting bug lived entirely in the
    gap between the two."""
    workflow = (
        Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    assert "./packaging/windows/install.ps1" in workflow, (
        "CI parses the installer but never executes it"
    )
    assert "cscript" in workflow, "the generated VBScript is never compiled"
    assert "./packaging/windows/uninstall.ps1" in workflow


# MARK: shortcuts


def test_there_is_a_way_to_start_it_without_a_terminal():
    """Quitting the tray used to leave no way back but opening PowerShell and
    running the installer again."""
    script = INSTALL.read_text(encoding="utf-8")
    assert "GetFolderPath('Programs')" in script, "no Start Menu entry"
    assert "GetFolderPath('Desktop')" in script, "no desktop shortcut"
    assert "poketokenbar.vbs" in script


def test_the_shortcuts_wear_the_app_icon():
    script = INSTALL.read_text(encoding="utf-8")
    assert "IconLocation" in script
    assert "poketokenbar.ico" in script


def test_the_icon_is_copied_into_the_install():
    """Only the package directory is copied, so an icon referenced where it
    sits in the repo is one the shortcuts lose the moment the repo is deleted
    — and a shortcut with a missing icon quietly wears the interpreter's."""
    script = INSTALL.read_text(encoding="utf-8")
    assert "Copy-Item -Force (Join-Path $PSScriptRoot 'poketokenbar.ico')" in script
    assert "Join-Path $app 'packaging" not in script, (
        "the icon is referenced where it is not installed")


def test_the_icon_is_a_real_icon_file():
    """Committed rather than generated at install time, so installing needs no
    network for it — and a corrupt one would be a blank shortcut nobody
    notices until they look at their desktop."""
    import struct

    icon = WINDOWS_DIR / "poketokenbar.ico"
    assert icon.is_file(), "the icon is missing"
    raw = icon.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", raw[:6])
    assert (reserved, kind) == (0, 1), "not an icon directory"
    assert count >= 4, "too few sizes; Windows picks badly from a short list"
    for index in range(count):
        entry = raw[6 + 16 * index:22 + 16 * index]
        width, height, _c, _r, _p, _bpp, size, offset = struct.unpack("<BBBBHHII", entry)
        blob = raw[offset:offset + size]
        assert blob[:8] == b"\x89PNG\r\n\x1a\n", f"entry {index} is not a PNG"
        png_width, png_height = struct.unpack(">II", blob[16:24])
        # 0 in the directory means 256; anything else must match the image.
        expected = width or 256
        assert (png_width, png_height) == (expected, expected)
    assert any(raw[6 + 16 * i] in (16, 32) for i in range(count)), (
        "no small size, so the taskbar would scale a large one")


def test_the_generator_is_kept_with_the_icon():
    """So the next person can rebuild it rather than guessing how it was made."""
    generator = WINDOWS_DIR.parent.parent / "tools" / "make_icon.py"
    assert generator.is_file()
    assert "poketokenbar.ico" in generator.read_text(encoding="utf-8")


def test_the_uninstaller_takes_the_shortcuts_with_it():
    script = UNINSTALL.read_text(encoding="utf-8")
    assert "GetFolderPath('Programs')" in script
    assert "GetFolderPath('Desktop')" in script


def test_the_windows_check_exercises_the_pet():
    """The pet vanishing when clicked was a Windows-only windowing behaviour,
    so the click path has to run on a Windows runner."""
    check = WINDOWS_DIR.parent.parent / "tools" / "windows_check_tray.py"
    source = check.read_text(encoding="utf-8")
    assert "WindowDoesNotAcceptFocus" in source
    assert "toggle_window()" in source


def test_the_windows_checks_print_nothing_the_console_cannot_encode():
    """The Windows console is cp1252. A single emoji in a print() takes the
    whole check down with a UnicodeEncodeError, which is a red build over a
    log line."""
    tools = (WINDOWS_DIR.parent.parent / "tools").glob("windows_check_*.py")
    for path in tools:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "print(" not in line:
                continue
            try:
                line.encode("cp1252")
            except UnicodeEncodeError:
                raise AssertionError(f"{path.name}:{number} prints non-cp1252 text")
