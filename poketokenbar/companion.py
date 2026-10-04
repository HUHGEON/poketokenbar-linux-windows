"""Companion state and growth — ports CompanionModel/CompanionStore.swift.

Pure functions over CompanionState with no I/O, so the whole game is testable
without a network or a filesystem. Species data arrives through an injected
line provider; persistence lives in save.py.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import balance, unown
from .balance import Rarity
from .profile import PokemonProfile


# Animated Black/White assets exist for Gen I-V only. A species without one is
# pruned from the tree along with everything below it, so a line can never plan
# a route through a form that has no sprite.
MAX_ANIMATED_SPECIES_ID = 649


@dataclass(slots=True)
class EvoNode:
    """One species in an evolution tree, with the forms it can become.

    A tree, not a list, because evolution branches: Eevee has eight children,
    Wurmple two, and which one a companion takes is a decision — one this port
    used to make by always taking the first, so seven of Eevee's eight forms
    were unreachable and the Pokedex could never be completed.
    """

    species_id: int
    children: list["EvoNode"] = field(default_factory=list)

    @property
    def depth(self) -> int:
        """Forms along the longest route. Branches are usually the same depth."""
        return 1 + max((child.depth for child in self.children), default=0)

    @property
    def finals(self) -> list[int]:
        """Every final form reachable from here."""
        if not self.children:
            return [self.species_id]
        return [final for child in self.children for final in child.finals]

    def find(self, species_id: int) -> "EvoNode | None":
        if self.species_id == species_id:
            return self
        for child in self.children:
            found = child.find(species_id)
            if found is not None:
                return found
        return None

    def keeping_animated(self) -> "EvoNode | None":
        """The tree with unsupported species removed, subtree and all."""
        if self.species_id > MAX_ANIMATED_SPECIES_ID:
            return None
        kept = [child.keeping_animated() for child in self.children]
        return EvoNode(self.species_id, [child for child in kept if child is not None])

    @staticmethod
    def chain(path_ids: list[int]) -> "EvoNode | None":
        """A straight line as a tree — what a branchless line looks like."""
        node = None
        for species_id in reversed(path_ids):
            node = EvoNode(species_id, [node] if node else [])
        return node


@dataclass(slots=True)
class EvoLine:
    """One evolution line: the whole branching tree, plus who it belongs to.

    `path_ids` is the route through it that a plan would take by default. It is
    kept because a straight line is the common case and a caller with one does
    not need to build a tree to describe it.
    """

    base_id: int
    path_ids: list[int]
    rarity: Rarity
    names: dict[int, dict[str, str]] = field(default_factory=dict)
    tree: EvoNode | None = None

    def __post_init__(self) -> None:
        if self.tree is None:
            self.tree = EvoNode.chain(self.path_ids) or EvoNode(self.base_id)

    @property
    def total_forms(self) -> int:
        """Forms along the longest route, which is what the disguise roll asks
        about — "does this line visibly evolve at all"."""
        return self.tree.depth if self.tree else len(self.path_ids)


def pick_planned_child(
    node: EvoNode, base_id: int, collected_finals: set[str], rng: random.Random
) -> EvoNode:
    """Choose which form to grow into, preferring one you have not collected.

    Ports pickPlannedChild: a branch is "fresh" when any final it leads to is
    missing from the Pokedex, and fresh branches are the pool when there are
    any. Without it the collection stalls — every Eevee would be the same one.
    """
    fresh = [
        child for child in node.children
        if any(f"{base_id}:{final}" not in collected_finals for final in child.finals)
    ]
    pool = fresh or node.children
    return pool[rng.randrange(len(pool))]


def plan_path(
    line: EvoLine, collected_finals: set[str], rng: random.Random
) -> list[int]:
    """The route this companion will take, decided once at hatch."""
    node = line.tree or EvoNode(line.base_id)
    plan = [node.species_id]
    while node.children:
        node = pick_planned_child(node, line.base_id, collected_finals, rng)
        plan.append(node.species_id)
    return plan


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
    profile: PokemonProfile | None = None
    # A line that has already reached the Pokedex grows at twice the normal
    # rate. Persist the hatch-time decision so later graduations do not change
    # an individual halfway through raising it.
    has_growth_boost: bool = False
    ditto_disguise: int | None = None
    ditto_revealed: bool = False
    hatched_at: float | None = None
    unown_form: str | None = None

    @property
    def visible_shiny(self) -> bool:
        return self.is_shiny and (self.ditto_disguise is None or self.ditto_revealed)

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
    profile: PokemonProfile | None = None
    # Epoch seconds. None on entries written before this was tracked; those
    # sort last rather than pretending to be ancient.
    caught_at: float | None = None
    raised_seconds: float | None = None
    unown_form: str | None = None
    released_at: float | None = None

    @property
    def is_released(self) -> bool:
        return self.released_at is not None


@dataclass(slots=True)
class CompanionState:
    # Persist the scale with progress, so restart/import cannot scale it twice.
    balance_multiplier: int = 1
    detected_plan: str | None = None
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
    pending_unown_form: str | None = None
    claimed_today_tokens_by_provider: dict[str, int] | None = None
    last_date: str = ""
    active: MonState | None = None
    # Species pinned to the panel and the desktop pet. None follows whatever is
    # being raised (or the egg). A species, not an individual: nature and the
    # rest belong to the companion, which Home keeps showing either way.
    representative_species_id: int | None = None
    representative_is_shiny: bool | None = None
    representative_unown_form: str | None = None
    dex: list[DexEntry] = field(default_factory=list)
    collected_finals: set[str] = field(default_factory=set)
    language: str = "en"
    inventory: dict[str, int] = field(default_factory=dict)
    candy_grant_tier: dict[str, int] = field(default_factory=dict)
    candy_feature_seeded: bool = False
    candy_window_epoch: dict[str, str] = field(default_factory=dict)

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
        if self.active.ditto_revealed:
            return [balance.DITTO_SPECIES_ID]
        return list(self.active.path_ids[: self.active.stage_index + 1])

    def appearances(self, species_id: int) -> set[tuple[bool, str | None]]:
        """Owned (shiny, form) pairs; unreached stages and disguises stay hidden."""
        owned = {
            (entry.is_shiny, unown.resolved(species_id, entry.unown_form))
            for entry in self.dex if species_id in entry.chain_order
        }
        if self.active is not None and species_id in self.reached_species():
            owned.add((self.active.visible_shiny,
                       unown.resolved(species_id, self.active.unown_form)))
        return owned

    def collected_unown_forms(self) -> set[str]:
        return {form for _shiny, form in self.appearances(unown.SPECIES_ID)
                if form is not None}

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

        A Ditto revealing itself or a hand-edited save could otherwise leave
        a species or appearance on the panel that the user does not own.
        """
        if self.representative_species_id is None:
            self.representative_is_shiny = None
            self.representative_unown_form = None
            return
        species_id = self.representative_species_id
        form = unown.resolved(species_id, self.representative_unown_form)
        owned = self.appearances(species_id)
        colors = {shiny for shiny, letter in owned if letter == form}
        if not colors:
            self.representative_species_id = None
            self.representative_is_shiny = None
            self.representative_unown_form = None
            return
        self.representative_unown_form = form
        if self.representative_is_shiny not in colors:
            self.representative_is_shiny = True in colors


