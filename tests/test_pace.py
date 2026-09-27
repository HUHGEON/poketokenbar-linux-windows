"""Pace against a limit window — ports PaceTierTests and paceFraction (upstream
68deb09, 2eec9af, b32717f)."""

import time
from datetime import datetime, timedelta, timezone

import pytest

from poketokenbar import pace


def resets_in(seconds: float, now: float | None = None) -> str:
    base = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    return (base + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


# --- how far through the window we are --------------------------------------


def test_the_elapsed_fraction_comes_from_the_reset_and_the_span():
    now = time.time()
    # An hour left of five: four fifths gone.
    assert pace.fraction(resets_in(3600, now), pace.FIVE_HOUR, now) == pytest.approx(0.8, abs=1e-6)
    # A window that has only just started. A second in, not exactly zero: a
    # reset one tick beyond the window's own length is outside it, and outside
    # has no pace at all.
    just_started = pace.fraction(resets_in(pace.SEVEN_DAY - 1, now), pace.SEVEN_DAY, now)
    assert 0 < just_started < 0.001


@pytest.mark.parametrize("seconds", [-60, pace.FIVE_HOUR + 60])
def test_a_reset_outside_the_window_has_no_pace_rather_than_a_clamped_one(seconds):
    """A five-hour window only starts on the first request, so an idle machine
    can hold a resets_at from a window that has already gone. Pinning that to
    either end would claim the window had just started or was about to end."""
    assert pace.fraction(resets_in(seconds), pace.FIVE_HOUR) is None


@pytest.mark.parametrize("resets_at,span", [
    (None, pace.FIVE_HOUR),
    ("", pace.FIVE_HOUR),
    ("not a date", pace.FIVE_HOUR),
    (resets_in(60), None),
    (resets_in(60), 0),
])
def test_without_both_halves_there_is_no_pace(resets_at, span):
    assert pace.fraction(resets_at, span) is None


def test_a_span_is_known_by_the_window_kind_or_reported_in_minutes():
    assert pace.span_for("session") == 5 * 3600
    assert pace.span_for("weekly") == 7 * 24 * 3600
    assert pace.span_for("whatever") is None
    assert pace.span_from_minutes(300) == 5 * 3600
    assert pace.span_from_minutes(0) is None and pace.span_from_minutes(None) is None


# --- the six tiers ----------------------------------------------------------


@pytest.mark.parametrize("utilization,expected", [
    (10, "way_under"),   # 40 points behind
    (35, "under"),       # 15 behind
    (48, "on_pace"),     # 2 behind
    (54, "on_pace"),      # 4 ahead, still on pace
    (60, "slightly_over"),
    (70, "over"),
    (85, "way_over"),
])
def test_the_tier_is_the_distance_from_the_pace(utilization, expected):
    # Half way through the window, so pace = 50 points.
    assert pace.tier(utilization, 0.5, crit=95) == expected


def test_the_same_boundaries_serve_every_window_length():
    """The delta is already normalised by the window's own length, so a weekly
    window needs no boundaries of its own."""
    for elapsed in (0.2, 0.4, 0.6):
        assert pace.tier(elapsed * 100 + 20, elapsed) == "over"


def test_crossing_the_critical_threshold_is_always_the_top_tier():
    assert pace.tier(96, 0.99, crit=95) == "way_over"


def test_the_tier_is_held_back_early_in_the_window():
    """Pace is near zero at the start, where one request swings the delta by
    whole tiers."""
    assert pace.tier(40, 0.05) is None
    assert pace.tier(40, pace.MINIMUM_PACE) is not None


def test_without_a_pace_there_is_no_tier():
    assert pace.tier(40, None) is None


# --- the gauge, which always has an answer ----------------------------------


def test_a_gauge_with_no_pace_falls_back_to_the_absolute_bands():
    assert pace.gauge(10, None, warn=80, crit=95) == "on_pace"
    assert pace.gauge(80, None, warn=80, crit=95) == "over"
    assert pace.gauge(95, None, warn=80, crit=95) == "way_over"
    # And so does a row still inside the early-window hold.
    assert pace.gauge(85, 0.01, warn=80, crit=95) == "over"


def test_a_gauge_with_a_pace_uses_the_tier():
    assert pace.gauge(20, 0.9, warn=80, crit=95) == "way_under"


def test_on_pace_or_slower_is_calm():
    assert [name for name in pace.TIERS if pace.is_calm(name)] == [
        "way_under", "under", "on_pace"]
    assert not pace.is_calm("whatever")
