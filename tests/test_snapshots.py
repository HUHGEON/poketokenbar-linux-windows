"""Local save recovery never reaches the user's real data directory."""

import json

import pytest

from poketokenbar import save, transfer
from poketokenbar.companion import CompanionState
from poketokenbar.companion_store import CompanionStore


def test_regular_save_creates_snapshot_and_throttles_following_writes(tmp_path):
    from poketokenbar import snapshots

    path = tmp_path / "companion.json"
    state = CompanionState(used_since_install=42)
    save.save(state, path)
    state.used_since_install = 99
    save.save(state, path)
    rows = snapshots.list_snapshots(path)
    assert len(rows) == 1
    assert rows[0]["used_since_install"] == 42
    assert save.load(path).used_since_install == 99


def test_snapshot_collision_retention_and_foreign_save_isolation(tmp_path):
    from poketokenbar import snapshots

    path = tmp_path / "a.json"
    for amount in range(12):
        snapshots.create_snapshot(CompanionState(used_since_install=amount), path, now=100 + amount)
    rows = snapshots.list_snapshots(path)
    assert len(rows) == 10
    assert rows[0]["used_since_install"] == 11
    assert rows[-1]["used_since_install"] == 2
    one = snapshots.create_snapshot(CompanionState(used_since_install=12), path, now=200)
    two = snapshots.create_snapshot(CompanionState(used_since_install=13), path, now=200)
    assert one["id"] != two["id"]
    assert snapshots.list_snapshots(tmp_path / "b.json") == []


def test_corruption_recovers_newest_valid_snapshot_and_preserves_corrupt_bytes(tmp_path):
    from poketokenbar import snapshots

    path = tmp_path / "save.json"
    snapshots.create_snapshot(CompanionState(used_since_install=123), path, now=10)
    newest = snapshots.create_snapshot(CompanionState(used_since_install=456), path, now=20)
    (snapshots.directory(path) / newest["id"]).write_text("{bad")
    path.write_text("{torn save")
    restored = save.load(path)
    assert restored.used_since_install == 123
    assert path.with_suffix(".json.corrupt").read_text() == "{torn save"
    assert any("snapshot" in note for note in save.last_repairs)
    assert save.load(path).used_since_install == 123


def test_snapshot_restore_backs_up_current_and_rebases_local_usage_and_grants(tmp_path):
    store = CompanionStore(save_path=tmp_path / "save.json")
    store.state.used_since_install = 123
    old = store.create_snapshot()
    store.state.used_since_install = 999
    store.state.language = "ko"
    store.state.claimed_today_tokens_by_provider = {"codex": 999}
    store.state.candy_feature_seeded = True
    store.state.candy_grant_tier = {"limit:weekly": 2}
    store.state.candy_window_epoch = {"limit:weekly": "2026-10-10"}
    store.restore_snapshot(old["id"])
    assert store.state.used_since_install == 123
    assert store.state.language == "ko"
    assert store.state.claimed_today_tokens_by_provider is None
    assert store.state.candy_grant_tier == {"limit:weekly": 2}
    assert store.state.candy_window_epoch == {"limit:weekly": "2026-10-10"}
    assert any(row["used_since_install"] == 999 for row in store.snapshots_payload())
    store.update({"codex": 1500}, today="2026-10-04")
    assert store.state.used_since_install == 123


def test_snapshot_restore_rejects_path_escape_without_mutation(tmp_path):
    store = CompanionStore(save_path=tmp_path / "save.json")
    store.state.used_since_install = 123
    with pytest.raises(transfer.TransferError):
        store.restore_snapshot("../../save.json")
    assert store.state.used_since_install == 123


def test_import_preserves_local_language_and_prevents_same_window_candy_regrant(tmp_path):
    current = CompanionState(language="ko", candy_feature_seeded=True)
    current.candy_grant_tier = {"limit:weekly": 2}
    current.candy_window_epoch = {"limit:weekly": "2026-10-10"}
    path = tmp_path / "save.json"
    save.save(current, path)
    exported = tmp_path / "export.json"
    transfer.export_to(exported, CompanionState(language="ja"))
    restored = transfer.import_from(exported, path)
    assert restored.language == "ko"
    assert restored.candy_grant_tier == {"limit:weekly": 2}
    assert restored.candy_window_epoch == {"limit:weekly": "2026-10-10"}


def test_snapshot_failure_does_not_lose_successful_save(tmp_path, monkeypatch):
    from poketokenbar import snapshots

    def unavailable(*args, **kwargs):
        raise OSError("read-only backup directory")

    monkeypatch.setattr(snapshots, "auto_snapshot", unavailable)
    path = tmp_path / "save.json"
    save.save(CompanionState(used_since_install=321), path)
    assert json.loads(path.read_text())["used_since_install"] == 321
