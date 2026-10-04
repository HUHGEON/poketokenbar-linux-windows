"""Kiro CLI usage — ports the Kiro half of LocalAdditionalUsageProvider.swift.

Kiro never persists a real token count, so everything here is a bytes/4 estimate
of the conversation text that gets resent on each request. That is why costs are
not reported: `usage_summary` credits are not API dollars, and pricing an
estimate would present a guess as a bill.

Four store shapes coexist, all of them read:

  data.sqlite3  conversations_v2   kiro-cli < 2.0.1, one row per conversation
  data.sqlite3  conversations      kiro-cli 2.0.1+, one row per working directory
  sessions/cli/<id>.jsonl          CLI 2.20+, Prompt/AssistantMessage/ToolResults
  <ws>/<id>/messages.jsonl         v3 / IDE, structured or flat envelopes

The estimate is cumulative on purpose: a turn's input is the whole conversation
so far plus this prompt, because that is what Kiro actually resends. Text from
turns that are themselves skipped still accumulates into that running total.

**Path remapping.** The SQLite store is an application-data directory rather
than a dotfile, so it moves with the platform:

    macOS    ~/Library/Application Support/kiro-cli
    Linux    $XDG_DATA_HOME/kiro-cli
    Windows  %APPDATA%\\kiro-cli

`~/.kiro/sessions` is a dotfile and is the same everywhere. `$KIRO_CLI_HOME`
and `$KIRO_HOME` override each half.

**A caveat inherited from upstream.** Kiro *deletes* turns from the SQLite store
on `/clear` or compaction, unlike every other source here whose logs only grow.
Previously-seen entries remain counted until restart, month rollover, or a
scan-root change, matching upstream.
"""

from __future__ import annotations

import os
from datetime import date, datetime
from pathlib import Path
from typing import Iterator, Mapping

from .. import platform_paths
from ..models import Entry
from .base import dedup_keep_max, loads, number, parse_iso, to_int
from .sqlite_source import SQLiteProvider, date_value, make_entry, query

# Kiro reports no tokens, so the text is modelled at four bytes each.
BYTES_PER_TOKEN = 4


def flexible_date(raw) -> datetime | None:
    if isinstance(raw, str):
        return parse_iso(raw)
    return date_value(raw)


def _timestamp_millis(raw, date: datetime) -> int:
    """A stable id component: the raw stamp when usable, else the parsed date."""
    value = number(raw)
    if value is not None and value > 0:
        millis = value * 1000 if value < 1_000_000_000_000 else value
        return int(millis)
    return int(date.timestamp() * 1000)


# MARK: byte estimation


def json_byte_length(value) -> int:
    """Stringified length of any JSON value, summed over containers."""
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return len(repr(value).encode("utf-8"))
    if isinstance(value, list):
        return sum(json_byte_length(v) for v in value)
    if isinstance(value, dict):
        return sum(json_byte_length(v) for v in value.values())
    return 0


def field_byte_length(value) -> int:
    """A turn's `user`/`assistant` field, matching kiro-usage's `_text_len`.

    `images` is excluded: a base64 blob would dwarf the actual text and is not
    separately modelled here.
    """
    if isinstance(value, dict):
        return sum(
            json_byte_length(v) for key, v in value.items() if key != "images"
        )
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    return 0


def text_byte_length(value) -> int:
    """Text content of a JSONL event, following the shapes the writers emit."""
    if isinstance(value, str):
        return len(value.encode("utf-8"))
    if isinstance(value, list):
        return sum(text_byte_length(v) for v in value)
    if not isinstance(value, dict):
        return 0
    kind = value.get("kind")
    if isinstance(kind, str):
        return text_byte_length(value.get("data")) if kind == "text" else 0
    for key in ("content", "text", "data"):
        if key in value:
            return text_byte_length(value[key])
    return 0


# MARK: SQLite conversations


