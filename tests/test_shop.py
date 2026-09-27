import random

import pytest

from poketokenbar import balance, shop
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, EvoLine, apply_usage


def _with_mon(tokens=0):
    s = CompanionState()
    line = EvoLine(base_id=1, path_ids=[1, 2, 3], rarity=Rarity.COMMON)
    apply_usage(s, balance.EGG_HATCH_THRESHOLD, line_for_egg=line, rng=random.Random(1))
    s.used_since_install = tokens
    s.spent_tokens = 0
    return s


# --- shop listing ----------------------------------------------------------


def test_entries_are_sorted_by_price():
    prices = [e.price for e in shop.entries(CompanionState())]
    assert prices == sorted(prices)


def test_shiny_charm_shows_as_owned_once_held():
    s = CompanionState()
    s.inventory["shinyCharm"] = 1
    charm = next(e for e in shop.entries(s) if e.key == "shinyCharm")
    assert charm.owned is True


def test_three_egg_tiers_are_offered():
    keys = {e.key for e in shop.entries(CompanionState())}
    assert "egg" in keys and f"egg:{Rarity.UNCOMMON}" in keys and f"egg:{Rarity.RARE}" in keys


# --- buying ----------------------------------------------------------------


def test_buying_debits_the_wallet_but_not_growth():
    s = _with_mon(tokens=balance.RARE_CANDY_PRICE)
    shop.buy(s, "rareCandy")
    assert s.inventory["rareCandy"] == 1
    assert s.spent_tokens == balance.RARE_CANDY_PRICE
    assert s.used_since_install == balance.RARE_CANDY_PRICE  # growth never rewinds
    assert s.spendable_tokens == 0


def test_cannot_buy_without_funds():
    s = CompanionState()
    with pytest.raises(shop.ShopError):
        shop.buy(s, "rareCandy")


def test_unknown_item_is_rejected():
    with pytest.raises(shop.ShopError):
        shop.buy(CompanionState(), "masterball")


def test_shiny_charm_cannot_be_bought_twice():
    s = _with_mon(tokens=balance.SHINY_CHARM_PRICE * 2)
    shop.buy(s, "shinyCharm")
    with pytest.raises(shop.ShopError):
        shop.buy(s, "shinyCharm")


def test_buying_an_egg_releases_the_companion_into_the_dex():
    # Ports upstream 60808c5: the released companion stays in the dex so its
    # species do not vanish, but it was not raised to its final form, so
    # collected_finals (completion and branch weighting) is untouched.
    s = _with_mon(tokens=balance.FRESH_EGG_PRICE)
    shop.buy(s, "egg")
    assert s.active is None
    assert s.egg_usage == 0
    assert len(s.dex) == 1
    released = s.dex[0]
    assert released.is_released
    assert released.chain_order == [1]
    assert released.caught_at == released.released_at
    assert s.collected_finals == set()


def test_a_release_credits_only_the_forms_reached():
    # The planned path would make an egg a shortcut to evolutions never seen.
    s = _with_mon(tokens=balance.FRESH_EGG_PRICE)
    apply_usage(s, balance.phase_threshold(Rarity.COMMON, 3, 0))
    assert s.active.stage_index == 1
    shop.buy(s, "egg")
    assert s.dex[0].chain_order == [1, 2]
    assert s.dex[0].final_id == 2
    assert not s.owns_species(3)


def test_releasing_a_disguised_ditto_keeps_its_shininess_hidden():
    # Recording the raw is_shiny would make releasing a way to see the reveal.
    s = _with_mon(tokens=balance.FRESH_EGG_PRICE)
    s.active.is_shiny = True
    s.active.ditto_disguise = 1
    shop.buy(s, "egg")
    assert s.dex[0].is_shiny is False


@pytest.mark.parametrize("key", ["egg", f"egg:{Rarity.UNCOMMON}", f"egg:{Rarity.RARE}"])
def test_no_egg_can_be_bought_during_the_egg_stage(key):
    # Ports upstream's ShopTests contract: the eggs stay listed, every tier is
    # refused, and the refused attempt leaves the wallet and the incubation
    # alone. A purchase here used to charge the price and reset egg_usage.
    s = CompanionState(egg_usage=1234)
    s.used_since_install = balance.egg_price(Rarity.RARE) * 2
    assert {e.key for e in shop.entries(s)} >= {"egg", "egg:uncommon", "egg:rare"}
    with pytest.raises(shop.ShopError):
        shop.buy(s, key)
    assert s.spent_tokens == 0
    assert s.egg_usage == 1234


def test_premium_egg_records_its_guarantee():
    s = _with_mon(tokens=balance.egg_price(Rarity.RARE))
    shop.buy(s, f"egg:{Rarity.RARE}")
    assert s.egg_tier == Rarity.RARE


# --- using items -----------------------------------------------------------


def test_candy_grows_the_companion():
    s = _with_mon()
    s.inventory["rareCandy"] = 1
    before = s.active.used_at_stage
    shop.use_item(s, "rareCandy")
    assert s.active.used_at_stage == before + balance.RARE_CANDY_XP
    assert s.inventory["rareCandy"] == 0


