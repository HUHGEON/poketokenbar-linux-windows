"""The pages of the popup window.

Each panel owns a layout and a single `update(state)`. Rebuilding the children
on every poll is the simplest correct thing at these sizes, with one exception:
sprites are handed a path and decide for themselves whether anything changed,
because rebuilding a QMovie restarts the animation from frame one.

Nothing here reimplements the file protocol. The panels read the same payload
`poketokenbar.state.build` produced and, where they write, call the daemon's own
`commands` and `config` modules — so unlike a front end in another language
there is no contract between the two halves to get wrong.

The layout follows the macOS popover row for row: a card per group, the day's
tokens as one large compact figure with the exact count and the cost beside it,
and every limit window the account has — including the model-scoped weekly one
that arrives only in `limits[]`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QComboBox, QGridLayout, QHBoxLayout, QLineEdit, QScrollArea, QSlider,
    QVBoxLayout, QWidget,
)

from .. import commands, config, l10n
from . import theme
from .widgets import (
    Segmented, Sprite, badge, big, button, card, chip, clear_layout, column,
    heading, icon_button, label, level_colour, meter, rarity_badge, row,
    separator, spread, stat_line, wrap_row,
)

# How many Pokedex cells fit on a page. Four columns, six rows — the grid the
# macOS popover uses at this window width.
DEX_COLUMNS = 4
DEX_PER_PAGE = 24

# Every cell is this wide inside its padding, whatever is in it. Nothing in a
# cell may set the column width, because all of it is translated: Korean names
# fit at four columns and "Seismitoad" and "Crapustule" do not, so an un-elided
# label pushed the grid past the popup and clipped the fourth column off the
# right edge entirely.
#
# The budget, measured: a 392px viewport (400 less the 8px scrollbar) less the
# panel's 28px of margins leaves 364 for four cells and three gaps. 78 is what
# the widest thing a cell can hold actually needs — a "EN ELEVAGE" badge at 77,
# and a shiny number beside the star at 76 — and 4 x (78 + 8) + 3 x 5 is 359.
DEX_CELL_WIDTH = 78

RARITIES = ("legendary", "rare", "uncommon", "common")

REPO_URL = "https://github.com/HUHGEON/poketokenbar-linux-windows"
# The macOS app this is a port of. Credited in the UI, not only in the README:
# the Pokedex, the balance and every string here came from it.
UPSTREAM_URL = "https://github.com/chattymin/PokeTokenBar"


def remaining_seconds(iso: str | None) -> float | None:
    """Seconds until an ISO instant, or None if it is not one."""
    if not iso:
        return None
    try:
        moment = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment - datetime.now(timezone.utc)).total_seconds()


def resets_in(iso: str | None, strings) -> str:
    """"2시간 36분" from an ISO instant.

    `resets_at` arrives as the raw timestamp the API returned; printed verbatim
    it is data rather than an answer to "how long have I got".
    """
    remaining = remaining_seconds(iso)
    if remaining is None:
        return ""
    if remaining <= 0:
        return strings("resetting_now")
    return duration(remaining, strings)


def duration(seconds: float, strings) -> str:
    """A coarse "2 units" duration, the way the popover writes a countdown.

    Two units at most and never a smaller one beside a larger: "6일 2시간",
    "2시간 36분", "26초". A full h:m:s breakdown of a week-long window is noise.
    """
    seconds = max(0, int(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    unit = lambda key, value: strings(key).replace("%1", str(value))
    if days:
        return f"{unit('unit_day', days)} {unit('unit_hour', hours)}" if hours \
            else unit("unit_day", days)
    if hours:
        return f"{unit('unit_hour', hours)} {unit('unit_minute', minutes)}" if minutes \
            else unit("unit_hour", hours)
    if minutes:
        return f"{unit('unit_minute', minutes)} {unit('unit_second', secs)}" if secs \
            else unit("unit_minute", minutes)
    return unit("unit_second", secs)


def ago(seconds: float | None, strings=None) -> str:
    """"방금 갱신" / "3분 전 갱신", in the daemon's language."""
    if seconds is None:
        return ""
    resolve = strings or (lambda key: key)
    if seconds < 90:
        return resolve("updated_just_now")
    return resolve("updated_minutes_ago").replace("%1", str(round(seconds / 60)))


