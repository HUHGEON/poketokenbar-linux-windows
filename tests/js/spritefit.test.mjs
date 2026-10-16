/* How a sprite's canvas is fitted to the box that draws it. */

import assert from 'node:assert/strict';
import test from 'node:test';

import {fitSize} from '../../gnome-extension/poketokenbar@huhgeon.github.io/lib/spritefit.js';

test('a square fit touches the long edge and keeps the aspect', () => {
    assert.deepEqual(fitSize(96, 96, 18), {width: 18, height: 18});
    assert.deepEqual(fitSize(120, 60, 18), {width: 18, height: 9});
});

test('a wide sprite fills the panel height when it may grow wider', () => {
    // Swanna's spread wings, 137x69: 9px tall in a square box, 18 with room.
    assert.deepEqual(fitSize(137, 69, 18, 32), {width: 32, height: 16});
    // Tynamo, 57x19, is wide enough that the width cap still binds.
    assert.deepEqual(fitSize(57, 19, 18, 32), {width: 32, height: 11});
    // An ordinary square sprite is unaffected by the allowance.
    assert.deepEqual(fitSize(96, 96, 18, 32), {width: 18, height: 18});
});

test('a canvas of no size falls back to the box', () => {
    assert.deepEqual(fitSize(0, 0, 18, 32), {width: 18, height: 18});
    assert.deepEqual(fitSize(undefined, 96, 18), {width: 18, height: 18});
});

test('nothing is ever drawn at zero', () => {
    assert.deepEqual(fitSize(400, 1, 18, 32), {width: 32, height: 1});
});
