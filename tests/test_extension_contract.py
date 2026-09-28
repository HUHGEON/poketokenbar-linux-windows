"""The extension reads state.json; this checks it only reads what exists.

A GNOME Shell extension cannot be run from here, and a JavaScript typo in a
field name does not fail loudly — `state.companion.sprite_pat` is `undefined`,
which renders as a blank label rather than an error. That is the failure this
catches, and it is the one most likely to survive into a release.

The method is deliberately mechanical: the payload keys the daemon emits are
enumerated from a real `state.build`, the keys the extension reads are pulled
out of its source, and the difference is the test. It is not a substitute for
running the extension on a real desktop — nothing here proves an actor renders
— but it does mean every field name was compared rather than assumed.
"""

import re
import tempfile
from datetime import timedelta
import time
from pathlib import Path

import pytest

from poketokenbar import limits, profile, providers, state
from poketokenbar.balance import Rarity
from poketokenbar.companion import CompanionState, DexEntry, MonState, migrate_profiles
from poketokenbar.companion_store import CompanionStore
from poketokenbar.models import BlockUsage, DailyUsage

class _StubSprites:
    """Enough of SpriteStore for the payload builders to fill their sprite rows."""

    def path(self, species_id, animated=True, shiny=False, unown_form=None):
        letter = f"-{unown_form}" if unown_form and unown_form != "a" else ""
        return Path(
            f"/cache/{species_id}{letter}{'-sh' if shiny else ''}{'a' if animated else 's'}")

    def item_path(self, item_name):
        return Path(f"/cache/item-{item_name}.png")

    def egg_path(self):
        return Path("/cache/egg.png")


class _StubDetails:
    """Cached details and names, so the Pokédex page fills every section."""

    def cached_details(self, species_id):
        return profile.PokemonDetails(
            species_id, "stub", 10, 100, None, 4, ["water"],
            {"hp": 50, "attack": 60}, [profile.AbilityOption("torrent", 1, False)],
            [profile.MoveOption("tackle", [profile.LearnMethod("level-up", 1)])])

    def cached_resource_names(self, kind, name):
        return {"en": name}

    def species(self, species_id):
        return {"names": []}


EXTENSION_DIR = (
    Path(__file__).resolve().parent.parent
    / "gnome-extension"
    / "poketokenbar@huhgeon.github.io"
)


