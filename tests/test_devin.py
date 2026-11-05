"""Devin CLI parsing — ports DevinUsageTests.swift (upstream 2f4e03d).

Synthetic databases: nothing here reads an installed session store.
"""

import json
import sqlite3

from poketokenbar.providers import devin


def make_db(path, rows, sessions=(("s1", "devin-1"),)):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, model TEXT)")
    db.execute("CREATE TABLE message_nodes (row_id INTEGER PRIMARY KEY, "
               "chat_message TEXT, session_id TEXT, created_at REAL)")
    db.executemany("INSERT INTO sessions VALUES (?,?)", sessions)
    db.executemany("INSERT INTO message_nodes VALUES (?,?,?,?)", rows)
    db.commit()
    db.close()
    return path


def message(message_id="m1", **metrics):
    base = {"input_tokens": 3, "output_tokens": 5,
            "cache_creation_tokens": 7, "cache_read_tokens": 11}
    base.update(metrics)
    return json.dumps({"message_id": message_id, "metadata": {"metrics": base}})


def test_a_turn_with_metrics_is_one_entry(tmp_path):
    db = make_db(tmp_path / "cli" / "sessions.db",
                 [(1, message(), "s1", 1_760_000_000.0)])
    entries = devin.parse_database(db)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.model == "devin-1"
    # Devin's input already excludes both cache buckets.
    assert (entry.input, entry.output) == (3, 5)
    assert (entry.cache_write, entry.cache_read) == (7, 11)
    assert entry.cost_unavailable is True
    assert entry.id.endswith("|s1|m1")


def test_a_row_without_metrics_is_not_a_charge(tmp_path):
    db = make_db(tmp_path / "cli" / "sessions.db", [
        (1, json.dumps({"message_id": "m1"}), "s1", 1_760_000_000.0),
        (2, json.dumps({"message_id": "m2", "metadata": {}}), "s1", 1_760_000_000.0),
        (3, "not json at all", "s1", 1_760_000_000.0),
    ])
    assert devin.parse_database(db) == []


def test_a_branch_copy_keeps_the_message_s_own_identity(tmp_path):
    """New row ids, same logical message: counting both would double it."""
    db = make_db(tmp_path / "cli" / "sessions.db", [
        (1, message("m1"), "s1", 1_760_000_000.0),
        (2, message("m1"), "s1", 1_760_000_000.0),
        (3, message("m2"), "s1", 1_760_000_100.0),
    ])
    assert len(devin.parse_database(db)) == 2


def test_a_row_with_no_message_id_falls_back_to_its_row(tmp_path):
    db = make_db(tmp_path / "cli" / "sessions.db", [
        (7, json.dumps({"metadata": {"metrics": {"input_tokens": 1}}}), "s1", 1_760_000_000.0),
    ])
    assert devin.parse_database(db)[0].id.endswith("|s1|row7")


def test_a_message_without_a_session_still_counts(tmp_path):
    db = make_db(tmp_path / "cli" / "sessions.db",
                 [(1, message(), None, 1_760_000_000.0)])
    entry = devin.parse_database(db)[0]
    assert entry.model == "unknown" and "|nosession|" in entry.id


def test_the_store_is_found_under_the_data_directory(tmp_path):
    provider = devin.DevinProvider(home=tmp_path)
    root = devin.roots(home=tmp_path)[0]
    assert root.name == "devin"
    assert provider.databases(root) == [root / "cli" / "sessions.db"]
    # A root that already points at the cli folder, or at the store itself.
    assert provider.databases(root / "cli") == [root / "cli" / "sessions.db"]
    db = make_db(tmp_path / "direct.db", [(1, message(), "s1", 1_760_000_000.0)])
    assert provider.databases(db) == [db]


def test_the_provider_reads_its_store(tmp_path):
    make_db(tmp_path / ".local" / "share" / "devin" / "cli" / "sessions.db",
            [(1, message(), "s1", 1_760_000_000.0)])
    provider = devin.DevinProvider(home=tmp_path)
    assert sum(e.total for e in provider.scan_entries()) == 3 + 5 + 7 + 11
    assert provider.reports_cost is False
