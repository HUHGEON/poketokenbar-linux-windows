"""Kiro CLI parsing — ports KiroUsageTests.swift.

Kiro persists no token count, so every number here is a bytes/4 estimate. The
fixture shapes come from the Swift suite, which took them from tokscale's
contract tests against real on-disk sessions — inventing a third envelope would
pass here and miss every live session.
"""

import json
import sqlite3

from poketokenbar.providers import kiro

MODEL = "claude-sonnet-4.5"


# MARK: SQLite fixtures


def turn(timestamp_ms, model=MODEL, user_text="", assistant_text="", response_bytes=0):
    metadata = {
        "request_start_timestamp_ms": timestamp_ms,
        "response_size": response_bytes,
        "time_between_chunks": [],
        "tool_use_ids_and_names": [],
    }
    if model is not None:
        metadata["model_id"] = model
    return {
        "user": {"content": user_text},
        "assistant": {"content": assistant_text},
        "request_metadata": metadata,
    }


def turn_without_timestamp(model=MODEL, user_text="", assistant_text=""):
    metadata = {"response_size": 0}
    if model is not None:
        metadata["model_id"] = model
    return {
        "user": {"content": user_text},
        "assistant": {"content": assistant_text},
        "request_metadata": metadata,
    }


def conversation(id, turns, latest_summary=None):
    return json.dumps(
        {"conversation_id": id, "history": turns, "latest_summary": latest_summary}
    )


def seed_v2(path, conversations):
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS conversations_v2 ("
            " conversation_id TEXT PRIMARY KEY, key TEXT,"
            " created_at INTEGER, updated_at INTEGER, value TEXT)"
        )
        for conversation_id, value in conversations:
            connection.execute(
                "INSERT INTO conversations_v2"
                " (conversation_id, key, created_at, updated_at, value)"
                " VALUES (?,?,0,0,?)",
                (conversation_id, "/home/dev/project", value),
            )
        connection.commit()
    finally:
        connection.close()
    return path


def seed_v1(path, rows):
    connection = sqlite3.connect(path)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS conversations (key TEXT, value TEXT)")
        connection.executemany("INSERT INTO conversations VALUES (?,?)", rows)
        connection.commit()
    finally:
        connection.close()
    return path


# MARK: SQLite estimation


def test_first_turn_input_is_the_user_message_byte_estimate(tmp_path):
    """No prior history to resend yet, so the prompt is the whole input."""
    path = seed_v2(
        tmp_path / "data.sqlite3",
        [("conv-1", conversation("conv-1", [turn(1_780_000_000_000, user_text="u" * 400, response_bytes=200)]))],
    )
    entries = kiro.parse_database(path)
    assert len(entries) == 1
    e = entries[0]
    assert e.input == 100, "400 bytes / 4"
    assert e.output == 50, "200 bytes / 4"
    assert e.cache_read == 0
    assert e.cache_write == 0
    assert e.model == MODEL
    assert e.id == "kiro|conv-1|1780000000000"


def test_later_turn_input_includes_the_accumulated_history(tmp_path):
    """Kiro has no server-side session — every turn resends the whole conversation.

    Counting only the newly typed message would undercount a long conversation
    by orders of magnitude.
    """
    path = seed_v2(
        tmp_path / "data.sqlite3",
        [
            (
                "conv-1",
                conversation(
                    "conv-1",
                    [
                        turn(1_780_000_000_000, user_text="u" * 400, assistant_text="a" * 800, response_bytes=800),
                        turn(1_780_000_100_000, user_text="u" * 40, response_bytes=40),
                    ],
                ),
            )
        ],
    )
    entries = {e.id: e for e in kiro.parse_database(path)}
    second = entries["kiro|conv-1|1780000100000"]
    assert second.input == (400 + 800 + 40) // 4


