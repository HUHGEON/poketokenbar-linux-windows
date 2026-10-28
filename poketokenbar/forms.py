"""Gen I–V alternate appearances from upstream PokemonForm.swift.

An individual's form follows its evolution line. Battle data always uses the
species default; forms select artwork and collection appearances only.
"""
from .unown import SPECIES_ID, FORMS, symbol

# (form, pokemon-form id, optional static-sprite pokemon variety id), default first.
CATALOG = {201: [('a', 201, None),
       ('b', 10001, None),
       ('c', 10002, None),
       ('d', 10003, None),
       ('e', 10004, None),
       ('f', 10005, None),
       ('g', 10006, None),
       ('h', 10007, None),
       ('i', 10008, None),
       ('j', 10009, None),
       ('k', 10010, None),
       ('l', 10011, None),
       ('m', 10012, None),
       ('n', 10013, None),
       ('o', 10014, None),
       ('p', 10015, None),
       ('q', 10016, None),
       ('r', 10017, None),
       ('s', 10018, None),
       ('t', 10019, None),
       ('u', 10020, None),
       ('v', 10021, None),
       ('w', 10022, None),
       ('x', 10023, None),
       ('y', 10024, None),
       ('z', 10025, None),
       ('exclamation', 10026, None),
       ('question', 10027, None)],
 351: [('normal', 351, None),
       ('sunny', 10028, 10013),
       ('rainy', 10029, 10014),
       ('snowy', 10030, 10015)],
 386: [('normal', 386, None),
       ('attack', 10031, 10001),
       ('defense', 10032, 10002),
       ('speed', 10033, 10003)],
 412: [('plant', 412, None), ('sandy', 10034, None), ('trash', 10035, None)],
 413: [('plant', 413, None), ('sandy', 10036, 10004), ('trash', 10037, 10005)],
 421: [('overcast', 421, None), ('sunshine', 10038, None)],
 422: [('west', 422, None), ('east', 10039, None)],
 423: [('west', 423, None), ('east', 10040, None)],
 479: [('normal', 479, None),
       ('heat', 10058, 10008),
       ('wash', 10059, 10009),
       ('frost', 10060, 10010),
       ('fan', 10061, 10011),
       ('mow', 10062, 10012)],
 487: [('altered', 487, None), ('origin', 10063, 10007)],
 492: [('land', 492, None), ('sky', 10064, 10006)],
 493: [('normal', 493, None),
       ('fighting', 10045, None),
       ('flying', 10047, None),
       ('poison', 10052, None),
       ('ground', 10050, None),
       ('rock', 10054, None),
       ('bug', 10041, None),
       ('ghost', 10048, None),
       ('steel', 10055, None),
       ('fire', 10046, None),
       ('water', 10056, None),
       ('grass', 10049, None),
       ('electric', 10044, None),
       ('psychic', 10053, None),
       ('ice', 10051, None),
       ('dragon', 10043, None),
       ('dark', 10042, None),
       ('fairy', 10085, None)],
 550: [('red-striped', 550, None), ('blue-striped', 10066, 10016)],
 555: [('standard', 555, None), ('zen', 10067, 10017)],
 585: [('spring', 585, None),
       ('summer', 10068, None),
       ('autumn', 10069, None),
       ('winter', 10070, None)],
 586: [('spring', 586, None),
       ('summer', 10071, None),
       ('autumn', 10072, None),
       ('winter', 10073, None)],
 641: [('incarnate', 641, None), ('therian', 10079, 10019)],
 642: [('incarnate', 642, None), ('therian', 10080, 10020)],
 645: [('incarnate', 645, None), ('therian', 10081, 10021)],
 646: [('normal', 646, None), ('black', 10082, 10022), ('white', 10083, 10023)],
 647: [('ordinary', 647, None), ('resolute', 10084, 10024)],
 648: [('aria', 648, None), ('pirouette', 10074, 10018)],
 649: [('normal', 649, None),
       ('douse', 10075, None),
       ('shock', 10076, None),
       ('burn', 10077, None),
       ('chill', 10078, None)]}
LINE_BASE_IDS = {413: 412, 421: 420, 423: 422, 555: 554, 586: 585}


def forms(species_id):
    return tuple(entry[0] for entry in CATALOG.get(species_id, ()))


def resolved(species_id, form=None):
    choices = forms(species_id)
    return (form if form in choices else choices[0]) if choices else None


def line_forms(base_id):
    return tuple(dict.fromkeys(form for species_id in sorted(CATALOG)
                 if LINE_BASE_IDS.get(species_id, species_id) == base_id
                 for form in forms(species_id)))


def resolved_line(base_id, form=None):
    choices = line_forms(base_id)
    return (form if form in choices else choices[0]) if choices else None


def sort_order(species_id, form):
    choices = forms(species_id)
    return choices.index(form) if form in choices else 0


def asset_name(species_id, form=None, *, static=False):
    form = resolved(species_id, form)
    entries = CATALOG.get(species_id, ())
    if static:
        for candidate, _, variety in entries:
            if candidate == form and variety:
                return str(variety)
    if not entries or form == entries[0][0]:
        return str(species_id)
    return f"{species_id}-{form}"


def display_name(name, species_id, form=None, label=None):
    form = resolved(species_id, form)
    if species_id == SPECIES_ID:
        return f"{name} [{symbol(form)}]"
    if form and form != forms(species_id)[0]:
        return f"{name} [{label or form.replace('-', ' ').title()}]"
    return name


def roll_form(roll, collected, choices=FORMS):
    remaining = roll % sum(1 if form in collected else 2 for form in choices)
    for form in choices:
        remaining -= 1 if form in collected else 2
        if remaining < 0:
            return form
    return choices[-1]
