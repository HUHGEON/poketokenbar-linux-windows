"""The Qt tray's reset clock matches the extension's (upstream f2fe5ac)."""

from datetime import datetime, timedelta, timezone

from poketokenbar import l10n
from poketokenbar.format import reset_clock


def t(key):
    return l10n.t(key, "en")


def test_near_resets_are_just_the_time():
    now = datetime(2026, 9, 17, 9, 0).astimezone()
    assert reset_clock((now + timedelta(hours=5)).isoformat(), t, now) == (
        f" ({(now + timedelta(hours=5)).strftime('%H:%M')})")


def test_far_resets_name_the_weekday_and_day():
    now = datetime(2026, 9, 17, 9, 0).astimezone()
    later = now + timedelta(days=2, hours=1)
    assert reset_clock(later.isoformat(), t, now) == f" (Sat 19, {later.strftime('%H:%M')})"


def test_nothing_for_the_past():
    now = datetime.now(timezone.utc)
    assert reset_clock((now - timedelta(minutes=1)).isoformat(), t, now) == ""
