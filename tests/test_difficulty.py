"""Growth and shop difficulty — upstream b0c6074 and 5963293.

Ported from DifficultyTests.swift and DifficultySaveTests.swift, adapted to a
setting that lives in config.json and reaches the save through the daemon.
"""

import json
import math
import random
import re
from pathlib import Path

import pytest

from poketokenbar import balance, config, save, shop
from poketokenbar.balance import Rarity
from poketokenbar.companion import (
    CompanionState,
    EvoLine,
    MonState,
    apply_usage,
    set_growth_difficulty,
)
from poketokenbar.companion_store import CompanionStore

SECTIONS_JS = (Path(__file__).resolve().parents[1] / "gnome-extension"
               / "poketokenbar@huhgeon.github.io" / "lib" / "sections.js")


def _mon(**kwargs):
    return MonState(base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3],
                    total_forms=3, **kwargs)


# MARK: clamping


@pytest.mark.parametrize("raw,expected", [
    (1.0, 1.0), (0.5, 0.5), (2, 2.0),
    (0, 0.1), (-3, 0.1), (0.01, 0.1), (20, 2.0),
    (math.nan, 1.0), (math.inf, 1.0), (-math.inf, 1.0),
    ("0.5", 0.5), ("fast", 1.0), (None, 1.0),
])
def test_a_hand_edited_multiplier_is_clamped(raw, expected):
    assert balance.clamp_difficulty(raw) == expected


def test_the_steps_the_settings_offer_are_all_in_range_and_include_the_default():
    steps = balance.DIFFICULTY_STEPS
    assert list(steps) == sorted(steps)
    assert steps[0] == balance.DIFFICULTY_MIN and steps[-1] == balance.DIFFICULTY_MAX
    assert balance.DEFAULT_DIFFICULTY in steps


def test_the_gnome_settings_offer_the_same_steps():
    source = SECTIONS_JS.read_text(encoding="utf-8")
    found = re.search(r"const DIFFICULTY_STEPS = \[([^\]]*)\]", source)
    assert found, "DIFFICULTY_STEPS not found in sections.js"
    js_steps = tuple(float(v) for v in found.group(1).split(","))
    assert js_steps == balance.DIFFICULTY_STEPS


# MARK: growth


def test_the_default_changes_nothing():
    state = CompanionState()
    assert state.egg_hatch_threshold == balance.EGG_HATCH_THRESHOLD
    assert state.stage_threshold(_mon()) == 125_000_000


def test_growth_scales_the_hatch_and_every_stage():
    state = CompanionState(growth_difficulty=0.5)
    assert state.egg_hatch_threshold == 2_500_000
    for stage in range(3):
        mon = _mon(stage_index=stage)
        assert state.stage_threshold(mon) == round(mon.phase_threshold * 0.5)


def test_the_repeat_boost_and_the_difficulty_multiply():
    state = CompanionState(growth_difficulty=0.5)
    assert state.stage_threshold(_mon(has_growth_boost=True)) == 31_250_000


def test_an_easier_egg_hatches_sooner_and_carries_the_overflow():
    state = CompanionState(growth_difficulty=0.5)
    line = EvoLine(base_id=1, path_ids=[1, 2, 3], rarity=Rarity.COMMON)
    events = apply_usage(state, 2_500_000 + 1_000, line_for_egg=line, rng=random.Random(1))
    assert events.hatched == 1
    assert state.active.used_at_stage == 1_000


def test_a_harder_stage_takes_longer():
    state = CompanionState(growth_difficulty=2.0, active=_mon())
    apply_usage(state, 125_000_000)
    assert state.active.stage_index == 0
    apply_usage(state, 125_000_000)
    assert state.active.stage_index == 1


def test_a_rare_candy_is_not_scaled():
    # Scaling the candy along with the thresholds would cancel the difficulty
    # out for candy alone.
    state = CompanionState(growth_difficulty=2.0, active=_mon())
    state.inventory["rareCandy"] = 1
    shop.use_item(state, "rareCandy")
    assert state.active.used_at_stage == balance.RARE_CANDY_XP


# MARK: changing growth keeps the earned fraction


def test_changing_growth_keeps_the_fraction_of_the_stage():
    state = CompanionState(active=_mon(used_at_stage=62_500_000))
    assert set_growth_difficulty(state, 2.0)
    assert state.growth_difficulty == 2.0
    assert state.active.used_at_stage == 125_000_000
    assert state.active.used_at_stage < state.stage_threshold(state.active)


def test_changing_growth_never_completes_a_stage():
    # One token short at the default. The fraction rounds up to a full stage
    # at 10%; the cap keeps it one short.
    state = CompanionState(active=_mon(used_at_stage=124_999_999))
    set_growth_difficulty(state, 0.1)
    threshold = state.stage_threshold(state.active)
    assert state.active.used_at_stage == threshold - 1
    events = apply_usage(state, 0)
    assert events.evolved_to is None and state.active.stage_index == 0


