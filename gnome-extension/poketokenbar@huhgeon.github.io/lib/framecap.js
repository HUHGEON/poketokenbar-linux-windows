/* framecap.js — the sprite arithmetic, kept away from the Shell.
 *
 * Deliberately free of any gi:// import so it can be run and tested outside a
 * Shell. These are the pieces of sprite handling with an algorithm rather than
 * an API call, and the places a plausible-looking version is wrong.
 *
 * Two of them: how long a loop is (`loopLength`) and how many of its frames get
 * drawn (`capFrameRate`).
 *
 * The second ports GIFDecoder.capFrameRate. The rule that matters: **decimate, do not
 * hold.** Raising each frame's own delay to the floor keeps every frame and
 * stretches the whole loop — upstream measured a Gen-V sprite (55 frames x
 * 0.05s = 2.75s) turning into a 22s loop at a 0.4s floor, an eighth of the
 * intended speed. Dropping frames instead keeps one loop the same length as
 * the source and only lowers how many frames it is drawn with.
 */

// Presets, in seconds per frame. These are frame-duration floors, so a larger
// number is fewer frames per second.
//
// None of them is 0. Native frame rate is an idle-wakeup regression: the cost
// of a frame is a recomposite, and a sprite that never stops asking for one
// keeps the machine awake. "saver" is the default for the same reason.
export const FRAME_FLOORS = {
    saver: 0.4,     // about 2.5fps
    balanced: 0.2,  // about 5fps
    smooth: 0.1,    // about 10fps
};

export const DEFAULT_QUALITY = 'saver';

// Animation switched off entirely. Deliberately not a fourth entry in the
// table above: those are frame rates, and this is the absence of one — keeping
// it out is also what lets a test still say "the default is the slowest
// preset" and mean something.
//
// An infinite floor expresses it exactly. capFrameRate collapses the whole
// loop into its first frame held for the loop's own length, and a one-frame
// sprite never schedules a timer, so a still sprite costs no wakeups at all.
// That is the point of the setting: not only the movement it hides but the
// recomposites it stops.
export const ANIMATION_OFF = 'off';

export function frameFloor(quality) {
    if (quality === ANIMATION_OFF)
        return Infinity;
    return FRAME_FLOORS[quality] ?? FRAME_FLOORS[DEFAULT_QUALITY];
}

/**
 * The quality to draw at, given the system's power-saver mode (upstream
 * 37763d3).
 *
 * A derived value that never touches the saved choice: power-saver caps a
 * faster preset at "saver", a slower choice (or "off") is left alone, and
 * leaving power-saver simply stops capping. There is nothing to restore, so
 * nothing can be restored wrongly.
 */
export function effectiveQuality(quality, powerSaver) {
    if (!powerSaver || frameFloor(quality) >= FRAME_FLOORS.saver)
        return quality;
    return 'saver';
}

// How many frames in a row have to match before a repeat counts as the loop
// starting over rather than a pose the sprite strikes twice.
export const LOOP_SIGNATURE = 3;

/**
 * Where a decoded sequence starts over, or 0 when it never does.
 *
 * GdkPixbuf hands out frames forever — its iterator wraps round at the end of
 * the animation rather than stopping — so the decoder has to recognise the wrap
 * itself. One repeated frame is not evidence enough: a sprite returns to the
 * same pose several times per loop, and cutting at the first repeat of frame
 * one throws most of the animation away. Lombre's idle is 112 frames and comes
 * back to its opening pose at frame 33; only the run of frames after the repeat
 * tells the two apart.
 *
 * `digests` is one comparable value per frame, in order.
 */
export function loopLength(digests, signature = LOOP_SIGNATURE) {
    if (!Array.isArray(digests))
        return 0;
    const width = Math.max(1, signature);
    for (let start = 1; start + width <= digests.length; start++) {
        let matched = true;
        for (let offset = 0; offset < width; offset++) {
            if (digests[start + offset] !== digests[offset]) {
                matched = false;
                break;
            }
        }
        if (matched)
            return start;
    }
    return 0;
}

/**
 * Thin `frames` so no frame is shown for less than `floor` seconds.
 *
 * Each output frame is the first of its interval, held for the length of that
 * interval, so the total duration of one loop is unchanged.
 *
 * `frames` is `[{delay, ...}]` in seconds; everything else on a frame is
 * carried through untouched.
 */
export function capFrameRate(frames, floor) {
    if (!(floor > 0) || !Array.isArray(frames) || frames.length <= 1)
        return frames;

    const out = [];
    let held = null;
    let accumulated = 0;

    for (const frame of frames) {
        if (held === null)
            held = frame;
        accumulated += frame.delay;
        // The epsilon keeps floating-point accumulation from pushing an
        // interval one frame further than it should: 0.05 x 4 comes out as
        // 0.19999999999999998 as often as 0.20000000000000004.
        if (accumulated + 1e-9 >= floor) {
            out.push({...held, delay: accumulated});
            held = null;
            accumulated = 0;
        }
    }

    // A short tail is merged into the previous frame rather than emitted on its
    // own, so the loop still lasts exactly as long as the source did.
    if (held !== null && accumulated > 0) {
        if (out.length === 0)
            out.push({...held, delay: accumulated});
        else
            out[out.length - 1].delay += accumulated;
    }
    return out;
}
