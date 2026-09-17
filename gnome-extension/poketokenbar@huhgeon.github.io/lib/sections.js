/* sections.js — the popup's tabs.
 *
 * Each section owns a box and a single `update(state)`. Rebuilding a section's
 * children on every poll is the simplest correct thing and cheap at these
 * sizes, with one exception: sprites are handed a path and decide for
 * themselves whether anything changed, because re-decoding ~55 GIF frames every
 * two seconds is not free.
 */

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as Commands from './commands.js';
import * as Config from './config.js';
import {ANIMATION_OFF, DEFAULT_QUALITY} from './framecap.js';
import {LANGUAGES} from './languages.js';
import {Sprite} from './sprite.js';
import {
    Meter, badge, button, column, heading, label, levelClass, markSent,
    paragraph, placeholder, resetsIn, row, statLine, toggleRow,
} from './widgets.js';

// The Pokedex grid. Six across is what the popup's fixed width holds at this
// sprite size; three rows down keeps a page inside the popup without a scroll,
// so browsing is page by page rather than page and then scroll.
const DEX_COLUMNS = 6;
const DEX_ROWS = 3;
const DEX_SPRITE_SIZE = 48;

/** Base: a vertical box that empties itself before each update. */
const Section = GObject.registerClass(
class Section extends St.BoxLayout {
    _init(styleClass = 'poketokenbar-section') {
        super._init({style_class: styleClass, x_expand: true});
        // Same reason as widgets.verticalBox: `vertical` is deprecated from 48
        // and `orientation` is not documented as present in 45.
        if ('orientation' in this)
            this.orientation = Clutter.Orientation.VERTICAL;
        else
            this.vertical = true;
    }

    clear() {
        this.destroy_all_children();
    }

    /** The popup closed, or another tab took over: nothing here is on screen.
     *
     * Dropping the children is what actually stops the animating sprites among
     * them — every Sprite kills its own timer on destroy — and it frees the
     * textures they uploaded. A section that is not visible was otherwise still
     * running a timer per sprite inside the compositor, which for the Pokedex
     * grid is two dozen of them.
     */
    release() {
        this.clear();
    }
});

// MARK: Home

