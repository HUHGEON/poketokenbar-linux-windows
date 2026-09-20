"""Growth, evolution and graduation, with the Plus baseline and Pro scale.

The constants are copied from CompanionModel.swift and checked here value by
value, because a number that drifts changes the game silently — nothing fails,
the Pokemon just takes a different amount of work. The order of the checks in
`apply_usage` is tested too: that ordering is load-bearing, and getting it
wrong put the wrong species in the Pokedex.
"""

import pytest

from poketokenbar import balance
from poketokenbar.balance import Rarity
from poketokenbar.companion import (
    MAX_GROWTH_STEPS, CompanionState, MonState, apply_usage,
)


# MARK: the balance table, as the Swift source states it


def test_the_egg_threshold_matches():
    assert balance.EGG_HATCH_THRESHOLD * 5 == 5_000_000


@pytest.mark.parametrize("rarity,total", [
    (Rarity.COMMON, 750_000_000),
    (Rarity.UNCOMMON, 1_875_000_000),
    (Rarity.RARE, 3_000_000_000),
    (Rarity.LEGENDARY, 6_000_000_000),
])
def test_graduation_totals_match(rarity, total):
    assert balance.graduation_total(rarity) * 5 == total


@pytest.mark.parametrize("rarity,ceiling", [
    (Rarity.RARE, 45), (Rarity.UNCOMMON, 120), (Rarity.COMMON, 255),
    (Rarity.LEGENDARY, None),
])
def test_capture_rate_ceilings_match(rarity, ceiling):
    assert rarity.capture_rate_ceiling == ceiling


def test_the_item_prices_match():
    assert balance.RARE_CANDY_XP == 100_000_000
    assert balance.RARE_CANDY_PRICE * 5 == 500_000_000
    assert balance.RARE_CANDY_WEEKLY_GRANT == 5
    assert balance.MINT_PRICE * 5 == 100_000_000
    assert balance.SHINY_CHARM_PRICE * 5 == 3_000_000_000
    assert balance.SHINY_CHARM_DENOMINATOR == 48
    assert balance.FRESH_EGG_PRICE * 5 == 1_000_000_000
    assert balance.SHINY_DENOMINATOR == 64
    assert balance.DITTO_DISGUISE_DENOMINATOR == 128
    assert balance.DITTO_SPECIES_ID == 132
    assert balance.EGG_SHOP_TIERS == [None, Rarity.UNCOMMON, Rarity.RARE]


def test_candy_relative_value_is_identical_across_plans():
    """The existing 100M Plus candy is intentionally stronger than upstream."""
    for rarity in Rarity:
        for forms in (1, 2, 3, 4):
            plus = balance.RARE_CANDY_XP / balance.phase_threshold(rarity, forms, 0)
            pro = balance.RARE_CANDY_XP * 5 / balance.phase_threshold(rarity, forms, 0, 5)
            assert plus == pro


# MARK: the phase weighting


@pytest.mark.parametrize("forms", [1, 2, 3, 4, 5])
@pytest.mark.parametrize("rarity", list(Rarity))
def test_the_stages_sum_to_the_graduation_total(rarity, forms):
    """"A line's total is the same regardless of how many forms it has" — the
    property the weighting exists for. Rounding may move it by a token or two."""
    total = sum(balance.phase_threshold(rarity, forms, i) for i in range(forms))
    assert abs(total - balance.graduation_total(rarity)) <= forms


@pytest.mark.parametrize("rarity", list(Rarity))
def test_later_stages_cost_more(rarity):
    thresholds = [balance.phase_threshold(rarity, 3, i) for i in range(3)]
    assert thresholds == sorted(thresholds)
    assert thresholds[0] < thresholds[2]


def test_the_weighting_matches_the_swift_formula():
    """T·i / (k(k+1)/2), spelled out for the shapes a real line takes."""
    assert balance.phase_threshold(Rarity.COMMON, 3, 0, 5) == 125_000_000
    assert balance.phase_threshold(Rarity.COMMON, 3, 1, 5) == 250_000_000
    assert balance.phase_threshold(Rarity.COMMON, 3, 2, 5) == 375_000_000
    assert balance.phase_threshold(Rarity.COMMON, 2, 0, 5) == 250_000_000
    assert balance.phase_threshold(Rarity.COMMON, 2, 1, 5) == 500_000_000
    assert balance.phase_threshold(Rarity.COMMON, 1, 0, 5) == 750_000_000
    assert balance.phase_threshold(Rarity.RARE, 3, 1, 5) == 1_000_000_000


def test_a_zero_form_line_is_treated_as_one():
    """max(1, k) in the Swift — and a zero here would be a division by zero."""
    assert balance.phase_threshold(Rarity.COMMON, 0, 0, 5) == 750_000_000


# MARK: growth


def _mon(**kwargs):
    base = dict(base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3],
                stage_index=0, rarity=Rarity.COMMON, total_forms=3)
    base.update(kwargs)
    return MonState(**base)


