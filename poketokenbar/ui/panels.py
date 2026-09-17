"""The tabs of the popup window.

Each panel owns a layout and a single `update(state)`. Rebuilding the children
on every poll is the simplest correct thing at these sizes, with one exception:
sprites are handed a path and decide for themselves whether anything changed,
because rebuilding a QMovie restarts the animation from frame one.

Nothing here reimplements the file protocol. The panels read the same payload
`poketokenbar.state.build` produced and, where they write, call the daemon's own
`commands` and `config` modules — so unlike a front end in another language
there is no contract between the two halves to get wrong.
"""

from __future__ import annotations

from datetime import datetime, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout, QLineEdit,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from .. import balance, commands, config, l10n
from .widgets import (
    Sprite, button, card, clear_layout, column, heading, label, level_colour,
    meter, row, separator, stat_line,
)

# How many Pokedex cells fit on a page, matching upstream's grid.
DEX_PER_PAGE = 24
DEX_COLUMNS = 6


def resets_in(iso: str | None, strings) -> str:
    """"2h 15m" from an ISO instant.

    `resets_at` arrives as the raw timestamp the API returned; printed verbatim
    it is data rather than an answer to "how long have I got".
    """
    if not iso:
        return ""
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    remaining = (moment - datetime.now(timezone.utc)).total_seconds()
    if remaining <= 0:
        return strings("resetting_now")
    minutes = int(remaining // 60)
    hours, days = minutes // 60, minutes // 1440
    if days > 0:
        return f"{days}d {hours % 24}h"
    if hours > 0:
        return f"{hours}h {minutes % 60}m"
    return f"{minutes}m"


def ago(seconds: float | None) -> str:
    if seconds is None:
        return ""
    if seconds < 90:
        return "just now"
    return f"{round(seconds / 60)} min ago"


class Panel(QWidget):
    """A scrollable column that empties itself before each update."""

    def __init__(self, reader) -> None:
        super().__init__()
        self.reader = reader
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        # Never horizontal: the window has a fixed width, so a sideways bar
        # would only ever mean something is laid out wrong.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setAlignment(Qt.AlignTop)
        scroll.setWidget(self.body)
        outer.addWidget(scroll)

    def t(self, key: str) -> str:
        return self.reader.text(key)

    def clear(self) -> None:
        clear_layout(self.layout_)

    def add(self, widget: QWidget) -> None:
        self.layout_.addWidget(widget)


class HomePanel(Panel):
    def __init__(self, reader) -> None:
        super().__init__(reader)
        # Held across rebuilds so its animation is not restarted every poll.
        self.sprite = Sprite(96)

    def update(self, state: dict | None) -> None:
        self.clear()
        companion = (state or {}).get("companion") or {}

        banner = (state or {}).get("celebration") or {}
        if banner.get("kind"):
            self.add(label(banner.get("title", ""), bold=True))
            if banner.get("detail"):
                self.add(label(banner["detail"], dim=True))

        if companion:
            # Home always shows what is being raised, never the pinned species:
            # pinning changes the tray icon, and hiding the companion here would
            # make its progress unreachable.
            self.sprite.set_path(companion.get("sprite_path") or None)
            self.sprite.setParent(None)
            self.add(self.sprite)

            if companion.get("stage") == "egg":
                self.add(label(self.t("egg"), bold=True, size=16))
                self.add(meter(companion.get("egg_progress", 0)))
                self.add(label(companion.get("label", ""), dim=True))
            else:
                name = companion.get("name") or f"#{companion.get('species_id')}"
                self.add(label(
                    f"✨ {name}" if companion.get("is_shiny") else name,
                    bold=True, size=16))
                traits = (f"{self.t(companion.get('rarity', 'common'))}"
                          f" · {companion.get('nature', '')}")
                # A repeat hatch grows faster; say so, or the meter looks wrong.
                if companion.get("growth_multiplier"):
                    boost = self.t("growth_boost").replace(
                        "%1", str(companion["growth_multiplier"]))
                    traits = f"{traits} · {boost}"
                self.add(label(traits, dim=True))
                self.add(meter(companion.get("stage_progress", 0)))
                goal = self.t(
                    "graduation" if companion.get("is_final_form") else "next_evolution")
                self.add(label(f"{companion.get('remaining_text', '')} → {goal}", dim=True))
                self.add(self._evolution_line(companion))
            self.add(label(companion.get("status_message", ""), dim=True))

        self.add(separator())
        today = (state or {}).get("today") or {}
        self.add(heading(self.t("todays_tokens")))
        self.add(stat_line(self.t("todays_tokens"), today.get("tokens_grouped", "0")))
        if today.get("cost_text"):
            self.add(stat_line("", today["cost_text"]))

        periods = (state or {}).get("periods") or {}
        for key, name in (("week", "this_week"), ("month", "this_month")):
            period = periods.get(key)
            if period:
                text = period.get("tokens_text", "")
                if period.get("cost_text"):
                    text = f"{text} · {period['cost_text']}"
                self.add(stat_line(self.t(name), text))

        # Only worth the rows when the day actually spanned several models.
        models = today.get("models") or []
        if len(models) > 1:
            for model_row in models[:6]:
                self.add(stat_line(model_row["model"], model_row["total_tokens_text"]))

        providers = (state or {}).get("providers") or {}
        if len(providers) > 1:
            for provider_id, usage in providers.items():
                self.add(stat_line(provider_id, usage["total_tokens_text"]))
                self.add(label(
                    f"in {usage['input_tokens']} · out {usage['output_tokens']}"
                    f" · cache w {usage['cache_creation_tokens']}"
                    f" · r {usage['cache_read_tokens']}", dim=True))

        self._add_status(state)
        self._add_limits(state)

    def _evolution_line(self, companion: dict) -> QWidget:
        line = QWidget()
        layout = QHBoxLayout(line)
        layout.setContentsMargins(0, 0, 0, 0)
        for stage in companion.get("evo_line") or []:
            sprite = Sprite(40)
            sprite.set_path(stage.get("sprite_path") or None)
            # Forms it has not reached are dimmed rather than hidden, so the
            # line still shows where the companion is heading.
            if not stage.get("reached"):
                sprite.setStyleSheet("opacity: 0.4;")
            layout.addWidget(sprite)
        layout.addStretch(1)
        return line

    def _add_status(self, state: dict | None) -> None:
        # Every row here is already a problem: the daemon drops the healthy
        # ones, and an unreachable status page is left out rather than reported
        # as an outage.
        for provider_id, status in ((state or {}).get("provider_status") or {}).items():
            self.add(stat_line(
                provider_id, status.get("label", ""),
                colour=level_colour(status.get("severity"))))

    def _add_limits(self, state: dict | None) -> None:
        limits = (state or {}).get("limits") or {}
        if not limits.get("session") and not limits.get("weekly"):
            return
        self.add(separator())

        plan = limits.get("plan")
        self.add(heading(
            f"{self.t('limits_official')} · {str(plan).upper()}" if plan
            else self.t("limits_official")))

        # Which account these belong to. Someone signed into two is otherwise
        # reading a bar for the other one.
        account = limits.get("account") or {}
        who = account.get("email") or account.get("name")
        if who:
            organization = account.get("organization")
            self.add(label(f"{who} · {organization}" if organization else who, dim=True))

        for key, name in (("session", "five_hour_session"), ("weekly", "weekly")):
            window = limits.get(key)
            if not window:
                continue
            percent = round(window.get("utilization", 0))
            self.add(stat_line(
                self.t(name), f"{percent}%", colour=level_colour(window.get("severity"))))
            self.add(meter(percent / 100, window.get("severity")))
            countdown = resets_in(window.get("resets_at"), self.t)
            if countdown:
                self.add(label(countdown, dim=True))
            burn = ((state or {}).get("burn") or {}).get(key) or {}
            if burn.get("eta_text"):
                self.add(label(
                    self.t("at_this_rate").replace("%1", burn["eta_text"]), dim=True))


class ShopPanel(Panel):
    def update(self, state: dict | None) -> None:
        self.clear()
        companion = (state or {}).get("companion") or {}
        self.add(heading(self.t("spendable_tokens")))
        self.add(label(companion.get("spendable_text", "0"), bold=True, size=16))
        self.add(label(self.t("spend_hint"), dim=True))

        for item in (state or {}).get("shop") or []:
            lines = [
                label(item.get("label") or item["key"]),
                label(item.get("description", ""), dim=True),
            ]
            # An egg during the egg stage: the disabled button needs a reason
            # the price does not give.
            if item.get("locked"):
                lines.append(label(self.t("egg_shop_locked_hint"), dim=True))
            left = column(*lines)
            widgets = [left]
            if item.get("owned_count"):
                widgets.append(label(f"{self.t('owned')} x{item['owned_count']}", dim=True))
            widgets.append(label(item.get("price_text", "")))
            if item.get("owned"):
                # Already held: a live Buy button would offer a purchase the
                # daemon refuses.
                widgets.append(label(self.t("owned")))
            else:
                # Disabled rather than hidden while unaffordable: a card that
                # vanishes reads as a bug, and the price is the point of the row.
                widgets.append(button(
                    self.t("buy"),
                    lambda _=False, key=item["key"]: commands.enqueue("buy", {"key": key}),
                    enabled=bool(item.get("affordable")),
                ))
            self.add(card(*widgets))


class BagPanel(Panel):
    def update(self, state: dict | None) -> None:
        self.clear()
        items = (state or {}).get("bag") or []
        if not items:
            self.add(label(self.t("bag_empty"), dim=True))
            return
        for item in items:
            left = column(
                label(f"{item.get('label') or item['key']} ×{item.get('count', 0)}"),
                label(item.get("effect") or item.get("description", ""), dim=True),
            )
            widgets = [left]
            if item.get("usable"):
                widgets.append(button(
                    self.t("use"),
                    lambda _=False, key=item["key"]: commands.enqueue("use", {"key": key}),
                ))
            elif item.get("passive"):
                widgets.append(label(self.t("active")))
            self.add(card(*widgets))


class CollectionPanel(Panel):
    def __init__(self, reader) -> None:
        super().__init__(reader)
        self._showing_log = False
        self._page = 0
        self._state: dict | None = None
        # The species whose Pokédex page is open, and which individual.
        self._inspecting: int | None = None
        self._individual = 0
        self._showing_moves = False

    def update(self, state: dict | None) -> None:
        self._state = state
        self.clear()
        self.add(row(
            button(self.t("pokedex"), lambda: self._show(False)),
            button(self.t("catch_log"), lambda: self._show(True)),
        ))
        if self._inspecting is not None:
            self._build_detail(state)
        elif self._showing_log:
            self._build_log(state)
        else:
            self._build_dex(state)

    def _show(self, log: bool) -> None:
        self._showing_log = log
        self._close(refresh=False)
        self.update(self._state)

    def _open(self, species_id: int) -> None:
        self._inspecting = species_id
        self._individual = 0
        self._showing_moves = False
        commands.enqueue("inspect", {"species_id": str(species_id)})
        self.update(self._state)

    def _close(self, refresh: bool = True) -> None:
        if self._inspecting is not None:
            self._inspecting = None
            commands.enqueue("inspect", {"species_id": "none"})
        if refresh:
            self.update(self._state)

    def _pick(self, index: int) -> None:
        self._individual = index
        self.update(self._state)

    def _toggle_moves(self) -> None:
        self._showing_moves = not self._showing_moves
        self.update(self._state)

    def _build_detail(self, state: dict | None) -> None:
        """The Pokédex page, as text: the same blocks the GNOME page shows."""
        detail = (state or {}).get("detail") or {}
        species_id = self._inspecting
        self.add(row(button(f"‹ {self.t('detail_back')}", self._close),
                     label(f"#{species_id}", dim=True)))
        if detail.get("species_id") != species_id or detail.get("status") == "loading":
            self.add(label(self.t("loading_pokemon_details"), dim=True))
            return

        sprite = Sprite(80)
        sprite.set_path(detail.get("sprite_path") or None)
        pinned = detail.get("is_pinned")
        marks = " ".join(
            word for word, on in (("✨", detail.get("is_shiny")),
                                  (self.t("raising"), detail.get("is_raising"))) if on)
        self.add(row(sprite, column(
            label(detail.get("name", ""), bold=True, size=16),
            label(f"{self.t(detail.get('rarity') or 'common')} {marks}".strip(), dim=True),
            button(self.t("unpin") if pinned else self.t("pin_to_panel"),
                   lambda _=False: commands.enqueue(
                       "represent", {"species_id": "none" if pinned else str(species_id)})),
        )))

        if detail.get("status") == "failed":
            self.add(label(self.t("pokemon_details_unavailable"), dim=True))
            self.add(button(self.t("retry"), lambda _=False: commands.enqueue(
                "inspect", {"species_id": str(species_id), "retry": True})))
            return

        individuals = detail.get("individuals") or []
        if len(individuals) > 1:
            self.add(row(*(
                button(one["label"], lambda _=False, i=index: self._pick(i))
                for index, one in enumerate(individuals))))
        species = detail.get("species") or {}
        if individuals:
            one = individuals[min(self._individual, len(individuals) - 1)]
            self.add(heading(self.t("pokemon_individual")))
            for key, value in (("level", one.get("level")), ("gender", one.get("gender_text")),
                               ("nature", one.get("nature_text")),
                               ("ability", one.get("ability_text"))):
                self.add(row(label(self.t(key), dim=True), label(str(value))))
            self.add(heading(self.t("actual_stats")))
            for stat in one.get("stats") or []:
                self.add(row(label(stat["label"]), meter(stat["fraction"]),
                             label(str(stat["value"])), label(f"IV {stat['iv']}", dim=True)))
            self.add(heading(self.t("known_moves")))
            if not one.get("moves"):
                self.add(label(self.t("no_level_moves"), dim=True))
            for move in one.get("moves") or []:
                self.add(row(label(move["name"]), label(f"Lv. {move['level']}", dim=True)))
        else:
            self.add(heading(self.t("base_stats")))
            for stat in species.get("base_stats") or []:
                self.add(row(label(stat["label"]), meter(stat["fraction"]),
                             label(str(stat["value"]))))
        if not species:
            return
        self.add(heading(self.t("species_data")))
        self.add(label(" · ".join(species.get("types") or [])))
        for key, value in (("height", species.get("height_text")),
                           ("weight", species.get("weight_text")),
                           ("base_stat_total", species.get("base_total"))):
            self.add(row(label(self.t(key), dim=True), label(str(value))))
        self.add(heading(self.t("possible_abilities")))
        self.add(label(", ".join(species.get("abilities") or []), dim=True))
        self.add(button(
            self.t("complete_move_list").replace("%1", str(detail.get("move_count", 0))),
            self._toggle_moves))
        if self._showing_moves:
            for move in species.get("moves") or []:
                self.add(row(label(move["name"]), label(move["methods"], dim=True)))

    def _build_dex(self, state: dict | None) -> None:
        entries = (state or {}).get("dex") or []
        if not entries:
            self.add(label(self.t("no_pokemon_yet"), dim=True))
            return
        self.add(label(f"{len(entries)} species", dim=True))

        counts = (state or {}).get("rarity_counts") or {}
        summary = "  ".join(
            f"{self.t(key)} {counts[key]}"
            for key in ("legendary", "rare", "uncommon", "common")
            if counts.get(key)
        )
        if summary:
            self.add(label(summary, dim=True))

        pages = max(1, (len(entries) + DEX_PER_PAGE - 1) // DEX_PER_PAGE)
        self._page = min(self._page, pages - 1)
        page = entries[self._page * DEX_PER_PAGE:(self._page + 1) * DEX_PER_PAGE]

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        for index, entry in enumerate(page):
            grid.addWidget(self._cell(entry), index // DEX_COLUMNS, index % DEX_COLUMNS)
        self.add(grid_widget)

        if pages > 1:
            self.add(row(
                button("‹", lambda: self._turn(-1)),
                label(f"{self._page + 1} / {pages}", dim=True),
                button("›", lambda: self._turn(1)),
            ))

    def _turn(self, direction: int) -> None:
        self._page = max(0, self._page + direction)
        self.update(self._state)

    def _cell(self, entry: dict) -> QWidget:
        sprite = Sprite(40)
        sprite.set_path(entry.get("sprite_path") or None)
        species = entry.get("species_id")
        caption = label(
            f"✨{species}" if entry.get("is_shiny") else f"#{species}", dim=True, size=10)
        parts = [sprite, caption]
        # The one being raised appears in the Pokedex before it graduates, and
        # without the badge it is indistinguishable from a finished catch.
        if entry.get("is_raising"):
            parts.append(label(self.t("raising"), dim=True, size=9))
        # Opens the species' page, which carries the pin. The daemon refuses a
        # species the save does not own, so this cannot reach a ghost.
        parts.append(button("ℹ", lambda _=False, sid=species: self._open(sid)))
        return column(*parts)

    def _build_log(self, state: dict | None) -> None:
        log = (state or {}).get("catch_log") or []
        if not log:
            self.add(label(self.t("no_pokemon_yet"), dim=True))
            return
        self.add(label(f"{len(log)} total", dim=True))

        counts = (state or {}).get("catch_counts") or {}
        summary = "  ".join(
            f"{self.t(key)} {counts[key]}"
            for key in ("legendary", "rare", "uncommon", "common")
            if counts.get(key)
        )
        if summary:
            self.add(label(summary, dim=True))

        for record in log[:40]:
            chain = QWidget()
            chain_layout = QHBoxLayout(chain)
            chain_layout.setContentsMargins(0, 0, 0, 0)
            stages = record.get("chain") or []
            for stage in stages:
                sprite = Sprite(28)
                sprite.set_path(stage.get("sprite_path") or None)
                chain_layout.addWidget(sprite)
            # catch_log rows carry no name of their own; the last stage is what
            # it graduated as.
            final = stages[-1] if stages else {}
            name = final.get("name") or f"#{final.get('species_id', '')}"
            title = f"✨ {name}" if record.get("is_shiny") else name
            if record.get("raising"):
                title = f"{title}  [{self.t('raising')}]"
            elif record.get("released"):
                title = f"{title}  [{self.t('dex_released')}]"
            details = column(
                label(title),
                label(
                    f"{self.t(record.get('rarity', 'common'))}"
                    f" · {record.get('nature', '')}"
                    f" · {record.get('raised_text', '')}", dim=True),
            )
            self.add(card(chain, details))


class SettingsPanel(Panel):
    """Every setting the daemon has, plus the per-provider scan folders.

    Written through `poketokenbar.config`, the daemon's own module, so the two
    cannot disagree about defaults or about what a key is called.
    """

    # Numeric settings and their ranges. Outside these the daemon misbehaves
    # quietly — a two-second refresh hammers the disk, a 0px pet is invisible —
    # and a spin box cannot express a value outside its range.
    SPINS = (
        ("refresh_interval", "Refresh every (s)", 60, 900, 60),
        ("warn_threshold", "Warn at (%)", 50, 95, 5),
        ("crit_threshold", "Critical at (%)", 60, 99, 1),
        ("floating_pet_size", "Pet size (px)", 48, 192, 12),
    )
    TOGGLES = (
        ("show_tokens_in_menu", "Tokens in the tray tooltip"),
        ("show_cost_in_menu", "Cost in the tray tooltip"),
        ("show_limit_in_menu", "Limits in the tray tooltip"),
        ("limit_notifications", "Notify on limit warnings"),
        ("companion_notifications", "Notify on companion events"),
        ("status_checks_enabled", "Check provider status"),
        ("floating_pet_enabled", "Desktop pet"),
        ("floating_pet_bubble_alerts", "Pet speech bubbles"),
    )
    # Difficulty multipliers, chosen from balance.DIFFICULTY_STEPS. The daemon
    # keeps the earned fraction of the current egg or stage when growth changes.
    DIFFICULTIES = (
        ("growth_difficulty", "Growth difficulty"),
        ("shop_difficulty", "Shop price difficulty"),
    )
    CHOICES = (
        ("limit_display_mode", "Limits shown", ("both", "session", "weekly")),
        ("animation_quality", "Animation", ("off", "saver", "balanced", "smooth")),
        ("language", "Language", tuple(l10n.LANGUAGES)),
    )

    def update(self, state: dict | None) -> None:
        self.clear()
        values = (state or {}).get("config") or {}

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        for key, text in self.TOGGLES:
            box = QCheckBox()
            box.setChecked(bool(values.get(key)))
            box.toggled.connect(lambda checked, k=key: self._set(k, checked))
            form.addRow(text, box)

        for key, text, low, high, step in self.SPINS:
            spin = QSpinBox()
            spin.setRange(low, high)
            spin.setSingleStep(step)
            spin.setValue(int(values.get(key) or low))
            spin.valueChanged.connect(lambda value, k=key: self._set(k, value))
            form.addRow(text, spin)

        for key, text in self.DIFFICULTIES:
            combo = QComboBox()
            steps = balance.DIFFICULTY_STEPS
            combo.addItems([f"{round(step * 100)}%" for step in steps])
            current = balance.clamp_difficulty(values.get(key, 1.0))
            # A hand-edited value between two steps shows as the nearest one.
            combo.setCurrentIndex(min(range(len(steps)), key=lambda i: abs(steps[i] - current)))
            combo.currentIndexChanged.connect(
                lambda index, k=key: self._set(k, balance.DIFFICULTY_STEPS[index]))
            form.addRow(text, combo)

        for key, text, options in self.CHOICES:
            combo = QComboBox()
            combo.addItems(list(options))
            current = str(values.get(key, options[0]))
            if current in options:
                combo.setCurrentIndex(options.index(current))
            combo.currentTextChanged.connect(lambda value, k=key: self._set(k, value))
            form.addRow(text, combo)
        self.add(form_widget)

        self.add(separator())
        self.add(heading("Extra scan folders"))
        for provider in ((state or {}).get("settings") or {}).get("providers", []):
            field = QLineEdit(provider.get("custom_scan_roots", ""))
            field.setPlaceholderText("comma or newline separated, * allowed")
            field.editingFinished.connect(
                lambda f=field, pid=provider["id"]: self._set_roots(pid, f.text()))
            # The count is of folders that survived, not patterns typed: an
            # extra that swallows a curated default is dropped.
            self.add(row(
                label(f"{provider['display_name']} ({provider.get('matched_folders', 0)})"),
                field,
            ))

    def _set(self, key: str, value) -> None:
        config.set_value(config.default_path(), key, str(value))
        commands.enqueue("reload_config", {})

    def _set_roots(self, provider_id: str, raw: str) -> None:
        config.set_scan_roots(config.default_path(), provider_id, raw)
        commands.enqueue("reload_config", {})
