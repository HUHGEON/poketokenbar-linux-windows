"""Game balance tuned for the lower token throughput of a Plus plan.

These are the Go/Plus baseline (one fifth of the original growth and prices).
Pro uses a per-save multiplier of five, including candy effects. Grants and
odds are independent of plan; never mutate module constants for an account.
"""

from __future__ import annotations

from enum import StrEnum

# Tokens the egg must absorb before it hatches. Overflow carries into the
# hatchling rather than being discarded.
EGG_HATCH_THRESHOLD = 1_000_000


class Rarity(StrEnum):
    COMMON = "common"
    UNCOMMON = "uncommon"
    RARE = "rare"
    LEGENDARY = "legendary"

    @property
    def sort_rank(self) -> int:
        return {"common": 0, "uncommon": 1, "rare": 2, "legendary": 3}[self.value]

    @property
    def capture_rate_ceiling(self) -> int | None:
        """capture_rate at or below this means the species is at least this tier.

        None for LEGENDARY: legendaries are flagged, not rate-derived, so a
        legendary-only egg cannot be expressed and is never sold.
        """
        return {"rare": 45, "uncommon": 120, "common": 255, "legendary": None}[self.value]

    def includes(self, capture_rate: int) -> bool:
        ceiling = self.capture_rate_ceiling
        return False if ceiling is None else capture_rate <= ceiling

    @staticmethod
    def classify(capture_rate: int, is_legendary: bool, is_mythical: bool) -> "Rarity":
        if is_legendary or is_mythical:
            return Rarity.LEGENDARY
        if Rarity.RARE.includes(capture_rate):
            return Rarity.RARE
        if Rarity.UNCOMMON.includes(capture_rate):
            return Rarity.UNCOMMON
        return Rarity.COMMON


GRADUATION_TOTAL: dict[Rarity, int] = {
    Rarity.COMMON: 150_000_000,
    Rarity.UNCOMMON: 375_000_000,
    Rarity.RARE: 600_000_000,
    Rarity.LEGENDARY: 1_200_000_000,
}


def graduation_total(rarity: Rarity) -> int:
    return GRADUATION_TOTAL[Rarity(rarity)]


def phase_threshold(rarity: Rarity, total_forms: int, stage_index: int, multiplier: int = 1) -> int:
    """Tokens needed at a stage before the next evolution or graduation.

    Weighted so later stages cost more while the sum over all stages equals the
    graduation total — a line's total is the same regardless of how many forms
    it has.
    """
    k = max(1, total_forms)
    i = stage_index + 1  # 1-based
    total = float(graduation_total(rarity))
    denom = (k * (k + 1)) / 2.0
    return round(total * i / denom) * multiplier


# --- items -----------------------------------------------------------------

RARE_CANDY_XP = 100_000_000
RARE_CANDY_PRICE = 100_000_000
RARE_CANDY_WEEKLY_GRANT = 5
RARE_CANDY_SESSION_GRANT = 1

MINT_PRICE = 20_000_000

SHINY_CHARM_PRICE = 600_000_000
SHINY_CHARM_DENOMINATOR = 48  # 1/64 -> 1/48 while held

FRESH_EGG_PRICE = 200_000_000
# Sold tiers: no guarantee, uncommon-or-better, rare-or-better. No legendary
# egg — the floor cannot be expressed through capture_rate.
EGG_SHOP_TIERS: list[Rarity | None] = [None, Rarity.UNCOMMON, Rarity.RARE]


def egg_price(tier: Rarity | None) -> int:
    """Premium egg price.

    Scaled by the graduation table (1 : 2.5 : 4), NOT by hatch probability.
    Probability-based pricing makes two uncommon eggs strictly dominate one
    rare egg on every axis, turning the higher tier into an inferior good.
    """
    if tier is None:
        return FRESH_EGG_PRICE
    multiplier = graduation_total(tier) / graduation_total(Rarity.COMMON)
    return round(FRESH_EGG_PRICE * multiplier)


# --- odds ------------------------------------------------------------------

SHINY_DENOMINATOR = 64
DITTO_DISGUISE_DENOMINATOR = 128
DITTO_SPECIES_ID = 132

# PokeAPI item sprite names; None means no sprite exists and the UI falls back
# to an emoji. Mint is a Gen-VIII item PokeAPI has no sprite for.
ITEM_SPRITE = {
    "rareCandy": "rare-candy",
    "mint": None,
    "shinyCharm": "shiny-charm",
}

# Catalogue keys for the words each item is shown with: (name, description,
# effect). The English tables below stay as the fallback for a caller with no
# language — the shop and the bag resolve these instead, so a Korean UI stops
# listing "Rare Candy · Raises your Pokemon's EXP by 100M." in English.
ITEM_STRINGS = {
    "rareCandy": ("item_rare_candy", "item_rare_candy_desc", "item_rare_candy_effect"),
    "mint": ("item_mint", "item_mint_desc", "item_mint_effect"),
    "shinyCharm": ("item_shiny_charm", "item_shiny_charm_desc", "item_shiny_charm_effect"),
}

# The egg tiers the shop sells, by the suffix in their key. None is the plain
# egg with no guarantee.
EGG_STRINGS = {
    None: "egg_common",
    "uncommon": "egg_uncommon",
    "rare": "egg_rare",
}

ITEM_LABEL = {
    "rareCandy": "Rare Candy",
    "mint": "Mint",
    "shinyCharm": "Shiny Charm",
}

ITEM_DESCRIPTION = {
    "rareCandy": "Raises your Pokemon's EXP by 100M.",
    "mint": "Randomly changes your Pokemon's nature.",
    "shinyCharm": "While owned, raises the chance of hatching a shiny.",
}

ITEM_EFFECT = {
    "rareCandy": "+100M XP",
    "mint": "Random nature",
    "shinyCharm": "Shiny rate up - active",
}

EGG_DESCRIPTION = {
    None: "Send off your current Pokemon and start fresh with a new egg.",
    "uncommon": "Send off your current Pokemon for an egg guaranteed to hatch Uncommon or better.",
    "rare": "Send off your current Pokemon for an egg guaranteed to hatch Rare or better.",
}

NATURES = [
    "hardy", "lonely", "brave", "adamant", "naughty",
    "bold", "docile", "relaxed", "impish", "lax",
    "timid", "hasty", "serious", "jolly", "naive",
    "modest", "mild", "quiet", "bashful", "rash",
    "calm", "gentle", "sassy", "careful", "quirky",
]
