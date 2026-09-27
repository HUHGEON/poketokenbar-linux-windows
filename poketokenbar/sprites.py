"""Sprite fetching — ports SpriteLoader.swift.

Sprites are downloaded at runtime and cached on disk; none are bundled.

The macOS app decodes GIF frames with ImageIO. QML's AnimatedImage plays a GIF
directly, so here the job is only to put a file on disk and hand back its path.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

from . import platform_paths, unown

SPRITE_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"
ITEM_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/items"
USER_AGENT = "poketokenbar/0.1"
# Animated Black/White sprites exist for Gen I-V only.
MAX_ANIMATED_ID = 649
# The egg is filed under the Pokemon sprites but is not a species, so it has no
# id and cannot go through `sprite_url`.
EGG_SPRITE_URL = f"{SPRITE_BASE}/egg.png"


def cache_key(species_id: int, animated: bool, shiny: bool, unown_form: str | None = None) -> str:
    """The cached file's name: species, letter, colour and format.

    Unown's A keeps the plain species key, so every sprite cached before
    letters existed is still the right file for it (upstream 10d1a07).
    """
    asset = unown.asset_name(species_id, unown_form) if unown_form else str(species_id)
    return f"{asset}-{'sh' if shiny else ''}{'a' if animated else 's'}"


def sprite_url(species_id: int, animated: bool, shiny: bool, unown_form: str | None = None) -> str:
    asset = unown.asset_name(species_id, unown_form) if unown_form else str(species_id)
    if animated:
        shiny_part = "shiny/" if shiny else ""
        return (
            f"{SPRITE_BASE}/versions/generation-v/black-white/animated/"
            f"{shiny_part}{asset}.gif"
        )
    return f"{SPRITE_BASE}/{'shiny/' if shiny else ''}{asset}.png"


class SpriteStore:
    def __init__(self, cache_dir: Path | None = None) -> None:
        base = cache_dir or (platform_paths.cache_base() / "poketokenbar")
        self.dir = base / "sprites"
        self.dir.mkdir(parents=True, exist_ok=True)

    def item_path(self, item_name: str) -> Path | None:
        """Local path to an item sprite, or None when PokeAPI has none."""
        target = self.dir / f"item-{item_name}.png"
        if target.is_file() and target.stat().st_size > 0:
            return target
        request = urllib.request.Request(f"{ITEM_BASE}/{item_name}.png")
        request.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status != 200:
                    return None
                data = response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        if not data:
            return None
        tmp = target.with_suffix(".png.tmp")
        tmp.write_bytes(data)
        tmp.replace(target)
        return target

    def egg_path(self) -> Path | None:
        """Local path to the egg sprite, downloading it once if needed.

        Its own method rather than a species id: the egg is not a species, so
        anything routed through `path()` would need an id invented for it, and
        that id would be asked of PokeAPI on the next lookup.

        Without this the egg stage had no picture anywhere. Home drew an empty
        box where the sprite goes, the desktop pet vanished between companions,
        and only the panel had a text fallback — which read as a UI that had
        stopped working rather than as an egg.
        """
        target = self.dir / "egg.png"
        if target.is_file() and target.stat().st_size > 0:
            return target
        return self._download(EGG_SPRITE_URL, target)

    def path(self, species_id: int, animated: bool = True, shiny: bool = False,
             unown_form: str | None = None) -> Path | None:
        """Local path to the sprite, downloading it once if needed.

        Returns None when unavailable so the caller can fall back rather than
        render a broken image. `unown_form` picks one of Unown's 28 letters;
        it is ignored for every other species.
        """
        if animated and species_id > MAX_ANIMATED_ID:
            animated = False

        key = cache_key(species_id, animated, shiny, unown_form)
        target = self.dir / f"{key}.{'gif' if animated else 'png'}"
        if target.is_file() and target.stat().st_size > 0:
            return target

        return self._download(sprite_url(species_id, animated, shiny, unown_form), target)

    def _download(self, url: str, target: Path) -> Path | None:
        """Fetch one sprite to `target`, or None when it cannot be had."""
        request = urllib.request.Request(url)
        request.add_header("User-Agent", USER_AGENT)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                if response.status != 200:
                    return None
                data = response.read()
        except (urllib.error.URLError, TimeoutError, OSError):
            return None
        if not data:
            return None

        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(target)  # atomic — a crash must not leave a torn sprite
        return target
