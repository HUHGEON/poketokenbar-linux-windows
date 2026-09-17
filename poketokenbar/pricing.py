"""Per-model token rates — ports ModelPricing.swift.

Rates are USD per million tokens. A model with no row is unpriced, and a total
that includes it says so — showing a guessed price would be worse than none.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelRate:
    input: float = 0.0
    output: float = 0.0
    cache_write: float = 0.0
    cache_read: float = 0.0


def per_million(
    input_: float, output: float, cache_write: float, cache_read: float
) -> ModelRate:
    m = 1_000_000
    return ModelRate(input_ / m, output / m, cache_write / m, cache_read / m)


ZERO = ModelRate()

# Standard API prices, as upstream's ModelPricing.swift at v2.5.4 (checked
# there 2026-09-11 against the OpenAI, Anthropic and Gemini price pages). An
# estimate of API-equivalent usage, not a subscription bill.
TABLE: dict[str, ModelRate] = {
    "claude-opus-4-20250514": per_million(15, 75, 18.75, 1.5),
    "claude-sonnet-4-20250514": per_million(3, 15, 3.75, 0.3),
    "claude-sonnet-4-5-20250929": per_million(3, 15, 3.75, 0.3),
    "claude-opus-4-8": per_million(5, 25, 6.25, 0.5),
    "claude-opus-4-7": per_million(5, 25, 6.25, 0.5),
    "claude-sonnet-4-6": per_million(3, 15, 3.75, 0.3),
    "claude-haiku-4-5-20251001": per_million(1, 5, 1.25, 0.1),
    "claude-fable-5": per_million(10, 50, 12.5, 1.0),
    # Same base rates as Fable 5, with cache reads cut to 0.025x input.
    "claude-fable-5-1": per_million(10, 50, 12.5, 0.25),
    "gpt-6-astra": per_million(10, 50, 12.5, 1),
    "gpt-5.6-sol": per_million(4, 20, 5, 0.4),
    "gpt-5.6-terra": per_million(2, 12, 2.5, 0.2),
    "gpt-5.6-luna": per_million(0.2, 1.2, 0.25, 0.02),
    "gpt-5": per_million(1.25, 10, 0, 0.125),
    "gpt-5-codex": per_million(1.25, 10, 0, 0.125),
    "gpt-5.1": per_million(1.25, 10, 0, 0.125),
    "gpt-5.1-codex": per_million(1.25, 10, 0, 0.125),
    "gpt-5.2": per_million(1.75, 14, 0, 0.175),
    "gpt-5.2-codex": per_million(1.75, 14, 0, 0.175),
    "gpt-5.3-codex": per_million(1.75, 14, 0, 0.175),
    "gpt-5.4": per_million(2.5, 15, 0, 0.25),
    "gpt-5.5": per_million(5, 30, 0, 0.5),
    # Gemini text token rates. Cache is the read rate only; storage-time and
    # audio charges cannot be recovered from the logs.
    "gemini-2.5-pro": per_million(1.25, 10, 0, 0.125),
    "gemini-2.5-flash": per_million(0.30, 2.5, 0, 0.03),
    "gemini-2.0-flash": per_million(0.10, 0.4, 0, 0.025),
}

# Documented identities only: dated snapshots and short names that resolve to
# a row above. Mirrors upstream's aliases table.
ALIASES: dict[str, str] = {
    "gpt-5.6": "gpt-5.6-sol",
    "claude-sonnet-4": "claude-sonnet-4-20250514",
    "claude-opus-4": "claude-opus-4-20250514",
    "claude-sonnet-4-5": "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
    "gpt-5-2025-08-07": "gpt-5",
    "gpt-5.1-2025-11-13": "gpt-5.1",
    "gpt-5.2-2025-12-11": "gpt-5.2",
    "gpt-5.4-2026-03-05": "gpt-5.4",
    "gpt-5.5-2026-04-23": "gpt-5.5",
}

# Provider namespaces some tools put in front of the model id. Only one is
# stripped, as upstream does. "antigravity/" is deliberately not here: that
# prefix marks subscription-billed usage and must not reach the table.
_NAMESPACES = ("openai/", "anthropic/", "google/", "models/")


def model_key(model: str) -> str:
    """The table key for a model id as a log wrote it."""
    key = (model or "").strip().lower()
    for prefix in _NAMESPACES:
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    return ALIASES.get(key, key)


def rate(model: str) -> ModelRate:
    """The table rate for a model, or ZERO when it has none."""
    return TABLE.get(model_key(model), ZERO)


# Long-context tier: past this many prompt tokens in one request, input is
# billed at 2x and output at 1.5x.
_LONG_CONTEXT = {
    "gpt-6-astra": 272_000,
    "gpt-5.6-sol": 272_000,
    "gpt-5.6-terra": 272_000,
    "gpt-5.6-luna": 272_000,
    "gpt-5.5": 272_000,
    "gpt-5.4": 272_000,
    "gemini-2.5-pro": 200_000,
}


def estimated_cost(
    model: str, input_: int, output: int, cache_write: int, cache_read: int
) -> float | None:
    """API-equivalent cost of one request, or None when it cannot be priced.

    Ports upstream's estimatedCost (69ff39b). A model with no row is not
    priced like its family any more: containing "gpt" or "opus" is not
    evidence of sharing that price, so it is unavailable rather than guessed.
    Pass one request, never a day's sum: the long-context tier is decided per
    request.
    """
    key = model_key(model)
    r = TABLE.get(key)
    if r is None or min(input_, output, cache_write, cache_read) < 0:
        return None
    # A zero write rate means no known separate rate, not free writes.
    if cache_write and not r.cache_write:
        return None
    prompt = input_ + cache_read + cache_write
    threshold = _LONG_CONTEXT.get(key)
    long_context = threshold is not None and prompt > threshold
    input_multiplier = 2.0 if long_context else 1.0
    output_multiplier = 1.5 if long_context else 1.0
    return (
        (input_ * r.input + cache_write * r.cache_write + cache_read * r.cache_read)
        * input_multiplier
        + output * r.output * output_multiplier
    )


def cost(model: str, input_: int, output: int, cache_write: int, cache_read: int) -> float:
    """estimated_cost, with an unpriced request counted as 0."""
    return estimated_cost(model, input_, output, cache_write, cache_read) or 0.0
