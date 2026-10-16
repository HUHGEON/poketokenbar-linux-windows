/* sprite.js — animated Gen-V sprites as Shell actors.
 *
 * The Plasma port got this for free: QML's AnimatedImage plays a GIF directly.
 * St has no equivalent, so the frames are decoded with GdkPixbuf and swapped on
 * a timer, which is what the macOS app does with ImageIO.
 *
 * Cheap on purpose. A Shell extension runs inside the compositor process, so a
 * frame swap here is a local content assignment with no IPC — but a leaked
 * timer is a leak in the compositor, which is why every actor stops its own on
 * destroy.
 */

import Clutter from 'gi://Clutter';
import Cogl from 'gi://Cogl';
import GdkPixbuf from 'gi://GdkPixbuf';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import {DEFAULT_QUALITY, LOOP_SIGNATURE, capFrameRate, frameFloor, loopLength}
    from './framecap.js';
import {fitSize} from './spritefit.js';

// GIF authoring commonly writes 0 or 10ms delays meaning "as fast as possible",
// which browsers clamp. Without a floor a sprite would spin the compositor.
const MINIMUM_FRAME_MS = 20;
// Frames past this are dropped. Gen-V sprites run ~55 frames; anything far
// beyond that is not one of ours and is not worth the memory.
const MAX_FRAMES = 240;

/** The Cogl context `set_bytes` wants, on the versions that want one.
 *
 * GNOME 48 gave `St.ImageContent.set_bytes` and `set_data` a new first
 * parameter. Resolved lazily and remembered: `global` does not exist until the
 * Shell is up, so reaching for it at import time throws before the extension
 * has even loaded.
 */
let coglContext;
let coglContextResolved = false;

function getCoglContext() {
    if (!coglContextResolved) {
        coglContextResolved = true;
        try {
            coglContext = global.stage.context.get_backend().get_cogl_context();
        } catch (_e) {
            // Older Shell: there is no such parameter to pass.
            coglContext = null;
        }
    }
    return coglContext;
}

/** `set_bytes` gained a leading `Cogl.Context` in GNOME 48.
 *
 * Tried in turn rather than version-checked: the manifest spans 45 to 51, and
 * a version check would be a second thing to keep correct across all of them.
 *
 * `new_with_preferred_size` needs no such handling — it has taken two ints in
 * every release, checked against the headers on both gnome-48 and main. An
 * earlier version of this file guessed otherwise while chasing the GrapheneSize
 * error, which turned out to come from the actor constructor instead.
 */
function setContentBytes(content, bytes, format, width, height, rowstride) {
    const context = getCoglContext();
    if (context) {
        try {
            content.set_bytes(context, bytes, format, width, height, rowstride);
            return;
        } catch (_e) {
            // Fall through to the older four-argument form.
        }
    }
    content.set_bytes(bytes, format, width, height, rowstride);
}

/** Content ready to assign, with the pixel size that goes with it.
 *
 * Matches the pattern GNOME Shell's own screenshot UI uses: an ImageContent
 * sized to the pixbuf, then the raw bytes with their format and rowstride.
 */
function frameFromPixbuf(pixbuf, delay) {
    const width = pixbuf.get_width();
    const height = pixbuf.get_height();
    const content = St.ImageContent.new_with_preferred_size(width, height);
    setContentBytes(
        content,
        pixbuf.read_pixel_bytes(),
        pixbuf.get_has_alpha() ? Cogl.PixelFormat.RGBA_8888 : Cogl.PixelFormat.RGB_888,
        width,
        height,
        pixbuf.get_rowstride());
    return {content, delay, width, height};
}

/** The animation's own clock, as the GTimeVal the iterator still takes.
 *
 * GLib.TimeVal is deprecated and gdk_pixbuf_animation_iter_advance has no
 * replacement that takes anything else, so the choice is this or the documented
 * shortcut of passing null — and null means "now". A decode loop finishes in
 * microseconds, so "now" never reaches the second frame: every sprite came out
 * as two copies of frame one and sat there, perfectly still, on a panel that
 * was supposed to be animating.
 */
function clockAt(milliseconds) {
    return new GLib.TimeVal({
        tv_sec: Math.floor(milliseconds / 1000),
        tv_usec: Math.round(milliseconds % 1000) * 1000,
    });
}

/** What a frame looks like, as a value that can be compared to another frame.
 *
 * The iterator hands back one pixbuf and rewrites its pixels in place, so
 * frames cannot be compared by identity, and holding their bytes to compare
 * later would compare every frame with itself. A digest taken on the spot is
 * the one thing that survives the next advance. MD5 because it is the cheapest
 * one GLib offers; nothing here is a secret.
 */