class Panel(QWidget):
    """A scrollable column that rebuilds itself, but only when it has to."""

    def __init__(self, reader) -> None:
        super().__init__()
        self.reader = reader
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        # Never horizontal: the window has a fixed width, so a sideways bar
        # would only ever mean something is laid out wrong.
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(14, 10, 14, 12)
        self.layout_.setSpacing(8)
        self.layout_.setAlignment(Qt.AlignTop)
        # The body's minimum follows the layout's, so content taller than the
        # viewport scrolls rather than being compressed into it.
        self.layout_.setSizeConstraint(QVBoxLayout.SetMinimumSize)
        self.scroll.setWidget(self.body)
        outer.addWidget(self.scroll)
        self._fingerprint: str | None = None

    def t(self, key: str) -> str:
        return self.reader.text(key)

    def nature(self, nature: str | None) -> str:
        """A nature's name, in the language the daemon is set to.

        Printed raw, it read "brave" beside a Pokemon whose form, rarity and
        status message were all translated.
        """
        return self.t(f"nature_{nature}") if nature else ""

    def fill(self, key: str, *values) -> str:
        """A catalogue string with its %1..%n placeholders filled in."""
        text = self.t(key)
        for index, value in enumerate(values, start=1):
            text = text.replace(f"%{index}", str(value))
        return text

    def clear(self) -> None:
        clear_layout(self.layout_)

    def add(self, widget: QWidget) -> None:
        self.layout_.addWidget(widget)

    def gap(self, height: int = 4) -> None:
        self.layout_.addSpacing(height)

    def fingerprint(self, state: dict | None) -> str:
        """What this panel actually shows, as a comparable value.

        Subclasses narrow it. The default is the whole state minus the clock,
        which changes every poll and would defeat the point.
        """
        trimmed = {k: v for k, v in (state or {}).items() if k != "updated_at"}
        return json.dumps(trimmed, sort_keys=True, default=str)

    def refresh(self, state: dict | None, force: bool = False) -> None:
        """Rebuild only when something visible changed, and keep the scroll.

        The daemon writes every couple of seconds whether or not the numbers
        moved. Rebuilding on each of those threw the scroll position away, so
        the Pokedex jumped back to the top while it was being read — and any
        text being selected was destroyed under the cursor.
        """
        current = self.fingerprint(state)
        if current == self._fingerprint and not force:
            return
        self._fingerprint = current

        bar = self.scroll.verticalScrollBar()
        position = bar.value()
        self.update(state)
        # Restored after the layout has settled, or the bar has no range yet
        # and the value is clamped straight back to zero.
        QTimer.singleShot(0, lambda: bar.setValue(min(position, bar.maximum())))


