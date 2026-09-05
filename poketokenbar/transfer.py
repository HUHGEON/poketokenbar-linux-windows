"""Save export / import — ports SaveTransfer.swift.

An export is an envelope around the save: format version, app version, device
name, and timestamp. Importing replaces local progress entirely, so the
envelope is validated before anything is overwritten, and the existing save is
kept as a backup rather than discarded.

Two things follow from "replaces entirely", and both are here rather than in
the caller:

*   The backup is what makes a mistaken import survivable, so it is dated and
    kept — an import that cannot be backed up is refused instead of proceeding
    unrecoverably, and a second import no longer overwrites the record of what
    the first one replaced.
*   The per-provider baseline is bookkeeping about *this* machine's logs, not
    progress, so it does not travel. Carrying it over made the first poll after
    an import either credit a whole day of usage at once or swallow real usage,
    depending on which machine had counted further.
"""

from __future__ import annotations

import json
import platform
import time
from datetime import datetime
from pathlib import Path

from . import save
from .companion import CompanionState

FORMAT = "poketokenbar.save"
FORMAT_VERSION = 1

BACKUP_SUFFIX = ".before-import"
# Enough to walk back a run of mistaken imports; not so many that a save
# directory fills with them.
KEEP_BACKUPS = 5


class TransferError(Exception):
    pass


def default_export_path() -> Path:
    """Where the UI's one-click export lands.

    The daemon owns this rather than the extension: the popup has to describe
    the file before offering to overwrite a Pokédex with it, and a path known
    to only one side cannot be described by the other.
    """
    return Path.home() / "poketokenbar-save.json"


def suggested_filename(now: float | None = None) -> str:
    stamp = datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d")
    return f"poketokenbar-save-{stamp}.json"


def encode(state: CompanionState, app_version: str = "0.1.0", now: float | None = None) -> dict:
    return {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "app_version": app_version,
        "device": platform.node(),
        "exported_at": now or time.time(),
        "save": save.encode(state),
    }


def summary(state: CompanionState) -> dict:
    """What a person needs to judge an overwrite before confirming it."""
    active = state.active
    return {
        "dex_count": len(state.dex),
        "used_since_install": state.used_since_install,
        "active_species": active.current_id if active else None,
        "items": sum(state.inventory.values()),
    }


