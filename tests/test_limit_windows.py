"""The limit rows the popup shows, and the numbers behind them.

Three of these did not exist until the screenshots of the macOS app were
compared row by row against what this port rendered: the model-scoped weekly
window, the plan label with its multiplier, and the rolling 5-hour block the
forecast is derived from. Each was a row the original had and this did not.
"""

from datetime import datetime, timedelta, timezone

import pytest

from poketokenbar import burn, limits, state
from poketokenbar.models import BlockUsage, CostCoverage, DailyUsage


# MARK: model-scoped weekly windows


def test_a_scoped_weekly_window_is_kept_not_dropped():
    """seven_day_opus/seven_day_sonnet are null now; a model's weekly limit
    arrives only as a limits[] entry, so a parser that recognises two kinds and
    discards the rest is a row short of what the account has."""
    status = limits.parse({"limits": [
        {"kind": "session", "percent": 27},
        {"kind": "weekly_all", "percent": 8},
        {"kind": "weekly_scoped", "percent": 0.4,
         "scope": {"model": {"display_name": "Fable"}}},
    ]})
    assert status.session.utilization == 27
    assert status.weekly.utilization == 8
    assert [(w.kind, w.model, w.window.utilization) for w in status.scoped] == [
        ("weekly_scoped", "Fable", 0.4)]


def test_an_unknown_kind_is_surfaced_rather_than_swallowed():
    """The filter is on the two kinds the legacy fields already carry, not on a
    list of known scoped kinds — so a window Anthropic adds later appears."""
    status = limits.parse({"limits": [{"kind": "monthly_all", "percent": 3}]})
    assert [w.kind for w in status.scoped] == ["monthly_all"]


def test_a_scoped_window_without_a_model_still_says_it_is_scoped():
    """Naming it plain "Weekly" would collide with the legacy weekly row
    directly above it, and the two are different limits."""
    payload = state._limits_payload(
        limits.parse({"limits": [{"kind": "weekly_scoped", "percent": 1}]}),
        strings={"weekly_scoped": "주간 (모델별)", "weekly_model": "주간 %1"},
    )
    assert payload["scoped"][0]["name"] == "주간 (모델별)"


def test_a_scoped_window_is_named_after_its_model():
    payload = state._limits_payload(
        limits.parse({"limits": [
            {"kind": "weekly_scoped", "percent": 1,
             "scope": {"model": {"display_name": "Fable"}}}]}),
        strings={"weekly_scoped": "주간 (모델별)", "weekly_model": "주간 %1"},
    )
    assert payload["scoped"][0]["name"] == "주간 Fable"


# MARK: the plan and account labels


@pytest.mark.parametrize("subscription,tier,expected", [
    ("max", "default_claude_max_5x", "Max 5x"),
    ("max", "default_claude_max_20x", "Max 20x"),
    ("pro", "default_claude_pro", "Pro"),
    ("free", None, "Free"),
    (None, "default_claude_max_5x", None),
])
def test_the_plan_keeps_its_multiplier(subscription, tier, expected):
    """Upper-casing the raw type printed "MAX" and lost the 5x entirely — and
    the multiplier is the part that says how many tokens the percentage is."""
    status = limits.LimitStatus(subscription_type=subscription, rate_limit_tier=tier)
    assert limits.plan_display(status) == expected


def test_a_personal_organisation_is_not_repeated_after_the_email():
    """A personal plan's organisation is named "<email>'s Organization", so
    printing both says the same thing twice."""
    status = limits.LimitStatus(account={
        "email": "a@b.com", "organization": "a@b.com's Organization"})
    assert limits.account_display(status) == "a@b.com"


def test_a_real_organisation_is_kept():
    status = limits.LimitStatus(account={"email": "a@b.com", "organization": "Acme"})
    assert limits.account_display(status) == "a@b.com · Acme"


def test_an_organisation_alone_is_not_a_label():
    """It does not identify which login the limits belong to, which is the only
    reason the label exists."""
    status = limits.LimitStatus(account={"organization": "Acme"})
    assert limits.account_display(status) is None


# MARK: used vs remaining


def test_remaining_mode_is_a_display_transform_only():
    assert limits.display_percent(27, "used") == 27
    assert limits.display_percent(27, "remaining") == 73
    # Past the limit there is no negative headroom.
    assert limits.display_percent(120, "remaining") == 0
    assert limits.panel_text(
        limits.LimitStatus(session=limits.LimitWindow(91.0)), "session", "remaining"
    ) == "5h 9%"


# MARK: the rolling 5-hour block


class _Provider:
    """The smallest thing ScanningProvider.fetch_active_block needs."""

    def __init__(self, entries):
        self._entries = entries

    scan_entries = property(lambda self: lambda: self._entries)
    # (amount, coverage), as ScanningProvider.cost_of answers here.
    cost_of = staticmethod(lambda entry: (0.0, CostCoverage()))


def _entry(minutes_ago: float, total: int):
    from poketokenbar.models import Entry

    when = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return Entry(id=str(minutes_ago), date=when, local_day="x", model="m", input=total)


def test_the_active_block_measures_only_the_last_five_hours():
    from poketokenbar.providers.base import ScanningProvider

    subject = _Provider([_entry(400, 999), _entry(60, 100), _entry(30, 50)])
    block = ScanningProvider.fetch_active_block(subject)
    assert block.total_tokens == 150, "the six-hour-old entry is outside the window"
    # 150 tokens over the ~60 minutes since the oldest kept entry.
    assert 2.0 < block.tokens_per_minute < 3.0


