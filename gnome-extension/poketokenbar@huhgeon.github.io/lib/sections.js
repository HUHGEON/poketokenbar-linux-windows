/* sections.js — the popup's pages.
 *
 * Laid out after the macOS popover (PopoverView, CompanionView, ShopView,
 * BagView, SettingsView): the same blocks in the same order, with the same
 * words, so the two apps read as one.
 *
 * Each section owns a box and a single `update(state)`. Rebuilding a section's
 * children on every poll is the simplest correct thing and cheap at these
 * sizes, with one exception: sprites are handed a path and decide for
 * themselves whether anything changed, because re-decoding ~55 GIF frames every
 * two seconds is not free.
 */

import Clutter from 'gi://Clutter';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Commands from './commands.js';
import {planCandyUse, maxCandyUses} from './candy.js';
import {DEX_SORTS, LOG_SORTS, dexRows, logRows, sortLabelKey} from './dexfilter.js';
import * as Config from './config.js';
import {ANIMATION_OFF, DEFAULT_QUALITY, effectiveQuality} from './framecap.js';
import {isPowerSaver} from './power.js';
import {LANGUAGES, LANGUAGE_NAMES} from './languages.js';
import {resetClock} from './resetclock.js';
import {Sprite} from './sprite.js';
import {
    Meter, RARITY_TINT, TIER_TINT, ago, borderedButton, button, caption, card, column,
    compact, divider, ellipsized, grouped, label, levelClass, markSent, paragraph, pill,
    placeholder, resetsIn, row, segmented, spacer, switchButton, valuePair, verticalBox,
} from './widgets.js';

// The Pokédex grid, as upstream's: four across and six down per page.
const DEX_COLUMNS = 4;
const DEX_ROWS = 6;
const DEX_SPRITE_SIZE = 44;
// Catch log cards per page. Every card carries a sprite per stage, so a page
// bounds how many are decoded at once; the log itself is never cut short.
const LOG_PER_PAGE = 20;
const DETAIL_SPRITE_SIZE = 82;
const COMPANION_SPRITE_SIZE = 72;
// The trend's tallest bar and an empty day's baseline, in pixels. A day with
// no usage keeps a sliver, or its column would read as a missing date.
const TREND_TRACK = 26;
const TREND_BASELINE = 2;
const RARITY_ORDER = ['legendary', 'rare', 'uncommon', 'common'];
// How big an item's picture is drawn in the shop and the bag.
const ITEM_ICON_SIZE = 32;

/** Base: a vertical box that empties itself before each update. */
const Section = GObject.registerClass(
class Section extends St.BoxLayout {
    _init(styleClass = 'poketokenbar-section') {
        super._init({style_class: styleClass, x_expand: true});
        // `vertical` is deprecated from 48 and `orientation` is not documented
        // as present in 45.
        if ('orientation' in this)
            this.orientation = Clutter.Orientation.VERTICAL;
        else
            this.vertical = true;
    }

    clear() {
        this.destroy_all_children();
    }

    /** The popup closed, or another page took over: nothing here is on screen.
     *
     * Dropping the children is what actually stops the animating sprites among
     * them — every Sprite kills its own timer on destroy — and it frees the
     * textures they uploaded.
     */
    release() {
        this.clear();
    }
});

/** The picture for one shop or bag row: its sprite, or its emoji without one.
 *
 * `zoom` is for the egg: PokéAPI's egg is a small egg in the middle of a 96px
 * canvas, so at item size it was a speck. It is drawn larger and cut to the
 * item box instead, which is how upstream's egg icon reads.
 */
function itemIcon(spritePath, emoji, zoom = false) {
    if (spritePath && zoom) {
        // A still PNG: its middle, drawn as a background larger than the box.
        const zoomed = ITEM_ICON_SIZE * 2.6;
        return new St.Widget({
            width: ITEM_ICON_SIZE,
            height: ITEM_ICON_SIZE,
            y_align: Clutter.ActorAlign.START,
            style: 'background-image: url("file://' + spritePath + '"); ' +
                'background-size: ' + zoomed + 'px ' + zoomed + 'px; background-position: center;',
        });
    }
    if (spritePath) {
        const sprite = new Sprite({size: ITEM_ICON_SIZE});
        sprite.setPath(spritePath);
        if (sprite.visible)
            return sprite;
        sprite.destroy();
    }
    return label(emoji || '', 'poketokenbar-item-emoji');
}

// MARK: Home

