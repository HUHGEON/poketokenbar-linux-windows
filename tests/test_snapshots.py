"""Local restore points — ports SaveSnapshotTests.swift (upstream 13e3bf2)."""

import json
import time

import pytest

from poketokenbar import save, snapshots, transfer
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, MonState


def _state(tokens=1_000, dex=0, active=False):
    state = CompanionState(used_since_install=tokens)
    state.dex = [
        DexEntry(base_id=1, final_id=3, chain_order=[1, 2, 3], rarity=Rarity.COMMON)
        for _ in range(dex)
    ]
    if active:
        state.active = MonState(base_id=4, path_ids=[4, 5], planned_path_ids=[4, 5],
                                rarity=Rarity.RARE, total_forms=2)
    return state


@pytest.fixture
def save_path(tmp_path):
    path = tmp_path / "companion.json"
    save.save(_state(), path)
    return path


# --- taking them ------------------------------------------------------------


def test_a_snapshot_is_an_export_of_the_save(save_path):
    """The same envelope as an export, so a restore point can also be carried
    to another machine and imported there."""
    taken = snapshots.create(_state(tokens=5_000, dex=2), save_path)
    raw = json.loads(taken.path.read_text(encoding="utf-8"))
    assert raw["format"] == transfer.FORMAT
    assert transfer.decode(raw).used_since_install == 5_000
    assert taken.dex_count == 2 and taken.used_since_install == 5_000


def test_two_snapshots_in_one_second_do_not_overwrite_each_other(save_path):
    now = time.time()
    first = snapshots.create(_state(tokens=1), save_path, now)
    second = snapshots.create(_state(tokens=2), save_path, now)
    assert first.id != second.id
    assert {s.used_since_install for s in snapshots.listing(save_path)} == {1, 2}


def test_only_the_ten_newest_are_kept(save_path):
    now = time.time()
    for index in range(13):
        snapshots.create(_state(tokens=index), save_path, now - (13 - index) * 3600)
    kept = snapshots.listing(save_path)
    assert len(kept) == snapshots.KEEP
    # The newest survive; the three oldest are the ones dropped.
    assert [s.used_since_install for s in kept] == list(range(12, 2, -1))


def test_snapshots_are_listed_newest_first(save_path):
    now = time.time()
    snapshots.create(_state(tokens=1), save_path, now - 7200)
    snapshots.create(_state(tokens=2), save_path, now)
    assert [s.used_since_install for s in snapshots.listing(save_path)] == [2, 1]


def test_an_unreadable_snapshot_is_left_out_rather_than_offered(save_path):
    good = snapshots.create(_state(tokens=1), save_path)
    (snapshots.directory(save_path) / f"{snapshots.PREFIX}2026-01-01-000000.json").write_text(
        "{ this is not json", encoding="utf-8")
    assert [s.id for s in snapshots.listing(save_path)] == [good.id]


def test_a_save_belongs_to_its_own_restore_points(tmp_path):
    """A test save and the real one must not share snapshots, or restoring in
    one would hand over the other's progress."""
    mine = tmp_path / "companion.json"
    theirs = tmp_path / "other.json"
    snapshots.create(_state(tokens=1), mine)
    assert snapshots.listing(theirs) == []


# --- taking them automatically ----------------------------------------------


def test_the_first_automatic_snapshot_needs_something_worth_keeping(save_path):
    assert snapshots.auto(CompanionState(), save_path) is None
    assert snapshots.auto(_state(tokens=10), save_path) is not None


def test_automatic_snapshots_are_twelve_hours_apart(save_path):
    now = time.time()
    assert snapshots.auto(_state(tokens=1), save_path, now) is not None
    assert snapshots.auto(_state(tokens=2), save_path, now + 3600) is None
    assert snapshots.auto(_state(tokens=3), save_path, now + snapshots.MIN_INTERVAL) is not None
    assert [s.used_since_install for s in snapshots.listing(save_path)] == [3, 1]


# --- putting one back -------------------------------------------------------


def test_restoring_keeps_what_it_replaced_as_a_new_snapshot(save_path):
    old = snapshots.create(_state(tokens=100, dex=1), save_path)
    save.save(_state(tokens=900, dex=4), save_path)

    restored = snapshots.restore(old.id, save_path)
    assert restored.used_since_install == 100
    assert save.load(save_path).used_since_install == 100
    # The state that was replaced is still reachable.
    assert 900 in {s.used_since_install for s in snapshots.listing(save_path)}


