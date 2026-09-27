"""Burn-rate forecast — when the current limit window will hit 100%.

The macOS app derives this from ccusage's `burnRate.tokensPerMinute`. We have
no ccusage, and the token→percent mapping is not published, so tokens/minute
cannot be converted into percent/minute.

Instead this samples the utilization percentage the API already reports and
fits a slope to it. That measures the thing we actually want to project, needs
no mapping, and stays correct even if Anthropic changes how usage is weighted.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

# Ignore samples older than this: a 5-hour window's early burn says little
# about the last hour.
WINDOW_SECONDS = 45 * 60
# Below this the slope is noise, not a trend.
MIN_SAMPLES = 3
# Percent-per-minute under which a forecast is meaningless (would be days out).
MIN_RATE = 0.01


@dataclass(slots=True)
class Forecast:
    rate_per_minute: float
    minutes_to_full: float | None
    eta_epoch: float | None

    @property
    def eta_text(self) -> str:
        if self.eta_epoch is None:
            return ""
        return time.strftime("%H:%M", time.localtime(self.eta_epoch))


class BurnTracker:
    """Keeps a short history of utilization samples per window kind."""

    def __init__(self, clock=time.time) -> None:
        self._clock = clock
        self._samples: dict[str, deque] = {}

    def record(self, kind: str, utilization: float) -> None:
        now = self._clock()
        series = self._samples.setdefault(kind, deque())
        # A window reset makes utilization drop sharply. Keeping the old, higher
        # samples would compute a negative slope and forecast nothing at all.
        if series and utilization < series[-1][1] - 1.0:
            series.clear()
        series.append((now, utilization))
        while series and now - series[0][0] > WINDOW_SECONDS:
            series.popleft()

    def forecast(self, kind: str) -> Forecast | None:
        series = self._samples.get(kind)
        if not series or len(series) < MIN_SAMPLES:
            return None

        first_t, first_u = series[0]
        last_t, last_u = series[-1]
        elapsed_minutes = (last_t - first_t) / 60.0
        if elapsed_minutes <= 0:
            return None

        rate = (last_u - first_u) / elapsed_minutes
        if rate < MIN_RATE:
            # Flat or falling: no meaningful ETA, but report the rate so the UI
            # can still say "holding steady".
            return Forecast(rate_per_minute=max(0.0, rate), minutes_to_full=None, eta_epoch=None)

        remaining = max(0.0, 100.0 - last_u)
        minutes = remaining / rate
        return Forecast(
            rate_per_minute=rate,
            minutes_to_full=minutes,
            eta_epoch=self._clock() + minutes * 60.0,
        )

    def payload(self, kinds=("session", "weekly")) -> dict:
        out = {}
        for kind in kinds:
            forecast = self.forecast(kind)
            if forecast is None:
                continue
            out[kind] = {
                "rate_per_minute": round(forecast.rate_per_minute, 4),
                "minutes_to_full": (
                    round(forecast.minutes_to_full) if forecast.minutes_to_full else None
                ),
                "eta_text": forecast.eta_text,
            }
        return out


# Below this the block is too small a sample for the tokens-per-percent
# estimate to mean anything, and below 5% utilization the divisor is noise.
MIN_BLOCK_RATE = 10_000
MIN_UTILIZATION = 5
# A projection further out than a day says nothing useful about a 5-hour window.
MAX_MINUTES_AHEAD = 60 * 24


@dataclass(slots=True)
class Depletion:
    """When the 5-hour window is projected to reach 100%, and whether that
    lands before it resets anyway."""

    minutes: float
    epoch: float
    before_reset: bool

    @property
    def eta_text(self) -> str:
        return time.strftime("%H:%M", time.localtime(self.epoch))


def depletion_forecast(
    utilization: float | None,
    resets_at_epoch: float | None,
    block_tokens: int,
    tokens_per_minute: float | None,
    now: float | None = None,
) -> Depletion | None:
    """Project the 5-hour limit forward — a port of UsageStore.forecastDepletion.

    The token→percent mapping is not published, so it is estimated from what
    is known: the active block's tokens divided by the utilization the API
    reports gives tokens-per-percent, and the block's own rate turns the
    remaining percent into minutes.

    This replaces sampling utilization over time as the source of the forecast
    row. The sampler needed three polls spread over minutes before it could say
    anything, so a freshly opened window showed no forecast at all — while this
    answers on the first poll, from figures that are already on hand.
    """
    if utilization is None:
        return None
    moment = time.time() if now is None else now
    if utilization >= 100:
        # Already out. Reported as depleted now rather than as no forecast.
        return Depletion(minutes=0.0, epoch=moment, before_reset=True)
    if (
        utilization < MIN_UTILIZATION
        or block_tokens <= 0
        or not tokens_per_minute
        or tokens_per_minute < MIN_BLOCK_RATE
    ):
        return None

    tokens_per_percent = block_tokens / utilization
    minutes = (100 - utilization) * tokens_per_percent / tokens_per_minute
    if minutes != minutes or minutes in (float("inf"), float("-inf")):
        return None
    if minutes >= MAX_MINUTES_AHEAD:
        return None
    epoch = moment + minutes * 60
    # No reset time means nothing to be "before": treated as reachable, which
    # is the cautious reading of a limit with an unknown reset.
    before = True if resets_at_epoch is None else epoch < resets_at_epoch
    return Depletion(minutes=minutes, epoch=epoch, before_reset=before)
