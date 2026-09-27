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


# MARK: the level-up mood lasts exactly one poll


def _grown_store(tmp_path):
    from poketokenbar.balance import Rarity
    from poketokenbar.companion import GrowthEvents, MonState
    from poketokenbar.companion_store import CompanionStore

    store = CompanionStore(save_path=tmp_path / "save" / "companion.json")
    store.state.active = MonState(
        base_id=4, path_ids=[4, 5], planned_path_ids=[4, 5], stage_index=1,
        rarity=Rarity.COMMON, total_forms=2)
    store.last_events = GrowthEvents(evolved_to=5)
    return store


def test_growth_events_are_cleared_even_with_notifications_off(tmp_path):
    """They are also what puts the companion in its level-up mood for one poll.

    Only the notifier cleared them, so with companion notifications switched
    off the mood stuck until the next thing grew.
    """
    store = _grown_store(tmp_path)
    d = _transfer_daemon(tmp_path, store)
    d.config_values["companion_notifications"] = False

    assert d.poll_once()["companion"]["display_state"] == "levelUp"
    assert store.last_events is None
    assert d.poll_once()["companion"]["display_state"] != "levelUp"


# MARK: a click is answered without re-reading the logs
#
# Pressing Buy, Use or a Pokedex cell used to wait for the whole poll: the
# two-second command check, then every provider's history, then whatever the
# network cost that time. That is the five seconds between the click and
# anything on screen changing.


class _CountingProvider(FakeProvider):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.scans = 0

    def fetch_daily(self, today=None):
        self.scans += 1
        return super().fetch_daily(today)


class _CountingLimits:
    def __init__(self):
        self.fetches = 0
        self.invalidated = 0
        self.last_error = ""
        self.offline = False

    def get(self):
        self.fetches += 1
        return None

    def invalidate(self):
        self.invalidated += 1


def _clicky_daemon(tmp_path):
    store = _store(tmp_path, tokens=10**9)
    provider = _CountingProvider(DailyUsage(date="2026-08-18", total_tokens=42))
    limits_source = _CountingLimits()
    d = Daemon(
        state_path=tmp_path / "state.json",
        config_path=tmp_path / "config.json",
        cache=None,
        providers=[provider],
        limits_source=limits_source,
        companion_store=store,
    )
    d.spool = tmp_path / "spool"
    return d, provider, limits_source, store, "rareCandy"


def test_a_buy_carries_its_quantity_through_the_spool(tmp_path):
    """The count is the only part of a bulk purchase that can go missing between
    the popup and the wallet."""
    from poketokenbar import commands

    d, _provider, _limits, store, key = _clicky_daemon(tmp_path)
    store.state.used_since_install = 10 ** 12
    d.poll_once()
    commands.enqueue("buy", {"key": key, "count": 6}, spool=d.spool)
    d.react()
    assert store.state.inventory.get(key, 0) == 6

    # A command from an older extension carries no count at all.
    commands.enqueue("buy", {"key": key}, spool=d.spool)
    d.react()
    assert store.state.inventory.get(key, 0) == 7


def test_a_buy_is_answered_from_the_last_scan(tmp_path):
    from poketokenbar import commands

    d, provider, limits_source, store, key = _clicky_daemon(tmp_path)
    d.poll_once()
    assert provider.scans == 1

    commands.enqueue("buy", {"key": key}, spool=d.spool)
    payload = d.react()

    assert payload is not None
    assert store.state.inventory.get(key, 0) == 1
    assert provider.scans == 1, "the logs had not changed; do not read them again"
    assert limits_source.fetches == 1, "and do not go near the network"
    # The token counts from that scan are still what the popup shows.
    assert payload["today"]["total_tokens"] == 42
    written = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert written["updated_at"] == payload["updated_at"]


def test_reacting_with_nothing_queued_writes_nothing(tmp_path):
    d, provider, _limits, _store, _key = _clicky_daemon(tmp_path)
    d.poll_once()
    before = (tmp_path / "state.json").stat().st_mtime_ns
    assert d.react() is None
    assert (tmp_path / "state.json").stat().st_mtime_ns == before


