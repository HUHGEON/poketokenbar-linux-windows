"""Copilot CLI parsing — ports CopilotUsageTests.swift.

The schema below is the Swift suite's, so the cached-prompt accounting and the
two timestamp shapes are verified without a Copilot install.
"""

import sqlite3

from poketokenbar.providers import copilot

SCHEMA = """
CREATE TABLE assistant_usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    turn_index INTEGER,
    agent_id TEXT,
    parent_tool_call_id TEXT,
    model TEXT NOT NULL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    reasoning_tokens INTEGER,
    total_nano_aiu INTEGER,
    request_multiplier REAL,
    duration_ms INTEGER,
    time_to_first_token_ms INTEGER,
    inter_token_latency_ms INTEGER,
    initiator TEXT,
    api_endpoint TEXT,
    reasoning_effort TEXT,
    finish_reason TEXT,
    content_filter_triggered INTEGER,
    token_details_json TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
"""


def seed(path, rows):
    connection = sqlite3.connect(path)
    try:
        connection.executescript(SCHEMA)
        for row in rows:
            connection.execute(
                "INSERT INTO assistant_usage_events"
                " (id, session_id, model, input_tokens, output_tokens,"
                "  cache_read_tokens, cache_write_tokens, reasoning_tokens, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    row["id"],
                    "s",
                    row["model"],
                    row["input"],
                    row["output"],
                    row["cache_read"],
                    row["cache_write"],
                    row.get("reasoning", 0),
                    row["created_at"],
                ),
            )
        connection.commit()
    finally:
        connection.close()
    return path


def row(id, model="claude-opus-5", input=0, output=0, cache_read=0, cache_write=0,
        reasoning=0, created_at="2026-01-04T10:00:00.000Z"):
    return {
        "id": id, "model": model, "input": input, "output": output,
        "cache_read": cache_read, "cache_write": cache_write,
        "reasoning": reasoning, "created_at": created_at,
    }


def database(tmp_path):
    return tmp_path / "session-store.db"


# MARK: token accounting


def test_cached_prompt_tokens_are_not_counted_twice(tmp_path):
    """input_tokens is the whole prompt; the cached parts are a subset of it.

    Adding the columns as they stand triples every cached prompt — the fault
    this reader exists to avoid.
    """
    path = seed(
        database(tmp_path),
        [row(1, input=43_792, output=443, cache_read=42_698, cache_write=904, reasoning=59)],
    )
    entries = copilot.parse_database(path)
    assert len(entries) == 1
    e = entries[0]
    assert e.input == 190, "uncached prompt = input_tokens - cache_read - cache_write"
    assert e.cache_read == 42_698
    assert e.cache_write == 904
    assert e.output == 443, "reasoning_tokens is a breakdown of output, not an extra charge"
    assert e.total == 44_235, "the prompt plus the completion, counted once"
    assert e.model == "claude-opus-5"


def test_fully_cached_prompt_keeps_zero_uncached_input(tmp_path):
    path = seed(
        database(tmp_path),
        [row(1, model="gpt-5.4-mini", input=57_375, output=35, cache_read=57_375)],
    )
    e = copilot.parse_database(path)[0]
    assert e.input == 0
    assert e.total == 57_410


def test_rows_without_tokens_are_skipped(tmp_path):
    path = seed(database(tmp_path), [row(1), row(2, input=5, output=1)])
    entries = copilot.parse_database(path)
    assert [e.id.split("|")[-1] for e in entries] == ["2"]


# MARK: timestamps


def test_reads_both_stored_timestamp_shapes(tmp_path):
    """The CLI writes ISO with a Z; the column default writes a space-separated
    UTC stamp. Both must land on the same instant scale."""
    path = seed(
        database(tmp_path),
        [
            row(1, input=100, output=10, created_at="2026-01-04T10:00:00.000Z"),
            row(2, input=200, output=20, created_at="2026-01-04 11:00:00"),
        ],
    )
    entries = sorted(copilot.parse_database(path), key=lambda e: e.date)
    assert len(entries) == 2
    assert entries[0].date.timestamp() == 1767520800.0  # 2026-01-04T10:00:00Z
    assert entries[1].date.timestamp() == 1767524400.0  # 2026-01-04T11:00:00Z


def test_negative_utc_offset_is_applied_not_ignored(tmp_path):
    """Its text sorts on 2026-01-03 but the instant is 2026-01-04T01:00:00Z."""
    path = seed(
        database(tmp_path),
        [row(1, input=100, output=10, created_at="2026-01-03T20:00:00-05:00")],
    )
    e = copilot.parse_database(path)[0]
    assert e.date.timestamp() == 1767488400.0  # 2026-01-04T01:00:00Z


def test_unparseable_timestamps_drop_only_their_own_row(tmp_path):
    path = seed(
        database(tmp_path),
        [row(1, input=10, output=1, created_at="not a date"), row(2, input=5, output=1)],
    )
    assert [e.id.split("|")[-1] for e in copilot.parse_database(path)] == ["2"]


# MARK: identity and shape


def test_entry_ids_include_the_database_path(tmp_path):
    """Row ids are unique only within one store, and COPILOT_HOME may name several.

    Without the database in the key, id 1 of each store would collapse during
    dedup and that usage would silently go missing.
    """
    first = seed(tmp_path / "a.db", [row(1, input=10, output=1)])
    second = seed(tmp_path / "b.db", [row(1, input=20, output=2)])
    entries = copilot.parse_database(first) + copilot.parse_database(second)
    assert len({e.id for e in entries}) == 2


def test_provider_reads_the_store_under_home(tmp_path):
    root = tmp_path / ".copilot"
    root.mkdir()
    seed(root / "session-store.db", [row(1, input=10, output=1)])
    provider = copilot.CopilotProvider(home=tmp_path)
    assert len(provider.scan_entries()) == 1


def test_copilot_reports_api_equivalent_estimate(tmp_path):
    """Recovered request buckets estimate usage separately from subscriptions."""
    root = tmp_path / ".copilot"
    root.mkdir()
    seed(root / "session-store.db", [row(1, model="claude-opus-5", input=1_000_000, output=1_000_000)])
    provider = copilot.CopilotProvider(home=tmp_path)
    entries = provider.scan_entries()
    daily = provider.aggregate_daily(entries[0].local_day, entries)
    assert daily.cost_coverage.estimated
    assert daily.total_cost == 30
    assert daily.total_tokens > 0


def test_roots_default_and_override(tmp_path):
    assert copilot.roots(home=tmp_path, env={}) == [tmp_path / ".copilot"]
    custom = tmp_path / "elsewhere"
    assert copilot.roots(home=tmp_path, env={"COPILOT_HOME": str(custom)}) == [custom]


def test_provider_identity():
    provider = copilot.CopilotProvider()
    assert provider.id == "copilot"
    assert provider.display_name == "Copilot CLI"
