"""Antigravity parsing — ports AntigravityUsageTests.swift.

The fixtures encode the field numbers the Swift suite read out of the
Antigravity CLI's own embedded FileDescriptorProto pool — ModelUsageStats
2/3/4/5/11, ChatStartMetadata.created_at 4, ChatModelMetadata.response_model 19
— and that mapping was checked against a live store before it was written down.
They are the contract, not a guess at the shape.
"""

import sqlite3

from poketokenbar.providers import antigravity as ag

# MARK: a minimal protobuf encoder, mirroring the reader


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        out.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(out)


def varint_field(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def bytes_field(field: int, payload: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(payload)) + payload


def string_field(field: int, text: str) -> bytes:
    return bytes_field(field, text.encode("utf-8"))


def make_record(
    response_id="r1",
    model="gemini-3.6-flash",
    created_at_seconds=1772618400,  # 2026-03-04T10:00:00Z
    input=0,
    output=0,
    cache_write=0,
    cache_read=0,
    execution_id=None,
    nanos=None,
) -> bytes:
    usage = b""
    if input:
        usage += varint_field(2, input)
    if output:
        usage += varint_field(3, output)
    if cache_write:
        usage += varint_field(4, cache_write)
    if cache_read:
        usage += varint_field(5, cache_read)
    if response_id is not None:
        usage += string_field(11, response_id)

    chat_model = bytes_field(4, usage)
    if created_at_seconds is not None:
        stamp = varint_field(1, created_at_seconds)
        if nanos is not None:
            stamp += varint_field(2, nanos)
        chat_model += bytes_field(9, bytes_field(4, stamp))
    chat_model += string_field(19, model)

    blob = bytes_field(1, chat_model)
    if execution_id is not None:
        blob += string_field(4, execution_id)
    return blob


def write_conversation(root, name, records):
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{name}.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE gen_metadata (idx INTEGER PRIMARY KEY, data BLOB)")
        connection.executemany(
            "INSERT INTO gen_metadata VALUES (?,?)",
            [(i, r) for i, r in enumerate(records)],
        )
        connection.commit()
    finally:
        connection.close()
    return path


def conversations_root(tmp_path):
    return tmp_path / ".gemini" / "antigravity" / "conversations"


# MARK: token mapping


def test_token_mapping_keeps_the_writer_semantics(tmp_path):
    """input_tokens is already net of the cache read, and output already
    contains the thinking half — neither may be adjusted the way the Gemini CLI
    parser adjusts its own fields."""
    path = write_conversation(
        conversations_root(tmp_path),
        "c1",
        [make_record(input=4667, output=462, cache_read=52968)],
    )
    entries = ag.parse_conversation(path)
    assert len(entries) == 1
    e = entries[0]
    assert e.input == 4667
    assert e.cache_read == 52968
    assert e.output == 462
    assert e.cache_write == 0
    assert e.model == "antigravity/gemini-3.6-flash"


def test_total_is_the_sum_of_the_counters(tmp_path):
    """The schema has no total field, so the total is what the counters add to."""
    path = write_conversation(
        conversations_root(tmp_path), "c1", [make_record(input=100, output=20, cache_read=300)]
    )
    assert ag.parse_conversation(path)[0].total == 420


def test_row_with_no_tokens_produces_no_entry(tmp_path):
    path = write_conversation(conversations_root(tmp_path), "c1", [make_record()])
    assert ag.parse_conversation(path) == []


def test_absurd_counters_are_discarded_not_clamped(tmp_path):
    """Clamping would keep a number that then dominates every aggregate it
    reaches — today's total, the burn tier, the companion. Discarding loses one
    counter and leaves the rest of the record intact."""
    path = write_conversation(
        conversations_root(tmp_path),
        "c1",
        [make_record(input=10**12, output=20, cache_read=300)],
    )
    e = ag.parse_conversation(path)[0]
    assert e.input == 0, "the sentinel counter is dropped"
    assert e.output == 20, "the rest of the record survives"
    assert e.cache_read == 300


def test_counter_exactly_at_the_ceiling_is_kept(tmp_path):
    path = write_conversation(
        conversations_root(tmp_path), "c1", [make_record(input=ag.TOKEN_CEILING)]
    )
    assert ag.parse_conversation(path)[0].input == ag.TOKEN_CEILING


# MARK: identity


def test_response_id_deduplicates_across_conversations(tmp_path):
    """The turn's own id, so the same call copied into a second store stays one
    charge rather than becoming two."""
    root = conversations_root(tmp_path)
    shared = make_record(response_id="same-call", input=100, output=20, cache_read=300)
    write_conversation(root, "c1", [shared])
    write_conversation(root, "c2", [shared])

    entries = ag.AntigravityProvider(home=tmp_path).scan_entries()
    assert len(entries) == 1
    assert entries[0].id == "antigravity|same-call"


def test_record_without_a_response_id_falls_back_to_file_and_index(tmp_path):
    path = write_conversation(
        conversations_root(tmp_path),
        "c1",
        [make_record(response_id=None, input=100, output=20)],
    )
    assert ag.parse_conversation(path)[0].id == "antigravity|c1|0"


# MARK: timestamps


def test_created_at_is_read_from_the_protobuf(tmp_path):
    path = write_conversation(
        conversations_root(tmp_path),
        "c1",
        [make_record(created_at_seconds=1772618400, input=100)],
    )
    assert ag.parse_conversation(path)[0].date.timestamp() == 1772618400


def test_missing_created_at_falls_back_to_the_file_mtime(tmp_path):
    """Antigravity 2.0 / IDE sessions may omit it; dropping the row would lose
    tokens that were really spent."""
    path = write_conversation(
        conversations_root(tmp_path),
        "c_modern",
        [make_record(response_id="r_modern_1", model="gemini-3.7-flash",
                     created_at_seconds=None, input=500, output=100, cache_read=2000)],
    )
    entries = ag.parse_conversation(path)
    assert len(entries) == 1
    e = entries[0]
    assert e.id == "antigravity|r_modern_1"
    assert e.total == 2600
    assert e.model == "antigravity/gemini-3.7-flash"
    assert abs(e.date.timestamp() - path.stat().st_mtime) < 1


def test_an_out_of_range_created_at_drops_the_record(tmp_path):
    """A stamp outside the plausible window means the bytes are not what we took
    them for — falling back to the file date would launder that into real usage."""
    path = write_conversation(
        conversations_root(tmp_path), "c1", [make_record(created_at_seconds=1, input=100)]
    )
    assert ag.parse_conversation(path) == []


# MARK: store handling


def test_a_database_without_gen_metadata_is_not_a_conversation(tmp_path):
    root = conversations_root(tmp_path)
    root.mkdir(parents=True)
    path = root / "other.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE something_else (x INTEGER)")
    connection.commit()
    connection.close()
    assert ag.parse_conversation(path) == []