def full_payload() -> dict:
    """A payload with every optional block populated.

    Anything left empty here would let a missing key pass unnoticed, so the
    fixture is deliberately maximal rather than realistic.
    """
    store = CompanionStore(api=None, sprite_store=None)
    store.state = CompanionState(
        used_since_install=10**9,
        dex=[
            DexEntry(
                base_id=1, final_id=3, chain_order=[1, 2, 3], rarity=Rarity.COMMON,
                is_shiny=True, nature="brave", caught_at=1767312000.0,
                raised_seconds=3600,
            )
        ],
        active=MonState(
            base_id=4, path_ids=[4, 5, 6], planned_path_ids=[4, 5, 6], stage_index=1,
            rarity=Rarity.RARE, total_forms=3, nature="timid",
        ),
        inventory={"rareCandy": 2, "shinyCharm": 1},
    )
    migrate_profiles(store.state)
    store.api = _StubDetails()
    store.enrich_profiles()
    store.inspect(5)
    dex_rows = store.dex_payload()
    return state.build(
        {"claude_code": DailyUsage(date="2026-09-03", total_tokens=10, models={"m": 10})},
        {"show_tokens_in_menu": True, "show_cost_in_menu": True, "show_limit_in_menu": True},
        [],
        companion_payload=store.payload(),
        shop_payload=store.shop_payload(),
        bag_payload=store.bag_payload(),
        dex_payload=dex_rows,
        detail=store.detail_payload(dex_rows),
        catch_log=store.catch_log_payload(),
        rarity_counts=store.rarity_counts(),
        catch_counts=store.catch_rarity_counts(),
        periods={"week": {"tokens": 1, "cost": 0.0}, "month": {"tokens": 2, "cost": 0.0},
                 "month_daily": {time.strftime("%Y-%m-01"): {"tokens": 2, "cost": 0.0}}},
        burn={"session": {"rate_per_minute": 1.0, "minutes_to_full": 5, "eta_text": "x",
                          "before_reset": False}},
        update={"supported": True, "installed": "a" * 40, "installed_short": "aaaaaaa",
                "available": "b" * 40, "available_short": "bbbbbbb", "error": ""},
        blocks={"claude_code": BlockUsage(
            id="b", start_time="2026-09-03T00:00:00+00:00",
            end_time="2026-09-03T05:00:00+00:00", is_active=True,
            total_tokens=362_500_000, cost_usd=1.0, tokens_per_minute=50_000.0)},
        limit_status=limits.LimitStatus(
            session=limits.LimitWindow(utilization=42.0, resets_at="2h", severity="warn"),
            weekly=limits.LimitWindow(utilization=10.0, resets_at="5d", severity="ok"),
            # The model-scoped weekly window, which arrives only in limits[] —
            # the row a front end reading session/weekly alone is short of.
            scoped=[limits.ScopedWindow(
                kind="weekly_scoped", model="Fable",
                window=limits.LimitWindow(utilization=0.4, resets_at="6d",
                                          severity="ok"))],
            subscription_type="max",
            rate_limit_tier="default_claude_max_5x",
            account={"email": "x@example.com"},
        ),
        # The real shape from StatusChecker.get(). Healthy providers are
        # dropped there, so every row that reaches here is an incident.
        limit_accounts=_limit_accounts(),
        provider_status={
            "anthropic": {"label": "Major outage", "severity": "crit",
                          "indicator": "major"},
        },
        celebration={"kind": "hatch", "title": "t", "detail": "d"},
        settings={"providers": [{"id": "pi", "display_name": "Pi Agent",
                                 "custom_scan_roots": "", "matched_folders": 0}]},
        # The real shape from Daemon.transfer_payload(): a describe() of the
        # export file plus what it would replace.
        transfer={
            "path": "/home/somebody/poketokenbar-save.json",
            "exists": True,
            "error": None,
            "exported_at": 1767312000.0,
            "device": "desktop",
            "dex_count": 3,
            "used_since_install": 10**6,
            "items": 2,
            "current_dex_count": 5,
            "current_used_since_install": 10**7,
            "can_undo": True,
            "undo_taken_at": 1767312000.0,
            "undo_dex_count": 5,
            "undo_used_since_install": 10**7,
            # Built by the store rather than written out here: the settings
            # page reads these fields, so they have to be the real ones.
            "snapshots": _snapshot_rows(),
        },
        recap=_recap_view(store),
    )


def _limit_accounts():
    """Two Claude logins, as MultiAccountLimits reports them."""
    class _Source:
        last_error = "login expired"
        stale = True

    class _Account:
        source = _Source()

    default = limits.LimitStatus(
        session=limits.LimitWindow(utilization=42.0, resets_at="2h", severity="warn"),
        weekly=limits.LimitWindow(utilization=10.0, resets_at="5d", severity="ok"),
        subscription_type="max", account={"email": "me@example.com"})
    other = limits.LimitStatus(
        session=limits.LimitWindow(utilization=90.0, resets_at="1h", severity="crit"),
        subscription_type="pro", account={"email": "work@example.com"})
    return [("default", default, _Account()), (".claude-work", other, _Account())]


def _recap_view(store) -> dict:
    """A recap of the month the fixture's catch happened in, as the daemon
    builds it: a real period, real buckets, and the individual it collected."""
    from datetime import date, datetime, time as day_start

    from poketokenbar import ledger as ledger_module
    from poketokenbar import recap as recap_module

    caught = datetime.fromtimestamp(1767312000.0).date()
    ledger = ledger_module.Ledger()
    ledger.merge({
        (caught.replace(day=1) + timedelta(days=index)).isoformat(): (index + 1) * 1000
        for index in range(5)
    })
    period = recap_module.period_of("month", caught)
    return {
        "recap": recap_module.make(ledger, period, date.today()),
        "offset": 0,
        "graduated": store.graduated_between(
            datetime.combine(period.start, day_start()).timestamp(),
            datetime.combine(period.end, day_start()).timestamp(),
        ),
    }