export const HomeSection = GObject.registerClass(
class HomeSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
        // Which provider the per-provider row shows; upstream keeps the pick
        // while the popup is open.
        this._providerId = null;
        // Held across updates so its decoded frames survive a rebuild.
        this._sprite = new Sprite({size: COMPANION_SPRITE_SIZE});
        this._spriteHolder = new St.Bin({
            style_class: 'poketokenbar-companion-sprite',
            x_align: Clutter.ActorAlign.START,
            y_align: Clutter.ActorAlign.START,
        });
        this._spriteHolder.set_child(this._sprite);
        this.connect('destroy', () => {
            if (!this._spriteHolder.get_parent())
                this._spriteHolder.destroy();
        });
    }

    /** Take the companion sprite out of the tree before the rest is destroyed,
     * so the holder this object keeps is never disposed with its parent row. */
    clear() {
        this._spriteHolder.get_parent()?.remove_child(this._spriteHolder);
        super.clear();
    }

    release() {
        super.release();
        this._sprite.setPaused(true);
    }

    update(state) {
        this.clear();
        const t = key => this._reader.text(key);
        const companion = state?.companion;
        this._sprite.setPaused(!companion);
        this._sprite.setQuality(effectiveQuality(
            state?.config?.animation_quality ?? DEFAULT_QUALITY, isPowerSaver()));

        // The daemon holds a celebration for exactly one poll.
        const banner = state?.celebration;
        if (banner?.kind) {
            const lines = [label(banner.title ?? '', 'poketokenbar-strong')];
            if (banner.detail)
                lines.push(paragraph(banner.detail, 'poketokenbar-caption poketokenbar-secondary'));
            this.add_child(card(lines, 'poketokenbar-banner'));
        }

        if (companion)
            this._addCompanion(companion, t);
        this._addPinRow(companion, t);

        this.add_child(divider());
        this._addToday(state, t);
        this.add_child(divider());
        this._addProviderStatus(state);
        if (this._addLimits(state, t))
            this.add_child(divider());
    }

    // --- companion header (upstream CompanionHeader) ----------------------

    _addCompanion(companion, t) {
        // Home always shows what is being raised, never the pinned species.
        this._sprite.setPath(companion.sprite_path || null);
        const lines = column([], 'poketokenbar-companion-lines');
        lines.x_expand = true;

        if (companion.stage === 'egg') {
            lines.add_child(label(t('egg'), 'poketokenbar-name'));
            const status = row([caption(
                companion.egg_imminent ? t('egg_imminent') : t('egg_incubating'),
                companion.egg_imminent ? 'orange' : 'secondary')]);
            if (companion.egg_tier) {
                status.add_child(pill(t('egg_guarantee').replace('%1', t(companion.egg_tier)),
                    RARITY_TINT[companion.egg_tier] ?? 'gray'));
            }
            lines.add_child(status);
            const meter = new Meter();
            meter.setFraction(companion.egg_progress ?? 0, 'ok', 'orange');
            lines.add_child(meter);
            lines.add_child(caption(
                t('egg_to_hatch').replace('%1', companion.egg_remaining_text ?? ''), 'tertiary'));
        } else {
            const nameRow = row([label(companion.name || `#${companion.species_id}`,
                'poketokenbar-name')]);
            if (companion.is_shiny)
                nameRow.add_child(label('✨', 'poketokenbar-caption'));
            nameRow.add_child(pill(t(companion.rarity ?? 'common').toUpperCase(),
                RARITY_TINT[companion.rarity] ?? 'gray'));
            if (companion.level)
                nameRow.add_child(caption(`Lv. ${companion.level}`, 'tertiary'));
            lines.add_child(nameRow);

            const stage = companion.is_final_form
                ? t('final_form')
                : t('stage_of').replace('%1', String((companion.stage_index ?? 0) + 1))
                    .replace('%2', String(companion.total_forms ?? 1));
            const stageRow = row([caption(
                companion.nature ? `${stage} · ${companion.nature}` : stage, 'secondary')]);
            // A repeat hatch grows faster; said beside the stage, or the bar
            // filling twice as fast looks like a counting bug.
            if (companion.growth_multiplier) {
                stageRow.add_child(pill(
                    t('growth_boost').replace('%1', String(companion.growth_multiplier)),
                    'soft-orange'));
            }
            lines.add_child(stageRow);

            const meter = new Meter();
            meter.setFraction(companion.stage_progress ?? 0, 'ok', 'orange');
            lines.add_child(meter);
            lines.add_child(caption(
                t(companion.is_final_form ? 'to_graduation' : 'to_next_evolution')
                    .replace('%1', companion.remaining_text ?? ''),
                'tertiary'));
        }
        lines.add_child(caption(companion.status_message ?? '', 'secondary'));
        this.add_child(row([this._spriteHolder, lines], 'poketokenbar-companion'));

        if (companion.stage !== 'egg')
            this.add_child(this._evolutionLine(companion));
    }

    _evolutionLine(companion) {
        const line = row([], 'poketokenbar-evoline');
        for (const evoStage of companion.evo_line ?? []) {
            const sprite = new Sprite({size: 30});
            sprite.setPath(evoStage.sprite_path || null);
            // Forms not reached yet are dimmed rather than hidden, so the line
            // still shows where the companion is heading.
            sprite.opacity = evoStage.reached ? 255 : 80;
            const dot = new St.Widget({
                style_class: 'poketokenbar-evodot',
                x_align: Clutter.ActorAlign.CENTER,
            });
            dot.opacity = evoStage.current ? 255 : 0;
            line.add_child(column([sprite, dot], 'poketokenbar-evostage'));
        }
        return line;
    }

    /** Which species is holding the panel, and the button that releases it. */
    _addPinRow(companion, t) {
        const pinned = companion?.representative_species_id;
        if (!pinned)
            return;
        const name = companion.panel_name || `#${pinned}`;
        const unpin = button(t('unpin'), () => markSent(unpin, Commands.represent(null)),
            'poketokenbar-link');
        this.add_child(row([
            caption(`\u{1F4CC} ${t('pinned_to_panel')}: ${name}`, 'secondary'),
            spacer(),
            unpin,
        ], 'poketokenbar-pinrow'));
    }

    // --- today (upstream PopoverView.header) ---------------------------------

    _addToday(state, t) {
        const today = state?.today;
        this.add_child(caption(t('todays_tokens'), 'secondary'));
        const total = row([
            label(today?.tokens_compact ?? '0', 'poketokenbar-big'),
            caption(today?.tokens_grouped ?? '0', 'secondary'),
            spacer(),
        ]);
        total.get_children()[1].y_align = Clutter.ActorAlign.END;
        if (today?.cost_text)
            total.add_child(label(today.cost_text, 'poketokenbar-callout poketokenbar-secondary'));
        this.add_child(total);

        const periods = state?.periods;
        if (periods?.week || periods?.month) {
            const line = row([]);
            if (periods.week)
                line.add_child(this._period(t('this_week'), periods.week));
            if (periods.month)
                line.add_child(this._period(t('this_month'), periods.month));
            this.add_child(line);
        }
        this._addMonthTrend(state?.month_trend, t);
        this._addProviders(state, t);
    }

    _period(name, periodRow) {
        const parts = [
            caption(name, 'tertiary'),
            label(periodRow.tokens_compact ?? '', 'poketokenbar-caption poketokenbar-strong'),
        ];
        if (periodRow.cost_text)
            parts.push(caption(periodRow.cost_text, 'secondary'));
        const box = row(parts);
        box.style = 'padding-right: 12px;';
        return box;
    }

    /**
     * This month by day (upstream 0912c68): a bar per day from the 1st to
     * today, today in the accent colour, weekends underlined, and a readout
     * that follows the pointer and returns to today when it leaves.
     */
    _addMonthTrend(monthTrend, t) {
        const days = monthTrend?.days ?? [];
        if (days.length === 0)
            return;
        const todayRow = days.find(trendDay => trendDay.is_today) ?? days[days.length - 1];
        const readout = label(todayRow.readout, 'poketokenbar-caption poketokenbar-secondary');
        this.add_child(row([
            caption(t('daily_trend'), 'tertiary'),
            readout,
            spacer(),
            caption(t('peak_day'), 'tertiary'),
            label(monthTrend.peak_text ?? '', 'poketokenbar-caption2 poketokenbar-strong'),
        ]));

        const bars = new St.BoxLayout({style_class: 'poketokenbar-trend', x_expand: true});
        const ticks = new St.BoxLayout({style_class: 'poketokenbar-trend-ticks', x_expand: true});
        const axis = new St.BoxLayout({style_class: 'poketokenbar-trend-axis', x_expand: true});
        for (const trendDay of days) {
            // A column the full track height, so a low bar is as easy to point
            // at as a tall one; the bar itself sits at its bottom.
            // A column the full track height with the bar at its foot. The
            // space above the bar is what expands: an St.Bin ignored the bar's
            // own END alignment and centred it, so the bars floated mid-track
            // instead of rising from a shared baseline.
            const barColumn = verticalBox({
                x_expand: true, reactive: true, track_hover: true, height: TREND_TRACK,
            });
            const classes = ['poketokenbar-trend-bar'];
            if (trendDay.is_today)
                classes.push('poketokenbar-trend-today');
            else if (trendDay.is_empty)
                classes.push('poketokenbar-trend-empty');
            barColumn.add_child(new St.Widget({y_expand: true}));
            barColumn.add_child(new St.Widget({
                style_class: classes.join(' '),
                x_expand: true,
                height: Math.max(TREND_BASELINE, Math.round(trendDay.fraction * TREND_TRACK)),
            }));
            barColumn.connect('notify::hover', () => {
                readout.text = barColumn.hover ? trendDay.readout : todayRow.readout;
            });
            bars.add_child(barColumn);
            ticks.add_child(new St.Widget({
                style_class: trendDay.is_weekend ? 'poketokenbar-trend-weekend' : '',
                x_expand: true, height: 2,
            }));
            axis.add_child(new St.Label({
                text: trendDay.axis_label,
                x_expand: true,
                style_class: trendDay.is_today
                    ? 'poketokenbar-trend-label-today' : 'poketokenbar-trend-label',
            }));
        }
        this.add_child(bars);
        this.add_child(ticks);
        this.add_child(axis);
    }

    /** Provider pills when more than one tool was used, then the chosen one's row. */
    _addProviders(state, t) {
        const providers = state?.providers ?? {};
        const ids = Object.keys(providers);
        if (ids.length === 0)
            return;
        if (!ids.includes(this._providerId))
            this._providerId = ids.includes('claude_code') ? 'claude_code' : ids[0];

        if (ids.length > 1) {
            const pills = row([]);
            for (const id of ids) {
                const selected = id === this._providerId;
                pills.add_child(button(providers[id].display_name ?? id, () => {
                    this._providerId = id;
                    this.update(this._reader.state);
                }, selected ? 'poketokenbar-providerpill poketokenbar-providerpill-selected'
                    : 'poketokenbar-providerpill'));
            }
            pills.style = 'padding-top: 6px;';
            this.add_child(pills);
        }

        const usageRow = providers[this._providerId];
        const head = row([
            label(usageRow.display_name ?? this._providerId, 'poketokenbar-callout-bold'),
            spacer(),
            label(usageRow.total_tokens_compact ?? '', 'poketokenbar-callout'),
        ]);
        if (usageRow.cost_text)
            head.add_child(caption(usageRow.cost_text, 'secondary'));
        this.add_child(head);
        this.add_child(row([
            this._tokenType('in', usageRow.input_compact),
            this._tokenType('out', usageRow.output_compact),
            this._tokenType('cache w', usageRow.cache_write_compact),
            this._tokenType('cache r', usageRow.cache_read_compact),
        ]));

        // Only worth the rows when the day spanned several models.
        const models = usageRow.models ?? [];
        if (models.length > 1) {
            for (const modelRow of models.slice(0, 6)) {
                const name = String(modelRow.model).split('/').pop();
                this.add_child(row([
                    ellipsized(name, 'poketokenbar-caption2 poketokenbar-secondary'),
                    spacer(),
                    label(modelRow.total_tokens_compact ?? '',
                        'poketokenbar-caption2 poketokenbar-tertiary'),
                ]));
            }
        }
    }

    _tokenType(name, value) {
        const box = row([
            label(name, 'poketokenbar-caption2 poketokenbar-tertiary'),
            label(value ?? '0', 'poketokenbar-caption2 poketokenbar-secondary'),
        ]);
        box.style = 'spacing: 3px; padding-right: 8px;';
        return box;
    }

    _addProviderStatus(state) {
        // Every row here is already a problem: the daemon drops healthy ones.
        const statuses = state?.provider_status ?? {};
        for (const id of Object.keys(statuses)) {
            const providerStatus = statuses[id];
            if (!providerStatus)
                continue;
            const dot = new St.Widget({
                style_class: `poketokenbar-dot poketokenbar-dot-${
                    providerStatus.severity === 'crit' ? 'red' : 'orange'}`,
                y_align: Clutter.ActorAlign.CENTER,
            });
            this.add_child(row([
                dot,
                label(providerStatus.label ?? '',
                    `poketokenbar-caption poketokenbar-strong ${levelClass(providerStatus.severity)}`),
                caption(id, 'secondary'),
            ]));
        }
    }

    // --- official limits (upstream limitsSection) ----------------------------

    _addLimits(state, t) {
        const limits = state?.limits;
        if (!limits || (!limits.session && !limits.weekly))
            return false;

        this.add_child(label(t('limits_official').toUpperCase(), 'poketokenbar-section-caption'));

        // The numbers are the last good ones and fetching again is failing.
        if (limits.stale) {
            const age = limits.updated_at ? Date.now() / 1000 - limits.updated_at : null;
            const refresh = borderedButton(t('refresh'), () => markSent(refresh, Commands.refresh()));
            this.add_child(row([
                caption(age === null ? t('stale_limits') : `${t('stale_limits')} · ${ago(age, t)}`,
                    'orange'),
                spacer(),
                refresh,
            ]));
        }
        if (limits.plan)
            this.add_child(caption(t('plan_label').replace('%1', String(limits.plan).toUpperCase()), 'tertiary'));
        const account = limits.account ?? {};
        const who = account.email || account.name;
        if (who)
            this.add_child(caption(t('account_label').replace('%1', who), 'tertiary'));

        const mode = state?.config?.limit_value_mode;
        for (const [key, name] of [['session', 'five_hour_session'], ['weekly', 'weekly']]) {
            const limitWindow = limits[key];
            if (!limitWindow)
                continue;
            const used = limitWindow.utilization ?? 0;
            const shown = mode === 'remaining' ? Math.max(0, 100 - used) : used;
            const percent = `${Math.round(shown)}%`;
            const head = row([label(t(name), 'poketokenbar-callout'), spacer()]);
            const resets = resetsIn(limitWindow.resets_at, t);
            if (resets) {
                head.add_child(caption(`${resets}${resetClock(limitWindow.resets_at, t)}`,
                    'tertiary'));
            }
            // Coloured by pace, not by the absolute number: 71% is fast half an
            // hour into a five-hour window and slow with ten minutes left
            // (upstream 68deb09). Yellow text is unreadable, so "slightly fast"
            // keeps the ordinary colour and says it in the hint instead.
            const tint = TIER_TINT[limitWindow.tier] ?? null;
            const textTint = limitWindow.tier === 'slightly_over' ? null : tint;
            head.add_child(label(mode === 'remaining' ? t('percent_left').replace('%1', percent) : percent,
                `poketokenbar-callout ${textTint ? `poketokenbar-text-${textTint}` : levelClass(limitWindow.severity)}`));
            const meter = new Meter();
            meter.setFraction(shown / 100, limitWindow.severity, tint);
            // The mark runs through the same displayed fraction as the fill, so
            // the remaining-percentage mode cannot flip one without the other.
            meter.setPace(mode === 'remaining' && typeof limitWindow.pace === 'number'
                ? 1 - limitWindow.pace : limitWindow.pace);
            this.add_child(column([head, meter]));
            // What the colour means, in words, since a colour alone is not an
            // answer — and the only place the pace percentage is spelled out.
            const pace = [limitWindow.tier_text, limitWindow.pace_delta_text, limitWindow.pace_hint]
                .filter(part => part).join(' · ');
            if (limitWindow.pace_hint)
                this.add_child(caption(pace, 'tertiary'));

            // The forecast belongs to the window it is a forecast for.
            const burnRow = state?.burn?.[key];
            if (burnRow?.eta_text)
                this.add_child(caption(`⚠ ${t('at_this_rate').replace('%1', burnRow.eta_text)}`, 'orange'));
        }
        return true;
    }
});

