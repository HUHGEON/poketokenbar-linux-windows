"""Ties the companion engine to live usage — ports CompanionStore.swift.

Providers report cumulative totals for *today*, not deltas. This converts them
into deltas by remembering what has already been credited per provider, which
is why the baseline is tracked per provider id rather than in aggregate: a
single total cannot be decomposed when one provider resets and another does not.
"""

from __future__ import annotations

import random
from datetime import date as _date
from pathlib import Path

from . import balance, companion, l10n, pokeapi, save, shop, sprites, forms, pokemon_types
from .companion import CompanionState
from .format import compact as _compact
from .plan import MULTIPLIERS
from .profile import PokemonProfile, computed_stats


def _duration(seconds: float | None) -> str:
    if not seconds or seconds <= 0:
        return ""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    if days > 0:
        return f"{days} days, {hours} hr"
    minutes = int((seconds % 3600) // 60)
    return f"{hours} hr, {minutes} min" if hours else f"{minutes} min"


class CompanionStore:
    def __init__(
        self,
        save_path: Path | None = None,
        api: pokeapi.PokeAPI | None = None,
        sprite_store: sprites.SpriteStore | None = None,
        rng: random.Random | None = None,
        growth_difficulty: float = balance.DEFAULT_DIFFICULTY,
        shop_difficulty: float = balance.DEFAULT_DIFFICULTY,
    ) -> None:
        self.save_path = save_path
        self.state: CompanionState = save.load(save_path)
        # What loading had to put back inside the rules, for the daemon to
        # report once. A save is repaired in silence otherwise, and the first
        # sign is a Pokemon that looks wrong.
        self.save_repairs: list[str] = list(save.last_repairs)
        self.api = api
        self.sprites = sprite_store
        self.rng = rng or random.Random()
        # Loaded from config alongside the save in production. Starting on the
        # persisted scale matters: treating every restart as 100% would
        # repeatedly rescale already-adjusted progress.
        self.growth_difficulty = balance.clamp_difficulty(growth_difficulty)
        self.shop_difficulty = balance.clamp_difficulty(shop_difficulty)
        # Held for one poll so the popup can show a celebration banner; the
        # notification fires immediately but the banner needs a render pass.
        self.celebration: dict | None = None
        self.last_events: companion.GrowthEvents | None = None
        self.hatch_error: str | None = None
        self._detail_payloads: dict[int, dict] = {}
        self._detail_status: dict[int, str] = {}
        self._ensure_profiles()

    def _ensure_profiles(self) -> None:
        """Add deterministic profiles to saves written before profiles existed."""
        mon = self.state.active
        if mon is not None and mon.profile is None:
            seed = (mon.base_id << 32) ^ int(mon.hatched_at or 0)
            mon.profile = PokemonProfile.generate(seed=seed)
        for index, entry in enumerate(self.state.dex):
            if entry.profile is None:
                seed = (entry.base_id << 32) ^ int(entry.caught_at or index + 1)
                entry.profile = PokemonProfile.generate(seed=seed)

    # --- usage -------------------------------------------------------------

    def set_difficulties(self, growth, prices) -> bool:
        """Apply preference-only difficulty while preserving earned progress.

        The counters in companion.json are banked progression credits.  When a
        threshold changes, keep their completed fraction instead of granting a
        hatch/evolution merely because Settings changed.  Token ledgers and the
        wallet are deliberately untouched.
        """
        new_growth = balance.clamp_difficulty(growth)
        new_prices = balance.clamp_difficulty(prices)
        progress_changed = False
        changed = False
        if new_growth != self.growth_difficulty:
            old = self.growth_difficulty
            if self.state.active is None:
                base = balance.EGG_HATCH_THRESHOLD * self.state.balance_multiplier
                self.state.egg_usage = self._rescaled_progress(
                    self.state.egg_usage, base, old, new_growth
                )
            else:
                mon = self.state.active
                base = round(balance.phase_threshold(
                    mon.rarity, mon.total_forms, mon.stage_index,
                    self.state.balance_multiplier,
                ) / (2 if mon.has_growth_boost else 1))
                mon.used_at_stage = self._rescaled_progress(
                    mon.used_at_stage, base, old, new_growth
                )
            self.growth_difficulty = new_growth
            progress_changed = True
            changed = True
        if new_prices != self.shop_difficulty:
            self.shop_difficulty = new_prices
            changed = True
        if progress_changed:
            self._persist()
        return changed

    @staticmethod
    def _rescaled_progress(
        credits: int, base: int, old_difficulty: float, new_difficulty: float
    ) -> int:
        old_threshold = balance.scale_difficulty(base, old_difficulty)
        new_threshold = balance.scale_difficulty(base, new_difficulty)
        scaled = int(credits / old_threshold * new_threshold)
        # Rounding cannot turn an incomplete stage into a completed one.
        if credits < old_threshold:
            scaled = min(scaled, new_threshold - 1)
        return max(0, scaled)

    def _egg_threshold(self) -> int:
        return balance.scale_difficulty(
            balance.EGG_HATCH_THRESHOLD * self.state.balance_multiplier,
            self.growth_difficulty,
        )

    def _stage_threshold(self, mon) -> int:
        multiplier = 2 if mon.has_growth_boost else 1
        return balance.scale_difficulty(
            max(1, round(balance.phase_threshold(
                mon.rarity, mon.total_forms, mon.stage_index,
                self.state.balance_multiplier,
            ) / multiplier)),
            self.growth_difficulty,
        )

    def apply_plan(self, detected: str | None) -> bool:
        """Change progress units once, without manufacturing real usage.

        An unavailable account keeps the saved scale. Raw provider baselines
        and the earned/spent token ledger are not progress and stay untouched.
        """
        if detected not in MULTIPLIERS:
            return False
        multiplier = MULTIPLIERS[detected]
        previous = self.state.balance_multiplier
        if multiplier == previous and self.state.detected_plan == detected:
            return False

        from copy import deepcopy

        updated = deepcopy(self.state)
        if multiplier != previous:
            # Floor only when converting to smaller units: repeated switches
            # must never generate XP through rounding. Loss is < one XP.
            updated.egg_usage = updated.egg_usage * multiplier // previous
            if updated.active is not None:
                updated.active.used_at_stage = updated.active.used_at_stage * multiplier // previous
        updated.balance_multiplier = multiplier
        updated.detected_plan = detected
        # Commit to disk before replacing the live state. A failed write must
        # not leave purchases on a scale that will disappear on restart.
        save.save(updated, self.save_path)
        self.state = updated
        return True

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

        # Hatch preparation persists its roll before a potentially slow fetch.
        # Keep the next baseline separate until the corresponding growth exists.
        claimed = dict(self.state.claimed_today_tokens_by_provider)

        delta = 0
        for provider_id, total in totals_by_provider.items():
            previous = claimed.get(provider_id, 0)
            # A total going backwards (log rotation, cache rebuild) must not
            # produce a negative delta.
            if total > previous:
                delta += total - previous
            claimed[provider_id] = total

        if delta <= 0:
            self.state.claimed_today_tokens_by_provider = claimed
            self.retry_hatch()
            self._persist()
            return

        line = self._line_for_egg() if self.state.active is None else None
        self.last_events = companion.apply_usage(
            self.state, delta, line_for_egg=line, rng=self.rng,
            growth_difficulty=self.growth_difficulty,
        )
        self.state.claimed_today_tokens_by_provider = claimed
        self._sync_profile(self.last_events)
        self._note_celebration(self.last_events)
        self._persist()

    def _sync_profile(self, events=None) -> None:
        """Advance level and enrich species-dependent fields when possible."""
        target = self.state.active
        species_id = target.current_id if target is not None else None
        profile = target.profile if target is not None else None
        nature = target.nature if target is not None else None
        if target is not None and profile is not None:
            standard_done = sum(
                balance.phase_threshold(target.rarity, target.total_forms, index)
                for index in range(target.stage_index)
            )
            standard_stage = balance.phase_threshold(
                target.rarity, target.total_forms, target.stage_index)
            actual_stage = max(1, self._stage_threshold(target))
            earned = standard_done + min(1.0, target.used_at_stage / actual_stage) * standard_stage
            profile.advance(earned / max(1, balance.graduation_total(target.rarity)))
            if events is not None and events.ditto_revealed:
                profile.gender = None
                profile.ability_slot = None
                profile.ability_name = None
                profile.ability_is_hidden = False
                profile.moves = []
        elif events is not None and events.graduated is not None:
            entry = events.graduated
            profile, species_id, nature = entry.profile, entry.final_id, entry.nature

        detail_fetch = getattr(self.api, "details", None) if self.api is not None else None
        if profile is None or species_id is None or detail_fetch is None:
            return
        try:
            profile.enrich(detail_fetch(species_id))
        except (pokeapi.PokeAPIError, OSError, ValueError, TypeError):
            pass

    def _profile_payload(self, profile: PokemonProfile | None, species_id: int,
                         nature: str | None) -> dict | None:
        if profile is None:
            return None
        cached = getattr(self.api, "cached_details", None) if self.api is not None else None
        details = cached(species_id) if cached is not None else None
        language = self.state.language
        descriptions = (details or {}).get("descriptions") or {}
        description = descriptions.get(language)
        if not description and language == "ja":
            description = descriptions.get("ja-Hrkt")
        description = description or descriptions.get("en", "")
        ability = profile.ability_name
        moves = [dict(move) for move in profile.moves]
        localize = (getattr(self.api, "localized_battle_names", None)
                    if self.api is not None else None)
        if callable(localize):
            try:
                ability, move_names = localize(
                    ability, [str(move.get("name") or "") for move in moves], language)
                for move in moves:
                    raw_name = str(move.get("name") or "")
                    move["display_name"] = move_names.get(raw_name, raw_name)
            except (pokeapi.PokeAPIError, OSError, ValueError, TypeError, AttributeError):
                pass
        return {
            "instance_id": profile.instance_id,
            "level": profile.level,
            "gender": profile.gender,
            "nature": nature,
            "ability": ability,
            "ability_is_hidden": profile.ability_is_hidden,
            "ivs": dict(profile.ivs),
            "moves": moves,
            "stats": computed_stats(details, profile, nature) if details else [],
            "types": list((details or {}).get("types") or []),
            "type_badges": pokemon_types.badges((details or {}).get("types"), language),
            "height": (details or {}).get("height"),
            "weight": (details or {}).get("weight"),
            "description": description,
        }

    def load_pokemon_details(self, species_id: int) -> None:
        """Resolve one owned species on demand, including reference-only stages."""
        owned = {sid for entry in self.state.dex for sid in entry.chain_order}
        owned.update(self.state.reached_species())
        if species_id not in owned:
            raise ValueError("Pokemon is not collected")
        try:
            reset_retry = getattr(self.api, "reset_details_retry", None)
            if callable(reset_retry):
                reset_retry(species_id)
            details = self.api.details(species_id)
            moves = [dict(move) for move in details.get("all_moves") or []]
            abilities = [dict(ability) for ability in details.get("abilities") or []]
            localize = getattr(self.api, "localized_battle_names", None)
            names = {}
            if callable(localize):
                for index, ability in enumerate(abilities or [{"name": None}]):
                    display, translated = localize(ability.get("name"),
                        [m["name"] for m in moves] if index == 0 else [], self.state.language)
                    if ability.get("name"):
                        ability["display_name"] = display
                    names.update(translated)
            for move in moves:
                move["display_name"] = names.get(move["name"]) or move["name"].replace("-", " ").title()
            descriptions = details.get("descriptions") or {}
            self._detail_payloads[species_id] = {
                "language": self.state.language,
                "height": details.get("height"), "weight": details.get("weight"),
                "base_stats": details.get("base_stats") or {},
                "base_stat_total": sum((details.get("base_stats") or {}).values()),
                "abilities": abilities, "moves": moves,
                "version_group": details.get("version_group"),
                "description": descriptions.get(self.state.language) or descriptions.get("en", ""),
            }
            self._detail_status[species_id] = ("ready" if
                details.get("version_group") == pokeapi.PREFERRED_VERSION_GROUP else "stale")
            # Refresh only moves/derived metadata. Rolled identity and earned progress stay intact.
            individuals = [e for e in self.state.dex if e.final_id == species_id]
            if self.state.active and self.state.active.current_id == species_id:
                individuals.append(self.state.active)
            for individual in individuals:
                if individual.profile:
                    individual.profile.enrich(details)
            self._persist()
        except (pokeapi.PokeAPIError, OSError, ValueError, TypeError, AttributeError):
            self._detail_status[species_id] = "error"

    def _note_celebration(self, events) -> None:
        """Build the banner the popup shows once, in the user's language.

        Shares the notification catalogue rather than carrying a second set of
        words: the banner and the toast announce the same event, and two
        wordings for one thing is how they drift apart. They were English
        literals before, which made them the largest untranslated surface in a
        UI that is otherwise fully localized.
        """
        if events is None:
            return
        mon = self.state.active
        language = self.state.language
        name = self._display_name(mon.current_id, mon.unown_form) if mon else ""
        label = name or l10n.t("raising", language)
        shiny = mon is not None and mon.visible_shiny

        def banner(kind: str, title_key: str, body_key: str, subject: str) -> dict:
            return {
                "kind": kind,
                "title": l10n.t(title_key, language),
                "detail": l10n.format_text(
                    l10n.t(body_key, language), subject,
                    balance.SHINY_CHARM_DENOMINATOR if self.state.inventory.get("shinyCharm", 0)
                    else balance.SHINY_DENOMINATOR),
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
                self._display_name(events.graduated.final_id, events.graduated.unown_form) or label)
        elif events.evolved_to is not None:
            self.celebration = banner(
                "evolved", "notif_evolve_title", "notif_evolve_body", label)
        elif events.hatched is not None:
            self.celebration = banner(
                "shiny" if shiny else "hatched",
                "notif_shiny_hatch_title" if shiny else "notif_hatch_title",
                "notif_shiny_hatch_body" if shiny else "notif_hatch_body",
                label)

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
            self.hatch_error = l10n.t("hatch_delayed", self.state.language)
            return None
        try:
            species_id = self.state.pending_hatch_id
            if species_id is None:
                species_id = self.api.roll_base_species(self.rng, self.state.egg_tier)
                self.state.pending_hatch_id = species_id
                self.state.pending_unown_form = (
                    forms.roll_form(self.rng.getrandbits(64), {
                        form for species in forms.CATALOG
                        if forms.LINE_BASE_IDS.get(species, species) == species_id
                        for _, form in self.state.appearances(species)
                    }, forms.line_forms(species_id)) if forms.line_forms(species_id) else None)
                self._persist()
            line = self.api.line(species_id)
            self.hatch_error = None
            return line
        except (pokeapi.PokeAPIError, OSError, ValueError):
            self.hatch_error = l10n.t("hatch_delayed", self.state.language)
            return None  # hold progress in the egg; hatch on a later poll

    def retry_hatch(self) -> bool:
        """Spend banked egg progress even when the next poll has no new usage."""
        if self.state.active is not None or self.state.egg_usage < self._egg_threshold():
            return False
        line = self._line_for_egg()
        if line is None:
            self._persist()
            return False
        self.last_events = companion.apply_usage(
            self.state, 0, line_for_egg=line, rng=self.rng, credit_wallet=False,
            growth_difficulty=self.growth_difficulty)
        self._sync_profile(self.last_events)
        self._note_celebration(self.last_events)
        self._persist()
        return self.last_events.hatched is not None

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
        names = {
            n["language"]["name"]: n["name"]
            for n in entry.get("names", [])
            if n.get("language", {}).get("name")
        }
        # ja-Hrkt is the kana form PokeAPI uses for Japanese.
        for code in ({"ja": ["ja-Hrkt", "ja"]}.get(language, [language])):
            if names.get(code):
                return names[code]
        return names.get("en", "")

    def sprite_path(self) -> str:
        mon = self.state.active
        if mon is None or self.sprites is None:
            return ""
        return self._sprite(mon.current_id, True, mon.visible_shiny, mon.unown_form)

    def _sprite(self, species_id: int, animated: bool, shiny: bool,
                form: str | None = None) -> str:
        if self.sprites is None:
            return ""
        kwargs = {"unown_form": form} if forms.forms(species_id) else {}
        path = self.sprites.path(species_id, animated=animated, shiny=shiny, **kwargs)
        return str(path) if path else ""

    def _display_name(self, species_id: int, form: str | None = None) -> str:
        resolved = forms.resolved(species_id, form)
        label = None
        if resolved and species_id != forms.SPECIES_ID and resolved != forms.forms(species_id)[0]:
            lookup = getattr(self.api, "form_label", None)
            if lookup:
                label = lookup(species_id, resolved, self.state.language)
        return forms.display_name(self.species_name(species_id, self.state.language), species_id, form, label)

    def panel_species(self) -> tuple[int | None, bool]:
        """What the panel and the desktop pet show: the pin, else the companion.

        While a species is pinned the panel stops following the egg, the hatch
        and the evolutions — Home still shows all of it.
        """
        self.state.reconcile_representative()
        pinned = self.state.representative_species_id
        if pinned is not None:
            return pinned, bool(self.state.representative_is_shiny)
        mon = self.state.active
        if mon is None:
            return None, False
        return mon.current_id, mon.visible_shiny

    def panel_unown_form(self) -> str | None:
        if self.state.representative_species_id is not None:
            return self.state.representative_unown_form
        mon = self.state.active
        return forms.resolved(mon.current_id, mon.unown_form) if mon else None

    def panel_sprite_path(self) -> str:
        species_id, shiny = self.panel_species()
        if species_id is None:
            # An egg is what the panel and the pet show before the first hatch.
            # Returning nothing left both of them blank.
            return self._egg_sprite()
        if self.sprites is None:
            return ""
        return self._sprite(species_id, True, shiny, self.panel_unown_form())

    def set_representative(self, species_id: int | None, is_shiny: bool | None = None,
                           unown_form: str | None = None) -> str:
        """Pin a species to the panel, or clear the pin with None.

        Refuses a species the user does not own rather than storing it and
        letting reconcile silently drop it — the caller gets told why.
        """
        if species_id is not None and not self.state.owns_species(species_id):
            raise ValueError(f"species {species_id} is not in your Pokedex")
        form = forms.resolved(species_id, unown_form)
        if species_id is not None:
            candidates = {
                (shiny, letter) for shiny, letter in self.state.appearances(species_id)
                if (unown_form is None or letter == form)
                and (is_shiny is None or shiny == is_shiny)
            }
            if not candidates:
                raise ValueError("this appearance is not in your Pokedex")
            previous = (self.state.representative_is_shiny, self.state.representative_unown_form)
            if self.state.representative_species_id == species_id and previous in candidates:
                is_shiny, form = previous
            else:
                is_shiny, form = min(candidates, key=lambda appearance: (
                    not appearance[0], forms.sort_order(species_id, appearance[1])))
        self.state.representative_species_id = species_id
        self.state.representative_is_shiny = is_shiny if species_id is not None else None
        self.state.representative_unown_form = form
        self._persist()
        if species_id is None:
            return "panel follows your companion again"
        return f"panel pinned to #{species_id}"

    def _panel_fields(self) -> dict:
        """Panel and pet sprite, which the pin overrides.

        Shipped alongside the companion rather than replacing it: Home reads the
        companion's own sprite, so pinning must not hide what is being raised.
        """
        species_id, shiny = self.panel_species()
        return {
            "panel_species_id": species_id,
            "panel_is_shiny": shiny,
            "panel_unown_form": self.panel_unown_form(),
            "panel_sprite_path": self.panel_sprite_path(),
            "representative_species_id": self.state.representative_species_id,
            "representative_is_shiny": self.state.representative_is_shiny,
            "representative_unown_form": self.state.representative_unown_form,
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
            return l10n.format_text(l10n.t("status_evolved", language), name)
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
            threshold = self._egg_threshold()
            progress = min(1.0, self.state.egg_usage / threshold)
            return {
                "stage": "egg",
                "label": f"\N{EGG}{round(progress * 100)}%",
                "egg_usage": self.state.egg_usage,
                "egg_threshold": threshold,
                "egg_progress": round(progress, 4),
                "egg_tier": str(self.state.egg_tier) if self.state.egg_tier else None,
                "hatch_status": ("delayed" if self.hatch_error else "ready") if progress >= 1 else "incubating",
                "hatch_error": self.hatch_error if progress >= 1 else None,
                "can_retry_hatch": progress >= 1,
                "is_high_value": False,
                # The real egg from PokeAPI, cropped to its content. It is a
                # 96x96 canvas around a 28x30 egg, so drawn uncropped it is a
                # third the size of every sprite beside it — and before this
                # the egg stage had no picture at all.
                "sprite_path": self._egg_sprite(),
                "dex_count": len(self.state.dex),
                "spendable_tokens": self.state.spendable_tokens,
                "spendable_text": _compact(self.state.spendable_tokens),
                "display_state": kind,
                "status_message": self._status_message(kind),
                **self._panel_fields(),
            }

        threshold = self._stage_threshold(mon)
        # Remaining to the NEXT step: an evolution mid-line, graduation at the end.
        remaining = max(0, threshold - mon.used_at_stage)
        evo_line = []
        if self.sprites is not None:
            for index, species_id in enumerate(mon.path_ids):
                evo_line.append(
                    {
                        "species_id": species_id,
                        "name": self._display_name(species_id, mon.unown_form),
                        "sprite_path": self._sprite(species_id, False, mon.visible_shiny, mon.unown_form),
                        "unown_form": forms.resolved(species_id, mon.unown_form),
                        "current": index == mon.stage_index,
                        "reached": index <= mon.stage_index,
                    }
                )
        return {
            "stage": "mon",
            "label": "",
            "species_id": mon.current_id,
            "name": self._display_name(mon.current_id, mon.unown_form),
            "unown_form": forms.resolved(mon.current_id, mon.unown_form),
            "is_high_value": shop.is_high_value(self.state),
            "can_retry_hatch": False,
            "is_final_form": mon.is_final_form,
            "remaining_tokens": remaining,
            "remaining_text": _compact(remaining),
            "goal": "graduation" if mon.is_final_form else "next evolution",
            "evo_line": evo_line,
            "is_shiny": mon.visible_shiny,
            "nature": mon.nature,
            "profile": self._profile_payload(mon.profile, mon.current_id, mon.nature),
            "growth_multiplier": 2 if mon.has_growth_boost else 1,
            "rarity": str(mon.rarity),
            "stage_index": mon.stage_index,
            "total_forms": mon.total_forms,
            "used_at_stage": mon.used_at_stage,
            "stage_threshold": threshold,
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

    def grant_candy(self, windows: dict[str, float], epochs: dict[str, str] | None = None) -> int:
        granted = shop.grant_candy(self.state, windows, epochs)
        self._persist()
        return granted

    def buy(self, key: str, confirmed: bool = False, count: int = 1) -> str:
        message = shop.buy(self.state, key, self.shop_difficulty, confirmed=confirmed, count=count)
        self.hatch_error = None
        self._persist()
        return message

    def use_item(self, key: str, count: int = 1) -> str:
        message = shop.use_item(
            self.state, key, rng=self.rng,
            growth_difficulty=self.growth_difficulty,
            count=count,
        )
        self._sync_profile()
        self._persist()
        return message

    def candy_preview(self, count: int = 1) -> dict | None:
        preview = shop.candy_preview(self.state, count, self.growth_difficulty)
        if preview is not None:
            preview["xp_gain"] = preview["xp"]
        return preview

    def _egg_sprite(self) -> str:
        if self.sprites is None:
            return ""
        path = self.sprites.egg_path()
        return str(path) if path else ""

    def _item_sprite(self, key: str) -> str:
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
        experience = _compact(balance.RARE_CANDY_XP * self.state.balance_multiplier)
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
        for e in shop.entries(self.state, self.shop_difficulty):
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
            out.append(
                {
                    "key": e.key,
                    "kind": e.kind,
                    "price": e.price,
                    "price_text": _compact(e.price),
                    "max_buy_count": (min(99, self.state.spendable_tokens // max(1, e.price))
                                      if e.key in ("rareCandy", "mint") else int(not e.owned and self.state.spendable_tokens >= e.price)),
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
                    "affordable": spendable >= e.price and not e.owned,
                    "requires_confirmation": e.kind == "egg" and shop.is_high_value(self.state),
                }
            )
        return out

    def bag_payload(self) -> list[dict]:
        emoji = {"rareCandy": "\N{CANDY}", "mint": "\N{HERB}", "shinyCharm": "\N{SPARKLES}"}
        return [
            {
                "key": key,
                "label": self._item_words(key)[0],
                "description": self._item_words(key)[1],
                "effect": self._item_words(key)[2],
                "sprite_path": self._item_sprite(key),
                "emoji": emoji.get(key, "?"),
                "count": count,
                # Passive items are held, not consumed.
                "usable": key in ("rareCandy", "mint") and self.state.active is not None,
                "passive": key == "shinyCharm",
                "max_use_count": (shop.max_candy_use_count(self.state, self.growth_difficulty)
                                  if key == "rareCandy" else 1),
                "per_candy_xp": balance.RARE_CANDY_XP * self.state.balance_multiplier if key == "rareCandy" else 0,
                "preview": self.candy_preview() if key == "rareCandy" else None,
                "previews": [self.candy_preview(amount) for amount in range(
                    1, shop.max_candy_use_count(self.state, self.growth_difficulty) + 1)]
                    if key == "rareCandy" else [],
            }
            for key, count in sorted(self.state.inventory.items())
            if count > 0
        ]

    def dex_payload(self) -> list[dict]:
        """Species-level collection — ports dexSpecies.

        Includes every species in a graduated chain, plus the CURRENT
        companion's reached forms only (path_ids up to stage_index). The
        planned path is never used: it contains stages not yet evolved into,
        which would list species that have never been owned.

        A species backed only by the current companion is flagged is_raising.
        Graduation or release moves its reached forms into permanent records.
        """
        acc: dict[int, dict] = {}

        for entry in self.state.dex:
            for species_id in entry.chain_order:
                slot = acc.setdefault(
                    species_id,
                    {"rarity": str(entry.rarity), "is_shiny": False, "graduated": False},
                )
                if entry.is_shiny:
                    slot["is_shiny"] = True
                slot["graduated"] = True

        mon = self.state.active
        if mon is not None:
            for species_id in self.state.reached_species():
                slot = acc.setdefault(
                    species_id,
                    {"rarity": str(mon.rarity), "is_shiny": False, "graduated": False},
                )
                if mon.visible_shiny:
                    slot["is_shiny"] = True

        out = []
        for species_id in sorted(acc):
            slot = acc[species_id]
            individuals = [entry for entry in self.state.dex if entry.final_id == species_id]
            if mon is not None and mon.current_id == species_id:
                individuals.append(mon)
            profiles = []
            profiles_by_appearance = {}
            for individual in individuals:
                profile = self._profile_payload(individual.profile, species_id, individual.nature)
                if profile is None:
                    continue
                profiles.append(profile)
                color = individual.visible_shiny if individual is mon else individual.is_shiny
                appearance_key = (color, forms.resolved(species_id, individual.unown_form))
                profiles_by_appearance.setdefault(appearance_key, []).append(profile)
            appearances = [
                {"is_shiny": shiny, "unown_form": form,
                 "name": self._display_name(species_id, form),
                 "sprite_path": self._sprite(species_id, False, shiny, form),
                 "profiles": profiles_by_appearance.get((shiny, form), [])}
                for shiny, form in sorted(self.state.appearances(species_id),
                    key=lambda value: (forms.sort_order(species_id, value[1]), value[0]))
            ]
            preferred = next((a for a in appearances if a["is_shiny"]), appearances[0])
            cached_details = getattr(self.api, 'cached_details', None)
            details = cached_details(species_id) if callable(cached_details) else None
            types = (details or {}).get('types') or (profiles[0].get('types', []) if profiles else [])
            out.append(
                {
                    "final_id": species_id,
                    "species_id": species_id,
                    "name": self.species_name(species_id, self.state.language),
                    "types": list(types),
                    "details": (self._detail_payloads.get(species_id)
                                if self._detail_payloads.get(species_id, {}).get("language") == self.state.language else None),
                    "details_status": (self._detail_status.get(species_id, "idle")
                                       if self._detail_payloads.get(species_id, {}).get("language", self.state.language) == self.state.language else "idle"),
                    "type_badges": pokemon_types.badges(types, self.state.language),
                    "rarity": slot["rarity"],
                    "is_shiny": slot["is_shiny"],
                    "is_raising": not slot["graduated"],
                    "sprite_path": (self._sprite(species_id, False, slot["is_shiny"])
                                    if species_id == 201 else preferred["sprite_path"]),
                    "unown_form": preferred["unown_form"],
                    "appearances": appearances,
                    "form_count": len({a["unown_form"] for a in appearances}) if forms.forms(species_id) else 0,
                    "unown_forms": len({a["unown_form"] for a in appearances}) if species_id == 201 else 0,
                    "forms": [{"unown_form": form, "symbol": forms.symbol(form) if species_id == 201 else form.replace("-", " ").title(),
                               "owned": any(a["unown_form"] == form for a in appearances),
                               "appearances": [a for a in appearances if a["unown_form"] == form]}
                              for form in forms.forms(species_id)],
                    "profiles": profiles,
                }
            )
        return out

    def _chain(self, species_ids, shiny: bool, form: str | None = None) -> list[dict]:
        out = []
        for species_id in species_ids:
            out.append(
                {
                    "species_id": species_id,
                    "name": self._display_name(species_id, form),
                    "sprite_path": self._sprite(species_id, False, shiny, form),
                    "unown_form": forms.resolved(species_id, form),
                }
            )
        return out

    def catch_log_payload(self) -> list[dict]:
        """Every catch, newest first, with its full evolution chain.

        Entries predating caught_at sort last rather than pretending to be
        ancient; ordering among them is unspecified.
        """
        out = [
            {
                "rarity": str(e.rarity),
                "nature": e.nature,
                "is_shiny": e.is_shiny,
                "chain": self._chain(e.chain_order, e.is_shiny, e.unown_form),
                "unown_form": forms.resolved(e.final_id, e.unown_form),
                "is_released": e.is_released,
                "caught_at": e.caught_at,
                "raised_text": _duration(e.raised_seconds),
                "raising": False,
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
                    "nature": mon.nature,
                    "is_shiny": mon.visible_shiny,
                    "chain": self._chain(self.state.reached_species(), mon.visible_shiny, mon.unown_form),
                    "unown_form": forms.resolved(mon.current_id, mon.unown_form),
                    "is_released": False,
                    "caught_at": mon.hatched_at,
                    "raised_text": "",
                    "raising": True,
                },
            )
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
        save.save(self.state, self.save_path)

    def snapshots_payload(self) -> list[dict]:
        from . import snapshots

        return snapshots.list_snapshots(self.save_path)

    def create_snapshot(self) -> dict:
        from . import snapshots

        return snapshots.create_snapshot(self.state, self.save_path)

    def restore_snapshot(self, snapshot_id: str) -> str:
        from . import snapshots, transfer

        restored = snapshots.read_snapshot(snapshot_id, self.save_path)
        # A failed safety copy must leave both the live and on-disk state alone.
        self.create_snapshot()
        restored = transfer.rebase(restored, self.state)
        save.save(restored, self.save_path)
        self.state = restored
        self._ensure_profiles()
        self.hatch_error = None
        self.last_events = None
        self.celebration = None
        return "restored local snapshot"
