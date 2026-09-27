"""Start at login, on each platform's own terms.

The macOS app registers a login item through SMAppService; neither Linux nor
Windows has that, and the two of them do not agree with each other either. What
they do share is a folder: drop a file in it and the session starts the command,
remove the file and it does not. So this is a two-line contract — `enable`,
`disable` — over a path that differs per platform.

Nothing here shells out to `systemctl` or edits the registry. Both would need a
privilege or a running user bus that a tray application cannot assume, and both
fail in ways a checkbox cannot report.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from . import platform_paths

# What the entry starts. Both halves, because a daemon with no window and a
# window with no daemon are each a broken install.
MODULES = ("poketokenbar.daemon", "poketokenbar.ui.app")

DESKTOP_NAME = "poketokenbar.desktop"
SHORTCUT_NAME = "PokeTokenBar.cmd"


def entry_path(home: Path | None = None, env: dict | None = None,
               system: str | None = None) -> Path:
    """Where the login entry lives.

    Windows uses the Start-up folder under Roaming; everything else uses the
    XDG autostart directory, which GNOME, KDE and every other freedesktop
    session read at login.
    """
    home = home or Path.home()
    env = os.environ if env is None else env
    system = system or sys.platform
    if system.startswith("win"):
        roaming = env.get("APPDATA") or str(home / "AppData" / "Roaming")
        return (Path(roaming) / "Microsoft" / "Windows" / "Start Menu"
                / "Programs" / "Startup" / SHORTCUT_NAME)
    return platform_paths.config_base(home, env, system) / "autostart" / DESKTOP_NAME


def _interpreter(system: str) -> str:
    """The interpreter to relaunch with.

    pythonw.exe on Windows: python.exe brings a console host with it, so a tray
    app started at login would flash a black window on every boot. The same
    substitution the installer makes.
    """
    executable = sys.executable or "python3"
    if system.startswith("win"):
        candidate = Path(executable).with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return executable


def contents(system: str | None = None, interpreter: str | None = None) -> str:
    """The file's text, as a value — so a test can read it without a login."""
    system = system or sys.platform
    python = interpreter or _interpreter(system)
    if system.startswith("win"):
        lines = ["@echo off"]
        # `start ""` so the shell does not wait: the second line would never run
        # otherwise, and the window would never appear.
        lines += [f'start "" "{python}" -m {module}' for module in MODULES]
        return "\r\n".join(lines) + "\r\n"

    # Backgrounded, not chained: the daemon never exits, so "daemon && ui"
    # would start the daemon and then wait forever for a window that never
    # appears. The last one takes over the shell so no stray sh lingers.
    head = " ".join(f'"{python}" -m {module} &' for module in MODULES[:-1])
    command = f'{head} exec "{python}" -m {MODULES[-1]}'.strip()
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=PokeTokenBar\n"
        f"Exec=sh -c '{command}'\n"
        "X-GNOME-Autostart-enabled=true\n"
        "Terminal=false\n"
    )


def is_enabled(path: Path | None = None) -> bool:
    return (path or entry_path()).is_file()


def enable(path: Path | None = None, system: str | None = None,
           interpreter: str | None = None) -> Path:
    target = path or entry_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents(system, interpreter), encoding="utf-8")
    if not (system or sys.platform).startswith("win"):
        target.chmod(0o755)
    return target


def disable(path: Path | None = None) -> None:
    # missing_ok: switching off something already off is not an error, and the
    # checkbox has no way to report one.
    (path or entry_path()).unlink(missing_ok=True)


def apply(enabled: bool, path: Path | None = None) -> None:
    """Make the entry match the setting."""
    if enabled:
        enable(path)
    else:
        disable(path)
