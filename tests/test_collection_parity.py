"""Upstream gameplay additions, exercised with local state and species fixtures."""

import random

import pytest

from poketokenbar import balance, companion, save, shop, sprites
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, EvoLine, MonState
from poketokenbar.companion_store import CompanionStore
from poketokenbar.pokeapi import PokeAPIError


def mon(species=1, path=None, **kwargs):
    path = path or [species]
    return MonState(species, path, list(path), total_forms=len(path), **kwargs)


def test_legacy_unown_defaults_to_a_and_other_species_ignore_forms():
    raw = save.encode(CompanionState(active=mon(201)))
    raw["active"].pop("unown_form", None)
    restored = save.decode(raw)
    assert getattr(restored.active, "unown_form", None) == "a"
    raw["active"]["base_id"] = 25
    raw["active"]["path_ids"] = [25]
    raw["active"]["unown_form"] = "question"
    assert save.decode(raw).active.unown_form is None


def test_unown_roll_weights_missing_forms_twice_and_covers_all_forms():
    from poketokenbar import unown

    picks = [unown.roll_form(roll, {"a"}) for roll in range(55)]
    assert picks.count("a") == 1
    assert picks.count("question") == 2
    assert len(set(picks)) == 28
    assert unown.display_name("Unown", 201, "exclamation") == "Unown [!]"


def test_unown_prepared_form_survives_hatch_graduation_and_save():
    state = CompanionState(pending_hatch_id=201, pending_unown_form="question")
    hatched = companion.hatch(state, EvoLine(201, [201], Rarity.UNCOMMON), random.Random(4))
    assert hatched.unown_form == "question"
    assert state.pending_unown_form is None
    companion.graduate(state, hatched)
    restored = save.decode(save.encode(state))
    assert restored.dex[0].unown_form == "question"
    assert restored.collected_unown_forms() == {"question"}


def test_unown_assets_keep_legacy_a_cache_and_distinguish_colors():
    assert sprites.cache_key(201, True, False, unown_form="a") == "201-a"
    assert sprites.cache_key(201, True, True, unown_form="question") == "201-question-sha"
    assert sprites.sprite_url(201, False, False, unown_form="b").endswith("/201-b.png")
    assert sprites.sprite_url(25, True, False, unown_form="b").endswith("/25.gif")


def test_collection_exposes_independent_owned_appearances_and_all_unown_forms(tmp_path):
    store = CompanionStore(save_path=tmp_path / "save.json")
    store.state.dex = [
        DexEntry(201, 201, [201], Rarity.UNCOMMON, unown_form="a"),
        DexEntry(201, 201, [201], Rarity.UNCOMMON, is_shiny=True, unown_form="b"),
        DexEntry(201, 201, [201], Rarity.UNCOMMON, unown_form="b"),
    ]
    row, = store.dex_payload()
    assert row["unown_forms"] == 2
    assert len(row["forms"]) == 28
    assert {(a["unown_form"], a["is_shiny"]) for a in row["appearances"]} == {
        ("a", False), ("b", False), ("b", True)}
    store.set_representative(201, is_shiny=False, unown_form="b")
    assert store.panel_species() == (201, False)
    assert store.payload()["panel_unown_form"] == "b"
    reopened = CompanionStore(save_path=store.save_path)
    assert reopened.payload()["panel_unown_form"] == "b"
    with pytest.raises(ValueError):
        reopened.set_representative(201, is_shiny=True, unown_form="a")


def test_bulk_candy_preview_caps_use_at_graduation_without_wallet_credit():
    state = CompanionState(active=mon(path=[1, 2, 3]), inventory={"rareCandy": 10})
    preview = shop.candy_preview(state, 10)
    assert preview == {"count": 2, "xp": 200_000_000, "evolves": True,
                       "graduates": True, "carryover_xp": 0, "discarded_xp": 50_000_000}
    shop.use_item(state, "rareCandy", count=10)
    assert state.active is None
    assert state.inventory["rareCandy"] == 8
    assert state.used_since_install == state.spent_tokens == 0
    assert len(state.dex) == 1


def test_bulk_candy_preview_honors_pro_plan_growth_boost_and_difficulty():
    state = CompanionState(balance_multiplier=5, active=mon(path=[1, 2, 3], has_growth_boost=True),
                           inventory={"rareCandy": 10})
    preview = shop.candy_preview(state, 1, growth_difficulty=2.0)
    assert preview["xp"] == 500_000_000
    assert preview["carryover_xp"] == 125_000_000
    assert preview["graduates"] is False
    shop.use_item(state, "rareCandy", count=1, growth_difficulty=2.0)
    assert state.active.stage_index == 2
    assert state.active.used_at_stage == 125_000_000


