"""Individual profiles — ported from PokemonProfileTests.swift and
ProfileGrowthIntegrationTests.swift (upstream b6bf676, 5963293)."""

import json
import random

import pytest

from poketokenbar import balance, profile as P, save, shop
from poketokenbar.balance import Rarity
from poketokenbar.companion import (
    CompanionState,
    DexEntry,
    EvoLine,
    MonState,
    apply_usage,
    migrate_profiles,
    set_growth_difficulty,
)
from poketokenbar.companion_store import CompanionStore

SLOWPOKE = P.PokemonDetails(
    species_id=79, name="slowpoke", height=12, weight=360, base_experience=63,
    gender_rate=8, types=["water", "psychic"],
    base_stats={"hp": 90, "attack": 65, "defense": 65,
                "special-attack": 40, "special-defense": 40, "speed": 15},
    abilities=[P.AbilityOption("oblivious", 1, False)],
    moves=[
        P.MoveOption("tackle", [P.LearnMethod("level-up", 1)]),
        P.MoveOption("curse", [P.LearnMethod("level-up", 1)]),
        P.MoveOption("yawn", [P.LearnMethod("level-up", 1)]),
        P.MoveOption("growl", [P.LearnMethod("level-up", 5)]),
        P.MoveOption("water-gun", [P.LearnMethod("level-up", 9)]),
        P.MoveOption("surf", [P.LearnMethod("machine", 0)]),
    ],
)


def _details(gender_rate, abilities):
    return P.PokemonDetails(999, "test", 10, 100, None, gender_rate, ["normal"],
                            {"hp": 50}, abilities, [])


# MARK: the generator


def test_splitmix_and_fnv_match_their_reference_values():
    # SplitMix64's first output from state 0 and FNV-1a 64 of "" are published
    # constants.
    rng = P.ProfileRNG(1)
    rng.state = 0
    assert rng.next() == 0xE220A8397B1DCDAF
    # Upstream maps a zero seed to the increment itself.
    assert P.ProfileRNG(0).next() == P.ProfileRNG(0x9E3779B97F4A7C15).next()
    assert P.migration_seed("") == 0xCBF29CE484222325
    assert P.migration_seed("a") == 0xAF63DC4C8601EC8C


def test_generation_is_deterministic_and_ivs_stay_in_range():
    a, b = P.generate(42), P.generate(42)
    assert a == b
    assert set(a.ivs) == set(P.STAT_ORDER)
    assert all(0 <= iv <= 31 for iv in a.ivs.values())
    assert a.level == 5


def test_enrichment_rolls_a_persistent_identity_and_four_legal_moves():
    profile = P.generate(7)
    profile.level = 9
    P.enrich(profile, SLOWPOKE)
    assert profile.gender == "female"
    assert (profile.ability_name, profile.ability_slot) == ("oblivious", 1)
    assert len(profile.moves) == 4
    assert "water-gun" in [m.name for m in profile.moves]
    assert "surf" not in [m.name for m in profile.moves]  # TMs are not auto-equipped

    first = json.dumps(save._encode_profile(profile))
    P.enrich(profile, SLOWPOKE)
    assert json.dumps(save._encode_profile(profile)) == first


def test_genderless_and_male_branches():
    genderless = P.generate(1)
    P.enrich(genderless, _details(-1, []))
    assert genderless.gender == "genderless"
    male = P.generate(1)
    P.enrich(male, _details(0, []))
    assert male.gender == "male"


def test_the_rare_hidden_ability_roll_matches_upstream_for_seed_115():
    profile = P.generate(115)
    P.enrich(profile, _details(-1, [P.AbilityOption("hidden-one", 3, True),
                                    P.AbilityOption("hidden-two", 4, True)]))
    assert (profile.ability_name, profile.ability_slot, profile.ability_is_hidden) == (
        "hidden-two", 4, True)


def test_only_hidden_abilities_fall_back_when_the_rare_roll_misses():
    profile = P.generate(1)
    P.enrich(profile, _details(-1, [P.AbilityOption("first-hidden", 2, True),
                                    P.AbilityOption("second-hidden", 3, True)]))
    assert (profile.ability_name, profile.ability_slot, profile.ability_is_hidden) == (
        "first-hidden", 2, True)


def test_a_stale_ability_selection_is_repaired():
    normal = P.AbilityOption("normal", 1, False)
    hidden = P.AbilityOption("hidden", 3, True)

    slot_only = P.generate(2)
    slot_only.ability_slot, slot_only.ability_is_hidden = 1, True
    P.enrich(slot_only, _details(-1, [normal]))
    assert (slot_only.ability_name, slot_only.ability_is_hidden) == ("normal", False)

    missing = P.generate(3)
    missing.ability_slot, missing.ability_is_hidden = 99, True
    P.enrich(missing, _details(-1, [hidden, normal]))
    assert (missing.ability_name, missing.ability_is_hidden) == ("normal", False)

    only_hidden = P.generate(4)
    only_hidden.ability_slot = 99
    P.enrich(only_hidden, _details(-1, [hidden]))
    assert (only_hidden.ability_name, only_hidden.ability_is_hidden) == ("hidden", True)


