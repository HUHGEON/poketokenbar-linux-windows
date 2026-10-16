/* The classic type-chart colours, keyed on PokeAPI's own type names.
 *
 * The names shown in the popup are translated, so the colour cannot be keyed
 * on them — the daemon sends the API's name alongside (upstream 46d5d91).
 *
 * No gi:// imports here, so the table is testable under plain node.
 */

export const TYPE_COLORS = {
    normal: '#aaaa99', fire: '#ff4422', water: '#3399ff', electric: '#ffcc33',
    grass: '#77cc55', ice: '#66ccff', fighting: '#bb5544', poison: '#aa5599',
    ground: '#ddbb55', flying: '#8899ff', psychic: '#ff5599', bug: '#aabb22',
    rock: '#bbaa66', ghost: '#6666bb', dragon: '#7766ee', dark: '#775544',
    steel: '#aaaabb', fairy: '#ee99ee',
};

/** That type's colour, or null for one this does not know. */
export function typeColor(apiName) {
    return TYPE_COLORS[String(apiName ?? '').toLowerCase()] ?? null;
}
