import json

from poketokenbar.daemon import Daemon
from poketokenbar.models import DailyUsage, ProviderEnrichment


class FakeProvider:
    id = "fake"
    display_name = "Fake"
    reports_cost = True

    def __init__(self, daily=None, boom=False, pid="fake"):
        self._daily = daily
        self._boom = boom
        self.id = pid

    def fetch_daily(self, today=None):
        if self._boom:
            raise RuntimeError("boom")
        return self._daily

    def fetch_enrichment(self):
        return ProviderEnrichment()


def _daemon(tmp_path, providers):
    return Daemon(
        state_path=tmp_path / "state.json",
        config_path=tmp_path / "config.json",
        cache=None,
        providers=providers,
    )


def test_poll_writes_state_file(tmp_path):
    d = _daemon(tmp_path, [FakeProvider(DailyUsage(date="2026-08-18", total_tokens=42))])
    d.poll_once()
    written = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert written["today"]["total_tokens"] == 42


def test_a_failing_provider_does_not_abort_the_poll(tmp_path):
    # Per-provider isolation: one bad parser must not zero the panel.
    d = _daemon(
        tmp_path,
        [
            FakeProvider(boom=True, pid="broken"),
            FakeProvider(DailyUsage(date="2026-08-18", total_tokens=7), pid="ok"),
        ],
    )
    payload = d.poll_once()
    assert payload["today"]["total_tokens"] == 7
    assert any("boom" in e for e in payload["errors"])


def test_provider_returning_none_contributes_nothing(tmp_path):
    d = _daemon(tmp_path, [FakeProvider(None)])
    payload = d.poll_once()
    assert payload["today"]["total_tokens"] == 0
    assert payload["errors"] == []


def test_reload_config_command_is_applied(tmp_path):
    from poketokenbar import commands

    spool = tmp_path / "spool"
    d = _daemon(tmp_path, [FakeProvider(DailyUsage(date="2026-08-18", total_tokens=42))])
    d.spool = spool
    (tmp_path / "config.json").write_text('{"show_tokens_in_menu": false}', encoding="utf-8")
    commands.enqueue("reload_config", {}, spool=spool)
    payload = d.poll_once()
    assert payload["panel"]["tokens_text"] == ""


# MARK: save transfer
#
# Import replaces a Pokedex, so what it writes, what it keeps, and what it can
# undo are all part of the command, not of the file format.


class _RecordingNotifier:
    def __init__(self):
        self.sent = []

    def transfer(self, key, language="en", subject=""):
        self.sent.append((key, language, subject))


def _store(tmp_path, tokens=999, dex=0):
    from poketokenbar.balance import Rarity
    from poketokenbar.companion import DexEntry
    from poketokenbar.companion_store import CompanionStore

    store = CompanionStore(save_path=tmp_path / "save" / "companion.json")
    store.state.used_since_install = tokens
    store.state.dex = [
        DexEntry(base_id=i, final_id=i, chain_order=[i], rarity=Rarity.COMMON)
        for i in range(1, dex + 1)
    ]
    store._persist()
    return store


def _transfer_daemon(tmp_path, store, notifier=None):
    d = Daemon(
        state_path=tmp_path / "state.json",
        config_path=tmp_path / "config.json",
        cache=None,
        providers=[],
        companion_store=store,
        notifier=notifier,
    )
    d.spool = tmp_path / "spool"
    return d


def test_import_writes_the_save_the_store_actually_reads(tmp_path):
    """It went to save.default_path() regardless of where the store persists,
    so the import landed in a file nothing read and the next persist undid it."""
    from poketokenbar import commands, save, transfer

    store = _store(tmp_path, tokens=999)
    d = _transfer_daemon(tmp_path, store)

    incoming = tmp_path / "export.json"
    transfer.export_to(incoming, _store(tmp_path / "other", tokens=42).state)
    commands.enqueue("import", {"path": str(incoming)}, spool=d.spool)
    d.poll_once()

    assert store.state.used_since_install == 42
    assert save.load(store.save_path).used_since_install == 42


def test_an_import_can_be_undone(tmp_path):
    from poketokenbar import commands, save, transfer

    store = _store(tmp_path, tokens=999)
    d = _transfer_daemon(tmp_path, store)

    incoming = tmp_path / "export.json"
    transfer.export_to(incoming, _store(tmp_path / "other", tokens=42).state)
    commands.enqueue("import", {"path": str(incoming)}, spool=d.spool)
    d.poll_once()

    commands.enqueue("restore", {}, spool=d.spool)
    d.poll_once()

    assert store.state.used_since_install == 999
    assert save.load(store.save_path).used_since_install == 999


