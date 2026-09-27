/* Number formatting for the popup — the half of poketokenbar/format.py the
 * extension needs for values the daemon cannot preformat.
 *
 * Everything the daemon ships is already formatted; this is for numbers the
 * popup computes itself, such as the XP of a candy batch that follows a
 * quantity stepper. Kept out of widgets.js, which imports gi:// and so cannot
 * be loaded by tests/js/compact.test.mjs.
 */

/**
 * "12.3K" / "190.6M" / "1.24B", mirroring poketokenbar/format.py's compact().
 *
 * Only for numbers computed in the popup — a candy batch's XP follows the
 * quantity stepper, so the daemon cannot preformat it. Everything the daemon
 * does ship is already formatted, and must not be re-formatted here.
 */
export function compact(value) {
    const n = Math.round(value || 0);
    const magnitude = Math.abs(n);
    const sign = n < 0 ? '-' : '';
    const trim = (scaled, decimals) => String(Number(scaled.toFixed(decimals)));
    if (magnitude < 1_000)
        return String(n);
    if (magnitude < 1_000_000)
        return `${sign}${trim(magnitude / 1_000, 1)}K`;
    if (magnitude < 1_000_000_000)
        return `${sign}${trim(magnitude / 1_000_000, 1)}M`;
    return `${sign}${trim(magnitude / 1_000_000_000, 2)}B`;
}

/** Compact "12,345" style text for a token count the daemon did not preformat. */
export function grouped(value) {
    // The daemon preformats everything it ships, so this is only for numbers
    // computed here. JS toLocaleString on a large float renders 8.55336e+07 in
    // some locales, hence the explicit grouping.
    const n = Math.round(value || 0);
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}


