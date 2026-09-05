/* indicator.js — the panel button and the popup it opens.
 *
 * The panel shows the companion (or the pinned species) beside the limit
 * percentages, coloured by how close they are. The popup carries the detail,
 * in tabs that mirror the macOS app's.
 */

import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import St from 'gi://St';

import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';

import * as Commands from './commands.js';
import {DEFAULT_QUALITY} from './framecap.js';
import {Sprite} from './sprite.js';
import {
    BagSection, CollectionSection, HomeSection, SettingsSection, ShopSection,
} from './sections.js';
import {ago, button, label, levelClass, paragraph, row, verticalBox} from './widgets.js';

// The popup is a fixed width so the Pokedex grid never reflows mid-browse.
const POPUP_WIDTH = 380;

export const Indicator = GObject.registerClass(
class Indicator extends PanelMenu.Button {
    _init(reader, settings) {
        super._init(0.5, 'PokeTokenBar', false);
        this._reader = reader;
        this._settings = settings;

        // --- panel ----------------------------------------------------------
        this._panelBox = new St.BoxLayout({style_class: 'poketokenbar-panel'});
        this._sprite = new Sprite({size: 18});
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
        this._currentTab = 'home';

        const item = new PopupMenu.PopupBaseMenuItem({
            reactive: false, can_focus: false, style_class: 'poketokenbar-popup',
        });
        const content = verticalBox({
            style_class: 'poketokenbar-content', x_expand: true,
        });
        content.set_width(POPUP_WIDTH);

        this._tabBar = row([], 'poketokenbar-tabs');
        content.add_child(this._tabBar);

        this._body = new St.ScrollView({
            style_class: 'poketokenbar-scroll',
            // Never horizontal: the popup is a fixed width, so a sideways
            // scrollbar would only ever mean something is laid out wrong.
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            y_expand: true,
        });
        this._bodyBox = verticalBox({x_expand: true});
        this._body.set_child(this._bodyBox);
        content.add_child(this._body);

        this._footer = label('', 'poketokenbar-footer');
        content.add_child(this._footer);
        // Both rebuilt on every render: the labels come from the daemon's
        // catalogue, which is empty until the first snapshot arrives, and the
        // buttons offered depend on what that snapshot says is on disk.
        this._actions = row([], 'poketokenbar-actions');
        content.add_child(this._actions);
        this._transferPrompt = verticalBox({
            style_class: 'poketokenbar-confirm', x_expand: true,
        });
        this._transferPrompt.visible = false;
        content.add_child(this._transferPrompt);
        // Which destructive action is waiting on an answer: '', 'import' or
        // 'undo'. Cleared whenever the popup closes, so a prompt left open
        // never fires against a snapshot from an hour ago.
        this._pending = '';
        this._transferNotice = '';

        item.add_child(content);
        this.menu.addMenuItem(item);

        // Animation is the compositor's cost, and nobody is watching a closed
        // popup — but the panel sprite keeps running, since that one is visible.
        this.menu.connect('open-state-changed', (_menu, open) => {
            for (const [name, section] of Object.entries(this._sections)) {
                section.visible = open && name === this._currentTab;
                if (!open)
                    section.release();
            }
            if (!open)
                this._dismissTransferPrompt();
            if (open)
                this._render();
        });

        this._buildTabs();
        this._readerHandler = reader.connect('changed', () => this._render());
        this._render();
    }

    destroy() {
        if (this._readerHandler) {
            this._reader.disconnect(this._readerHandler);
            this._readerHandler = 0;
        }
        super.destroy();
    }

    _buildTabs() {
        this._tabBar.destroy_all_children();
        this._bodyBox.destroy_all_children();
        for (const [name, key] of [
            ['home', 'home'], ['shop', 'shop'], ['bag', 'bag'],
            ['collection', 'collection'], ['settings', 'refresh'],
        ]) {
            const tab = button(this._reader.text(key), () => this._selectTab(name),
                'poketokenbar-tab');
            this._tabBar.add_child(tab);
            this._bodyBox.add_child(this._sections[name]);
            this._sections[name].visible = name === this._currentTab;
        }
    }

    _selectTab(name) {
        this._currentTab = name;
        for (const [key, section] of Object.entries(this._sections)) {
            section.visible = key === name;
            // The tab that just went away keeps animating otherwise: its
            // sprites are still in the tree, still on their own timers.
            if (key !== name)
                section.release();
        }
        this._render();
    }

    /** Where a save is written to and read from.
     *
     * A fixed, predictable path rather than a file chooser: an extension has no
     * portal-backed dialog available to it, and inventing one would be more
     * surface than the feature is worth. The daemon reports which path that is,
     * because it is the daemon that has to describe the file before the popup
     * offers to overwrite a save with it — two copies of the constant is how
     * the popup ends up describing one file and importing another. The literal
     * survives only as the fallback for the first render, before any snapshot
     * has arrived.
     */
    _savePath(state) {
        return state?.transfer?.path || GLib.build_filenamev([
            GLib.get_home_dir(), 'poketokenbar-save.json',
        ]);
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
        // Only the visible tab, and only while the popup is actually open. A
        // rebuild destroys the section's children and decodes every sprite in
        // it again — the Pokedex grid is two dozen GIFs — and doing that every
        // two seconds behind a closed menu is compositor load nobody can see.
        // Opening the menu renders, so nothing is missed by skipping this.
        if (this.menu.isOpen) {
            this._sections[this._currentTab]?.update(state);
            // Same reason as the sections: nothing below the panel is visible
            // with the menu closed, and these labels come from a catalogue
            // that changes only when the language does.
            this._renderActions(state);
        }
        this._renderFooter(state);
    }

    _renderPanel(state) {
        const panel = state?.panel;
        // The sprite is decoration; the percentages are the point. Keep one
        // from taking the other with it.
        try {
            this._sprite.setQuality(state?.config?.animation_quality ?? DEFAULT_QUALITY);
            this._sprite.setPath(panel?.sprite_path || null);
        } catch (error) {
            logError(error, 'PokeTokenBar: panel sprite');
        }
        const companion = state?.companion;

        // The egg has no sprite of its own, so its percentage stands in —
        // leaving the slot blank until the first hatch reads as broken.
        const eggText = !panel?.sprite_path && companion?.label ? companion.label : '';
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
            this._limitBox.add_child(label(
                panelWindow.text, `poketokenbar-panel-text ${levelClass(panelWindow.level)}`));
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

    _renderFooter(state) {
        if (this._reader.error) {
            this._footer.text = this._reader.error;
            return;
        }
        if (this._reader.isStale()) {
            this._footer.text = this._reader.text('stale_warning');
            return;
        }
        const errors = state?.errors ?? [];
        if (errors.length > 0) {
            this._footer.text = errors.join(', ');
            return;
        }
        // Freshness, so a working daemon looks different from a stopped one
        // before the ten-minute staleness threshold is anywhere near.
        if (state?.scanning) {
            this._footer.text = this._reader.text('scanning');
            return;
        }
        const age = this._reader.ageSeconds();
        this._footer.text = age === null
            ? ''
            : `${this._reader.text('updated')} ${ago(age, key => this._reader.text(key))}`;
    }

    /** Pause every sprite in the extension — used while the session is locked. */
    setPaused(paused) {
        this._sprite.setPaused(paused);
    }
});