def test_a_failed_import_is_reported_not_raised(tmp_path):
    from poketokenbar import commands

    store = _store(tmp_path, tokens=999)
    d = _transfer_daemon(tmp_path, store)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    commands.enqueue("import", {"path": str(bad)}, spool=d.spool)

    payload = d.poll_once()
    assert any("import" in e for e in payload["errors"])
    assert store.state.used_since_install == 999


def test_transfer_messages_are_localised(tmp_path):
    from poketokenbar import commands

    notifier = _RecordingNotifier()
    store = _store(tmp_path)
    d = _transfer_daemon(tmp_path, store, notifier)
    (tmp_path / "config.json").write_text('{"language": "ko"}', encoding="utf-8")
    d.config_values = {"language": "ko"}

    commands.enqueue("export", {"path": str(tmp_path / "out.json")}, spool=d.spool)
    d.poll_once()

    assert notifier.sent == [("save_exported", "ko", str(tmp_path / "out.json"))]


def test_the_state_describes_the_file_import_would_read(tmp_path):
    """The popup has no way to ask a question and wait, so what it needs to
    confirm an overwrite has to be in the snapshot it polls."""
    from poketokenbar import transfer

    store = _store(tmp_path, tokens=999, dex=3)
    d = _transfer_daemon(tmp_path, store)
    transfer.export_to(transfer.default_export_path(), _store(tmp_path / "o", tokens=42, dex=1).state)

    payload = d.poll_once()
    block = payload["transfer"]
    assert block["exists"] is True
    assert block["path"] == str(transfer.default_export_path())
    assert block["dex_count"] == 1
    assert block["used_since_install"] == 42
    assert block["exported_text"]
    assert block["can_undo"] is False


def test_the_state_says_when_there_is_nothing_to_import(tmp_path):
    d = _transfer_daemon(tmp_path, _store(tmp_path))
    block = d.poll_once()["transfer"]
    assert block["exists"] is False
    assert block["error"] == ""


def test_undo_is_only_offered_once_there_is_a_backup(tmp_path):
    from poketokenbar import commands, transfer

    store = _store(tmp_path, tokens=999)
    d = _transfer_daemon(tmp_path, store)
    assert d.poll_once()["transfer"]["can_undo"] is False

    incoming = tmp_path / "export.json"
    transfer.export_to(incoming, _store(tmp_path / "other", tokens=42).state)
    commands.enqueue("import", {"path": str(incoming)}, spool=d.spool)

    assert d.poll_once()["transfer"]["can_undo"] is True


def test_the_state_flags_an_import_that_would_lose_progress(tmp_path):
    """The whole complaint: the button restored an older export and a day of
    raising went with it. The popup can only warn if the daemon says so."""
    from poketokenbar import transfer

    store = _store(tmp_path, tokens=999, dex=4)
    d = _transfer_daemon(tmp_path, store)
    transfer.export_to(
        transfer.default_export_path(), _store(tmp_path / "o", tokens=10, dex=1).state
    )

    assert d.poll_once()["transfer"]["goes_backwards"] is True

    transfer.export_to(
        transfer.default_export_path(), _store(tmp_path / "o2", tokens=5000, dex=9).state
    )
    assert d.poll_once()["transfer"]["goes_backwards"] is False


def test_the_state_describes_what_the_undo_would_restore(tmp_path):
    """Undo overwrites the save too, so the popup has to be able to say what
    it would put back before someone reaches for it."""
    from poketokenbar import commands, transfer

    store = _store(tmp_path, tokens=999, dex=4)
    d = _transfer_daemon(tmp_path, store)
    incoming = tmp_path / "export.json"
    transfer.export_to(incoming, _store(tmp_path / "other", tokens=42, dex=1).state)
    commands.enqueue("import", {"path": str(incoming)}, spool=d.spool)

    block = d.poll_once()["transfer"]
    assert block["can_undo"] is True
    assert block["undo_dex_count"] == 4
    assert block["undo_used_text"]
    assert block["undo_taken_text"]
    # The backup holds more than the imported save, so restoring it gains
    # progress rather than losing it.
    assert block["undo_goes_backwards"] is False
