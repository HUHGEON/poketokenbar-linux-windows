"""Copilot CLI usage — ports the Copilot half of LocalAdditionalUsageProvider.swift.

One row per billed API call in `~/.copilot/session-store.db`, subagent calls
included: those are separate requests, not a copy of the parent turn, so unlike
Grok's session logs there is nothing here to exclude.

The accounting fault this reader exists to avoid: `input_tokens` is the *whole*
prompt, with cached reads and writes as a subset of it. Adding the columns as
they stand triples every cached prompt, so the cached parts are subtracted back
out. `reasoning_tokens` is likewise a breakdown of `output_tokens`, not an extra
charge, and is ignored.

Recoverable request buckets can be estimated at standard API prices; premium
request credits and subscription invoices are separate.

Timestamps arrive in two shapes — the CLI writes ISO-8601 with a `Z`, while the
column default (`datetime('now')`) writes `YYYY-MM-DD HH:MM:SS` in UTC — and a
row may carry a UTC offset. All three are normalised to the same instant.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ..models import Entry
from .base import parse_iso, to_int
from .sqlite_source import SQLiteProvider, make_entry, query

_SQL = """
SELECT id, model, input_tokens, output_tokens,
       cache_read_tokens, cache_write_tokens, created_at
FROM assistant_usage_events
"""


def parse_date(raw) -> datetime | None:
    """Both stored shapes, plus an explicit UTC offset when one is present."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) < 19:
        return None
    # "YYYY-MM-DD HH:MM:SS" -> "YYYY-MM-DDTHH:MM:SS"
    if " " in text:
        text = text.replace(" ", "T", 1)
    # A bare local-looking stamp is UTC: that column default writes UTC.
    time_part = text[11:]
    if "Z" not in time_part and "+" not in time_part and "-" not in time_part:
        text += "Z"
    parsed = parse_iso(text)
    if parsed is None:
        return None
    # Normalise to UTC so an offset row lands on the instant it represents,
    # not on the calendar day its text happens to sort under.
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def parse_database(path: Path) -> list[Entry]:
    rows = query(path, _SQL)
    if not rows:
        return []
    out: list[Entry] = []
    for row_id, model, input_tokens, output, cache_read, cache_write, created_at in rows:
        date = parse_date(created_at)
        if date is None:
            continue
        read = to_int(cache_read)
        write = to_int(cache_write)
        entry = make_entry(
            # The row id is unique only *within* one store, and $COPILOT_HOME may
            # name several. Without the database in the key, id 1 of each store
            # would collapse during dedup and that usage would go missing.
            f"copilot|{path}|{row_id}",
            date,
            model if isinstance(model, str) and model else "unknown",
            # Cached reads and writes are a subset of the prompt.
            input=max(0, to_int(input_tokens) - read - write),
            output=output,
            cache_write=write,
            cache_read=read,
        )
        if entry is not None:
            out.append(entry)
    return out


def roots(home: Path | None = None, env: Mapping[str, str] | None = None) -> list[Path]:
    """`$COPILOT_HOME`, else `~/.copilot` — a dotfile, so unchanged on Linux."""
    env = os.environ if env is None else env
    configured = (env.get("COPILOT_HOME") or "").strip()
    if configured:
        return [Path(configured).expanduser()]
    return [(home or Path.home()) / ".copilot"]


class CopilotProvider(SQLiteProvider):
    """GitHub Copilot CLI local usage."""

    id = "copilot"
    display_name = "Copilot CLI"
    reports_cost = True
    PARSER_VERSION = 1
    database_names = ("session-store.db",)

    def curated_roots(self) -> list[Path]:
        return roots(self._home)

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_database(path)