def test_a_species_rebase_keeps_ivs_and_clears_the_disguise():
    profile = P.generate(7)
    P.enrich(profile, SLOWPOKE)
    ivs = dict(profile.ivs)
    P.apply_growth(profile, 125_000_000, Rarity.COMMON)
    P.rebase_for_species_identity(profile, Rarity.COMMON, Rarity.RARE)
    assert profile.ivs == ivs
    assert (profile.gender, profile.ability_slot, profile.ability_name) == (None, None, None)
    assert profile.moves == []
    assert profile.growth_tokens == 500_000_000
    assert profile.level == 20


# MARK: stats


def test_a_nature_changes_the_calculated_non_hp_stats():
    profile = P.generate(1)
    profile.level = 50
    stats = {s.name: s for s in P.compute_stats(SLOWPOKE, profile, "adamant")}
    neutral_attack = ((2 * 65 + profile.ivs["attack"]) * 50) // 100 + 5
    neutral_special = ((2 * 40 + profile.ivs["special-attack"]) * 50) // 100 + 5
    assert stats["attack"].value == int(neutral_attack * 1.1)
    assert stats["special-attack"].value == int(neutral_special * 0.9)
    assert stats["hp"].value == ((2 * 90 + profile.ivs["hp"]) * 50) // 100 + 50 + 10


def test_the_stat_scale_grows_past_300():
    assert P.display_scale_maximum([180, 299]) == 300
    assert P.display_scale_maximum([651, 300]) == 700


def test_every_nature_raises_and_lowers_one_stat_or_none():
    neutral = {"hardy", "docile", "serious", "bashful", "quirky"}
    stats = [s for s in P.STAT_ORDER if s != "hp"]
    for nature in balance.NATURES:
        raised = [s for s in stats if P.nature_modifier(nature, s) == 1.1]
        lowered = [s for s in stats if P.nature_modifier(nature, s) == 0.9]
        if nature in neutral:
            assert raised == lowered == [], nature
        else:
            assert len(raised) == len(lowered) == 1 and raised != lowered, nature


# MARK: growth and level


def test_growth_maps_hatch_to_5_and_graduation_to_100():
    profile = P.generate(1)
    P.apply_growth(profile, balance.graduation_total(Rarity.COMMON), Rarity.COMMON)
    assert profile.level == 100


def _line(forms):
    return EvoLine(base_id=1, path_ids=list(range(1, forms + 1)), rarity=Rarity.COMMON)


@pytest.mark.parametrize("difficulty", [0.1, 1.0, 2.0])
@pytest.mark.parametrize("forms", [1, 2, 3])
def test_every_difficulty_and_repeat_hatch_graduates_at_level_100(difficulty, forms):
    state, rng = CompanionState(growth_difficulty=difficulty), random.Random(3)
    for repeated in (False, True):
        apply_usage(state, state.egg_hatch_threshold, line_for_egg=_line(forms), rng=rng)
        assert state.active.has_growth_boost is repeated
        assert state.active.profile.level == 5
        for _ in range(forms):
            apply_usage(state, state.stage_threshold(state.active) - state.active.used_at_stage)
        assert state.active is None
        graduate = state.dex[-1].profile
        assert (graduate.level, graduate.growth_tokens) == (100, 750_000_000)


def test_difficulty_changes_never_undo_an_earned_level():
    state = CompanionState(growth_difficulty=0.5, collected_finals={"1-1"})
    apply_usage(state, state.egg_hatch_threshold, line_for_egg=_line(1), rng=random.Random(1))
    apply_usage(state, 93_750_000)
    assert state.active.profile.level == 52
    set_growth_difficulty(state, 2.0)
    apply_usage(state, 0)
    assert state.active.profile.level == 52
    set_growth_difficulty(state, 0.1)
    assert state.active.used_at_stage / state.stage_threshold(state.active) == pytest.approx(0.5)
    assert state.active.profile.level == 52


def test_small_usage_chunks_match_one_large_delta():
    small = CompanionState(growth_difficulty=2.0)
    large = CompanionState(growth_difficulty=2.0)
    for state in (small, large):
        apply_usage(state, state.egg_hatch_threshold, line_for_egg=_line(3), rng=random.Random(1))
    for _ in range(20):
        apply_usage(small, 1)
    apply_usage(large, 20)
    assert small.active.profile.growth_tokens == 10
    assert small.active.profile.growth_tokens == large.active.profile.growth_tokens


