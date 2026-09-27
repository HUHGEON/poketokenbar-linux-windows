"""Provider extension point — ports UsageProvider.swift.

Adding a source means adding an implementation and a PROVIDERS entry. Never
branch on a provider id in shared code; see docs/reference/provider-extension.md.

`ScanningProvider` holds the half of that contract every file-scanning source
repeats: walk roots, parse each file (through the mtime/size cache), dedup, then
aggregate into today / week / month. Subclasses supply only what actually
differs — `roots()` and `parse_file()`.

The aggregation lives here rather than in each provider on purpose. Upstream's
extension rule is that general totals must be provider-agnostic, and the first
two ports had already drifted: Codex reimplemented `fetch_daily` and never grew
a `fetch_periods` at all, so its week and month silently read zero.
"""

from __future__ import annotations

import math
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator, Protocol

from .. import pricing
from .. import scan_roots
from ..cache import ScanCache
from ..models import CostCoverage, DailyUsage, Entry, ProviderEnrichment

try:  # orjson is ~2x faster on this workload but must not be required
    import orjson

    def loads(raw: str | bytes):
        return orjson.loads(raw)

except ModuleNotFoundError:  # pragma: no cover - exercised on hosts without orjson
    import json

    def loads(raw: str | bytes):
        return json.loads(raw)


class UsageProvider(Protocol):
    id: str
    display_name: str
    reports_cost: bool

    def fetch_daily(self, today: str | None = None) -> DailyUsage | None:
        """Today's totals. None when the source is absent or unused today."""
        ...

    def fetch_enrichment(self) -> ProviderEnrichment:
        """Blocks and period totals. Best effort; never raises."""
        ...


# MARK: shared parsing helpers


# Parsing ceiling — 100,000x real-world usage (billions), so it never truncates a
# genuine total. Ports LocalUsageReader.maxParsedTokenValue.
#
# Swift needs the ceiling below Int.max because `output + thoughts` is summed right
# after parsing and would trap on overflow. Python ints do not overflow, but the
# clamp still has to match: an uncapped `1e30` from one corrupt record would swamp
# the day's totals and hand the companion a nonsense lifetime spend.
MAX_PARSED_TOKEN_VALUE = 1_000_000_000_000_000


def number(value) -> float | None:
    """A finite JSON number, or None. Mirrors Swift's `doubleOrNil`.

    None means "no figure here" — a missing key, a JSON null, a string, or a
    non-finite value. Callers rely on that being distinguishable from 0, which
    is a real reading of zero.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):  # NaN / ±Inf
        return None
    return float(value)


def int_or_none(value) -> int | None:
    """A token count, or None when the field carries no number.

    Mirrors Swift's `intOrNil`: negatives collapse to 0 (there is no such thing
    as negative tokens) and anything at or above the ceiling clamps to it, but a
    missing or unparseable field stays None so callers can tell "absent" from
    "zero". Several providers branch on exactly that difference — treating a
    JSON null as present would subtract a cache read that was never reported.

    Bools are refused: `isinstance(True, int)` is True in Python, and a bool in a
    token field is a schema error, not the number 1.
    """
    raw = number(value)
    if raw is None:
        return None
    if raw <= 0:
        return 0
    if raw >= MAX_PARSED_TOKEN_VALUE:
        return MAX_PARSED_TOKEN_VALUE
    return int(raw)


def to_int(value) -> int:
    """`int_or_none` with absent folded into 0, for fields with no such branch."""
    parsed = int_or_none(value)
    return 0 if parsed is None else parsed


def parse_iso(raw: str) -> datetime | None:
    """ISO-8601 with a trailing 'Z' and optional fractional seconds."""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def local_day(date: datetime) -> str:
    """The calendar day the entry belongs to, in the machine's own timezone."""
    return date.astimezone().strftime("%Y-%m-%d")


def dedup_keep_max(entries: list[Entry]) -> list[Entry]:
    """Keep the largest-total entry per id — the completed one.

    The turn's time is the earliest of the copies, not the kept one's. Forking
    or resuming a session logs the same turn again, with a later timestamp, and
    whichever copy happens to hold the larger total would otherwise decide
    which day the tokens fall on — moving usage into a day it did not happen in
    (upstream e76a8e0).
    """
    by_id: dict[str, Entry] = {}
    for e in entries:
        existing = by_id.get(e.id)
        if existing is None:
            by_id[e.id] = e
            continue
        kept = e if e.total > existing.total else existing
        earliest = e if e.date < existing.date else existing
        if kept.date != earliest.date:
            kept.date = earliest.date
            kept.local_day = earliest.local_day
        by_id[e.id] = kept
    return list(by_id.values())


