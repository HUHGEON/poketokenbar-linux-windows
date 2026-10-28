/* languages.js — the UI languages the daemon can resolve strings for.
 *
 * Kept in step with poketokenbar/l10n.py's LANGUAGES by a test rather than by
 * memory: a code listed here that the daemon does not know would silently fall
 * back to English, with the settings row still showing it as selected.
 */

export const LANGUAGES = ['en', 'ko', 'ja', 'es', 'fr', 'pt', 'de', 'ru'];
