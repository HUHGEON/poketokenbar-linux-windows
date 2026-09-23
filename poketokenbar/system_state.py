"""Small cross-platform signals used to avoid waste and recover promptly."""

from __future__ import annotations

import ctypes
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from .processes import background_options


_power_checked_at = 0.0
_power_cached = False


def power_saver() -> bool:
    """Cached power mode; the Qt tray asks every two seconds."""
    global _power_checked_at, _power_cached
    now = time.monotonic()
    if now - _power_checked_at >= 15:
        _power_cached = _read_power_saver()
        _power_checked_at = now
    return _power_cached


def _read_power_saver() -> bool:
    """Whether the operating system currently asks apps to conserve power."""
    if sys.platform == "win32":
        class Status(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_ubyte),
                ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte),
                ("SystemStatusFlag", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_ulong),
                ("BatteryFullLifeTime", ctypes.c_ulong),
            ]

        status = Status()
        try:
            if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                return status.SystemStatusFlag == 1
        except (AttributeError, OSError):
            return False
        return False

    profile = Path("/sys/firmware/acpi/platform_profile")
    try:
        if profile.read_text(encoding="utf-8").strip().lower() in {
            "low-power", "power-saver", "quiet",
        }:
            return True
    except OSError:
        pass
    try:
        result = subprocess.run(
            ["powerprofilesctl", "get"], capture_output=True, text=True,
            timeout=1, **background_options(),
        )
        return result.returncode == 0 and result.stdout.strip() == "power-saver"
    except (OSError, subprocess.SubprocessError):
        return False


def network_available(timeout: float = 1.0) -> bool:
    """Best-effort internet reachability without sending application data."""
    if sys.platform == "win32":
        flags = ctypes.c_ulong()
        try:
            return bool(ctypes.windll.wininet.InternetGetConnectedState(
                ctypes.byref(flags), 0
            ))
        except (AttributeError, OSError):
            pass
    try:
        connection = socket.create_connection(("1.1.1.1", 443), timeout=timeout)
    except OSError:
        return False
    connection.close()
    return True


class ConnectivityMonitor:
    """Edge detector: only offline -> online requests a refresh."""

    def __init__(self, probe=network_available, clock=time.monotonic,
                 interval: float = 10.0) -> None:
        self.probe = probe
        self.clock = clock
        self.interval = interval
        self._next_check = 0.0
        self._last: bool | None = None

    def reconnected(self) -> bool:
        now = self.clock()
        if now < self._next_check:
            return False
        self._next_check = now + self.interval
        current = bool(self.probe())
        reconnected = self._last is False and current
        self._last = current
        return reconnected
