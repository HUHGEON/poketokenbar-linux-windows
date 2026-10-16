"""Local save snapshots — ports SaveSnapshots.swift (upstream 13e3bf2).

A companion save is months of growth in one file, and the only copies of it
were the ones taken just before an import. This keeps dated restore points
beside the save: one at most every twelve hours while the daemon runs, the ten
newest kept, and one taken by hand whenever someone asks.

They are written in the export envelope's own format, so a snapshot is also an
export: it can be copied to another machine and imported there. A save that
will not parse is recovered from the newest snapshot that does, instead of
starting the companion over.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import save, transfer
from .companion import CompanionState

PREFIX = "companion-snapshot-"
SUFFIX = ".json"
# Enough to walk back through a bad week without filling a directory.
KEEP = 10
# A restore point every twelve hours: often enough to lose little, rare enough
# that a daemon polling every two seconds is not writing the save all day.
MIN_INTERVAL = 12 * 3600


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One restore point, described well enough to choose between them."""

    id: str
    path: Path
    taken_at: float
    dex_count: int
    used_since_install: int
    species_id: int | None
    is_shiny: bool


def directory(state_path: Path) -> Path:
    """Where this save's snapshots live.

    Keyed by the save's own file name: a test save and the real one must not
    share restore points, or restoring in one would hand over the other's.
    """
    return state_path.parent / ".snapshots" / state_path.name


def file_name(now: float) -> str:
    return f"{PREFIX}{datetime.fromtimestamp(now).strftime('%Y-%m-%d-%H%M%S')}{SUFFIX}"


def _taken_at(path: Path) -> float | None:
    """The instant in the file name, or None when it is not one of ours."""
    stem = path.name
    if not stem.startswith(PREFIX) or not stem.endswith(SUFFIX):
        return None
    raw = stem[len(PREFIX):-len(SUFFIX)]
    # Two snapshots inside one second get a "-2" serial; the instant is what
    # comes before it.
    for candidate in (raw, raw.rsplit("-", 1)[0]):
        try:
            return datetime.strptime(candidate, "%Y-%m-%d-%H%M%S").timestamp()
        except ValueError:
            continue
    return None


def listing(state_path: Path) -> list[Snapshot]:
    """Every readable snapshot for this save, newest first.

    A file that no longer parses is left out rather than offered: a restore
    point that cannot be restored is worse than one fewer.
    """
    folder = directory(state_path)
    try:
        found = sorted(folder.glob(f"{PREFIX}*{SUFFIX}"))
    except OSError:
        return []

    out: list[Snapshot] = []
    for path in found:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            state = transfer.decode(raw)
        except (OSError, ValueError, transfer.TransferError):
            continue
        taken = raw.get("exported_at")
        if not isinstance(taken, (int, float)):
            taken = _taken_at(path)
        if taken is None:
            try:
                taken = path.stat().st_mtime
            except OSError:
                continue
        active = state.active
        out.append(Snapshot(
            id=path.name,
            path=path,
            taken_at=float(taken),
            dex_count=len(state.dex),
            used_since_install=state.used_since_install,
            species_id=active.current_id if active is not None else None,
            is_shiny=bool(active.displays_shiny) if active is not None else False,
        ))
    # The name breaks a tie, as it carries the same instant plus its serial.
    out.sort(key=lambda s: (s.taken_at, s.id), reverse=True)
    return out


def create(state: CompanionState, state_path: Path, now: float | None = None) -> Snapshot:
    """Write a restore point for `state`, then prune the oldest beyond KEEP."""
    now = time.time() if now is None else now
    folder = directory(state_path)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / file_name(now)
    # A name is only unique to the second, and two snapshots can land inside
    # one — a manual one right before a restore, for instance.
    serial = 2
    while path.exists():
        path = folder / f"{file_name(now)[:-len(SUFFIX)]}-{serial}{SUFFIX}"
        serial += 1
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(transfer.encode(state, now=now), indent=2), encoding="utf-8")
    tmp.replace(path)
    prune(state_path)
    active = state.active
    return Snapshot(
        id=path.name,
        path=path,
        taken_at=now,
        dex_count=len(state.dex),
        used_since_install=state.used_since_install,
        species_id=active.current_id if active is not None else None,
        is_shiny=bool(active.displays_shiny) if active is not None else False,
    )


def prune(state_path: Path) -> None:
    for stale in listing(state_path)[KEEP:]:
        try:
            stale.path.unlink()
        except OSError:
            pass  # a leftover restore point harms nothing


def auto(state: CompanionState, state_path: Path, now: float | None = None) -> Snapshot | None:
    """Take a restore point if the newest one is old enough, else nothing.

    A save with nothing in it yet is not worth a restore point: the first
    snapshot should be of a companion, not of an empty install.
    """
    now = time.time() if now is None else now
    if state.used_since_install <= 0 and not state.dex and state.active is None:
        return None
    newest = listing(state_path)
    if newest and now - newest[0].taken_at < MIN_INTERVAL:
        return None
    try:
        return create(state, state_path, now)
    except OSError:
        return None  # a snapshot that cannot be written must not stop the poll


def load_state(path: Path) -> CompanionState | None:
    """The state inside one snapshot, or None when it cannot be read."""
    try:
        return transfer.decode(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, transfer.TransferError):
        return None


def latest_valid(state_path: Path) -> CompanionState | None:
    """The newest snapshot that still parses, for recovering a corrupt save."""
    for snapshot in listing(state_path):
        state = load_state(snapshot.path)
        if state is not None:
            return state
    return None


def restore(snapshot_id: str, state_path: Path, now: float | None = None) -> CompanionState:
    """Put one snapshot back, keeping what it replaces as a new snapshot.

    The chosen snapshot is read *before* the safety one is written: at the
    retention limit that extra file prunes the oldest, which may be the very
    one being restored (upstream's own fix inside 13e3bf2).
    """
    match = next((s for s in listing(state_path) if s.id == snapshot_id), None)
    if match is None:
        raise transfer.TransferError(f"no such snapshot: {snapshot_id}")
    restored = load_state(match.path)
    if restored is None:
        raise transfer.TransferError(f"snapshot cannot be read: {snapshot_id}")

    current = save.load(state_path)
    try:
        create(current, state_path, now)
    except OSError:
        pass  # the restore still stands; only the way back is missing
    # Local bookkeeping does not travel, exactly as an import does not carry it.
    restored = transfer._drop_local_bookkeeping(restored)
    save.save(restored, state_path)
    return restored
