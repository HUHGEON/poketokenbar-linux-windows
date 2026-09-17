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
    # A cost the source recorded (omp, Pi, Grok, OpenCode, Hermes). Preferred
    # over the price table, zero included: upstream 69ff39b stopped reading 0
    # as "no figure". It is what the tool wrote, not necessarily a charge.
    explicit_cost: float | None = None
    # The recorded cost is the tool's own estimate rather than a reported one.
    cost_is_estimate: bool = False
    # No price-table estimate is possible: the model is only a session-wide
    # guess, or the token split cannot be recovered. Without a recorded cost
    # the entry counts as unpriced.
    cost_unavailable: bool = False

    @property
    def total(self) -> int:
        return self.input + self.output + self.cache_write + self.cache_read


@dataclass(slots=True)
class CostCoverage:
    """Where a total's money came from — ports upstream's CostCoverage.

    A total can mix all three: some usage with a recorded cost, some priced
    from the table, some that could not be priced at all.
    """

    reported: bool = False
    estimated: bool = False
    unknown: bool = False

    @property
    def has_known(self) -> bool:
        return self.reported or self.estimated

    @property
    def only_unknown(self) -> bool:
        """Nothing could be priced, so the amount is not a number to show."""
        return self.unknown and not self.has_known

    def merge(self, other: "CostCoverage") -> None:
        self.reported = self.reported or other.reported
        self.estimated = self.estimated or other.estimated
        self.unknown = self.unknown or other.unknown


@dataclass(slots=True)
class DailyUsage:
    date: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    cost_coverage: CostCoverage = field(default_factory=CostCoverage)
    # Tokens per model id for the day. Upstream fills this for one opt-in
    # provider; here every source records a real model id, so it is collected
    # for all of them and the UI decides when a breakdown is worth showing.
    # A per-provider opt-in would be exactly the kind of id-keyed branch the
    # extension rules keep out of shared aggregation.
    models: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class BlockUsage:
    id: str
    start_time: str
    end_time: str
    is_active: bool = False
    total_tokens: int = 0
    cost_usd: float = 0.0
    tokens_per_minute: float | None = None


@dataclass(slots=True)
class PeriodUsage:
    period: str
    total_tokens: int = 0
    total_cost: float = 0.0


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