def test_an_evolution_carries_the_overflow_forward():
    mon = _mon()
    state = CompanionState(active=mon)
    threshold = balance.phase_threshold(Rarity.COMMON, 3, 0)
    apply_usage(state, threshold + 7)
    assert mon.stage_index == 1
    assert mon.used_at_stage == 7, "the excess was clipped instead of carried"


def test_evolving_changes_which_species_is_shown():
    """The whole point of an evolution, and the thing a front end draws."""
    mon = _mon()
    state = CompanionState(active=mon)
    assert mon.current_id == 1
    events = apply_usage(state, balance.phase_threshold(Rarity.COMMON, 3, 0))
    assert mon.current_id == 2
    assert events.evolved_to == 2


def test_one_large_delta_walks_the_whole_line():
    """A machine that was asleep for a week arrives as a single delta."""
    mon = _mon()
    state = CompanionState(active=mon)
    events = apply_usage(state, balance.graduation_total(Rarity.COMMON))
    assert events.graduated is not None
    assert events.graduated.final_id == 3
    assert state.active is None, "the slot is cleared for a fresh egg"
    assert state.egg_usage == 0, "graduation does not carry into the next egg"


def test_graduation_records_the_line_it_walked():
    mon = _mon(is_shiny=True, nature="brave")
    state = CompanionState(active=mon)
    entry = apply_usage(state, balance.graduation_total(Rarity.COMMON)).graduated
    assert entry.chain_order == [1, 2, 3]
    assert entry.base_id == 1 and entry.final_id == 3
    assert entry.is_shiny and entry.nature == "brave"


# MARK: the order the checks happen in


def test_a_disguised_ditto_reveals_before_it_can_graduate():
    """The Swift comment says the reveal must come before the terminal check,
    and this is why: a disguise whose borrowed line is a single form otherwise
    graduates as the species it was pretending to be, which then sits in the
    Pokedex as a catch that never happened."""
    mon = _mon(base_id=129, path_ids=[129], planned_path_ids=[129], total_forms=1,
               ditto_disguise=129)
    state = CompanionState(active=mon)
    events = apply_usage(state, balance.phase_threshold(Rarity.COMMON, 1, 0))

    assert events.ditto_revealed is True
    assert events.graduated is None, "it graduated as the disguise"
    assert state.active is mon, "the slot was cleared by a graduation"
    assert mon.current_id == balance.DITTO_SPECIES_ID


def test_the_reveal_does_not_spend_the_threshold():
    """It stops the walk rather than consuming a stage, so the next tick picks
    up exactly where this one stopped."""
    mon = _mon(base_id=129, path_ids=[129], planned_path_ids=[129], total_forms=1,
               ditto_disguise=129)
    state = CompanionState(active=mon)
    threshold = balance.phase_threshold(Rarity.COMMON, 1, 0)
    apply_usage(state, threshold)
    assert mon.used_at_stage == threshold

    entry = apply_usage(state, 1).graduated
    assert entry is not None and entry.final_id == balance.DITTO_SPECIES_ID


def test_a_revealed_ditto_is_not_revealed_twice():
    mon = _mon(ditto_disguise=1, ditto_revealed=True)
    state = CompanionState(active=mon)
    events = apply_usage(state, balance.phase_threshold(Rarity.COMMON, 3, 0))
    assert events.ditto_revealed is False
    assert events.evolved_to is not None


def test_growth_is_bounded_even_on_a_nonsense_save():
    """A large enough total_forms drives the threshold to zero, and a zero
    threshold is an evolution every iteration, forever."""
    mon = _mon(total_forms=10_000_000, path_ids=list(range(1, 60)),
               planned_path_ids=list(range(1, 60)))
    state = CompanionState(active=mon)
    assert balance.phase_threshold(Rarity.COMMON, mon.total_forms, 0) == 0

    apply_usage(state, 1)  # must return rather than hang
    assert mon.stage_index <= MAX_GROWTH_STEPS


def test_nothing_happens_without_tokens():
    mon = _mon()
    state = CompanionState(active=mon)
    for delta in (0, -5):
        assert apply_usage(state, delta) == type(apply_usage(state, 0))()
    assert mon.used_at_stage == 0


# MARK: the pin


def test_pinning_and_releasing_a_species():
    """The Pokedex star sets it and clears it; clearing is what the star did
    not have a way to do."""
    from poketokenbar.companion import DexEntry
    from poketokenbar.companion_store import CompanionStore

    store = CompanionStore(api=None, sprite_store=None)
    store.state = CompanionState(
        active=_mon(),
        dex=[DexEntry(base_id=1, final_id=3, chain_order=[1, 2, 3], rarity=Rarity.COMMON)],
    )
    store._persist = lambda: None

    store.set_representative(3)
    assert store.panel_species()[0] == 3, "the pin does not override the companion"

    store.set_representative(None)
    assert store.panel_species()[0] == 1, "releasing did not go back to the companion"


def test_a_species_nobody_owns_cannot_be_pinned():
    from poketokenbar.companion_store import CompanionStore

    store = CompanionStore(api=None, sprite_store=None)
    store.state = CompanionState(active=_mon())
    store._persist = lambda: None
    with pytest.raises(ValueError):
        store.set_representative(999)
