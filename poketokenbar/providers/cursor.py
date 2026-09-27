"""Cursor usage — ports the local half of Cursor's reader in
LocalAdditionalUsageProvider.swift.

Cursor keeps its chat history in the VS Code-style key/value store
`state.vscdb`, where every `bubbleId:*` row is one chat bubble carrying
`tokenCount.{inputTokens, outputTokens}`, a `createdAt`, and a nullable
`modelType`.

Costs are not reported: an included-plan Cursor account is billed by request,
not per token, and the dashboard shows tokens only.

**Path remapping.** Cursor is an Electron app, so its user-data directory is
`app.getPath("userData")` — which is one of the three places in this project
where the platform actually changes the answer:

    macOS    ~/Library/Application Support/Cursor/User/globalStorage
    Linux    $XDG_CONFIG_HOME/Cursor/User/globalStorage
    Windows  %APPDATA%\\Cursor\\User\\globalStorage

The Windows location is documented by Cursor's own users; the Linux one follows
the convention VS Code itself uses (`~/.config/Code`). Neither is pinned by an
upstream test — the Swift suite only ever exercises the macOS layout — so
`$CURSOR_DATA_DIR` overrides both, and a report of where the files really were
is more useful than a guess.

Not yet ported: the signed-in dashboard API, which upstream prefers over this
local scan when a Cursor login is present. The local store is what that path
falls back to, so this reads usage offline; it can undercount against the
dashboard for usage that never touched this machine.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Mapping

from .. import platform_paths
from ..models import Entry
from .base import loads, parse_iso, to_int
from .sqlite_source import SQLiteProvider, date_value, make_entry, query

_SQL = "SELECT rowid, key, value FROM cursorDiskKV WHERE key GLOB 'bubbleId:*'"


def flexible_date(raw) -> datetime | None:
    """`createdAt` is an ISO-8601 string in some rows and an epoch number in others."""
    if isinstance(raw, str):
        return parse_iso(raw)
    return date_value(raw)


def parse_bubble(obj: dict, key: str) -> Entry | None:
    token_count = obj.get("tokenCount")
    if not isinstance(token_count, dict):
        return None
    input_tokens = to_int(token_count.get("inputTokens"))
    output = to_int(token_count.get("outputTokens"))
    if input_tokens + output <= 0:
        return None
    date = flexible_date(obj.get("createdAt"))
    if date is None:
        return None
    model = obj.get("modelType")
    return make_entry(
        f"cursor|{key}",
        date,
        model if isinstance(model, str) and model else "unknown",
        input=input_tokens,
        output=output,
        # Local bubbles carry no cost, and their model and token split are not
        # enough to price from the table (upstream 69ff39b).
        cost_unavailable=True,
    )


def parse_database(path: Path) -> list[Entry]:
    rows = query(path, _SQL)
    if not rows:
        return []
    out: list[Entry] = []
    for _rowid, key, payload in rows:
        if not isinstance(key, str):
            continue
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", "replace")
        if not isinstance(payload, str):
            continue
        try:
            obj = loads(payload)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        entry = parse_bubble(obj, key)
        if entry is not None:
            out.append(entry)
    return out


def user_data_dirs(
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    system: str | None = None,
) -> list[Path]:
    """Electron user-data directories for Cursor and Cursor Nightly.

    Not a convention that happens to work: `app.getPath('userData')` is
    documented as the `appData` directory plus the app's name, and `appData` is
    `%APPDATA%` on Windows, `$XDG_CONFIG_HOME` or `~/.config` on Linux and
    `~/Library/Application Support` on macOS — which is exactly what
    `platform_paths.config_base` returns. Cursor is an Electron application, so
    all three follow from its own runtime rather than from a guess.
    """
    env = os.environ if env is None else env
    configured = (env.get("CURSOR_DATA_DIR") or "").strip()
    if configured:
        return [Path(configured).expanduser()]
    base = platform_paths.config_base(home=home, env=env, system=system)
    return [
        base / "Cursor" / "User" / "globalStorage",
        base / "Cursor Nightly" / "User" / "globalStorage",
    ]


class CursorProvider(SQLiteProvider):
    """Cursor local usage, read from its chat store."""

    id = "cursor"
    display_name = "Cursor"
    # Included-plan usage is billed by request, and the dashboard is token-only.
    # v2: local bubbles are unpriced (69ff39b).
    PARSER_VERSION = 2
    database_names = ("state.vscdb",)

    def curated_roots(self) -> list[Path]:
        return user_data_dirs(self._home)

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_database(path)