def _snapshot_rows() -> list[dict]:
    """One real restore point, described as the daemon describes them."""
    folder = Path(tempfile.mkdtemp(prefix="ptb-snapshots-"))
    store = CompanionStore(save_path=folder / "companion.json", api=None, sprite_store=None)
    store.state = CompanionState(used_since_install=10**6)
    store.create_snapshot()
    return store.snapshot_rows()


_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_QUOTED = re.compile("'[^'\\n]*'" + '|"[^"\\n]*"')
_TEMPLATE = re.compile(r"`[^`]*`", re.S)
_INTERPOLATION = re.compile(r"\$\{([^{}]*)\}")


def _strip_literals(text: str) -> str:
    """Remove string text while keeping the code inside `${...}`.

    Dropping template literals whole was a real hole: every
    `${providerRow.matched_folders}` disappeared with them, so a typo in one
    passed. Only the literal halves go.
    """
    text = _TEMPLATE.sub(lambda m: " ".join(_INTERPOLATION.findall(m.group(0))), text)
    return _QUOTED.sub("''", text)


def source_files() -> list[Path]:
    return sorted(EXTENSION_DIR.rglob("*.js"))


def source_code(strip_strings: bool = False) -> list[str]:
    """Each file with its comments stripped, and optionally its string literals.

    Prose mentions API names — "matching limits.level() in the daemon" — and a
    message like 'state.json is not valid JSON' reads as a property access, so
    scanning either would fail the build over a sentence. The catalogue scan
    needs the strings, hence the switch.
    """
    out = []
    for path in source_files():
        text = _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", path.read_text(encoding="utf-8")))
        out.append(_strip_literals(text) if strip_strings else text)
    return out


@pytest.fixture(scope="module")
def payload():
    return full_payload()


@pytest.fixture(scope="module")
def companion_keys():
    """Both companion stages, unioned.

    The egg branch and the raising branch emit different keys — `egg_progress`
    exists only before the first hatch — so checking against one of them would
    fail every field belonging to the other.
    """
    store = CompanionStore(api=None, sprite_store=None)
    store.state = CompanionState()
    egg = set(store.payload())
    store.state = CompanionState(
        active=MonState(
            base_id=4, path_ids=[4, 5, 6], planned_path_ids=[4, 5, 6], stage_index=1,
            rarity=Rarity.RARE, total_forms=3, nature="timid",
        )
    )
    return egg | set(store.payload())


def test_the_extension_directory_is_where_the_tests_expect():
    assert EXTENSION_DIR.is_dir(), f"no extension at {EXTENSION_DIR}"
    assert (EXTENSION_DIR / "metadata.json").is_file()
    assert source_files(), "no JavaScript found"


# MARK: top-level blocks


# Every top-level key the extension may read off the parsed state.
def top_level_reads() -> set[str]:
    found: set[str] = set()
    pattern = re.compile(_NOT_A_MEMBER + r"state(?:\?)?\.(\w+)")
    for code in source_code(strip_strings=True):
        found.update(pattern.findall(code))
    return found


def test_every_top_level_block_the_extension_reads_exists(payload):
    # Reader methods and locals that share the name; they are not payload keys.
    not_payload = {"strings"}
    unknown = top_level_reads() - set(payload) - not_payload
    assert not unknown, f"extension reads state.{sorted(unknown)}, which the daemon never emits"


# MARK: per-block field names


# The lookbehind keeps `Main.panel.addToStatusArea` from reading as a payload
# access: the Shell's own panel shares the name with ours, and without it the
# test fails on a line that is entirely correct.
_NOT_A_MEMBER = r"(?<![.\w])"

BLOCK_ACCESSORS = {
    "companion": r"companion(?:\?)?\.(\w+)",
    "today": r"today(?:\?)?\.(\w+)",
    "panel": r"panel(?:\?)?\.(\w+)",
    "limits": r"limits(?:\?)?\.(\w+)",
    "transfer": r"transfer(?:\?)?\.(\w+)",
    "detail": r"detail(?:\?)?\.(\w+)",
    "recap": r"recap(?:\?)?\.(\w+)",
    "update": r"update(?:\?)?\.(\w+)",
}


