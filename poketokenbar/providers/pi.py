"""Pi Agent and omp (oh-my-pi) usage — ports the Pi/omp halves of LocalUsageReader.swift.

Both write the same session envelope, one JSON document per line, so the record
reader is shared and the two providers differ only in roots, id scoping, and
which envelope fields carry the model.

Counted line shapes:

  type == "message"            one API response. `message.usage` is the charge.
                               Aborted and errored messages are skipped — they
                               were never billed.
  type == "compaction"         a summarisation pass the agent ran on itself;
  type == "branch_summary"     its usage sits on the envelope, not a message.

Every counted line is one response, so rewound branches are not filtered out:
they were already billed, matching pi-session-manager's own accounting.

`usage.input` is already the non-cached input, and Pi's reasoning tokens are a
subset of `output`, so neither is adjusted. When the granular buckets are all
missing the record is malformed; its `totalTokens` is preserved as input rather
than invented a split for.
"""

from __future__ import annotations

import math

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from ..models import Entry
from .base import (
    ScanningProvider,
    dedup_keep_max,
    loads,
    local_day,
    number,
    parse_iso,
    to_int,
)

# Granular buckets. Their presence is what separates a well-formed usage record
# from a total-only one.
_BUCKETS = ("input", "output", "cacheWrite", "cacheRead")


def _message_date(message: dict, envelope: dict) -> datetime | None:
    """Pi stamps messages in epoch milliseconds; envelopes in ISO-8601."""
    millis = number(message.get("timestamp"))
    if millis is not None and millis > 0:
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc)
    return _envelope_date(envelope)


def _envelope_date(envelope: dict) -> datetime | None:
    raw = envelope.get("timestamp")
    return parse_iso(raw) if isinstance(raw, str) else None


def _explicit_cost(usage: dict) -> float | None:
    """`usage.cost.total`, the cost the agent estimated from its own prices.

    Zero counts (upstream 69ff39b): a free model's turn cost nothing, and
    reading 0 as "no figure" priced it from the table instead.
    """
    cost = usage.get("cost")
    if not isinstance(cost, dict):
        return None
    total = number(cost.get("total"))
    return total if total is not None and math.isfinite(total) and total >= 0 else None


def _entry(entry_id: str, date: datetime, usage: dict, model: str) -> Entry | None:
    cost = _explicit_cost(usage)
    common = {
        "id": entry_id,
        "date": date,
        "local_day": local_day(date),
        "model": model,
        "explicit_cost": cost,
        # The agent's figure is its own estimate from model prices.
        "cost_is_estimate": True,
    }
    if any(number(usage.get(name)) is not None for name in _BUCKETS):
        return Entry(
            input=to_int(usage.get("input")),
            output=to_int(usage.get("output")),
            cache_write=to_int(usage.get("cacheWrite")),
            cache_read=to_int(usage.get("cacheRead")),
            **common,
        )
    # Total-only usage has no recoverable split; keep the aggregate rather than
    # dropping a real charge.
    if number(usage.get("totalTokens")) is None:
        return None
    return Entry(
        input=to_int(usage.get("totalTokens")),
        output=0,
        cache_write=0,
        cache_read=0,
        # No bucket split to price from the table.
        cost_unavailable=True,
        **common,
    )


def parse_line(
    line: str,
    *,
    file_name: str,
    default_model: str,
    scope_id_by_file: bool,
    require_assistant_role: bool,
    envelope_model_wins: bool,
) -> Entry | None:
    """One session line. The keyword flags are where Pi and omp actually differ."""
    try:
        envelope = loads(line)
    except Exception:
        return None
    if not isinstance(envelope, dict):
        return None
    kind = envelope.get("type")
    if not isinstance(kind, str):
        return None

    raw_id = envelope.get("id")
    if scope_id_by_file:
        # omp message ids are 8 hex chars, unique only within one session.
        entry_id = raw_id if isinstance(raw_id, str) and raw_id else str(uuid.uuid4())
        entry_id = f"omp|{file_name}|{entry_id}"
    else:
        # Pi ids are globally unique, and dedup across files depends on that.
        if not isinstance(raw_id, str) or not raw_id:
            return None
        entry_id = raw_id

    usage: dict | None = None
    date: datetime | None = None
    model = default_model

    if kind == "message":
        message = envelope.get("message")
        if not isinstance(message, dict):
            return None
        if require_assistant_role and message.get("role") != "assistant":
            return None
        # Aborted and errored turns were never billed.
        if message.get("stopReason") in ("aborted", "error"):
            return None
        message_usage = message.get("usage")
        if not isinstance(message_usage, dict):
            return None
        usage = message_usage
        date = _message_date(message, envelope)
        # Forks write the model on the envelope; vanilla Pi nests it in the message.
        candidates = (
            (envelope.get("model"), message.get("model"))
            if envelope_model_wins
            else (message.get("model"),)
        )
        for candidate in candidates:
            if isinstance(candidate, str) and candidate:
                model = candidate
                break
    elif kind in ("compaction", "branch_summary"):
        envelope_usage = envelope.get("usage")
        usage = envelope_usage if isinstance(envelope_usage, dict) else {}
        date = _envelope_date(envelope)
    else:
        return None

    if date is None or not usage:
        return None
    return _entry(entry_id, date, usage, model)


