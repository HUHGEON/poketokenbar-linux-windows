"""omp (oh-my-pi) parsing — ports OmpUsageTests.swift.

omp shares Pi's envelope but differs in three ways the Swift suite pins: only
assistant messages count, ids are scoped by file because omp's are 8 hex chars
unique only within a session, and `bridge/` copies must not be counted twice.
"""

from poketokenbar.providers import pi

SESSION_JSONL = "\n".join(
    [
        '{"type":"session","version":3,"id":"019f9552","timestamp":"2026-07-03T01:00:00.000Z","cwd":"/Users/x/Proj"}',
        '{"type":"model_change","id":"aa01","parentId":null,"timestamp":"2026-07-03T01:00:01.000Z","model":"modal-k3/moonshotai/Kimi-K3"}',
        '{"type":"message","id":"bb01","parentId":"aa01","timestamp":"2026-07-03T01:00:05.000Z","message":{"role":"user","content":[{"type":"text","text":"hi"}]}}',
        '{"type":"message","id":"cc01","parentId":"bb01","timestamp":"2026-07-03T01:00:10.000Z","message":{"role":"assistant","content":[{"type":"text","text":"hello"}],"model":"moonshotai/Kimi-K3","usage":{"input":100,"output":10,"cacheRead":600,"cacheWrite":40,"totalTokens":750,"cost":{"input":0.001,"output":0.002,"cacheRead":0.002,"cacheWrite":0.0,"total":0.005}}}}',
        '{"type":"message","id":"dd01","parentId":"cc01","timestamp":"2026-07-03T01:00:12.000Z","message":{"role":"toolResult","toolCallId":"t1","content":[{"type":"text","text":"ok"}]}}',
        '{"type":"message","id":"ee01","parentId":"dd01","timestamp":"2026-07-03T01:01:00.000Z","message":{"role":"assistant","content":[],"model":"modal/nvidia/GLM-5.2","usage":{"input":5,"output":7,"cacheRead":0,"cacheWrite":3,"totalTokens":15,"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"total":0}}}}',
        '{"type":"custom","customType":"tool_execution_start","timestamp":"2026-07-03T01:01:05.000Z"}',
    ]
)


def write(tmp_path, text, name="session.jsonl", sub="sessions/-Users-x-Proj"):
    directory = tmp_path / sub
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def parsed(path):
    return pi.OmpProvider().parse_file(path)


def by_message_id(entries):
    return {e.id.split("|")[-1]: e for e in entries}


def test_only_assistant_usage_lines_are_collected(tmp_path):
    entries = parsed(write(tmp_path, SESSION_JSONL))
    assert len(entries) == 2, "user / toolResult / custom lines carry no charge"

    found = by_message_id(entries)
    cc = found["cc01"]
    assert cc.model == "moonshotai/Kimi-K3"
    assert (cc.input, cc.output, cc.cache_write, cc.cache_read) == (100, 10, 40, 600)
    assert cc.total == 750, "Entry.total preserves usage.totalTokens"
    assert cc.explicit_cost == 0.005, "the source-persisted charge wins over the table"

    ee = found["ee01"]
    assert ee.model == "modal/nvidia/GLM-5.2"
    assert ee.total == 15
    # A recorded 0 is a free turn, not a missing figure (upstream 69ff39b).
    assert ee.explicit_cost == 0.0
    assert ee.cost_is_estimate and cc.cost_is_estimate, "omp's cost is its own estimate"


def test_non_assistant_and_malformed_lines_yield_nothing(tmp_path):
    tricky = "\n".join(
        [
            # mentions usage in prose, is a user turn
            '{"type":"message","id":"u1","timestamp":"2026-07-03T01:00:05.000Z","message":{"role":"user","content":[{"type":"text","text":"what is my usage?"}]}}',
            # assistant with no usage object
            '{"type":"message","id":"a1","timestamp":"2026-07-03T01:00:10.000Z","message":{"role":"assistant","content":[],"model":"m"}}',
            # usage but no timestamp anywhere
            '{"type":"message","id":"a2","message":{"role":"assistant","usage":{"input":1,"output":1,"cacheRead":0,"cacheWrite":0}}}',
            # aborted turn was never billed
            '{"type":"message","id":"a3","timestamp":"2026-07-03T01:00:20.000Z","message":{"role":"assistant","stopReason":"aborted","usage":{"input":9,"output":1,"cacheRead":0,"cacheWrite":0}}}',
            # compaction whose usage is null
            '{"type":"compaction","id":"cp1","timestamp":"2026-07-03T01:00:30.000Z","usage":null}',
            # truncated final line
            '{"type":"message","id":"a4","timestamp":"2026-07-03T01:00:40.000Z","message":{"role":"assistant","usage":{"input":1,',
        ]
    )
    assert parsed(write(tmp_path, tricky, name="broken.jsonl")) == []