def block_reads(expression: str) -> set[str]:
    pattern = re.compile(_NOT_A_MEMBER + expression)
    found: set[str] = set()
    for code in source_code(strip_strings=True):
        found.update(pattern.findall(code))
    return found


@pytest.mark.parametrize("block,expression", sorted(BLOCK_ACCESSORS.items()))
def test_fields_read_out_of_each_block_exist(block, expression, payload, companion_keys):
    emitted = companion_keys if block == "companion" else set(payload[block])
    # Locals and helpers that happen to match the accessor shape.
    ignore = {"session", "weekly", "text", "forEach", "map", "filter", "length", "slice"}
    unknown = block_reads(expression) - emitted - ignore
    assert not unknown, (
        f"extension reads {block}.{sorted(unknown)}; "
        f"{block} actually carries {sorted(emitted)}"
    )


# MARK: list row fields, read through their own loop variable
#
# The sections deliberately name each loop variable after its block, so a field
# read off a shop row cannot be checked against a bag row's keys. Union-ing them
# would make every one of these assertions weaker than the bug it is for.


ROW_ACCESSORS = {
    "shopItem": "shop",
    "bagItem": "bag",
    # The candy ladder hangs off the one bag row that has stages to preview.
    "candy": "bag_candy",
    "dexEntry": "dex",
    "catchRecord": "catch_log",
    "modelRow": "today_models",
    "evoStage": "evo_line",
    "chainStage": "catch_chain",
    "limitWindow": "limit_window",
    "panelWindow": "panel_window",
    "providerRow": "settings_provider",
    "usageRow": "provider_usage",
    "burnRow": "burn_window",
    "forecast": "burn_window",
    "block": "active_block",
    "providerStatus": "provider_status",
    "config": "config",
    "dexRow": "dex",
    "periodRow": "period",
    "monthTrend": "month_trend",
    "trendDay": "month_trend_day",
    "todayRow": "month_trend_day",
    "snapshotRow": "snapshot",
    "recapBucket": "recap_bucket",
    "unownForm": "unown_form",
    "limitAccount": "limit_account",
    "graduatedRow": "recap_graduated",
    "individual": "detail_individual",
    "statRow": "detail_stat",
    "knownMove": "detail_known_move",
    "baseStat": "detail_base_stat",
    "species": "detail_species",
    "speciesMove": "detail_species_move",
    "update": "update",
}


def row_keys(name: str, payload: dict) -> set[str]:
    """The keys a row of that kind actually carries, taken from a real payload."""
    if name == "today_models":
        return set(payload["today"]["models"][0])
    if name == "limit_window":
        return set(payload["limits"]["session"])
    if name == "provider_usage":
        return set(payload["providers"]["claude_code"])
    if name == "burn_window":
        return set(payload["burn"]["session"])
    if name == "active_block":
        return set(payload["blocks"]["claude_code"])
    if name == "provider_status":
        return set(payload["provider_status"]["anthropic"])
    if name == "settings_provider":
        return set(payload["settings"]["providers"][0])
    if name == "update":
        return set(payload["update"])
    if name == "config":
        # Not the fixture's config, which is a stub: the real defaults, because
        # config.load drops any key that has no default and the setting would
        # then silently do nothing.
        from poketokenbar import config as config_module

        return set(config_module.DEFAULTS)
    if name == "panel_window":
        # Deliberately separate from limit_window: the panel row carries text
        # and a level already resolved, the popup row the raw utilisation.
        return set(payload["panel"]["limit_windows"][0])
    if name == "evo_line":
        # The evolution line is only built when a sprite store is present, so a
        # stub stands in — the field names are what is being checked, not the
        # paths.
        store = CompanionStore(api=None, sprite_store=_StubSprites())
        store.state = CompanionState(
            active=MonState(
                base_id=4, path_ids=[4, 5, 6], planned_path_ids=[4, 5, 6],
                stage_index=1, rarity=Rarity.RARE, total_forms=3,
            )
        )
        return set(store.payload()["evo_line"][0])
    if name == "catch_chain":
        return set(payload["catch_log"][0]["chain"][0])
    if name == "limit_account":
        return set(payload["limits"]["accounts"][0])
    if name == "unown_form":
        store = CompanionStore(api=None, sprite_store=_StubSprites())
        store.state = CompanionState(
            dex=[DexEntry(base_id=201, final_id=201, chain_order=[201],
                          rarity=Rarity.RARE, unown_form="b")])
        store.inspect(201)
        return set(store.detail_payload()["unown_forms"][0])
    if name == "recap_bucket":
        return set(payload["recap"]["buckets"][0])
    if name == "recap_graduated":
        return set(payload["recap"]["graduated"][0])
    if name == "snapshot":
        return set(payload["transfer"]["snapshots"][0])
    if name == "bag_candy":
        return set(next(r for r in payload["bag"] if r["key"] == "rareCandy")["candy"])
    if name == "month_trend":
        return set(payload["month_trend"])
    if name == "month_trend_day":
        return set(payload["month_trend"]["days"][0])
    if name == "period":
        return set(payload["periods"]["week"])
    if name.startswith("detail_"):
        detail = payload["detail"]
        individual = detail["individuals"][0]
        return set({
            "detail_individual": individual,
            "detail_stat": individual["stats"][0],
            "detail_known_move": individual["moves"][0],
            "detail_base_stat": detail["species"]["base_stats"][0],
            "detail_species": detail["species"],
            "detail_species_move": detail["species"]["moves"][0],
        }[name])
    return set(payload[name][0])