def test_a_block_seconds_old_does_not_report_a_rate_in_the_millions():
    """The elapsed minutes are floored at one, or a brand-new block divides by
    near-zero."""
    from poketokenbar.providers.base import ScanningProvider

    block = ScanningProvider.fetch_active_block(_Provider([_entry(0.01, 1_000_000)]))
    assert block.tokens_per_minute == 1_000_000


def test_no_recent_entries_means_no_block():
    from poketokenbar.providers.base import ScanningProvider

    assert ScanningProvider.fetch_active_block(_Provider([_entry(400, 1)])) is None


def test_a_naive_timestamp_does_not_raise():
    """parse_iso returns a naive datetime for any log line written without an
    offset, and comparing one of those against an aware window start raises
    rather than sorting."""
    from poketokenbar.models import Entry
    from poketokenbar.providers.base import ScanningProvider

    naive = Entry(id="n", date=datetime.now() - timedelta(minutes=5),
                  local_day="x", model="m", input=7)
    block = ScanningProvider.fetch_active_block(_Provider([naive]))
    assert block.total_tokens == 7


# MARK: the forecast


def test_the_forecast_says_when_the_window_runs_out():
    now = 1_000_000.0
    # 27% of the window has cost 362.5M, so 100% costs ~1.34B; at 5M/min the
    # remaining 73% is about 3.3 hours away.
    result = burn.depletion_forecast(27.0, now + 2 * 3600, 362_500_000, 5_000_000, now=now)
    assert result is not None
    assert 190 < result.minutes < 210
    assert result.before_reset is False, "3.3h out, but the window resets in 2h"


def test_a_depletion_before_the_reset_is_flagged():
    now = 1_000_000.0
    result = burn.depletion_forecast(27.0, now + 12 * 3600, 362_500_000, 5_000_000, now=now)
    assert result.before_reset is True


def test_a_window_already_full_is_reported_as_depleted_now():
    result = burn.depletion_forecast(100.0, 2.0, 1, 1.0, now=1.0)
    assert result.minutes == 0 and result.before_reset is True


@pytest.mark.parametrize("utilization,tokens,rate", [
    (3.0, 1_000_000, 1_000_000),     # under 5%: the divisor is noise
    (27.0, 0, 1_000_000),            # no block, nothing to scale from
    (27.0, 362_500_000, 9_999),      # too slow to mean anything
    (27.0, 362_500_000, 500_000),    # lands more than a day out
])
def test_an_unprojectable_window_reports_nothing(utilization, tokens, rate):
    """Rather than a number with no support under it."""
    assert burn.depletion_forecast(
        utilization, 2_000_000.0, tokens, rate, now=1_000_000.0) is None


def test_the_forecast_reaches_the_payload_with_its_verdict():
    """Both outcomes have to be distinguishable: "reaches the limit at 15:52"
    and "will not reach it" are different rows, and only the first has a time."""
    from poketokenbar.daemon import Daemon

    class _Stub(Daemon):
        def __init__(self):
            self.burn = None

    status = limits.LimitStatus(session=limits.LimitWindow(
        27.0, resets_at=(datetime.now(timezone.utc)
                         + timedelta(hours=12)).isoformat()))
    block = BlockUsage(id="b", start_time="", end_time="", is_active=True,
                       total_tokens=362_500_000, tokens_per_minute=5_000_000)
    payload = _Stub()._burn_payload(status, {"claude_code": block})
    assert payload["session"]["before_reset"] is True
    assert payload["session"]["eta_text"]


def test_a_block_the_forecast_cannot_use_drops_the_stale_row():
    """A sampled row left standing beside a block that no longer supports it is
    a forecast nothing is behind."""
    from poketokenbar.daemon import Daemon

    class _Stub(Daemon):
        def __init__(self):
            self.burn = type("B", (), {"payload": lambda self: {
                "session": {"eta_text": "old"}}})()

    status = limits.LimitStatus(session=limits.LimitWindow(1.0))
    block = BlockUsage(id="b", start_time="", end_time="", is_active=True,
                       total_tokens=1, tokens_per_minute=1)
    assert "session" not in _Stub()._burn_payload(status, {"claude_code": block})


# MARK: what the payload carries


def test_the_payload_carries_the_block_and_the_scoped_rows():
    payload = state.build(
        {"claude_code": DailyUsage(date="2026-09-03", total_tokens=10, total_cost=1.5)},
        {"language": "ko"},
        [],
        limit_status=limits.parse({"limits": [
            {"kind": "session", "percent": 27},
            {"kind": "weekly_scoped", "percent": 0.4,
             "scope": {"model": {"display_name": "Fable"}}}]}),
        blocks={"claude_code": BlockUsage(
            id="b", start_time="s", end_time="e", is_active=True,
            total_tokens=362_500_000, cost_usd=2.0, tokens_per_minute=1.0)},
    )
    assert payload["limits"]["scoped"][0]["name"] == "주간 Fable"
    assert payload["blocks"]["claude_code"]["total_tokens_compact"] == "362.5M"
    # Every figure arrives preformatted, so no front end derives one twice.
    assert payload["providers"]["claude_code"]["cost_text"]
    assert payload["providers"]["claude_code"]["cache_read_compact"]
