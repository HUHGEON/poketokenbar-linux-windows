"""Kimi Code usage — ports the Kimi half of LocalUsageReader.swift (upstream 40b506e).

Usage lives in `sessions/<work dir>/<session>/agents/<agent>/wire.jsonl`, one
JSON document per line. Every agent — the main one and each subagent — keeps
its own wire log and records its own requests, so all of them count.

Only `type == "usage.record"` lines carry usage. Kimi writes one such record
per LLM request with that request's own token counts. `usageScope` is "turn"
inside a turn and "session" for a request outside one, such as a compaction;
both are per-request deltas and both count, as Kimi's own `byModel` total sums
them. A scope this does not know is skipped rather than guessed at.

Costs are not reported: the records carry token counts only.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ..models import Entry
from .base import ScanningProvider, dedup_keep_max, loads, local_day, number, to_int

# The standalone CLI's data root, from Kimi Code's own
# docs/en/configuration/data-locations.md.
CLI_HOME = ".kimi-code"
# The desktop app embeds the same runtime under its own root (upstream #386).
# macOS-shaped, and kept for a save carried between machines; the Linux and
# Windows roots below are where that runtime actually lands.
DESKTOP_HOMES = (
    "Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/kimi-code/home",
    ".config/kimi-desktop/daimon-share/daimon/runtime/kimi-code/home",
    "AppData/Roaming/kimi-desktop/daimon-share/daimon/runtime/kimi-code/home",
)
# Scopes that are a request's own delta. Anything else is a shape this parser
# has not seen.
SCOPES = (None, "turn", "session")


def session_roots(home: Path | None = None,
                  env: Mapping[str, str] | None = None) -> list[Path]:
    """`<root>/sessions` for the CLI root, each desktop runtime root, and
    `$KIMI_CODE_HOME` when it is set."""
    env = os.environ if env is None else env
    base = home or Path.home()
    roots = [base / CLI_HOME / "sessions"]
    roots += [base / Path(desktop) / "sessions" for desktop in DESKTOP_HOMES]
    configured = (env.get("KIMI_CODE_HOME") or "").strip()
    if configured:
        roots.append(Path(configured).expanduser() / "sessions")
    return roots


def is_usage_file(path: Path) -> bool:
    """Usage is only ever in a `wire.jsonl`; the other logs are messages."""
    return path.name == "wire.jsonl"


def parse_record(record: dict) -> Entry | None:
    """One `usage.record` line, or None for every other kind of line."""
    if record.get("type") != "usage.record":
        return None
    usage = record.get("usage")
    if not isinstance(usage, dict):
        return None
    millis = number(record.get("time"))
    if millis is None or millis <= 0:
        return None
    scope = record.get("usageScope")
    if scope not in SCOPES:
        return None

    model = record.get("model")
    model = model if isinstance(model, str) and model else "kimi-code"
    input_ = to_int(usage.get("inputOther"))
    output = to_int(usage.get("output"))
    cache_read = to_int(usage.get("inputCacheRead"))
    cache_write = to_int(usage.get("inputCacheCreation"))
    when = datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    # The records carry no id of their own, and `/fork` copies a session
    # wholesale — an id made from the file's path would count the copied
    # history a second time. The record's own content identifies it.
    identity = (f"kimi|{int(millis)}|{model}|{scope or '-'}"
                f"|{input_}|{output}|{cache_read}|{cache_write}")
    return Entry(
        id=identity,
        date=when,
        local_day=local_day(when),
        model=model,
        input=input_,
        output=output,
        cache_write=cache_write,
        cache_read=cache_read,
    )


def parse_file(path: Path) -> list[Entry]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[Entry] = []
    for line in text.splitlines():
        # Most lines are messages and request traces, and this file is read on
        # every scan: the substring check keeps the JSON parse for the few
        # lines that can possibly be usage.
        if '"usage.record"' not in line:
            continue
        try:
            record = loads(line)
        except Exception:
            continue
        if not isinstance(record, dict):
            continue
        entry = parse_record(record)
        if entry is not None:
            out.append(entry)
    return out


class KimiCodeProvider(ScanningProvider):
    """Kimi Code local usage."""

    id = "kimi_code"
    display_name = "Kimi Code"
    # The records carry token counts only.
    reports_cost = False

    def curated_roots(self) -> list[Path]:
        return session_roots(self._home)

    def files(self, root: Path):
        for candidate in super().files(root):
            if is_usage_file(candidate):
                yield candidate

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_file(path)

    def dedup(self, entries: list[Entry]) -> list[Entry]:
        return dedup_keep_max(entries)