class HomePanel(Panel):
    def __init__(self, reader) -> None:
        super().__init__(reader)
        # Held across rebuilds so its animation is not restarted every poll.
        self.sprite = Sprite(76)

    def update(self, state: dict | None) -> None:
        self.clear()
        companion = (state or {}).get("companion") or {}

        banner = (state or {}).get("celebration") or {}
        if banner.get("kind"):
            self.add(card(column(
                label(banner.get("title", ""), bold=True),
                label(banner.get("detail", ""), dim=True, wrap=True),
            ), horizontal=False))

        if companion:
            self._add_companion(companion)

        self.add(separator())
        self._add_today(state)
        self._add_status(state)
        self._add_limits(state)

    # --- companion ---------------------------------------------------------

    def _add_companion(self, companion: dict) -> None:
        # Home always shows what is being raised, never the pinned species:
        # pinning changes the tray icon, and hiding the companion here would
        # make its progress unreachable.
        self.sprite.set_path(companion.get("sprite_path") or None)
        self.sprite.setParent(None)
        portrait = card(self.sprite, padding=6)

        if companion.get("stage") == "egg":
            details = column(
                label(self.t("egg"), bold=True, size=16),
                meter(companion.get("egg_progress", 0), None),
                label(companion.get("label", ""), dim=True, wrap=True),
                spacing=6,
            )
        else:
            name = companion.get("name") or f"#{companion.get('species_id')}"
            title = row(
                label(f"✨ {name}" if companion.get("is_shiny") else name,
                      bold=True, size=17),
                rarity_badge(companion.get("rarity"),
                             self.t(companion.get("rarity", "common"))),
                stretch=True,
            )
            form = self.t("final_form") if companion.get("is_final_form") \
                else self.t("next_evolution")
            progress = meter(companion.get("stage_progress", 0))
            # The companion's own bar is never a limit warning, so it keeps one
            # colour instead of turning red as it fills.
            progress.setStyleSheet(
                f"QProgressBar {{ border: none; background: {theme.RAISED};"
                f" border-radius: 3px; }}"
                f"QProgressBar::chunk {{ background: {theme.ORANGE};"
                f" border-radius: 3px; }}")
            remaining_key = "graduation_remaining" if companion.get("is_final_form") \
                else "evolution_remaining"
            details = column(
                title,
                label(f"{form} · {self.nature(companion.get('nature'))}", dim=True),
                progress,
                label(self.fill(remaining_key, companion.get("remaining_text", "")),
                      dim=True),
                label(companion.get("status_message", ""), dim=True, wrap=True),
                spacing=5,
            )

        self.add(row(portrait, details, spacing=12))
        if companion.get("evo_line"):
            self.add(self._evolution_line(companion))

    def _evolution_line(self, companion: dict) -> QWidget:
        """The chain, with the reached forms lit and the current one marked."""
        stages = companion.get("evo_line") or []
        reached = [index for index, stage in enumerate(stages) if stage.get("reached")]
        current = reached[-1] if reached else 0

        line = QWidget()
        layout = QHBoxLayout(line)
        layout.setContentsMargins(6, 2, 0, 2)
        layout.setSpacing(6)
        for index, stage in enumerate(stages):
            if index:
                layout.addWidget(label("→", faint=True))
            size = 46 if index == current else 34
            sprite = Sprite(size)
            sprite.set_path(stage.get("sprite_path") or None)
            if not stage.get("reached"):
                # Forms it has not reached are dimmed rather than hidden, so the
                # line still shows where the companion is heading.
                sprite.setGraphicsEffect(_faded())
            dot = label("●", colour=theme.ACCENT, size=7) if index == current \
                else label(" ", size=7)
            dot.setAlignment(Qt.AlignCenter)
            layout.addWidget(column(sprite, dot, spacing=1))
        layout.addStretch(1)
        return line

    # --- today -------------------------------------------------------------

    def _add_today(self, state: dict | None) -> None:
        today = (state or {}).get("today") or {}
        self.add(heading(self.t("todays_tokens")))

        headline = row(
            big(today.get("tokens_compact", "0")),
            label(today.get("tokens_grouped", ""), dim=True),
            spacing=8,
        )
        headline.layout().setAlignment(Qt.AlignBottom)
        self.add(spread(headline, label(today.get("cost_text", ""), dim=True)))

        periods = (state or {}).get("periods") or {}
        parts = []
        for key, name in (("week", "this_week"), ("month", "this_month")):
            bucket = periods.get(key)
            if not bucket:
                continue
            parts += [
                label(self.t(name), faint=True, size=12),
                label(bucket.get("tokens_compact", ""), bold=True),
                label(bucket.get("cost_text", ""), dim=True, size=12),
            ]
            parts.append(label("   "))
        if parts:
            self.add(row(*parts[:-1], spacing=5, stretch=True))

        providers = (state or {}).get("providers") or {}
        for provider_id, usage in providers.items():
            self.add(spread(
                label(self._provider_name(state, provider_id), bold=True, size=15),
                row(label(usage.get("total_tokens_compact", ""), bold=True, size=15),
                    label(usage.get("cost_text", ""), dim=True)),
            ))
            self.add(label(
                self.fill(
                    "token_breakdown",
                    usage.get("input_compact", 0), usage.get("output_compact", 0),
                    usage.get("cache_creation_compact", 0),
                    usage.get("cache_read_compact", 0)),
                faint=True, size=12))

        # Only worth the rows when the day actually spanned several models.
        models = today.get("models") or []
        if len(models) > 1:
            for model_row in models[:6]:
                self.add(stat_line(model_row["model"],
                                   model_row["total_tokens_compact"]))

    def _provider_name(self, state: dict | None, provider_id: str) -> str:
        """The provider's display name, as the daemon registered it."""
        for provider in ((state or {}).get("settings") or {}).get("providers", []):
            if provider.get("id") == provider_id:
                return provider.get("display_name") or provider_id
        return provider_id

    # --- limits ------------------------------------------------------------

    def _add_status(self, state: dict | None) -> None:
        # Every row here is already a problem: the daemon drops the healthy
        # ones, and an unreachable status page is left out rather than reported
        # as an outage.
        for provider_id, status in ((state or {}).get("provider_status") or {}).items():
            self.add(stat_line(
                self._provider_name(state, provider_id), status.get("label", ""),
                colour=level_colour(status.get("severity"))))

    def _add_limits(self, state: dict | None) -> None:
        limits = (state or {}).get("limits") or {}
        rows = [("session", self.t("five_hour_session"), limits.get("session")),
                ("weekly", self.t("weekly"), limits.get("weekly"))]
        rows += [(entry.get("kind"), entry.get("name"), entry)
                 for entry in limits.get("scoped") or []]
        rows = [r for r in rows if r[2]]
        blocks = (state or {}).get("blocks") or {}
        if not rows and not blocks.get("claude_code"):
            return

        self.add(separator())
        self.add(heading(self.t("limits_official")))
        if limits.get("plan_text"):
            self.add(label(self.fill("plan_label", limits["plan_text"]),
                           faint=True, size=12))
        # Which account these belong to. Someone signed into two is otherwise
        # reading a bar for the other one.
        if limits.get("account_text"):
            self.add(label(self.fill("account_label", limits["account_text"]),
                           faint=True, size=12))

        # "Used" or "left" is a display transform only: the meter and the
        # colour stay on the utilization, so a window at 95% is still red while
        # it reads "5% left".
        remaining = ((state or {}).get("config") or {}).get(
            "limit_percent_mode") == "remaining"
        for key, name, window in rows:
            utilization = window.get("utilization", 0)
            severity = window.get("severity")
            shown = round(max(0.0, 100.0 - utilization) if remaining else utilization)
            text = self.fill("percent_remaining", f"{shown}%") if remaining \
                else f"{shown}%"
            countdown = resets_in(window.get("resets_at"), self.t)
            self.add(spread(
                label(name, bold=True, size=15),
                row(label(text, colour=level_colour(severity), bold=True),
                    label(f"· {countdown}" if countdown else "", dim=True, size=12)),
            ))
            self.add(meter(utilization / 100, severity))
            if key == "session":
                self._add_forecast(state)

        self._add_block(state, blocks)

    def _add_forecast(self, state: dict | None) -> None:
        """Whether the 5-hour window runs out before it resets.

        Two outcomes, not one: reaching the limit is a warning with a time on
        it, and not reaching it is the reassurance the popover actually shows
        most of the time. Rendering only the first left the row blank in the
        ordinary case.
        """
        forecast = ((state or {}).get("burn") or {}).get("session") or {}
        if "before_reset" not in forecast:
            return
        if forecast.get("before_reset"):
            self.add(label(
                f"⚠ {self.fill('forecast_reach', forecast.get('eta_text', ''))}",
                colour=theme.ORANGE, size=12))
        else:
            self.add(label(f"✓ {self.t('no_limit_before_reset')}",
                           faint=True, size=12))

    def _add_block(self, state: dict | None, blocks: dict) -> None:
        block = blocks.get("claude_code")
        if not block:
            return
        # A block runs five hours from its earliest entry, so once that hour is
        # past there is nothing left to count down to: the window has simply
        # gone quiet. Printing "reset" beside "resetting now" said nothing and
        # said it permanently.
        remaining = remaining_seconds(block.get("end_time"))
        countdown = (
            f"{self.t('reset')} {duration(remaining, self.t)}"
            if remaining is not None and remaining > 0 else "")
        self.add(spread(
            row(label(self.t("claude_current_block"), dim=True),
                label(block.get("total_tokens_compact", ""), bold=True)),
            label(countdown, faint=True, size=12),
        ))


