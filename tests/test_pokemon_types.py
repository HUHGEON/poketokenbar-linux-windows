from poketokenbar import l10n, pokemon_types
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, MonState
from poketokenbar.companion_store import CompanionStore
from poketokenbar.profile import PokemonProfile


def test_dragon_uses_upstream_color_and_korean_name():
    assert pokemon_types.badges(['dragon'], 'ko') == [
        {'type':'dragon', 'name':'드래곤', 'color':'#7766EE', 'foreground':'#ffffff'}]


def test_dual_types_preserve_slot_order_without_duplicate_badges():
    assert [row['name'] for row in pokemon_types.badges(['Grass','poison','grass'], 'ko')] == ['풀','독']
    assert pokemon_types.badges(['stellar'], 'ko')[0]['color'] == '#808080'
    assert pokemon_types.badges([]) == []


def test_all_eighteen_types_have_korean_names_with_english_fallback():
    assert pokemon_types.badges(["fire"], "ja")[0]["name"] == "Fire"
    assert len(pokemon_types.COLORS) == 18
    assert pokemon_types.LANGUAGES == l10n.LANGUAGES
    for slug, names in pokemon_types.NAMES.items():
        assert len(names) == 8
        for language in l10n.LANGUAGES:
            assert l10n.t('type_' + slug, language) == pokemon_types.badges([slug], language)[0]['name']


def test_home_and_reference_dex_entries_expose_cached_types_without_fetching(tmp_path):
    class API:
        def cached_details(self, species_id):
            return {'types':['dragon']} if species_id == 612 else {'types':['grass','poison']}
        def details(self, species_id):
            raise AssertionError('displaying types must not make another network request')
    store = CompanionStore(save_path=tmp_path/'companion.json', api=API())
    store.state = CompanionState(language='ko', active=MonState(
        610,[610,611,612],[610,611,612],stage_index=2,total_forms=3,
        rarity=Rarity.RARE,profile=PokemonProfile.generate(seed=1)))
    profile = store.payload()['profile']
    assert profile['types'] == ['dragon']
    assert profile['type_badges'][0]['name'] == '드래곤'
    dex = {row['species_id']:row for row in store.dex_payload()}
    assert dex[610]['profiles'] == []
    assert [row['name'] for row in dex[610]['type_badges']] == ['풀','독']
