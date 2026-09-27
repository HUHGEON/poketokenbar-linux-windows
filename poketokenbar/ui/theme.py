"""Colours and the one stylesheet the window is painted with.

Taken from the macOS popover rather than from the desktop theme. That is a
deliberate departure from how a Qt app usually behaves: the popover is a dark
card surface whatever the system is set to, and letting a light Windows theme
repaint it produced a window that shared no visual property with the original —
grey rows on white, no cards, no accent.

Every colour a panel needs is named here so none is spelled out twice.
"""

from __future__ import annotations

# Surfaces, darkest first.
WINDOW = "#1c1c1e"
CARD = "#2c2c2e"
RAISED = "#3a3a3c"
DIVIDER = "#38383a"

# Text, in the three weights the popover uses.
TEXT = "#ffffff"
SECONDARY = "#98989f"
TERTIARY = "#6e6e73"

ACCENT = "#0a84ff"
GREEN = "#30d158"
ORANGE = "#ff9f0a"
RED = "#ff453a"

# Rarity, matching the badge colours in the Pokedex and the shop.
RARITY = {
    "common": ("#48484a", "#d5d5da"),
    "uncommon": ("#2b6a3d", "#5be07c"),
    "rare": ("#12508f", "#66b6ff"),
    "legendary": ("#8a5a12", "#ffc95c"),
}
RARITY_DOT = {
    "common": "#98989f",
    "uncommon": "#30d158",
    "rare": "#0a84ff",
    "legendary": "#ff9f0a",
}


def rarity_colours(rarity: str | None) -> tuple[str, str]:
    return RARITY.get(rarity or "common", RARITY["common"])


STYLESHEET = f"""
QWidget {{
    background: {WINDOW};
    color: {TEXT};
    font-size: 13px;
}}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 2px 2px 2px 0;
}}
QScrollBar::handle:vertical {{
    background: {RAISED}; border-radius: 4px; min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}
QToolTip {{
    background: {CARD}; color: {TEXT}; border: 1px solid {DIVIDER}; padding: 4px;
}}
"""
