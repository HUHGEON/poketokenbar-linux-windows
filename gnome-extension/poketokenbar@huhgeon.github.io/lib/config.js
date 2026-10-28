/* config.js — writing the daemon's settings.
 *
 * Reading is not done here: the daemon ships its live config inside state.json,
 * so the UI renders from the same values the poll loop is using and the two
 * cannot drift. This module only writes, mirroring poketokenbar/config.py, and
 * then asks the daemon to reload.
 *
 * The file is shared with a running daemon, so it is written to a temp name and
 * renamed into place — the same rule the daemon itself follows.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as Commands from './commands.js';

export function configPath() {
    const base = GLib.getenv('XDG_CONFIG_HOME') ||
        GLib.build_filenamev([GLib.get_home_dir(), '.config']);
    return GLib.build_filenamev([base, 'poketokenbar', 'config.json']);
}

function readAll() {
    try {
        const [ok, bytes] = Gio.File.new_for_path(configPath()).load_contents(null);
        if (!ok)
            return {};
        const parsed = JSON.parse(new TextDecoder().decode(bytes));
        return typeof parsed === 'object' && parsed !== null ? parsed : {};
    } catch (_e) {
        // A missing or unreadable file means "all defaults", which is exactly
        // what an empty object produces once the daemon merges it.
        return {};
    }
}

function writeAll(values) {
    const path = configPath();
    const file = Gio.File.new_for_path(path);
    try {
        file.get_parent().make_directory_with_parents(null);
    } catch (e) {
        if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.EXISTS))
            return false;
    }
    const temp = Gio.File.new_for_path(`${path}.tmp`);
    try {
        const payload = `${JSON.stringify(values, null, 2)}\n`;
        temp.replace_contents(
            new TextEncoder().encode(payload), null, false,
            Gio.FileCreateFlags.REPLACE_DESTINATION, null);
        temp.move(file, Gio.FileCopyFlags.OVERWRITE, null, null);
        return true;
    } catch (_e) {
        try {
            temp.delete(null);
        } catch (_ignored) {
            // Nothing useful to do about a leftover temp file.
        }
        return false;
    }
}

/**
 * Set one setting and tell the daemon to pick it up.
 *
 * Reads the file rather than the shipped snapshot before writing: another
 * writer (poketokenctl, or a second copy of the prefs window) may have changed
 * a different key since the last poll, and writing the snapshot back would undo
 * it.
 */
export function set(key, value) {
    const values = readAll();
    values[key] = value;
    if (key === 'warn_threshold' && value >= (values.crit_threshold ?? 95))
        values.crit_threshold = Math.min(100, value + 5);
    if (key === 'crit_threshold' && value <= (values.warn_threshold ?? 80))
        values.warn_threshold = Math.max(50, value - 5);
    if (!writeAll(values))
        return false;
    Commands.reloadConfig();
    return true;
}

/** Set one provider's extra scan folders. Mirrors config.set_scan_roots. */
export function setScanRoots(providerId, raw) {
    if (!providerId || providerId.includes('/'))
        return false;
    const values = readAll();
    const roots = typeof values.custom_scan_roots === 'object' && values.custom_scan_roots
        ? {...values.custom_scan_roots}
        : {};
    if (raw && raw.trim())
        roots[providerId] = raw;
    else
        delete roots[providerId];  // clearing removes the key rather than storing ''
    values.custom_scan_roots = roots;
    if (!writeAll(values))
        return false;
    Commands.reloadConfig();
    return true;
}