export const HomeSection = GObject.registerClass(
class HomeSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
        // Held across updates so its decoded frames survive a rebuild.
        this._sprite = new Sprite({size: 72});
        this._spriteHolder = new St.Bin({
            style_class: 'poketokenbar-companion-sprite',
            x_align: Clutter.ActorAlign.CENTER,
        });
        this._spriteHolder.set_child(this._sprite);
        // Nothing else owns the holder while it sits out of the tree, so this
        // object has to be the one that frees it.
        this.connect('destroy', () => {
            if (!this._spriteHolder.get_parent())
                this._spriteHolder.destroy();
        });
    }

    /** Take the companion sprite out of the tree before the rest is destroyed.
     *
     * The base clear() destroys every child, and from the first update onwards
     * the sprite holder is one of them — so the second update reached a
     * disposed St.Bin ("impossible to access it") and the Home tab stopped
     * rendering from then on. Removing it drops the parent's reference while
     * this object keeps its own, which is what "held across updates" was meant
     * to mean all along.
     */
    clear() {
        if (this._spriteHolder.get_parent() === this)
            this.remove_child(this._spriteHolder);
        super.clear();
    }

    release() {
        super.release();
        // The holder survives clear(), so its sprite has to be told directly.
        this._sprite.setPaused(true);
    }

    update(state) {
        this.clear();
        const t = key => this._reader.text(key);
        const companion = state?.companion;
        // Without a companion the holder stays out of the tree, and a sprite
        // nobody can see must not keep asking for frames.
        this._sprite.setPaused(!companion);
        // The animation setting reached the panel and the desktop pet but
        // never this one, which is the largest sprite the extension draws — so
        // turning the animation down, or off, left the companion on Home
        // moving exactly as before.
        this._sprite.setQuality(state?.config?.animation_quality ?? DEFAULT_QUALITY);

        // The daemon holds a celebration for exactly one poll, so it shows
        // once rather than staying up until the next hatch.
        const banner = state?.celebration;
        if (banner?.kind) {
            this.add_child(label(banner.title ?? '', 'poketokenbar-celebration'));
            if (banner.detail)
                this.add_child(paragraph(banner.detail, 'poketokenbar-subtle'));
        }

        // --- companion -----------------------------------------------------
        if (companion) {
            // Home always shows what is being raised, never the pinned species:
            // pinning changes the panel, and hiding the companion here would
            // make its progress unreachable.
            this._sprite.setPath(companion.sprite_path || null);
            this.add_child(this._spriteHolder);

            if (companion.stage === 'egg') {
                this.add_child(label(t('egg'), 'poketokenbar-title'));
                const meter = new Meter();
                meter.setFraction(companion.egg_progress ?? 0);
                this.add_child(meter);
                this.add_child(label(companion.label ?? '', 'poketokenbar-subtle'));
            } else {
                const name = companion.name || `#${companion.species_id}`;
                this.add_child(label(
                    companion.is_shiny ? `✨ ${name}` : name, 'poketokenbar-title'));
                this.add_child(label(
                    `${t(companion.rarity ?? 'common')} · ${companion.nature ?? ''}`,
                    'poketokenbar-subtle'));

                const meter = new Meter();
                meter.setFraction(companion.stage_progress ?? 0);
                this.add_child(meter);
                this.add_child(label(
                    `${companion.remaining_text} → ${
                        companion.is_final_form ? t('graduation') : t('next_evolution')}`,
                    'poketokenbar-subtle'));

                this.add_child(this._evolutionLine(companion));
            }
            this.add_child(label(companion.status_message ?? '', 'poketokenbar-status'));
        }

        // --- the pin --------------------------------------------------------
        // The pin only changes the panel and the desktop pet, never Home, so
        // when one is set this is the one screen that can explain why those
        // two disagree with what is shown above. It used to be explained
        // nowhere: the panel simply stopped following the companion, said
        // nothing about it, and offered no way back.
        this._addPinRow(companion, t);

        // --- today ---------------------------------------------------------
        this.add_child(heading(t('todays_tokens')));
        const today = state?.today;
        this.add_child(statLine(t('todays_tokens'), today?.tokens_grouped ?? '0'));
        if (today?.cost_text)
            this.add_child(statLine('', today.cost_text));

        const periods = state?.periods;
        if (periods?.week)
            this.add_child(statLine(t('this_week'), periods.week.tokens_text ?? ''));
        if (periods?.month)
            this.add_child(statLine(t('this_month'), periods.month.tokens_text ?? ''));

        // Only worth the rows when the day actually spanned several models.
        const models = today?.models ?? [];
        if (models.length > 1) {
            for (const modelRow of models.slice(0, 6))
                this.add_child(statLine(modelRow.model, modelRow.total_tokens_text));
        }

        // --- per provider ---------------------------------------------------
        // Only when more than one tool is in use: a single-provider day would
        // just restate the total on a second line.
        const providers = state?.providers ?? {};
        const ids = Object.keys(providers);
        if (ids.length > 1) {
            for (const id of ids) {
                // Named apart from the settings page's providerRow: both are
                // "a provider", and they are not the same shape.
                const usageRow = providers[id];
                this.add_child(statLine(id, usageRow.total_tokens_text));
                this.add_child(label(
                    `in ${usageRow.input_tokens} · out ${usageRow.output_tokens}` +
                    ` · cache w ${usageRow.cache_creation_tokens}` +
                    ` · r ${usageRow.cache_read_tokens}`,
                    'poketokenbar-subtle'));
            }
        }

        this._addProviderStatus(state);

        // --- official limits -------------------------------------------------
        this._addLimits(state);
    }

    /** Which species is holding the panel, and the button that releases it.
     *
     * Shown whenever a pin is set, including one on the companion's own
     * current form: "the panel happens to agree right now" is not the same as
     * "nothing is pinned", and the difference is exactly what surprises
     * someone at the next evolution.
     */
    _addPinRow(companion, t) {
        const pinned = companion?.representative_species_id;
        if (!pinned)
            return;
        const name = companion.panel_name || `#${pinned}`;
        const spacer = new St.Widget({x_expand: true});
        const unpin = button(t('unpin'), () => markSent(unpin, Commands.represent(null)));
        this.add_child(row([
            label(`\u{1F4CC} ${t('pinned_to_panel')}: ${name}`, 'poketokenbar-subtle'),
            spacer,
            unpin,
        ], 'poketokenbar-pinrow'));
    }

    _evolutionLine(companion) {
        const line = row([], 'poketokenbar-evoline');
        for (const evoStage of companion.evo_line ?? []) {
            const sprite = new Sprite({size: 32});
            sprite.setPath(evoStage.sprite_path || null);
            // Forms it has not reached yet are dimmed rather than hidden, so
            // the line still shows where the companion is heading.
            sprite.opacity = evoStage.reached ? 255 : 90;
            line.add_child(sprite);
        }
        return line;
    }

    _addProviderStatus(state) {
        // Every row here is already a problem: the daemon drops the healthy
        // ones, and an unreachable status page is left out rather than
        // reported as an outage. So there is nothing to filter — a row means
        // something is wrong, and that is the one thing that explains a number
        // looking off.
        const statuses = state?.provider_status ?? {};
        for (const id of Object.keys(statuses)) {
            const providerStatus = statuses[id];
            if (!providerStatus)
                continue;
            this.add_child(row([
                badge(id),
                new St.Widget({x_expand: true}),
                label(providerStatus.label ?? '',
                    `poketokenbar-value ${levelClass(providerStatus.severity)}`),
            ]));
        }
    }

    _addLimits(state) {
        const t = key => this._reader.text(key);
        const limits = state?.limits;
        if (!limits || (!limits.session && !limits.weekly))
            return;

        // The plan is worth naming: the same percentage means a different
        // number of tokens on Pro and on Max.
        this.add_child(heading(limits.plan
            ? `${t('limits_official')} · ${String(limits.plan).toUpperCase()}`
            : t('limits_official')));

        // Which account these are for. Someone signed into two is otherwise
        // reading a bar that belongs to the other one.
        const account = limits.account ?? {};
        const who = account.email || account.name;
        if (who) {
            this.add_child(label(
                account.organization ? `${who} · ${account.organization}` : who,
                'poketokenbar-subtle'));
        }
        for (const [key, name] of [['session', 'five_hour_session'], ['weekly', 'weekly']]) {
            const limitWindow = limits[key];
            if (!limitWindow)
                continue;
            const percent = Math.round(limitWindow.utilization ?? 0);
            this.add_child(statLine(
                t(name), `${percent}%`, `poketokenbar-value ${levelClass(limitWindow.severity)}`));
            const meter = new Meter();
            meter.setFraction(percent / 100, limitWindow.severity);
            this.add_child(meter);
            const resets = resetsIn(limitWindow.resets_at, t);
            if (resets)
                this.add_child(label(resets, 'poketokenbar-subtle'));

            // The forecast belongs to the window it is a forecast for.
            const burnRow = state?.burn?.[key];
            if (burnRow?.eta_text) {
                this.add_child(label(
                    t('at_this_rate').replace('%1', burnRow.eta_text),
                    'poketokenbar-subtle'));
            }
        }
    }
});

