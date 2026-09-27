"""poketokend — polls providers, writes state.json, drains commands."""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import commands, config, l10n, platform_paths, save, state, transfer
from .companion_store import CompanionStore
from .burn import BurnTracker
from .notify import Notifier
from .status import StatusChecker
from .limits_source import LimitsSource
from .detail_loader import DetailLoader
from .pokeapi import PokeAPI
from .sprites import SpriteStore
from .cache import ScanCache
from .models import CostCoverage, DailyUsage

# How long a queued command waits before the daemon notices it. One glob of a
# near-empty directory, so checking often costs nothing; sleeping two seconds
# between checks was most of what made a click feel ignored.
COMMAND_POLL_SECONDS = 0.25

# Commands whose effect is not right until the logs have been read again: a
# refresh is a request for fresh numbers, and a config change can add scan
# folders. Everything else changes the save, not the logs.
RESCAN_COMMANDS = frozenset({"refresh", "reload_config"})


class Daemon:
    def __init__(
        self, state_path: Path, config_path: Path, cache, providers,
        limits_source=None, companion_store=None, notifier=None,
        burn_tracker=None, status_checker=None,
    ) -> None:
        self.state_path = state_path
        self.config_path = config_path
        self.cache = cache
        self.providers = providers
        # Injected so tests never reach the network. None disables limits.
        self.limits_source = limits_source
        self.companion_store = companion_store
        self.notifier = notifier
        self.burn = burn_tracker
        # Which account the last limits belonged to. Switching accounts changes
        # what the percentages mean, so cached limits and burn history from the
        # previous account must not carry over.
        self._account_uuid: str | None = None
        self.status_checker = status_checker
        self.spool: Path | None = None
        self.config_values = config.load(config_path)
        # What the last full poll found, so a command can be answered from it
        # without reading the logs again: per-provider daily usage, the
        # week/month periods, and the errors that scan produced.
        self._last_scan: tuple[dict, dict, list[str]] | None = None
        self._limit_status = None
        self._status_payload: dict | None = None
        self._status_error: str = ""
        self._last_full_poll_at: float = 0.0

    def custom_scan_roots(self, provider_id: str) -> str | None:
        """This provider's extra scan folders, as configured right now."""
        configured = self.config_values.get("custom_scan_roots")
        if not isinstance(configured, dict):
            return None
        value = configured.get(provider_id)
        return value if isinstance(value, str) and value.strip() else None

    def settings_payload(self) -> dict:
        """Provider rows for the settings page, with live extra-folder counts."""
        from . import scan_roots

        rows = []
        for provider in self.providers or []:
            raw = self.custom_scan_roots(provider.id) or ""
            curated = provider.curated_roots() if hasattr(provider, "curated_roots") else []
            rows.append(
                {
                    "id": provider.id,
                    "display_name": provider.display_name,
                    "custom_scan_roots": raw,
                    "matched_folders": scan_roots.surviving_extra_count(curated, raw)
                    if raw.strip()
                    else 0,
                }
            )
        return {"providers": rows}

    def _language(self) -> str:
        return str(self.config_values.get("language", "en"))

    def _save_path(self) -> Path:
        """The save the store actually persists to.

        Import used to write to `save.default_path()` regardless, so a store
        pointed anywhere else had its file left alone and the import undone by
        the next persist.
        """
        return self.companion_store.save_path or save.default_path()

    def _transfer_command(self, name: str, command: dict) -> None:
        """Run one export / import / undo, and say what happened."""
        store = self.companion_store
        args = command.get("args") or {}
        path = Path(args.get("path") or transfer.default_export_path())

        if name == "export":
            written = transfer.export_to(path, store.state)
            self._notify_transfer("save_exported", str(written))
            return

        if name == "import":
            store.state = transfer.import_from(path, target=self._save_path())
            message = "save_imported"
        else:
            store.state = transfer.restore_backup(self._save_path())
            message = "save_restored"

        # A save exported before profiles existed gets its individuals now.
        store.migrate_profiles()
        # The replaced save's pending announcements belong to progress that is
        # no longer there; firing them after the swap would narrate a hatch the
        # incoming save never had.
        store.last_events = None
        store.celebration = None
        self._notify_transfer(message)

    def _notify_transfer(self, key: str, subject: str = "") -> None:
        if self.notifier is not None:
            self.notifier.transfer(key, self._language(), subject)

    def transfer_payload(self) -> dict:
        """The export file the popup's Import button would read, described.

        Read every poll rather than on demand: the popup has no channel to ask
        a question and wait for an answer, so what it needs to show the
        confirmation must already be in the snapshot it polls.
        """
        described = transfer.describe(transfer.default_export_path())
        if self.companion_store is None:
            return described
        current = transfer.summary(self.companion_store.state)
        described["current_dex_count"] = current["dex_count"]
        described["current_used_since_install"] = current["used_since_install"]
        # The undo overwrites the save too, so it is described as fully as the
        # import is; a button that quietly restores a week-old backup is the
        # same trap in the other direction.
        # Restore points, so the settings page can list them without asking.
        described["snapshots"] = self.companion_store.snapshot_rows()
        undo = transfer.describe_backup(self._save_path())
        described["can_undo"] = undo["exists"]
        described["undo_taken_at"] = undo["taken_at"]
        described["undo_dex_count"] = undo["dex_count"]
        described["undo_used_since_install"] = undo["used_since_install"]
        return described

    def poll_once(self) -> dict:
        """One scheduled poll: act on queued commands, read the logs, publish."""
        errors: list[str] = []
        self._handle_commands(errors)
        return self._full_poll(errors)

    def react(self) -> dict | None:
        """Act on queued commands now, ahead of the next scheduled poll.

        A buy, a use or a pin changes the save, not the logs. Answering it
        used to mean the whole poll — a couple of seconds of Claude history
        on a large machine, plus whatever the network cost that time — so
        the popup sat unchanged long enough to look like the click was lost.
        Here the answer is a rebuild of the last snapshot with the new save,
        written at once; only a refresh or a config change reads the logs.
        """
        errors: list[str] = []
        handled = self._handle_commands(errors)
        if not handled:
            return None
        if "refresh" in handled or self._last_scan is None:
            return self._full_poll(errors)
        payload = self._publish(errors, fresh_limits=False)
        if handled & RESCAN_COMMANDS:
            # Published once already so the settings change lands at once;
            # the rescan is for anything the change did to the scan folders.
            payload = self._full_poll(list(errors))
        return payload

    def _sync_difficulty(self) -> None:
        """Hand the difficulty settings to the save.

        Run before anything reads a threshold or a price: at every drain, after
        a config reload, and after a transfer replaces the save — an imported
        save may have been earned at another difficulty, and it arrives with
        the default shop multiplier.
        """
        if self.companion_store is None:
            return
        self.companion_store.sync_difficulty(
            self.config_values.get("growth_difficulty", 1.0),
            self.config_values.get("shop_difficulty", 1.0),
        )

    def _handle_commands(self, errors: list[str]) -> set[str]:
        """Drain the spool. Returns the names of the commands acted on."""
        handled: set[str] = set()
        self._sync_difficulty()
        for command in commands.drain(spool=self.spool):
            name = command.get("name")
            handled.add(str(name))
            if name == "refresh":
                # Manual refresh: drop cached limits so the next fetch is live.
                if self.limits_source is not None:
                    self.limits_source.invalidate()
            elif name == "reload_config":
                self.config_values = config.load(self.config_path)
                self._sync_difficulty()
            elif name in ("export", "import", "restore") and self.companion_store is not None:
                try:
                    self._transfer_command(name, command)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
                self._sync_difficulty()
            elif name == "represent" and self.companion_store is not None:
                raw = (command.get("args") or {}).get("species_id")
                try:
                    species_id = None if raw in (None, "", "none") else int(raw)
                    message = self.companion_store.set_representative(species_id)
                    if self.notifier is not None:
                        self.notifier._send("PokeTokenBar", message)
                except (TypeError, ValueError) as exc:
                    errors.append(f"represent: {exc}")
            elif name == "inspect" and self.companion_store is not None:
                args = command.get("args") or {}
                raw = args.get("species_id")
                try:
                    species_id = None if raw in (None, "", "none") else int(raw)
                    self.companion_store.inspect(species_id, retry=bool(args.get("retry")))
                except (TypeError, ValueError) as exc:
                    errors.append(f"inspect: {exc}")
            elif name in ("snapshot", "restore_snapshot") and self.companion_store is not None:
                args = command.get("args") or {}
                try:
                    if name == "snapshot":
                        message = self.companion_store.create_snapshot()
                    else:
                        message = self.companion_store.restore_snapshot(
                            str(args.get("id") or ""))
                    if self.notifier is not None:
                        self.notifier._send("PokeTokenBar", message)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
            elif name in ("buy", "use") and self.companion_store is not None:
                args = command.get("args") or {}
                key = args.get("key", "")
                try:
                    # A missing or unreadable count is one, the old behaviour.
                    try:
                        count = max(1, int(args.get("count", 1)))
                    except (TypeError, ValueError):
                        count = 1
                    if name == "buy":
                        message = self.companion_store.buy(key, count)
                    else:
                        message = self.companion_store.use_item(key, count)
                    if self.notifier is not None:
                        self.notifier._send("PokeTokenBar", message)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
        return handled

    def _full_poll(self, errors: list[str]) -> dict:
        """Read the logs, refresh limits and status, then publish."""
        scan_errors: list[str] = []
        daily_by_provider: dict[str, DailyUsage] = {}
        for provider in self.providers:
            try:
                daily = provider.fetch_daily()
            except Exception as exc:  # per-provider isolation
                scan_errors.append(f"{provider.id}: {exc}")
                continue
            if daily is not None:
                daily_by_provider[provider.id] = daily

        periods: dict = {}
        for provider in self.providers:
            fetch_periods = getattr(provider, "fetch_periods", None)
            if fetch_periods is None:
                continue
            try:
                result = fetch_periods()
            except Exception as exc:
                scan_errors.append(f"{provider.id} periods: {exc}")
                continue
            for key in ("week", "month"):
                bucket = periods.setdefault(
                    key, {"tokens": 0, "cost": 0.0, "coverage": CostCoverage()})
                bucket["tokens"] += result[key]["tokens"]
                bucket["cost"] += result[key]["cost"]
                if result[key].get("coverage") is not None:
                    bucket["coverage"].merge(result[key]["coverage"])
            # This month by day, summed across providers. The axis is the union
            # of theirs, so one whose scan straddled midnight cannot cut
            # everyone else's last day.
            daily = periods.setdefault("month_daily", {})
            for day, row in (result.get("month_daily") or {}).items():
                bucket = daily.setdefault(
                    day, {"tokens": 0, "cost": 0.0, "coverage": CostCoverage()})
                bucket["tokens"] += row["tokens"]
                bucket["cost"] += row["cost"]
                bucket["coverage"].merge(row["coverage"])
        self._last_scan = (daily_by_provider, periods, scan_errors)
        self._last_full_poll_at = time.monotonic()

        self._limit_status = None
        if self.limits_source is not None:
            # Best effort: limits failing hides that section but must never
            # affect the token counts, which come from local logs.
            limit_status = self.limits_source.get()
            if limit_status is not None and limit_status.account:
                uuid = limit_status.account.get("uuid") or ""
                if self._account_uuid is not None and uuid != self._account_uuid:
                    # A different account's utilization is a different scale;
                    # a slope fitted across the switch would be meaningless.
                    if self.burn is not None:
                        self.burn = type(self.burn)()
                    self.limits_source.invalidate()
                    limit_status = self.limits_source.get()
                self._account_uuid = uuid
            self._limit_status = limit_status

        self._status_payload = None
        self._status_error = ""
        if self.status_checker is not None and self.config_values.get(
            "status_checks_enabled", True
        ):
            try:
                self._status_payload = self.status_checker.get()
            except Exception as exc:
                self._status_error = f"status: {exc}"

        return self._publish(errors, fresh_limits=True)

    def _limits_error(self, language: str) -> str:
        source = self.limits_source
        if source is None or not source.last_error:
            return ""
        if getattr(source, "offline", False):
            # The socket library's wording ("Name or service not known") is
            # what used to land in the footer, right after every login,
            # while the network was still coming up.
            return l10n.t("limits_offline", language)
        return f"limits: {source.last_error}"

    def _publish(self, command_errors: list[str], *, fresh_limits: bool) -> dict:
        """Build state.json from the last scan and the save as it is now.

        `fresh_limits` says the limits were just fetched, so candy, the burn
        history and the threshold notifications may act on them. A publish
        that only re-reads the save must not: it would record the same
        utilization sample twice and hand out candy for progress it has
        already paid for.
        """
        daily_by_provider, periods, scan_errors = self._last_scan or ({}, {}, [])
        errors = list(command_errors) + list(scan_errors)
        language = str(self.config_values.get("language", "en"))
        limit_status = self._limit_status
        limits_error = self._limits_error(language)
        if limits_error:
            errors.append(limits_error)

        companion_payload = None
        if self.companion_store is not None:
            try:
                # One language, not two. The catalogue reads config while the
                # companion reads the save, so they must be kept in step or the
                # popup renders half-translated.
                self.companion_store.state.language = language
                self.companion_store.enrich_profiles()
                self.companion_store.update(
                    {pid: d.total_tokens for pid, d in daily_by_provider.items()}
                )
                today_total = sum(x.total_tokens for x in daily_by_provider.values())
                warn = float(self.config_values.get("warn_threshold", 80))
                limit_warning = False
                if limit_status is not None and limit_status.session is not None:
                    limit_warning = limit_status.session.utilization >= warn
                companion_payload = self.companion_store.payload(
                    today_tokens=today_total, limit_warning=limit_warning
                )
                # Candy and notifications ride on fresh limits.
                if fresh_limits and limit_status is not None:
                    windows = {}
                    # When each window resets, so a grant can tell a window that
                    # has rolled over from one that simply stayed full.
                    epochs: dict[str, str | None] = {}
                    if limit_status.session is not None:
                        windows["session"] = limit_status.session.utilization
                        epochs["session"] = limit_status.session.resets_at
                    if limit_status.weekly is not None:
                        windows["weekly"] = limit_status.weekly.utilization
                        epochs["weekly"] = limit_status.weekly.resets_at
                    if self.burn is not None:
                        for kind, utilization in windows.items():
                            self.burn.record(kind, utilization)
                    self.companion_store.grant_candy(windows, epochs)
                    if self.notifier is not None and self.config_values.get(
                        "limit_notifications", True
                    ):
                        self.notifier.limits(
                            windows,
                            float(self.config_values.get("warn_threshold", 80)),
                            float(self.config_values.get("crit_threshold", 95)),
                            language,
                        )
                if self.notifier is not None and self.config_values.get(
                    "companion_notifications", True
                ):
                    self.notifier.companion(
                        self.companion_store.last_events,
                        companion_payload.get("name"),
                        language,
                        shiny=bool(companion_payload.get("is_shiny")),
                        disguise=self.companion_store.disguise_name(),
                        shiny_odds=self.companion_store.shiny_odds(),
                    )
                # Cleared whether or not it was announced. These events are
                # also what puts the companion in its level-up mood for exactly
                # one poll, and with companion notifications switched off
                # nothing else ever cleared them — the mood stuck until the
                # next thing grew.
                self.companion_store.last_events = None
            except Exception as exc:
                # The companion is cosmetic; never let it break the numbers.
                errors.append(f"companion: {exc}")

        if self._status_error:
            errors.append(self._status_error)

        dex_rows = self.companion_store.dex_payload() if self.companion_store else None
        payload = state.build(
            daily_by_provider,
            self.config_values,
            errors,
            limit_status=limit_status,
            limits_freshness={
                "stale": getattr(self.limits_source, "stale", False),
                "updated_at": getattr(self.limits_source, "updated_at", None),
            },
            companion_payload=companion_payload,
            shop_payload=self.companion_store.shop_payload() if self.companion_store else None,
            bag_payload=self.companion_store.bag_payload() if self.companion_store else None,
            dex_payload=dex_rows,
            catch_log=self.companion_store.catch_log_payload() if self.companion_store else None,
            rarity_counts=self.companion_store.rarity_counts() if self.companion_store else None,
            catch_counts=self.companion_store.catch_rarity_counts() if self.companion_store else None,
            periods=periods,
            burn=self.burn.payload() if self.burn is not None else None,
            provider_status=self._status_payload,
            celebration=self.companion_store.celebration if self.companion_store else None,
            settings=self.settings_payload(),
            transfer=self.transfer_payload(),
            detail=self.companion_store.detail_payload(dex_rows) if self.companion_store else None,
            provider_names={p.id: p.display_name for p in self.providers or []},
        )
        state.write(self.state_path, payload)
        # Cleared after publishing so the banner shows once rather than
        # persisting until the next hatch.
        if self.companion_store is not None:
            self.companion_store.celebration = None
        return payload

    def run(self) -> None:
        while True:
            self.poll_once()
            # Between polls, watch the spool and answer commands as they land.
            # The deadline is measured from the last full poll rather than
            # from here, so a refresh command (which is a full poll) restarts
            # the interval instead of being followed by a second scan.
            while True:
                interval = int(self.config_values.get("refresh_interval", 120))
                if time.monotonic() - self._last_full_poll_at >= interval:
                    break
                time.sleep(COMMAND_POLL_SECONDS)
                if self._has_commands():
                    self.react()
                elif self._details_arrived():
                    # Rebuilt from the last scan: details change what the
                    # popup shows, not what the logs say.
                    self._publish([], fresh_limits=False)

    def _details_arrived(self) -> bool:
        loader = getattr(self.companion_store, "detail_loader", None)
        return loader is not None and self._last_scan is not None and loader.take_changed()

    def _has_commands(self) -> bool:
        spool = self.spool or commands.spool_dir()
        return spool.is_dir() and any(spool.glob("*.json"))


def _companion_store() -> CompanionStore:
    api = PokeAPI()
    return CompanionStore(api=api, sprite_store=SpriteStore(), detail_loader=DetailLoader(api))


def main() -> int:
    from . import providers as provider_registry

    cache = ScanCache(platform_paths.cache_base() / "poketokenbar" / "scan.db")
    daemon = Daemon(
        state_path=state.default_path(),
        config_path=config.default_path(),
        cache=cache,
        providers=None,  # replaced below, once the daemon can answer for its config
        limits_source=LimitsSource(),
        companion_store=_companion_store(),
        notifier=Notifier(),
        burn_tracker=BurnTracker(),
        status_checker=StatusChecker(),
    )
    # The daemon owns the live config, so it is what answers the providers'
    # extra-folders lookup — reading it per call, not once at startup.
    daemon.providers = provider_registry.build(
        cache=cache, custom_roots=daemon.custom_scan_roots
    )
    try:
        daemon.run()
    except KeyboardInterrupt:
        return 0
    finally:
        cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
