"""Aside mutable per-turn usage, read from each profile's state.db."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ..models import Entry
from .base import dedup_keep_max, loads, number
from .sqlite_source import SQLiteProvider, date_value, make_entry, query

_SQL = """
SELECT t.id, t.token_usage, COALESCE(t.finished_at, t.last_message_timestamp), s.model
FROM session_turns t LEFT JOIN sessions s ON s.id = t.session_id
"""


def parse_database(path: Path) -> list[Entry]:
    rows = query(path, _SQL)
    if not rows:
        return []
    try:
        store = f"aside|{path.resolve()}#{path.stat().st_ino}"
    except OSError:
        return []
    entries = []
    for ident, payload, stamp, model_data in rows:
        try:
            usage = loads(payload)
        except Exception:
            continue
        if not isinstance(usage, dict):
            continue
        when = date_value(stamp)
        if when is None:
            continue
        model = "aside"
        try:
            metadata = loads(model_data)
            if isinstance(metadata, dict) and isinstance(metadata.get("modelId"), str):
                model = metadata["modelId"]
        except Exception:
            pass
        has_buckets = any(number(usage.get(key)) is not None for key in ("input", "output", "cacheRead", "cacheWrite"))
        cost = usage.get("cost")
        entry = make_entry(
            f"{store}:{ident}", when, model,
            input=usage.get("input" if has_buckets else "totalTokens"),
            output=usage.get("output"), cache_write=usage.get("cacheWrite"),
            cache_read=usage.get("cacheRead"),
            cost=cost.get("total") if isinstance(cost, dict) else None,
            # sessions.model is the current setting, not a historical turn model.
            cost_unavailable=True,
        )
        if entry is not None:
            entries.append(entry)
    return entries


class AsideProvider(SQLiteProvider):
    id = "aside"
    display_name = "Aside"
    reports_cost = True
    include_models = False
    PARSER_VERSION = 1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen: list[Entry] = []
        self._generation = None

    def curated_roots(self) -> list[Path]:
        return [self.home / ".aside" / "u"]

    def databases(self, root: Path) -> list[Path]:
        if root.is_file():
            return [root]
        try:
            candidates = [root, *root.iterdir()]
        except OSError:
            return []
        return sorted({(p / "state.db").resolve() for p in candidates if (p / "state.db").is_file()})

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_database(path)

    def scan_entries(self) -> list[Entry]:
        generation = (date.today().strftime("%Y-%m"), self.custom_roots_value())
        if generation != self._generation:
            self._seen = []
            self._generation = generation
        # Turn aggregates may shrink or disappear on session deletion. Preserve each
        # observed high-water mark until restart, month rollover, or root change.
        self._seen = dedup_keep_max(self._seen + super().scan_entries())
        return self._seen
