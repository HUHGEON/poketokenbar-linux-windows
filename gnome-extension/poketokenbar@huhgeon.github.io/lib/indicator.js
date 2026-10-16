/* indicator.js — the panel button and the popup it opens.
 *
 * The panel shows the companion (or the pinned species) beside the limit
 * percentages, coloured by how close they are. The popup carries the detail,
 * in tabs that mirror the macOS app's.
 */

import Clutter from 'gi://Clutter';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import * as Commands from './commands.js';
import * as Config from './config.js';
import {DEFAULT_QUALITY, effectiveQuality} from './framecap.js';
import {isPowerSaver} from './power.js';
import {Sprite} from './sprite.js';
import {
    BagSection, CollectionSection, HomeSection, SettingsSection, ShopSection,
} from './sections.js';
import {
    TIER_TINT, ago, button, iconButton, label, levelClass, row, segmented, spacer,
    verticalBox,
} from './widgets.js';

// The popup is a fixed width so the Pokédex grid never reflows mid-browse.
const POPUP_WIDTH = 380;
// The tabs, as upstream's: settings is a page behind the gear, not a tab.
const TABS = ['home', 'shop', 'bag', 'collection'];

export const Indicator = GObject.registerClass(
class Indicator extends PanelMenu.Button {
    _init(reader, settings) {
        super._init(0.5, 'PokeTokenBar', false);
        this._reader = reader;
        this._settings = settings;

        // --- panel ----------------------------------------------------------
        this._panelBox = new St.BoxLayout({style_class: 'poketokenbar-panel'});
        // 18px tall, and a wide species may spread to 32 rather than shrink
        // itself to 9px to fit a square (upstream 481ad3a).
        this._sprite = new Sprite({size: 18, maxWidth: 32});
        this._eggLabel = label('', 'poketokenbar-panel-text');
        this._limitBox = new St.BoxLayout({style_class: 'poketokenbar-panel-limits'});
        this._tokensLabel = label('', 'poketokenbar-panel-text');
        this._costLabel = label('', 'poketokenbar-panel-text');

        this._panelBox.add_child(this._sprite);
        this._panelBox.add_child(this._eggLabel);
        this._panelBox.add_child(this._limitBox);
        this._panelBox.add_child(this._tokensLabel);
        this._panelBox.add_child(this._costLabel);
        this.add_child(this._panelBox);

        // --- popup ----------------------------------------------------------
        this._sections = {
            home: new HomeSection(reader),
            shop: new ShopSection(reader),
            bag: new BagSection(reader),
            collection: new CollectionSection(reader),
            settings: new SettingsSection(reader),
        };
        // A section that wants to send someone to another tab — the empty bag
        // pointing at the shop — asks through this rather than reaching into
        // the indicator.
        for (const section of Object.values(this._sections)) {
            section.selectTab = name => this._selectTab(name);
            // A sprite of a species already in the dex opens its page
            // (upstream 26efe4e).
            section.openDexEntry = speciesId => {
                this._selectTab('collection');
                this._sections.collection.openSpecies(speciesId);
            };
        }
        this._currentTab = 'home';
        // Settings is a page behind the gear, not a fifth tab, as upstream's.
        this._settingsOpen = false;

        const item = new PopupMenu.PopupBaseMenuItem({
            reactive: false, can_focus: false, style_class: 'poketokenbar-popup',
        });
        const content = verticalBox({
            style_class: 'poketokenbar-content', x_expand: true,
        });
        content.set_width(POPUP_WIDTH);

        // Rebuilt on every render: the labels come from the daemon's
        // catalogue, which is empty until the first snapshot and changes with
        // the language. Built once, the tabs showed their raw keys for good.
        this._header = verticalBox({x_expand: true});
        content.add_child(this._header);

        this._body = new St.ScrollView({
            style_class: 'poketokenbar-scroll',
            // Never horizontal: the popup is a fixed width.
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            y_expand: true,
        });
        this._bodyBox = verticalBox({x_expand: true});
        this._body.set_child(this._bodyBox);
        for (const section of Object.values(this._sections)) {
            this._bodyBox.add_child(section);
            section.visible = false;
        }
        this._sections.home.visible = true;
        content.add_child(this._body);

        this._footer = row([], 'poketokenbar-footer');
        content.add_child(this._footer);

        item.add_child(content);
        this.menu.addMenuItem(item);

        // Animation is the compositor's cost, and nobody is watching a closed
        // popup — but the panel sprite keeps running, since that one is visible.
        this.menu.connect('open-state-changed', (_menu, open) => {
            if (!open) {
                this._settingsOpen = false;
                for (const section of Object.values(this._sections))
                    section.release();
            }
            this._showCurrent();
            if (open)
                this._render();
        });

        this._readerHandler = reader.connect('changed', () => this._render());
        this._render();
    }

    destroy() {
        if (this._readerHandler) {
            this._reader.disconnect(this._readerHandler);
            this._readerHandler = 0;
        }
        // Closed before it is destroyed. An open menu holds a keyboard and
        // pointer grab; tearing the actor out from under it — which is what
        // an upgrade or a disable does — leaves the grab behind, and the
        // desktop stops answering clicks until something else takes it.
        if (this.menu.isOpen)
            this.menu.close(false);
        for (const section of Object.values(this._sections))
            section.release();
        super.destroy();
    }

    /** The page on screen: the settings page while it is open, else the tab. */
    _pageName() {
        return this._settingsOpen ? 'settings' : this._currentTab;
    }

    _showCurrent() {
        const current = this._pageName();
        for (const [name, section] of Object.entries(this._sections)) {
            const visible = this.menu.isOpen && name === current;
            // A page that just went away keeps animating otherwise: its sprites
            // are still in the tree, still on their own timers.
            if (section.visible && !visible)
                section.release();
            section.visible = visible;
        }
    }

    _selectTab(name) {
        this._currentTab = name;
        this._settingsOpen = false;
        this._showCurrent();
        this._body.vadjustment.value = 0;
        this._render();
    }

    _setSettingsOpen(open) {
        this._settingsOpen = open;
        this._showCurrent();
        this._body.vadjustment.value = 0;
        this._render();
    }

    /** The segmented tab bar, or the settings page's back header. */
    _renderHeader() {
        const t = key => this._reader.text(key);
        this._header.destroy_all_children();
        if (this._settingsOpen) {
            const back = button(`‹ ${t('detail_back')}`, () => this._setSettingsOpen(false),
                'poketokenbar-link');
            const title = label(t('settings'), 'poketokenbar-pagetitle');
            title.x_expand = true;
            title.x_align = Clutter.ActorAlign.CENTER;
            // An invisible twin of the back button keeps the title centred.
            const balance = button(`‹ ${t('detail_back')}`, () => {}, 'poketokenbar-link');
            balance.opacity = 0;
            balance.reactive = false;
            const bar = row([back, title, balance], 'poketokenbar-pageheader');
            bar.x_expand = true;
            this._header.add_child(bar);
            return;
        }
        this._header.add_child(segmented(
            TABS.map(name => ({label: t(name), value: name})),
            this._currentTab, name => this._selectTab(name)));
    }

    /** Upstream's footer: refresh and freshness on Home, settings on the right. */
    _renderFooter(state) {
        const t = key => this._reader.text(key);
        this._footer.destroy_all_children();
        this._footer.visible = !this._settingsOpen;
        if (this._settingsOpen)
            return;
        if (this._currentTab === 'home') {
            this._footer.add_child(iconButton('view-refresh-symbolic', () => Commands.refresh()));
            this._footer.add_child(label(this._freshness(state), 'poketokenbar-footer-text'));
        }
        this._footer.add_child(spacer());
        // Turning the desktop pet off is a right-click on the pet itself, so
        // turning it back on needs somewhere that is always reachable — the
        // settings page is two taps away and the pet is not there to click
        // (upstream 3272509).
        const petOn = Boolean(state?.config?.floating_pet_enabled);
        this._footer.add_child(iconButton(
            petOn ? 'view-reveal-symbolic' : 'view-conceal-symbolic',
            () => Config.set('floating_pet_enabled', !petOn)));
        this._footer.add_child(iconButton('emblem-system-symbolic', () => this._setSettingsOpen(true)));
    }

    /** "Updated 3 min ago", or what is wrong instead. */
    _freshness(state) {
        const t = key => this._reader.text(key);
        if (this._reader.error)
            return this._reader.error;
        if (this._reader.isStale())
            return t('stale_warning');
        const errors = state?.errors ?? [];
        if (errors.length > 0)
            return `⚠ ${errors.join(', ')}`;
        if (state?.scanning)
            return t('scanning');
        const age = this._reader.ageSeconds();
        return age === null ? '' : `${t('updated')} ${ago(age, t)}`;
    }

    /** The refresh / export / import row, plus the undo once one is possible. */
    _renderActions(state) {
        const t = key => this._reader.text(key);
        const transfer = state?.transfer ?? {};
        this._actions.destroy_all_children();
        this._actions.add_child(button('↻', () => Commands.refresh()));
        this._actions.add_child(new St.Widget({x_expand: true}));
        // The daemon has handled these all along; without a control they were
        // reachable only from poketokenctl, which is not where anyone would
        // look for "move my Pokedex to another machine".
        this._actions.add_child(button(t('export_save'), () => {
            Commands.exportSave(this._savePath(state));
            this._dismissTransferPrompt();
        }));
        // Undoing overwrites the save as thoroughly as importing does, so it
        // goes through the same prompt rather than acting on the first click.
        if (transfer.can_undo)
            this._actions.add_child(button(t('undo_import'), () => this._ask('undo')));
        this._actions.add_child(button(t('import_save'), () => this._askImport(state)));
        this._renderTransferPrompt(state);
    }

    /** Import asks before it overwrites, instead of reporting afterwards.
     *
     * It used to fire on the single click, replacing the save with whatever
     * file happened to be sitting at the export path — usually an older export,
     * so the button read as "throw away everything since my last backup". The
     * click now only opens this.
     */
    _askImport(state) {
        const transfer = state?.transfer ?? {};
        if (!transfer.exists) {
            this._notice(this._reader.text('import_no_file')
                .replace('%1', this._savePath(state)));
        } else if (transfer.error) {
            this._notice(this._reader.text('import_unreadable'));
        } else {
            this._ask('import');
        }
    }

    _ask(what) {
        this._pending = what;
        this._transferNotice = '';
        this._renderTransferPrompt(this._reader.state);
    }

    _notice(message) {
        this._pending = '';
        this._transferNotice = message;
        this._renderTransferPrompt(this._reader.state);
    }

    _dismissTransferPrompt() {
        this._pending = '';
        this._transferNotice = '';
        if (this._transferPrompt)
            this._renderTransferPrompt(this._reader.state);
    }

    _renderTransferPrompt(state) {
        const t = key => this._reader.text(key);
        const transfer = state?.transfer ?? {};
        this._transferPrompt.destroy_all_children();
        this._transferPrompt.visible = this._pending !== '' || this._transferNotice !== '';
        if (!this._transferPrompt.visible)
            return;

        if (this._transferNotice !== '') {
            this._transferPrompt.add_child(
                paragraph(this._transferNotice, 'poketokenbar-confirm-detail'));
            this._transferPrompt.add_child(row([
                new St.Widget({x_expand: true}),
                button(t('cancel'), () => this._dismissTransferPrompt()),
            ]));
            return;
        }

        const undoing = this._pending === 'undo';
        this._transferPrompt.add_child(label(
            t(undoing ? 'undo_confirm' : 'import_confirm'), 'poketokenbar-confirm-title'));
        // What is in the incoming save, and what it would replace — the two
        // halves of the decision, both already formatted by the daemon.
        this._transferPrompt.add_child(paragraph(
            t(undoing ? 'undo_file_detail' : 'import_file_detail')
                .replace('%1', undoing ? transfer.undo_taken_text : transfer.exported_text)
                .replace('%2', String(
                    (undoing ? transfer.undo_dex_count : transfer.dex_count) ?? 0))
                .replace('%3', undoing ? transfer.undo_used_text : transfer.used_text),
            'poketokenbar-confirm-detail'));
        this._transferPrompt.add_child(paragraph(
            t('import_current_detail')
                .replace('%1', String(transfer.current_dex_count ?? 0))
                .replace('%2', transfer.current_used_text),
            'poketokenbar-confirm-detail'));
        if (undoing ? transfer.undo_goes_backwards : transfer.goes_backwards) {
            this._transferPrompt.add_child(paragraph(
                t('import_goes_backwards'), 'poketokenbar-confirm-warning'));
        }
        this._transferPrompt.add_child(row([
            new St.Widget({x_expand: true}),
            button(t(undoing ? 'restore' : 'replace'), () => {
                if (undoing)
                    Commands.undoImport();
                else
                    Commands.importSave(this._savePath(state));
                this._dismissTransferPrompt();
            }, 'poketokenbar-button poketokenbar-danger'),
            button(t('cancel'), () => this._dismissTransferPrompt()),
        ]));
    }

    /** Paint everything from the latest snapshot. */
    _render() {
        const state = this._reader.state;
        this._renderPanel(state);
        // Only the visible page, and only while the popup is actually open. A
        // rebuild destroys the page's children and decodes every sprite in it
        // again, and doing that behind a closed menu is load nobody can see.
        if (this.menu.isOpen) {
            this._renderHeader();
            this._sections[this._pageName()]?.update(state);
            this._renderFooter(state);
        }
    }

    _renderPanel(state) {
        const panel = state?.panel;
        // The sprite is decoration; the percentages are the point. Keep one
        // from taking the other with it.
        try {
            this._sprite.setQuality(effectiveQuality(
                state?.config?.animation_quality ?? DEFAULT_QUALITY, isPowerSaver()));
            this._sprite.setPath(panel?.sprite_path || null);
        } catch (error) {
            logError(error, 'PokeTokenBar: panel sprite');
        }
        const companion = state?.companion;

        // How close the egg is to hatching, beside the egg itself. Only while
        // the panel is actually showing the egg: under a pinned species it
        // would be a number belonging to nothing on screen.
        //
        // The daemon's label carries an egg glyph of its own, which is the
        // fallback for the run where the sprite could not be fetched. With the
        // sprite there it would be a second egg, so the percentage goes alone.
        const isEgg = companion?.stage === 'egg' && !companion?.representative_species_id;
        let eggText = '';
        if (isEgg) {
            eggText = panel?.sprite_path
                ? `${Math.round((companion.egg_progress ?? 0) * 100)}%`
                : (companion.label ?? '');
        }
        this._eggLabel.text = eggText;
        this._eggLabel.visible = eggText !== '';

        this._limitBox.destroy_all_children();
        const windows = panel?.limit_windows ?? [];
        // A different row shape from limits.session: the panel ships text and
        // a level already computed against the user's own thresholds, while the
        // popup gets the raw utilisation. Same idea, not the same fields.
        windows.forEach((panelWindow, index) => {
            if (index > 0)
                this._limitBox.add_child(label('|', 'poketokenbar-panel-sep'));
            // The popup gauge's tier, so the panel number and the bar behind it
            // agree (upstream b32717f). `level` is the fallback for a payload
            // written before the tier existed.
            const tint = TIER_TINT[panelWindow.tier];
            this._limitBox.add_child(label(panelWindow.text,
                `poketokenbar-panel-text ${tint ? `poketokenbar-text-${tint}` : levelClass(panelWindow.level)}`));
        });

        this._tokensLabel.text = panel?.tokens_text ?? '';
        this._tokensLabel.visible = this._tokensLabel.text !== '';
        this._costLabel.text = panel?.cost_text ?? '';
        this._costLabel.visible = this._costLabel.text !== '';

        // Before the first successful read there is nothing at all to show, and
        // an empty panel button is invisible and unclickable.
        const empty = !panel?.sprite_path && eggText === '' && windows.length === 0 &&
            this._tokensLabel.text === '' && this._costLabel.text === '';
        this._eggLabel.visible = this._eggLabel.visible || empty;
        if (empty)
            this._eggLabel.text = '…';
    }

    /** Pause every sprite in the extension — used while the session is locked. */
    setPaused(paused) {
        this._sprite.setPaused(paused);
    }
});