@pytest.mark.parametrize("variable,block", sorted(ROW_ACCESSORS.items()))
def test_row_fields_read_in_the_extension_exist(variable, block, payload):
    pattern = rf"{variable}(?:\?)?\.(\w+)"
    unknown = block_reads(pattern) - row_keys(block, payload)
    assert not unknown, (
        f"extension reads {variable}.{sorted(unknown)}; "
        f"a {block} row carries {sorted(row_keys(block, payload))}"
    )


# MARK: list row shapes


LIST_ROW_FIELDS = {
    "shop": {"key", "kind", "price", "price_text", "label", "description", "badge",
             "sprite_path", "emoji", "owned", "owned_count", "affordable", "locked", "rarity",
             "max_buy", "release_note"},
    "bag": {"key", "label", "description", "effect", "sprite_path", "emoji", "count",
            "usable", "passive"},
    "dex": {"final_id", "species_id", "name", "rarity", "is_shiny", "has_normal",
            "is_raising", "is_pinned", "sprite_path", "search", "form_count_text"},
}

# Fields only some rows in a block carry — the candy ladder belongs to the one
# item that has stages to preview.
OPTIONAL_ROW_FIELDS = {"bag": {"candy"}}


@pytest.mark.parametrize("block", sorted(LIST_ROW_FIELDS))
def test_list_row_fields_match_what_the_daemon_emits(block, payload):
    """Pins the row shape itself, so a rename on either side is a failure here
    rather than a blank column in the popup."""
    rows = payload[block]
    assert rows, f"{block} fixture produced no rows"
    optional = OPTIONAL_ROW_FIELDS.get(block, set())
    for row in rows:
        assert set(row) - optional == LIST_ROW_FIELDS[block]


def test_the_candy_row_carries_the_ladder_the_popup_previews_from(payload):
    candy = next(row for row in payload["bag"] if row["key"] == "rareCandy")
    assert set(candy["candy"]) == {
        "xp", "xp_text", "effect_template", "max_use", "stage_costs", "used_at_stage"}


def test_catch_log_row_shape(payload):
    row = payload["catch_log"][0]
    assert set(row) == {
        "rarity", "nature", "is_shiny", "chain", "caught_at", "raised_text", "raising",
        "released", "search", "species_id", "name",
    }
    assert set(row["chain"][0]) == {"species_id", "name", "sprite_path"}


# MARK: strings


def test_every_string_key_the_extension_asks_for_is_in_the_catalogue(payload):
    """`text('foo')` falls back to the key itself, so a typo shows as raw text
    in the UI instead of failing."""
    # Both spellings: the reader method, and the `t` alias each section binds.
    pattern = re.compile(r"""(?:\.text|\bt)\(\s*['"]([a-z0-9_]+)['"]\s*\)""")
    asked: set[str] = set()
    for code in source_code():
        asked.update(pattern.findall(code))
    assert asked, "no catalogue lookups found; has the accessor been renamed?"
    unknown = asked - set(payload["strings"])
    assert not unknown, f"extension asks for strings {sorted(unknown)} that do not exist"


