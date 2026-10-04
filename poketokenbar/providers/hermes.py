"""Hermes Agent usage — ports the Hermes half of LocalAdditionalUsageProvider.swift.

One row per session in `~/.hermes/state.db`, already aggregated by the agent,
so there is nothing to dedup within a file — the session id is the entry id.

`reasoning_tokens` is billed as output and is *not* already inside
`output_tokens` here (unlike Pi), so the two are summed. Cost prefers the
actual charge over the estimate whenever the agent recorded one.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from ..models import Entry
from .base import number, to_int
from .sqlite_source import SQLiteProvider, date_value, make_entry, query

_SQL = """
SELECT id, model, billing_provider, started_at, message_count,
       input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
       reasoning_tokens, estimated_cost_usd, actual_cost_usd
FROM sessions
WHERE model IS NOT NULL AND TRIM(model) != ''
"""


def parse_database(path: Path) -> list[Entry]:
    rows = query(path, _SQL)
    if not rows:
        return []
    out: list[Entry] = []
    for row in rows:
        session_id = (row[0] or "").strip() if isinstance(row[0], str) else ""
        model = (row[1] or "").strip() if isinstance(row[1], str) else ""
        if not session_id or not model:
            continue
        date = date_value(row[3])
        if date is None:
            continue
        estimated, actual = number(row[10]), number(row[11])
        actual = actual if actual is not None and actual >= 0 else None
        entry = make_entry(
            f"hermes|{session_id}",
            date,
            model,
            input=row[5],
            # Hermes bills reasoning on top of output rather than inside it.
            output=to_int(row[6]) + to_int(row[9]),
            cache_write=row[8],
            cache_read=row[7],
            cost=actual if actual is not None else estimated,
            cost_is_estimate=actual is None,
            cost_unavailable=True,
        )
        if entry is not None:
            out.append(entry)
    return out


def roots(home: Path | None = None, env: Mapping[str, str] | None = None) -> list[Path]:
    """`$HERMES_HOME` if set, else `~/.hermes` — the same on Linux and macOS."""
    env = os.environ if env is None else env
    configured = (env.get("HERMES_HOME") or "").strip()
    if configured:
        return [Path(configured).expanduser()]
    return [(home or Path.home()) / ".hermes"]


class HermesProvider(SQLiteProvider):
    """Hermes Agent local usage."""

    id = "hermes"
    display_name = "Hermes Agent"
    reports_cost = True
    PARSER_VERSION = 2
    database_names = ("state.db",)

    def curated_roots(self) -> list[Path]:
        return roots(self._home)

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_database(path)
