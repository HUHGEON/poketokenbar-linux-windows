"""state.json — the daemon's only output to the UI.

Written atomically (temp + rename) so the plasmoid, which polls, can never
read a torn file. Always parses: a failing poll produces errors[], never a
partial document.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path

from . import format as fmt
from . import platform_paths
from . import l10n, limits
from .models import DailyUsage

SCHEMA_VERSION = 1


def default_path() -> Path:
    return platform_paths.state_base() / "poketokenbar" / "state.json"


def _limits_payload(status) -> dict:
    """Serialise a limits.LimitStatus, or an empty dict when unavailable."""
    if status is None:
        return {}

    def window(w):
        if w is None:
            return None
        return {
            "utilization": w.utilization,
            "resets_at": w.resets_at,
            "severity": w.severity,
        }

    return {
        "session": window(status.session),
        "weekly": window(status.weekly),
        "plan": status.subscription_type,
        "account": status.account or {},
    }


def _period_rows(periods: dict | None) -> dict:
    """Week and month with their text prepared, like every other number here.

    The daemon sums these as raw ints; formatting them in the UI is what led to
    QML rendering 8.55336e+07 in the first place.
    """
    out = {}
    for key, bucket in (periods or {}).items():
        tokens = bucket.get("tokens", 0)
        cost = bucket.get("cost", 0.0)
        out[key] = {
            "tokens": tokens,
            "cost": cost,
            "tokens_text": fmt.grouped(tokens),
            "tokens_compact": fmt.compact(tokens),
            "cost_text": fmt.cost(cost),
        }
    return out


def _combined_models(daily_by_provider: dict) -> dict[str, int]:
    combined: dict[str, int] = {}
    for daily in daily_by_provider.values():
        for name, tokens in daily.models.items():
            combined[name] = combined.get(name, 0) + tokens
    return combined


def _model_rows(models: dict[str, int]) -> list[dict]:
    """Biggest first, so the popover reads top-down without sorting again.

    Ties break on the model name to keep the order stable between polls —
    otherwise two equal models would swap places on every refresh.
    """
    return [
        {
            "model": name,
            "total_tokens": tokens,
            "total_tokens_text": fmt.grouped(tokens),
            "total_tokens_compact": fmt.compact(tokens),
        }
        for name, tokens in sorted(models.items(), key=lambda kv: (-kv[1], kv[0]))
        if tokens > 0
    ]


def _transfer_payload(described: dict | None) -> dict:
    """The export file the popup would import, described before it is used.

    Importing replaces a Pokédex, so the popup has to be able to say *which*
    save it is about to replace it with — when it was taken, on what machine,
    and how much progress is in it. Formatted here with everything else the UI
    renders rather than in JavaScript.
    """
    if not described:
        return {}
    exported_at = described.get("exported_at")
    used = described.get("used_since_install")
    current_used = described.get("current_used_since_install")
    taken_at = described.get("undo_taken_at")
    undo_used = described.get("undo_used_since_install")
    return {
        "path": described.get("path", ""),
        "exists": bool(described.get("exists")),
        "error": described.get("error") or "",
        "exported_at": exported_at,
        "exported_text": datetime.fromtimestamp(exported_at).strftime("%Y-%m-%d %H:%M")
        if exported_at
        else "",
        "device": described.get("device") or "",
        "dex_count": described.get("dex_count"),
        "used_since_install": used,
        "used_text": fmt.compact(used) if used is not None else "",
        "items": described.get("items"),
        # The save that would be replaced, so the prompt shows both sides
        # rather than asking someone to remember where they were.
        "current_dex_count": described.get("current_dex_count"),
        "current_used_since_install": current_used,
        "current_used_text": fmt.compact(current_used) if current_used is not None else "",
        # The case worth a warning: importing a stale export as if it were a
        # newer one is how a day of raising disappears.
        "goes_backwards": used is not None and current_used is not None and used < current_used,
        # The undo, described the same way: it is the same overwrite, and the
        # backup it restores is not always the one someone has in mind.
        "can_undo": bool(described.get("can_undo")),
        "undo_taken_text": datetime.fromtimestamp(taken_at).strftime("%Y-%m-%d %H:%M")
        if taken_at
        else "",
        "undo_dex_count": described.get("undo_dex_count"),
        "undo_used_text": fmt.compact(undo_used) if undo_used is not None else "",
        "undo_goes_backwards": undo_used is not None
        and current_used is not None
        and undo_used < current_used,
    }


def build(
    daily_by_provider: dict[str, DailyUsage],
    config_values: dict,
    errors: list[str],
    scanning: bool = False,
    limit_status=None,
    companion_payload: dict | None = None,
    shop_payload: list | None = None,
    bag_payload: list | None = None,
    dex_payload: list | None = None,
    catch_log: list | None = None,
    rarity_counts: dict | None = None,
    catch_counts: dict | None = None,
    periods: dict | None = None,
    burn: dict | None = None,
    provider_status: dict | None = None,
    celebration: dict | None = None,
    settings: dict | None = None,
    transfer: dict | None = None,
    detail: dict | None = None,
) -> dict:
    total_tokens = sum(d.total_tokens for d in daily_by_provider.values())
    total_cost = sum(d.total_cost for d in daily_by_provider.values())
    limit_mode = config_values.get("limit_display_mode", "both")

    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": time.time(),
        "scanning": scanning,
        "errors": errors,
        "today": {
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "tokens_grouped": fmt.grouped(total_tokens),
            "tokens_compact": fmt.compact(total_tokens),
            "cost_text": fmt.cost(total_cost),
            # Across every provider, so a day spent on one model through two
            # tools still reads as one row.
            "models": _model_rows(_combined_models(daily_by_provider)),
        },
        "providers": {
            pid: {
                "total_tokens": d.total_tokens,
                # Preformatted: QML's Number.toLocaleString() renders large
                # values as 8.55336e+07. Formatting belongs in one place.
                "total_tokens_text": fmt.grouped(d.total_tokens),
                "total_tokens_compact": fmt.compact(d.total_tokens),
                "total_cost": d.total_cost,
                "input_tokens": d.input_tokens,
                "output_tokens": d.output_tokens,
                "cache_creation_tokens": d.cache_creation_tokens,
                "cache_read_tokens": d.cache_read_tokens,
                # One session log can carry several models — Pi and its forks
                # route them all through one file — so the day is broken down
                # by the model that actually answered.
                "models": _model_rows(d.models),
            }
            for pid, d in daily_by_provider.items()
        },
        "limits": _limits_payload(limit_status),
        "companion": companion_payload or {},
        "shop": shop_payload or [],
        "bag": bag_payload or [],
        "dex": dex_payload or [],
        "catch_log": catch_log or [],
        "rarity_counts": rarity_counts or {},
        "catch_counts": catch_counts or {},
        "periods": _period_rows(periods),
        "strings": l10n.catalogue(config_values.get("language", "en")),
        "celebration": celebration or {},
        # The Pokédex page the popup has open, or {} for none.
        "detail": detail or {},
        "burn": burn or {},
        "provider_status": provider_status or {},
        # What the settings page needs that only the daemon can answer: which
        # sources are registered, and how many of a person's extra folders
        # actually survived. Counting their raw patterns instead would report a
        # folder as accepted when it had been dropped for swallowing a default.
        "settings": settings or {},
        # The export file the Import button would read, described so the popup
        # can ask before overwriting instead of after.
        "transfer": _transfer_payload(transfer),
        # The live config, so a preferences UI renders current values without
        # parsing config.json itself and without the two drifting apart.
        "config": dict(config_values),
        "panel": {
            "tokens_text": fmt.compact(total_tokens)
            if config_values.get("show_tokens_in_menu")
            else "",
            "cost_text": fmt.cost_compact(total_cost)
            if config_values.get("show_cost_in_menu")
            else "",
            "limit_text": limits.panel_text(limit_status, limit_mode)
            if config_values.get("show_limit_in_menu")
            else "",
            # Structured form so the panel can colour each number on its own.
            "limit_windows": [
                {
                    "value": w.utilization,
                    "text": limits.format_percent(w.utilization),
                    "level": limits.level(
                        w.utilization,
                        config_values.get("warn_threshold", 80),
                        config_values.get("crit_threshold", 95),
                    ),
                }
                for w in limits.windows(limit_status, limit_mode)
            ]
            if config_values.get("show_limit_in_menu")
            else [],
            # The pinned species when there is one, else the companion. Reading
            # `sprite_path` here instead would leave the pin with nowhere to
            # take effect, which is the only thing pinning does.
            "sprite_path": (companion_payload or {}).get(
                "panel_sprite_path", (companion_payload or {}).get("sprite_path", "")
            ),
        },
    }


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