class ShopPanel(Panel):
    def update(self, state: dict | None) -> None:
        self.clear()
        companion = (state or {}).get("companion") or {}
        self.add(card(column(
            label(self.t("spendable_tokens"), dim=True, size=12),
            big(companion.get("spendable_text", "0"), size=28),
            label(self.t("spendable_tokens_hint"), faint=True, size=12, wrap=True),
            spacing=3,
        ), horizontal=False, padding=12))

        for item in (state or {}).get("shop") or []:
            self.add(self._item(item))

    def _item(self, item: dict) -> QWidget:
        sprite = Sprite(34)
        sprite.set_fallback(item.get("emoji", ""))
        sprite.set_path(item.get("sprite_path") or None)

        title = row(label(item.get("label") or item["key"], bold=True), stretch=True)
        # A guaranteed-rarity egg says which rarity it guarantees; the badge is
        # the only thing separating the three eggs at a glance.
        if item.get("rarity"):
            title.layout().insertWidget(
                1, rarity_badge(item["rarity"], self.t(item["rarity"])))

        if item.get("owned"):
            # Already held: a live Buy button would offer a purchase the
            # daemon refuses.
            action = label(f"✅ {self.t('owned_now')}", colour=theme.GREEN, size=12)
        elif item.get("affordable"):
            action = button(
                self.t("buy"),
                lambda _=False, key=item["key"]: commands.enqueue("buy", {"key": key}),
            )
        else:
            # Named rather than disabled-and-silent: the reason a button is not
            # there is the one thing someone wants to know.
            action = label(self.t("insufficient_tokens"), faint=True, size=12)

        price = f'{self.t("price")} {item.get("price_text", "")}'
        footer = spread(label(price, faint=True, size=12), action)
        body = column(
            title,
            label(item.get("description", ""), dim=True, size=12, wrap=True),
            footer,
            spacing=5,
        )
        holder = card(sprite, body, padding=11)
        holder.layout().setAlignment(sprite, Qt.AlignTop)
        return holder


class BagPanel(Panel):
    def update(self, state: dict | None) -> None:
        self.clear()
        items = (state or {}).get("bag") or []
        if not items:
            self.add(label(self.t("bag_empty"), dim=True))
            return
        for item in items:
            sprite = Sprite(34)
            sprite.set_fallback(item.get("emoji", ""))
            sprite.set_path(item.get("sprite_path") or None)
            name = item.get("label") or item["key"]
            count = item.get("count", 0)
            title = row(
                label(f"{name} ×{count}" if count > 1 else name, bold=True),
                stretch=True,
            )
            if item.get("usable"):
                title.layout().addWidget(button(
                    self.t("use"),
                    lambda _=False, key=item["key"]: commands.enqueue(
                        "use", {"key": key}),
                ))
            rows = [title,
                    label(item.get("description", ""), dim=True, size=12, wrap=True)]
            if item.get("passive"):
                effect = item.get("effect") or self.t("active")
                rows.append(label(f"✅ {effect}", colour=theme.GREEN, size=12))
            holder = card(sprite, column(*rows, spacing=5), padding=11)
            holder.layout().setAlignment(sprite, Qt.AlignTop)
            self.add(holder)


