import random

from poketokenbar import balance, pokeapi, save
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, EvoLine, apply_usage
from poketokenbar.companion_store import CompanionStore
from poketokenbar.profile import PokemonProfile, STAT_ORDER, computed_stats


DETAILS = {
    "gender_rate": 8,
    "base_stats": {name: 50 for name in STAT_ORDER},
    "abilities": [{"name": "overgrow", "slot": 1, "is_hidden": False}],
    "moves": [
        {"name": "tackle", "learned_at": 1},
        {"name": "growl", "learned_at": 3},
        {"name": "vine-whip", "learned_at": 5},
        {"name": "poison-powder", "learned_at": 7},
        {"name": "razor-leaf", "learned_at": 9},
    ],
}


def test_profile_generation_is_seeded_and_ivs_are_valid():
    first = PokemonProfile.generate(seed=42)
    second = PokemonProfile.generate(seed=42)
    assert first.ivs == second.ivs
    assert all(0 <= value <= 31 for value in first.ivs.values())
    assert first.instance_id != second.instance_id


def test_profile_enrichment_adds_gender_ability_and_latest_four_moves():
    profile = PokemonProfile.generate(seed=5)
    profile.level = 10
    profile.enrich(DETAILS)
    assert profile.gender == "female"
    assert profile.ability_name == "overgrow"
    assert [move["name"] for move in profile.moves] == [
        "growl", "vine-whip", "poison-powder", "razor-leaf"
    ]


def test_stats_include_ivs_level_and_nature():
    profile = PokemonProfile.generate(seed=7)
    profile.level = 50
    neutral = {row["name"]: row["value"] for row in computed_stats(DETAILS, profile, "hardy")}
    adamant = {row["name"]: row["value"] for row in computed_stats(DETAILS, profile, "adamant")}
    assert adamant["attack"] > neutral["attack"]
    assert adamant["special-attack"] < neutral["special-attack"]


def test_profile_survives_save_and_graduation():
    state = CompanionState()
    line = EvoLine(1, [1], Rarity.COMMON)
    apply_usage(state, balance.EGG_HATCH_THRESHOLD, line_for_egg=line,
                rng=random.Random(4))
    instance = state.active.profile.instance_id
    restored = save.decode(save.encode(state))
    assert restored.active.profile.instance_id == instance

    apply_usage(restored, balance.graduation_total(Rarity.COMMON))
    assert restored.dex[0].profile.instance_id == instance
    assert restored.dex[0].profile.level == 100


def test_pokeapi_details_are_normalized_and_cached(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, timeout=15.0):
        calls.append(url)
        return {
            "height": 7, "weight": 69,
            "types": [{"slot": 1, "type": {"name": "grass"}}],
            "stats": [{"base_stat": 45, "stat": {"name": "hp"}}],
            "abilities": [{"slot": 1, "is_hidden": False,
                           "ability": {"name": "overgrow"}}],
            "moves": [{"move": {"name": "tackle"}, "version_group_details": [{
                "level_learned_at": 1,
                "version_group": {"name": "black-2-white-2"},
                "move_learn_method": {"name": "level-up"},
            }]}],
        }

    api = pokeapi.PokeAPI(cache_dir=tmp_path)
    monkeypatch.setattr(pokeapi, "_get_json", fake_get)
    monkeypatch.setattr(api, "species", lambda _sid: {
        "gender_rate": 1,
        "flavor_text_entries": [{"language": {"name": "ko"},
                                 "flavor_text": "씨앗\n포켓몬"}],
    })
    details = api.details(1)
    assert details["moves"] == [{"name": "tackle", "learned_at": 1}]
    assert details["descriptions"]["ko"] == "씨앗 포켓몬"
    assert api.details(1) is details
    assert len(calls) == 1


def test_battle_names_are_localized_in_one_request_and_cached(tmp_path, monkeypatch):
    calls = []

    def fake_post(url, payload, timeout=20.0):
        calls.append((url, payload))
        return {"data": {
            "abilityname": [
                {"name": "심록", "language": {"name": "ko"},
                 "ability": {"name": "overgrow"}},
                {"name": "Overgrow", "language": {"name": "en"},
                 "ability": {"name": "overgrow"}},
            ],
            "movename": [
                {"name": "몸통박치기", "language": {"name": "ko"},
                 "move": {"name": "tackle"}},
                {"name": "Tackle", "language": {"name": "en"},
                 "move": {"name": "tackle"}},
            ],
        }}

    monkeypatch.setattr(pokeapi, "_post_json", fake_post)
    api = pokeapi.PokeAPI(cache_dir=tmp_path)
    ability, moves = api.localized_battle_names("overgrow", ["tackle"], "ko")
    assert ability == "심록"
    assert moves == {"tackle": "몸통박치기"}
    assert len(calls) == 1
    assert "overgrow" in calls[0][1]["query"] and "tackle" in calls[0][1]["query"]

    # A fresh process reads the disk cache and makes no second request.
    cached = pokeapi.PokeAPI(cache_dir=tmp_path)
    ability, moves = cached.localized_battle_names("overgrow", ["tackle"], "ko")
    assert (ability, moves["tackle"]) == ("심록", "몸통박치기")
    assert len(calls) == 1


def test_profile_payload_translates_without_rewriting_the_saved_profile(tmp_path):
    class LocalizedAPI:
        @staticmethod
        def cached_details(_species_id):
            return {"descriptions": {"ko": "씨앗포켓몬"}}

        @staticmethod
        def localized_battle_names(ability, moves, language):
            assert (ability, moves, language) == ("overgrow", ["tackle"], "ko")
            return "심록", {"tackle": "몸통박치기"}

    subject = CompanionStore(
        api=LocalizedAPI(), sprite_store=None, save_path=tmp_path / "save.json")
    subject.state = CompanionState(language="ko")
    profile = PokemonProfile.generate(seed=1)
    profile.ability_name = "overgrow"
    profile.moves = [{"name": "tackle", "learned_at": 1}]

    payload = subject._profile_payload(profile, 1, "hardy")
    assert payload["ability"] == "심록"
    assert payload["moves"][0]["display_name"] == "몸통박치기"
    assert profile.ability_name == "overgrow"
    assert profile.moves[0]["name"] == "tackle"
