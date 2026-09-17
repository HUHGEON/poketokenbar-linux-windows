/* The reset clock suffix, run under node. */

import assert from 'node:assert/strict';
import test from 'node:test';

import {resetClock} from '../../gnome-extension/poketokenbar@huhgeon.github.io/lib/resetclock.js';

const words = {
    reset_clock_far: '%1 %2, %3',
    weekday_thu: 'Thu',
    weekday_fri: 'Fri',
};
const t = key => words[key] ?? key;
const local = (y, mo, d, h, mi) => new Date(y, mo - 1, d, h, mi).getTime();

test('a reset later today is just the time', () => {
    const now = local(2026, 9, 17, 9, 0);
    assert.equal(resetClock(new Date(local(2026, 9, 17, 23, 5)).toISOString(), t, now), ' (23:05)');
});

test('within six hours stays short even across midnight', () => {
    const now = local(2026, 9, 17, 22, 0);
    assert.equal(resetClock(new Date(local(2026, 9, 18, 3, 30)).toISOString(), t, now), ' (03:30)');
});

test('further off names the weekday and day', () => {
    const now = local(2026, 9, 17, 9, 0);
    assert.equal(resetClock(new Date(local(2026, 9, 18, 16, 0)).toISOString(), t, now),
        ' (Fri 18, 16:00)');
});

test('nothing for a past, missing or broken instant', () => {
    const now = local(2026, 9, 17, 9, 0);
    assert.equal(resetClock(new Date(now - 1000).toISOString(), t, now), '');
    assert.equal(resetClock(null, t, now), '');
    assert.equal(resetClock('not a date', t, now), '');
});
