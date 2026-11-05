from datetime import datetime, timezone

import pytest

from poketokenbar.cache import ScanCache
from poketokenbar.models import Entry


@pytest.fixture
def cache(tmp_path):
    c = ScanCache(tmp_path / "scan.db")
    yield c
    c.close()


def _entry(total_output=570):
    return Entry(
        id="msg_1|req_1",
        date=datetime(2026, 8, 18, 20, 50, 59, tzinfo=timezone.utc),
        local_day="2026-08-18",
        model="claude-opus-5",
        input=2,
        output=total_output,
        cache_write=24_155,
        cache_read=16_203,
    )


def test_miss_returns_none(cache, tmp_path):
    assert cache.get("claude_code", tmp_path / "s.jsonl", 1.0, 10, 1) is None


def test_hit_roundtrips_entries(cache, tmp_path):
    p = tmp_path / "s.jsonl"
    cache.put("claude_code", p, 1.0, 10, 1, [_entry()])
    got = cache.get("claude_code", p, 1.0, 10, 1)
    assert got is not None
    assert len(got.entries) == 1
    assert got.entries[0].total == 40_930
    assert got.entries[0].local_day == "2026-08-18"
    assert got.entries[0].date == datetime(2026, 8, 18, 20, 50, 59, tzinfo=timezone.utc)


def test_changed_mtime_misses(cache, tmp_path):
    p = tmp_path / "s.jsonl"
    cache.put("claude_code", p, 1.0, 10, 1, [_entry()])
    assert cache.get("claude_code", p, 2.0, 10, 1) is None


def test_changed_size_misses(cache, tmp_path):
    p = tmp_path / "s.jsonl"
    cache.put("claude_code", p, 1.0, 10, 1, [_entry()])
    assert cache.get("claude_code", p, 1.0, 11, 1) is None


def test_parser_version_bump_invalidates(cache, tmp_path):
    p = tmp_path / "s.jsonl"
    cache.put("claude_code", p, 1.0, 10, 1, [_entry()])
    assert cache.get("claude_code", p, 1.0, 10, 2) is None


def test_empty_result_is_cached_not_treated_as_miss(cache, tmp_path):
    # A file with no assistant rows must be remembered as empty. Storing
    # nothing would re-parse it on every single refresh forever.
    p = tmp_path / "s.jsonl"
    cache.put("claude_code", p, 1.0, 10, 1, [])
    assert cache.get("claude_code", p, 1.0, 10, 1).entries == []


def test_providers_do_not_collide(cache, tmp_path):
    p = tmp_path / "s.jsonl"
    cache.put("claude_code", p, 1.0, 10, 1, [_entry()])
    assert cache.get("codex", p, 1.0, 10, 1) is None


def test_prune_drops_deleted_files(cache, tmp_path):
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    cache.put("claude_code", a, 1.0, 10, 1, [_entry()])
    cache.put("claude_code", b, 1.0, 10, 1, [_entry()])
    cache.prune("claude_code", {str(a)})
    assert cache.get("claude_code", a, 1.0, 10, 1) is not None
    assert cache.get("claude_code", b, 1.0, 10, 1) is None


def test_survives_reopen(tmp_path):
    db = tmp_path / "scan.db"
    p = tmp_path / "s.jsonl"
    first = ScanCache(db)
    first.put("claude_code", p, 1.0, 10, 1, [_entry()])
    first.close()
    second = ScanCache(db)
    assert second.get("claude_code", p, 1.0, 10, 1) is not None
    second.close()
