"""Ties the companion engine to live usage — ports CompanionStore.swift.

Providers report cumulative totals for *today*, not deltas. This converts them
into deltas by remembering what has already been credited per provider, which
is why the baseline is tracked per provider id rather than in aggregate: a
single total cannot be decomposed when one provider resets and another does not.
"""

from __future__ import annotations

import random
import time as _time
import unicodedata
from datetime import date as _date
from pathlib import Path

from . import (balance, companion, forms, l10n, pokeapi, profile, save, shop,
               snapshots, sprites, transfer)
from .companion import CompanionState
from .format import compact as _compact


def _fold(text: str) -> str:
    """Lowercased and stripped of diacritics, for search matching.

    "Flabébé" and "flabebe" have to be the same word to a search box; the same
    fold runs in the popup on the query.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Recomposed, or a Hangul syllable would be left as loose jamo and every
    # Korean name would only match a query decomposed exactly the same way.
    return unicodedata.normalize("NFC", stripped).casefold()


def _duration(seconds: float | None, language: str = "en") -> str:
    """How long a Pokémon was raised, as upstream's catch log words it."""
    if not seconds or seconds <= 0:
        return ""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    if days > 0:
        return l10n.t("duration_days_hours", language).replace("%1", str(days)).replace("%2", str(hours))
    if hours > 0:
        return l10n.t("duration_hours_minutes", language).replace("%1", str(hours)).replace("%2", str(minutes))
    return l10n.t("duration_minutes", language).replace("%1", str(minutes))


