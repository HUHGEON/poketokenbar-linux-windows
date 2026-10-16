/* The type-chart colours the popup paints its badges with. */

import assert from 'node:assert/strict';
import test from 'node:test';

import {TYPE_COLORS, typeColor} from '../../gnome-extension/poketokenbar@huhgeon.github.io/lib/types.js';

test('it knows all eighteen main-series types', () => {
    const types = ['normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting',
        'poison', 'ground', 'flying', 'psychic', 'bug', 'rock', 'ghost', 'dragon',
        'dark', 'steel', 'fairy'];
    assert.deepEqual(Object.keys(TYPE_COLORS).sort(), [...types].sort());
});

test('the colours are the ones the games use', () => {
    assert.equal(typeColor('fire'), '#ff4422');
    assert.equal(typeColor('water'), '#3399ff');
    assert.equal(typeColor('fairy'), '#ee99ee');
});

test('the lookup ignores case, and an unknown type has no colour', () => {
    assert.equal(typeColor('Electric'), '#ffcc33');
    assert.equal(typeColor('ELECTRIC'), '#ffcc33');
    assert.equal(typeColor('stellar'), null);
    assert.equal(typeColor(null), null);
    assert.equal(typeColor(undefined), null);
});

test('every colour is a six-digit hex triple', () => {
    for (const [name, color] of Object.entries(TYPE_COLORS))
        assert.match(color, /^#[0-9a-f]{6}$/, name);
});
