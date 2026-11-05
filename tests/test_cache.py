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


def test_only_the_days_asked_for_are_brought_back(cache, tmp_path):
    """A year of history sits in these blobs and a poll reads the last few
    weeks of it; the rest was rebuilt into objects to be looked past."""
    p = tmp_path / "s.jsonl"
    old = _entry()
    old.local_day = "2026-01-02"
    recent = _entry()
    recent.local_day = "2026-11-03"
    cache.put("claude_code", p, 1.0, 10, 1, [old, recent])

    assert len(cache.get("claude_code", p, 1.0, 10, 1).entries) == 2
    narrowed = cache.get("claude_code", p, 1.0, 10, 1, since="2026-11-01")
    assert [e.local_day for e in narrowed.entries] == ["2026-11-03"]

    # The row itself still holds everything: the window moves on.
    assert len(cache.previous("claude_code", p, 1).entries) == 2


def test_a_file_entirely_older_than_the_window_is_not_even_decoded(cache, tmp_path, monkeypatch):
    """A year of sessions sit in these rows; decoding them to throw all of it
    away was most of a poll."""
    from poketokenbar import cache as cache_module

    p = tmp_path / "old.jsonl"
    old = _entry()
    old.local_day = "2026-01-02"
    cache.put("claude_code", p, 1.0, 10, 1, [old])

    decoded = []
    real = cache_module._decode
    monkeypatch.setattr(cache_module, "_decode",
                        lambda raw, since=None: (decoded.append(raw), real(raw, since))[1])

    blob = cache.get("claude_code", p, 1.0, 10, 1, since="2026-11-01")
    assert blob.entries == []
    assert decoded == ["[]"], "the stored entries were decoded anyway"

    # Asked for without a window, the row still reads in full.
    blob = cache.get("claude_code", p, 1.0, 10, 1)
    assert len(blob.entries) == 1


def test_rows_written_before_the_column_existed_are_filled_in(tmp_path):
    """An old file never changes, so it would never be rewritten — and would
    be decoded on every poll for ever."""
    import sqlite3

    from poketokenbar.cache import ScanCache

    path = tmp_path / "scan.db"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE blobs (provider TEXT NOT NULL, path TEXT NOT NULL, mtime REAL"
        " NOT NULL, size INTEGER NOT NULL, parser_version INTEGER NOT NULL, entries"
        " TEXT NOT NULL, PRIMARY KEY (provider, path));"
    )
    db.execute(
        "INSERT INTO blobs VALUES ('claude_code', '/x.jsonl', 1.0, 10, 1, ?)",
        ('[{"id": "a", "date": "2026-01-02T00:00:00+00:00", "local_day": "2026-01-02",'
         ' "model": "m", "input": 1, "output": 0, "cache_write": 0, "cache_read": 0,'
         ' "explicit_cost": null, "cost_is_estimate": false, "cost_unavailable": false}]',),
    )
    db.commit()
    db.close()

    cache = ScanCache(path)
    assert cache._db.execute(
        "SELECT last_day FROM blobs").fetchone()[0] == "2026-01-02"
