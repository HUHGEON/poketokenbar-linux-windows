"""This month's day-by-day trend — ported from MonthDailyTrendTests.swift
(upstream 0912c68)."""

from datetime import datetime, timezone

import pytest

from poketokenbar import l10n, state
from poketokenbar.models import CostCoverage, Entry
from poketokenbar.providers.base import ScanningProvider


def entry(local_day, tokens, model="claude-sonnet-4-6"):
    return Entry(id=f"{local_day}-{tokens}", date=datetime(2026, 9, 1, tzinfo=timezone.utc),
                 local_day=local_day, model=model, input=tokens)


def periods(*entries, today="2026-09-17"):
    provider = ScanningProvider()
    provider.scan_entries = lambda: list(entries)
    return provider.fetch_periods(today)


def test_every_day_from_the_1st_to_today_is_present_empty_ones_as_zero():
    result = periods(entry("2026-09-03", 10), entry("2026-09-17", 5))
    series = result["month_daily"]
    assert list(series) == [f"2026-09-{n:02d}" for n in range(1, 18)]
    assert series["2026-09-02"]["tokens"] == 0
    assert series["2026-09-03"]["tokens"] == 10


def test_last_month_and_the_future_have_no_slot():
    result = periods(entry("2026-08-31", 99), entry("2026-09-18", 7), entry("2026-09-01", 1))
    series = result["month_daily"]
    assert "2026-08-31" not in series and "2026-09-18" not in series
    assert sum(day["tokens"] for day in series.values()) == 1


def test_the_series_agrees_with_the_month_total_through_today():
    result = periods(entry("2026-09-01", 3), entry("2026-09-10", 4), entry("2026-08-30", 50))
    assert sum(day["tokens"] for day in result["month_daily"].values()) == result["month"]["tokens"]


def test_the_daemon_sums_providers_on_the_union_of_their_axes(tmp_path):
    from poketokenbar.daemon import Daemon

    class Provider:
        display_name = "p"
        reports_cost = True

        def __init__(self, pid, series):
            self.id, self.series = pid, series

        def fetch_daily(self, today=None):
            return None

        def fetch_periods(self, today=None):
            bucket = {"tokens": 0, "cost": 0.0, "coverage": CostCoverage()}
            return {"week": dict(bucket), "month": dict(bucket), "month_daily": {
                day: {"tokens": tokens, "cost": 0.0, "coverage": CostCoverage()}
                for day, tokens in self.series.items()}}

    daemon = Daemon(state_path=tmp_path / "state.json", config_path=tmp_path / "c.json",
                    cache=None, providers=[
                        Provider("a", {"2026-09-01": 2, "2026-09-02": 3}),
                        Provider("b", {"2026-09-01": 5}),
                    ])
    daemon.poll_once()
    merged = daemon._last_scan[1]["month_daily"]
    assert {day: row["tokens"] for day, row in merged.items()} == {"2026-09-01": 7, "2026-09-02": 3}


def _trend(series, today="2026-09-17", language="en"):
    rows = {day: {"tokens": tokens, "cost": 0.0, "coverage": CostCoverage()}
            for day, tokens in series.items()}
    return state._month_trend({"month_daily": rows}, language, today)


def test_no_usage_all_month_draws_nothing():
    assert _trend({"2026-09-01": 0, "2026-09-02": 0}, today="2026-09-02") == {}


def test_bars_are_fractions_of_the_peak_and_today_is_marked():
    trend = _trend({"2026-09-01": 50, "2026-09-02": 0, "2026-09-03": 200}, today="2026-09-03")
    assert trend["peak_text"] == "200"
    days = trend["days"]
    assert [d["fraction"] for d in days] == [0.25, 0.0, 1.0]
    assert [d["is_today"] for d in days] == [False, False, True]
    assert days[1]["is_empty"]


def test_the_axis_labels_the_1st_every_7th_day_and_today_but_not_beside_today():
    series = {f"2026-09-{n:02d}": 1 for n in range(1, 23)}
    labels = [d["axis_label"] for d in _trend(series, today="2026-09-22")["days"]]
    assert [label for label in labels if label] == ["1", "7", "14", "22"], "21 is too close to 22"


def test_weekends_follow_the_calendar():
    days = _trend({"2026-09-18": 1, "2026-09-19": 1, "2026-09-20": 1}, today="2026-09-20")["days"]
    assert [d["is_weekend"] for d in days] == [False, True, True]


@pytest.mark.parametrize("language,stamp", [
    ("en", "Thu, 9/17"), ("ko", "9. 17. (목)"), ("ja", "9/17(木)"),
    ("fr", "jeu. 17/09"), ("de", "Do., 17.9."),
])
def test_the_readout_writes_the_day_in_the_language_order(language, stamp):
    assert l10n.day_stamp("2026-09-17", language) == stamp
    rows = {"2026-09-17": {"tokens": 1_500_000, "cost": 1.25,
                           "coverage": CostCoverage(estimated=True)}}
    days = state._month_trend({"month_daily": rows}, language, "2026-09-17")["days"]
    assert days[0]["readout"] == f"{stamp} 1.5M $1.25"