// MARK: Shop and Bag

// How big an item's picture is drawn in the shop and the bag.
const ITEM_ICON_SIZE = 32;

/** The picture for one shop or bag row.
 *
 * Takes the two values rather than the row, so the field names stay where the
 * contract test can see which block they were read from.
 *
 * The daemon ships a sprite for the items that have one and an emoji for the
 * rest — an egg is a glyph, a Rare Candy is a picture — and both were being
 * dropped on the floor, which left the shop as a wall of text. A sprite that
 * fails to decode hides itself, and that is the third case: the emoji is the
 * fallback, not the second choice.
 */
function itemIcon(spritePath, emoji) {
    if (spritePath) {
        const sprite = new Sprite({size: ITEM_ICON_SIZE});
        sprite.setPath(spritePath);
        if (sprite.visible)
            return sprite;
        sprite.destroy();
    }
    return label(emoji || '', 'poketokenbar-item-emoji');
}

export const ShopSection = GObject.registerClass(
class ShopSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
    }

    update(state) {
        this.clear();
        const t = key => this._reader.text(key);

        this.add_child(heading(t('spendable_tokens')));
        this.add_child(label(
            state?.companion?.spendable_text ?? '0', 'poketokenbar-title'));
        this.add_child(label(t('spend_hint'), 'poketokenbar-subtle'));

        for (const shopItem of state?.shop ?? []) {
            const icon = itemIcon(shopItem.sprite_path, shopItem.emoji);
            // The text column takes whatever width the icon, price and button
            // leave, and the description wraps inside it. With a spacer soaking
            // up the free space instead, the column got its natural width and
            // every description ran off the edge of a 380px popup.
            const lines = [
                label(shopItem.label || shopItem.key, 'poketokenbar-key'),
                paragraph(shopItem.description ?? '', 'poketokenbar-subtle'),
            ];
            // An egg during the egg stage: the button below is disabled for
            // a reason the price does not explain, so the card says it.
            if (shopItem.locked)
                lines.push(paragraph(t('egg_shop_locked_hint'), 'poketokenbar-subtle'));
            const left = column(lines);
            left.x_expand = true;
            const price = label(shopItem.price_text ?? '', 'poketokenbar-value');
            const children = [icon, left];
            if (shopItem.owned_count > 0)
                children.push(badge(t('owned_count').replace('%1', String(shopItem.owned_count))));
            children.push(price);
            if (shopItem.owned) {
                // A one-off that is already held: showing a live Buy button
                // would offer a purchase the daemon refuses.
                children.push(label(t('owned'), 'poketokenbar-value'));
            } else {
                const buy = button(t('buy'), () => markSent(buy, Commands.buy(shopItem.key)));
                // Disabled rather than hidden while unaffordable: a card that
                // vanishes reads as a bug, and the price is the point of the row.
                buy.reactive = Boolean(shopItem.affordable);
                buy.opacity = shopItem.affordable ? 255 : 120;
                children.push(buy);
            }
            this.add_child(row(children, 'poketokenbar-card'));
        }
    }
});

