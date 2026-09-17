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
    ) -> None:
        self.save_path = save_path
        self.state: CompanionState = save.load(save_path)
        self.api = api
        self.sprites = sprite_store
        self.rng = rng or random.Random()
        # Held for one poll so the popup can show a celebration banner; the
        # notification fires immediately but the banner needs a render pass.
        self.celebration: dict | None = None
        self.last_events: companion.GrowthEvents | None = None

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

        if delta <= 0:
            self._persist()
            return

        line = self._line_for_egg() if self.state.active is None else None
        events = companion.apply_usage(
            self.state, delta, line_for_egg=line, rng=self.rng
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
            self.celebration = banner(
                "graduated", "notif_graduate_title", "notif_graduate_body", label)
        elif events.evolved_to is not None:
            self.celebration = banner(
                "evolved", "notif_evolve_title", "notif_evolve_body", label)
        elif events.hatched is not None:
            self.celebration = banner(
                "shiny" if shiny else "hatched",
                "notif_shiny_hatch_title" if shiny else "notif_hatch_title",
                "notif_shiny_hatch_body" if shiny else "notif_hatch_body",
                label)
        else:
            return False
        return True

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
        if self.sprites is None:
            return ""
        # Nothing pinned and nothing hatched: the panel and the desktop pet
        # show the egg rather than going blank.
        if species_id is None:
            return self._egg_sprite()
        path = self.sprites.path(species_id, animated=True, shiny=shiny)
        return str(path) if path else ""

    def set_representative(self, species_id: int | None) -> str:
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
        if species_id is not None and species_id == self.state.representative_species_id:
            species_id = None
        if species_id is not None and not self.state.owns_species(species_id):
            raise ValueError(f"species {species_id} is not in your Pokedex")
        self.state.representative_species_id = species_id
        self._persist()
        language = self.state.language
        if species_id is None:
            return l10n.t("panel_unpinned", language)
        name = self.species_name(species_id, language) or f"#{species_id}"
        return l10n.t("panel_pinned", language).replace("%1", name)

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
                else self.species_name(species_id, self.state.language)
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
            progress = min(1.0, self.state.egg_usage / balance.EGG_HATCH_THRESHOLD)
            return {
                "stage": "egg",
                "label": f"\N{EGG}{round(progress * 100)}%",
                "egg_usage": self.state.egg_usage,
                "egg_progress": round(progress, 4),
                "egg_tier": str(self.state.egg_tier) if self.state.egg_tier else None,
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

        threshold = balance.phase_threshold(mon.rarity, mon.total_forms, mon.stage_index)
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
        result = shop.buy(self.state, key)
        # A bought egg discards the companion, so a pin that was following it
        # names a species nobody owns any more.
        self.state.reconcile_representative()
        self._persist()
        return self._shop_message(result)

    def use_item(self, key: str) -> str:
        result = shop.use_item(self.state, key, rng=self.rng)
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
            return l10n.t("shop_nature_now", language).replace("%1", result.nature)
        key = "shop_bought" if result.action == "buy" else "shop_used"
        return l10n.t(key, language).replace("%1", self._label_for(result.key))

    def _item_banner(self, result: shop.ItemResult) -> dict:
        """The popup banner for an item use that changed no threshold."""
        language = self.state.language
        detail = (
            l10n.t("shop_nature_now", language).replace("%1", result.nature)
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
                sprite = self._item_sprite("egg")
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
                    "sprite_path": sprite,
                    "emoji": {"rareCandy": "\N{CANDY}", "mint": "\N{HERB}",
                              "shinyCharm": "\N{SPARKLES}"}.get(e.key, "\N{EGG}"),
                    "owned": e.owned,
                    "owned_count": self.state.inventory.get(e.key, 0),
                    "affordable": spendable >= e.price and not e.owned and not locked,
                    "locked": locked,
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
                    {"rarity": str(entry.rarity), "is_shiny": False},
                )
                if entry.is_shiny:
                    slot["is_shiny"] = True

        mon = self.state.active
        if mon is not None:
            for species_id in mon.path_ids[: mon.stage_index + 1]:
                slot = acc.setdefault(
                    species_id,
                    {"rarity": str(mon.rarity), "is_shiny": False},
                )
                if mon.is_shiny:
                    slot["is_shiny"] = True

        # Which cell is holding the panel. Without this the pin was invisible:
        # the panel stopped following the companion and nothing anywhere said
        # why, or which of these cells to tap to give it back.
        self.state.reconcile_representative()
        pinned = self.state.representative_species_id
        raising = mon.current_id if mon is not None else None

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
                    "is_raising": species_id == raising,
                    "is_pinned": species_id == pinned,
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
