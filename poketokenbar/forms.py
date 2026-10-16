"""An individual's appearance within its species — ports PokemonForm.swift
(upstream 04b12da).

Unown's letter was the first of these (upstream 10d1a07); this is the same idea
for every generation 1-5 species whose forms all have an animated Black/White
sprite: Castform's weather, Deoxys's stances, Burmy's cloak, Cherrim, Shellos's
sea, Rotom's appliances, Giratina, Shaymin, Arceus's plates, Basculin's stripe,
Darmanitan's mode, Deerling's season, the forces of nature, Kyurem, Keldeo,
Meloetta and Genesect's drives.

The form belongs to the individual, not to the species: it is chosen once when
the egg hatches, carried through the whole evolution line, and resolved per
species — a Sandy Burmy becomes a Sandy Wormadam, while the Mothim branch has
only the one appearance. Species ids and evolution paths are untouched; the
form picks sprites, names and collection slots.

Gender differences are not forms, and neither is anything a Pokemon only wears
mid-battle unless Gen V drew it.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

UNOWN_SPECIES_ID = 201
# Its plates are named after types, which PokeAPI translates everywhere.
ARCEUS_SPECIES_ID = 493

# An uncollected form is twice as likely as one already collected — the same
# adjustment the species roll makes, with no streak counter behind it.
UNCOLLECTED_WEIGHT = 2


@dataclass(frozen=True)
class Entry:
    """One appearance of one species.

    `form_id` is the PokeAPI `pokemon-form` resource holding its localized
    names. `pokemon_id` is the variety whose static PNG holds it — Sky Shaymin
    is `10006.png` — and None means the still picture is named like the
    animated one (`412-sandy.png`).
    """

    form: str
    form_id: int
    pokemon_id: int | None = None


def _unown_entries() -> list[Entry]:
    letters = [chr(code) for code in range(ord("a"), ord("z") + 1)]
    letters += ["exclamation", "question"]
    return [
        Entry(letter, UNOWN_SPECIES_ID if index == 0 else 10000 + index)
        for index, letter in enumerate(letters)
    ]


# Every catalogued species lists its default appearance first; that one keeps
# the plain `<id>.png` / `<id>.gif` sprites, so every file cached before forms
# existed is still the right file.
CATALOG: dict[int, list[Entry]] = {
    UNOWN_SPECIES_ID: _unown_entries(),
    351: [Entry("normal", 351), Entry("sunny", 10028, 10013),
          Entry("rainy", 10029, 10014), Entry("snowy", 10030, 10015)],
    386: [Entry("normal", 386), Entry("attack", 10031, 10001),
          Entry("defense", 10032, 10002), Entry("speed", 10033, 10003)],
    412: [Entry("plant", 412), Entry("sandy", 10034), Entry("trash", 10035)],
    413: [Entry("plant", 413), Entry("sandy", 10036, 10004),
          Entry("trash", 10037, 10005)],
    421: [Entry("overcast", 421), Entry("sunshine", 10038)],
    422: [Entry("west", 422), Entry("east", 10039)],
    423: [Entry("west", 423), Entry("east", 10040)],
    479: [Entry("normal", 479), Entry("heat", 10058, 10008),
          Entry("wash", 10059, 10009), Entry("frost", 10060, 10010),
          Entry("fan", 10061, 10011), Entry("mow", 10062, 10012)],
    487: [Entry("altered", 487), Entry("origin", 10063, 10007)],
    492: [Entry("land", 492), Entry("sky", 10064, 10006)],
    493: [Entry("normal", 493), Entry("fighting", 10045), Entry("flying", 10047),
          Entry("poison", 10052), Entry("ground", 10050), Entry("rock", 10054),
          Entry("bug", 10041), Entry("ghost", 10048), Entry("steel", 10055),
          Entry("fire", 10046), Entry("water", 10056), Entry("grass", 10049),
          Entry("electric", 10044), Entry("psychic", 10053), Entry("ice", 10051),
          Entry("dragon", 10043), Entry("dark", 10042), Entry("fairy", 10085)],
    550: [Entry("red-striped", 550), Entry("blue-striped", 10066, 10016)],
    555: [Entry("standard", 555), Entry("zen", 10067, 10017)],
    585: [Entry("spring", 585), Entry("summer", 10068),
          Entry("autumn", 10069), Entry("winter", 10070)],
    586: [Entry("spring", 586), Entry("summer", 10071),
          Entry("autumn", 10072), Entry("winter", 10073)],
    641: [Entry("incarnate", 641), Entry("therian", 10079, 10019)],
    642: [Entry("incarnate", 642), Entry("therian", 10080, 10020)],
    645: [Entry("incarnate", 645), Entry("therian", 10081, 10021)],
    646: [Entry("normal", 646), Entry("black", 10082, 10022),
          Entry("white", 10083, 10023)],
    647: [Entry("ordinary", 647), Entry("resolute", 10084, 10024)],
    648: [Entry("aria", 648), Entry("pirouette", 10074, 10018)],
    649: [Entry("normal", 649), Entry("douse", 10075), Entry("shock", 10076),
          Entry("burn", 10077), Entry("chill", 10078)],
}

# Catalogued species whose line starts elsewhere. The form is chosen at hatch,
# so a Cherubi egg already knows which Cherrim it will become.
LINE_BASE_IDS: dict[int, int] = {413: 412, 421: 420, 423: 422, 555: 554, 586: 585}

# Castform, Rotom, Kyurem and Genesect have no official name for their usual
# look: PokeAPI either says "Rotom Forme" or nothing at all.
UNNAMED_DEFAULTS = frozenset({351, 479, 646, 649})


def entries(species_id: int) -> list[Entry]:
    return CATALOG.get(species_id, [])


def forms(species_id: int) -> list[str]:
    """The species' forms, default first; empty for a single appearance."""
    return [entry.form for entry in entries(species_id)]


