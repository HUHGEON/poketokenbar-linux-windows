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

from . import balance, forms, platform_paths, profile as profiles

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


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _decode_profile(raw) -> profiles.PokemonProfile | None:
    """A profile, or None when it is damaged beyond clamping.

    None costs nothing: migrate_profiles gives the Pokémon a new one, and the
    Pokémon itself is kept either way.
    """
    if not isinstance(raw, dict):
        return None
    seed = _int(raw.get("seed"))
    ivs = raw.get("ivs")
    if seed is None or not isinstance(ivs, dict):
        return None
    if not all(_int(ivs.get(stat)) is not None for stat in profiles.STAT_ORDER):
        return None
    moves = []
    for move in raw.get("moves") or []:
        if isinstance(move, dict) and isinstance(move.get("name"), str):
            moves.append(profiles.KnownMove(move["name"], _int(move.get("learned_at_level")) or 0))
    ability_name = raw.get("ability_name")
    profile = profiles.PokemonProfile(
        instance_id=raw.get("instance_id") if isinstance(raw.get("instance_id"), str) else "",
        seed=seed & ((1 << 64) - 1),
        ivs={stat: ivs[stat] for stat in profiles.STAT_ORDER},
        gender=raw.get("gender") if isinstance(raw.get("gender"), str) else None,
        ability_slot=_int(raw.get("ability_slot")),
        ability_name=ability_name if isinstance(ability_name, str) else None,
        ability_is_hidden=_lenient(raw, "ability_is_hidden", bool, False),
        level=_int(raw.get("level")) or profiles.HATCH_LEVEL,
        growth_tokens=_int(raw.get("growth_tokens")) or 0,
        moves=moves,
    )
    profiles.sanitize(profile)
    return profile


def _encode_profile(p: profiles.PokemonProfile | None):
    if p is None:
        return None
    return {
        "instance_id": p.instance_id,
        "seed": p.seed,
        "ivs": dict(p.ivs),
        "gender": p.gender,
        "ability_slot": p.ability_slot,
        "ability_name": p.ability_name,
        "ability_is_hidden": p.ability_is_hidden,
        "level": p.level,
        "growth_tokens": p.growth_tokens,
        "moves": [{"name": m.name, "learned_at_level": m.learned_at_level} for m in p.moves],
    }


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
        profile=_decode_profile(raw.get("profile")),
        form=_form(raw, path_ids),
    )


def _form(raw: dict, species_ids=()) -> str | None:
    """The appearance this record wears, or None.

    `form` is what saves write now; `unown_form` is what they wrote while only
    Unown had forms, and is still read (upstream 04b12da). A form is dropped
    unless some species in the record can actually wear it — one on another
    species is meaningless, and an imported or hand-edited save is where that
    appears.
    """
    value = raw.get("form")
    if not isinstance(value, str) or not value:
        value = raw.get("unown_form")
    if not isinstance(value, str):
        return None
    return value if any(forms.is_form(sid, value) for sid in species_ids) else None


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
        profile=_decode_profile(raw.get("profile")),
        form=_form(raw, chain),
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
    state.representative_form = _form(
        {"form": raw.get("representative_form"),
         "unown_form": raw.get("representative_unown_form")},
        [state.representative_species_id])
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
    epochs = raw.get("candy_window_epoch")
    if isinstance(epochs, dict):
        state.candy_window_epoch = {
            k: v for k, v in epochs.items() if isinstance(k, str) and isinstance(v, str)
        }
    state.candy_feature_seeded = _lenient(raw, "candy_feature_seeded", bool, False)
    global last_repairs
    last_repairs = reconcile(state)
    return state


# The highest species id that can exist. A save naming one above it has been
# edited or damaged; there is nothing to draw and nothing to look up.
MAX_SPECIES_ID = 1025


def _deduped(species_ids: list[int]) -> list[int]:
    """The same line with each species kept once, in the order it first appears.

    A chain holding one species twice is only reachable by hand-editing, and it
    makes the dex name lookup, the release record and the graduation record
    disagree with themselves (upstream 9c9c805).
    """
    seen: set[int] = set()
    return [i for i in species_ids if not (i in seen or seen.add(i))]


