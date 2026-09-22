import json
import random

import pytest

from poketokenbar import balance, shop
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, EvoLine, apply_usage
from poketokenbar.companion_store import CompanionStore


def line():
    return EvoLine(base_id=1, path_ids=[1, 2, 3], rarity=Rarity.COMMON)


def hatched_state() -> CompanionState:
    state = CompanionState()
    apply_usage(
        state, balance.EGG_HATCH_THRESHOLD, line_for_egg=line(),
        rng=random.Random(1),
    )
    return state


def test_same_tokens_evolve_only_at_easier_growth():
    normal = hatched_state()
    easy = hatched_state()
    half = balance.phase_threshold(Rarity.COMMON, 3, 0) // 2
    apply_usage(normal, half)
    apply_usage(easy, half, growth_difficulty=0.5)
    assert normal.active.stage_index == 0
    assert easy.active.stage_index == 1


def test_egg_hatch_point_moves_with_growth_difficulty():
    state = CompanionState()
    apply_usage(
        state, balance.EGG_HATCH_THRESHOLD // 2,
        line_for_egg=line(), rng=random.Random(1), growth_difficulty=0.5,
    )
    assert state.active is not None


def test_shop_difficulty_changes_gate_and_charge_without_moving_growth():
    state = hatched_state()
    state.used_since_install = balance.RARE_CANDY_PRICE // 2
    with pytest.raises(shop.ShopError):
        shop.buy(state, "rareCandy")
    shop.buy(state, "rareCandy", shop_difficulty=0.5)
    assert state.spent_tokens == balance.RARE_CANDY_PRICE // 2
    assert balance.phase_threshold(Rarity.COMMON, 3, 0) == 25_000_000


def test_changing_growth_preserves_fraction_and_does_not_advance(tmp_path):
    store = CompanionStore(save_path=tmp_path / "companion.json")
    store.state = hatched_state()
    base = balance.phase_threshold(Rarity.COMMON, 3, 0)
    store.state.active.used_at_stage = base // 2
    store._persist()

    store.set_difficulties(0.5, 1.0)

    assert store.state.active.stage_index == 0
    assert store.state.active.used_at_stage == base // 4
    assert store.payload()["stage_progress"] == pytest.approx(0.5, abs=0.0001)
    saved = json.loads((tmp_path / "companion.json").read_text(encoding="utf-8"))
    assert "growth_difficulty" not in saved
    assert "shop_difficulty" not in saved

    reopened = CompanionStore(
        save_path=tmp_path / "companion.json", growth_difficulty=0.5,
    )
    reopened.set_difficulties(0.5, 1.0)
    assert reopened.state.active.used_at_stage == base // 4


def test_candy_is_not_scaled_with_difficulty(tmp_path):
    store = CompanionStore(save_path=tmp_path / "companion.json", rng=random.Random(1))
    store.state = hatched_state()
    store.state.inventory["rareCandy"] = 1
    store.set_difficulties(2.0, 1.0)
    store.use_item("rareCandy")
    # At 200% the ordinary 100M candy clears the 50M first stage and leaves
    # 50M in stage two. Scaling the candy too would advance another stage.
    assert store.state.active.stage_index == 1
    assert store.state.active.used_at_stage == 50_000_000
