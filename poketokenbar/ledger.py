"""Day-by-day token history — ports UsageLedger (upstream 78595ed).

Providers only report the current month, so on the 3rd a seven-day recap would
have lost four days and a year would be out of reach entirely. Every poll
copies the month's daily totals into this ledger, which is a cache of numbers
the daemon already derived: no new user state, nothing to carry between
machines, and it rebuilds itself from the next refresh.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date as _date
from pathlib import Path

# A day key is yyyy-mm-dd, which sorts lexicographically exactly as it sorts
# chronologically — every comparison here relies on that.
_KEY_LENGTH = 10


def _is_day(key) -> bool:
    if not isinstance(key, str) or len(key) != _KEY_LENGTH:
        return False
    try:
        _date.fromisoformat(key)
    except ValueError:
        return False
    return True


@dataclass(slots=True)
class Ledger:
    """What was used each day, and the first day that answer is trustworthy."""

    days: dict[str, int] = field(default_factory=dict)
    # Before this day the daemon was not recording. A recap must not draw that
    # as a quiet stretch, so "no row" means nothing before it and zero after.
    covered_since: str | None = None

    def tokens(self, day: str) -> int:
        return self.days.get(day, 0)

    def covers(self, day: str) -> bool:
        return self.covered_since is not None and day >= self.covered_since

    def knows(self, day: str) -> bool:
        """Whether this day's number means anything — recorded, or vouched for."""
        return self.tokens(day) > 0 or self.covers(day)

    def merge(self, daily: dict[str, int]) -> None:
        """Record one refresh's month-to-date series.

        A day never goes down. A rotated or pruned log makes a provider report
        less than it did yesterday, and a recap would then lose days that
        really happened; today's own total climbs all day, so keeping the
        larger of the two is also what the live figures do.
        """
        for day, tokens in daily.items():
            if not _is_day(day) or not isinstance(tokens, int) or tokens <= 0:
                continue
            self.days[day] = max(self.days.get(day, 0), tokens)
        # The series carries every day since the 1st, empty ones included, so
        # the whole stretch was scanned: that is what makes a zero a real zero.
        first = min((day for day in daily if _is_day(day)), default=None)
        if first is not None and (self.covered_since is None or first < self.covered_since):
            self.covered_since = first

    def prune(self, before: str) -> None:
        """Drop what no recap can reach any more."""
        self.days = {day: tokens for day, tokens in self.days.items() if day >= before}
        if self.covered_since is not None and self.covered_since < before:
            # The dropped days are unknown again, not empty.
            self.covered_since = before


def load(path: Path) -> Ledger:
    """The ledger on disk, or an empty one.

    A hand-edited file is data, not truth: rows that do not parse as a day with
    a positive count are dropped. A junk key sorting below every real day would
    otherwise backdate the coverage and turn "not recording yet" into "quiet".
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Ledger()
    if not isinstance(raw, dict):
        return Ledger()
    days = raw.get("days")
    ledger = Ledger()
    if isinstance(days, dict):
        ledger.days = {
            day: tokens for day, tokens in days.items()
            if _is_day(day) and isinstance(tokens, int) and not isinstance(tokens, bool)
            and tokens > 0
        }
    since = raw.get("covered_since")
    if _is_day(since):
        ledger.covered_since = since
    return ledger


def save(ledger: Ledger, path: Path) -> None:
    """Write the ledger atomically, as every other file here is written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"days": ledger.days, "covered_since": ledger.covered_since}),
        encoding="utf-8",
    )
    tmp.replace(path)
