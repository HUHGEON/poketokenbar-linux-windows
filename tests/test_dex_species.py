"""The Pokedex is species-level, the catch log is individual-level.

Conflating them is what hid the active companion from the dex entirely.
"""

import random

from poketokenbar import balance
from poketokenbar.balance import Rarity
from poketokenbar.companion import DexEntry, EvoLine, apply_usage
from poketokenbar.companion_store import CompanionStore


class FakeAPI:
    def __init__(self, forms=3, rarity=Rarity.COMMON):
        self.forms, self.rarity = forms, rarity

    def roll_base_species(self, rng, tier=None):
        return 1

    def line(self, base_id):
        return EvoLine(base_id=1, path_ids=list(range(1, self.forms + 1)), rarity=self.rarity)

    def species(self, species_id):
        return {"names": [{"language": {"name": "en"}, "name": f"Mon{species_id}"}]}


def _store(tmp_path, forms=3):
    s = CompanionStore(
        save_path=tmp_path / "c.json", api=FakeAPI(forms=forms), rng=random.Random(2)
    )
    s.update({}, today="2026-08-19")
    return s


def test_active_companion_appears_in_the_dex(tmp_path):
    # The bug: a hatched companion was invisible until it graduated.
    s = _store(tmp_path)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD}, today="2026-08-19")
    ids = [row["species_id"] for row in s.dex_payload()]
    assert ids == [1]


def test_active_entry_is_flagged_as_still_raising(tmp_path):
    s = _store(tmp_path)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD}, today="2026-08-19")
    assert s.dex_payload()[0]["is_raising"] is True


def test_only_reached_forms_count_not_the_planned_path(tmp_path):
    # planned_path_ids holds stages not yet evolved into; listing them would
    # claim species that have never been owned.
    s = _store(tmp_path, forms=3)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD}, today="2026-08-19")
    assert [r["species_id"] for r in s.dex_payload()] == [1]

    apply_usage(s.state, balance.phase_threshold(Rarity.COMMON, 3, 0))
    assert [r["species_id"] for r in s.dex_payload()] == [1, 2]


def test_graduated_chain_contributes_every_species(tmp_path):
    s = _store(tmp_path)
    s.state.dex = [
        DexEntry(base_id=41, final_id=169, chain_order=[41, 42, 169], rarity=Rarity.COMMON)
    ]
    assert [r["species_id"] for r in s.dex_payload()] == [41, 42, 169]


def test_species_are_sorted_by_dex_number(tmp_path):
    s = _store(tmp_path)
    s.state.dex = [
        DexEntry(base_id=333, final_id=334, chain_order=[333, 334], rarity=Rarity.COMMON),
        DexEntry(base_id=41, final_id=42, chain_order=[41, 42], rarity=Rarity.COMMON),
    ]
    assert [r["species_id"] for r in s.dex_payload()] == [41, 42, 333, 334]


def test_a_species_seen_twice_collapses_to_one_entry(tmp_path):
    s = _store(tmp_path)
    s.state.dex = [
        DexEntry(base_id=41, final_id=42, chain_order=[41, 42], rarity=Rarity.COMMON),
        DexEntry(base_id=41, final_id=42, chain_order=[41, 42], rarity=Rarity.COMMON),
    ]
    assert [r["species_id"] for r in s.dex_payload()] == [41, 42]


def test_only_the_current_form_is_marked_raising(tmp_path):
    # Ports upstream 79ba760: an outgrown form is still owned, but badging it
    # read as raising two Pokemon at once.
    s = _store(tmp_path, forms=3)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD}, today="2026-08-19")
    apply_usage(s.state, balance.phase_threshold(Rarity.COMMON, 3, 0))
    rows = s.dex_payload()
    assert [r["species_id"] for r in rows] == [1, 2]
    assert [r["is_raising"] for r in rows] == [False, True]


def test_a_graduated_line_raised_again_badges_its_current_form(tmp_path):
    # The badge means "the one you are raising", not "not yet permanent", so a
    # graduation record for the same species does not hide it.
    s = _store(tmp_path, forms=3)
    s.update({"claude_code": balance.EGG_HATCH_THRESHOLD}, today="2026-08-19")
    apply_usage(s.state, balance.phase_threshold(Rarity.COMMON, 3, 0))
    s.state.dex = [
        DexEntry(base_id=1, final_id=3, chain_order=[1, 2, 3], rarity=Rarity.COMMON)
    ]
    assert [r["is_raising"] for r in s.dex_payload()] == [False, True, False]


def test_graduated_species_is_not_marked_raising(tmp_path):
    s = _store(tmp_path)
    s.state.dex = [
        DexEntry(base_id=41, final_id=42, chain_order=[41, 42], rarity=Rarity.COMMON)
    ]
    assert all(not r["is_raising"] for r in s.dex_payload())