def test_skipped_turns_still_contribute_to_later_history(tmp_path):
    """A turn with no timestamp gets no entry, but its text is still resent."""
    path = seed_v2(
        tmp_path / "data.sqlite3",
        [
            (
                "conv-1",
                conversation(
                    "conv-1",
                    [
                        turn_without_timestamp(user_text="u" * 400, assistant_text="a" * 400),
                        turn(1_780_000_000_000, user_text="u" * 40, response_bytes=40),
                    ],
                ),
            )
        ],
    )
    entries = kiro.parse_database(path)
    assert len(entries) == 1
    assert entries[0].input == (400 + 400 + 40) // 4


def test_latest_summary_seeds_the_history_after_compaction(tmp_path):
    """It stands in for turns compaction removed, and is still resent."""
    path = seed_v2(
        tmp_path / "data.sqlite3",
        [
            (
                "conv-1",
                conversation(
                    "conv-1",
                    [turn(1_780_000_000_000, user_text="u" * 40, response_bytes=40)],
                    latest_summary="s" * 800,
                ),
            )
        ],
    )
    assert kiro.parse_database(path)[0].input == (800 + 40) // 4


def test_images_are_excluded_from_the_estimate(tmp_path):
    """A base64 blob would dwarf the text it sits beside."""
    heavy = {
        "user": {"content": "u" * 40, "images": ["x" * 100_000]},
        "assistant": {"content": ""},
        "request_metadata": {
            "request_start_timestamp_ms": 1_780_000_000_000,
            "response_size": 0,
            "model_id": MODEL,
        },
    }
    path = seed_v2(tmp_path / "data.sqlite3", [("c", conversation("c", [heavy]))])
    assert kiro.parse_database(path)[0].input == 10


def test_the_2_0_1_generation_is_read_too(tmp_path):
    """2.0.1+ keeps one row per working directory, with the id inside the JSON."""
    path = seed_v1(
        tmp_path / "data.sqlite3",
        [("/home/dev/project", conversation("conv-v1", [turn(1_780_000_000_000, user_text="u" * 400, response_bytes=200)]))],
    )
    entries = kiro.parse_database(path)
    assert len(entries) == 1
    assert entries[0].id == "kiro|conv-v1|1780000000000"


def test_a_store_with_neither_table_is_silent(tmp_path):
    path = tmp_path / "data.sqlite3"
    sqlite3.connect(path).close()
    assert kiro.parse_database(path) == []


# MARK: CLI JSONL (2.20+)


def seed_cli_session(root, session_id, turns, model="claude-sonnet-4-5"):
    cli = root / "sessions" / "cli"
    cli.mkdir(parents=True, exist_ok=True)
    lines = []
    for index, (prompt, assistant, timestamp) in enumerate(turns):
        lines.append(
            json.dumps(
                {
                    "version": "v1",
                    "kind": "Prompt",
                    "data": {
                        "message_id": f"prompt-{index + 1}",
                        "content": [{"kind": "text", "data": prompt}],
                        "meta": {"timestamp": timestamp},
                    },
                }
            )
        )
        lines.append(
            json.dumps(
                {
                    "version": "v1",
                    "kind": "AssistantMessage",
                    "data": {
                        "message_id": f"assistant-{index + 1}",
                        "content": [{"kind": "text", "data": assistant}],
                    },
                }
            )
        )
    (cli / f"{session_id}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (cli / f"{session_id}.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "cwd": "/tmp/project",
                "session_state": {"rts_model_state": {"model_info": {"model_id": model}}},
            }
        ),
        encoding="utf-8",
    )
    return cli / f"{session_id}.jsonl"


def test_cli_jsonl_session_is_read_from_writer_shaped_events(tmp_path):
    path = seed_cli_session(
        tmp_path, "session-1", [("hello world", "response text", 1_770_983_426.420942)]
    )
    entries = kiro.parse_cli_jsonl(path)
    assert len(entries) == 1
    e = entries[0]
    assert e.model == "claude-sonnet-4-5"
    assert e.input == 11 // 4, "utf8 bytes/4, the same estimator as the SQLite path"
    assert e.output == 13 // 4
    assert e.id == "kiro|cli|session-1|1770983426420"
    assert e.explicit_cost is None


