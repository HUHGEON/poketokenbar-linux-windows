import pytest

from poketokenbar import pricing


def test_exact_table_match():
    r = pricing.rate("claude-sonnet-4-6")
    assert r.input == pytest.approx(3 / 1_000_000)
    assert r.output == pytest.approx(15 / 1_000_000)


def test_family_fallback_for_unknown_version():
    # Version drift must not silently zero a real model's cost.
    assert pricing.rate("claude-opus-9-9").input == pytest.approx(5 / 1_000_000)


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


def test_gemini_family_fallback():
    assert pricing.rate("gemini-3.0-pro").input == pytest.approx(1.25 / 1_000_000)
    assert pricing.rate("gemini-3.0-flash").input == pytest.approx(0.30 / 1_000_000)


def test_unknown_gemini_variant_is_zero():
    assert pricing.rate("gemini-experimental-x") == pricing.ZERO


def test_cost_sums_all_four_token_kinds():
    # 1M of each against sonnet: 3 + 15 + 3.75 + 0.3
    total = pricing.cost("claude-sonnet-4-6", 1_000_000, 1_000_000, 1_000_000, 1_000_000)
    assert total == pytest.approx(22.05)


def test_cost_of_an_unpriced_model_is_zero():
    assert pricing.cost("totally-unknown-model", 10**9, 10**9, 10**9, 10**9) == 0.0


def per_token(*rates):
    return pricing.per_million(*rates)


@pytest.mark.parametrize("model,rates", [
    # Fable 5 was a $0 placeholder; upstream priced it from the LiteLLM snapshot.
    ("claude-fable-5", (10, 50, 12.5, 1.0)),
    # Fable 5.1 keeps Fable 5's base rates but reads cache at 0.025x input.
    ("claude-fable-5-1", (10, 50, 12.5, 0.25)),
    ("claude-opus-4-20250514", (15, 75, 18.75, 1.5)),
    ("claude-sonnet-4-5-20250929", (3, 15, 3.75, 0.3)),
    ("gpt-6-astra", (10, 50, 12.5, 1)),
    ("gpt-5.6-luna", (0.2, 1.2, 0.25, 0.02)),
    # Real gpt-5 turns were priced by the family fallback at $5/$30.
    ("gpt-5", (1.25, 10, 0, 0.125)),
    ("gpt-5.3-codex", (1.75, 14, 0, 0.175)),
    ("gpt-5.4", (2.5, 15, 0, 0.25)),
    ("gemini-2.5-pro", (1.25, 10, 0, 0.125)),
    ("gemini-2.5-flash", (0.30, 2.5, 0, 0.03)),
])
def test_table_matches_upstream_v2_5_4(model, rates):
    assert pricing.rate(model) == per_token(*rates)


@pytest.mark.parametrize("model,key", [
    ("gpt-5.6", "gpt-5.6-sol"),
    ("claude-sonnet-4-5", "claude-sonnet-4-5-20250929"),
    ("gpt-5.2-2025-12-11", "gpt-5.2"),
    ("openai/gpt-5", "gpt-5"),
    ("anthropic/claude-fable-5-1", "claude-fable-5-1"),
    ("models/gemini-2.5-pro", "gemini-2.5-pro"),
    ("  GPT-5.4 ", "gpt-5.4"),
])
def test_documented_aliases_and_namespaces_reach_the_table(model, key):
    assert pricing.model_key(model) == key
    assert pricing.rate(model) == pricing.TABLE[key]


def test_antigravity_prefix_is_not_a_namespace():
    assert pricing.model_key("antigravity/gpt-5") == "antigravity/gpt-5"
    assert pricing.rate("antigravity/gpt-5") == pricing.ZERO
