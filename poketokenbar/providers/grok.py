"""Grok CLI usage — ports the Grok half of LocalUsageReader.swift.

Sessions live at `~/.grok/sessions/<id>/`, and only `updates.jsonl` carries
tokens: `chat_history.jsonl` has no usage field and `events.jsonl` records turn
outcomes, so scanning either only fills the cache with empty blobs.

Within that file only `sessionUpdate == "turn_completed"` lines count. The other
token numbers in there — `_meta.totalTokens`, auto-compact and subagent progress
events — are *context window sizes*, not spend; mixing them in inflates the
totals badly. Turns discarded by a rewind still count: undoing a branch does not
refund what was already billed.

Token mapping, arranged so that `Entry.total` equals the source's own
`totalTokens`:

  inputTokens   (camelCase)  the whole prompt, cache reads included, so
                             input = inputTokens - cachedReadTokens
  input_tokens  (snake_case) already excludes cache, so it is used as-is
  output                     outputTokens; reasoning is already inside it
  cache_write                always 0 — Grok folds cache writes into the prompt

The two spellings mean different things, so the branch is on which key is
present. Treating them as synonyms subtracts the cached reads twice.
"""

from __future__ import annotations

import math

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ..models import Entry
from .base import (
    ScanningProvider,
    dedup_keep_max,
    int_or_none,
    loads,
    local_day,
    number,
    parse_iso,
)

# The only file in a session directory that holds usage.
UPDATES_FILE_NAME = "updates.jsonl"


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    parsed = number(value)
    return parsed is not None and parsed != 0


def _first_int(usage: dict, *names: str) -> int | None:
    """The first of `names` that carries an actual number."""
    for name in names:
        parsed = int_or_none(usage.get(name))
        if parsed is not None:
            return parsed
    return None


def session_is_subagent(session_dir: Path) -> bool:
    """Whether `summary.json` marks this session as a subagent's.

    A subagent's tokens are already folded into the parent turn's usage, so
    counting the subagent session too bills them twice. This uses the same
    `session_kind` prefix the CLI itself hides sessions by.

    A missing or unreadable summary reads as a user session: the CLI writes the
    summary when it creates a session, so absence means "new session, no turns
    yet" — nothing to count either way.

    `hidden` is deliberately not consulted; a user who hid a normal session
    would then be under-counted.
    """
    try:
        raw = (session_dir / "summary.json").read_bytes()
    except OSError:
        return False
    try:
        obj = loads(raw)
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    kind = obj.get("session_kind")
    return isinstance(kind, str) and kind.startswith("subagent")


def is_usage_file(path: Path) -> bool:
    """Judged when picking files, never inside the parse.

    The parsed-blob cache is keyed on `updates.jsonl`'s own mtime and size, but
    the evidence for this verdict lives in a sibling (`summary.json`). Filtering
    inside the parse would freeze a subagent session into the cache whenever it
    was first read before its summary carried `session_kind` — and since the
    file never changes again, the cache would keep hitting and the double count
    would be permanent. Re-judging at selection time heals itself on every refresh.
    """
    if path.name != UPDATES_FILE_NAME:
        return False
    return not session_is_subagent(path.parent)


def _model(usage: dict) -> str | None:
    """The busiest model in the per-model breakdown; ties go to the first name.

    Only the label comes from here — the numbers always come from the totals, so
    a per-model breakdown that disagrees with them cannot move the totals.
    """
    by_model = usage.get("modelUsage")
    if not isinstance(by_model, dict):
        by_model = usage.get("model_usage")
    if not isinstance(by_model, dict):
        return None
    best_name: str | None = None
    best_total = -1
    for name in sorted(by_model):
        fields = by_model[name] if isinstance(by_model[name], dict) else {}
        total = _first_int(fields, "totalTokens", "total_tokens") or 0
        if total > best_total:
            best_name, best_total = name, total
    return best_name if best_name else None


def _cost(usage: dict) -> float | None:
    """Only the server's own figure, in ticks where 1e10 ticks = $1.

    There is no Grok price table to fall back on, so a partial or incomplete
    reading is dropped rather than estimated — a wrong dollar figure is worse
    than none.
    """
    if _truthy(usage.get("usageIsIncomplete")) or _truthy(usage.get("usage_is_incomplete")):
        return None
    if _truthy(usage.get("costIsPartial")) or _truthy(usage.get("cost_is_partial")):
        return None
    ticks = number(usage.get("costUsdTicks"))
    if ticks is None:
        ticks = number(usage.get("cost_usd_ticks"))
    # Zero ticks is a recorded $0 (upstream 69ff39b), not a missing figure.
    if ticks is None or not math.isfinite(ticks) or ticks < 0:
        return None
    return ticks / 1e10


