"""Behavioral regressions ported from macOS v2.5.6 (d82867b)."""
import json
import random
from datetime import datetime, timezone

import pytest

from poketokenbar import balance, config, forms, format as fmt, l10n, pricing, save, shop, sprites
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, EvoLine, MonState, hatch, apply_usage
from poketokenbar.companion_store import CompanionStore
from poketokenbar.profile import PokemonProfile, computed_stats
from poketokenbar.providers.kimi import KimiProvider, parse_line
from poketokenbar.providers.kiro import text_byte_length


def record(**overrides):
    return {"type": "usage.record", "time": 1790000000000, "model": "kimi-code",
            "usageScope": "turn", "usage": {"inputOther": 40, "inputCacheRead": 20,
            "inputCacheCreation": 10, "output": 5}, **overrides}


def test_kimi_counts_main_subagent_compaction_and_deduplicates_forks(tmp_path):
    root = tmp_path / '.kimi-code/sessions'
    for agent, records in [('main', [record(), record(time=1790000001000, usageScope='session')]),
                           ('child', [record(time=1790000002000)]), ('fork', [record()])]:
        path = root / 'work/session/agents' / agent / 'wire.jsonl'
        path.parent.mkdir(parents=True)
        path.write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
    (root / 'messages.jsonl').write_text(json.dumps(record(time=1790000003000)))
    provider = KimiProvider(home=tmp_path)
    entries = provider.scan_entries()
    assert len(entries) == 3
    daily = provider.aggregate_daily(entries[0].local_day, entries)
    assert daily.total_tokens == 225
    assert daily.cost_coverage.unknown and not daily.cost_coverage.estimated


@pytest.mark.parametrize('overrides', [dict(type='message'), dict(usageScope='future'),
                                      dict(time=True), dict(time=1e30), dict(usage=None)])
def test_kimi_skips_unusable_records(overrides):
    assert parse_line(json.dumps(record(**overrides))) is None


def test_kimi_clamps_tokens_and_accepts_legacy_scope():
    entry = parse_line(json.dumps(record(usageScope=None, usage={'inputOther': 1e30, 'output': -1})))
    assert entry.input == 10**15 and entry.output == 0


def test_kimi_env_and_custom_roots_are_additive(tmp_path, monkeypatch):
    monkeypatch.setenv('KIMI_CODE_HOME', str(tmp_path / 'override'))
    default = tmp_path / '.kimi-code/sessions'
    override = tmp_path / 'override/sessions'
    extra = tmp_path / 'extra'
    for root in (default, override, extra):
        root.mkdir(parents=True)
    provider = KimiProvider(home=tmp_path, custom_roots=lambda _: str(extra))
    assert set(provider.roots()) == {default, override, extra}


@pytest.mark.parametrize('value,expected', [(999949, '999.9K'), (999950, '1M'),
                                          (999950000, '1B'), (-999950, '-1M')])
def test_compact_promotes_rounded_units(value, expected):
    assert fmt.compact(value) == expected


def test_rounded_cost_and_percent_pick_display_precision():
    assert fmt.cost_compact(99.96) == '$100'
    assert fmt.cost_compact(9999.6) == '$10.0K'
    assert fmt.percent(79.96) == '80%'


@pytest.mark.parametrize('kind,advance', [('session', 1800), ('weekly', 86400)])
def test_candy_ignores_reset_jitter_and_advances_from_original_epoch(kind, advance):
    state = CompanionState(candy_feature_seeded=True)
    key = 'codex:account:' + kind
    start = 1790000000
    def epoch(offset):
        return datetime.fromtimestamp(start + offset, timezone.utc).isoformat()
    assert shop.grant_candy(state, {key: 100}, {key: epoch(0)}) > 0
    for offset in (0.001, 1, -1, advance - 1):
        assert shop.grant_candy(state, {key: 100}, {key: epoch(offset)}) == 0
    assert shop.grant_candy(state, {key: 100}, {key: epoch(advance)}) > 0
    assert shop.grant_candy(state, {key: 20}, {key: epoch(advance + 1)}) == 0
    assert shop.grant_candy(state, {key: 100}, {key: epoch(advance + 1)}) > 0


@pytest.mark.parametrize('species,form,static', [(492,'sky','10006'), (479,'wash','10009'),
                                              (412,'sandy','412-sandy'), (423,'east','423-east')])
def test_forms_select_correct_static_and_animated_assets(species, form, static):
    assert sprites.sprite_url(species, True, False, form).endswith(f'/{species}-{form}.gif')
    assert sprites.sprite_url(species, False, True, form).endswith(f'/shiny/{static}.png')


