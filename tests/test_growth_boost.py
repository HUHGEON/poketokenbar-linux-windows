"""A line that has graduated before grows twice as fast — upstream dec297a.

Ported from CompanionTests, DittoTests and RareCandyTests.swift.
"""

import json
import random

import pytest

from poketokenbar import balance, save, shop
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, EvoLine, MonState, apply_usage
from poketokenbar.companion_store import CompanionStore


def _line(base=1, forms=3):
    return EvoLine(base_id=base, path_ids=list(range(base, base + forms)), rarity=Rarity.COMMON)


def _raise_to_graduation(state, line, rng):
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=line, rng=rng)
    for stage in range(line.total_forms):
        apply_usage(state, balance.phase_threshold(Rarity.COMMON, line.total_forms, stage), rng=rng)
    assert state.active is None


@pytest.mark.parametrize("rarity", list(Rarity))
@pytest.mark.parametrize("forms", [1, 2, 3])
def test_the_boost_halves_every_phase_threshold(rarity, forms):
    for stage in range(forms):
        standard = balance.phase_threshold(rarity, forms, stage)
        boosted = balance.phase_threshold(
            rarity, forms, stage, balance.REPEAT_GROWTH_MULTIPLIER)
        assert boosted == int(standard / 2 + 0.5)


def test_a_boosted_common_first_stage_is_62_5m():
    assert balance.phase_threshold(
        Rarity.COMMON, 3, 0, balance.REPEAT_GROWTH_MULTIPLIER) == 62_500_000


def test_a_first_hatch_has_no_boost():
    state = CompanionState()
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=random.Random(1))
    assert state.active.has_growth_boost is False
    assert state.active.phase_threshold == 125_000_000


def test_hatching_a_line_that_graduated_before_grows_twice_as_fast():
    state, rng = CompanionState(), random.Random(1)
    _raise_to_graduation(state, _line(), rng)

    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=rng)
    mon = state.active
    assert mon.has_growth_boost is True
    assert mon.phase_threshold == 62_500_000

    apply_usage(state, 62_500_000, rng=rng)
    assert state.active.stage_index == 1


def test_the_boost_is_decided_by_the_base_species_not_a_prefix_of_it():
    # collected_finals keys are "base-final", so base 1 must not match "11-...".
    state = CompanionState(collected_finals={"11-13"})
    assert not state.has_collected_final(1)
    assert state.has_collected_final(11)


def test_a_released_line_earns_no_boost():
    # A release does not touch collected_finals, so it is not a repeat.
    state, rng = CompanionState(), random.Random(1)
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=rng)
    state.used_since_install = balance.FRESH_EGG_PRICE
    state.spent_tokens = 0
    shop.buy(state, "egg")
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=rng)
    assert state.active.has_growth_boost is False


def test_the_boost_survives_a_save_and_old_saves_grow_normally(tmp_path):
    path = tmp_path / "companion.json"
    state = CompanionState(active=MonState(
        base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3],
        total_forms=3, has_growth_boost=True))
    save.save(state, path)
    assert save.load(path).active.phase_threshold == 62_500_000

    legacy = json.loads(path.read_text())
    del legacy["active"]["has_growth_boost"]
    path.write_text(json.dumps(legacy))
    loaded = save.load(path).active
    assert loaded.has_growth_boost is False
    assert loaded.phase_threshold == 125_000_000


def test_a_boosted_disguise_reveals_at_the_halved_threshold_and_a_new_ditto_drops_the_boost():
    """The hatch borrowed the disguise's line, boost included. From the reveal
    on it is a Ditto, and only a repeat Ditto grows faster (upstream eb6ea0c);
    the level it reached while disguised is its own either way."""
    state = CompanionState(active=MonState(
        base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3], total_forms=3,
        ditto_disguise=1, has_growth_boost=True))
    events = apply_usage(state, 62_500_000)
    assert events.ditto_revealed
    assert state.active.ditto_revealed
    assert not state.active.has_growth_boost


def test_a_repeat_ditto_keeps_the_boost_through_the_reveal():
    state = CompanionState(active=MonState(
        base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3], total_forms=3,
        ditto_disguise=1, has_growth_boost=True))
    state.collected_finals.add(f"{balance.DITTO_SPECIES_ID}:{balance.DITTO_SPECIES_ID}")
    apply_usage(state, 62_500_000)
    assert state.active.has_growth_boost


def test_one_candy_advances_one_boosted_stage():
    state = CompanionState(active=MonState(
        base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3], total_forms=3,
        has_growth_boost=True))
    apply_usage(state, state.active.phase_threshold - 1)
    state.inventory["rareCandy"] = 1
    shop.use_item(state, "rareCandy")
    assert state.active.stage_index == 1
    assert state.active.used_at_stage == balance.RARE_CANDY_XP - 1
    assert state.active.used_at_stage < state.active.phase_threshold


def test_the_payload_says_when_the_companion_is_boosted():
    subject = CompanionStore(api=None, sprite_store=None)
    subject.state = CompanionState(active=MonState(
        base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3], total_forms=3,
        has_growth_boost=True))
    payload = subject.payload()
    assert payload["growth_multiplier"] == 2
    assert payload["stage_threshold"] == 62_500_000
    assert payload["remaining_tokens"] == 62_500_000

    subject.state.active.has_growth_boost = False
    assert subject.payload()["growth_multiplier"] is None