def test_hidden_ditto_candy_preview_does_not_spoil_but_consumption_stops_at_reveal():
    state = CompanionState(active=mon(path=[1, 2, 3], ditto_disguise=1),
                           inventory={"rareCandy": 10})
    assert shop.candy_preview(state, 10)["count"] == 2
    shop.use_item(state, "rareCandy", count=10)
    assert state.active.ditto_revealed
    assert state.inventory["rareCandy"] == 9


@pytest.mark.parametrize("shiny,rarity", [(True, Rarity.COMMON), (False, Rarity.LEGENDARY)])
def test_precious_egg_discard_requires_confirmation_before_debit(shiny, rarity):
    state = CompanionState(active=mon(is_shiny=shiny, rarity=rarity), used_since_install=10**12)
    with pytest.raises(shop.ShopError, match="confirm"):
        shop.buy(state, "egg")
    assert state.active is not None and state.spent_tokens == 0
    shop.buy(state, "egg", confirmed=True)
    assert state.active is None and state.spent_tokens > 0


def test_precious_guard_does_not_reveal_hidden_shiny_ditto():
    state = CompanionState(active=mon(is_shiny=True, ditto_disguise=1), used_since_install=10**12)
    assert not shop.is_high_value(state)
    shop.buy(state, "egg")
    assert state.active is None


class OfflineLineAPI:
    def __init__(self):
        self.offline = True
        self.rolls = 0

    def roll_base_species(self, rng, tier=None):
        self.rolls += 1
        return 201 if self.rolls == 1 else 25

    def line(self, species):
        if self.offline:
            raise PokeAPIError("offline")
        return EvoLine(species, [species], Rarity.UNCOMMON)


def test_ready_egg_retries_same_form_without_new_tokens_after_restart(tmp_path):
    api = OfflineLineAPI()
    path = tmp_path / "save.json"
    store = CompanionStore(save_path=path, api=api)
    store.update({}, today="2026-10-04")
    store.update({"codex": 1_000_010}, today="2026-10-04")
    assert store.payload()["hatch_status"] == "delayed"
    prepared = store.state.pending_unown_form
    assert store.state.pending_hatch_id == 201
    api.offline = False
    reopened = CompanionStore(save_path=path, api=api)
    reopened.update({"codex": 1_000_010}, today="2026-10-04")
    assert reopened.state.active.current_id == 201
    assert reopened.state.active.unown_form == prepared
    assert reopened.state.active.used_at_stage == 10
    assert reopened.state.used_since_install == 1_000_010


def test_candy_grants_rearm_below_full_and_when_stable_window_epoch_changes():
    state = CompanionState(candy_feature_seeded=True)
    assert shop.grant_candy(state, {"codex:weekly": 100}, {"codex:weekly": "1"}) == 5
    assert shop.grant_candy(state, {"codex:weekly": 100}, {"codex:weekly": "1"}) == 0
    assert shop.grant_candy(state, {"codex:weekly": 100}, {"codex:weekly": "2"}) == 5
    shop.grant_candy(state, {"codex:weekly": 90}, {"codex:weekly": "2"})
    restored = save.decode(save.encode(state))
    assert shop.grant_candy(restored, {"codex:weekly": 100}, {"codex:weekly": "2"}) == 5


def test_no_limit_data_does_not_seed_candy_feature():
    state = CompanionState()
    shop.grant_candy(state, {})
    assert state.candy_feature_seeded is False


@pytest.mark.parametrize("count", [0, -1, True, "2", 1.5, None])
def test_invalid_candy_quantities_never_consume_inventory_or_advance(count):
    state = CompanionState(active=mon(), inventory={"rareCandy": 10})
    with pytest.raises(shop.ShopError):
        shop.use_item(state, "rareCandy", count=count)
    assert state.inventory["rareCandy"] == 10
    assert state.active.used_at_stage == 0


def test_release_preserves_reached_forms_and_profile_without_graduation_credit(tmp_path):
    store = CompanionStore(save_path=tmp_path / "save.json")
    store.state.active = mon(path=[1, 2, 3], stage_index=1)
    store._ensure_profiles()
    identity = store.state.active.profile.instance_id
    store.state.used_since_install = 10**12
    store.set_representative(2, is_shiny=False)
    store.buy("egg")
    assert len(store.state.dex) == 1
    released = store.state.dex[0]
    assert released.chain_order == [1, 2]
    assert released.final_id == 2
    assert released.profile.instance_id == identity
    assert released.is_released
    assert not store.state.collected_finals
    assert store.panel_species() == (2, False)
    assert store.catch_log_payload()[0]["is_released"]
    reopened = CompanionStore(save_path=store.save_path)
    assert reopened.state.dex[0].is_released