def test_candy_cannot_be_used_on_an_egg():
    s = CompanionState()
    s.inventory["rareCandy"] = 1
    with pytest.raises(shop.ShopError):
        shop.use_item(s, "rareCandy")


def test_using_an_item_you_lack_is_rejected():
    with pytest.raises(shop.ShopError):
        shop.use_item(_with_mon(), "rareCandy")


def test_candy_hands_back_what_it_grew():
    """The events are the whole point of routing through apply_usage.

    They used to be dropped here, so an evolution or a graduation paid for
    with a candy reached neither the notifier nor the celebration banner.
    """
    s = _with_mon()
    s.inventory["rareCandy"] = 1
    mon = s.active
    mon.used_at_stage = balance.phase_threshold(
        mon.rarity, mon.total_forms, mon.stage_index) - balance.RARE_CANDY_XP

    result = shop.use_item(s, "rareCandy")
    assert result.events is not None
    assert result.events.evolved_to == s.active.current_id


def test_mint_reports_the_nature_it_rolled():
    s = _with_mon()
    s.inventory["mint"] = 1
    result = shop.use_item(s, "mint", rng=random.Random(5))
    assert result.nature == s.active.nature


def test_mint_rerolls_the_nature():
    s = _with_mon()
    s.inventory["mint"] = 1
    s.active.nature = "hardy"
    shop.use_item(s, "mint", rng=random.Random(5))
    assert s.active.nature in balance.NATURES
    assert s.inventory["mint"] == 0


# --- candy grants ----------------------------------------------------------


def test_first_run_does_not_pay_out_for_an_already_full_window():
    # Installing while a window sits at 100% must not backfill candy.
    s = CompanionState()
    assert shop.grant_candy(s, {"session": 100.0}) == 0
    assert s.inventory.get("rareCandy", 0) == 0


def test_full_session_window_grants_one_candy():
    s = CompanionState()
    shop.grant_candy(s, {"session": 10.0})  # seeds the feature
    assert shop.grant_candy(s, {"session": 100.0}) == balance.RARE_CANDY_SESSION_GRANT


def test_full_weekly_window_grants_five():
    s = CompanionState()
    shop.grant_candy(s, {"weekly": 10.0})
    assert shop.grant_candy(s, {"weekly": 100.0}) == balance.RARE_CANDY_WEEKLY_GRANT


def test_grant_is_edge_triggered_not_repeated_every_poll():
    s = CompanionState()
    shop.grant_candy(s, {"session": 10.0})
    first = shop.grant_candy(s, {"session": 100.0})
    second = shop.grant_candy(s, {"session": 100.0})
    third = shop.grant_candy(s, {"session": 100.0})
    assert first > 0
    assert second == 0 and third == 0


def test_window_rearms_after_dropping_below_the_warning_line():
    s = CompanionState()
    shop.grant_candy(s, {"session": 10.0})
    shop.grant_candy(s, {"session": 100.0})
    shop.grant_candy(s, {"session": 5.0})  # window reset
    assert shop.grant_candy(s, {"session": 100.0}) > 0


def test_a_window_that_has_reset_pays_out_again_without_ever_dipping(monkeypatch):
    """The weekly window is usually read as already full, then read as full
    again after it rolls over — it never passes through a low utilization for
    the dip to catch, so the reset itself has to rearm it (upstream e94da86)."""
    s = CompanionState()
    shop.grant_candy(s, {"weekly": 10.0}, {"weekly": "2026-09-22T00:00:00Z"})
    first = shop.grant_candy(s, {"weekly": 100.0}, {"weekly": "2026-09-22T00:00:00Z"})
    again = shop.grant_candy(s, {"weekly": 100.0}, {"weekly": "2026-09-22T00:00:00Z"})
    after_reset = shop.grant_candy(s, {"weekly": 100.0}, {"weekly": "2026-09-29T00:00:00Z"})
    assert first > 0 and again == 0 and after_reset > 0


def test_a_window_with_no_reset_instant_still_needs_the_dip():
    # Not every provider reports one, and a missing instant must not read as a
    # window that has changed.
    s = CompanionState()
    shop.grant_candy(s, {"session": 10.0})
    assert shop.grant_candy(s, {"session": 100.0}) > 0
    assert shop.grant_candy(s, {"session": 100.0}, {"session": None}) == 0


def test_the_first_sighting_of_a_window_is_not_a_reset():
    s = CompanionState()
    shop.grant_candy(s, {"session": 10.0}, {"session": "2026-09-27T00:00:00Z"})
    assert shop.grant_candy(s, {"session": 100.0}, {"session": "2026-09-27T00:00:00Z"}) > 0
    assert s.candy_window_epoch == {"limit:session": "2026-09-27T00:00:00Z"}


def test_window_key_excludes_volatile_fields():
    # A rolling weekly window reports a new resets_at on every fetch. Keying on
    # it re-fired the notification each refresh in the Swift app.
    assert shop.window_key("weekly") == "limit:weekly"
    assert "resets" not in shop.window_key("weekly")