# MARK: commands


def test_every_command_the_extension_sends_is_one_the_daemon_drains():
    """A command name the daemon does not know is dropped in silence."""
    source = (EXTENSION_DIR / "lib" / "commands.js").read_text(encoding="utf-8")
    sent = set(re.findall(r"""enqueue\(\s*['"](\w+)['"]""", source))
    daemon = (
        Path(__file__).resolve().parent.parent / "poketokenbar" / "daemon.py"
    ).read_text(encoding="utf-8")
    handled = set(re.findall(r"""name\s*==\s*['"](\w+)['"]""", daemon))
    handled.update(re.findall(r"""name\s+in\s+\(([^)]*)\)""", daemon)[0].replace(
        '"', "").replace("'", "").replace(" ", "").split(",")
        if re.findall(r"""name\s+in\s+\(([^)]*)\)""", daemon) else [])
    for group in re.findall(r"""name\s+in\s+\(([^)]*)\)""", daemon):
        handled.update(part.strip().strip("\"'") for part in group.split(","))
    unknown = sent - handled
    assert not unknown, f"extension sends {sorted(unknown)}, which the daemon ignores"


def test_the_settings_block_lists_every_provider(payload):
    """The settings page has no other source for the provider list."""
    assert "providers" in payload["settings"]
    row = payload["settings"]["providers"][0]
    assert set(row) == {"id", "display_name", "custom_scan_roots", "matched_folders"}
    assert set(providers.registered_ids())  # registry is non-empty


def test_every_settings_toggle_maps_to_a_real_default():
    """A switch bound to a key with no default flips and changes nothing:
    config.load drops it on the next read."""
    from poketokenbar import config as config_module

    source = (EXTENSION_DIR / "lib" / "sections.js").read_text(encoding="utf-8")
    keys = set(re.findall(r"""\{\s*key:\s*['"](\w+)['"]""", source))
    assert keys, "no declared toggles found; has TOGGLES been renamed?"
    unknown = keys - set(config_module.DEFAULTS)
    assert not unknown, f"settings toggles with no daemon default: {sorted(unknown)}"


def test_every_settings_toggle_labels_itself_from_the_catalogue(payload):
    source = (EXTENSION_DIR / "lib" / "sections.js").read_text(encoding="utf-8")
    strings = set(re.findall(r"""string:\s*['"](\w+)['"]""", source))
    unknown = strings - set(payload["strings"])
    assert not unknown, f"toggle labels with no catalogue entry: {sorted(unknown)}"


# MARK: the check that keeps the checks honest


# Names that are not payload data: Shell APIs, JavaScript built-ins, and the
# extension's own locals. Anything else holding snake_case fields is a payload
# access and has to be declared above.
_NOT_PAYLOAD = {
    # imported namespaces and classes
    "this", "super", "Main", "Clutter", "GObject", "St", "Gio", "GLib", "Cogl",
    "GdkPixbuf", "Math", "JSON", "Object", "Commands", "Config", "PopupMenu",
    "PanelMenu", "Extension", "Sprite", "console", "Number", "String", "Array",
    "Date", "TextDecoder", "TextEncoder",
    # locals
    "e", "_e", "path", "file", "temp", "final", "animation", "iter", "pixbuf",
    "content", "frame", "result", "entry", "widget", "box", "meter", "sprite",
    "toggle", "tab", "cell", "item", "clickable", "chain", "line", "caption",
    "spacer", "price", "buy", "banner", "name", "key", "children", "stages",
    "work", "event", "menu", "section", "reader", "target", "values", "roots",
    "payload", "obj", "parsed", "metadata", "css", "source", "text", "label",
    "pattern", "found", "out", "stem", "dir", "connection", "doc", "left",
    "details", "store", "currentRow", "summary", "buttons",
    # GLib.TimeVal's own fields. It is a boxed type the sprite decoder drives
    # by hand, not anything the daemon emits — and it is snake_case like every
    # payload field, which is the only reason it lands here.
    "timeVal",
    # Top-level access has its own test; repeating it here would only duplicate
    # the failure message.
    "state",
}

