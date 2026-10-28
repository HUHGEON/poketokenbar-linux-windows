"""Kimi Code per-request wire usage, including subagents and compaction.

Ports LocalUsageReader in upstream v2.5.6. Copied fork history is identified by
record content, since the writer supplies no request id. Costs stay unavailable.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from .base import ScanningProvider, loads, local_day, number, to_int
from ..models import Entry


def parse_line(line: str) -> Entry | None:
    try:
        record = loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(record, dict) or record.get("type") != "usage.record":
        return None
    usage = record.get("usage")
    millis = number(record.get("time"))
    scope = record.get("usageScope")
    if not isinstance(usage, dict) or millis is None or millis <= 0:
        return None
    if scope is not None and scope not in ("turn", "session"):
        return None
    try:
        date = datetime.fromtimestamp(millis / 1000, timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None
    model = record.get("model")
    model = model if isinstance(model, str) and model else "kimi-code"
    input_ = to_int(usage.get("inputOther"))
    output = to_int(usage.get("output"))
    read = to_int(usage.get("inputCacheRead"))
    write = to_int(usage.get("inputCacheCreation"))
    ident = f"kimi|{int(millis)}|{model}|{scope or '-'}|{input_}|{output}|{read}|{write}"
    return Entry(ident, date, local_day(date), model, input=input_, output=output,
                 cache_read=read, cache_write=write)


class KimiProvider(ScanningProvider):
    id = "kimi_code"
    display_name = "Kimi Code"
    reports_cost = False
    file_glob = "wire.jsonl"

    def curated_roots(self) -> list[Path]:
        # Desktop data paths outside macOS are not established upstream. Extra
        # folders support them without guessing a platform-specific location.
        roots = [self.home / ".kimi-code/sessions"]
        import sys
        if sys.platform == "darwin":
            roots.append(self.home / "Library/Application Support/kimi-desktop/daimon-share/daimon/runtime/kimi-code/home/sessions")
        configured = (os.environ.get("KIMI_CODE_HOME") or "").strip()
        if configured:
            roots.append(Path(configured).expanduser() / "sessions")
        return roots

    def parse_file(self, path: Path) -> list[Entry]:
        entries = []
        try:
            with path.open(encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    if '"usage.record"' in line:
                        entry = parse_line(line)
                        if entry is not None:
                            entries.append(entry)
        except OSError:
            return []
        return self.dedup(entries)
