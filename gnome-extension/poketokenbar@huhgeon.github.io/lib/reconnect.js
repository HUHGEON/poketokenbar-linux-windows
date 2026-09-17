/* reconnect.js — when a network change should refresh (upstream b34673a).
 *
 * The daemon polls every couple of minutes, and after a suspend, a Wi-Fi
 * switch or an outage that means minutes of stale limits for no reason. A
 * transition from offline to online is worth a refresh at once.
 *
 * Pure, so node tests it; extension.js feeds it Gio.NetworkMonitor.
 */

export const COOLDOWN_MS = 5000;

/**
 * Upstream's shouldTriggerReconnect. The first report is not a transition,
 * only offline -> online is, and a flapping interface triggers at most once
 * per cooldown.
 */
export function shouldRefresh(previous, current, lastTriggeredMs, nowMs, cooldownMs = COOLDOWN_MS) {
    if (previous === null || previous === undefined)
        return false;
    if (previous || !current)
        return false;
    return lastTriggeredMs === null || lastTriggeredMs === undefined ||
        nowMs - lastTriggeredMs >= cooldownMs;
}

/** Remembers the last state and trigger, and calls `onReconnect` when due. */
export class ReconnectWatch {
    constructor(onReconnect, clock = () => Date.now()) {
        this._onReconnect = onReconnect;
        this._clock = clock;
        this._previous = null;
        this._lastTriggered = null;
    }

    report(available) {
        const now = this._clock();
        const due = shouldRefresh(this._previous, available, this._lastTriggered, now);
        this._previous = Boolean(available);
        if (due) {
            this._lastTriggered = now;
            this._onReconnect();
        }
        return due;
    }
}
