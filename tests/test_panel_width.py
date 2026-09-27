"""Nothing in the popup may be wider than the popup.

The window is a fixed 400px, and every string in it is translated. A layout
sized against Korean has 40% more room than the same layout in French, so
"it fits" is a claim that has to be made once per language, not once.

This exists because it did not: the Pokedex grid was four columns wide in
Korean and four-and-a-bit in every other language, and Qt resolved that by
widening the scroll content until the fourth column sat outside the viewport.
On screen it looked like the last column had been cropped off the app.
"""

import pytest

pytest.importorskip("PySide6", reason="the Qt front end is optional")

import os  # noqa: E402

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QScrollArea  # noqa: E402

from poketokenbar import l10n  # noqa: E402
from poketokenbar.ui.app import WINDOW_SIZE, Window  # noqa: E402
from poketokenbar.ui.reader import StateReader  # noqa: E402

# The longest name in each language among the species the game can reach, and
# the widest cell decorations: a shiny marker on a three-digit number, and the
# "raising" badge, which is "EN ELEVAGE" in French and "키우는 중" in Korean.
LONGEST = {
    "en": ["Pidgeotto", "Seismitoad", "Beautifly", "Probopass"],
    "ko": ["피죤", "두빅굴", "뷰티플라이", "대코파스"],
    "ja": ["ピジョン", "ガマゲロゲ", "アゲハント", "ダイノーズ"],
    "de": ["Tauboga", "Barschuft", "Papinella", "Voluminas"],
    "fr": ["Roucoups", "Crapustule", "Charmillon", "Tarinorme"],
    "es": ["Pidgeotto", "Seismitoad", "Beautifly", "Probopass"],
    "pt": ["Pidgeotto", "Seismitoad", "Beautifly", "Probopass"],
}


def _payload(language: str, names: list[str]) -> dict:
    return {
        "schema_version": 1,
        "updated_at": 0,
        "scanning": False,
        "errors": [],
        "strings": l10n.catalogue(language),
        "today": {},
        "providers": {},
        "periods": {},
        "limits": {},
        "blocks": {},
        "burn": {},
        "companion": {},
        "shop": [],
        "bag": [],
        # 649 is the highest id the game reaches, so this is the widest the
        # number badge ever gets.
        "dex": [
            {"species_id": 649, "name": name, "sprite_path": "",
             "rarity": "common", "is_shiny": index % 4 == 0,
             "is_raising": index % 4 == 1}
            for index, name in enumerate(names * 6)
        ],
        "rarity_counts": {"legendary": 0, "rare": 1, "uncommon": 0, "common": 23},
        "catch_log": [],
        "catch_counts": {},
        "provider_status": {},
        "settings": {"providers": []},
        "config": {"language": language},
        "panel": {},
        "celebration": {},
        "update": {},
    }


@pytest.mark.parametrize("language", sorted(LONGEST))
@pytest.mark.parametrize("tab", ["home", "shop", "bag", "collection"])
def test_no_tab_is_wider_than_the_window(qt_app, language, tab):
    window = Window(_read(language))
    window.resize(*WINDOW_SIZE)
    window.show()
    window.show_tab(tab)
    qt_app.processEvents()
    qt_app.processEvents()

    for area in window.findChildren(QScrollArea):
        content = area.widget()
        if content is None or not area.isVisible():
            continue
        needed = content.minimumSizeHint().width()
        available = area.viewport().width()
        assert needed <= available, (
            f"{language}/{tab}: content wants {needed}px in a {available}px "
            f"viewport, so part of it sits outside the window"
        )
    window.close()


def _read(language: str) -> StateReader:
    reader = StateReader()
    reader.state = _payload(language, LONGEST[language])
    return reader


def test_a_long_name_is_elided_rather_than_widening_its_cell(qt_app):
    """The name is cut with an ellipsis; the full one stays in the tooltip.

    Truncation without the tooltip would be the same bug in a quieter form —
    "Seismitoa" and "Seismitoad" are one species, and the Pokedex is the only
    place the name is ever shown.
    """
    from poketokenbar.ui.panels import DEX_CELL_WIDTH, CollectionPanel

    panel = CollectionPanel.__new__(CollectionPanel)
    panel._state = {"panel": {}}
    panel.t = lambda key: {"representative": "rep", "raising": "RAISING"}[key]

    cell = panel._cell({
        "species_id": 537, "name": "Seismitoad" * 3,
        "sprite_path": "", "rarity": "common",
    })
    from PySide6.QtWidgets import QLabel

    texts = [w.text() for w in cell.findChildren(QLabel)]
    assert any(t.endswith("…") for t in texts), texts
    tooltips = [w.toolTip() for w in cell.findChildren(QLabel)]
    assert "Seismitoad" * 3 in tooltips
    assert cell.minimumSizeHint().width() <= DEX_CELL_WIDTH + 16
