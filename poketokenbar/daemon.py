"""poketokend — polls providers, writes state.json, drains commands."""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import balance, commands, config, platform_paths, save, state, transfer
from .companion_store import CompanionStore
from . import autostart
from . import updater as updater_module
from . import burn as burn_module
from .burn import BurnTracker


def _epoch_of(iso: str | None) -> float | None:
    """An ISO instant as a POSIX timestamp, or None if it is not one."""
    if not iso:
        return None
    from datetime import datetime, timezone

    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()
from .notify import Notifier
from .status import StatusChecker
from .pokeapi import PokeAPI
from .sprites import SpriteStore
from .cache import ScanCache
from .models import CostCoverage, DailyUsage
from .plan import PlanSource
from .single_instance import SingleInstance
from .recap import UsageLedger


class Daemon:
    def __init__(
        self, state_path: Path, config_path: Path, cache, providers,
        limits_source=None, companion_store=None, notifier=None,
        burn_tracker=None, status_checker=None, updater=None, plan_source=None,
        connectivity=None, power_probe=None,
        cursor_limits_source=None, antigravity_limits_source=None,
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
        self.updater = updater
        self.plan_source = plan_source
        self.connectivity = connectivity
        self.power_probe = power_probe
        self.cursor_limits_source = cursor_limits_source
        self.antigravity_limits_source = antigravity_limits_source
        # Which account the last limits belonged to. Switching accounts changes
        # what the percentages mean, so cached limits and burn history from the
        # previous account must not carry over.
        self._account_uuid: str | None = None
        self.status_checker = status_checker
        self.spool: Path | None = None
        self.config_values = config.load(config_path)
        self.usage_ledger = UsageLedger(state_path.with_name("usage-ledger.json"))

    def custom_scan_roots(self, provider_id: str) -> str | None:
        """This provider's extra scan folders, as configured right now."""
        configured = self.config_values.get("custom_scan_roots")
        if not isinstance(configured, dict):
            return None
        value = configured.get(provider_id)
        return value if isinstance(value, str) and value.strip() else None

    def _apply_difficulty(self) -> None:
        if self.companion_store is None:
            return
        self.companion_store.set_difficulties(
            self.config_values.get("growth_difficulty", 1.0),
            self.config_values.get("shop_difficulty", 1.0),
        )

    def _burn_payload(self, limit_status, blocks: dict) -> dict:
        """The forecast rows, from the block rate rather than from sampling.

        The sampler stays as the source for windows with no block behind them —
        it is the only thing that can say anything about the weekly limit — but
        the 5-hour row prefers the block estimate, which answers on the first
        poll instead of after three.
        """
        payload = self.burn.payload() if self.burn is not None else {}
        session = getattr(limit_status, "session", None)
        block = blocks.get("claude_code")
        if session is None or block is None:
            return payload

        forecast = burn_module.depletion_forecast(
            session.utilization,
            _epoch_of(session.resets_at),
            block.total_tokens,
            block.tokens_per_minute,
        )
        if forecast is None:
            # Nothing projectable. The stale sampled row is dropped rather than
            # left standing beside a block that no longer supports it.
            payload.pop("session", None)
            return payload
        row = dict(payload.get("session") or {})
        row.update({
            "eta_text": forecast.eta_text,
            "minutes_to_full": round(forecast.minutes),
            "before_reset": forecast.before_reset,
        })
        payload["session"] = row
        return payload

    def _update_payload(self, errors: list[str]) -> dict:
        """Whether a newer commit is published. Never fatal.

        A machine with no network has to behave exactly like one that is up to
        date: an update banner is not worth an error in the panel.
        """
        if self.updater is None:
            return {"supported": False}
        try:
            self.updater.check()
        except Exception as exc:  # pragma: no cover - check() swallows its own
            errors.append(f"update check: {exc}")
        payload = self.updater.payload()
        skipped = str(self.config_values.get("skipped_update_revision") or "")
        payload["skipped"] = skipped
        payload["skipped_short"] = skipped[:7]
        if skipped and payload.get("available") == skipped:
            payload["available"] = ""
            payload["available_short"] = ""
        return payload

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
        companion = self.companion_store.state if self.companion_store else None
        return {"providers": rows, "claude_accounts": list(
            getattr(self.limits_source, "account_metadata", {}).values()), "plan": {
            "detected": self.plan_source.current if self.plan_source else None,
            "status": self.plan_source.status if self.plan_source else "unavailable",
            "multiplier": companion.balance_multiplier if companion else 1,
        }}

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
        undo = transfer.describe_backup(self._save_path())
        described["can_undo"] = undo["exists"]
        described["undo_taken_at"] = undo["taken_at"]
        described["undo_dex_count"] = undo["dex_count"]
        described["undo_used_since_install"] = undo["used_since_install"]
        return described

    def _reward_windows(self, primary, extra: dict) -> tuple[dict, dict]:
        windows, epochs = {}, {}
        def add(key, value, reset):
            windows[key] = value
            if reset:
                epochs[key] = reset
        statuses = {"": primary}
        statuses.update({f"claude:{identity}:": status for identity, status in
                         getattr(self.limits_source, "account_statuses", {}).items()
                         if identity != "default"})
        for prefix, status in statuses.items():
            for kind in ("session", "weekly"):
                window = getattr(status, kind, None)
                if window is not None:
                    add(prefix + kind, window.utilization, window.resets_at)
        for bucket in (getattr(self.plan_source, "current_limits", None) or {}).get("buckets", []):
            for window in bucket.get("windows", []):
                duration = window.get("duration_minutes")
                kind = "session" if duration == 300 else "weekly" if duration == 10080 else None
                if kind:
                    add(f"codex:{bucket.get('id') or bucket.get('name', 'codex')}:{kind}",
                        window.get("utilization", 0), window.get("resets_at"))
        for group in (extra.get("antigravity_limits") or {}).get("groups", []):
            for window in group.get("buckets", []):
                kind = window.get("kind")
                if kind in ("session", "weekly"):
                    add(f"antigravity:{group.get('name', '')}:{window.get('id', '')}:{kind}",
                        window.get("utilization", 0), window.get("resets_at"))
        return windows, epochs

    def poll_once(self) -> dict:
        errors: list[str] = []
        configure_accounts = getattr(self.limits_source, "configure", None)
        if configure_accounts is not None:
            configure_accounts(self.config_values.get("additional_claude_config_dirs", ""))
        account_roots = {identity: Path(metadata["root"]) for identity, metadata in
                         getattr(self.limits_source, "account_metadata", {}).items()}
        for provider in self.providers:
            if hasattr(provider, "configure_account_roots"):
                provider.configure_account_roots(account_roots)
        detected_plan = None
        if self.plan_source is not None:
            try:
                detected_plan = self.plan_source.get()
                if self.companion_store is not None:
                    self.companion_store.apply_plan(detected_plan)
            except Exception:
                # Do not include account/helper errors: they may contain
                # private account fields. A lookup cannot break the tracker.
                errors.append("plan: unable to apply detected balance")
        self._apply_difficulty()
        for command in commands.drain(spool=self.spool):
            name = command.get("name")
            if name == "refresh":
                # Manual refresh: drop cached limits so the next fetch is live.
                if self.limits_source is not None:
                    self.limits_source.invalidate()
                for source in (self.cursor_limits_source, self.antigravity_limits_source, self.plan_source):
                    if source is not None and hasattr(source, "invalidate"):
                        source.invalidate()
            elif name in ("save_session_key", "clear_session_key"):
                try:
                    args = command.get("args") or {}
                    store = self.limits_source.session_key_store(str(args.get("account_id", "default")))
                    if name == "clear_session_key":
                        store.clear()
                    else:
                        store.save(str(args.get("key", "")), args.get("organization_id"))
                    self.limits_source.invalidate()
                except Exception:
                    errors.append("session key: unable to update this account")
            elif name == "update":
                # Applied by the daemon, not the tray: it is the half that is
                # always running, and the swap must not race two processes
                # rewriting the same directory.
                if self.updater is None:
                    errors.append("update: not an installed copy")
                else:
                    try:
                        revision = self.updater.apply()
                        message = f"updated to {revision[:7]}"
                        if self.notifier is not None:
                            self.notifier._send("PokeTokenBar", message)
                        self._pending_restart = True
                    except Exception as exc:
                        errors.append(f"update: {exc}")
            elif name in ("skip_update", "unskip_update"):
                revision = ""
                if name == "skip_update" and self.updater is not None:
                    revision = str(self.updater.available or "")
                try:
                    config.set_value(
                        self.config_path, "skipped_update_revision", revision
                    )
                    self.config_values = config.load(self.config_path)
                except (OSError, ValueError, KeyError) as exc:
                    errors.append(f"{name}: {exc}")
            elif name == "reload_config":
                self.config_values = config.load(self.config_path)
                self._apply_difficulty()
                if configure_accounts is not None:
                    configure_accounts(self.config_values.get("additional_claude_config_dirs", ""))
                    self.limits_source.invalidate()
                # The login entry is a file on disk, so the setting only means
                # anything if something writes it. The daemon does it rather
                # than the tray: it is the half that is guaranteed to be
                # running, and a setting changed through poketokenctl has to
                # take effect too.
                try:
                    autostart.apply(bool(self.config_values.get("launch_at_login")))
                except OSError as exc:
                    errors.append(f"autostart: {exc}")
            elif name in ("export", "import", "restore") and self.companion_store is not None:
                try:
                    self._transfer_command(name, command)
                    if name != "export":
                        # Imported and restored saves carry their own balance
                        # units. Convert immediately so a buy/use command later
                        # in this same spool batch sees the current Codex plan.
                        self.companion_store.apply_plan(detected_plan)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
            elif name == "represent" and self.companion_store is not None:
                args = command.get("args") or {}
                raw = args.get("species_id")
                try:
                    species_id = None if raw in (None, "", "none") else int(raw)
                    appearance = {key: args[key] for key in ("is_shiny", "unown_form") if key in args}
                    message = self.companion_store.set_representative(species_id, **appearance)
                    if self.notifier is not None:
                        self.notifier._send("PokeTokenBar", message)
                except (TypeError, ValueError) as exc:
                    errors.append(f"represent: {exc}")
            elif name in ("buy", "use") and self.companion_store is not None:
                args = command.get("args") or {}
                key = args.get("key", "")
                try:
                    if name == "buy":
                        message = self.companion_store.buy(key, **(
                            {"confirmed": args["confirmed"] is True} if "confirmed" in args else {}))
                    else:
                        message = self.companion_store.use_item(key, **(
                            {"count": args["count"]} if "count" in args else {}))
                    if self.notifier is not None:
                        self.notifier._send("PokeTokenBar", message)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
            elif name in ("retry_hatch", "create_snapshot", "restore_snapshot") and self.companion_store is not None:
                try:
                    if name == "restore_snapshot":
                        self.companion_store.restore_snapshot((command.get("args") or {}).get("id", ""))
                        self.companion_store.apply_plan(detected_plan)
                        self._apply_difficulty()
                    else:
                        getattr(self.companion_store, name)()
                except Exception as exc:
                    errors.append(f"{name}: {exc}")

        daily_by_provider: dict[str, DailyUsage] = {}
        for provider in self.providers:
            try:
                daily = provider.fetch_daily()
            except Exception as exc:  # per-provider isolation
                errors.append(f"{provider.id}: {exc}")
                continue
            if daily is not None:
                daily_by_provider[provider.id] = daily

        periods: dict = {}
        month_daily: dict = {}
        for provider in self.providers:
            fetch_periods = getattr(provider, "fetch_periods", None)
            if fetch_periods is None:
                continue
            try:
                result = fetch_periods()
            except Exception as exc:
                errors.append(f"{provider.id} periods: {exc}")
                continue
            for key in ("week", "month"):
                bucket = periods.setdefault(key, {"tokens": 0, "cost": 0.0,
                                                   "cost_coverage": CostCoverage()})
                bucket["tokens"] += result[key]["tokens"]
                bucket["cost"] += result[key]["cost"]
                if result[key].get("cost_coverage") is not None:
                    bucket["cost_coverage"].merge(result[key]["cost_coverage"])
            fetch_month_daily = getattr(provider, "fetch_month_daily", None)
            if fetch_month_daily is not None:
                try:
                    month_daily[provider.id] = fetch_month_daily()
                except Exception as exc:
                    errors.append(f"{provider.id} daily trend: {exc}")

        # The rolling 5-hour block per provider. It carries the tokens/minute
        # the limit forecast is derived from, so without it the popup can say
        # how full the window is but not when it runs out.
        blocks: dict = {}
        for provider in self.providers:
            try:
                enrichment = provider.fetch_enrichment()
            except Exception as exc:
                errors.append(f"{provider.id} block: {exc}")
                continue
            if enrichment.blocks_ok and enrichment.active_block is not None:
                blocks[provider.id] = enrichment.active_block

        limit_status = None
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
            if self.limits_source.last_error:
                errors.append(f"limits: {self.limits_source.last_error}")

        extra_limits = {}
        for key, source in (("cursor_limits", self.cursor_limits_source),
                            ("antigravity_limits", self.antigravity_limits_source)):
            if source is not None:
                try:
                    extra_limits[key] = source.get() or {}
                    if source.last_error:
                        extra_limits[key] = {**extra_limits[key], "error": source.last_error,
                                             "stale": bool(extra_limits[key])}
                except Exception:
                    extra_limits[key] = {"error": "Unable to read official limits"}

        # Said once, on the poll after the save was read: a repaired save that
        # says nothing is the same silence the repair exists to end.
        if self.companion_store is not None and self.companion_store.save_repairs:
            for note in self.companion_store.save_repairs:
                errors.append(f"save: {note}")
            self.companion_store.save_repairs = []

        companion_payload = None
        if self.companion_store is not None:
            try:
                # One language, not two. The catalogue reads config while the
                # companion reads the save, so they must be kept in step or the
                # popup renders half-translated.
                language = str(self.config_values.get("language", "en"))
                self.companion_store.state.language = language
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
                windows, epochs = self._reward_windows(limit_status, extra_limits)
                if windows:
                    if self.burn is not None:
                        for kind, utilization in windows.items():
                            if kind in ("session", "weekly"):
                                self.burn.record(kind, utilization)
                    self.companion_store.grant_candy(windows, epochs=epochs)
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
                        shiny_denominator=(balance.SHINY_CHARM_DENOMINATOR
                            if self.companion_store.state.inventory.get("shinyCharm", 0)
                            else balance.SHINY_DENOMINATOR),
                    )
                    self.companion_store.last_events = None
            except Exception as exc:
                # The companion is cosmetic; never let it break the numbers.
                errors.append(f"companion: {exc}")

        status_payload = None
        if self.status_checker is not None and self.config_values.get(
            "status_checks_enabled", True
        ):
            try:
                status_payload = self.status_checker.get()
            except Exception as exc:
                errors.append(f"status: {exc}")

        payload = state.build(
            daily_by_provider,
            self.config_values,
            errors,
            limit_status=limit_status,
            companion_payload=companion_payload,
            shop_payload=self.companion_store.shop_payload() if self.companion_store else None,
            bag_payload=self.companion_store.bag_payload() if self.companion_store else None,
            dex_payload=self.companion_store.dex_payload() if self.companion_store else None,
            catch_log=self.companion_store.catch_log_payload() if self.companion_store else None,
            rarity_counts=self.companion_store.rarity_counts() if self.companion_store else None,
            catch_counts=self.companion_store.catch_rarity_counts() if self.companion_store else None,
            periods=periods,
            month_daily=month_daily,
            codex_limits=getattr(self.plan_source, "current_limits", None),
            power_saver=bool(self.power_probe()) if self.power_probe else False,
            burn=self._burn_payload(limit_status, blocks),
            blocks=blocks,
            provider_status=status_payload,
            celebration=self.companion_store.celebration if self.companion_store else None,
            settings=self.settings_payload(),
            update=self._update_payload(errors),
            transfer=self.transfer_payload(),
        )
        payload.update(extra_limits)
        payload["claude_accounts"] = [
            {**metadata, "limits": state._limits_payload(
                self.limits_source.account_statuses.get(identity), payload["strings"],
                self.config_values),
             "error": self.limits_source.account_errors.get(identity, "")}
            for identity, metadata in getattr(self.limits_source, "account_metadata", {}).items()
        ]
        for provider in self.providers:
            if hasattr(provider, "fetch_accounts") and account_roots:
                try:
                    usage = provider.fetch_accounts(account_roots)
                    for account in payload["claude_accounts"]:
                        daily = usage.get(account["id"])
                        if daily is not None:
                            account["usage"] = {"total_tokens": daily.total_tokens,
                                                **state._cost_payload(daily.total_cost, daily.cost_coverage, payload["strings"])}
                except Exception:
                    errors.append("accounts: unable to attribute local usage")
        if self.companion_store is not None and hasattr(self.companion_store, "snapshots_payload"):
            payload["snapshots"] = self.companion_store.snapshots_payload()
        try:
            self.usage_ledger.merge(payload["month_daily"]["combined"])
        except OSError:
            errors.append("history: unable to save usage history")
        payload["usage_history"] = {
            "tokens": self.usage_ledger.tokens,
            "covered_since": self.usage_ledger.covered_since,
        }
        state.write(self.state_path, payload)
        if getattr(self, "_pending_restart", False):
            # After the write, so the tray reads the new revision and can offer
            # to restart itself too. execv never returns.
            self._pending_restart = False
            updater_module.restart_self()
        # Cleared after publishing so the banner shows once rather than
        # persisting until the next hatch.
        if self.companion_store is not None:
            self.companion_store.celebration = None
        return payload

    def run(self) -> None:
        while True:
            self.poll_once()
            interval = int(self.config_values.get("refresh_interval", 120))
            # Sleep in short slices so a queued command is picked up promptly
            # without re-scanning the logs every second.
            waited = 0
            while interval <= 0 or waited < interval:
                time.sleep(2 if interval <= 0 else min(2, interval - waited))
                waited += 2
                if self._has_commands() or (self.plan_source is not None and self.plan_source.ready):
                    break
                if self.connectivity is not None and self.connectivity.reconnected():
                    self._handle_reconnect()
                    break

    def _handle_reconnect(self) -> None:
        """Drop only network-backed caches; local log scans need no reset."""
        if self.limits_source is not None:
            self.limits_source.invalidate()
        for source in (self.cursor_limits_source, self.antigravity_limits_source):
            if source is not None:
                source.invalidate()
        if self.plan_source is not None:
            invalidate = getattr(self.plan_source, "invalidate", None)
            if invalidate is not None:
                invalidate()

    def _has_commands(self) -> bool:
        spool = self.spool or commands.spool_dir()
        return spool.is_dir() and any(spool.glob("*.json"))


