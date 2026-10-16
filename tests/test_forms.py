"""An individual's appearance — ports UnownTests.swift and PokemonFormTests.swift
(upstream 10d1a07, generalised in 04b12da).

The rules that matter: the form belongs to the individual, it is drawn only
after the species roll, it favours the forms not yet collected, it is resolved
per species of the line, and it survives everything that happens to the
Pokemon afterwards.
"""

import random
from collections import Counter

import pytest

from poketokenbar import balance, companion, forms, save, sprites
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, EvoLine, MonState, apply_usage
from poketokenbar.companion_store import CompanionStore


UNOWN_FORMS = tuple(forms.forms(201))


def _unown_line():
    return EvoLine(base_id=201, path_ids=[201], rarity=Rarity.RARE)


def _hatched_unown(seed=0):
    state = CompanionState()
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=_unown_line(),
                rng=random.Random(seed))
    return state


# --- the letters themselves -------------------------------------------------


def test_there_are_twenty_eight_letters():
    assert len(UNOWN_FORMS) == 28
    assert UNOWN_FORMS[0] == "a" and UNOWN_FORMS[-2:] == ("exclamation", "question")
    assert len(set(UNOWN_FORMS)) == 28


@pytest.mark.parametrize("form,expected", [
    ("a", "A"), ("z", "Z"), ("exclamation", "!"), ("question", "?"),
])
def test_a_letter_is_written_as_itself(form, expected):
    assert forms.symbol(form) == expected


def test_the_name_carries_the_letter_only_for_unown():
    assert forms.display_name("안농", 201, "b") == "안농 [B]"
    assert forms.display_name("Unown", 201, "question") == "Unown [?]"
    # A letter stored against another species is not drawn.
    assert forms.display_name("Pikachu", 25, "b") == "Pikachu"


def test_an_unown_with_no_letter_recorded_is_the_one_it_was_already_drawn_as():
    """Saves from before letters existed showed the default A sprite, and that
    is what they have to keep showing."""
    assert forms.resolved(201, None) == "a"
    assert forms.resolved(201, "nonsense") == "a"
    assert forms.resolved(25, "b") is None


# --- drawing one ------------------------------------------------------------


def test_an_uncollected_letter_is_twice_as_likely_as_a_collected_one():
    drawn = Counter(forms.roll(random.Random(seed), UNOWN_FORMS, collected={"a"}) for seed in range(6000))
    assert drawn["a"] > 0, "a collected letter is still reachable"
    # Every other letter weighs 2 against a's 1, within sampling noise.
    others = sum(count for form, count in drawn.items() if form != "a") / 27
    assert 1.6 < others / drawn["a"] < 2.5


def test_once_every_letter_is_collected_the_draw_is_even_again():
    weights = {forms.collection_weight(form, set(UNOWN_FORMS)) for form in UNOWN_FORMS}
    assert weights == {1}


def test_every_letter_stays_reachable():
    assert all(forms.collection_weight(form, set(UNOWN_FORMS)) >= 1 for form in UNOWN_FORMS)


# --- hatching ---------------------------------------------------------------


def test_hatching_an_unown_draws_a_letter():
    state = _hatched_unown()
    assert state.active.base_id == 201
    assert state.active.form in UNOWN_FORMS


def test_hatching_anything_else_draws_none():
    state = CompanionState()
    apply_usage(state, balance.EGG_HATCH_THRESHOLD,
                line_for_egg=EvoLine(base_id=1, path_ids=[1, 2, 3], rarity=Rarity.COMMON),
                rng=random.Random(0))
    assert state.active.form is None


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
    state.active.form = "q"
    apply_usage(state, balance.graduation_total(Rarity.RARE))
    assert state.dex and state.dex[0].form == "q"


def test_the_letter_follows_a_release():
    state = _hatched_unown()
    state.active.form = "m"
    companion.release(state, state.active)
    assert state.dex[-1].form == "m"


def test_the_letter_survives_a_save(tmp_path):
    state = _hatched_unown()
    state.active.form = "exclamation"
    path = tmp_path / "companion.json"
    save.save(state, path)
    assert save.load(path).active.form == "exclamation"


def test_a_letter_on_another_species_is_dropped_when_read(tmp_path):
    """An imported or hand-edited save is where one appears, and it means
    nothing on anything but Unown."""
    state = CompanionState(active=MonState(
        base_id=25, path_ids=[25], planned_path_ids=[25], rarity=Rarity.COMMON, total_forms=1))
    state.active.form = "b"
    path = tmp_path / "companion.json"
    save.save(state, path)
    assert save.load(path).active.form is None


