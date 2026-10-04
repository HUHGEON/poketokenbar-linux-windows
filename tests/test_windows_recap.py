from datetime import date

from poketokenbar.recap import UsageLedger, make_recap


def test_ledger_keeps_observed_high_water_and_recovers_from_bad_file(tmp_path):
    path = tmp_path / "usage-ledger.json"
    ledger = UsageLedger(path)
    ledger.merge([{"date": "2026-09-01", "total_tokens": 50},
                  {"date": "2026-09-02", "total_tokens": 0}])
    ledger.merge([{"date": "2026-09-01", "total_tokens": 20}])
    assert UsageLedger(path).tokens == {"2026-09-01": 50}
    assert ledger.covered_since == "2026-09-01"
    path.write_text("[]")
    assert UsageLedger(path).tokens == {}


def test_running_month_compares_same_number_of_days_and_marks_future_unknown(tmp_path):
    ledger = UsageLedger(tmp_path / "ledger.json")
    ledger.merge([{"date": "2026-08-01", "total_tokens": 10},
                  {"date": "2026-08-02", "total_tokens": 20},
                  {"date": "2026-08-31", "total_tokens": 999},
                  {"date": "2026-09-01", "total_tokens": 20},
                  {"date": "2026-09-02", "total_tokens": 40}])
    result = make_recap(ledger, "month", "2026-09-02", today=date(2026, 9, 2))
    assert result["total"] == 60
    assert result["previous_total"] == 30
    assert result["delta"] == 1.0
    assert result["best_streak"] == 2
    assert len(result["buckets"]) == 30
    assert result["buckets"][1]["has_data"]
    assert not result["buckets"][2]["has_data"]


def test_year_has_twelve_months_and_partial_history_is_not_zero(tmp_path):
    ledger = UsageLedger(tmp_path / "ledger.json")
    ledger.merge([{"date": "2026-09-01", "total_tokens": 30}])
    result = make_recap(ledger, "year", "2026-09-01", today=date(2026, 9, 2))
    assert len(result["buckets"]) == 12
    assert result["buckets"][8]["total_tokens"] == 30
    assert not result["buckets"][0]["has_data"]
    assert result["previous_total"] is None
    assert result["counted_days"] == 2


def test_calendar_week_crosses_year_boundary_and_excludes_releases(tmp_path):
    ledger = UsageLedger(tmp_path / "ledger.json")
    ledger.merge([{"date": "2025-12-29", "total_tokens": 5}])
    dex = [{"caught_at": "2026-01-01T10:00:00", "is_released": False},
           {"caught_at": "2026-01-02T10:00:00", "is_released": True},
           {"caught_at": "2026-01-03T10:00:00", "raising": True}]
    result = make_recap(ledger, "week", "2026-01-01", dex=dex,
                        today=date(2026, 1, 3))
    assert result["start"] == "2025-12-29"
    assert result["end"] == "2026-01-05"
    assert len(result["graduated"]) == 1