class CollectionPanel(Panel):
    def __init__(self, reader) -> None:
        super().__init__(reader)
        self._showing_log = False
        self._page = 0
        self._rarity: str | None = None
        self._state: dict | None = None

    def fingerprint(self, state: dict | None) -> str:
        # The view, the page and the filter are this panel's own state; without
        # them in the key, switching tab or turning a page changes nothing the
        # payload can see and the rebuild is skipped.
        return json.dumps(
            [super().fingerprint(state), self._showing_log, self._page, self._rarity])

    def update(self, state: dict | None) -> None:
        self._state = state
        self.clear()
        self.tabs = Segmented(
            (("dex", self.t("pokedex")), ("log", self.t("catch_log"))),
            lambda value: self._show(value == "log"),
            active="log" if self._showing_log else "dex",
            compact=True,
        )
        self.add(row(self.tabs, stretch=True))
        if self._showing_log:
            self._build_log(state)
        else:
            self._build_dex(state)

    def _show(self, log: bool) -> None:
        if log == self._showing_log:
            return
        self._showing_log = log
        self._page = 0
        self.refresh(self._state, force=True)

    def _filter_row(self, counts: dict) -> QWidget:
        """The rarity chips. Clicking one narrows the list; clicking it again
        clears the filter, which is the only way back without a reset button."""
        widgets = []
        for key in RARITIES:
            count = counts.get(key, 0)
            widgets.append(chip(
                f"{self.t(key)} {count}", theme.RARITY_DOT[key],
                active=self._rarity == key or (self._rarity is None and count > 0),
                on_click=lambda k=key: self._filter(k),
            ))
        return wrap_row(*widgets, spacing=2)

    def _filter(self, rarity: str) -> None:
        self._rarity = None if self._rarity == rarity else rarity
        self._page = 0
        self.refresh(self._state, force=True)

    def _keep(self, records: list) -> list:
        if self._rarity is None:
            return records
        return [r for r in records if r.get("rarity") == self._rarity]

    def _build_dex(self, state: dict | None) -> None:
        entries = (state or {}).get("dex") or []
        if not entries:
            self.add(label(self.t("no_pokemon_yet"), dim=True))
            return
        self.add(row(
            label(self.t("pokedex"), bold=True, size=15),
            label(self.fill("species_count", len(entries)), dim=True),
            stretch=True,
        ))
        self.add(self._filter_row((state or {}).get("rarity_counts") or {}))

        shown = self._keep(entries)
        pages = max(1, (len(shown) + DEX_PER_PAGE - 1) // DEX_PER_PAGE)
        self._page = min(self._page, pages - 1)
        page = shown[self._page * DEX_PER_PAGE:(self._page + 1) * DEX_PER_PAGE]

        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setContentsMargins(0, 4, 0, 4)
        grid.setSpacing(5)
        for index, entry in enumerate(page):
            grid.addWidget(self._cell(entry), index // DEX_COLUMNS, index % DEX_COLUMNS)
        self.add(grid_widget)

        if pages > 1:
            self.add(row(
                icon_button("‹", lambda: self._turn(-1)),
                label(f"{self._page + 1} / {pages}", dim=True, size=12),
                icon_button("›", lambda: self._turn(1)),
                spacing=4,
            ))

    def _turn(self, direction: int) -> None:
        self._page = max(0, self._page + direction)
        self.refresh(self._state, force=True)

    def _cell(self, entry: dict) -> QWidget:
        sprite = Sprite(46)
        sprite.set_path(entry.get("sprite_path") or None)
        species = entry.get("species_id")
        pinned = str(species) == str(self._pinned())

        number = badge(
            f"✨{species}" if entry.get("is_shiny") else f"#{species}",
            theme.RAISED, theme.SECONDARY, size=9)
        # The star both shows and sets which species the panel follows. Pressing
        # it again clears the pin — without that there was no way back to the
        # companion short of the settings dropdown.
        star = icon_button(
            "★" if pinned else "☆",
            lambda _=False, sid=species, on=pinned: self._pin(sid, on),
            self.t("representative"), size=13)
        if pinned:
            star.setStyleSheet(star.styleSheet().replace(
                f"color: {theme.SECONDARY}", f"color: {theme.ORANGE}"))

        header = QWidget()
        header.setFixedWidth(DEX_CELL_WIDTH)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(0)
        header_layout.addWidget(number)
        header_layout.addStretch(1)
        header_layout.addWidget(star)

        parts = [header, sprite]
        # The one being raised appears in the Pokedex before it graduates, and
        # without the badge it is indistinguishable from a finished catch.
        if entry.get("is_raising"):
            raising = row(badge(self.t("raising"), theme.ACCENT, "#ffffff", size=9))
            raising.layout().setAlignment(Qt.AlignCenter)
            raising.setFixedWidth(DEX_CELL_WIDTH)
            parts.append(raising)
        full_name = entry.get("name") or f"#{species}"
        name = label(full_name, size=11)
        name.setAlignment(Qt.AlignCenter)
        name.setFixedWidth(DEX_CELL_WIDTH)
        name.setText(name.fontMetrics().elidedText(
            full_name, Qt.ElideRight, DEX_CELL_WIDTH))
        if name.text() != full_name:
            name.setToolTip(full_name)
        parts.append(name)

        return card(column(*parts, spacing=3), horizontal=False, padding=4)

    def _pinned(self) -> str:
        return str(((self._state or {}).get("panel") or {}).get("representative_id") or "")

    def _pin(self, species_id, currently_pinned: bool) -> None:
        """Pin this species to the panel, or release it back to the companion.

        The daemon refuses a species the save does not own, so this cannot pin
        a ghost; clearing is an empty id, which it reads as "follow again".
        """
        commands.enqueue(
            "represent", {"species_id": "" if currently_pinned else str(species_id)})

    def _build_log(self, state: dict | None) -> None:
        log = (state or {}).get("catch_log") or []
        if not log:
            self.add(label(self.t("no_pokemon_yet"), dim=True))
            return
        self.add(row(
            label(self.t("catch_log"), bold=True, size=15),
            label(self.fill("catches_total", len(log)), dim=True),
            stretch=True,
        ))
        self.add(self._filter_row((state or {}).get("catch_counts") or {}))

        for record in self._keep(log)[:60]:
            self.add(self._record(record))

    def _record(self, record: dict) -> QWidget:
        rarity = record.get("rarity", "common")
        header = [rarity_badge(rarity, self.t(rarity))]
        if record.get("raising"):
            header.append(badge(self.t("raising"), theme.ACCENT, "#ffffff", size=9))
        top = spread(row(*header, spacing=4),
                     label(self.nature(record.get("nature")), faint=True, size=12))

        chain = QWidget()
        chain_layout = QHBoxLayout(chain)
        chain_layout.setContentsMargins(0, 2, 0, 0)
        chain_layout.setSpacing(8)
        stages = record.get("chain") or []
        for index, stage in enumerate(stages):
            if index:
                chain_layout.addWidget(label("→", faint=True))
            sprite = Sprite(48)
            sprite.set_path(stage.get("sprite_path") or None)
            caption = label(stage.get("name") or f"#{stage.get('species_id', '')}",
                            dim=True, size=11)
            caption.setAlignment(Qt.AlignCenter)
            chain_layout.addWidget(column(sprite, caption, spacing=2))
        chain_layout.addStretch(1)

        parts = [top, chain]
        if record.get("raised_text"):
            parts.append(label(record["raised_text"], faint=True, size=11))
        return card(column(*parts, spacing=4), horizontal=False, padding=11)


class SettingsPanel(Panel):
    """Every setting the daemon has, plus the per-provider scan folders.

    Written through `poketokenbar.config`, the daemon's own module, so the two
    cannot disagree about defaults or about what a key is called.

    The three tables below are the source of truth for what is editable, and a
    test compares them against `config.DEFAULTS` in both directions: a setting
    missing here has no control at all, and a key here that the daemon has no
    default for is a control that changes nothing. The layout picks rows out of
    them by key, so grouping them into cards cannot drop one.
    """

    # (key, label, subtitle) — every label is a catalogue key, never a literal:
    # a literal is a label that never translates, which is exactly how the
    # settings page ended up entirely in English.
    TOGGLES = (
        ("show_tokens_in_menu", "setting_tokens_in_panel"),
        ("show_cost_in_menu", "setting_cost_in_panel"),
        ("show_limit_in_menu", "setting_limits_in_panel"),
        ("limit_notifications", "setting_limit_notifications"),
        ("companion_notifications", "setting_companion_notifications"),
        ("status_checks_enabled", "setting_status_checks"),
        ("floating_pet_enabled", "setting_desktop_pet"),
        ("floating_pet_bubble_alerts", "setting_pet_bubbles"),
        ("launch_at_login", "setting_launch_at_login"),
    )
    SUBTITLES = {
        "status_checks_enabled": "status_checks_hint",
        "floating_pet_enabled": "floating_pet_hint",
        "animation_quality": "animation_hint",
    }
    # Sliders and their ranges. Outside these the daemon misbehaves quietly —
    # a 0px pet is invisible — and a control cannot express a value outside its
    # range.
    SPINS = (
        ("floating_pet_size", "size", 48, 192, 8, "%1px"),
        ("warn_threshold", "warn_at", 50, 95, 5, "%1%"),
        ("crit_threshold", "crit_at", 60, 99, 1, "%1%"),
    )
    CHOICES = (
        # Language names stay in their own language: someone who has landed on
        # the wrong one needs to recognise theirs, not read it translated.
        ("language", "setting_language", tuple(l10n.LANGUAGES), None),
        ("refresh_interval", "setting_refresh_interval",
         (60, 120, 300, 600, 900), None),
        ("animation_quality", "setting_animation",
         ("saver", "balanced", "smooth"),
         ("quality_saver", "quality_balanced", "quality_smooth")),
        ("limit_percent_mode", "setting_limit_percent",
         ("used", "remaining"), ("usage", "remaining")),
        ("pin_on_graduation", "setting_pin_on_graduation",
         ("keep", "release"), ("pin_keep", "pin_release")),
        ("limit_display_mode", "setting_limit_display",
         ("both", "session", "weekly"),
         ("limits_both", "five_hour_session", "weekly")),
    )
    # Which of the CHOICES are drawn as a two-or-three-way switch rather than a
    # dropdown, matching the settings sheet.
    SEGMENTED = ("limit_percent_mode", "pin_on_graduation")

    def update(self, state: dict | None) -> None:
        self.clear()
        values = (state or {}).get("config") or {}

        self.add(heading(self.t("general")))
        self.add(self._group([
            self._choice_row(values, "language"),
            self._representative_row(state, values),
            self._choice_row(values, "refresh_interval"),
            self._choice_row(values, "animation_quality"),
            self._choice_row(values, "limit_percent_mode"),
            self._choice_row(values, "pin_on_graduation"),
            self._choice_row(values, "limit_display_mode"),
            self._toggle_row(values, "launch_at_login"),
        ]))

        self.add(heading(self.t("show_in_panel")))
        self.add(self._group([
            self._toggle_row(values, key) for key in
            ("show_tokens_in_menu", "show_cost_in_menu", "show_limit_in_menu")
        ]))
        self.add(label(self.t("panel_all_off_hint"), faint=True, size=11, wrap=True))

        self.add(heading(self.t("floating_pet")))
        self.add(self._group([
            self._toggle_row(values, "floating_pet_enabled"),
            self._slider_row(values, "floating_pet_size"),
            self._toggle_row(values, "floating_pet_bubble_alerts"),
        ]))

        self.add(heading(self.t("notifications")))
        self.add(self._group([
            self._toggle_row(values, "limit_notifications"),
            self._slider_row(values, "warn_threshold"),
            self._slider_row(values, "crit_threshold"),
            self._toggle_row(values, "companion_notifications"),
            self._toggle_row(values, "status_checks_enabled"),
        ]))

        providers = ((state or {}).get("settings") or {}).get("providers", [])
        if providers:
            self.add(heading(self.t("setting_scan_folders")))
            self.add(self._group([self._roots_row(p) for p in providers]))

        self.add(self._update_row(state))
        self.add(self._about())

    def _update_row(self, state: dict | None) -> QWidget:
        """Whether a newer commit is published, and a button to take it.

        Reinstalling meant finding the repo again and running a script, which
        is enough friction that a fix nobody installs may as well not exist.
        """
        update = (state or {}).get("update") or {}
        if not update.get("supported"):
            return label(self.t("update_unsupported"), faint=True, size=11, wrap=True)

        if update.get("available"):
            control = button(
                self.t("update_now"),
                lambda _=False: commands.enqueue("update", {}),
            )
            title = self.t("update_available")
            subtitle = f"{update.get('installed_short', '')} → {update['available_short']}"
        else:
            # Restarting is the tray's own doing: the daemon has already
            # replaced the source and re-executed itself, but this process is
            # still running the code it started with.
            control = button(self.t("restart"), lambda _=False: _restart_tray())
            title = self.fill("update_current", update.get("installed_short", "?"))
            subtitle = update.get("error", "")

        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)
        layout.addWidget(column(
            label(title),
            *([label(subtitle, faint=True, size=11)] if subtitle else []),
            spacing=2))
        layout.addStretch(1)
        layout.addWidget(control)
        return card(holder, horizontal=False, padding=0, spacing=0)

    def _about(self) -> QWidget:
        """Version and where to go from here — the sheet's footer.

        The version matters more here than in most apps: this is a port, and
        the first thing to establish about a bug report is which of the three
        front ends it came from.
        """
        from .. import __version__

        links = label(
            f'v{__version__} · <a href="{REPO_URL}" style="color:{theme.SECONDARY}">'
            f'GitHub</a> · <a href="{UPSTREAM_URL}" '
            f'style="color:{theme.SECONDARY}">PokeTokenBar</a>',
            faint=True, size=11)
        links.setOpenExternalLinks(True)
        links.setAlignment(Qt.AlignCenter)
        return links

    # --- row shapes --------------------------------------------------------

    def _group(self, rows: list[QWidget]) -> QWidget:
        """One card, its rows separated by hairlines — the settings-sheet look."""
        stack = []
        for index, item in enumerate(rows):
            if index:
                stack.append(separator())
            stack.append(item)
        return card(*stack, horizontal=False, padding=0, spacing=0)

    def _shell(self, key: str, title: str, control: QWidget) -> QWidget:
        subtitle = self.SUBTITLES.get(key)
        left = column(label(title),
                      *([label(self.t(subtitle), faint=True, size=11, wrap=True)]
                        if subtitle else []),
                      spacing=2)
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(10)
        layout.addWidget(left)
        layout.addStretch(1)
        layout.addWidget(control)
        return holder

    def _toggle_row(self, values, key: str) -> QWidget:
        label_key = dict(self.TOGGLES)[key]
        switch = _Switch(bool(values.get(key)))
        switch.toggled.connect(lambda checked, k=key: self._set(k, checked))
        return self._shell(key, self.t(label_key), switch)

    def _choice_row(self, values, key: str) -> QWidget:
        label_key, options, option_keys = next(
            (l, o, s) for k, l, o, s in self.CHOICES if k == key)
        shown = [
            self.t(option_keys[index]) if option_keys else self._option_text(key, option)
            for index, option in enumerate(options)
        ]
        current = values.get(key, options[0])

        if key in self.SEGMENTED:
            control = Segmented(
                tuple(zip(options, shown)),
                lambda value, k=key: self._set(k, value),
                active=current, compact=True,
            )
            return self._shell(key, self.t(label_key), control)

        combo = _combo()
        for index, option in enumerate(options):
            # The value stored is the option; only what is shown is translated,
            # so a language change cannot rewrite the setting.
            combo.addItem(shown[index], option)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda i, k=key, c=combo: self._set(k, c.itemData(i)))
        return self._shell(key, self.t(label_key), combo)

    def _option_text(self, key: str, option) -> str:
        """How an untranslated option is written.

        The refresh interval is stored in seconds but read in minutes, so the
        raw value would offer "120" where the sheet says "2분".
        """
        if key == "refresh_interval":
            return self.fill("unit_minute", int(option) // 60)
        if key == "language":
            # In its own language: someone who has landed on the wrong one has
            # to recognise theirs, and "ko" in a list of two-letter codes is
            # not something to recognise — which is what it used to show.
            return l10n.LANGUAGE_NAMES.get(option, option)
        return str(option)

    def _representative_row(self, state, values) -> QWidget:
        """Which species the tray icon shows.

        The Pokedex can pin one by clicking it, but nothing there could unpin —
        this is where "follow the current Pokemon" lives. It is stored in the
        save rather than in config, so it goes through the daemon's command
        spool like every other save change.
        """
        combo = _combo()
        combo.addItem(self.t("follow_current"), "")
        for entry in (state or {}).get("dex") or []:
            species = str(entry.get("species_id"))
            combo.addItem(entry.get("name") or f"#{species}", species)
        current = str(((state or {}).get("panel") or {}).get("representative_id") or "")
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda i, c=combo: commands.enqueue(
                "represent", {"species_id": c.itemData(i) or ""}))
        return self._shell("representative", self.t("representative"), combo)

    def _slider_row(self, values, key: str) -> QWidget:
        label_key, low, high, step, template = next(
            (l, lo, hi, st, tp) for k, l, lo, hi, st, tp in self.SPINS if k == key)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider.setSingleStep(step)
        slider.setPageStep(step)
        slider.setFixedWidth(140)
        slider.setValue(max(low, min(high, int(values.get(key) or low))))
        readout = label(template.replace("%1", str(slider.value())), dim=True, size=12)
        readout.setFixedWidth(42)
        readout.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        slider.valueChanged.connect(
            lambda value: readout.setText(template.replace("%1", str(value))))
        # Written on release, not on every pixel of the drag: each write goes
        # through config.json and asks the daemon to reload it.
        slider.sliderReleased.connect(lambda k=key, sl=slider: self._set(k, sl.value()))
        slider.setStyleSheet(_SLIDER_STYLE)
        return self._shell(key, self.t(label_key), row(slider, readout, spacing=8))

    def _roots_row(self, provider: dict) -> QWidget:
        field = QLineEdit(provider.get("custom_scan_roots", ""))
        field.setPlaceholderText(self.t("scan_folders_hint"))
        field.setFixedWidth(170)
        field.setStyleSheet(
            f"QLineEdit {{ background: {theme.RAISED}; color: {theme.TEXT};"
            f" border: none; border-radius: 6px; padding: 4px 8px;"
            f" font-size: 12px; }}")
        field.editingFinished.connect(
            lambda f=field, pid=provider["id"]: self._set_roots(pid, f.text()))
        # The count is of folders that survived, not patterns typed: an extra
        # that swallows a curated default is dropped.
        return self._shell(
            "scan_roots",
            f"{provider['display_name']} ({provider.get('matched_folders', 0)})", field)

    def _set(self, key: str, value) -> None:
        config.set_value(config.default_path(), key, str(value))
        commands.enqueue("reload_config", {})

    def _set_roots(self, provider_id: str, raw: str) -> None:
        config.set_scan_roots(config.default_path(), provider_id, raw)
        commands.enqueue("reload_config", {})


