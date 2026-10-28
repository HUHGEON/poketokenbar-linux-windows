import pytest

from poketokenbar import l10n


def test_english_is_the_default():
    assert l10n.t("home") == "Home"


@pytest.mark.parametrize("lang,expected", [("ko", "홈"), ("ja", "ホーム"), ("es", "Inicio")])
def test_other_languages_resolve(lang, expected):
    assert l10n.t("home", lang) == expected


def test_unknown_language_falls_back_to_english():
    # "de" used to stand in for "unknown" here and is now a real language, so
    # this needs a code that will not become one.
    assert l10n.t("home", "xx") == "Home"
    assert l10n.t("home", "") == "Home"


def test_unknown_key_returns_the_key_not_blank():
    # A blank label hides the bug; the key makes it visible.
    assert l10n.t("no_such_key", "ko") == "no_such_key"


def test_catalogue_covers_every_string():
    assert set(l10n.catalogue("ja")) == set(l10n.STRINGS)


def test_every_string_is_a_non_empty_string():
    for key, row in l10n.STRINGS.items():
        assert all(isinstance(v, str) and v for v in row), key


def test_status_messages_exist_for_each_display_state():
    from poketokenbar.companion import STATUS_MESSAGE

    for kind in STATUS_MESSAGE:
        assert f"status_{kind.lower()}" in l10n.STRINGS or kind == "levelUp"


# MARK: language coverage


def test_every_row_covers_every_language():
    """Positional tuples: a short row is a silent IndexError waiting in the UI.

    This is the guard that makes the shape safe, and the reason `t` can fall
    back instead of raising.
    """
    short = {k: len(v) for k, v in l10n.STRINGS.items() if len(v) != len(l10n.LANGUAGES)}
    assert not short, f"rows missing translations: {short}"


def test_no_translation_is_left_blank():
    blank = [
        (key, l10n.LANGUAGES[i])
        for key, row in l10n.STRINGS.items()
        for i, value in enumerate(row)
        if not value.strip()
    ]
    assert not blank, f"blank translations: {blank}"


@pytest.mark.parametrize("language", l10n.LANGUAGES)
def test_catalogue_resolves_every_key_for_every_language(language):
    catalogue = l10n.catalogue(language)
    assert set(catalogue) == set(l10n.STRINGS)
    assert all(value for value in catalogue.values())


def test_the_eight_languages_are_the_upstream_set():
    assert set(l10n.LANGUAGES) == {"en", "ko", "ja", "es", "fr", "pt", "de", "ru"}


def test_pokemon_name_languages_track_the_ui_languages():
    """A UI language with no name code pins that user to English Pokemon names."""
    from poketokenbar import pokeapi

    codes = set(pokeapi.LANG_CODES)
    for language in l10n.LANGUAGES:
        assert language in codes, f"{language} has no PokeAPI name code"


def test_placeholder_strings_keep_their_placeholder():
    """%1 is substituted by the UI; a translation that drops it loses the time."""
    for language in l10n.LANGUAGES:
        assert "%1" in l10n.t("at_this_rate", language), language


def test_the_extension_language_list_matches_the_daemon():
    """A code the extension offers but the daemon cannot resolve falls back to
    English while the settings row still shows it selected."""
    import json
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parent.parent
        / "gnome-extension" / "poketokenbar@huhgeon.github.io" / "lib" / "languages.js"
    ).read_text(encoding="utf-8")
    listed = json.loads(re.search(r"\[(.*?)\]", source, re.S).group(0).replace("'", '"'))
    assert listed == list(l10n.LANGUAGES)
