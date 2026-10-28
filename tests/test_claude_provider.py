import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from poketokenbar.cache import ScanCache
from poketokenbar.providers.claude import ClaudeProvider


def _write(root, name, *, when, output=570, msg_id="msg_1", req="req_1"):
    root.mkdir(parents=True, exist_ok=True)
    obj = {
        "type": "assistant",
        "timestamp": when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "requestId": req,
        "message": {
            "id": msg_id,
            "model": "claude-opus-5",
            "usage": {
                "input_tokens": 2,
                "output_tokens": output,
                "cache_creation_input_tokens": 24_155,
                "cache_read_input_tokens": 16_203,
            },
        },
    }
    (root / name).write_text(json.dumps(obj) + "\n", encoding="utf-8")


@pytest.fixture
def home(tmp_path):
    return tmp_path


def test_returns_none_when_no_roots_exist(home):
    assert ClaudeProvider(home=home).fetch_daily() is None


def test_sums_todays_tokens(home):
    root = home / ".claude" / "projects" / "proj"
    _write(root, "a.jsonl", when=datetime.now().astimezone())
    daily = ClaudeProvider(home=home).fetch_daily()
    assert daily is not None
    assert daily.total_tokens == 40_930
    assert daily.input_tokens == 2
    assert daily.output_tokens == 570
    assert daily.cache_creation_tokens == 24_155
    assert daily.cache_read_tokens == 16_203


def test_excludes_other_days(home):
    root = home / ".claude" / "projects" / "proj"
    _write(root, "old.jsonl", when=datetime.now().astimezone() - timedelta(days=3))
    assert ClaudeProvider(home=home).fetch_daily() is None


def test_dedups_the_same_turn_across_two_roots(home):
    # A resumed session can be copied into a second root. Global dedup on
    # (message.id, requestId) must count it once, not twice.
    now = datetime.now().astimezone()
    _write(home / ".claude" / "projects" / "p", "a.jsonl", when=now)
    _write(home / ".config" / "claude" / "projects" / "p", "a.jsonl", when=now)
    daily = ClaudeProvider(home=home).fetch_daily()
    assert daily.total_tokens == 40_930


def test_unchanged_file_is_not_reparsed(home, tmp_path):
    # Prove the cache is actually consulted: corrupt the file's *contents*
    # while restoring its mtime and size so the cache key still matches. A
    # cache hit returns the old total; a miss would parse garbage and give None.
    root = home / ".claude" / "projects" / "proj"
    path = root / "a.jsonl"
    _write(root, "a.jsonl", when=datetime.now().astimezone())
    # Normalize before caching: some mounted filesystems round restored timestamps.
    os.utime(path, (int(path.stat().st_atime), int(path.stat().st_mtime)))
    original = path.stat()

    cache = ScanCache(tmp_path / "cache" / "scan.db")
    provider = ClaudeProvider(cache=cache, home=home)
    assert provider.fetch_daily().total_tokens == 40_930

    path.write_bytes(b"x" * original.st_size)  # same size, different bytes
    os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
    assert provider.fetch_daily().total_tokens == 40_930
    cache.close()


def test_cache_miss_after_file_changes(home, tmp_path):
    root = home / ".claude" / "projects" / "proj"
    now = datetime.now().astimezone()
    _write(root, "a.jsonl", when=now, output=570)
    cache = ScanCache(tmp_path / "cache" / "scan.db")
    provider = ClaudeProvider(cache=cache, home=home)
    assert provider.fetch_daily().total_tokens == 40_930

    _write(root, "a.jsonl", when=now, output=1_570, req="req_2")
    assert provider.fetch_daily().total_tokens == 41_930
    cache.close()