def main() -> int:
    instance = SingleInstance("daemon")
    if not instance.acquire():
        return 0
    try:
        return _run()
    finally:
        instance.release()


def _run() -> int:
    from . import providers as provider_registry
    from .system_state import ConnectivityMonitor, power_saver
    from .claude_accounts import ClaudeAccountsSource
    from .cursor_limits import CursorLimitsSource
    from .antigravity_limits import AntigravityLimitsSource

    cache = ScanCache(platform_paths.cache_base() / "poketokenbar" / "scan.db")
    config_path = config.default_path()
    initial_config = config.load(config_path)
    daemon = Daemon(
        state_path=state.default_path(),
        config_path=config_path,
        cache=cache,
        providers=None,  # replaced below, once the daemon can answer for its config
        limits_source=ClaudeAccountsSource(state.default_path().parent),
        cursor_limits_source=CursorLimitsSource(),
        antigravity_limits_source=AntigravityLimitsSource(state.default_path().parent),
        companion_store=CompanionStore(
            api=PokeAPI(), sprite_store=SpriteStore(),
            growth_difficulty=initial_config["growth_difficulty"],
            shop_difficulty=initial_config["shop_difficulty"],
        ),
        notifier=Notifier(),
        burn_tracker=BurnTracker(),
        status_checker=StatusChecker(),
        updater=updater_module.Updater(),
        plan_source=PlanSource(),
        connectivity=ConnectivityMonitor(),
        power_probe=power_saver,
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
