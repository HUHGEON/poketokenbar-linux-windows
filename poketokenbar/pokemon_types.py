"""Localized Pokémon types and the macOS app's classic type-chart colors."""

LANGUAGES = ('en', 'ko', 'ja', 'es', 'fr', 'pt', 'de', 'ru')
TYPE_IDS = ('normal', 'fire', 'water', 'electric', 'grass', 'ice', 'fighting',
            'poison', 'ground', 'flying', 'psychic', 'bug', 'rock', 'ghost',
            'dragon', 'dark', 'steel', 'fairy')
COLORS = dict(zip(TYPE_IDS, (
    '#AAAA99', '#FF4422', '#3399FF', '#FFCC33', '#77CC55', '#66CCFF',
    '#BB5544', '#AA5599', '#DDBB55', '#8899FF', '#FF5599', '#AABB22',
    '#BBAA66', '#6666BB', '#7766EE', '#775544', '#AAAABB', '#EE99EE',
)))
_KOREAN_NAMES = '노말|불꽃|물|전기|풀|얼음|격투|독|땅|비행|에스퍼|벌레|바위|고스트|드래곤|악|강철|페어리'.split('|')
# Only Korean is translated for now. Other UI languages keep the canonical
# English names until their type-name translations are requested.
NAMES = {slug: tuple(_KOREAN_NAMES[index] if code == 'ko' else slug.title()
                     for code in LANGUAGES)
         for index, slug in enumerate(TYPE_IDS)}


def badges(types, language='en') -> list[dict]:
    """Keep PokéAPI's slot order; future types get a neutral readable badge."""
    index = LANGUAGES.index(language) if language in LANGUAGES else 0
    result = []
    seen = set()
    for raw in types or []:
        if not isinstance(raw, str) or not raw.strip():
            continue
        slug = raw.strip().lower()
        if slug in seen:
            continue
        seen.add(slug)
        color = COLORS.get(slug, '#808080')
        red, green, blue = (int(color[offset:offset + 2], 16) for offset in (1, 3, 5))
        foreground = '#1c1c1e' if .299 * red + .587 * green + .114 * blue > 165 else '#ffffff'
        result.append({'type': slug, 'name': NAMES[slug][index] if slug in NAMES else slug.title(),
                       'color': color, 'foreground': foreground})
    return result
