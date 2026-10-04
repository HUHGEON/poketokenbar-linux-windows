"""Bounded local save snapshots, separate for each companion save file."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from . import save, transfer
from .companion import CompanionState

PREFIX = "companion-snapshot-"
KEEP = 10
AUTO_INTERVAL = 12 * 60 * 60


def directory(target: Path | None = None) -> Path:
    target = target or save.default_path()
    return target.parent / ".snapshots" / target.name


def _read(path: Path) -> tuple[CompanionState, float]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    repairs = list(save.last_repairs)
    try:
        if isinstance(raw, dict) and raw.get("format") == transfer.FORMAT:
            state = transfer.decode(raw)
            taken_at = raw.get("exported_at")
        elif isinstance(raw, dict) and any(key in raw for key in ("dex", "active", "used_since_install")):
            state = save.decode(raw)
            taken_at = None
        else:
            raise transfer.TransferError("not a companion snapshot")
    finally:
        save.last_repairs = repairs
    return state, float(taken_at) if isinstance(taken_at, (int, float)) else path.stat().st_mtime


def _summary(path: Path, state: CompanionState, taken_at: float) -> dict:
    return {"id": path.name, "taken_at": taken_at, **transfer.summary(state),
            "is_shiny": state.active.visible_shiny if state.active else False}


def list_snapshots(target: Path | None = None) -> list[dict]:
    rows = []
    for path in directory(target).glob(f"{PREFIX}*.json"):
        if path.is_symlink():
            continue
        try:
            state, taken_at = _read(path)
            rows.append(_summary(path, state, taken_at))
        except (OSError, ValueError, TypeError, transfer.TransferError):
            continue
    return sorted(rows, key=lambda row: (row["taken_at"], row["id"]), reverse=True)


def read_snapshot(snapshot_id: str, target: Path | None = None) -> CompanionState:
    if (not isinstance(snapshot_id, str) or "/" in snapshot_id or "\\" in snapshot_id
            or not snapshot_id.startswith(PREFIX) or not snapshot_id.endswith(".json")):
        raise transfer.TransferError("invalid snapshot identifier")
    path = directory(target) / snapshot_id
    if path.is_symlink() or not any(row["id"] == snapshot_id for row in list_snapshots(target)):
        raise transfer.TransferError("snapshot is missing or invalid")
    try:
        return _read(path)[0]
    except (OSError, ValueError, TypeError) as exc:
        raise transfer.TransferError(f"cannot read snapshot: {exc}") from exc


def create_snapshot(state: CompanionState, target: Path | None = None,
                    now: float | None = None) -> dict:
    now = time.time() if now is None else now
    base = directory(target)
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    path = base / f"{PREFIX}{stamp}.json"
    serial = 1
    while path.exists():
        path = base / f"{PREFIX}{stamp}-{serial:04d}.json"
        serial += 1
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(transfer.encode(state, now=now), indent=2), encoding="utf-8")
    tmp.replace(path)
    for row in list_snapshots(target)[KEEP:]:
        try:
            (base / row["id"]).unlink()
        except OSError:
            pass
    return _summary(path, state, now)


def auto_snapshot(state: CompanionState, target: Path | None = None,
                  now: float | None = None) -> None:
    now = time.time() if now is None else now
    rows = list_snapshots(target)
    if not rows or now - rows[0]["taken_at"] >= AUTO_INTERVAL:
        create_snapshot(state, target, now)


def latest_state(target: Path | None = None) -> CompanionState | None:
    for row in list_snapshots(target):
        try:
            return read_snapshot(row["id"], target)
        except transfer.TransferError:
            continue
    return None
