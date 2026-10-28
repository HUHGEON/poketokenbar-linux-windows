"""Public usage behavior carried forward from upstream v2.5.5 fixtures."""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

from poketokenbar import pricing
from poketokenbar.cache import ScanCache
from poketokenbar.models import Entry
from poketokenbar.providers.base import ScanningProvider, dedup_keep_max, to_int
from poketokenbar.providers.claude import parse_file
from poketokenbar.providers.opencode import parse_database
from poketokenbar.providers.sqlite_source import make_entry

NOW = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)


def entry(**values):
    return Entry(id='turn', date=NOW, local_day='2026-09-25', model='gpt-5.5', input=100, **values)


def test_reported_zero_is_known_and_unknown_model_is_not_guessed():
    provider = ScanningProvider()
    free = make_entry('free', NOW, 'gpt-5.5', input=100, cost=0)
    daily = provider.aggregate_daily('2026-09-25', [free])
    assert daily.total_cost == 0
    assert daily.cost_coverage.reported
    assert not daily.cost_coverage.unknown
    unknown = Entry('unknown', NOW, '2026-09-25', 'claude-opus-future', input=100)
    partial = provider.aggregate_daily('2026-09-25', [free, unknown])
    assert partial.cost_coverage.reported and partial.cost_coverage.unknown


def test_total_only_and_zero_tokens_do_not_invent_cost():
    provider = ScanningProvider()
    total = entry(cost_unavailable=True)
    zero = Entry('zero', NOW, '2026-09-25', 'gpt-5.5', explicit_cost=50)
    daily = provider.aggregate_daily('2026-09-25', [total, zero])
    assert daily.total_tokens == 100
    assert daily.total_cost == 0
    assert daily.cost_coverage.unknown
    assert not daily.cost_coverage.reported


def test_cost_provenance_and_session_ownership_survive_cache(tmp_path):
    cache = ScanCache(tmp_path / 'cache.db')
    original = entry(explicit_cost=0, cost_is_estimate=True, cost_unavailable=True,
                     session_id='parent', session_ids=['parent', 'fork'])
    cache.put('claude_code', tmp_path / 'log', 1, 1, 2, [original])
    loaded = cache.get('claude_code', tmp_path / 'log', 1, 1, 2)[0]
    assert loaded == original
    cache.close()


def test_dedup_preserves_original_day_and_all_claude_sessions():
    first = entry(session_id='parent')
    later = Entry('turn', datetime(2026, 9, 26, tzinfo=timezone.utc), '2026-09-26',
                  'gpt-5.5', input=200, session_id='fork')
    result = dedup_keep_max([later, first])[0]
    assert result.total == 200
    assert result.local_day == '2026-09-25'
    assert set(result.session_ids) == {'parent', 'fork'}


def test_pricing_exact_aliases_and_request_tiers():
    assert pricing.cost('openai/gpt-5.2', 1000000, 0, 0, 0) == pytest.approx(1.75)
    assert pricing.cost('claude-opus-5-5', 1000000, 0, 0, 1000000) == pytest.approx(4.2)
    assert pricing.cost('claude-fable-5-1', 0, 0, 0, 1000000) == pytest.approx(.25)
    assert pricing.cost('gpt-5.5', 272001, 1000, 0, 0) == pytest.approx(2.76501)
    assert pricing.cost('gpt-6.1-sol', 1000000, 100000, 0, 2000000) == pytest.approx(5.9)
    assert pricing.rate('claude-opus-unreleased') == pricing.ZERO
    assert pricing.rate('gemini-3-future-pro') == pricing.ZERO


def test_absurd_python_integer_clamps_without_float_overflow():
    assert to_int(10 ** 1000) == 10 ** 15


def test_claude_cost_ledger_last_state_allocates_after_dedup(tmp_path):
    path = tmp_path / 'session-a' / 'subagents' / 'worker.jsonl'
    path.parent.mkdir(parents=True)
    def message(ident, tokens):
        return {'type': 'assistant', 'timestamp': NOW.isoformat(), 'requestId': ident,
                'message': {'id': ident, 'model': 'unpriced-model',
                            'usage': {'input_tokens': tokens}}}
    rows = [message('a', 10), message('a', 20), message('b', 80),
            {'type': 'cost-state', 'modelUsage': {'unpriced-model[1m]': {'costUSD': 9}}},
            {'type': 'cost-state', 'modelUsage': {'unpriced-model[1m]': {'costUSD': 5},
                                                'unmatched': {'costUSD': 100}}}]
    path.write_text('\n'.join(map(json.dumps, rows)))
    parsed = parse_file(path)
    assert [e.explicit_cost for e in parsed] == [1, 4]
    assert {e.session_id for e in parsed} == {'session-a'}