def test_species_count_exceeds_catch_count(tmp_path):
    # 2 catches of 3-form lines = 6 species. This ratio is exactly what the
    # macOS screenshot shows (14 catches, 28 species).
    s = _store(tmp_path)
    s.state.dex = [
        DexEntry(base_id=1, final_id=3, chain_order=[1, 2, 3], rarity=Rarity.COMMON),
        DexEntry(base_id=4, final_id=6, chain_order=[4, 5, 6], rarity=Rarity.COMMON),
    ]
    assert len(s.dex_payload()) == 6
    assert sum(s.catch_rarity_counts().values()) == 2


def test_dex_and_catch_counts_are_tallied_separately(tmp_path):
    s = _store(tmp_path)
    s.state.dex = [
        DexEntry(base_id=1, final_id=3, chain_order=[1, 2, 3], rarity=Rarity.UNCOMMON)
    ]
    assert s.rarity_counts()["uncommon"] == 3      # species
    assert s.catch_rarity_counts()["uncommon"] == 1  # individuals


def test_a_species_caught_both_ways_owns_both_appearances(tmp_path):
    """A shiny catch used to be all a species had: the ordinary one you also
    caught had nowhere to be seen (upstream 4bfae97)."""
    s = _store(tmp_path)
    s.state.active = None
    s.state.dex = [
        DexEntry(base_id=41, final_id=42, chain_order=[41, 42], rarity=Rarity.COMMON),
        DexEntry(base_id=41, final_id=42, chain_order=[41, 42], rarity=Rarity.COMMON,
                 is_shiny=True),
    ]
    row = next(r for r in s.dex_payload() if r["species_id"] == 42)
    assert row["is_shiny"] and row["has_normal"]


def test_a_species_caught_only_one_way_says_so(tmp_path):
    s = _store(tmp_path)
    s.state.active = None
    s.state.dex = [
        DexEntry(base_id=41, final_id=42, chain_order=[41, 42], rarity=Rarity.COMMON,
                 is_shiny=True),
    ]
    row = next(r for r in s.dex_payload() if r["species_id"] == 42)
    assert row["is_shiny"] and not row["has_normal"]


# MARK: how much of each generation is collected (upstream a49237c)


def test_a_species_is_placed_by_its_dex_number_alone():
    from poketokenbar import regions

    assert regions.region_of(1) == "kanto"
    assert regions.region_of(151) == "kanto"
    assert regions.region_of(152) == "johto"
    assert regions.region_of(649) == "unova"
    # Generation 6 onwards cannot hatch here — no Black/White animation.
    assert regions.region_of(650) is None
    assert sum(regions.total_of(name) for name, _f, _l in regions.REGIONS) == 649


def test_a_region_counts_each_species_once_and_in_shiny_if_any_was():
    from poketokenbar import regions

    owned = {1: False, 2: True, 200: False}
    found = {c.region: c for c in regions.completions(owned)}
    assert (found["kanto"].owned, found["kanto"].shiny_owned) == (2, 1)
    assert (found["johto"].owned, found["johto"].shiny_owned) == (1, 0)
    assert found["kanto"].total == 151 and not found["kanto"].complete


def test_finishing_a_region_earns_its_badge_and_the_shiny_one_separately():
    from poketokenbar import regions

    plain = {i: False for i in range(1, 152)}
    assert regions.badges(plain, unown_forms=0) == ["region.kanto"]

    shiny = {i: True for i in range(1, 152)}
    assert regions.badges(shiny, unown_forms=0) == ["region.kanto", "regionShiny.kanto"]

    # All 28 letters is its own badge, and the National Dex is two more.
    every = {i: True for i in range(1, 650)}
    assert regions.badges(every, unown_forms=28) == [
        *(f"{kind}.{name}" for name, _f, _l in regions.REGIONS
          for kind in ("region", "regionShiny")),
        "unown", "national", "nationalShiny",
    ]


def test_the_store_reports_progress_from_the_grid_it_shows(tmp_path):
    from poketokenbar.balance import Rarity
    from poketokenbar.companion import CompanionState, DexEntry
    from poketokenbar.companion_store import CompanionStore

    store = CompanionStore(save_path=tmp_path / "companion.json", api=None,
                           sprite_store=None)
    store.state = CompanionState(dex=[
        DexEntry(base_id=1, final_id=3, chain_order=[1, 2, 3], rarity=Rarity.COMMON),
        DexEntry(base_id=152, final_id=152, chain_order=[152], rarity=Rarity.RARE,
                 is_shiny=True),
    ])
    progress = store.dex_progress()
    by_region = {row["region"]: row for row in progress["regions"]}
    assert by_region["kanto"]["text"] == "3/151"
    assert by_region["johto"]["owned"] == 1 and by_region["johto"]["shiny_owned"] == 1
    assert progress["national"]["text"] == "4/649"
    assert progress["badges"] == []
