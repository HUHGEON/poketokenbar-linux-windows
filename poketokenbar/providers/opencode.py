"""OpenCode usage — ports the OpenCode half of LocalAdditionalUsageProvider.swift.

Two layouts coexist under `~/.local/share/opencode`, and both are read:

  opencode.db                 current — one row per message, the JSON payload
                              in a `data` column
  storage/message/*.json      older — the same payload, one file each

Two database generations coexist as well: newer stores expose `time_created`
as a column, older ones do not, so a failed query falls back to the column-less
statement rather than reporting no usage.

Named channels (`opencode-<channel>.db`) are picked up when the standard file is
absent, with the channel restricted to plain identifier characters so a stray
file cannot steer the read somewhere unintended.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .. import platform_paths
from ..models import Entry
from .base import loads
from .sqlite_source import SQLiteProvider, date_value, make_entry, query

# Newer stores can filter on a real column; older ones have no such column and
# the query fails, which is the signal to use the second form.
_SQL_WITH_TIME = "SELECT id, session_id, data FROM message WHERE time_created IS NOT NULL"
_SQL_LEGACY = "SELECT id, session_id, data FROM message"


def parse_message(obj: dict, fallback_id: str) -> Entry | None:
    """One message payload, in either layout — they carry the same document."""
    tokens = obj.get("tokens")
    if not isinstance(tokens, dict):
        return None
    time = obj.get("time")
    date = date_value(time.get("created")) if isinstance(time, dict) else None
    if date is None:
        return None
    model = obj.get("modelID")
    if not isinstance(model, str) or not model:
        return None
    # providerID must be present: a payload without it is not a billed message.
    if not isinstance(obj.get("providerID"), str):
        return None

    cache = tokens.get("cache")
    cache = cache if isinstance(cache, dict) else {}
    raw_id = obj.get("id")
    entry_id = raw_id if isinstance(raw_id, str) and raw_id else fallback_id
    cost = obj.get("cost")
    return make_entry(
        f"opencode|{entry_id}",
        date,
        model,
        input=tokens.get("input"),
        output=tokens.get("output"),
        cache_write=cache.get("write"),
        cache_read=cache.get("read"),
        # Any tokens the buckets do not account for are retained as output so
        # Entry.total still equals the reported total.
        total=tokens.get("total"),
        cost=cost if isinstance(cost, (int, float)) else None,
    )


def parse_database(path: Path) -> list[Entry]:
    rows = query(path, _SQL_WITH_TIME)
    if rows is None:
        # Older databases have no time_created column at all.
        rows = query(path, _SQL_LEGACY)
    if not rows:
        return []
    out: list[Entry] = []
    for row_id, _session_id, payload in rows:
        if not isinstance(payload, str):
            continue
        try:
            obj = loads(payload)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        entry = parse_message(obj, fallback_id=str(row_id))
        if entry is not None:
            out.append(entry)
    return out


def parse_legacy_file(path: Path) -> list[Entry]:
    try:
        obj = loads(path.read_bytes())
    except (OSError, Exception):
        return []
    if not isinstance(obj, dict):
        return []
    entry = parse_message(obj, fallback_id=path.stem)
    return [entry] if entry is not None else []


def _is_channel_database(name: str) -> bool:
    """`opencode-<channel>.db`, with the channel kept to identifier characters."""
    if not name.startswith("opencode-") or not name.endswith(".db"):
        return False
    channel = name[len("opencode-") : -len(".db")]
    return bool(channel) and all(c.isascii() and (c.isalnum() or c in "_-") for c in channel)


def roots(
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    system: str | None = None,
) -> list[Path]:
    """`$OPENCODE_DATA_DIR`, else the platform's application-data directory.

    The Linux path (`~/.local/share/opencode`) is the one upstream names. The
    others follow the same convention the tool's own runtime would, and like
    Cursor and Kiro they are unverified — the variable overrides them.
    """
    env = os.environ if env is None else env
    configured = (env.get("OPENCODE_DATA_DIR") or "").strip()
    if configured:
        return [Path(configured).expanduser()]
    return [platform_paths.data_base(home=home, env=env, system=system) / "opencode"]


class OpenCodeProvider(SQLiteProvider):
    """OpenCode local usage."""

    id = "opencode"
    display_name = "OpenCode"
    reports_cost = True
    # v2: tokens beyond the buckets are unpriced (69ff39b).
    PARSER_VERSION = 2

    def curated_roots(self) -> list[Path]:
        return roots(self._home)

    def databases(self, root: Path) -> list[Path]:
        if root.is_file():
            return [root]
        standard = root / "opencode.db"
        if standard.is_file():
            return [standard]
        try:
            names = sorted(p.name for p in root.iterdir())
        except OSError:
            return []
        return [root / name for name in names if _is_channel_database(name)][:1]

    def files(self, root: Path):
        yield from self.databases(root)
        # The older per-message layout can sit beside the database.
        legacy = root / "storage" / "message"
        if legacy.is_dir():
            yield from sorted(legacy.rglob("*.json"))

    def file_signature(self, path: Path) -> tuple[float, int] | None:
        if path.suffix == ".json":
            try:
                stat = path.stat()
            except OSError:
                return None
            return (stat.st_mtime, stat.st_size)
        return super().file_signature(path)

    def parse_file(self, path: Path) -> list[Entry]:
        if path.suffix == ".json":
            return parse_legacy_file(path)
        return parse_database(path)
