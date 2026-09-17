/* widgets.js — the small pieces every popup section builds out of.
 *
 * Kept together so the popup reads as layout rather than as St boilerplate, and
 * so a spacing or colour decision lands in one place instead of five.
 */

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';
import St from 'gi://St';

/** Utilisation bands, matching limits.level() in the daemon. */
export function levelClass(level) {
    if (level === 'crit')
        return 'poketokenbar-crit';
    if (level === 'warn')
        return 'poketokenbar-warn';
    return 'poketokenbar-ok';
}

/**
 * A vertical St.BoxLayout, whichever way this Shell wants to be told.
 *
 * `vertical` is deprecated as of GNOME 48 and slated for removal, and its
 * replacement `orientation` is not documented as existing in 45. Rather than
 * pick one and hope, the property that is actually present wins — which is also
 * the only way one file can serve the whole 45-49 range this extension claims.
 */
export function verticalBox(params = {}) {
    const box = new St.BoxLayout(params);
    if ('orientation' in box)
        box.orientation = Clutter.Orientation.VERTICAL;
    else
        box.vertical = true;
    return box;
}

export function label(text, styleClass = '') {
    return new St.Label({
        text: text ?? '',
        style_class: styleClass,
        y_align: Clutter.ActorAlign.CENTER,
    });
}

/**
 * A label for a sentence rather than a value: it wraps instead of running off.
 *
 * St.Label lays a line out at its natural width and the popup is a fixed 380px,
 * so every shop description was cut off mid-sentence — "Send off your current
 * Pokemon for an egg guarant…" is not a description of anything. Wrapping needs
 * three things together: the wrap flag, a wrap mode, and ellipsize turned off,
 * because the default ellipsize wins over line_wrap and re-truncates the text.
 * The actor also has to be allowed to expand, or it wraps at its natural width
 * and every word ends up on its own line.
 */
export function paragraph(text, styleClass = '') {
    const widget = new St.Label({
        text: text ?? '',
        style_class: styleClass,
        x_expand: true,
        y_align: Clutter.ActorAlign.CENTER,
    });
    widget.clutter_text.line_wrap = true;
    widget.clutter_text.line_wrap_mode = Pango.WrapMode.WORD_CHAR;
    widget.clutter_text.ellipsize = Pango.EllipsizeMode.NONE;
    return widget;
}

export function row(children, styleClass = 'poketokenbar-row') {
    const box = new St.BoxLayout({style_class: styleClass});
    for (const child of children)
        box.add_child(child);
    return box;
}

export function column(children, styleClass = 'poketokenbar-column') {
    const box = verticalBox({style_class: styleClass});
    for (const child of children)
        box.add_child(child);
    return box;
}

/** A left label and a right value on one line. */
export function statLine(name, value, valueClass = 'poketokenbar-value') {
    const left = label(name, 'poketokenbar-key');
    const spacer = new St.Widget({x_expand: true});
    return row([left, spacer, label(value, valueClass)]);
}

/**
 * A horizontal progress bar.
 *
 * Drawn as two nested widgets rather than with a repaint handler: the fill only
 * ever changes width, and letting the layout do that keeps it out of the
 * compositor's paint path.
 */
export const Meter = GObject.registerClass(
class Meter extends St.Widget {
    _init(styleClass = 'poketokenbar-meter') {
        super._init({style_class: styleClass, x_expand: true});
        this._fill = new St.Widget({style_class: 'poketokenbar-meter-fill'});
        this.add_child(this._fill);
        this._fraction = 0;
    }

    /** `fraction` is 0..1; anything past 1 is clamped so a full bar stays full. */
    setFraction(fraction, level = 'ok') {
        this._fraction = Math.max(0, Math.min(1, fraction || 0));
        this._fill.style_class = `poketokenbar-meter-fill ${levelClass(level)}`;
        this.queue_relayout();
    }

    /**
     * The fill is sized from the allocation, not measured when it is set.
     *
     * Every caller fills a meter in before adding it to its section, so asking
     * `get_width()` there measures an actor that is not in the tree yet — which
     * makes St log `st_widget_get_theme_node called on the widget ... which is
     * not in the stage` for each meter on each poll. Sizing here instead is
     * also simply the right place: the width is not known until then.
     */
    vfunc_allocate(box) {
        super.vfunc_allocate(box);
        const height = box.get_height();
        this._fill.allocate(new Clutter.ActorBox({
            x1: 0,
            y1: 0,
            x2: Math.round(box.get_width() * this._fraction),
            y2: height,
        }));
    }
});

