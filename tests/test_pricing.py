import pytest

from poketokenbar import pricing


def test_exact_table_match():
    r = pricing.rate("claude-sonnet-4-6")
    assert r.input == pytest.approx(3 / 1_000_000)
    assert r.output == pytest.approx(15 / 1_000_000)


def test_unknown_version_is_not_priced_from_a_family_guess():
    assert pricing.estimated_cost("claude-opus-9-9", 1000, 0, 0, 0) is None


def test_sol_61_uses_its_rates_instead_of_the_older_gpt_fallback():
    # A Codex turn includes cached input; charging that at the old GPT rate
    # substantially overstates its estimated cost.
    assert pricing.cost("gpt-6.1-sol", 1_000_000, 100_000, 0, 2_000_000) == pytest.approx(3.2)
    assert pricing.cost("gpt-6.1-sol", 0, 0, 1_000_000, 0) == pytest.approx(2.5)


def test_grok_is_zero_before_any_family_fallback():
    # grok-codex-* would otherwise match the "codex" -> GPT fallback and show a
    # fabricated dollar amount.
    assert pricing.rate("grok-codex-fast") == pricing.ZERO
    assert pricing.rate("grok-4o-mini") == pricing.ZERO


def test_antigravity_prefix_is_zero_even_for_a_priced_model():
    # That CLI calls claude-sonnet-4-6, which would match the exact table
    # without the prefix. It is subscription-billed, so cost must stay 0.
    assert pricing.rate("antigravity/claude-sonnet-4-6") == pricing.ZERO


def test_unknown_model_costs_nothing_rather_than_guessing():
    assert pricing.rate("totally-unknown-model") == pricing.ZERO


def test_unknown_gemini_versions_remain_unavailable():
    assert pricing.estimated_cost("gemini-3.0-pro", 1000, 0, 0, 0) is None
    assert pricing.estimated_cost("gemini-3.0-flash", 1000, 0, 0, 0) is None


def test_unknown_gemini_variant_is_zero():
    assert pricing.rate("gemini-experimental-x") == pricing.ZERO


def test_cost_sums_all_four_token_kinds():
    # 1M of each against sonnet: 3 + 15 + 3.75 + 0.3
    total = pricing.cost("claude-sonnet-4-6", 1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert total == pytest.approx(22.05)


def test_fable_5_now_has_documented_pricing():
    assert pricing.cost("claude-fable-5", 10**6, 10**6, 10**6, 10**6) == pytest.approx(73.5)
