"""Species details and localized names from PokéAPI, fetched off the daemon's
thread and applied to profiles on it (upstream b6bf676, 2fab082)."""

import json

import pytest

from poketokenbar import pokeapi, profile as P, save
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, MonState
from poketokenbar.companion_store import CompanionStore
from poketokenbar.detail_loader import DetailLoader

RAW_POKEMON = {
    "name": "slowpoke",
    "height": 12,
    "weight": 360,
    "base_experience": 63,
    "types": [{"slot": 2, "type": {"name": "psychic"}}, {"slot": 1, "type": {"name": "water"}}],
    "stats": [{"base_stat": 90, "stat": {"name": "hp"}}, {"base_stat": 15, "stat": {"name": "speed"}}],
    "abilities": [
        {"is_hidden": True, "slot": 3, "ability": {"name": "regenerator"}},
        {"is_hidden": False, "slot": 1, "ability": {"name": "oblivious"}},
    ],
    "moves": [
        {"move": {"name": "tackle"}, "version_group_details": [
            {"level_learned_at": 1, "move_learn_method": {"name": "level-up"},
             "version_group": {"name": "black-2-white-2"}},
            {"level_learned_at": 3, "move_learn_method": {"name": "level-up"},
             "version_group": {"name": "sword-shield"}},
        ]},
        {"move": {"name": "future-sight"}, "version_group_details": [
            {"level_learned_at": 1, "move_learn_method": {"name": "level-up"},
             "version_group": {"name": "scarlet-violet"}},
        ]},
    ],
}


class Clock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def network(monkeypatch):
    """Answers PokéAPI URLs from a dict and records every request."""
    calls = []
    responses = {}

    def fake_get(url, timeout=15.0):
        calls.append(url)
        if url not in responses:
            raise pokeapi.PokeAPIError(f"offline: {url}")
        return json.loads(json.dumps(responses[url]))

    monkeypatch.setattr(pokeapi, "_get_json", fake_get)
    return responses, calls


def _api(tmp_path, network, clock=None):
    responses, _ = network
    responses[f"{pokeapi.REST_BASE}/pokemon/79"] = RAW_POKEMON
    responses[f"{pokeapi.REST_BASE}/pokemon-species/79"] = {"gender_rate": 4, "names": []}
    return pokeapi.PokeAPI(cache_dir=tmp_path / "cache", clock=clock or Clock())


# MARK: parsing


def test_details_keep_only_the_supported_version_group_before_caching():
    details = pokeapi.parse_details(79, RAW_POKEMON, 4)
    assert details.types == ["water", "psychic"]
    assert [a.name for a in details.abilities] == ["oblivious", "regenerator"]
    assert [m.name for m in details.moves] == ["tackle"]
    assert details.moves[0].learn_methods == [P.LearnMethod("level-up", 1)]
    assert details.gender_rate == 4
    assert details.base_stat_total == 105


# MARK: caching


def test_details_are_cached_for_30_days_then_refreshed(tmp_path, network):
    _, calls = network
    clock = Clock()
    api = _api(tmp_path, network, clock)
    assert api.details(79).name == "slowpoke"
    requests = len(calls)

    fresh = pokeapi.PokeAPI(cache_dir=tmp_path / "cache", clock=clock)
    fresh.details(79)
    assert len(calls) == requests, "a fresh disk copy answers without a request"

    clock.now += pokeapi.DETAIL_TTL_SECONDS + 1
    pokeapi.PokeAPI(cache_dir=tmp_path / "cache", clock=clock).details(79)
    assert len(calls) > requests


def test_a_stale_copy_answers_when_the_network_is_gone(tmp_path, network):
    responses, _ = network
    clock = Clock()
    _api(tmp_path, network, clock).details(79)
    responses.clear()
    clock.now += pokeapi.DETAIL_TTL_SECONDS * 3
    offline = pokeapi.PokeAPI(cache_dir=tmp_path / "cache", clock=clock)
    assert offline.details(79).name == "slowpoke"


