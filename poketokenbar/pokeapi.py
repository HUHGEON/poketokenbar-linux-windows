"""PokéAPI access — ports PokeAPIClient.swift.

Species data is fetched at runtime and cached on disk; nothing Pokémon-related
is bundled in the repository.

Everything here is best effort. If the network is down the caller keeps the
tokens in the egg and hatches later — progress is never discarded.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import l10n
from .balance import DITTO_SPECIES_ID, Rarity
from .companion import EvoLine

REST_BASE = "https://pokeapi.co/api/v2"
GRAPHQL_URL = "https://graphql.pokeapi.co/v1beta2"
# Gen I-V. The animated Black/White sprites the panel uses stop here.
MAX_SPECIES_ID = 649
# Every PokéAPI code l10n.api_codes can ask for, lower-cased as
# l10n.names_from_api stores them. Brazilian Portuguese names are under pt-BR;
# plain "pt" is kept in case PokéAPI ever adds it.
LANG_CODES = ("ko", "en", "ja-hrkt", "ja", "es", "fr", "pt-br", "pt", "de")
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

        path: list[int] = []
        node = chain.get("chain")
        while node:
            species_ref = node.get("species") or {}
            species_id = _id_from_url(species_ref.get("url", ""))
            if species_id is None or species_id > MAX_SPECIES_ID:
                break
            path.append(species_id)
            nxt = node.get("evolves_to") or []
            node = nxt[0] if nxt else None

        if not path:
            raise PokeAPIError(f"empty evolution path for {base_species_id}")

        rarity = Rarity.classify(
            int(base.get("capture_rate") or 255),
            bool(base.get("is_legendary")),
            bool(base.get("is_mythical")),
        )
        names: dict[int, dict[str, str]] = {}
        for sid in path:
            try:
                entry = self.species(sid)
            except PokeAPIError:
                continue
            names[sid] = {
                code: name
                for code, name in l10n.names_from_api(entry.get("names")).items()
                if code in LANG_CODES
            }

        evo = EvoLine(base_id=base_species_id, path_ids=path, rarity=rarity, names=names)
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
