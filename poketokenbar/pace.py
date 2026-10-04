"""Quota window timing and the upstream six-tier pace palette."""

from __future__ import annotations

import math
from datetime import datetime, timezone

TIERS = ("way_under", "under", "on_pace", "slightly_over", "over", "way_over")


def window_pace(resets_at, duration_seconds, now=None) -> float | None:
    if not resets_at or not duration_seconds or duration_seconds <= 0:
        return None
    try:
        reset = datetime.fromisoformat(resets_at.replace("Z", "+00:00")) if isinstance(resets_at, str) else resets_at
        if reset.tzinfo is None:
            reset = reset.replace(tzinfo=timezone.utc)
        remaining = (reset - (now or datetime.now(timezone.utc))).total_seconds()
    except (ValueError, TypeError, AttributeError):
        return None
    if not math.isfinite(remaining) or not 0 <= remaining <= duration_seconds:
        return None
    return 1 - remaining / duration_seconds


def rounded_delta(utilization: float, pace: float) -> int:
    delta = utilization - pace * 100
    return math.floor(delta + .5) if delta >= 0 else math.ceil(delta - .5)


def pace_tier(utilization: float, pace: float | None, crit: float = 95) -> str | None:
    if pace is None or not math.isfinite(pace) or pace < .1:
        return None
    if utilization >= crit:
        return "way_over"
    delta = rounded_delta(utilization, pace)
    for boundary, tier in zip((-25, -10, 5, 15, 30), TIERS):
        if delta < boundary:
            return tier
    return "way_over"


def gauge_tier(utilization: float, pace: float | None, warn: float = 80, crit: float = 95) -> str:
    return pace_tier(utilization, pace, crit) or (
        "way_over" if utilization >= crit else "over" if utilization >= warn else "on_pace")


def marker_fraction(pace: float | None, mode: str = "used") -> float | None:
    return None if pace is None else 1 - pace if mode == "remaining" else pace