def test_an_egg_already_over_its_threshold_stays_ready_to_hatch():
    # Offline, an egg holds its tokens past the threshold until species data
    # arrives; that completion must survive a change.
    state = CompanionState(egg_usage=6_000_000)
    set_growth_difficulty(state, 2.0)
    assert state.egg_usage >= state.egg_hatch_threshold


def test_changing_growth_rescales_the_egg():
    state = CompanionState(egg_usage=2_500_000)
    set_growth_difficulty(state, 0.5)
    assert state.egg_usage == 1_250_000


def test_changing_growth_leaves_usage_and_the_wallet_alone():
    state = CompanionState(active=_mon(used_at_stage=10), used_since_install=999,
                           spent_tokens=100, claimed_today_tokens_by_provider={"codex": 5})
    set_growth_difficulty(state, 0.25)
    assert (state.used_since_install, state.spent_tokens) == (999, 100)
    assert state.claimed_today_tokens_by_provider == {"codex": 5}


def test_the_same_value_changes_nothing():
    state = CompanionState(active=_mon(used_at_stage=77))
    assert not set_growth_difficulty(state, 1.0)
    assert not set_growth_difficulty(state, "1")
    assert state.active.used_at_stage == 77


# MARK: shop


def test_shop_prices_scale_and_the_charge_matches_the_listing():
    state = CompanionState(active=_mon(), shop_difficulty=0.5)
    state.used_since_install = balance.RARE_CANDY_PRICE
    listed = {e.key: e.price for e in shop.entries(state)}
    assert listed["rareCandy"] == balance.RARE_CANDY_PRICE // 2
    assert listed["egg:rare"] == balance.egg_price(Rarity.RARE) // 2
    shop.buy(state, "rareCandy")
    assert state.spent_tokens == balance.RARE_CANDY_PRICE // 2


def test_growth_does_not_move_prices_and_shop_does_not_move_growth():
    state = CompanionState(growth_difficulty=0.1, shop_difficulty=2.0, active=_mon())
    assert {e.key: e.price for e in shop.entries(state)}["mint"] == balance.MINT_PRICE * 2
    assert state.stage_threshold(state.active) == 12_500_000


# MARK: persistence and the daemon's hand-off


def test_the_save_records_what_its_progress_was_earned_under(tmp_path):
    path = tmp_path / "companion.json"
    save.save(CompanionState(growth_difficulty=0.5, shop_difficulty=2.0), path)
    raw = json.loads(path.read_text())
    assert raw["growth_difficulty"] == 0.5
    assert "shop_difficulty" not in raw  # a price holds no progress
    assert save.load(path).growth_difficulty == 0.5


@pytest.mark.parametrize("stored,expected", [(None, 1.0), (True, 1.0), (50, 2.0), ("x", 1.0)])
def test_an_old_or_damaged_save_reads_as_the_default_or_the_nearest_bound(tmp_path, stored, expected):
    path = tmp_path / "companion.json"
    body = {} if stored is None else {"growth_difficulty": stored}
    path.write_text(json.dumps(body))
    assert save.load(path).growth_difficulty == expected


def test_the_store_rescales_and_persists_once(tmp_path):
    store = CompanionStore(save_path=tmp_path / "c.json", api=None, sprite_store=None)
    store.state = CompanionState(active=_mon(used_at_stage=62_500_000))
    store.sync_difficulty(0.5, 1.25)
    assert store.state.active.used_at_stage == 31_250_000
    assert store.state.shop_difficulty == 1.25
    assert save.load(tmp_path / "c.json").growth_difficulty == 0.5

    # Again at the same setting: nothing moves.
    store.sync_difficulty(0.5, 1.25)
    assert store.state.active.used_at_stage == 31_250_000
    payload = store.payload()
    assert payload["stage_threshold"] == 62_500_000
    assert payload["stage_progress"] == 0.5


def test_a_save_imported_from_another_difficulty_keeps_its_fraction(tmp_path):
    # Earned at 50% on another machine, loaded where the setting is 100%.
    store = CompanionStore(save_path=tmp_path / "c.json", api=None, sprite_store=None)
    store.state = CompanionState(growth_difficulty=0.5, active=_mon(used_at_stage=31_250_000))
    store.sync_difficulty(1.0, 1.0)
    assert store.state.active.used_at_stage == 62_500_000


def test_the_setting_is_written_as_a_number(tmp_path):
    path = tmp_path / "config.json"
    config.set_value(path, "growth_difficulty", "0.25")
    assert config.load(path)["growth_difficulty"] == 0.25
