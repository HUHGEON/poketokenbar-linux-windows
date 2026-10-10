"""Recover the tray's background worker without launching duplicate workers."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from . import commands, platform_paths
from .processes import background_options
from .single_instance import SingleInstance

_last_launch = float("-inf")


def launch_module(module: str) -> None:
    root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root) + os.pathsep + env.get("PYTHONPATH", "")
    logs = platform_paths.state_base() / "poketokenbar"
    logs.mkdir(parents=True, exist_ok=True)
    name = "daemon" if module == "poketokenbar.daemon" else "tray"
    with (logs / f"{name}.stdout.log").open("ab") as stdout, \
            (logs / f"{name}.stderr.log").open("ab") as stderr:
        subprocess.Popen(
            [sys.executable, "-m", module], cwd=root, env=env,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            **background_options(),
        )


def ensure_daemon() -> bool:
    """Start an absent daemon; its lifetime lock protects existing workers."""
    global _last_launch
    if time.monotonic() - _last_launch < 30:
        return False
    probe = SingleInstance("daemon")
    if not probe.acquire():
        return False
    probe.release()
    launch_module("poketokenbar.daemon")
    _last_launch = time.monotonic()
    return True


def refresh_data() -> None:
    commands.enqueue("refresh", {})
    ensure_daemon()
