/* Searching, sorting and filtering the collection lists, run under node. */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    DEX_SORTS, LOG_SORTS, dexRows, fold, logRows, search, sortLabelKey,
} from '../../gnome-extension/poketokenbar@huhgeon.github.io/lib/dexfilter.js';

const row = (id, name, rarity, extra = {}) => ({
    species_id: id, name, rarity, is_shiny: false,
    // As the daemon ships it: folded, with the number and every language's name.
    search: fold(`#${id} ${name}`),
    ...extra,
});

const dex = [
    row(1, 'Bulbasaur', 'common'),
    row(25, 'Pikachu', 'rare'),
    row(125, 'Electabuzz', 'uncommon', {is_shiny: true}),
    row(669, 'Flabébé', 'legendary'),
];

test('a blank query filters nothing', () => {
    assert.equal(search(dex, '').length, 4);
    assert.equal(search(dex, '   ').length, 4);
});

test('a name matches without its accents', () => {
    assert.deepEqual(search(dex, 'flabebe').map(r => r.species_id), [669]);
    assert.deepEqual(search(dex, 'FLABÉBÉ').map(r => r.species_id), [669]);
});

test('a number matches with or without the hash, partially included', () => {
    assert.deepEqual(search(dex, '#25').map(r => r.species_id), [25]);
    // "25" is also in "#125", which is what a partial number search means.
    assert.deepEqual(search(dex, '25').map(r => r.species_id), [25, 125]);
});

test('the chips, the shiny toggle and the query all narrow together', () => {
    assert.deepEqual(dexRows(dex, {rarity: 'rare'}).map(r => r.species_id), [25]);
    assert.deepEqual(dexRows(dex, {shinyOnly: true}).map(r => r.species_id), [125]);
    assert.deepEqual(dexRows(dex, {shinyOnly: true, query: 'pika'}), []);
});

test('the dex sorts by number, name and rarity', () => {
    assert.deepEqual(dexRows(dex, {sort: 'number_asc'}).map(r => r.species_id), [1, 25, 125, 669]);
    assert.deepEqual(dexRows(dex, {sort: 'number_desc'}).map(r => r.species_id), [669, 125, 25, 1]);
    assert.deepEqual(dexRows(dex, {sort: 'name_asc'}).map(r => r.name),
        ['Bulbasaur', 'Electabuzz', 'Flabébé', 'Pikachu']);
    assert.deepEqual(dexRows(dex, {sort: 'rarity_desc'}).map(r => r.rarity),
        ['legendary', 'rare', 'uncommon', 'common']);
});

test('the log keeps the daemon order for "most recent" and reverses it for oldest', () => {
    const log = [row(3, 'Venusaur', 'common'), row(6, 'Charizard', 'rare')];
    assert.deepEqual(logRows(log, {sort: 'date_desc'}).map(r => r.species_id), [3, 6]);
    assert.deepEqual(logRows(log, {sort: 'date_asc'}).map(r => r.species_id), [6, 3]);
    // And sorting must not scramble the caller's own array.
    assert.deepEqual(log.map(r => r.species_id), [3, 6]);
});

test('every offered sort names a catalogue key', () => {
    for (const sort of [...DEX_SORTS, ...LOG_SORTS])
        assert.match(sortLabelKey(sort), /^sort_[a-z_]+$/);
});
