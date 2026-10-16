/* state.js — the daemon's state.json, watched and parsed.
 *
 * The daemon writes atomically (temp + rename), so a torn read is not supposed
 * to happen. It still can — a rename is atomic but our read is not scheduled
 * against it — so a parse failure keeps the last good snapshot rather than
 * blanking the panel, and only says so after several in a row.
 *
 * Watched with a file monitor and polled as a backstop. The monitor alone is
 * not enough: a rename over a watched path can deliver as DELETED + CREATED,
 * and some filesystems (and containers) deliver nothing at all.
 */

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';

// How stale the file may get before the UI says the daemon looks stopped.
// The daemon's own default refresh is 120s, so this is several missed polls
// rather than one slow one.
export const STALE_AFTER_SECONDS = 600;

// Consecutive unparseable reads before the error surfaces. One is a torn read
// racing a rename; a run of them is a real problem.
const PARSE_FAILURES_BEFORE_REPORTING = 3;

// The handful of strings the extension owns itself (everything the daemon can
// answer for comes through `state.strings`). Bound to real gettext in
// extension.js; the identity default keeps this module usable on its own.
let _ = s => s;

export function bindTranslations(gettext) {
    _ = gettext;
}

export function statePath() {
    const base = GLib.getenv('XDG_STATE_HOME') ||
        GLib.build_filenamev([GLib.get_home_dir(), '.local', 'state']);
    return GLib.build_filenamev([base, 'poketokenbar', 'state.json']);
}

// A replace is two monitor events, and a daemon answering a click writes
// again right after its poll did. Long enough to fold those together, short
// enough that a click still feels answered at once.
const COALESCE_MS = 120;

export const StateReader = GObject.registerClass({
    Signals: {'changed': {}},
}, class StateReader extends GObject.Object {
    _init(pollSeconds = 2) {
        super._init();
        this._path = statePath();
        this._file = Gio.File.new_for_path(this._path);
        this._pollSeconds = pollSeconds;
        this._monitor = null;
        this._monitorHandler = 0;
        this._timer = 0;
        this._coalesce = 0;
        this._parseFailures = 0;
        // Set by stop(). A file monitor can deliver an event that was already
        // queued when it was cancelled, and reading — let alone emitting — at
        // that point reaches listeners that have been torn down, or the
        // reader itself while it is being collected.
        this._stopped = false;

        /** Last successfully parsed payload, or null before the first read. */
        this.state = null;
        /** Human-readable reason the state is missing, or ''. */
        this.error = '';
    }

    start() {
        this._stopped = false;
        this.read();
        try {
            this._monitor = this._file.monitor_file(Gio.FileMonitorFlags.NONE, null);
            this._monitorHandler = this._monitor.connect('changed', () => this._readSoon());
        } catch (_e) {
            // No monitor available; the poll below still keeps things current.
            this._monitor = null;
        }
        this._timer = GLib.timeout_add_seconds(
            GLib.PRIORITY_DEFAULT, this._pollSeconds, () => {
                this.read();
                return GLib.SOURCE_CONTINUE;
            });
    }

    stop() {
        this._stopped = true;
        if (this._coalesce) {
            GLib.Source.remove(this._coalesce);
            this._coalesce = 0;
        }
        if (this._timer) {
            GLib.Source.remove(this._timer);
            this._timer = 0;
        }
        // Disconnected before the cancel, not after: cancelling does not
        // unqueue an event the monitor has already handed to the main loop.
        if (this._monitorHandler) {
            this._monitor?.disconnect(this._monitorHandler);
            this._monitorHandler = 0;
        }
        this._monitor?.cancel();
        this._monitor = null;
    }

    /**
     * Read once for a burst of writes.
     *
     * The daemon replaces this file on every poll and after every command, and
     * a replace is two monitor events. The payload is over a megabyte — a full
     * Pokédex, every string in the UI language — and parsing it happens on the
     * compositor's own main loop, where it is a visible stutter. One read for
     * everything that lands inside a frame or two costs nothing in freshness.
     */
    _readSoon() {
        if (this._stopped || this._coalesce)
            return;
        this._coalesce = GLib.timeout_add(GLib.PRIORITY_DEFAULT, COALESCE_MS, () => {
            this._coalesce = 0;
            this.read();
            return GLib.SOURCE_REMOVE;
        });
    }

    read() {
        if (this._stopped)
            return;
        let contents;
        try {
            const [ok, bytes] = this._file.load_contents(null);
            if (!ok)
                throw new Error('load_contents returned false');
            contents = new TextDecoder().decode(bytes);
        } catch (_e) {
            // Distinguish "not running yet" from "running but broken": the
            // first is the normal state right after install and must not read
            // as a fault.
            this.error = this.state
                ? _('Cannot read state file')
                : _('Waiting for poketokend…');
            this.emit('changed');
            return;
        }

        let parsed;
        try {
            parsed = JSON.parse(contents);
        } catch (_e) {
            this._parseFailures += 1;
            if (this._parseFailures >= PARSE_FAILURES_BEFORE_REPORTING)
                this.error = _('state.json is not valid JSON');
            // The previous snapshot stays on screen either way.
            this.emit('changed');
            return;
        }

        this._parseFailures = 0;
        this.state = parsed;
        this.error = '';
        this.emit('changed');
    }

    /** Seconds since the daemon last wrote, or null when it never has. */
    ageSeconds() {
        const updatedAt = this.state?.updated_at;
        if (!updatedAt)
            return null;
        return Math.max(0, Date.now() / 1000 - updatedAt);
    }

    isStale() {
        const age = this.ageSeconds();
        return age !== null && age > STALE_AFTER_SECONDS;
    }

    /** One localised string from the daemon's catalogue, or the key itself.
     *
     * The daemon resolves every string and ships it here, so the extension
     * holds no catalogue of its own and a language change lands on the next
     * poll without reloading anything.
     */
    text(key) {
        return this.state?.strings?.[key] ?? key;
    }
});
