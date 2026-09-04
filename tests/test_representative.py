"""Representative Pokemon — the species pinned to the panel and the desktop pet.

Ports the reconcile and ownership rules from CompanionModel.swift. The pin is a
species, not an individual: Home keeps showing whatever is actually being
raised, so the pin only ever changes the panel.
"""

import pytest

from poketokenbar import save
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, MonState
from poketokenbar.companion_store import CompanionStore


def graduated(base_id=1, final_id=3, chain=(1, 2, 3), shiny=False):
    return DexEntry(
        base_id=base_id,
        final_id=final_id,
        chain_order=list(chain),
        rarity=Rarity.COMMON,
        is_shiny=shiny,
    )


def raising(path=(4, 5, 6), stage=1, shiny=False, ditto_disguise=None, ditto_revealed=False):
    return MonState(
        base_id=path[0],
        path_ids=list(path),
        planned_path_ids=list(path),
        stage_index=stage,
        rarity=Rarity.COMMON,
        total_forms=len(path),
        is_shiny=shiny,
        ditto_disguise=ditto_disguise,
        ditto_revealed=ditto_revealed,
    )


def store(state):
    """A store around a prepared state.

    The store loads from disk on construction, so the state is assigned after —
    these cases are about the panel rules, not about loading.
    """
    subject = CompanionStore(api=None, sprite_store=None)
    subject.state = state
    return subject


# MARK: ownership


def test_a_graduated_line_is_owned_at_every_stage():
    state = CompanionState(dex=[graduated()])
    assert all(state.owns_species(i) for i in (1, 2, 3))


def test_the_current_companion_is_owned_only_up_to_where_it_reached():
    """A form it has not evolved into yet is not something anyone owns."""
    state = CompanionState(active=raising(path=(4, 5, 6), stage=1))
    assert state.owns_species(4)
    assert state.owns_species(5)
    assert not state.owns_species(6), "not evolved into yet"


def test_an_unknown_species_is_not_owned():
    assert not CompanionState().owns_species(25)


def test_shininess_comes_from_the_owned_copy():
    shiny_state = CompanionState(dex=[graduated(shiny=True)])
    plain_state = CompanionState(dex=[graduated(shiny=False)])
    assert shiny_state.owns_shiny_species(2)
    assert not plain_state.owns_shiny_species(2)


def test_a_disguised_ditto_keeps_its_shininess_hidden():
    """The panel must not spoil the reveal."""
    disguised = CompanionState(active=raising(shiny=True, ditto_disguise=132))
    assert not disguised.owns_shiny_species(4)

    revealed = CompanionState(
        active=raising(shiny=True, ditto_disguise=132, ditto_revealed=True)
    )
    assert revealed.owns_shiny_species(4)


# MARK: reconcile


def test_a_pin_on_an_owned_species_survives():
    state = CompanionState(dex=[graduated()], representative_species_id=2)
    state.reconcile_representative()
    assert state.representative_species_id == 2


def test_a_pin_on_a_species_no_longer_owned_is_dropped():
    """Buying a fresh egg would otherwise strand a ghost species on the panel."""
    state = CompanionState(active=raising(), representative_species_id=5)
    assert state.owns_species(5)

    state.active = None  # released the companion for a fresh egg
    state.reconcile_representative()
    assert state.representative_species_id is None


def test_a_hand_edited_save_cannot_pin_a_species_you_never_had():
    state = CompanionState(dex=[graduated()], representative_species_id=999)
    state.reconcile_representative()
    assert state.representative_species_id is None


def test_no_pin_reconciles_to_nothing():
    state = CompanionState()
    state.reconcile_representative()
    assert state.representative_species_id is None


# MARK: what the panel shows


def test_the_panel_follows_the_companion_when_nothing_is_pinned():
    state = CompanionState(active=raising(path=(4, 5, 6), stage=1, shiny=True))
    assert store(state).panel_species() == (5, True)


def test_the_panel_shows_the_pinned_species_instead():
    """While pinned, the panel stops following the egg, hatch and evolutions."""
    state = CompanionState(
        dex=[graduated(shiny=True)],
        active=raising(path=(4, 5, 6), stage=1),
        representative_species_id=3,
    )
    assert store(state).panel_species() == (3, True)


def test_an_egg_with_no_pin_shows_nothing():
    assert store(CompanionState()).panel_species() == (None, False)


def test_a_pin_still_shows_while_the_companion_is_an_egg():
    """The point of pinning: the panel keeps a favourite through the egg stage."""
    state = CompanionState(dex=[graduated()], representative_species_id=3)
    assert store(state).panel_species() == (3, False)


def test_the_payload_carries_both_the_companion_and_the_panel():
    """Home reads the companion's own sprite, so pinning must not hide it."""
    state = CompanionState(
        dex=[graduated()], active=raising(path=(4, 5, 6), stage=1), representative_species_id=3
    )
    payload = store(state).payload()
    assert payload["species_id"] == 5, "Home still shows what is being raised"
    assert payload["panel_species_id"] == 3
    assert payload["representative_species_id"] == 3


# MARK: setting it


def test_setting_a_pin_requires_owning_the_species(tmp_path):
    subject = store(CompanionState(dex=[graduated()]))
    with pytest.raises(ValueError):
        subject.set_representative(999)
    assert subject.state.representative_species_id is None


def test_setting_and_clearing_a_pin():
    subject = store(CompanionState(dex=[graduated()]))
    subject.set_representative(2)
    assert subject.state.representative_species_id == 2
    subject.set_representative(None)
    assert subject.state.representative_species_id is None