// MARK: Shop and Bag (upstream ShopView, BagView)

export const ShopSection = GObject.registerClass(
class ShopSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
        // The item whose Buy is waiting on a second tap, as upstream's
        // two-step confirm. An egg throws the companion away.
        this._confirming = null;
        // The egg whose Buy has passed the first confirm and is now asking
        // again, because the companion it would discard is shiny or legendary.
        this._preciousConfirming = null;
        // How many of each item the stepper is set to. Kept here rather than in
        // the daemon: it is a pending choice, not saved state, and it must
        // answer the tap without waiting for a poll.
        this._quantity = new Map();
    }

    release() {
        this._confirming = null;
        this._preciousConfirming = null;
        this._quantity.clear();
        super.release();
    }

    /** The chosen quantity, clamped to what the wallet can pay for now. */
    _quantityFor(shopItem) {
        const limit = Math.max(1, Math.trunc(shopItem.max_buy ?? 1));
        return Math.min(Math.max(1, this._quantity.get(shopItem.key) ?? 1), limit);
    }

    update(state) {
        this.clear();
        const t = key => this._reader.text(key);
        // Whether an egg would throw away something hard to replace. Judged
        // from the companion the popup is already showing, so a disguised Ditto
        // keeps its secret (upstream b4ff5de).
        const companion = state?.companion ?? {};
        this._precious = Boolean(companion.is_shiny) || companion.rarity === 'legendary';
        this._companionIsShiny = Boolean(companion.is_shiny);
        this._companionIsLegendary = companion.rarity === 'legendary';

        this.add_child(card([
            caption(t('spendable_tokens'), 'secondary'),
            label(state?.companion?.spendable_text ?? '0', 'poketokenbar-big'),
            caption(t('spend_hint'), 'tertiary'),
        ]));

        for (const shopItem of state?.shop ?? []) {
            const nameRow = row([label(shopItem.label || shopItem.key, 'poketokenbar-callout-bold')]);
            if (shopItem.owned_count > 0 && !shopItem.owned) {
                nameRow.add_child(label(t('owned_count').replace('%1', String(shopItem.owned_count)),
                    'poketokenbar-caption2 poketokenbar-strong poketokenbar-secondary'));
            }
            // A guaranteed egg says its floor as a rarity capsule, as upstream's.
            const tier = String(shopItem.key).split(':')[1];
            if (shopItem.kind === 'egg' && tier)
                nameRow.add_child(pill(t(tier), RARITY_TINT[tier] ?? 'gray'));
            const text = column([
                nameRow,
                paragraph(shopItem.description ?? '', 'poketokenbar-caption poketokenbar-secondary'),
            ]);
            text.x_expand = true;
            const top = row([itemIcon(shopItem.sprite_path, shopItem.emoji, shopItem.kind === 'egg'), text]);
            top.style = 'spacing: 10px;';

            // What a release keeps, right where the reader has just been told
            // what they give up (upstream c951492).
            if (shopItem.release_note)
                text.add_child(paragraph(shopItem.release_note, 'poketokenbar-caption2 poketokenbar-tertiary'));
            const parts = [top, this._controls(shopItem, t)];
            // An egg during the egg stage: the reason the button is off.
            if (shopItem.locked)
                parts.push(paragraph(t('egg_shop_locked_hint'), 'poketokenbar-caption2 poketokenbar-tertiary'));
            this.add_child(card(parts));
        }
    }

    _controls(shopItem, t) {
        if (shopItem.owned) {
            return row([label(`✓ ${t('owned_already')}`,
                'poketokenbar-caption poketokenbar-strong poketokenbar-green')]);
        }
        const count = this._quantityFor(shopItem);
        const times = n => t('times_count').replace('%1', String(n));
        // A shiny or legendary companion is worth one more question. A rare one
        // is not: they are common enough that the extra tap is just fatigue.
        if (this._preciousConfirming === shopItem.key) {
            const send = borderedButton(
                this._companionIsShiny && !this._companionIsLegendary
                    ? t('fresh_egg_discard_shiny')
                    : t('fresh_egg_discard_valuable'),
                () => {
                    this._preciousConfirming = null;
                    markSent(send, Commands.buy(shopItem.key));
                });
            return column([
                paragraph(this._companionIsLegendary
                    ? t('fresh_egg_legendary_warning')
                    : t('fresh_egg_shiny_warning'), 'poketokenbar-caption poketokenbar-orange'),
                row([
                    spacer(),
                    send,
                    button(t('cancel'), () => {
                        this._preciousConfirming = null;
                        this.update(this._reader.state);
                    }),
                ]),
            ]);
        }
        if (this._confirming === shopItem.key) {
            const name = shopItem.label || shopItem.key;
            const buy = borderedButton(count > 1 ? `${t('buy')} ${times(count)}` : t('buy'), () => {
                this._confirming = null;
                if (shopItem.kind === 'egg' && this._precious) {
                    this._preciousConfirming = shopItem.key;
                    this.update(this._reader.state);
                    return;
                }
                markSent(buy, Commands.buy(shopItem.key, count));
            }, true);
            return row([
                caption(t('buy_confirm').replace(
                    '%1', count > 1 ? `${name} ${times(count)}` : name), 'secondary'),
                spacer(),
                buy,
                button(t('cancel'), () => {
                    this._confirming = null;
                    this.update(this._reader.state);
                }),
            ]);
        }
        // One item's price, or the running total once the stepper has moved:
        // a bulk purchase is only safe if the bill is on screen before the tap.
        const priceText = count > 1
            ? compact(shopItem.price * count)
            : (shopItem.price_text ?? '');
        const controls = row([
            caption(`${t('price')} ${priceText}`, 'tertiary'),
            spacer(),
        ]);
        // Buying several at once is this port's own. Eggs stay single: one
        // replaces the companion, so a stack of them means nothing.
        if (shopItem.affordable && (shopItem.max_buy ?? 0) > 1)
            controls.add_child(this._quantityStepper(shopItem, count, t));
        if (shopItem.affordable) {
            controls.add_child(borderedButton(count > 1 ? `${t('buy')} ${times(count)}` : t('buy'),
                () => {
                    this._confirming = shopItem.key;
                    this.update(this._reader.state);
                }));
        } else if (shopItem.locked) {
            const buy = borderedButton(t('buy'), () => {});
            buy.reactive = false;
            buy.opacity = 110;
            controls.add_child(buy);
        } else {
            controls.add_child(caption(t('not_enough_tokens'), 'tertiary'));
        }
        return controls;
    }

    /** − ×n + max, clamped to what one purchase can cover. */
    _quantityStepper(shopItem, count, t) {
        const limit = Math.max(1, Math.trunc(shopItem.max_buy ?? 1));
        const set = value => {
            this._quantity.set(shopItem.key, Math.max(1, Math.min(limit, value)));
            this.update(this._reader.state);
        };
        const down = button('−', () => set(count - 1));
        const up = button('+', () => set(count + 1));
        down.opacity = count > 1 ? 255 : 110;
        up.opacity = count < limit ? 255 : 110;
        const stepper = row([down, label(String(count), 'poketokenbar-stepvalue'), up],
            'poketokenbar-stepper');
        // Stepping to a hundred one tap at a time is not a purchase flow.
        if (limit > 2)
            stepper.add_child(button(t('quantity_max'), () => set(limit)));
        return stepper;
    }
});