@dataclass(slots=True)
class GrowthEvents:
    """What happened during one apply_usage call, for notifications."""

    hatched: int | None = None
    evolved_to: int | None = None
    graduated: DexEntry | None = None
    ditto_revealed: bool = False


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
    # Which branch this one takes, chosen now and recorded. `total_forms` is
    # the plan's length, not the tree's depth: a companion on a two-form branch
    # of a three-deep tree has two stages to pay for, not three.
    plan = plan_path(line, state.collected_finals, rng)
    shiny = roll_shiny(rng, has_charm)
    nature = roll_nature(rng)
    disguise = line.base_id if roll_ditto(rng, line) else None
    mon = MonState(
        base_id=line.base_id,
        path_ids=list(plan),
        planned_path_ids=list(plan),
        stage_index=0,
        used_at_stage=0,
        rarity=line.rarity,
        total_forms=len(plan),
        is_shiny=shiny,
        nature=nature,
        profile=PokemonProfile.generate(rng),
        has_growth_boost=any(
            key.startswith(f"{line.base_id}:") for key in state.collected_finals
        ),
        hatched_at=__import__("time").time(),
        unown_form=(
            unown.resolved(line.base_id, state.pending_unown_form)
            if state.pending_hatch_id == line.base_id and state.pending_unown_form
            else unown.roll_form(rng.getrandbits(64), state.collected_unown_forms())
            if line.base_id == unown.SPECIES_ID else None
        ),
        # The disguise stores the species being impersonated; the reveal swaps
        # the display to Ditto while keeping this for the "it was Ditto!" moment.
        ditto_disguise=disguise,
    )
    state.active = mon
    # The guarantee is consumed by the hatch it paid for.
    state.egg_tier = None
    state.pending_hatch_id = None
    state.pending_unown_form = None
    state.egg_usage = 0
    return mon


def graduate(state: CompanionState, mon: MonState, now: float | None = None) -> DexEntry:
    """Archive a completed companion and clear the slot for a fresh egg."""
    import time as _time

    now = _time.time() if now is None else now
    if mon.profile is not None:
        mon.profile.advance(1.0)
    entry = DexEntry(
        base_id=mon.base_id,
        final_id=mon.current_id,
        chain_order=[balance.DITTO_SPECIES_ID] if mon.ditto_revealed else list(mon.path_ids),
        rarity=mon.rarity,
        is_shiny=mon.is_shiny,
        nature=mon.nature,
        profile=mon.profile,
        caught_at=now,
        raised_seconds=(now - mon.hatched_at) if mon.hatched_at else None,
        unown_form=unown.resolved(mon.current_id, mon.unown_form),
    )
    state.dex.append(entry)
    state.collected_finals.add(f"{mon.base_id}:{mon.current_id}")
    state.active = None
    state.egg_usage = 0
    return entry


