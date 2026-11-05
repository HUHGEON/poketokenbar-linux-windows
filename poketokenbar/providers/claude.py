"""Claude Code usage — ports the Claude half of LocalUsageReader.swift.

Rule: keep `type == "assistant"` rows, sum the four token fields of
`message.usage`, deduplicate on `(message.id, requestId)` keeping the entry
with the LARGEST total, and bucket by local date from `timestamp`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from datetime import date as _date
from datetime import datetime
from pathlib import Path

from .. import pricing
from ..cache import ScanCache
from ..models import DailyUsage, Entry, ProviderEnrichment

from .base import (ScanningProvider, dedup_keep_max, loads as _loads,
                   number as _number, parse_iso, streamed, to_int as _int)

# Re-exported under their original names: the tests and the Codex provider
# already import them from here.
_parse_timestamp = parse_iso


def parse_line(line: str) -> Entry | None:
    try:
        obj = _loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict) or obj.get("type") != "assistant":
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    date = _parse_timestamp(obj.get("timestamp", ""))
    if date is None:
        return None
    return Entry(
        id=f"{msg.get('id') or ''}|{obj.get('requestId') or ''}",
        date=date,
        local_day=date.astimezone().strftime("%Y-%m-%d"),
        model=msg.get("model") or "unknown",
        # Only top-level fields. usage["iterations"] repeats these numbers.
        input=_int(usage.get("input_tokens")),
        output=_int(usage.get("output_tokens")),
        cache_write=_int(usage.get("cache_creation_input_tokens")),
        cache_read=_int(usage.get("cache_read_input_tokens")),
    )


def cost_model_key(model: str) -> str:
    """The base model id, with the context-window variant dropped.

    `modelUsage` names the variant (`claude-opus-5[1m]`) while an assistant
    line's `message.model` never does, so attribution has to match on the base
    id. Pooling both variants under it is right: they are one model's spend.
    """
    head, _, _ = model.partition("[")
    return head


def parse_cost_state_line(line: str) -> dict[str, float] | None:
    """Claude Code's own cost ledger (`type: "cost-state"`), or None.

    Ports upstream's parseClaudeCostStateLine (8b2dd95). The record is appended
    cumulatively through a session and carries authoritative per-model totals,
    covering models and context variants the price table holds no rate for. A
    ledger with no usable row returns None so it cannot clobber an earlier one.
    """
    try:
        obj = _loads(line)
    except Exception:
        return None
    if not isinstance(obj, dict) or obj.get("type") != "cost-state":
        return None
    usage = obj.get("modelUsage")
    if not isinstance(usage, dict):
        return None
    by_model: dict[str, float] = {}
    for model, fields in usage.items():
        if not isinstance(fields, dict) or not isinstance(model, str):
            continue
        cost = _number(fields.get("costUSD"))
        if cost is None or cost < 0:
            continue
        key = cost_model_key(model)
        by_model[key] = by_model.get(key, 0.0) + cost
    return by_model or None


def apply_reported_cost(entries: list[Entry], by_model: dict[str, float]) -> list[Entry]:
    """Spread each model's reported session total over that model's entries.

    The session sum stays exact; only the split *within* one session is
    inferred, so the amount is still a reported cost — a redistributed report,
    not a price-table guess. A model the source priced but that produced no
    parsed entry is skipped rather than reassigned, so an amount that cannot be
    attributed never inflates another model's day.
    """
    if not by_model:
        return entries
    indices: dict[str, list[int]] = {}
    for i, e in enumerate(entries):
        if e.total > 0:
            indices.setdefault(cost_model_key(e.model), []).append(i)
    for model, cost in by_model.items():
        idx = indices.get(model)
        if not idx:
            continue
        total_tokens = sum(entries[i].total for i in idx)
        if total_tokens <= 0:
            continue
        remaining = cost
        for n, i in enumerate(idx):
            # The last entry absorbs the rounding remainder, so the session
            # total is exact however the shares divide.
            share = remaining if n == len(idx) - 1 else cost * entries[i].total / total_tokens
            entries[i].explicit_cost = max(0.0, share)
            entries[i].cost_is_estimate = False
            remaining -= share
    return entries


# Read in blocks rather than a line at a time: a session log runs to hundreds
# of megabytes, and this bounds what is held however long one line turns out
# to be.
_BLOCK = 1 << 22


def parse_from(path: Path, offset: int = 0) -> tuple[list[Entry], int, dict[str, float] | None]:
    """The entries from `offset` on, the byte it stopped at, and the ledger.

    The byte it stopped at is the end of the last *complete* line. A session
    being written to right now ends mid-line as often as not, and consuming a
    half-written record would lose it: the next poll starts again from there
    and reads the whole line once it has a newline after it.

    Lines are matched as bytes before anything is decoded. Most of a session
    log is user turns, file contents and tool output, and decoding all of that
    to find the assistant turns was most of the cold scan (upstream 8f74054).
    """
    out: list[Entry] = []
    cost_state: dict[str, float] | None = None
    consumed = offset

    def _read(raw: bytes) -> None:
        nonlocal cost_state
        # The ledger is cumulative, so the last record in the file wins.
        # Checked before the assistant prefilter: a cost-state line carries
        # "modelUsage", not "usage".
        if b'"cost-state"' in raw:
            cost_state = parse_cost_state_line(raw.decode("utf-8", "replace")) or cost_state
            return
        if b'"usage"' not in raw or b'"assistant"' not in raw:
            return
        entry = parse_line(raw.decode("utf-8", "replace"))
        if entry is not None:
            out.append(entry)

    try:
        with streamed(path, binary=True) as fh:
            fh.seek(offset)
            rest = b""
            while True:
                block = fh.read(_BLOCK)
                if not block:
                    break
                lines = (rest + block).split(b"\n")
                rest = lines.pop()
                for raw in lines:
                    consumed += len(raw) + 1
                    _read(raw)
            # A file that simply ends without a newline is still a record, and
            # a session mid-write looks exactly the same. It is read either
            # way but never counted as consumed: once the rest of it lands,
            # the whole line is read again and the repeat deduplicates away.
            if rest:
                _read(rest)
    except OSError:
        return [], offset, None
    return dedup_keep_max(out), consumed, cost_state


def parse_file(path: Path) -> list[Entry]:
    """Every entry in the file, with the session's reported costs applied."""
    entries, _offset, cost_state = parse_from(path, 0)
    if cost_state is None:
        return entries
    return apply_reported_cost(entries, cost_state)