export const BagSection = GObject.registerClass(
class BagSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
        // How many candies the stepper is set to, as in the shop.
        this._candyCount = 1;
    }

    release() {
        this._candyCount = 1;
        super.release();
    }

    update(state) {
        this.clear();
        const t = key => this._reader.text(key);
        const items = state?.bag ?? [];
        if (items.length === 0) {
            this.add_child(placeholder(t('bag_empty')));
            return;
        }
        for (const bagItem of items) {
            const text = column([
                row([
                    label(bagItem.label || bagItem.key, 'poketokenbar-callout-bold'),
                    label(`×${bagItem.count ?? 0}`,
                        'poketokenbar-caption poketokenbar-strong poketokenbar-secondary'),
                ]),
                paragraph(bagItem.description ?? '', 'poketokenbar-caption poketokenbar-secondary'),
            ]);
            text.x_expand = true;
            const top = row([itemIcon(bagItem.sprite_path, bagItem.emoji), text]);
            top.style = 'spacing: 10px;';
            // Several candies at once, with what the batch would do underneath
            // (upstream 2e8efdd). The rest of the bag is one at a time.
            const limit = bagItem.usable ? maxCandyUses(bagItem.candy) : 0;
            const count = Math.min(Math.max(1, this._candyCount), Math.max(1, limit));
            const plan = limit > 0 ? planCandyUse(bagItem.candy, count) : null;
            const effect = plan && bagItem.candy?.effect_template
                ? bagItem.candy.effect_template.replace('%1', compact(plan.xp))
                : (bagItem.effect ?? '');
            const bottom = row([caption(effect, 'tertiary'), spacer()]);
            if (limit > 1)
                bottom.add_child(this._candyStepper(limit, count));
            if (bagItem.usable) {
                const uses = plan?.count ?? 1;
                const use = borderedButton(
                    uses > 1 ? `${t('use')} ${t('times_count').replace('%1', String(uses))}` : t('use'),
                    () => markSent(use, Commands.use(bagItem.key, uses)));
                bottom.add_child(use);
            } else if (bagItem.passive) {
                bottom.add_child(label(`✓ ${t('active')}`,
                    'poketokenbar-caption poketokenbar-strong poketokenbar-green'));
            }
            this.add_child(card([top, bottom, ...this._preview(plan, t)]));
        }
    }

    _candyStepper(limit, count) {
        const set = value => {
            this._candyCount = Math.max(1, Math.min(limit, value));
            this.update(this._reader.state);
        };
        const down = button('−', () => set(count - 1));
        const up = button('+', () => set(count + 1));
        down.opacity = count > 1 ? 255 : 110;
        up.opacity = count < limit ? 255 : 110;
        return row([down, label(String(count), 'poketokenbar-stepvalue'), up],
            'poketokenbar-stepper');
    }

    /** What this batch would do: graduation, discarded XP, or carry-over. */
    _preview(plan, t) {
        if (plan === null)
            return [];
        const lines = [];
        if (plan.graduates)
            lines.push(caption(t('candy_graduates'), 'secondary'));
        if (plan.discardedXP > 0) {
            lines.push(paragraph(t('candy_discarded_xp').replace('%1', compact(plan.discardedXP)),
                'poketokenbar-caption2 poketokenbar-orange'));
        } else if (plan.evolves && !plan.graduates) {
            lines.push(paragraph(t('candy_carryover_xp').replace('%1', compact(plan.carryoverXP)),
                'poketokenbar-caption2 poketokenbar-secondary'));
        }
        return lines;
    }
});

// MARK: Collection (upstream CollectionView)

