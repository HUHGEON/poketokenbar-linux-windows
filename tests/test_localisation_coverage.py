"""Nothing user-visible escapes the catalogue.

Setting the language to Korean left parts of the app in English more than once,
and each time it was found by looking rather than by a test: the settings page,
then the tray menu, then the shop and the bag, then every Pokemon's nature.
The pattern is always the same — a string that lives somewhere other than
`l10n`, so translating the app translates everything around it.

These tests look for that shape directly instead of for the individual strings.
"""

import json
import re
from pathlib import Path

import pytest

from poketokenbar import balance, l10n
from poketokenbar.balance import Rarity

ROOT = Path(__file__).resolve().parent.parent
QT_UI = ROOT / "poketokenbar" / "ui"


# MARK: the catalogue itself


@pytest.mark.parametrize("language", l10n.LANGUAGES)
def test_every_language_has_every_string(language):
    catalogue = l10n.catalogue(language)
    assert set(catalogue) == set(l10n.STRINGS)
    blank = [key for key, value in catalogue.items() if not value.strip()]
    assert not blank, f"{language} has empty strings: {blank}"


@pytest.mark.parametrize("language", l10n.LANGUAGES)
def test_every_nature_is_named(language):
    """25 of them, and they used not to be in the catalogue at all."""
    catalogue = l10n.catalogue(language)
    names = []
    for nature in balance.NATURES:
        key = f"nature_{nature}"
        assert key in catalogue, f"{key} is missing"
        names.append(catalogue[key])
    assert len(set(names)) == len(names), f"{language} reuses a nature name"


@pytest.mark.parametrize("language", l10n.LANGUAGES)
def test_every_shop_and_bag_string_is_named(language):
    """They were English-only tables in balance.py, which is why the shop
    stayed in English however the language was set."""
    catalogue = l10n.catalogue(language)
    for keys in balance.ITEM_STRINGS.values():
        for key in keys:
            assert key in catalogue, f"{key} is missing"
    for key in balance.EGG_STRINGS.values():
        assert key in catalogue, f"{key} is missing"
    for key in ("egg_desc_fresh", "egg_desc_guaranteed", "egg_guarantee"):
        assert key in catalogue


@pytest.mark.parametrize("language", l10n.LANGUAGES)
def test_every_rarity_is_named(language):
    catalogue = l10n.catalogue(language)
    for rarity in Rarity:
        assert catalogue.get(str(rarity), "").strip()


def test_placeholders_survive_translation():
    """A dropped %1 is a sentence with a hole where the number should be."""
    for key, values in l10n.STRINGS.items():
        english = values[0]
        expected = set(re.findall(r"%\d", english))
        for index, language in enumerate(l10n.LANGUAGES):
            assert set(re.findall(r"%\d", values[index])) == expected, (
                f"{key} in {language} does not carry {sorted(expected)}")


# MARK: the front ends


def _payload_strings(payload, path="", out=None):
    out = [] if out is None else out
    if isinstance(payload, dict):
        for key, value in payload.items():
            _payload_strings(value, f"{path}.{key}", out)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _payload_strings(value, f"{path}[{index}]", out)
    elif isinstance(payload, str):
        out.append((path, payload))
    return out


def test_no_display_text_in_the_payload_is_hardcoded_english():
    """The fields a front end prints verbatim, swept in one go.

    Identifier fields (`rarity`, `nature`, `key`) are deliberately raw — they
    are catalogue keys the front end resolves — so only the prepared text is
    checked here.
    """
    from poketokenbar.companion import CompanionState, MonState
    from poketokenbar.companion_store import CompanionStore

    store = CompanionStore(api=None, sprite_store=None)
    store.state = CompanionState(
        active=MonState(base_id=1, path_ids=[1, 2], planned_path_ids=[1, 2],
                        stage_index=0, rarity=Rarity.COMMON, total_forms=2,
                        nature="brave"),
        used_since_install=9_000_000_000,
        inventory={"rareCandy": 2, "shinyCharm": 1},
        language="ko",
    )
    text_fields = {"label", "description", "effect", "status_message"}
    latin = re.compile(r"[A-Za-z]{3,}")
    for row in store.shop_payload() + store.bag_payload():
        for field in text_fields & set(row):
            assert not latin.search(row[field] or ""), (
                f"{row['key']}.{field} is English in a Korean save: {row[field]!r}")


