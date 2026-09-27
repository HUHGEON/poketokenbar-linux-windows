"""Unown's 28 letters — ports UnownTests.swift (upstream 10d1a07).

The rules that matter: the letter is an attribute of the individual, it is
drawn only after the species roll, it favours letters not yet collected, and it
survives everything that happens to the Pokémon afterwards.
"""

import random
from collections import Counter

import pytest

from poketokenbar import balance, companion, save, sprites, unown
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, EvoLine, MonState, apply_usage
from poketokenbar.companion_store import CompanionStore


def _unown_line():
    return EvoLine(base_id=201, path_ids=[201], rarity=Rarity.RARE)


def _hatched_unown(seed=0):
    state = CompanionState()
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=_unown_line(),
                rng=random.Random(seed))
    return state


# --- the letters themselves -------------------------------------------------


def test_there_are_twenty_eight_letters():
    assert len(unown.FORMS) == 28
    assert unown.FORMS[0] == "a" and unown.FORMS[-2:] == ("exclamation", "question")
    assert len(set(unown.FORMS)) == 28


@pytest.mark.parametrize("form,expected", [
    ("a", "A"), ("z", "Z"), ("exclamation", "!"), ("question", "?"),
])
def test_a_letter_is_written_as_itself(form, expected):
    assert unown.symbol(form) == expected


def test_the_name_carries_the_letter_only_for_unown():
    assert unown.display_name("안농", 201, "b") == "안농 [B]"
    assert unown.display_name("Unown", 201, "question") == "Unown [?]"
    # A letter stored against another species is not drawn.
    assert unown.display_name("Pikachu", 25, "b") == "Pikachu"


def test_an_unown_with_no_letter_recorded_is_the_one_it_was_already_drawn_as():
    """Saves from before letters existed showed the default A sprite, and that
    is what they have to keep showing."""
    assert unown.resolved(201, None) == "a"
    assert unown.resolved(201, "nonsense") == "a"
    assert unown.resolved(25, "b") is None


# --- drawing one ------------------------------------------------------------


def test_an_uncollected_letter_is_twice_as_likely_as_a_collected_one():
    drawn = Counter(unown.roll(random.Random(seed), collected={"a"}) for seed in range(6000))
    assert drawn["a"] > 0, "a collected letter is still reachable"
    # Every other letter weighs 2 against a's 1, within sampling noise.
    others = sum(count for form, count in drawn.items() if form != "a") / 27
    assert 1.6 < others / drawn["a"] < 2.5


def test_once_every_letter_is_collected_the_draw_is_even_again():
    weights = {unown.collection_weight(form, set(unown.FORMS)) for form in unown.FORMS}
    assert weights == {1}


def test_every_letter_stays_reachable():
    assert all(unown.collection_weight(form, set(unown.FORMS)) >= 1 for form in unown.FORMS)


# --- hatching ---------------------------------------------------------------


def test_hatching_an_unown_draws_a_letter():
    state = _hatched_unown()
    assert state.active.base_id == 201
    assert state.active.unown_form in unown.FORMS


def test_hatching_anything_else_draws_none():
    state = CompanionState()
    apply_usage(state, balance.EGG_HATCH_THRESHOLD,
                line_for_egg=EvoLine(base_id=1, path_ids=[1, 2, 3], rarity=Rarity.COMMON),
                rng=random.Random(0))
    assert state.active.unown_form is None


def test_the_letter_draw_leaves_every_other_roll_where_it_was():
    """It runs after the species is known, so nothing else in the sequence can
    move — a shiny that used to hatch still hatches."""
    def hatch(line):
        state = CompanionState()
        apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=line, rng=random.Random(7))
        return state.active

    # Against a line of the same shape: choosing a branch draws from the rng
    # too, so a three-form line would differ for that reason alone.
    ordinary = hatch(EvoLine(base_id=132, path_ids=[132], rarity=Rarity.RARE))
    letters = hatch(_unown_line())
    assert ordinary.is_shiny == letters.is_shiny
    assert ordinary.nature == letters.nature


# --- keeping it -------------------------------------------------------------


def test_the_letter_follows_a_graduation_into_the_pokedex():
    state = _hatched_unown()
    state.active.unown_form = "q"
    apply_usage(state, balance.graduation_total(Rarity.RARE))
    assert state.dex and state.dex[0].unown_form == "q"


def test_the_letter_follows_a_release():
    state = _hatched_unown()
    state.active.unown_form = "m"
    companion.release(state, state.active)
    assert state.dex[-1].unown_form == "m"


def test_the_letter_survives_a_save(tmp_path):
    state = _hatched_unown()
    state.active.unown_form = "exclamation"
    path = tmp_path / "companion.json"
    save.save(state, path)
    assert save.load(path).active.unown_form == "exclamation"


