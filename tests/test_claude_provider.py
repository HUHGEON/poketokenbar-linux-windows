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
    original = path.stat()

    cache = ScanCache(tmp_path / "cache" / "scan.db")
    provider = ClaudeProvider(cache=cache, home=home)
    assert provider.fetch_daily().total_tokens == 40_930

    path.write_bytes(b"x" * original.st_size)  # same size, different bytes
    os.utime(path, (original.st_atime, original.st_mtime))
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


def test_a_log_is_read_without_keeping_its_pages(tmp_path, monkeypatch):
    """Four gigabytes of sessions read into the page cache showed up as the
    daemon's own memory in every system monitor."""
    import os

    from poketokenbar.providers import base, claude

    advised = []
    real = os.posix_fadvise

    def spy(fd, offset, length, advice):
        advised.append(advice)
        return real(fd, offset, length, advice)

    monkeypatch.setattr(os, "posix_fadvise", spy)
    path = tmp_path / "session.jsonl"
    path.write_text("{}\n", encoding="utf-8")

    claude.parse_file(path)
    assert advised == [os.POSIX_FADV_DONTNEED]

    # A platform without it still reads the file.
    monkeypatch.delattr(os, "posix_fadvise")
    with base.streamed(path) as handle:
        assert handle.read() == "{}\n"


# MARK: resuming an append-only log (upstream 8f74054)


def _record(when, *, msg_id, req, output=570):
    return json.dumps({
        "type": "assistant",
        "timestamp": when.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "requestId": req,
        "message": {
            "id": msg_id,
            "model": "claude-opus-5",
            "usage": {"input_tokens": 2, "output_tokens": output,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        },
    }) + "\n"


def test_an_appended_session_is_read_from_where_it_stopped(home, tmp_path, monkeypatch):
    """The session being written to is the one file that changes every poll,
    and it was re-read from byte zero each time."""
    from poketokenbar.providers import claude as module

    root = home / ".claude" / "projects" / "proj"
    root.mkdir(parents=True)
    log = root / "a.jsonl"
    now = datetime.now().astimezone()
    log.write_text(_record(now, msg_id="m1", req="r1"), encoding="utf-8")

    cache = ScanCache(tmp_path / "cache" / "scan.db")
    provider = ClaudeProvider(cache=cache, home=home)
    assert provider.fetch_daily().total_tokens == 572

    read_from = []
    real = module.parse_from
    monkeypatch.setattr(module, "parse_from",
                        lambda path, offset=0: (read_from.append(offset), real(path, offset))[1])

    with log.open("a", encoding="utf-8") as fh:
        fh.write(_record(now, msg_id="m2", req="r2", output=1_570))
    provider.release_scan()
    assert provider.fetch_daily().total_tokens == 572 + 1_572
    assert read_from == [len(_record(now, msg_id="m1", req="r1"))], \
        "the whole file was read again"
    cache.close()


def test_a_rewritten_file_is_read_from_the_start_even_when_it_grew(home, tmp_path):
    """Appending and rewriting longer look the same from the size alone; the
    bytes before the resume point are what tell them apart."""
    root = home / ".claude" / "projects" / "proj"
    root.mkdir(parents=True)
    log = root / "a.jsonl"
    now = datetime.now().astimezone()
    log.write_text(_record(now, msg_id="m1", req="r1"), encoding="utf-8")

    cache = ScanCache(tmp_path / "cache" / "scan.db")
    provider = ClaudeProvider(cache=cache, home=home)
    assert provider.fetch_daily().total_tokens == 572

    # Same single record, different content, one byte longer.
    log.write_text(_record(now, msg_id="m9", req="r9", output=1_570), encoding="utf-8")
    provider.release_scan()
    assert provider.fetch_daily().total_tokens == 1_572, "the old entry was kept"
    cache.close()


def test_a_half_written_line_is_picked_up_once_it_is_whole(home, tmp_path):
    root = home / ".claude" / "projects" / "proj"
    root.mkdir(parents=True)
    log = root / "a.jsonl"
    now = datetime.now().astimezone()
    whole = _record(now, msg_id="m1", req="r1")
    log.write_text(whole + '{"type":"assistant","timestamp":"', encoding="utf-8")

    cache = ScanCache(tmp_path / "cache" / "scan.db")
    provider = ClaudeProvider(cache=cache, home=home)
    assert provider.fetch_daily().total_tokens == 572, "the fragment was counted"

    log.write_text(whole + _record(now, msg_id="m2", req="r2", output=1_570), encoding="utf-8")
    provider.release_scan()
    assert provider.fetch_daily().total_tokens == 572 + 1_572
    cache.close()


def test_the_session_ledger_covers_the_whole_file_after_a_tail_read(home, tmp_path):
    """Claude's cost ledger is a running total for the session, so it cannot
    be applied to the tail alone."""
    root = home / ".claude" / "projects" / "proj"
    root.mkdir(parents=True)
    log = root / "a.jsonl"
    now = datetime.now().astimezone()
    log.write_text(_record(now, msg_id="m1", req="r1"), encoding="utf-8")

    cache = ScanCache(tmp_path / "cache" / "scan.db")
    provider = ClaudeProvider(cache=cache, home=home)
    provider.fetch_daily()

    ledger = json.dumps({
        "type": "cost-state",
        "totalCostUSD": 9.0,
        "modelUsage": {"claude-opus-5": {"costUSD": 9.0}},
    }) + "\n"
    with log.open("a", encoding="utf-8") as fh:
        fh.write(_record(now, msg_id="m2", req="r2") + ledger)
    provider.release_scan()

    entries = provider.scan_entries()
    assert len(entries) == 2
    assert sum(e.explicit_cost or 0 for e in entries) == pytest.approx(9.0), \
        "the reported total was split over the tail only"
    cache.close()