QT_TEXT_CALL = re.compile(r"""\blabel\(\s*(?:f?)["']([^"'{}]{4,})["']""")


def test_the_qt_panels_do_not_spell_out_english():
    """A literal in a panel is a label that never translates, which is exactly
    how the settings page ended up entirely in English."""
    offenders = []
    for path in sorted(QT_UI.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        # Comments and docstrings mention API names; only code is scanned.
        source = re.sub(r'"""..*?"""', "", source, flags=re.S)
        source = re.sub(r"^\s*#.*$", "", source, flags=re.M)
        for match in QT_TEXT_CALL.findall(source):
            if re.search(r"[A-Za-z]{4,}", match):
                offenders.append(f"{path.name}: {match!r}")
    assert not offenders, "hardcoded labels: " + "; ".join(offenders)


def test_the_qt_settings_labels_are_all_catalogue_keys():
    # The Qt front end is optional, and the job that runs without it still has
    # every other check in this file to run.
    pytest.importorskip("PySide6", reason="the Qt front end is optional")
    from poketokenbar.ui import panels

    keys = {label for _key, label in panels.SettingsPanel.TOGGLES}
    keys |= {label for _key, label, *_ in panels.SettingsPanel.SPINS}
    keys |= {label for _key, label, *_ in panels.SettingsPanel.CHOICES}
    keys |= set(panels.SettingsPanel.SUBTITLES.values())
    for _key, _label, _options, shown in panels.SettingsPanel.CHOICES:
        if shown:
            keys |= set(shown)
    unknown = keys - set(l10n.STRINGS)
    assert not unknown, f"labels that are not catalogue keys: {sorted(unknown)}"


def test_the_tray_menu_labels_are_catalogue_keys():
    """A menu is built once and never rebuilt, so an English literal there
    survives every language change."""
    source = (QT_UI / "app.py").read_text(encoding="utf-8")
    for key in re.findall(r'self\._menu_actions\["(\w+)"\]', source):
        assert key in l10n.STRINGS, f"tray menu uses {key!r}, which is not a string"
    assert len(re.findall(r'self\._menu_actions\["(\w+)"\]', source)) >= 5


def test_the_language_names_are_written_in_their_own_language():
    """A dropdown of two-letter codes is not something to recognise, and that
    is what it showed."""
    assert set(l10n.LANGUAGE_NAMES) == set(l10n.LANGUAGES)
    assert l10n.LANGUAGE_NAMES["ko"] == "한국어"
    assert all(name.strip() for name in l10n.LANGUAGE_NAMES.values())


def test_both_front_ends_resolve_natures():
    """The same payload field, so one of them printing it raw is a bug in
    exactly one place. It arrives as an id — "brave" — and every other label
    beside it is translated."""
    sections = (ROOT / "gnome-extension" / "poketokenbar@huhgeon.github.io"
                / "lib" / "sections.js").read_text(encoding="utf-8")
    assert "nature_" in sections, "the extension prints the id"
    panels = (QT_UI / "panels.py").read_text(encoding="utf-8")
    assert "nature_" in panels, "the Qt panels print the id"


@pytest.mark.parametrize("language", l10n.LANGUAGES)
def test_no_two_settings_share_a_label(language):
    """A screen with the same words twice gives no way to tell which control
    you are about to change. `setting_limit_display` and
    `setting_limit_percent` were both "한도 표시 방식" — one is upstream's
    used-versus-remaining, the other is this port's which-windows-to-show."""
    # The Qt front end is optional, and the job that runs without it still has
    # every other check in this file to run.
    pytest.importorskip("PySide6", reason="the Qt front end is optional")
    from poketokenbar.ui import panels

    catalogue = l10n.catalogue(language)
    keys = [label for _key, label in panels.SettingsPanel.TOGGLES]
    keys += [label for _key, label, *_ in panels.SettingsPanel.SPINS]
    keys += [label for _key, label, *_ in panels.SettingsPanel.CHOICES]
    labels = [catalogue[key] for key in keys]
    duplicated = {text for text in labels if labels.count(text) > 1}
    assert not duplicated, f"{language}: two settings share {sorted(duplicated)}"