def project_roots(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> list[Path]:
    """Existing Claude project roots, symlink-deduplicated.

    macOS also probes ~/Library/Application Support/Claude for Claude Desktop
    embedded sessions. That path cannot exist on Linux, so it is omitted rather
    than branched on.
    """
    home = home or Path.home()
    env = os.environ if env is None else env

    candidates = [home / ".claude" / "projects", home / ".config" / "claude" / "projects"]
    configured = env.get("CLAUDE_CONFIG_DIR")
    if configured:
        candidates.append(Path(configured) / "projects")

    seen: set[Path] = set()
    roots: list[Path] = []
    for path in candidates:
        if not path.is_dir():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        roots.append(path)
    return roots


def jsonl_files(root: Path) -> Iterator[Path]:
    """Every *.jsonl under root, including inside hidden directories."""
    yield from root.rglob("*.jsonl")


class ClaudeProvider(ScanningProvider):
    """Claude Code local usage."""

    id = "claude_code"
    display_name = "Claude Code"
    reports_cost = True
    # Bump when parse_line changes shape, to invalidate cached blobs. 2 adds
    # the reported cost from Claude Code's own cost-state ledger; 3 keeps a
    # duplicated turn's earliest timestamp.
    PARSER_VERSION = 3

    def curated_roots(self) -> list[Path]:
        return project_roots(home=self._home)

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_file(path)

    def parse_from(self, path: Path, offset: int):
        """The tail of an append-only session log (upstream 8f74054).

        The entries are handed back raw, with the ledger beside them: it is a
        running total for the whole session, so it has to be applied over
        every entry in the file rather than over the tail alone.
        """
        entries, consumed, cost_state = parse_from(path, offset)
        return entries, consumed, (None if cost_state is None else dict(cost_state))

    def attributed(self, entries: list[Entry], extra: dict | None) -> list[Entry]:
        if not extra:
            # Nothing reported, or a row written before the ledger was kept
            # beside the entries — those were stored with it already applied.
            return entries
        return apply_reported_cost(entries, extra)