# Clutter actor layout properties. Every section sets these on its own widgets,
# and no payload row carries a field by these names.
_ACTOR_LAYOUT = {"x_expand", "y_expand", "x_align", "y_align"}

# The negative lookahead is what separates data from API: St and Clutter methods
# are snake_case too (`add_child`, `set_size`), and listing them by name would be
# a list to maintain forever. A payload field is never called.
# `(?!\w)` first, or the greedy \w+ backtracks to `add_chil` and satisfies the
# lookahead on the `d` that follows.
_ACCESS = re.compile(r"(?<![.\w])([a-zA-Z_]\w*)(?:\?)?\.(\w+)(?!\w)(?!\s*\()")


def test_every_row_variable_is_bound_where_it_is_used():
    """A row variable used outside the loop that binds it is a crash.

    It shipped once: a rename swept `individual.is_shiny` into
    `graduatedRow.is_shiny` inside the Pokédex page, where nothing binds that
    name, and opening a Pokémon's page threw ReferenceError — the popup went
    blank on the tap. Nothing caught it, because the name is a real accessor
    and the field is a real field of its own block, and a page whose species
    details had not loaded never reached the line.

    The rule that catches it: in the method where a row variable is read, it
    has to appear at least once *not* as `name.field` — as a parameter, a
    destructured element, or an assignment. A stray rename leaves only field
    reads behind, which is exactly what this looks for.
    """
    loose: dict[str, list[str]] = {}
    for path in source_files():
        code = _strip_literals(path.read_text(encoding="utf-8"))
        # Comments name these variables while explaining them, which is not a
        # use; only code counts.
        code = re.sub(r"//[^\n]*", "", code)
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
        # One method at a time: a name bound in another method is out of scope
        # here, which is the whole point.
        for body in re.split(r"\n    (?=[_A-Za-z]\w*\()", code):
            for name in ROW_ACCESSORS:
                reads = re.findall(rf"(?<![.\w]){re.escape(name)}(?![\w])", body)
                if not reads:
                    continue
                fields = re.findall(rf"(?<![.\w]){re.escape(name)}(?=\?\.|\.)", body)
                if len(reads) == len(fields):
                    loose.setdefault(path.name, []).append(name)
    assert not loose, (
        "these row variables are only ever read, never bound, in the method "
        "that uses them: " + str({k: sorted(set(v)) for k, v in loose.items()})
    )


def test_no_payload_access_escapes_the_declared_accessors():
    """Every snake_case field read must belong to a declared accessor.

    Without this the coverage is only as good as the list, and the list was
    already short: `burn.forecast_text` sat unchecked and turned out to name a
    field the daemon never emitted, so the burn forecast simply never appeared.

    A new block therefore has to be added to BLOCK_ACCESSORS or ROW_ACCESSORS
    before its fields can be read at all — which is the point.
    """
    declared = set(BLOCK_ACCESSORS) | set(ROW_ACCESSORS)
    escaped: dict[str, list[str]] = {}
    for code in source_code(strip_strings=True):
        for variable, field in _ACCESS.findall(code):
            if variable in declared or variable in _NOT_PAYLOAD or variable[0].isupper():
                continue
            if "_" not in field:
                continue  # a method or a plain property, not a payload field
            if field in _ACTOR_LAYOUT:
                continue  # set on a widget, never read from the payload
            escaped.setdefault(variable, []).append(field)
    assert not escaped, (
        "these read payload-shaped fields but are not declared accessors: "
        + str({k: sorted(set(v)) for k, v in escaped.items()})
    )