def test_a_letter_on_another_species_is_dropped_when_read(tmp_path):
    """An imported or hand-edited save is where one appears, and it means
    nothing on anything but Unown."""
    state = CompanionState(active=MonState(
        base_id=25, path_ids=[25], planned_path_ids=[25], rarity=Rarity.COMMON, total_forms=1))
    state.active.unown_form = "b"
    path = tmp_path / "companion.json"
    save.save(state, path)
    assert save.load(path).active.unown_form is None


# --- collecting them --------------------------------------------------------


def _with_letters(*letters):
    state = CompanionState()
    state.dex = [
        DexEntry(base_id=201, final_id=201, chain_order=[201], rarity=Rarity.RARE,
                 unown_form=letter)
        for letter in letters
    ]
    return state


def test_the_tally_counts_letters_not_catches():
    state = _with_letters("a", "b", "b")
    assert state.collected_unown_forms() == {"a", "b"}


def test_a_shiny_and_a_normal_of_one_letter_are_one_letter():
    state = _with_letters("c")
    state.dex.append(DexEntry(base_id=201, final_id=201, chain_order=[201],
                              rarity=Rarity.RARE, is_shiny=True, unown_form="c"))
    assert state.collected_unown_forms() == {"c"}


def test_owning_unown_is_asked_per_letter():
    state = _with_letters("b")
    assert state.owns_species(201) and state.owns_species(201, "b")
    assert not state.owns_species(201, "c")


# --- the sprites ------------------------------------------------------------


def test_a_uses_the_files_every_older_save_already_cached():
    assert sprites.cache_key(201, True, False, "a") == sprites.cache_key(201, True, False)
    assert sprites.sprite_url(201, False, False, "a").endswith("/201.png")


def test_each_other_letter_has_its_own_file():
    assert sprites.sprite_url(201, False, False, "b").endswith("/201-b.png")
    assert sprites.sprite_url(201, True, True, "question").endswith("/shiny/201-question.gif")
    assert sprites.cache_key(201, False, True, "question") == "201-question-shs"


def test_another_species_ignores_the_letter():
    assert sprites.sprite_url(25, False, False, "b").endswith("/25.png")


# --- the popup's side -------------------------------------------------------


class _Sprites:
    def path(self, species_id, animated=True, shiny=False, unown_form=None):
        letter = f"-{unown_form}" if unown_form and unown_form != "a" else ""
        return f"/cache/{species_id}{letter}.png"

    def item_path(self, name):
        return ""


def _store(state):
    store = CompanionStore(api=None, sprite_store=_Sprites())
    store.state = state
    return store


def test_the_grid_shows_one_unown_cell_with_its_tally():
    store = _store(_with_letters("a", "b", "c"))
    rows = [row for row in store.dex_payload() if row["species_id"] == 201]
    assert len(rows) == 1
    assert "3" in rows[0]["form_count_text"] and "28" in rows[0]["form_count_text"]


def test_the_page_lists_all_twenty_eight_and_marks_what_is_missing():
    store = _store(_with_letters("b"))
    store.inspect(201)
    page = store.detail_payload()
    forms = page["unown_forms"]
    assert len(forms) == 28
    assert [f["form"] for f in forms if f["collected"]] == ["b"]
    assert [f["form"] for f in forms if f["selected"]] == ["b"]
    assert page["name"].endswith("[B]")


def test_a_page_opens_on_a_letter_that_is_collected():
    """Opening on an empty letter would be a page of nothing."""
    store = _store(_with_letters("z"))
    store.inspect(201, unown_form="c")
    assert store.inspected_unown_form == "z"


def test_a_page_lists_only_the_letter_it_is_about():
    state = _with_letters("b", "c")
    for entry, letter in zip(state.dex, ("b", "c")):
        entry.profile = __import__("poketokenbar.profile", fromlist=["x"]).generate(
            ord(letter))
    store = _store(state)
    store.inspect(201, unown_form="c")
    assert [e.unown_form for e, _p, _s in store.individuals(201, "c")] == ["c"]


def test_the_pin_keeps_its_letter():
    store = _store(_with_letters("b", "d"))
    store.set_representative(201, "d")
    assert store.state.representative_unown_form == "d"
    assert store.panel_individual()[2] == "d"
    assert store.panel_sprite_path().endswith("201-d.png")
    assert "[D]" in store._panel_fields()["panel_name"]


def test_pinning_a_letter_nobody_has_is_refused():
    store = _store(_with_letters("b"))
    with pytest.raises(ValueError):
        store.set_representative(201, "d")


def test_tapping_the_pinned_letter_again_releases_it():
    store = _store(_with_letters("b"))
    store.set_representative(201, "b")
    store.set_representative(201, "b")
    assert store.state.representative_species_id is None
    assert store.state.representative_unown_form is None
