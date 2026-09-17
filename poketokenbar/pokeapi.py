"""PokéAPI access — ports PokeAPIClient.swift.

Species data is fetched at runtime and cached on disk; nothing Pokémon-related
is bundled in the repository.

Everything here is best effort. If the network is down the caller keeps the
tokens in the egg and hatches later — progress is never discarded.
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

from . import l10n, profile as profiles
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


# Species details and localized resource names change rarely; after this long a
# cached copy is refreshed, and until then it is served without a request. A
# stale copy is still served when the refresh fails.
DETAIL_TTL_SECONDS = 30 * 86400
# The resources a detail page names. Anything else is refused before it can
# become part of a URL or a cache path.
NAME_KINDS = ("type", "ability", "move")
_RESOURCE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


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
    def __init__(self, cache_dir: Path | None = None, clock=time.time) -> None:
        self.cache_dir = cache_dir or (Path.home() / ".cache" / "poketokenbar")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._species: dict[int, dict] = {}
        self._lines: dict[int, EvoLine] = {}
        self._details: dict[int, profiles.PokemonDetails] = {}
        self._names: dict[tuple[str, str], dict[str, str]] = {}
        # The detail loader fills these from its own thread while the daemon
        # reads them; the lock keeps a half-written entry from being seen.
        self._lock = threading.Lock()
        self._clock = clock

    # --- details (upstream b6bf676) ------------------------------------------

    def _details_file(self, species_id: int) -> Path:
        return self.cache_dir / "pokemon-details-v1" / f"{int(species_id)}.json"

    def cached_details(self, species_id: int) -> profiles.PokemonDetails | None:
        """Details from memory or disk, however old. Never touches the network.

        What the daemon's own thread uses: enriching a profile or drawing a
        detail page must not wait on a request.
        """
        with self._lock:
            found = self._details.get(species_id)
        if found is not None:
            return found
        snapshot = _read_snapshot(self._details_file(species_id))
        if snapshot is None:
            return None
        details = _details_from_json(snapshot.get("details"))
        if details is not None:
            with self._lock:
                self._details[species_id] = details
        return details

    def details(self, species_id: int) -> profiles.PokemonDetails:
        """Details for one species: memory, a fresh disk copy, then PokéAPI.

        A stale disk copy answers when the request fails, so a Pokémon seen
        once is never blank offline.
        """
        with self._lock:
            found = self._details.get(species_id)
        if found is not None:
            return found
        path = self._details_file(species_id)
        snapshot = _read_snapshot(path)
        disk = _details_from_json(snapshot.get("details")) if snapshot else None
        if disk is not None and self._clock() - snapshot.get("fetched_at", 0) < DETAIL_TTL_SECONDS:
            with self._lock:
                self._details[species_id] = disk
            return disk
        try:
            raw = _get_json(f"{REST_BASE}/pokemon/{int(species_id)}")
            gender_rate = self.species(species_id).get("gender_rate")
            details = parse_details(species_id, raw, gender_rate)
        except (PokeAPIError, KeyError, TypeError, ValueError) as exc:
            if disk is not None:
                with self._lock:
                    self._details[species_id] = disk
                return disk
            raise PokeAPIError(f"details for {species_id}: {exc}") from exc
        _write_snapshot(path, {"fetched_at": self._clock(), "details": asdict(details)})
        with self._lock:
            self._details[species_id] = details
        return details

    # --- localized names for types, abilities and moves (upstream 2fab082) ---

    def _names_file(self, kind: str, name: str) -> Path:
        return self.cache_dir / "pokemon-names-v1" / kind / f"{name}.json"

    @staticmethod
    def _valid_resource(kind: str, name: str) -> bool:
        return kind in NAME_KINDS and bool(_RESOURCE_NAME.match(name or ""))

    def cached_resource_names(self, kind: str, name: str) -> dict[str, str] | None:
        """{language code: name} from memory or disk, or None. No network."""
        if not self._valid_resource(kind, name):
            return None
        with self._lock:
            found = self._names.get((kind, name))
        if found is not None:
            return found
        snapshot = _read_snapshot(self._names_file(kind, name))
        names = snapshot.get("names") if snapshot else None
        if not isinstance(names, dict):
            return None
        with self._lock:
            self._names[(kind, name)] = names
        return names

    def resource_names(self, kind: str, name: str) -> dict[str, str]:
        """Localized names of one type, ability or move."""
        if not self._valid_resource(kind, name):
            raise PokeAPIError(f"not a {kind} name: {name!r}")
        with self._lock:
            found = self._names.get((kind, name))
        if found is not None:
            return found
        path = self._names_file(kind, name)
        snapshot = _read_snapshot(path)
        disk = snapshot.get("names") if snapshot else None
        if isinstance(disk, dict) and self._clock() - snapshot.get("fetched_at", 0) < DETAIL_TTL_SECONDS:
            with self._lock:
                self._names[(kind, name)] = disk
            return disk
        try:
            raw = _get_json(f"{REST_BASE}/{kind}/{name}/")
            names = l10n.names_from_api(raw.get("names") if isinstance(raw, dict) else None)
        except PokeAPIError:
            if isinstance(disk, dict):
                with self._lock:
                    self._names[(kind, name)] = disk
                return disk
            raise
        _write_snapshot(path, {"fetched_at": self._clock(), "names": names})
        with self._lock:
            self._names[(kind, name)] = names
        return names

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
        # Atomic: the detail loader's thread writes here too, and a half-written
        # file read by the daemon would send it back to the network.
        cached.parent.mkdir(parents=True, exist_ok=True)
        tmp = cached.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(cached)
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


def parse_details(species_id: int, raw: dict, gender_rate) -> profiles.PokemonDetails:
    """PokéAPI's /pokemon/{id} reduced to what a profile and its page use.

    Moves are cut down to the supported version group here, at the trust
    boundary, before anything is cached: the full cross-generation history is
    most of the response and none of it is shown.
    """
    moves = []
    for entry in raw.get("moves") or []:
        methods = [
            profiles.LearnMethod(row["move_learn_method"]["name"], int(row["level_learned_at"]))
            for row in entry.get("version_group_details") or []
            if (row.get("version_group") or {}).get("name") == profiles.PREFERRED_VERSION_GROUP
        ]
        if methods:
            moves.append(profiles.MoveOption(entry["move"]["name"], methods))
    moves.sort(key=lambda m: m.name)
    return profiles.PokemonDetails(
        species_id=int(species_id),
        name=str(raw["name"]),
        height=int(raw.get("height") or 0),
        weight=int(raw.get("weight") or 0),
        base_experience=raw.get("base_experience") if isinstance(raw.get("base_experience"), int) else None,
        gender_rate=gender_rate if isinstance(gender_rate, int) else -1,
        types=[t["type"]["name"] for t in sorted(raw.get("types") or [], key=lambda t: t["slot"])],
        base_stats={s["stat"]["name"]: int(s["base_stat"]) for s in raw.get("stats") or []},
        abilities=sorted(
            (profiles.AbilityOption(a["ability"]["name"], int(a["slot"]), bool(a["is_hidden"]))
             for a in raw.get("abilities") or []),
            key=lambda a: a.slot,
        ),
        moves=moves,
    )


def _details_from_json(raw) -> profiles.PokemonDetails | None:
    """Details as cached by asdict(), or None when the file is not that."""
    if not isinstance(raw, dict):
        return None
    try:
        return profiles.PokemonDetails(
            species_id=int(raw["species_id"]),
            name=str(raw["name"]),
            height=int(raw["height"]),
            weight=int(raw["weight"]),
            base_experience=raw.get("base_experience"),
            gender_rate=int(raw["gender_rate"]),
            types=[str(t) for t in raw["types"]],
            base_stats={str(k): int(v) for k, v in raw["base_stats"].items()},
            abilities=[profiles.AbilityOption(str(a["name"]), int(a["slot"]), bool(a["is_hidden"]))
                       for a in raw["abilities"]],
            moves=[profiles.MoveOption(str(m["name"]),
                                       [profiles.LearnMethod(str(l["method"]), int(l["level"]))
                                        for l in m["learn_methods"]])
                   for m in raw["moves"]],
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _read_snapshot(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def _write_snapshot(path: Path, body: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # a cache that cannot be written is only a slower cache


def _id_from_url(url: str) -> int | None:
    parts = [p for p in url.rstrip("/").split("/") if p]
    if not parts:
        return None
    try:
        return int(parts[-1])
    except ValueError:
        return None
