/* PokeTokenBar for GNOME — the loader.
 *
 * GNOME Shell imports extension.js once per session and caches every module it
 * reaches by URL, so on Wayland new code on disk used to take a log out to
 * appear: disabling and enabling the extension ran the cached modules again.
 *
 * This file is kept small and stable for that reason. Each enable() reads which
 * UI directory is current from the `current` file beside it and imports
 * main.js from there. The installer puts every release in a directory of its
 * own (lib-<stamp>) and then disables and enables the extension, so the next
 * enable imports modules at URLs the session has never seen, and the new popup
 * appears without a new session. Without a `current` file, as when run
 * straight from a checkout, the UI is the plain lib directory.
 *
 * A change to this file itself still needs a new session, like any extension.
 */

import GLib from 'gi://GLib';

import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

// A UI directory name: "lib", or "lib-" and a release stamp. Anything else in
// `current` is ignored, so the file can only ever pick a directory beside it.
const UI_DIRECTORY = /^lib(-[._0-9A-Za-z]+)?$/;

export default class PokeTokenBarExtension extends Extension {
    enable() {
        // Counts enables and disables, so an import that finishes after the
        // extension was disabled (or enabled again) is dropped.
        const generation = this._generation = (this._generation ?? 0) + 1;
        const main = GLib.build_filenamev([this.path, this._uiDirectory(), 'main.js']);
        import(GLib.filename_to_uri(main, null)).then(module => {
            if (generation !== this._generation)
                return;
            this._main = new module.PokeTokenBar(this, _);
            this._main.enable();
        }).catch(error => logError(error, 'PokeTokenBar: could not load its UI'));
    }

    disable() {
        this._generation = (this._generation ?? 0) + 1;
        this._main?.disable();
        this._main = null;
    }

    /** The UI directory the installer named, or "lib" without a valid one. */
    _uiDirectory() {
        try {
            const [, bytes] = GLib.file_get_contents(GLib.build_filenamev([this.path, 'current']));
            const name = new TextDecoder().decode(bytes).trim();
            const main = GLib.build_filenamev([this.path, name, 'main.js']);
            if (UI_DIRECTORY.test(name) && GLib.file_test(main, GLib.FileTest.EXISTS))
                return name;
        } catch (_error) {
            // No `current` file: running from a checkout.
        }
        return 'lib';
    }
}
