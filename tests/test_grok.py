"""Grok CLI parsing — ports GrokUsageTests.swift.

The fixtures mirror the real `updates.jsonl` envelope shape, which the Swift
suite derives from the grok-build sources (`extensions/notification.rs`, the
SessionUpdate / PromptUsage serde contract).
"""

import json

from poketokenbar import pricing
from poketokenbar.providers import grok

# A streaming chunk line. Most of a real updates.jsonl looks like this, and its
# `_meta.totalTokens` is the context window size — counting it would inflate
# every total.
CHUNK_LINE = json.dumps(
    {
        "timestamp": 1785000000,
        "method": "_x.ai/session/update",
        "params": {
            "sessionId": "s1",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": "hi"},
            },
            "_meta": {
                "totalTokens": 100,
                "eventId": "e0",
                "agentTimestampMs": 1785000000000,
                "chunkId": 0,
            },
        },
    }
)


def turn_line(
    prompt_id,
    input=41203,
    output=812,
    cached_read=38400,
    total=42015,
    cost_ticks=12_000_000_000,
    cost_is_partial=False,
    usage_is_incomplete=False,
    model="grok-build-1",
    envelope_seconds=1785000010,
    agent_timestamp_ms=1785000010000,
    is_replay=False,
):
    """The durable ACP wire shape: camelCase, inputTokens includes cache reads."""
    usage = {
        "inputTokens": input,
        "outputTokens": output,
        "totalTokens": total,
        "cachedReadTokens": cached_read,
        "reasoningTokens": 260,
        "modelCalls": 3,
        "numTurns": 1,
    }
    if cost_ticks is not None:
        usage["costUsdTicks"] = cost_ticks
    if cost_is_partial:
        usage["costIsPartial"] = True
    if usage_is_incomplete:
        usage["usageIsIncomplete"] = True
    if model:
        usage["modelUsage"] = {
            model: {
                "inputTokens": input,
                "outputTokens": output,
                "totalTokens": total,
                "cachedReadTokens": cached_read,
            }
        }

    meta = {"totalTokens": total, "eventId": f"ev-{prompt_id}", "promptId": prompt_id}
    if agent_timestamp_ms is not None:
        meta["agentTimestampMs"] = agent_timestamp_ms
    if is_replay:
        meta["isReplay"] = True

    envelope = {}
    if envelope_seconds is not None:
        envelope["timestamp"] = envelope_seconds
    envelope["method"] = "_x.ai/session/update"
    envelope["params"] = {
        "sessionId": "s1",
        "update": {
            "sessionUpdate": "turn_completed",
            "prompt_id": prompt_id,
            "stop_reason": "end_turn",
            "usage": usage,
        },
        "_meta": meta,
    }
    return json.dumps(envelope)


def write_session(root, session_id, lines, session_kind=None, summary=True):
    """Real layout is sessions/<encoded-cwd>/<session-id>/, one level deeper —
    written at the same depth so the scan's recursion is exercised too."""
    directory = root / "cwd-group" / session_id
    directory.mkdir(parents=True, exist_ok=True)
    updates = directory / "updates.jsonl"
    updates.write_text("\n".join(lines), encoding="utf-8")
    if summary:
        doc = {"session_summary": "x"}
        if session_kind:
            doc["session_kind"] = session_kind
        (directory / "summary.json").write_text(json.dumps(doc), encoding="utf-8")
    return updates


def sessions_root(tmp_path):
    return tmp_path / ".grok" / "sessions"


# MARK: token mapping


def test_turn_completed_mapping_preserves_total_identity(tmp_path):
    path = write_session(sessions_root(tmp_path), "s1", [CHUNK_LINE, turn_line("p-1")])
    entries = grok.parse_file(path)
    assert len(entries) == 1, "chunk lines carry no usage"
    e = entries[0]
    assert e.input == 2803, "inputTokens(41203) - cachedReadTokens(38400)"
    assert e.cache_read == 38400
    assert e.output == 812, "reasoning is already inside output"
    assert e.cache_write == 0, "Grok folds cache writes into the prompt tokens"
    assert e.total == 42015, "Entry.total == usage.totalTokens"
    assert e.model == "grok-build-1"
    assert abs(e.explicit_cost - 1.2) < 1e-9, "12e9 ticks = $1.2"


def test_headless_snake_case_input_is_not_cache_adjusted_again(tmp_path):
    """`input_tokens` already excludes cache; subtracting again drops 60 to 20."""
    line = json.dumps(
        {
            "timestamp": 1785000020,
            "method": "_x.ai/session/update",
            "params": {
                "sessionId": "s2",
                "update": {
                    "sessionUpdate": "turn_completed",
                    "prompt_id": "p-snake",
                    "stop_reason": "end_turn",
                    "usage": {
                        "input_tokens": 60,
                        "output_tokens": 10,
                        "total_tokens": 110,
                        "cached_read_tokens": 40,
                    },
                },
                "_meta": {"eventId": "ev-snake", "agentTimestampMs": 1785000020000},
            },
        }
    )
    e = grok.parse_file(write_session(sessions_root(tmp_path), "s2", [line]))[0]
    assert e.input == 60
    assert e.cache_read == 40
    assert e.output == 10
    assert e.total == 110