function digestOf(pixbuf) {
    return GLib.compute_checksum_for_bytes(
        GLib.ChecksumType.MD5, pixbuf.read_pixel_bytes());
}

function stillFrame(pixbuf) {
    try {
        return [frameFromPixbuf(pixbuf, 0)];
    } catch (_e) {
        return [];
    }
}

/**
 * Decode every frame of a sprite file.
 *
 * Returns [] when the file cannot be read, so callers fall back to a glyph
 * rather than rendering a broken image. A still PNG comes back as one frame,
 * which is also what a GIF with a single frame should look like.
 *
 * The animation is walked on its own clock rather than the wall clock, and the
 * walk stops where `loopLength` says the sequence starts over — the iterator
 * itself never stops, it just wraps round and hands out the loop again.
 */
export function decodeFrames(path) {
    if (!path)
        return [];
    let animation;
    try {
        animation = GdkPixbuf.PixbufAnimation.new_from_file(path);
    } catch (_e) {
        return [];
    }

    if (animation.is_static_image())
        return stillFrame(animation.get_static_image());

    let iter;
    try {
        iter = animation.get_iter(clockAt(0));
    } catch (_e) {
        // No usable GTimeVal on this GLib. One still frame is a worse sprite
        // than an animated one and a much better one than none.
        return stillFrame(animation.get_static_image());
    }

    const frames = [];
    // One digest per kept frame, so `loopLength` compares what is on screen
    // rather than what came off the decoder.
    const digests = [];
    let elapsed = 0;
    // The extra room is what the loop signature is matched in: the wrap is only
    // provable a few frames after it has happened.
    for (let i = 0; i < MAX_FRAMES + LOOP_SIGNATURE; i++) {
        // get_delay_time is milliseconds; the frames themselves and framecap
        // work in seconds, so the conversion happens once, here.
        const delay = Math.max(MINIMUM_FRAME_MS, iter.get_delay_time());
        let pixbuf;
        try {
            pixbuf = iter.get_pixbuf();
        } catch (_e) {
            break;
        }
        const digest = digestOf(pixbuf);

        if (digests.length > 0 && digest === digests[digests.length - 1]) {
            // Gen-V sprites hold a pose across several frames — Lombre draws
            // 112 frames out of 47 distinct images. Lengthening the frame
            // before it looks identical and saves that many texture uploads.
            frames[frames.length - 1].delay += delay / 1000;
        } else {
            let frame;
            try {
                frame = frameFromPixbuf(pixbuf, delay / 1000);
            } catch (_e) {
                break;
            }
            frames.push(frame);
            digests.push(digest);
        }

        const loop = loopLength(digests);
        if (loop > 0)
            return frames.slice(0, loop);

        elapsed += delay;
        if (elapsed > 60000)
            break;  // pathological file; keep what we have
        try {
            iter.advance(clockAt(elapsed));
        } catch (_e) {
            break;
        }
    }
    return frames.slice(0, MAX_FRAMES);
}

/* Decoded frames, keyed by path.
 *
 * Rebuilding a section makes fresh Sprite actors for files that have not
 * changed — the Pokedex grid alone is 24 of them — and decoding one Gen-V GIF
 * means uploading ~55 textures. Clutter content is refcounted and shareable
 * between actors, so a second Sprite on the same path can simply be handed the
 * frames the first one decoded.
 */
const frameCache = new Map();

// Bounded because the entries are textures living in the compositor, and a
// full Pokedex is a thousand species. Comfortably more than one popup shows.
const MAX_CACHED_SPRITES = 96;

function cachedFrames(path) {
    if (frameCache.has(path)) {
        // Re-inserted so the least recently used entry is the one that goes:
        // Map iterates in insertion order.
        const frames = frameCache.get(path);
        frameCache.delete(path);
        frameCache.set(path, frames);
        return frames;
    }
    const frames = decodeFrames(path);
    frameCache.set(path, frames);
    if (frameCache.size > MAX_CACHED_SPRITES)
        frameCache.delete(frameCache.keys().next().value);
    return frames;
}

/** Drop every decoded sprite. Called from disable(): the textures are held in
 * the compositor's memory, and a disabled extension must not be holding any. */
export function clearFrameCache() {
    frameCache.clear();
}

/**
 * An actor that plays a decoded sprite.
 *
 * `size` is the square box the sprite fits inside. Gen-V GIF canvases are not
 * square and differ per species — Spoink is 36x66, Pikachu 50x46 — so a plain
 * size x size assignment stretches them. The aspect is preserved and the actor
 * asks for the fitted width, which is also what keeps the panel from jumping
 * as the companion evolves.
 */
