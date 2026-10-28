"""Species details preserve complete B2W2 learnsets and existing individuals."""
import copy
import json

import pytest

from poketokenbar import pokeapi
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry
from poketokenbar.companion_store import CompanionStore
from poketokenbar.profile import PokemonProfile


def move(name, method='level-up', level=1, version='black-2-white-2'):
    return {'move': {'name': name}, 'version_group_details': [{
        'version_group': {'name': version}, 'move_learn_method': {'name': method},
        'level_learned_at': level}]}


def install_api(tmp_path, monkeypatch):
    api = pokeapi.PokeAPI(tmp_path)
    raw = {'height': 7, 'weight': 69, 'stats': [{'stat': {'name': 'hp'}, 'base_stat': 45}],
           'abilities': [{'ability': {'name': 'overgrow'}, 'slot': 1, 'is_hidden': False}],
           'moves': [move('tackle'), move('solar-beam', 'machine', 0),
                     move('skull-bash', 'egg', 0), move('old-move', version='black-white'),
                     move('growl', level=3)]}
    monkeypatch.setattr(pokeapi, '_get_json', lambda *a, **k: raw)
    monkeypatch.setattr(api, 'species', lambda sid: {'gender_rate': 1})
    return api


def test_full_learnset_keeps_machine_and_egg_without_auto_equipping_them(tmp_path, monkeypatch):
    api = install_api(tmp_path, monkeypatch)
    details = api.details(1)
    assert details['version_group'] == 'black-2-white-2'
    assert [m['name'] for m in details['all_moves']] == ['growl', 'skull-bash', 'solar-beam', 'tackle']
    assert {m['name'] for m in details['moves']} == {'tackle', 'growl'}
    profile = PokemonProfile.generate(seed=1)
    profile.level = 100
    profile.enrich(details)
    assert {m['name'] for m in profile.moves} == {'tackle', 'growl'}
    assert pokeapi.PokeAPI(tmp_path).details(1) == details


def test_old_cache_is_upgraded_even_when_fresh_and_already_in_memory(tmp_path, monkeypatch):
    api = install_api(tmp_path, monkeypatch)
    path = api._details_file(1)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'fetched_at': 99999999999, 'details': {'moves': [{'name': 'old-move', 'learned_at': 1}]}}))
    assert api.cached_details(1)['moves'][0]['name'] == 'old-move'
    assert api.details(1)['version_group'] == 'black-2-white-2'
    assert 'all_moves' in json.loads(path.read_text())['details']


def test_old_cache_survives_offline_upgrade_failure(tmp_path, monkeypatch):
    api = install_api(tmp_path, monkeypatch)
    old = {'moves': [{'name': 'old-move', 'learned_at': 1}]}
    api._details[1] = old
    def offline(*a, **k):
        raise pokeapi.PokeAPIError('offline')
    monkeypatch.setattr(pokeapi, '_get_json', offline)
    assert api.details(1) == old


def make_store(tmp_path, monkeypatch):
    api = install_api(tmp_path / 'cache', monkeypatch)
    monkeypatch.setattr(api, 'localized_battle_names', lambda ability, moves, language:
                        ('심록' if ability else '', {name: '기술-' + name for name in moves}))
    store = CompanionStore(api=api, sprite_store=None, save_path=tmp_path/'save.json')
    profile = PokemonProfile.generate(seed=1)
    store.state = CompanionState(language='ko', dex=[DexEntry(
        base_id=1, final_id=2, chain_order=[1, 2], rarity=Rarity.COMMON, profile=profile)])
    return store


def test_reference_stage_details_exist_without_individual_and_localize_all_moves(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    store.load_pokemon_details(1)
    assert store._detail_status[1] == 'ready'
    details = store._detail_payloads[1]
    assert details['base_stat_total'] == 45
    assert details['height'] == 7 and details['weight'] == 69
    assert details['abilities'][0]['display_name'] == '심록'
    assert all(m['display_name'].startswith('기술-') for m in details['moves'])
    assert store.state.dex[0].profile.moves == []  # not the requested species


def test_detail_refresh_preserves_individual_identity_and_progress(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    profile = store.state.dex[0].profile
    profile.level = 80
    before = copy.deepcopy((profile.ivs, profile.instance_id, profile.level, store.state.used_since_install))
    store.load_pokemon_details(2)
    assert profile.moves
    assert (profile.ivs, profile.instance_id, profile.level, store.state.used_since_install) == before


def test_uncollected_species_rejected_and_network_failure_is_retryable(tmp_path, monkeypatch):
    store = make_store(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        store.load_pokemon_details(999)
    def offline(sid):
        raise pokeapi.PokeAPIError('offline')
    original = store.api.details
    monkeypatch.setattr(store.api, 'details', offline)
    store.load_pokemon_details(1)
    assert store._detail_status[1] == 'error'
    monkeypatch.setattr(store.api, 'details', original)
    store.load_pokemon_details(1)
    assert store._detail_status[1] == 'ready'


def test_offline_detail_backoff_does_not_delay_every_poll_and_manual_retry_resets_it(tmp_path, monkeypatch):
    api = install_api(tmp_path, monkeypatch)
    api._details[1] = {"moves": []}
    calls = []
    def offline(*a, **k):
        calls.append(1)
        raise pokeapi.PokeAPIError('offline')
    monkeypatch.setattr(pokeapi, '_get_json', offline)
    api.details(1)
    api.details(1)
    assert len(calls) == 1
    api.reset_details_retry(1)
    api.details(1)
    assert len(calls) == 2
