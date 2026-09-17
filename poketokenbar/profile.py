"""Individual Pokémon profiles — ports PokemonProfile.swift (upstream b6bf676).

A profile is what makes one caught Pokémon distinct from another of its
species: individual values, gender, ability, level and known moves. It is
rolled from a 64-bit seed with upstream's SplitMix64 generator, so the same
seed produces the same individual on either app.

Pure functions and dataclasses only. Species metadata (base stats, abilities,
learnsets) arrives as PokemonDetails from pokeapi.py; nothing here touches the
network or the disk.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from . import balance
from .balance import Rarity

# Save-transfer ceiling for any token count, as upstream's maxTokenValue.
MAX_TOKEN_VALUE = 1_000_000_000_000_000

_MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15
# Enrichment draws from its own stream, so rolling gender and ability never
# shifts the IVs generated from the same seed.
_ENRICH_SALT = 0xA11B1E5D9EED

STAT_ORDER = ("hp", "attack", "defense", "special-attack", "special-defense", "speed")
HATCH_LEVEL = 5
MAX_LEVEL = 100
MAX_MOVES = 4
# Learnsets come from Black 2/White 2: hatchable species stop at Gen V, where
# the animated sprites stop. Keep in step if that bound is ever raised.
PREFERRED_VERSION_GROUP = "black-2-white-2"

# (raised, lowered) per nature; the five neutral natures are absent.
NATURE_MODIFIERS: dict[str, tuple[str, str]] = {
    "lonely": ("attack", "defense"),
    "brave": ("attack", "speed"),
    "adamant": ("attack", "special-attack"),
    "naughty": ("attack", "special-defense"),
    "bold": ("defense", "attack"),
    "relaxed": ("defense", "speed"),
    "impish": ("defense", "special-attack"),
    "lax": ("defense", "special-defense"),
    "timid": ("speed", "attack"),
    "hasty": ("speed", "defense"),
    "jolly": ("speed", "special-attack"),
    "naive": ("speed", "special-defense"),
    "modest": ("special-attack", "attack"),
    "mild": ("special-attack", "defense"),
    "quiet": ("special-attack", "speed"),
    "rash": ("special-attack", "special-defense"),
    "calm": ("special-defense", "attack"),
    "gentle": ("special-defense", "defense"),
    "sassy": ("special-defense", "speed"),
    "careful": ("special-defense", "special-attack"),
}


class ProfileRNG:
    """SplitMix64, bit for bit as upstream's ProfileRNG."""

    def __init__(self, seed: int) -> None:
        seed &= _MASK64
        self.state = _GOLDEN if seed == 0 else seed

    def next(self) -> int:
        self.state = (self.state + _GOLDEN) & _MASK64
        value = self.state
        value = ((value ^ (value >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
        value = ((value ^ (value >> 27)) * 0x94D049BB133111EB) & _MASK64
        return value ^ (value >> 31)


def migration_seed(text: str) -> int:
    """FNV-1a 64 over UTF-8, as upstream's PokemonProfileMigration.seed."""
    value = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        value = ((value ^ byte) * 0x100000001B3) & _MASK64
    return value


# MARK: species metadata


@dataclass(slots=True)
class AbilityOption:
    name: str
    slot: int
    is_hidden: bool


@dataclass(slots=True)
class LearnMethod:
    method: str
    level: int


@dataclass(slots=True)
class MoveOption:
    name: str
    learn_methods: list[LearnMethod]


@dataclass(slots=True)
class PokemonDetails:
    """Immutable PokéAPI metadata for one species' default form."""

    species_id: int
    name: str
    height: int  # decimetres
    weight: int  # hectograms
    base_experience: int | None
    gender_rate: int  # eighths female; -1 is genderless
    types: list[str]
    base_stats: dict[str, int]
    abilities: list[AbilityOption]
    moves: list[MoveOption]

    @property
    def base_stat_total(self) -> int:
        return sum(self.base_stats.values())

    def level_up_moves(self, through: int) -> list["KnownMove"]:
        """Level-up moves learnable at or below a level, earliest first."""
        best: dict[str, int] = {}
        for move in self.moves:
            levels = [m.level for m in move.learn_methods
                      if m.method == "level-up" and m.level <= through]
            if levels:
                best[move.name] = min(best.get(move.name, min(levels)), min(levels))
        return sorted((KnownMove(name, level) for name, level in best.items()),
                      key=lambda m: (m.learned_at_level, m.name))


# MARK: the individual


@dataclass(slots=True)
class KnownMove:
    name: str
    learned_at_level: int


@dataclass(slots=True)
class PokemonProfile:
    instance_id: str
    seed: int
    ivs: dict[str, int]
    gender: str | None = None  # "male" | "female" | "genderless"
    ability_slot: int | None = None
    ability_name: str | None = None
    ability_is_hidden: bool = False
    level: int = HATCH_LEVEL
    # Earned growth in default-balance units, independent of difficulty and of
    # the repeat-hatch boost, so neither can change a level already reached.
    growth_tokens: int = 0
    moves: list[KnownMove] = field(default_factory=list)


def _instance_id(seed: int) -> str:
    return str(uuid.UUID(int=(seed << 64) | migration_seed(f"instance:{seed}")))


def generate(seed: int, growth_tokens: int = 0, instance_id: str | None = None) -> PokemonProfile:
    """Roll a new individual: six IVs from the seed, level 5.

    Gender, ability and moves need the species' details, so enrich() fills
    them later. The instance id is derived from the seed unless given, which
    keeps a migrated save's individuals the same on every machine.
    """
    seed &= _MASK64
    rng = ProfileRNG(seed)
    ivs = {stat: rng.next() % 32 for stat in STAT_ORDER}
    profile = PokemonProfile(
        instance_id=instance_id or _instance_id(seed),
        seed=seed,
        ivs=ivs,
        growth_tokens=max(0, growth_tokens),
    )
    return profile


def enrich(profile: PokemonProfile, details: PokemonDetails) -> None:
    """Fill the species-dependent fields. Never rerolls one already set."""
    rng = ProfileRNG(profile.seed ^ _ENRICH_SALT)
    if profile.gender is None:
        if details.gender_rate < 0:
            profile.gender = "genderless"
        else:
            profile.gender = "female" if rng.next() % 8 < details.gender_rate else "male"

    normal = sorted((a for a in details.abilities if not a.is_hidden), key=lambda a: a.slot)
    hidden = sorted((a for a in details.abilities if a.is_hidden), key=lambda a: a.slot)
    if profile.ability_slot is None:
        # Hidden abilities are deliberately rare; normal slots are even odds.
        if hidden and rng.next() % 128 == 0:
            profile.ability_slot = hidden[rng.next() % len(hidden)].slot
            profile.ability_is_hidden = True
        elif normal:
            profile.ability_slot = normal[rng.next() % len(normal)].slot
            profile.ability_is_hidden = False
        elif details.abilities:
            fallback = min(details.abilities, key=lambda a: a.slot)
            profile.ability_slot = fallback.slot
            profile.ability_is_hidden = fallback.is_hidden

    chosen = (
        next((a for a in details.abilities
              if a.slot == profile.ability_slot and a.is_hidden == profile.ability_is_hidden), None)
        or next((a for a in details.abilities if a.slot == profile.ability_slot), None)
        or (normal[0] if normal else None)
        or (hidden[0] if hidden else None)
    )
    profile.ability_name = chosen.name if chosen else None
    if chosen is not None:
        profile.ability_slot = chosen.slot
        profile.ability_is_hidden = chosen.is_hidden

    # The four most recently learned level-up moves.
    profile.moves = details.level_up_moves(profile.level)[-MAX_MOVES:]


def advance_growth(profile: PokemonProfile, candidate: int, rarity: Rarity) -> None:
    """Raise growth and level to a candidate, never lower them.

    A difficulty change or an import can make the candidate smaller than what
    was already earned; the high-water mark keeps the earned level.
    """
    profile.growth_tokens = min(MAX_TOKEN_VALUE, max(profile.growth_tokens, max(0, candidate)))
    total = max(1, balance.graduation_total(rarity))
    progress = min(1.0, profile.growth_tokens / total)
    profile.level = min(MAX_LEVEL, max(profile.level, HATCH_LEVEL + int(progress * 95)))


def apply_growth(profile: PokemonProfile, delta: int, rarity: Rarity) -> None:
    advance_growth(profile, profile.growth_tokens + max(0, delta), rarity)


def rebase_for_species_identity(profile: PokemonProfile, old: Rarity, new: Rarity) -> None:
    """A Ditto reveal: same individual, different species.

    The IVs stay; everything that depended on the disguise's species is
    cleared so the next enrichment rolls it for Ditto. Growth keeps its
    fraction of the graduation total across the rarity change.
    """
    fraction = min(1.0, max(0, profile.growth_tokens) / balance.graduation_total(old))
    rebased = int(fraction * balance.graduation_total(new))
    profile.gender = None
    profile.ability_slot = None
    profile.ability_name = None
    profile.ability_is_hidden = False
    profile.moves = []
    profile.growth_tokens = rebased
    advance_growth(profile, rebased, new)


def sanitize(profile: PokemonProfile) -> None:
    """Clamp a profile read from a file anyone could have edited."""
    profile.level = min(MAX_LEVEL, max(HATCH_LEVEL, profile.level))
    profile.growth_tokens = min(MAX_TOKEN_VALUE, max(0, profile.growth_tokens))
    profile.ivs = {stat: min(31, max(0, int(profile.ivs.get(stat, 0)))) for stat in STAT_ORDER}
    profile.moves = [
        KnownMove(m.name[:80], min(MAX_LEVEL, max(0, m.learned_at_level)))
        for m in profile.moves[:MAX_MOVES]
    ]
    if profile.gender not in (None, "male", "female", "genderless"):
        profile.gender = None
    if not profile.instance_id:
        profile.instance_id = _instance_id(profile.seed)


# MARK: stats


@dataclass(slots=True)
class ComputedStat:
    name: str
    base: int
    iv: int
    value: int


def nature_modifier(nature: str | None, stat: str) -> float:
    pair = NATURE_MODIFIERS.get(nature or "")
    if pair is None:
        return 1.0
    if stat == pair[0]:
        return 1.1
    if stat == pair[1]:
        return 0.9
    return 1.0


def compute_stats(details: PokemonDetails, profile: PokemonProfile,
                  nature: str | None) -> list[ComputedStat]:
    """Actual stats at the profile's level. No EVs, as upstream."""
    out = []
    level = profile.level
    for stat in STAT_ORDER:
        base = details.base_stats.get(stat)
        if base is None:
            continue
        iv = profile.ivs.get(stat, 0)
        if stat == "hp":
            value = ((2 * base + iv) * level) // 100 + level + 10
        else:
            neutral = ((2 * base + iv) * level) // 100 + 5
            # A plain floor of the double, as Swift's rounded(.down), so both
            # apps agree on every value.
            value = int(neutral * nature_modifier(nature, stat))
        out.append(ComputedStat(stat, base, iv, value))
    return out


def display_scale_maximum(values: list[int]) -> int:
    """Stat bar scale: at least 300, rounded up to a hundred."""
    highest = max(300, max(values, default=300))
    remainder = highest % 100
    return highest if remainder == 0 else highest + (100 - remainder)


# MARK: growth reconstruction


def reconstructed_growth_tokens(rarity: Rarity, total_forms: int,
                                completed_stages: int, current_stage_usage: int) -> int:
    """Default-balance growth for completed stages plus current usage."""
    forms = max(1, total_forms)
    completed = min(max(0, completed_stages), forms)
    growth = sum(balance.phase_threshold(rarity, forms, stage) for stage in range(completed))
    return min(MAX_TOKEN_VALUE, growth + min(MAX_TOKEN_VALUE, max(0, current_stage_usage)))