def has_forms(species_id: int) -> bool:
    return species_id in CATALOG


def form_species(base_id: int) -> list[int]:
    """Species of the line that change with the individual's form, in order."""
    return sorted(sid for sid in CATALOG if LINE_BASE_IDS.get(sid, sid) == base_id)


def line_forms(base_id: int) -> list[str]:
    """Everything an individual of this line can carry, default first."""
    out: list[str] = []
    for species_id in form_species(base_id):
        for form in forms(species_id):
            if form not in out:
                out.append(form)
    return out


def is_form(species_id: int, value) -> bool:
    return isinstance(value, str) and value in forms(species_id)


def resolved(species_id: int, form: str | None) -> str | None:
    """How an individual looks at one species: its own form when that species
    has it, else the species' default. None for a species without forms.

    An Unown saved before letters existed showed the default A sprite, and a
    form stored against a species that cannot wear it is ignored rather than
    drawn.
    """
    available = forms(species_id)
    if not available:
        return None
    return form if form in available else available[0]


def resolved_for_line(base_id: int, form: str | None) -> str | None:
    """The form an individual of this line stores: None for a line without
    forms, and the line default for a record written before it had any."""
    available = line_forms(base_id)
    if not available:
        return None
    return form if form in available else available[0]


def is_default(species_id: int, form: str | None) -> bool:
    available = forms(species_id)
    return bool(available) and resolved(species_id, form) == available[0]


def sort_order(species_id: int, form: str | None) -> int:
    available = forms(species_id)
    if form is None or form not in available:
        return 0
    return available.index(form)


def symbol(form: str) -> str:
    """What Unown's letter is written as: "B", "!", "?"."""
    if form == "exclamation":
        return "!"
    if form == "question":
        return "?"
    return form.upper()


def collection_weight(form: str, collected) -> int:
    """Ports CollectionWeight.adjusted: halved once collected, never zero."""
    return max(1, UNCOLLECTED_WEIGHT // 2) if form in collected else UNCOLLECTED_WEIGHT


def roll(rng: random.Random, available, collected=()) -> str | None:
    """Pick a form, favouring the ones not collected yet.

    Only runs once the species roll has landed, so it changes neither species
    weights nor shiny odds.
    """
    available = list(available)
    if not available:
        return None
    collected = set(collected)
    weights = [collection_weight(form, collected) for form in available]
    return rng.choices(available, weights=weights, k=1)[0]


def asset_name(species_id: int, form: str | None) -> str:
    """The animated sprite and cache key for this appearance.

    The default form keeps the plain `<id>`, so every sprite cached before
    forms existed is still the right file for it.
    """
    resolved_form = resolved(species_id, form)
    if resolved_form is None or is_default(species_id, resolved_form):
        return str(species_id)
    return f"{species_id}-{resolved_form}"


def static_asset_name(species_id: int, form: str | None) -> str:
    """The still picture, which for some forms is a PokeAPI variety of its own."""
    resolved_form = resolved(species_id, form)
    for entry in entries(species_id):
        if entry.form == resolved_form and entry.pokemon_id is not None:
            return str(entry.pokemon_id)
    return asset_name(species_id, form)


def form_id(species_id: int, form: str | None) -> int | None:
    """The PokeAPI `pokemon-form` id carrying this form's localized names."""
    resolved_form = resolved(species_id, form)
    for entry in entries(species_id):
        if entry.form == resolved_form:
            return entry.form_id
    return None


def has_unnamed_default(species_id: int, form: str | None) -> bool:
    return species_id in UNNAMED_DEFAULTS and is_default(species_id, form)


def name_resource(species_id: int, form: str | None) -> int | None:
    """The form resource to look a name up in, or None when there is no name
    to look up: Unown names its letter, and some usual looks have no name."""
    if species_id == UNOWN_SPECIES_ID or has_unnamed_default(species_id, form):
        return None
    return form_id(species_id, form)


def display_name(name: str, species_id: int, form: str | None,
                 label: str | None = None) -> str:
    """"Unown [B]", "Shaymin [Sky Forme]", and just "Mothim" for a default."""
    resolved_form = resolved(species_id, form)
    if resolved_form is None:
        return name
    if species_id == UNOWN_SPECIES_ID:
        return f"{name} [{symbol(resolved_form)}]"
    if is_default(species_id, resolved_form) or not label:
        return name
    return f"{name} [{label}]"
