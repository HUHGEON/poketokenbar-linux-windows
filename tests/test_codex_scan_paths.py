"""Codex scanning must avoid per-file Windows realpath calls and alias replays."""
import json
from pathlib import Path

import pytest

from poketokenbar.providers.codex import CodexProvider


def write_rollout(path, session):
    path.parent.mkdir(parents=True, exist_ok=True)
    records = [
        {'type':'session_meta', 'payload':{'id':session}},
        {'type':'event_msg', 'timestamp':'2026-10-24T00:00:00Z',
         'payload':{'type':'token_count', 'info':{
             'last_token_usage':{'input_tokens':10},
             'total_token_usage':{'input_tokens':10}}}},
    ]
    path.write_text('\n'.join(json.dumps(record) for record in records), encoding='utf-8')


def test_ordinary_rollouts_do_not_require_realpath_per_file(tmp_path, monkeypatch):
    root = tmp_path / '.codex/sessions'
    for index in range(20):
        write_rollout(root / f'{index}.jsonl', str(index))
    original = Path.resolve
    def resolve(path, *args, **kwargs):
        if path.suffix == '.jsonl':
            raise AssertionError('ordinary rollout triggered expensive realpath')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', resolve)
    assert sum(entry.total for entry in CodexProvider(home=tmp_path).scan_entries()) == 200


def test_file_symlink_alias_does_not_count_a_rollout_twice(tmp_path):
    root = tmp_path / '.codex/sessions'
    path = root / 'original.jsonl'
    write_rollout(path, 'one')
    try:
        (root / 'alias.jsonl').symlink_to(path)
    except OSError:
        pytest.skip('file symlinks unavailable')
    assert sum(entry.total for entry in CodexProvider(home=tmp_path).scan_entries()) == 10



def test_hardlink_alias_of_ownerless_usage_is_counted_once(tmp_path):
    import os
    root = tmp_path / '.codex/sessions'
    path = root / 'original.jsonl'
    write_rollout(path, None)
    try:
        os.link(path, root / 'hardlink.jsonl')
    except OSError:
        pytest.skip('hardlinks unavailable')
    assert sum(entry.total for entry in CodexProvider(home=tmp_path).scan_entries()) == 10
