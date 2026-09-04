import json

from poketokenbar import save
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, MonState


def _full_state():
    s = CompanionState()
    s.used_since_install = 1_234
    s.spent_tokens = 100
    s.egg_tier = Rarity.RARE
    s.active = MonState(
        base_id=1, path_ids=[1, 2, 3], planned_path_ids=[1, 2, 3],
        stage_index=1, used_at_stage=50, rarity=Rarity.RARE, total_forms=3,
        is_shiny=True, nature="jolly",
    )
    s.dex = [DexEntry(base_id=4, final_id=6, chain_order=[4, 5, 6], rarity=Rarity.RARE)]
    s.collected_finals = {"4-6"}
    s.inventory = {"rareCandy": 2}
    return s


def test_roundtrip_preserves_everything(tmp_path):
    p = tmp_path / "companion.json"
    save.save(_full_state(), p)
    loaded = save.load(p)
    assert loaded.used_since_install == 1_234
    assert loaded.spent_tokens == 100
    assert loaded.egg_tier == Rarity.RARE
    assert loaded.active.current_id == 2
    assert loaded.active.is_shiny is True
    assert loaded.active.nature == "jolly"
    assert loaded.dex[0].chain_order == [4, 5, 6]
    assert loaded.collected_finals == {"4-6"}
    assert loaded.inventory == {"rareCandy": 2}


def test_missing_file_yields_a_fresh_state(tmp_path):
    assert save.load(tmp_path / "nope.json").used_since_install == 0


def test_write_is_atomic(tmp_path):
    p = tmp_path / "companion.json"
    save.save(_full_state(), p)
    assert list(tmp_path.iterdir()) == [p]


# --- lenient decoding ------------------------------------------------------


def test_unknown_egg_tier_degrades_to_no_guarantee(tmp_path):
    # Never invent a guarantee nobody paid for.
    p = tmp_path / "companion.json"
    p.write_text(json.dumps({"egg_tier": "mythic-plus"}), encoding="utf-8")
    assert save.load(p).egg_tier is None


def test_one_corrupt_dex_entry_does_not_wipe_the_dex(tmp_path):
    p = tmp_path / "companion.json"
    p.write_text(
        json.dumps(
            {
                "dex": [
                    {"base_id": 1, "final_id": 3, "chain_order": [1, 2, 3], "rarity": "rare"},
                    {"base_id": "broken"},
                    {"base_id": 4, "final_id": 6, "chain_order": [4, 5, 6], "rarity": "rare"},
                ]
            }
        ),
        encoding="utf-8",
    )
    dex = save.load(p).dex
    assert [d.final_id for d in dex] == [3, 6]


def test_empty_path_ids_falls_back_to_an_egg_but_keeps_the_dex(tmp_path):
    p = tmp_path / "companion.json"
    p.write_text(
        json.dumps(
            {
                "active": {"base_id": 1, "path_ids": []},
                "dex": [{"base_id": 1, "final_id": 3, "chain_order": [1], "rarity": "common"}],
                "inventory": {"rareCandy": 3},
            }
        ),
        encoding="utf-8",
    )
    loaded = save.load(p)
    assert loaded.active is None
    assert len(loaded.dex) == 1
    assert loaded.inventory == {"rareCandy": 3}


def test_out_of_range_stage_index_is_clamped(tmp_path):
    p = tmp_path / "companion.json"
    p.write_text(
        json.dumps({"active": {"base_id": 1, "path_ids": [1, 2], "stage_index": 99}}),
        encoding="utf-8",
    )
    assert save.load(p).active.stage_index == 1


def test_wrong_typed_field_falls_back_without_losing_the_rest(tmp_path):
    """The neighbouring field is `egg_usage` rather than `spent_tokens`: the
    ledger is reconciled after decoding, so a spend against a total that fell
    back to zero is pulled to zero with it — correctly, and not what this test
    is about."""
    p = tmp_path / "companion.json"
    p.write_text(
        json.dumps({"used_since_install": "lots", "egg_usage": 7}), encoding="utf-8"
    )
    loaded = save.load(p)
    assert loaded.used_since_install == 0
    assert loaded.egg_usage == 7


def test_a_spend_against_a_total_that_fell_back_is_pulled_back_too(tmp_path):
    """Left alone it is a ledger claiming more spent than was ever earned, and
    every figure derived from it afterwards is wrong by the difference."""
    p = tmp_path / "companion.json"
    p.write_text(
        json.dumps({"used_since_install": "lots", "spent_tokens": 7}), encoding="utf-8"
    )
    loaded = save.load(p)
    assert (loaded.used_since_install, loaded.spent_tokens) == (0, 0)


def test_legacy_save_without_per_provider_map_signals_reseed(tmp_path):
    # None means "seed from the next snapshot"; {} means "seeded, nobody
    # reported today". Collapsing them would retroactively grant past usage.
    p = tmp_path / "companion.json"
    p.write_text(json.dumps({"used_since_install": 5}), encoding="utf-8")
    assert save.load(p).claimed_today_tokens_by_provider is None


def test_empty_provider_map_is_preserved_as_distinct(tmp_path):
    p = tmp_path / "companion.json"
    p.write_text(json.dumps({"claimed_today_tokens_by_provider": {}}), encoding="utf-8")
    assert save.load(p).claimed_today_tokens_by_provider == {}


# --- corruption ------------------------------------------------------------


def test_unparseable_save_is_quarantined_not_overwritten(tmp_path):
    p = tmp_path / "companion.json"
    p.write_text("{not json", encoding="utf-8")
    loaded = save.load(p)
    assert loaded.used_since_install == 0
    assert (tmp_path / "companion.json.corrupt").is_file()


def test_non_object_save_is_quarantined(tmp_path):
    p = tmp_path / "companion.json"
    p.write_text("[1,2,3]", encoding="utf-8")
    save.load(p)
    assert (tmp_path / "companion.json.corrupt").is_file()
