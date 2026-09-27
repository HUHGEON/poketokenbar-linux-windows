"""Companion state and growth — ports CompanionModel/CompanionStore.swift.

Pure functions over CompanionState with no I/O, so the whole game is testable
without a network or a filesystem. Species data arrives through an injected
line provider; persistence lives in save.py.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from . import balance, profile as profiles, unown
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
    # Fixed at hatch: this line had graduated before, so it grows
    # REPEAT_GROWTH_MULTIPLIER times faster. False on saves from before it.
    has_growth_boost: bool = False
    # IVs, gender, ability, level and moves. None only on a save from before
    # profiles, until migrate_profiles gives it one.
    profile: profiles.PokemonProfile | None = None
    # Unown's letter, for the one species that has 28 of them. None on every
    # other species, and on an Unown saved before letters existed — which is
    # read as A, the sprite it was already being drawn with (upstream 10d1a07).
    unown_form: str | None = None

    @property
    def growth_multiplier(self) -> int:
        return balance.REPEAT_GROWTH_MULTIPLIER if self.has_growth_boost else 1

    @property
    def phase_threshold(self) -> int:
        """Tokens this stage needs at the default difficulty, boost included.

        Growth is checked through CompanionState.stage_threshold, which scales
        this by the difficulty."""
        return balance.phase_threshold(
            self.rarity, self.total_forms, self.stage_index, self.growth_multiplier
        )

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
    # The individual as it was when it graduated or was released.
    profile: profiles.PokemonProfile | None = None
    # Which Unown this was. See MonState.unown_form.
    unown_form: str | None = None

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
    # Which letter the pinned Unown is, when the pin is on Unown.
    representative_unown_form: str | None = None
    dex: list[DexEntry] = field(default_factory=list)
    collected_finals: set[str] = field(default_factory=set)
    language: str = "en"
    inventory: dict[str, int] = field(default_factory=dict)
    candy_grant_tier: dict[str, int] = field(default_factory=dict)
    # The reset instant each window was last judged against. A window that has
    # since reset is a new window, so the grant rearms even though its
    # utilization never dipped (upstream e94da86). Kept out of the tier key
    # itself: a rolling weekly window reports a new resets_at on every fetch,
    # which would mint a new key each time and pay out for ever.
    candy_window_epoch: dict[str, str] = field(default_factory=dict)
    candy_feature_seeded: bool = False
    # The growth difficulty that egg_usage and used_at_stage were earned under.
    # Saved, unlike the setting itself: when the setting differs (changed in
    # the settings, changed while the daemon was down, or a save imported from
    # a machine set differently) the banked progress is re-expressed at the
    # new difficulty rather than silently changing how complete it is.
    growth_difficulty: float = balance.DEFAULT_DIFFICULTY
    # Shop price multiplier, from the settings. Not saved: prices hold no
    # progress, so there is nothing to re-express.
    shop_difficulty: float = balance.DEFAULT_DIFFICULTY

    @property
    def spendable_tokens(self) -> int:
        return max(0, self.used_since_install - self.spent_tokens)

    @property
    def egg_hatch_threshold(self) -> int:
        return max(1, balance.scaled(balance.EGG_HATCH_THRESHOLD, self.growth_difficulty))

    def stage_threshold(self, mon: MonState) -> int:
        """Tokens a stage needs: the boost, then the difficulty.

        Every growth check goes through here, so none of them can forget
        either one. Never below one token, or the growth loop never stops
        crediting a stage.
        """
        return max(1, balance.scaled(mon.phase_threshold, self.growth_difficulty))

    def reached_species(self) -> list[int]:
        """Stages the current companion has actually reached.

        Not the whole planned line: a form it has not evolved into yet is not
        something anyone owns.
        """
        if self.active is None:
            return []
        return list(self.active.path_ids[: self.active.stage_index + 1])

    def has_collected_final(self, base_id: int) -> bool:
        """Whether any line starting at this base species has graduated."""
        prefix = f"{base_id}-"
        return any(key.startswith(prefix) for key in self.collected_finals)

    def owns_species(self, species_id: int, unown_form: str | None = None) -> bool:
        """Whether a graduation record or the current companion covers this species.

        A light path on purpose — checking one species must not build the whole
        Pokedex display model. With a letter, only that Unown counts: the 28
        forms are collected separately.
        """
        if unown_form is not None and species_id == unown.SPECIES_ID:
            return unown_form in self.collected_unown_forms()
        if any(species_id in entry.chain_order for entry in self.dex):
            return True
        return species_id in self.reached_species()

    def collected_unown_forms(self) -> set[str]:
        """Every Unown letter owned, shiny or not — the 28-form tally."""
        found = set()
        for entry in self.dex:
            if unown.SPECIES_ID in entry.chain_order:
                letter = unown.resolved(unown.SPECIES_ID, entry.unown_form)
                if letter is not None:
                    found.add(letter)
        mon = self.active
        if mon is not None and unown.SPECIES_ID in self.reached_species():
            letter = unown.resolved(unown.SPECIES_ID, mon.unown_form)
            if letter is not None:
                found.add(letter)
        return found

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
            self.representative_unown_form = None
            return
        letter = unown.resolved(
            self.representative_species_id, self.representative_unown_form)
        if not self.owns_species(self.representative_species_id, letter):
            self.representative_species_id = None
            self.representative_unown_form = None
        else:
            # A letter recorded against anything but Unown is not a letter.
            self.representative_unown_form = letter


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
    return rng.randrange(balance.shiny_denominator(has_charm)) == 0


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
        has_growth_boost=state.has_collected_final(line.base_id),
        # Drawn last, so every roll above sees the same sequence it always has.
        profile=profiles.generate(rng.getrandbits(64)),
    )
    # Unown's letter, drawn only once the species roll has landed on it, so no
    # other species' sequence or odds change (upstream 10d1a07).
    if mon.base_id == unown.SPECIES_ID:
        mon.unown_form = unown.roll(rng, state.collected_unown_forms())
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
        unown_form=mon.unown_form,
        profile=mon.profile,
    )
    state.dex.append(entry)
    return entry


def reconcile_profile_growth(state: CompanionState) -> None:
    """Bring the active profile's growth up to the progress it represents.

    Ports upstream's reconcileActiveProfileGrowth. Completed stages count at
    their default-balance size; the current stage counts its earned fraction
    of the default size, whatever difficulty and boost made that fraction
    cost. So the same progress is the same level at every setting, and
    advance_growth's high-water mark keeps a level already reached.
    """
    mon = state.active
    if mon is None or mon.profile is None:
        return
    completed = profiles.reconstructed_growth_tokens(
        mon.rarity, mon.total_forms, mon.stage_index, 0)
    standard = balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
    fraction = min(1.0, max(0.0, mon.used_at_stage / max(1, state.stage_threshold(mon))))
    candidate = min(balance.graduation_total(mon.rarity), completed + int(standard * fraction))
    profiles.advance_growth(mon.profile, candidate, mon.rarity)


def migrate_profiles(state: CompanionState) -> bool:
    """Give every companion and dex entry from an older save a profile.

    Ports upstream's migratePokemonProfilesIfNeeded. No network: gender,
    ability and moves are filled later by enrichment. Seeds come from
    upstream's FNV-1a key for the active companion, and from a key built of
    the entry's own fields for the dex (upstream keys that on a random entry
    id the fork does not have), so migrating the same save twice, or on two
    machines, gives the same individuals. Returns whether anything changed.
    """
    changed = False
    mon = state.active
    if mon is not None and mon.profile is None:
        reached = ",".join(str(i) for i in mon.path_ids[: mon.stage_index + 1])
        mon.profile = profiles.generate(
            profiles.migration_seed(f"active:{mon.base_id}:{reached}:{state.last_date}"))
        changed = True
    for index, entry in enumerate(state.dex):
        if entry.profile is not None:
            continue
        if entry.is_released:
            # Only the reached chain was kept, so its length stands in for the
            # planned form count: an upper bound when released early.
            forms = max(1, len(entry.chain_order))
            growth = profiles.reconstructed_growth_tokens(entry.rarity, forms, forms - 1, 0)
        else:
            growth = balance.graduation_total(entry.rarity)
        caught = "" if entry.caught_at is None else repr(entry.caught_at)
        entry.profile = profiles.generate(
            profiles.migration_seed(f"dex:{index}:{entry.base_id}:{entry.final_id}:{caught}"),
            growth_tokens=growth,
        )
        profiles.apply_growth(entry.profile, 0, entry.rarity)
        changed = True
    reconcile_profile_growth(state)
    return changed


def set_growth_difficulty(state: CompanionState, value) -> bool:
    """Change the growth difficulty, keeping the earned fraction of this stage.

    Ports upstream's rescaleBankedGrowth (5963293). These are progression
    credits, not usage: used_since_install, the provider ledger and the wallet
    are untouched. It never evolves, graduates or hatches on the spot, because
    an incomplete stage is capped one token short of its new threshold.
    Returns whether anything changed.
    """
    new = balance.clamp_difficulty(value)
    old = state.growth_difficulty
    if new == old:
        return False

    def rescaled(credits: int, base: int) -> int:
        old_threshold = max(1, balance.scaled(base, old))
        new_threshold = max(1, balance.scaled(base, new))
        value = max(0, int(credits / old_threshold * new_threshold))
        # Rounding must never turn an incomplete stage into a completed one.
        return min(new_threshold - 1, value) if credits < old_threshold else value

    if state.active is not None:
        state.active.used_at_stage = rescaled(
            state.active.used_at_stage, state.active.phase_threshold)
    else:
        state.egg_usage = rescaled(state.egg_usage, balance.EGG_HATCH_THRESHOLD)
    state.growth_difficulty = new
    return True


def graduate(state: CompanionState, mon: MonState, now: float | None = None) -> DexEntry:
    """Archive a completed companion and clear the slot for a fresh egg."""
    import time as _time

    now = _time.time() if now is None else now
    if mon.profile is not None:
        # A graduate has earned the whole line: level 100 at every difficulty.
        profiles.advance_growth(mon.profile, balance.graduation_total(mon.rarity), mon.rarity)
    entry = DexEntry(
        base_id=mon.base_id,
        final_id=mon.current_id,
        chain_order=list(mon.path_ids),
        rarity=mon.rarity,
        is_shiny=mon.is_shiny,
        nature=mon.nature,
        caught_at=now,
        raised_seconds=(now - mon.hatched_at) if mon.hatched_at else None,
        profile=mon.profile,
        unown_form=mon.unown_form,
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
    if tokens < 0:
        return events
    # Zero is not a no-op: a ready egg whose species could not be fetched last
    # time is hatched here, with the tokens it has already banked. Everything
    # below adds nothing when there is nothing to add.
    rng = rng or random.Random()

    state.used_since_install += tokens

    # --- egg ---
    if state.active is None:
        state.egg_usage += tokens
        if state.egg_usage < state.egg_hatch_threshold:
            return events
        if line_for_egg is None:
            # No species data (offline). Hold the tokens in the egg and hatch
            # once a line is available — never discard progress.
            return events
        overflow = state.egg_usage - state.egg_hatch_threshold
        mon = hatch(state, line_for_egg, rng)
        events.hatched = mon.current_id
        tokens = overflow
        if tokens <= 0:
            return events

    # --- growth ---
    mon = state.active
    mon.used_at_stage += tokens
    reconcile_profile_growth(state)
    while True:
        threshold = state.stage_threshold(mon)
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
            if mon.profile is not None:
                # Same individual, new species: keep the IVs, reroll the rest
                # once Ditto's details are known.
                profiles.rebase_for_species_identity(mon.profile, mon.rarity, mon.rarity)
        # The pin does not move. It names a species the user chose, and growth
        # is not a reason to overrule that choice — an evolution included.
        #
        # A pin on the form being outgrown used to be dragged up with it, on
        # the grounds that a panel left on the old form made the evolution look
        # like it had not happened. What actually made it look that way was
        # that nothing said the panel was pinned at all. Home names the pinned
        # species and offers to release it now, so the panel disagreeing with
        # the companion reads as the choice it is.

    reconcile_profile_growth(state)
    return events