def test_a_refresh_still_reads_the_logs(tmp_path):
    from poketokenbar import commands

    d, provider, limits_source, _store, _key = _clicky_daemon(tmp_path)
    d.poll_once()
    commands.enqueue("refresh", {}, spool=d.spool)
    d.react()
    assert provider.scans == 2
    assert limits_source.invalidated == 1


def test_a_config_change_lands_before_the_rescan(tmp_path):
    """Language and toggles must not wait on a scan, but extra scan folders
    do need one — so the change is published first and the logs read after."""
    from poketokenbar import commands

    d, provider, _limits, _store, _key = _clicky_daemon(tmp_path)
    d.poll_once()
    (tmp_path / "config.json").write_text('{"language": "ko"}', encoding="utf-8")
    commands.enqueue("reload_config", {}, spool=d.spool)

    payload = d.react()
    assert payload["strings"]["home"] == "홈"
    assert provider.scans == 2


def test_the_first_command_before_any_poll_is_a_full_poll(tmp_path):
    from poketokenbar import commands

    d, provider, _limits, _store, key = _clicky_daemon(tmp_path)
    commands.enqueue("buy", {"key": key}, spool=d.spool)
    payload = d.react()
    assert provider.scans == 1
    assert payload["today"]["total_tokens"] == 42


def test_a_quick_answer_does_not_replay_the_limits(tmp_path):
    """Candy and the burn history ride on a fresh fetch. Rebuilding from the
    cached limits must not record the same sample or pay out twice."""
    from poketokenbar import commands, limits
    from poketokenbar.burn import BurnTracker

    class _StaticLimits(_CountingLimits):
        def get(self):
            self.fetches += 1
            return limits.parse({"limits": [{"kind": "session", "percent": 40}]})

    store = _store(tmp_path, tokens=10**9)
    burn = BurnTracker()
    d = Daemon(
        state_path=tmp_path / "state.json",
        config_path=tmp_path / "config.json",
        cache=None,
        providers=[],
        limits_source=_StaticLimits(),
        companion_store=store,
        burn_tracker=burn,
    )
    d.spool = tmp_path / "spool"
    d.poll_once()
    assert len(burn._samples["session"]) == 1

    commands.enqueue("represent", {"species_id": "none"}, spool=d.spool)
    payload = d.react()
    assert payload["limits"] is not None, "the cached limits are still shown"
    assert len(burn._samples["session"]) == 1


def test_an_offline_limits_fetch_is_reported_in_words(tmp_path):
    """The footer read `limits: <urlopen error [Errno -2] Name or service not
    known>` after every login while the network was still coming up."""
    d, _provider, limits_source, _store, _key = _clicky_daemon(tmp_path)
    limits_source.last_error = "<urlopen error [Errno -2] Name or service not known>"
    limits_source.offline = True
    d.config_values["language"] = "ko"

    payload = d.poll_once()
    assert payload["errors"] == ["한도: 네트워크에 연결할 수 없음"]

    limits_source.offline = False
    payload = d.poll_once()
    assert payload["errors"] == [
        "limits: <urlopen error [Errno -2] Name or service not known>"
    ]


def test_a_difficulty_change_reaches_the_shop_and_the_save(tmp_path):
    """The extension writes config.json and sends reload_config; the next buy
    in the same drain must already see the new price, and the save must carry
    the new growth difficulty."""
    from poketokenbar import balance, commands, save

    d, _provider, _limits, store, key = _clicky_daemon(tmp_path)
    d.poll_once()
    (tmp_path / "config.json").write_text(
        '{"growth_difficulty": 0.5, "shop_difficulty": 0.5}', encoding="utf-8")
    commands.enqueue("reload_config", {}, spool=d.spool)
    commands.enqueue("buy", {"key": key}, spool=d.spool)
    d.react()

    assert store.state.spent_tokens == balance.RARE_CANDY_PRICE // 2
    assert store.state.growth_difficulty == 0.5
    assert save.load(store.save_path).growth_difficulty == 0.5