def dedup_keep_first(entries: list[Entry]) -> list[Entry]:
    """Keep the first entry per id.

    For sources whose turns are replayed verbatim into forked or resumed
    sessions: every copy carries the same numbers, so the later ones add
    nothing and 'largest wins' would be a coin flip between equals.
    """
    by_id: dict[str, Entry] = {}
    for e in entries:
        by_id.setdefault(e.id, e)
    return list(by_id.values())


# MARK: scanning provider


class ScanningProvider:
    """A usage source that is a tree of files on disk.

    Subclasses set `id` / `display_name` and implement `roots()` and
    `parse_file()`. Everything below that — caching, dedup, and the today /
    week / month aggregates — is shared and must stay provider-agnostic.
    """

    id: str = ""
    display_name: str = ""
    reports_cost: bool = True
    # Bump when parse_file changes shape, to invalidate cached blobs.
    PARSER_VERSION: int = 1
    # Files worth opening under a root. Overridden by sources that also keep
    # legacy .json sessions, or that read a database instead.
    file_glob: str = "*.jsonl"

    def __init__(
        self,
        cache: ScanCache | None = None,
        home: Path | None = None,
        custom_roots: Callable[[str], str | None] | None = None,
    ) -> None:
        self._cache = cache
        self._home = home
        # A callable, not a value: the daemon reloads its config in place, and a
        # captured dict would keep serving the settings from process start.
        self._custom_roots = custom_roots

    @property
    def home(self) -> Path:
        return self._home or Path.home()

    # --- subclass contract -------------------------------------------------

    def curated_roots(self) -> list[Path]:
        """Where this source keeps its logs by default, existing or not."""
        raise NotImplementedError

    def custom_roots_value(self) -> str | None:
        """The user's extra scan folders for this provider, if any."""
        if self._custom_roots is None:
            return None
        return self._custom_roots(self.id)

    def roots(self) -> list[Path]:
        """Curated defaults plus the user's extras, folded and filtered to what exists.

        Final on purpose: a provider that overrode this would silently stop
        honouring the extra-folders setting, which is exactly the failure the
        setting exists to fix.
        """
        return self.existing_roots(
            scan_roots.union(self.curated_roots(), self.custom_roots_value())
        )

    def parse_file(self, path: Path) -> list[Entry]:
        """Every usage entry in one file. Never raises; returns [] on damage."""
        raise NotImplementedError

    def files(self, root: Path) -> Iterator[Path]:
        """Candidate files under one root, including inside hidden directories."""
        if root.is_file():
            yield root
            return
        yield from root.rglob(self.file_glob)

    def dedup(self, entries: list[Entry]) -> list[Entry]:
        return dedup_keep_max(entries)

    def file_signature(self, path: Path) -> tuple[float, int] | None:
        """(mtime, size) the parsed-blob cache is keyed on, or None to skip.

        Overridden by the SQLite-backed sources: a WAL database can take writes
        without the main file's mtime or size moving at all, so keying on it
        alone would serve a stale blob until something else happened to touch
        the file.
        """
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_mtime, stat.st_size)

    # --- shared machinery --------------------------------------------------

    def existing_roots(self, candidates: list[Path]) -> list[Path]:
        """Drop absent roots and fold symlinked duplicates.

        Two roots resolving to one directory would parse every file twice; the
        global dedup would repair the totals but not the doubled scan cost.
        """
        seen: set[Path] = set()
        out: list[Path] = []
        for path in candidates:
            if not path.exists():
                continue
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if resolved in seen:
                continue
            seen.add(resolved)
            out.append(path)
        return out

    def scan_entries(self) -> list[Entry]:
        """Every parsed entry across all roots, globally deduplicated."""
        all_entries: list[Entry] = []
        live: set[str] = set()
        seen_files: set[str] = set()
        for root in self.roots():
            for path in sorted(self.files(root)):
                key = str(path)
                # Overlapping roots (a custom root above a curated one) would
                # otherwise parse the same file once per root.
                if key in seen_files:
                    continue
                seen_files.add(key)
                signature = self.file_signature(path)
                if signature is None:
                    continue
                mtime, size = signature
                live.add(key)
                entries = None
                if self._cache is not None:
                    entries = self._cache.get(
                        self.id, path, mtime, size, self.PARSER_VERSION
                    )
                if entries is None:
                    entries = self.parse_file(path)
                    if self._cache is not None:
                        self._cache.put(
                            self.id, path, mtime, size, self.PARSER_VERSION, entries
                        )
                all_entries.extend(entries)
        if self._cache is not None:
            self._cache.prune(self.id, live)
        return self.dedup(all_entries)

    def cost_of(self, entry: Entry) -> tuple[float, CostCoverage]:
        """One entry's cost and where it came from. Ports upstream's Bucket.add.

        Priced per entry, because a day mixes models with different rates. A
        recorded cost wins, zero included; then the price table, unless the
        entry cannot be priced; otherwise the entry is unpriced. A zero-token
        entry counts for nothing, so a replayed record cannot make an
        unpriced total look partly priced.
        """
        if entry.total <= 0:
            return 0.0, CostCoverage()
        recorded = entry.explicit_cost
        if recorded is not None and math.isfinite(recorded) and recorded >= 0:
            if entry.cost_is_estimate:
                return recorded, CostCoverage(estimated=True)
            return recorded, CostCoverage(reported=True)
        if not entry.cost_unavailable:
            estimate = pricing.estimated_cost(
                entry.model, entry.input, entry.output, entry.cache_write, entry.cache_read)
            if estimate is not None:
                return estimate, CostCoverage(estimated=True)
            # A missing price row is the cause here, and nothing else says so
            # (upstream 5f6a4f0). Where the source itself declared the cost
            # unavailable, the table is not to blame.
            pricing.note_unpriced(entry.model)
        return 0.0, CostCoverage(unknown=True)

    def fetch_daily(self, today: str | None = None) -> DailyUsage | None:
        """Today's totals, or None when the source did nothing today.

        A record with no tokens is not activity (upstream a910767): a synthetic
        assistant turn would otherwise surface a provider row reading zero
        tokens and no cost, as if the tool had been used.
        """
        day = today or _date.today().strftime("%Y-%m-%d")
        entries = [e for e in self.scan_entries() if e.local_day == day]
        if not any(e.total > 0 for e in entries):
            return None
        return self.aggregate_daily(day, entries)

    def aggregate_daily(self, day: str, entries: list[Entry]) -> DailyUsage:
        daily = DailyUsage(date=day)
        for e in entries:
            daily.input_tokens += e.input
            daily.output_tokens += e.output
            daily.cache_creation_tokens += e.cache_write
            daily.cache_read_tokens += e.cache_read
            amount, coverage = self.cost_of(e)
            daily.total_cost += amount
            daily.cost_coverage.merge(coverage)
            daily.models[e.model] = daily.models.get(e.model, 0) + e.total
        daily.total_tokens = (
            daily.input_tokens
            + daily.output_tokens
            + daily.cache_creation_tokens
            + daily.cache_read_tokens
        )
        return daily

    def fetch_periods(self, today: str | None = None) -> dict:
        """Week-to-date and month-to-date totals.

        The week starts Monday, matching the Swift period grouping.
        """
        day = today or _date.today().strftime("%Y-%m-%d")
        anchor = datetime.strptime(day, "%Y-%m-%d").date()
        week_start = anchor - timedelta(days=anchor.weekday())
        month_prefix = day[:7]

        week = {"tokens": 0, "cost": 0.0, "coverage": CostCoverage()}
        month = {"tokens": 0, "cost": 0.0, "coverage": CostCoverage()}
        # Every day from the 1st through today, empty days included: a bar's
        # position is its date (upstream 0912c68). Days are built from the
        # month rather than from the entries, so a session carried over from
        # last month cannot add a partial, untrue previous month.
        month_daily = {
            f"{month_prefix}-{number:02d}": {"tokens": 0, "cost": 0.0, "coverage": CostCoverage()}
            for number in range(1, anchor.day + 1)
        }
        for e in self.scan_entries():
            cost, coverage = self.cost_of(e)
            bucket = month_daily.get(e.local_day)
            if bucket is not None:
                bucket["tokens"] += e.total
                bucket["cost"] += cost
                bucket["coverage"].merge(coverage)
            if e.local_day[:7] == month_prefix:
                month["tokens"] += e.total
                month["cost"] += cost
                month["coverage"].merge(coverage)
            try:
                entry_day = datetime.strptime(e.local_day, "%Y-%m-%d").date()
            except ValueError:
                continue
            if week_start <= entry_day <= anchor:
                week["tokens"] += e.total
                week["cost"] += cost
                week["coverage"].merge(coverage)
        return {"week": week, "month": month, "month_daily": month_daily}

    def fetch_enrichment(self) -> ProviderEnrichment:
        # Blocks/burn-rate remain unported; the *_ok flags stay false so callers
        # keep their previous values rather than zeroing.
        return ProviderEnrichment()
