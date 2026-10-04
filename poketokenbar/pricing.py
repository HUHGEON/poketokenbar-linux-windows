"""Per-model token rates — ports ModelPricing.swift.

Rates are USD per million tokens, matching ccusage's offline LiteLLM snapshot.
An unpriced model costs 0, exactly as ccusage treats it — showing a guessed
price would be worse than showing none.
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

TABLE: dict[str, ModelRate] = {
    "claude-opus-4-8": per_million(5, 25, 6.25, 0.5),
    "claude-opus-4-7": per_million(5, 25, 6.25, 0.5),
    "claude-sonnet-4-6": per_million(3, 15, 3.75, 0.3),
    "claude-haiku-4-5-20251001": per_million(1, 5, 1.25, 0.1),
    "claude-fable-5": ZERO,  # unpriced by ccusage
    "gpt-5.5": per_million(5, 30, 0, 0.5),
    # Official standard API rates for prompts up to 272K input tokens.
    # https://developers.openai.com/api/docs/models/gpt-6.1-sol
    "gpt-6.1-sol": per_million(2, 10, 2.5, 0.1),
    # Gemini official API rates (base tier, <=200K prompt). Cache is the read
    # rate only; storage-time charges are not modelled.
    "gemini-2.5-pro": per_million(1.25, 10, 0, 0.3125),
    "gemini-2.5-flash": per_million(0.30, 2.5, 0, 0.075),
    "gemini-2.0-flash": per_million(0.10, 0.4, 0, 0.025),
}


def rate(model: str) -> ModelRate:
    """Exact match first, then a family fallback for version drift."""
    exact = TABLE.get(model)
    if exact is not None:
        return exact

    m = (model or "").lower()

    # Grok reports its own cost; there is no rate card. This must precede the
    # family fallbacks so names like grok-codex-* are not priced as GPT.
    if m.startswith("grok"):
        return ZERO
    # Antigravity is subscription-billed and reports no amount. Its
    # "antigravity/" prefix also dodges the exact table, which matters because
    # that CLI calls models like claude-sonnet-4-6 that would otherwise match.
    if m.startswith("antigravity/"):
        return ZERO

    if "opus" in m:
        return per_million(5, 25, 6.25, 0.5)
    if "sonnet" in m:
        return per_million(3, 15, 3.75, 0.3)
    if "haiku" in m:
        return per_million(1, 5, 1.25, 0.1)
    if "gpt" in m or "codex" in m or "o4" in m or "o3" in m:
        return per_million(5, 30, 0, 0.5)
    if m.startswith("gemini"):
        if "pro" in m:
            return per_million(1.25, 10, 0, 0.3125)
        if "flash" in m:
            return per_million(0.30, 2.5, 0, 0.075)
    return ZERO


def cost(model: str, input_: int, output: int, cache_write: int, cache_read: int) -> float:
    r = rate(model)
    return (
        input_ * r.input
        + output * r.output
        + cache_write * r.cache_write
        + cache_read * r.cache_read
    )
