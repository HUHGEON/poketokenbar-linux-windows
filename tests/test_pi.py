"""Pi Agent parsing — ports PiUsageTests.swift.

The Swift suite is the specification here: it pins the reasoning-is-a-subset
rule, the aborted/errored skip, the total-only fallback, the clamp, and the
global envelope-id dedup, none of which need a Pi install to verify.
"""

import json
from datetime import datetime, timezone

from poketokenbar.providers import pi
from poketokenbar.providers.base import MAX_PARSED_TOKEN_VALUE


def usage(input=0, output=0, reasoning=None, cache_write=0, cache_read=0, total_tokens=None):
    value = {
        "input": input,
        "output": output,
        "cacheWrite": cache_write,
        "cacheRead": cache_read,
    }
    if reasoning is not None:
        value["reasoning"] = reasoning
    if total_tokens is not None:
        value["totalTokens"] = total_tokens
    return value


def message(
    id,
    role="assistant",
    envelope_timestamp="2026-08-17T10:00:00.000Z",
    message_timestamp=None,
    stop_reason=None,
    usage=None,
):
    nested = {
        "role": role,
        "provider": "example",
        "model": "model-name",
        "content": [],
        "usage": usage if usage is not None else {},
    }
    if message_timestamp is not None:
        nested["timestamp"] = message_timestamp
    if stop_reason is not None:
        nested["stopReason"] = stop_reason
    return {
        "type": "message",
        "id": id,
        "parentId": None,
        "timestamp": envelope_timestamp,
        "message": nested,
    }


def write(tmp_path, objects, name="session.jsonl", sub="a", trailing=()):
    root = tmp_path / sub
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    lines = [json.dumps(o) for o in objects] + list(trailing)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def parsed(path):
    provider = pi.PiProvider()
    return provider.parse_file(path)


def by_id(entries):
    return {e.id: e for e in entries}


def test_output_already_includes_reasoning_and_message_timestamp_wins(tmp_path):
    actual = datetime(2026, 8, 16, 23, 59, 59, tzinfo=timezone.utc)
    path = write(
        tmp_path,
        [
            message(
                "turn-1",
                envelope_timestamp="2026-08-17T10:00:00.000Z",
                message_timestamp=actual.timestamp() * 1000,
                usage=usage(
                    input=10, output=20, reasoning=5, cache_write=4, cache_read=30,
                    total_tokens=64,
                ),
            )
        ],
    )
    entry = parsed(path)[0]
    assert entry.id == "turn-1"
    # The real model id, not "pi" — pricing and the per-model breakdown need it.
    assert entry.model == "model-name"
    assert entry.input == 10
    assert entry.output == 20, "Pi reasoning is a subset of output"
    assert entry.cache_write == 4
    assert entry.cache_read == 30
    assert entry.total == 64, "totalTokens already includes reasoning through output"
    assert abs(entry.date.timestamp() - actual.timestamp()) < 0.001


def test_message_compaction_and_branch_summary_all_count(tmp_path):
    """Pi counts every usage-bearing line, tool results included.

    `retainedTail` inside a compaction is copied context, not new usage.
    """
    retained = message("copied", usage=usage(input=1000))["message"]
    compaction = {
        "type": "compaction",
        "id": "compact",
        "parentId": "assistant",
        "timestamp": "2026-08-17T10:00:02.000Z",
        "usage": usage(input=3),
        "retainedTail": [retained],
    }
    branch_summary = {
        "type": "branch_summary",
        "id": "summary",
        "parentId": "compact",
        "timestamp": "2026-08-17T10:00:03.000Z",
        "usage": usage(output=4),
    }
    path = write(
        tmp_path,
        [
            message("assistant", usage=usage(input=1)),
            message("tool-result", role="toolResult", usage=usage(output=2)),
            compaction,
            branch_summary,
        ],
    )
    entries = parsed(path)
    assert {e.id for e in entries} == {"assistant", "tool-result", "compact", "summary"}
    assert sum(e.total for e in entries) == 10
    assert "copied" not in {e.id for e in entries}


def test_aborted_and_errored_messages_are_skipped(tmp_path):
    """Neither was billed, so neither may raise a Pokemon."""
    path = write(
        tmp_path,
        [
            message("aborted", stop_reason="aborted", usage=usage(input=10)),
            message("errored", stop_reason="error", usage=usage(input=20)),
            message("complete", stop_reason="stop", usage=usage(input=30)),
        ],
    )
    assert [e.id for e in parsed(path)] == ["complete"]


def test_malformed_and_partial_records_stay_safe(tmp_path):
    total_only = {
        "type": "message",
        "id": "total-only",
        "parentId": None,
        "timestamp": "2026-08-17T10:00:00.000Z",
        "message": {"role": "assistant", "usage": {"totalTokens": 77}},
    }
    null_granular = {
        "type": "message",
        "id": "null-fields",
        "parentId": None,
        "timestamp": "2026-08-17T10:00:00.000Z",
        "message": {
            "role": "assistant",
            "usage": {"input": None, "output": "not-a-number", "totalTokens": 88},
        },
    }
    negative = message("negative", usage=usage(input=-5, total_tokens=99))
    path = write(
        tmp_path,
        [total_only, null_granular, negative, {"type": "message", "id": "no-usage"}],
        trailing=['{"type":"message","id":'],
    )
    found = by_id(parsed(path))
    assert found["total-only"].total == 77
    assert found["null-fields"].total == 88
    # -5 is still a number, so the granular branch is taken and clamps to 0.
    # Falling back to totalTokens here would invent 99 tokens that were not spent.
    assert found["negative"].total == 0
    assert len(found) == 3


