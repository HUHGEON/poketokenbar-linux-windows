"""Local usage history and calendar recaps, matching upstream UsageRecap."""

from __future__ import annotations

import calendar
import json
from datetime import date, datetime, timedelta
from pathlib import Path


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


class UsageLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.tokens: dict[str, int] = {}
        self.covered_since: str | None = None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                values = raw.get("tokens", {})
                if isinstance(values, dict):
                    self.tokens = {k: v for k, v in values.items()
                                   if _day(k) and type(v) is int and v > 0}
                if _day(raw.get("covered_since")):
                    self.covered_since = raw["covered_since"]
        except (OSError, ValueError):
            pass

    def merge(self, series: list[dict]) -> None:
        days = []
        for row in series:
            key, value = row.get("date"), row.get("total_tokens", 0)
            if not _day(key) or type(value) is not int or value < 0:
                continue
            days.append(key)
            if value > 0:
                self.tokens[key] = max(value, self.tokens.get(key, 0))
        if not days:
            return
        self.covered_since = min(days + ([self.covered_since] if self.covered_since else []))
        # Upstream retains three years of history. Historical recaps do not
        # require reopening a person's original logs after every refresh.
        cutoff = (date.today() - timedelta(days=366 * 3)).isoformat()
        self.tokens = {k: v for k, v in self.tokens.items() if k >= cutoff}
        self.covered_since = max(cutoff, self.covered_since)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps({"tokens": self.tokens,
                                    "covered_since": self.covered_since}), encoding="utf-8")
        temp.replace(self.path)


def _period(scope: str, anchor: date) -> tuple[date, date]:
    if scope == "week":
        start = anchor - timedelta(days=(anchor.weekday() - calendar.firstweekday()) % 7)
        return start, start + timedelta(days=7)
    if scope == "month":
        start = anchor.replace(day=1)
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return start, end
    if scope == "year":
        return anchor.replace(month=1, day=1), date(anchor.year + 1, 1, 1)
    raise ValueError("unknown recap period")


def make_recap(ledger: UsageLedger, scope: str, anchor: str | None = None,
               *, dex: list[dict] | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    selected = min(_day(anchor) or today, today)
    start, end = _period(scope, selected)
    previous_start, previous_end = _period(scope, start - timedelta(days=1))

    def days(a, b):
        return [a + timedelta(days=n) for n in range((b - a).days)]

    def known(day):
        return day <= today and (ledger.tokens.get(day.isoformat(), 0) > 0 or
                                bool(ledger.covered_since and day.isoformat() >= ledger.covered_since))

    elapsed = days(start, min(end, today + timedelta(days=1)))
    active = [d for d in elapsed if ledger.tokens.get(d.isoformat(), 0) > 0]
    streak = best_streak = 0
    for day in elapsed:
        streak = streak + 1 if day in active else 0
        best_streak = max(best_streak, streak)
    total = sum(ledger.tokens.get(d.isoformat(), 0) for d in elapsed)
    compared = days(previous_start, previous_end)
    in_progress = start <= today < end
    if in_progress:
        compared = compared[:len(elapsed)]
    previous_total = (sum(ledger.tokens.get(d.isoformat(), 0) for d in compared)
                      if ledger.covered_since and compared and
                      compared[0].isoformat() >= ledger.covered_since else None)
    buckets = []
    starts = [date(start.year, m, 1) for m in range(1, 13)] if scope == "year" else days(start, end)
    for day in starts:
        bucket_end = _period("month", day)[1] if scope == "year" else day + timedelta(days=1)
        bucket_days = days(day, bucket_end)
        buckets.append({"date": day.isoformat(),
                        "total_tokens": sum(ledger.tokens.get(d.isoformat(), 0)
                                            for d in bucket_days if d <= today),
                        "has_data": any(known(d) for d in bucket_days),
                        "is_current": day <= today < bucket_end})
    graduated = []
    for entry in dex or []:
        caught = entry.get("caught_at")
        try:
            moment = (datetime.fromtimestamp(caught) if isinstance(caught, (int, float))
                      else datetime.fromisoformat(str(caught).replace("Z", "+00:00")))
            caught_day = moment.astimezone().date() if moment.tzinfo else moment.date()
        except (ValueError, TypeError, OverflowError, OSError):
            continue
        if (not entry.get("raising") and not entry.get("is_released", entry.get("released", False))
                and start <= caught_day < end):
            graduated.append(entry)
    best_day = max(active, key=lambda d: ledger.tokens[d.isoformat()], default=None)
    return {"scope": scope, "start": start.isoformat(), "end": end.isoformat(),
            "previous": previous_start.isoformat(), "next": end.isoformat(),
            "total": total, "previous_total": previous_total,
            "delta": (total - previous_total) / previous_total if previous_total else None,
            "in_progress": in_progress, "buckets": buckets,
            "best_day": best_day.isoformat() if best_day else None,
            "active_days": len(active), "counted_days": sum(known(d) for d in elapsed),
            "best_streak": best_streak, "graduated": graduated,
            "can_go_back": bool(ledger.covered_since and
                                 (start - timedelta(days=1)).isoformat() >= ledger.covered_since),
            "can_go_forward": end <= today}