def test_assistant_line_without_an_id_still_counts(tmp_path):
    line = '{"type":"message","timestamp":"2026-07-03T01:00:10.000Z","message":{"role":"assistant","usage":{"input":10,"output":5,"cacheRead":0,"cacheWrite":0}}}'
    entries = parsed(write(tmp_path, line, name="noid.jsonl"))
    assert len(entries) == 1
    assert entries[0].total == 15
    assert entries[0].id.startswith("omp|noid.jsonl|")


def test_duplicate_lines_within_one_file_count_once(tmp_path):
    line = '{"type":"message","id":"cc01","timestamp":"2026-07-03T01:00:10.000Z","message":{"role":"assistant","usage":{"input":10,"output":5,"cacheRead":0,"cacheWrite":0}}}'
    entries = parsed(write(tmp_path, "\n".join([line, line]), name="dup.jsonl"))
    assert len(entries) == 1
    assert entries[0].total == 15


def test_branch_summary_envelope_usage_counts(tmp_path):
    line = '{"type":"branch_summary","id":"bs01","timestamp":"2026-07-03T01:04:00.000Z","usage":{"input":40,"output":6,"cacheRead":0,"cacheWrite":0,"totalTokens":46,"cost":{"input":0,"output":0,"cacheRead":0,"cacheWrite":0,"total":0}}}'
    entries = parsed(write(tmp_path, line, name="branch.jsonl"))
    assert len(entries) == 1
    assert entries[0].total == 46
    assert entries[0].model == "omp", "envelope usage carries no model"


def test_partial_granular_usage_defaults_the_missing_buckets(tmp_path):
    """Granular wins as soon as any one bucket key is present."""
    line = '{"type":"message","id":"pg01","timestamp":"2026-07-03T01:05:00.000Z","message":{"role":"assistant","usage":{"input":7}}}'
    entry = parsed(write(tmp_path, line, name="partial.jsonl"))[0]
    assert entry.input == 7
    assert entry.output + entry.cache_write + entry.cache_read == 0


def test_total_token_only_usage_is_preserved_as_input(tmp_path):
    line = '{"type":"message","id":"tt01","timestamp":"2026-07-03T01:06:00.000Z","message":{"role":"assistant","usage":{"totalTokens":42}}}'
    entry = parsed(write(tmp_path, line, name="totalonly.jsonl"))[0]
    assert [entry.input, entry.output, entry.cache_write, entry.cache_read] == [42, 0, 0, 0]


def test_unreadable_file_inside_a_scanned_root_is_skipped(tmp_path):
    """One damaged file must not poison the rest of the scan."""
    home = tmp_path
    sessions = home / ".omp" / "agent" / "sessions" / "-Users-x-Proj"
    sessions.mkdir(parents=True)
    (sessions / "ok.jsonl").write_text(SESSION_JSONL, encoding="utf-8")
    (sessions / "garbage.jsonl").write_bytes(bytes([0xFF, 0xFE, 0x41, 0x42]))

    entries = pi.OmpProvider(home=home).scan_entries()
    assert len(entries) == 2


def test_bridge_copies_are_not_counted_twice(tmp_path):
    """pi-session-manager mirrors other tools' sessions into `bridge/`.

    Those tokens are already billed under whichever provider owns the original,
    so counting the copy doubles them.
    """
    home = tmp_path
    root = home / ".omp" / "agent" / "sessions"
    (root / "-Projects").mkdir(parents=True)
    (root / "bridge").mkdir(parents=True)
    (root / "-Projects" / "s.jsonl").write_text(SESSION_JSONL, encoding="utf-8")
    (root / "bridge" / "s.jsonl").write_text(SESSION_JSONL, encoding="utf-8")

    provider = pi.OmpProvider(home=home)
    scanned = [p.name for r in provider.roots() for p in provider.files(r)]
    assert scanned == ["s.jsonl"], "the bridge copy must never be opened"
    assert len(provider.scan_entries()) == 2


def test_ids_are_scoped_by_file(tmp_path):
    """omp ids repeat across sessions; without the file they would collapse."""
    home = tmp_path
    root = home / ".omp" / "agent" / "sessions" / "-Proj"
    root.mkdir(parents=True)
    line = '{"type":"message","id":"cc01","timestamp":"2026-07-03T01:00:10.000Z","message":{"role":"assistant","usage":{"input":10,"output":5,"cacheRead":0,"cacheWrite":0}}}'
    (root / "one.jsonl").write_text(line, encoding="utf-8")
    (root / "two.jsonl").write_text(line, encoding="utf-8")

    entries = pi.OmpProvider(home=home).scan_entries()
    assert len(entries) == 2, "same id in two sessions is two separate charges"
    assert sum(e.total for e in entries) == 30


def test_session_roots_default_and_override(tmp_path):
    assert pi.omp_session_roots(home=tmp_path, env={}) == [
        tmp_path / ".omp" / "agent" / "sessions"
    ]
    agent = tmp_path / "custom"
    roots = pi.omp_session_roots(home=tmp_path, env={"OMP_CODING_AGENT_DIR": str(agent)})
    assert roots == [tmp_path / ".omp" / "agent" / "sessions", agent / "sessions"]


def test_provider_identity():
    provider = pi.OmpProvider()
    assert provider.id == "omp"
    assert provider.display_name == "omp"