def test_form_follows_evolution_and_survives_save_export_and_pin(tmp_path):
    store = CompanionStore(save_path=tmp_path / 'save.json')
    mon = MonState(422, [422,423], [422,423], total_forms=2, unown_form='east')
    store.state = CompanionState(active=mon)
    store.set_representative(422, False, 'east')
    restored = save.decode(save.encode(store.state))
    assert restored.active.unown_form == 'east'
    apply_usage(restored, balance.phase_threshold(Rarity.COMMON, 2, 0))
    assert restored.active.current_id == 423
    assert restored.representative_species_id == 423
    assert restored.appearances(423) == {(False,'east')}
    store.state = restored
    row = store.dex_payload()[-1]
    assert row['form_count'] == 1 and len(row['forms']) == 2
    assert row['appearances'][0]['unown_form'] == 'east'


def test_future_evolution_form_is_preserved_before_it_is_visible():
    mon = MonState(420,[420,421],[420,421], total_forms=2, unown_form='sunshine')
    restored = save.decode(save.encode(CompanionState(active=mon)))
    assert restored.active.unown_form == 'sunshine'
    assert restored.appearances(420) == {(False,None)}
    apply_usage(restored, balance.phase_threshold(Rarity.COMMON,2,0))
    assert restored.appearances(421) == {(False,'sunshine')}


def test_legacy_unown_saves_keep_their_letter():
    raw=save.encode(CompanionState(active=MonState(201,[201],[201],unown_form='question')))
    raw['active'].pop('form')
    assert save.decode(raw).active.unown_form == 'question'


def test_form_roll_prefers_uncollected_without_guaranteeing_novelty():
    choices=forms.line_forms(492)
    picks=[forms.roll_form(value, {'land'}, choices) for value in range(3)]
    assert picks.count('land') == 1 and picks.count('sky') == 2


def test_shedinja_hp_is_one_at_every_level():
    profile=PokemonProfile.generate(seed=1)
    for level in (5,50,100):
        profile.level=level
        assert computed_stats({'species_id':292,'base_stats':{'hp':1}},profile,'hardy')[0]['value'] == 1


def test_kiro_counts_only_tool_and_thinking_payloads():
    assert text_byte_length({'kind':'toolUse','data':{'input':{'text':'abcd'},'id':'ignored'}}) == 4
    assert text_byte_length({'kind':'toolResult','data':{'content':[{'kind':'json','data':{'out':'abcd'}}]}}) == 4
    assert text_byte_length({'kind':'thinking','data':{'text':'abcd','signature':'ignored'}}) == 4
    assert text_byte_length({'kind':'image','data':'ignored'}) == 0


def test_bulk_purchase_is_atomic_and_reaches_persistent_store(tmp_path):
    store=CompanionStore(save_path=tmp_path/'save.json')
    store.state.used_since_install=balance.RARE_CANDY_PRICE*5
    store.buy('rareCandy',count=3)
    assert store.state.inventory['rareCandy'] == 3
    assert save.load(store.save_path).inventory['rareCandy'] == 3
    with pytest.raises(shop.ShopError):
        store.buy('rareCandy',count=3)
    assert store.state.inventory['rareCandy'] == 3
    assert store.state.spent_tokens == balance.RARE_CANDY_PRICE*3


@pytest.mark.parametrize('count',[True,0,-1,1.5,100])
def test_bulk_rejects_invalid_quantities(count):
    state=CompanionState(used_since_install=10**12)
    with pytest.raises(shop.ShopError):
        shop.buy(state,'mint',count=count)
    assert state.spent_tokens == 0


def test_thresholds_keep_warning_below_critical(tmp_path):
    path=tmp_path/'config.json'
    config.set_value(path,'warn_threshold','95')
    assert config.load(path)['crit_threshold'] == 100
    config.set_value(path,'crit_threshold','80')
    assert config.load(path)['warn_threshold'] == 75


def test_russian_catalogue_preserves_every_placeholder():
    import re
    assert l10n.system_default('ru_RU.UTF-8') == 'ru'
    for key in l10n.STRINGS:
        assert set(re.findall(r'%\d+',l10n.t(key,'en'))) == set(re.findall(r'%\d+',l10n.t(key,'ru')))