export const CollectionSection = GObject.registerClass(
class CollectionSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
        this._showingCatchLog = false;
        this._page = 0;
        this._logPage = 0;
        this._perPage = DEX_COLUMNS * DEX_ROWS;
        this._state = null;
        // Rarity chips filter the grid and the log, as upstream's do.
        this._dexFilter = null;
        this._logFilter = null;
        // The search box, the shiny-only toggle and the chosen order. The entry
        // is kept as a widget rather than rebuilt every poll: destroying it
        // under the cursor would throw away what is half typed.
        this._search = null;
        this._query = '';
        this._shinyOnly = false;
        this._dexSort = DEX_SORTS[0];
        this._logSort = LOG_SORTS[0];
        // The species whose page is open, and what the page is showing. Kept
        // here as well as in the daemon so the page opens on the tap.
        this._inspecting = null;
        this._individualIndex = 0;
        this._showingMoves = false;
    }

    /** Closing the popup or leaving the tab closes the page too. */
    release() {
        if (this._inspecting !== null) {
            this._inspecting = null;
            Commands.inspect(null);
        }
        // clear() destroys the entry with everything else, and a search left
        // over from last time would be a filter nobody remembers setting.
        this._search = null;
        this._query = '';
        this._shinyOnly = false;
        super.release();
    }

    update(state) {
        this._state = state;
        // The search entry is detached rather than destroyed: it holds the text
        // being typed, and rebuilding it every poll would throw that away
        // mid-word. Focus goes back to it once it is on screen again.
        const focused = this._searchHasFocus();
        this._detachSearch();
        this.clear();
        const t = key => this._reader.text(key);

        if (this._inspecting !== null) {
            this._buildDetail(state);
            return;
        }
        this.add_child(segmented([
            {label: t('pokedex'), value: false},
            {label: t('catch_log'), value: true},
        ], this._showingCatchLog, value => {
            this._showingCatchLog = value;
            this.update(this._state);
        }, {accent: true, expand: false}));

        if (this._showingCatchLog)
            this._buildCatchLog(state);
        else
            this._buildPokedex(state);
        if (focused)
            this._focusSearch();
    }

    // --- search, filters and order (upstream ae7bd9d) ------------------------

    _searchHasFocus() {
        return this._search !== null
            && global.stage.get_key_focus() === this._search.clutter_text;
    }

    _focusSearch() {
        if (this._search !== null && this._search.get_parent() !== null)
            global.stage.set_key_focus(this._search.clutter_text);
    }

    _detachSearch() {
        const parent = this._search?.get_parent() ?? null;
        if (parent !== null)
            parent.remove_child(this._search);
    }

    /** The search box, the shiny-only toggle and the sort control, as one row. */
    _controls(t, sorts, sort, setSort) {
        if (this._search === null) {
            this._search = new St.Entry({
                style_class: 'poketokenbar-search',
                hint_text: t('dex_search_placeholder'),
                can_focus: true,
                x_expand: true,
            });
            this._search.clutter_text.connect('text-changed', () => {
                this._query = this._search.get_text() ?? '';
                this._page = 0;
                this._logPage = 0;
                this.update(this._state);
            });
        }
        this._search.hint_text = t('dex_search_placeholder');

        const shiny = button(`✨ ${t('filter_shiny_only')}`, () => {
            this._shinyOnly = !this._shinyOnly;
            this._page = 0;
            this._logPage = 0;
            this.update(this._state);
        }, this._shinyOnly
            ? 'poketokenbar-valuepill poketokenbar-valuepill-on'
            : 'poketokenbar-valuepill');
        // One button cycling the orders, as the settings pills do: a menu is a
        // second popup inside a popup.
        const next = sorts[(sorts.indexOf(sort) + 1) % sorts.length];
        const order = button(t(sortLabelKey(sort)), () => {
            setSort(next);
            this._page = 0;
            this._logPage = 0;
            this.update(this._state);
        }, 'poketokenbar-valuepill');

        this.add_child(this._search);
        this.add_child(row([shiny, spacer(), caption(t('sort_title'), 'tertiary'), order],
            'poketokenbar-filters'));
    }

    /** Nothing matched: say so, and offer the way back. */
    _noResults(t) {
        this.add_child(placeholder(t('no_search_results')));
        const reset = borderedButton(t('clear_filters'), () => {
            this._query = '';
            this._shinyOnly = false;
            this._dexFilter = null;
            this._logFilter = null;
            this._page = 0;
            this._logPage = 0;
            if (this._search !== null)
                this._search.set_text('');
            this.update(this._state);
        });
        reset.x_align = Clutter.ActorAlign.CENTER;
        this.add_child(reset);
    }

    _open(speciesId) {
        this._inspecting = speciesId;
        this._individualIndex = 0;
        // Which appearance the page is showing: null follows what was caught
        // first, true or false is a choice made on the page.
        this._appearance = null;
        this._showingMoves = false;
        Commands.inspect(speciesId);
        this.update(this._state);
    }

    _close() {
        this._inspecting = null;
        Commands.inspect(null);
        this.update(this._state);
    }

    /** "Pokédex 28 species" and the rarity chips under it. */
    _header(title, total, counts, filter, onFilter, t) {
        this.add_child(row([
            label(title, 'poketokenbar-callout-bold'),
            label(total, 'poketokenbar-callout poketokenbar-tertiary'),
        ]));
        const chips = row([]);
        chips.style = 'spacing: 5px;';
        for (const key of RARITY_ORDER) {
            const count = counts[key] ?? 0;
            const classes = ['poketokenbar-chip'];
            if (filter === key)
                classes.push('poketokenbar-chip-selected');
            if (count === 0)
                classes.push('poketokenbar-chip-empty');
            const chip = new St.Button({
                style_class: classes.join(' '),
                reactive: count > 0,
                can_focus: count > 0,
                track_hover: true,
                child: row([
                    new St.Widget({
                        style_class: `poketokenbar-dot poketokenbar-dot-${RARITY_TINT[key]}`,
                        y_align: Clutter.ActorAlign.CENTER,
                    }),
                    label(t(key)),
                    label(String(count), 'poketokenbar-strong'),
                ]),
            });
            chip.connect('clicked', () => onFilter(filter === key ? null : key));
            chips.add_child(chip);
        }
        this.add_child(chips);
    }

    _buildPokedex(state) {
        const t = key => this._reader.text(key);
        const entries = state?.dex ?? [];
        if (entries.length === 0) {
            this.add_child(placeholder(t('no_pokemon_yet')));
            return;
        }
        const counts = state?.rarity_counts ?? {};
        this._header(t('pokedex'), t('species_total').replace('%1', String(entries.length)),
            counts, this._dexFilter, key => {
                this._dexFilter = key;
                this._page = 0;
                this.update(this._state);
            }, t);

        this._controls(t, DEX_SORTS, this._dexSort, sort => {
            this._dexSort = sort;
        });
        const shown = dexRows(entries, {
            rarity: this._dexFilter,
            shinyOnly: this._shinyOnly,
            query: this._query,
            sort: this._dexSort,
        });
        if (shown.length === 0) {
            this._noResults(t);
            return;
        }
        const pages = Math.max(1, Math.ceil(shown.length / this._perPage));
        this._page = Math.min(this._page, pages - 1);
        const page = shown.slice(this._page * this._perPage, (this._page + 1) * this._perPage);

        const describe = dexEntry => dexEntry
            ? `#${dexEntry.species_id} ${dexEntry.name || ''} · ${t(dexEntry.rarity ?? 'common')}`
            : '';
        const info = caption(describe(page.find(dexEntry => dexEntry.is_pinned) ?? page[0]), 'secondary');

        let currentRow = null;
        page.forEach((dexEntry, index) => {
            if (index % DEX_COLUMNS === 0) {
                currentRow = row([], 'poketokenbar-dexrow');
                this.add_child(currentRow);
            }
            const cell = this._dexCell(dexEntry, t);
            cell.connect('notify::hover', () => {
                if (cell.hover)
                    info.text = describe(dexEntry);
            });
            currentRow.add_child(cell);
        });

        const footer = row([info, spacer()], 'poketokenbar-pager');
        this._addPager(footer, this._page, pages, page => {
            this._page = page;
        });
        this.add_child(footer);
    }

    /** "‹ 1 / 2 ›" at the end of `footer`, when there is more than one page. */
    _addPager(footer, current, pages, setPage) {
        if (pages <= 1)
            return;
        const go = page => {
            setPage(page);
            this.update(this._state);
        };
        const previous = button('‹', () => go(Math.max(0, current - 1)));
        const next = button('›', () => go(Math.min(pages - 1, current + 1)));
        previous.reactive = current > 0;
        previous.opacity = current > 0 ? 255 : 110;
        next.reactive = current < pages - 1;
        next.opacity = current < pages - 1 ? 255 : 110;
        footer.add_child(previous);
        footer.add_child(label(`${current + 1} / ${pages}`, 'poketokenbar-callout-bold'));
        footer.add_child(next);
    }

    _dexCell(dexEntry, t) {
        const sprite = new Sprite({size: DEX_SPRITE_SIZE});
        sprite.setPath(dexEntry.sprite_path || null);
        const spriteBin = new St.Bin({child: sprite, x_align: Clutter.ActorAlign.CENTER});
        // The number carries the rarity, so rarity still reads in the "all"
        // view where the chips are not filtering (upstream f0ef5ff).
        const tint = RARITY_TINT[dexEntry.rarity] ?? 'gray';
        const top = row([
            label(`#${dexEntry.species_id}`, `poketokenbar-dexnum poketokenbar-dexnum-${tint}`),
            spacer(),
        ]);
        if (dexEntry.is_shiny)
            top.add_child(label('✨', 'poketokenbar-caption2'));
        const parts = [top, spriteBin];
        if (dexEntry.is_raising) {
            const badge = pill(t('raising').toUpperCase(), 'soft-blue');
            badge.x_align = Clutter.ActorAlign.CENTER;
            parts.push(badge);
        }
        const name = ellipsized(dexEntry.name || '', 'poketokenbar-dexname');
        name.x_align = Clutter.ActorAlign.CENTER;
        parts.push(name);

        // Tapping a cell opens its page, which carries the pin.
        const clickable = new St.Button({
            style_class: dexEntry.is_pinned
                ? 'poketokenbar-dexbutton poketokenbar-dexbutton-pinned'
                : 'poketokenbar-dexbutton',
            can_focus: true,
            track_hover: true,
            child: column(parts, 'poketokenbar-dexcell'),
        });
        clickable.connect('clicked', () => this._open(dexEntry.species_id));
        return clickable;
    }

    _buildCatchLog(state) {
        const t = key => this._reader.text(key);
        const log = state?.catch_log ?? [];
        if (log.length === 0) {
            this.add_child(placeholder(t('no_pokemon_yet')));
            return;
        }
        this._header(t('catch_log'), t('catch_total').replace('%1', String(log.length)),
            state?.catch_counts ?? {}, this._logFilter, key => {
                this._logFilter = key;
                this._logPage = 0;
                this.update(this._state);
            }, t);

        this._controls(t, LOG_SORTS, this._logSort, sort => {
            this._logSort = sort;
        });
        const shown = logRows(log, {
            rarity: this._logFilter,
            shinyOnly: this._shinyOnly,
            query: this._query,
            sort: this._logSort,
        });
        if (shown.length === 0) {
            this._noResults(t);
            return;
        }
        // Paged rather than cut off: the log used to stop at the 40 newest,
        // and everything older could not be reached at all.
        const pages = Math.max(1, Math.ceil(shown.length / LOG_PER_PAGE));
        this._logPage = Math.min(this._logPage, pages - 1);
        const page = shown.slice(this._logPage * LOG_PER_PAGE, (this._logPage + 1) * LOG_PER_PAGE);
        for (const catchRecord of page) {
            const head = row([pill(t(catchRecord.rarity ?? 'common').toUpperCase(),
                RARITY_TINT[catchRecord.rarity] ?? 'gray')]);
            if (catchRecord.raising)
                head.add_child(pill(t('raising').toUpperCase(), 'soft-blue'));
            else if (catchRecord.released)
                head.add_child(pill(t('dex_released').toUpperCase(), 'soft-gray'));
            head.add_child(spacer());
            head.add_child(caption(
                catchRecord.is_shiny ? `✨ ${catchRecord.nature ?? ''}` : (catchRecord.nature ?? ''),
                'secondary'));

            const chain = row([], 'poketokenbar-chain');
            (catchRecord.chain ?? []).forEach((chainStage, index) => {
                if (index > 0)
                    chain.add_child(label('→', 'poketokenbar-arrow'));
                const sprite = new Sprite({size: 40});
                sprite.setPath(chainStage.sprite_path || null);
                const name = ellipsized(chainStage.name || `#${chainStage.species_id}`,
                    'poketokenbar-caption2 poketokenbar-secondary');
                name.x_align = Clutter.ActorAlign.CENTER;
                chain.add_child(column([new St.Bin({child: sprite, x_align: Clutter.ActorAlign.CENTER}), name],
                    'poketokenbar-chainstage'));
            });
            const parts = [head, chain];
            if (catchRecord.raised_text)
                parts.push(caption(catchRecord.raised_text, 'tertiary'));
            this.add_child(card(parts));
        }
        const footer = row([spacer()], 'poketokenbar-pager');
        this._addPager(footer, this._logPage, pages, logPage => {
            this._logPage = logPage;
        });
        if (pages > 1)
            this.add_child(footer);
        else
            footer.destroy();
    }

    // MARK: the detail page (upstream PokemonDetailView)

    _buildDetail(state) {
        const t = key => this._reader.text(key);
        const detail = state?.detail ?? {};
        const ready = detail.species_id === this._inspecting;
        const dexRow = (state?.dex ?? []).find(cell => cell.species_id === this._inspecting) ?? {};

        this.add_child(row([
            button(`‹ ${t('detail_back')}`, () => this._close(), 'poketokenbar-link'),
            spacer(),
            caption(`#${this._inspecting}`, 'secondary'),
        ]));

        // Identity: drawn from the grid's own row until the daemon answers.
        const sprite = new Sprite({size: DETAIL_SPRITE_SIZE});
        const spriteBox = new St.Bin({
            style_class: 'poketokenbar-companion-sprite',
            child: sprite,
            y_align: Clutter.ActorAlign.START,
        });
        const rarity = (ready ? detail.rarity : dexRow.rarity) || 'common';
        const individuals = ready ? (detail.individuals ?? []) : [];
        // A species caught both ways owns two appearances, and one used to hide
        // the other (upstream 4bfae97). The choice only holds while that
        // appearance is actually collected.
        const hasShiny = Boolean(ready ? detail.is_shiny : dexRow.is_shiny);
        const hasNormal = Boolean(ready ? detail.has_normal : dexRow.has_normal);
        let showingShiny;
        if (this._appearance === true && hasShiny)
            showingShiny = true;
        else if (this._appearance === false && hasNormal)
            showingShiny = false;
        else
            showingShiny = individuals[0]?.is_shiny ?? hasShiny;
        const identity = column([
            label(ready ? detail.name : (dexRow.name || `#${this._inspecting}`), 'poketokenbar-title'),
            label(t(rarity), 'poketokenbar-caption poketokenbar-strong poketokenbar-secondary'),
        ], 'poketokenbar-companion-lines');
        identity.x_expand = true;
        if (showingShiny)
            identity.add_child(caption(`✨ ${t('shiny')}`, 'secondary'));
        if (ready ? detail.is_raising : dexRow.is_raising)
            identity.add_child(caption(t('raising'), 'accent'));
        sprite.setPath((ready
            ? (showingShiny ? detail.sprite_path_shiny : detail.sprite_path_normal)
                || detail.sprite_path
            : dexRow.sprite_path) || null);
        const pinned = ready ? detail.is_pinned : dexRow.is_pinned;
        const pin = borderedButton(pinned ? t('unpin') : t('pin_to_panel'), () =>
            markSent(pin, Commands.represent(pinned ? null : this._inspecting)));
        pin.x_align = Clutter.ActorAlign.START;
        identity.add_child(pin);
        this.add_child(row([spriteBox, identity], 'poketokenbar-companion'));

        if (!ready || detail.status === 'loading') {
            this.add_child(placeholder(t('loading_pokemon_details')));
            return;
        }
        if (detail.status === 'failed') {
            this.add_child(placeholder(t('pokemon_details_unavailable')));
            const retry = borderedButton(t('retry'), () =>
                markSent(retry, Commands.inspect(this._inspecting, true)));
            retry.x_align = Clutter.ActorAlign.CENTER;
            this.add_child(retry);
            return;
        }

        // Both appearances collected: pick which one this page is about.
        if (hasNormal && hasShiny) {
            this.add_child(segmented([
                {label: t('dex_normal_label'), value: false},
                {label: `✨ ${t('shiny')}`, value: true},
            ], showingShiny, value => {
                this._appearance = value;
                this._individualIndex = 0;
                this.update(this._state);
            }, {accent: true, expand: false}));
        }

        const shown = individuals.filter(individual => Boolean(individual.is_shiny) === showingShiny);
        const index = Math.min(this._individualIndex, Math.max(0, shown.length - 1));
        if (shown.length > 1) {
            this.add_child(segmented(shown.map((individual, position) => ({
                label: individual.label, value: position,
            })), index, position => {
                this._individualIndex = position;
                this.update(this._state);
            }, {expand: false}));
        } else if (shown.length === 1) {
            this.add_child(caption(shown[0].label, 'secondary'));
        } else {
            // An earlier stage of a line, or the colour you have not caught:
            // the species reference below is all there is to show.
            this.add_child(caption(t('dex_appearance_preview'), 'secondary'));
        }
        const individual = shown[index];
        if (individual)
            this._addIndividual(individual, t);
        else
            this._addBaseStats(detail.species?.base_stats ?? [], t);
        this._addSpecies(detail, t);
    }

    _addIndividual(individual, t) {
        const parts = [
            label(t('pokemon_individual'), 'poketokenbar-callout-bold poketokenbar-secondary'),
            row([
                valuePair(t('level'), String(individual.level)),
                valuePair(t('gender'), individual.gender_text),
                valuePair(t('nature'), individual.nature_text),
            ]),
            valuePair(t('ability'), individual.ability_text),
            caption(t('actual_stats'), 'secondary'),
        ];
        for (const statRow of individual.stats ?? [])
            parts.push(this._statBar(statRow.label, statRow.value, statRow.fraction, `IV ${statRow.iv}`));

        parts.push(caption(t('known_moves'), 'secondary'));
        const moves = individual.moves ?? [];
        if (moves.length === 0)
            parts.push(caption(t('no_level_moves'), 'secondary'));
        for (const knownMove of moves) {
            parts.push(row([label(knownMove.name, 'poketokenbar-caption'), spacer(),
                caption(`Lv. ${knownMove.level}`, 'secondary')]));
        }
        this.add_child(card(parts));
    }

    _statBar(name, value, fraction, suffix) {
        const meter = new Meter();
        meter.setFraction(fraction, 'ok', 'blue');
        meter.y_align = Clutter.ActorAlign.CENTER;
        const parts = [label(name, 'poketokenbar-statname'), meter,
            label(String(value), 'poketokenbar-statvalue')];
        if (suffix)
            parts.push(caption(suffix, 'secondary'));
        const line = row(parts);
        line.style = 'spacing: 8px;';
        return line;
    }

    _addBaseStats(stats, t) {
        const parts = [label(t('base_stats'), 'poketokenbar-callout-bold poketokenbar-secondary')];
        for (const baseStat of stats)
            parts.push(this._statBar(baseStat.label, baseStat.value, baseStat.fraction, null));
        this.add_child(card(parts));
    }

    _addSpecies(detail, t) {
        const species = detail.species;
        if (!species)
            return;
        const types = row([]);
        for (const name of species.types ?? [])
            types.add_child(pill(String(name).toUpperCase(), 'soft-blue'));
        this.add_child(card([
            label(t('species_data'), 'poketokenbar-callout-bold poketokenbar-secondary'),
            types,
            row([
                valuePair(t('height'), species.height_text),
                valuePair(t('weight'), species.weight_text),
                valuePair(t('base_stat_total'), String(species.base_total)),
            ]),
            caption(t('possible_abilities'), 'secondary'),
            paragraph((species.abilities ?? []).join(', '), 'poketokenbar-caption poketokenbar-secondary'),
        ]));

        // A hundred rows is most of a page, so the full list waits to be asked for.
        const parts = [button(
            `${this._showingMoves ? '▾' : '▸'} ${
                t('complete_move_list').replace('%1', String(detail.move_count ?? 0))}`,
            () => {
                this._showingMoves = !this._showingMoves;
                this.update(this._state);
            }, 'poketokenbar-link')];
        if (this._showingMoves) {
            for (const speciesMove of species.moves ?? []) {
                parts.push(row([label(speciesMove.name, 'poketokenbar-caption'), spacer(),
                    caption(speciesMove.methods, 'secondary')]));
            }
        }
        this.add_child(card(parts));
    }
});

