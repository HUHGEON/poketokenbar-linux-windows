import json

import pytest

from poketokenbar import save, transfer
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry


def _state(dex=2, tokens=1234):
    s = CompanionState()
    s.used_since_install = tokens
    s.dex = [
        DexEntry(base_id=i, final_id=i, chain_order=[i], rarity=Rarity.COMMON)
        for i in range(1, dex + 1)
    ]
    s.inventory = {"rareCandy": 3}
    return s


def test_roundtrip_preserves_progress(tmp_path):
    path = tmp_path / "export.json"
    transfer.export_to(path, _state())
    target = tmp_path / "companion.json"
    restored = transfer.import_from(path, target=target)
    assert restored.used_since_install == 1234
    assert len(restored.dex) == 2
    assert restored.inventory == {"rareCandy": 3}


def test_export_envelope_carries_provenance(tmp_path):
    path = tmp_path / "export.json"
    transfer.export_to(path, _state())
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["format"] == transfer.FORMAT
    assert raw["format_version"] == transfer.FORMAT_VERSION
    assert raw["device"]
    assert raw["exported_at"] > 0


def test_export_is_atomic(tmp_path):
    path = tmp_path / "export.json"
    transfer.export_to(path, _state())
    assert list(tmp_path.iterdir()) == [path]


def test_importing_a_foreign_file_is_refused(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(transfer.TransferError):
        transfer.import_from(path, target=tmp_path / "companion.json")


def test_importing_a_future_version_is_refused(tmp_path):
    # Silently dropping fields we cannot read would lose progress invisibly.
    path = tmp_path / "future.json"
    path.write_text(
        json.dumps({"format": transfer.FORMAT, "format_version": 99, "save": {}}),
        encoding="utf-8",
    )
    with pytest.raises(transfer.TransferError):
        transfer.import_from(path, target=tmp_path / "companion.json")


def test_importing_corrupt_json_is_refused(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(transfer.TransferError):
        transfer.import_from(path, target=tmp_path / "companion.json")


def test_a_refused_import_leaves_the_existing_save_untouched(tmp_path):
    target = tmp_path / "companion.json"
    save.save(_state(dex=5, tokens=999), target)

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"format": "something-else"}), encoding="utf-8")
    with pytest.raises(transfer.TransferError):
        transfer.import_from(bad, target=target)

    assert save.load(target).used_since_install == 999


def test_import_backs_up_the_previous_save(tmp_path):
    target = tmp_path / "companion.json"
    save.save(_state(dex=5, tokens=999), target)

    incoming = tmp_path / "export.json"
    transfer.export_to(incoming, _state(dex=1, tokens=1))
    transfer.import_from(incoming, target=target)

    kept = transfer.backups(target)
    assert len(kept) == 1
    assert save.load(kept[0]).used_since_install == 999
    assert save.load(target).used_since_install == 1


def test_a_second_import_does_not_destroy_the_first_backup(tmp_path):
    """The fixed backup name meant importing twice lost the original save.

    Which is precisely the case someone hits: import the wrong file, then
    import again trying to fix it, and the only copy of what they started with
    is gone.
    """
    target = tmp_path / "companion.json"
    save.save(_state(dex=5, tokens=999), target)

    for tokens in (1, 2):
        incoming = tmp_path / f"export-{tokens}.json"
        transfer.export_to(incoming, _state(dex=1, tokens=tokens))
        transfer.import_from(incoming, target=target)

    kept = transfer.backups(target)
    assert len(kept) == 2
    assert {save.load(b).used_since_install for b in kept} == {999, 1}


def test_backups_are_capped(tmp_path):
    target = tmp_path / "companion.json"
    save.save(_state(tokens=1), target)
    incoming = tmp_path / "export.json"
    transfer.export_to(incoming, _state(dex=1, tokens=1))

    for _ in range(transfer.KEEP_BACKUPS + 3):
        transfer.import_from(incoming, target=target)

    assert len(transfer.backups(target)) == transfer.KEEP_BACKUPS


