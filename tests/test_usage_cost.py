"""Estimated, reported and unavailable costs — ported from UsageCostTests.swift
(upstream 69ff39b, with a8b3ba8's plain-dollar text)."""

import json
from datetime import datetime, timezone

import pytest

from poketokenbar import config, pricing, state
from poketokenbar.models import CostCoverage, DailyUsage, Entry
from poketokenbar.providers.base import ScanningProvider
from poketokenbar.providers.codex import parse_rollout

WHEN = datetime(2026, 9, 17, 12, tzinfo=timezone.utc)


def entry(model="claude-sonnet-4-6", tokens=1_000_000, **kwargs):
    return Entry(id=str(kwargs), date=WHEN, local_day="2026-09-17", model=model,
                 input=tokens, **kwargs)


def day(*entries):
    return ScanningProvider().aggregate_daily("2026-09-17", list(entries))


def test_a_known_model_is_estimated():
    d = day(entry())
    assert d.total_cost == pytest.approx(3.0)
    assert d.cost_coverage == CostCoverage(estimated=True)


def test_a_recorded_cost_wins_and_zero_counts():
    d = day(entry(explicit_cost=0.0), entry(model="unlisted", explicit_cost=0.5))
    assert d.total_cost == pytest.approx(0.5)
    assert d.cost_coverage == CostCoverage(reported=True)


def test_a_recorded_estimate_is_an_estimate():
    assert day(entry(explicit_cost=1.0, cost_is_estimate=True)).cost_coverage == CostCoverage(
        estimated=True)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0])
def test_an_invalid_recorded_cost_is_not_a_cost(bad):
    d = day(entry(model="unlisted", explicit_cost=bad))
    assert d.total_cost == 0 and d.cost_coverage.only_unknown


def test_an_unpriceable_entry_is_unknown_even_for_a_known_model():
    d = day(entry(cost_unavailable=True))
    assert d.total_cost == 0 and d.cost_coverage.only_unknown


def test_a_mixed_day_keeps_its_known_part_and_says_it_is_partial():
    d = day(entry(), entry(model="unlisted"))
    assert d.total_cost == pytest.approx(3.0)
    assert d.cost_coverage == CostCoverage(estimated=True, unknown=True)


def test_zero_token_records_cannot_make_an_unknown_day_look_priced():
    d = day(entry(model="unlisted"), entry(tokens=0, explicit_cost=0.0))
    assert d.cost_coverage.only_unknown


def test_a_missing_price_row_is_reported_but_a_declared_unavailable_cost_is_not():
    """A blank cost otherwise leaves no trace at all (upstream 5f6a4f0). Only a
    missing table row is the table's fault; a source that declared the cost
    unavailable is not evidence of one.
    """
    seen = set(pricing._unpriced_seen)
    pricing._unpriced_seen.clear()
    try:
        day(entry(model="unlisted-by-the-table"), entry(cost_unavailable=True))
        assert pricing._unpriced_seen == {"unlisted-by-the-table"}
    finally:
        pricing._unpriced_seen.clear()
        pricing._unpriced_seen.update(seen)


# MARK: text


def _payload(*daily, **config_values):
    values = dict(config.DEFAULTS, show_cost_in_menu=True, **config_values)
    return state.build({f"p{i}": d for i, d in enumerate(daily)}, values, [])


def test_plain_dollars_whenever_anything_was_priced():
    payload = _payload(day(entry(), entry(model="unlisted")))
    assert payload["today"]["cost_text"] == "$3.00"
    assert payload["panel"]["cost_text"] == "$3.0"


def test_unavailable_when_nothing_could_be_priced():
    payload = _payload(day(entry(model="unlisted")), language="ko")
    assert payload["today"]["cost_text"] == "계산 불가"
    assert payload["panel"]["cost_text"] == "$—"
    assert payload["providers"]["p0"]["cost_text"] == "계산 불가"


def test_no_text_without_usage():
    payload = _payload()
    assert payload["today"]["cost_text"] == ""
    assert payload["panel"]["cost_text"] == ""


def test_week_and_month_carry_their_coverage():
    provider = ScanningProvider()
    provider.scan_entries = lambda: [entry(model="unlisted"), entry()]
    periods = provider.fetch_periods("2026-09-17")
    assert periods["month"]["coverage"] == CostCoverage(estimated=True, unknown=True)
    payload = state.build({}, config.DEFAULTS, [], periods=periods)
    assert payload["periods"]["month"]["cost_text"] == "$3.00"


# MARK: Codex


def _rollout(tmp_path, *events):
    path = tmp_path / "rollout.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n")
    return parse_rollout(path).entries


def _token_count(last, cumulative):
    return {"type": "event_msg", "timestamp": "2026-09-17T01:00:00.000Z",
            "payload": {"type": "token_count",
                        "info": {"last_token_usage": last, "total_token_usage": cumulative}}}


def test_a_codex_turn_before_any_model_is_named_is_unpriced(tmp_path):
    usage = {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11}
    (turn,) = _rollout(tmp_path, _token_count(usage, usage))
    assert turn.model == "codex"
    assert day(turn).cost_coverage.only_unknown


def test_a_codex_total_only_turn_is_counted_but_unpriced(tmp_path):
    (turn,) = _rollout(
        tmp_path,
        {"type": "turn_context", "payload": {"model": "gpt-5"}},
        _token_count({"total_tokens": 500}, {"total_tokens": 500}),
    )
    assert (turn.model, turn.total, turn.cost_unavailable) == ("gpt-5", 500, True)