def test_a_rare_candy_that_graduates_finishes_the_profile():
    state = CompanionState(growth_difficulty=0.1, inventory={"rareCandy": 1})
    apply_usage(state, state.egg_hatch_threshold, line_for_egg=_line(3), rng=random.Random(1))
    shop.use_item(state, "rareCandy")
    assert state.active is None
    assert state.dex[-1].profile.level == 100


def test_a_release_keeps_the_individual():
    state = CompanionState(used_since_install=balance.FRESH_EGG_PRICE)
    apply_usage(state, state.egg_hatch_threshold, line_for_egg=_line(3), rng=random.Random(1))
    individual = state.active.profile
    shop.buy(state, "egg")
    assert state.dex[-1].profile is individual


# MARK: migration and persistence


def test_a_legacy_stage_migrates_using_the_boost_and_the_difficulty():
    state = CompanionState(growth_difficulty=0.1, active=MonState(
        base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3], stage_index=1,
        used_at_stage=6_250_000, total_forms=3, has_growth_boost=True))
    assert migrate_profiles(state)
    assert state.active.profile.growth_tokens == 250_000_000
    assert state.active.profile.level == 36


def test_migration_is_deterministic_and_happens_once():
    def legacy():
        return CompanionState(
            last_date="2026-09-17",
            active=MonState(base_id=4, path_ids=[4, 5, 6], planned_path_ids=[4, 5, 6],
                            total_forms=3),
            dex=[DexEntry(base_id=1, final_id=3, chain_order=[1, 2, 3], rarity=Rarity.COMMON,
                          caught_at=1.0),
                 DexEntry(base_id=7, final_id=8, chain_order=[7, 8], rarity=Rarity.COMMON,
                          released_at=2.0)],
        )
    first, second = legacy(), legacy()
    assert migrate_profiles(first) and migrate_profiles(second)
    assert first.active.profile == second.active.profile
    assert [e.profile for e in first.dex] == [e.profile for e in second.dex]
    # The active key is upstream's, so the same companion has the same IVs.
    assert first.active.profile.seed == P.migration_seed("active:4:4:2026-09-17")
    assert first.dex[0].profile.level == 100  # a graduate
    # A release credits its reached chain: [7, 8] as a two-form line, first stage.
    assert first.dex[1].profile.growth_tokens == balance.phase_threshold(Rarity.COMMON, 2, 0)
    assert not migrate_profiles(first)


def test_the_store_backs_up_a_legacy_save_once(tmp_path):
    path = tmp_path / "companion.json"
    path.write_text(json.dumps({"active": {"base_id": 1, "path_ids": [1, 2]}}))
    original = path.read_bytes()
    store = CompanionStore(save_path=path, api=None, sprite_store=None)
    assert store.state.active.profile is not None
    backup = tmp_path / "companion.pre-profiles-v1.json"
    assert backup.read_bytes() == original
    assert json.loads(path.read_text())["active"]["profile"]["level"] == 5

    CompanionStore(save_path=path, api=None, sprite_store=None)
    assert backup.read_bytes() == original


def test_a_profile_survives_a_save(tmp_path):
    path = tmp_path / "companion.json"
    profile = P.generate(99)
    P.enrich(profile, SLOWPOKE)
    P.apply_growth(profile, 300_000_000, Rarity.COMMON)
    state = CompanionState(
        active=MonState(base_id=1, path_ids=[1], planned_path_ids=[1], profile=profile),
        dex=[DexEntry(base_id=2, final_id=2, chain_order=[2], rarity=Rarity.COMMON,
                      profile=P.generate(5))])
    save.save(state, path)
    loaded = save.load(path)
    assert loaded.active.profile == profile
    assert loaded.dex[0].profile == state.dex[0].profile


def test_a_hostile_profile_is_clamped(tmp_path):
    path = tmp_path / "companion.json"
    path.write_text(json.dumps({"active": {"base_id": 1, "path_ids": [1], "profile": {
        "instance_id": "", "seed": 5, "level": 900, "growth_tokens": -4,
        "ivs": {"hp": 99, "attack": -1, "defense": 3, "special-attack": 4,
                "special-defense": 5, "speed": 6},
        "gender": "robot",
        "moves": [{"name": "x" * 200, "learned_at_level": 500}] * 9,
    }}}))
    p = save.load(path).active.profile
    assert (p.level, p.growth_tokens, p.ivs["hp"], p.ivs["attack"]) == (100, 0, 31, 0)
    assert p.gender is None and p.instance_id
    assert len(p.moves) == 4 and len(p.moves[0].name) == 80
    assert p.moves[0].learned_at_level == 100


def test_a_corrupt_profile_regenerates_without_losing_the_pokemon(tmp_path):
    path = tmp_path / "companion.json"
    path.write_text(json.dumps({"active": {"base_id": 1, "path_ids": [1, 2], "profile": "bad"}}))
    store = CompanionStore(save_path=path, api=None, sprite_store=None)
    assert store.state.active.base_id == 1
    assert store.state.active.profile is not None