def test_an_import_that_cannot_be_backed_up_is_refused(tmp_path, monkeypatch):
    """The backup is the only way back, so proceeding without one is worse
    than not importing at all."""
    from pathlib import Path as _Path

    target = tmp_path / "companion.json"
    save.save(_state(dex=5, tokens=999), target)
    incoming = tmp_path / "export.json"
    transfer.export_to(incoming, _state(dex=1, tokens=1))

    def refuse(self, data):
        raise OSError("read-only file system")

    monkeypatch.setattr(_Path, "write_bytes", refuse)
    with pytest.raises(transfer.TransferError):
        transfer.import_from(incoming, target=target)

    assert save.load(target).used_since_install == 999


def test_import_does_not_carry_the_other_machine_baseline(tmp_path):
    """`claimed_today_tokens_by_provider` says how far *this* machine's logs
    have been counted, so importing it either re-credits a whole day or
    swallows real usage, depending on which machine had read further."""
    exported = _state()
    exported.claimed_today_tokens_by_provider = {"claude_code": 5_000_000}
    exported.last_date = "2020-01-01"
    path = tmp_path / "export.json"
    transfer.export_to(path, exported)

    restored = transfer.import_from(path, target=tmp_path / "companion.json")

    # None is the "seed from the next snapshot, grant nothing" sentinel.
    assert restored.claimed_today_tokens_by_provider is None
    assert restored.last_date == ""
    # Progress itself still travels.
    assert restored.used_since_install == 1234


def test_restore_puts_the_previous_save_back(tmp_path):
    target = tmp_path / "companion.json"
    save.save(_state(dex=5, tokens=999), target)

    incoming = tmp_path / "export.json"
    transfer.export_to(incoming, _state(dex=1, tokens=1))
    transfer.import_from(incoming, target=target)
    assert save.load(target).used_since_install == 1

    restored = transfer.restore_backup(target)
    assert restored.used_since_install == 999
    assert save.load(target).used_since_install == 999


def test_restore_can_itself_be_undone(tmp_path):
    target = tmp_path / "companion.json"
    save.save(_state(dex=5, tokens=999), target)
    incoming = tmp_path / "export.json"
    transfer.export_to(incoming, _state(dex=1, tokens=1))
    transfer.import_from(incoming, target=target)

    transfer.restore_backup(target)
    assert save.load(target).used_since_install == 999
    transfer.restore_backup(target)
    assert save.load(target).used_since_install == 1


def test_restore_without_a_backup_says_so(tmp_path):
    with pytest.raises(transfer.TransferError):
        transfer.restore_backup(tmp_path / "companion.json")


def test_describe_reports_what_is_in_an_export(tmp_path):
    path = tmp_path / "export.json"
    transfer.export_to(path, _state(dex=4, tokens=50))

    described = transfer.describe(path)
    assert described["exists"] is True
    assert described["error"] is None
    assert described["dex_count"] == 4
    assert described["used_since_install"] == 50
    assert described["items"] == 3
    assert described["exported_at"] > 0
    assert described["device"]


def test_describe_reports_a_missing_file_rather_than_raising(tmp_path):
    described = transfer.describe(tmp_path / "nothing.json")
    assert described["exists"] is False
    assert described["error"] is None
    assert described["dex_count"] is None


def test_describe_reports_a_foreign_file_rather_than_raising(tmp_path):
    path = tmp_path / "other.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    described = transfer.describe(path)
    assert described["exists"] is True
    assert described["error"]


def test_the_export_path_is_the_same_one_the_ui_offers():
    """Both sides read it from here; a second copy in the extension is how the
    popup ends up describing a different file from the one it imports."""
    assert transfer.default_export_path().name == "poketokenbar-save.json"


def test_summary_describes_progress_for_the_overwrite_prompt():
    s = transfer.summary(_state(dex=4, tokens=50))
    assert s["dex_count"] == 4
    assert s["used_since_install"] == 50
    assert s["items"] == 3


def test_suggested_filename_is_dated():
    assert transfer.suggested_filename().startswith("poketokenbar-save-")
    assert transfer.suggested_filename().endswith(".json")
