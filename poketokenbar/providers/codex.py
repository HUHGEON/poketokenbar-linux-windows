"""Codex usage — ports the Codex half of LocalUsageReader.swift.

Rollout files at ~/.codex/sessions/**/rollout-*.jsonl carry
`payload.type == "token_count"` events. Each event's `info.last_token_usage`
is the delta for that turn, so entries are summed rather than max-reduced.

Turn identity is `(file, turn index)`. A forked or resumed session copies its
parent's events verbatim, so the same turn can appear in several files; the
provider deduplicates on the session id it finds in the file metadata.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date as _date
from pathlib import Path

from .. import pricing
from ..cache import ScanCache
from ..models import DailyUsage, Entry, ProviderEnrichment
from .base import ScanningProvider, dedup_keep_first
from .claude import _parse_timestamp, jsonl_files

# v2: a turn whose last_token_usage has only total_tokens is counted (upstream #278).
PARSER_VERSION = 2


def _int(value) -> int:
    return value if isinstance(value, int) else 0


@dataclass(slots=True)
class ParsedRollout:
    entries: list[Entry]
    session_id: str | None


def parse_rollout(path: Path) -> ParsedRollout:
    """Parse one rollout file into per-turn entries."""
    entries: list[Entry] = []
    session_id: str | None = None
    model = "gpt-5.5"
    turn = 0
    # Cumulative total of the previous token_count event that carried one, for
    # telling a real total-only turn from a fork's zero-context replay.
    previous_cumulative: int | None = None
    name = path.name

    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"session_id"' in line or '"model"' in line:
                    obj = _load(line)
                    if isinstance(obj, dict):
                        found = _find_session_id(obj)
                        if found and session_id is None:
                            session_id = found
                        found_model = _find_model(obj)
                        if found_model:
                            model = found_model
                if "token_count" not in line:
                    continue
                obj = _load(line)
                if not isinstance(obj, dict):
                    continue
                payload = obj.get("payload")
                if not isinstance(payload, dict) or payload.get("type") != "token_count":
                    continue
                info = payload.get("info")
                if not isinstance(info, dict):
                    continue
                last = info.get("last_token_usage")
                if not isinstance(last, dict):
                    continue
                date = _parse_timestamp(obj.get("timestamp", ""))
                if date is None:
                    continue

                input_total = _int(last.get("input_tokens"))
                cached = _int(last.get("cached_input_tokens"))
                input_ = max(0, input_total - cached)
                output = _int(last.get("output_tokens"))
                cumulative = info.get("total_token_usage")
                if not isinstance(cumulative, dict):
                    cumulative = None
                if input_ + cached + output == 0 and _trust_total_only(
                    _last_total(last), cumulative, previous_cumulative
                ):
                    # Every component is 0 but the turn has a total. The
                    # split cannot be recovered, so it is all counted as input.
                    input_, output, cached = _last_total(last), 0, 0
                if cumulative is not None:
                    previous_cumulative = _int(cumulative.get("total_tokens"))
                entries.append(
                    Entry(
                        # Keyed by (cumulative, delta), not by file position or
                        # timestamp. A fork replays the parent's turns with
                        # fresh timestamps but an identical cumulative
                        # sequence, so this collapses the copies while keeping
                        # the fork's own turns. The delta is part of the key
                        # because a fork emits a zero-delta turn that repeats
                        # the parent's final cumulative value.
                        id=f"codex|{_cumulative(info)}|{_last_total(last)}",
                        date=date,
                        local_day=date.astimezone().strftime("%Y-%m-%d"),
                        model=model,
                        input=input_,
                        output=output,
                        cache_write=0,
                        cache_read=cached,
                    )
                )
                turn += 1
    except OSError:
        return ParsedRollout([], None)

    return ParsedRollout(entries, session_id)


def _components(usage: dict) -> int:
    """input (which includes cached) plus output: what an Entry is built from."""
    return _int(usage.get("input_tokens")) + _int(usage.get("output_tokens"))


def _trust_total_only(
    last_total: int, cumulative: dict | None, previous_cumulative: int | None
) -> bool:
    """Whether a turn with no token components should count its total_tokens.

    Codex sometimes writes last_token_usage with every component at 0 and only
    total_tokens set (upstream #278); those turns were dropped. Ported from
    upstream's shouldTrustCodexTotalOnlyLast and
    codexEntryTrustingTotalOnlyLast. The total is trusted when:

    - there is no cumulative usage, so the total is the only signal;
    - the cumulative has no components either, so the session is total-only;
    - the turn's total is the whole session total (a sole or first turn);
    - the cumulative total grew since the previous event.

    Otherwise it stays 0. That remaining shape is a fork's zero-context turn
    after replaying its parent: the cumulative is unchanged, and its total is
    not new usage.
    """
    if last_total <= 0:
        return False
    if cumulative is None:
        return True
    cumulative_total = _int(cumulative.get("total_tokens"))
    if _components(cumulative) == 0 and cumulative_total > 0:
        return True
    if cumulative_total == last_total:
        return True
    return previous_cumulative is not None and cumulative_total > previous_cumulative


def _cumulative(info: dict) -> int:
    total = info.get("total_token_usage")
    return _int(total.get("total_tokens")) if isinstance(total, dict) else 0


def _last_total(last: dict) -> int:
    return _int(last.get("total_tokens"))


def _load(line: str):
    try:
        return json.loads(line)
    except ValueError:
        return None


def _find_session_id(obj: dict) -> str | None:
    for key in ("session_id", "sessionId", "id"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return value
    payload = obj.get("payload")
    if isinstance(payload, dict):
        return _find_session_id(payload)
    return None


def _find_model(obj: dict) -> str | None:
    value = obj.get("model")
    if isinstance(value, str) and value:
        return value
    payload = obj.get("payload")
    if isinstance(payload, dict):
        return _find_model(payload)
    return None


def session_roots(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    root = home / ".codex" / "sessions"
    return [root] if root.is_dir() else []


class CodexProvider(ScanningProvider):
    """Codex local usage."""

    id = "codex"
    display_name = "Codex"
    reports_cost = True
    PARSER_VERSION = PARSER_VERSION

    def curated_roots(self) -> list[Path]:
        return session_roots(self._home)

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_rollout(path).entries

    def dedup(self, entries: list[Entry]) -> list[Entry]:
        # A fork or resume replays the parent's turns verbatim, so every copy
        # carries identical numbers — first wins, not largest.
        return dedup_keep_first(entries)

    # Kept as a static entry point: the tests dedup a hand-built list.
    dedup_entries = staticmethod(dedup_keep_first)