/** A section heading with a hairline under it. */
export function heading(text) {
    return label(text, 'poketokenbar-heading');
}

/** Text shown in place of a list that has nothing in it yet. */
export function placeholder(text) {
    return label(text, 'poketokenbar-placeholder');
}

/**
 * A settings row with a label on the left and an on/off control on the right.
 *
 * Not PopupSwitchMenuItem: that is a PopupBaseMenuItem and only works inside a
 * PopupMenu via addMenuItem. Adding one to an St container does not lay out —
 * the whole settings tab would have rendered as nothing.
 */
export function toggleRow(text, value, onToggle, words = null) {
    const control = new St.Button({
        // `words` is the catalogue; without one the switch keeps saying "on"
        // and "off" in English next to a translated label.
        label: words ? words(value ? 'on' : 'off') : (value ? 'on' : 'off'),
        style_class: value ? 'poketokenbar-toggle-on' : 'poketokenbar-toggle-off',
        can_focus: true,
        reactive: true,
        track_hover: true,
    });
    control.connect('clicked', () => onToggle(!value));
    // The label wraps: several settings need a sentence, and a fixed-width
    // popup cuts a one-line label off rather than making the popup wider.
    return row([paragraph(text, 'poketokenbar-key'), control]);
}

/**
 * A flat button that looks like a row rather than a dialog button.
 *
 * `onClick` is wired here rather than by the caller so that every button in the
 * popup is reactive and track-hover in the same way — a button that is only
 * sometimes reactive reads as broken.
 */
export function button(text, onClick, styleClass = 'poketokenbar-button') {
    const widget = new St.Button({
        label: text,
        style_class: styleClass,
        can_focus: true,
        reactive: true,
        track_hover: true,
        x_expand: false,
    });
    widget.connect('clicked', () => onClick());
    return widget;
}

/** Compact "12,345" style text for a token count the daemon did not preformat. */
export function grouped(value) {
    // The daemon preformats everything it ships, so this is only for numbers
    // computed here. JS toLocaleString on a large float renders 8.55336e+07 in
    // some locales, hence the explicit grouping.
    const n = Math.round(value || 0);
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}


/**
 * "resets in 2h 15m" from an ISO-8601 instant.
 *
 * `resets_at` arrives as the raw timestamp the API returned. Rendering it
 * verbatim puts `2026-09-03T10:00:00Z` under the meter, which is data rather
 * than an answer to "how long have I got".
 */
export function resetsIn(iso, strings) {
    if (!iso)
        return '';
    const remaining = new Date(iso).getTime() - Date.now();
    if (Number.isNaN(remaining))
        return '';
    if (remaining <= 0)
        return strings('resetting_now');
    const minutes = Math.floor(remaining / 60000);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);
    if (days > 0)
        return `${days}d ${hours % 24}h`;
    if (hours > 0)
        return `${hours}h ${minutes % 60}m`;
    return `${minutes}m`;
}

/** "just now" / "3 min ago" for the footer's freshness line.
 *
 * `strings` is the catalogue, as in `resetsIn`: the footer is the one line that
 * is on screen every second the popup is open, and it was the last one still
 * in English.
 */
export function ago(seconds, strings) {
    if (seconds === null || seconds === undefined)
        return '';
    const t = strings ?? (key => key);
    if (seconds < 90)
        return t('just_now');
    return t('minutes_ago').replace('%1', String(Math.round(seconds / 60)));
}

/** A small pill, for badges like RAISING or a provider incident. */
export function badge(text, styleClass = 'poketokenbar-badge') {
    return label(text, styleClass);
}

/**
 * Dim and disable a button whose command has been queued.
 *
 * The section rebuilds itself from the daemon's answer, so this lasts only
 * until then — but that window is the one where a click has no visible
 * effect, which reads as the click having been lost, and a second press in
 * it queues the command twice. `sent` is what Commands.enqueue returned: a
 * false means the file never landed, and the button must stay live.
 */
export function markSent(widget, sent) {
    if (!sent)
        return;
    widget.reactive = false;
    widget.can_focus = false;
    widget.opacity = 120;
}
