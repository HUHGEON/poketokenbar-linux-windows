import pytest

from poketokenbar.balance import (
    EGG_HATCH_THRESHOLD,
    FRESH_EGG_PRICE,
    Rarity,
    egg_price,
    graduation_total,
    phase_threshold,
)


def test_plus_egg_threshold_is_one_fifth_of_swift():
    assert EGG_HATCH_THRESHOLD == 1_000_000


@pytest.mark.parametrize(
    "rarity,total",
    [
        (Rarity.COMMON, 750_000_000),
        (Rarity.UNCOMMON, 1_875_000_000),
        (Rarity.RARE, 3_000_000_000),
        (Rarity.LEGENDARY, 6_000_000_000),
    ],
)
def test_pro_graduation_totals_match_swift(rarity, total):
    assert graduation_total(rarity) * 5 == total
    assert phase_threshold(rarity, 1, 0, multiplier=5) == total


def test_phase_thresholds_sum_to_the_graduation_total():
    # The point of the weighting: a 1-form line and a 3-form line cost the same
    # in total, just distributed differently.
    for forms in (1, 2, 3):
        total = sum(phase_threshold(Rarity.COMMON, forms, i) for i in range(forms))
        assert total == pytest.approx(graduation_total(Rarity.COMMON), rel=1e-9)


def test_later_stages_cost_more():
    a = phase_threshold(Rarity.COMMON, 3, 0)
    b = phase_threshold(Rarity.COMMON, 3, 1)
    c = phase_threshold(Rarity.COMMON, 3, 2)
    assert a < b < c


def test_single_form_line_needs_the_whole_total():
    assert phase_threshold(Rarity.COMMON, 1, 0) == 150_000_000


# --- rarity ---------------------------------------------------------------


@pytest.mark.parametrize(
    "rate,expected",
    [(3, Rarity.RARE), (45, Rarity.RARE), (46, Rarity.UNCOMMON),
     (120, Rarity.UNCOMMON), (121, Rarity.COMMON), (255, Rarity.COMMON)],
)
def test_capture_rate_classification(rate, expected):
    assert Rarity.classify(rate, False, False) == expected


def test_legendary_flag_overrides_capture_rate():
    assert Rarity.classify(255, True, False) == Rarity.LEGENDARY
    assert Rarity.classify(255, False, True) == Rarity.LEGENDARY


def test_legendary_cannot_be_derived_from_capture_rate():
    # There is no rate that means "legendary", which is why no legendary-only
    # egg is sold.
    assert Rarity.LEGENDARY.capture_rate_ceiling is None
    assert Rarity.LEGENDARY.includes(1) is False


def test_sort_rank_orders_rarity_ascending():
    ranks = [r.sort_rank for r in (Rarity.COMMON, Rarity.UNCOMMON, Rarity.RARE, Rarity.LEGENDARY)]
    assert ranks == sorted(ranks)


# --- egg pricing ----------------------------------------------------------


def test_plain_egg_price():
    assert egg_price(None) == FRESH_EGG_PRICE


def test_premium_egg_prices_follow_the_graduation_table():
    assert egg_price(Rarity.UNCOMMON) == 500_000_000
    assert egg_price(Rarity.RARE) == 800_000_000


def test_higher_tier_egg_is_not_an_inferior_good():
    # Two uncommon eggs must cost more than one rare egg, or the rare tier is
    # dominated and nobody should ever buy it.
    assert 2 * egg_price(Rarity.UNCOMMON) > egg_price(Rarity.RARE)