def test_cached_details_never_make_a_request(tmp_path, network):
    _, calls = network
    api = pokeapi.PokeAPI(cache_dir=tmp_path / "cache")
    assert api.cached_details(79) is None
    assert calls == []


def test_resource_names_are_cached_and_resolved(tmp_path, network):
    responses, calls = network
    responses[f"{pokeapi.REST_BASE}/move/water-gun/"] = {"names": [
        {"language": {"name": "ko"}, "name": "물대포"},
        {"language": {"name": "en"}, "name": "Water Gun"},
    ]}
    api = pokeapi.PokeAPI(cache_dir=tmp_path / "cache", clock=Clock())
    assert api.cached_resource_names("move", "water-gun") is None
    assert api.resource_names("move", "water-gun")["ko"] == "물대포"
    again = pokeapi.PokeAPI(cache_dir=tmp_path / "cache", clock=Clock())
    assert again.cached_resource_names("move", "water-gun") == {"ko": "물대포", "en": "Water Gun"}
    assert len(calls) == 1


@pytest.mark.parametrize("kind,name", [
    ("move", "../../etc/passwd"), ("move", "Water Gun"), ("species", "pikachu"), ("type", ""),
])
def test_unsafe_resource_names_are_refused_before_any_request(tmp_path, network, kind, name):
    _, calls = network
    api = pokeapi.PokeAPI(cache_dir=tmp_path / "cache")
    with pytest.raises(pokeapi.PokeAPIError):
        api.resource_names(kind, name)
    assert api.cached_resource_names(kind, name) is None
    assert calls == []


# MARK: the loader


def test_the_loader_remembers_failures_so_offline_is_not_a_loop(tmp_path, network):
    _, calls = network
    loader = DetailLoader(pokeapi.PokeAPI(cache_dir=tmp_path / "cache"), start=False)
    loader.request_details(79)
    assert loader.is_loading(79)
    loader.drain()
    assert loader.has_failed(79) and not loader.is_loading(79)
    assert loader.take_changed() and not loader.take_changed()

    requests = len(calls)
    loader.request_details(79)
    loader.request_names("move", ["tackle"])
    loader.drain()
    loader.request_names("move", ["tackle"])
    loader.drain()
    assert len(calls) == requests + 1, "the details are not asked again; the name only once"

    loader.request_details(79, retry=True)
    loader.request_names("move", ["tackle"])
    loader.drain()
    assert len(calls) == requests + 3, "a retry asks for both again"


# MARK: enrichment


def _store(tmp_path, api, loader=None, **state):
    store = CompanionStore(save_path=tmp_path / "companion.json", api=api,
                           sprite_store=None, detail_loader=loader)
    store.state = CompanionState(**state)
    return store


def test_the_companion_is_enriched_once_its_details_arrive(tmp_path, network):
    api = _api(tmp_path, network)
    loader = DetailLoader(api, start=False)
    mon = MonState(base_id=79, path_ids=[79], planned_path_ids=[79], rarity=Rarity.COMMON,
                   profile=P.generate(7))
    store = _store(tmp_path, api, loader, active=mon)

    assert not store.enrich_profiles()
    assert loader.is_loading(79), "the companion's details are fetched unasked"
    assert mon.profile.gender is None

    loader.drain()
    assert store.enrich_profiles()
    assert mon.profile.gender in ("male", "female")
    assert mon.profile.ability_name == "oblivious"
    saved = save.load(tmp_path / "companion.json")
    assert saved.active.profile.ability_name == "oblivious"
    assert not store.enrich_profiles(), "nothing rerolls"


def test_a_dex_entry_waits_for_its_page_to_fetch(tmp_path, network):
    api = _api(tmp_path, network)
    loader = DetailLoader(api, start=False)
    entry = DexEntry(base_id=79, final_id=79, chain_order=[79], rarity=Rarity.COMMON,
                     profile=P.generate(3))
    store = _store(tmp_path, api, loader, dex=[entry])
    store.enrich_profiles()
    assert not loader.is_loading(79)

    api.details(79)
    assert store.enrich_profiles()
    assert entry.profile.ability_name == "oblivious"