def _parse(path: Path, **flags) -> list[Entry]:
    out: list[Entry] = []
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                # user/toolResult/custom lines carry no usage — cheap string
                # gate before the JSON decode.
                if '"usage"' not in line:
                    continue
                entry = parse_line(line, file_name=path.name, **flags)
                if entry is not None:
                    out.append(entry)
    except OSError:
        return []
    # Within-file dedup as well as global: a session file can carry the same
    # envelope id twice, and the cached blob should already be collapsed.
    return dedup_keep_max(out)


def _env_roots(
    home: Path, default_relative: str, env: Mapping[str, str], agent_dir_var: str,
    session_dir_var: str | None = None,
) -> list[Path]:
    roots = [home / default_relative]
    agent_dir = (env.get(agent_dir_var) or "").strip()
    if agent_dir:
        roots.append(Path(agent_dir).expanduser() / "sessions")
    if session_dir_var:
        session_dir = (env.get(session_dir_var) or "").strip()
        if session_dir:
            roots.append(Path(session_dir).expanduser())
    return roots


def pi_session_roots(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> list[Path]:
    return _env_roots(
        home or Path.home(),
        ".pi/agent/sessions",
        os.environ if env is None else env,
        "PI_CODING_AGENT_DIR",
        "PI_CODING_AGENT_SESSION_DIR",
    )


def omp_session_roots(
    home: Path | None = None, env: Mapping[str, str] | None = None
) -> list[Path]:
    # omp has no separate session-dir variable; only OMP_CODING_AGENT_DIR exists.
    return _env_roots(
        home or Path.home(),
        ".omp/agent/sessions",
        os.environ if env is None else env,
        "OMP_CODING_AGENT_DIR",
    )


def is_omp_usage_file(path: Path) -> bool:
    """Anything under `bridge/` is a conversion copy of another session source.

    pi-session-manager mirrors Claude, Codex, even omp's own sessions into
    `bridge/`. That usage is already counted by whichever provider owns the
    original, so counting the copy bills the same tokens twice.
    """
    return "bridge" not in path.parts


class PiProvider(ScanningProvider):
    """Pi Agent local usage."""

    id = "pi"
    display_name = "Pi Agent"
    reports_cost = True
    # v2: zero recorded costs count, total-only turns are unpriced (69ff39b).
    PARSER_VERSION = 2

    def curated_roots(self) -> list[Path]:
        return pi_session_roots(self._home)

    def parse_file(self, path: Path) -> list[Entry]:
        return _parse(
            path,
            default_model="pi",
            scope_id_by_file=False,
            require_assistant_role=False,
            envelope_model_wins=True,
        )


class OmpProvider(ScanningProvider):
    """omp (oh-my-pi) local usage."""

    id = "omp"
    display_name = "omp"
    reports_cost = True
    # v2: zero recorded costs count, total-only turns are unpriced (69ff39b).
    PARSER_VERSION = 2

    def curated_roots(self) -> list[Path]:
        return omp_session_roots(self._home)

    def files(self, path: Path):
        for candidate in super().files(path):
            if is_omp_usage_file(candidate):
                yield candidate

    def parse_file(self, path: Path) -> list[Entry]:
        return _parse(
            path,
            default_model="omp",
            scope_id_by_file=True,
            require_assistant_role=True,
            envelope_model_wins=False,
        )