def conversation_entries(conversation_id: str, obj: dict) -> list[Entry]:
    turns = obj.get("history")
    if not isinstance(turns, list):
        return []
    out: list[Entry] = []
    # `latest_summary` stands in for turns compaction removed from history. It is
    # still resent on every later request, so it seeds the running total.
    cumulative = json_byte_length(obj.get("latest_summary", 0))
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        user_bytes = field_byte_length(turn.get("user"))
        assistant_bytes = field_byte_length(turn.get("assistant"))
        meta = turn.get("request_metadata")
        if isinstance(meta, dict):
            raw_timestamp = meta.get("request_start_timestamp_ms")
            stamp = number(raw_timestamp)
            date = date_value(raw_timestamp)
            if stamp is not None and stamp > 0 and date is not None:
                model = meta.get("model_id")
                entry = make_entry(
                    f"kiro|{conversation_id}|{int(stamp)}",
                    date,
                    model if isinstance(model, str) and model else "unknown",
                    input=(cumulative + user_bytes) // BYTES_PER_TOKEN,
                    output=to_int(meta.get("response_size")) // BYTES_PER_TOKEN,
                )
                if entry is not None:
                    out.append(entry)
        # Accumulates even for skipped turns — later turns still resend this text.
        cumulative += user_bytes + assistant_bytes
    return out


def parse_database(path: Path) -> list[Entry]:
    # kiro-cli < 2.0.1: one row per conversation, with its id in a column.
    v2_rows = query(path, "SELECT conversation_id, value FROM conversations_v2")
    # kiro-cli 2.0.1+: one row per working directory; the id lives in the JSON.
    v1_rows = query(path, "SELECT value FROM conversations")
    # Both None means the open or the read failed rather than a table being
    # absent, and the next poll must retry. One generation missing while the
    # other succeeds is still a completed scan.
    if v2_rows is None and v1_rows is None:
        return []

    out: list[Entry] = []
    for row in v2_rows or []:
        row_id, value = row[0], row[1]
        obj = _load(value)
        if obj is None:
            continue
        conversation_id = row_id if isinstance(row_id, str) and row_id else None
        if conversation_id is None:
            candidate = obj.get("conversation_id")
            conversation_id = candidate if isinstance(candidate, str) else str(path)
        out.extend(conversation_entries(conversation_id, obj))

    for row in v1_rows or []:
        obj = _load(row[0])
        if obj is None:
            continue
        candidate = obj.get("conversation_id")
        conversation_id = candidate if isinstance(candidate, str) else str(path)
        out.extend(conversation_entries(conversation_id, obj))
    return out


def _load(value):
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    if not isinstance(value, str):
        return None
    try:
        obj = loads(value)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


# MARK: CLI JSONL sessions (2.20+)


def parse_cli_jsonl(path: Path) -> list[Entry]:
    """`{version, kind: Prompt|AssistantMessage|ToolResults|Clear, data}` lines.

    A sibling `<id>.json` carries the session id and the model.
    """
    companion = _read_json(path.with_suffix(".json")) or {}
    session_id = companion.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        session_id = path.stem
    state = companion.get("session_state")
    model = "unknown"
    if isinstance(state, dict):
        rts = state.get("rts_model_state")
        if isinstance(rts, dict):
            info = rts.get("model_info")
            if isinstance(info, dict) and isinstance(info.get("model_id"), str):
                model = info["model_id"]

    entries: list[Entry] = []
    history = 0
    prompt = 0
    prompt_raw = None
    prompt_date: datetime | None = None
    assistant = 0
    tool = 0
    started = False

    def flush():
        nonlocal history, prompt, prompt_raw, prompt_date, assistant, tool
        if started and prompt_date is not None:
            entry = make_entry(
                f"kiro|cli|{session_id}|{_timestamp_millis(prompt_raw, prompt_date)}",
                prompt_date,
                model,
                input=(history + prompt + tool) // BYTES_PER_TOKEN,
                output=assistant // BYTES_PER_TOKEN,
            )
            if entry is not None:
                entries.append(entry)
        # A missing timestamp skips the entry but keeps its text in history.
        history += prompt + assistant + tool
        prompt = assistant = tool = 0
        prompt_raw = None
        prompt_date = None

    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                obj = _load(line)
                if obj is None:
                    continue
                kind = obj.get("kind")
                data = obj.get("data")
                data = data if isinstance(data, dict) else {}
                if kind == "Prompt":
                    if started:
                        flush()
                    started = True
                    prompt = text_byte_length(data.get("content"))
                    meta = data.get("meta")
                    prompt_raw = meta.get("timestamp") if isinstance(meta, dict) else None
                    prompt_date = flexible_date(prompt_raw)
                    assistant = tool = 0
                elif kind == "AssistantMessage":
                    assistant += text_byte_length(data.get("content"))
                elif kind == "ToolResults":
                    tool += text_byte_length(data.get("content"))
                elif kind == "Clear":
                    flush()
                    started = False
                    history = 0
    except OSError:
        return []
    flush()
    return entries


