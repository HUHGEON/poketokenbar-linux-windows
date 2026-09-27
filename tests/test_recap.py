"""The usage recap and the ledger behind it — ports UsageRecapTests.swift
(upstream 78595ed)."""

import json
from datetime import date

import pytest

from poketokenbar import ledger as ledger_module
from poketokenbar import recap


def _ledger(**days):
    out = ledger_module.Ledger()
    out.merge({day.replace("_", "-"): tokens for day, tokens in days.items()})
    return out


# --- the ledger -------------------------------------------------------------


def test_a_day_never_goes_down():
    """A rotated or pruned log makes a provider report less than it did
    yesterday, and the recap would lose days that really happened."""
    book = _ledger(**{"2026_09_01": 500})
    book.merge({"2026-09-01": 100})
    assert book.tokens("2026-09-01") == 500
    book.merge({"2026-09-01": 900})
    assert book.tokens("2026-09-01") == 900


def test_coverage_starts_at_the_earliest_day_a_series_carried():
    """The series lists every day since the 1st, empty ones included, so the
    whole stretch was scanned — that is what makes a zero a real zero."""
    book = ledger_module.Ledger()
    book.merge({"2026-09-01": 0, "2026-09-02": 10})
    assert book.covered_since == "2026-09-01"
    assert book.knows("2026-09-01") and not book.knows("2026-08-31")
    book.merge({"2026-08-01": 0, "2026-08-02": 5})
    assert book.covered_since == "2026-08-01"


def test_pruning_makes_the_dropped_days_unknown_again_not_empty():
    book = _ledger(**{"2025_12_31": 5, "2026_01_02": 7})
    book.prune(before="2026-01-01")
    assert book.days == {"2026-01-02": 7}
    assert not book.knows("2025-12-31")
    assert book.covered_since == "2026-01-01"


def test_a_hand_edited_file_keeps_only_what_parses(tmp_path):
    """A junk key sorting below every real day would backdate the coverage and
    turn "not recording yet" into "quiet"."""
    path = tmp_path / "usage-ledger.json"
    path.write_text(json.dumps({
        "days": {"2026-09-01": 10, "yesterday": 5, "2026-09-02": -3, "2026-13-40": 1},
        "covered_since": "not a day",
    }), encoding="utf-8")
    book = ledger_module.load(path)
    assert book.days == {"2026-09-01": 10}
    assert book.covered_since is None


def test_a_missing_or_broken_file_is_an_empty_ledger(tmp_path):
    assert ledger_module.load(tmp_path / "nothing.json").days == {}
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json", encoding="utf-8")
    assert ledger_module.load(broken).days == {}


def test_the_ledger_survives_a_round_trip(tmp_path):
    path = tmp_path / "usage-ledger.json"
    book = _ledger(**{"2026_09_01": 10})
    ledger_module.save(book, path)
    assert ledger_module.load(path) == book


# --- periods ----------------------------------------------------------------


def test_a_week_runs_monday_to_sunday():
    period = recap.period_of("week", date(2026, 9, 17))   # a Thursday
    assert period.start == date(2026, 9, 14) and period.end == date(2026, 9, 21)


def test_months_and_years_are_calendar_periods():
    month = recap.period_of("month", date(2026, 9, 17))
    assert month.start == date(2026, 9, 1) and month.end == date(2026, 10, 1)
    year = recap.period_of("year", date(2026, 9, 17))
    assert year.start == date(2026, 1, 1) and year.end == date(2027, 1, 1)


@pytest.mark.parametrize("scope,start,offset,expected", [
    ("week", date(2026, 9, 17), -1, date(2026, 9, 7)),
    ("month", date(2026, 1, 15), -1, date(2025, 12, 1)),
    ("month", date(2026, 12, 15), 1, date(2027, 1, 1)),
    ("year", date(2026, 3, 3), -2, date(2024, 1, 1)),
])
def test_stepping_lands_on_the_neighbouring_period(scope, start, offset, expected):
    assert recap.shifted(recap.period_of(scope, start), offset).start == expected


