import random

from poketokenbar import balance
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, EvoLine, apply_usage, roll_ditto


class Rigged(random.Random):
    """Forces the ditto roll to hit or miss deterministically."""

    def __init__(self, ditto: bool):
        super().__init__(1)
        self._ditto = ditto

    def randrange(self, n):
        if n == balance.DITTO_DISGUISE_DENOMINATOR:
            return 0 if self._ditto else 1
        # Every other roll: anything but zero, so the hatch is never shiny —
        # but still a valid index, which `randrange` guarantees and this used
        # not to. Choosing an evolution branch calls randrange(1), and a stub
        # answering 1 there indexes past the end of a one-child pool.
        return 1 % n if n else 0


def _line(forms=2, rarity=Rarity.COMMON):
    return EvoLine(base_id=1, path_ids=list(range(1, forms + 1)), rarity=rarity)


def test_ditto_only_disguises_common_lines():
    assert roll_ditto(Rigged(True), _line(rarity=Rarity.RARE)) is False
    assert roll_ditto(Rigged(True), _line(rarity=Rarity.COMMON)) is True


def test_ditto_needs_at_least_two_forms():
    # A single-form line never "evolves", so the reveal would never fire.
    assert roll_ditto(Rigged(True), _line(forms=1)) is False


def test_hatch_can_produce_a_disguised_ditto():
    s = CompanionState()
    apply_usage(s, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=Rigged(True))
    assert s.active.ditto_disguise == 1
    assert s.active.ditto_revealed is False
    # Still shows the disguise species, not Ditto.
    assert s.active.current_id == 1


def test_normal_hatch_has_no_disguise():
    s = CompanionState()
    apply_usage(s, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=Rigged(False))
    assert s.active.ditto_disguise is None


def test_disguise_reveals_on_first_evolution():
    s = CompanionState()
    apply_usage(s, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=Rigged(True))
    events = apply_usage(s, balance.phase_threshold(Rarity.COMMON, 2, 0))
    assert events.ditto_revealed is True
    assert s.active.ditto_revealed is True
    assert s.active.current_id == balance.DITTO_SPECIES_ID


def test_reveal_happens_only_once():
    s = CompanionState()
    apply_usage(s, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(forms=3), rng=Rigged(True))
    apply_usage(s, balance.phase_threshold(Rarity.COMMON, 3, 0))
    second = apply_usage(s, balance.phase_threshold(Rarity.COMMON, 3, 1))
    assert second.ditto_revealed is False


def test_undisguised_evolution_does_not_report_a_reveal():
    s = CompanionState()
    apply_usage(s, balance.EGG_HATCH_THRESHOLD, line_for_egg=_line(), rng=Rigged(False))
    events = apply_usage(s, balance.phase_threshold(Rarity.COMMON, 2, 0))
    assert events.ditto_revealed is False


def test_a_disguised_ditto_keeps_its_colour_secret_everywhere(tmp_path):
    """Every surface that draws the companion asks the same question. A save
    snapshot asked a different one and listed a shiny sprite for a Pokemon the
    popup was still drawing plain (upstream 1a71018)."""
    from poketokenbar import snapshots
    from poketokenbar.companion import CompanionState, MonState
    from poketokenbar.companion_store import CompanionStore

    mon = MonState(base_id=1, path_ids=[1, 2], planned_path_ids=[1, 2], total_forms=2,
                   is_shiny=True, ditto_disguise=1)
    store = CompanionStore(save_path=tmp_path / "companion.json", api=None, sprite_store=None)
    store.state = CompanionState(active=mon)

    assert mon.is_shiny, "it really is shiny underneath"
    assert not mon.displays_shiny
    assert store.payload()["is_shiny"] is False
    assert store.panel_individual()[1] is False
    assert snapshots.create(store.state, store.save_path).is_shiny is False
    assert store.catch_log_payload()[0]["is_shiny"] is False
    assert all(not row["is_shiny"] for row in store.dex_payload())

    mon.ditto_revealed = True
    assert mon.displays_shiny
    assert store.payload()["is_shiny"] is True
    assert snapshots.create(store.state, store.save_path).is_shiny is True


def test_a_chain_holding_one_species_twice_is_read_once(tmp_path):
    """Only reachable by hand-editing, and it made the dex name lookup, the
    release record and the graduation record disagree (upstream 9c9c805)."""
    import json

    from poketokenbar import save
    from poketokenbar.balance import Rarity
    from poketokenbar.companion import CompanionState, DexEntry, MonState

    state = CompanionState(
        active=MonState(base_id=1, path_ids=[1, 2, 2, 3], planned_path_ids=[1, 2, 2, 3],
                        stage_index=2, total_forms=4),
        dex=[DexEntry(base_id=1, final_id=3, chain_order=[1, 2, 2, 3], rarity=Rarity.COMMON)],
    )
    path = tmp_path / "companion.json"
    save.save(state, path)
    loaded = save.load(path)

    assert loaded.active.path_ids == [1, 2, 3]
    assert loaded.active.current_id == 2, "the form on screen is still the one showing"
    assert loaded.dex[0].chain_order == [1, 2, 3]
    assert json.loads(path.read_text())  # the file itself is untouched until the next save
