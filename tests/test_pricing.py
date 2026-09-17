import pytest

from poketokenbar import pricing


def test_exact_table_match():
    r = pricing.rate("claude-sonnet-4-6")
    assert r.input == pytest.approx(3 / 1_000_000)
    assert r.output == pytest.approx(15 / 1_000_000)


def test_an_unlisted_version_is_unpriced_rather_than_priced_like_its_family():
    # Upstream 69ff39b: "opus" in a name is not evidence of an Opus price.
    assert pricing.estimated_cost("claude-opus-9-9", 1_000_000, 0, 0, 0) is None
    assert pricing.rate("claude-opus-9-9") == pricing.ZERO


def test_grok_names_are_unpriced():
    assert pricing.estimated_cost("grok-codex-fast", 1, 1, 0, 0) is None
    assert pricing.estimated_cost("grok-4o-mini", 1, 1, 0, 0) is None


def test_antigravity_prefix_is_unpriced_even_for_a_priced_model():
    # That CLI calls claude-sonnet-4-6, which is in the table without the prefix.
    assert pricing.estimated_cost("antigravity/claude-sonnet-4-6", 1, 1, 0, 0) is None


def test_unknown_model_is_unpriced_rather_than_guessed():
    assert pricing.estimated_cost("totally-unknown-model", 1, 1, 0, 0) is None
    assert pricing.rate("totally-unknown-model") == pricing.ZERO


def test_an_unlisted_gemini_is_unpriced():
    assert pricing.estimated_cost("gemini-3.0-pro", 1, 1, 0, 0) is None
    assert pricing.estimated_cost("gemini-3.0-flash", 1, 1, 0, 0) is None


def test_cache_writes_on_a_model_with_no_write_rate_are_unpriced():
    # gpt-5.4 has no separate write rate; zero there is "unknown", not "free".
    assert pricing.estimated_cost("gpt-5.4", 1_000, 1_000, 1, 0) is None
    assert pricing.estimated_cost("gpt-5.4", 1_000, 1_000, 0, 1_000) is not None


def test_the_long_context_tier_is_per_request():
    base = pricing.estimated_cost("gpt-5.4", 272_000, 1_000_000, 0, 0)
    assert base == pytest.approx(272_000 * 2.5e-6 + 15.0)
    long = pricing.estimated_cost("gpt-5.4", 272_001, 1_000_000, 0, 0)
    assert long == pytest.approx(272_001 * 2.5e-6 * 2 + 15.0 * 1.5)
    assert pricing.estimated_cost("gemini-2.5-pro", 150_000, 0, 0, 60_000) == pytest.approx(
        (150_000 * 1.25e-6 + 60_000 * 0.125e-6) * 2)
    # Models without the tier are never surcharged.
    assert pricing.estimated_cost("claude-sonnet-4-6", 1_000_000, 0, 0, 0) == pytest.approx(3.0)


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
