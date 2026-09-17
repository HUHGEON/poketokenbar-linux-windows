"""Companion save file — ports the lenient decoding in CompanionModel.swift.

Decoding is deliberately forgiving: one damaged field must not cost someone
their Pokédex. Unknown enum values degrade to None (never to an invented
guarantee), a corrupt dex entry drops only itself, and a MonState with empty
path_ids falls back to an egg while dex and inventory survive.

Only a non-object top level is fatal; then the original is preserved as
.corrupt and a fresh save begins.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from . import balance, platform_paths

from .balance import Rarity
from .companion import CompanionState, DexEntry, MonState


def default_path() -> Path:
    return platform_paths.data_base() / "poketokenbar" / "companion.json"


def _rarity(value, default=Rarity.COMMON) -> Rarity:
    try:
        return Rarity(value)
    except ValueError:
        return default


def _optional_rarity(value) -> Rarity | None:
    """Unknown tier degrades to None — the safe direction for a guarantee.

    Defaulting to a real tier would hand out a guarantee nobody paid for.
    """
    if value is None:
        return None
    try:
        return Rarity(value)
    except ValueError:
        return None


def _lenient(raw: dict, key: str, kind, default):
    value = raw.get(key, default)
    return value if isinstance(value, kind) else default


def _decode_mon(raw) -> MonState | None:
    if not isinstance(raw, dict):
        return None
    path_ids = raw.get("path_ids")
    # Empty path_ids means a damaged companion: fall back to an egg rather than
    # carrying a state whose current_id is meaningless.
    if not isinstance(path_ids, list) or not path_ids:
        return None
    if not all(isinstance(i, int) for i in path_ids):
        return None

    planned = raw.get("planned_path_ids")
    if not isinstance(planned, list) or not planned:
        planned = list(path_ids)

    stage = _lenient(raw, "stage_index", int, 0)
    stage = min(max(0, stage), len(path_ids) - 1)

    return MonState(
        base_id=_lenient(raw, "base_id", int, path_ids[0]),
        path_ids=list(path_ids),
        planned_path_ids=list(planned),
        stage_index=stage,
        used_at_stage=_lenient(raw, "used_at_stage", int, 0),
        rarity=_rarity(raw.get("rarity")),
        total_forms=_lenient(raw, "total_forms", int, len(path_ids)),
        is_shiny=_lenient(raw, "is_shiny", bool, False),
        nature=raw.get("nature") if isinstance(raw.get("nature"), str) else None,
        ditto_disguise=raw.get("ditto_disguise")
        if isinstance(raw.get("ditto_disguise"), int)
        else None,
        ditto_revealed=_lenient(raw, "ditto_revealed", bool, False),
        hatched_at=raw.get("hatched_at") if isinstance(raw.get("hatched_at"), (int, float)) else None,
        has_growth_boost=_lenient(raw, "has_growth_boost", bool, False),
    )


def _decode_dex_entry(raw) -> DexEntry | None:
    if not isinstance(raw, dict):
        return None
    chain = raw.get("chain_order")
    if not isinstance(chain, list) or not all(isinstance(i, int) for i in chain):
        return None
    base_id = raw.get("base_id")
    final_id = raw.get("final_id")
    if not isinstance(base_id, int) or not isinstance(final_id, int):
        return None
    return DexEntry(
        base_id=base_id,
        final_id=final_id,
        chain_order=list(chain),
        rarity=_rarity(raw.get("rarity")),
        is_shiny=_lenient(raw, "is_shiny", bool, False),
        nature=raw.get("nature") if isinstance(raw.get("nature"), str) else None,
        caught_at=raw.get("caught_at") if isinstance(raw.get("caught_at"), (int, float)) else None,
        raised_seconds=raw.get("raised_seconds")
        if isinstance(raw.get("raised_seconds"), (int, float))
        else None,
        released_at=raw.get("released_at")
        if isinstance(raw.get("released_at"), (int, float))
        else None,
    )


def decode(raw: dict) -> CompanionState:
    state = CompanionState()
    state.install_baseline_set = _lenient(raw, "install_baseline_set", bool, False)
    state.used_since_install = _lenient(raw, "used_since_install", int, 0)
    state.spent_tokens = _lenient(raw, "spent_tokens", int, 0)
    state.egg_usage = _lenient(raw, "egg_usage", int, 0)
    state.egg_tier = _optional_rarity(raw.get("egg_tier"))
    representative = raw.get("representative_species_id")
    state.representative_species_id = representative if isinstance(representative, int) else None
    state.pending_hatch_id = (
        raw.get("pending_hatch_id") if isinstance(raw.get("pending_hatch_id"), int) else None
    )
    # None means a save that predates per-provider tracking: seed from the next
    # snapshot rather than retroactively granting past usage. An empty dict is
    # the distinct "seeded, nobody reported today" state.
    claimed = raw.get("claimed_today_tokens_by_provider")
    state.claimed_today_tokens_by_provider = claimed if isinstance(claimed, dict) else None
    state.last_date = _lenient(raw, "last_date", str, "")
    state.active = _decode_mon(raw.get("active"))

    dex_raw = raw.get("dex")
    if isinstance(dex_raw, list):
        # Per-entry isolation: one bad entry must not wipe the Pokédex.
        state.dex = [e for e in (_decode_dex_entry(d) for d in dex_raw) if e is not None]

    finals = raw.get("collected_finals")
    if isinstance(finals, list):
        state.collected_finals = {f for f in finals if isinstance(f, str)}

    state.language = _lenient(raw, "language", str, "en")
    # Saves from before difficulty were earned at the default.
    growth = raw.get("growth_difficulty")
    state.growth_difficulty = (
        balance.clamp_difficulty(growth)
        if isinstance(growth, (int, float)) and not isinstance(growth, bool)
        else balance.DEFAULT_DIFFICULTY
    )
    inventory = raw.get("inventory")
    if isinstance(inventory, dict):
        state.inventory = {k: v for k, v in inventory.items() if isinstance(v, int)}
    tiers = raw.get("candy_grant_tier")
    if isinstance(tiers, dict):
        state.candy_grant_tier = {k: v for k, v in tiers.items() if isinstance(v, int)}
    state.candy_feature_seeded = _lenient(raw, "candy_feature_seeded", bool, False)
    return state


def encode(state: CompanionState) -> dict:
    def mon(m: MonState | None):
        if m is None:
            return None
        return {
            "base_id": m.base_id,
            "path_ids": m.path_ids,
            "planned_path_ids": m.planned_path_ids,
            "stage_index": m.stage_index,
            "used_at_stage": m.used_at_stage,
            "rarity": str(m.rarity),
            "total_forms": m.total_forms,
            "is_shiny": m.is_shiny,
            "nature": m.nature,
            "ditto_disguise": m.ditto_disguise,
            "ditto_revealed": m.ditto_revealed,
            "hatched_at": m.hatched_at,
            "has_growth_boost": m.has_growth_boost,
        }

    return {
        "install_baseline_set": state.install_baseline_set,
        "used_since_install": state.used_since_install,
        "spent_tokens": state.spent_tokens,
        "egg_usage": state.egg_usage,
        "egg_tier": str(state.egg_tier) if state.egg_tier else None,
        "pending_hatch_id": state.pending_hatch_id,
        "claimed_today_tokens_by_provider": state.claimed_today_tokens_by_provider,
        "last_date": state.last_date,
        "active": mon(state.active),
        "representative_species_id": state.representative_species_id,
        "dex": [
            {
                "base_id": d.base_id,
                "final_id": d.final_id,
                "chain_order": d.chain_order,
                "rarity": str(d.rarity),
                "is_shiny": d.is_shiny,
                "nature": d.nature,
                "caught_at": d.caught_at,
                "raised_seconds": d.raised_seconds,
                "released_at": d.released_at,
            }
            for d in state.dex
        ],
        "collected_finals": sorted(state.collected_finals),
        "language": state.language,
        "growth_difficulty": state.growth_difficulty,
        "inventory": state.inventory,
        "candy_grant_tier": state.candy_grant_tier,
        "candy_feature_seeded": state.candy_feature_seeded,
    }


def load(path: Path | None = None) -> CompanionState:
    path = path or default_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return CompanionState()
    except (OSError, ValueError):
        _quarantine(path)
        return CompanionState()
    if not isinstance(raw, dict):
        _quarantine(path)
        return CompanionState()
    return decode(raw)


def _quarantine(path: Path) -> None:
    """Preserve an unreadable save instead of silently overwriting it."""
    try:
        path.replace(path.with_suffix(path.suffix + ".corrupt"))
    except OSError:
        pass


def save(state: CompanionState, path: Path | None = None) -> None:
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(encode(state), indent=2), encoding="utf-8")
    tmp.replace(path)