export const BagSection = GObject.registerClass(
class BagSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
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
            const icon = itemIcon(bagItem.sprite_path, bagItem.emoji);
            const left = column([
                label(`${bagItem.label || bagItem.key} ×${bagItem.count ?? 0}`,
                    'poketokenbar-key'),
                paragraph(bagItem.effect || bagItem.description || '',
                    'poketokenbar-subtle'),
            ]);
            left.x_expand = true;
            const children = [icon, left];
            if (bagItem.usable) {
                const use = button(t('use'), () => markSent(use, Commands.use(bagItem.key)));
                children.push(use);
            }
            else if (bagItem.passive)
                children.push(label(t('active'), 'poketokenbar-value'));
            this.add_child(row(children, 'poketokenbar-card'));
        }
    }
});

// MARK: Collection

export const CollectionSection = GObject.registerClass(
class CollectionSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
        this._showingCatchLog = false;
        this._page = 0;
        this._perPage = DEX_COLUMNS * DEX_ROWS;
        this._state = null;
    }

    update(state) {
        this._state = state;
        this.clear();
        const t = key => this._reader.text(key);

        const toggle = row([
            button(t('pokedex'), () => {
                this._showingCatchLog = false;
                this.update(this._state);
            }),
            button(t('catch_log'), () => {
                this._showingCatchLog = true;
                this.update(this._state);
            }),
        ]);
        this.add_child(toggle);

        if (this._showingCatchLog)
            this._buildCatchLog(state);
        else
            this._buildPokedex(state);
    }

    _buildPokedex(state) {
        const t = key => this._reader.text(key);
        const entries = state?.dex ?? [];
        if (entries.length === 0) {
            this.add_child(placeholder(t('no_pokemon_yet')));
            return;
        }

        this.add_child(label(`${entries.length} species`, 'poketokenbar-subtle'));
        // What a tap on a cell does. It pins to the panel, which is not a
        // thing a grid of sprites looks like it would do, and the tap that
        // releases it is the same one — neither was written down anywhere.
        this.add_child(paragraph(t('dex_pin_hint'), 'poketokenbar-subtle'));
        const counts = state?.rarity_counts ?? {};
        const summary = ['legendary', 'rare', 'uncommon', 'common']
            .filter(key => counts[key])
            .map(key => `${t(key)} ${counts[key]}`)
            .join('  ');
        if (summary)
            this.add_child(label(summary, 'poketokenbar-subtle'));

        const pages = Math.max(1, Math.ceil(entries.length / this._perPage));
        this._page = Math.min(this._page, pages - 1);
        const page = entries.slice(
            this._page * this._perPage, (this._page + 1) * this._perPage);

        // A fixed six-wide grid: the popup has a fixed width, so reflowing by
        // available space would only ever change how ragged the last row is.
        let currentRow = null;
        page.forEach((dexEntry, index) => {
            if (index % DEX_COLUMNS === 0) {
                currentRow = row([], 'poketokenbar-dexrow');
                this.add_child(currentRow);
            }
            currentRow.add_child(this._dexCell(dexEntry));
        });

        if (pages > 1) {
            const spacer = new St.Widget({x_expand: true});
            const previous = button('‹', () => {
                this._page = Math.max(0, this._page - 1);
                this.update(this._state);
            });
            const next = button('›', () => {
                this._page = Math.min(pages - 1, this._page + 1);
                this.update(this._state);
            });
            // Dimmed at the ends rather than hidden, so the row keeps its
            // shape and the count stays centred while paging.
            previous.reactive = this._page > 0;
            previous.opacity = this._page > 0 ? 255 : 120;
            next.reactive = this._page < pages - 1;
            next.opacity = this._page < pages - 1 ? 255 : 120;
            this.add_child(row([
                previous,
                spacer,
                label(`${this._page + 1} / ${pages}`, 'poketokenbar-subtle'),
                new St.Widget({x_expand: true}),
                next,
            ], 'poketokenbar-pager'));
        }
    }

    _dexCell(dexEntry) {
        const t = key => this._reader.text(key);
        const sprite = new Sprite({size: DEX_SPRITE_SIZE});
        sprite.setPath(dexEntry.sprite_path || null);
        const caption = label(
            dexEntry.is_shiny ? `✨${dexEntry.species_id}` : `#${dexEntry.species_id}`,
            'poketokenbar-dexnum');
        const parts = [sprite, caption];
        // The one being raised right now appears in the Pokedex before it
        // graduates, and without the badge it is indistinguishable from a
        // finished catch.
        if (dexEntry.is_raising)
            parts.push(badge(t('raising'), 'poketokenbar-badge-small'));
        // The species currently holding the panel. The pin used to be
        // invisible, so a panel that had stopped following the companion —
        // and stopped showing its evolutions — looked like a stuck panel
        // rather than a choice anyone had made.
        if (dexEntry.is_pinned)
            parts.push(badge(t('pinned'), 'poketokenbar-badge-pinned'));
        const cell = column(parts, 'poketokenbar-dexcell');

        // Tapping a cell pins that species to the panel; tapping the pinned
        // one again releases it, which is the only way back to a panel that
        // follows the companion. The daemon refuses a species the save does
        // not own, so this cannot pin a ghost.
        const clickable = new St.Button({
            style_class: dexEntry.is_pinned
                ? 'poketokenbar-dexbutton poketokenbar-dexbutton-pinned'
                : 'poketokenbar-dexbutton',
            can_focus: true,
            child: cell,
        });
        clickable.connect('clicked', () =>
            markSent(clickable, Commands.represent(dexEntry.species_id)));
        return clickable;
    }

    _buildCatchLog(state) {
        const t = key => this._reader.text(key);
        const log = state?.catch_log ?? [];
        if (log.length === 0) {
            this.add_child(placeholder(t('no_pokemon_yet')));
            return;
        }
        this.add_child(label(`${log.length} total`, 'poketokenbar-subtle'));
        const catchCounts = state?.catch_counts ?? {};
        const catchSummary = ['legendary', 'rare', 'uncommon', 'common']
            .filter(key => catchCounts[key])
            .map(key => `${t(key)} ${catchCounts[key]}`)
            .join('  ');
        if (catchSummary)
            this.add_child(label(catchSummary, 'poketokenbar-subtle'));

        for (const catchRecord of log.slice(0, 40)) {
            const chain = row([], 'poketokenbar-chain');
            // The chain's last stage is what it graduated as; catch_log rows
            // carry no name of their own.
            const stages = catchRecord.chain ?? [];
            for (const chainStage of stages) {
                const sprite = new Sprite({size: 24});
                sprite.setPath(chainStage.sprite_path || null);
                chain.add_child(sprite);
            }
            const finalName = stages.length > 0
                ? (stages[stages.length - 1].name || `#${stages[stages.length - 1].species_id}`)
                : '';
            // Not named `heading`: that is an imported helper, and shadowing it
            // here would break the next person who reaches for it in this method.
            const nameRow = row([
                label(catchRecord.is_shiny ? `✨ ${finalName}` : finalName,
                    'poketokenbar-key'),
            ]);
            if (catchRecord.raising)
                nameRow.add_child(badge(t('raising'), 'poketokenbar-badge-small'));
            const details = column([
                nameRow,
                label(`${t(catchRecord.rarity ?? 'common')} · ${catchRecord.nature ?? ''} · ${
                    catchRecord.raised_text ?? ''}`, 'poketokenbar-subtle'),
            ]);
            this.add_child(row([chain, details], 'poketokenbar-card'));
        }
    }
});