// MARK: Settings (upstream SettingsView)

// Declared rather than passed inline so a test can check every one of them
// against the daemon's own defaults: config.load drops a key it has no default
// for, which makes a wrong name here a switch that flips and does nothing.
const PANEL_TOGGLES = [
    {key: 'show_tokens_in_menu', string: 'setting_tokens_in_panel'},
    {key: 'show_cost_in_menu', string: 'setting_cost_in_panel'},
    {key: 'show_limit_in_menu', string: 'setting_limits_in_panel'},
];
const PANEL_LIMIT_WINDOWS = {
    key: 'limit_display_mode',
    string: 'setting_panel_limit_windows',
    options: [
        {value: 'both', string: 'limits_both'},
        {value: 'session', string: 'five_hour_session'},
        {value: 'weekly', string: 'weekly'},
    ],
};
const LIMIT_VALUE = {
    key: 'limit_value_mode',
    string: 'setting_limit_value',
    options: [
        {value: 'used', string: 'limit_value_used'},
        {value: 'remaining', string: 'limit_value_remaining'},
    ],
};
// Frame-rate presets, plus switching the animation off.
const ANIMATION = {
    key: 'animation_quality',
    string: 'setting_animation',
    hint: 'animation_hint',
    options: [
        {value: ANIMATION_OFF, string: 'quality_off'},
        {value: 'saver', string: 'quality_saver'},
        {value: 'balanced', string: 'quality_balanced'},
        {value: 'smooth', string: 'quality_smooth'},
    ],
};
const REFRESH_INTERVAL = {key: 'refresh_interval', string: 'setting_refresh_interval',
    presets: [60, 120, 300, 600, 900]};