def test_multiple_turns_aggregate(tmp_path):
    path = write_session(
        sessions_root(tmp_path),
        "s3",
        [
            CHUNK_LINE,
            turn_line("p-1"),
            CHUNK_LINE,
            turn_line("p-2", input=100, output=20, cached_read=0, total=120, cost_ticks=None),
        ],
    )
    entries = grok.parse_file(path)
    assert len(entries) == 2
    assert sum(e.total for e in entries) == 42015 + 120


def test_cache_read_is_clamped_to_the_prompt_total(tmp_path):
    """A cache read cannot exceed the prompt it is part of.

    Clamping keeps the identity; folding with max(0, ...) instead let
    input + cache_read run past inputTokens and inflated the total.
    """
    line = turn_line("p-clamp", input=100, cached_read=150, output=10, total=110)
    e = grok.parse_file(write_session(sessions_root(tmp_path), "s-clamp", [line]))[0]
    assert e.input == 0
    assert e.cache_read == 100
    assert e.input + e.cache_read == 100


def test_residual_against_reported_total_goes_to_output(tmp_path):
    line = turn_line("p-res", input=100, cached_read=0, output=10, total=200)
    e = grok.parse_file(write_session(sessions_root(tmp_path), "s-res", [line]))[0]
    assert e.total == 200
    # parts = 100 input + 10 output + 0 cache = 110; the 90 shortfall lands on output.
    assert e.output == 100, "the shortfall is attributed to output"


def test_zero_usage_turn_produces_no_entry(tmp_path):
    """A turn cancelled before any model call is not a record of spend."""
    line = turn_line("p-zero", input=0, output=0, cached_read=0, total=0, cost_ticks=None)
    assert grok.parse_file(write_session(sessions_root(tmp_path), "s-zero", [line])) == []


def test_null_token_fields_do_not_zero_the_turn(tmp_path):
    """A JSON null means 'not reported', not 'zero' — the other spelling wins."""
    line = json.dumps(
        {
            "timestamp": 1785000030,
            "params": {
                "update": {
                    "sessionUpdate": "turn_completed",
                    "prompt_id": "p-null",
                    "usage": {
                        "inputTokens": None,
                        "input_tokens": 60,
                        "outputTokens": None,
                        "output_tokens": 10,
                        "cachedReadTokens": None,
                        "cached_read_tokens": 40,
                    },
                },
                "_meta": {"agentTimestampMs": 1785000030000},
            },
        }
    )
    e = grok.parse_file(write_session(sessions_root(tmp_path), "s-null", [line]))[0]
    assert (e.input, e.output, e.cache_read) == (60, 10, 40)


# MARK: double-count defences


def test_replay_lines_are_not_counted_twice(tmp_path):
    """Two defences overlap, so each is stepped on separately."""
    root = sessions_root(tmp_path)
    deduped = write_session(root, "s4", [turn_line("p-1"), turn_line("p-1", is_replay=True)])
    entries = grok.parse_file(deduped)
    assert len(entries) == 1, "the same turn id counts once"
    assert entries[0].total == 42015

    # isReplay on its own: a different id, so dedup cannot be what saves it.
    replay_only = write_session(
        root, "s4-replay", [turn_line("p-live"), turn_line("p-replayed", is_replay=True)]
    )
    assert [e.id for e in grok.parse_file(replay_only)] == ["grok|p-live"]


def test_forked_session_copy_does_not_double_count(tmp_path):
    """A fork copies the parent's updates; the turn id must not include the file."""
    root = sessions_root(tmp_path)
    write_session(root, "parent", [turn_line("p-1")])
    write_session(root, "child-fork", [turn_line("p-1")], session_kind="fork")

    entries = grok.GrokProvider(home=tmp_path).scan_entries()
    assert len(entries) == 1, "one prompt_id is one turn, in however many files"
    assert entries[0].total == 42015


def test_subagent_sessions_are_skipped_but_user_sessions_kept(tmp_path):
    """Subagent tokens are already folded into the parent turn's usage."""
    root = sessions_root(tmp_path)
    write_session(root, "main", [turn_line("p-main")])
    write_session(root, "sub", [turn_line("p-sub")], session_kind="subagent")
    write_session(root, "sub2", [turn_line("p-sub2")], session_kind="subagent_fork")
    write_session(root, "wt", [turn_line("p-wt")], session_kind="worktree")

    entries = grok.GrokProvider(home=tmp_path).scan_entries()
    assert {e.id for e in entries} == {"grok|p-main", "grok|p-wt"}


def test_session_without_a_summary_is_treated_as_a_user_session(tmp_path):
    """The CLI writes the summary at creation, so absence means 'no turns yet'."""
    root = sessions_root(tmp_path)
    write_session(root, "nosummary", [turn_line("p-x")], summary=False)
    assert len(grok.GrokProvider(home=tmp_path).scan_entries()) == 1


