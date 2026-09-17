"""OpenCode and Hermes parsing — ports LocalAdditionalUsageTests.swift.

Both are SQLite-backed, and the Swift suite carries their real schemas, so the
readers can be verified without either tool installed.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from poketokenbar.providers import hermes, opencode


def execute(path, sql):
    connection = sqlite3.connect(path)
    try:
        connection.executescript(sql)
        connection.commit()
    finally:
        connection.close()
    return path


# MARK: OpenCode


OPENCODE_PAYLOAD = {
    "id": "msg-1",
    "sessionID": "session-1",
    "providerID": "anthropic",
    "modelID": "claude-sonnet-4-20250514",
    "time": {"created": 1767312000000},
    "tokens": {"input": 100, "output": 50, "total": 250, "cache": {"read": 10, "write": 20}},
    "cost": 0.25,
}


def test_opencode_reads_sqlite_and_preserves_reported_total_and_cost(tmp_path):
    database = tmp_path / "opencode.db"
    execute(
        database,
        """
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            data TEXT NOT NULL
        );
        INSERT INTO message VALUES (
            'msg-1', 'session-1', 1767312000000, '%s'
        );
        """
        % json.dumps(OPENCODE_PAYLOAD).replace("'", "''"),
    )
    entries = opencode.parse_database(database)
    assert len(entries) == 1
    e = entries[0]
    assert e.input == 100
    assert e.output == 120, "unclassified total tokens are retained as output"
    assert e.cache_write == 20
    assert e.cache_read == 10
    assert e.total == 250
    assert e.explicit_cost == 0.25


def test_opencode_falls_back_to_a_database_without_time_created(tmp_path):
    """Older stores have no such column; the query fails and the second form runs."""
    payload = dict(
        OPENCODE_PAYLOAD,
        id="legacy-1",
        providerID="openai",
        modelID="gpt-5",
        tokens={"input": 7, "output": 3, "cache": {"read": 2, "write": 1}},
        cost=0,
    )
    database = tmp_path / "opencode.db"
    execute(
        database,
        """
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, data TEXT NOT NULL);
        INSERT INTO message VALUES ('legacy-1', 'session-1', '%s');
        """
        % json.dumps(payload).replace("'", "''"),
    )
    entries = opencode.parse_database(database)
    assert len(entries) == 1
    assert entries[0].total == 13


def test_opencode_zero_cost_is_a_recorded_zero(tmp_path):
    """0 is a free turn, not a missing figure (upstream 69ff39b)."""
    payload = dict(OPENCODE_PAYLOAD, cost=0)
    entry = opencode.parse_message(payload, "x")
    assert entry.explicit_cost == 0.0
    assert not entry.cost_is_estimate


@pytest.fixture
def opencode_dir(tmp_path, monkeypatch):
    """A store the provider is pointed at, on any platform.

    Computing the default instead let the fixture and the provider disagree:
    one asked with an empty environment, the other with the real one.
    """
    root = tmp_path / "opencode-data"
    monkeypatch.setenv("OPENCODE_DATA_DIR", str(root))
    return root


def test_opencode_legacy_message_files_are_read(tmp_path, opencode_dir):
    root = opencode_dir / "storage" / "message"
    root.mkdir(parents=True)
    (root / "msg-1.json").write_text(json.dumps(OPENCODE_PAYLOAD), encoding="utf-8")

    entries = opencode.OpenCodeProvider(home=tmp_path).scan_entries()
    assert len(entries) == 1
    assert entries[0].total == 250


def test_opencode_payload_without_provider_is_not_a_billed_message():
    payload = {k: v for k, v in OPENCODE_PAYLOAD.items() if k != "providerID"}
    assert opencode.parse_message(payload, "x") is None


def test_opencode_named_channel_database_is_used_when_standard_is_absent(
        tmp_path, opencode_dir):
    root = opencode_dir
    root.mkdir(parents=True)
    execute(
        root / "opencode-nightly.db",
        """
        CREATE TABLE message (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, data TEXT NOT NULL);
        INSERT INTO message VALUES ('m', 's', '%s');
        """
        % json.dumps(OPENCODE_PAYLOAD).replace("'", "''"),
    )
    entries = opencode.OpenCodeProvider(home=tmp_path).scan_entries()
    assert len(entries) == 1


@pytest.mark.parametrize(
    "name", ["opencode-.db", "opencode-../evil.db", "opencode-a b.db", "notopencode.db"]
)
def test_opencode_rejects_channel_names_outside_the_identifier_set(name):
    assert not opencode._is_channel_database(name)


def test_opencode_roots_follow_the_platform(tmp_path):
    """`system` is pinned, not read: otherwise this asserts whatever the machine
    running the suite happens to be, and passes there while failing elsewhere."""
    assert opencode.roots(home=tmp_path, env={}, system="linux") == [
        tmp_path / ".local" / "share" / "opencode"
    ]
    assert opencode.roots(home=tmp_path, env={}, system="darwin") == [
        tmp_path / "Library" / "Application Support" / "opencode"
    ]
    assert opencode.roots(
        home=tmp_path, env={"APPDATA": "C:/Roaming"}, system="win32"
    ) == [Path("C:/Roaming/opencode")]


def test_opencode_data_dir_overrides_every_platform(tmp_path):
    custom = tmp_path / "elsewhere"
    for system in ("linux", "darwin", "win32"):
        assert opencode.roots(
            home=tmp_path, env={"OPENCODE_DATA_DIR": str(custom)}, system=system
        ) == [custom]


# MARK: Hermes


HERMES_SCHEMA = """
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    model TEXT,
    billing_provider TEXT,
    started_at REAL NOT NULL,
    message_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL,
    actual_cost_usd REAL
);
"""


def test_hermes_reads_session_tokens_reasoning_and_actual_cost(tmp_path):
    database = tmp_path / "state.db"
    execute(
        database,
        HERMES_SCHEMA
        + """
        INSERT INTO sessions VALUES (
            'session-1', 'claude-sonnet-4-20250514', 'anthropic', 1767312000, 42,
            100, 50, 10, 20, 5, 0.12, 0.34
        );
        """,
    )
    entries = hermes.parse_database(database)
    assert len(entries) == 1
    e = entries[0]
    assert e.input == 100
    assert e.output == 55, "Hermes bills reasoning on top of output, not inside it"
    assert e.cache_write == 20
    assert e.cache_read == 10
    assert e.total == 185
    assert e.explicit_cost == 0.34, "the actual charge wins over the estimate"


def test_hermes_falls_back_to_the_estimate_only_when_no_actual_cost_was_recorded(tmp_path):
    database = tmp_path / "state.db"
    execute(
        database,
        HERMES_SCHEMA
        + """
        INSERT INTO sessions VALUES ('none', 'm', 'p', 1767312000, 1, 10, 5, 0, 0, 0, 0.12, NULL);
        INSERT INTO sessions VALUES ('zero', 'm', 'p', 1767312000, 1, 10, 5, 0, 0, 0, 0.12, 0);
        INSERT INTO sessions VALUES ('neither', 'm', 'p', 1767312000, 1, 10, 5, 0, 0, 0, NULL, NULL);
        """,
    )
    by_id = {e.id: e for e in hermes.parse_database(database)}
    estimated = by_id["hermes|none"]
    assert (estimated.explicit_cost, estimated.cost_is_estimate) == (0.12, True)
    zero = by_id["hermes|zero"]
    assert (zero.explicit_cost, zero.cost_is_estimate) == (0.0, False), "a recorded $0 counts"
    neither = by_id["hermes|neither"]
    assert neither.explicit_cost is None and neither.cost_unavailable


def test_hermes_accepts_a_millisecond_started_at(tmp_path):
    database = tmp_path / "state.db"
    execute(
        database,
        HERMES_SCHEMA
        + """
        INSERT INTO sessions VALUES (
            'session-ms', 'gpt-5', 'openai', 1767312000000, 1, 10, 5, 0, 0, 0, 0, 0
        );
        """,
    )
    entries = hermes.parse_database(database)
    assert len(entries) == 1
    assert entries[0].total == 15
    assert abs(entries[0].date.timestamp() - 1767312000) < 0.001


def test_hermes_rows_without_a_model_are_skipped(tmp_path):
    """A session with no model never reached a provider."""
    database = tmp_path / "state.db"
    execute(
        database,
        HERMES_SCHEMA
        + """
        INSERT INTO sessions VALUES ('a', NULL, 'p', 1767312000, 1, 10, 5, 0, 0, 0, 0, 0);
        INSERT INTO sessions VALUES ('b', '   ', 'p', 1767312000, 1, 10, 5, 0, 0, 0, 0, 0);
        """,
    )
    assert hermes.parse_database(database) == []


def test_hermes_provider_reads_the_state_database_under_home(tmp_path):
    root = tmp_path / ".hermes"
    root.mkdir()
    execute(
        root / "state.db",
        HERMES_SCHEMA
        + """
        INSERT INTO sessions VALUES ('s', 'm', 'p', 1767312000, 1, 10, 5, 0, 0, 0, 0, 0);
        """,
    )
    assert len(hermes.HermesProvider(home=tmp_path).scan_entries()) == 1


def test_hermes_roots_default_and_override(tmp_path):
    assert hermes.roots(home=tmp_path, env={}) == [tmp_path / ".hermes"]
    custom = tmp_path / "elsewhere"
    assert hermes.roots(home=tmp_path, env={"HERMES_HOME": str(custom)}) == [custom]


# MARK: shared SQLite behaviour


def test_wal_writes_invalidate_the_cached_blob(tmp_path):
    """A WAL store takes writes without the main file's stat moving.

    Keying the blob cache on the database alone would keep serving the old
    parse, so the usage would simply stop updating until something else
    happened to touch the file.
    """
    provider = hermes.HermesProvider()
    database = tmp_path / "state.db"
    execute(database, HERMES_SCHEMA)
    before = provider.file_signature(database)

    wal = tmp_path / "state.db-wal"
    wal.write_bytes(b"x" * 32)
    after = provider.file_signature(database)
    assert after != before


def test_shm_is_excluded_from_the_signature(tmp_path):
    """A read-only connection writes read marks into -shm.

    Including it would let this reader invalidate the blob it had just written,
    on every sweep, forever.
    """
    provider = hermes.HermesProvider()
    database = tmp_path / "state.db"
    execute(database, HERMES_SCHEMA)
    before = provider.file_signature(database)

    (tmp_path / "state.db-shm").write_bytes(b"y" * 64)
    assert provider.file_signature(database) == before