def test_all_three_editions_are_scanned(tmp_path):
    for edition in ("antigravity", "antigravity-cli", "antigravity-ide"):
        root = tmp_path / ".gemini" / edition / "conversations"
        write_conversation(root, edition, [make_record(response_id=edition, input=100)])
    entries = ag.AntigravityProvider(home=tmp_path).scan_entries()
    assert len(entries) == 3


def test_roots_are_dotfile_paths_and_unchanged_on_linux(tmp_path):
    assert ag.roots(home=tmp_path, env={}) == [
        tmp_path / ".gemini" / "antigravity" / "conversations",
        tmp_path / ".gemini" / "antigravity-cli" / "conversations",
        tmp_path / ".gemini" / "antigravity-ide" / "conversations",
    ]


def test_antigravity_usage_is_unpriced(tmp_path):
    """Subscription-billed, with no cost field. The `antigravity/` prefix keeps
    its model names off the price table, which matters because it calls models
    like claude-sonnet-4-6, so the day is unavailable rather than a guess."""
    from poketokenbar import pricing

    write_conversation(
        conversations_root(tmp_path), "c1", [make_record(model="claude-sonnet-4-6", input=1_000_000)]
    )
    provider = ag.AntigravityProvider(home=tmp_path)
    entries = provider.scan_entries()
    assert entries[0].model == "antigravity/claude-sonnet-4-6"
    assert pricing.estimated_cost(entries[0].model, 1, 1, 0, 0) is None
    daily = provider.aggregate_daily(entries[0].local_day, entries)
    assert daily.total_cost == 0
    assert daily.cost_coverage.only_unknown


# MARK: the wire reader itself


def test_walk_stops_on_a_group_tag():
    """Groups were removed from the language, so meeting one means these bytes
    are not the message we took them for."""
    assert ag.varint(_varint(1 << 3 | 3) + b"\x01", 1) is None


def test_truncated_length_delimited_field_is_refused():
    payload = _varint((1 << 3) | 2) + _varint(50) + b"short"
    assert ag.message(payload, 1) is None


def test_absent_field_reads_as_zero_not_missing():
    """cache_write_tokens is declared and never written — an absent field is a
    legitimate zero, distinct from a value that cannot be a count."""
    assert ag.token_count(b"", 4) == 0
    assert ag.token_count(varint_field(4, 10**12), 4) is None


def test_provider_identity():
    provider = ag.AntigravityProvider()
    assert provider.id == "antigravity"
    assert provider.display_name == "Antigravity"
