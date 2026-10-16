"""Settings shared by the daemon and the plasmoid.

Keys port from UsageStore's UserDefaults. Dropped deliberately:
disableKeychainAccess (no Keychain on Linux) and updateNotificationsEnabled
(no release channel for a personal build).
"""

from __future__ import annotations

import json
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
    # Whether limit percentages read as used ("15%") or remaining ("85% left"),
    # everywhere they are shown. Upstream's limitDisplayMode; used is its default.
    "limit_value_mode": "used",
    "launch_at_login": False,
    # What happens to a pin once the Pokemon it names has graduated.
    #
    # "keep"    — the panel goes on showing the species you pinned. "Pin" read
    #             literally, and a graduated species is still in your Pokedex.
    #             The default, because it is what pressing the star says.
    # "release" — the pin is let go and the panel follows the companion again:
    #             the next egg, its hatch and its evolutions all appear.
    #
    # Neither is wrong, so it is a choice rather than a rule — and a named
    # choice rather than a switch, because "off" does not say which of the two
    # it means.
    "pin_on_graduation": "keep",
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
    # How smoothly the panel sprite and the desktop pet animate: "off",
    # "saver", "balanced" or "smooth". A frame costs a recomposite, so this is
    # a real power setting, and the default matches upstream's. "off" holds the
    # sprite on its first frame and schedules no frames at all.
    "animation_quality": "saver",
    # Extra scan folders, one raw string per provider id (comma/newline
    # separated). A dict rather than one field per provider: the readers are
    # per-provider on purpose, so a folder added for Gemini is never handed to
    # Claude's parser.
    "custom_scan_roots": {},
    # Difficulty multipliers (1.0 = the default balance, 0.1-2.0). Growth
    # scales hatch and stage thresholds, shop scales prices. A preference, so
    # it lives here rather than in the save; the save only records what its
    # banked progress was earned under.
    "growth_difficulty": 1.0,
    "shop_difficulty": 1.0,
    # Claude config folders to read limits from besides the ones found on
    # their own (the default folder, $CLAUDE_CONFIG_DIR, and ~/.claude-* /
    # ~/.claude_* logins). Comma or newline separated, for a second login that
    # follows neither convention.
    "extra_claude_config_dirs": "",
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
    return values


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
        return float(raw)
    return raw


# The two alert thresholds share a scale and their ranges overlap, so one can
# be moved past the other. A window between them would then raise a critical
# alert below the warning line, and the warning tier would never fire at all
# (upstream 231002d). Moving one pushes the other along by this much.
THRESHOLD_GAP = 5


def set_value(path: Path, key: str, raw: str) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"unknown setting: {key}")
    values = load(path)
    values[key] = _coerce(key, raw)
    _keep_thresholds_apart(values, moved=key)
    save(path, values)


def _keep_thresholds_apart(values: dict, moved: str) -> None:
    """Whichever threshold was just moved stays; the other gets out of its way."""
    warn = values.get("warn_threshold", DEFAULTS["warn_threshold"])
    crit = values.get("crit_threshold", DEFAULTS["crit_threshold"])
    if crit > warn:
        return
    if moved == "crit_threshold":
        values["warn_threshold"] = max(0, crit - THRESHOLD_GAP)
    elif moved == "warn_threshold":
        values["crit_threshold"] = min(100, warn + THRESHOLD_GAP)


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
