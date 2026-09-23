"""PokéAPI access — ports PokeAPIClient.swift.

Species data is fetched at runtime and cached on disk; nothing Pokémon-related
is bundled in the repository.

Everything here is best effort. If the network is down the caller keeps the
tokens in the egg and hatches later — progress is never discarded.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .balance import DITTO_SPECIES_ID, Rarity
from .companion import EvoLine, EvoNode

REST_BASE = "https://pokeapi.co/api/v2"
GRAPHQL_URL = "https://graphql.pokeapi.co/v1beta2"
# Gen I-V. The animated Black/White sprites the panel uses stop here.
MAX_SPECIES_ID = 649
# Lockstep with l10n.LANGUAGES, so a Pokemon's name is available in whatever
# language the UI is set to. "pt" collects nothing today — PokeAPI has no such
# language — but is listed so it is picked up the moment one appears; omitting
# it would pin Portuguese users to English names forever.
LANG_CODES = ("ko", "en", "ja-Hrkt", "ja", "es", "fr", "pt", "de")
# PokéAPI's GraphQL endpoint answers 403 to urllib's default User-Agent.
USER_AGENT = "poketokenbar/0.1 (+https://github.com/chattymin/PokeTokenBar)"


class PokeAPIError(Exception):
    pass


@dataclass(slots=True)
class BaseSpecies:
    id: int
    capture_rate: int


def _get_json(url: str, timeout: float = 15.0):
    request = urllib.request.Request(url)
    request.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise PokeAPIError(f"GET {url}: {exc}") from exc


def _post_json(url: str, payload: dict, timeout: float = 20.0):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body)
    request.add_header("Content-Type", "application/json")
    request.add_header("User-Agent", USER_AGENT)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise PokeAPIError(f"POST {url}: {exc}") from exc


class PokeAPI:
    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or (Path.home() / ".cache" / "poketokenbar")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._species: dict[int, dict] = {}
        self._lines: dict[int, EvoLine] = {}
        self._details: dict[int, dict] = {}
        self._battle_names: dict[str, dict[str, dict[str, str]]] | None = None
        self._battle_names_retry_after = 0.0

    # --- translated battle names -----------------------------------------

    @property
    def _battle_names_file(self) -> Path:
        return self.cache_dir / "battle-names-v1.json"

    def _load_battle_names(self) -> dict[str, dict[str, dict[str, str]]]:
        if self._battle_names is not None:
            return self._battle_names
        try:
            raw = json.loads(self._battle_names_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            raw = {}
        self._battle_names = {
            "ability": raw.get("ability", {}) if isinstance(raw, dict) else {},
            "move": raw.get("move", {}) if isinstance(raw, dict) else {},
        }
        return self._battle_names

    def localized_battle_names(self, ability: str | None, moves: list[str],
                               language: str) -> tuple[str, dict[str, str]]:
        """Translate one profile's ability and moves in one cached request.

        Profiles persist PokéAPI's stable English slugs.  Display names live in
        a separate cache so changing the app language never rewrites a save.
        """
        wanted = {
            "ability": [ability] if ability else [],
            "move": list(dict.fromkeys(name for name in moves if name)),
        }
        cache = self._load_battle_names()
        missing = {
            kind: [name for name in names if name not in cache[kind]]
            for kind, names in wanted.items()
        }
        if any(missing.values()) and time.time() >= self._battle_names_retry_after:
            query = (
                "{ abilityname(where: {ability: {name: {_in: "
                + json.dumps(missing["ability"])
                + "}}}) { name language { name } ability { name } } "
                "movename(where: {move: {name: {_in: "
                + json.dumps(missing["move"])
                + "}}}) { name language { name } move { name } } }"
            )
            try:
                payload = _post_json(GRAPHQL_URL, {"query": query})
                data = payload.get("data") or {}
                for kind, rows, relation in (
                    ("ability", data.get("abilityname") or [], "ability"),
                    ("move", data.get("movename") or [], "move"),
                ):
                    # Record even a resource with no translated row, otherwise
                    # an absent language would trigger the same request forever.
                    for name in missing[kind]:
                        cache[kind].setdefault(name, {})
                    for row in rows:
                        slug = str((row.get(relation) or {}).get("name") or "")
                        code = str((row.get("language") or {}).get("name") or "")
                        translated = str(row.get("name") or "")
                        if slug and code and translated:
                            if code == "ja-hrkt":
                                code = "ja-Hrkt"
                            cache[kind].setdefault(slug, {})[code] = translated
                tmp = self._battle_names_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self._battle_names_file)
            except (PokeAPIError, OSError, ValueError, TypeError, AttributeError):
                # A disconnected machine should not stall every two-second
                # state poll. Network recovery or five minutes is soon enough.
                self._battle_names_retry_after = time.time() + 300

        def resolve(kind: str, slug: str) -> str:
            names = cache[kind].get(slug) or {}
            for code in ({"ja": ["ja-Hrkt", "ja"]}.get(language, [language])):
                if names.get(code):
                    return names[code]
            return names.get("en") or slug

        return resolve("ability", ability) if ability else "", {
            name: resolve("move", name) for name in wanted["move"]
        }

    # --- individual details -----------------------------------------------

    def _details_file(self, species_id: int) -> Path:
        return self.cache_dir / "pokemon-details-v1" / f"{species_id}.json"

    def cached_details(self, species_id: int) -> dict | None:
        if species_id in self._details:
            return self._details[species_id]
        path = self._details_file(species_id)
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            details = snapshot.get("details")
            if isinstance(details, dict):
                self._details[species_id] = details
                return details
        except (OSError, ValueError, AttributeError):
            pass
        return None

    def details(self, species_id: int) -> dict:
        """Default-form battle data, cached for 30 days with stale fallback."""
        if species_id in self._details:
            return self._details[species_id]
        path = self._details_file(species_id)
        cached = self.cached_details(species_id)
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8"))
            if cached is not None and time.time() - float(snapshot.get("fetched_at", 0)) < 30 * 86400:
                return cached
        except (OSError, ValueError, TypeError, AttributeError):
            pass
        try:
            pokemon = _get_json(f"{REST_BASE}/pokemon/{species_id}")
            species = self.species(species_id)
            moves = []
            for move in pokemon.get("moves") or []:
                levels = [
                    int(row.get("level_learned_at", 0))
                    for row in move.get("version_group_details") or []
                    if (row.get("version_group") or {}).get("name") == "black-white"
                    and (row.get("move_learn_method") or {}).get("name") == "level-up"
                ]
                if levels:
                    moves.append({"name": (move.get("move") or {}).get("name", ""),
                                  "learned_at": min(levels)})
            descriptions = {}
            for entry in species.get("flavor_text_entries") or []:
                code = (entry.get("language") or {}).get("name")
                if code in LANG_CODES and code not in descriptions:
                    descriptions[code] = " ".join(str(entry.get("flavor_text") or "").split())
            details = {
                "species_id": species_id,
                "height": int(pokemon.get("height") or 0),
                "weight": int(pokemon.get("weight") or 0),
                "gender_rate": int(species.get("gender_rate", -1)),
                "types": [row.get("type", {}).get("name", "")
                          for row in sorted(pokemon.get("types") or [],
                                            key=lambda row: row.get("slot", 0))],
                "base_stats": {row.get("stat", {}).get("name", ""): int(row.get("base_stat", 0))
                               for row in pokemon.get("stats") or []},
                "abilities": [{"name": row.get("ability", {}).get("name", ""),
                               "slot": int(row.get("slot", 0)),
                               "is_hidden": bool(row.get("is_hidden"))}
                              for row in pokemon.get("abilities") or []],
                "moves": sorted(moves, key=lambda move: (move["learned_at"], move["name"])),
                "descriptions": descriptions,
            }
            self._details[species_id] = details
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"fetched_at": time.time(), "details": details}),
                           encoding="utf-8")
            tmp.replace(path)
            return details
        except PokeAPIError:
            if cached is not None:
                return cached
            raise

    # --- hatch candidates --------------------------------------------------

    @property
    def _index_file(self) -> Path:
        return self.cache_dir / "base-species.json"

    def base_species_index(self) -> list[BaseSpecies]:
        """Every Gen I-V evolution-line start, with its capture rate.

        One GraphQL query, cached to disk. Ditto is excluded from the normal
        pool; it only appears through the disguise mechanic.
        """
        if self._index_file.is_file():
            try:
                raw = json.loads(self._index_file.read_text(encoding="utf-8"))
                if raw:
                    return [BaseSpecies(r["id"], r["capture_rate"]) for r in raw]
            except (ValueError, KeyError, TypeError):
                pass  # rebuild below

        query = (
            "{ pokemonspecies(where: {evolves_from_species_id: {_is_null: true}, "
            f"id: {{_lte: {MAX_SPECIES_ID}, _neq: {DITTO_SPECIES_ID}}}}}, "
            "order_by: {id: asc}) { id capture_rate } }"
        )
        payload = _post_json(GRAPHQL_URL, {"query": query})
        rows = (payload.get("data") or {}).get("pokemonspecies") or []
        if not rows:
            raise PokeAPIError("empty base species index")

        out = [
            BaseSpecies(int(r["id"]), int(r["capture_rate"]))
            for r in rows
            if r.get("capture_rate") is not None
        ]
        tmp = self._index_file.with_suffix(".tmp")
        tmp.write_text(
            json.dumps([{"id": b.id, "capture_rate": b.capture_rate} for b in out]),
            encoding="utf-8",
        )
        tmp.replace(self._index_file)
        return out

    # --- lines -------------------------------------------------------------

    def species(self, species_id: int) -> dict:
        if species_id in self._species:
            return self._species[species_id]
        cached = self.cache_dir / "species" / f"{species_id}.json"
        if cached.is_file():
            try:
                data = json.loads(cached.read_text(encoding="utf-8"))
                self._species[species_id] = data
                return data
            except ValueError:
                pass
        data = _get_json(f"{REST_BASE}/pokemon-species/{species_id}")
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(data), encoding="utf-8")
        self._species[species_id] = data
        return data

    def line(self, base_species_id: int) -> EvoLine:
        """The evolution line starting at base_species_id.

        Branching lines pick one path; the panel shows a single companion.
        """
        if base_species_id in self._lines:
            return self._lines[base_species_id]

        base = self.species(base_species_id)
        chain_url = (base.get("evolution_chain") or {}).get("url")
        if not chain_url or not chain_url.startswith("https://pokeapi.co/"):
            raise PokeAPIError(f"bad evolution chain url for {base_species_id}")
        chain = _get_json(chain_url)

        tree = _tree_from_chain(chain.get("chain"))
        if tree is None:
            raise PokeAPIError(f"empty evolution path for {base_species_id}")
        # Species without an animated sprite go, and their branches with them,
        # so a plan can never route through a form that cannot be drawn.
        tree = tree.keeping_animated() or EvoNode(base_species_id)
        # The default straight route. A companion's actual route is chosen per
        # hatch, from the whole tree — following this one for everybody is what
        # made seven of Eevee's eight evolutions unreachable.
        path = _first_route(tree)

        rarity = Rarity.classify(
            int(base.get("capture_rate") or 255),
            bool(base.get("is_legendary")),
            bool(base.get("is_mythical")),
        )
        names: dict[int, dict[str, str]] = {}
        # Every species in the tree, not only the default route: any of them can
        # be the form this companion grows into, and a missing name renders as
        # "#134".
        for sid in _species_in(tree):
            try:
                entry = self.species(sid)
            except PokeAPIError:
                continue
            by_lang = {
                n["language"]["name"]: n["name"]
                for n in entry.get("names", [])
                if n.get("language", {}).get("name") in LANG_CODES
            }
            names[sid] = by_lang

        evo = EvoLine(base_id=base_species_id, path_ids=path, rarity=rarity,
                      names=names, tree=tree)
        self._lines[base_species_id] = evo
        return evo

    # --- rolling -----------------------------------------------------------

    def roll_base_species(self, rng, tier: Rarity | None = None) -> int:
        """Capture-rate-weighted pick, so commons are common.

        capture_rate runs 3 (legendary-ish) to 255 (Caterpie). Using it directly
        as the weight reproduces the official rarity curve.
        """
        candidates = self.base_species_index()
        if tier is not None:
            ceiling = tier.capture_rate_ceiling
            if ceiling is not None:
                candidates = [c for c in candidates if c.capture_rate <= ceiling]
        if not candidates:
            raise PokeAPIError("no hatch candidates")
        weights = [c.capture_rate for c in candidates]
        return rng.choices(candidates, weights=weights, k=1)[0].id


def _id_from_url(url: str) -> int | None:
    parts = [p for p in url.rstrip("/").split("/") if p]
    if not parts:
        return None
    try:
        return int(parts[-1])
    except ValueError:
        return None


def _tree_from_chain(node) -> "EvoNode | None":
    """PokeAPI's nested `chain` as an EvoNode, branches and all."""
    if not isinstance(node, dict):
        return None
    species_id = _id_from_url((node.get("species") or {}).get("url", ""))
    if species_id is None:
        return None
    children = [
        child for child in
        (_tree_from_chain(entry) for entry in node.get("evolves_to") or [])
        if child is not None
    ]
    return EvoNode(species_id, children)


def _first_route(node: "EvoNode") -> list[int]:
    route = [node.species_id]
    while node.children:
        node = node.children[0]
        route.append(node.species_id)
    return route


def _species_in(node: "EvoNode") -> list[int]:
    found = [node.species_id]
    for child in node.children:
        found += _species_in(child)
    return found