# --- the recap --------------------------------------------------------------


def _september():
    return _ledger(**{f"2026_09_{day:02d}": day * 100 for day in range(1, 18)})


def test_a_running_period_counts_only_the_days_that_have_happened():
    found = recap.make(_september(), recap.period_of("month", date(2026, 9, 17)),
                       today=date(2026, 9, 17))
    assert found.total == sum(day * 100 for day in range(1, 18))
    assert found.is_in_progress
    assert found.active_days == 17 and found.counted_days == 17
    assert found.best_day == ("2026-09-17", 1700)
    assert found.best_streak == 17


def test_the_future_is_unknown_rather_than_zero():
    found = recap.make(_september(), recap.period_of("month", date(2026, 9, 17)),
                       today=date(2026, 9, 17))
    future = [bucket for bucket in found.buckets if bucket.key > "2026-09-17"]
    assert future and not any(bucket.has_data for bucket in future)


def test_days_before_the_ledger_started_are_unknown_too():
    book = _ledger(**{"2026_09_10": 500})
    found = recap.make(book, recap.period_of("month", date(2026, 9, 17)),
                       today=date(2026, 9, 17))
    early = next(bucket for bucket in found.buckets if bucket.key == "2026-09-05")
    assert not early.has_data
    assert found.counted_days == 8   # the 10th through the 17th


def test_a_running_period_is_compared_over_the_same_number_of_days():
    """The 18th of the month would otherwise read as a huge drop against a
    whole month."""
    book = _ledger(**{f"2026_08_{day:02d}": 100 for day in range(1, 32)})
    book.merge({f"2026-09-{day:02d}": 100 for day in range(1, 11)})
    found = recap.make(book, recap.period_of("month", date(2026, 9, 10)),
                       today=date(2026, 9, 10))
    assert found.total == 1000
    assert found.previous_total == 1000   # the 1st to the 10th of August
    assert found.delta == 0


def test_there_is_no_comparison_the_ledger_cannot_vouch_for():
    """Days nobody recorded would count as zero and invent a jump."""
    found = recap.make(_september(), recap.period_of("month", date(2026, 9, 17)),
                       today=date(2026, 9, 17))
    assert found.previous_total is None and found.delta is None
    assert not found.can_go_back


def test_stepping_back_is_offered_once_the_ledger_reaches_there():
    book = _ledger(**{"2026_08_31": 10, "2026_09_01": 10})
    found = recap.make(book, recap.period_of("month", date(2026, 9, 17)),
                       today=date(2026, 9, 17))
    assert found.can_go_back


def test_a_streak_is_the_longest_run_of_days_used():
    book = _ledger(**{"2026_09_01": 5, "2026_09_02": 5, "2026_09_04": 5,
                      "2026_09_05": 5, "2026_09_06": 5})
    found = recap.make(book, recap.period_of("month", date(2026, 9, 30)),
                       today=date(2026, 9, 30))
    assert found.best_streak == 3 and found.active_days == 5


def test_the_year_view_is_twelve_months():
    found = recap.make(_september(), recap.period_of("year", date(2026, 9, 17)),
                       today=date(2026, 9, 17))
    assert len(found.buckets) == 12
    september = found.buckets[8]
    assert september.tokens == sum(day * 100 for day in range(1, 18))
    assert september.is_current
    # A month that has not happened yet holds nothing to report.
    assert not found.buckets[11].has_data


def test_a_finished_period_is_compared_whole():
    book = _ledger(**{f"2026_08_{day:02d}": 100 for day in range(1, 32)})
    book.merge({f"2026-09-{day:02d}": 200 for day in range(1, 31)})
    found = recap.make(book, recap.period_of("month", date(2026, 9, 1)),
                       today=date(2026, 10, 5))
    assert not found.is_in_progress
    assert found.total == 6000 and found.previous_total == 3100


