"""state.json's own shape — the contract the UI reads.

Every number the UI shows is formatted here rather than in the front end. That
rule exists because QML renders a large float as 8.55336e+07, and the same trap
is waiting in any other UI that formats numbers itself.
"""

from poketokenbar import state
from poketokenbar.models import DailyUsage


def test_periods_carry_prepared_text():
    """The daemon sums these as raw ints; the UI must not have to format them."""
    payload = state.build(
        {}, {}, [], periods={"week": {"tokens": 85_533_600, "cost": 1.5},
                             "month": {"tokens": 2, "cost": 0.0}}
    )
    week = payload["periods"]["week"]
    assert week["tokens"] == 85_533_600
    assert week["tokens_text"] == "85,533,600"
    assert "e+" not in week["tokens_compact"]
    assert week["cost_text"]
    assert payload["periods"]["month"]["tokens_text"] == "2"


def test_absent_periods_stay_empty():
    assert state.build({}, {}, [])["periods"] == {}


def test_the_panel_sprite_follows_the_pin():
    """Pinning changes the panel and nothing else, so if the panel ignored it
    the feature would have nowhere to take effect at all."""
    payload = state.build(
        {}, {}, [],
        companion_payload={
            "sprite_path": "/cache/5-a.gif",
            "panel_sprite_path": "/cache/3-sha.gif",
        },
    )
    assert payload["panel"]["sprite_path"] == "/cache/3-sha.gif"
    assert payload["companion"]["sprite_path"] == "/cache/5-a.gif", (
        "Home still shows what is being raised"
    )


def test_the_panel_falls_back_to_the_companion_sprite():
    """A save from before pinning existed has no panel_sprite_path at all."""
    payload = state.build({}, {}, [], companion_payload={"sprite_path": "/cache/5-a.gif"})
    assert payload["panel"]["sprite_path"] == "/cache/5-a.gif"


def test_the_panel_sprite_is_blank_without_a_companion():
    assert state.build({}, {}, [])["panel"]["sprite_path"] == ""


def test_today_totals_are_preformatted():
    payload = state.build(
        {"claude_code": DailyUsage(date="d", total_tokens=85_533_600, total_cost=12.5)},
        {},
        [],
    )
    assert payload["today"]["tokens_grouped"] == "85,533,600"
    assert "e+" not in payload["today"]["tokens_compact"]
    assert payload["today"]["cost_text"]


def test_provider_totals_are_preformatted():
    payload = state.build(
        {"pi": DailyUsage(date="d", total_tokens=1_234_567)}, {}, []
    )
    row = payload["providers"]["pi"]
    assert row["total_tokens_text"] == "1,234,567"
    assert "e+" not in row["total_tokens_compact"]


def test_the_live_config_is_shipped():
    """A preferences UI needs the current values; parsing config.json itself
    would let the two drift the moment a default changes."""
    payload = state.build({}, {"language": "ko", "floating_pet_size": 96}, [])
    assert payload["config"]["language"] == "ko"
    assert payload["config"]["floating_pet_size"] == 96


def test_the_shipped_config_is_a_copy():
    """The payload is serialised later; handing out the daemon's own dict would
    let a mutation there rewrite an already-built snapshot."""
    values = {"language": "en"}
    payload = state.build({}, values, [])
    values["language"] = "ko"
    assert payload["config"]["language"] == "en"


# --- a provider nobody used today (upstream a8dd806, 11eebe6) ---------------


def test_a_provider_with_a_week_behind_it_keeps_its_row_on_an_idle_day():
    """The tab strip changed shape on a quiet day, and again on the 1st of a
    month, because a row only existed while the provider had usage *today*."""
    from poketokenbar import state
    from poketokenbar.models import CostCoverage, DailyUsage

    periods = {
        "week": {"tokens": 10, "cost": 0.0, "coverage": CostCoverage()},
        "month": {"tokens": 10, "cost": 0.0, "coverage": CostCoverage()},
        "by_provider": {
            "claude_code": {"week": {"tokens": 7}, "month": {"tokens": 9}},
            "codex": {"week": {"tokens": 3}, "month": {"tokens": 3}},
            # Installed, never used: still nothing to show.
            "gemini": {"week": {"tokens": 0}, "month": {"tokens": 0}},
        },
    }
    payload = state.build(
        {"claude_code": DailyUsage(date="2026-10-16", total_tokens=5)},
        {"language": "en"}, [], periods=periods,
    )
    rows = payload["providers"]
    assert set(rows) == {"claude_code", "codex"}
    assert rows["codex"]["total_tokens"] == 0, "an idle day is an empty day"
    assert rows["codex"]["week_compact"] == "3"
    assert rows["claude_code"]["month_compact"] == "9"


def test_the_period_rows_are_not_confused_by_the_per_provider_map():
    from poketokenbar import state
    from poketokenbar.models import CostCoverage, DailyUsage

    payload = state.build(
        {"claude_code": DailyUsage(date="2026-10-16", total_tokens=5)},
        {"language": "en"}, [],
        periods={"week": {"tokens": 10, "cost": 0.0, "coverage": CostCoverage()},
                 "by_provider": {"claude_code": {"week": {"tokens": 10},
                                                 "month": {"tokens": 10}}}},
    )
    assert set(payload["periods"]) == {"week"}
