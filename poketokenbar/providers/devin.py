"""Devin CLI usage — ports LocalDevinProvider (upstream 2f4e03d).

Devin keeps its sessions in one SQLite store, `cli/sessions.db` under its data
directory. Every `message_nodes` row carries the message as JSON, and a turn
that cost tokens has them under `metadata.metrics`. The model is on the
session the message belongs to, which is why the two tables are joined.

Costs are not reported: the metrics carry token counts only. Devin's
`input_tokens` already excludes both cache buckets, so nothing is subtracted
from it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from .. import platform_paths
from ..models import Entry
from .base import dedup_keep_max, loads, to_int
from .sqlite_source import SQLiteProvider, date_value, make_entry, query

# The message, its session and when it happened, with the session's model.
_SQL = (
    "SELECT m.row_id, m.chat_message, m.session_id, m.created_at, s.model "
    "FROM message_nodes m LEFT JOIN sessions s ON s.id = m.session_id"
)


def roots(home: Path | None = None, env: Mapping[str, str] | None = None) -> list[Path]:
    """`$XDG_DATA_HOME/devin`, else `~/.local/share/devin`."""
    env = os.environ if env is None else env
    return [platform_paths.data_base(home=home, env=env) / "devin"]


def parse_row(row, database: Path) -> Entry | None:
    """One `message_nodes` row, or None when it is not a billed turn."""
    row_id, payload, session_id, created_at, model = row
    if not isinstance(payload, str):
        return None
    try:
        message = loads(payload)
    except Exception:
        return None
    if not isinstance(message, dict):
        return None
    metadata = message.get("metadata")
    metrics = metadata.get("metrics") if isinstance(metadata, dict) else None
    if not isinstance(metrics, dict):
        return None
    date = date_value(created_at)
    if date is None:
        return None

    # A branch copy gets a new row id but keeps the message's own id, so that
    # is what identifies the turn; without one the row id has to do.
    message_id = message.get("message_id")
    message_id = message_id if isinstance(message_id, str) and message_id else f"row{row_id}"
    session = session_id if isinstance(session_id, str) and session_id else "nosession"
    return make_entry(
        f"devin|{database}|{session}|{message_id}",
        date,
        model if isinstance(model, str) and model else "unknown",
        input=to_int(metrics.get("input_tokens")),
        output=to_int(metrics.get("output_tokens")),
        cache_write=to_int(metrics.get("cache_creation_tokens")),
        cache_read=to_int(metrics.get("cache_read_tokens")),
        cost_unavailable=True,
    )


def parse_database(path: Path) -> list[Entry]:
    rows = query(path, _SQL)
    if not rows:
        return []
    out = [entry for entry in (parse_row(row, path) for row in rows) if entry is not None]
    return dedup_keep_max(out)


class DevinProvider(SQLiteProvider):
    """Devin CLI local usage."""

    id = "devin"
    display_name = "Devin"
    # The metrics hold token counts and no amount.
    reports_cost = False

    def curated_roots(self) -> list[Path]:
        return roots(self._home)

    def databases(self, root: Path) -> list[Path]:
        """`<root>/cli/sessions.db`, or the store itself when named directly."""
        if root.is_file():
            return [root]
        if root.name == "cli":
            return [root / "sessions.db"]
        return [root / "cli" / "sessions.db"]

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_database(path)
