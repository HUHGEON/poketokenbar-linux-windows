"""Shared helpers for the SQLite-backed sources.

OpenCode, Hermes, Cursor, Copilot, Kiro and Antigravity all keep their usage in
a local database rather than a log tree. What they share is here so a fix to the
read-only open, the WAL-aware cache signature, or the token-total rule cannot
land in only one of them.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ..models import Entry
from .base import ScanningProvider, local_day, number, to_int


def open_readonly(path: Path) -> sqlite3.Connection | None:
    """A read-only connection, or None when the file cannot be opened as one.

    `immutable=0` so an actively-written store is still read correctly through
    its WAL; the URI form is what keeps this from ever creating a database when
    the path is wrong.
    """
    if not path.is_file():
        return None
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1.0)
    except sqlite3.Error:
        return None


def query(path: Path, sql: str, params: tuple = ()) -> list[tuple] | None:
    """Rows, [] when the store is absent, or None when the read itself failed.

    The three-way result matters: an absent store is "this tool is not
    installed", while a failed read is "try again next refresh" — collapsing
    them would cache an empty day over real usage.
    """
    if not path.is_file():
        return []
    connection = open_readonly(path)
    if connection is None:
        return None
    try:
        return list(connection.execute(sql, params))
    except sqlite3.Error:
        # A missing table is the usual cause: schema generations coexist, and
        # the caller falls back to the other one.
        return None
    finally:
        connection.close()


def table_exists(path: Path, name: str) -> bool:
    rows = query(
        path, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    )
    return bool(rows)


def date_value(raw) -> datetime | None:
    """An epoch timestamp in seconds, absorbing a milliseconds variant."""
    parsed = number(raw)
    if parsed is None or parsed <= 0:
        return None
    seconds = parsed / 1000 if parsed >= 100_000_000_000 else parsed
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def make_entry(
    entry_id: str,
    date: datetime,
    model: str,
    input: int = 0,
    output: int = 0,
    cache_write: int = 0,
    cache_read: int = 0,
    total: int = 0,
    cost: float | None = None,
    cost_is_estimate: bool = False,
    cost_unavailable: bool = False,
) -> Entry | None:
    """Ports `makeEntry` — the shared bucket-safety and total-identity rule.

    Negative buckets fold to 0, and when the store's own `total` exceeds the
    buckets the shortfall is attributed to output so `Entry.total` still equals
    what the source reported. A row that ends up at zero tokens is not a record
    of spend and returns None.
    """
    safe_input = max(0, to_int(input))
    safe_cache_write = max(0, to_int(cache_write))
    safe_cache_read = max(0, to_int(cache_read))
    safe_output = max(0, to_int(output))

    parts = safe_input + safe_output + safe_cache_write + safe_cache_read
    reported_total = to_int(total)
    if reported_total > parts:
        safe_output += reported_total - parts

    if safe_input + safe_output + safe_cache_write + safe_cache_read <= 0:
        return None
    return Entry(
        id=entry_id,
        date=date,
        local_day=local_day(date),
        model=model,
        input=safe_input,
        output=safe_output,
        cache_write=safe_cache_write,
        cache_read=safe_cache_read,
        # Zero is a recorded cost too (upstream 69ff39b); only NaN, infinities
        # and negatives are not.
        explicit_cost=cost if isinstance(cost, (int, float)) and math.isfinite(cost) and cost >= 0
        else None,
        cost_is_estimate=cost_is_estimate,
        # Tokens beyond the buckets cannot be put in a bucket to price.
        cost_unavailable=cost_unavailable or reported_total > parts,
    )


class SQLiteProvider(ScanningProvider):
    """A source whose usage lives in one or more local SQLite databases.

    `roots()` returns directories; `database_names()` says which files inside
    them to open. Subclasses implement `parse_database()`.
    """

    # Database file names to look for under each root, in order of preference.
    database_names: tuple[str, ...] = ()

    def databases(self, root: Path) -> list[Path]:
        """The stores under one root. A root naming a file directly is used as-is."""
        if root.is_file():
            return [root]
        return [root / name for name in self.database_names if (root / name).is_file()]

    def files(self, root: Path):
        yield from self.databases(root)

    def file_signature(self, path: Path) -> tuple[float, int] | None:
        """Fold the `-wal` sidecar into the cache key.

        A WAL store takes writes without the main file's mtime or size moving,
        so keying on it alone serves a stale blob until something else touches
        it — the usage would simply stop updating.

        `-shm` is deliberately excluded: it holds no committed data, and a
        read-only connection writes read marks into it, so including it would
        invalidate the blob this reader had just written, on every sweep,
        forever.
        """
        newest: float | None = None
        size = 0
        found = False
        for candidate in (path, path.with_name(path.name + "-wal")):
            try:
                stat = candidate.stat()
            except OSError:
                continue
            found = True
            newest = stat.st_mtime if newest is None else max(newest, stat.st_mtime)
            size += stat.st_size
        if not found or newest is None:
            return None
        return (newest, size)