const PET_TOGGLES = [
    {key: 'floating_pet_enabled', string: 'setting_desktop_pet', hint: 'pet_hint'},
    {key: 'floating_pet_bubble_alerts', string: 'setting_pet_bubbles'},
];
const PET_SIZE = {key: 'floating_pet_size', string: 'setting_pet_size', unit: 'px',
    min: 48, max: 384, step: 12};
const NOTIFICATION_TOGGLES = [
    {key: 'limit_notifications', string: 'setting_limit_notifications'},
    {key: 'companion_notifications', string: 'setting_companion_notifications'},
    {key: 'status_checks_enabled', string: 'setting_status_checks', hint: 'status_checks_hint'},
];
// Numeric settings as steppers: each has a range outside which the daemon
// misbehaves quietly, and a stepper cannot express a value outside it.
const THRESHOLDS = [
    {key: 'warn_threshold', string: 'setting_warn_threshold', unit: '%', min: 50, max: 95, step: 5},
    {key: 'crit_threshold', string: 'setting_crit_threshold', unit: '%', min: 60, max: 99, step: 1},
];
// Difficulty multipliers, stepped through a fixed ladder rather than a slider.
// DIFFICULTY_STEPS mirrors balance.DIFFICULTY_STEPS; a test holds them equal.
const DIFFICULTY_STEPS = [0.1, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2];
const DIFFICULTIES = [
    {key: 'growth_difficulty', string: 'difficulty_growth'},
    {key: 'shop_difficulty', string: 'difficulty_shop'},
];