class CompanionStore:
    def __init__(
        self,
        save_path: Path | None = None,
        api: pokeapi.PokeAPI | None = None,
        sprite_store: sprites.SpriteStore | None = None,
        rng: random.Random | None = None,
        detail_loader=None,
    ) -> None:
        # Resolved here rather than left as None: save() falls back to the
        # default path on its own, so a store built without one still had a
        # file — but everything that has to name that file (restore points,
        # most of all) saw None and quietly did nothing.
        self.save_path = save_path or save.default_path()
        # What the save last said, and how many times it has changed. The
        # Pokedex grid and the catch log are built from the save alone, so
        # they are rebuilt when this moves and reused when it does not. Set
        # before anything can persist: the migration below does.
        self._saved_text: str | None = None
        self._revision = 0
        self._dex_rows: tuple | None = None
        self._catch_rows: tuple | None = None
        # Restore points, described once and kept until this process changes
        # them; the popup asks for them on every poll.
        self._snapshot_rows: list[dict] | None = None
        # A save that will not parse is rebuilt from the newest restore point
        # rather than started over (upstream 13e3bf2).
        self.state: CompanionState = save.load(
            self.save_path, recover=snapshots.latest_valid)
        # What loading had to put back inside the rules, for the daemon to
        # report once. A save is repaired in silence otherwise, and the first
        # sign is a Pokemon that looks wrong. Read straight away: anything that
        # decodes another save — listing restore points, for one — replaces it.
        self.save_repairs: list[str] = list(save.last_repairs)
        self.migrate_profiles()
        self.api = api
        # Fetches species details in the background; None means only what is
        # already cached is used (and in tests, nothing is fetched at all).
        self.detail_loader = detail_loader
        self.sprites = sprite_store
        self.rng = rng or random.Random()
        # Set by the daemon from config each poll, the way the language is.
        # False keeps a pin where it is when the Pokemon graduates.
        self.release_pin_on_graduation = False
        # Held for one poll so the popup can show a celebration banner; the
        # notification fires immediately but the banner needs a render pass.
        self.celebration: dict | None = None
        self.last_events: companion.GrowthEvents | None = None
        # The species whose Pokédex page is open. Not saved: it is where the
        # popup is looking, not progress.
        self.inspected_species_id: int | None = None
        # Which appearance the open page is about; None otherwise.
        self.inspected_form: str | None = None

    def migrate_profiles(self) -> None:
        """Give an older save's Pokémon their profiles, once.

        Called on load and after an import replaces the state. The first time
        a save on disk changes shape, the file as it was is copied beside it,
        and that copy is never overwritten.
        """
        if not companion.migrate_profiles(self.state):
            return
        path = self.save_path or save.default_path()
        backup = path.with_name(path.stem + ".pre-profiles-v1" + path.suffix)
        try:
            if path.is_file() and not backup.exists():
                backup.write_bytes(path.read_bytes())
        except OSError:
            pass  # a failed backup must not stop the save from loading
        self._persist()

    def cached_details(self, species_id: int):
        """Species details if cached, else None. Never waits on the network."""
        lookup = getattr(self.api, "cached_details", None)
        if lookup is None:
            return None
        try:
            return lookup(species_id)
        except Exception:
            return None

    def enrich_profiles(self) -> bool:
        """Fill gender, ability and moves wherever species details are cached.

        Ports upstream's enrichProfiles and preparePokemonProfiles. Runs on
        every publish, so a profile catches up as soon as its details arrive
        and moves follow the level as it rises. Only the companion's details
        are fetched unasked; a dex entry's arrive when its page is opened.
        Returns whether any profile changed, having saved if so.
        """
        targets = []
        mon = self.state.active
        if mon is not None and mon.profile is not None:
            targets.append((mon.current_id, mon.profile, True))
        for entry in self.state.dex:
            if entry.profile is not None:
                targets.append((entry.final_id, entry.profile, False))

        changed = False
        for species_id, individual, is_active in targets:
            details = self.cached_details(species_id)
            if details is None:
                if is_active and self.detail_loader is not None:
                    self.detail_loader.request_details(species_id)
                continue
            before = save._encode_profile(individual)
            profile.enrich(individual, details)
            if save._encode_profile(individual) != before:
                changed = True
        if changed:
            self._persist()
        return changed

    # --- the Pokédex detail page (upstream b6bf676) ----------------------------

    def inspect(self, species_id: int | None, retry: bool = False,
                form: str | None = None) -> None:
        """Open a species' page, or close it with None.

        Only an owned species opens: the page is built from the save, and a
        species nobody has would be a page of nothing.
        """
        if species_id is None or not self.state.owns_species(species_id):
            self.inspected_species_id = None
            self.inspected_form = None
            return
        self.inspected_species_id = species_id
        # Which appearance the page is about. None picks one that is actually
        # collected, so the page never opens on a form nobody has.
        if forms.has_forms(species_id):
            collected = self.state.collected_forms(species_id)
            chosen = forms.resolved(species_id, form)
            self.inspected_form = (
                chosen if chosen in collected
                else self._representative_letter(species_id, collected)
            )
        else:
            self.inspected_form = None
        if self.detail_loader is not None:
            self.detail_loader.request_details(species_id, retry=retry)

    def individuals(self, species_id: int, form: str | None = None
                    ) -> list[tuple[companion.DexEntry | None, object, bool]]:
        """(dex entry or None for the companion, profile, is_shiny) for a species.

        Ports pokemonIndividuals: the companion first when it is this species
        now, then graduated and released individuals that ended as it, newest
        first. An earlier stage of a line has no individual of its own; its
        page is a species reference.
        """
        def form_of(record) -> str | None:
            return forms.resolved(species_id, record.form)

        wanted = forms.resolved(species_id, form) if form else None
        out = []
        mon = self.state.active
        if mon is not None and mon.profile is not None and mon.current_id == species_id:
            shiny = mon.displays_shiny
            if wanted is None or form_of(mon) == wanted:
                out.append((None, mon.profile, shiny))
        stored = [e for e in self.state.dex if e.final_id == species_id and e.profile is not None]
        if wanted is not None:
            stored = [e for e in stored if form_of(e) == wanted]
        stored.sort(key=lambda e: e.caught_at or 0, reverse=True)
        out.extend((e, e.profile, e.is_shiny) for e in stored)
        return out

    def _resource_name(self, kind: str, slug: str, fallback: str | None = None) -> str:
        """A type, ability, move or form name in the UI language.

        "…" while its name is on the way, as upstream 1a8a725 does, so the
        page never flashes English first; `fallback` — or the slug made
        readable — when no name will come. A form's slug is a resource number,
        which reads as nothing, so those pass their own.
        """
        language = self.state.language
        lookup = getattr(self.api, "cached_resource_names", None)
        names = lookup(kind, slug) if lookup is not None else None
        if names:
            resolved = l10n.resolve_name(names, language)
            if resolved:
                return resolved
        elif self.detail_loader is not None:
            self.detail_loader.request_names(kind, [slug])
            if not self.detail_loader.names_failed(kind, slug):
                return "\N{HORIZONTAL ELLIPSIS}"
        return fallback if fallback else slug.replace("-", " ").title()

    def _move_methods(self, move) -> str:
        language = self.state.language
        words = []
        for method in move.learn_methods:
            if method.method == "level-up":
                word = f"Lv. {method.level}" if method.level > 0 else l10n.t("move_method_start", language)
            elif method.method == "machine":
                word = "TM"
            elif method.method in ("egg", "tutor"):
                word = l10n.t(f"move_method_{method.method}", language)
            else:
                word = method.method.replace("-", " ")
            if word not in words:
                words.append(word)
        return " · ".join(words)

    def detail_payload(self, dex_rows: list[dict] | None = None) -> dict | None:
        """The open page, every label already in the UI language."""
        species_id = self.inspected_species_id
        if species_id is None:
            return None
        if not self.state.owns_species(species_id):
            # Released by an import or a reveal while the page was open.
            self.inspected_species_id = None
            return None
        language = self.state.language
        t = lambda key: l10n.t(key, language)  # noqa: E731
        row = next((r for r in dex_rows or [] if r.get("species_id") == species_id), {})
        details = self.cached_details(species_id)
        loader = self.detail_loader
        if details is not None:
            status = "ready"
        elif loader is not None and loader.has_failed(species_id):
            status = "failed"
        else:
            status = "loading"
            if loader is not None:
                loader.request_details(species_id)

        letter = self.inspected_form if forms.has_forms(species_id) else None
        individuals = []
        found = self.individuals(species_id, letter)
        for index, (entry, individual, shiny) in enumerate(found):
            nature = entry.nature if entry is not None else self.state.active.nature
            # Enrichment already ran this publish (enrich_profiles), on the
            # one path that saves what it changes.
            ability = "—"
            if individual.ability_name:
                ability = self._resource_name("ability", individual.ability_name)
                if individual.ability_is_hidden:
                    ability = f"{ability} · {t('hidden_ability')}"
            stats = []
            if details is not None:
                computed = profile.compute_stats(details, individual, nature)
                scale = profile.display_scale_maximum([s.value for s in computed])
                stats = [
                    {"label": t("stat_" + s.name.replace("-", "_")), "value": s.value,
                     "iv": s.iv, "fraction": round(s.value / scale, 4)}
                    for s in computed
                ]
            appearance = (
                f"\N{SPARKLES} {t('shiny')}" if shiny else t('dex_normal_label')
            )
            # When it was caught, or that it is the one being raised. The
            # appearance belongs here too, because the picker is now filtered by
            # it and "#2" alone says nothing about which one is on screen
            # (upstream 4bfae97).
            caught = entry.caught_at if entry is not None else None
            when = (
                _time.strftime("%Y-%m-%d", _time.localtime(caught)) if caught
                else (t("raising") if entry is None else "—")
            )
            individuals.append({
                "instance_id": individual.instance_id,
                "label": f"#{index + 1} · {appearance} · Lv. {individual.level} · {when}",
                "is_active": entry is None,
                "is_released": entry is not None and entry.is_released,
                "is_shiny": shiny,
                "level": individual.level,
                "gender_text": t(f"gender_{individual.gender}") if individual.gender else "—",
                "nature_text": l10n.nature_name(nature, language) or "—",
                "ability_text": ability,
                "stats": stats,
                "moves": [
                    {"name": self._resource_name("move", m.name), "level": m.learned_at_level}
                    for m in individual.moves
                ],
            })

        species = None
        if details is not None:
            species = {
                "types": [self._resource_name("type", name) for name in details.types],
                # The API's own names as well, for the badge colours: the names
                # above are translated and cannot be keyed on (upstream
                # 46d5d91).
                "type_keys": list(details.types),
                "height_text": f"{details.height / 10:.1f} m",
                "weight_text": f"{details.weight / 10:.1f} kg",
                "base_total": details.base_stat_total,
                "base_stats": [
                    {"label": t("stat_" + name.replace("-", "_")),
                     "value": details.base_stats[name],
                     "fraction": round(min(1.0, details.base_stats[name] / 300), 4)}
                    for name in profile.STAT_ORDER if name in details.base_stats
                ],
                "abilities": [
                    self._resource_name("ability", a.name)
                    + (f" ({t('hidden')})" if a.is_hidden else "")
                    for a in details.abilities
                ],
                "moves": [
                    {"name": self._resource_name("move", m.name), "methods": self._move_methods(m)}
                    for m in details.moves
                ],
            }

        # Both colours, so the page can follow the appearance picker without a
        # round trip; either can be empty when its sprite has not been cached.
        def sprite_for(shiny: bool) -> str:
            if self.sprites is None:
                return ""
            path = self.sprites.path(species_id, animated=True, shiny=shiny, form=letter)
            return str(path) if path else ""

        default_shiny = found[0][2] if found else bool(row.get("is_shiny"))
        return {
            "species_id": species_id,
            "name": self.individual_name(species_id, letter),
            # The species' appearances: which are collected, and which this
            # page is about. Empty for a species that has only one.
            "form": letter or "",
            "forms": self._form_rows(species_id, letter),
            "forms_text": (
                l10n.fill("forms_collected", language,
                          str(len(self.state.collected_forms(species_id))),
                          str(len(forms.forms(species_id))))
                if forms.has_forms(species_id) else ""
            ),
            "rarity": row.get("rarity", ""),
            "is_shiny": bool(row.get("is_shiny")),
            # Which appearances this species has actually been collected in.
            "has_normal": bool(row.get("has_normal")),
            "sprite_path_normal": sprite_for(False),
            "sprite_path_shiny": sprite_for(True),
            "is_raising": bool(row.get("is_raising")),
            "is_pinned": self.state.representative_species_id == species_id,
            "sprite_path": sprite_for(default_shiny),
            "status": status,
            "individuals": individuals,
            "species": species,
            "move_count": len(details.moves) if details is not None else 0,
        }

    # --- usage -------------------------------------------------------------

    def update(self, totals_by_provider: dict[str, int], today: str | None = None) -> None:
        """Credit the growth of today's usage since the last update."""
        today = today or _date.today().strftime("%Y-%m-%d")

        # The None sentinel must be checked BEFORE the day rollover, or a
        # fresh save (last_date == "") takes the rollover branch, loses the
        # sentinel, and credits the whole existing day retroactively.
        if self.state.claimed_today_tokens_by_provider is None:
            # First run: seed the baseline, granting nothing for past usage.
            self.state.claimed_today_tokens_by_provider = dict(totals_by_provider)
            self.state.install_baseline_set = True
            self.state.last_date = today
            self._persist()
            return

        # A new day restarts every provider's "today" total at zero, so the
        # old baselines would make every delta negative. Clearing them lets the
        # new day's usage count from zero, which is real usage, not a re-count.
        if self.state.last_date != today:
            self.state.last_date = today
            self.state.claimed_today_tokens_by_provider = {}

        claimed = self.state.claimed_today_tokens_by_provider

        delta = 0
        for provider_id, total in totals_by_provider.items():
            previous = claimed.get(provider_id, 0)
            # A total going backwards (log rotation, cache rebuild) must not
            # produce a negative delta.
            if total > previous:
                delta += total - previous
            claimed[provider_id] = total

        waiting_to_hatch = (
            self.state.active is None
            and self.state.egg_usage >= self.state.egg_hatch_threshold
        )
        if delta <= 0 and not waiting_to_hatch:
            self._persist()
            return

        # An egg that has earned its hatch but could not be given a species —
        # offline, or the API failed — used to wait for the next token delta to
        # try again. On a machine that has stopped working for the day that
        # never comes, and the egg sits ready for ever (upstream 2ecf7d2).
        line = self._line_for_egg() if self.state.active is None else None
        if delta <= 0 and line is None:
            self._persist()
            return
        events = companion.apply_usage(
            self.state, delta, line_for_egg=line, rng=self.rng,
            release_pin_on_graduation=self.release_pin_on_graduation
        )
        self._record_events(events)
        self._note_celebration(events)
        self._persist()

    def _record_events(self, events) -> None:
        """Queue growth events for the one announcement this poll makes.

        Folded rather than assigned: an item used earlier in the same poll has
        already left its events here, and overwriting them is how a candy's
        evolution went unannounced whenever any real usage landed alongside it.
        """
        self.last_events = (
            events if self.last_events is None else self.last_events.merge(events)
        )

    def _note_celebration(self, events) -> bool:
        """Build the banner the popup shows once, in the user's language.

        Returns whether one was built, so an item use can fall back to
        announcing itself when nothing hatched, evolved or graduated.

        Shares the notification catalogue rather than carrying a second set of
        words: the banner and the toast announce the same event, and two
        wordings for one thing is how they drift apart. They were English
        literals before, which made them the largest untranslated surface in a
        UI that is otherwise fully localized.
        """
        if events is None:
            return False
        mon = self.state.active
        language = self.state.language
        name = self.species_name(mon.current_id, language) if mon else ""
        label = name or l10n.t("raising", language)
        shiny = mon is not None and mon.displays_shiny

        def banner(kind: str, title_key: str, body_key: str, *subjects: str) -> dict:
            return {
                "kind": kind,
                "title": l10n.t(title_key, language),
                "detail": l10n.fill(body_key, language, *subjects),
            }

        if events.ditto_revealed:
            was = self.disguise_name() or label
            self.celebration = banner(
                "ditto",
                "notif_shiny_ditto_title" if shiny else "notif_ditto_title",
                "notif_shiny_ditto_body" if shiny else "notif_ditto_body",
                was)
        elif events.graduated is not None:
            # From the record, not from the companion: graduating clears the
            # slot, so by the time this runs there is no active Pokemon left to
            # take a name from and the banner read "raising — saved to your
            # Pokedex".
            self.celebration = banner(
                "graduated", "notif_graduate_title", "notif_graduate_body",
                self.species_name(events.graduated.final_id, language) or label)
        elif events.evolved_to is not None:
            self.celebration = banner(
                "evolved", "notif_evolve_title", "notif_evolve_body", label)
        elif events.hatched is not None:
            self.celebration = banner(
                "shiny" if shiny else "hatched",
                "notif_shiny_hatch_title" if shiny else "notif_hatch_title",
                "notif_shiny_hatch_body" if shiny else "notif_hatch_body",
                label, str(self.shiny_odds()))
        else:
            return False
        return True

    def shiny_odds(self) -> int:
        """The denominator the shiny roll used: 1 in this.

        Read from the charm rather than written into the copy, so a charm holder
        is not told they beat 1/64 when they beat 1/48 (upstream fe51577).
        """
        return balance.shiny_denominator(self.state.inventory.get("shinyCharm", 0) > 0)

    def disguise_name(self) -> str | None:
        """What a Ditto is pretending to be, for the reveal notification.

        Read from the disguise rather than the companion: by the time anything
        announces the reveal the companion is already called Ditto, and "you
        thought it was Ditto" is not the joke.
        """
        mon = self.state.active
        if mon is None or mon.ditto_disguise is None:
            return None
        return self.species_name(mon.ditto_disguise, self.state.language) or None

    def _line_for_egg(self):
        """Species data for a hatch, or None when offline."""
        if self.api is None:
            return None
        try:
            species_id = self.state.pending_hatch_id
            if species_id is None:
                species_id = self.api.roll_base_species(self.rng, self.state.egg_tier)
            return self.api.line(species_id)
        except pokeapi.PokeAPIError:
            return None  # hold progress in the egg; hatch on a later poll

    # --- presentation ------------------------------------------------------

    def species_name(self, species_id: int, language: str = "en") -> str:
        """Localised species name, or "" when unknown.

        Reads the on-disk species cache the line lookup already populated, so
        this costs nothing after the hatch and stays silent when offline.
        """
        if self.api is None:
            return ""
        try:
            entry = self.api.species(species_id)
        except Exception:
            return ""
        return l10n.resolve_name(l10n.names_from_api(entry.get("names")), language) or ""

    def species_names(self, species_id: int) -> dict[str, str]:
        """Every name PokéAPI knows for a species, by language code.

        The search box matches any of them, so "flabebe" finds Flabébé and a
        Korean name is found by someone typing English.
        """
        if self.api is None:
            return {}
        try:
            entry = self.api.species(species_id)
        except Exception:
            return {}
        return l10n.names_from_api(entry.get("names")) or {}

    def _search_text(self, species_ids) -> str:
        """What a row matches a search against: its numbers and all its names.

        Folded here rather than in the popup — one rule, and Python already has
        the Unicode tables for it. The popup folds the query the same way.
        """
        parts = []
        for species_id in species_ids:
            parts.append(f"#{species_id}")
            parts.extend(self.species_names(species_id).values())
        return _fold(" ".join(parts))

    def _egg_sprite(self) -> str:
        """The egg's own picture, for every surface that draws the companion.

        There was none: the egg stage rendered an empty box on Home and made
        the desktop pet disappear altogether between companions, which reads as
        a UI that has stopped working rather than as an egg warming up.
        """
        if self.sprites is None:
            return ""
        path = self.sprites.egg_path()
        return str(path) if path else ""

    def sprite_path(self) -> str:
        mon = self.state.active
        if self.sprites is None:
            return ""
        if mon is None:
            return self._egg_sprite()
        # The animation first; if that download fails, the still picture keeps
        # Home from drawing an empty box, and the next poll asks for the
        # animation again — a failure is never cached (upstream 2f2fb32).
        form = forms.resolved(mon.current_id, mon.form)
        path = self.sprites.path(mon.current_id, animated=True,
                                 shiny=mon.displays_shiny, form=form)
        if path is None:
            path = self.sprites.path(mon.current_id, animated=False,
                                     shiny=mon.displays_shiny, form=form)
        return str(path) if path else ""

    def panel_species(self) -> tuple[int | None, bool]:
        """What the panel and the desktop pet show: the pin, else the companion.

        While a species is pinned the panel stops following the egg, the hatch
        and the evolutions — Home still shows all of it.
        """
        species_id, shiny, _form = self.panel_individual()
        return species_id, shiny

    def panel_individual(self) -> tuple[int | None, bool, str | None]:
        """The panel's species, colour and, where it has one, its appearance."""
        self.state.reconcile_representative()
        pinned = self.state.representative_species_id
        if pinned is not None:
            form = forms.resolved(pinned, self.state.representative_form)
            return pinned, self.owns_shiny_individual(pinned, form), form
        mon = self.state.active
        if mon is None:
            return None, False, None
        return (mon.current_id, mon.displays_shiny,
                forms.resolved(mon.current_id, mon.form))

    def owns_shiny_individual(self, species_id: int, form: str | None = None) -> bool:
        """Whether the owned copy is shiny — per appearance, where there are
        several."""
        if form is None or not forms.has_forms(species_id):
            return self.state.owns_shiny_species(species_id)
        for entry in self.state.dex:
            if (entry.is_shiny and species_id in entry.chain_order
                    and forms.resolved(species_id, entry.form) == form):
                return True
        mon = self.state.active
        return bool(
            mon is not None and mon.displays_shiny
            and forms.resolved(mon.current_id, mon.form) == form
            and self.state.owns_species(species_id)
        )

    def panel_sprite_path(self) -> str:
        species_id, shiny, letter = self.panel_individual()
        if self.sprites is None:
            return ""
        # Nothing pinned and nothing hatched: the panel and the desktop pet
        # show the egg rather than going blank.
        if species_id is None:
            return self._egg_sprite()
        path = self.sprites.path(species_id, animated=True, shiny=shiny, form=letter)
        return str(path) if path else ""

    def set_representative(self, species_id: int | None,
                           form: str | None = None) -> str:
        """Pin a species to the panel, or clear the pin with None.

        Asking for the species that is already pinned releases it instead. The
        pin was one-way before: the only thing that sends this is a tap on a
        Pokedex cell, and a tap that looks like "show me this one" left the
        panel and the desktop pet frozen on that species through every
        evolution afterwards, with nothing in the UI to undo it. That is what
        made an evolution look like it had never happened.

        Refuses a species the user does not own rather than storing it and
        letting reconcile silently drop it — the caller gets told why.
        """
        if species_id is not None and form is None and forms.has_forms(species_id):
            # Asked for from the grid, which has no form in hand: pin the one
            # that species is actually owned in, not its default — the default
            # may be an appearance nobody has caught.
            chosen = self._representative_letter(
                species_id, self.state.collected_forms(species_id))
        else:
            chosen = forms.resolved(species_id, form) if species_id is not None else None
        if (species_id is not None and species_id == self.state.representative_species_id
                and chosen == self.state.representative_form):
            species_id, chosen = None, None
        if species_id is not None and not self.state.owns_species(species_id, chosen):
            raise ValueError(f"species {species_id} is not in your Pokedex")
        self.state.representative_species_id = species_id
        self.state.representative_form = chosen
        self._persist()
        language = self.state.language
        if species_id is None:
            return l10n.t("panel_unpinned", language)
        return l10n.fill("panel_pinned", language,
                         self.individual_name(species_id, chosen))

    def _panel_fields(self) -> dict:
        """Panel and pet sprite, which the pin overrides.

        Shipped alongside the companion rather than replacing it: Home reads the
        companion's own sprite, so pinning must not hide what is being raised.
        """
        species_id, shiny = self.panel_species()
        return {
            "panel_species_id": species_id,
            "panel_is_shiny": shiny,
            "panel_sprite_path": self.panel_sprite_path(),
            "representative_species_id": self.state.representative_species_id,
            # Named, not just numbered: the popup has to be able to say which
            # species is holding the panel, and "#90" explains nothing to
            # someone wondering why the panel disagrees with Home.
            "panel_name": (
                "" if species_id is None
                else self.individual_name(species_id, self.panel_individual()[2])
            ),
        }

    def _status_message(self, kind: str) -> str:
        """The catalogue line for one display state.

        Not `f"status_{kind.lower()}"`: display_state returns "levelUp", whose
        lower case is `status_levelup`, and no such key exists — so a companion
        that had just evolved reported the literal string "status_levelup" on
        the panel, and `status_grew` was never reachable at all.
        """
        language = self.state.language
        if kind == "levelUp":
            mon = self.state.active
            name = self.species_name(mon.current_id, language) if mon else ""
            if not name:
                return l10n.t("status_grew", language)
            return l10n.fill("status_evolved", language, name)
        return l10n.t(f"status_{kind.lower()}", language)

    def payload(self, today_tokens: int = 0, limit_warning: bool = False) -> dict:
        """Companion section of state.json."""
        # An evolution this poll is what puts the companion in its level-up
        # state. It was never passed, so the celebration mood existed in the
        # ported code and could not occur.
        just_evolved = (
            self.last_events is not None and self.last_events.evolved_to is not None
        )
        kind = companion.display_state(
            self.state, today_tokens, limit_warning, just_evolved=just_evolved)
        mon = self.state.active
        if mon is None:
            progress = min(1.0, self.state.egg_usage / self.state.egg_hatch_threshold)
            return {
                "stage": "egg",
                "label": f"\N{EGG}{round(progress * 100)}%",
                "egg_usage": self.state.egg_usage,
                # What the bar is a fraction of, for the readout on it.
                "egg_threshold": self.state.egg_hatch_threshold,
                "egg_progress": round(progress, 4),
                # Upstream's egg header: "about to hatch" from 90%, and how
                # many tokens are left until it does.
                "egg_imminent": progress >= 0.9,
                "egg_remaining_text": _compact(
                    max(0, self.state.egg_hatch_threshold - self.state.egg_usage)),
                "egg_tier": str(self.state.egg_tier) if self.state.egg_tier else None,
                # Ready, but still an egg: the species could not be fetched,
                # so the hatch is waiting on the next poll to try again
                # (upstream 2ecf7d2). Derived rather than stored — "no
                # companion and the threshold is already paid" is the state.
                "egg_delayed": self.state.egg_usage >= self.state.egg_hatch_threshold,
                # The egg's own picture. This was a hardcoded "", so Home drew
                # an empty box for the whole egg stage.
                "sprite_path": self.sprite_path(),
                "dex_count": len(self.state.dex),
                "spendable_tokens": self.state.spendable_tokens,
                "spendable_text": _compact(self.state.spendable_tokens),
                "display_state": kind,
                "status_message": self._status_message(kind),
                **self._panel_fields(),
            }

        threshold = self.state.stage_threshold(mon)
        # Remaining to the NEXT step: an evolution mid-line, graduation at the end.
        remaining = max(0, threshold - mon.used_at_stage)
        evo_line = []
        if self.sprites is not None:
            for index, species_id in enumerate(mon.path_ids):
                # The line is drawn in the individual's own appearance, where
                # that species has it: a Sandy Burmy's line shows the Sandy
                # Wormadam it is heading for.
                path = self.sprites.path(species_id, animated=False,
                                         shiny=mon.displays_shiny,
                                         form=forms.resolved(species_id, mon.form))
                evo_line.append(
                    {
                        "species_id": species_id,
                        "name": self.individual_name(species_id, mon.form),
                        "sprite_path": str(path) if path else "",
                        "current": index == mon.stage_index,
                        "reached": index <= mon.stage_index,
                    }
                )
        home_details = self.cached_details(mon.current_id)
        return {
            "stage": "mon",
            "label": "",
            "species_id": mon.current_id,
            "types": ([self._resource_name("type", name) for name in home_details.types]
                      if home_details is not None else []),
            "type_keys": list(home_details.types) if home_details is not None else [],
            "name": self.individual_name(mon.current_id, mon.form),
            "is_final_form": mon.is_final_form,
            "remaining_tokens": remaining,
            "remaining_text": _compact(remaining),
            "goal": "graduation" if mon.is_final_form else "next evolution",
            "evo_line": evo_line,
            "is_shiny": mon.displays_shiny,
            "nature": l10n.nature_name(mon.nature, self.state.language),
            "rarity": str(mon.rarity),
            "stage_index": mon.stage_index,
            "total_forms": mon.total_forms,
            "used_at_stage": mon.used_at_stage,
            "stage_threshold": threshold,
            # 2 on a repeat hatch, else None. Home badges it next to the stage.
            "growth_multiplier": mon.growth_multiplier if mon.has_growth_boost else None,
            "level": mon.profile.level if mon.profile is not None else None,
            "stage_progress": round(min(1.0, mon.used_at_stage / threshold), 4)
            if threshold
            else 0.0,
            "sprite_path": self.sprite_path(),
            "dex_count": len(self.state.dex),
            "spendable_tokens": self.state.spendable_tokens,
            "spendable_text": _compact(self.state.spendable_tokens),
            "display_state": kind,
            "status_message": self._status_message(kind),
            **self._panel_fields(),
        }

    # --- economy -----------------------------------------------------------

    def sync_difficulty(self, growth, shop) -> None:
        """Bring the save in line with the difficulty settings.

        Called whenever the settings or the save may have changed under the
        store. Growth re-expresses banked progress when it differs from what
        the save was earned under, and is persisted at once so a restart does
        not do it twice.
        """
        self.state.shop_difficulty = balance.clamp_difficulty(shop)
        if companion.set_growth_difficulty(self.state, growth):
            self._persist()

    def grant_candy(
        self, windows: dict[str, float], epochs: dict[str, str | None] | None = None
    ) -> int:
        granted = shop.grant_candy(self.state, windows, epochs)
        self._persist()
        return granted

    def buy(self, key: str, count: int = 1) -> str:
        result = shop.buy(self.state, key, count)
        # A bought egg discards the companion, so a pin that was following it
        # names a species nobody owns any more.
        self.state.reconcile_representative()
        self._persist()
        return self._shop_message(result)

    def use_item(self, key: str, count: int = 1) -> str:
        result = shop.use_item(self.state, key, rng=self.rng, count=count)
        self._persist()
        # An item that evolves or graduates the companion has to announce it
        # exactly as real usage does. These events used to be discarded here,
        # so a candy that pushed a Pokemon over the line evolved it in silence:
        # no toast, no banner, and no level-up mood on the panel — which is
        # what made the candy look like it had done nothing at all.
        if result.events is not None:
            self._record_events(result.events)
            if self._note_celebration(result.events):
                return self._shop_message(result)
        # Nothing grew past a threshold. The use still gets a banner of its
        # own, because "the count went down and nothing happened" is
        # indistinguishable from a bug.
        self.celebration = self._item_banner(result)
        return self._shop_message(result)

    def _label_for(self, key: str) -> str:
        """The shop label for one entry key, in the user's language."""
        if key.startswith("egg"):
            tier = key.split(":")[1] if ":" in key else None
            return self._egg_words(tier)[0]
        return self._item_words(key)[0]

    def _shop_message(self, result: shop.ItemResult) -> str:
        """The toast for one purchase or item use.

        Resolved here rather than in shop.py: that module stays free of the
        catalogue, and this is the layer that already knows the language. The
        message used to be an English literal built in shop.py, which is the
        one toast a fully-localized UI could still answer a click with in the
        wrong language.
        """
        language = self.state.language
        if result.nature is not None:
            return l10n.fill(
                "shop_nature_now", language, l10n.nature_name(result.nature, language))
        key = "shop_bought" if result.action == "buy" else "shop_used"
        label = self._label_for(result.key)
        if result.count > 1:
            # "×3" rather than a plural form in seven languages.
            label = f"{label} {l10n.t('times_count', language).replace('%1', str(result.count))}"
        return l10n.t(key, language).replace("%1", label)

    def _item_banner(self, result: shop.ItemResult) -> dict:
        """The popup banner for an item use that changed no threshold."""
        language = self.state.language
        detail = (
            l10n.fill(
                "shop_nature_now", language, l10n.nature_name(result.nature, language))
            if result.nature is not None
            else l10n.t("shop_used_body", language).replace(
                "%1", self._item_words(result.key)[2])
        )
        return {
            "kind": "item",
            "title": l10n.t("shop_used", language).replace(
                "%1", self._label_for(result.key)),
            "detail": detail,
        }

    def _item_sprite(self, key: str) -> str:
        # Every egg tier is the same picture; only the guarantee differs, and
        # that is what the badge beside it says.
        if key == "egg":
            return self._egg_sprite()
        name = balance.ITEM_SPRITE.get(key)
        if not name or self.sprites is None:
            return ""
        path = self.sprites.item_path(name)
        return str(path) if path else ""

    def _item_words(self, key: str) -> tuple[str, str, str]:
        """Name, description and effect for one item, in the user's language.

        The Rare Candy's numbers are read off the balance constants and
        substituted in, so the description cannot drift from what the item
        actually does the way a hardcoded "100M" would.
        """
        language = self.state.language
        names = balance.ITEM_STRINGS.get(key)
        if names is None:
            return balance.ITEM_LABEL.get(key, key), "", ""
        experience = _compact(balance.RARE_CANDY_XP)
        resolved = [l10n.t(name, language).replace("%1", experience) for name in names]
        return resolved[0], resolved[1], resolved[2]

    def _egg_words(self, tier: str | None) -> tuple[str, str, str]:
        """Name, description and guarantee badge for one egg tier."""
        language = self.state.language
        name = l10n.t(balance.EGG_STRINGS.get(tier, "egg_common"), language)
        if tier is None:
            return name, l10n.t("egg_desc_fresh", language), ""
        rarity = l10n.t(tier, language)
        return (
            name,
            l10n.t("egg_desc_guaranteed", language).replace("%1", rarity),
            l10n.t("egg_guarantee", language).replace("%1", rarity),
        )

    def shop_payload(self) -> list[dict]:
        spendable = self.state.spendable_tokens
        out = []
        for e in shop.entries(self.state):
            if e.kind == "item":
                sprite = self._item_sprite(e.key)
                label, description, _effect = self._item_words(e.key)
                badge = ""
            else:
                # ITEM_SPRITE has no "egg" entry, so asking for one returned
                # nothing and every egg in the shop was a blank square.
                sprite = self._egg_sprite()
                tier = e.key.split(":")[1] if ":" in e.key else None
                label, description, badge = self._egg_words(tier)
            # An egg stays listed during the egg stage but cannot be bought:
            # shop.buy refuses it, and the card says why under a disabled
            # button rather than vanishing.
            locked = e.kind == "egg" and self.state.active is None
            out.append(
                {
                    "key": e.key,
                    "kind": e.kind,
                    "price": e.price,
                    "price_text": _compact(e.price),
                    "label": label,
                    "description": description,
                    "badge": badge,
                    # The tier as a catalogue key, so a front end shows "고급"
                    # rather than "UNCOMMON". `badge` is the uppercase word and
                    # is not translatable.
                    "rarity": tier if e.kind != "item" else None,
                    "sprite_path": sprite,
                    "emoji": {"rareCandy": "\N{CANDY}", "mint": "\N{HERB}",
                              "shinyCharm": "\N{SPARKLES}"}.get(e.key, "\N{EGG}"),
                    "owned": e.owned,
                    "owned_count": self.state.inventory.get(e.key, 0),
                    "affordable": spendable >= e.price and not e.owned and not locked,
                    "locked": locked,
                    # How many the wallet can take in one purchase. An egg is
                    # always one: it replaces the companion.
                    "max_buy": 0 if locked else shop.max_buy(self.state, e),
                    # Only an egg releases anything, and only while there is a
                    # companion to release.
                    "release_note": (
                        l10n.t("egg_release_note", self.state.language)
                        if e.kind == "egg" and self.state.active is not None
                        else ""
                    ),
                }
            )
        return out

    def bag_payload(self) -> list[dict]:
        emoji = {"rareCandy": "\N{CANDY}", "mint": "\N{HERB}", "shinyCharm": "\N{SPARKLES}"}
        return [
            {
                "key": key,
                # Everything the popup needs to preview a batch of candy
                # without a round trip, and nothing about how growth works:
                # the ladder is already rounded to this difficulty and boost.
                **({"candy": self._candy_payload()} if key == "rareCandy" else {}),
                "label": self._item_words(key)[0],
                "description": self._item_words(key)[1],
                "effect": self._item_words(key)[2],
                "sprite_path": self._item_sprite(key),
                "emoji": emoji.get(key, "?"),
                "count": count,
                # Passive items are held, not consumed.
                "usable": key in ("rareCandy", "mint") and self.state.active is not None,
                "passive": key == "shinyCharm",
            }
            for key, count in sorted(self.state.inventory.items())
            if count > 0
        ]

    def _form_rows(self, species_id: int, selected: str | None) -> list[dict]:
        """Every appearance of this species, in order, with the ones not
        collected marked. Empty for a species that has only one.

        The whole set is shipped rather than only what is owned: the page is
        how someone sees which are still missing.
        """
        if not forms.has_forms(species_id):
            return []
        collected = self.state.collected_forms(species_id)
        # A label rather than a sprite: Unown's 28 letters alone would be 28
        # more textures in an open popup, and they read better as "B" and "?"
        # anyway. Other species name their form.
        return [
            {
                "form": form,
                "symbol": self.form_label(species_id, form),
                "collected": form in collected,
                "selected": form == selected,
            }
            for form in forms.forms(species_id)
        ]

    def form_label(self, species_id: int, form: str | None) -> str:
        """What this appearance is called.

        Unown names its letter. Arceus's plates are types, which PokeAPI does
        translate. The rest come from our own table where PokeAPI has nothing
        for this language — its `pokemon-form` resources are named in English,
        French and German only — and from PokeAPI otherwise.
        """
        resolved = forms.resolved(species_id, form)
        if resolved is None:
            return ""
        if species_id == forms.UNOWN_SPECIES_ID:
            return forms.symbol(resolved)
        if forms.has_unnamed_default(species_id, resolved):
            return l10n.t("normal_form", self.state.language)
        readable = resolved.replace("-", " ").title()
        if species_id == forms.ARCEUS_SPECIES_ID:
            # The plate is a type, and the type endpoint is translated.
            return self._resource_name("type", resolved, fallback=readable)
        ours = l10n.form_name(resolved, self.state.language)
        if ours:
            return ours
        resource = forms.name_resource(species_id, resolved)
        if resource is None:
            return readable
        return self._resource_name("pokemon-form", str(resource), fallback=readable)

    def individual_name(self, species_id: int, form: str | None) -> str:
        """The species' name with its appearance beside it, where it has one:
        "Unown [B]", "Shaymin [Sky Forme]"."""
        name = self.species_name(species_id, self.state.language) or f"#{species_id}"
        resolved = forms.resolved(species_id, form)
        if resolved is None or forms.is_default(species_id, resolved):
            # Unown still names its letter; the default A is one of 28.
            if species_id != forms.UNOWN_SPECIES_ID or resolved is None:
                return name
        return forms.display_name(name, species_id, resolved,
                                  self.form_label(species_id, resolved))

    def _candy_payload(self) -> dict:
        """The stage ladder a candy batch is measured against.

        The popup steps the quantity locally, so the preview arithmetic happens
        there; what it cannot work out for itself — what each remaining stage
        costs at this difficulty, and how much of the current one is already
        paid for — comes from here.
        """
        return {
            "xp": balance.RARE_CANDY_XP,
            "xp_text": _compact(balance.RARE_CANDY_XP),
            # "+%1 XP" unsubstituted: the popup fills in the batch's own total,
            # and "XP" is not the same word in every language.
            "effect_template": l10n.t("item_rare_candy_effect", self.state.language),
            "max_use": shop.max_candy_uses(self.state),
            "stage_costs": shop.candy_stage_costs(self.state),
            "used_at_stage": self.state.active.used_at_stage if self.state.active else 0,
        }

    def dex_payload(self) -> list[dict]:
        """The Pokedex grid, rebuilt only when the save has changed.

        Nine hundred and seventy-nine cells, each one asking the sprite store
        for a file, built fresh on every poll whether or not anything had
        happened. A row that is still missing its sprite is not kept, so the
        picture appears as soon as it has been fetched rather than at the next
        catch.
        """
        key = (self._revision, self.state.language)
        if self._dex_rows is not None and self._dex_rows[0] == key:
            return self._dex_rows[1]
        rows = self._build_dex_payload()
        if all(row["sprite_path"] for row in rows):
            self._dex_rows = (key, rows)
        return rows

    def _build_dex_payload(self) -> list[dict]:
        """Species-level collection — ports dexSpecies.

        Includes every species in a graduated chain, plus the CURRENT
        companion's reached forms only (path_ids up to stage_index). The
        planned path is never used: it contains stages not yet evolved into,
        which would list species that have never been owned.

        is_raising marks the one form the companion is right now, as upstream
        does since 79ba760. It used to mark every reached form without a
        graduation record, which put the badge on forms already outgrown and
        read as raising two Pokemon at once.
        """
        acc: dict[int, dict] = {}

        for entry in self.state.dex:
            for species_id in entry.chain_order:
                slot = acc.setdefault(
                    species_id,
                    {"rarity": str(entry.rarity), "is_shiny": False, "has_normal": False},
                )
                # Both colours are tracked, not just "any shiny": owning a
                # shiny one used to hide the ordinary one you also caught
                # (upstream 4bfae97).
                if entry.is_shiny:
                    slot["is_shiny"] = True
                else:
                    slot["has_normal"] = True

        mon = self.state.active
        if mon is not None:
            for species_id in mon.path_ids[: mon.stage_index + 1]:
                slot = acc.setdefault(
                    species_id,
                    {"rarity": str(mon.rarity), "is_shiny": False, "has_normal": False},
                )
                if mon.displays_shiny:
                    slot["is_shiny"] = True
                else:
                    slot["has_normal"] = True

        # Which cell is holding the panel. Without this the pin was invisible:
        # the panel stopped following the companion and nothing anywhere said
        # why, or which of these cells to tap to give it back.
        self.state.reconcile_representative()
        pinned = self.state.representative_species_id
        raising = mon.current_id if mon is not None else None

        # A species is one cell whatever it is wearing: 28 Unown would swamp
        # a grid of species, and the forms are collected on the species' own
        # page (upstream 10d1a07, 04b12da).
        out = []
        for species_id in sorted(acc):
            slot = acc[species_id]
            owned_forms = self.state.collected_forms(species_id)
            # The cell shows an appearance actually owned, not the default.
            letter = (self._representative_letter(species_id, owned_forms)
                      if owned_forms else None)
            sprite = ""
            if self.sprites is not None:
                path = self.sprites.path(
                    species_id, animated=False, shiny=slot["is_shiny"], form=letter
                )
                sprite = str(path) if path else ""
            out.append(
                {
                    "final_id": species_id,
                    "species_id": species_id,
                    "name": self.species_name(species_id, self.state.language),
                    "rarity": slot["rarity"],
                    "is_shiny": slot["is_shiny"],
                    "has_normal": slot["has_normal"],
                    "is_raising": species_id == raising,
                    "is_pinned": species_id == pinned,
                    "sprite_path": sprite,
                    "search": self._search_text([species_id]),
                    # How many of this species' appearances are collected; ""
                    # for one that has a single appearance. Bare, because a dex
                    # cell is 72px wide: the sentence is on the page it opens.
                    "form_count_text": (
                        f"{len(owned_forms)}/{len(forms.forms(species_id))}"
                        if forms.has_forms(species_id) else ""
                    ),
                }
            )
        return out

    def _representative_letter(self, species_id: int, owned) -> str | None:
        """Which appearance the grid draws for a species: the pinned one, the
        one being raised, else the first collected."""
        if (self.state.representative_species_id == species_id
                and self.state.representative_form in owned):
            return self.state.representative_form
        mon = self.state.active
        if mon is not None and mon.current_id == species_id:
            return forms.resolved(species_id, mon.form)
        return (min(owned, key=lambda form: forms.sort_order(species_id, form))
                if owned else None)

    def _chain(self, species_ids, shiny: bool, form: str | None = None) -> list[dict]:
        out = []
        for species_id in species_ids:
            resolved = forms.resolved(species_id, form)
            sprite = ""
            if self.sprites is not None:
                path = self.sprites.path(species_id, animated=False, shiny=shiny,
                                         form=resolved)
                sprite = str(path) if path else ""
            out.append(
                {
                    "species_id": species_id,
                    "name": self.individual_name(species_id, resolved),
                    "sprite_path": sprite,
                }
            )
        return out

    def catch_log_payload(self) -> list[dict]:
        """The catch log, rebuilt only when the save has changed.

        Same reasoning as the grid above: a thousand rows, each with its whole
        evolution chain and a sprite per stage.
        """
        key = (self._revision, self.state.language)
        if self._catch_rows is not None and self._catch_rows[0] == key:
            return self._catch_rows[1]
        rows = self._build_catch_log_payload()
        if all(stage["sprite_path"] for row in rows for stage in row["chain"]):
            self._catch_rows = (key, rows)
        return rows

    def _build_catch_log_payload(self) -> list[dict]:
        """Every catch, newest first, with its full evolution chain.

        Entries predating caught_at sort last rather than pretending to be
        ancient; ordering among them is unspecified.
        """
        out = [
            {
                "rarity": str(e.rarity),
                "nature": l10n.nature_name(e.nature, self.state.language),
                "is_shiny": e.is_shiny,
                "chain": self._chain(e.chain_order, e.is_shiny, e.form),
                "caught_at": e.caught_at,
                "raised_text": _duration(e.raised_seconds, self.state.language),
                "raising": False,
                "released": e.is_released,
                # A catch is found through any species in its line, as its row
                # shows the whole chain.
                "search": self._search_text(e.chain_order),
                "species_id": e.final_id,
                "name": self.individual_name(e.final_id, e.form),
            }
            for e in self.state.dex
        ]
        out.sort(key=lambda d: d["caught_at"] or 0, reverse=True)

        # The companion still being raised leads the log, as in the macOS app.
        mon = self.state.active
        if mon is not None:
            out.insert(
                0,
                {
                    "rarity": str(mon.rarity),
                    "nature": l10n.nature_name(mon.nature, self.state.language),
                    "is_shiny": mon.displays_shiny,
                    "chain": self._chain(mon.path_ids[: mon.stage_index + 1],
                                         mon.displays_shiny, mon.form),
                    "caught_at": mon.hatched_at,
                    "raised_text": "",
                    "raising": True,
                    "released": False,
                    "search": self._search_text(mon.path_ids[: mon.stage_index + 1]),
                    "species_id": mon.current_id,
                    "name": self.individual_name(mon.current_id, mon.form),
                },
            )
        return out

    def graduated_between(self, start: float, end: float) -> list[dict]:
        """Individuals collected inside a period, newest first.

        For the usage recap: the tokens say how much was spent, and these say
        what came of it. A released Pokémon is left out — it was not collected,
        it was let go.
        """
        language = self.state.language
        found = [
            e for e in self.state.dex
            if not e.is_released and e.caught_at is not None and start <= e.caught_at < end
        ]
        found.sort(key=lambda e: e.caught_at or 0, reverse=True)
        out = []
        for entry in found:
            sprite = ""
            if self.sprites is not None:
                path = self.sprites.path(
                    entry.final_id, animated=False, shiny=entry.is_shiny,
                    form=forms.resolved(entry.final_id, entry.form))
                sprite = str(path) if path else ""
            out.append({
                "species_id": entry.final_id,
                "name": self.individual_name(entry.final_id, entry.form),
                "rarity": str(entry.rarity),
                "is_shiny": entry.is_shiny,
                "sprite_path": sprite,
                "when_text": _time.strftime("%Y-%m-%d", _time.localtime(entry.caught_at)),
            })
        return out

    def rarity_counts(self) -> dict:
        """Species counts for the Pokedex filters.

        The catch log counts individuals instead — 14 catches can be 28
        species — so the two tabs cannot share one tally.
        """
        counts = {"legendary": 0, "rare": 0, "uncommon": 0, "common": 0}
        for row in self.dex_payload():
            key = row["rarity"]
            if key in counts:
                counts[key] += 1
        return counts

    def catch_rarity_counts(self) -> dict:
        """Individual counts for the catch log, including the one being raised."""
        counts = {"legendary": 0, "rare": 0, "uncommon": 0, "common": 0}
        for entry in self.state.dex:
            key = str(entry.rarity)
            if key in counts:
                counts[key] += 1
        if self.state.active is not None:
            key = str(self.state.active.rarity)
            if key in counts:
                counts[key] += 1
        return counts

    def _persist(self) -> None:
        """Write the save, if it would say anything new.

        Every poll calls this, whether or not the usage moved anything: it is
        the one place that knows the state is settled. Encoding it is cheap
        against writing it, so the text is compared first — a quiet minute now
        costs no disk write, and the revision below only moves when the save
        really changed, which is what the built payloads are keyed on.
        """
        text = save.encoded_text(self.state)
        if text != self._saved_text:
            save.save(self.state, self.save_path, text=text)
            self._saved_text = text
            self._revision += 1
        self._auto_snapshot()

    # --- restore points (upstream 13e3bf2) -----------------------------------

    def _auto_snapshot(self) -> None:
        """A restore point every twelve hours, taken as the save is written."""
        if self.save_path is None:
            return
        if snapshots.auto(self.state, self.save_path) is not None:
            self._snapshot_rows = None

    def snapshot_rows(self) -> list[dict]:
        """Every restore point, newest first, described for the settings page.

        Cached: the popup asks for this on every poll, and the answer only
        changes when this process takes or restores one.
        """
        if self.save_path is None:
            return []
        if self._snapshot_rows is not None:
            return self._snapshot_rows
        language = self.state.language
        out = []
        for snapshot in snapshots.listing(self.save_path):
            out.append({
                "id": snapshot.id,
                "taken_at": snapshot.taken_at,
                "dex_count": snapshot.dex_count,
                "used_text": _compact(snapshot.used_since_install),
                "summary": l10n.fill(
                    "snapshot_summary", language,
                    str(snapshot.dex_count), _compact(snapshot.used_since_install)),
                "sprite_path": (
                    str(self.sprites.path(snapshot.species_id, animated=False,
                                          shiny=snapshot.is_shiny,
                                          form=snapshot.form) or "")
                    if self.sprites is not None and snapshot.species_id else ""
                ),
            })
        self._snapshot_rows = out
        return out

    def create_snapshot(self) -> str:
        """Take a restore point now, and say so in the user's language."""
        if self.save_path is None:
            raise transfer.TransferError("this store has no file to snapshot")
        snapshots.create(self.state, self.save_path)
        self._snapshot_rows = None
        return l10n.t("snapshot_created", self.state.language)

    def restore_snapshot(self, snapshot_id: str) -> str:
        """Put one restore point back, keeping what it replaces as another."""
        if self.save_path is None:
            raise transfer.TransferError("this store has no file to restore into")
        self.state = snapshots.restore(snapshot_id, self.save_path)
        self._snapshot_rows = None
        self.migrate_profiles()
        self.state.reconcile_representative()
        return l10n.fill(
            "snapshot_restored", self.state.language,
            str(len(self.state.dex)), _compact(self.state.used_since_install))