def test_cli_jsonl_later_turn_accumulates_history(tmp_path):
    path = seed_cli_session(
        tmp_path,
        "session-2",
        [
            ("u" * 400, "a" * 800, 1_770_983_426.0),
            ("u" * 40, "a" * 40, 1_770_983_526.0),
        ],
    )
    entries = {e.id: e for e in kiro.parse_cli_jsonl(path)}
    second = entries["kiro|cli|session-2|1770983526000"]
    assert second.input == (400 + 800 + 40) // 4
    assert second.output == 40 // 4


def test_cli_clear_resets_the_running_history(tmp_path):
    """`/clear` starts a fresh conversation; the old text is no longer resent."""
    cli = tmp_path / "sessions" / "cli"
    cli.mkdir(parents=True)
    lines = [
        json.dumps({"kind": "Prompt", "data": {"content": "u" * 400, "meta": {"timestamp": 1_770_983_426.0}}}),
        json.dumps({"kind": "AssistantMessage", "data": {"content": "a" * 800}}),
        json.dumps({"kind": "Clear", "data": {}}),
        json.dumps({"kind": "Prompt", "data": {"content": "u" * 40, "meta": {"timestamp": 1_770_983_526.0}}}),
    ]
    path = cli / "s.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    entries = {e.id: e for e in kiro.parse_cli_jsonl(path)}
    assert entries["kiro|cli|s|1770983526000"].input == 40 // 4


# MARK: v3 / IDE JSONL


def seed_v3_session(root, workspace, session_id, model, prompt, assistant, timestamp, credits=1.5):
    directory = root / "sessions" / workspace / session_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "session.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0.0",
                "id": session_id,
                "modelId": model,
                "createdAt": timestamp,
                "lastModifiedAt": timestamp,
            }
        ),
        encoding="utf-8",
    )
    lines = [
        json.dumps({"timestamp": timestamp, "payload": {"type": "user", "content": prompt}}),
        json.dumps({"timestamp": timestamp, "payload": {"type": "assistant", "content": assistant}}),
        json.dumps({"payload": {"type": "usage_summary", "promptTurnSummaries": [{"usage": credits}]}}),
        json.dumps({"payload": {"type": "turn_end"}, "timestamp": timestamp}),
    ]
    path = directory / "messages.jsonl"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_v3_messages_jsonl_session_is_read(tmp_path):
    path = seed_v3_session(
        tmp_path, "ws", "sess-1", "claude-sonnet-4-5", "u" * 400, "a" * 800,
        "2026-02-13T12:00:00Z",
    )
    entries = kiro.parse_v3_jsonl(path)
    assert len(entries) == 1
    e = entries[0]
    assert e.model == "claude-sonnet-4-5"
    assert e.input == 100
    assert e.output == 200
    assert e.id == "kiro|v3|sess-1|0"
    assert e.explicit_cost is None, "usage_summary credits are not API dollars"


def test_v3_flat_role_envelope_is_read(tmp_path):
    """The older flat `{role, content}` shape coexists with the structured one."""
    directory = tmp_path / "sessions" / "ws" / "sess-2"
    directory.mkdir(parents=True)
    (directory / "session.json").write_text(
        json.dumps({"id": "sess-2", "modelId": "m", "createdAt": "2026-02-13T12:00:00Z"}),
        encoding="utf-8",
    )
    path = directory / "messages.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"timestamp": "2026-02-13T12:00:00Z", "role": "user", "content": "u" * 400}),
                json.dumps({"timestamp": "2026-02-13T12:00:01Z", "role": "assistant", "content": "a" * 800}),
            ]
        ),
        encoding="utf-8",
    )
    entries = kiro.parse_v3_jsonl(path)
    assert len(entries) == 1
    assert entries[0].input == 100
    assert entries[0].output == 200


# MARK: layout and roots


