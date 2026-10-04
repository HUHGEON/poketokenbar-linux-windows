"""Incremental scan cache — ports LocalUsageCache.swift.

Keyed on (provider, path, mtime, size, parser_version). Persisted so that the
expensive full parse happens once, not on every daemon start: a daily user's
session files are all "modified this month", so an mtime filter alone still
re-reads everything.
"""

from __future__ import annotations

import json
import sqlite3
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
                "session_id": e.session_id,
                "session_ids": e.session_ids,
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
            cost_is_estimate=d.get("cost_is_estimate", False),
            cost_unavailable=d.get("cost_unavailable", False),
            session_id=d.get("session_id"),
            session_ids=d.get("session_ids") or [],
        )
        for d in json.loads(raw)
    ]


class ScanCache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(db_path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def get(
        self, provider: str, path: Path, mtime: float, size: int, parser_version: int
    ) -> list[Entry] | None:
        row = self._db.execute(
            "SELECT entries FROM blobs WHERE provider=? AND path=? AND mtime=?"
            " AND size=? AND parser_version=?",
            (provider, str(path), mtime, size, parser_version),
        ).fetchone()
        return None if row is None else _decode(row[0])

    def put(
        self,
        provider: str,
        path: Path,
        mtime: float,
        size: int,
        parser_version: int,
        entries: list[Entry],
    ) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO blobs"
            " (provider, path, mtime, size, parser_version, entries)"
            " VALUES (?,?,?,?,?,?)",
            (provider, str(path), mtime, size, parser_version, _encode(entries)),
        )
        self._db.commit()

    def get_document(self, provider: str, path: Path, mtime: float, size: int,
                     parser_version: int) -> dict | None:
        """Metadata-rich parser blobs (Codex needs the unresolved event graph)."""
        row = self._db.execute(
            "SELECT entries FROM blobs WHERE provider=? AND path=? AND mtime=?"
            " AND size=? AND parser_version=?",
            (provider, str(path), mtime, size, parser_version),
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def put_document(self, provider: str, path: Path, mtime: float, size: int,
                     parser_version: int, document: dict) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO blobs"
            " (provider, path, mtime, size, parser_version, entries) VALUES (?,?,?,?,?,?)",
            (provider, str(path), mtime, size, parser_version, json.dumps(document)),
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
