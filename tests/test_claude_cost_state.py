"""Claude Code's own cost ledger — ports ClaudeReportedCostTests.swift (8b2dd95).

Claude Code prices each session itself and writes the result to the transcript
as cumulative `type: "cost-state"` records, covering models and context
variants (`claude-opus-5[1m]`) the local price table may hold no rate for. These
cover preferring that reported amount over an estimate, and the attribution
rules that keep a session total exact.
"""

import json

import pytest

from poketokenbar import pricing
from poketokenbar.models import CostCoverage
from poketokenbar.providers import claude
from poketokenbar.providers.base import ScanningProvider

# Deliberately absent from the price table, so only a reported cost can price it.
UNPRICED = "claude-opus-9"


def assistant(id, model, ts, input=0, output=0, cache_write=0, cache_read=0):
    return json.dumps({
        "type": "assistant",
        "timestamp": ts,
        "requestId": f"r-{id}",
        "message": {"id": id, "model": model, "usage": {
            "input_tokens": input,
            "output_tokens": output,
            "cache_creation_input_tokens": cache_write,
            "cache_read_input_tokens": cache_read,
        }},
    })


def cost_state(models, unknown=False):
    return json.dumps({
        "type": "cost-state",
        "totalCostUSD": sum(models.values()),
        "modelUsage": {k: {"costUSD": v} for k, v in models.items()},
        "hasUnknownModelCost": unknown,
    })


@pytest.fixture
def parse(tmp_path):
    def run(lines):
        path = tmp_path / "s.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return claude.parse_file(path)
    return run


def priced(entries):
    """Sum and coverage, as a day's aggregation sees them."""
    provider = ScanningProvider()
    total = 0.0
    coverage = None
    for e in entries:
        amount, part = provider.cost_of(e)
        total += amount
        if coverage is None:
            coverage = part
        else:
            coverage.merge(part)
    return total, coverage


def test_an_unpriced_model_uses_the_cost_its_source_reported(parse):
    # The regression: a model with no table rate read as "cost unavailable"
    # although Claude had already priced it in the same file.
    assert pricing.estimated_cost(UNPRICED, 10, 10, 0, 0) is None
    total, coverage = priced(parse([
        assistant("a", UNPRICED, "2026-09-15T10:00:00.000Z", input=100, output=50),
        cost_state({f"{UNPRICED}[1m]": 12.5}),
    ]))
    assert total == pytest.approx(12.5)
    assert coverage == CostCoverage(reported=True)


def test_a_context_window_variant_pools_onto_the_base_model(parse):
    total, _ = priced(parse([
        assistant("a", "claude-opus-5", "2026-09-15T10:00:00.000Z", input=10, output=10),
        cost_state({"claude-opus-5[1m]": 4, "claude-opus-5": 1}),
    ]))
    assert total == pytest.approx(5.0)


def test_a_reported_cost_beats_the_table_estimate(parse):
    model = "claude-haiku-4-5-20251001"
    assert pricing.estimated_cost(model, 10**6, 0, 0, 0) == pytest.approx(1.0)
    total, coverage = priced(parse([
        assistant("a", model, "2026-09-15T10:00:00.000Z", input=10**6),
        cost_state({model: 7.25}),
    ]))
    assert total == pytest.approx(7.25)
    assert coverage.reported and not coverage.estimated


def test_the_ledger_is_cumulative_so_the_last_record_describes_the_session(parse):
    total, _ = priced(parse([
        assistant("a", "claude-opus-5", "2026-09-15T10:00:00.000Z", input=10),
        cost_state({"claude-opus-5": 1}),
        assistant("b", "claude-opus-5", "2026-09-15T11:00:00.000Z", input=10),
        cost_state({"claude-opus-5": 9}),
    ]))
    assert total == pytest.approx(9.0)


def test_a_session_that_straddles_a_day_splits_by_tokens_and_still_totals_exactly(parse):
    # 24h apart, so the fixture crosses a local day in any timezone.
    entries = parse([
        assistant("a", "claude-opus-5", "2026-09-15T12:00:00.000Z", input=300),
        assistant("b", "claude-opus-5", "2026-09-16T12:00:00.000Z", input=100),
        cost_state({"claude-opus-5": 10}),
    ])
    assert len({e.local_day for e in entries}) == 2
    assert sum(e.explicit_cost for e in entries) == pytest.approx(10.0)
    by_date = sorted(entries, key=lambda e: e.date)
    assert by_date[0].explicit_cost == pytest.approx(7.5)  # 300 of 400 tokens
    assert by_date[1].explicit_cost == pytest.approx(2.5)  # 100 of 400
    assert all(e.cost_is_estimate is False for e in entries)


def test_cost_for_a_model_with_no_parsed_entry_is_dropped_not_moved(parse):
    total, _ = priced(parse([
        assistant("a", "claude-opus-5", "2026-09-15T10:00:00.000Z", input=100),
        cost_state({"claude-opus-5": 2, "claude-haiku-4-5-20251001": 98}),
    ]))
    assert total == pytest.approx(2.0)


def test_a_zero_token_record_absorbs_none_of_the_money(parse):
    total, _ = priced(parse([
        assistant("a", "claude-opus-5", "2026-09-15T10:00:00.000Z"),
        assistant("b", "claude-opus-5", "2026-09-15T10:05:00.000Z", input=500),
        cost_state({"claude-opus-5": 6}),
    ]))
    assert total == pytest.approx(6.0)


def test_without_a_ledger_the_table_still_decides(parse):
    total, coverage = priced(parse([
        assistant("a", "claude-haiku-4-5-20251001", "2026-09-15T10:00:00.000Z", input=10**6),
    ]))
    assert total == pytest.approx(1.0) and coverage.estimated
    total, coverage = priced(parse([
        assistant("a", UNPRICED, "2026-09-15T10:00:00.000Z", input=10**6),
    ]))
    assert total == 0 and coverage.only_unknown


@pytest.mark.parametrize("bad", [
    '{"type":"cost-state","modelUsage":{}}',
    '{"type":"cost-state","modelUsage":[]}',
    '{"type":"cost-state"}',
    '{"type":"cost-state","modelUsage":{"claude-opus-5":{"costUSD":"1.0"}}}',
    '{"type":"cost-state","modelUsage":{"claude-opus-5":{"costUSD":-1}}}',
    '{"type":"cost-state","modelUsage":{"claude-opus-5":{}}}',
    'not json at all "cost-state"',
])
def test_a_ledger_with_no_usable_row_leaves_the_earlier_one_standing(parse, bad):
    total, _ = priced(parse([
        assistant("a", "claude-opus-5", "2026-09-15T10:00:00.000Z", input=10),
        cost_state({"claude-opus-5": 3}),
        bad,
    ]))
    assert total == pytest.approx(3.0)


def test_the_parser_version_invalidates_blobs_cached_before_the_ledger_was_read():
    # Entries cached under the old rule carry no reported cost, and a Claude
    # blob only re-parses on mtime or size, so the version must move.
    assert claude.ClaudeProvider.PARSER_VERSION >= 2