# --- the daemon's side ------------------------------------------------------


def _daemon(tmp_path, providers=None):
    from poketokenbar.daemon import Daemon

    return Daemon(state_path=tmp_path / "state.json", config_path=tmp_path / "config.json",
                  cache=None, providers=providers or [], limits_source=None)


def test_the_daemon_records_the_month_series_and_keeps_it(tmp_path):
    """Providers only report the current month, so the ledger is what makes a
    recap possible at all after the 1st."""
    daemon = _daemon(tmp_path)
    daemon._record_ledger({"month_daily": {
        "2026-09-01": {"tokens": 10, "cost": 0.0},
        "2026-09-02": {"tokens": 20, "cost": 0.0},
    }})
    assert daemon.ledger.tokens("2026-09-02") == 20
    assert ledger_module.load(daemon.ledger_path).tokens("2026-09-01") == 10

    # A later poll in the same month keeps what the month before had recorded.
    daemon._record_ledger({"month_daily": {"2026-09-01": {"tokens": 30, "cost": 0.0}}})
    assert daemon.ledger.tokens("2026-09-02") == 20
    assert daemon.ledger.tokens("2026-09-01") == 30


def test_a_poll_with_no_series_leaves_the_ledger_alone(tmp_path):
    daemon = _daemon(tmp_path)
    daemon._record_ledger({"month_daily": {"2026-09-01": {"tokens": 10, "cost": 0.0}}})
    daemon._record_ledger({})
    daemon._record_ledger(None)
    assert daemon.ledger.days == {"2026-09-01": 10}


def test_the_recap_page_opens_steps_and_closes(tmp_path):
    from poketokenbar import commands

    daemon = _daemon(tmp_path)
    daemon.spool = tmp_path / "spool"
    assert daemon.recap_view() is None

    commands.enqueue("recap", {"scope": "week", "offset": 0}, spool=daemon.spool)
    daemon._handle_commands([])
    assert daemon.recap["scope"] == "week"
    view = daemon.recap_view()
    assert view["recap"].period.scope == "week"

    commands.enqueue("recap", {"scope": "week", "offset": -2}, spool=daemon.spool)
    daemon._handle_commands([])
    assert daemon.recap["offset"] == -2

    # The future holds nothing to report, so a forward step past now is clamped.
    commands.enqueue("recap", {"scope": "week", "offset": 3}, spool=daemon.spool)
    daemon._handle_commands([])
    assert daemon.recap["offset"] == 0

    commands.enqueue("recap", {"scope": "none"}, spool=daemon.spool)
    daemon._handle_commands([])
    assert daemon.recap is None and daemon.recap_view() is None


def test_an_unknown_scope_is_an_error_not_a_page(tmp_path):
    from poketokenbar import commands

    daemon = _daemon(tmp_path)
    daemon.spool = tmp_path / "spool"
    errors = []
    commands.enqueue("recap", {"scope": "fortnight"}, spool=daemon.spool)
    daemon._handle_commands(errors)
    assert daemon.recap is None and errors


def test_the_payload_describes_the_period_in_the_users_language(tmp_path):
    from poketokenbar import state
    from poketokenbar.models import DailyUsage

    daemon = _daemon(tmp_path)
    daemon._record_ledger({"month_daily": {
        f"2026-09-{day:02d}": {"tokens": day * 100, "cost": 0.0} for day in range(1, 18)
    }})
    daemon.recap = {"scope": "month", "offset": 0}
    payload = state.build(
        {"claude_code": DailyUsage(date="2026-09-17", total_tokens=1)},
        {"language": "ko"}, [], recap=daemon.recap_view(),
    )
    found = payload["recap"]
    assert found["scope"] == "month"
    assert found["title"].endswith("월")
    assert len(found["buckets"]) in (28, 29, 30, 31)
    assert found["buckets"][0]["label"] == "1"
    assert found["total_text"] and found["total_grouped"]