# --- buying several at once -------------------------------------------------
#
# This port's own: upstream's shop is one item per click, which is a lot of
# clicking for a wallet holding hundreds of candies.


def _candy_price(state):
    return next(e for e in shop.entries(state) if e.key == "rareCandy").price


def test_one_purchase_can_cover_a_stack_of_items():
    s = _with_mon(tokens=10 ** 12)
    price = _candy_price(s)
    result = shop.buy(s, "rareCandy", 7)
    assert result.count == 7
    assert s.inventory["rareCandy"] == 7
    assert s.spent_tokens == price * 7


def test_a_stack_the_wallet_cannot_cover_is_refused_whole():
    s = _with_mon(tokens=0)
    s.used_since_install = _candy_price(s) * 2
    with pytest.raises(shop.ShopError):
        shop.buy(s, "rareCandy", 3)
    assert s.inventory.get("rareCandy", 0) == 0
    assert s.spent_tokens == 0


def test_max_buy_is_what_the_wallet_covers_and_eggs_stay_single():
    s = _with_mon(tokens=0)
    price = _candy_price(s)
    s.used_since_install = price * 5
    candy = next(e for e in shop.entries(s) if e.key == "rareCandy")
    assert shop.max_buy(s, candy) == 5
    egg = next(e for e in shop.entries(s) if e.key == "egg")
    s.used_since_install = 10 ** 12
    assert shop.max_buy(s, egg) == 1
    with pytest.raises(shop.ShopError):
        shop.buy(s, "egg", 2)


def test_a_passive_and_a_nonsense_count_are_refused():
    s = _with_mon(tokens=10 ** 12)
    with pytest.raises(shop.ShopError):
        shop.buy(s, "shinyCharm", 2)
    with pytest.raises(shop.ShopError):
        shop.buy(s, "rareCandy", 0)
    assert s.inventory == {}


# --- using several candies at once (upstream 2e8efdd) -----------------------


def test_the_offer_never_exceeds_what_graduation_can_absorb():
    s = _with_mon(tokens=10 ** 12)
    s.inventory["rareCandy"] = 500
    needed = -(-sum(shop.candy_stage_costs(s)) // balance.RARE_CANDY_XP)
    assert shop.max_candy_uses(s) == needed < 500
    # And never more than the bag holds.
    s.inventory["rareCandy"] = 2
    assert shop.max_candy_uses(s) == 2


def test_a_batch_short_of_the_threshold_only_progresses():
    s = _with_mon(tokens=10 ** 12)
    s.inventory["rareCandy"] = 1
    plan = shop.plan_candy_use(s, 1)
    assert plan.count == 1 and plan.xp == balance.RARE_CANDY_XP
    assert not plan.evolves and not plan.graduates
    assert plan.carryover_xp == 0 and plan.discarded_xp == 0


def test_a_batch_that_clears_a_stage_evolves_and_carries_the_rest_over():
    s = _with_mon(tokens=10 ** 12)
    s.inventory["rareCandy"] = 500
    costs = shop.candy_stage_costs(s)
    count = -(-costs[0] // balance.RARE_CANDY_XP) + 1
    plan = shop.plan_candy_use(s, count)
    assert plan.evolves and not plan.graduates
    assert plan.carryover_xp == count * balance.RARE_CANDY_XP - costs[0]
    assert plan.discarded_xp == 0


def test_a_batch_that_clears_every_stage_graduates_and_discards_the_leftover():
    s = _with_mon(tokens=10 ** 12)
    s.inventory["rareCandy"] = 500
    total = sum(shop.candy_stage_costs(s))
    count = shop.max_candy_uses(s)
    plan = shop.plan_candy_use(s, count)
    assert plan.graduates and plan.carryover_xp == 0
    assert plan.discarded_xp == count * balance.RARE_CANDY_XP - total


def test_using_a_batch_spends_exactly_the_candies_the_plan_needed():
    s = _with_mon(tokens=10 ** 12)
    s.inventory["rareCandy"] = 500
    needed = shop.max_candy_uses(s)
    before = s.active.used_at_stage
    result = shop.use_item(s, "rareCandy", rng=random.Random(2), count=500)
    assert result.count == needed
    assert s.inventory["rareCandy"] == 500 - needed
    # Graduating clears the companion, which is what a full batch is for.
    assert result.events.graduated is not None
    assert before >= 0


def test_a_batch_of_one_is_still_the_old_single_use():
    s = _with_mon(tokens=10 ** 12)
    s.inventory["rareCandy"] = 3
    result = shop.use_item(s, "rareCandy", rng=random.Random(3))
    assert result.count == 1 and s.inventory["rareCandy"] == 2
    assert s.active.used_at_stage == balance.RARE_CANDY_XP


def test_candy_has_no_plan_without_a_companion_or_a_candy():
    s = CompanionState()
    s.inventory["rareCandy"] = 5
    assert shop.max_candy_uses(s) == 0 and shop.plan_candy_use(s, 1) is None
    with pytest.raises(shop.ShopError):
        shop.use_item(s, "rareCandy", count=3)
