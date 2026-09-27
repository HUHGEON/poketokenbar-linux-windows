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


def test_the_seven_languages_are_the_upstream_set():
    assert set(l10n.LANGUAGES) == {"en", "ko", "ja", "es", "fr", "pt", "de"}


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


def test_every_nature_has_a_distinct_name_in_every_language():
    from poketokenbar import balance

    assert set(l10n.NATURE_NAMES) == set(balance.NATURES)
    for index, language in enumerate(l10n.LANGUAGES):
        names = [row[index] for row in l10n.NATURE_NAMES.values()]
        assert all(name.strip() for name in names), language
        assert len(set(names)) == len(names), language


def test_a_nature_is_named_in_the_ui_language():
    assert l10n.nature_name("adamant", "ko") == "고집"
    assert l10n.nature_name("adamant", "en") == "Adamant"
    assert l10n.nature_name("adamant", "de") == "Hart"
    assert l10n.nature_name("not-a-nature", "ko") == "not-a-nature"
    assert l10n.nature_name(None, "ko") == ""


def test_pokeapi_names_resolve_case_insensitively_with_regional_codes():
    names = l10n.names_from_api([
        {"language": {"name": "ja-Hrkt"}, "name": "フシギダネ"},
        {"language": {"name": "pt-BR"}, "name": "Bulbassauro"},
        {"language": {"name": "en"}, "name": "Bulbasaur"},
    ])
    assert l10n.resolve_name(names, "ja") == "フシギダネ"
    assert l10n.resolve_name(names, "pt") == "Bulbassauro"
    assert l10n.resolve_name(names, "ko") == "Bulbasaur"
    assert l10n.resolve_name({}, "ko") is None


# --- Korean particles (upstream 746d838) ------------------------------------


@pytest.mark.parametrize("word,kind,expected", [
    # No coda: 가 / 를 / 로.
    ("피카츄", "s", "가"),
    ("피카츄", "o", "를"),
    ("피카츄", "d", "로"),
    # A coda: 이 / 을 / 으로.
    ("이상해꽃", "s", "이"),
    ("이상해꽃", "o", "을"),
    ("듀랄루돈", "d", "으로"),
    ("잉어킹", "d", "으로"),
    # ㄹ takes 로, not 으로.
    ("코일", "d", "로"),
    ("아라리", "d", "로"),
])
def test_the_particle_follows_the_last_syllable(word, kind, expected):
    assert l10n.korean_particle(word, kind) == expected


@pytest.mark.parametrize("word", ["", "#123", "[A]", "Pikachu", "ピカチュウ", "/home/u/save.json"])
def test_a_word_that_is_not_hangul_keeps_both_forms(word):
    """Better to write both than to write the wrong one: the coda of a dex
    number or a file path cannot be told."""
    assert l10n.korean_particle(word, "s") == "이(가)"
    assert l10n.korean_particle(word, "o") == "을(를)"
    assert l10n.korean_particle(word, "d") == "(으)로"


def test_korean_copy_agrees_with_the_name_it_follows():
    assert l10n.fill("notif_hatch_body", "ko", "피카츄") == "알에서 피카츄가 나왔어요!"
    assert l10n.fill("notif_hatch_body", "ko", "이상해꽃") == "알에서 이상해꽃이 나왔어요!"
    assert l10n.fill("notif_evolve_body", "ko", "듀랄루돈") == "듀랄루돈으로 진화했어요!"
    assert l10n.fill("notif_evolve_body", "ko", "리자몽") == "리자몽으로 진화했어요!"
    assert l10n.fill("notif_evolve_body", "ko", "#5") == "#5(으)로 진화했어요!"


def test_other_languages_substitute_exactly_as_before():
    for language in l10n.LANGUAGES:
        if language == "ko":
            continue
        assert l10n.fill("notif_hatch_body", language, "Pikachu") == (
            l10n.t("notif_hatch_body", language).replace("%1", "Pikachu"))


def test_no_korean_string_still_writes_both_forms_where_a_name_goes():
    """The marker is what makes the choice possible; a leftover "%1이(가)" is a
    string this port forgot to convert."""
    leftovers = [
        key for key, row in l10n.STRINGS.items()
        if "%1" in row[1] and any(both in row[1] for both in ("이(가)", "을(를)", "(으)로"))
    ]
    assert leftovers == []


def test_an_unfilled_marker_never_reaches_the_screen():
    """Every marker has to be resolved by fill(), not shipped raw: the JS
    catalogue renders what it is given."""
    for key, row in l10n.STRINGS.items():
        for language, text in zip(l10n.LANGUAGES, row):
            if "{s}" in text or "{o}" in text or "{d}" in text:
                assert "%1" in text, f"{key}/{language} marks a particle with nothing to fill"
                assert "{s}" not in l10n.fill(key, language, "피카츄")
