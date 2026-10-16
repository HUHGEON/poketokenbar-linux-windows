/* widgets.js — the small pieces every popup section builds out of.
 *
 * Kept together so the popup reads as layout rather than as St boilerplate, and
 * so a spacing or colour decision lands in one place instead of five.
 */

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';
import St from 'gi://St';

import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import {typeColor} from './types.js';

/** Utilisation bands, matching limits.level() in the daemon. */
/**
 * The colour a pace tier is drawn in, slowest to fastest.
 *
 * One map for the bar, the percentage and the panel, so a number and the bar
 * under it can never disagree about what a colour means.
 */
export const TIER_TINT = {
    way_under: 'blue',
    under: 'teal',
    on_pace: 'green',
    slightly_over: 'yellow',
    over: 'orange',
    way_over: 'red',
};

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
        // Where an even burn would have reached by now. Hidden unless set: a
        // window whose length is unknown has no line to draw.
        this._pace = new St.Widget({style_class: 'poketokenbar-meter-pace', visible: false});
        this.add_child(this._pace);
        this._fraction = 0;
        this._paceFraction = null;
    }

    /**
     * `fraction` is 0..1; anything past 1 is clamped so a full bar stays full.
     * `tint` names a fixed colour (orange, blue) for bars that are not a
     * utilisation, like growth or a stat; without one the level colours it.
     */
    setFraction(fraction, level = 'ok', tint = null) {
        this._fraction = Math.max(0, Math.min(1, fraction || 0));
        this._fill.style_class = tint
            ? `poketokenbar-meter-fill poketokenbar-fill-${tint}`
            : `poketokenbar-meter-fill ${levelClass(level)}`;
        this.queue_relayout();
    }

    /**
     * The pace mark: the fraction of the window already elapsed, or null for
     * none. Fill past the mark means this window will run out before it resets.
     */
    setPace(fraction) {
        this._paceFraction = typeof fraction === 'number' && fraction >= 0 && fraction <= 1
            ? fraction : null;
        this._pace.visible = this._paceFraction !== null;
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
        if (this._paceFraction === null)
            return;
        // A hairline that overhangs the track top and bottom, so it reads as a
        // mark on the bar rather than a gap in the fill.
        const x = Math.round(box.get_width() * this._paceFraction);
        this._pace.allocate(new Clutter.ActorBox({
            x1: Math.max(0, Math.min(box.get_width() - 1, x)),
            y1: -2,
            x2: Math.max(1, Math.min(box.get_width(), x + 1)),
            y2: height + 2,
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

// Number formatting lives in format.js so it can be run under node: this
// module imports gi:// and a test cannot load it.
export {compact, grouped} from './format.js';

/**
 * "resets in 2h 15m" from an ISO-8601 instant.
 *
 * `resets_at` arrives as the raw timestamp the API returned. Rendering it
 * verbatim puts `2026-09-03T10:00:00Z` under the meter, which is data rather
 * than an answer to "how long have I got".
 */
export function resetsIn(iso, strings) {
    const remaining = remainingSeconds(iso);
    if (remaining === null)
        return '';
    if (remaining <= 0)
        return strings('resetting_now');
    return duration(remaining, strings);
}

/** Seconds until an ISO-8601 instant, or null if it is not one. */
export function remainingSeconds(iso) {
    if (!iso)
        return null;
    const remaining = new Date(iso).getTime() - Date.now();
    return Number.isNaN(remaining) ? null : remaining / 1000;
}

/** A coarse "two units" countdown, the way the popover writes one.
 *
 * Two units at most and never a smaller beside a larger: "6일 2시간",
 * "2시간 36분", "26초". Through the catalogue, because it used to build
 * "6d 2h" out of English letters — so a Korean install counted down in
 * English under a Korean label.
 */
export function duration(seconds, strings) {
    const total = Math.max(0, Math.floor(seconds));
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    const minutes = Math.floor((total % 3600) / 60);
    const secs = total % 60;
    const unit = (key, value) => strings(key).replace('%1', String(value));
    if (days)
        return hours ? `${unit('unit_day', days)} ${unit('unit_hour', hours)}` : unit('unit_day', days);
    if (hours)
        return minutes ? `${unit('unit_hour', hours)} ${unit('unit_minute', minutes)}` : unit('unit_hour', hours);
    if (minutes)
        return secs ? `${unit('unit_minute', minutes)} ${unit('unit_second', secs)}` : unit('unit_minute', minutes);
    return unit('unit_second', secs);
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

// MARK: the upstream-style pieces
//
// The macOS popover this ports is built from a handful of shapes: a segmented
// control, rounded cards, capsule badges, bordered buttons and thin bars. These
// are those shapes, so the sections read as the same layout.

/** Soaks up the free space in a row. */
export function spacer() {
    return new St.Widget({x_expand: true});
}

/** A rounded surface grouping one thing: a shop item, a catch, a detail block. */
export function card(children, extraClass = '') {
    const box = column(children, `poketokenbar-card ${extraClass}`.trim());
    box.x_expand = true;
    return box;
}

/** A hairline between blocks, as upstream's Divider. */
export function divider() {
    return new St.Widget({style_class: 'poketokenbar-divider', x_expand: true});
}

/** Rarity to capsule colour, as upstream's rarityColor. */
export const RARITY_TINT = {
    common: 'gray',
    uncommon: 'green',
    rare: 'blue',
    legendary: 'orange',
};

/** A capsule badge in one of the fixed tints. */
export function pill(text, tint = 'gray') {
    return label(text, `poketokenbar-pill poketokenbar-pill-${tint}`);
}

/**
 * A type badge in that type's colour, or the plain pill for a type this does
 * not know — a new generation's type should still show its name.
 */
export function typeBadge(text, apiName) {
    const color = typeColor(apiName);
    if (!color)
        return pill(text, 'soft-blue');
    const badge = label(text, 'poketokenbar-pill poketokenbar-typebadge');
    // White on a light type needs the shadow to stay legible, as upstream's.
    badge.style = `background-color: ${color};`;
    return badge;
}

/** A small caption, upstream's .caption with a secondary or tertiary colour. */
export function caption(text, tone = 'secondary') {
    return label(text, `poketokenbar-caption poketokenbar-${tone}`);
}

/** A name above a value, as upstream's detail page lays out level and gender. */
export function valuePair(name, value) {
    return column([
        label(name, 'poketokenbar-pair-name'),
        label(value, 'poketokenbar-pair-value'),
    ], 'poketokenbar-pair');
}

/**
 * A segmented control: one button per option, the chosen one raised.
 *
 * `accent` fills the chosen segment with the accent colour, as upstream's
 * Pokédex / Catch log switch does; the main tab bar uses the neutral look.
 */
export function segmented(options, current, onSelect, {accent = false, expand = true} = {}) {
    const box = row([], accent ? 'poketokenbar-segmented poketokenbar-segmented-accent'
        : 'poketokenbar-segmented');
    box.x_expand = expand;
    if (!expand)
        box.x_align = Clutter.ActorAlign.START;
    for (const option of options) {
        const selected = option.value === current;
        const widget = button(option.label, () => {
            if (!selected)
                onSelect(option.value);
        }, selected ? 'poketokenbar-segment poketokenbar-segment-selected'
            : 'poketokenbar-segment');
        widget.x_expand = expand;
        box.add_child(widget);
    }
    return box;
}

/** A borderless symbolic icon button, for the footer's refresh and settings. */
export function iconButton(iconName, onClick) {
    const widget = new St.Button({
        style_class: 'poketokenbar-iconbutton',
        can_focus: true,
        reactive: true,
        track_hover: true,
        child: new St.Icon({icon_name: iconName, style_class: 'poketokenbar-icon'}),
    });
    widget.connect('clicked', () => onClick());
    return widget;
}

/** Upstream's .bordered button; `prominent` is .borderedProminent. */
export function borderedButton(text, onClick, prominent = false) {
    return button(text, onClick,
        prominent ? 'poketokenbar-button-prominent' : 'poketokenbar-button-bordered');
}

/** An on/off switch drawn the way the Shell's own menus draw one. */
export function switchButton(value, onToggle) {
    const widget = new St.Button({
        style_class: 'poketokenbar-switch',
        can_focus: true,
        reactive: true,
        track_hover: true,
        y_align: Clutter.ActorAlign.CENTER,
        child: new PopupMenu.Switch(Boolean(value)),
    });
    widget.connect('clicked', () => onToggle(!value));
    return widget;
}

/** A single-line label that ends in "…" instead of widening its row. */
export function ellipsized(text, styleClass = '') {
    const widget = label(text, styleClass);
    widget.clutter_text.ellipsize = Pango.EllipsizeMode.END;
    return widget;
}

