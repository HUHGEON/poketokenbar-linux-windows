"""Per-model token rates — ports ModelPricing.swift.

Rates are USD per million tokens. A model with no row and no family fallback
costs 0 — showing a guessed price would be worse than showing none.
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
    """Exact match first, then a family fallback for version drift."""
    m = model_key(model)
    exact = TABLE.get(m)
    if exact is not None:
        return exact

    # Grok reports its own cost; there is no rate card. This must precede the
    # family fallbacks so names like grok-codex-* are not priced as GPT.
    if m.startswith("grok"):
        return ZERO
    # Antigravity is subscription-billed and reports no amount. Its
    # "antigravity/" prefix also dodges the exact table, which matters because
    # that CLI calls models like claude-sonnet-4-6 that would otherwise match.
    if m.startswith("antigravity/"):
        return ZERO

    if "fable" in m:
        return per_million(10, 50, 12.5, 1.0)
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
            return per_million(1.25, 10, 0, 0.125)
        if "flash" in m:
            return per_million(0.30, 2.5, 0, 0.03)
    return ZERO


def cost(model: str, input_: int, output: int, cache_write: int, cache_read: int) -> float:
    r = rate(model)
    return (
        input_ * r.input
        + output * r.output
        + cache_write * r.cache_write
        + cache_read * r.cache_read
    )
