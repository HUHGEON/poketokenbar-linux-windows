/* pet.js — the companion, living on the desktop.
 *
 * This is the one feature a normal Linux app cannot do on Wayland: a client
 * has no way to place its own window at an absolute position, so the pet could
 * never be dragged or restored where it was left. An extension is not a client
 * — it runs inside the compositor and puts an actor straight on the stage — so
 * the whole limitation is simply absent here.
 *
 * The actor is added to the layout manager's chrome, so it floats above
 * windows the way the macOS panel does, and steps out of the way of anything
 * fullscreen.
 */

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import {DEFAULT_QUALITY, effectiveQuality} from './framecap.js';
import {isPowerSaver} from './power.js';
import {Sprite} from './sprite.js';

// How far a press may travel and still count as a click rather than a drag.
// Without this every click ends as a one-pixel drag and the popup never opens.
const CLICK_SLOP = 4;

// How far above the pet its caption sits.
const TOOLTIP_GAP = 24;

export const DesktopPet = GObject.registerClass(
class DesktopPet extends St.Widget {
    _init(reader, {onActivate, onSavePosition} = {}) {
        super._init({
            style_class: 'poketokenbar-pet',
            reactive: true,
            track_hover: true,
            can_focus: false,
        });
        this._reader = reader;
        this._onActivate = onActivate ?? (() => {});
        this._onSavePosition = onSavePosition ?? (() => {});

        this._sprite = new Sprite({size: 96});
        this.add_child(this._sprite);

        this._tooltip = new St.Label({style_class: 'poketokenbar-pet-tooltip'});
        this._tooltip.hide();
        // Chrome claims an actor's rectangle for input by default, and a label
        // that takes input right above the pet is a rectangle the pointer keeps
        // falling into: hover showed the tooltip, the tooltip took the pointer,
        // the pet saw a leave, the tooltip went away — a flicker for as long as
        // the mouse sat there. It is a caption; it has no business taking
        // clicks.
        Main.layoutManager.addTopChrome(this._tooltip, {affectsInputRegion: false});

        this._dragging = false;
        this._pressPoint = null;
        this._grab = null;

        this.connect('button-press-event', (_a, event) => this._onPress(event));
        this.connect('motion-event', (_a, event) => this._onMotion(event));
        this.connect('button-release-event', (_a, event) => this._onRelease(event));
        this.connect('enter-event', () => this._showTooltip());
        this.connect('leave-event', () => this._tooltip.hide());
        this.connect('destroy', () => {
            // A grab outlives the actor that took it. Dropped mid-drag — by a
            // disable, or by the pet being switched off — it would leave the
            // session routing every pointer event at an actor that is gone.
            this._releaseGrab();
            this._tooltip.destroy();
        });
    }

    setSize(size) {
        this._sprite.setSize(size);
        this.set_size(size, size);
    }

    setPaused(paused) {
        this._sprite.setPaused(paused);
    }

    update(state) {
        // The pet follows the panel, so a pinned species shows here too.
        this._sprite.setPath(state?.panel?.sprite_path || null);
        // Both always-visible surfaces share one setting, as they do upstream.
        this._sprite.setQuality(effectiveQuality(
            state?.config?.animation_quality ?? DEFAULT_QUALITY, isPowerSaver()));
        this._tooltipText = state?.today?.tokens_grouped ?? '';
        if (this._tooltip.visible)
            this._showTooltip();
    }

    /** Place the pet, clamped so it can never be dragged off every monitor.
     *
     * A position saved on a monitor that is no longer attached would otherwise
     * leave the pet invisible with no way to get it back.
     */
    place(x, y) {
        const work = Main.layoutManager.getWorkAreaForMonitor(
            Main.layoutManager.primaryIndex);
        const size = this.get_width() || 96;
        const clampedX = Math.max(work.x, Math.min(x, work.x + work.width - size));
        const clampedY = Math.max(work.y, Math.min(y, work.y + work.height - size));
        this.set_position(Math.round(clampedX), Math.round(clampedY));
    }

    _showTooltip() {
        if (!this._tooltipText)
            return;
        this._tooltip.text = this._tooltipText;
        const [x, y] = this.get_transformed_position();
        const work = Main.layoutManager.getWorkAreaForMonitor(
            Main.layoutManager.primaryIndex);
        // Above the pet, unless there is no room above it — a pet parked under
        // the top bar would otherwise caption itself off the top of the screen.
        const above = y - TOOLTIP_GAP;
        const top = above >= work.y ? above : y + this.get_height();
        this._tooltip.set_position(Math.round(x), Math.round(top));
        this._tooltip.show();
    }

    _onPress(event) {
        const [x, y] = event.get_coords();
        if (event.get_button() === Clutter.BUTTON_SECONDARY) {
            this._onActivate('menu');
            return Clutter.EVENT_STOP;
        }
        this._pressPoint = {x, y, actor: this.get_position()};
        this._dragging = false;
        // Without a grab an actor only hears about the pointer while the
        // pointer is over it. A 96px pet is smaller than the distance a hand
        // moves between two frames, so a drag broke up the moment the cursor
        // outran it — and the button release landed on whatever was underneath
        // instead, leaving the press live. The next time the mouse so much as
        // crossed the pet, it picked the drag straight back up.
        this._takeGrab();
        return Clutter.EVENT_STOP;
    }

    _takeGrab() {
        this._releaseGrab();
        try {
            this._grab = global.stage.grab(this);
        } catch (error) {
            // A refused grab costs a smooth drag, not the pet: without one the
            // press still works, it just stops tracking at the actor's edge.
            logError(error, 'PokeTokenBar: could not grab the pointer');
            this._grab = null;
        }
    }

    _releaseGrab() {
        if (!this._grab)
            return;
        this._grab.dismiss();
        this._grab = null;
    }

    _onMotion(event) {
        if (!this._pressPoint)
            return Clutter.EVENT_PROPAGATE;
        const [x, y] = event.get_coords();
        const dx = x - this._pressPoint.x;
        const dy = y - this._pressPoint.y;
        if (!this._dragging && Math.hypot(dx, dy) < CLICK_SLOP)
            return Clutter.EVENT_STOP;
        this._dragging = true;
        this._tooltip.hide();
        this.place(this._pressPoint.actor[0] + dx, this._pressPoint.actor[1] + dy);
        return Clutter.EVENT_STOP;
    }

    _onRelease(_event) {
        this._releaseGrab();
        if (!this._pressPoint)
            return Clutter.EVENT_PROPAGATE;
        const wasDragging = this._dragging;
        this._pressPoint = null;
        this._dragging = false;
        if (wasDragging) {
            const [x, y] = this.get_position();
            this._onSavePosition(x, y);
        } else {
            this._onActivate('click');
        }
        return Clutter.EVENT_STOP;
    }
});
