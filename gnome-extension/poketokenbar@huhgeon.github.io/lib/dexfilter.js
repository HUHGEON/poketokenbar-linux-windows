/**
 * Searching, sorting and filtering the Pokédex grid and the catch log.
 *
 * Pure functions over the rows the daemon ships, so the two lists cannot drift
 * apart and node can test the rules (tests/js/dexfilter.test.mjs). The daemon
 * ships each row's searchable text already folded — lowercase and stripped of
 * diacritics — and `fold` here puts the query through the same rule, so
 * "flabebe" finds Flabébé.
 */

/** Slowest to rarest, for the rarity sort. */
const RARITY_RANK = {common: 0, uncommon: 1, rare: 2, legendary: 3};

export function fold(text) {
    return String(text ?? '')
        .normalize('NFKD')
        // Combining marks only: \p{M} needs the unicode flag, which older
        // GJS regexes do not take.
        .replace(/[\u0300-\u036f]/g, '')
        // Recomposed, so a Hangul syllable is a syllable again rather than
        // loose jamo — the daemon folds the row text the same way.
        .normalize('NFC')
        .toLowerCase()
        .trim();
}

/** Rows whose searchable text contains the query. A blank query filters nothing. */
export function search(rows, query) {
    const needle = fold(query);
    if (needle === '')
        return rows;
    return rows.filter(dexEntry => String(dexEntry.search ?? '').includes(needle));
}

/** The Pokédex grid: rarity chip, shiny-only, search, then the chosen order. */
export function dexRows(rows, {rarity = null, shinyOnly = false, query = '', sort = 'number_asc'} = {}) {
    let out = rows ?? [];
    if (rarity)
        out = out.filter(dexEntry => dexEntry.rarity === rarity);
    if (shinyOnly)
        out = out.filter(dexEntry => dexEntry.is_shiny);
    out = search(out, query);
    return sortRows(out, sort);
}

/** The catch log: the same controls, plus its own date orders. */
export function logRows(rows, {rarity = null, shinyOnly = false, query = '', sort = 'date_desc'} = {}) {
    let out = rows ?? [];
    if (rarity)
        out = out.filter(catchRecord => catchRecord.rarity === rarity);
    if (shinyOnly)
        out = out.filter(catchRecord => catchRecord.is_shiny);
    out = search(out, query);
    return sortRows(out, sort);
}

function sortRows(rows, sort) {
    // A copy: the payload's own order is what "most recent" already means, and
    // sorting in place would scramble it for the next caller.
    const out = [...rows];
    const number = dexEntry => Number(dexEntry.species_id ?? 0);
    const name = dexEntry => String(dexEntry.name ?? '');
    switch (sort) {
    case 'number_asc':
        return out.sort((a, b) => number(a) - number(b));
    case 'number_desc':
        return out.sort((a, b) => number(b) - number(a));
    case 'name_asc':
        // Ties keep Pokédex order, so the list never shuffles between polls.
        return out.sort((a, b) => name(a).localeCompare(name(b)) || number(a) - number(b));
    case 'rarity_desc':
        return out.sort((first, second) =>
            (RARITY_RANK[second.rarity] ?? -1) - (RARITY_RANK[first.rarity] ?? -1)
            || number(first) - number(second));
    case 'date_desc':
        return out;   // the daemon already ships the log newest first
    case 'date_asc':
        return out.reverse();
    default:
        return out;
    }
}

/** The sort options each list offers, in the order the control cycles them. */
export const DEX_SORTS = ['number_asc', 'number_desc', 'name_asc', 'rarity_desc'];
export const LOG_SORTS = ['date_desc', 'date_asc', 'number_asc', 'name_asc', 'rarity_desc'];

/** The catalogue key naming one sort option. */
export function sortLabelKey(sort) {
    return `sort_${sort}`;
}
