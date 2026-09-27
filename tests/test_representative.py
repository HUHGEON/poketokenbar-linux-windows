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
    """A companion that vanishes without a record (a hand-edited save) would
    otherwise strand a ghost species on the panel."""
    state = CompanionState(active=raising(), representative_species_id=5)
    assert state.owns_species(5)

    state.active = None
    state.reconcile_representative()
    assert state.representative_species_id is None


def test_a_pin_on_a_released_species_survives_the_egg():
    """A shop egg now keeps the released companion in the dex, so the species
    is still owned and the user's pin stays (upstream 60808c5)."""
    subject = CompanionStore(api=None, sprite_store=None)
    subject.state = CompanionState(active=raising(), representative_species_id=5)
    subject.state.used_since_install = 10**12
    subject.buy("egg")
    assert subject.state.active is None
    assert subject.state.representative_species_id == 5
    rows = {r["species_id"]: r for r in subject.dex_payload()}
    assert 5 in rows
    assert rows[5]["is_raising"] is False
    assert subject.catch_log_payload()[0]["released"] is True


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


# MARK: a pin stays where it was put


def evolve(state):
    """Feed the companion exactly enough to advance one stage."""
    from poketokenbar import balance, companion

    mon = state.active
    threshold = balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
    return companion.apply_usage(state, threshold - mon.used_at_stage)


def test_an_evolution_does_not_move_the_pin():
    """The pin names a species the user chose, and growth is not a reason to
    overrule that choice.

    A pin on the form being outgrown used to be dragged along with the
    evolution, on the grounds that a panel left on the old form made the
    evolution look like it had not happened. What made it look that way was
    that nothing said the panel was pinned at all — Home names the pinned
    species and offers to release it now.
    """
    state = CompanionState(active=raising(path=(4, 5, 6), stage=0))
    state.representative_species_id = 4

    events = evolve(state)

    assert events.evolved_to == 5, "the companion still evolves"
    assert state.representative_species_id == 4
    assert store(state).panel_species() == (4, False)


def test_a_pin_on_another_form_is_left_alone():
    state = CompanionState(dex=[graduated(chain=(1, 2, 3))], active=raising(stage=0))
    state.representative_species_id = 2

    evolve(state)

    assert state.active.current_id == 5
    assert state.representative_species_id == 2


def test_a_run_through_several_stages_does_not_move_the_pin():
    """Overflow can carry a companion through more than one stage at a time.
    None of them is a reason to repoint the panel."""
    from poketokenbar import balance, companion

    state = CompanionState(active=raising(path=(4, 5, 6), stage=0))
    state.representative_species_id = 4
    mon = state.active
    two_stages = sum(
        balance.phase_threshold(mon.rarity, mon.total_forms, stage) for stage in (0, 1))

    events = companion.apply_usage(state, two_stages)

    assert events.evolved_to == 6
    assert state.active.current_id == 6
    assert state.representative_species_id == 4


def test_a_ditto_reveal_does_not_move_the_pin_either():
    """The reveal replaces an evolution, and it is still growth. What the pin
    names — the ordinary species the user picked out of the Pokedex — is
    unaffected, and it does not spoil the reveal by naming Ditto."""
    state = CompanionState(active=raising(path=(4, 5, 6), stage=0, ditto_disguise=4))
    state.representative_species_id = 4

    events = evolve(state)

    assert events.ditto_revealed
    assert state.representative_species_id == 4


# MARK: a pin outlives the companion, on purpose


def graduate_now(state):
    """Feed the final form enough to complete it."""
    from poketokenbar import balance, companion

    mon = state.active
    threshold = balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
    return companion.apply_usage(state, threshold - mon.used_at_stage)


def test_a_graduation_does_not_release_the_pin():
    """Keeping a favourite on the panel through the egg stage is what pinning
    is for.

    It used to be released here, because a pin nobody could see or clear kept
    the graduated Pokemon on the panel through the next egg and looked like a
    stuck panel. The pin is badged in the Pokedex and has a release button on
    Home now, so there is no longer a reason to overrule the user.
    """
    state = CompanionState(active=raising(path=(4, 5, 6), stage=2))
    state.representative_species_id = 6

    events = graduate_now(state)

    assert events.graduated is not None
    assert state.active is None, "the companion still graduates"
    assert state.representative_species_id == 6
    assert store(state).panel_species() == (6, False)


def test_a_pin_held_through_a_graduation_survives_the_next_hatch():
    """The panel keeps showing the chosen species while the next one grows;
    Home shows the newcomer, as it always does."""
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

    subject = store(state)
    assert subject.panel_species()[0] == 6
    assert subject.payload()["species_id"] == 270, "Home follows the new companion"


def test_releasing_the_pin_hands_the_panel_to_the_new_companion():
    """The way out of the above, and the only one needed: one tap on the
    release button."""
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

    subject = store(state)
    subject.set_representative(None)
    assert subject.panel_species()[0] == 270


def test_a_pin_on_a_different_species_survives_a_graduation():
    state = CompanionState(
        dex=[graduated(chain=(1, 2, 3))], active=raising(path=(4, 5, 6), stage=2)
    )
    state.representative_species_id = 2

    graduate_now(state)

    assert state.representative_species_id == 2
    assert store(state).panel_species() == (2, False)


def test_a_pin_on_an_outgrown_form_of_the_same_companion_survives():
    state = CompanionState(active=raising(path=(4, 5, 6), stage=2))
    state.representative_species_id = 4

    graduate_now(state)

    assert state.representative_species_id == 4