def test_opencode_v2_reads_reasoning_and_merges_legacy(tmp_path):
    path = tmp_path / 'opencode.db'
    db = sqlite3.connect(path)
    db.execute('CREATE TABLE session_message (id TEXT, type TEXT, time_created INTEGER, data TEXT)')
    db.execute('CREATE TABLE message (id TEXT, session_id TEXT, data TEXT)')
    v2 = {'model': {'id': 'gpt-5.5', 'providerID': 'openai'},
          'tokens': {'input': 100, 'output': 20, 'reasoning': 30, 'cache': {'read': 40, 'write': 5}}, 'cost': 0}
    db.execute('INSERT INTO session_message VALUES (?, ?, ?, ?)', ('v2', 'assistant', NOW.timestamp()*1000, json.dumps(v2)))
    db.execute('INSERT INTO session_message VALUES (?, ?, ?, ?)', ('user', 'user', NOW.timestamp()*1000, json.dumps(v2)))
    v1 = {'id': 'legacy', 'modelID': 'gpt-5.5', 'providerID': 'openai', 'time': {'created': NOW.timestamp()*1000}, 'tokens': {'input': 10}}
    db.execute('INSERT INTO message VALUES (?, ?, ?)', ('legacy', 's', json.dumps(v1)))
    db.commit()
    db.close()
    entries = parse_database(path)
    assert sum(e.total for e in entries) == 205
    modern = next(e for e in entries if e.id == 'opencode|v2')
    assert modern.output == 50
    assert modern.explicit_cost == 0


def test_aside_mutable_turns_use_activity_and_keep_seen_usage(tmp_path):
    import poketokenbar.providers as providers
    provider_type = next((p for p in providers.REGISTRY if p.id == 'aside'), None)
    assert provider_type is not None
    root = tmp_path / '.aside' / 'u' / 'user'
    root.mkdir(parents=True)
    db = sqlite3.connect(root / 'state.db')
    db.executescript('CREATE TABLE sessions (id TEXT, model TEXT); CREATE TABLE session_turns (id INTEGER, session_id TEXT, token_usage TEXT, finished_at REAL, last_message_timestamp REAL);')
    db.execute('INSERT INTO sessions VALUES (?, ?)', ('s', json.dumps({'modelId': 'gpt-5.5'})))
    db.execute('INSERT INTO session_turns VALUES (?, ?, ?, ?, ?)', (1, 's', json.dumps({'totalTokens': 120}), None, NOW.timestamp()))
    db.commit()
    provider = provider_type(home=tmp_path)
    first = provider.fetch_daily('2026-09-25')
    assert first.total_tokens == 120 and first.total_cost == 0
    assert first.cost_coverage.unknown
    db.execute('UPDATE session_turns SET token_usage = ?', (json.dumps({'input': 150, 'output': 30, 'cost': {'total': 0}}),))
    db.commit()
    second = provider.fetch_daily('2026-09-25')
    assert second.total_tokens == 180 and second.cost_coverage.reported
    db.execute('DELETE FROM session_turns')
    db.commit()
    assert provider.fetch_daily('2026-09-25').total_tokens == 180
    assert provider_type(home=tmp_path).fetch_daily('2026-09-25') is None
    db.close()


def test_claude_accounts_follow_latest_prompt_and_original_replay_time():
    import poketokenbar.providers.claude as claude
    owner = getattr(claude, 'account_owner', None)
    assert owner is not None
    accounts = {'first': {'parent': [datetime(2026, 9, 25, 10, tzinfo=timezone.utc)]},
                'second': {'parent': [datetime(2026, 9, 25, 13, tzinfo=timezone.utc)],
                           'fork': [datetime(2026, 9, 26, 10, tzinfo=timezone.utc)]}}
    assert owner(entry(session_ids=['parent', 'fork']), accounts) == 'first'
    later = Entry('later', datetime(2026, 9, 25, 14, tzinfo=timezone.utc), '2026-09-25', 'm', input=1, session_id='parent')
    assert owner(later, accounts) == 'second'
    assert owner(entry(session_id='unknown'), accounts) is None


def test_pi_total_only_stays_unpriced_and_explicit_zero_is_estimated(tmp_path):
    from poketokenbar.providers.pi import PiProvider
    root = tmp_path / '.pi' / 'agent' / 'sessions'
    root.mkdir(parents=True)
    obj = {'id': 'turn', 'type': 'message', 'timestamp': NOW.isoformat(),
           'message': {'model': 'gpt-5.5', 'usage': {'totalTokens': 100}}}
    path = root / 'session.jsonl'
    path.write_text(json.dumps(obj))
    provider = PiProvider(home=tmp_path)
    daily = provider.fetch_daily('2026-09-25')
    assert daily.total_cost == 0 and daily.cost_coverage.unknown
    obj['message']['usage'] = {'input': 100, 'cost': {'total': 0}}
    path.write_text(json.dumps(obj))
    daily = provider.fetch_daily('2026-09-25')
    assert daily.total_cost == 0 and daily.cost_coverage.estimated


