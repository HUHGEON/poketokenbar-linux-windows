/* Refresh-on-reconnect, run under node. Ports NetworkReachabilityTests.swift. */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    ReconnectWatch, shouldRefresh,
} from '../../gnome-extension/poketokenbar@huhgeon.github.io/lib/reconnect.js';

test('the first report is never a reconnect', () => {
    assert.equal(shouldRefresh(null, true, null, 0), false);
});

test('only offline to online triggers', () => {
    assert.equal(shouldRefresh(false, true, null, 0), true);
    assert.equal(shouldRefresh(true, true, null, 0), false);
    assert.equal(shouldRefresh(true, false, null, 0), false);
    assert.equal(shouldRefresh(false, false, null, 0), false);
});

test('a flapping interface triggers once per cooldown', () => {
    let now = 0;
    let refreshes = 0;
    const watch = new ReconnectWatch(() => refreshes++, () => now);
    watch.report(false);
    now = 1000; watch.report(true);
    now = 2000; watch.report(false);
    now = 3000; watch.report(true);
    assert.equal(refreshes, 1, 'the second reconnect is inside the cooldown');
    now = 9000; watch.report(false);
    now = 9500; watch.report(true);
    assert.equal(refreshes, 2);
});
