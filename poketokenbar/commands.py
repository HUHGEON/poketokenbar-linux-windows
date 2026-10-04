"""UI -> daemon commands, as files in a spool directory.

A directory rather than a socket or D-Bus: a queued command survives a daemon
restart, neither side needs an IPC library, and poketokenctl stays
shell-testable.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import platform_paths

_counter = 0


def spool_dir() -> Path:
    return platform_paths.runtime_base() / "poketokenbar" / "commands"


def enqueue(name: str, args: dict, spool: Path | None = None) -> Path:
    global _counter
    spool = spool or spool_dir()
    spool.mkdir(parents=True, exist_ok=True)
    _counter += 1
    # Monotonic, zero-padded, unique per process — drain() sorts on this name.
    stem = f"{time.time_ns():020d}-{os.getpid()}-{_counter:04d}"
    tmp = spool / f".{stem}.tmp"
    final = spool / f"{stem}.json"
    # Session-key updates use this same spool. Restrict the temporary file from
    # creation, before writing any credentials into it.
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"name": name, "args": args}, handle)
    tmp.replace(final)  # atomic — the daemon never reads a half-written command
    return final


def drain(spool: Path | None = None) -> list[dict]:
    spool = spool or spool_dir()
    if not spool.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(spool.glob("*.json")):
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass  # corrupt command is dropped, not retried forever
        finally:
            path.unlink(missing_ok=True)
    return out