def export_to(path: Path, state: CompanionState, app_version: str = "0.1.0") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(encode(state, app_version), indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def decode(raw: dict) -> CompanionState:
    if not isinstance(raw, dict):
        raise TransferError("not a save file")
    if raw.get("format") != FORMAT:
        raise TransferError("not a PokeTokenBar save file")
    version = raw.get("format_version")
    if not isinstance(version, int) or version > FORMAT_VERSION:
        # Refuse the future rather than silently dropping fields we cannot read.
        raise TransferError(f"unsupported save version: {version}")
    body = raw.get("save")
    if not isinstance(body, dict):
        raise TransferError("save file has no payload")
    return save.decode(body)


def read_envelope(path: Path) -> dict:
    """The validated envelope, without touching the local save."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise TransferError(f"cannot read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise TransferError("not a save file")
    decode(raw)  # validates; the state itself is rebuilt by the caller
    return raw


def describe(path: Path) -> dict:
    """What is in an export file, for a prompt shown before overwriting.

    Never raises: a missing or unreadable file is a thing the popup has to
    render, not an error that stops the poll that renders it.
    """
    out: dict = {
        "path": str(path),
        "exists": False,
        "error": None,
        "exported_at": None,
        "device": None,
        "dex_count": None,
        "used_since_install": None,
        "items": None,
    }
    if not path.is_file():
        return out
    out["exists"] = True
    try:
        raw = read_envelope(path)
    except TransferError as exc:
        out["error"] = str(exc)
        return out
    exported = raw.get("exported_at")
    out["exported_at"] = exported if isinstance(exported, (int, float)) else None
    device = raw.get("device")
    out["device"] = device if isinstance(device, str) else None
    counted = summary(decode(raw))
    for key in ("dex_count", "used_since_install", "items"):
        out[key] = counted[key]
    return out


def backups(target: Path | None = None) -> list[Path]:
    """Every kept pre-import copy of this save, newest first."""
    target = target or save.default_path()
    try:
        found = list(target.parent.glob(target.name + BACKUP_SUFFIX + "*"))
    except OSError:
        return []
    # Name breaks the tie: two imports inside one second share a timestamp, and
    # mtime alone would then order them arbitrarily — including the pair that
    # `restore_backup` has to tell apart.
    return sorted(found, key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def describe_backup(target: Path | None = None) -> dict:
    """The save an undo would put back, described like an export file.

    Undoing is the same destructive write as importing, only in the other
    direction, so it is offered with the same numbers in front of it rather
    than as a button that silently replaces a save with an older one.
    """
    out: dict = {
        "exists": False,
        "taken_at": None,
        "dex_count": None,
        "used_since_install": None,
        "items": None,
    }
    kept = backups(target or save.default_path())
    if not kept:
        return out
    newest = kept[0]
    try:
        state = save.decode(json.loads(newest.read_text(encoding="utf-8")))
        out["taken_at"] = newest.stat().st_mtime
    except (OSError, ValueError):
        return out  # an unreadable backup is one that cannot be offered
    out["exists"] = True
    counted = summary(state)
    for key in ("dex_count", "used_since_install", "items"):
        out[key] = counted[key]
    return out


def _back_up(target: Path, now: float | None = None) -> Path | None:
    """Copy the save aside under a dated name, or refuse the import.

    Dated because the previous behaviour — one fixed name — meant a second
    import destroyed the only copy of what the first one replaced, which is
    exactly when someone is most likely to need it.
    """
    if not target.is_file():
        return None
    stamp = datetime.fromtimestamp(now or time.time()).strftime("%Y%m%d-%H%M%S")
    backup = target.with_name(f"{target.name}{BACKUP_SUFFIX}-{stamp}")
    # A dated name is only unique to the second, and undoing an import right
    # after making it lands inside the same one.
    serial = 2
    while backup.exists():
        backup = target.with_name(f"{target.name}{BACKUP_SUFFIX}-{stamp}-{serial}")
        serial += 1
    try:
        backup.write_bytes(target.read_bytes())
    except OSError as exc:
        # Importing is destructive and the backup is the only way back, so a
        # failure here has to stop the import rather than be swallowed.
        raise TransferError(f"cannot back up {target}: {exc}") from exc
    for stale in backups(target)[KEEP_BACKUPS:]:
        try:
            stale.unlink()
        except OSError:
            pass  # a leftover copy is harmless; failing the import is not
    return backup


def _drop_local_bookkeeping(state: CompanionState) -> CompanionState:
    """Forget what the exporting machine had already counted.

    `claimed_today_tokens_by_provider` records how far this machine's logs had
    been read, so it means nothing here. None is the "seed from the next
    snapshot, grant nothing" sentinel, which is what an imported save wants:
    progress carries over, today's usage starts counting from now.
    """
    state.claimed_today_tokens_by_provider = None
    state.last_date = ""
    return state


def import_from(path: Path, target: Path | None = None) -> CompanionState:
    """Replace the local save with an exported one.

    The current save is copied aside first: importing is destructive, and a
    mistaken import should be recoverable.
    """
    incoming = _drop_local_bookkeeping(decode(read_envelope(path)))

    target = target or save.default_path()
    _back_up(target)

    save.save(incoming, target)
    return incoming


def restore_backup(target: Path | None = None) -> CompanionState:
    """Undo the most recent import by putting its backup back.

    The backup of the *current* save is taken first, so undoing an undo is
    itself possible and the newest copy is never the one being discarded.
    """
    target = target or save.default_path()
    kept = backups(target)
    if not kept:
        raise TransferError("no pre-import backup to restore")
    newest = kept[0]
    try:
        restored = save.decode(json.loads(newest.read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise TransferError(f"cannot read {newest}: {exc}") from exc

    _back_up(target)
    save.save(restored, target)
    try:
        newest.unlink()
    except OSError:
        pass  # restored either way; the copy is only clutter now
    return restored
