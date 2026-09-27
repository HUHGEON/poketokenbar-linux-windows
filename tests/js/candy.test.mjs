/* The Rare Candy batch preview, run under node. Mirrors tests/test_shop.py's
 * plan cases, so the popup and the daemon cannot disagree about what a batch
 * would do. */

import assert from 'node:assert/strict';
import test from 'node:test';

import {planCandyUse, maxCandyUses} from '../../gnome-extension/poketokenbar@huhgeon.github.io/lib/candy.js';

// One stage left, costing 300; a candy is worth 100.
const oneStage = {xp: 100, max_use: 3, stage_costs: [300], used_at_stage: 0};
// Two stages of 300, the first half paid for.
const twoStages = {xp: 100, max_use: 6, stage_costs: [300, 300], used_at_stage: 150};

test('nothing to use has no plan', () => {
    assert.equal(planCandyUse(oneStage, 0), null);
    assert.equal(planCandyUse({xp: 100, max_use: 0, stage_costs: [300], used_at_stage: 0}, 2), null);
    assert.equal(planCandyUse(undefined, 1), null);
});

test('a batch short of the threshold only progresses', () => {
    assert.deepEqual(planCandyUse(oneStage, 2),
        {count: 2, xp: 200, evolves: false, graduates: false, carryoverXP: 0, discardedXP: 0});
});

test('the last stage graduates and discards the leftover', () => {
    assert.deepEqual(planCandyUse({...oneStage, max_use: 4}, 4),
        {count: 4, xp: 400, evolves: false, graduates: true, carryoverXP: 0, discardedXP: 100});
});

test('clearing a middle stage evolves and carries the rest over', () => {
    assert.deepEqual(planCandyUse(twoStages, 2),
        {count: 2, xp: 200, evolves: true, graduates: false, carryoverXP: 50, discardedXP: 0});
});

test('a batch that clears every stage graduates', () => {
    const plan = planCandyUse(twoStages, 5);
    assert.equal(plan.graduates, true);
    assert.equal(plan.discardedXP, 50);   // 150 banked + 500 spent - 600 of stages
});

test('the request is clamped to what the bag and the stages allow', () => {
    assert.equal(planCandyUse(oneStage, 99).count, 3);
    assert.equal(maxCandyUses(twoStages), 6);
    assert.equal(maxCandyUses(undefined), 0);
});