# --- collecting them --------------------------------------------------------


def _with_letters(*letters):
    state = CompanionState()
    state.dex = [
        DexEntry(base_id=201, final_id=201, chain_order=[201], rarity=Rarity.RARE,
                 form=letter)
        for letter in letters
    ]
    return state


def test_the_tally_counts_letters_not_catches():
    state = _with_letters("a", "b", "b")
    assert state.collected_forms(201) == {"a", "b"}


def test_a_shiny_and_a_normal_of_one_letter_are_one_letter():
    state = _with_letters("c")
    state.dex.append(DexEntry(base_id=201, final_id=201, chain_order=[201],
                              rarity=Rarity.RARE, is_shiny=True, form="c"))
    assert state.collected_forms(201) == {"c"}


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
    def path(self, species_id, animated=True, shiny=False, form=None):
        letter = f"-{form}" if form and not forms.is_default(species_id, form) else ""
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
    rows = page["forms"]
    assert len(rows) == 28
    assert [f["form"] for f in rows if f["collected"]] == ["b"]
    assert [f["form"] for f in rows if f["selected"]] == ["b"]
    assert page["name"].endswith("[B]")


def test_a_page_opens_on_a_letter_that_is_collected():
    """Opening on an empty letter would be a page of nothing."""
    store = _store(_with_letters("z"))
    store.inspect(201, form="c")
    assert store.inspected_form == "z"


def test_a_page_lists_only_the_letter_it_is_about():
    state = _with_letters("b", "c")
    for entry, letter in zip(state.dex, ("b", "c")):
        entry.profile = __import__("poketokenbar.profile", fromlist=["x"]).generate(
            ord(letter))
    store = _store(state)
    store.inspect(201, form="c")
    assert [e.form for e, _p, _s in store.individuals(201, "c")] == ["c"]


def test_the_pin_keeps_its_letter():
    store = _store(_with_letters("b", "d"))
    store.set_representative(201, "d")
    assert store.state.representative_form == "d"
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
    assert store.state.representative_form is None


# --- every other species with more than one appearance (upstream 04b12da) ---


def test_the_catalogue_is_the_species_whose_forms_all_have_a_gen_v_sprite():
    assert forms.has_forms(351) and forms.has_forms(493) and forms.has_forms(649)
    # Gender differences are not forms, and neither is a species with one look.
    assert not forms.has_forms(25) and not forms.has_forms(1)
    # Every form is listed once, and the default leads.
    for species_id, rows in forms.CATALOG.items():
        names = [entry.form for entry in rows]
        assert len(names) == len(set(names)), species_id
        assert names[0] == forms.resolved(species_id, None), species_id


def test_the_form_is_resolved_against_the_species_it_is_drawn_at():
    """A Sandy Burmy becomes a Sandy Wormadam; the Mothim branch has one look."""
    assert forms.resolved(412, "sandy") == "sandy"
    assert forms.resolved(413, "sandy") == "sandy"
    assert forms.resolved(414, "sandy") is None
    # A form the species cannot wear falls back to its default rather than
    # drawing something that does not exist.
    assert forms.resolved(412, "sky") == "plant"


def test_a_line_carries_every_form_any_of_its_species_shows():
    assert forms.line_forms(412) == ["plant", "sandy", "trash"]
    # Cherrim's line starts at Cherubi, which has no forms of its own.
    assert forms.form_species(420) == [421]
    assert forms.line_forms(420) == ["overcast", "sunshine"]
    assert forms.line_forms(25) == []


def test_a_default_appearance_keeps_the_plain_sprite_names():
    assert sprites.cache_key(412, True, False, "plant") == sprites.cache_key(412, True, False)
    assert sprites.sprite_url(492, True, False, "land").endswith("/492.gif")


def test_a_form_that_is_its_own_pokeapi_variety_uses_that_still_picture():
    """Sky Shaymin's animation is `492-sky.gif`, but its PNG is `10006.png`."""
    assert sprites.sprite_url(492, True, False, "sky").endswith("/492-sky.gif")
    assert sprites.sprite_url(492, False, False, "sky").endswith("/10006.png")
    # Burmy's cloaks are named like the animation in both.
    assert sprites.sprite_url(412, False, False, "sandy").endswith("/412-sandy.png")