def test_only_the_updates_file_is_read(tmp_path):
    """chat_history has no usage and events records outcomes — reading either
    only fills the cache with empty blobs."""
    root = sessions_root(tmp_path)
    directory = root / "cwd-group" / "s5"
    directory.mkdir(parents=True)
    (directory / "updates.jsonl").write_text(turn_line("p-1"), encoding="utf-8")
    (directory / "chat_history.jsonl").write_text(turn_line("p-other"), encoding="utf-8")
    (directory / "events.jsonl").write_text(turn_line("p-third"), encoding="utf-8")

    provider = grok.GrokProvider(home=tmp_path)
    scanned = [p.name for r in provider.roots() for p in provider.files(r)]
    assert scanned == ["updates.jsonl"]


# MARK: cost trust


def test_untrustworthy_costs_are_dropped(tmp_path):
    """No Grok rate card exists, so a doubtful figure becomes none, not a guess."""
    root = sessions_root(tmp_path)
    partial = write_session(root, "cost-partial", [turn_line("p-partial", cost_is_partial=True)])
    assert grok.parse_file(partial)[0].explicit_cost is None

    incomplete = write_session(
        root, "cost-incomplete", [turn_line("p-incomplete", usage_is_incomplete=True)]
    )
    assert grok.parse_file(incomplete)[0].explicit_cost is None


def test_daily_cost_of_an_untrusted_turn_is_zero(tmp_path):
    root = sessions_root(tmp_path)
    write_session(root, "cost-partial", [turn_line("p-partial", cost_is_partial=True)])
    provider = grok.GrokProvider(home=tmp_path)
    entries = provider.scan_entries()
    daily = provider.aggregate_daily(entries[0].local_day, entries)
    assert daily.total_cost == 0, "an unpriced model shows no amount rather than a wrong one"


def test_grok_names_are_never_priced_from_the_table():
    """There is no Grok rate card, and a name containing "codex" or "4o" is not
    evidence of a GPT price. Only the server's own figure is used."""
    for name in ["grok-build-1", "grok-4-fast", "grok-code-fast-1", "grok-codex-next", "grok-4o-mini"]:
        assert pricing.estimated_cost(name, 1_000_000, 1_000_000, 0, 0) is None, name
        assert pricing.rate(name) == pricing.ZERO, name


# MARK: timestamps


def test_agent_timestamp_wins_over_the_envelope_write_time(tmp_path):
    """A fork re-stamps the envelope; trusting it piles history onto fork day."""
    line = turn_line("p-ts", envelope_seconds=1_800_000_000, agent_timestamp_ms=1785000010000)
    e = grok.parse_file(write_session(sessions_root(tmp_path), "s-ts", [line]))[0]
    assert abs(e.date.timestamp() - 1785000010) < 0.001


def test_envelope_seconds_used_when_agent_timestamp_missing(tmp_path):
    line = turn_line("p-env", envelope_seconds=1785000010, agent_timestamp_ms=None)
    e = grok.parse_file(write_session(sessions_root(tmp_path), "s-env", [line]))[0]
    assert abs(e.date.timestamp() - 1785000010) < 0.001


def test_millisecond_envelope_timestamps_are_absorbed(tmp_path):
    line = turn_line("p-ms", envelope_seconds=1785000010000, agent_timestamp_ms=None)
    e = grok.parse_file(write_session(sessions_root(tmp_path), "s-ms", [line]))[0]
    assert abs(e.date.timestamp() - 1785000010) < 0.001


# MARK: shape and roots


def test_missing_model_usage_falls_back_to_the_generic_name(tmp_path):
    line = turn_line("p-nomodel", model=None)
    e = grok.parse_file(write_session(sessions_root(tmp_path), "s-nomodel", [line]))[0]
    assert e.model == "grok"


def test_busiest_model_labels_the_turn(tmp_path):
    """Only the label comes from the breakdown; the numbers stay with totals."""
    line = json.dumps(
        {
            "timestamp": 1785000010,
            "params": {
                "update": {
                    "sessionUpdate": "turn_completed",
                    "prompt_id": "p-multi",
                    "usage": {
                        "inputTokens": 100,
                        "outputTokens": 10,
                        "totalTokens": 110,
                        "modelUsage": {
                            "small": {"totalTokens": 10},
                            "big": {"totalTokens": 100},
                        },
                    },
                },
                "_meta": {"agentTimestampMs": 1785000010000},
            },
        }
    )
    e = grok.parse_file(write_session(sessions_root(tmp_path), "s-multi", [line]))[0]
    assert e.model == "big"
    assert e.total == 110


def test_file_without_turn_completed_yields_nothing(tmp_path):
    path = write_session(sessions_root(tmp_path), "s6", [CHUNK_LINE, CHUNK_LINE])
    assert grok.parse_file(path) == []


def test_session_roots_default_and_grok_home(tmp_path):
    assert grok.session_roots(home=tmp_path, env={}) == [tmp_path / ".grok" / "sessions"]
    custom = tmp_path / "elsewhere"
    assert grok.session_roots(home=tmp_path, env={"GROK_HOME": str(custom)}) == [
        custom / "sessions"
    ]


def test_provider_identity():
    provider = grok.GrokProvider()
    assert provider.id == "grok"
    assert provider.display_name == "Grok CLI"
