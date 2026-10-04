"""Per-model token rates — ports ModelPricing.swift.

Standard API-equivalent rates ported from upstream v2.5.5. Unknown models
have no estimate; the numeric compatibility interface returns zero.
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
    "claude-opus-5": per_million(5, 25, 6.25, 0.5),
    "claude-opus-5-5": per_million(4, 20, 5, 0.2),
    "claude-sonnet-5": per_million(2, 10, 2.5, 0.2),
    "claude-opus-4-20250514": per_million(15, 75, 18.75, 1.5),
    "claude-sonnet-4-20250514": per_million(3, 15, 3.75, 0.3),
    "claude-sonnet-4-5-20250929": per_million(3, 15, 3.75, 0.3),
    "claude-opus-4-8": per_million(5, 25, 6.25, 0.5),
    "claude-opus-4-7": per_million(5, 25, 6.25, 0.5),
    "claude-sonnet-4-6": per_million(3, 15, 3.75, 0.3),
    "claude-haiku-4-5-20251001": per_million(1, 5, 1.25, 0.1),
    "claude-fable-5": per_million(10, 50, 12.5, 1.0),
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
    "gemini-2.5-pro": per_million(1.25, 10, 0, 0.125),
    "gemini-2.5-flash": per_million(0.30, 2.5, 0, 0.03),
    "gemini-2.5-flash-lite": per_million(0.10, 0.40, 0, 0.01),
    "gemini-2.0-flash": per_million(0.10, 0.4, 0, 0.025),
    # Official standard API rates for prompts up to 272K input tokens.
    # https://developers.openai.com/api/docs/models/gpt-6.1-sol
    "gpt-6.1-sol": per_million(2, 10, 2.5, 0.1),
}

ALIASES = {
    "gpt-5.6": "gpt-5.6-sol",
    "claude-sonnet-4": "claude-sonnet-4-20250514",
    "claude-opus-4": "claude-opus-4-20250514",
    "claude-sonnet-4-5": "claude-sonnet-4-5-20250929",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
    "gpt-5-2025-08-07": "gpt-5",
    "gpt-5.1-2025-11-13": "gpt-5.1",
    "gpt-5.2-2025-12-11": "gpt-5.2",
    "gpt-5.4-2026-03-05": "gpt-5.4",
    "gpt-5.5-2026-04-23": "gpt-5.5"
}


def model_key(model: str) -> str:
    key = (model or "").strip().lower()
    for prefix in ("openai/", "anthropic/", "google/", "models/"):
        if key.startswith(prefix):
            key = key[len(prefix):]
            break
    return ALIASES.get(key, key)


def rate(model: str) -> ModelRate:
    """Only documented identities are priced; unknown versions stay unavailable."""
    return TABLE.get(model_key(model), ZERO)


def estimated_cost(model: str, input_: int, output: int, cache_write: int,
                   cache_read: int) -> float | None:
    key = model_key(model)
    r = TABLE.get(key)
    if r is None or min(input_, output, cache_write, cache_read) < 0:
        return None
    if cache_write and not r.cache_write:
        return None
    prompt = input_ + cache_write + cache_read
    long_context = (
        key in {"gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5.5", "gpt-5.4"}
        and prompt > 272_000
    ) or (key == "gemini-2.5-pro" and prompt > 200_000)
    return ((input_ * r.input + cache_write * r.cache_write + cache_read * r.cache_read)
            * (2 if long_context else 1) + output * r.output * (1.5 if long_context else 1))


def cost(model: str, input_: int, output: int, cache_write: int, cache_read: int) -> float:
    return estimated_cost(model, input_, output, cache_write, cache_read) or 0.0