def test_released_hidden_ditto_does_not_reveal_unowned_species_or_shiny():
    state = CompanionState(active=mon(path=[1, 2, 3], is_shiny=True, ditto_disguise=1),
                           used_since_install=10**12)
    shop.buy(state, "egg")
    assert state.dex[0].chain_order == [1]
    assert state.dex[0].is_shiny is False


def test_bag_previews_cover_exact_quantities_without_following_huge_inventory(tmp_path):
    store = CompanionStore(save_path=tmp_path / "save.json")
    store.state.active = mon(path=[1, 2, 3])
    store.state.inventory = {"rareCandy": 10**30}
    bag, = store.bag_payload()
    assert bag["max_use_count"] == 2
    assert len(bag["previews"]) == 2
    assert bag["previews"][0]["carryover_xp"] == 25_000_000
    assert bag["previews"][0]["graduates"] is False
    assert bag["previews"][1]["discarded_xp"] == 50_000_000
    assert bag["previews"][1]["graduates"] is True


def test_shiny_celebration_uses_charm_odds_and_hides_ditto_identity(tmp_path):
    store = CompanionStore(save_path=tmp_path / "save.json")
    store.state.active = mon(25, is_shiny=True)
    store.state.inventory["shinyCharm"] = 1
    store._note_celebration(companion.GrowthEvents(hatched=25))
    assert "48" in store.celebration["detail"]
    store.state.active.ditto_disguise = 25
    store._note_celebration(companion.GrowthEvents(hatched=25))
    assert store.celebration["kind"] == "hatched"


def test_pinned_normal_appearance_stays_when_a_shiny_companion_evolves(tmp_path):
    store = CompanionStore(save_path=tmp_path / "save.json")
    store.state.dex = [DexEntry(1, 1, [1], Rarity.COMMON)]
    store.state.active = mon(path=[1, 2], is_shiny=True)
    store.set_representative(1, is_shiny=False)
    companion.apply_usage(store.state, 50_000_000)
    assert store.state.active.current_id == 2
    assert store.panel_species() == (1, False)


def test_unown_appearance_only_lists_matching_individual_profiles(tmp_path):
    from poketokenbar.profile import PokemonProfile

    store = CompanionStore(save_path=tmp_path / "save.json")
    first = PokemonProfile.generate(seed=1)
    second = PokemonProfile.generate(seed=2)
    store.state.dex = [
        DexEntry(201, 201, [201], Rarity.UNCOMMON, profile=first, unown_form="a"),
        DexEntry(201, 201, [201], Rarity.UNCOMMON, profile=second, unown_form="b"),
    ]
    appearances = store.dex_payload()[0]["appearances"]
    assert [p["instance_id"] for p in appearances[0]["profiles"]] == [first.instance_id]
    assert [p["instance_id"] for p in appearances[1]["profiles"]] == [second.instance_id]


def test_interrupted_species_fetch_does_not_save_usage_baseline_without_growth(tmp_path):
    class InterruptedAPI(OfflineLineAPI):
        def line(self, species):
            raise KeyboardInterrupt("process stopped during fetch")

    path = tmp_path / "save.json"
    store = CompanionStore(save_path=path, api=InterruptedAPI())
    store.update({}, today="2026-10-04")
    with pytest.raises(KeyboardInterrupt):
        store.update({"codex": 1_000_000}, today="2026-10-04")
    restored = save.load(path)
    assert restored.pending_hatch_id == 201
    assert restored.claimed_today_tokens_by_provider == {}
    assert restored.used_since_install == 0


def test_unown_species_shorthand_selects_owned_form_and_preserves_pinned_color(tmp_path):
    store = CompanionStore(save_path=tmp_path / "save.json")
    store.state.dex = [DexEntry(201, 201, [201], Rarity.UNCOMMON, unown_form="b")]
    store.set_representative(201)
    assert store.payload()["panel_unown_form"] == "b"
    assert store.panel_species() == (201, False)
    store.state.dex.append(DexEntry(201, 201, [201], Rarity.UNCOMMON,
                                    unown_form="question", is_shiny=True))
    store.set_representative(201)
    assert store.payload()["panel_unown_form"] == "b"
    assert store.panel_species() == (201, False)
    store.set_representative(201, is_shiny=True)
    assert store.payload()["panel_unown_form"] == "question"
    assert store.panel_species() == (201, True)
    with pytest.raises(ValueError):
        store.set_representative(201, unown_form="a")
    with pytest.raises(ValueError):
        store.set_representative(201, unown_form="b", is_shiny=True)