# --- small controls --------------------------------------------------------


def _restart_tray() -> None:
    """Re-exec this process so it runs the source the daemon just installed."""
    import os
    import sys

    os.execv(sys.executable, [sys.executable, "-m", "poketokenbar.ui.app"])


def _faded():
    """A 40% opacity effect for an unreached evolution.

    A stylesheet `opacity` does nothing on a QWidget — it is not a Qt style
    property — which is why the unreached forms used to render at full
    strength.
    """
    from PySide6.QtWidgets import QGraphicsOpacityEffect

    effect = QGraphicsOpacityEffect()
    effect.setOpacity(0.35)
    return effect


def _combo() -> QComboBox:
    combo = QComboBox()
    combo.setCursor(Qt.PointingHandCursor)
    combo.setStyleSheet(
        f"QComboBox {{ background: {theme.RAISED}; color: {theme.TEXT};"
        f" border: none; border-radius: 7px; padding: 4px 10px; font-size: 12px; }}"
        f"QComboBox::drop-down {{ border: none; width: 16px; }}"
        f"QComboBox QAbstractItemView {{ background: {theme.CARD};"
        f" color: {theme.TEXT}; selection-background-color: {theme.ACCENT};"
        f" border: 1px solid {theme.DIVIDER}; }}")
    return combo


