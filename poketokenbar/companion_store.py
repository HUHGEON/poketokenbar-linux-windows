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

from . import balance, companion, l10n, pokeapi, save, shop, sprites
from .companion import CompanionState
from .format import compact as _compact
from .plan import MULTIPLIERS


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
                base = balance.phase_threshold(
                    mon.rarity, mon.total_forms, mon.stage_index,
                    self.state.balance_multiplier,
                )
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
        return balance.scale_difficulty(
            balance.phase_threshold(
                mon.rarity, mon.total_forms, mon.stage_index,
                self.state.balance_multiplier,
            ),
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

        claimed = self.state.claimed_today_tokens_by_provider

        delta = 0
        for provider_id, total in totals_by_provider.items():
            previous = claimed.get(provider_id, 0)
            # A total going backwards (log rotation, cache rebuild) must not
            # produce a negative delta.
            if total > previous:
                delta += total - previous
            claimed[provider_id] = total

        if delta <= 0:
            self._persist()
            return

        line = self._line_for_egg() if self.state.active is None else None
        self.last_events = companion.apply_usage(
            self.state, delta, line_for_egg=line, rng=self.rng,
            growth_difficulty=self.growth_difficulty,
        )
        self._note_celebration(self.last_events)
        self._persist()

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
        name = self.species_name(mon.current_id, language) if mon else ""
        label = name or l10n.t("raising", language)
        shiny = mon is not None and mon.is_shiny

        def banner(kind: str, title_key: str, body_key: str, subject: str) -> dict:
            return {
                "kind": kind,
                "title": l10n.t(title_key, language),
                "detail": l10n.t(body_key, language).replace("%1", subject),
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
        path = self.sprites.path(mon.current_id, animated=True, shiny=mon.is_shiny)
        return str(path) if path else ""

    def panel_species(self) -> tuple[int | None, bool]:
        """What the panel and the desktop pet show: the pin, else the companion.

        While a species is pinned the panel stops following the egg, the hatch
        and the evolutions — Home still shows all of it.
        """
        self.state.reconcile_representative()
        pinned = self.state.representative_species_id
        if pinned is not None:
            return pinned, self.state.owns_shiny_species(pinned)
        mon = self.state.active
        if mon is None:
            return None, False
        return mon.current_id, mon.is_shiny

    def panel_sprite_path(self) -> str:
        species_id, shiny = self.panel_species()
        if species_id is None:
            # An egg is what the panel and the pet show before the first hatch.
            # Returning nothing left both of them blank.
            return self._egg_sprite()
        if self.sprites is None:
            return ""
        path = self.sprites.path(species_id, animated=True, shiny=shiny)
        return str(path) if path else ""

    def set_representative(self, species_id: int | None) -> str:
        """Pin a species to the panel, or clear the pin with None.

        Refuses a species the user does not own rather than storing it and
        letting reconcile silently drop it — the caller gets told why.
        """
        if species_id is not None and not self.state.owns_species(species_id):
            raise ValueError(f"species {species_id} is not in your Pokedex")
        self.state.representative_species_id = species_id
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
            "panel_sprite_path": self.panel_sprite_path(),
            "representative_species_id": self.state.representative_species_id,
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
            return l10n.t("status_evolved", language).replace("%1", name)
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
                "egg_progress": round(progress, 4),
                "egg_tier": str(self.state.egg_tier) if self.state.egg_tier else None,
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
                path = self.sprites.path(species_id, animated=False, shiny=mon.is_shiny)
                evo_line.append(
                    {
                        "species_id": species_id,
                        "name": self.species_name(species_id, self.state.language),
                        "sprite_path": str(path) if path else "",
                        "current": index == mon.stage_index,
                        "reached": index <= mon.stage_index,
                    }
                )
        return {
            "stage": "mon",
            "label": "",
            "species_id": mon.current_id,
            "name": self.species_name(mon.current_id, self.state.language),
            "is_final_form": mon.is_final_form,
            "remaining_tokens": remaining,
            "remaining_text": _compact(remaining),
            "goal": "graduation" if mon.is_final_form else "next evolution",
            "evo_line": evo_line,
            "is_shiny": mon.is_shiny,
            "nature": mon.nature,
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

    def grant_candy(self, windows: dict[str, float]) -> int:
        granted = shop.grant_candy(self.state, windows)
        self._persist()
        return granted

    def buy(self, key: str) -> str:
        message = shop.buy(self.state, key, self.shop_difficulty)
        self._persist()
        return message

    def use_item(self, key: str) -> str:
        message = shop.use_item(
            self.state, key, rng=self.rng,
            growth_difficulty=self.growth_difficulty,
        )
        self._persist()
        return message

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

        A species backed only by the current companion is flagged is_raising —
        buying an egg discards that companion and the entry disappears, so it
        is not yet permanent.
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
            for species_id in mon.path_ids[: mon.stage_index + 1]:
                slot = acc.setdefault(
                    species_id,
                    {"rarity": str(mon.rarity), "is_shiny": False, "graduated": False},
                )
                if mon.is_shiny:
                    slot["is_shiny"] = True

        out = []
        for species_id in sorted(acc):
            slot = acc[species_id]
            sprite = ""
            if self.sprites is not None:
                path = self.sprites.path(
                    species_id, animated=False, shiny=slot["is_shiny"]
                )
                sprite = str(path) if path else ""
            out.append(
                {
                    "final_id": species_id,
                    "species_id": species_id,
                    "name": self.species_name(species_id, self.state.language),
                    "rarity": slot["rarity"],
                    "is_shiny": slot["is_shiny"],
                    "is_raising": not slot["graduated"],
                    "sprite_path": sprite,
                }
            )
        return out

    def _chain(self, species_ids, shiny: bool) -> list[dict]:
        out = []
        for species_id in species_ids:
            sprite = ""
            if self.sprites is not None:
                path = self.sprites.path(species_id, animated=False, shiny=shiny)
                sprite = str(path) if path else ""
            out.append(
                {
                    "species_id": species_id,
                    "name": self.species_name(species_id, self.state.language),
                    "sprite_path": sprite,
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
                "chain": self._chain(e.chain_order, e.is_shiny),
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
                    "is_shiny": mon.is_shiny,
                    "chain": self._chain(mon.path_ids[: mon.stage_index + 1], mon.is_shiny),
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
