/* How big a sprite is drawn inside its box.
 *
 * The panel's box is 18px tall and a sprite's canvas is whatever PokeAPI
 * drew: Swanna's spread wings are 137x69, Tynamo is 57x19. Fitting those
 * into a square let the width decide — Swanna came out 9px tall, a smudge
 * beside the text. The height is what should be filled, with the width free
 * to grow to a limit so one wide species cannot push the usage text across
 * the panel (upstream 481ad3a).
 *
 * No gi:// imports, so the arithmetic is testable under plain node.
 */

/**
 * The drawn size for a sprite of `width` x `height` pixels in a box `box`
 * tall, never wider than `maxWidth` (defaults to the box: a square fit).
 */
export function fitSize(width, height, box, maxWidth = box) {
    if (!(width > 0) || !(height > 0) || !(box > 0))
        return {width: box, height: box};
    const scale = Math.min(maxWidth / width, box / height);
    return {
        width: Math.max(1, Math.round(width * scale)),
        height: Math.max(1, Math.round(height * scale)),
    };
}
