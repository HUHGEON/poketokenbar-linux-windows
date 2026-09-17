/* Runs the real frame-cap code under node, ports the cases from
 * SpriteAnimationTests / the capFrameRate documentation in the macOS app.
 *
 * This module imports nothing from gi://, which is the whole reason it can be
 * executed here at all — and the reason the algorithm was put in its own file.
 * Every other part of the sprite path is API calls that only a Shell can make;
 * this is the part with arithmetic in it, and arithmetic can be checked.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    ANIMATION_OFF, DEFAULT_QUALITY, FRAME_FLOORS, capFrameRate, frameFloor,
} from '../../gnome-extension/poketokenbar@huhgeon.github.io/lib/framecap.js';

const gen5 = () =>
    Array.from({length: 55}, (_, i) => ({id: i, delay: 0.05}));

const total = frames => frames.reduce((sum, f) => sum + f.delay, 0);

test('a loop keeps its length when it is thinned', () => {
    // The defect this exists to prevent: raising each frame to the floor keeps
    // 55 frames and turns 2.75s into 22s — an eighth of the intended speed.
    const source = gen5();
    const capped = capFrameRate(source, 0.4);
    assert.ok(Math.abs(total(capped) - total(source)) < 1e-9,
        'the capped loop must last exactly as long as the source');
});

test('thinning actually removes frames', () => {
    const capped = capFrameRate(gen5(), 0.4);
    assert.ok(capped.length < 55);
    // 0.05s frames against a 0.4s floor is eight per interval: six full
    // intervals cover 48 frames, and the seven left over are a 0.35s tail that
    // is merged into the sixth rather than emitted as a seventh.
    assert.equal(capped.length, 6);
    assert.ok(Math.abs(capped[5].delay - (0.4 + 0.35)) < 1e-9,
        'the tail is merged into the last frame, not dropped');
});

test('no frame is shown for less than the floor, except a merged tail', () => {
    const capped = capFrameRate(gen5(), 0.4);
    for (const frame of capped.slice(0, -1))
        assert.ok(frame.delay + 1e-9 >= 0.4, `frame held for only ${frame.delay}`);
});

test('the kept frame is the first of its interval', () => {
    const capped = capFrameRate(gen5(), 0.4);
    assert.equal(capped[0].id, 0);
    assert.equal(capped[1].id, 8);
});

test('everything else on a frame survives', () => {
    const frames = [
        {content: 'a', width: 10, height: 20, delay: 0.05},
        {content: 'b', width: 10, height: 20, delay: 0.05},
    ];
    const [first] = capFrameRate(frames, 0.1);
    assert.equal(first.content, 'a');
    assert.equal(first.width, 10);
    assert.equal(first.height, 20);
});

test('floating point accumulation does not shift an interval', () => {
    // 0.05 x 4 lands on 0.19999999999999998 as readily as 0.2000000000000000;
    // without the epsilon one interval in four takes a fifth frame.
    const capped = capFrameRate(Array.from({length: 40}, () => ({delay: 0.05})), 0.2);
    assert.equal(capped.length, 10);
});

test('a single frame is returned untouched', () => {
    const one = [{delay: 0.05}];
    assert.equal(capFrameRate(one, 0.4), one);
});

test('a zero or missing floor disables the cap', () => {
    const frames = gen5();
    assert.equal(capFrameRate(frames, 0), frames);
    assert.equal(capFrameRate(frames, undefined), frames);
});

test('a tail shorter than the floor is merged, not emitted', () => {
    // Three 0.05s frames against a 0.1s floor: one full interval, then a
    // half-length remainder that must not become its own frame.
    const capped = capFrameRate([{delay: 0.05}, {delay: 0.05}, {delay: 0.05}], 0.1);
    assert.equal(capped.length, 1);
    assert.ok(Math.abs(capped[0].delay - 0.15) < 1e-9);
});

test('frames already slower than the floor are left alone', () => {
    const slow = [{delay: 1.0}, {delay: 1.0}];
    const capped = capFrameRate(slow, 0.4);
    assert.equal(capped.length, 2);
    assert.ok(Math.abs(total(capped) - 2.0) < 1e-9);
});

test('no preset disables the cap', () => {
    // Native frame rate is an idle-wakeup regression: the cost of a frame is a
    // recomposite, and a sprite that never stops asking for one keeps the
    // machine awake.
    for (const [name, floor] of Object.entries(FRAME_FLOORS))
        assert.ok(floor > 0, `${name} would run at native frame rate`);
});

test('the default is the cheapest preset', () => {
    assert.equal(frameFloor(DEFAULT_QUALITY), Math.max(...Object.values(FRAME_FLOORS)));
});

test('an unknown quality falls back to the default rather than to no cap', () => {
    assert.equal(frameFloor('nonsense'), FRAME_FLOORS[DEFAULT_QUALITY]);
    assert.equal(frameFloor(undefined), FRAME_FLOORS[DEFAULT_QUALITY]);
});

test('switching animation off collapses a loop into one frame', () => {
    // One frame is what makes it free: the actor only ever schedules a timer
    // when it has more than one, so a still sprite costs no recomposites.
    const frames = [
        {delay: 0.05, id: 'a'},
        {delay: 0.05, id: 'b'},
        {delay: 0.05, id: 'c'},
        {delay: 0.05, id: 'd'},
    ];
    const capped = capFrameRate(frames, frameFloor(ANIMATION_OFF));
    assert.equal(capped.length, 1);
    assert.equal(capped[0].id, 'a', 'the still is the frame the sprite opens on');
    // The hold is the whole loop, which is what keeps every other length
    // calculation in this file true for the off case too.
    assert.ok(Math.abs(capped[0].delay - 0.2) < 1e-9);
});

test('off is not one of the presets', () => {
    // It is the absence of a frame rate, not a slower one. Folding it into the
    // table would quietly break "the default is the cheapest preset".
    assert.ok(!(ANIMATION_OFF in FRAME_FLOORS));
    assert.equal(frameFloor(ANIMATION_OFF), Infinity);
});

test('a single-frame sprite is unchanged by switching animation off', () => {
    const still = [{delay: 0, id: 'only'}];
    assert.deepEqual(capFrameRate(still, frameFloor(ANIMATION_OFF)), still);
});

test('power-saver caps a faster preset at saver and leaves slower ones alone', async () => {
    const {effectiveQuality} = await import(
        '../../gnome-extension/poketokenbar@huhgeon.github.io/lib/framecap.js');
    assert.equal(effectiveQuality('smooth', true), 'saver');
    assert.equal(effectiveQuality('balanced', true), 'saver');
    assert.equal(effectiveQuality('saver', true), 'saver');
    assert.equal(effectiveQuality(ANIMATION_OFF, true), ANIMATION_OFF);
    assert.equal(effectiveQuality('smooth', false), 'smooth', 'the saved choice is untouched');
});
