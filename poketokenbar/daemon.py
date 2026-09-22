"""poketokend — polls providers, writes state.json, drains commands."""

from __future__ import annotations

import os
import time
from pathlib import Path

from . import commands, config, platform_paths, state
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
from .limits_source import LimitsSource
from .pokeapi import PokeAPI
from .sprites import SpriteStore
from .cache import ScanCache
from .models import DailyUsage
from .plan import PlanSource


class Daemon:
    def __init__(
        self, state_path: Path, config_path: Path, cache, providers,
        limits_source=None, companion_store=None, notifier=None,
        burn_tracker=None, status_checker=None, updater=None, plan_source=None,
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
        # Which account the last limits belonged to. Switching accounts changes
        # what the percentages mean, so cached limits and burn history from the
        # previous account must not carry over.
        self._account_uuid: str | None = None
        self.status_checker = status_checker
        self.spool: Path | None = None
        self.config_values = config.load(config_path)

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
        return self.updater.payload()

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
        return {"providers": rows, "plan": {
            "detected": self.plan_source.current if self.plan_source else None,
            "status": self.plan_source.status if self.plan_source else "unavailable",
            "multiplier": companion.balance_multiplier if companion else 1,
        }}

    def poll_once(self) -> dict:
        errors: list[str] = []
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
            elif name == "reload_config":
                self.config_values = config.load(self.config_path)
                self._apply_difficulty()
                # The login entry is a file on disk, so the setting only means
                # anything if something writes it. The daemon does it rather
                # than the tray: it is the half that is guaranteed to be
                # running, and a setting changed through poketokenctl has to
                # take effect too.
                try:
                    autostart.apply(bool(self.config_values.get("launch_at_login")))
                except OSError as exc:
                    errors.append(f"autostart: {exc}")
            elif name in ("export", "import") and self.companion_store is not None:
                target = (command.get("args") or {}).get("path", "")
                try:
                    from . import transfer

                    if name == "export":
                        written = transfer.export_to(
                            Path(target), self.companion_store.state
                        )
                        message = f"exported to {written}"
                    else:
                        self.companion_store.state = transfer.import_from(
                            Path(target), target=self.companion_store.save_path
                        )
                        # An imported save carries its own units. Convert before
                        # a later buy/use command in the same batch can run.
                        self.companion_store.apply_plan(detected_plan)
                        message = "save imported"
                    if self.notifier is not None:
                        self.notifier._send("PokeTokenBar", message)
                except Exception as exc:
                    errors.append(f"{name}: {exc}")
            elif name == "represent" and self.companion_store is not None:
                raw = (command.get("args") or {}).get("species_id")
                try:
                    species_id = None if raw in (None, "", "none") else int(raw)
                    message = self.companion_store.set_representative(species_id)
                    if self.notifier is not None:
                        self.notifier._send("PokeTokenBar", message)
                except (TypeError, ValueError) as exc:
                    errors.append(f"represent: {exc}")
            elif name in ("buy", "use") and self.companion_store is not None:
                key = (command.get("args") or {}).get("key", "")
                try:
                    if name == "buy":
                        message = self.companion_store.buy(key)
                    else:
                        message = self.companion_store.use_item(key)
                    if self.notifier is not None:
                        self.notifier._send("PokeTokenBar", message)
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
                bucket = periods.setdefault(key, {"tokens": 0, "cost": 0.0})
                bucket["tokens"] += result[key]["tokens"]
                bucket["cost"] += result[key]["cost"]

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
                if limit_status is not None:
                    windows = {}
                    if limit_status.session is not None:
                        windows["session"] = limit_status.session.utilization
                    if limit_status.weekly is not None:
                        windows["weekly"] = limit_status.weekly.utilization
                    if self.burn is not None:
                        for kind, utilization in windows.items():
                            self.burn.record(kind, utilization)
                    self.companion_store.grant_candy(windows)
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
            burn=self._burn_payload(limit_status, blocks),
            blocks=blocks,
            provider_status=status_payload,
            celebration=self.companion_store.celebration if self.companion_store else None,
            settings=self.settings_payload(),
            update=self._update_payload(errors),
        )
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
            while waited < interval:
                time.sleep(min(2, interval - waited))
                waited += 2
                if self._has_commands() or (self.plan_source is not None and self.plan_source.ready):
                    break

    def _has_commands(self) -> bool:
        spool = self.spool or commands.spool_dir()
        return spool.is_dir() and any(spool.glob("*.json"))


def main() -> int:
    from . import providers as provider_registry

    cache = ScanCache(platform_paths.cache_base() / "poketokenbar" / "scan.db")
    config_path = config.default_path()
    initial_config = config.load(config_path)
    daemon = Daemon(
        state_path=state.default_path(),
        config_path=config_path,
        cache=cache,
        providers=None,  # replaced below, once the daemon can answer for its config
        limits_source=LimitsSource(),
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