// MARK: Settings

// Declared rather than passed inline so a test can check every one of them
// against the daemon's own defaults: config.load drops a key it has no default
// for, which makes a wrong name here a switch that flips and does nothing.
// A switch is only as good as its label, and these borrowed theirs from
// whichever catalogue entry came closest: three of them read "Limits
// (official)" and two read "Raising", so the list was a column of duplicates
// and the desktop pet was a switch nobody could pick out. They have their own
// strings now.
const TOGGLES = [
    {key: 'show_tokens_in_menu', string: 'setting_tokens_in_panel'},
    {key: 'show_cost_in_menu', string: 'setting_cost_in_panel'},
    {key: 'show_limit_in_menu', string: 'setting_limits_in_panel'},
    {key: 'limit_notifications', string: 'setting_limit_notifications'},
    {key: 'companion_notifications', string: 'setting_companion_notifications'},
    {key: 'status_checks_enabled', string: 'setting_status_checks'},
    {key: 'floating_pet_enabled', string: 'setting_desktop_pet'},
    {key: 'floating_pet_bubble_alerts', string: 'setting_pet_bubbles'},
];

// Numeric settings, as a stepper rather than a text field: every one of these
// has a range outside which the daemon misbehaves quietly — a two-second
// refresh hammers the disk, a 0px pet is invisible — and a stepper cannot
// express a value outside it.
//
// The unit rides on the value rather than the label ("120s", not "Refresh
// every (s)"): a unit in the label has to be translated seven times to say
// what the symbol already says everywhere.
const STEPPERS = [
    {key: 'refresh_interval', string: 'setting_refresh_interval', unit: 's',
        min: 60, max: 900, step: 60},
    {key: 'warn_threshold', string: 'setting_warn_threshold', unit: '%',
        min: 50, max: 95, step: 5},
    {key: 'crit_threshold', string: 'setting_crit_threshold', unit: '%',
        min: 60, max: 99, step: 1},
    {key: 'floating_pet_size', string: 'setting_pet_size', unit: 'px',
        min: 48, max: 192, step: 12},
];