export const Sprite = GObject.registerClass(
class Sprite extends St.Widget {
    _init(params = {}) {
        // `size` is ours, and it must not reach the actor's constructor.
        //
        // Clutter.Actor already has a `size` property and its type is the boxed
        // graphene_size_t, so spreading this straight through made every
        // `new Sprite({size: 18})` throw "Wrong type number; boxed type
        // GrapheneSize expected" — which took the whole extension down before
        // it had drawn anything, because the panel builds a sprite first.
        // `maxWidth` is ours as well: the panel lets a wide sprite grow past
        // its box rather than shrink to fit the width (upstream 481ad3a).
        const {size = 22, maxWidth = 0, ...actorParams} = params;
        super._init({
            style_class: 'poketokenbar-sprite',
            // Pixel art: never smooth it.
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            ...actorParams,
        });
        this._size = size;
        this._maxWidth = maxWidth || size;
        this._frames = [];
        this._index = 0;
        this._timer = 0;
        this._path = null;
        this._paused = false;
        this._quality = DEFAULT_QUALITY;
        // Frames as decoded, before the rate cap. Kept so changing quality does
        // not mean re-reading and re-uploading the whole GIF.
        this._sourceFrames = [];

        this.connect('destroy', () => this._stopTimer());
    }

    /** Point the actor at a sprite file. A repeat of the same path is a no-op.
     *
     * Re-decoding on every poll would rebuild ~55 textures every two seconds
     * for a sprite that had not changed.
     */
    setPath(path) {
        if (path === this._path)
            return;
        this._path = path;
        this._stopTimer();
        this._index = 0;
        // A sprite that cannot be decoded must cost the numbers nothing. This
        // is the one place the extension touches an API whose signature moved
        // between the versions the manifest claims, and an uncaught throw here
        // takes the whole panel down — usage tracker included — over a picture.
        try {
            this._sourceFrames = cachedFrames(path);
        } catch (error) {
            logError(error, `PokeTokenBar: could not decode ${path}`);
            this._sourceFrames = [];
        }
        this._frames = capFrameRate(this._sourceFrames, frameFloor(this._quality));

        if (this._frames.length === 0) {
            this.content = null;
            this.visible = false;
            return;
        }
        this.visible = true;
        this._applyFrame(0);
        if (this._frames.length > 1 && !this._paused)
            this._scheduleNext();
    }

    /** Change how smoothly this sprite animates.
     *
     * Re-caps the frames already decoded rather than reading the file again:
     * the pixels have not changed, only how many of them get drawn.
     */
    setQuality(quality) {
        if (quality === this._quality)
            return;
        this._quality = quality;
        if (this._sourceFrames.length === 0)
            return;
        this._stopTimer();
        this._frames = capFrameRate(this._sourceFrames, frameFloor(quality));
        this._index = 0;
        this._applyFrame(0);
        if (this._frames.length > 1 && !this._paused)
            this._scheduleNext();
    }

    setSize(size) {
        if (this._maxWidth === this._size)
            this._maxWidth = size;
        if (size === this._size)
            return;
        this._size = size;
        if (this._frames.length > 0)
            this._applyFrame(this._index);
    }

    /** Stop or resume animating without discarding the decoded frames.
     *
     * Used when the popup closes and while the screen is locked or blanked:
     * a sprite nobody can see must not keep waking the compositor.
     */
    setPaused(paused) {
        if (paused === this._paused)
            return;
        this._paused = paused;
        if (paused)
            this._stopTimer();
        else if (this._frames.length > 1)
            this._scheduleNext();
    }

    _applyFrame(index) {
        const frame = this._frames[index];
        if (!frame)
            return;
        this.content = frame.content;
        // The natural size is carried on the frame, not asked of the content.
        // Clutter.Content.get_preferred_size returns a boolean with width and
        // height as out-parameters, so in GJS it is [ok, width, height] —
        // destructuring two names off it silently binds the boolean to width.
        const {width, height} = frame;
        const fitted = fitSize(width, height, this._size, this._maxWidth);
        this.set_size(fitted.width, fitted.height);
    }

    _scheduleNext() {
        const frame = this._frames[this._index];
        // framecap works in seconds, GLib in milliseconds.
        const delay = Math.max(
            MINIMUM_FRAME_MS, Math.round((frame ? frame.delay : 0.1) * 1000));
        this._timer = GLib.timeout_add(GLib.PRIORITY_DEFAULT, delay, () => {
            this._timer = 0;
            this._index = (this._index + 1) % this._frames.length;
            this._applyFrame(this._index);
            this._scheduleNext();
            return GLib.SOURCE_REMOVE;
        });
    }

    _stopTimer() {
        if (this._timer) {
            GLib.Source.remove(this._timer);
            this._timer = 0;
        }
    }
});