def release(state: CompanionState, now: float | None = None) -> DexEntry | None:
    """Keep reached forms and this individual's profile without graduation credit."""
    import time

    mon = state.active
    if mon is None:
        return None
    now = time.time() if now is None else now
    reached = state.reached_species() or [mon.base_id]
    entry = DexEntry(
        base_id=mon.base_id, final_id=reached[-1], chain_order=reached,
        rarity=mon.rarity, is_shiny=mon.visible_shiny, nature=mon.nature,
        profile=mon.profile, caught_at=now, released_at=now,
        raised_seconds=now - mon.hatched_at if mon.hatched_at else None,
        unown_form=unown.resolved(mon.current_id, mon.unown_form),
    )
    state.dex.append(entry)
    state.active = None
    return entry


# The Swift loop's guard. Reached only by a corrupted save; a real line runs
# out of forms long before this.
MAX_GROWTH_STEPS = 50


def apply_usage(
    state: CompanionState,
    tokens: int,
    line_for_egg=None,
    rng: random.Random | None = None,
    credit_wallet: bool = True,
    growth_difficulty: float = balance.DEFAULT_DIFFICULTY,
) -> GrowthEvents:
    """Feed tokens to the companion.

    Overflow always carries forward, so a single large delta can hatch and then
    immediately advance a stage rather than being clipped.
    """
    events = GrowthEvents()
    if tokens < 0 or (tokens == 0 and (state.active is not None or line_for_egg is None)):
        return events
    rng = rng or random.Random()

    if credit_wallet:
        state.used_since_install += tokens

    # --- egg ---
    if state.active is None:
        state.egg_usage += tokens
        egg_threshold = balance.scale_difficulty(
            balance.EGG_HATCH_THRESHOLD * state.balance_multiplier,
            growth_difficulty,
        )
        if state.egg_usage < egg_threshold:
            return events
        if line_for_egg is None:
            # No species data (offline). Hold the tokens in the egg and hatch
            # once a line is available — never discard progress.
            return events
        overflow = state.egg_usage - egg_threshold
        mon = hatch(state, line_for_egg, rng)
        events.hatched = mon.current_id
        tokens = overflow
        if tokens <= 0:
            return events

    # --- growth ---
    mon = state.active
    mon.used_at_stage += tokens
    # Bounded like the Swift loop rather than `while True`: a save with a
    # nonsensical total_forms drives the threshold towards zero, and a zero
    # threshold is an evolution on every iteration forever.
    for _ in range(MAX_GROWTH_STEPS):
        threshold = balance.scale_difficulty(
            max(1, round(balance.phase_threshold(
                mon.rarity, mon.total_forms, mon.stage_index,
                state.balance_multiplier,
            ) / (2 if mon.has_growth_boost else 1))),
            growth_difficulty,
        )
        if mon.used_at_stage < threshold:
            break

        # The disguise is resolved before anything else, and without spending
        # the threshold. A Ditto's borrowed line can end up a single form after
        # the species data is normalised, and checking "is this the final form"
        # first then graduates the disguise straight into the Pokedex — the
        # wrong species, permanently, with the real Ditto never revealed.
        #
        # It also means an evolution below can never be a Ditto's: by the time
        # one gets there the reveal has already happened on an earlier pass.
        if mon.ditto_disguise is not None and not mon.ditto_revealed:
            was_showing = mon.current_id
            mon.ditto_revealed = True
            events.ditto_revealed = True
            # A pin on the disguise follows the reveal. The form it was
            # pretending to grow into is one nobody owns, and the form it was
            # pretending to be is gone — leaving the panel on either would show
            # a species that is not in anyone's Pokedex.
            if (state.representative_species_id == was_showing
                    and state.representative_is_shiny in (None, False)):
                state.representative_species_id = mon.current_id
                state.representative_is_shiny = mon.visible_shiny
            break

        if mon.is_final_form:
            # No carry-over: graduation clears the slot and the next egg starts
            # its incubation from zero.
            events.graduated = graduate(state, mon)
            break

        mon.used_at_stage -= threshold  # overflow carries into the new stage
        was_showing = mon.current_id
        mon.stage_index += 1
        events.evolved_to = mon.current_id
        # A pin on the form that just evolved moves up with it. Pinning the
        # companion as it is now is the ordinary reason to pin at all, and
        # leaving the panel on the outgrown form made the evolution look like it
        # had not happened. A pin on any *other* form stays exactly where it is:
        # that one names a species someone chose over the companion, and the
        # companion growing is no reason to overrule it.
        if (state.representative_species_id == was_showing
                and state.representative_is_shiny in (None, mon.visible_shiny)):
            state.representative_species_id = mon.current_id

    return events
