"""Calendar usage recap presented in the existing Windows popover."""

from datetime import date
from types import SimpleNamespace

from .. import format as fmt
from ..recap import make_recap
from .panels import Panel
from .widgets import MonthlyChart, Segmented, big, button, card, column, heading, label, row, stat_line


class RecapPanel(Panel):
    def __init__(self, reader) -> None:
        super().__init__(reader)
        self.scope = "week"
        self.anchor = date.today().isoformat()

    def update(self, state: dict | None) -> None:
        self.clear()
        history = (state or {}).get("usage_history") or {}
        ledger = SimpleNamespace(tokens=history.get("tokens") or {},
                                 covered_since=history.get("covered_since"))
        recap = make_recap(ledger, self.scope, self.anchor,
                           dex=(state or {}).get("catch_log") or [])
        self.add(Segmented(tuple((key, self.t("recap_" + key))
                                 for key in ("week", "month", "year")),
                           self._scope, active=self.scope, compact=True))
        self.add(row(button("‹", lambda: self._move(recap["previous"]), recap["can_go_back"]),
                     label(recap["start"], bold=True),
                     button("›", lambda: self._move(recap["next"]), recap["can_go_forward"])))
        self.add(card(column(big(fmt.compact(recap["total"])),
                             label(fmt.grouped(recap["total"]), dim=True)), horizontal=False))
        series = [{**item, "total_tokens_compact": fmt.compact(item["total_tokens"]),
                   "cost_text": ""} for item in recap["buckets"]]
        self.add(MonthlyChart(series))
        self.add(stat_line(self.t("recap_active_days"),
                           f'{recap["active_days"]} / {recap["counted_days"]}'))
        self.add(stat_line(self.t("recap_best_day"), recap["best_day"] or "—"))
        self.add(stat_line(self.t("recap_streak"), str(recap["best_streak"])))
        previous = fmt.compact(recap["previous_total"]) if recap["previous_total"] is not None else "—"
        if recap["delta"] is not None:
            previous += f'  ({recap["delta"]:+.0%})'
        self.add(stat_line(self.t("recap_previous"), previous))
        self.add(label(self.fill("recap_partial", ledger.covered_since or "—"),
                       faint=True, size=11, wrap=True))
        if recap["graduated"]:
            self.add(heading(self.t("catch_log")))
            for entry in recap["graduated"]:
                chain = entry.get("chain") or []
                self.add(label(" → ".join(str(stage.get("name", "")) for stage in chain), wrap=True))

    def _scope(self, scope: str) -> None:
        self.scope = scope
        self.refresh(self.reader.state, force=True)

    def _move(self, anchor: str) -> None:
        self.anchor = anchor
        self.refresh(self.reader.state, force=True)
