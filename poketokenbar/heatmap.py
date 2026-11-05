"""The last sixteen weeks as a grid — ports ActivityHeatmapMetrics (upstream d4ff501).

The daily bars show this month. The grid shows the habit: one square per day,
weeks as columns and weekdays as rows, shaded by how much was used. It is
built from the ledger, the same day-by-day history the recap reads, so it
costs nothing beyond what a poll already knows.

The grid is cut into whole weeks, so every row is one weekday all the way
across; the days before the first Monday are in it but not of it, and are
drawn as gaps.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import timedelta

WEEKS = 16
DAYS_PER_WEEK = 7
# 0 is "nothing at all", and the rest splits the range into quarters. The
# boundaries are inclusive, so a day at exactly a quarter of the peak does
# not leak into the level above.
LEVELS = 4


def level(tokens: int, peak: int) -> int:
    """Which shade a day gets, 0 through 4."""
    if tokens <= 0 or peak <= 0:
        return 0
    for step in range(1, LEVELS):
        if tokens <= peak * step // LEVELS:
            return step
    return LEVELS


def grid(ledger, today: _date, weeks: int = WEEKS) -> dict:
    """Columns of seven days each, oldest first, ending on today's week.

    Every column is a Monday-to-Sunday week. Days after today, and days the
    ledger cannot vouch for, carry `known: False` so the view can leave them
    blank rather than draw them as quiet days.
    """
    end = today + timedelta(days=6 - today.weekday())        # the Sunday of this week
    start = end - timedelta(days=weeks * DAYS_PER_WEEK - 1)  # a Monday
    peak = max(
        (ledger.tokens((start + timedelta(days=offset)).isoformat())
         for offset in range(weeks * DAYS_PER_WEEK)),
        default=0,
    )

    columns = []
    for week in range(weeks):
        column = []
        for weekday in range(DAYS_PER_WEEK):
            day = start + timedelta(days=week * DAYS_PER_WEEK + weekday)
            key = day.isoformat()
            tokens = ledger.tokens(key)
            column.append({
                "date": key,
                "tokens": tokens,
                "level": level(tokens, peak),
                "is_today": day == today,
                "known": day <= today and ledger.knows(key),
            })
        columns.append(column)
    return {"columns": columns, "peak": peak, "weeks": weeks}