// Settings chosen from a short row of buttons. Both the setting and each of its
// values carry a catalogue key: the values used to render as the raw strings
// the daemon stores, so the settings tab offered "both / session / weekly" and
// "saver / balanced / smooth" in English under a heading that read
// "limit_display_mode".
const CHOICES = [
    {
        key: 'limit_display_mode',
        string: 'setting_limit_display',
        options: [
            {value: 'both', string: 'limits_both'},
            {value: 'session', string: 'five_hour_session'},
            {value: 'weekly', string: 'weekly'},
        ],
    },
    // Frame-rate presets, plus switching the animation off. The values live in
    // framecap.js next to the algorithm; these are only their names. "Off"
    // leads because it is the one choice that is not a rate, and because a
    // still sprite is what someone comes to this row looking for.
    {
        key: 'animation_quality',
        string: 'setting_animation',
        options: [
            {value: ANIMATION_OFF, string: 'quality_off'},
            {value: 'saver', string: 'quality_saver'},
            {value: 'balanced', string: 'quality_balanced'},
            {value: 'smooth', string: 'quality_smooth'},
        ],
    },
];

export const SettingsSection = GObject.registerClass(
class SettingsSection extends Section {
    _init(reader) {
        super._init();
        this._reader = reader;
        // Which provider's scan-folder field is open. Only one at a time: the
        // list is twelve long and twelve text fields is a wall, not a setting.
        this._openProvider = null;
        this._state = null;
    }

    update(state) {
        this._state = state;
        this.clear();
        const config = state?.config ?? {};
        const t = key => this._reader.text(key);

        // "Settings", not "Refresh": the heading was borrowed from the nearest
        // catalogue entry and named one row of the tab it sits above.
        this.add_child(heading(t('settings')));
        for (const toggle of TOGGLES)
            this._addToggle(toggle.key, toggle.string, config);
        for (const stepper of STEPPERS)
            this._addStepper(stepper, config);

        for (const choice of CHOICES)
            this._addChoice(choice, config);
        this._addLanguage(config);
        this._addScanFolders(state);
    }

    _addToggle(key, stringKey, config) {
        this.add_child(toggleRow(
            this._reader.text(stringKey),
            Boolean(config[key]),
            value => Config.set(key, value),
            word => this._reader.text(word)));
    }

    _addStepper(spec, config) {
        const current = Number(config[spec.key]) || spec.min;
        const clamp = value => Math.max(spec.min, Math.min(spec.max, value));
        const name = paragraph(this._reader.text(spec.string), 'poketokenbar-key');
        this.add_child(row([
            name,
            button('−', () => Config.set(spec.key, clamp(current - spec.step))),
            label(`${current}${spec.unit ?? ''}`, 'poketokenbar-value'),
            button('+', () => Config.set(spec.key, clamp(current + spec.step))),
        ]));
    }

    _addChoice(spec, config) {
        const current = config[spec.key];
        const buttons = spec.options.map(option => {
            const widget = button(
                this._reader.text(option.string),
                () => Config.set(spec.key, option.value));
            // The chosen one stays flat rather than disabled: a disabled button
            // reads as unavailable, not as selected.
            widget.opacity = option.value === current ? 255 : 130;
            return widget;
        });
        this.add_child(row([label(this._reader.text(spec.string), 'poketokenbar-key')]));
        this.add_child(row(buttons));
    }

    _addLanguage(config) {
        const current = config.language ?? 'en';
        // Labelled, like every other setting. Seven bare language codes with
        // nothing above them read as debug output.
        this.add_child(row([label(this._reader.text('setting_language'),
            'poketokenbar-key')]));
        const buttons = LANGUAGES.map(code => {
            const widget = button(code, () => Config.set('language', code));
            // The chosen one stays flat rather than being disabled: a disabled
            // button reads as unavailable, not as selected.
            widget.opacity = code === current ? 255 : 130;
            return widget;
        });
        this.add_child(row(buttons));
    }

    _addScanFolders(state) {
        const providers = state?.settings?.providers ?? [];
        if (providers.length === 0)
            return;
        // "Scan folders", not "Collection" — that one names the Pokedex tab.
        this.add_child(heading(this._reader.text('scan_folders')));
        this.add_child(paragraph(this._reader.text('setting_scan_roots_hint'),
            'poketokenbar-subtle'));

        for (const providerRow of providers) {
            const summary = providerRow.custom_scan_roots
                ? `${providerRow.display_name} (${providerRow.matched_folders})`
                : providerRow.display_name;
            const open = this._openProvider === providerRow.id;
            const toggle = button(summary, () => {
                this._openProvider = open ? null : providerRow.id;
                this.update(this._state);
            });
            this.add_child(toggle);
            if (open)
                this.add_child(this._scanFolderEntry(providerRow));
        }
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
        return column([
            entry,
            // The count comes from the daemon and reports folders that
            // survived, not patterns typed: an extra that swallows a curated
            // default is dropped, and saying otherwise would be a lie.
            label(this._reader.text('setting_scan_roots_matches')
                .replace('%1', String(providerRow.matched_folders)),
            'poketokenbar-subtle'),
        ]);
    }
});
