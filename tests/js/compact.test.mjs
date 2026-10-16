/* The popup's compact formatter, which has to agree with the daemon's. The
 * cases come from poketokenbar/format.py's own docstring and tests. */

import assert from 'node:assert/strict';
import test from 'node:test';

import {compact, grouped} from '../../gnome-extension/poketokenbar@huhgeon.github.io/lib/format.js';

test('it matches the daemon at each magnitude', () => {
    assert.equal(compact(987), '987');
    assert.equal(compact(12345), '12.3K');
    assert.equal(compact(190612940), '190.6M');
    assert.equal(compact(1_240_000_000), '1.24B');
    assert.equal(compact(1_000_000), '1M');
    assert.equal(compact(0), '0');
    assert.equal(compact(-12345), '-12.3K');
});

test('a unit is promoted where its rounded text would overflow', () => {
    // "1000.0K" is not a thing anyone writes.
    assert.equal(compact(999_949), '999.9K');
    assert.equal(compact(999_950), '1M');
    assert.equal(compact(999_999), '1M');
    assert.equal(compact(999_949_999), '999.9M');
    assert.equal(compact(999_950_000), '1B');
    assert.equal(compact(-999_950), '-1M');
});

test('grouped is still the exact form', () => {
    assert.equal(grouped(190612940), '190,612,940');
});
