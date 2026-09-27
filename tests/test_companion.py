import random

import random

from poketokenbar import balance
from poketokenbar.balance import Rarity
from poketokenbar.companion import (
    CompanionState,
    EvoLine,
    MonState,
    apply_usage,
    roll_shiny,
)


def _line(forms=3, rarity=Rarity.COMMON):
    return EvoLine(base_id=1, path_ids=list(range(1, forms + 1)), rarity=rarity)


def _state():
    return CompanionState()


def _rng():
    """A hatch that is never a surprise.

    Every hatch rolls shiny, nature and a 1-in-128 Ditto disguise, and an
    unseeded Random meant those rolls differed per run. A disguised Ditto's
    first threshold is a reveal rather than an evolution — correctly, since it
    cannot evolve — so a growth test written without a seed failed about once
    in two hundred runs, on whichever platform happened to draw it. The
    disguise is tested through test_ditto, not through growth.
    """
    return random.Random(20260903)


# --- egg -------------------------------------------------------------------


def test_egg_absorbs_tokens_without_hatching_early():
    s = _state()
    apply_usage(s, 1_000_000, line_for_egg=_line(), rng=_rng())
    assert s.active is None
    assert s.egg_usage == 1_000_000


def test_egg_hatches_at_the_threshold():
    s = _state()
    events = apply_usage(s, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=_rng())
    assert s.active is not None
    assert events.hatched == 1


def test_hatch_overflow_carries_into_the_hatchling():
    s = _state()
    apply_usage(s, balance.EGG_HATCH_THRESHOLD + 250, line_for_egg=_line(), rng=_rng())
    assert s.active.used_at_stage == 250


def test_egg_holds_progress_when_no_species_data_is_available():
    # Offline at the moment of hatching must not discard the tokens.
    s = _state()
    apply_usage(s, balance.EGG_HATCH_THRESHOLD + 500, line_for_egg=None, rng=_rng())
    assert s.active is None
    assert s.egg_usage == balance.EGG_HATCH_THRESHOLD + 500


def test_hatching_consumes_a_premium_egg_guarantee():
    s = _state()
    s.egg_tier = Rarity.RARE
    apply_usage(s, balance.EGG_HATCH_THRESHOLD,
                line_for_egg=_line(rarity=Rarity.RARE), rng=_rng())
    assert s.egg_tier is None


# --- growth ----------------------------------------------------------------


def _hatched(forms=3, rarity=Rarity.COMMON):
    """A hatched companion that is definitely itself.

    Seeded: a common line of two or more forms has a 1 in 128 chance of
    hatching a disguised Ditto, whose chain and graduation are deliberately not
    the line's — which made every test built on this fixture fail about once in
    a hundred runs for reasons that had nothing to do with it.
    """
    s = _state()
    apply_usage(s, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(forms, rarity),
                rng=_rng())
    return s


def test_evolves_when_the_stage_threshold_is_met():
    s = _hatched()
    need = balance.phase_threshold(Rarity.COMMON, 3, 0)
    events = apply_usage(s, need)
    assert s.active.stage_index == 1
    assert events.evolved_to == 2


def test_does_not_evolve_one_token_short():
    s = _hatched()
    need = balance.phase_threshold(Rarity.COMMON, 3, 0)
    apply_usage(s, need - 1)
    assert s.active.stage_index == 0


def test_a_large_delta_can_cross_two_stages_at_once():
    s = _hatched()
    need = balance.phase_threshold(Rarity.COMMON, 3, 0) + balance.phase_threshold(
        Rarity.COMMON, 3, 1
    )
    apply_usage(s, need)
    assert s.active.stage_index == 2


def test_graduates_from_the_final_form():
    s = _hatched(forms=1)
    events = apply_usage(s, balance.graduation_total(Rarity.COMMON))
    assert events.graduated is not None
    assert s.active is None, "slot clears for a fresh egg"
    assert len(s.dex) == 1


def test_graduation_records_the_full_chain():
    s = _hatched(forms=3)
    apply_usage(s, balance.graduation_total(Rarity.COMMON))
    assert s.dex[0].chain_order == [1, 2, 3]
    assert s.dex[0].final_id == 3


def test_graduation_marks_the_base_final_pair_as_collected():
    """"base:final", the key the branch preference looks the pair up by. It is
    written the way upstream writes it — the two halves are read back apart, so
    both ends have to agree on the separator."""
    s = _hatched(forms=1)
    apply_usage(s, balance.graduation_total(Rarity.COMMON))
    assert "1:1" in s.collected_finals


def test_rarer_lines_take_longer_to_graduate():
    common = _hatched(forms=1, rarity=Rarity.COMMON)
    legendary = _hatched(forms=1, rarity=Rarity.LEGENDARY)
    amount = balance.graduation_total(Rarity.COMMON)
    apply_usage(common, amount)
    apply_usage(legendary, amount)
    assert common.active is None
    assert legendary.active is not None


# --- currency --------------------------------------------------------------


def test_usage_accumulates_into_the_growth_meter():
    s = _state()
    apply_usage(s, 5_000)
    assert s.used_since_install == 5_000


def test_spending_reduces_the_wallet_but_not_the_growth_meter():
    s = _state()
    apply_usage(s, 1_000)
    s.spent_tokens = 400
    assert s.used_since_install == 1_000
    assert s.spendable_tokens == 600


def test_wallet_never_goes_negative():
    s = _state()
    s.spent_tokens = 10
    assert s.spendable_tokens == 0


def test_zero_or_negative_usage_is_a_no_op():
    s = _state()
    apply_usage(s, 0)
    apply_usage(s, -5)
    assert s.used_since_install == 0


# --- rolls -----------------------------------------------------------------


def test_shiny_charm_improves_the_odds():
    # Deterministic seeds: the charm's denominator must be the smaller one.
    class AlwaysBoundary(random.Random):
        def randrange(self, n):
            self.seen = n
            return 1

    plain, charmed = AlwaysBoundary(), AlwaysBoundary()
    roll_shiny(plain, has_charm=False)
    roll_shiny(charmed, has_charm=True)
    assert plain.seen == balance.SHINY_DENOMINATOR
    assert charmed.seen == balance.SHINY_CHARM_DENOMINATOR
    assert charmed.seen < plain.seen


def test_shiny_and_nature_are_fixed_at_hatch():
    s = _state()
    apply_usage(s, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=random.Random(1))
    shiny, nature = s.active.is_shiny, s.active.nature
    apply_usage(s, balance.phase_threshold(Rarity.COMMON, 3, 0))
    assert s.active.is_shiny == shiny
    assert s.active.nature == nature
    assert nature in balance.NATURES


# --- damaged state ---------------------------------------------------------


def test_current_id_survives_empty_path_ids():
    # A corrupted save must not crash rendering, which runs every frame.
    mon = MonState(base_id=25, path_ids=[], planned_path_ids=[], rarity=Rarity.COMMON)
    assert mon.current_id == 25


def test_current_id_clamps_an_out_of_range_stage():
    mon = MonState(base_id=1, path_ids=[1, 2], planned_path_ids=[1, 2], stage_index=99)
    assert mon.current_id == 2
