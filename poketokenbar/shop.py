"""Shop, bag, and rare-candy grants — ports the economy half of CompanionStore.

Tokens serve two roles at once: an unspendable growth meter
(used_since_install) and a spendable wallet (minus spent_tokens). Buying never
rewinds growth; it only debits the wallet.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass

from . import balance, companion, pace
from .balance import Rarity
from .companion import CompanionState


class ShopError(Exception):
    """A purchase that cannot proceed (unknown item, funds, or state)."""


@dataclass(slots=True)
class ItemResult:
    """What one purchase or item use did.

    Carries the growth events rather than a finished sentence: a rare candy can
    evolve or graduate a companion, and those have to reach the notifier and
    the celebration banner exactly as the events from real usage do. Returning
    only a message is what dropped them on the floor, so a candy that pushed a
    Pokemon over the line did it in silence.

    The wording is left to the caller, which is the layer that knows the
    language; this module stays free of the catalogue.
    """

    key: str
    action: str  # "buy" | "use"
    events: companion.GrowthEvents | None = None
    nature: str | None = None
    # How many were bought or used. One purchase or use can cover several
    # items, and the toast has to say which it was.
    count: int = 1


@dataclass(slots=True)
class ShopEntry:
    key: str
    kind: str  # "item" | "egg"
    price: int
    label: str
    owned: bool = False


def entries(state: CompanionState) -> list[ShopEntry]:
    """Everything on sale, cheapest first, at the shop difficulty.

    The price listed is the price charged: buy() debits entry.price, so the
    two cannot disagree.
    """
    def price(base: int) -> int:
        return balance.scaled(base, state.shop_difficulty)

    out = [
        ShopEntry("rareCandy", "item", price(balance.RARE_CANDY_PRICE), "Rare Candy"),
        ShopEntry("mint", "item", price(balance.MINT_PRICE), "Mint"),
        ShopEntry(
            "shinyCharm",
            "item",
            price(balance.SHINY_CHARM_PRICE),
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
        out.append(ShopEntry(key, "egg", price(balance.egg_price(tier)), label))
    return sorted(out, key=lambda e: e.price)


def _debit(state: CompanionState, price: int) -> None:
    if state.spendable_tokens < price:
        raise ShopError(
            f"not enough tokens: need {price:,}, have {state.spendable_tokens:,}"
        )
    state.spent_tokens += price


def max_buy(state: CompanionState, entry: ShopEntry) -> int:
    """How many of this entry the wallet can take in one purchase.

    An egg is one per purchase whatever the wallet holds: it throws the current
    companion away, so "buy three" has no meaning. A passive already held is
    not for sale again.
    """
    if entry.owned:
        return 0
    if entry.kind != "item" or entry.key == "shinyCharm":
        return 1 if state.spendable_tokens >= entry.price else 0
    return state.spendable_tokens // entry.price


def buy(state: CompanionState, key: str, count: int = 1) -> ItemResult:
    """Purchase one shop entry, or several of a stackable item.

    Buying in bulk is this port's own: upstream's shop is one item per click,
    which is a lot of clicking for a wallet holding hundreds of candies. The
    price per item is unchanged — quantity multiplies the one entry rather than
    unlocking a cheaper bundle.
    """
    entry = next((e for e in entries(state) if e.key == key), None)
    if entry is None:
        raise ShopError(f"unknown shop item: {key}")
    if count < 1:
        raise ShopError(f"a purchase needs a count of at least one: {count}")

    if entry.kind == "item":
        if entry.key == "shinyCharm":
            if entry.owned:
                raise ShopError("shiny charm is already held")
            if count > 1:
                raise ShopError("the shiny charm is passive: one is all it takes")
        # No clamping: the wallet's refusal names the shortfall, and the UI
        # already offers no more than it can pay for.
        _debit(state, entry.price * count)
        state.inventory[entry.key] = state.inventory.get(entry.key, 0) + count
        return ItemResult(entry.key, "buy", count=count)

    if count > 1:
        raise ShopError("an egg replaces the companion, so it is bought one at a time")

    # Eggs replace the current companion outright.
    tier = {"egg": None, f"egg:{Rarity.UNCOMMON}": Rarity.UNCOMMON,
            f"egg:{Rarity.RARE}": Rarity.RARE}[entry.key]
    # Checked before the debit. During the egg stage there is no companion to
    # replace, and a purchase here charged the wallet and reset egg_usage,
    # throwing away the incubation already earned. Upstream's canBuyEgg has
    # always required an active Pokemon; the listing keeps the eggs visible.
    if state.active is None:
        raise ShopError("an egg needs a hatched companion to replace")
    _debit(state, entry.price)
    # Released, not graduated: its reached forms stay in the dex, and
    # collected_finals is left alone.
    companion.release(state, state.active)
    state.active = None
    state.egg_usage = 0
    state.egg_tier = tier
    state.pending_hatch_id = None
    return ItemResult(entry.key, "buy")


def candy_stage_costs(state: CompanionState) -> list[int]:
    """What each remaining stage costs, at the difficulty and boost in force.

    The same rounded thresholds growth itself uses, so a preview cannot promise
    an evolution the growth loop then withholds. Read off the apparent line: a
    disguised Ditto must not be detectable from the bag.
    """
    mon = state.active
    if mon is None:
        return []
    probe = copy.copy(mon)
    costs = []
    for stage in range(mon.stage_index, mon.total_forms):
        probe.stage_index = stage
        costs.append(state.stage_threshold(probe))
    return costs


def max_candy_uses(state: CompanionState) -> int:
    """How many candies can be used at once — never more than graduation needs.

    Candies past the last threshold would be swallowed for nothing, so they
    stay in the bag.
    """
    held = state.inventory.get("rareCandy", 0)
    mon = state.active
    if held <= 0 or mon is None:
        return 0
    remaining = max(0, sum(candy_stage_costs(state)) - mon.used_at_stage)
    needed = -(-remaining // balance.RARE_CANDY_XP)  # ceil
    return min(held, needed)


@dataclass(frozen=True, slots=True)
class CandyPlan:
    """What using `count` candies right now would do."""

    count: int
    xp: int
    evolves: bool
    graduates: bool
    carryover_xp: int
    discarded_xp: int


def plan_candy_use(state: CompanionState, count: int) -> CandyPlan | None:
    """Walk the stage costs to see how far `count` candies would get.

    None when nothing can be used. Carry-over is only reported when an
    evolution actually happens, and leftover XP at graduation is discarded
    rather than carried — there is nothing left to carry it into.
    """
    count = min(max(0, count), max_candy_uses(state))
    mon = state.active
    if count <= 0 or mon is None:
        return None
    xp = count * balance.RARE_CANDY_XP
    remaining = mon.used_at_stage + xp
    evolves = False
    costs = candy_stage_costs(state)
    for index, cost in enumerate(costs):
        if remaining < cost:
            break
        remaining -= cost
        if index == len(costs) - 1:
            return CandyPlan(count, xp, evolves, True, 0, remaining)
        evolves = True
    return CandyPlan(count, xp, evolves, False, remaining if evolves else 0, 0)


def use_item(state: CompanionState, key: str, rng=None, count: int = 1) -> ItemResult:
    """Consume held items — several candies at once, one of anything else."""
    held = state.inventory.get(key, 0)
    if held <= 0:
        raise ShopError(f"no {key} in bag")

    if key == "rareCandy":
        if state.active is None:
            raise ShopError("candy needs a hatched companion")
        plan = plan_candy_use(state, count)
        if plan is None:
            raise ShopError("this companion has no growth left for candy")
        # plan.count, not the request: the plan already refused to spend
        # candies the last threshold has no room for.
        state.inventory[key] = held - plan.count
        # Routed through apply_usage so carry-over, evolution, and graduation
        # all behave exactly as they do for real usage — and the events it
        # reports are handed back for the same reason.
        events = companion.apply_usage(state, plan.xp, rng=rng)
        return ItemResult(key, "use", events=events, count=plan.count)

    if key == "mint":
        if state.active is None:
            raise ShopError("mint needs a hatched companion")
        import random

        rng = rng or random.Random()
        state.inventory[key] = held - 1
        state.active.nature = companion.roll_nature(rng)
        return ItemResult(key, "use", nature=state.active.nature)

    raise ShopError(f"{key} cannot be used")


# --- rare candy grants -----------------------------------------------------


def window_key(kind: str) -> str:
    """Stable identifier for a limit window.

    Must never include volatile fields such as resets_at. Including them made
    the Swift app re-notify on every refresh, because a rolling weekly window
    reports a new resets_at each time.
    """
    return f"limit:{kind}"


# How far a reset instant has to move before it means a new window rather than
# noise. The endpoint answers with microseconds that differ on every fetch, and
# a rolling window drifts forward a little each time; either one read as a reset
# rearms the grant and pays out again, over and over, while the window sits at
# 100% (upstream d888793).
WINDOW_MIN_ADVANCE = {"session": 30 * 60.0, "weekly": 24 * 3600.0}


def window_advanced(previous: str, current: str, kind: str) -> bool:
    """Whether the window actually reset between these two instants.

    Instants that cannot be read fall back to comparing them as text, which is
    what a synthetic value in a test is.
    """
    if previous == current:
        return False
    before = pace.instant(previous)
    after = pace.instant(current)
    if before is None or after is None:
        return True
    # A window whose reset moved backwards is a different window too, but not
    # one this ever has to pay out twice for: only a forward jump counts.
    return (after - before) >= WINDOW_MIN_ADVANCE.get(kind.partition("@")[0], 30 * 60.0)


def grant_candy(
    state: CompanionState,
    windows: dict[str, float],
    epochs: dict[str, str | None] | None = None,
) -> int:
    """Award candy for maxed limit windows. Edge-triggered.

    `windows` maps kind ("session"/"weekly") to utilization percent, and
    `epochs` the same kinds to the instant each window resets. Returns how many
    candies were granted.
    """
    granted = 0
    for kind, utilization in windows.items():
        key = window_key(kind)
        epoch = (epochs or {}).get(kind)
        # A window that has reset since it last paid out is a new window: rearm
        # before judging it, or a user who fills the weekly limit every week
        # collects once and never again (upstream e94da86). Checked before the
        # utilization test, because a fresh window usually reports a high
        # utilization straight away rather than dipping through zero first.
        if epoch is not None:
            previous_epoch = state.candy_window_epoch.get(key)
            if previous_epoch is not None and window_advanced(previous_epoch, epoch, kind):
                state.candy_grant_tier.pop(key, None)
            # Recorded either way, so the next comparison is against the last
            # thing seen rather than against a baseline the drift creeps past.
            state.candy_window_epoch[key] = epoch
        tier = 2 if utilization >= 100 else (1 if utilization >= 80 else 0)
        previous = state.candy_grant_tier.get(key, 0)

        if tier == 0:
            # Dropped back below the warning line — rearm for next time.
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
            if kind == "weekly"
            else balance.RARE_CANDY_SESSION_GRANT
        )
        state.inventory["rareCandy"] = state.inventory.get("rareCandy", 0) + amount
        granted += amount

    state.candy_feature_seeded = True
    return granted