def test_oversized_fields_clamp_without_double_counting_reasoning(tmp_path):
    path = write(
        tmp_path,
        [
            message(
                "huge",
                usage=usage(
                    input=1e30, output=1e30, reasoning=1e30,
                    cache_write=1e30, cache_read=1e30,
                ),
            )
        ],
    )
    entry = parsed(path)[0]
    assert entry.input == MAX_PARSED_TOKEN_VALUE
    assert entry.output == MAX_PARSED_TOKEN_VALUE
    assert entry.cache_write == MAX_PARSED_TOKEN_VALUE
    assert entry.cache_read == MAX_PARSED_TOKEN_VALUE
    assert entry.total == MAX_PARSED_TOKEN_VALUE * 4


def test_global_envelope_id_dedup_drops_fork_copies_but_keeps_branches(tmp_path):
    """A fork copies the parent's turns verbatim under the same envelope id."""
    home = tmp_path / "home"
    sessions = home / ".pi" / "agent" / "sessions"
    shared = message("shared", usage=usage(input=10))
    write(sessions, [shared, message("branch-a", usage=usage(input=20))], sub="a")
    write(sessions, [shared, message("branch-b", usage=usage(input=30))], sub="b")

    entries = pi.PiProvider(home=home).scan_entries()
    assert {e.id for e in entries} == {"shared", "branch-a", "branch-b"}
    assert sum(e.total for e in entries) == 60


def test_session_roots_cover_default_and_both_overrides(tmp_path):
    home = tmp_path / "home"
    agent = tmp_path / "custom-agent"
    sessions = tmp_path / "custom-sessions"
    roots = pi.pi_session_roots(
        home=home,
        env={
            "PI_CODING_AGENT_DIR": str(agent),
            "PI_CODING_AGENT_SESSION_DIR": str(sessions),
        },
    )
    assert set(roots) == {
        home / ".pi" / "agent" / "sessions",
        agent / "sessions",
        sessions,
    }


def test_session_roots_without_overrides_are_just_the_default(tmp_path):
    assert pi.pi_session_roots(home=tmp_path, env={}) == [
        tmp_path / ".pi" / "agent" / "sessions"
    ]


def test_blank_override_is_ignored(tmp_path):
    """An exported-but-empty variable must not add the home directory as a root."""
    roots = pi.pi_session_roots(
        home=tmp_path, env={"PI_CODING_AGENT_DIR": "   ", "PI_CODING_AGENT_SESSION_DIR": ""}
    )
    assert roots == [tmp_path / ".pi" / "agent" / "sessions"]


def test_provider_identity():
    provider = pi.PiProvider()
    assert provider.id == "pi"
    assert provider.display_name == "Pi Agent"


# MARK: omo and senpi, which write Pi's format elsewhere (upstream 964269c)


def test_omo_reads_both_documented_defaults(tmp_path):
    from poketokenbar.providers.pi import omo_session_roots

    found = omo_session_roots(home=tmp_path, env={})
    assert found == [tmp_path / ".omo/agent/sessions", tmp_path / ".senpi/agent/sessions"]


def test_omo_honours_either_agent_directory(tmp_path):
    from poketokenbar.providers.pi import omo_session_roots

    found = omo_session_roots(home=tmp_path, env={
        "OMO_CODING_AGENT_DIR": str(tmp_path / "o"),
        "SENPI_CODING_AGENT_DIR": str(tmp_path / "s"),
    })
    assert found[-2:] == [tmp_path / "o" / "sessions", tmp_path / "s" / "sessions"]


def test_omo_never_reads_pi_s_own_directory(tmp_path):
    """The binary falls back to it, and Pi already counts what is there."""
    from poketokenbar.providers.pi import omo_session_roots

    found = omo_session_roots(home=tmp_path, env={"PI_CODING_AGENT_DIR": str(tmp_path / "p")})
    assert all("pi" not in str(root).split("/")[-3:] for root in found), found


def test_omo_reads_a_pi_format_session(tmp_path):
    from poketokenbar.providers.pi import OmoProvider

    root = tmp_path / ".omo" / "agent" / "sessions"
    root.mkdir(parents=True)
    (root / "a.jsonl").write_text(
        json.dumps(message("m1", usage=usage(input=10, output=5))), encoding="utf-8")

    entries = OmoProvider(home=tmp_path).scan_entries()
    assert [e.total for e in entries] == [15]
    # A bridge copy is another source's session converted; Pi's rule holds here.
    bridge = root / "bridge"
    bridge.mkdir()
    (bridge / "b.jsonl").write_text(
        json.dumps(message("m2", usage=usage(input=99))), encoding="utf-8")
    assert [e.total for e in OmoProvider(home=tmp_path).scan_entries()] == [15]