@pytest.mark.parametrize('model,input_rate,output_rate,write_rate,read_rate', [
    ('gpt-6-sol',2,10,2.5,.2), ('gpt-6.1-sol',2,10,2.5,.1),
    ('gpt-6-luna',.1,.5,.125,.01), ('claude-sonnet-5-5',2,10,2.5,.1),
])
def test_new_model_prices(model,input_rate,output_rate,write_rate,read_rate):
    rate=pricing.rate(model)
    assert (rate.input,rate.output,rate.cache_write,rate.cache_read) == pytest.approx(
        tuple(value/1e6 for value in (input_rate,output_rate,write_rate,read_rate)))


def test_new_gpt_long_context_tier_starts_after_272k():
    assert pricing.cost('gpt-6.1-sol',272000,1000,0,0) == pytest.approx(.554)
    assert pricing.cost('gpt-6.1-sol',272001,1000,0,0) == pytest.approx(1.103004)


def test_deduped_save_chains_keep_current_species():
    mon=MonState(1,[1,2,2,3],[1,2,2,3],stage_index=2,total_forms=4)
    state=CompanionState(active=mon,dex=[DexEntry(1,3,[1,2,2,3],Rarity.COMMON)])
    restored=save.decode(save.encode(state))
    assert restored.active.path_ids == [1,2,3]
    assert restored.active.stage_index == 1 and restored.active.current_id == 2
    assert restored.dex[0].chain_order == [1,2,3]


def test_form_name_translation_is_cached_and_can_fall_back_offline(tmp_path,monkeypatch):
    from poketokenbar import pokeapi
    api=pokeapi.PokeAPI(cache_dir=tmp_path)
    calls=[]
    def response(url):
        calls.append(url)
        return {'form_names':[{'language':{'name':'ko'},'name':'스카이폼'}]}
    monkeypatch.setattr(pokeapi,'_get_json',response)
    assert api.form_label(492,'sky','ko') == '스카이폼'
    assert api.form_label(492,'sky','ko') == '스카이폼'
    assert len(calls) == 1
    assert pokeapi.PokeAPI(cache_dir=tmp_path).form_label(492,'sky','ko') == '스카이폼'
    assert len(calls) == 1


def test_failed_update_check_can_retry_without_consuming_cooldown(tmp_path,monkeypatch):
    from poketokenbar import updater
    root=tmp_path/'install'
    (root/'app').mkdir(parents=True)
    (root/'app'/updater.REVISION_FILE).write_text('a'*40)
    instance=updater.Updater(root=root,clock=lambda:1000)
    calls=[]
    def response(url,timeout=15):
        calls.append(url)
        if len(calls)==1:
            return b'{"sha":null}'
        return json.dumps({'sha':'b'*40}).encode()
    monkeypatch.setattr(updater,'_get',response)
    assert instance.check() == ''
    assert instance.check() == 'b'*40
    assert instance.check() == 'b'*40 and len(calls) == 2


def test_idle_provider_keeps_its_tab_and_historical_usage(tmp_path):
    from poketokenbar.daemon import Daemon
    from poketokenbar.models import ProviderEnrichment
    class IdleProvider:
        id='idle'
        display_name='Idle'
        def fetch_daily(self): return None
        def fetch_periods(self):
            return {'week':{'tokens':10,'cost':0},'month':{'tokens':10,'cost':0}}
        def fetch_enrichment(self): return ProviderEnrichment()
    daemon=Daemon(tmp_path/'state.json',tmp_path/'config.json',None,[IdleProvider()])
    payload=daemon.poll_once()
    assert payload['providers']['idle']['total_tokens'] == 0
    assert payload['periods']['month']['tokens'] == 10



def test_malformed_planned_chain_is_filtered_without_discarding_companion():
    raw=save.encode(CompanionState(active=MonState(1,[1,2],[1,2],total_forms=2)))
    raw['active']['planned_path_ids']=[1,{},2,2,None]
    restored=save.decode(raw)
    assert restored.active is not None
    assert restored.active.planned_path_ids == [1,2]



def test_ditto_boost_uses_ditto_history_after_reveal():
    mon=MonState(1,[1,2],[1,2],total_forms=2,ditto_disguise=1,has_growth_boost=True)
    state=CompanionState(active=mon,collected_finals={'1:2'})
    apply_usage(state,balance.phase_threshold(Rarity.COMMON,2,0))
    assert state.active.ditto_revealed and not state.active.has_growth_boost
    mon=MonState(1,[1,2],[1,2],total_forms=2,ditto_disguise=1)
    state=CompanionState(active=mon,collected_finals={'1:132'})
    apply_usage(state,balance.phase_threshold(Rarity.COMMON,2,0))
    assert state.active.ditto_revealed and state.active.has_growth_boost