def test_the_daemon_publishes_again_when_details_arrive(tmp_path, network):
    from poketokenbar.daemon import Daemon
    from poketokenbar.models import DailyUsage

    class Provider:
        id = "fake"
        display_name = "Fake"
        reports_cost = True

        def fetch_daily(self, today=None):
            return DailyUsage(date="2026-09-17", total_tokens=1)

    api = _api(tmp_path, network)
    loader = DetailLoader(api, start=False)
    mon = MonState(base_id=79, path_ids=[79], planned_path_ids=[79], profile=P.generate(7))
    store = _store(tmp_path, api, loader, active=mon)
    daemon = Daemon(state_path=tmp_path / "state.json", config_path=tmp_path / "config.json",
                    cache=None, providers=[Provider()], companion_store=store)
    daemon.poll_once()
    assert not daemon._details_arrived()

    loader.drain()
    assert daemon._details_arrived()
    daemon._publish([], fresh_limits=False)
    assert mon.profile.ability_name == "oblivious"


# MARK: the detail page


def _page_store(tmp_path, network, **state):
    api = _api(tmp_path, network)
    loader = DetailLoader(api, start=False)
    return _store(tmp_path, api, loader, **state), api, loader


def test_only_an_owned_species_opens_a_page(tmp_path, network):
    store, _, _ = _page_store(tmp_path, network)
    store.inspect(79)
    assert store.inspected_species_id is None
    assert store.detail_payload() is None


def test_the_page_loads_then_names_its_individuals_newest_first(tmp_path, network):
    older = DexEntry(base_id=79, final_id=79, chain_order=[79], rarity=Rarity.COMMON,
                     caught_at=1.0, profile=P.generate(1))
    newer = DexEntry(base_id=79, final_id=79, chain_order=[79], rarity=Rarity.COMMON,
                     caught_at=2.0, released_at=2.0, profile=P.generate(2))
    mon = MonState(base_id=79, path_ids=[79], planned_path_ids=[79], nature="adamant",
                   profile=P.generate(3))
    store, _, loader = _page_store(tmp_path, network, active=mon, dex=[older, newer],
                                   language="ko")
    store.inspect(79)
    assert store.detail_payload()["status"] == "loading"

    loader.drain()
    store.enrich_profiles()
    page = store.detail_payload()
    assert page["status"] == "ready"
    labels = [(one["is_active"], one["is_released"]) for one in page["individuals"]]
    assert labels == [(True, False), (False, True), (False, False)]
    first = page["individuals"][0]
    assert first["nature_text"] == "고집"
    # The appearance and the date belong in the label: the picker filters by
    # appearance, so "#1" alone would not say which one is on screen.
    assert first["label"] == "#1 · 일반 · Lv. 5 · 키우는 중"
    assert page["individuals"][1]["label"].startswith("#2 · 일반 · Lv. ")
    assert [s["label"] for s in first["stats"]] == ["HP", "스피드"]
    # Names are on their way: an ellipsis, never an English flash.
    assert first["ability_text"] == "…"
    assert page["species"]["types"] == ["…", "…"]

    loader.drain()  # every names request fails: this fixture is offline for them
    page = store.detail_payload()
    assert page["individuals"][0]["ability_text"] == "Oblivious"
    assert page["species"]["abilities"] == ["Oblivious", "Regenerator (숨김)"]
    assert page["species"]["moves"] == [{"name": "Tackle", "methods": "Lv. 1"}]


def test_a_failed_page_can_be_retried(tmp_path, network):
    responses, _ = network
    entry = DexEntry(base_id=80, final_id=80, chain_order=[80], rarity=Rarity.COMMON,
                     profile=P.generate(1))
    store, _, loader = _page_store(tmp_path, network, dex=[entry])
    store.inspect(80)
    loader.drain()
    assert store.detail_payload()["status"] == "failed"

    responses[f"{pokeapi.REST_BASE}/pokemon/80"] = RAW_POKEMON
    responses[f"{pokeapi.REST_BASE}/pokemon-species/80"] = {"gender_rate": -1}
    store.inspect(80, retry=True)
    loader.drain()
    assert store.detail_payload()["status"] == "ready"


