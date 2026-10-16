"""Kimi Code parsing — ports KimiCodeUsageTests.swift (upstream 40b506e).

The record shapes come from the Swift suite, which took them from Kimi's own
`usageAgentModel.ts`: one `usage.record` line per LLM request, written by every
agent in the session.
"""

import json

from poketokenbar.providers import kimi

MILLIS = 1_760_000_000_000  # 2025-10-09T09:33:20Z


def record(**overrides):
    base = {
        "type": "usage.record",
        "time": MILLIS,
        "model": "kimi-k2",
        "usageScope": "turn",
        "usage": {"inputOther": 100, "output": 20,
                  "inputCacheRead": 300, "inputCacheCreation": 40},
    }
    base.update(overrides)
    return base


def wire(tmp_path, *records, agent="main"):
    """One agent's wire log inside a session, under the CLI's own data root."""
    folder = (tmp_path / kimi.CLI_HOME / "sessions" / "work" / "session-1"
              / "agents" / agent)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "wire.jsonl"
    lines = [json.dumps(r) for r in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# MARK: one record


def test_a_usage_record_is_one_request(tmp_path):
    entries = kimi.parse_file(wire(tmp_path, record()))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.model == "kimi-k2"
    assert (entry.input, entry.output) == (100, 20)
    assert (entry.cache_read, entry.cache_write) == (300, 40)
    assert entry.local_day == kimi.local_day(entry.date)


def test_only_usage_records_count(tmp_path):
    path = wire(
        tmp_path,
        {"type": "message", "time": MILLIS, "content": "hello"},
        {"type": "request.trace", "time": MILLIS},
        record(),
    )
    assert len(kimi.parse_file(path)) == 1


def test_both_scopes_are_per_request_deltas_and_both_count(tmp_path):
    """A compaction runs outside a turn and is billed like any other request."""
    path = wire(tmp_path, record(usageScope="turn"),
                record(time=MILLIS + 1000, usageScope="session"))
    assert len(kimi.parse_file(path)) == 2


def test_a_scope_this_parser_does_not_know_is_skipped_not_guessed(tmp_path):
    path = wire(tmp_path, record(usageScope="lifetime"))
    assert kimi.parse_file(path) == []


def test_a_record_with_no_model_is_attributed_to_the_tool(tmp_path):
    entries = kimi.parse_file(wire(tmp_path, record(model="")))
    assert entries[0].model == "kimi-code"


def test_a_record_without_a_time_or_usage_is_not_a_charge(tmp_path):
    path = wire(tmp_path, record(time=0), record(time=None),
                {"type": "usage.record", "time": MILLIS})
    assert kimi.parse_file(path) == []


def test_a_damaged_line_does_not_lose_the_rest_of_the_file(tmp_path):
    path = wire(tmp_path, record())
    path.write_text('{"type": "usage.record", broken\n' + path.read_text(), encoding="utf-8")
    assert len(kimi.parse_file(path)) == 1


# MARK: identity


def test_the_same_record_in_a_forked_session_is_counted_once(tmp_path):
    """`/fork` copies a session wholesale, so an id made from the file's path
    would count the copied history again."""
    first = kimi.parse_file(wire(tmp_path, record()))
    second = kimi.parse_file(wire(tmp_path / "fork", record()))
    assert first[0].id == second[0].id
    assert len(kimi.dedup_keep_max(first + second)) == 1


def test_two_requests_in_the_same_millisecond_are_both_kept(tmp_path):
    path = wire(tmp_path, record(), record(usage={"inputOther": 7, "output": 1,
                                                  "inputCacheRead": 0,
                                                  "inputCacheCreation": 0}))
    entries = kimi.dedup_keep_max(kimi.parse_file(path))
    assert len(entries) == 2


# MARK: which files and roots


def test_usage_is_only_read_from_a_wire_log(tmp_path):
    assert kimi.is_usage_file(tmp_path / "wire.jsonl")
    assert not kimi.is_usage_file(tmp_path / "messages.jsonl")


def test_every_agent_in_a_session_keeps_its_own_log(tmp_path):
    wire(tmp_path, record(), agent="main")
    wire(tmp_path, record(time=MILLIS + 5000), agent="subagent-1")
    provider = kimi.KimiCodeProvider(home=tmp_path)
    found = [path.name for path in provider.files(tmp_path / kimi.CLI_HOME / "sessions")]
    assert found == ["wire.jsonl", "wire.jsonl"]


def test_the_roots_are_the_cli_root_the_desktop_runtime_and_the_override(tmp_path):
    roots = kimi.session_roots(home=tmp_path, env={})
    assert roots[0] == tmp_path / ".kimi-code" / "sessions"
    assert any("kimi-desktop" in str(root) for root in roots)

    configured = kimi.session_roots(home=tmp_path, env={"KIMI_CODE_HOME": str(tmp_path / "x")})
    assert configured[-1] == tmp_path / "x" / "sessions"
    # An empty value is not a root.
    assert kimi.session_roots(home=tmp_path, env={"KIMI_CODE_HOME": "  "}) == roots


def test_the_provider_reads_a_whole_session_tree(tmp_path):
    wire(tmp_path, record(), agent="main")
    wire(tmp_path, record(time=MILLIS + 1000), agent="sub")
    provider = kimi.KimiCodeProvider(home=tmp_path)
    assert sum(e.total for e in provider.scan_entries()) == 2 * (100 + 20 + 300 + 40)
    assert provider.reports_cost is False
