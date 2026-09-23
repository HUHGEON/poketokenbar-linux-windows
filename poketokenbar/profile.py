"""Persistent individual Pokemon profiles and battle-stat calculations."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field

STAT_ORDER = ("hp", "attack", "defense", "special-attack", "special-defense", "speed")


@dataclass(slots=True)
class PokemonProfile:
    instance_id: str
    seed: int
    ivs: dict[str, int]
    gender: str | None = None
    ability_slot: int | None = None
    ability_name: str | None = None
    ability_is_hidden: bool = False
    level: int = 5
    moves: list[dict] = field(default_factory=list)

    @classmethod
    def generate(cls, rng: random.Random | None = None, seed: int | None = None):
        rng = rng or random.Random()
        seed = rng.getrandbits(64) if seed is None else int(seed)
        values = random.Random(seed)
        return cls(str(uuid.uuid4()), seed,
                   {name: values.randrange(32) for name in STAT_ORDER})

    def enrich(self, details: dict) -> None:
        values = random.Random(self.seed ^ 0xA11B1E5D9EED)
        if self.gender is None:
            rate = int(details.get("gender_rate", -1))
            self.gender = "genderless" if rate < 0 else (
                "female" if values.randrange(8) < rate else "male")
        abilities = list(details.get("abilities") or [])
        normal = sorted((a for a in abilities if not a.get("is_hidden")),
                        key=lambda a: a.get("slot", 0))
        hidden = sorted((a for a in abilities if a.get("is_hidden")),
                        key=lambda a: a.get("slot", 0))
        if self.ability_slot is None:
            pool = hidden if hidden and values.randrange(128) == 0 else normal
            if not pool:
                pool = hidden
            if pool:
                chosen = pool[values.randrange(len(pool))]
                self.ability_slot = int(chosen.get("slot", 0))
                self.ability_is_hidden = bool(chosen.get("is_hidden"))
        chosen = next((a for a in abilities if a.get("slot") == self.ability_slot
                       and bool(a.get("is_hidden")) == self.ability_is_hidden), None)
        chosen = chosen or next((a for a in abilities
                                 if a.get("slot") == self.ability_slot), None)
        if chosen:
            self.ability_name = str(chosen.get("name") or "") or None
            self.ability_is_hidden = bool(chosen.get("is_hidden"))
        learned = [m for m in details.get("moves") or []
                   if int(m.get("learned_at", 0)) <= self.level]
        learned.sort(key=lambda m: (int(m.get("learned_at", 0)), str(m.get("name", ""))))
        self.moves = learned[-4:]

    def advance(self, progress: float) -> None:
        target = 5 + int(max(0.0, min(1.0, progress)) * 95)
        self.level = max(self.level, min(100, target))

    def sanitize(self) -> None:
        self.level = max(5, min(100, int(self.level)))
        self.ivs = {name: max(0, min(31, int(self.ivs.get(name, 0))))
                    for name in STAT_ORDER}
        self.moves = [m for m in self.moves[:4] if isinstance(m, dict)]
        if not self.instance_id:
            self.instance_id = str(uuid.uuid4())


_NATURES = {
    "lonely": ("attack", "defense"), "brave": ("attack", "speed"),
    "adamant": ("attack", "special-attack"), "naughty": ("attack", "special-defense"),
    "bold": ("defense", "attack"), "relaxed": ("defense", "speed"),
    "impish": ("defense", "special-attack"), "lax": ("defense", "special-defense"),
    "timid": ("speed", "attack"), "hasty": ("speed", "defense"),
    "jolly": ("speed", "special-attack"), "naive": ("speed", "special-defense"),
    "modest": ("special-attack", "attack"), "mild": ("special-attack", "defense"),
    "quiet": ("special-attack", "speed"), "rash": ("special-attack", "special-defense"),
    "calm": ("special-defense", "attack"), "gentle": ("special-defense", "defense"),
    "sassy": ("special-defense", "speed"), "careful": ("special-defense", "special-attack"),
}


def computed_stats(details: dict, profile: PokemonProfile,
                   nature: str | None) -> list[dict]:
    base_stats = details.get("base_stats") or {}
    raised, lowered = _NATURES.get(nature or "", (None, None))
    out = []
    for name in STAT_ORDER:
        if name not in base_stats:
            continue
        base, iv = int(base_stats[name]), profile.ivs[name]
        if name == "hp":
            value = ((2 * base + iv) * profile.level) // 100 + profile.level + 10
        else:
            value = ((2 * base + iv) * profile.level) // 100 + 5
            value = int(value * (1.1 if name == raised else 0.9 if name == lowered else 1.0))
        out.append({"name": name, "base": base, "iv": iv, "value": value})
    return out
