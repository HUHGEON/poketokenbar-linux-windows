"""Unown's 28 letters — ports UnownForm.swift (upstream 10d1a07).

Unown (#201) is one species with 28 collectible forms: A–Z, ! and ?. The letter
is an attribute of the individual, independent of its species and of whether it
is shiny, and it stays with the Pokémon through raising, graduation, release
and a save export.

Nothing else about the species changes: evolution paths, difficulty, the
repeat-hatch bonus and the shiny odds all keep working on the species.
"""

from __future__ import annotations

import random

SPECIES_ID = 201

FORMS: tuple[str, ...] = (
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "exclamation", "question",
)

# An uncollected letter is twice as likely as one already collected — the same
# adjustment the species roll makes, and no streak counter or guarantee behind
# it. Once every letter is collected the draw is uniform again.
UNCOLLECTED_WEIGHT = 2


def is_form(value) -> bool:
    return isinstance(value, str) and value in FORMS


def symbol(form: str) -> str:
    """What the letter is written as: "B", "!", "?"."""
    if form == "exclamation":
        return "!"
    if form == "question":
        return "?"
    return form.upper()


def sort_order(form: str) -> int:
    return FORMS.index(form) if form in FORMS else len(FORMS)


def collection_weight(form: str, collected) -> int:
    """Ports CollectionWeight.adjusted: halved once collected, never zero."""
    weight = UNCOLLECTED_WEIGHT
    return max(1, weight // 2) if form in collected else max(1, weight)


def roll(rng: random.Random, collected=()) -> str:
    """Pick a letter, favouring the ones not collected yet.

    Only runs once the species roll has already landed on Unown, so it changes
    neither species weights nor shiny odds.
    """
    collected = set(collected)
    weights = [collection_weight(form, collected) for form in FORMS]
    return rng.choices(FORMS, weights=weights, k=1)[0]


def resolved(species_id: int, form: str | None) -> str | None:
    """The letter to use for a species, or None when it has none.

    An Unown saved before letters existed showed the default A sprite; keeping
    that appearance is what "no letter recorded" has to mean. A letter stored
    against any other species is ignored rather than drawn.
    """
    if species_id != SPECIES_ID:
        return None
    return form if is_form(form) else "a"


def display_name(name: str, species_id: int, form: str | None) -> str:
    """"Unown [B]" — the letter belongs beside the name wherever one is shown."""
    letter = resolved(species_id, form)
    if letter is None:
        return name
    return f"{name} [{symbol(letter)}]"


def asset_name(species_id: int, form: str | None) -> str:
    """The sprite file this individual is drawn from.

    A keeps the plain "201", so every sprite cached before letters existed is
    still the right file for it.
    """
    letter = resolved(species_id, form)
    if letter is None or letter == "a":
        return str(species_id)
    return f"{species_id}-{letter}"
