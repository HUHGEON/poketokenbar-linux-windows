"""Shop, bag, and rare-candy grants — ports the economy half of CompanionStore.

Tokens serve two roles at once: an unspendable growth meter
(used_since_install) and a spendable wallet (minus spent_tokens). Buying never
rewinds growth; it only debits the wallet.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import balance, companion
from .balance import Rarity
from .companion import CompanionState


class ShopError(Exception):
    """A purchase that cannot proceed (unknown item, funds, or state)."""


@dataclass(slots=True)
class ShopEntry:
    key: str
    kind: str  # "item" | "egg"
    price: int
    label: str
    owned: bool = False


def entries(
    state: CompanionState,
    shop_difficulty: float = balance.DEFAULT_DIFFICULTY,
) -> list[ShopEntry]:
    """Everything on sale, cheapest first."""
    out = [
        ShopEntry("rareCandy", "item", balance.RARE_CANDY_PRICE, "Rare Candy"),
        ShopEntry("mint", "item", balance.MINT_PRICE, "Mint"),
        ShopEntry(
            "shinyCharm",
            "item",
            balance.SHINY_CHARM_PRICE,
            "Shiny Charm",
            # Passive and permanent: held, never consumed, bought once.
            owned=state.inventory.get("shinyCharm", 0) > 0,
        ),
    ]
    for tier in balance.EGG_SHOP_TIERS:
        key = f"egg:{tier}" if tier else "egg"
        label = {
            None: "Pokemon Egg",
            Rarity.UNCOMMON: "Uncommon Egg",
            Rarity.RARE: "Rare Egg",
        }[tier]
        out.append(ShopEntry(key, "egg", balance.egg_price(tier), label))
    for entry in out:
        entry.price = balance.scale_difficulty(
            entry.price * state.balance_multiplier, shop_difficulty
        )
    return sorted(out, key=lambda e: e.price)


def _debit(state: CompanionState, price: int) -> None:
    if state.spendable_tokens < price:
        raise ShopError(
            f"not enough tokens: need {price:,}, have {state.spendable_tokens:,}"
        )
    state.spent_tokens += price


def buy(
    state: CompanionState,
    key: str,
    shop_difficulty: float = balance.DEFAULT_DIFFICULTY,
    confirmed: bool = False,
) -> str:
    """Purchase one shop entry. Returns a short description of what happened."""
    entry = next(
        (e for e in entries(state, shop_difficulty) if e.key == key), None
    )
    if entry is None:
        raise ShopError(f"unknown shop item: {key}")

    if entry.kind == "item":
        if entry.key == "shinyCharm" and entry.owned:
            raise ShopError("shiny charm is already held")
        _debit(state, entry.price)
        state.inventory[entry.key] = state.inventory.get(entry.key, 0) + 1
        return f"bought {entry.label}"

    # Eggs replace the current companion outright.
    if is_high_value(state) and not confirmed:
        raise ShopError("confirm before replacing a shiny or legendary companion")
    tier = {"egg": None, f"egg:{Rarity.UNCOMMON}": Rarity.UNCOMMON,
            f"egg:{Rarity.RARE}": Rarity.RARE}[entry.key]
    _debit(state, entry.price)
    # Reached forms remain owned, but release never completes an evolution line.
    companion.release(state)
    state.egg_usage = 0
    state.egg_tier = tier
    state.pending_hatch_id = None
    state.pending_unown_form = None
    state.reconcile_representative()
    return f"bought {entry.label}"


def is_high_value(state: CompanionState) -> bool:
    mon = state.active
    return mon is not None and (mon.visible_shiny or mon.rarity == Rarity.LEGENDARY)


def _candy_stage_costs(state: CompanionState, growth_difficulty: float) -> list[int]:
    mon = state.active
    if mon is None:
        return []
    return [balance.scale_difficulty(max(1, round(balance.phase_threshold(
        mon.rarity, mon.total_forms, stage, state.balance_multiplier,
    ) / (2 if mon.has_growth_boost else 1))), growth_difficulty)
            for stage in range(mon.stage_index, len(mon.path_ids))]


def max_candy_use_count(state: CompanionState,
                       growth_difficulty: float = balance.DEFAULT_DIFFICULTY) -> int:
    costs = _candy_stage_costs(state, growth_difficulty)
    mon = state.active
    if not costs or mon is None:
        return 0
    if mon.ditto_disguise is not None and not mon.ditto_revealed and mon.used_at_stage >= costs[0]:
        return 0
    remaining = max(0, sum(costs) - mon.used_at_stage)
    xp = balance.RARE_CANDY_XP * state.balance_multiplier
    return min(state.inventory.get("rareCandy", 0), (remaining + xp - 1) // xp)


def candy_preview(state: CompanionState, count: int = 1,
                  growth_difficulty: float = balance.DEFAULT_DIFFICULTY) -> dict | None:
    if type(count) is not int or count <= 0:
        return None
    count = min(count, max_candy_use_count(state, growth_difficulty))
    if count <= 0:
        return None
    xp = count * balance.RARE_CANDY_XP * state.balance_multiplier
    remaining = state.active.used_at_stage + xp
    result = {"count": count, "xp": xp, "evolves": False, "graduates": False,
              "carryover_xp": 0, "discarded_xp": 0}
    costs = _candy_stage_costs(state, growth_difficulty)
    for index, cost in enumerate(costs):
        if remaining < cost:
            break
        remaining -= cost
        if index == len(costs) - 1:
            result.update(graduates=True, discarded_xp=remaining)
            return result
        result["evolves"] = True
    if result["evolves"]:
        result["carryover_xp"] = remaining
    return result


def use_item(
    state: CompanionState,
    key: str,
    rng=None,
    growth_difficulty: float = balance.DEFAULT_DIFFICULTY,
    count: int = 1,
) -> str:
    """Consume one held item."""
    held = state.inventory.get(key, 0)
    if held <= 0:
        raise ShopError(f"no {key} in bag")

    if key == "rareCandy":
        if state.active is None:
            raise ShopError("candy needs a hatched companion")
        preview = candy_preview(state, count, growth_difficulty)
        if preview is None:
            raise ShopError("no candy can be used on this companion")
        consumed = preview["count"]
        mon = state.active
        xp = balance.RARE_CANDY_XP * state.balance_multiplier
        if mon.ditto_disguise is not None and not mon.ditto_revealed:
            remaining = max(0, _candy_stage_costs(state, growth_difficulty)[0] - mon.used_at_stage)
            consumed = min(consumed, (remaining + xp - 1) // xp)
        state.inventory[key] = held - consumed
        # Routed through apply_usage so carry-over, evolution, and graduation
        # all behave exactly as they do for real usage.
        companion.apply_usage(
            state, consumed * xp,
            rng=rng, credit_wallet=False,
            growth_difficulty=growth_difficulty,
        )
        return "used Rare Candy" if consumed == 1 else f"used Rare Candy ×{consumed}"

    if key == "mint":
        if state.active is None:
            raise ShopError("mint needs a hatched companion")
        import random

        rng = rng or random.Random()
        state.inventory[key] = held - 1
        state.active.nature = companion.roll_nature(rng)
        return f"nature is now {state.active.nature}"

    raise ShopError(f"{key} cannot be used")


# --- rare candy grants -----------------------------------------------------


def window_key(kind: str) -> str:
    """Stable identifier for a limit window.

    Must never include volatile fields such as resets_at. Including them made
    the Swift app re-notify on every refresh, because a rolling weekly window
    reports a new resets_at each time.
    """
    return f"limit:{kind}"


def grant_candy(state: CompanionState, windows: dict[str, float],
                epochs: dict[str, str] | None = None) -> int:
    """Award candy for maxed limit windows. Edge-triggered.

    `windows` maps kind ("session"/"weekly") to utilization percent.
    Returns how many candies were granted.
    """
    granted = 0
    if not windows:
        return granted
    for kind, utilization in windows.items():
        key = window_key(kind)
        epoch = (epochs or {}).get(kind)
        if epoch is not None:
            previous_epoch = state.candy_window_epoch.get(key)
            if previous_epoch is not None and previous_epoch != epoch:
                state.candy_grant_tier.pop(key, None)
            state.candy_window_epoch[key] = epoch
        tier = 2 if utilization >= 100 else 0
        previous = state.candy_grant_tier.get(key, 0)

        if tier == 0:
            # Any dip below full rearms the next full crossing.
            state.candy_grant_tier.pop(key, None)
            continue
        if tier <= previous:
            continue
        state.candy_grant_tier[key] = tier
        if tier < 2:
            continue  # only a full window pays out

        if not state.candy_feature_seeded:
            # First run must not pay out for a window that was already full
            # before the feature existed.
            continue
        amount = (
            balance.RARE_CANDY_WEEKLY_GRANT
            if kind.rsplit(":", 1)[-1] == "weekly" or kind.rsplit(".", 1)[-1] == "weekly"
            else balance.RARE_CANDY_SESSION_GRANT
        )
        state.inventory["rareCandy"] = state.inventory.get("rareCandy", 0) + amount
        granted += amount

    state.candy_feature_seeded = True
    return granted
