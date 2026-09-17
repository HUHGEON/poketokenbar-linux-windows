/* resetclock.js — the wall-clock time a limit resets at (upstream f2fe5ac).
 *
 * "in 2d 9h" alone does not say when a weekly limit is back, so the countdown
 * gets the time as well: just "(14:30)" when the reset is today or within six
 * hours, and the weekday and day too when it is further off. Always 24-hour.
 *
 * Pure: no gi:// imports, so node runs it in tests. The words come from the
 * daemon's catalogue, which is why GNOME and the Qt tray write it the same way.
 * Mirrors reset_clock in poketokenbar/ui/panels.py.
 */

export const NEARBY_SECONDS = 6 * 3600;
export const WEEKDAY_KEYS = [
    'weekday_sun', 'weekday_mon', 'weekday_tue', 'weekday_wed',
    'weekday_thu', 'weekday_fri', 'weekday_sat',
];

const pad = value => String(value).padStart(2, '0');

/**
 * " (14:30)" or " (Thu 17, 09:00)" for an ISO instant, in local time; ''
 * when there is nothing to say. `nowMs` is injected so tests can pin it.
 */
export function resetClock(iso, t, nowMs = Date.now()) {
    if (!iso)
        return '';
    const reset = new Date(iso);
    const at = reset.getTime();
    if (Number.isNaN(at) || at <= nowMs)
        return '';
    const now = new Date(nowMs);
    const time = `${pad(reset.getHours())}:${pad(reset.getMinutes())}`;
    const sameDay = reset.getFullYear() === now.getFullYear() &&
        reset.getMonth() === now.getMonth() && reset.getDate() === now.getDate();
    if (sameDay || (at - nowMs) / 1000 <= NEARBY_SECONDS)
        return ` (${time})`;
    const far = t('reset_clock_far')
        .replace('%1', t(WEEKDAY_KEYS[reset.getDay()]))
        .replace('%2', String(reset.getDate()))
        .replace('%3', time);
    return ` (${far})`;
}