# MARK: persistence


def test_the_pin_survives_a_save_round_trip():
    state = CompanionState(dex=[graduated()], representative_species_id=3)
    restored = save.decode(save.encode(state))
    assert restored.representative_species_id == 3


def test_a_save_written_before_the_field_existed_still_loads():
    """Its absence means 'follow the companion', which is the old behaviour."""
    assert save.decode({"used_since_install": 5}).representative_species_id is None


def test_a_non_integer_pin_in_a_save_is_ignored():
    assert save.decode({"representative_species_id": "3"}).representative_species_id is None


# MARK: a pin that grows with what it names


def evolve(state):
    """Feed the companion exactly enough to advance one stage."""
    from poketokenbar import balance, companion

    mon = state.active
    threshold = balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
    return companion.apply_usage(state, threshold - mon.used_at_stage)


def test_a_pin_on_the_current_form_follows_the_evolution():
    """The ordinary reason to pin is "show me what I am raising, as it is now".

    Leaving the panel on the outgrown form made the evolution look like it had
    not happened at all — the notification arrived and the picture did not move.
    """
    state = CompanionState(active=raising(path=(4, 5, 6), stage=0))
    state.representative_species_id = 4

    events = evolve(state)

    assert events.evolved_to == 5
    assert state.representative_species_id == 5
    assert store(state).panel_species() == (5, False)


def test_a_pin_on_another_form_is_left_alone():
    """A pin on anything else names a species someone chose over the companion,
    and the companion growing is no reason to overrule it."""
    state = CompanionState(dex=[graduated(chain=(1, 2, 3))], active=raising(stage=0))
    state.representative_species_id = 2

    evolve(state)

    assert state.active.current_id == 5
    assert state.representative_species_id == 2


def test_a_pin_follows_every_stage_of_a_run():
    """Overflow can carry a companion through more than one stage at a time; the
    pin has to arrive where the companion does, not one form behind it."""
    from poketokenbar import balance, companion

    state = CompanionState(active=raising(path=(4, 5, 6), stage=0))
    state.representative_species_id = 4
    mon = state.active
    two_stages = sum(
        balance.phase_threshold(mon.rarity, mon.total_forms, stage) for stage in (0, 1))

    events = companion.apply_usage(state, two_stages)

    assert events.evolved_to == 6
    assert state.representative_species_id == state.active.current_id == 6


def test_a_pinned_ditto_lands_on_ditto_not_on_the_form_it_faked():
    """A Ditto's first evolution is a reveal, so the form it was pretending to
    grow into is one nobody owns. Pinning that would put a species on the panel
    that is not in anyone's Pokedex."""
    from poketokenbar import balance

    state = CompanionState(active=raising(path=(4, 5, 6), stage=0, ditto_disguise=4))
    state.representative_species_id = 4

    events = evolve(state)

    assert events.ditto_revealed
    assert state.representative_species_id == balance.DITTO_SPECIES_ID


# MARK: the pin lets go when the companion does


def graduate_now(state):
    """Feed the final form enough to complete it."""
    from poketokenbar import balance, companion

    mon = state.active
    threshold = balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
    return companion.apply_usage(state, threshold - mon.used_at_stage)


def test_a_pin_following_the_companion_is_released_when_it_graduates():
    """Otherwise the panel keeps the graduated Pokemon through the next egg.

    The species is in the dex by then, so reconcile has no reason to drop it,
    and the pin outlives the thing it was following.
    """
    state = CompanionState(active=raising(path=(4, 5, 6), stage=2))
    state.representative_species_id = 6

    events = graduate_now(state)

    assert events.graduated is not None
    assert state.representative_species_id is None
    # Nothing on the panel but the egg, which is the point.
    assert store(state).panel_species() == (None, False)


def test_the_panel_shows_the_next_companion_once_the_egg_hatches():
    """The complaint in full: pin, graduate, hatch — and the panel was still
    showing the Pokemon from two companions ago."""
    import random

    from poketokenbar import companion
    from poketokenbar.companion import EvoLine

    state = CompanionState(active=raising(path=(4, 5, 6), stage=2))
    state.representative_species_id = 6
    graduate_now(state)

    companion.hatch(
        state,
        EvoLine(base_id=270, path_ids=[270, 271, 272], rarity=Rarity.COMMON),
        random.Random(1),
    )

    assert store(state).panel_species()[0] == 270
    # And it keeps following: the released pin means "follow", not "empty".
    from poketokenbar import balance

    mon = state.active
    companion.apply_usage(
        state,
        balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
        - mon.used_at_stage,
    )
    assert store(state).panel_species()[0] == 271


def test_a_pin_on_a_different_species_survives_a_graduation():
    """Same rule as the evolution handoff: a pin on anything but the current
    form names a species chosen over the companion, and stays chosen."""
    state = CompanionState(
        dex=[graduated(chain=(1, 2, 3))], active=raising(path=(4, 5, 6), stage=2)
    )
    state.representative_species_id = 2

    graduate_now(state)

    assert state.representative_species_id == 2
    assert store(state).panel_species() == (2, False)


def test_a_pin_on_an_outgrown_form_of_the_same_companion_survives():
    """Pinning 4 while raising its final form can only be a deliberate choice —
    the handoff would have moved a following pin along with the evolutions."""
    state = CompanionState(active=raising(path=(4, 5, 6), stage=2))
    state.representative_species_id = 4

    graduate_now(state)

    assert state.representative_species_id == 4
