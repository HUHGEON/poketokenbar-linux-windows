"""Dex completion by generation — ports PokedexRegion.swift (upstream a49237c).

Which generation a species belongs to follows from its National Dex number
alone — Kanto is 1-151, Johto 152-251, Hoenn 252-386, Sinnoh 387-493, Unova
494-649 — so nothing has to be fetched to place one. Gen 1-5 is also exactly
what can hatch here, because that is as far as the animated Black/White
sprites go.

The badges are cosmetic: finishing a region, finishing it in shiny, all 28
Unown letters, and the National Dex either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import forms

# Name, first and last National Dex number.
REGIONS: tuple[tuple[str, int, int], ...] = (
    ("kanto", 1, 151),
    ("johto", 152, 251),
    ("hoenn", 252, 386),
    ("sinnoh", 387, 493),
    ("unova", 494, 649),
)

NATIONAL_FIRST, NATIONAL_LAST = 1, 649


def region_of(species_id: int) -> str | None:
    """The region a dex number belongs to, or None outside generations 1-5."""
    for name, first, last in REGIONS:
        if first <= species_id <= last:
            return name
    return None


def total_of(region: str) -> int:
    for name, first, last in REGIONS:
        if name == region:
            return last - first + 1
    return 0


NATIONAL_TOTAL = NATIONAL_LAST - NATIONAL_FIRST + 1


@dataclass(frozen=True, slots=True)
class Completion:
    """How much of one region is collected, and how much of it in shiny."""

    region: str
    owned: int
    shiny_owned: int
    total: int

    @property
    def complete(self) -> bool:
        return self.owned >= self.total

    @property
    def shiny_complete(self) -> bool:
        return self.shiny_owned >= self.total


def completions(owned: dict[int, bool]) -> list[Completion]:
    """One row per region, from {species id: owned in shiny}.

    A species counts once however many of it were caught, and counts as shiny
    when any one of them was.
    """
    out = []
    for name, first, last in REGIONS:
        ids = [sid for sid in owned if first <= sid <= last]
        out.append(Completion(
            region=name,
            owned=len(ids),
            shiny_owned=sum(1 for sid in ids if owned[sid]),
            total=last - first + 1,
        ))
    return out


def national(owned: dict[int, bool]) -> Completion:
    ids = [sid for sid in owned if NATIONAL_FIRST <= sid <= NATIONAL_LAST]
    return Completion(
        region="national",
        owned=len(ids),
        shiny_owned=sum(1 for sid in ids if owned[sid]),
        total=NATIONAL_TOTAL,
    )


def badges(owned: dict[int, bool], unown_forms: int) -> list[str]:
    """Every badge earned, by the key it is remembered under.

    The keys are persisted, so they must not drift between releases.
    """
    earned = []
    for found in completions(owned):
        if found.complete:
            earned.append(f"region.{found.region}")
        if found.shiny_complete:
            earned.append(f"regionShiny.{found.region}")
    if unown_forms >= len(forms.forms(forms.UNOWN_SPECIES_ID)):
        earned.append("unown")
    whole = national(owned)
    if whole.complete:
        earned.append("national")
    if whole.shiny_complete:
        earned.append("nationalShiny")
    return earned
