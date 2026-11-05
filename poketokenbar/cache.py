"""Incremental scan cache — ports LocalUsageCache.swift.

Keyed on (provider, path, mtime, size, parser_version). Persisted so that the
expensive full parse happens once, not on every daemon start: a daily user's
session files are all "modified this month", so an mtime filter alone still
re-reads everything.

A row also records how far into the file the parse got, and whatever the
provider needs to make sense of the entries afterwards. An append-only log
that has only grown is then read from that offset instead of from byte zero —
which is what the session being written to right now does on every single
poll (upstream 8f74054). Rows written before those columns existed are still
read; they simply cannot be tail-parsed until the file next changes.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .models import Entry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS blobs (
    provider       TEXT NOT NULL,
    path           TEXT NOT NULL,
    mtime          REAL NOT NULL,
    size           INTEGER NOT NULL,
    parser_version INTEGER NOT NULL,
    entries        TEXT NOT NULL,
    PRIMARY KEY (provider, path)
);
"""

# Added after the table shipped; an existing database gets them in place.
_COLUMNS = (
    ("offset", "INTEGER"),
    ("extra", "TEXT"),
    ("tail", "TEXT"),
)


@dataclass(frozen=True, slots=True)
class Blob:
    """One file's parsed entries, and what is needed to go on from there.

    `offset` is how many bytes of the file those entries account for, and
    None on a row from before the column existed or from a parser that cannot
    resume mid-file. `extra` is the provider's own state at that point —
    Claude's cumulative cost ledger — kept raw so a later total can be
    applied over the whole file rather than the tail alone.
    """

    entries: list[Entry]
    size: int
    offset: int | None = None
    extra: dict | None = None
    # The bytes just before `offset`, as hex. A file that grew is only
    # resumed when those bytes are still there: growing and being rewritten
    # look the same from a size alone.
    tail: str | None = None


def _encode(entries: list[Entry]) -> str:
    return json.dumps(
        [
            {
                "id": e.id,
                "date": e.date.isoformat(),
                "local_day": e.local_day,
                "model": e.model,
                "input": e.input,
                "output": e.output,
                "cache_write": e.cache_write,
                "cache_read": e.cache_read,
                "explicit_cost": e.explicit_cost,
                "cost_is_estimate": e.cost_is_estimate,
                "cost_unavailable": e.cost_unavailable,
            }
            for e in entries
        ]
    )


def _decode(raw: str) -> list[Entry]:
    return [
        Entry(
            id=d["id"],
            date=datetime.fromisoformat(d["date"]),
            local_day=d["local_day"],
            model=d["model"],
            input=d["input"],
            output=d["output"],
            cache_write=d["cache_write"],
            cache_read=d["cache_read"],
            # Blobs written before the field existed simply carry no charge.
            explicit_cost=d.get("explicit_cost"),
            cost_is_estimate=bool(d.get("cost_is_estimate", False)),
            cost_unavailable=bool(d.get("cost_unavailable", False)),
        )
        for d in json.loads(raw)
    ]


def _row(row) -> Blob:
    entries, size, offset, extra, tail = row
    return Blob(
        entries=_decode(entries),
        size=size,
        offset=offset,
        extra=None if extra is None else json.loads(extra),
        tail=tail,
    )


class ScanCache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        for name, kind in _COLUMNS:
            try:
                self._db.execute(f"ALTER TABLE blobs ADD COLUMN {name} {kind}")
            except sqlite3.OperationalError:
                pass  # already there
        self._db.commit()

    def get(
        self, provider: str, path: Path, mtime: float, size: int, parser_version: int
    ) -> Blob | None:
        """The row for exactly this file as it is now, or None."""
        row = self._db.execute(
            "SELECT entries, size, offset, extra, tail FROM blobs"
            " WHERE provider=? AND path=? AND mtime=? AND size=? AND parser_version=?",
            (provider, str(path), mtime, size, parser_version),
        ).fetchone()
        return None if row is None else _row(row)

    def previous(self, provider: str, path: Path, parser_version: int) -> Blob | None:
        """The row for this file from before it changed.

        The entries in it are still good for the bytes they were parsed from,
        which is what lets an append-only log be read from where the last
        parse stopped.
        """
        row = self._db.execute(
            "SELECT entries, size, offset, extra, tail FROM blobs"
            " WHERE provider=? AND path=? AND parser_version=?",
            (provider, str(path), parser_version),
        ).fetchone()
        return None if row is None else _row(row)

    def put(
        self,
        provider: str,
        path: Path,
        mtime: float,
        size: int,
        parser_version: int,
        entries: list[Entry],
        offset: int | None = None,
        extra: dict | None = None,
        tail: str | None = None,
    ) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO blobs"
            " (provider, path, mtime, size, parser_version, entries, offset, extra, tail)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (provider, str(path), mtime, size, parser_version, _encode(entries),
             offset, None if extra is None else json.dumps(extra), tail),
        )
        self._db.commit()

    def prune(self, provider: str, live_paths: set[str]) -> None:
        """Drop rows for files that no longer exist."""
        stale = [
            row[0]
            for row in self._db.execute(
                "SELECT path FROM blobs WHERE provider=?", (provider,)
            )
            if row[0] not in live_paths
        ]
        if stale:
            self._db.executemany(
                "DELETE FROM blobs WHERE provider=? AND path=?",
                [(provider, p) for p in stale],
            )
            self._db.commit()

    def close(self) -> None:
        self._db.close()
