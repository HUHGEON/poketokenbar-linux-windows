"""state.json — the daemon's only output to the UI.

Written atomically (temp + rename) so the plasmoid, which polls, can never
read a torn file. Always parses: a failing poll produces errors[], never a
partial document.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import format as fmt
from . import platform_paths
from . import l10n, limits, pace as pace_module
from .models import CostCoverage, DailyUsage

SCHEMA_VERSION = 1


def default_path() -> Path:
    return platform_paths.state_base() / "poketokenbar" / "state.json"


def _limits_payload(
    status,
    freshness: dict | None = None,
    language: str = "en",
    warn: float = 80,
    crit: float = 95,
    accounts=None,
    strings: dict | None = None,
) -> dict:
    """Serialise a limits.LimitStatus, or an empty dict when unavailable.

    `freshness` says whether the numbers are the last good ones while fetching
    is failing, and when they were fetched.
    """
    if status is None:
        return {}
    freshness = freshness or {}

    def window(w, kind):
        if w is None:
            return None
        # How far through the window we are, and how far ahead of that the
        # usage is. 71% means nothing on its own: early in a window it is fast,
        # late in one it is slow (upstream 68deb09, 2eec9af).
        elapsed = pace_module.fraction(w.resets_at, pace_module.span_for(kind))
        tier = pace_module.gauge(w.utilization, elapsed, warn, crit)
        delta = (
            pace_module.rounded_delta(w.utilization, elapsed)
            if elapsed is not None and elapsed >= pace_module.MINIMUM_PACE
            else None
        )
        return {
            "utilization": w.utilization,
            "resets_at": w.resets_at,
            "severity": w.severity,
            # None while the window has barely started, or when its length is
            # unknown: no mark at all beats one in the wrong place.
            "pace": elapsed,
            "tier": tier,
            "tier_text": l10n.t(f"pace_{tier}", language),
            # Whole points: the tier is judged on a rounded delta, so a hint
            # reading 80.4% beside a 10-point delta would not add up.
            "pace_hint": (
                l10n.fill("pace_hint", language, f"{round(elapsed * 100)}%")
                if elapsed is not None
                else ""
            ),
            "pace_delta_text": (
                l10n.fill("pace_delta_over" if delta > 0 else "pace_delta_under",
                          language, str(abs(delta)))
                if delta
                else ""
            ),
        }

    def rows():
        """One row per logged-in Claude account, the default one first.

        With a single login this is the same numbers the block already carries,
        and the popup shows no tabs (upstream e5b4800).
        """
        out = []
        for account_id, account_status, source in accounts or []:
            who = (account_status.account or {}) if account_status is not None else {}
            out.append({
                "id": account_id,
                "label": who.get("email") or who.get("display_name") or account_id,
                "is_default": account_id == (accounts[0][0] if accounts else ""),
                "session": window(
                    account_status.session if account_status is not None else None, "session"),
                "weekly": window(
                    account_status.weekly if account_status is not None else None, "weekly"),
                "plan": account_status.subscription_type if account_status is not None else None,
                # Each account fails on its own: an expired login must not make
                # another account's numbers look wrong.
                "error": getattr(source.source, "last_error", ""),
                "stale": bool(getattr(source.source, "stale", False)),
            })
        return out

    return {
        "session": window(status.session, "session"),
        "weekly": window(status.weekly, "weekly"),
        # Only worth showing when there is more than one; the block above is
        # the default account either way.
        "accounts": rows() if accounts and len(accounts) > 1 else [],
        # Model-scoped weekly windows ("Weekly Fable"). They arrive only in
        # limits[], never in the legacy fields, so a front end reading
        # session/weekly alone is a row short of what the account actually has.
        "scoped": [
            {
                "kind": entry.kind,
                "model": entry.model,
                # Resolved here, not in the front end: the name depends on the
                # catalogue and every front end would otherwise repeat the rule.
                "name": _scoped_name(entry, strings or {}),
                **(window(entry.window, entry.kind) or {}),
            }
            for entry in (status.scoped or [])
            if window(entry.window, entry.kind) is not None
        ],
        "plan": status.subscription_type,
        "plan_text": limits.plan_display(status),
        "account": status.account or {},
        "stale": bool(freshness.get("stale")),
        "updated_at": freshness.get("updated_at"),
        "account_text": limits.account_display(status),
    }


def _scoped_name(entry, strings: dict) -> str:
    """The row label for a limits[] entry outside the legacy fields.

    Ported from Localization.claudeLimitEntry: a scoped weekly with a model is
    "Weekly <model>", and one without falls back to a label that says it is
    scoped — plain "Weekly" would collide with the legacy weekly row above it.
    """
    weekly_scoped = strings.get("weekly_scoped", "Weekly (scoped)")
    if entry.kind == "weekly_scoped":
        if not entry.model:
            return weekly_scoped
        return strings.get("weekly_model", "Weekly %1").replace("%1", entry.model)
    base = (entry.kind or "limit").replace("_", " ")
    return f"{base} {entry.model}" if entry.model else base




def _recap_payload(recap_view, language: str) -> dict:
    """One recap period, every label already in the UI language.

    `recap_view` is what daemon.recap_view() built: the computed recap plus the
    individuals that graduated inside the period. None when the page is closed.
    """
    if not recap_view:
        return {}
    found = recap_view["recap"]
    period = found.period
    peak = max((bucket.tokens for bucket in found.buckets), default=0)
    delta = found.delta
    return {
        "scope": period.scope,
        "offset": recap_view.get("offset", 0),
        "title": l10n.period_title(
            period.scope, period.start.isoformat(),
            (period.end - timedelta(days=1)).isoformat(), language),
        "total_tokens": found.total,
        "total_text": fmt.compact(found.total),
        "total_grouped": fmt.grouped(found.total),
        "buckets": [
            {
                "key": bucket.key,
                "label": (
                    l10n.month_title(bucket.key, language) if period.scope == "year"
                    else str(int(bucket.key[-2:]))
                ),
                "tokens": bucket.tokens,
                "tokens_text": fmt.compact(bucket.tokens),
                "fraction": round(bucket.tokens / peak, 4) if peak > 0 else 0.0,
                "is_current": bucket.is_current,
                # A day nobody was recording is drawn as unknown, not as zero.
                "has_data": bucket.has_data,
            }
            for bucket in found.buckets
        ],
        "best_day_text": (
            l10n.day_stamp(found.best_day[0], language) if found.best_day else ""
        ),
        "best_day_tokens_text": fmt.compact(found.best_day[1]) if found.best_day else "",
        "active_days": found.active_days,
        "counted_days": found.counted_days,
        "best_streak": found.best_streak,
        # Only when the period before is fully covered: otherwise days nobody
        # recorded would count as zero and invent a jump.
        "delta_text": f"{delta * 100:+.0f}%" if delta is not None else "",
        "delta_up": bool(delta is not None and delta > 0),
        "is_in_progress": found.is_in_progress,
        "can_go_back": found.can_go_back,
        # The future holds nothing to report.
        "can_go_forward": recap_view.get("offset", 0) < 0,
        "graduated": recap_view.get("graduated", []),
    }


def _cost_texts(amount: float, coverage, language: str, tokens: int) -> tuple[str, str]:
    """(popup text, panel text) for a cost total. Ports UsageCost.text.

    Plain dollars whenever anything was priced, as upstream a8b3ba8 settled
    on; "Unavailable" (the panel's "$—") when usage exists but none of it
    could be priced; nothing at all when there was no usage to price.
    """
    if coverage is None or not (coverage.has_known or coverage.unknown):
        # A total built without coverage is read as upstream decodes one: no
        # tokens is nothing, an amount is an estimate, otherwise unpriced.
        if tokens <= 0:
            return "", ""
        coverage = CostCoverage(estimated=amount > 0, unknown=amount <= 0)
    if coverage.only_unknown:
        return l10n.t("cost_unavailable", language), "$\u2014"
    return fmt.cost(amount), fmt.cost_compact(amount)


def _combined_coverage(coverages) -> CostCoverage:
    combined = CostCoverage()
    for coverage in coverages:
        if coverage is not None:
            combined.merge(coverage)
    return combined


def _period_rows(periods: dict | None, language: str = "en") -> dict:
    """Week and month with their text prepared, like every other number here.

    The daemon sums these as raw ints; formatting them in the UI is what led to
    QML rendering 8.55336e+07 in the first place.
    """
    out = {}
    for key, bucket in (periods or {}).items():
        if key == "month_daily":
            continue  # a series, not a bucket: see _month_trend
        tokens = bucket.get("tokens", 0)
        cost = bucket.get("cost", 0.0)
        out[key] = {
            "tokens": tokens,
            "cost": cost,
            "tokens_text": fmt.grouped(tokens),
            "tokens_compact": fmt.compact(tokens),
            "cost_text": _cost_texts(cost, bucket.get("coverage"), language, tokens)[0],
        }
    return out


def _month_trend(periods: dict | None, language: str, today: str) -> dict:
    """This month's day-by-day bars, ready to draw. Ports MonthDailyTrend.

    Heights are fractions of the peak day; a day with usage never draws
    thinner than the empty-day baseline the extension gives every bar. The
    axis labels the 1st, every 7th day and today, and drops a regular label
    within two days of today so two numbers never run together.
    """
    series = (periods or {}).get("month_daily") or {}
    if not series:
        return {}
    days = sorted(series)
    peak = max(series[day]["tokens"] for day in days)
    if peak <= 0:
        return {}
    today_number = int(today[-2:]) if today[:7] == days[0][:7] else None
    out = []
    for day in days:
        row = series[day]
        number = int(day[-2:])
        is_today = day == today
        regular = number == 1 or number % 7 == 0
        near_today = today_number is not None and abs(number - today_number) < 3
        tokens = row["tokens"]
        cost_text = _cost_texts(row["cost"], row.get("coverage"), language, tokens)[0]
        stamp = l10n.day_stamp(day, language)
        out.append({
            "date": day,
            "tokens": tokens,
            "fraction": round(min(1.0, tokens / peak), 4),
            "is_today": is_today,
            "is_empty": tokens == 0,
            "is_weekend": datetime.strptime(day, "%Y-%m-%d").weekday() >= 5,
            "axis_label": str(number) if is_today or (regular and not near_today) else "",
            "readout": " ".join(part for part in (stamp, fmt.compact(tokens), cost_text) if part),
        })
    return {"days": out, "peak_text": fmt.compact(peak)}


def _combined_models(daily_by_provider: dict) -> dict[str, int]:
    combined: dict[str, int] = {}
    for daily in daily_by_provider.values():
        for name, tokens in daily.models.items():
            combined[name] = combined.get(name, 0) + tokens
    return combined


def _model_rows(models: dict[str, int]) -> list[dict]:
    """Biggest first, so the popover reads top-down without sorting again.

    Ties break on the model name to keep the order stable between polls —
    otherwise two equal models would swap places on every refresh.
    """
    return [
        {
            "model": name,
            "total_tokens": tokens,
            "total_tokens_text": fmt.grouped(tokens),
            "total_tokens_compact": fmt.compact(tokens),
        }
        for name, tokens in sorted(models.items(), key=lambda kv: (-kv[1], kv[0]))
        if tokens > 0
    ]


def _transfer_payload(described: dict | None) -> dict:
    """The export file the popup would import, described before it is used.

    Importing replaces a Pokédex, so the popup has to be able to say *which*
    save it is about to replace it with — when it was taken, on what machine,
    and how much progress is in it. Formatted here with everything else the UI
    renders rather than in JavaScript.
    """
    if not described:
        return {}
    exported_at = described.get("exported_at")
    used = described.get("used_since_install")
    current_used = described.get("current_used_since_install")
    taken_at = described.get("undo_taken_at")
    undo_used = described.get("undo_used_since_install")
    return {
        "path": described.get("path", ""),
        "exists": bool(described.get("exists")),
        "error": described.get("error") or "",
        "exported_at": exported_at,
        "exported_text": datetime.fromtimestamp(exported_at).strftime("%Y-%m-%d %H:%M")
        if exported_at
        else "",
        "device": described.get("device") or "",
        "dex_count": described.get("dex_count"),
        "used_since_install": used,
        "used_text": fmt.compact(used) if used is not None else "",
        "items": described.get("items"),
        # The save that would be replaced, so the prompt shows both sides
        # rather than asking someone to remember where they were.
        "current_dex_count": described.get("current_dex_count"),
        "current_used_since_install": current_used,
        "current_used_text": fmt.compact(current_used) if current_used is not None else "",
        # The case worth a warning: importing a stale export as if it were a
        # newer one is how a day of raising disappears.
        "goes_backwards": used is not None and current_used is not None and used < current_used,
        # The undo, described the same way: it is the same overwrite, and the
        # backup it restores is not always the one someone has in mind.
        "can_undo": bool(described.get("can_undo")),
        "undo_taken_text": datetime.fromtimestamp(taken_at).strftime("%Y-%m-%d %H:%M")
        if taken_at
        else "",
        "undo_dex_count": described.get("undo_dex_count"),
        "undo_used_text": fmt.compact(undo_used) if undo_used is not None else "",
        "undo_goes_backwards": undo_used is not None
        and current_used is not None
        and undo_used < current_used,
        # Local restore points, newest first, already described by the store.
        "snapshots": described.get("snapshots") or [],
    }


def build(
    daily_by_provider: dict[str, DailyUsage],
    config_values: dict,
    errors: list[str],
    scanning: bool = False,
    limit_status=None,
    limit_accounts=None,
    limits_freshness: dict | None = None,
    companion_payload: dict | None = None,
    shop_payload: list | None = None,
    bag_payload: list | None = None,
    dex_payload: list | None = None,
    catch_log: list | None = None,
    rarity_counts: dict | None = None,
    catch_counts: dict | None = None,
    periods: dict | None = None,
    burn: dict | None = None,
    provider_status: dict | None = None,
    blocks: dict | None = None,
    celebration: dict | None = None,
    settings: dict | None = None,
    update: dict | None = None,
    transfer: dict | None = None,
    recap: dict | None = None,
    detail: dict | None = None,
    provider_names: dict | None = None,
) -> dict:
    total_tokens = sum(d.total_tokens for d in daily_by_provider.values())
    total_cost = sum(d.total_cost for d in daily_by_provider.values())
    limit_mode = config_values.get("limit_display_mode", "both")
    language = config_values.get("language", "en")
    coverage = _combined_coverage(d.cost_coverage for d in daily_by_provider.values())
    cost_text, cost_compact = _cost_texts(total_cost, coverage, language, total_tokens)
    percent_mode = config_values.get("limit_value_mode", "used")

    return {
        "schema_version": SCHEMA_VERSION,
        "updated_at": time.time(),
        "scanning": scanning,
        "errors": errors,
        "today": {
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "tokens_grouped": fmt.grouped(total_tokens),
            "tokens_compact": fmt.compact(total_tokens),
            "cost_text": cost_text,
            # Across every provider, so a day spent on one model through two
            # tools still reads as one row.
            "models": _model_rows(_combined_models(daily_by_provider)),
        },
        "providers": {
            pid: {
                "display_name": (provider_names or {}).get(pid, pid),
                "total_tokens": d.total_tokens,
                "input_compact": fmt.compact(d.input_tokens),
                "output_compact": fmt.compact(d.output_tokens),
                "cache_write_compact": fmt.compact(d.cache_creation_tokens),
                "cache_read_compact": fmt.compact(d.cache_read_tokens),
                # Preformatted: QML's Number.toLocaleString() renders large
                # values as 8.55336e+07. Formatting belongs in one place.
                "total_tokens_text": fmt.grouped(d.total_tokens),
                "total_tokens_compact": fmt.compact(d.total_tokens),
                "total_cost": d.total_cost,
                "cost_text": _cost_texts(d.total_cost, d.cost_coverage, language, d.total_tokens)[0],
                "input_tokens": d.input_tokens,
                "output_tokens": d.output_tokens,
                "cache_creation_tokens": d.cache_creation_tokens,
                "cache_read_tokens": d.cache_read_tokens,
                # The breakdown line is rendered compact ("cache r 478M"), so
                # the compact forms belong here beside every other prepared
                # number rather than being derived again per front end.
                "input_compact": fmt.compact(d.input_tokens),
                "output_compact": fmt.compact(d.output_tokens),
                "cache_creation_compact": fmt.compact(d.cache_creation_tokens),
                "cache_read_compact": fmt.compact(d.cache_read_tokens),
                # One session log can carry several models — Pi and its forks
                # route them all through one file — so the day is broken down
                # by the model that actually answered.
                "models": _model_rows(d.models),
            }
            for pid, d in daily_by_provider.items()
        },
        "limits": _limits_payload(
            limit_status,
            limits_freshness,
            language,
            float(config_values.get("warn_threshold", 80)),
            float(config_values.get("crit_threshold", 95)),
            limit_accounts,
            l10n.catalogue(language),
        ),
        "companion": companion_payload or {},
        "shop": shop_payload or [],
        "bag": bag_payload or [],
        "dex": dex_payload or [],
        "catch_log": catch_log or [],
        "rarity_counts": rarity_counts or {},
        "catch_counts": catch_counts or {},
        "periods": _period_rows(periods, language),
        "month_trend": _month_trend(periods, language, time.strftime("%Y-%m-%d")),
        "strings": l10n.catalogue(config_values.get("language", "en")),
        "celebration": celebration or {},
        # The Pokédex page the popup has open, or {} for none.
        "detail": detail or {},
        "burn": burn or {},
        # The rolling 5-hour block per provider — what the popup's
        # "current 5h block" row shows, and where the forecast's rate comes
        # from. Preformatted for the same reason everything else here is.
        "blocks": {
            pid: {
                "total_tokens": block.total_tokens,
                "total_tokens_text": fmt.grouped(block.total_tokens),
                "total_tokens_compact": fmt.compact(block.total_tokens),
                "cost_text": fmt.cost(block.cost_usd),
                "tokens_per_minute": block.tokens_per_minute,
                "start_time": block.start_time,
                "end_time": block.end_time,
            }
            for pid, block in (blocks or {}).items()
        },
        "provider_status": provider_status or {},
        # What the settings page needs that only the daemon can answer: which
        # sources are registered, and how many of a person's extra folders
        # actually survived. Counting their raw patterns instead would report a
        # folder as accepted when it had been dropped for swallowing a default.
        "settings": settings or {},
        # Whether a newer commit is published, and which one is installed. Only
        # an installed copy answers; a git checkout reports unsupported, since
        # overwriting one would throw away whatever is being worked on.
        "update": update or {"supported": False},
        # The export file the Import button would read, described so the popup
        # can ask before overwriting instead of after.
        "transfer": _transfer_payload(transfer),
        "recap": _recap_payload(recap, language),

        # The live config, so a preferences UI renders current values without
        # parsing config.json itself and without the two drifting apart.
        "config": dict(config_values),
        "panel": {
            "tokens_text": fmt.compact(total_tokens)
            if config_values.get("show_tokens_in_menu")
            else "",
            "cost_text": cost_compact
            if config_values.get("show_cost_in_menu")
            else "",
            "limit_text": limits.panel_text(limit_status, limit_mode, percent_mode)
            if config_values.get("show_limit_in_menu")
            else "",
            # Structured form so the panel can colour each number on its own.
            "limit_windows": [
                {
                    "value": w.utilization,
                    "text": limits.format_percent(limits.display_percent(
                        w.utilization, config_values.get("limit_value_mode"))),
                    "level": limits.level(
                        w.utilization,
                        config_values.get("warn_threshold", 80),
                        config_values.get("crit_threshold", 95),
                    ),
                    # The popup gauge's own tier, so the panel number and the
                    # bar under it cannot say different things (upstream
                    # b32717f). `level` stays for anything that only knows the
                    # three absolute bands.
                    "tier": pace_module.gauge(
                        w.utilization,
                        pace_module.fraction(w.resets_at, pace_module.span_for(kind)),
                        float(config_values.get("warn_threshold", 80)),
                        float(config_values.get("crit_threshold", 95)),
                    ),
                }
                for kind, w in limits.named_windows(limit_status, limit_mode)
            ]
            if config_values.get("show_limit_in_menu")
            else [],
            # The pinned species when there is one, else the companion. Reading
            # `sprite_path` here instead would leave the pin with nowhere to
            # take effect, which is the only thing pinning does.
            "sprite_path": (companion_payload or {}).get(
                "panel_sprite_path", (companion_payload or {}).get("sprite_path", "")
            ),
            # Which species is pinned, so the settings dropdown can show the
            # current choice rather than always reading "follow the current
            # Pokemon" — the one state a pin has that nothing else exposes.
            "representative_id": (companion_payload or {}).get(
                "representative_species_id") or "",
        },
    }


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
