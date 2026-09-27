"""Usage recap for a week, a month or a year — ports UsageRecap (78595ed).

Read-only, computed on demand from the daily ledger and the Pokédex. Nothing
here is a goal or a reward: it reports what already happened, so the app still
asks nothing of anyone.

Calendar periods rather than rolling windows, so stepping back lands on "the
week of the 7th" rather than on an arbitrary seven days. Weeks start on Monday,
as every other period in this port does.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date as _date
from datetime import timedelta

SCOPES = ("week", "month", "year")


@dataclass(frozen=True, slots=True)
class Period:
    """One calendar week, month or year: [start, end)."""

    scope: str
    start: _date
    end: _date

    @property
    def days(self) -> list[_date]:
        out = []
        cursor = self.start
        while cursor < self.end:
            out.append(cursor)
            cursor += timedelta(days=1)
        return out


def period_of(scope: str, day: _date) -> Period:
    """The week, month or year that holds `day`."""
    if scope == "week":
        start = day - timedelta(days=day.weekday())
        return Period(scope, start, start + timedelta(days=7))
    if scope == "month":
        start = day.replace(day=1)
        end = (start.replace(year=start.year + 1, month=1) if start.month == 12
               else start.replace(month=start.month + 1))
        return Period(scope, start, end)
    if scope == "year":
        start = day.replace(month=1, day=1)
        return Period(scope, start, start.replace(year=start.year + 1))
    raise ValueError(f"unknown recap scope: {scope}")


def shifted(period: Period, offset: int) -> Period:
    """The same scope, `offset` periods away — negative for the past."""
    if period.scope == "week":
        return period_of("week", period.start + timedelta(weeks=offset))
    if period.scope == "year":
        return period_of("year", period.start.replace(year=period.start.year + offset))
    # Months are not a fixed number of days, so they are counted, not added.
    total = period.start.year * 12 + (period.start.month - 1) + offset
    return period_of("month", _date(total // 12, total % 12 + 1, 1))


@dataclass(frozen=True, slots=True)
class Bucket:
    """One meter: a day in the week and month views, a month in the year view."""

    key: str
    tokens: int
    is_current: bool
    # False for the future, and for days before the ledger started: those are
    # unknown, not zero, and a bar drawn at zero would claim otherwise.
    has_data: bool


@dataclass(frozen=True, slots=True)
class Recap:
    period: Period
    buckets: list[Bucket] = field(default_factory=list)
    total: int = 0
    is_in_progress: bool = False
    # The period before this one, over the same number of days while this one
    # is running. None when the ledger does not reach its first day: days
    # nobody recorded would count as zero and invent a jump.
    previous_total: int | None = None
    best_day: tuple[str, int] | None = None
    active_days: int = 0
    counted_days: int = 0
    best_streak: int = 0
    can_go_back: bool = False

    @property
    def delta(self) -> float | None:
        if not self.previous_total:
            return None
        return (self.total - self.previous_total) / self.previous_total


def make(ledger, period: Period, today: _date) -> Recap:
    """The recap for one period, as the ledger can vouch for it."""
    key = lambda day: day.isoformat()  # noqa: E731
    elapsed = [day for day in period.days if day <= today]

    streak = best_streak = 0
    for day in elapsed:
        streak = streak + 1 if ledger.tokens(key(day)) > 0 else 0
        best_streak = max(best_streak, streak)

    buckets: list[Bucket] = []
    if period.scope == "year":
        for index in range(12):
            start = _date(period.start.year, index + 1, 1)
            end = start + timedelta(days=monthrange(start.year, start.month)[1])
            month_days = [d for d in _between(start, end) if d <= today]
            buckets.append(Bucket(
                key=key(start),
                tokens=sum(ledger.tokens(key(d)) for d in month_days),
                is_current=start <= today < end,
                has_data=any(ledger.knows(key(d)) for d in month_days),
            ))
    else:
        for day in period.days:
            buckets.append(Bucket(
                key=key(day),
                tokens=ledger.tokens(key(day)),
                is_current=day == today,
                has_data=day <= today and ledger.knows(key(day)),
            ))

    in_progress = period.start <= today < period.end
    previous = shifted(period, -1)
    previous_days = [key(day) for day in previous.days]
    # A running period is compared over the same number of days, or the 18th of
    # the month reads as a 40% drop against a whole month.
    compared = previous_days[: len(elapsed)] if in_progress else previous_days
    previous_total = (
        sum(ledger.tokens(day) for day in compared)
        if compared and ledger.covers(compared[0])
        else None
    )

    worked = [(key(day), ledger.tokens(key(day))) for day in elapsed
              if ledger.tokens(key(day)) > 0]
    return Recap(
        period=period,
        buckets=buckets,
        total=sum(tokens for _day, tokens in worked),
        is_in_progress=in_progress,
        previous_total=previous_total,
        best_day=max(worked, key=lambda pair: pair[1]) if worked else None,
        active_days=len(worked),
        counted_days=sum(1 for day in elapsed if ledger.knows(key(day))),
        best_streak=best_streak,
        can_go_back=bool(previous_days) and ledger.covers(previous_days[-1]),
    )


def _between(start: _date, end: _date) -> list[_date]:
    out = []
    cursor = start
    while cursor < end:
        out.append(cursor)
        cursor += timedelta(days=1)
    return out
