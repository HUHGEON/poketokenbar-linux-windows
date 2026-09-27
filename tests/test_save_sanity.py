"""A save that cannot be true.

The file is plain JSON on the machine of whoever is running this, and that is
not a hole to be plugged: there is no server, no leaderboard, and the currency
is tokens they have already spent. A signature would need its key on the same
disk, and would cost the ability to recover a damaged save. Upstream ships
plain JSON for the same reason.

What is worth catching is the *impossible*, not the generous. Those values
arrive by more routes than editing — a write cut short, a disk error, a save
carried between machines, a field an older version wrote, and the `import`
command, which takes somebody else's file wholesale — and every one of them
used to be accepted in silence and then quietly misbehave.
"""

import json

import pytest

from poketokenbar import balance, save
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, MonState


def a_save(**overrides) -> dict:
    state = CompanionState(
        active=MonState(base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3],
                        stage_index=0, rarity=Rarity.COMMON, total_forms=3),
        used_since_install=1000,
        install_baseline_set=True,
        dex=[DexEntry(base_id=4, final_id=6, chain_order=[4, 5, 6],
                      rarity=Rarity.COMMON)],
    )
    return {**save.encode(state), **overrides}


def loaded(raw: dict) -> CompanionState:
    return save.decode(json.loads(json.dumps(raw)))


# MARK: the ledger


def test_spending_more_than_was_earned_is_pulled_back():
    """Spendable already floors at zero, so this is invisible until the ledger
    is read for anything else — and then every figure from it is wrong by the
    difference."""
    state = loaded(a_save(spent_tokens=10 ** 12))
    assert state.spent_tokens == state.used_since_install
    assert state.spendable_tokens == 0


def test_negative_totals_become_zero():
    state = loaded(a_save(used_since_install=-5000, spent_tokens=-1, egg_usage=-7))
    assert (state.used_since_install, state.spent_tokens, state.egg_usage) == (0, 0, 0)


def test_a_generous_but_possible_save_is_left_alone():
    """The point of the line: a save someone has edited to be rich is not a
    save that cannot be true, and this is not an anti-cheat measure."""
    state = loaded(a_save(used_since_install=10 ** 12, spent_tokens=0,
                          inventory={"rareCandy": 200}))
    assert state.used_since_install == 10 ** 12
    assert state.inventory == {"rareCandy": 200}


# MARK: the companion


def test_a_species_that_cannot_exist_leaves_an_egg():
    """There is nothing to draw and nothing to look up, and a blank square is
    worse than starting over — the Pokedex is untouched either way."""
    raw = a_save()
    raw["active"] = dict(raw["active"], base_id=99999, path_ids=[99999],
                         planned_path_ids=[99999])
    state = loaded(raw)
    assert state.active is None
    assert len(state.dex) == 1, "the Pokedex was collateral"


def test_a_stage_past_the_end_of_the_line_is_pulled_back():
    raw = a_save()
    raw["active"] = dict(raw["active"], stage_index=99)
    state = loaded(raw)
    assert state.active.stage_index == len(state.active.path_ids) - 1
    assert state.active.current_id in state.active.path_ids


def test_a_negative_stage_is_pulled_back():
    raw = a_save()
    raw["active"] = dict(raw["active"], stage_index=-3)
    assert loaded(raw).active.stage_index == 0


def test_fewer_forms_than_stages_is_corrected():
    """The threshold weighting divides by the number of forms, so claiming
    fewer than the line actually has makes a later stage cost less than an
    earlier one."""
    raw = a_save()
    raw["active"] = dict(raw["active"], total_forms=1)
    state = loaded(raw)
    assert state.active.total_forms == 3
    thresholds = [balance.phase_threshold(Rarity.COMMON, state.active.total_forms, i)
                  for i in range(3)]
    assert thresholds == sorted(thresholds)


def test_an_impossible_form_is_dropped_from_the_line():
    raw = a_save()
    raw["active"] = dict(raw["active"], path_ids=[1, 99999, 3])
    state = loaded(raw)
    assert state.active.path_ids == [1, 3]


# MARK: the collections


def test_a_dex_entry_naming_a_species_that_cannot_exist_is_dropped():
    raw = a_save()
    raw["dex"] = raw["dex"] + [{"base_id": 99999, "final_id": 99999,
                                "chain_order": [99999], "rarity": "common"}]
    state = loaded(raw)
    assert [entry.final_id for entry in state.dex] == [6]


def test_inventory_counts_are_positive_integers():
    state = loaded(a_save(inventory={"rareCandy": -5, "mint": 3, "junk": "x",
                                     "zero": 0}))
    assert state.inventory == {"mint": 3}


def test_an_inventory_that_is_not_a_map_is_ignored():
    assert loaded(a_save(inventory="cheat")).inventory == {}


def test_a_pin_on_a_species_nobody_owns_is_released():
    """Otherwise the panel shows a ghost permanently."""
    state = loaded(a_save(representative_species_id=888))
    assert state.representative_species_id is None


# MARK: it has to say so


def test_a_repair_is_reported_rather_than_made_in_silence():
    """A save quietly corrected is the same silence this exists to end: the
    first sign would be a Pokemon that looks wrong."""
    loaded(a_save(spent_tokens=10 ** 12, used_since_install=-1))
    assert save.last_repairs
    assert any("spent_tokens" in note for note in save.last_repairs)


def test_a_healthy_save_reports_nothing():
    loaded(a_save())
    assert save.last_repairs == []


def test_the_daemon_surfaces_it_once(tmp_path):
    from poketokenbar import config, state as state_module
    from poketokenbar.companion_store import CompanionStore
    from poketokenbar.daemon import Daemon

    path = tmp_path / "companion.json"
    path.write_text(json.dumps(a_save(spent_tokens=10 ** 12)), encoding="utf-8")

    store = CompanionStore(save_path=path, api=None, sprite_store=None)
    assert store.save_repairs, "the store did not carry the repair"

    daemon = Daemon(state_path=tmp_path / "state.json",
                    config_path=config.default_path(), cache=None, providers=[],
                    companion_store=store)
    first = daemon.poll_once()
    assert any("save:" in error for error in first["errors"])

    second = daemon.poll_once()
    assert not any("save:" in error for error in second["errors"]), (
        "reported on every poll for the life of the process"
    )


# MARK: what is deliberately not defended


def test_editing_the_save_still_works():
    """Stated as a test so nobody mistakes this file for an anti-cheat
    measure and 'fixes' it into one. The save belongs to whoever is running
    this, there is nothing to cheat at, and a signature would need its key on
    the same disk while costing the ability to recover a damaged save."""
    state = loaded(a_save(inventory={"rareCandy": 200, "shinyCharm": 1}))
    assert state.inventory["rareCandy"] == 200


@pytest.mark.parametrize("field", ["used_since_install", "spent_tokens", "egg_usage"])
def test_no_checksum_or_signature_is_written(field, tmp_path):
    path = tmp_path / "companion.json"
    save.save(CompanionState(**{field: 5}), path)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert not any(key in written for key in ("hash", "hmac", "signature", "checksum"))