def test_the_oldest_snapshot_can_still_be_restored_at_the_retention_limit(save_path):
    """The safety snapshot prunes the oldest file, which is the one being
    restored — so the selection is read before anything is written."""
    now = time.time()
    oldest = None
    for index in range(snapshots.KEEP):
        taken = snapshots.create(_state(tokens=index + 1), save_path,
                                 now - (snapshots.KEEP - index) * 3600)
        oldest = oldest or taken
    save.save(_state(tokens=10_000), save_path)
    assert snapshots.restore(oldest.id, save_path).used_since_install == 1


def test_restoring_something_that_is_not_there_is_refused(save_path):
    with pytest.raises(transfer.TransferError):
        snapshots.restore("companion-snapshot-1999-01-01-000000.json", save_path)


def test_a_restored_save_forgets_the_other_machines_bookkeeping(save_path):
    state = _state(tokens=100)
    state.claimed_today_tokens_by_provider = {"claude_code": 5}
    state.last_date = "2026-01-01"
    taken = snapshots.create(state, save_path)
    restored = snapshots.restore(taken.id, save_path)
    assert restored.claimed_today_tokens_by_provider is None
    assert restored.last_date == ""


# --- recovering a corrupt save ----------------------------------------------


def test_a_corrupt_save_is_rebuilt_from_the_newest_snapshot(save_path):
    snapshots.create(_state(tokens=42, dex=2), save_path)
    save_path.write_text("{ not a save", encoding="utf-8")

    recovered = save.load(save_path, recover=snapshots.latest_valid)
    assert recovered.used_since_install == 42 and len(recovered.dex) == 2
    # And the unreadable file is kept rather than thrown away.
    assert save_path.with_suffix(".json.corrupt").is_file()


def test_a_corrupt_save_with_no_snapshot_still_starts_fresh(save_path):
    save_path.write_text("{ not a save", encoding="utf-8")
    assert save.load(save_path, recover=snapshots.latest_valid).used_since_install == 0


def test_a_missing_save_is_a_fresh_start_not_a_recovery(save_path):
    snapshots.create(_state(tokens=42), save_path)
    save_path.unlink()
    assert save.load(save_path, recover=snapshots.latest_valid).used_since_install == 0


def test_the_store_recovers_on_its_own(tmp_path):
    from poketokenbar.companion_store import CompanionStore

    path = tmp_path / "companion.json"
    store = CompanionStore(save_path=path, api=None, sprite_store=None)
    store.state = _state(tokens=777)
    store.create_snapshot()
    path.write_text("{ ruined", encoding="utf-8")

    reopened = CompanionStore(save_path=path, api=None, sprite_store=None)
    assert reopened.state.used_since_install == 777


def test_the_store_lists_and_restores_its_own_snapshots(tmp_path):
    from poketokenbar.companion_store import CompanionStore

    store = CompanionStore(save_path=tmp_path / "companion.json", api=None, sprite_store=None)
    store.state = _state(tokens=500, dex=3)
    store.create_snapshot()
    store.state = _state(tokens=900)
    store._persist()

    rows = store.snapshot_rows()
    assert len(rows) == 1 and rows[0]["dex_count"] == 3
    assert "500" in rows[0]["summary"] or "3" in rows[0]["summary"]
    store.restore_snapshot(rows[0]["id"])
    assert store.state.used_since_install == 500


def test_the_listing_is_not_rebuilt_on_every_poll(tmp_path, monkeypatch):
    """The popup asks for this twice a second; reading ten files each time is
    work nobody asked for."""
    from poketokenbar import companion_store as module
    from poketokenbar.companion_store import CompanionStore

    store = CompanionStore(save_path=tmp_path / "companion.json", api=None, sprite_store=None)
    store.state = _state(tokens=500)
    store.create_snapshot()

    reads = []
    real = module.snapshots.listing
    monkeypatch.setattr(module.snapshots, "listing",
                        lambda path: (reads.append(path), real(path))[1])
    store.snapshot_rows()
    store.snapshot_rows()
    assert len(reads) == 1

    # Taking another one is exactly when the answer changes, so the next ask
    # reads again (create prunes, which reads too).
    store.create_snapshot()
    before = len(reads)
    store.snapshot_rows()
    store.snapshot_rows()
    assert len(reads) == before + 1


def test_a_store_built_without_a_path_still_has_one(tmp_path, monkeypatch):
    """save() falls back to the default path on its own, so a store built
    without one still had a file — but everything that has to *name* that file
    saw None and did nothing, which is how the daemon ran for a while taking no
    restore points at all."""
    from poketokenbar import companion_store as module
    from poketokenbar.companion_store import CompanionStore

    monkeypatch.setattr(module.save, "default_path", lambda: tmp_path / "companion.json")
    store = CompanionStore(api=None, sprite_store=None)
    assert store.save_path == tmp_path / "companion.json"

    store.state = _state(tokens=1234)
    store._persist()
    assert [row["id"] for row in store.snapshot_rows()], "a restore point was taken"
