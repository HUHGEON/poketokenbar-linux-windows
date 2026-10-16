"""Number formatting — ports Sources/PokeTokenBar/Core/TokenFormatter.swift.

Thresholds and decimal counts are copied verbatim; changing them changes what
the panel shows.
"""

from datetime import datetime, timezone



def _trim(value: float, decimals: int) -> str:
    s = f"{value:.{decimals}f}"
    s = s.rstrip("0").rstrip(".")
    return s


def compact(value: int) -> str:
    """987 -> '987', 12345 -> '12.3K', 190612940 -> '190.6M', 1.24e9 -> '1.24B'.

    The unit changes where its *rounded* text would overflow, not at the round
    number: K and M carry one decimal, so 999,950 reads "1M" rather than
    "1000.0K" (upstream 4cab9f0).
    """
    v = float(abs(value))
    sign = "-" if value < 0 else ""
    if v < 1_000:
        return str(value)
    if v < 999_950:
        return sign + _trim(v / 1_000, 1) + "K"
    if v < 999_950_000:
        return sign + _trim(v / 1_000_000, 1) + "M"
    return sign + _trim(v / 1_000_000_000, 2) + "B"


def grouped(value: int) -> str:
    """Thousands separators for popup detail — 190612940 -> '190,612,940'."""
    return f"{value:,}"


def cost(usd: float) -> str:
    return f"${usd:.2f}"


def cost_compact(usd: float) -> str:
    """Panel cost: $9.5 / $311 / $12.0K.

    Each band is chosen from the text it would print, not from the raw value:
    branching on 99.96 and then rounding printed "$100.0", which is the band
    above (upstream 711fca7).
    """
    tenths = f"{usd:.1f}"
    if float(tenths) < 100:
        return f"${tenths}"
    whole = f"{usd:.0f}"
    if float(whole) < 10_000:
        return f"${whole}"
    return f"${usd / 1_000:.1f}K"


def percent(value: float) -> str:
    """79.96 reads "80%", not "80.0%": the decimal is dropped on the rounded
    text rather than on the raw value (upstream 711fca7)."""
    tenths = f"{value:.1f}"
    return (tenths[:-2] if tenths.endswith(".0") else tenths) + "%"


RESET_CLOCK_NEARBY_SECONDS = 6 * 3600
_WEEKDAY_KEYS = ("weekday_mon", "weekday_tue", "weekday_wed", "weekday_thu",
                 "weekday_fri", "weekday_sat", "weekday_sun")


def reset_clock(iso: str | None, strings, now: datetime | None = None) -> str:
    """" (14:30)", or " (Thu 17, 09:00)" when the reset is not today and more
    than six hours off. Mirrors resetClock in the extension's resetclock.js."""
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    remaining = (moment - now).total_seconds()
    if remaining <= 0:
        return ""
    local, local_now = moment.astimezone(), now.astimezone()
    time = local.strftime("%H:%M")
    if local.date() == local_now.date() or remaining <= RESET_CLOCK_NEARBY_SECONDS:
        return f" ({time})"
    far = (strings("reset_clock_far").replace("%1", strings(_WEEKDAY_KEYS[local.weekday()]))
           .replace("%2", str(local.day)).replace("%3", time))
    return f" ({far})"
