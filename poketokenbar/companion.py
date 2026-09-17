"""Companion state and growth — ports CompanionModel/CompanionStore.swift.

Pure functions over CompanionState with no I/O, so the whole game is testable
without a network or a filesystem. Species data arrives through an injected
line provider; persistence lives in save.py.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import balance
from .balance import Rarity


@dataclass(slots=True)
class EvoLine:
    """One evolution line: ordered species ids from base to final."""

    base_id: int
    path_ids: list[int]
    rarity: Rarity
    names: dict[int, dict[str, str]] = field(default_factory=dict)

    @property
    def total_forms(self) -> int:
        return len(self.path_ids)


@dataclass(slots=True)
class MonState:
    base_id: int
    path_ids: list[int]
    planned_path_ids: list[int]
    stage_index: int = 0
    used_at_stage: int = 0
    rarity: Rarity = Rarity.COMMON
    total_forms: int = 1
    is_shiny: bool = False
    nature: str | None = None
    ditto_disguise: int | None = None
    ditto_revealed: bool = False
    hatched_at: float | None = None

    @property
    def current_id(self) -> int:
        """Species currently displayed.

        Falls back to base_id when path_ids is empty so a damaged save cannot
        crash rendering, which happens on every frame.
        """
        if self.ditto_revealed:
            return balance.DITTO_SPECIES_ID
        if not self.path_ids:
            return self.base_id
        return self.path_ids[min(self.stage_index, len(self.path_ids) - 1)]

    @property
    def is_final_form(self) -> bool:
        return self.stage_index >= len(self.path_ids) - 1


@dataclass(slots=True)
class DexEntry:
    base_id: int
    final_id: int
    chain_order: list[int]
    rarity: Rarity
    is_shiny: bool = False
    nature: str | None = None
    # Epoch seconds. None on entries written before this was tracked; those
    # sort last rather than pretending to be ancient.
    caught_at: float | None = None
    raised_seconds: float | None = None
    # Epoch seconds when a shop egg released this companion before it
    # graduated. None is a graduation, which is also what every entry written
    # before this field reads as, so old saves need no migration.
    released_at: float | None = None

    @property
    def is_released(self) -> bool:
        return self.released_at is not None


@dataclass(slots=True)
class CompanionState:
    # Tokens are only counted from install onward.
    install_baseline_set: bool = False
    used_since_install: int = 0
    # Ledger of tokens spent in the shop. Spendable = used_since_install
    # - spent_tokens. The growth meter (used_since_install) never rewinds.
    spent_tokens: int = 0
    # Tokens absorbed by the current egg; resets per egg.
    egg_usage: int = 0
    # Rarity floor a premium egg guarantees. Persisted because the species roll
    # needs the network, which may be unavailable at purchase time.
    egg_tier: Rarity | None = None
    pending_hatch_id: int | None = None
    claimed_today_tokens_by_provider: dict[str, int] | None = None
    last_date: str = ""
    active: MonState | None = None
    # Species pinned to the panel and the desktop pet. None follows whatever is
    # being raised (or the egg). A species, not an individual: nature and the
    # rest belong to the companion, which Home keeps showing either way.
    representative_species_id: int | None = None
    dex: list[DexEntry] = field(default_factory=list)
    collected_finals: set[str] = field(default_factory=set)
    language: str = "en"
    inventory: dict[str, int] = field(default_factory=dict)
    candy_grant_tier: dict[str, int] = field(default_factory=dict)
    candy_feature_seeded: bool = False

    @property
    def spendable_tokens(self) -> int:
        return max(0, self.used_since_install - self.spent_tokens)

    def reached_species(self) -> list[int]:
        """Stages the current companion has actually reached.

        Not the whole planned line: a form it has not evolved into yet is not
        something anyone owns.
        """
        if self.active is None:
            return []
        return list(self.active.path_ids[: self.active.stage_index + 1])

    def owns_species(self, species_id: int) -> bool:
        """Whether a graduation record or the current companion covers this species.

        A light path on purpose — checking one species must not build the whole
        Pokedex display model.
        """
        if any(species_id in entry.chain_order for entry in self.dex):
            return True
        return species_id in self.reached_species()

    def owns_shiny_species(self, species_id: int) -> bool:
        """Whether the owned copy of this species is shiny.

        A Ditto still in disguise keeps its shininess hidden until it reveals —
        the panel must not spoil the reveal.
        """
        if any(e.is_shiny and species_id in e.chain_order for e in self.dex):
            return True
        active = self.active
        if active is None or not active.is_shiny:
            return False
        if species_id not in self.reached_species():
            return False
        return active.ditto_disguise is None or active.ditto_revealed

    def reconcile_representative(self) -> None:
        """Drop a pin that no longer names a species the user owns.

        Buying a fresh egg, a Ditto revealing itself, or a hand-edited save
        would otherwise leave a ghost species on the panel permanently.
        """
        if self.representative_species_id is None:
            return
        if not self.owns_species(self.representative_species_id):
            self.representative_species_id = None


@dataclass(slots=True)
class GrowthEvents:
    """What happened during one apply_usage call, for notifications."""

    hatched: int | None = None
    evolved_to: int | None = None
    graduated: DexEntry | None = None
    ditto_revealed: bool = False

    def merge(self, other: "GrowthEvents") -> "GrowthEvents":
        """Fold a later set of events into this one.

        One poll can grow the companion twice — a rare candy taken out of the
        bag, and then the usage since the last poll — but the notifier is told
        once, at the end. Replacing dropped whichever happened first, which in
        practice was always the candy.
        """
        return GrowthEvents(
            hatched=self.hatched if other.hatched is None else other.hatched,
            evolved_to=(
                self.evolved_to if other.evolved_to is None else other.evolved_to
            ),
            graduated=self.graduated if other.graduated is None else other.graduated,
            ditto_revealed=self.ditto_revealed or other.ditto_revealed,
        )


def display_state(
    state: CompanionState,
    today_tokens: int,
    limit_warning: bool = False,
    just_evolved: bool = False,
) -> str:
    """Which mood the companion is in — ports computeState().

    Order matters: a level-up beats a limit warning, which beats sleep. Any
    other ordering hides the celebration behind a warning.
    """
    if state.active is None:
        return "egg"
    if just_evolved:
        return "levelUp"
    if limit_warning:
        return "tired"
    if today_tokens <= 0:
        return "sleep"
    # Burn tiers, in tokens/day equivalents.
    if today_tokens >= 150_000_000:
        return "focus"
    if today_tokens >= 20_000_000:
        return "working"
    return "idle"


STATUS_MESSAGE = {
    "egg": "An egg is warming up.",
    "idle": "Keeping quiet today.",
    "working": "Today's work is piling up.",
    "focus": "In focus mode now.",
    "tired": "Careful — the limit is close.",
    "sleep": "Sleeping now.",
    "levelUp": "It grew!",
}


def roll_shiny(rng: random.Random, has_charm: bool) -> bool:
    denominator = (
        balance.SHINY_CHARM_DENOMINATOR if has_charm else balance.SHINY_DENOMINATOR
    )
    return rng.randrange(denominator) == 0


def roll_nature(rng: random.Random) -> str:
    return rng.choice(balance.NATURES)


def roll_ditto(rng: random.Random, line: EvoLine) -> bool:
    """Whether this hatch is secretly a disguised Ditto.

    Restricted to common lines with 2+ forms, matching the Swift rule: the joke
    only lands when the disguise is something ordinary that visibly "evolves"
    before the reveal.
    """
    if line.rarity != Rarity.COMMON or line.total_forms < 2:
        return False
    return rng.randrange(balance.DITTO_DISGUISE_DENOMINATOR) == 0


def hatch(state: CompanionState, line: EvoLine, rng: random.Random) -> MonState:
    """Turn the egg into a companion. Shiny and nature are fixed here."""
    has_charm = state.inventory.get("shinyCharm", 0) > 0
    mon = MonState(
        base_id=line.base_id,
        path_ids=list(line.path_ids),
        planned_path_ids=list(line.path_ids),
        stage_index=0,
        used_at_stage=0,
        rarity=line.rarity,
        total_forms=line.total_forms,
        is_shiny=roll_shiny(rng, has_charm),
        nature=roll_nature(rng),
        hatched_at=__import__("time").time(),
        # The disguise stores the species being impersonated; the reveal swaps
        # the display to Ditto while keeping this for the "it was Ditto!" moment.
        ditto_disguise=line.base_id if roll_ditto(rng, line) else None,
    )
    state.active = mon
    # The guarantee is consumed by the hatch it paid for.
    state.egg_tier = None
    state.pending_hatch_id = None
    state.egg_usage = 0
    return mon


def release(state: CompanionState, mon: MonState, now: float | None = None) -> DexEntry:
    """Record a companion a shop egg replaces, so its species stay in the dex.

    Ports upstream's releasedDexEntry (60808c5). Buying an egg used to drop the
    companion without a trace, which was the one way the Pokedex could shrink.

    - Only reached forms are credited, the same prefix the dex lists while
      raising. The planned path would make an egg a shortcut to evolutions
      never reached.
    - Shiny is recorded as currently shown, so releasing a disguised Ditto
      does not reveal it.
    - collected_finals is untouched: the line was not raised to its final
      form, so it must not count toward completion or branch weighting.
    """
    import time as _time

    now = _time.time() if now is None else now
    # At least one form survives a damaged stage_index, as current_id does.
    chain = list(mon.path_ids[: max(1, mon.stage_index + 1)]) or [mon.base_id]
    entry = DexEntry(
        base_id=mon.base_id,
        # Named the way graduate names a revealed Ditto.
        final_id=mon.current_id if mon.ditto_revealed else chain[-1],
        chain_order=chain,
        rarity=mon.rarity,
        is_shiny=mon.is_shiny and (mon.ditto_disguise is None or mon.ditto_revealed),
        nature=mon.nature,
        # The catch log sorts on caught_at, so it is when the record was made.
        caught_at=now,
        raised_seconds=(now - mon.hatched_at) if mon.hatched_at else None,
        released_at=now,
    )
    state.dex.append(entry)
    return entry


def graduate(state: CompanionState, mon: MonState, now: float | None = None) -> DexEntry:
    """Archive a completed companion and clear the slot for a fresh egg."""
    import time as _time

    now = _time.time() if now is None else now
    entry = DexEntry(
        base_id=mon.base_id,
        final_id=mon.current_id,
        chain_order=list(mon.path_ids),
        rarity=mon.rarity,
        is_shiny=mon.is_shiny,
        nature=mon.nature,
        caught_at=now,
        raised_seconds=(now - mon.hatched_at) if mon.hatched_at else None,
    )
    state.dex.append(entry)
    state.collected_finals.add(f"{mon.base_id}-{mon.current_id}")
    # The pin is left exactly where the user put it, graduation included.
    #
    # It used to be released here, because a pin nobody could see or clear kept
    # the graduated Pokemon on the panel through the next egg and the hatch
    # after it, and that was indistinguishable from a stuck panel. The pin is
    # now badged in the Pokedex and carries its own release button on Home, so
    # the reason for overruling the user is gone — and keeping a favourite on
    # the panel through the egg stage is what pinning is for.
    state.active = None
    state.egg_usage = 0
    return entry


def apply_usage(
    state: CompanionState,
    tokens: int,
    line_for_egg=None,
    rng: random.Random | None = None,
) -> GrowthEvents:
    """Feed tokens to the companion.

    Overflow always carries forward, so a single large delta can hatch and then
    immediately advance a stage rather than being clipped.
    """
    events = GrowthEvents()
    if tokens <= 0:
        return events
    rng = rng or random.Random()

    state.used_since_install += tokens

    # --- egg ---
    if state.active is None:
        state.egg_usage += tokens
        if state.egg_usage < balance.EGG_HATCH_THRESHOLD:
            return events
        if line_for_egg is None:
            # No species data (offline). Hold the tokens in the egg and hatch
            # once a line is available — never discard progress.
            return events
        overflow = state.egg_usage - balance.EGG_HATCH_THRESHOLD
        mon = hatch(state, line_for_egg, rng)
        events.hatched = mon.current_id
        tokens = overflow
        if tokens <= 0:
            return events

    # --- growth ---
    mon = state.active
    mon.used_at_stage += tokens
    while True:
        threshold = balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
        if mon.used_at_stage < threshold:
            break
        mon.used_at_stage -= threshold
        if mon.is_final_form:
            events.graduated = graduate(state, mon)
            break
        mon.stage_index += 1
        events.evolved_to = mon.current_id
        # A disguised Ditto reveals itself on its first evolution — the moment
        # the "evolution" would have to actually happen.
        if mon.ditto_disguise is not None and not mon.ditto_revealed:
            mon.ditto_revealed = True
            events.ditto_revealed = True
        # The pin does not move. It names a species the user chose, and growth
        # is not a reason to overrule that choice — an evolution included.
        #
        # A pin on the form being outgrown used to be dragged up with it, on
        # the grounds that a panel left on the old form made the evolution look
        # like it had not happened. What actually made it look that way was
        # that nothing said the panel was pinned at all. Home names the pinned
        # species and offers to release it now, so the panel disagreeing with
        # the companion reads as the choice it is.

    return events