export const SettingsSection = GObject.registerClass(
class SettingsSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
        // Which provider's scan-folder field is open: one at a time.
        this._openProvider = null;
        this._advancedOpen = false;
        this._state = null;
        // Which destructive transfer is waiting on an answer: '', 'import' or
        // 'undo'; and a notice for an import that cannot start.
        this._pending = '';
        this._transferNotice = '';
    }

    release() {
        this._pending = '';
        this._transferNotice = '';
        super.release();
    }

    update(state) {
        this._state = state;
        this.clear();
        const config = state?.config ?? {};
        const t = key => this._reader.text(key);

        this._group(t('general'), [
            this._item(t('setting_language'), this._cyclePill(
                LANGUAGE_NAMES[config.language] ?? config.language ?? 'en',
                () => {
                    const index = LANGUAGES.indexOf(config.language ?? 'en');
                    Config.set('language', LANGUAGES[(index + 1) % LANGUAGES.length]);
                })),
            this._item(t(REFRESH_INTERVAL.string), this._cyclePill(
                t('minutes_unit').replace('%1',
                    String(Math.round((Number(config[REFRESH_INTERVAL.key]) || 120) / 60))),
                () => {
                    const presets = REFRESH_INTERVAL.presets;
                    const current = Number(config[REFRESH_INTERVAL.key]) || 120;
                    const next = presets.find(value => value > current) ?? presets[0];
                    Config.set(REFRESH_INTERVAL.key, next);
                })),
            this._choiceItem(ANIMATION, config, t),
            this._choiceItem(LIMIT_VALUE, config, t),
        ]);

        this._group(t('section_panel'), [
            ...PANEL_TOGGLES.map(spec => this._toggleItem(spec, config, t)),
            this._choiceItem(PANEL_LIMIT_WINDOWS, config, t),
        ], t('all_off_hint'));

        this._group(t('section_pet'), [
            ...PET_TOGGLES.map(spec => this._toggleItem(spec, config, t)),
            this._item(t(PET_SIZE.string), this._stepper(PET_SIZE, config)),
        ]);

        this._group(t('notifications'), [
            ...NOTIFICATION_TOGGLES.map(spec => this._toggleItem(spec, config, t)),
            ...THRESHOLDS.map(spec => this._item(t(spec.string), this._stepper(spec, config))),
        ]);

        this._group(t('difficulty_section'), DIFFICULTIES.map(spec =>
            this._item(t(spec.string), this._difficultyStepper(spec, config))),
        `${Math.round(DIFFICULTY_STEPS[0] * 100)}%–${Math.round(DIFFICULTY_STEPS.at(-1) * 100)}% · ${
            t('difficulty_hint')}`);

        this._addTransfer(state, t);
        this._addAdvanced(state, t);
    }

    // --- grouped list rows ---------------------------------------------------

    _group(title, items, hint = null) {
        this.add_child(label(title, 'poketokenbar-group-title'));
        const box = column(items, 'poketokenbar-group');
        box.x_expand = true;
        items.at(-1)?.set_style('border-bottom-width: 0;');
        this.add_child(box);
        if (hint)
            this.add_child(paragraph(hint, 'poketokenbar-caption2 poketokenbar-tertiary'));
    }

    /**
     * One grouped-list row: the name and its control on a line, and a hint
     * under both. The hint is its own line at the row's full width: wrapped
     * beside the control, St measured its height before its width and the
     * next row was drawn over it.
     */
    _item(text, control, hint = null) {
        const name = label(text, 'poketokenbar-callout');
        name.x_expand = true;
        const parts = [row([name, control], 'poketokenbar-group-line')];
        if (hint)
            parts.push(paragraph(hint, 'poketokenbar-caption2 poketokenbar-tertiary'));
        return column(parts, 'poketokenbar-group-row');
    }

    _toggleItem(spec, config, t) {
        return this._item(t(spec.string),
            switchButton(Boolean(config[spec.key]), value => Config.set(spec.key, value)),
            spec.hint ? t(spec.hint) : null);
    }

    /** A choice as upstream's menu picker looks: a pill naming the current
     * option, which steps to the next one on a click. */
    _choiceItem(spec, config, t) {
        const current = config[spec.key] ?? spec.options[0].value;
        const index = Math.max(0, spec.options.findIndex(option => option.value === current));
        const next = spec.options[(index + 1) % spec.options.length];
        return this._item(t(spec.string),
            this._cyclePill(t(spec.options[index].string), () => Config.set(spec.key, next.value)),
            spec.hint ? t(spec.hint) : null);
    }

    _cyclePill(text, onClick) {
        return button(text, onClick, 'poketokenbar-valuepill');
    }

    _stepper(spec, config) {
        const current = Number(config[spec.key]) || spec.min;
        const clamp = value => Math.max(spec.min, Math.min(spec.max, value));
        return row([
            button('−', () => Config.set(spec.key, clamp(current - spec.step))),
            label(`${current}${spec.unit ?? ''}`, 'poketokenbar-stepvalue'),
            button('+', () => Config.set(spec.key, clamp(current + spec.step))),
        ], 'poketokenbar-stepper');
    }

    _difficultyStepper(spec, config) {
        const raw = Number(config[spec.key]);
        const current = Number.isFinite(raw)
            ? Math.min(Math.max(raw, DIFFICULTY_STEPS[0]), DIFFICULTY_STEPS.at(-1))
            : 1;
        // A hand-edited value between two steps moves to its neighbour.
        const lower = DIFFICULTY_STEPS.filter(step => step < current).at(-1);
        const higher = DIFFICULTY_STEPS.find(step => step > current);
        const down = button('−', () => {
            if (lower !== undefined)
                Config.set(spec.key, lower);
        });
        const up = button('+', () => {
            if (higher !== undefined)
                Config.set(spec.key, higher);
        });
        down.opacity = lower === undefined ? 110 : 255;
        up.opacity = higher === undefined ? 110 : 255;
        return row([down, label(`${Math.round(current * 100)}%`, 'poketokenbar-stepvalue'), up],
            'poketokenbar-stepper');
    }

    // --- backup & transfer (upstream transferSection) -------------------------

    /** Where a save is written to and read from, as the daemon reports it. */
    _savePath(state) {
        return state?.transfer?.path || GLib.build_filenamev([
            GLib.get_home_dir(), 'poketokenbar-save.json',
        ]);
    }

    _addTransfer(state, t) {
        const transfer = state?.transfer ?? {};
        const items = [
            this._item(t('export_save'), borderedButton(t('export_save'), () => {
                Commands.exportSave(this._savePath(state));
                this._pending = '';
                this._transferNotice = '';
            }), t('export_hint')),
            // Import asks first: it overwrites the save.
            this._item(t('import_save'), borderedButton(t('import_save'), () => {
                if (!transfer.exists) {
                    this._transferNotice = t('import_no_file').replace('%1', this._savePath(state));
                    this._pending = '';
                } else if (transfer.error) {
                    this._transferNotice = t('import_unreadable');
                    this._pending = '';
                } else {
                    this._pending = 'import';
                    this._transferNotice = '';
                }
                this.update(this._state);
            }), t('import_hint')),
        ];
        // Undoing overwrites the save as thoroughly as importing does.
        if (transfer.can_undo) {
            items.push(this._item(t('undo_import'), borderedButton(t('undo_import'), () => {
                this._pending = 'undo';
                this._transferNotice = '';
                this.update(this._state);
            })));
        }
        this._group(t('section_transfer'), items);
        this._addTransferPrompt(state, t);
    }

    _addTransferPrompt(state, t) {
        const transfer = state?.transfer ?? {};
        const dismiss = () => {
            this._pending = '';
            this._transferNotice = '';
            this.update(this._state);
        };
        if (this._transferNotice !== '') {
            this.add_child(card([
                paragraph(this._transferNotice, 'poketokenbar-confirm-detail'),
                row([spacer(), button(t('cancel'), dismiss)]),
            ], 'poketokenbar-confirm'));
            return;
        }
        if (this._pending === '')
            return;

        const undoing = this._pending === 'undo';
        const parts = [
            label(t(undoing ? 'undo_confirm' : 'import_confirm'), 'poketokenbar-confirm-title'),
            // What is in the incoming save, and what it would replace.
            paragraph(t(undoing ? 'undo_file_detail' : 'import_file_detail')
                .replace('%1', undoing ? transfer.undo_taken_text : transfer.exported_text)
                .replace('%2', String((undoing ? transfer.undo_dex_count : transfer.dex_count) ?? 0))
                .replace('%3', undoing ? transfer.undo_used_text : transfer.used_text),
            'poketokenbar-confirm-detail'),
            paragraph(t('import_current_detail')
                .replace('%1', String(transfer.current_dex_count ?? 0))
                .replace('%2', transfer.current_used_text),
            'poketokenbar-confirm-detail'),
        ];
        if (undoing ? transfer.undo_goes_backwards : transfer.goes_backwards)
            parts.push(paragraph(t('import_goes_backwards'), 'poketokenbar-confirm-warning'));
        parts.push(row([
            spacer(),
            button(t(undoing ? 'restore' : 'replace'), () => {
                if (undoing)
                    Commands.undoImport();
                else
                    Commands.importSave(this._savePath(state));
                dismiss();
            }, 'poketokenbar-button-bordered poketokenbar-danger'),
            button(t('cancel'), dismiss),
        ]));
        this.add_child(card(parts, 'poketokenbar-confirm'));
    }

    // --- advanced: extra scan folders -------------------------------------------

    _addAdvanced(state, t) {
        const providers = state?.settings?.providers ?? [];
        if (providers.length === 0)
            return;
        this.add_child(button(`${this._advancedOpen ? '▾' : '▸'} ${t('section_advanced')}`, () => {
            this._advancedOpen = !this._advancedOpen;
            this.update(this._state);
        }, 'poketokenbar-link'));
        if (!this._advancedOpen)
            return;

        const items = [];
        for (const providerRow of providers) {
            const open = this._openProvider === providerRow.id;
            const summary = providerRow.custom_scan_roots
                ? t('setting_scan_roots_matches').replace('%1', String(providerRow.matched_folders))
                : '';
            const item = this._item(providerRow.display_name, button(open ? '▾' : '▸', () => {
                this._openProvider = open ? null : providerRow.id;
                this.update(this._state);
            }), summary || null);
            items.push(item);
            if (open)
                items.push(this._scanFolderEntry(providerRow));
        }
        this._group(t('scan_folders'), items, t('setting_scan_roots_hint'));
    }

    _scanFolderEntry(providerRow) {
        const entry = new St.Entry({
            style_class: 'poketokenbar-entry',
            can_focus: true,
            x_expand: true,
        });
        entry.set_text(providerRow.custom_scan_roots ?? '');
        entry.clutter_text.connect('activate', () => {
            Config.setScanRoots(providerRow.id, entry.get_text());
        });
        return row([entry], 'poketokenbar-group-row');
    }
});
