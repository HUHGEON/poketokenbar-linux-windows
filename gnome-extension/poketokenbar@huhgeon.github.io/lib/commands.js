/* commands.js — the extension's only way to talk to the daemon.
 *
 * A spool directory of one-shot JSON files, mirroring poketokenbar/commands.py.
 * Files rather than D-Bus: a queued command survives a daemon restart, neither
 * side needs an IPC library, and the same commands can be sent by hand with
 * poketokenctl while debugging.
 *
 * Written to a dot-prefixed temp name and renamed into place, because the
 * daemon globs `*.json` and would otherwise pick up a half-written file.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

let counter = 0;

export function spoolDir() {
    // Matches commands.spool_dir(): XDG_RUNTIME_DIR, else the temp directory.
    // Python falls back to /tmp; GLib's temp dir is /tmp on every system this
    // runs on, and asking GLib keeps the two agreeing if that ever changes.
    const base = GLib.getenv('XDG_RUNTIME_DIR') || GLib.get_tmp_dir();
    return GLib.build_filenamev([base, 'poketokenbar', 'commands']);
}

/**
 * Queue one command for the daemon.
 *
 * Returns true when the file landed. A false is worth surfacing: it means the
 * click did nothing, and silently swallowing that is what makes a UI feel
 * broken rather than busy.
 */
export function enqueue(name, args = {}) {
    const dir = spoolDir();
    try {
        Gio.File.new_for_path(dir).make_directory_with_parents(null);
    } catch (e) {
        if (!e.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.EXISTS))
            return false;
    }

    counter += 1;
    // Monotonic, zero-padded, unique per process — the daemon drains in name
    // order, so this is also the ordering guarantee.
    const stem = `${String(GLib.get_real_time() * 1000).padStart(20, '0')}-` +
        `${Gio.Application.get_default()?.application_id ?? 'shell'}-` +
        `${String(counter).padStart(4, '0')}`;
    const temp = Gio.File.new_for_path(GLib.build_filenamev([dir, `.${stem}.tmp`]));
    const final = Gio.File.new_for_path(GLib.build_filenamev([dir, `${stem}.json`]));

    try {
        const payload = JSON.stringify({name, args});
        temp.replace_contents(
            new TextEncoder().encode(payload), null, false,
            Gio.FileCreateFlags.REPLACE_DESTINATION, null);
        // Atomic: the daemon never reads a half-written command.
        temp.move(final, Gio.FileCopyFlags.OVERWRITE, null, null);
        return true;
    } catch (_e) {
        try {
            temp.delete(null);
        } catch (_ignored) {
            // Nothing useful to do; the leftover is a dotfile the daemon skips.
        }
        return false;
    }
}

export const refresh = () => enqueue('refresh', {});
export const reloadConfig = () => enqueue('reload_config', {});
// `count` buys or uses several at once: several candies in one go, and one
// purchase for a stack of them. The daemon clamps it either way.
export const buy = (key, count = 1) => enqueue('buy', {key, count});
export const use = (key, count = 1) => enqueue('use', {key, count});
// Open a species' Pokédex page, or close it with null. `retry` asks again for
// details that failed to load.
// `unownForm` names one of Unown's 28 letters; every other species ignores it.
export const inspect = (speciesId, retry = false, unownForm = null) =>
    enqueue('inspect', {
        species_id: speciesId === null ? 'none' : String(speciesId),
        retry,
        unown_form: unownForm ?? '',
    });
export const represent = (speciesId, unownForm = null) =>
    enqueue('represent', {
        species_id: speciesId === null ? 'none' : String(speciesId),
        unown_form: unownForm ?? '',
    });
export const exportSave = path => enqueue('export', {path});
export const importSave = path => enqueue('import', {path});
// The way back from an import that replaced the wrong save. No path: the
// daemon restores from the backup it took when it overwrote the file.
export const undoImport = () => enqueue('restore', {});
// Open the usage recap on a week, a month or a year, `offset` periods back
// (0 is the current one, negative is the past). A null scope closes it.
export const recap = (scope, offset = 0) =>
    enqueue('recap', {scope: scope === null ? 'none' : scope, offset});
// Fetch and apply the published update the daemon has already found.
export const update = () => enqueue('update', {});
// Local restore points: take one now, or put one back by its file name.
export const snapshot = () => enqueue('snapshot', {});
export const restoreSnapshot = id => enqueue('restore_snapshot', {id});
