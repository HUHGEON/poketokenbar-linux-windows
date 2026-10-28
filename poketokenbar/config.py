"""Settings shared by the daemon and the plasmoid.

Keys port from UsageStore's UserDefaults. Dropped deliberately:
disableKeychainAccess (no Keychain on Linux) and updateNotificationsEnabled
(no release channel for a personal build).
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path

from . import l10n, platform_paths

DEFAULTS: dict[str, object] = {
    "refresh_interval": 120,
    "warn_threshold": 80,
    "crit_threshold": 95,
    "show_tokens_in_menu": False,
    "show_cost_in_menu": False,
    "show_limit_in_menu": True,
    "limit_display_mode": "both",
    # Whether a limit reads as how much is used or how much is left. Purely a
    # display transform: colours, gauges and notification thresholds keep using
    # the utilization, so "10% left" still shows red.
    "limit_percent_mode": "used",
    "launch_at_login": False,
    "limit_notifications": True,
    "companion_notifications": True,
    "status_checks_enabled": True,
    "floating_pet_enabled": False,
    "floating_pet_size": 96,
    # Where the desktop pet was last left. Stored here rather than in the UI's
    # own settings so it survives a reinstall of the front end, and because
    # config.load drops any key it has no default for.
    "floating_pet_x": 80,
    "floating_pet_y": 80,
    "floating_pet_bubble_alerts": True,
    # Filled at import from the system locale, as upstream does: a fresh
    # install reading English on a Korean machine is a setting nobody goes
    # looking for.
    "language": l10n.system_default(),
    # How smoothly the panel sprite and the desktop pet animate: "saver",
    # "balanced" or "smooth". A frame costs a recomposite, so this is a real
    # power setting, and the default matches upstream's.
    "animation_quality": "saver",
    # Independent user preferences. They stay out of companion.json so an
    # imported save cannot silently bring somebody else's difficulty with it.
    "growth_difficulty": 1.0,
    "shop_difficulty": 1.0,
    # Extra scan folders, one raw string per provider id (comma/newline
    # separated). A dict rather than one field per provider: the readers are
    # per-provider on purpose, so a folder added for Gemini is never handed to
    # Claude's parser.
    "custom_scan_roots": {},
    "additional_claude_config_dirs": "",
    # The exact revision a user chose not to be reminded about. A later head
    # commit appears normally; clearing the string restores the skipped one.
    "skipped_update_revision": "",
}


def default_path() -> Path:
    return platform_paths.config_base() / "poketokenbar" / "config.json"


def load(path: Path) -> dict:
    values = dict(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return values
    if not isinstance(raw, dict):
        return values
    for key, value in raw.items():
        if key in DEFAULTS:
            values[key] = value
    from . import balance

    for key in ("growth_difficulty", "shop_difficulty"):
        values[key] = balance.clamp_difficulty(values[key])
    normalize_thresholds(values)
    return values


def normalize_thresholds(values: dict, changed: str | None = None) -> None:
    for key, low, high in (("warn_threshold", 50, 95), ("crit_threshold", 60, 100)):
        value = values.get(key, DEFAULTS[key])
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            value = DEFAULTS[key]
        values[key] = max(low, min(high, value))
    if values["warn_threshold"] >= values["crit_threshold"]:
        if changed == "crit_threshold":
            values["warn_threshold"] = values["crit_threshold"] - 5
        else:
            values["crit_threshold"] = values["warn_threshold"] + 5


def save(path: Path, values: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(values, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _coerce(key: str, raw: str):
    default = DEFAULTS[key]
    if isinstance(default, bool):
        lowered = raw.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"{key} expects a boolean, got {raw!r}")
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        from . import balance

        return balance.clamp_difficulty(raw)
    return raw


def set_value(path: Path, key: str, raw: str) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting: {key}")
    values = load(path)
    values[key] = _coerce(key, raw)
    normalize_thresholds(values, key)
    save(path, values)


def set_scan_roots(path: Path, provider_id: str, raw: str) -> None:
    """Store one provider's extra scan folders.

    Kept out of `set_value`, which coerces to the type of a scalar default —
    this key is a mapping, and routing it through there would either flatten the
    other providers' entries or reject the write outright.
    """
    if not provider_id or "/" in provider_id:
        raise ValueError(f"not a provider id: {provider_id!r}")
    values = load(path)
    configured = values.get("custom_scan_roots")
    configured = dict(configured) if isinstance(configured, dict) else {}
    cleaned = (raw or "").strip()
    if cleaned:
        configured[provider_id] = raw
    else:
        # Clearing the field removes the entry rather than storing an empty
        # string, so the file does not accumulate dead keys.
        configured.pop(provider_id, None)
    values["custom_scan_roots"] = configured
    save(path, values)