def test_only_layout_shaped_jsonl_files_are_scanned(tmp_path):
    """Matching any .jsonl would sweep in unrelated files."""
    assert kiro.is_session_file(tmp_path / "sessions" / "cli" / "a.jsonl")
    assert kiro.is_session_file(tmp_path / "sessions" / "ws" / "s" / "messages.jsonl")
    assert not kiro.is_session_file(tmp_path / "sessions" / "other" / "a.jsonl")
    assert not kiro.is_session_file(tmp_path / "notes.json")


def test_a_kiro_home_with_only_jsonl_still_yields_usage(tmp_path):
    """The reader used to open data.sqlite3 only, so a JSONL-only install read 0."""
    seed_cli_session(tmp_path / ".kiro", "session-1", [("u" * 400, "a" * 200, 1_770_983_426.0)])
    entries = kiro.KiroProvider(home=tmp_path).scan_entries()
    assert len(entries) == 1
    assert entries[0].input == 100
    assert entries[0].output == 50
    assert entries[0].explicit_cost is None


def test_sqlite_root_searches_both_places_the_database_is_known_to_live(tmp_path):
    """Kiro's session-management page says only "SQLite database in `~/.kiro/`",
    while its macOS install puts one at
    `~/Library/Application Support/kiro-cli/data.sqlite3`. Neither statement
    covers all three platforms, so both are searched rather than one being
    guessed — an empty root costs a directory check, and picking the wrong one
    reads as "this provider has no usage"."""
    from pathlib import Path

    assert kiro.sqlite_roots(home=tmp_path, env={}, system="linux") == [
        tmp_path / ".local" / "share" / "kiro-cli", tmp_path / ".kiro",
    ]
    assert kiro.sqlite_roots(home=tmp_path, env={}, system="darwin") == [
        tmp_path / "Library" / "Application Support" / "kiro-cli", tmp_path / ".kiro",
    ]
    assert kiro.sqlite_roots(
        home=tmp_path, env={"APPDATA": "C:/Roaming"}, system="win32"
    ) == [Path("C:/Roaming/kiro-cli"), tmp_path / ".kiro"]


def test_the_dotfile_root_follows_kiro_home(tmp_path):
    moved = tmp_path / "elsewhere"
    roots = kiro.sqlite_roots(home=tmp_path, env={"KIRO_HOME": str(moved)}, system="linux")
    assert moved in roots
    assert kiro.session_roots(home=tmp_path, env={"KIRO_HOME": str(moved)}) == [
        moved / "sessions"
    ]


def test_sqlite_root_overrides(tmp_path):
    elsewhere = tmp_path / "xdg"
    assert kiro.sqlite_roots(
        home=tmp_path, env={"XDG_DATA_HOME": str(elsewhere)}, system="linux"
    ) == [elsewhere / "kiro-cli", tmp_path / ".kiro"]
    custom = tmp_path / "custom"
    for system in ("linux", "darwin", "win32"):
        assert kiro.sqlite_roots(
            home=tmp_path, env={"KIRO_CLI_HOME": str(custom)}, system=system
        ) == [custom]


def test_session_root_is_a_dotfile_and_unchanged(tmp_path):
    assert kiro.session_roots(home=tmp_path, env={}) == [tmp_path / ".kiro" / "sessions"]
    custom = tmp_path / "custom"
    assert kiro.session_roots(home=tmp_path, env={"KIRO_HOME": str(custom)}) == [
        custom / "sessions"
    ]


def test_kiro_turns_are_unpriced(tmp_path):
    """Tokens are a byte estimate and usage_summary credits are not dollars."""
    path = seed_v2(
        tmp_path / "data.sqlite3",
        [("conv-1", conversation("conv-1", [turn(1_780_000_000_000, user_text="u" * 400,
                                                 response_bytes=200)]))],
    )
    entries = kiro.parse_database(path)
    assert all(e.cost_unavailable for e in entries)
    daily = kiro.KiroProvider().aggregate_daily(entries[0].local_day, entries)
    assert daily.cost_coverage.only_unknown


def test_provider_identity():
    provider = kiro.KiroProvider()
    assert provider.id == "kiro"
    assert provider.display_name == "Kiro CLI"
