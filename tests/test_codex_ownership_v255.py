"""Ownership fixtures include canonical upstream v2.5.5 commit 42df4e6."""
import json

from poketokenbar.providers.codex import CodexProvider, parse_rollout


def write(root, name, session, events, *, parent=None, subagent=False):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {'id': session}
    if parent:
        payload['forked_from_id'] = parent
    if subagent:
        payload['thread_source'] = 'subagent'
    rows = [{'type': 'session_meta', 'timestamp': '2026-09-25T12:00:00Z', 'payload': payload},
            {'type': 'turn_context', 'payload': {'model': 'gpt-6.1-sol'}}]
    for stamp, total, last in events:
        rows.append({'type': 'event_msg', 'timestamp': stamp, 'payload': {
            'type': 'token_count', 'info': {'total_token_usage': total, 'last_token_usage': last}}})
    path.write_text('\n'.join(map(json.dumps, rows)))
    return path


def vector(tokens):
    return {'input_tokens': tokens, 'total_tokens': tokens}


def test_equal_totals_from_unrelated_sessions_both_count(tmp_path):
    root = tmp_path / '.codex' / 'sessions'
    for name in ('one', 'two'):
        write(root, name + '.jsonl', name, [('2026-09-25T12:00:01Z', vector(10), vector(10))])
    assert CodexProvider(home=tmp_path).fetch_daily('2026-09-25').total_tokens == 20


def test_repeated_snapshot_is_not_new_usage_and_missing_cumulative_is(tmp_path):
    events = [('2026-09-25T12:00:01Z', vector(10), vector(10)),
              ('2026-09-25T12:00:02Z', vector(10), vector(10))]
    root = tmp_path / '.codex' / 'sessions'
    write(root, 'one.jsonl', 'one', events)
    assert len(parse_rollout(root / 'one.jsonl').entries) == 1
    write(root, 'legacy.jsonl', 'legacy', [(s, None, last) for s, _, last in events])
    assert CodexProvider(home=tmp_path).fetch_daily('2026-09-25').total_tokens == 30


def test_total_only_counts_without_pricing_and_handles_mid_session_growth(tmp_path):
    root = tmp_path / '.codex' / 'sessions'
    write(root, 'one.jsonl', 'one', [
        ('2026-09-25T12:00:01Z', vector(100), vector(100)),
        ('2026-09-25T12:01:00Z', {'input_tokens': 100, 'total_tokens': 150}, {'total_tokens': 50})])
    daily = CodexProvider(home=tmp_path).fetch_daily('2026-09-25')
    assert daily.total_tokens == 150
    assert daily.cost_coverage.estimated and daily.cost_coverage.unknown


def test_fork_replay_removed_but_identical_sibling_work_retained(tmp_path):
    root = tmp_path / '.codex' / 'sessions'
    first = ('2026-09-24T12:00:01Z', vector(10), vector(10))
    write(root, 'parent.jsonl', 'parent', [first])
    for child in ('child', 'sibling'):
        write(root, child + '.jsonl', child, [
            ('2026-09-25T12:00:01Z', vector(10), vector(10)),
            ('2026-09-25T12:05:00Z', vector(30), vector(20))], parent='parent')
    provider = CodexProvider(home=tmp_path)
    assert provider.fetch_daily('2026-09-24').total_tokens == 10
    assert provider.fetch_daily('2026-09-25').total_tokens == 40


def test_orphan_subagent_keeps_first_turn_and_manual_fork_skips_burst(tmp_path):
    root = tmp_path / '.codex' / 'sessions'
    events = [('2026-09-25T12:00:01Z', vector(10), vector(10)),
              ('2026-09-25T12:00:01.100Z', vector(20), vector(10)),
              ('2026-09-25T12:00:05Z', vector(50), vector(30))]
    write(root, 'sub.jsonl', 'sub', events, parent='missing', subagent=True)
    write(root, 'fork.jsonl', 'fork', events, parent='missing')
    assert CodexProvider(home=tmp_path).fetch_daily('2026-09-25').total_tokens == 80


def test_archived_duplicate_keeps_earliest_date_and_cumulative_reset_counts(tmp_path):
    root = tmp_path / '.codex' / 'sessions'
    events = [('2026-09-25T12:00:01Z', vector(10), vector(10)),
              ('2026-09-25T12:00:02Z', vector(20), vector(10)),
              ('2026-09-25T12:00:03Z', vector(10), vector(10))]
    write(root, 'one.jsonl', 'one', events)
    write(tmp_path / '.codex' / 'archived_sessions', 'copy.jsonl', 'one', events)
    assert CodexProvider(home=tmp_path).fetch_daily('2026-09-25').total_tokens == 30


def test_rollout_cache_keeps_parent_metadata_across_instances(tmp_path):
    from poketokenbar.cache import ScanCache
    import os
    root = tmp_path / '.codex' / 'sessions'
    events = [('2026-09-25T12:00:01Z', vector(10), vector(10))]
    parent = write(root, 'parent.jsonl', 'parent', events)
    write(root, 'child.jsonl', 'child', events + [('2026-09-25T12:01:00Z', vector(30), vector(20))], parent='parent')
    # Normalize before caching: some mounted filesystems round restored timestamps.
    os.utime(parent, (int(parent.stat().st_atime), int(parent.stat().st_mtime)))
    cache_path = tmp_path / 'cache.db'
    cache = ScanCache(cache_path)
    assert CodexProvider(cache=cache, home=tmp_path).fetch_daily('2026-09-25').total_tokens == 30
    cache.close()
    stat = parent.stat()
    parent.write_bytes(b'x' * stat.st_size)
    os.utime(parent, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    cache = ScanCache(cache_path)
    assert CodexProvider(cache=cache, home=tmp_path).fetch_daily('2026-09-25').total_tokens == 30
    cache.close()


def test_canonical_upstream_fork_and_subagent_fixtures():
    from pathlib import Path
    from poketokenbar.providers.codex import resolve_rollouts
    fixtures = Path(__file__).parent / 'fixtures' / 'upstream-v2.5.5'
    fork = fixtures / 'CodexFork'
    entries = resolve_rollouts([parse_rollout(p) for p in sorted(fork.glob('*.jsonl'))])
    assert sum(e.total for e in entries) == 369215
    assert [e.total for e in CodexProvider().parse_file(fork / 'child.jsonl')] == [0, 28138]
    for suffix, totals in [('', [22992, 23043, 23062, 23219, 23291]),
                           ('-v145', [20863, 21175, 21365, 21458, 21722])]:
        paths = [fixtures / 'CodexSubagent' / f'{name}{suffix}.jsonl' for name in ('parent', 'child')]
        resolved = resolve_rollouts([parse_rollout(p) for p in paths])
        assert sorted(e.total for e in resolved) == totals
