import pytest

from poketokenbar import config, limits, state
from poketokenbar.models import DailyUsage


def _status(session=96.0, weekly=18.0):
    return limits.parse(
        {
            "limits": [
                {"kind": "session", "percent": session, "resets_at": "2026-08-19T01:49:59Z"},
                {"kind": "weekly_all", "percent": weekly, "resets_at": "2026-08-25T12:59:59Z"},
            ]
        }
    )


# --- level thresholds ------------------------------------------------------


def test_level_is_ok_below_warn():
    assert limits.level(50.0, warn=80, crit=95) == "ok"


def test_level_is_warn_at_the_warn_threshold():
    # Boundary belongs to the more severe band — 80 with warn=80 is a warning,
    # not still-fine.
    assert limits.level(80.0, warn=80, crit=95) == "warn"


def test_level_is_crit_at_the_crit_threshold():
    assert limits.level(95.0, warn=80, crit=95) == "crit"


def test_level_is_crit_above_crit():
    assert limits.level(96.0, warn=80, crit=95) == "crit"


# --- panel windows ---------------------------------------------------------


def _panel(cfg=None, status=None):
    values = dict(config.DEFAULTS, show_limit_in_menu=True, show_tokens_in_menu=False)
    values.update(cfg or {})
    payload = state.build(
        {"claude_code": DailyUsage(date="2026-08-18", total_tokens=1)},
        values,
        [],
        limit_status=status if status is not None else _status(),
    )
    return payload["panel"]


def test_panel_exposes_one_window_per_limit():
    windows = _panel()["limit_windows"]
    assert [w["text"] for w in windows] == ["96%", "18%"]


def test_panel_windows_carry_levels_for_colouring():
    windows = _panel()["limit_windows"]
    assert [w["level"] for w in windows] == ["crit", "ok"]


def test_panel_windows_respect_configured_thresholds():
    windows = _panel(cfg={"warn_threshold": 10, "crit_threshold": 20})["limit_windows"]
    assert [w["level"] for w in windows] == ["crit", "warn"]


def test_panel_windows_follow_display_mode():
    windows = _panel(cfg={"limit_display_mode": "session"})["limit_windows"]
    assert [w["text"] for w in windows] == ["96%"]


def test_panel_windows_empty_when_limits_hidden():
    assert _panel(cfg={"show_limit_in_menu": False})["limit_windows"] == []


def test_panel_windows_omit_a_missing_window():
    status = limits.parse({"limits": [{"kind": "session", "percent": 96}]})
    assert [w["text"] for w in _panel(status=status)["limit_windows"]] == ["96%"]


def test_tokens_text_can_be_switched_off_independently():
    assert _panel()["tokens_text"] == ""


# --- pace tiers (upstream 68deb09, 2eec9af, b32717f) ------------------------


def _live_status(session_percent, seconds_left, span):
    """A window whose reset is a real instant, so it has a pace."""
    from datetime import datetime, timedelta, timezone

    resets = (datetime.now(timezone.utc) + timedelta(seconds=seconds_left)).isoformat()
    kind = "session" if span == "session" else "weekly_all"
    return limits.parse({"limits": [
        {"kind": kind, "percent": session_percent, "resets_at": resets.replace("+00:00", "Z")},
    ]})


def _limits(status):
    values = dict(config.DEFAULTS, show_limit_in_menu=True)
    return state.build(
        {"claude_code": DailyUsage(date="2026-08-18", total_tokens=1)},
        values, [], limit_status=status,
    )


def test_a_window_carries_its_pace_and_tier():
    from poketokenbar import pace

    # Four fifths through a five-hour window, at 90%: 10 points ahead.
    payload = _limits(_live_status(90.0, 3600, "session"))
    window = payload["limits"]["session"]
    assert window["pace"] == pytest.approx(0.8, abs=1e-3)
    assert window["tier"] == "slightly_over"
    assert window["tier_text"] == "Slightly fast"
    assert "10" in window["pace_delta_text"]
    assert "80%" in window["pace_hint"]


def test_a_window_with_a_stale_reset_has_no_pace_but_still_has_a_tier():
    """The panel and the popup always need a colour; the mark is what needs a
    trustworthy pace."""
    payload = _limits(_status(session=96.0))
    window = payload["limits"]["session"]
    assert window["pace"] is None
    assert window["pace_hint"] == "" and window["pace_delta_text"] == ""
    assert window["tier"] == "way_over"  # from the absolute threshold


def test_the_panel_number_and_the_popup_gauge_share_one_tier():
    status = _live_status(90.0, 3600, "session")
    payload = _limits(status)
    assert payload["panel"]["limit_windows"][0]["tier"] == payload["limits"]["session"]["tier"]


def test_the_payload_lists_every_account_only_when_there_is_more_than_one():
    """One login is the normal case, and a tab strip of one is noise."""
    class _Source:
        last_error = ""
        stale = False

    class _Holder:
        source = _Source()

    one = _live_status(10.0, 3600, "session")
    two = limits.LimitStatus(session=limits.LimitWindow(utilization=90.0),
                             account={"email": "work@example.com"})
    values = dict(config.DEFAULTS, show_limit_in_menu=True)
    alone = state.build(
        {"claude_code": DailyUsage(date="2026-08-18", total_tokens=1)}, values, [],
        limit_status=one, limit_accounts=[("default", one, _Holder())],
    )
    assert alone["limits"]["accounts"] == []

    both = state.build(
        {"claude_code": DailyUsage(date="2026-08-18", total_tokens=1)}, values, [],
        limit_status=one,
        limit_accounts=[("default", one, _Holder()), (".claude-work", two, _Holder())],
    )
    rows = both["limits"]["accounts"]
    assert [row["id"] for row in rows] == ["default", ".claude-work"]
    assert rows[1]["label"] == "work@example.com"
    assert rows[1]["session"]["utilization"] == 90.0
    assert rows[0]["is_default"] and not rows[1]["is_default"]
    # The block itself still describes the default account, which is what the
    # panel and the companion mood follow.
    assert both["limits"]["session"]["utilization"] == 10.0
