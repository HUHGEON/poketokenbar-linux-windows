/**
 * What a batch of Rare Candy would do, previewed in the popup.
 *
 * The rules live in the daemon (poketokenbar/shop.py: plan_candy_use) and are
 * enforced there; this mirrors the arithmetic so stepping the quantity answers
 * instantly instead of waiting for a poll. It works only on numbers the daemon
 * already rounded for this difficulty — `stage_costs` and `used_at_stage` — so
 * no growth rule is duplicated here. tests/js/candy.test.mjs pins it against
 * the Python cases.
 */

/** The quantity actually offered: never more than graduation can absorb. */
export function maxCandyUses(candy) {
    return Math.max(0, Math.trunc(candy?.max_use ?? 0));
}

/**
 * The plan for `count` candies, or null when there is nothing to use.
 *
 * `evolves`/`graduates` say what the batch reaches. Carry-over is only
 * reported when an evolution happens, and XP left over at graduation is
 * discarded — there is no next stage to carry it into.
 */
export function planCandyUse(candy, count) {
    const xpEach = Math.max(0, Math.trunc(candy?.xp ?? 0));
    const costs = candy?.stage_costs ?? [];
    const used = Math.max(0, Math.trunc(candy?.used_at_stage ?? 0));
    const n = Math.min(Math.max(0, Math.trunc(count || 0)), maxCandyUses(candy));
    if (n <= 0 || xpEach <= 0 || costs.length === 0)
        return null;

    const xp = n * xpEach;
    let remaining = used + xp;
    let evolves = false;
    for (let index = 0; index < costs.length; index++) {
        if (remaining < costs[index])
            break;
        remaining -= costs[index];
        if (index === costs.length - 1)
            return {count: n, xp, evolves, graduates: true, carryoverXP: 0, discardedXP: remaining};
        evolves = true;
    }
    return {
        count: n, xp, evolves, graduates: false,
        carryoverXP: evolves ? remaining : 0, discardedXP: 0,
    };
}