def test_every_daemon_setting_is_reachable_from_the_ui():
    """A setting nobody can change may as well not exist.

    The daemon owns seventeen; the extension exposed four for a while, and the
    rest were reachable only from poketokenctl. The exceptions below are the
    ones a UI genuinely should not offer, each with its reason.
    """
    from poketokenbar import config as config_module

    source = "\n".join(
        p.read_text(encoding="utf-8") for p in (EXTENSION_DIR / "lib").glob("*.js")
    )
    # Every declaration table names its setting as `{key: '...'}`, whether or
    # not the brace and the key share a line, and anything set directly names
    # it in the Config.set call.
    reachable = set(re.findall(r"""\{\s*key:\s*['"](\w+)['"]""", source))
    reachable.update(re.findall(r"""Config\.set\(\s*['"](\w+)['"]""", source))

    not_for_the_ui = {
        # Written by dragging the pet, not by typing a coordinate.
        "floating_pet_x",
        "floating_pet_y",
        # Edited per provider through its own field, not as one blob.
        "custom_scan_roots",
        # Chosen from the language row.
        "language",
    }
    missing = set(config_module.DEFAULTS) - reachable - not_for_the_ui
    assert not missing, f"settings with no control anywhere in the UI: {sorted(missing)}"


# MARK: the rows the popup is expected to draw
#
# Reading a field is not the same as drawing it, and these went missing the
# other way round: the daemon shipped them and the extension read none of them,
# so a GNOME user saw less than a Windows user from the same state.json.


def test_the_popup_reads_every_limit_window_the_account_has(payload):
    """seven_day_opus and seven_day_sonnet are null now, so a model's weekly
    limit arrives only in limits[]. Reading session and weekly alone is a row
    short of what is actually in force."""
    source = "\n".join(source_code(strip_strings=True))
    assert "limits.scoped" in source, "the model-scoped weekly windows are not read"
    assert payload["limits"]["scoped"], "the fixture has no scoped window to read"


def test_the_popup_names_the_plan_the_way_the_daemon_built_it(payload):
    """Upper-casing the raw type printed "MAX" and lost the 5x, which is the
    part that says how many tokens the percentage is."""
    source = "\n".join(source_code(strip_strings=True))
    assert "limits.plan_text" in source
    assert "limits.plan" not in source.replace("limits.plan_text", ""), (
        "the plan is being built in the front end")
    assert "limits.account_text" in source


def test_the_popup_draws_the_rolling_block(payload):
    """What has been spent inside the current window, and where the forecast's
    rate comes from."""
    source = "\n".join(source_code(strip_strings=True))
    assert "blocks" in source
    assert payload["blocks"]["claude_code"]["total_tokens_compact"]


def test_the_popup_renders_both_forecast_outcomes(payload):
    """Reaching the limit is a warning with a time on it; not reaching it is
    the reassurance shown most of the time. Only the first was drawn, so the
    row was blank in the ordinary case."""
    source = "\n".join(source_code(strip_strings=True))
    assert "before_reset" in source
    assert "no_limit_before_reset" in "\n".join(source_code())
    assert "before_reset" in payload["burn"]["session"]


def test_the_pokedex_can_release_a_pin_as_well_as_set_one(payload):
    """Tapping a cell only ever pinned, so the way back to the companion was
    the settings dropdown — and nothing in the grid said which species was
    pinned in the first place."""
    source = "\n".join(source_code(strip_strings=True))
    # Which species holds the panel: the grid badges its cell, and Home names
    # it. Either is enough for the question "why is the panel showing that?"
    assert "is_pinned" in source or "representative_species_id" in source, (
        "nothing reads which species is pinned")
    with_strings = "\n".join(source_code())
    assert re.search(r"Commands\.represent\(\s*(pinned \? )?(null|'')", with_strings), (
        "there is no release; null is what the daemon reads as "
        "'follow the companion again'"
    )
    assert "representative_id" in payload["panel"]


def test_the_popup_offers_the_update_the_daemon_can_apply(payload):
    """Without it a fix means finding the repo again and re-running install.sh,
    which is enough friction that one nobody installs may as well not exist."""
    source = "\n".join(source_code(strip_strings=True))
    assert "update.available" in source
    assert "update.installed_short" in source
    with_strings = "\n".join(source_code())
    assert "enqueue('update'" in with_strings, "nothing asks the daemon to apply it"
    assert "update.supported" in source, (
        "a checkout cannot be updated by overwriting it, and a button that "
        "refuses is worse than a sentence saying why"
    )
    assert set(payload["update"]) >= {"supported", "installed_short", "available_short"}