# MARK: v3 / IDE JSONL sessions


def parse_v3_jsonl(path: Path) -> list[Entry]:
    """`messages.jsonl` beside a `session.json`.

    Two envelopes coexist — structured `{payload:{type}}` and flat
    `{role, content}`. `usage_summary` is ignored: its credits are not dollars.
    """
    session = _read_json(path.parent / "session.json") or {}
    session_id = session.get("id")
    if not isinstance(session_id, str) or not session_id:
        session_id = path.parent.name
    model = session.get("modelId")
    model = model if isinstance(model, str) and model else "unknown"
    fallback_date = flexible_date(session.get("createdAt")) or flexible_date(
        session.get("lastModifiedAt")
    )

    entries: list[Entry] = []
    history = 0
    prompt = 0
    prompt_date: datetime | None = None
    assistant = 0
    started = False
    turn_index = 0

    def flush():
        nonlocal history, prompt, prompt_date, assistant, turn_index
        had_content = started and (prompt + assistant) > 0
        if had_content:
            date = prompt_date or fallback_date
            if date is not None:
                entry = make_entry(
                    f"kiro|v3|{session_id}|{turn_index}",
                    date,
                    model,
                    input=(history + prompt) // BYTES_PER_TOKEN,
                    output=assistant // BYTES_PER_TOKEN,
                )
                if entry is not None:
                    entries.append(entry)
        history += prompt + assistant
        prompt = assistant = 0
        prompt_date = None
        if had_content:
            turn_index += 1

    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                obj = _load(line)
                if obj is None:
                    continue
                event_date = flexible_date(obj.get("timestamp"))
                payload = obj.get("payload")
                if isinstance(payload, dict) and isinstance(payload.get("type"), str):
                    kind = payload["type"]
                    if kind == "user":
                        if started:
                            flush()
                        started = True
                        prompt = text_byte_length(payload.get("content"))
                        prompt_date = event_date
                        assistant = 0
                    elif kind == "assistant":
                        assistant += text_byte_length(payload.get("content"))
                        if not started and assistant > 0:
                            started = True
                        if prompt_date is None:
                            prompt_date = event_date
                    elif kind == "tool_call":
                        args = payload.get("args")
                        if args is not None:
                            assistant += (
                                len(args.encode("utf-8"))
                                if isinstance(args, str)
                                else json_byte_length(args)
                            )
                        if not started and assistant > 0:
                            started = True
                    elif kind == "tool_result":
                        prompt += text_byte_length(payload.get("content"))
                    elif kind == "turn_end":
                        if prompt_date is None:
                            prompt_date = event_date
                        flush()
                        started = False
                    # usage_summary / session_metadata carry no billable text.
                elif isinstance(obj.get("role"), str):
                    role = obj["role"]
                    if role in ("user", "human", "prompt"):
                        if started:
                            flush()
                        started = True
                        prompt = text_byte_length(obj.get("content"))
                        prompt_date = event_date
                        assistant = 0
                    elif role in ("assistant", "bot"):
                        assistant += text_byte_length(obj.get("content"))
                        if not started and assistant > 0:
                            started = True
                        if prompt_date is None:
                            prompt_date = event_date
    except OSError:
        return []
    flush()
    return entries