def test_hatching_a_burmy_decides_which_wormadam_it_will_become():
    state = CompanionState()
    apply_usage(state, balance.EGG_HATCH_THRESHOLD,
                line_for_egg=EvoLine(base_id=412, path_ids=[412, 413], rarity=Rarity.COMMON),
                rng=random.Random(3))
    assert state.active.form in forms.line_forms(412)


def test_a_form_counts_as_collected_only_once_every_species_wears_it():
    """A Sandy Burmy that became Mothim still leaves Sandy Wormadam to find."""
    state = CompanionState(dex=[DexEntry(base_id=412, final_id=414,
                                         chain_order=[412, 414],
                                         rarity=Rarity.COMMON, form="sandy")])
    assert state.collected_forms(412) == {"sandy"}
    assert state.collected_forms(413) == set()
    assert "sandy" not in state.collected_line_forms(412)

    state.dex.append(DexEntry(base_id=412, final_id=413, chain_order=[412, 413],
                              rarity=Rarity.COMMON, form="sandy"))
    assert state.collected_line_forms(412) == {"sandy"}


def test_a_named_form_is_written_beside_the_species_name():
    assert forms.display_name("Shaymin", 492, "sky", "Sky Forme") == "Shaymin [Sky Forme]"
    # The usual look is just the species' name.
    assert forms.display_name("Shaymin", 492, "land", "Land Forme") == "Shaymin"
    # Unown always names its letter, default included.
    assert forms.display_name("Unown", 201, "a", None) == "Unown [A]"


def test_the_page_lists_a_species_formes_with_what_is_missing():
    state = CompanionState(dex=[DexEntry(base_id=492, final_id=492, chain_order=[492],
                                         rarity=Rarity.LEGENDARY, form="sky")])
    store = _store(state)
    store.inspect(492)
    page = store.detail_payload()
    assert [row["form"] for row in page["forms"]] == ["land", "sky"]
    assert [row["collected"] for row in page["forms"]] == [False, True]
    assert page["form"] == "sky"
    cell = [row for row in store.dex_payload() if row["species_id"] == 492][0]
    assert cell["form_count_text"] == "1/2"


def test_a_species_with_one_appearance_has_no_picker_and_no_tally():
    state = CompanionState(dex=[DexEntry(base_id=25, final_id=25, chain_order=[25],
                                         rarity=Rarity.COMMON)])
    store = _store(state)
    store.inspect(25)
    page = store.detail_payload()
    assert page["forms"] == [] and page["forms_text"] == "" and page["form"] == ""
    assert [row for row in store.dex_payload()
            if row["species_id"] == 25][0]["form_count_text"] == ""


def test_an_older_save_keeps_reading_its_unown_key(tmp_path):
    raw = {"active": {"base_id": 201, "path_ids": [201], "planned_path_ids": [201],
                      "total_forms": 1, "unown_form": "q"},
           "representative_species_id": 201, "representative_unown_form": "q"}
    path = tmp_path / "companion.json"
    path.write_text(__import__("json").dumps(raw), encoding="utf-8")
    state = save.load(path)
    assert state.active.form == "q"
    assert state.representative_form == "q"


def test_home_draws_the_companion_in_its_own_appearance():
    """The line, the sprite and the name all follow the individual's form, not
    the species' default."""
    state = CompanionState(active=MonState(
        base_id=412, path_ids=[412, 413], planned_path_ids=[412, 413],
        total_forms=2, rarity=Rarity.COMMON, form="trash"))
    store = _store(state)
    payload = store.payload()
    assert store.sprite_path().endswith("412-trash.png")
    assert [stage["sprite_path"] for stage in payload["evo_line"]] == [
        "/cache/412-trash.png", "/cache/413-trash.png"]
    # The companion's name carries the form once PokeAPI has named it; with no
    # name store here it falls back to the readable identifier.
    assert "Trash" in payload["name"]


def test_a_species_without_that_form_keeps_its_own_sprite():
    state = CompanionState(active=MonState(
        base_id=412, path_ids=[412, 414], planned_path_ids=[412, 414],
        total_forms=2, rarity=Rarity.COMMON, form="sandy"))
    store = _store(state)
    assert [stage["sprite_path"] for stage in store.payload()["evo_line"]] == [
        "/cache/412-sandy.png", "/cache/414.png"]
