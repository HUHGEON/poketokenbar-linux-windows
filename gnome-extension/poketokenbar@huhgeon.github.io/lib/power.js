/* power.js — whether the system is in power-saver mode.
 *
 * Read from power-profiles-daemon, which is what GNOME's own power menu uses.
 * On a machine without it the answer is simply "no", and animation follows
 * the setting as before.
 */

import Gio from 'gi://Gio';

const BUS_NAME = 'net.hadess.PowerProfiles';
const OBJECT_PATH = '/net/hadess/PowerProfiles';

let powerSaver = false;

/** Whether animation should be capped right now. */
export const isPowerSaver = () => powerSaver;

export class PowerSaverWatch {
    /** `onChange` runs whenever the mode flips, so sprites can be re-capped. */
    constructor(onChange) {
        this._onChange = onChange;
        this._proxy = null;
        this._handler = 0;
        this._cancellable = new Gio.Cancellable();
    }

    start() {
        Gio.DBusProxy.new_for_bus(
            Gio.BusType.SYSTEM, Gio.DBusProxyFlags.DO_NOT_AUTO_START, null,
            BUS_NAME, OBJECT_PATH, BUS_NAME, this._cancellable,
            (_source, result) => {
                try {
                    this._proxy = Gio.DBusProxy.new_for_bus_finish(result);
                } catch (_e) {
                    return; // no daemon, or disabled while connecting
                }
                this._handler = this._proxy.connect('g-properties-changed', () => this._read());
                this._read();
            });
    }

    stop() {
        this._cancellable.cancel();
        if (this._proxy && this._handler)
            this._proxy.disconnect(this._handler);
        this._proxy = null;
        this._handler = 0;
        powerSaver = false;
    }

    _read() {
        const profile = this._proxy?.get_cached_property('ActiveProfile')?.unpack();
        const next = profile === 'power-saver';
        if (next === powerSaver)
            return;
        powerSaver = next;
        this._onChange();
    }
}