def _date(envelope: dict, meta: dict | None) -> datetime | None:
    """`_meta.agentTimestampMs` wins over the envelope's record time.

    A fork copies the parent's updates and re-stamps the envelope, so trusting
    the envelope would pile every historical turn onto the day of the fork and
    skew today, this week, and this month. `_meta` survives the copy intact.
    """
    if meta is not None:
        millis = number(meta.get("agentTimestampMs"))
        if millis is not None and millis > 0:
            return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    raw = number(envelope.get("timestamp"))
    if raw is not None and raw > 0:
        # The envelope is in seconds, but absorb a milliseconds variant too.
        seconds = raw / 1000 if raw >= 100_000_000_000 else raw
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    text = envelope.get("timestamp")
    return parse_iso(text) if isinstance(text, str) else None


def parse_line(line: str) -> Entry | None:
    try:
        envelope = loads(line)
    except Exception:
        return None
    if not isinstance(envelope, dict):
        return None
    # Three layers on disk: envelope -> notification -> update. Older lines are
    # the notification itself, with no envelope around it.
    params = envelope.get("params")
    notification = params if isinstance(params, dict) else envelope

    update = notification.get("update")
    if not isinstance(update, dict) or update.get("sessionUpdate") != "turn_completed":
        return None
    usage = update.get("usage")
    if not isinstance(usage, dict):
        return None

    meta = notification.get("_meta")
    meta = meta if isinstance(meta, dict) else None
    # Secondary guard only; the turn-id dedup below is the real defence. Replays
    # are usually marked on the wire and never reach disk.
    if meta is not None and _truthy(meta.get("isReplay")):
        return None

    turn_id = update.get("prompt_id")
    if not isinstance(turn_id, str) or not turn_id:
        return None
    date = _date(envelope, meta)
    if date is None:
        return None

    output = _first_int(usage, "outputTokens", "output_tokens") or 0
    reported_cache_read = _first_int(usage, "cachedReadTokens", "cached_read_tokens") or 0

    full = int_or_none(usage.get("inputTokens"))
    if full is not None:
        # Cache reads are a subset of the prompt and cannot exceed it. Clamping
        # keeps the identity; a max(0, ...) instead let input + cache_read run
        # past inputTokens and quietly inflated the total.
        clamped = min(reported_cache_read, full)
        input_tokens, cache_read = full - clamped, clamped
    else:
        # A headless projection already reports input net of cache.
        input_tokens = int_or_none(usage.get("input_tokens")) or 0
        cache_read = reported_cache_read

    reported_total = _first_int(usage, "totalTokens", "total_tokens")
    if reported_total is not None:
        parts = input_tokens + output + cache_read
        if reported_total > parts:
            # Attribute the shortfall to output so the total still matches the
            # source, the same rule the other readers follow.
            output += reported_total - parts

    # A zero-token turn (cancelled before any call) is not a record of spend.
    if input_tokens + output + cache_read <= 0:
        return None

    return Entry(
        id=f"grok|{turn_id}",
        date=date,
        local_day=local_day(date),
        model=_model(usage) or "grok",
        input=input_tokens,
        output=output,
        cache_write=0,
        cache_read=cache_read,
        explicit_cost=_cost(usage),
    )


def parse_file(path: Path) -> list[Entry]:
    out: list[Entry] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                # updates.jsonl keeps every streaming chunk as its own line —
                # tens of thousands per session. Filter before decoding.
                if "turn_completed" not in line:
                    continue
                entry = parse_line(line)
                if entry is not None:
                    out.append(entry)
    except OSError:
        return []
    return dedup_keep_max(out)


def session_roots(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> list[Path]:
    """`$GROK_HOME/sessions`, else `~/.grok/sessions` — the CLI's own rule."""
    env = os.environ if env is None else env
    configured = (env.get("GROK_HOME") or "").strip()
    if configured:
        return [Path(configured).expanduser() / "sessions"]
    return [(home or Path.home()) / ".grok" / "sessions"]


class GrokProvider(ScanningProvider):
    """Grok CLI local usage."""

    id = "grok"
    display_name = "Grok CLI"
    reports_cost = True
    # v2: a zero-tick cost counts (69ff39b).
    PARSER_VERSION = 2

    def curated_roots(self) -> list[Path]:
        return session_roots(self._home)

    def files(self, root: Path):
        for candidate in super().files(root):
            if is_usage_file(candidate):
                yield candidate

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_file(path)
