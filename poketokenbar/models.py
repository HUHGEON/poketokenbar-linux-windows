"""Usage data models — ports Sources/PokeTokenBar/Core/Models.swift."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class Entry:
    """One assistant turn's token usage, as parsed from a provider log line."""

    id: str
    date: datetime
    local_day: str
    model: str
    input: int = 0
    output: int = 0
    cache_write: int = 0
    cache_read: int = 0
    # Source-reported amounts, including zero, take precedence over estimates.
    explicit_cost: float | None = None
    cost_is_estimate: bool = False
    cost_unavailable: bool = False
    session_id: str | None = None
    session_ids: list[str] = field(default_factory=list)

    @property
    def claude_session_ids(self) -> list[str]:
        return sorted(set(self.session_ids + ([self.session_id] if self.session_id else [])))

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_write + self.cache_read


@dataclass(slots=True)
class CostCoverage:
    """Provenance of an amount; a reported amount need not be an invoice."""

    reported: bool = False
    estimated: bool = False
    unknown: bool = False

    def merge(self, other: CostCoverage) -> None:
        self.reported |= other.reported
        self.estimated |= other.estimated
        self.unknown |= other.unknown

    @property
    def has_known(self) -> bool:
        return self.reported or self.estimated


@dataclass(slots=True)
class DailyUsage:
    date: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    # Per-model totals when the source has a historical model identity.
    models: dict[str, int] = field(default_factory=dict)
    cost_coverage: CostCoverage = field(default_factory=CostCoverage)


@dataclass(slots=True)
class BlockUsage:
    id: str
    start_time: str
    end_time: str
    is_active: bool = False
    total_tokens: int = 0
    cost_usd: float = 0.0
    tokens_per_minute: float | None = None
    cost_coverage: CostCoverage = field(default_factory=CostCoverage)


@dataclass(slots=True)
class PeriodUsage:
    period: str
    total_tokens: int = 0
    total_cost: float = 0.0
    cost_coverage: CostCoverage = field(default_factory=CostCoverage)


@dataclass(slots=True)
class ProviderEnrichment:
    """Best-effort detail. The *_ok flags distinguish 'failed' from 'empty' —
    on failure the caller keeps its previous values instead of zeroing them.
    """

    active_block: BlockUsage | None = None
    blocks_ok: bool = False
    week_total: PeriodUsage | None = None
    month_total: PeriodUsage | None = None
    periods_ok: bool = False