_SLIDER_STYLE = (
    f"QSlider::groove:horizontal {{ height: 4px; background: {theme.RAISED};"
    f" border-radius: 2px; }}"
    f"QSlider::sub-page:horizontal {{ background: {theme.ACCENT};"
    f" border-radius: 2px; }}"
    f"QSlider::handle:horizontal {{ background: #f2f2f7; width: 18px;"
    f" height: 18px; margin: -7px 0; border-radius: 9px; }}"
)


class _Switch(QWidget):
    """An iOS-style toggle.

    A QCheckBox draws a tick box, which is the one control in this window that
    would have looked like a different application. This is a plain widget with
    a painted pill, so it matches the sheet it sits in and still reports
    `toggled` the way a checkbox does.
    """

    toggled = Signal(bool)

    def __init__(self, checked: bool = False) -> None:
        super().__init__()
        self._checked = checked
        self.setFixedSize(40, 24)
        self.setCursor(Qt.PointingHandCursor)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, value: bool) -> None:
        if value != self._checked:
            self._checked = value
            self.update()

    def mousePressEvent(self, event) -> None:
        self._checked = not self._checked
        self.update()
        self.toggled.emit(self._checked)
        event.accept()

    def paintEvent(self, event) -> None:
        from PySide6.QtGui import QColor, QPainter

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT if self._checked else theme.RAISED))
        painter.drawRoundedRect(self.rect(), 12, 12)
        painter.setBrush(QColor("#ffffff"))
        x = self.width() - 21 if self._checked else 3
        painter.drawEllipse(x, 3, 18, 18)
        painter.end()
