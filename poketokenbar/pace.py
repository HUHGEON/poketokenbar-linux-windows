"""Pace against a limit window — ports PaceTier.swift and paceFraction.

A limit gauge showing 71% says nothing about whether that is fast: 71% half an
hour into a five-hour window and 71% with ten minutes left are opposite
situations. Pace is how much of the window has elapsed, and the tier is how far
the utilization is ahead of it.

Warnings, notifications and the desktop pet keep judging on absolute
thresholds. This only decides how a gauge is coloured, and where the pace mark
sits on it.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

FIVE_HOUR = 5 * 3600
SEVEN_DAY = 7 * 24 * 3600

# Below this much of the window elapsed, the tier is held back: pace is near
# zero at the start, where a single request swings the delta by whole tiers.
# 30 minutes of a five-hour window, about 17 hours of a weekly one.
MINIMUM_PACE = 0.1

# Slowest to fastest. The order is the comparison: is_calm is "on pace or
# slower", and a UI maps each name to one colour.
TIERS = ("way_under", "under", "on_pace", "slightly_over", "over", "way_over")

# How each window's length is known. Providers report it differently — Codex in
# minutes, Claude by window kind — so the conversion lives here rather than
# leaking a provider branch into the UI.
_SPANS = {"session": FIVE_HOUR, "weekly": SEVEN_DAY}


def span_for(kind: str) -> float | None:
    """The length of a named window, or None when it is not a known kind."""
    return _SPANS.get(kind)


def span_from_minutes(minutes: int | None) -> float | None:
    """A window length reported in minutes. Zero or less is not a length."""
    if not minutes or minutes <= 0:
        return None
    return float(minutes) * 60


def fraction(resets_at: str | None, span: float | None, now: float | None = None) -> float | None:
    """How much of the window has elapsed, 0…1, or None when it cannot be told.

    Outside 0…1 the answer is None rather than a clamp: a five-hour window only
    starts on the first request, so an idle machine can be holding a resets_at
    from a window that has already passed, and pinning that to either end of the
    bar would claim the window had just started or was about to end. A mark in
    the wrong place is worse than no mark.
    """
    if not resets_at or not span or span <= 0:
        return None
    reset = instant(resets_at)
    if reset is None:
        return None
    elapsed = (span - (reset - (time.time() if now is None else now))) / span
    if elapsed != elapsed or elapsed in (float("inf"), float("-inf")):
        return None
    if not 0.0 <= elapsed <= 1.0:
        return None
    return elapsed


def rounded_delta(utilization: float, pace: float) -> int:
    """Utilization minus pace, in percentage points, as the tooltip says it."""
    return round(utilization - pace * 100)


def tier(utilization: float, pace: float | None, crit: float = 95) -> str | None:
    """The pace tier, or None when there is no pace to judge against.

    The boundaries are the same for every window: the delta is already
    normalised by the window's own length. Judged on the real utilization, so
    showing the remaining percentage instead cannot change the colour.
    """
    if pace is None or pace < MINIMUM_PACE:
        return None
    if utilization >= crit:
        return "way_over"
    delta = rounded_delta(utilization, pace)
    if delta < -25:
        return "way_under"
    if delta < -10:
        return "under"
    if delta < 5:
        return "on_pace"
    if delta < 15:
        return "slightly_over"
    if delta < 30:
        return "over"
    return "way_over"


def gauge(utilization: float, pace: float | None, warn: float = 80, crit: float = 95) -> str:
    """The tier a gauge is drawn in, with or without a pace.

    A row with no pace — or still inside the early-window hold — maps the
    absolute thresholds onto the same six names, so the popup gauge and the
    panel percentage cannot disagree about what colour means what.
    """
    judged = tier(utilization, pace, crit)
    if judged is not None:
        return judged
    if utilization >= crit:
        return "way_over"
    if utilization >= warn:
        return "over"
    return "on_pace"


def is_calm(name: str) -> bool:
    """On pace or slower — nothing to act on yet."""
    return name in TIERS and TIERS.index(name) <= TIERS.index("on_pace")


def instant(value) -> float | None:
    """A reset instant as epoch seconds, or None when it cannot be read.

    ISO-8601, or a bare number: providers report the same thing both ways, and
    a number may be in seconds or in milliseconds (upstream d888793). A naive
    stamp is read as UTC, as everything else in this port does: the limits API
    always answers in UTC, and guessing local time would move the mark by
    hours.
    """
    if value is None:
        return None
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        pass
    else:
        # Milliseconds past some point in 33000 AD is not a plausible second.
        if number > 1_000_000_000_000:
            return number / 1000.0
        if number > 100_000_000:
            return number
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()