def test_an_earlier_stage_is_a_species_page_without_individuals(tmp_path, network):
    entry = DexEntry(base_id=79, final_id=80, chain_order=[79, 80], rarity=Rarity.COMMON,
                     profile=P.generate(1))
    store, api, _ = _page_store(tmp_path, network, dex=[entry])
    api.details(79)
    store.inspect(79)
    page = store.detail_payload()
    assert page["individuals"] == []
    assert [s["value"] for s in page["species"]["base_stats"]] == [90, 15]


def test_the_inspect_command_opens_and_closes_the_page(tmp_path, network):
    from poketokenbar import commands
    from poketokenbar.daemon import Daemon

    entry = DexEntry(base_id=79, final_id=79, chain_order=[79], rarity=Rarity.COMMON,
                     profile=P.generate(1))
    store, _, _ = _page_store(tmp_path, network, dex=[entry])
    daemon = Daemon(state_path=tmp_path / "state.json", config_path=tmp_path / "config.json",
                    cache=None, providers=[], companion_store=store)
    daemon.spool = tmp_path / "spool"
    daemon.poll_once()

    commands.enqueue("inspect", {"species_id": "79"}, spool=daemon.spool)
    assert daemon.react()["detail"]["species_id"] == 79
    commands.enqueue("inspect", {"species_id": "none"}, spool=daemon.spool)
    assert daemon.react()["detail"] == {}


def test_the_page_carries_both_appearances_so_the_picker_can_switch(tmp_path, network):
    """The header sprite follows the appearance picker, and switching it must
    not wait for a poll — so both sprites travel with the page."""
    store, _api, loader = _page_store(
        tmp_path, network,
        dex=[
            DexEntry(base_id=79, final_id=79, chain_order=[79], rarity=Rarity.COMMON,
                     profile=P.generate(1), caught_at=1_780_000_000),
            DexEntry(base_id=79, final_id=79, chain_order=[79], rarity=Rarity.COMMON,
                     is_shiny=True, profile=P.generate(2), caught_at=1_781_000_000),
        ])
    class Sprites:
        def path(self, species_id, animated=False, shiny=False, unown_form=None):
            return f"/sprites/{species_id}{'-shiny' if shiny else ''}.gif"

        def item_path(self, name):
            return ""

    store.sprites = Sprites()
    store.inspect(79)
    loader.drain()
    store.enrich_profiles()
    page = store.detail_payload(dex_rows=store.dex_payload())

    assert page["is_shiny"] and page["has_normal"]
    assert page["sprite_path_normal"] == "/sprites/79.gif"
    assert page["sprite_path_shiny"] == "/sprites/79-shiny.gif"
    appearances = [one["is_shiny"] for one in page["individuals"]]
    assert appearances == [True, False], "newest first, both kept"
    assert "✨" in page["individuals"][0]["label"]


def test_shedinja_has_one_hp_at_every_level():
    """The main series pins it to 1; the generic formula gives it level + 12 or
    more, and Nincada's branch makes it reachable here (upstream fad8f1a)."""
    from poketokenbar.profile import PokemonDetails, compute_stats

    details = PokemonDetails(
        species_id=292, name="shedinja", height=8, weight=12, base_experience=83,
        gender_rate=-1, types=["bug", "ghost"],
        base_stats={"hp": 1, "attack": 90, "defense": 45,
                    "special-attack": 30, "special-defense": 30, "speed": 40},
        abilities=[], moves=[],
    )
    for level in (5, 50, 100):
        individual = P.generate(level)
        individual.level = level
        hp = next(s for s in compute_stats(details, individual, None) if s.name == "hp")
        assert hp.value == 1, f"level {level}"

    # Any other species keeps the formula.
    details.species_id = 291
    hp = next(s for s in compute_stats(details, P.generate(1), None) if s.name == "hp")
    assert hp.value > 1