# MARK: letting the pin go again


def test_tapping_the_pinned_species_again_releases_it():
    """The pin was one-way: nothing in the UI could give the panel back.

    A Pokedex tap is the only thing that sends `represent`, and a tap on a grid
    of sprites reads as "show me this one". So the panel and the desktop pet
    froze on whatever was tapped, through every evolution after it, and the
    growth looked like it had stopped.
    """
    subject = store(CompanionState(dex=[graduated()]))
    subject.set_representative(2)
    assert subject.state.representative_species_id == 2

    subject.set_representative(2)
    assert subject.state.representative_species_id is None


def test_releasing_a_pin_on_an_outgrown_form_hands_the_panel_back():
    """The case that was reported: pinned to a form the companion has left.

    That pin keeps overriding the companion by design — it names a species
    someone chose. What was missing is the way out.
    """
    state = CompanionState(active=raising(path=(4, 5, 6), stage=1))
    state.representative_species_id = 4
    subject = store(state)
    assert subject.panel_species() == (4, False)

    subject.set_representative(4)
    assert subject.panel_species() == (5, False)


def test_the_pokedex_says_which_cell_holds_the_panel():
    """The pin was invisible, so a panel that had stopped following the
    companion looked stuck rather than pinned, with no clue which cell to tap
    to undo it."""
    state = CompanionState(dex=[graduated()], representative_species_id=2)
    rows = {row["species_id"]: row["is_pinned"] for row in store(state).dex_payload()}
    assert rows[2] is True
    assert all(pinned is False for species, pinned in rows.items() if species != 2)


def test_the_payload_names_the_species_holding_the_panel():
    """The popup has to be able to say *which* one is pinned. "#90" explains
    nothing to someone wondering why the panel disagrees with Home, and the
    number is all the payload carried."""
    state = CompanionState(dex=[graduated()], representative_species_id=2)
    fields = store(state).payload()
    assert fields["representative_species_id"] == 2
    assert "panel_name" in fields


def test_an_unpinned_panel_names_the_companion_it_follows():
    state = CompanionState(active=raising(path=(4, 5, 6), stage=1))
    fields = store(state).payload()
    assert fields["representative_species_id"] is None
    assert fields["panel_species_id"] == 5


def test_an_egg_with_no_pin_names_nothing():
    fields = store(CompanionState()).payload()
    assert fields["panel_species_id"] is None
    assert fields["panel_name"] == ""


def test_pin_messages_are_in_the_users_language():
    state = CompanionState(dex=[graduated()], language="ko")
    subject = store(state)
    from poketokenbar import l10n

    # "#2" is not Hangul, so the particle keeps both forms.
    assert subject.set_representative(2) == l10n.fill("panel_pinned", "ko", "#2")
    assert subject.set_representative(2) == l10n.t("panel_unpinned", "ko")


# MARK: the egg has a picture of its own


class _StubSprites:
    """Enough of SpriteStore to tell which file each surface asked for."""

    def path(self, species_id, animated=True, shiny=False, unown_form=None):
        from pathlib import Path

        letter = f"-{unown_form}" if unown_form and unown_form != "a" else ""
        return Path(f"/cache/{species_id}{letter}.gif")

    def item_path(self, item_name):
        from pathlib import Path

        return Path(f"/cache/item-{item_name}.png")

    def egg_path(self):
        from pathlib import Path

        return Path("/cache/egg.png")


def _egg_store():
    subject = CompanionStore(api=None, sprite_store=_StubSprites())
    subject.state = CompanionState()
    return subject


def test_the_egg_has_a_sprite_on_home():
    """It had none. Home drew an empty box where the picture goes, which reads
    as a UI that has stopped working rather than as an egg warming up."""
    payload = _egg_store().payload()
    assert payload["stage"] == "egg"
    assert payload["sprite_path"] == "/cache/egg.png"


def test_an_unpinned_panel_shows_the_egg_rather_than_nothing():
    """Same gap on the panel and the desktop pet: between a graduation and the
    next hatch the pet simply disappeared."""
    payload = _egg_store().payload()
    assert payload["panel_species_id"] is None
    assert payload["panel_sprite_path"] == "/cache/egg.png"


def test_a_pin_still_wins_over_the_egg_sprite():
    subject = _egg_store()
    subject.state = CompanionState(dex=[graduated()], representative_species_id=3)
    subject.sprites = _StubSprites()
    assert subject.payload()["panel_sprite_path"] == "/cache/3.gif"


def test_the_shop_shows_a_picture_for_its_eggs():
    """Every tier is the same picture; the guarantee is what the badge says."""
    rows = {row["key"]: row for row in _egg_store().shop_payload()}
    for key in ("egg", "egg:uncommon", "egg:rare"):
        assert rows[key]["sprite_path"] == "/cache/egg.png", key


def test_the_eggs_are_listed_but_locked_during_the_egg_stage():
    subject = _egg_store()
    subject.state.used_since_install = 10**12
    rows = {row["key"]: row for row in subject.shop_payload()}
    for key in ("egg", "egg:uncommon", "egg:rare"):
        assert rows[key]["locked"] is True, key
        assert rows[key]["affordable"] is False, key
    # Items are not eggs; a full wallet still buys them.
    assert rows["rareCandy"]["locked"] is False
    assert rows["rareCandy"]["affordable"] is True
