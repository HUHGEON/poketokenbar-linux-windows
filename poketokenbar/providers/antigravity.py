"""Antigravity usage — ports LocalAntigravityUsageReader.swift.

Each conversation is its own SQLite store under `~/.gemini/antigravity*/
conversations/`, and every `gen_metadata` row holds a protobuf blob rather than
JSON. There is no generated code for that schema, so the fields this reader
needs are picked out of the wire format directly.

Field map, as read from the blob:

    1                   chat model
    1.4                 usage
    1.4.2/3/4/5         input / output / cache write / cache read tokens
    1.4.11              response_id — the turn's own identity
    1.9.4               chat_start_metadata.created_at (google.protobuf.Timestamp)
    1.19                response_model
    4                   execution id

Costs are not reported: Antigravity is subscription-billed and states no
per-token amount. The `antigravity/` model prefix keeps those names away from
the price table, which matters because it calls models like claude-sonnet-4-6
that would otherwise match.

Entry identity is the turn's `response_id`, not the file it sits in, so a copied
conversation store does not read as fresh spend.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Mapping

from ..models import Entry
from .sqlite_source import SQLiteProvider, make_entry, query

# Tokens are uint64 on the wire. A per-call counter three orders of magnitude
# past the largest context window is a sentinel, not a count.
#
# This differs from the JSON readers' ceiling on both axes, deliberately. It is
# tighter because nothing here sums two parsed values before Entry.total, and
# an over-ceiling value is *discarded* rather than clamped: clamping keeps a
# number that then dominates every aggregate it reaches — today's total, the
# burn tier, the companion — while discarding loses one counter and leaves the
# rest of the record intact.
TOKEN_CEILING = 1_000_000_000

_SQL = "SELECT idx, data FROM gen_metadata WHERE data IS NOT NULL ORDER BY idx"


# MARK: minimal protobuf wire reader


def _varint_at(data: bytes, index: int) -> tuple[int, int] | None:
    result = 0
    shift = 0
    while index < len(data):
        byte = data[index]
        index += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, index
        shift += 7
        if shift > 63:
            return None
    return None


def walk(data: bytes, visit: Callable[[int, int, bytes | None], bool]) -> None:
    """Visit each field in order until `visit` returns False or the bytes stop making sense.

    Length-delimited fields arrive as `payload`; varints arrive as `value`.
    Fixed-width fields are skipped — nothing this reader wants is encoded that way.
    """
    index = 0
    while index < len(data):
        key_pair = _varint_at(data, index)
        if key_pair is None:
            return
        key, index = key_pair
        field = key >> 3
        if field <= 0:
            return
        wire = key & 7
        if wire == 0:
            value_pair = _varint_at(data, index)
            if value_pair is None:
                return
            value, index = value_pair
            if not visit(field, value, None):
                return
        elif wire == 1:
            if len(data) - index < 8:
                return
            index += 8
        elif wire == 2:
            length_pair = _varint_at(data, index)
            if length_pair is None:
                return
            length, after = length_pair
            if length > len(data) - after:
                return
            end = after + length
            if not visit(field, 0, data[after:end]):
                return
            index = end
        elif wire == 5:
            if len(data) - index < 4:
                return
            index += 4
        else:
            # Groups (3 and 4) were removed from the language, so meeting one
            # means these bytes are not the message we took them for.
            return


def varint(data: bytes, field: int) -> int | None:
    found: int | None = None

    def visit(number, value, payload):
        nonlocal found
        if number != field or payload is not None:
            return True
        found = value
        return False

    walk(data, visit)
    return found


def message(data: bytes, field: int) -> bytes | None:
    found: bytes | None = None

    def visit(number, _value, payload):
        nonlocal found
        if number != field or payload is None:
            return True
        found = payload
        return False

    walk(data, visit)
    return found


def string(data: bytes, field: int) -> str | None:
    payload = message(data, field)
    if not payload:
        return None
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return text or None


def token_count(data: bytes, field: int) -> int | None:
    """None means the field was present and its value cannot be a count.

    That is not the same as the field being absent, which is a legitimate zero —
    `cache_write_tokens` is declared and never written — and the caller needs to
    tell the two apart to be able to report that a discard happened.
    """
    value = varint(data, field)
    if value is None:
        return 0
    return value if value <= TOKEN_CEILING else None


# MARK: record parsing


class Record:
    __slots__ = ("entry", "discarded_counters")

    def __init__(self, entry: Entry | None = None, discarded_counters: int = 0) -> None:
        self.entry = entry
        self.discarded_counters = discarded_counters


def _created_at(chat_model: bytes) -> tuple[str, datetime | None]:
    """`chat_start_metadata.created_at`, a google.protobuf.Timestamp.

    Returns ("absent"|"valid"|"invalid", date). Absent means fall back to a
    step date; invalid means the record itself is not trustworthy.
    """
    start = message(chat_model, 9)
    if start is None:
        return ("absent", None)
    stamp = message(start, 4)
    if stamp is None:
        return ("absent", None)
    seconds = varint(stamp, 1)
    if seconds is None or seconds < 1_000_000_000 or seconds > 4_102_444_800:
        return ("invalid", None)
    raw_nanos = varint(stamp, 2)
    nanos = raw_nanos if raw_nanos is not None and raw_nanos < 1_000_000_000 else 0
    return ("valid", datetime.fromtimestamp(seconds + nanos / 1e9, tz=timezone.utc))


def parse_generation_metadata(
    blob: bytes,
    conversation: str,
    index: int,
    fallback_date: Callable[[str | None, str | None], datetime | None] = lambda r, e: None,
) -> Record:
    chat_model = message(blob, 1)
    if chat_model is None:
        return Record()
    usage = message(chat_model, 4)
    if usage is None:
        return Record()

    response_id = string(usage, 11)
    execution_id = string(blob, 4)

    state, date = _created_at(chat_model)
    if state == "absent":
        date = fallback_date(response_id, execution_id)
        if date is None:
            return Record()
    elif state == "invalid":
        return Record()

    # The turn's own id, not the file it happens to sit in: a copied
    # conversation must not read as fresh spend.
    identity = (
        f"antigravity|{response_id}"
        if response_id
        else f"antigravity|{conversation}|{index}"
    )
    model = string(chat_model, 19) or "unknown"

    counters = [
        token_count(usage, 2),
        token_count(usage, 3),
        token_count(usage, 4),
        token_count(usage, 5),
    ]
    input_tokens, output, cache_write, cache_read = counters
    return Record(
        entry=make_entry(
            identity,
            date,
            # The prefix short-circuits the rate lookup: Antigravity is a
            # subscription and bills no per-token amount.
            f"antigravity/{model}",
            input=input_tokens or 0,
            output=output or 0,
            cache_write=cache_write or 0,
            cache_read=cache_read or 0,
        ),
        discarded_counters=sum(1 for c in counters if c is None),
    )


def parse_conversation(path: Path) -> list[Entry]:
    rows = query(path, _SQL)
    # A missing gen_metadata table means this database is not a conversation
    # store, which is a permanent property of the file; a failed read is this
    # moment failing. Neither yields entries, and the blob cache re-reads when
    # the signature moves either way.
    if not rows:
        return []
    conversation = path.stem
    # Used when a record carries no created_at of its own.
    store_date = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    out: list[Entry] = []
    for index, blob in rows:
        if isinstance(blob, str):
            blob = blob.encode("utf-8", "replace")
        if not isinstance(blob, (bytes, bytearray)) or not blob:
            continue
        record = parse_generation_metadata(
            bytes(blob),
            conversation,
            index if isinstance(index, int) else 0,
            fallback_date=lambda _r, _e: store_date,
        )
        if record.entry is not None:
            out.append(record.entry)
    return out


def roots(home: Path | None = None, env: Mapping[str, str] | None = None) -> list[Path]:
    """Conversation directories across the Antigravity editions (2.0/Core, CLI, IDE).

    All three are dotfile paths under `~/.gemini`, so they are unchanged on Linux.
    """
    env = os.environ if env is None else env
    configured = (env.get("ANTIGRAVITY_HOME") or "").strip()
    base = Path(configured).expanduser() if configured else (home or Path.home()) / ".gemini"
    return [
        base / "antigravity" / "conversations",
        base / "antigravity-cli" / "conversations",
        base / "antigravity-ide" / "conversations",
    ]


class AntigravityProvider(SQLiteProvider):
    """Antigravity local usage."""

    id = "antigravity"
    display_name = "Antigravity"
    # Subscription-billed; it states no per-token amount.
    PARSER_VERSION = 1

    def curated_roots(self) -> list[Path]:
        return roots(self._home)

    def databases(self, root: Path) -> list[Path]:
        if root.is_file():
            return [root]
        try:
            return sorted(p for p in root.iterdir() if p.suffix == ".db" and p.is_file())
        except OSError:
            return []

    def files(self, root: Path) -> Iterator[Path]:
        yield from self.databases(root)

    def parse_file(self, path: Path) -> list[Entry]:
        return parse_conversation(path)