def _read_json(path: Path):
    try:
        obj = loads(path.read_bytes())
    except (OSError, Exception):
        return None
    return obj if isinstance(obj, dict) else None


# MARK: layout


def is_session_file(path: Path) -> bool:
    """Layout-shaped, not "every jsonl under the root".

    2.20 writes `sessions/cli/<id>.jsonl`; v3 and the IDE write `messages.jsonl`
    beside a `session.json`. Matching any .jsonl would sweep in unrelated files.
    """
    if path.name == "messages.jsonl":
        return True
    return path.suffix == ".jsonl" and path.parent.name == "cli"


def sqlite_roots(
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    system: str | None = None,
) -> list[Path]:
    """`$KIRO_CLI_HOME`, else both places the database is known to live.

    Kiro's own session-management page says only "SQLite database in
    `~/.kiro/`", while its macOS install puts one at
    `~/Library/Application Support/kiro-cli/data.sqlite3`. Neither statement
    covers all three platforms, so both are searched rather than one being
    guessed — an empty root costs a directory check, and picking the wrong one
    reads as "this provider has no usage".
    """
    env = os.environ if env is None else env
    configured = (env.get("KIRO_CLI_HOME") or "").strip()
    if configured:
        return [Path(configured).expanduser()]
    return [
        platform_paths.data_base(home=home, env=env, system=system) / "kiro-cli",
        _kiro_home(home, env),
    ]


def _kiro_home(home: Path | None, env: Mapping[str, str] | None) -> Path:
    """`$KIRO_HOME`, else `~/.kiro` — a dotfile, the same on every platform."""
    env = os.environ if env is None else env
    configured = (env.get("KIRO_HOME") or "").strip()
    return Path(configured).expanduser() if configured else (home or Path.home()) / ".kiro"


def session_roots(home: Path | None = None, env: Mapping[str, str] | None = None) -> list[Path]:
    """`$KIRO_HOME/sessions`, else `~/.kiro/sessions` — a dotfile, unchanged."""
    return [_kiro_home(home, env) / "sessions"]


class KiroProvider(SQLiteProvider):
    """Kiro CLI local usage, estimated from conversation text."""

    id = "kiro"
    display_name = "Kiro CLI"
    # Tokens here are an estimate, and usage_summary credits are not API dollars.
    reports_cost = False
    PARSER_VERSION = 1
    database_names = ("data.sqlite3",)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._seen: list[Entry] = []
        self._generation = None

    def scan_entries(self) -> list[Entry]:
        generation = (date.today().strftime("%Y-%m"), self.custom_roots_value())
        if generation != self._generation:
            self._seen = []
            self._generation = generation
        self._seen = dedup_keep_max(self._seen + super().scan_entries())
        return self._seen

    def curated_roots(self) -> list[Path]:
        return sqlite_roots(self._home) + session_roots(self._home)

    def files(self, root: Path) -> Iterator[Path]:
        if root.is_file():
            yield root
            return
        yield from self.databases(root)
        for candidate in sorted(root.rglob("*.jsonl")):
            if is_session_file(candidate):
                yield candidate

    def file_signature(self, path: Path) -> tuple[float, int] | None:
        if path.suffix == ".jsonl":
            try:
                stat = path.stat()
            except OSError:
                return None
            return (stat.st_mtime, stat.st_size)
        return super().file_signature(path)

    def parse_file(self, path: Path) -> list[Entry]:
        if path.name == "messages.jsonl":
            return parse_v3_jsonl(path)
        if path.suffix == ".jsonl":
            return parse_cli_jsonl(path)
        return parse_database(path)