def reconcile(state: CompanionState) -> list[str]:
    """Pull a save back inside the rules, and say what had to move.

    Not an anti-cheat measure — the file belongs to whoever is running this and
    a value that merely *is* generous stays. This is for the values that cannot
    be true at all, and it exists because they arrive by more routes than
    editing: a write cut short, a disk error, a save carried between machines,
    a field an older version wrote, and the `import` command, which takes
    somebody else's file wholesale.

    They used to be accepted in silence and then quietly misbehave — a species
    id nothing can draw showed a blank square, a stage past the end of the
    evolution line drew the wrong form, a ledger claiming more spent than
    earned made every later balance wrong.
    """
    notes: list[str] = []

    if state.used_since_install < 0:
        notes.append("used_since_install was negative")
        state.used_since_install = 0
    if state.spent_tokens < 0:
        notes.append("spent_tokens was negative")
        state.spent_tokens = 0
    if state.spent_tokens > state.used_since_install:
        # Spendable already floors at zero, so this is invisible until the
        # ledger is read for anything else — and then every figure from it is
        # wrong by the difference.
        notes.append("spent_tokens exceeded used_since_install")
        state.spent_tokens = state.used_since_install
    if state.egg_usage < 0:
        notes.append("egg_usage was negative")
        state.egg_usage = 0

    state.inventory = {
        key: value for key, value in state.inventory.items()
        if isinstance(key, str) and isinstance(value, int) and value > 0
    }
    state.candy_grant_tier = {
        key: value for key, value in state.candy_grant_tier.items()
        if isinstance(key, str) and isinstance(value, int) and value >= 0
    }

    mon = state.active
    if mon is not None:
        showing = mon.current_id
        mon.path_ids = _deduped([i for i in mon.path_ids if _is_species(i)])
        mon.planned_path_ids = _deduped(
            [i for i in mon.planned_path_ids if _is_species(i)])
        if showing in mon.path_ids:
            # The stage follows the form that was on screen, wherever the
            # deduplication left it.
            mon.stage_index = mon.path_ids.index(showing)
        if not mon.path_ids or not _is_species(mon.base_id):
            # Nothing left to show. An egg is the honest state, and the dex is
            # untouched — losing one companion beats rendering a ghost.
            notes.append("the companion named a species that cannot exist")
            state.active = None
        else:
            if not 0 <= mon.stage_index < len(mon.path_ids):
                notes.append("stage_index was outside the evolution line")
                mon.stage_index = max(0, min(mon.stage_index, len(mon.path_ids) - 1))
            if mon.total_forms < len(mon.path_ids):
                # Fewer forms than stages makes the threshold for the last one
                # smaller than the one before it.
                notes.append("total_forms was below the number of stages")
                mon.total_forms = len(mon.path_ids)
            if mon.used_at_stage < 0:
                notes.append("used_at_stage was negative")
                mon.used_at_stage = 0

    for entry in state.dex:
        entry.chain_order = _deduped(entry.chain_order)
    kept = [entry for entry in state.dex if _is_species(entry.final_id)
            and _is_species(entry.base_id)]
    if len(kept) != len(state.dex):
        notes.append(f"{len(state.dex) - len(kept)} dex entries named a species "
                     "that cannot exist")
        state.dex = kept

    state.reconcile_representative()
    return notes


def _is_species(value) -> bool:
    return isinstance(value, int) and 1 <= value <= MAX_SPECIES_ID


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
            "profile": _encode_profile(m.profile),
            "form": m.form,
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
        "representative_form": state.representative_form,
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
                "profile": _encode_profile(d.profile),
                "form": d.form,
            }
            for d in state.dex
        ],
        "collected_finals": sorted(state.collected_finals),
        "language": state.language,
        "growth_difficulty": state.growth_difficulty,
        "inventory": state.inventory,
        "candy_grant_tier": state.candy_grant_tier,
        "candy_window_epoch": state.candy_window_epoch,
        "candy_feature_seeded": state.candy_feature_seeded,
    }




# What the last `load` had to put back inside the rules. Read once by the
# daemon and cleared, so a repair is reported when it happens rather than on
# every poll for the life of the process.
last_repairs: list[str] = []


def load(path: Path | None = None, recover=None) -> CompanionState:
    """The save at `path`, a recovered one, or a fresh state.

    `recover(path)` is asked for a replacement when the file is there but
    unreadable — months of growth is worth more than a clean slate, and the
    caller is the layer that knows where restore points are kept. The corrupt
    file is preserved either way.
    """
    path = path or default_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return CompanionState()
    except (OSError, ValueError):
        _quarantine(path)
        return _recovered(path, recover)
    if not isinstance(raw, dict):
        _quarantine(path)
        return _recovered(path, recover)
    return decode(raw)


def _recovered(path: Path, recover) -> CompanionState:
    if recover is None:
        return CompanionState()
    try:
        state = recover(path)
    except Exception:
        return CompanionState()
    return state if state is not None else CompanionState()


def _quarantine(path: Path) -> None:
    """Preserve an unreadable save instead of silently overwriting it."""
    try:
        path.replace(path.with_suffix(path.suffix + ".corrupt"))
    except OSError:
        pass


def encoded_text(state: CompanionState) -> str:
    """The save exactly as `save()` would write it."""
    return json.dumps(encode(state), indent=2)


def save(state: CompanionState, path: Path | None = None, text: str | None = None) -> str:
    """Write the save and return what was written.

    `text` is what `encoded_text` already produced for this state, so a caller
    that had to encode it anyway — to see whether anything changed — does not
    encode it twice.
    """
    path = path or default_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = encoded_text(state) if text is None else text
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return text