def test_hermes_actual_zero_overrides_estimate_and_missing_cost_stays_unknown(tmp_path):
    from poketokenbar.providers.hermes import HermesProvider, parse_database
    from tests.test_opencode_hermes import HERMES_SCHEMA
    path = tmp_path / 'state.db'
    db = sqlite3.connect(path)
    db.executescript(HERMES_SCHEMA)
    db.execute('INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
               ('s', 'gpt-5.5', 'openai', NOW.timestamp(), 1, 100, 20, 0, 0, 0, 1.5, 0))
    db.commit()
    parsed = parse_database(path)
    assert parsed[0].explicit_cost == 0
    assert not parsed[0].cost_is_estimate
    db.execute('UPDATE sessions SET actual_cost_usd = NULL, estimated_cost_usd = NULL')
    db.commit()
    daily = HermesProvider().aggregate_daily('2026-09-25', parse_database(path))
    assert daily.total_cost == 0 and daily.cost_coverage.unknown
    db.close()


def test_all_periods_keep_cost_coverage_and_ignore_future_days():
    class Provider(ScanningProvider):
        def scan_entries(self):
            return [entry(explicit_cost=0), Entry('unknown', NOW, '2026-09-25', 'unpriced', input=20),
                    Entry('future', NOW, '2026-09-26', 'gpt-5.5', input=1000000)]
    periods = Provider().fetch_periods('2026-09-25')
    assert periods['month']['tokens'] == 120
    assert periods['month']['cost_coverage'].reported and periods['month']['cost_coverage'].unknown


def test_claude_account_roots_and_daily_attribution_are_configurable(tmp_path):
    from poketokenbar.providers.claude import ClaudeProvider
    root = tmp_path / 'additional'
    (root / 'projects').mkdir(parents=True)
    (root / 'history.jsonl').write_text(json.dumps({'sessionId': 'session', 'timestamp': NOW.timestamp() * 1000}) + '\n')
    (root / 'projects' / 'session.jsonl').write_text(json.dumps({'type': 'assistant', 'timestamp': NOW.isoformat(), 'message': {'id': 'turn', 'model': 'gpt-5.5', 'usage': {'input_tokens': 100}}}))
    provider = ClaudeProvider(home=tmp_path)
    configure = getattr(provider, 'configure_account_roots', None)
    assert configure is not None
    configure(lambda: {'additional': root})
    daily = provider.fetch_daily('2026-09-25')
    assert daily.total_tokens == 100
    accounts = provider.fetch_accounts({'additional': root}, today='2026-09-25')
    assert accounts['additional'].total_tokens == 100
    assert accounts[''].total_tokens == 0


def test_zero_usage_has_no_active_block_or_daily_presence():
    class Provider(ScanningProvider):
        def scan_entries(self):
            return [Entry('synthetic', NOW, '2026-09-25', 'unknown')]
    assert Provider().fetch_daily('2026-09-25') is None
    assert Provider().fetch_active_block(now=NOW) is None


def test_grok_explicit_zero_stays_reported():
    from poketokenbar.providers.grok import GrokProvider, parse_line
    from tests.test_grok import turn_line
    parsed = parse_line(turn_line('zero-cost', cost_ticks=0))
    daily = GrokProvider().aggregate_daily(parsed.local_day, [parsed])
    assert daily.total_cost == 0 and daily.cost_coverage.reported


def test_copilot_recoverable_buckets_have_api_estimates():
    from poketokenbar.providers.copilot import CopilotProvider
    daily = CopilotProvider().aggregate_daily('2026-09-25', [entry()])
    assert daily.total_cost == pytest.approx(.0005)
    assert daily.cost_coverage.estimated


def test_kiro_preserves_usage_after_store_clear_until_restart(tmp_path):
    from poketokenbar.providers.kiro import KiroProvider
    from tests.test_kiro import seed_v2, conversation, turn
    root = tmp_path / '.local' / 'share' / 'kiro-cli'
    root.mkdir(parents=True)
    path = seed_v2(root / 'data.sqlite3', [('s', conversation('s', [turn(NOW.timestamp()*1000, user_text='u'*400, response_bytes=200)]))])
    provider = KiroProvider(home=tmp_path)
    assert provider.fetch_daily('2026-09-25').total_tokens == 150
    db = sqlite3.connect(path)
    db.execute('DELETE FROM conversations_v2')
    db.commit()
    db.close()
    assert provider.fetch_daily('2026-09-25').total_tokens == 150
    assert KiroProvider(home=tmp_path).fetch_daily('2026-09-25') is None


def test_aside_current_model_does_not_label_historical_breakdown():
    from poketokenbar.providers.aside import AsideProvider
    daily = AsideProvider().aggregate_daily('2026-09-25', [entry(cost_unavailable=True)])
    assert daily.total_tokens == 100
    assert daily.models == {}
